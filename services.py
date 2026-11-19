"""Packaging quotes and administrator planning views."""
import json
from contextlib import closing
from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from financial_model import D, INPUTS, RATES, SCENARIOS, cents, number, project, read_fields, service_lines

SERVICES = {"packaging": "Packaging only", "branding": "Branding only", "combined": "Packaging and branding"}
TRANSITIONS = {
    "Requested": ("Awaiting clarification", "Quoted", "Rejected"),
    "Awaiting clarification": ("Awaiting clarification", "Quoted", "Rejected"),
    "Quoted": ("Quoted", "Awaiting clarification", "Accepted", "Rejected"),
    "Accepted": ("Planning", "Rejected"),
    "Planning": ("Planning", "Rejected"),
    "Rejected": (),
}


def migrate_services(db):
    db.execute("""CREATE TABLE IF NOT EXISTS planning_settings (
        name TEXT PRIMARY KEY, settings_json TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS packaging_quotes (
        id INTEGER PRIMARY KEY,
        farmer_id INTEGER NOT NULL REFERENCES farmers(id),
        listing_id INTEGER NOT NULL REFERENCES produce_listings(id),
        crop TEXT NOT NULL,
        quantity_kg TEXT NOT NULL,
        service TEXT NOT NULL CHECK(service IN ('packaging','branding','combined')),
        labelled_units INTEGER NOT NULL CHECK(labelled_units >= 0),
        new_design INTEGER NOT NULL CHECK(new_design IN (0,1)),
        requirements TEXT NOT NULL,
        estimate_cents INTEGER NOT NULL CHECK(estimate_cents >= 0),
        estimate_rates TEXT NOT NULL,
        quote_cents INTEGER CHECK(quote_cents >= 0),
        status TEXT NOT NULL DEFAULT 'Requested',
        review_note TEXT,
        revision INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    quote_columns = {row["name"] for row in db.execute("PRAGMA table_info(packaging_quotes)")}
    if "revision" not in quote_columns:
        db.execute("ALTER TABLE packaging_quotes ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
    db.execute("""CREATE INDEX IF NOT EXISTS packaging_quotes_farmer
        ON packaging_quotes(farmer_id, id)""")
    db.execute("""CREATE TABLE IF NOT EXISTS packaging_quote_events (
        id INTEGER PRIMARY KEY,
        quote_id INTEGER NOT NULL REFERENCES packaging_quotes(id),
        admin_id INTEGER NOT NULL REFERENCES admin_accounts(id),
        prior_status TEXT NOT NULL,
        status TEXT NOT NULL,
        quote_cents INTEGER,
        note TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")


def load_settings(db, name):
    row = db.execute("SELECT settings_json FROM planning_settings WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else {}


def save_settings(db, name, values):
    db.execute("""INSERT INTO planning_settings VALUES (?,?)
        ON CONFLICT(name) DO UPDATE SET settings_json=excluded.settings_json""",
        (name, json.dumps({key: str(value) for key, value in values.items()})))


def register_services(app, get_db, require_role, limiter):
    @app.get("/packaging")
    def packaging():
        listings, quotes = [], []
        with closing(get_db()) as db:
            rates = read_fields(RATES, load_settings(db, "rates"))
            if current_user.is_authenticated and current_user.role == "farmer":
                listings = db.execute("""SELECT id,crop,available_kg FROM produce_listings
                    WHERE farmer_id=? AND available_kg>0 AND available_until>=?
                    ORDER BY id DESC""", (current_user.profile_id, date.today().isoformat())).fetchall()
                quotes = db.execute("""SELECT * FROM packaging_quotes
                    WHERE farmer_id=? ORDER BY id DESC""", (current_user.profile_id,)).fetchall()
        return render_template("packaging.html", listings=listings, quotes=quotes, rates=rates, services=SERVICES)

    @app.post("/packaging/request")
    @require_role("farmer")
    @limiter.limit("12 per hour")
    def request_packaging():
        try:
            listing_id = request.form.get("listing_id", 0, type=int)
            if not 0 < listing_id < 2**63:
                raise ValueError("Choose one of your available listings.")
            service = request.form.get("service")
            if service not in SERVICES:
                raise ValueError("Choose a valid service.")
            kg = number(request.form.get("quantity_kg"), "1000000")
            units = int(number(request.form.get("labelled_units", "0"), "1000000", 0))
            design = request.form.get("new_design") == "yes"
            notes = request.form.get("requirements", "").strip()
            if not kg or not 10 <= len(notes) <= 1000:
                raise ValueError("Enter a positive quantity and describe your requirements in 10?1000 characters.")
            if service == "packaging" and (units or design):
                raise ValueError("Label quantities and new artwork require branding.")
            if service != "packaging" and not units:
                raise ValueError("Enter the number of units that need labels.")
            with closing(get_db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                listing = db.execute("""SELECT crop,available_kg,available_until FROM produce_listings
                    WHERE id=? AND farmer_id=?""", (listing_id, current_user.profile_id)).fetchone()
                if not listing:
                    abort(404)
                if (not listing["available_until"] or listing["available_until"] < date.today().isoformat()
                        or kg > D(str(listing["available_kg"]))):
                    raise ValueError("The quantity exceeds current availability or the listing has expired.")
                rates = read_fields(RATES, load_settings(db, "rates"))
                revenue, _ = service_lines(rates, D(0), kg if service != "branding" else D(0), units, int(design))
                db.execute("""INSERT INTO packaging_quotes
                    (farmer_id,listing_id,crop,quantity_kg,service,labelled_units,new_design,
                     requirements,estimate_cents,estimate_rates)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (current_user.profile_id, listing_id, listing["crop"], str(kg), service,
                     units, int(design), notes, cents(sum(revenue.values())),
                     json.dumps({key: str(value) for key, value in rates.items() if key.endswith("_price")})))
            flash("Quote requested. Review and fulfilment capacity are subject to confirmation.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("packaging") + "#service-requests")

    @app.get("/admin/packaging")
    @require_role("admin")
    def admin_packaging():
        with closing(get_db()) as db:
            quotes = db.execute("""SELECT q.*,f.name AS farmer_name FROM packaging_quotes q
                JOIN farmers f ON f.id=q.farmer_id ORDER BY q.id DESC""").fetchall()
        return render_template("admin_packaging.html", quotes=quotes, services=SERVICES, transitions=TRANSITIONS)

    @app.post("/admin/packaging/<int:quote_id>")
    @require_role("admin")
    @limiter.limit("40 per hour")
    def review_packaging(quote_id):
        try:
            status = request.form.get("status")
            note = request.form.get("note", "").strip()
            revision = request.form.get("revision", type=int)
            if not 10 <= len(note) <= 500:
                raise ValueError("Enter a review note of 10?500 characters.")
            with closing(get_db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                quote = db.execute("SELECT * FROM packaging_quotes WHERE id=?", (quote_id,)).fetchone()
                if not quote:
                    abort(404)
                if revision != quote["revision"] or status not in TRANSITIONS[quote["status"]]:
                    raise ValueError("The request changed or the selected status is unavailable. Review it again.")
                amount = quote["quote_cents"]
                if status == "Quoted":
                    amount = cents(number(request.form.get("amount"), "100000000"))
                db.execute("""UPDATE packaging_quotes
                    SET status=?,quote_cents=?,review_note=?,revision=revision+1 WHERE id=?""",
                    (status, amount, note, quote_id))
                db.execute("""INSERT INTO packaging_quote_events
                    (quote_id,admin_id,prior_status,status,quote_cents,note) VALUES (?,?,?,?,?,?)""",
                    (quote_id, current_user.db_id, quote["status"], status, amount, note))
            flash("Quote review recorded.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("admin_packaging") + f"#quote-{quote_id}")

    @app.route("/admin/finance", methods=["GET", "POST"])
    @require_role("admin")
    def finance():
        scenario = request.args.get("scenario", "base")
        if scenario not in SCENARIOS:
            abort(404)
        with closing(get_db()) as db, db:
            stored_rates = load_settings(db, "rates")
            stored_inputs = SCENARIOS[scenario] | load_settings(db, scenario)
            if request.method == "POST":
                try:
                    rates = read_fields(RATES, stored_rates | request.form.to_dict())
                    inputs = read_fields(INPUTS, stored_inputs | request.form.to_dict())
                except ValueError as exc:
                    flash(str(exc), "error")
                else:
                    save_settings(db, "rates", rates)
                    save_settings(db, scenario, inputs)
                    flash("Pilot rates and scenario saved.", "success")
                    return redirect(url_for("finance", scenario=scenario))
            rates = read_fields(RATES, stored_rates)
            inputs = read_fields(INPUTS, stored_inputs)
        example_revenue, example_costs = service_lines(read_fields(RATES, {}), D(15000), D(1000), 1000, 1)
        return render_template("finance.html", rates=rates, inputs=inputs, scenario=scenario,
                               rate_fields=RATES, input_fields=INPUTS, scenarios=SCENARIOS,
                               model=project(rates, inputs), example_revenue=example_revenue,
                               example_costs=example_costs)
