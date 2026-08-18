"""
AI Business Copilot.

Two modes:
1. Built-in analyst (no API key needed): keyword-matches the question to
   tables/columns and runs pandas aggregations. Honest and offline.
2. OpenAI mode (set OPENAI_API_KEY): sends the schema + question, receives a
   single read-only SQL SELECT which is validated before execution.
"""
import os
import re
import json
import pandas as pd
from database import fetch_df, get_tables_meta, get_columns_meta, get_table_df, safe_ident
from formulas import apply_formulas

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")


def schema_text(table_names: list[str]) -> str:
    lines = []
    tables = get_tables_meta()
    for _, t in tables.iterrows():
        if t["name"] not in table_names:
            continue
        cols = get_columns_meta(t["name"])
        col_desc = ", ".join(f'{c["name"]} ({c["col_type"]})' for _, c in cols.iterrows())
        lines.append(f'Table data_{t["name"]} — "{t["display_name"]}": id, {col_desc}')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode 2: OpenAI text-to-SQL (read-only, validated)
# ---------------------------------------------------------------------------

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma|grant)\b", re.I)


def _validate_sql(sql: str, allowed_tables: list[str]) -> str | None:
    s = sql.strip().rstrip(";")
    if not s.lower().startswith("select"):
        return "Only SELECT queries are allowed."
    if _FORBIDDEN.search(s):
        return "Query contains a forbidden keyword."
    if ";" in s:
        return "Multiple statements are not allowed."
    referenced = set(re.findall(r"\bdata_([a-z0-9_]+)", s, re.I))
    for t in referenced:
        if t not in allowed_tables:
            return f"You don't have access to table {t}."
    return None


def ask_openai(question: str, allowed_tables: list[str]):
    import urllib.request
    schema = schema_text(allowed_tables)
    prompt = (
        "You are a SQL analyst for a solar business. Given this schema:\n"
        f"{schema}\n\n"
        "Write ONE read-only SQLite SELECT query answering the question. "
        "Respond with ONLY the SQL, no markdown, no explanation.\n"
        f"Question: {question}"
    )
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {OPENAI_KEY}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    sql = data["choices"][0]["message"]["content"].strip()
    sql = re.sub(r"^```(sql)?|```$", "", sql, flags=re.M).strip()
    err = _validate_sql(sql, allowed_tables)
    if err:
        return None, err
    try:
        return fetch_df(sql), sql
    except Exception as e:
        return None, f"Query failed: {e}"


# ---------------------------------------------------------------------------
# Mode 1: built-in analyst (offline)
# ---------------------------------------------------------------------------

AGG_WORDS = {
    "how many": "count", "count": "count", "number of": "count",
    "total": "sum", "sum": "sum", "revenue": "sum", "amount": "sum",
    "average": "mean", "avg": "mean",
    "maximum": "max", "max": "max", "highest": "max", "top": "max", "most": "max",
    "minimum": "min", "lowest": "min",
}


def _score_table(q: str, tname: str, display: str, cols: pd.DataFrame) -> int:
    score = 0
    ql = q.lower()
    for word in re.findall(r"[a-z]+", display.lower() + " " + tname):
        if len(word) > 3 and word.rstrip("s") in ql:
            score += 3
    for _, c in cols.iterrows():
        for word in re.findall(r"[a-z]+", str(c["label"]).lower()):
            if len(word) > 3 and word.rstrip("s") in ql:
                score += 1
        # status/dropdown values mentioned in the question ("overdue", "won"…)
        if c["col_type"] in ("Status", "Dropdown") and c.get("options"):
            try:
                for opt in json.loads(c["options"]):
                    if opt and len(str(opt)) > 3 and str(opt).lower() in ql:
                        score += 4
            except Exception:
                pass
    return score


def ask_builtin(question: str, allowed_tables: list[str]):
    """Return (answer_text, dataframe_or_None)."""
    q = question.lower()
    tables = get_tables_meta()
    tables = tables[tables["name"].isin(allowed_tables)]
    best, best_score = None, 0
    for _, t in tables.iterrows():
        cols = get_columns_meta(t["name"])
        s = _score_table(q, t["name"], t["display_name"], cols)
        if s > best_score:
            best, best_score = t, s
    if best is None or best_score == 0:
        return ("I couldn't match that question to your data. Try mentioning a table "
                "name like leads, payments, inventory or customers — or open the "
                "table and use filters.", None)

    tname = best["name"]
    df = apply_formulas(get_table_df(tname), get_columns_meta(tname))
    if df.empty:
        return (f"**{best['display_name']}** has no records yet.", None)

    cols = get_columns_meta(tname)
    # find status-like filters in the question ("pending", "overdue", "won"...)
    status_cols = cols[cols["col_type"].isin(["Status", "Dropdown"])]["name"].tolist()
    filtered = df
    applied = []
    for sc in status_cols:
        values = df[sc].dropna().astype(str).unique()
        for v in values:
            if v.lower() in q and len(v) > 2:
                filtered = filtered[filtered[sc].astype(str).str.lower() == v.lower()]
                applied.append(f"{sc} = {v}")
                break

    # aggregation intent
    agg = None
    for phrase, a in AGG_WORDS.items():
        if phrase in q:
            agg = a
            break

    num_cols = [c["name"] for _, c in cols.iterrows()
                if c["col_type"] in ("Number", "Currency", "Formula")]
    target_num = None
    for nc in num_cols:
        for word in re.findall(r"[a-z]+", nc):
            if len(word) > 3 and word in q:
                target_num = nc
                break
        if target_num:
            break
    if target_num is None and num_cols:
        target_num = num_cols[0]

    # group by intent: "by rep", "per city", "which rep"
    group_col = None
    m = re.search(r"(?:by|per|which|who)\s+([a-z_ ]+)", q)
    if m:
        key = m.group(1).strip().split(" ")[0].rstrip("s")
        for _, c in cols.iterrows():
            if key and key in c["name"]:
                group_col = c["name"]
                break

    fdesc = f" (filtered: {', '.join(applied)})" if applied else ""
    if group_col and target_num and agg in ("sum", "max", "mean"):
        g = (filtered.assign(**{target_num: pd.to_numeric(filtered[target_num], errors="coerce")})
             .groupby(group_col)[target_num].sum().sort_values(ascending=False).reset_index())
        top = g.iloc[0]
        return (f"**{top[group_col]}** leads with **{top[target_num]:,.0f}** "
                f"total {target_num.replace('_',' ')} in {best['display_name']}{fdesc}.", g)
    if agg == "count" or (agg is None and not target_num):
        return (f"**{len(filtered)}** records in {best['display_name']}{fdesc}.",
                filtered.head(50))
    if agg in ("sum", "mean", "max", "min") and target_num:
        series = pd.to_numeric(filtered[target_num], errors="coerce")
        val = getattr(series, agg)()
        label = {"sum": "Total", "mean": "Average", "max": "Highest", "min": "Lowest"}[agg]
        return (f"{label} **{target_num.replace('_',' ')}** in {best['display_name']}{fdesc}: "
                f"**{val:,.2f}** across {len(filtered)} records.", filtered.head(50))
    return (f"Here are the matching records from **{best['display_name']}**{fdesc} "
            f"({len(filtered)} rows).", filtered.head(50))


def ask(question: str, allowed_tables: list[str]):
    """Main entry point. Returns (text, df, sql_or_None)."""
    if OPENAI_KEY:
        result, info = ask_openai(question, allowed_tables)
        if result is not None:
            return ("Here is what I found:", result, info)
        # fall through to builtin on failure
    text, df = ask_builtin(question, allowed_tables)
    return (text, df, None)
