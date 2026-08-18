"""Authentication + Role Based Access Control."""
import bcrypt
import pandas as pd
from database import run, fetch_df, now_iso, safe_ident

DEFAULT_ROLES = [
    ("Super Admin", "Full access to everything including the app builder", 1),
    ("Business Owner", "All business data, dashboards and copilot", 1),
    ("Sales Manager", "All sales and lead data", 0),
    ("Sales Rep", "Own leads and customers only", 0),
    ("Inventory Manager", "Inventory, purchase orders and kit mapping", 0),
    ("Finance Team", "Invoices, payments and accounting", 0),
    ("Installation Team", "Installation and commissioning tasks", 0),
    ("Service Team", "Warranty and service requests", 0),
    ("Retail Partner", "Own retail inventory and orders", 0),
]


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_user(username, password, full_name, role, phone="", email=""):
    run("INSERT INTO sys_users (username, password_hash, full_name, role, phone, email, active, created_at) "
        "VALUES (:u,:p,:f,:r,:ph,:e,1,:t)",
        {"u": username.strip().lower(), "p": hash_pw(password), "f": full_name,
         "r": role, "ph": phone, "e": email, "t": now_iso()})


def authenticate(username, password):
    df = fetch_df("SELECT * FROM sys_users WHERE username=:u AND active=1",
                  {"u": username.strip().lower()})
    if df.empty:
        return None
    row = df.iloc[0]
    if check_pw(password, row["password_hash"]):
        return {"username": row["username"], "full_name": row["full_name"],
                "role": row["role"]}
    return None


def is_admin(role: str) -> bool:
    df = fetch_df("SELECT is_admin FROM sys_roles WHERE role=:r", {"r": role})
    return (not df.empty) and bool(df["is_admin"].iloc[0])


def get_permission(role: str, tname: str) -> dict:
    tname = safe_ident(tname)
    if is_admin(role):
        return {"can_view": True, "can_edit": True, "can_add": True,
                "can_delete": True, "own_rows_only": False}
    df = fetch_df("SELECT * FROM sys_permissions WHERE role=:r AND table_name=:t",
                  {"r": role, "t": tname})
    if df.empty:
        return {"can_view": False, "can_edit": False, "can_add": False,
                "can_delete": False, "own_rows_only": False}
    p = df.iloc[0]
    return {"can_view": bool(p["can_view"]), "can_edit": bool(p["can_edit"]),
            "can_add": bool(p["can_add"]), "can_delete": bool(p["can_delete"]),
            "own_rows_only": bool(p["own_rows_only"])}


def visible_tables(role: str) -> pd.DataFrame:
    tables = fetch_df("SELECT * FROM sys_tables ORDER BY module, sort_order, display_name")
    if is_admin(role):
        return tables
    perms = fetch_df("SELECT table_name FROM sys_permissions WHERE role=:r AND can_view=1",
                     {"r": role})
    return tables[tables["name"].isin(perms["table_name"])].reset_index(drop=True)


def init_roles():
    existing = fetch_df("SELECT role FROM sys_roles")["role"].tolist()
    for role, desc, adm in DEFAULT_ROLES:
        if role not in existing:
            run("INSERT INTO sys_roles (role, description, is_admin) VALUES (:r,:d,:a)",
                {"r": role, "d": desc, "a": adm})
