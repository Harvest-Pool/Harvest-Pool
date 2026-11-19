"""Plan entitlements and isolated, local mock subscription billing."""
import calendar
import csv
import io
import secrets
from contextlib import closing
from datetime import date, datetime, timezone

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from financial_model import cents, number

PLANS = (
    ("free", "Free", None, 0, 3, 2, 20),
    ("farmer-pro", "Farmer Pro", "farmer", 9900, None, None, 100),
    ("buyer-pro", "Buyer Pro", "buyer", 49900, None, None, 100),
)

ACTIVE_SQL = {
    "farmer": """SELECT count(*) FROM produce_listings
        WHERE farmer_id=? AND available_until>=? AND available_kg>0""",
    "buyer": """SELECT count(*) FROM buyer_demands d WHERE d.buyer_id=? AND d.deadline>=?
        AND NOT EXISTS(SELECT 1 FROM demo_orders o WHERE o.demand_id=d.id)""",
}


def migrate_subscriptions(db):
    statements = (
        """CREATE TABLE IF NOT EXISTS subscription_plans (
            code TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT,
            price_cents INTEGER NOT NULL CHECK(price_cents>=0),
            farmer_limit INTEGER CHECK(farmer_limit>0),
            buyer_limit INTEGER CHECK(buyer_limit>0),
            guide_daily INTEGER NOT NULL CHECK(guide_daily>0))""",
        """CREATE TABLE IF NOT EXISTS subscription_attempts (
            reference TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            plan_code TEXT NOT NULL REFERENCES subscription_plans(code),
            amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
            currency TEXT NOT NULL DEFAULT 'ZAR' CHECK(currency='ZAR'),
            outcome TEXT NOT NULL CHECK(outcome IN ('mock_success','mock_failure')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE INDEX IF NOT EXISTS subscription_attempt_owner ON subscription_attempts(user_id, created_at)""",
        """CREATE TABLE IF NOT EXISTS subscription_periods (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            plan_code TEXT NOT NULL REFERENCES subscription_plans(code),
            starts_on TEXT NOT NULL, ends_on TEXT NOT NULL CHECK(ends_on>starts_on),
            reference TEXT NOT NULL UNIQUE REFERENCES subscription_attempts(reference),
            cancel_renewal INTEGER NOT NULL DEFAULT 0 CHECK(cancel_renewal IN (0,1)))""",
        """CREATE INDEX IF NOT EXISTS subscription_period_owner ON subscription_periods(user_id, ends_on)""",
        """CREATE TABLE IF NOT EXISTS subscription_events (
            id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            admin_id INTEGER REFERENCES admin_accounts(id), kind TEXT NOT NULL,
            details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS subscription_demo (
            id INTEGER PRIMARY KEY CHECK(id=1))""",
        """CREATE TABLE IF NOT EXISTS subscription_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            crop TEXT NOT NULL, place TEXT NOT NULL, notify INTEGER NOT NULL CHECK(notify IN (0,1)),
            quantity TEXT NOT NULL, target_price TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS subscription_guide_usage (
            user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL,
            requests INTEGER NOT NULL, PRIMARY KEY(user_id, day))""",
    )
    for sql in statements:
        db.execute(sql)
    db.executemany("INSERT OR IGNORE INTO subscription_plans VALUES (?,?,?,?,?,?,?)", PLANS)


def period_for(db, user_id, today):
    return db.execute("""SELECT * FROM subscription_periods
        WHERE user_id=? AND starts_on<=? AND ends_on>? ORDER BY ends_on DESC,id DESC LIMIT 1""",
        (user_id, today, today)).fetchone()


def demo_enabled(db, config):
    return bool(config.get("DEMO_MODE") and config.get("SUBSCRIPTION_DEMO")
                and db.execute("SELECT 1 FROM subscription_demo WHERE id=1").fetchone())


def plan_for(db, user, config, today=None):
    day = today or date.today().isoformat()
    period = period_for(db, user.id, day) if demo_enabled(db, config) else None
    code = period["plan_code"] if period else "free"
    return db.execute("SELECT * FROM subscription_plans WHERE code=? AND (role IS NULL OR role=?)",
                      (code, user.role)).fetchone() or db.execute(
                          "SELECT * FROM subscription_plans WHERE code='free'").fetchone()


def resource_limit_reached(db, user, config, day):
    plan = plan_for(db, user, config, day)
    limit = plan[f"{user.role}_limit"]
    return limit is not None and db.execute(ACTIVE_SQL[user.role], (user.profile_id, day)).fetchone()[0] >= limit


def consume_guide_request(db, user, config):
    day = datetime.now(timezone.utc).date().isoformat()
    db.execute("BEGIN IMMEDIATE")
    limit = plan_for(db, user, config)["guide_daily"]
    result = db.execute("""INSERT INTO subscription_guide_usage VALUES (?,?,1)
        ON CONFLICT(user_id,day) DO UPDATE SET requests=requests+1 WHERE requests<?""",
        (user.id, day, limit))
    return result.rowcount == 1


def add_month(day):
    year, month = day.year + (day.month == 12), day.month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def record_event(db, kind, details, user_id=None, admin_id=None):
    db.execute("INSERT INTO subscription_events(user_id,admin_id,kind,details) VALUES (?,?,?,?)",
               (user_id, admin_id, kind, details))


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def pro_data(db, user):
    if user.role == "farmer":
        return db.execute("""SELECT p.id,p.crop,p.quantity_kg,p.available_kg,
            COUNT(CASE WHEN c.offer_status='Accepted' THEN 1 END) AS accepted_offers,
            COALESCE(SUM(CASE WHEN c.offer_status='Accepted' THEN c.quantity_kg ELSE 0 END),0) AS accepted_kg
            FROM produce_listings p LEFT JOIN pool_contributions c ON c.listing_id=p.id
            WHERE p.farmer_id=? GROUP BY p.id ORDER BY p.id DESC""", (user.profile_id,)).fetchall()
    return db.execute("""SELECT o.id,d.crop,o.total_kg,o.indicative_total_cents,
            COUNT(DISTINCT a.farmer_id) AS growers,o.status
            FROM demo_orders o JOIN buyer_demands d ON d.id=o.demand_id
            LEFT JOIN order_farmer_allocations a ON a.order_id=o.id
            WHERE o.buyer_id=? GROUP BY o.id ORDER BY o.id DESC""", (user.profile_id,)).fetchall()


def register_subscriptions(app, get_db, require_role, limiter):
    def require_account():
        if current_user.role not in ACTIVE_SQL:
            abort(403)

    @app.route("/account", methods=["GET", "POST"])
    @login_required
    @limiter.limit("12 per hour", methods=["POST"])
    def account_profile():
        require_account()
        farmer = current_user.role == "farmer"
        table, name_field, place_field = (("farmers", "name", "village") if farmer
                                         else ("buyers", "contact_name", "location"))
        with closing(get_db()) as db, db:
            if request.method == "POST":
                name = request.form.get("name", "").strip()
                place = request.form.get("place", "").strip()
                if 0 < len(name) <= 100 and 0 < len(place) <= 150:
                    db.execute("BEGIN IMMEDIATE")
                    if farmer:
                        condition = " AND (verification_status!='Approved' OR (name=? AND village=?))"
                        params = (name, place, current_user.profile_id, name, place)
                    else:
                        condition = ""
                        params = (name, place, current_user.profile_id)
                    saved = db.execute(f"UPDATE {table} SET {name_field}=?,{place_field}=? WHERE id=?" + condition,
                                       params)
                    flash("Profile updated." if saved.rowcount else
                          "Contact an administrator to change reviewed seller details.",
                          "success" if saved.rowcount else "error")
                    return redirect(url_for("account_profile"))
                flash("Enter a valid name and location.", "error")
            profile = db.execute(f"SELECT {name_field} AS name,{place_field} AS place FROM {table} WHERE id=?",
                                 (current_user.profile_id,)).fetchone()
        if not profile:
            abort(404)
        return render_template("account.html", profile=profile)

    @app.get("/pricing")
    def pricing():
        with closing(get_db()) as db:
            plans = db.execute("SELECT * FROM subscription_plans ORDER BY price_cents, code").fetchall()
        return render_template("pricing.html", plans=plans)

    @app.get("/subscription")
    @login_required
    def subscription():
        require_account()
        with closing(get_db()) as db:
            today = date.today().isoformat()
            enabled = demo_enabled(db, app.config)
            plan = plan_for(db, current_user, app.config, today)
            period = period_for(db, current_user.id, today) if enabled else None
            proposed = db.execute("SELECT * FROM subscription_plans WHERE role=?", (current_user.role,)).fetchone()
            attempts = db.execute("""SELECT a.*,p.name FROM subscription_attempts a
                JOIN subscription_plans p ON p.code=a.plan_code WHERE a.user_id=?
                ORDER BY a.created_at DESC,a.rowid DESC LIMIT 30""", (current_user.id,)).fetchall()
            count = db.execute(ACTIVE_SQL[current_user.role], (current_user.profile_id, today)).fetchone()[0]
        return render_template("subscription.html", plan=plan, period=period, proposed=proposed,
                               attempts=attempts, demo_enabled=enabled, count=count,
                               reference=secrets.token_hex(16))

    @app.post("/subscription/mock")
    @login_required
    @limiter.limit("8 per hour")
    def mock_subscription():
        require_account()
        nonce = request.form.get("reference", "")
        if len(nonce) != 32 or any(char not in "0123456789abcdef" for char in nonce):
            abort(400)
        choice = request.form.get("outcome")
        if choice not in ("mock_success", "mock_failure"):
            abort(400)
        reference = f"mock-{current_user.id}-{nonce}"
        today = date.today()
        with closing(get_db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not demo_enabled(db, app.config):
                abort(403)
            plan = db.execute("SELECT * FROM subscription_plans WHERE code=? AND role=?",
                              (request.form.get("plan"), current_user.role)).fetchone()
            if not plan:
                abort(403)
            if db.execute("SELECT 1 FROM subscription_attempts WHERE reference=?", (reference,)).fetchone():
                return redirect(url_for("subscription"))
            period = period_for(db, current_user.id, today.isoformat())
            if period:
                flash("A mock period is already active. Wait for it to expire.", "error")
                return redirect(url_for("subscription"))
            db.execute("""INSERT INTO subscription_attempts(reference,user_id,plan_code,amount_cents,outcome)
                VALUES (?,?,?,?,?)""", (reference, current_user.id, plan["code"], plan["price_cents"], choice))
            if choice == "mock_success":
                db.execute("""INSERT INTO subscription_periods(user_id,plan_code,starts_on,ends_on,reference)
                    VALUES (?,?,?,?,?)""",
                    (current_user.id, plan["code"], today.isoformat(), add_month(today).isoformat(), reference))
            record_event(db, choice, reference, current_user.id)
        return redirect(url_for("subscription"))

    @app.post("/subscription/cancel")
    @login_required
    def cancel_subscription():
        require_account()
        with closing(get_db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not demo_enabled(db, app.config):
                abort(403)
            period = period_for(db, current_user.id, date.today().isoformat())
            if period and not period["cancel_renewal"]:
                db.execute("UPDATE subscription_periods SET cancel_renewal=1 WHERE id=?", (period["id"],))
                record_event(db, "mock_cancel_renewal", period["reference"], current_user.id)
        return redirect(url_for("subscription"))

    @app.route("/subscription/tools", methods=["GET", "POST"])
    @login_required
    def subscription_tools():
        require_account()
        with closing(get_db()) as db, db:
            if request.method == "POST":
                db.execute("BEGIN IMMEDIATE")
            if plan_for(db, current_user, app.config)["code"] == "free":
                abort(403)
            if request.method == "POST":
                form = request.form
                crop, place = form.get("crop", "").strip(), form.get("place", "").strip()
                quantity, target = form.get("quantity", ""), form.get("target_price", "")
                try:
                    if len(crop) > 100 or len(place) > 150:
                        raise ValueError
                    quantity = str(number(quantity or "0", "1000000"))
                    target = str(number(target or "0", "1000000"))
                except ValueError:
                    flash("Enter valid sourcing preferences.", "error")
                else:
                    db.execute("""INSERT INTO subscription_preferences VALUES (?,?,?,?,?,?)
                        ON CONFLICT(user_id) DO UPDATE SET crop=excluded.crop,place=excluded.place,
                        notify=excluded.notify,quantity=excluded.quantity,target_price=excluded.target_price""",
                        (current_user.id, crop, place, int(form.get("notify") == "yes"), quantity, target))
                    return redirect(url_for("subscription_tools"))
            prefs = db.execute("SELECT * FROM subscription_preferences WHERE user_id=?", (current_user.id,)).fetchone()
            insights = []
            if prefs and prefs["crop"]:
                if current_user.role == "farmer":
                    insights = db.execute("""SELECT crop,quantity_kg,target_price,deadline FROM buyer_demands d
                        WHERE crop=? COLLATE NOCASE AND deadline>=? AND NOT EXISTS
                        (SELECT 1 FROM demo_orders o WHERE o.demand_id=d.id)
                        ORDER BY target_price DESC LIMIT 20""", (prefs["crop"], date.today().isoformat())).fetchall()
                else:
                    insights = db.execute("""SELECT p.crop,p.available_kg,p.asking_price,f.village
                        FROM produce_listings p JOIN farmers f ON f.id=p.farmer_id
                        JOIN seller_eligibility se ON se.farmer_id=f.id
                        WHERE p.crop=? COLLATE NOCASE AND p.available_kg>0 AND p.asking_price IS NOT NULL
                        AND se.eligible=1 AND p.available_until>=?
                        AND (?='' OR instr(lower(f.village),lower(?))>0)
                        AND (CAST(? AS REAL)=0 OR p.asking_price<=CAST(? AS REAL))
                        ORDER BY p.asking_price LIMIT 20""",
                        (prefs["crop"], date.today().isoformat(), prefs["place"], prefs["place"],
                         prefs["target_price"], prefs["target_price"])).fetchall()
            rows = pro_data(db, current_user)
            quote_overview = []
            if current_user.role == "farmer":
                quote_overview = db.execute("""SELECT status,count(*) AS total FROM packaging_quotes
                    WHERE farmer_id=? GROUP BY status ORDER BY status""", (current_user.profile_id,)).fetchall()
        return render_template("subscription_tools.html", prefs=prefs, rows=rows, insights=insights,
                               quote_overview=quote_overview)

    @app.get("/subscription/report.csv")
    @login_required
    def subscription_report():
        require_account()
        with closing(get_db()) as db:
            if plan_for(db, current_user, app.config)["code"] == "free":
                abort(403)
            rows = pro_data(db, current_user)
        stream = io.StringIO()
        writer = csv.writer(stream)
        headers = ("listing_id","crop","listed_kg","available_kg","accepted_offers","accepted_kg") if current_user.role == "farmer" else (
            "order_id","crop","total_kg","produce_value_cents","growers","order_status")
        writer.writerow(headers)
        writer.writerows([csv_cell(value) for value in row] for row in rows)
        return Response(stream.getvalue(), mimetype="text/csv", headers={
            "Content-Disposition": "attachment; filename=harvest-pool-report.csv", "Cache-Control": "no-store"})

    @app.route("/admin/subscriptions", methods=["GET", "POST"])
    @require_role("admin")
    @limiter.limit("20 per hour", methods=["POST"])
    def admin_subscriptions():
        with closing(get_db()) as db, db:
            if request.method == "POST":
                db.execute("BEGIN IMMEDIATE")
                code = request.form.get("code")
                plan = db.execute("SELECT * FROM subscription_plans WHERE code=?", (code,)).fetchone()
                if not plan:
                    abort(404)
                try:
                    guide = int(number(request.form.get("guide_daily"), "10000", 0))
                    if not guide:
                        raise ValueError
                    if code == "free":
                        price = 0
                        farmer = int(number(request.form.get("farmer_limit"), "10000", 0))
                        buyer = int(number(request.form.get("buyer_limit"), "10000", 0))
                        if not farmer or not buyer:
                            raise ValueError
                    else:
                        price = cents(number(request.form.get("price"), "100000"))
                        if not price:
                            raise ValueError
                        limit = request.form.get("active_limit", "").strip()
                        limit = int(number(limit, "10000", 0)) if limit else None
                        if limit == 0:
                            raise ValueError
                        farmer = limit if plan["role"] == "farmer" else None
                        buyer = limit if plan["role"] == "buyer" else None
                except ValueError:
                    flash("Enter valid positive limits and a valid plan price.", "error")
                else:
                    db.execute("""UPDATE subscription_plans SET price_cents=?, farmer_limit=?,
                        buyer_limit=?,guide_daily=? WHERE code=?""", (price, farmer, buyer, guide, code))
                    record_event(db, "plan_updated", f"{code}: {price} cents; farmer={farmer}; buyer={buyer}; guide={guide}",
                                 admin_id=current_user.db_id)
                    return redirect(url_for("admin_subscriptions"))
            today = date.today().isoformat()
            plans = db.execute("SELECT * FROM subscription_plans ORDER BY price_cents, code").fetchall()
            periods = db.execute("""SELECT s.*,u.email,p.name FROM subscription_periods s
                JOIN users u ON u.id=s.user_id JOIN subscription_plans p ON p.code=s.plan_code
                ORDER BY s.id DESC LIMIT 100""").fetchall()
            counts = {"free": db.execute("SELECT count(*) FROM users WHERE is_active=1").fetchone()[0],
                      "farmer-pro": 0, "buyer-pro": 0}
            if demo_enabled(db, app.config):
                for row in db.execute("""SELECT s.plan_code,count(DISTINCT s.user_id) AS total
                    FROM subscription_periods s JOIN users u ON u.id=s.user_id
                    WHERE s.starts_on<=? AND s.ends_on>? AND u.is_active=1 GROUP BY s.plan_code""", (today, today)):
                    counts[row["plan_code"]] = row["total"]
                    counts["free"] -= row["total"]
            failures = db.execute("""SELECT a.*,u.email FROM subscription_attempts a JOIN users u ON u.id=a.user_id
                WHERE a.outcome='mock_failure' ORDER BY a.created_at DESC LIMIT 30""").fetchall()
            events = db.execute("SELECT * FROM subscription_events ORDER BY id DESC LIMIT 50").fetchall()
        return render_template("admin_subscriptions.html", plans=plans, periods=periods, counts=counts,
                               failures=failures, events=events, today=today)
