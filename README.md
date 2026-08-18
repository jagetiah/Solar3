# ☀️ Solar OS

A Glide-style, Excel-simple **business operating system for solar dealerships** — leads, customers, inventory, payments, installations, service, retail partners and finance in one login-protected app that runs on web and mobile.

Built with **Streamlit + PostgreSQL** (SQLite out of the box for local use).

---

## Quick start (local, 2 minutes)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 — the database seeds itself on first run with all solar modules, demo data, alert rules and demo users:

| Role | Username | Password |
|---|---|---|
| Business Owner | admin | admin123 |
| Super Admin | superadmin | super123 |
| Sales Rep (own leads only) | rep1 | rep123 |
| Inventory Manager | inv1 | inv123 |
| Finance Team | fin1 | fin123 |

**Change these passwords before going live** (Users & Access page).

## Production (Docker + PostgreSQL)

```bash
export POSTGRES_PASSWORD='a-strong-secret'
export OPENAI_API_KEY='sk-...'        # optional, upgrades the copilot
docker compose up -d --build
```

Or point any host at Postgres directly:

```bash
export DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/solaros"
streamlit run app.py
```

### Cloud deployment
- **AWS**: run the container on ECS/Fargate or App Runner; use **RDS PostgreSQL** as `DATABASE_URL`; put an ALB + ACM certificate in front for HTTPS. Enable RDS automated backups (daily snapshots + point-in-time recovery = your disaster recovery).
- **Azure**: Azure Container Apps + Azure Database for PostgreSQL Flexible Server.
- **GCP**: Cloud Run + Cloud SQL (PostgreSQL), connect via the Cloud SQL connector.
- **Simplest**: a single VM (EC2/Droplet) with `docker compose up -d` behind Caddy/Nginx for HTTPS.

### Mobile
Streamlit is responsive; users open the same URL on any phone and can "Add to Home Screen" (Android Chrome / iOS Safari) to get an app-like icon and full-screen experience. Every screen in Solar OS is usable on a phone.

---

## What's inside

### Modules (seeded, all editable/extensible)
- **Inventory** — Inventory Master (with reorder levels & margin formula), Purchase Orders, Inventory Movement (inward/outward/damage/return), Solar Kit Mapping (which serial numbers went to which customer), Damage Claims.
- **Sales & CRM** — Leads (source, stage, assigned rep, lead-age formula, lost reasons), Site Visits (roof, bill, GPS), Quotations (versions, discounts), Incentives (auto-calculated %).
- **Customer Journey** — Customers (KYC, loan, journey stage), Invoices (GST formula), Payments (30% advance / supply / final milestones, balance formula, overdue status), Installations, Metering & DISCOM, Subsidy Tracking, Service & Warranty (open-days formula), Referrals & Feedback.
- **Retail Partners** — partner CRM (prospect → active, training, driving rep), Retail Orders (order value & outstanding formulas).

### The Excel + WhatsApp experience
- Every table is a **spreadsheet-style grid**: click a cell to edit, add rows at the bottom, delete rows, then hit **Save changes**. Dropdowns, checkboxes, currency and dates are proper cell types.
- **Universal filters** on every screen (every dropdown/status/user column + date ranges), per-table search, and a **global search** in the sidebar that scans everything (customer, invoice, SKU, serial number…).
- **Export to Excel** on every table; **bulk upload** from Excel/CSV with a preview before import.

### No-code App Builder (the Glide part)
Admins get a **🧱 App Builder** page:
- **New table** = new tab in the sidebar (e.g. Insurance, HR, Fleet) with columns of type Text, Number, Currency, Date, Dropdown, Checkbox, Email, Phone, Status, User, **Formula**, **Lookup**, Image URL, Long Text.
- **New column** on any existing table — like inserting a column in Excel.
- **Formulas** are Excel-like and validated before saving: `selling_price - cost_price`, `DAYS(TODAY(), lead_date)`, `IF(quantity > 10, price*0.9, price)`. Safe by construction (AST-parsed; no code execution).
- **Relationships** via Lookup columns: point a column at another table's key (e.g. `customer_name`) and the grid shows a dropdown of real customers; a **Related records** panel on the parent table shows all linked invoices, payments, tickets, kits, etc. for a chosen customer.

### No-code Alert Rules
**⚠️ Alert Rules** page: "IF *days since lead_date* > 7 THEN warn Sales Manager", "IF payment status = Overdue THEN alert everyone", "IF stock < 10 THEN alert Inventory Manager", "IF insurance expires in ≤ 10 days…". Alerts appear as banners on everyone's Home page (filtered by role). Four sensible rules ship enabled.

### AI Business Copilot
Ask in plain language: *"Which customers have overdue payments?"*, *"Which rep generated maximum quote value?"*, *"How many leads lost because of price?"*
- **Offline mode** (default): a built-in analyst matches your question to tables, statuses and numeric columns and answers with figures + a table + a chart. No data leaves your server.
- **OpenAI mode** (set `OPENAI_API_KEY`): questions become a single **read-only, validated SELECT** — writes and out-of-permission tables are blocked. The copilot only ever sees tables the logged-in role can see.

### Security & governance
- **Login required**; passwords hashed with **bcrypt**; server-side sessions.
- **RBAC**: 9 roles seeded (Super Admin, Business Owner, Sales Manager, Sales Rep, Inventory Manager, Finance, Installation, Service, Retail Partner). Per-table view/edit toggles editable in the UI, plus **"own rows only"** (a Sales Rep sees only leads assigned to or created by them).
- **Full audit trail**: who changed what, when, old value → new value — for edits, inserts, deletes, imports, logins, permission changes.
- All SQL is parameterized; dynamic table/column names pass a strict identifier whitelist; formulas and copilot SQL are validated before execution.

### Bulk data / backend access
- UI: bulk upload on every table.
- Backend: it's plain PostgreSQL — connect pgAdmin/DBeaver or a script and write to `data_<table>` tables directly for large migrations. Column metadata lives in `sys_columns`, permissions in `sys_permissions`, history in `sys_audit`.

---

## Architecture

```
app.py            UI: login, grids, filters, dashboards, builder, rules, copilot
auth.py           bcrypt auth + RBAC (roles, per-table permissions, own-rows)
database.py       SQLAlchemy engine (SQLite/PostgreSQL), dynamic DDL, audit log
formulas.py       Safe Excel-like formula engine (AST whitelist)
rules_engine.py   No-code IF/THEN alert evaluation
copilot.py        NL Q&A: offline analyst + optional OpenAI text-to-SQL (validated)
seed.py           First-run setup: roles, users, 18 solar tables, rules, demo data
```

Data model: each business table is a real SQL table `data_<name>` with `id`, your columns, and `_created_by/_created_at/_updated_by/_updated_at`. Everything else (tables, columns, formulas, lookups, rules, permissions, audit) is metadata — which is what makes the app configurable without code.

## Going-live checklist
1. Deploy with PostgreSQL (`DATABASE_URL`), HTTPS in front.
2. Log in as `superadmin`, create real users, change/disable demo accounts.
3. Review role permissions per table in **Users & Access** (new tables default to view-for-everyone).
4. Clear demo rows (select-all + delete in each grid, or truncate `data_*` tables) and bulk-upload your real data.
5. Set up your own alert rules and (optionally) `OPENAI_API_KEY`.
6. Turn on database backups (RDS/Cloud SQL automated backups).

## Notes & roadmap ideas
- WhatsApp/SMS/email delivery of alerts: the rules engine already computes matches; wire `rules_engine.evaluate_rules_for_role` to a scheduled job + WhatsApp Business API / MSG91 / Twilio.
- File/photo uploads currently use link columns; swap to S3 pre-signed uploads for native photos.
- Retailer web-scraping prospecting is intentionally left out of the core app (legal/ToS varies); import prospect lists via bulk upload into **Retail Partners** instead.
