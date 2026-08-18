"""
No-code alert rules ("IF lead age > 7 days THEN alert manager").

Rule types:
  value        — field <op> value                (e.g. stock_quantity < 10)
  days_since   — days since a date field <op> N  (e.g. lead_date older than 7 days)
  days_until   — days until a date field <op> N  (e.g. payment due in <= 3 days / overdue)
  status_is    — field equals a given status
"""
import json
import pandas as pd
from datetime import date
from database import fetch_df, run, get_table_df, get_columns_meta, now_iso, safe_ident
from formulas import apply_formulas, _to_date

OPERATORS = {">": "greater than", ">=": "at least", "<": "less than",
             "<=": "at most", "==": "equal to", "!=": "not equal to"}


def _cmp(a, op, b):
    try:
        if op == ">":  return a > b
        if op == ">=": return a >= b
        if op == "<":  return a < b
        if op == "<=": return a <= b
        if op == "==": return a == b
        if op == "!=": return a != b
    except TypeError:
        return False
    return False


def add_rule(name, table_name, rule_type, field, operator, value, message,
             severity, notify_roles, created_by):
    run("INSERT INTO sys_rules (name, table_name, rule_type, field, operator, value, "
        "message, severity, notify_roles, active, created_by, created_at) "
        "VALUES (:n,:t,:rt,:f,:o,:v,:m,:s,:nr,1,:u,:ts)",
        {"n": name, "t": safe_ident(table_name), "rt": rule_type, "f": field,
         "o": operator, "v": str(value), "m": message, "s": severity,
         "nr": notify_roles, "u": created_by, "ts": now_iso()})


def get_rules(active_only=True) -> pd.DataFrame:
    q = "SELECT * FROM sys_rules"
    if active_only:
        q += " WHERE active=1"
    return fetch_df(q)


def evaluate_rules_for_role(role: str, visible_table_names: list[str]) -> list[dict]:
    """Return alerts: [{rule_name, table, message, severity, count, sample}]"""
    alerts = []
    rules = get_rules()
    today = date.today()
    for _, rule in rules.iterrows():
        notify = str(rule["notify_roles"] or "ALL")
        if notify != "ALL" and role not in [r.strip() for r in notify.split(",")]:
            continue
        if rule["table_name"] not in visible_table_names:
            continue
        try:
            df = get_table_df(rule["table_name"])
            if df.empty:
                continue
            df = apply_formulas(df, get_columns_meta(rule["table_name"]))
            field = rule["field"]
            if field not in df.columns:
                continue
            op = rule["operator"]
            rtype = rule["rule_type"]
            raw_val = rule["value"]

            if rtype == "value":
                try:
                    val = float(raw_val)
                    series = pd.to_numeric(df[field], errors="coerce")
                except (TypeError, ValueError):
                    val = str(raw_val)
                    series = df[field].astype(str)
                mask = series.apply(lambda x: _cmp(x, op, val) if pd.notna(x) else False)
            elif rtype in ("days_since", "days_until"):
                n = float(raw_val)
                def diff(v):
                    d = _to_date(v)
                    if d is None:
                        return None
                    return (today - d).days if rtype == "days_since" else (d - today).days
                series = df[field].apply(diff)
                mask = series.apply(lambda x: _cmp(x, op, n) if x is not None else False)
            elif rtype == "status_is":
                mask = df[field].astype(str).str.strip().str.lower() == str(raw_val).strip().lower()
            else:
                continue

            count = int(mask.sum())
            if count > 0:
                matched = df[mask]
                # pick a friendly identifying column for the sample
                name_cols = [c for c in matched.columns
                             if any(k in c for k in ("name", "customer", "lead", "invoice", "sku", "product"))]
                sample_col = name_cols[0] if name_cols else "id"
                sample = ", ".join(matched[sample_col].astype(str).head(3).tolist())
                alerts.append({
                    "rule_name": rule["name"], "table": rule["table_name"],
                    "message": rule["message"], "severity": rule["severity"],
                    "count": count, "sample": sample,
                })
        except Exception:
            continue
    return alerts
