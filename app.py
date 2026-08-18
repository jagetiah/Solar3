"""
Solar OS — a Glide-style, Excel-simple business operating system for
solar dealerships. Run:  streamlit run app.py
"""
import json
import io
import pandas as pd
import streamlit as st
from datetime import date

import database as db
import auth
import formulas
import rules_engine
import copilot
from seed import run_seed

st.set_page_config(page_title="Solar OS", page_icon="☀️", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# One-time setup
# ---------------------------------------------------------------------------
@st.cache_resource
def _bootstrap():
    run_seed()
    return True

_bootstrap()

st.markdown("""
<style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {background: #f6f8fa; border: 1px solid #e3e8ee;
        border-radius: 10px; padding: 12px 16px;}
    .stButton>button {border-radius: 8px;}
    div[data-testid="stDataFrame"] {border: 1px solid #e3e8ee; border-radius: 8px;}
    @media (max-width: 640px) {
        .block-container {padding-left: 0.6rem; padding-right: 0.6rem;}
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        st.markdown("## ☀️ Solar OS")
        st.caption("Your entire solar business — leads, customers, inventory, "
                   "payments and service — in one simple app.")
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", use_container_width=True, type="primary")
        if ok:
            user = auth.authenticate(u, p)
            if user:
                st.session_state.user = user
                db.log_audit(user["username"], "-", "-", "login")
                st.rerun()
            else:
                st.error("Wrong username or password. Please try again.")
        with st.expander("Demo accounts"):
            st.markdown(
                "| Role | Username | Password |\n|---|---|---|\n"
                "| Business Owner | admin | admin123 |\n"
                "| Super Admin | superadmin | super123 |\n"
                "| Sales Rep | rep1 | rep123 |\n"
                "| Inventory Manager | inv1 | inv123 |\n"
                "| Finance Team | fin1 | fin123 |")
    st.stop()

USER = st.session_state.user
ROLE = USER["role"]
IS_ADMIN = auth.is_admin(ROLE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_options(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def column_config_for(cols_meta: pd.DataFrame, df: pd.DataFrame):
    cfg = {"id": st.column_config.NumberColumn("ID", disabled=True)}
    users_list = db.fetch_df("SELECT username FROM sys_users WHERE active=1")["username"].tolist()
    for _, c in cols_meta.iterrows():
        n, label, t = c["name"], c["label"], c["col_type"]
        if t in ("Number",):
            cfg[n] = st.column_config.NumberColumn(label)
        elif t == "Currency":
            cfg[n] = st.column_config.NumberColumn(label, format="₹ %.0f")
        elif t == "Date":
            cfg[n] = st.column_config.TextColumn(label, help="YYYY-MM-DD")
        elif t in ("Dropdown", "Status"):
            opts = parse_options(c["options"])
            cfg[n] = st.column_config.SelectboxColumn(label, options=opts or None)
        elif t == "Checkbox":
            cfg[n] = st.column_config.CheckboxColumn(label)
        elif t == "User":
            cfg[n] = st.column_config.SelectboxColumn(label, options=users_list)
        elif t == "Lookup":
            opts = []
            if c["lookup_table"] and c["lookup_key"]:
                try:
                    src = db.get_table_df(c["lookup_table"])
                    opts = sorted(src[c["lookup_key"]].dropna().astype(str).unique().tolist())
                except Exception:
                    opts = []
            cfg[n] = st.column_config.SelectboxColumn(f"{label} 🔗", options=opts or None)
        elif t == "Formula":
            cfg[n] = st.column_config.NumberColumn(f"{label} ƒ", disabled=True,
                                                   help=f"Formula: {c['formula']}")
        elif t == "Image URL":
            cfg[n] = st.column_config.LinkColumn(label)
        elif t == "Long Text":
            cfg[n] = st.column_config.TextColumn(label, width="large")
        else:
            cfg[n] = st.column_config.TextColumn(label)
    for hidden in ("_created_by", "_created_at", "_updated_by", "_updated_at"):
        if hidden in df.columns:
            cfg[hidden] = None
    return cfg


def coerce_value(v):
    if isinstance(v, bool):
        return int(v)
    if pd.isna(v) if not isinstance(v, (list, dict)) else False:
        return None
    if isinstance(v, (pd.Timestamp, date)):
        return str(v)[:10]
    return v


def save_grid_changes(tname: str, original: pd.DataFrame, edited: pd.DataFrame,
                      cols_meta: pd.DataFrame, perm: dict):
    """Diff the edited grid against the original and write changes with audit."""
    editable_cols = [c["name"] for _, c in cols_meta.iterrows() if c["col_type"] != "Formula"]
    changes = 0
    orig_by_id = original.set_index("id") if "id" in original.columns else original

    # updates + inserts
    for _, row in edited.iterrows():
        rid = row.get("id")
        if pd.isna(rid):  # new row
            if not perm["can_add"]:
                continue
            payload = {c: coerce_value(row.get(c)) for c in editable_cols if c in row.index}
            payload = {k: v for k, v in payload.items() if v not in (None, "")}
            if not payload:
                continue
            keys = list(payload.keys())
            db.run(f'INSERT INTO "data_{tname}" ({", ".join(chr(34)+k+chr(34) for k in keys)}, '
                   f'_created_by, _created_at) VALUES ({", ".join(":"+k for k in keys)}, :_u, :_t)',
                   {**payload, "_u": USER["username"], "_t": db.now_iso()})
            db.log_audit(USER["username"], tname, "new", "insert", "", "", json.dumps(payload, default=str)[:400])
            changes += 1
        else:
            rid = int(rid)
            if rid not in orig_by_id.index:
                continue
            old_row = orig_by_id.loc[rid]
            for c in editable_cols:
                if c not in row.index:
                    continue
                new_v, old_v = coerce_value(row[c]), coerce_value(old_row.get(c))
                if str(new_v or "") != str(old_v or ""):
                    if not perm["can_edit"]:
                        continue
                    db.run(f'UPDATE "data_{tname}" SET "{db.safe_ident(c)}"=:v, '
                           f'_updated_by=:u, _updated_at=:t WHERE id=:id',
                           {"v": new_v, "u": USER["username"], "t": db.now_iso(), "id": rid})
                    db.log_audit(USER["username"], tname, rid, "update", c, old_v, new_v)
                    changes += 1

    # deletes
    if perm["can_delete"] and "id" in edited.columns:
        deleted_ids = set(orig_by_id.index) - set(edited["id"].dropna().astype(int))
        for rid in deleted_ids:
            db.run(f'DELETE FROM "data_{tname}" WHERE id=:id', {"id": int(rid)})
            db.log_audit(USER["username"], tname, rid, "delete")
            changes += 1
    return changes


def auto_filters(df: pd.DataFrame, cols_meta: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """Universal filters: every Dropdown/Status/User/Lookup column plus date ranges."""
    with st.expander("🔍 Filters", expanded=False):
        filter_cols = cols_meta[cols_meta["col_type"].isin(
            ["Dropdown", "Status", "User", "Lookup"])]
        date_cols = cols_meta[cols_meta["col_type"] == "Date"]
        widgets = st.columns(min(4, max(1, len(filter_cols))) or 1)
        i = 0
        for _, c in filter_cols.iterrows():
            if c["name"] not in df.columns:
                continue
            options = sorted(df[c["name"]].dropna().astype(str).replace("", pd.NA).dropna().unique().tolist())
            if not options:
                continue
            with widgets[i % len(widgets)]:
                sel = st.multiselect(c["label"], options, key=f"{key_prefix}_f_{c['name']}")
            if sel:
                df = df[df[c["name"]].astype(str).isin(sel)]
            i += 1
        for _, c in date_cols.iterrows():
            if c["name"] not in df.columns:
                continue
            c1, c2 = st.columns(2)
            with c1:
                d_from = st.text_input(f"{c['label']} — from (YYYY-MM-DD)", key=f"{key_prefix}_df_{c['name']}")
            with c2:
                d_to = st.text_input(f"{c['label']} — to", key=f"{key_prefix}_dt_{c['name']}")
            if d_from:
                df = df[df[c["name"]].astype(str) >= d_from]
            if d_to:
                df = df[df[c["name"]].astype(str) <= d_to]
    return df


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
tables = auth.visible_tables(ROLE)

with st.sidebar:
    st.markdown(f"### ☀️ Solar OS")
    st.caption(f"👤 {USER['full_name']} · {ROLE}")
    if st.button("Log out", use_container_width=True):
        db.log_audit(USER["username"], "-", "-", "logout")
        st.session_state.user = None
        st.rerun()
    st.divider()

    special_pages = ["🏠 Home", "🤖 Ask Copilot"]
    if IS_ADMIN:
        special_pages += ["🧱 App Builder", "⚠️ Alert Rules", "👥 Users & Access", "📜 Audit Trail"]

    nav_labels, nav_map = list(special_pages), {}
    for mod in tables["module"].unique():
        nav_labels.append(f"— {mod} —")
        for _, t in tables[tables["module"] == mod].iterrows():
            label = f'{t["icon"]} {t["display_name"]}'
            nav_labels.append(label)
            nav_map[label] = t["name"]

    choice = st.radio("Go to", nav_labels, label_visibility="collapsed",
                      format_func=lambda x: x)
    # global search
    st.divider()
    gsearch = st.text_input("🔎 Global search", placeholder="Customer, invoice, SKU…")

# section headers aren't destinations
if choice.startswith("— "):
    choice = "🏠 Home"

# ---------------------------------------------------------------------------
# Global search results
# ---------------------------------------------------------------------------
if gsearch and len(gsearch) >= 2:
    st.subheader(f'Search results for "{gsearch}"')
    hits = 0
    for _, t in tables.iterrows():
        try:
            df = db.get_table_df(t["name"])
        except Exception:
            continue
        if df.empty:
            continue
        mask = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore") \
                 .astype(str).apply(lambda r: r.str.contains(gsearch, case=False, na=False)).any(axis=1)
        found = df[mask]
        if not found.empty:
            hits += len(found)
            st.markdown(f'**{t["icon"]} {t["display_name"]}** — {len(found)} match(es)')
            st.dataframe(found.drop(columns=[c for c in found.columns if c.startswith("_")]),
                         use_container_width=True, hide_index=True)
    if hits == 0:
        st.info("No matches found in your tables.")
    st.stop()

# ---------------------------------------------------------------------------
# HOME — dashboard + alerts
# ---------------------------------------------------------------------------
if choice == "🏠 Home":
    st.title(f"Good day, {USER['full_name'].split(' ')[0]} 👋")

    alerts = rules_engine.evaluate_rules_for_role(ROLE, tables["name"].tolist())
    if alerts:
        st.markdown("#### 🔔 Needs your attention")
        for a in alerts:
            fn = st.error if a["severity"] == "error" else st.warning
            fn(f'**{a["rule_name"]}** — {a["count"]} record(s) in '
               f'*{a["table"].replace("_", " ").title()}*: {a["message"]}  \n'
               f'e.g. {a["sample"]}')
    else:
        st.success("No alerts right now. Everything looks on track. ✅")

    st.markdown("#### 📊 Business snapshot")
    kpis = []
    def _safe(tname):
        try:
            return formulas.apply_formulas(db.get_table_df(tname), db.get_columns_meta(tname))
        except Exception:
            return pd.DataFrame()

    visible = set(tables["name"])
    if "leads" in visible:
        L = _safe("leads")
        if not L.empty:
            open_leads = L[~L["stage"].isin(["Won", "Lost"])]
            won = (L["stage"] == "Won").sum()
            closed = L["stage"].isin(["Won", "Lost"]).sum()
            kpis.append(("Open leads", len(open_leads)))
            kpis.append(("Lead conversion", f"{(won / closed * 100):.0f}%" if closed else "—"))
    if "payments" in visible:
        P = _safe("payments")
        if not P.empty:
            bal = pd.to_numeric(P["balance"], errors="coerce").fillna(0)
            kpis.append(("Outstanding ₹", f"{bal.sum():,.0f}"))
            kpis.append(("Overdue payments", int((P["status"] == "Overdue").sum())))
    if "customers" in visible:
        C = _safe("customers")
        if not C.empty:
            kpis.append(("Customers", len(C)))
            kpis.append(("Order book ₹", f"{pd.to_numeric(C['order_value'], errors='coerce').sum():,.0f}"))
    if "inventory" in visible:
        I = _safe("inventory")
        if not I.empty:
            low = (pd.to_numeric(I["stock_quantity"], errors="coerce")
                   < pd.to_numeric(I["reorder_level"], errors="coerce")).sum()
            kpis.append(("Low-stock items", int(low)))
    if "installations" in visible:
        N = _safe("installations")
        if not N.empty:
            kpis.append(("Pending installs", int((~N["status"].isin(["Commissioned"])).sum())))

    if kpis:
        for row_start in range(0, len(kpis), 4):
            cols = st.columns(4)
            for col, (label, val) in zip(cols, kpis[row_start:row_start + 4]):
                col.metric(label, val)

    # simple charts
    c1, c2 = st.columns(2)
    if "leads" in visible:
        L = _safe("leads")
        if not L.empty:
            with c1:
                st.markdown("**Leads by stage**")
                st.bar_chart(L["stage"].value_counts())
            with c2:
                st.markdown("**Leads by source**")
                st.bar_chart(L["source"].value_counts())
    if "payments" in visible:
        P = _safe("payments")
        if not P.empty:
            st.markdown("**Collections: due vs received by milestone**")
            g = P.groupby("milestone")[["amount_due", "amount_received"]] \
                 .apply(lambda x: x.apply(pd.to_numeric, errors="coerce").sum())
            st.bar_chart(g)

# ---------------------------------------------------------------------------
# COPILOT
# ---------------------------------------------------------------------------
elif choice == "🤖 Ask Copilot":
    st.title("🤖 Business Copilot")
    st.caption("Ask questions in plain language. Answers come only from tables "
               "your role can see."
               + (" (OpenAI mode active)" if copilot.OPENAI_KEY else
                  " Tip: set OPENAI_API_KEY for smarter answers."))
    examples = ["How many pending installations do we have?",
                "Which rep generated maximum quote value?",
                "Which customers have overdue payments?",
                "Total outstanding balance in payments",
                "How many leads lost because of price?"]
    ecols = st.columns(len(examples))
    for i, ex in enumerate(examples):
        if ecols[i].button(ex, key=f"ex{i}", use_container_width=True):
            st.session_state["copilot_q"] = ex
    q = st.text_input("Your question", value=st.session_state.get("copilot_q", ""),
                      placeholder="e.g. Which customers have pending balances?")
    if q:
        text, df, sql = copilot.ask(q, tables["name"].tolist())
        st.markdown(text)
        if sql:
            with st.expander("SQL used"):
                st.code(sql, language="sql")
        if df is not None and not df.empty:
            show = df.drop(columns=[c for c in df.columns if str(c).startswith("_")], errors="ignore")
            st.dataframe(show, use_container_width=True, hide_index=True)
            num = show.select_dtypes("number")
            if len(show) > 1 and not num.empty and len(show) <= 25:
                label_col = next((c for c in show.columns if show[c].dtype == object), None)
                if label_col:
                    st.bar_chart(show.set_index(label_col)[num.columns[0]])

# ---------------------------------------------------------------------------
# APP BUILDER (admin) — Glide-style tables & columns
# ---------------------------------------------------------------------------
elif choice == "🧱 App Builder":
    st.title("🧱 App Builder")
    st.caption("Add new tabs (tables) and columns — just like adding sheets and "
               "columns in Excel. No coding needed.")
    tab1, tab2, tab3 = st.tabs(["➕ New table (tab)", "➕ New column", "ƒ Formula help"])

    with tab1:
        with st.form("new_table"):
            c1, c2 = st.columns(2)
            disp = c1.text_input("Table name*", placeholder="e.g. Fleet Vehicles")
            module = c2.text_input("Module / group*", value="General",
                                   placeholder="e.g. HR, Insurance, Fleet")
            icon = st.selectbox("Icon", ["📋", "🚚", "🧑‍💼", "🛡️", "📦", "💰", "🎯", "🛠️", "🏪", "⚡"])
            st.markdown("**Columns** — add up to 8 now; you can add more later.")
            new_cols = []
            for i in range(8):
                cc1, cc2, cc3 = st.columns([2, 1.4, 2])
                nm = cc1.text_input(f"Column {i+1} name", key=f"nc{i}",
                                    placeholder="e.g. Vehicle Number" if i == 0 else "")
                ty = cc2.selectbox("Type", db.COLUMN_TYPES, key=f"nt{i}")
                extra = cc3.text_input("Options / formula (if needed)", key=f"ne{i}",
                                       placeholder="Dropdown: comma-separated · Formula: a - b")
                if nm.strip():
                    d = {"name": nm, "label": nm.strip(), "col_type": ty}
                    if ty in ("Dropdown", "Status") and extra:
                        d["options"] = [o.strip() for o in extra.split(",") if o.strip()]
                    if ty == "Formula" and extra:
                        d["formula"] = extra.strip()
                    new_cols.append(d)
            submitted = st.form_submit_button("Create table", type="primary")
        if submitted:
            if not disp.strip() or not new_cols:
                st.error("Give the table a name and at least one column.")
            else:
                try:
                    for d in new_cols:
                        if d["col_type"] == "Formula":
                            err = formulas.validate(d.get("formula", ""),
                                                    [db.safe_ident(x["name"]) for x in new_cols])
                            if err:
                                raise ValueError(f'Formula problem in "{d["label"]}": {err}')
                    db.create_data_table(disp, disp.strip(), module.strip() or "General",
                                         icon, new_cols, USER["username"])
                    db.log_audit(USER["username"], disp, "-", "create_table")
                    st.success(f'Table "{disp}" created. It now appears in the sidebar.')
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with tab2:
        all_tables = db.get_tables_meta()
        tsel = st.selectbox("Table", all_tables["display_name"],
                            key="addcol_table")
        trow = all_tables[all_tables["display_name"] == tsel].iloc[0]
        existing = db.get_columns_meta(trow["name"])
        st.caption("Existing columns: " + ", ".join(existing["label"].tolist()))
        with st.form("new_col"):
            c1, c2 = st.columns(2)
            cname = c1.text_input("Column name*", placeholder="e.g. Discount Amount")
            ctype = c2.selectbox("Type", db.COLUMN_TYPES)
            opts = st.text_input("Dropdown/Status options (comma-separated)",
                                 placeholder="e.g. Low, Medium, High")
            formula_txt = st.text_input("Formula (for Formula type)",
                                        placeholder="e.g. quantity * unit_price")
            lc1, lc2 = st.columns(2)
            lk_table = lc1.selectbox("Lookup: pull values from table (for Lookup type)",
                                     ["—"] + all_tables["name"].tolist())
            lk_key = lc2.text_input("Lookup: column to match on",
                                    placeholder="e.g. customer_name")
            addcol = st.form_submit_button("Add column", type="primary")
        if addcol:
            if not cname.strip():
                st.error("Column needs a name.")
            else:
                try:
                    d = {"name": cname, "label": cname.strip(), "col_type": ctype}
                    if ctype in ("Dropdown", "Status") and opts:
                        d["options"] = [o.strip() for o in opts.split(",") if o.strip()]
                    if ctype == "Formula":
                        err = formulas.validate(formula_txt, existing["name"].tolist())
                        if err:
                            raise ValueError(f"Formula problem: {err}")
                        d["formula"] = formula_txt.strip()
                    if ctype == "Lookup" and lk_table != "—":
                        d["lookup_table"], d["lookup_key"] = lk_table, db.safe_ident(lk_key)
                    db.add_column_to_table(trow["name"], d)
                    db.log_audit(USER["username"], trow["name"], "-", "add_column", cname)
                    st.success(f'Column "{cname}" added to {tsel}.')
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with tab3:
        st.markdown("""
Formulas work like Excel — use column names instead of cell references:

| What you want | Formula |
|---|---|
| Profit | `selling_price - cost_price` |
| Pending amount | `amount_due - amount_received` |
| Lead age in days | `DAYS(TODAY(), lead_date)` |
| Total with GST | `amount + amount * gst_pct / 100` |
| Bulk discount | `IF(quantity > 10, price * 0.9, price)` |

Available functions: `TODAY()`, `DAYS(a, b)`, `IF(condition, yes, no)`,
`ROUND(x, digits)`, `MIN`, `MAX`, `ABS`. Column names are lowercase with
underscores (shown in the "New column" tab).
        """)

# ---------------------------------------------------------------------------
# ALERT RULES (admin)
# ---------------------------------------------------------------------------
elif choice == "⚠️ Alert Rules":
    st.title("⚠️ Alert Rules")
    st.caption('No-code automation: "IF lead age > 7 days THEN alert the manager."')
    rules = rules_engine.get_rules(active_only=False)
    if not rules.empty:
        st.dataframe(rules[["name", "table_name", "rule_type", "field", "operator",
                            "value", "severity", "notify_roles", "active"]],
                     use_container_width=True, hide_index=True)
        dis = st.selectbox("Toggle a rule on/off", ["—"] + rules["name"].tolist())
        if dis != "—" and st.button("Toggle"):
            r = rules[rules["name"] == dis].iloc[0]
            db.run("UPDATE sys_rules SET active=:a WHERE id=:i",
                   {"a": 0 if r["active"] else 1, "i": int(r["id"])})
            st.rerun()
    st.markdown("#### ➕ New rule")
    all_tables = db.get_tables_meta()
    tsel = st.selectbox("When looking at table…", all_tables["display_name"])
    trow = all_tables[all_tables["display_name"] == tsel].iloc[0]
    cols = db.get_columns_meta(trow["name"])
    with st.form("new_rule"):
        rname = st.text_input("Rule name*", placeholder="e.g. Stale leads")
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1.4])
        rtype = c1.selectbox("Condition type", [
            ("days_since", "Days since a date is…"),
            ("days_until", "Days until a date is…"),
            ("value", "A number/text value is…"),
            ("status_is", "A status equals…")], format_func=lambda x: x[1])[0]
        field = c2.selectbox("Column", cols["name"].tolist(),
                             format_func=lambda n: cols[cols["name"] == n]["label"].iloc[0])
        op = c3.selectbox("Is", list(rules_engine.OPERATORS.keys()))
        val = c4.text_input("Value*", placeholder="e.g. 7 or Overdue")
        msg = st.text_input("Alert message*", placeholder="Follow up with these leads today.")
        sev = st.selectbox("Severity", ["warning", "error", "info"])
        roles_all = db.fetch_df("SELECT role FROM sys_roles")["role"].tolist()
        notify = st.multiselect("Who should see it (empty = everyone)", roles_all)
        ok = st.form_submit_button("Create rule", type="primary")
    if ok:
        if not (rname and val and msg):
            st.error("Please fill rule name, value and message.")
        else:
            rules_engine.add_rule(rname, trow["name"], rtype, field, op, val, msg,
                                  sev, ", ".join(notify) if notify else "ALL",
                                  USER["username"])
            st.success("Rule created. It will show on the Home page whenever it matches.")
            st.rerun()

# ---------------------------------------------------------------------------
# USERS & ACCESS (admin)
# ---------------------------------------------------------------------------
elif choice == "👥 Users & Access":
    st.title("👥 Users & Access")
    users = db.fetch_df("SELECT id, username, full_name, role, phone, email, active FROM sys_users")
    st.dataframe(users, use_container_width=True, hide_index=True)
    roles_all = db.fetch_df("SELECT role FROM sys_roles")["role"].tolist()

    st.markdown("#### ➕ Add user")
    with st.form("new_user"):
        c1, c2, c3 = st.columns(3)
        nu = c1.text_input("Username*")
        np_ = c2.text_input("Password*", type="password")
        nf = c3.text_input("Full name*")
        c4, c5, c6 = st.columns(3)
        nr = c4.selectbox("Role", roles_all)
        nph = c5.text_input("Phone")
        nem = c6.text_input("Email")
        ok = st.form_submit_button("Create user", type="primary")
    if ok:
        if not (nu and np_ and nf):
            st.error("Username, password and full name are required.")
        elif len(np_) < 6:
            st.error("Password should be at least 6 characters.")
        else:
            try:
                auth.create_user(nu, np_, nf, nr, nph, nem)
                db.log_audit(USER["username"], "sys_users", nu, "create_user")
                st.success(f"User {nu} created.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not create user: {e}")

    st.markdown("#### 🔐 Role permissions per table")
    rsel = st.selectbox("Role", [r for r in roles_all if r not in ("Super Admin", "Business Owner")])
    perms = db.fetch_df("SELECT * FROM sys_permissions WHERE role=:r", {"r": rsel})
    all_tables = db.get_tables_meta()
    rows = []
    for _, t in all_tables.iterrows():
        p = perms[perms["table_name"] == t["name"]]
        rows.append({"table": t["display_name"], "table_name": t["name"],
                     "can_view": bool(p["can_view"].iloc[0]) if not p.empty else False,
                     "can_edit": bool(p["can_edit"].iloc[0]) if not p.empty else False,
                     "own_rows_only": bool(p["own_rows_only"].iloc[0]) if not p.empty else False})
    pdf = pd.DataFrame(rows)
    edited = st.data_editor(pdf, hide_index=True, use_container_width=True,
                            disabled=["table", "table_name"], key="perm_editor")
    if st.button("Save permissions", type="primary"):
        db.run("DELETE FROM sys_permissions WHERE role=:r", {"r": rsel})
        for _, r in edited.iterrows():
            if r["can_view"] or r["can_edit"]:
                db.run("INSERT INTO sys_permissions (role, table_name, can_view, can_edit, "
                       "can_add, can_delete, own_rows_only) VALUES (:r,:t,:v,:e,:e2,0,:o)",
                       {"r": rsel, "t": r["table_name"], "v": int(r["can_view"] or r["can_edit"]),
                        "e": int(r["can_edit"]), "e2": int(r["can_edit"]),
                        "o": int(r["own_rows_only"])})
        db.log_audit(USER["username"], "sys_permissions", rsel, "update_permissions")
        st.success("Permissions saved.")
        st.rerun()

# ---------------------------------------------------------------------------
# AUDIT TRAIL (admin)
# ---------------------------------------------------------------------------
elif choice == "📜 Audit Trail":
    st.title("📜 Audit Trail")
    st.caption("Who changed what, when — old value and new value.")
    audit = db.fetch_df("SELECT ts, username, table_name, record_id, action, field, "
                        "old_value, new_value FROM sys_audit ORDER BY id DESC LIMIT 1000")
    f1, f2 = st.columns(2)
    fu = f1.text_input("Filter by user")
    ft = f2.text_input("Filter by table")
    if fu:
        audit = audit[audit["username"].str.contains(fu, case=False, na=False)]
    if ft:
        audit = audit[audit["table_name"].str.contains(ft, case=False, na=False)]
    st.dataframe(audit, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# DATA TABLES — Excel-like grid
# ---------------------------------------------------------------------------
else:
    tname = nav_map.get(choice)
    if not tname:
        st.stop()
    trow = tables[tables["name"] == tname].iloc[0]
    perm = auth.get_permission(ROLE, tname)
    if not perm["can_view"]:
        st.error("You don't have access to this table.")
        st.stop()

    cols_meta = db.get_columns_meta(tname)
    df = db.get_table_df(tname)

    # own-rows restriction for e.g. Sales Reps
    if perm["own_rows_only"] and not df.empty:
        user_cols = [c["name"] for _, c in cols_meta.iterrows() if c["col_type"] == "User"]
        mask = df["_created_by"] == USER["username"]
        for uc in user_cols:
            mask = mask | (df[uc].astype(str) == USER["username"])
        df = df[mask]

    df = formulas.apply_formulas(df, cols_meta)

    st.title(f'{trow["icon"]} {trow["display_name"]}')
    top1, top2, top3 = st.columns([2, 1, 1])
    with top1:
        st.caption(f'{len(df)} records · Module: {trow["module"]}'
                   + (" · showing only your records" if perm["own_rows_only"] else ""))

    view = auto_filters(df, cols_meta, tname)

    # quick per-table search
    tsearch = st.text_input("Search in this table", key=f"s_{tname}",
                            placeholder="Type to filter rows…")
    if tsearch:
        m = view.astype(str).apply(lambda r: r.str.contains(tsearch, case=False, na=False)).any(axis=1)
        view = view[m]

    editable = perm["can_edit"] or perm["can_add"]
    cfg = column_config_for(cols_meta, view)
    order = ["id"] + cols_meta["name"].tolist()
    order = [c for c in order if c in view.columns]

    if editable:
        edited = st.data_editor(
            view, key=f"grid_{tname}", use_container_width=True, hide_index=True,
            num_rows="dynamic" if perm["can_add"] else "fixed",
            column_config=cfg, column_order=order, height=460)
        csave, cexp, cimp = st.columns([1, 1, 2])
        if csave.button("💾 Save changes", type="primary", key=f"save_{tname}"):
            n = save_grid_changes(tname, view, edited, cols_meta, perm)
            if n:
                st.success(f"Saved {n} change(s). ✅")
                st.rerun()
            else:
                st.info("Nothing to save.")
    else:
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config=cfg, column_order=order, height=460)
        cexp, cimp = st.columns([1, 3])

    # export
    show = view.drop(columns=[c for c in view.columns if c.startswith("_")], errors="ignore")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        show.to_excel(xw, index=False, sheet_name=trow["display_name"][:30])
    cexp.download_button("⬇️ Export Excel", buf.getvalue(),
                         file_name=f"{tname}.xlsx", key=f"exp_{tname}",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # bulk import
    if perm["can_add"]:
        with st.expander("📥 Bulk upload (Excel/CSV)"):
            st.caption("Columns in your file should match the column names shown in the grid. "
                       "Extra columns are ignored; missing ones stay blank.")
            up = st.file_uploader("Choose a file", type=["csv", "xlsx"], key=f"up_{tname}")
            if up is not None:
                try:
                    imp = pd.read_csv(up) if up.name.endswith(".csv") else pd.read_excel(up)
                    imp.columns = [db.safe_ident(c) for c in imp.columns]
                    valid_cols = [c for c in imp.columns
                                  if c in cols_meta[cols_meta["col_type"] != "Formula"]["name"].tolist()]
                    st.dataframe(imp[valid_cols].head(10), use_container_width=True)
                    st.caption(f"{len(imp)} rows · will import columns: {', '.join(valid_cols)}")
                    if st.button("Import now", key=f"impbtn_{tname}", type="primary"):
                        count = 0
                        for _, r in imp.iterrows():
                            payload = {c: coerce_value(r[c]) for c in valid_cols if pd.notna(r[c])}
                            if not payload:
                                continue
                            keys = list(payload.keys())
                            db.run(f'INSERT INTO "data_{tname}" '
                                   f'({", ".join(chr(34)+k+chr(34) for k in keys)}, _created_by, _created_at) '
                                   f'VALUES ({", ".join(":"+k for k in keys)}, :_u, :_t)',
                                   {**payload, "_u": USER["username"], "_t": db.now_iso()})
                            count += 1
                        db.log_audit(USER["username"], tname, "-", "bulk_import", "", "", f"{count} rows")
                        st.success(f"Imported {count} rows. ✅")
                        st.rerun()
                except Exception as e:
                    st.error(f"Could not read that file: {e}")

    # linked records (relationship view via Lookup columns)
    rel_sources = db.fetch_df(
        "SELECT table_name, name, label, lookup_key FROM sys_columns "
        "WHERE lookup_table=:t", {"t": tname})
    if not rel_sources.empty and not view.empty:
        with st.expander("🔗 Related records"):
            key_options = rel_sources["lookup_key"].unique().tolist()
            pick_col = key_options[0]
            if pick_col in view.columns:
                pick = st.selectbox(f"Pick a {pick_col.replace('_',' ')}",
                                    sorted(view[pick_col].dropna().astype(str).unique()),
                                    key=f"rel_{tname}")
                for _, rs in rel_sources.iterrows():
                    try:
                        child = db.get_table_df(rs["table_name"])
                    except Exception:
                        continue
                    if child.empty or rs["name"] not in child.columns:
                        continue
                    matches = child[child[rs["name"]].astype(str) == str(pick)]
                    if not matches.empty:
                        meta = db.get_tables_meta()
                        disp = meta[meta["name"] == rs["table_name"]]["display_name"].iloc[0]
                        st.markdown(f"**{disp}** ({len(matches)})")
                        st.dataframe(matches.drop(columns=[c for c in matches.columns
                                                           if c.startswith("_")]),
                                     use_container_width=True, hide_index=True)
