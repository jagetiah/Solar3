"""First-run setup: roles, users, solar business tables, permissions, rules, demo data."""
from database import (init_system_tables, fetch_df, run, create_data_table,
                      table_exists, now_iso, today_iso)
from auth import init_roles, create_user
from rules_engine import add_rule
from datetime import date, timedelta

T = lambda d: (date.today() - timedelta(days=d)).isoformat()
F = lambda d: (date.today() + timedelta(days=d)).isoformat()


def seeded() -> bool:
    if not table_exists("sys_tables"):
        return False
    return not fetch_df("SELECT id FROM sys_tables LIMIT 1").empty


MODULES = {
    # --- INVENTORY -----------------------------------------------------------
    "inventory": dict(
        display="Inventory Master", module="Inventory", icon="📦",
        cols=[
            ("sku", "SKU", "Text"), ("product_name", "Product Name", "Text"),
            ("category", "Category", "Dropdown", ["Panel", "Inverter", "Battery", "Structure", "Cable", "Meter", "Other"]),
            ("brand", "Brand", "Text"), ("model", "Model", "Text"),
            ("warranty_years", "Warranty (Years)", "Number"),
            ("cost_price", "Cost Price", "Currency"),
            ("selling_price", "Selling Price", "Currency"),
            ("stock_quantity", "Stock Qty", "Number"),
            ("reorder_level", "Reorder Level", "Number"),
            ("warehouse", "Warehouse", "Dropdown", ["Main", "North", "South"]),
            ("status", "Status", "Status", ["Active", "Discontinued"]),
            ("margin", "Margin/Unit", "Formula", None, "selling_price - cost_price"),
        ],
        rows=[
            dict(sku="PNL-540", product_name="540W Mono Panel", category="Panel", brand="Adani", model="AS-540", warranty_years=25, cost_price=9500, selling_price=11500, stock_quantity=120, reorder_level=50, warehouse="Main", status="Active"),
            dict(sku="INV-5K", product_name="5kW String Inverter", category="Inverter", brand="Growatt", model="MIN-5000", warranty_years=7, cost_price=32000, selling_price=39000, stock_quantity=8, reorder_level=10, warehouse="Main", status="Active"),
            dict(sku="BAT-150", product_name="150Ah Solar Battery", category="Battery", brand="Luminous", model="LPT-150", warranty_years=5, cost_price=13500, selling_price=16500, stock_quantity=25, reorder_level=15, warehouse="North", status="Active"),
            dict(sku="STR-3K", product_name="3kW Structure Kit", category="Structure", brand="SolarEdge", model="GI-3K", warranty_years=10, cost_price=8000, selling_price=10500, stock_quantity=4, reorder_level=8, warehouse="Main", status="Active"),
        ]),
    "purchase_orders": dict(
        display="Purchase Orders", module="Inventory", icon="🛒",
        cols=[
            ("po_number", "PO Number", "Text"), ("vendor", "Vendor", "Text"),
            ("sku", "SKU", "Lookup", None, None, "inventory", "sku"),
            ("quantity", "Quantity", "Number"), ("unit_cost", "Unit Cost", "Currency"),
            ("order_date", "Order Date", "Date"), ("expected_delivery", "Expected Delivery", "Date"),
            ("status", "Status", "Status", ["Draft", "Ordered", "In Transit", "Received", "Cancelled"]),
            ("total_cost", "Total Cost", "Formula", None, "quantity * unit_cost"),
        ],
        rows=[
            dict(po_number="PO-1001", vendor="Adani Solar", sku="PNL-540", quantity=100, unit_cost=9400, order_date=T(12), expected_delivery=T(-2), status="In Transit"),
            dict(po_number="PO-1002", vendor="Growatt India", sku="INV-5K", quantity=15, unit_cost=31500, order_date=T(5), expected_delivery=F(6), status="Ordered"),
        ]),
    "inventory_movement": dict(
        display="Inventory Movement", module="Inventory", icon="🔄",
        cols=[
            ("movement_date", "Date", "Date"),
            ("sku", "SKU", "Lookup", None, None, "inventory", "sku"),
            ("movement_type", "Type", "Dropdown", ["Inward", "Outward", "Transfer", "Damage", "Replacement", "Return"]),
            ("quantity", "Quantity", "Number"),
            ("reference", "Reference (Order/PO/Customer)", "Text"),
            ("notes", "Notes", "Long Text"),
        ],
        rows=[
            dict(movement_date=T(3), sku="PNL-540", movement_type="Outward", quantity=6, reference="ORD-2041", notes="Supplied to Ramesh Kumar site"),
            dict(movement_date=T(1), sku="INV-5K", movement_type="Damage", quantity=1, reference="DMG-009", notes="Cracked casing in transit"),
        ]),
    "kit_mapping": dict(
        display="Solar Kit Mapping", module="Inventory", icon="🔗",
        cols=[
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("order_id", "Order ID", "Text"),
            ("panel_serials", "Panel Serial Nos", "Long Text"),
            ("inverter_serial", "Inverter Serial No", "Text"),
            ("battery_serial", "Battery Serial No", "Text"),
            ("structure_kit_id", "Structure Kit ID", "Text"),
            ("supply_date", "Supply Date", "Date"),
        ],
        rows=[
            dict(customer_name="Ramesh Kumar", order_id="ORD-2041", panel_serials="AS540-88121, AS540-88122, AS540-88123, AS540-88124, AS540-88125, AS540-88126", inverter_serial="GRW-MIN5K-4471", battery_serial="", structure_kit_id="GI3K-0192", supply_date=T(3)),
        ]),
    "damage_claims": dict(
        display="Damage Claims", module="Inventory", icon="🧾",
        cols=[
            ("claim_id", "Claim ID", "Text"),
            ("sku", "SKU", "Lookup", None, None, "inventory", "sku"),
            ("claim_date", "Claim Date", "Date"),
            ("quantity", "Quantity", "Number"),
            ("claim_amount", "Claim Amount", "Currency"),
            ("photo_url", "Photo Link", "Image URL"),
            ("vendor_status", "Vendor Claim Status", "Status", ["Reported", "Under Review", "Approved", "Rejected", "Paid"]),
            ("resolution", "Resolution Notes", "Long Text"),
        ],
        rows=[
            dict(claim_id="DMG-009", sku="INV-5K", claim_date=T(1), quantity=1, claim_amount=31500, photo_url="", vendor_status="Reported", resolution=""),
        ]),
    # --- LEADS / CRM ----------------------------------------------------------
    "leads": dict(
        display="Leads", module="Sales & CRM", icon="🎯",
        cols=[
            ("lead_name", "Lead Name", "Text"), ("phone", "Phone", "Phone"),
            ("city", "City", "Text"),
            ("source", "Source", "Dropdown", ["Website", "Facebook", "Instagram", "Google", "Referral", "Retail Partner", "Walk-in", "Call Center"]),
            ("lead_date", "Lead Date", "Date"),
            ("assigned_rep", "Assigned Rep", "User"),
            ("stage", "Stage", "Status", ["New", "Contacted", "Qualified", "Site Visit", "Quotation Shared", "Negotiation", "Won", "Lost"]),
            ("last_contact", "Last Contact", "Date"),
            ("next_follow_up", "Next Follow-up", "Date"),
            ("quote_value", "Quote Value", "Currency"),
            ("lost_reason", "Lost Reason", "Dropdown", ["", "Price", "Competitor", "Financing", "No Decision", "Trust Issues", "Other"]),
            ("lead_age_days", "Lead Age (Days)", "Formula", None, "DAYS(TODAY(), lead_date)"),
        ],
        rows=[
            dict(lead_name="Sunita Sharma", phone="98110xxxxx", city="Jaipur", source="Facebook", lead_date=T(10), assigned_rep="rep1", stage="Contacted", last_contact=T(8), next_follow_up=T(1), quote_value=185000, lost_reason=""),
            dict(lead_name="Vikram Patel", phone="98220xxxxx", city="Ahmedabad", source="Referral", lead_date=T(4), assigned_rep="rep1", stage="Site Visit", last_contact=T(1), next_follow_up=F(2), quote_value=310000, lost_reason=""),
            dict(lead_name="Anil Verma", phone="99880xxxxx", city="Jaipur", source="Google", lead_date=T(25), assigned_rep="rep1", stage="Lost", last_contact=T(15), next_follow_up="", quote_value=150000, lost_reason="Price"),
            dict(lead_name="Meena Joshi", phone="97770xxxxx", city="Udaipur", source="Retail Partner", lead_date=T(2), assigned_rep="rep1", stage="New", last_contact="", next_follow_up=F(1), quote_value=0, lost_reason=""),
        ]),
    "site_visits": dict(
        display="Site Visits", module="Sales & CRM", icon="📍",
        cols=[
            ("lead_name", "Lead", "Lookup", None, None, "leads", "lead_name"),
            ("visit_date", "Visit Date", "Date"),
            ("roof_area_sqft", "Roof Area (sqft)", "Number"),
            ("monthly_bill", "Monthly Electricity Bill", "Currency"),
            ("monthly_units", "Monthly Units (kWh)", "Number"),
            ("gps", "GPS Coordinates", "Text"),
            ("photos", "Photos Link", "Image URL"),
            ("notes", "Notes", "Long Text"),
        ],
        rows=[
            dict(lead_name="Vikram Patel", visit_date=T(1), roof_area_sqft=800, monthly_bill=6500, monthly_units=750, gps="23.0225, 72.5714", photos="", notes="Shadow-free south facing roof, 5kW feasible"),
        ]),
    "quotations": dict(
        display="Quotations", module="Sales & CRM", icon="📄",
        cols=[
            ("quote_no", "Quote No", "Text"),
            ("lead_name", "Lead", "Lookup", None, None, "leads", "lead_name"),
            ("version", "Version", "Number"),
            ("system_kw", "System Size (kW)", "Number"),
            ("price", "Price", "Currency"), ("discount", "Discount", "Currency"),
            ("status", "Status", "Status", ["Draft", "Shared", "Approved", "Rejected", "Expired"]),
            ("quote_date", "Quote Date", "Date"),
            ("final_price", "Final Price", "Formula", None, "price - discount"),
        ],
        rows=[
            dict(quote_no="QT-311", lead_name="Vikram Patel", version=1, system_kw=5, price=320000, discount=10000, status="Shared", quote_date=T(1)),
        ]),
    "incentives": dict(
        display="Incentives", module="Sales & CRM", icon="🏆",
        cols=[
            ("employee", "Employee", "User"),
            ("incentive_type", "Type", "Dropdown", ["Sales", "Referral", "Retailer", "Manager"]),
            ("order_id", "Order ID", "Text"),
            ("order_value", "Order Value", "Currency"),
            ("incentive_pct", "Incentive %", "Number"),
            ("month", "Month", "Text"),
            ("status", "Status", "Status", ["Pending", "Approved", "Paid"]),
            ("incentive_amount", "Incentive Amount", "Formula", None, "order_value * incentive_pct / 100"),
        ],
        rows=[
            dict(employee="rep1", incentive_type="Sales", order_id="ORD-2041", order_value=295000, incentive_pct=1.5, month="Aug-2026", status="Pending"),
        ]),
    # --- CUSTOMER JOURNEY -------------------------------------------------------
    "customers": dict(
        display="Customers", module="Customer Journey", icon="👥",
        cols=[
            ("customer_name", "Customer Name", "Text"), ("phone", "Phone", "Phone"),
            ("email", "Email", "Email"), ("city", "City", "Text"), ("state", "State", "Text"),
            ("order_id", "Order ID", "Text"),
            ("system_kw", "System Size (kW)", "Number"),
            ("order_value", "Order Value", "Currency"),
            ("order_date", "Order Date", "Date"),
            ("kyc_status", "KYC Status", "Status", ["Pending", "Submitted", "Verified"]),
            ("loan_status", "Loan Status", "Status", ["Not Applicable", "Applied", "Verification", "Approved", "Disbursed"]),
            ("journey_stage", "Journey Stage", "Status", ["Order Confirmed", "Advance Paid", "Supply Done", "Installed", "Meter Installed", "Commissioned", "Closed"]),
            ("referral_source", "Referred By", "Text"),
        ],
        rows=[
            dict(customer_name="Ramesh Kumar", phone="98000xxxxx", email="ramesh@example.com", city="Jaipur", state="Rajasthan", order_id="ORD-2041", system_kw=3, order_value=295000, order_date=T(20), kyc_status="Verified", loan_status="Disbursed", journey_stage="Supply Done", referral_source=""),
            dict(customer_name="Priya Nair", phone="98111xxxxx", email="priya@example.com", city="Kochi", state="Kerala", order_id="ORD-2042", system_kw=5, order_value=410000, order_date=T(35), kyc_status="Verified", loan_status="Not Applicable", journey_stage="Commissioned", referral_source="Ramesh Kumar"),
        ]),
    "invoices": dict(
        display="Invoices", module="Customer Journey", icon="🧾",
        cols=[
            ("invoice_no", "Invoice No", "Text"),
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("invoice_date", "Invoice Date", "Date"),
            ("amount", "Amount", "Currency"),
            ("gst_pct", "GST %", "Number"),
            ("status", "Status", "Status", ["Draft", "Issued", "Revised", "Credit Note", "Cancelled"]),
            ("total_with_gst", "Total (with GST)", "Formula", None, "amount + amount * gst_pct / 100"),
        ],
        rows=[
            dict(invoice_no="INV-501", customer_name="Ramesh Kumar", invoice_date=T(18), amount=295000, gst_pct=13.8, status="Issued"),
            dict(invoice_no="INV-502", customer_name="Priya Nair", invoice_date=T(30), amount=410000, gst_pct=13.8, status="Issued"),
        ]),
    "payments": dict(
        display="Payments", module="Customer Journey", icon="💰",
        cols=[
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("invoice_no", "Invoice No", "Lookup", None, None, "invoices", "invoice_no"),
            ("milestone", "Milestone", "Dropdown", ["30% Advance", "Supply Payment", "Final Payment", "Other"]),
            ("due_date", "Due Date", "Date"),
            ("amount_due", "Amount Due", "Currency"),
            ("amount_received", "Amount Received", "Currency"),
            ("received_date", "Received Date", "Date"),
            ("mode", "Mode", "Dropdown", ["UPI", "Bank Transfer", "Cheque", "Cash", "Loan Disbursement"]),
            ("status", "Status", "Status", ["Pending", "Partial", "Received", "Overdue"]),
            ("balance", "Balance", "Formula", None, "amount_due - amount_received"),
        ],
        rows=[
            dict(customer_name="Ramesh Kumar", invoice_no="INV-501", milestone="30% Advance", due_date=T(19), amount_due=88500, amount_received=88500, received_date=T(19), mode="UPI", status="Received"),
            dict(customer_name="Ramesh Kumar", invoice_no="INV-501", milestone="Supply Payment", due_date=T(4), amount_due=177000, amount_received=100000, received_date=T(2), mode="Bank Transfer", status="Partial"),
            dict(customer_name="Priya Nair", invoice_no="INV-502", milestone="Final Payment", due_date=T(8), amount_due=41000, amount_received=0, received_date="", mode="", status="Overdue"),
        ]),
    "installations": dict(
        display="Installations", module="Customer Journey", icon="🔧",
        cols=[
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("scheduled_date", "Scheduled Date", "Date"),
            ("team", "Assigned Team", "Text"),
            ("checklist_done", "Checklist Complete", "Checkbox"),
            ("photos", "Photos Link", "Image URL"),
            ("status", "Status", "Status", ["Scheduled", "In Progress", "Installed", "Commissioned", "On Hold"]),
            ("completion_date", "Completion Date", "Date"),
        ],
        rows=[
            dict(customer_name="Ramesh Kumar", scheduled_date=F(2), team="Team A", checklist_done=0, photos="", status="Scheduled", completion_date=""),
            dict(customer_name="Priya Nair", scheduled_date=T(20), team="Team B", checklist_done=1, photos="", status="Commissioned", completion_date=T(15)),
        ]),
    "metering": dict(
        display="Metering & DISCOM", module="Customer Journey", icon="⚡",
        cols=[
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("application_no", "Application No", "Text"),
            ("discom", "Electricity Board", "Text"),
            ("application_date", "Application Date", "Date"),
            ("status", "Status", "Status", ["Applied", "Verification", "Testing", "Approved", "Net Meter Installed"]),
            ("net_meter_date", "Net Meter Date", "Date"),
        ],
        rows=[
            dict(customer_name="Priya Nair", application_no="KSEB-8812", discom="KSEB", application_date=T(18), status="Net Meter Installed", net_meter_date=T(12)),
            dict(customer_name="Ramesh Kumar", application_no="JVVNL-4432", discom="JVVNL", application_date=T(6), status="Verification", net_meter_date=""),
        ]),
    "subsidies": dict(
        display="Subsidy Tracking", module="Customer Journey", icon="🏛️",
        cols=[
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("scheme", "Scheme", "Dropdown", ["PM Surya Ghar", "State Subsidy", "Other"]),
            ("application_date", "Application Date", "Date"),
            ("expected_amount", "Expected Amount", "Currency"),
            ("received_amount", "Received Amount", "Currency"),
            ("status", "Status", "Status", ["Applied", "Approved", "Received", "Rejected"]),
            ("pending_amount", "Pending Amount", "Formula", None, "expected_amount - received_amount"),
        ],
        rows=[
            dict(customer_name="Ramesh Kumar", scheme="PM Surya Ghar", application_date=T(15), expected_amount=78000, received_amount=0, status="Applied"),
            dict(customer_name="Priya Nair", scheme="PM Surya Ghar", application_date=T(30), expected_amount=78000, received_amount=78000, status="Received"),
        ]),
    "service_requests": dict(
        display="Service & Warranty", module="Customer Journey", icon="🛠️",
        cols=[
            ("ticket_no", "Ticket No", "Text"),
            ("customer_name", "Customer", "Lookup", None, None, "customers", "customer_name"),
            ("request_date", "Request Date", "Date"),
            ("issue_type", "Issue Type", "Dropdown", ["Warranty Claim", "Maintenance", "Performance Issue", "Query", "Other"]),
            ("description", "Description", "Long Text"),
            ("assigned_to", "Assigned To", "User"),
            ("status", "Status", "Status", ["Open", "In Progress", "Parts Ordered", "Resolved", "Closed"]),
            ("resolved_date", "Resolved Date", "Date"),
            ("open_days", "Open For (Days)", "Formula", None, "DAYS(TODAY(), request_date)"),
        ],
        rows=[
            dict(ticket_no="SR-101", customer_name="Priya Nair", request_date=T(3), issue_type="Performance Issue", description="Generation lower than expected on cloudy days", assigned_to="", status="Open", resolved_date=""),
        ]),
    "referrals": dict(
        display="Referrals & Feedback", module="Customer Journey", icon="💚",
        cols=[
            ("customer_name", "Referring Customer", "Lookup", None, None, "customers", "customer_name"),
            ("referred_name", "Referred Person", "Text"),
            ("referred_phone", "Referred Phone", "Phone"),
            ("referral_date", "Date", "Date"),
            ("converted", "Converted", "Checkbox"),
            ("reward_amount", "Reward", "Currency"),
            ("feedback_rating", "Feedback (1-5)", "Number"),
            ("testimonial", "Testimonial", "Long Text"),
        ],
        rows=[
            dict(customer_name="Ramesh Kumar", referred_name="Suresh Gupta", referred_phone="98123xxxxx", referral_date=T(5), converted=0, reward_amount=0, feedback_rating=5, testimonial="Very smooth installation process"),
        ]),
    # --- RETAIL PARTNERS ---------------------------------------------------------
    "retailers": dict(
        display="Retail Partners", module="Retail Partners", icon="🏪",
        cols=[
            ("partner_name", "Partner Name", "Text"), ("owner", "Owner", "Text"),
            ("phone", "Phone", "Phone"), ("city", "City", "Text"),
            ("business_type", "Business Type", "Dropdown", ["Electrical Shop", "Hardware Store", "Electronics", "Other"]),
            ("potential", "Potential", "Dropdown", ["High", "Medium", "Low"]),
            ("status", "Status", "Status", ["Prospect", "Contacted", "Onboarded", "Active", "Inactive"]),
            ("training_done", "Training Complete", "Checkbox"),
            ("driving_rep", "Driving Sales Rep", "User"),
        ],
        rows=[
            dict(partner_name="Shakti Electricals", owner="Mahesh Jain", phone="94140xxxxx", city="Jaipur", business_type="Electrical Shop", potential="High", status="Active", training_done=1, driving_rep="rep1"),
            dict(partner_name="Om Hardware", owner="Kishore Bhatt", phone="94610xxxxx", city="Udaipur", business_type="Hardware Store", potential="Medium", status="Prospect", training_done=0, driving_rep="rep1"),
        ]),
    "retail_orders": dict(
        display="Retail Orders", module="Retail Partners", icon="📑",
        cols=[
            ("partner_name", "Partner", "Lookup", None, None, "retailers", "partner_name"),
            ("order_date", "Order Date", "Date"),
            ("sku", "SKU", "Lookup", None, None, "inventory", "sku"),
            ("quantity", "Quantity", "Number"),
            ("unit_price", "Unit Price", "Currency"),
            ("amount_paid", "Amount Paid", "Currency"),
            ("status", "Status", "Status", ["Ordered", "Dispatched", "Delivered", "Returned"]),
            ("order_value", "Order Value", "Formula", None, "quantity * unit_price"),
            ("outstanding", "Outstanding", "Formula", None, "quantity * unit_price - amount_paid"),
        ],
        rows=[
            dict(partner_name="Shakti Electricals", order_date=T(9), sku="PNL-540", quantity=20, unit_price=11000, amount_paid=150000, status="Delivered"),
        ]),
}


def _seed_module(key, spec, owner="admin"):
    cols = []
    for c in spec["cols"]:
        d = {"name": c[0], "label": c[1], "col_type": c[2]}
        if len(c) > 3 and c[3]:
            d["options"] = c[3]
        if len(c) > 4 and c[4]:
            d["formula"] = c[4]
        if len(c) > 5 and c[5]:
            d["lookup_table"], d["lookup_key"] = c[5], c[6]
        cols.append(d)
    create_data_table(key, spec["display"], spec["module"], spec["icon"], cols, owner)
    for row in spec.get("rows", []):
        keys = list(row.keys())
        run(f'INSERT INTO "data_{key}" ({", ".join(chr(34)+k+chr(34) for k in keys)}, _created_by, _created_at) '
            f'VALUES ({", ".join(":"+k for k in keys)}, :_u, :_t)',
            {**row, "_u": owner, "_t": now_iso()})


def _seed_permissions():
    """Role → tables they can see/edit, and whether restricted to own rows."""
    grants = {
        "Sales Manager": {"leads": "edit", "site_visits": "edit", "quotations": "edit",
                          "incentives": "view", "customers": "edit", "retailers": "view"},
        "Sales Rep": {"leads": "edit-own", "site_visits": "edit-own", "quotations": "edit-own",
                      "customers": "view", "incentives": "view-own", "retailers": "edit-own",
                      "retail_orders": "edit-own"},
        "Inventory Manager": {"inventory": "edit", "purchase_orders": "edit",
                              "inventory_movement": "edit", "kit_mapping": "edit",
                              "damage_claims": "edit"},
        "Finance Team": {"invoices": "edit", "payments": "edit", "subsidies": "edit",
                         "customers": "view", "incentives": "edit", "retail_orders": "view"},
        "Installation Team": {"installations": "edit", "kit_mapping": "view",
                              "customers": "view", "metering": "edit"},
        "Service Team": {"service_requests": "edit", "customers": "view",
                         "kit_mapping": "view", "referrals": "edit"},
        "Retail Partner": {"retail_orders": "view-own", "retailers": "view-own"},
    }
    run("DELETE FROM sys_permissions WHERE role NOT IN ('Super Admin','Business Owner')")
    for role, tables in grants.items():
        for t, mode in tables.items():
            can_edit = 1 if mode.startswith("edit") else 0
            own = 1 if mode.endswith("-own") else 0
            run("INSERT INTO sys_permissions (role, table_name, can_view, can_edit, can_add, can_delete, own_rows_only) "
                "VALUES (:r,:t,1,:e,:e2,0,:o)",
                {"r": role, "t": t, "e": can_edit, "e2": can_edit, "o": own})


def _seed_rules():
    add_rule("Stale leads", "leads", "days_since", "lead_date", ">", 7,
             "Leads older than 7 days that are not yet Won/Lost — follow up today.",
             "warning", "Business Owner, Sales Manager, Super Admin", "admin")
    add_rule("Payment overdue", "payments", "status_is", "status", "==", "Overdue",
             "Customer payments are overdue — call for collection.",
             "error", "ALL", "admin")
    add_rule("Low stock", "inventory", "value", "stock_quantity", "<", 10,
             "Stock below 10 units — raise a purchase order.",
             "warning", "Business Owner, Inventory Manager, Super Admin", "admin")
    add_rule("Service tickets open 3+ days", "service_requests", "days_since",
             "request_date", ">=", 3,
             "Service tickets open for 3+ days — check with the service team.",
             "warning", "Business Owner, Service Team, Super Admin", "admin")


def run_seed():
    init_system_tables()
    if seeded():
        return False
    init_roles()
    create_user("admin", "admin123", "Business Owner", "Business Owner", email="owner@example.com")
    create_user("superadmin", "super123", "Super Admin", "Super Admin")
    create_user("rep1", "rep123", "Arjun Singh (Sales Rep)", "Sales Rep")
    create_user("inv1", "inv123", "Kavita Rao (Inventory)", "Inventory Manager")
    create_user("fin1", "fin123", "Deepak Shah (Finance)", "Finance Team")
    for key, spec in MODULES.items():
        _seed_module(key, spec)
    _seed_permissions()
    _seed_rules()
    return True


if __name__ == "__main__":
    created = run_seed()
    print("Seeded fresh database." if created else "Database already seeded.")
