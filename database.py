"""
Database layer for Solar OS.
Uses SQLite out of the box for local/dev; switches to PostgreSQL in production
by setting the DATABASE_URL environment variable, e.g.:
    export DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/solaros"
All queries are parameterized. Dynamic table/column names are validated
against a strict identifier whitelist before being interpolated.
"""
import os
import re
import json
from datetime import datetime, date
from sqlalchemy import create_engine, text
import pandas as pd

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///solar_os.db")

_engine = None

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def get_engine():
    global _engine
    if _engine is None:
        kwargs = {}
        if DATABASE_URL.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, **kwargs)
    return _engine


def safe_ident(name: str) -> str:
    """Validate a table/column identifier. Raises on anything unsafe."""
    n = str(name).strip().lower().replace(" ", "_")
    n = re.sub(r"[^a-z0-9_]", "", n)
    if not IDENT_RE.match(n):
        raise ValueError(f"Invalid identifier: {name!r}")
    reserved = {"select", "insert", "update", "delete", "drop", "table", "user", "order", "group"}
    if n in reserved:
        n = n + "_col"
    return n


def run(sql: str, params: dict | None = None):
    eng = get_engine()
    with eng.begin() as conn:
        return conn.execute(text(sql), params or {})


def fetch_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def table_exists(name: str) -> bool:
    eng = get_engine()
    if DATABASE_URL.startswith("sqlite"):
        df = fetch_df("SELECT name FROM sqlite_master WHERE type='table' AND name=:n", {"n": name})
    else:
        df = fetch_df(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n", {"n": name})
    return not df.empty


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# System (metadata) schema
# ---------------------------------------------------------------------------

SYSTEM_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS sys_users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        role TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sys_roles (
        id INTEGER PRIMARY KEY,
        role TEXT UNIQUE NOT NULL,
        description TEXT,
        is_admin INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS sys_permissions (
        id INTEGER PRIMARY KEY,
        role TEXT NOT NULL,
        table_name TEXT NOT NULL,
        can_view INTEGER DEFAULT 1,
        can_edit INTEGER DEFAULT 0,
        can_add INTEGER DEFAULT 0,
        can_delete INTEGER DEFAULT 0,
        own_rows_only INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS sys_tables (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        module TEXT DEFAULT 'General',
        icon TEXT DEFAULT '📋',
        description TEXT,
        sort_order INTEGER DEFAULT 100,
        created_by TEXT,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sys_columns (
        id INTEGER PRIMARY KEY,
        table_name TEXT NOT NULL,
        name TEXT NOT NULL,
        label TEXT NOT NULL,
        col_type TEXT NOT NULL,
        options TEXT,
        formula TEXT,
        lookup_table TEXT,
        lookup_key TEXT,
        required INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 100
    )""",
    """CREATE TABLE IF NOT EXISTS sys_audit (
        id INTEGER PRIMARY KEY,
        ts TEXT,
        username TEXT,
        table_name TEXT,
        record_id TEXT,
        action TEXT,
        field TEXT,
        old_value TEXT,
        new_value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sys_rules (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        table_name TEXT NOT NULL,
        rule_type TEXT NOT NULL,
        field TEXT NOT NULL,
        operator TEXT NOT NULL,
        value TEXT,
        message TEXT,
        severity TEXT DEFAULT 'warning',
        notify_roles TEXT DEFAULT 'ALL',
        active INTEGER DEFAULT 1,
        created_by TEXT,
        created_at TEXT
    )""",
]


def init_system_tables():
    for sql in SYSTEM_TABLES_SQL:
        if not DATABASE_URL.startswith("sqlite"):
            sql = sql.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
        run(sql)


# ---------------------------------------------------------------------------
# Dynamic table management (the Glide-like part)
# ---------------------------------------------------------------------------

COLUMN_TYPES = [
    "Text", "Number", "Currency", "Date", "Dropdown", "Checkbox",
    "Email", "Phone", "Status", "User", "Formula", "Lookup", "Image URL", "Long Text",
]

SQL_TYPE = {
    "Text": "TEXT", "Long Text": "TEXT", "Number": "REAL", "Currency": "REAL",
    "Date": "TEXT", "Dropdown": "TEXT", "Checkbox": "INTEGER", "Email": "TEXT",
    "Phone": "TEXT", "Status": "TEXT", "User": "TEXT", "Formula": "REAL",
    "Lookup": "TEXT", "Image URL": "TEXT",
}


def create_data_table(name: str, display_name: str, module: str, icon: str,
                      columns: list[dict], created_by: str):
    """columns: [{name,label,col_type,options?,formula?,lookup_table?,lookup_key?}]"""
    tname = safe_ident(name)
    if table_exists(f"data_{tname}"):
        raise ValueError(f"A table called '{display_name}' already exists.")
    col_defs = []
    for c in columns:
        cn = safe_ident(c["name"])
        col_defs.append(f'"{cn}" {SQL_TYPE.get(c["col_type"], "TEXT")}')
    pk = "INTEGER PRIMARY KEY" if DATABASE_URL.startswith("sqlite") else "SERIAL PRIMARY KEY"
    ddl = (f'CREATE TABLE "data_{tname}" (id {pk}, ' + ", ".join(col_defs) +
           ", _created_by TEXT, _created_at TEXT, _updated_by TEXT, _updated_at TEXT)")
    run(ddl)
    run("INSERT INTO sys_tables (name, display_name, module, icon, created_by, created_at) "
        "VALUES (:n,:d,:m,:i,:u,:t)",
        {"n": tname, "d": display_name, "m": module, "i": icon, "u": created_by, "t": now_iso()})
    for i, c in enumerate(columns):
        add_column_meta(tname, c, i)
    # everyone with a role gets view by default; admin roles get edit
    roles = fetch_df("SELECT role, is_admin FROM sys_roles")
    for _, r in roles.iterrows():
        run("INSERT INTO sys_permissions (role, table_name, can_view, can_edit, can_add, can_delete) "
            "VALUES (:r,:t,:v,:e,:a,:d)",
            {"r": r["role"], "t": tname, "v": 1,
             "e": int(r["is_admin"]), "a": int(r["is_admin"]), "d": int(r["is_admin"])})
    return tname


def add_column_meta(tname: str, c: dict, order: int = 100):
    run("INSERT INTO sys_columns (table_name, name, label, col_type, options, formula, "
        "lookup_table, lookup_key, required, sort_order) "
        "VALUES (:t,:n,:l,:ty,:o,:f,:lt,:lk,:req,:so)",
        {"t": tname, "n": safe_ident(c["name"]), "l": c.get("label", c["name"]),
         "ty": c["col_type"], "o": json.dumps(c.get("options")) if c.get("options") else None,
         "f": c.get("formula"), "lt": c.get("lookup_table"), "lk": c.get("lookup_key"),
         "req": int(c.get("required", 0)), "so": order})


def add_column_to_table(tname: str, c: dict):
    tname = safe_ident(tname)
    cn = safe_ident(c["name"])
    existing = fetch_df("SELECT name FROM sys_columns WHERE table_name=:t", {"t": tname})
    if cn in existing["name"].tolist():
        raise ValueError(f"Column '{c['name']}' already exists.")
    run(f'ALTER TABLE "data_{tname}" ADD COLUMN "{cn}" {SQL_TYPE.get(c["col_type"], "TEXT")}')
    mx = fetch_df("SELECT COALESCE(MAX(sort_order),0) AS m FROM sys_columns WHERE table_name=:t",
                  {"t": tname})["m"].iloc[0]
    add_column_meta(tname, c, int(mx) + 1)


def get_tables_meta() -> pd.DataFrame:
    return fetch_df("SELECT * FROM sys_tables ORDER BY module, sort_order, display_name")


def get_columns_meta(tname: str) -> pd.DataFrame:
    return fetch_df("SELECT * FROM sys_columns WHERE table_name=:t ORDER BY sort_order, id",
                    {"t": safe_ident(tname)})


def get_table_df(tname: str) -> pd.DataFrame:
    return fetch_df(f'SELECT * FROM "data_{safe_ident(tname)}"')


def log_audit(username, table_name, record_id, action, field="", old="", new=""):
    run("INSERT INTO sys_audit (ts, username, table_name, record_id, action, field, old_value, new_value) "
        "VALUES (:ts,:u,:t,:r,:a,:f,:o,:n)",
        {"ts": now_iso(), "u": username, "t": table_name, "r": str(record_id),
         "a": action, "f": str(field), "o": str(old)[:500], "n": str(new)[:500]})
