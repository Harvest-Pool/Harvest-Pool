
from flask import (
    Flask, render_template, request,
    redirect, url_for, flash
)
import sqlite3
import os
import math

app = Flask(__name__)
app.secret_key = "harvest-pool-dev-key"

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "harvest_pool.db"
)


# -----------------------------
# DATABASE CONNECTION
# -----------------------------

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():

    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS farmers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            village TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS buyers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            location TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS produce_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            crop TEXT NOT NULL,
            quantity_kg REAL NOT NULL,
            available_kg REAL NOT NULL,
            harvest_date TEXT NOT NULL,
            quality TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farmer_id) REFERENCES farmers(id)
        );

        CREATE TABLE IF NOT EXISTS buyer_demands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER NOT NULL,
            crop TEXT NOT NULL,
            quantity_kg REAL NOT NULL,
            target_price REAL NOT NULL,
            deadline TEXT NOT NULL,
            delivery_location TEXT NOT NULL,
            status TEXT DEFAULT 'Open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (buyer_id) REFERENCES buyers(id)
        );

        CREATE TABLE IF NOT EXISTS harvest_pools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            demand_id INTEGER NOT NULL UNIQUE,
            total_allocated_kg REAL DEFAULT 0,
            status TEXT DEFAULT 'Open',
            FOREIGN KEY (demand_id) REFERENCES buyer_demands(id)
        );

        CREATE TABLE IF NOT EXISTS pool_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            farmer_id INTEGER NOT NULL,
            quantity_kg REAL NOT NULL,
            indicative_price REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (pool_id) REFERENCES harvest_pools(id),
            FOREIGN KEY (listing_id) REFERENCES produce_listings(id),
            FOREIGN KEY (farmer_id) REFERENCES farmers(id)
        );
    """)

    db.commit()
    db.close()


# -----------------------------
# VALIDATION
# -----------------------------

def positive_number(value):

    try:
        number = float(value)

        if number <= 0 or not math.isfinite(number):
            return None

        return number

    except (ValueError, TypeError):
        return None


# -----------------------------
# DASHBOARD
# -----------------------------

@app.route("/")
def dashboard():

    db = get_db()

    stats = {
        "farmers": db.execute(
            "SELECT COUNT(*) FROM farmers"
        ).fetchone()[0],

        "buyers": db.execute(
            "SELECT COUNT(*) FROM buyers"
        ).fetchone()[0],

        "supply": db.execute(
            "SELECT COALESCE(SUM(available_kg), 0) "
            "FROM produce_listings"
        ).fetchone()[0],

        "demands": db.execute(
            """SELECT COUNT(*) FROM buyer_demands
               WHERE status IN ('Open', 'Partially matched')"""
        ).fetchone()[0]
    }

    farmers = db.execute(
        "SELECT * FROM farmers ORDER BY id DESC"
    ).fetchall()

    buyers = db.execute(
        "SELECT * FROM buyers ORDER BY id DESC"
    ).fetchall()

    listings = db.execute("""
        SELECT p.*, f.name AS farmer_name, f.village
        FROM produce_listings p
        JOIN farmers f ON p.farmer_id = f.id
        ORDER BY p.id DESC
    """).fetchall()

    demands = db.execute("""
        SELECT d.*, b.business_name
        FROM buyer_demands d
        JOIN buyers b ON d.buyer_id = b.id
        ORDER BY d.id DESC
    """).fetchall()

    pools = db.execute("""
        SELECT
            hp.*,
            d.crop,
            d.quantity_kg,
            d.target_price,
            b.business_name,
            COUNT(pc.id) AS contribution_count
        FROM harvest_pools hp
        JOIN buyer_demands d ON hp.demand_id = d.id
        JOIN buyers b ON d.buyer_id = b.id
        LEFT JOIN pool_contributions pc ON hp.id = pc.pool_id
        GROUP BY hp.id
        ORDER BY hp.id DESC
    """).fetchall()

    db.close()

    return render_template(
        "index.html",
        stats=stats,
        farmers=farmers,
        buyers=buyers,
        listings=listings,
        demands=demands,
        pools=pools
    )


# -----------------------------
# FARMER REGISTRATION
# -----------------------------

@app.route("/farmers/add", methods=["POST"])
def add_farmer():

    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    village = request.form.get("village", "").strip()

    if not all([name, phone, village]):
        flash("Complete all farmer registration fields.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    try:
        db.execute("""
            INSERT INTO farmers (name, phone, village)
            VALUES (?, ?, ?)
        """, (name, phone, village))

        db.commit()
        flash("Farmer registered successfully.", "success")

    except sqlite3.IntegrityError:
        flash("This phone number is already registered.", "error")

    finally:
        db.close()

    return redirect(url_for("dashboard"))


# -----------------------------
# BUYER REGISTRATION
# -----------------------------

@app.route("/buyers/add", methods=["POST"])
def add_buyer():

    business = request.form.get(
        "business_name", ""
    ).strip()

    contact = request.form.get(
        "contact_name", ""
    ).strip()

    phone = request.form.get("phone", "").strip()
    location = request.form.get("location", "").strip()

    if not all([business, contact, phone, location]):
        flash("Complete all buyer registration fields.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    try:
        db.execute("""
            INSERT INTO buyers (
                business_name, contact_name, phone, location
            )
            VALUES (?, ?, ?, ?)
        """, (business, contact, phone, location))

        db.commit()
        flash("Buyer registered successfully.", "success")

    except sqlite3.IntegrityError:
        flash("This buyer phone number is already registered.", "error")

    finally:
        db.close()

    return redirect(url_for("dashboard"))


# -----------------------------
# PRODUCE LISTING
# -----------------------------

@app.route("/produce/add", methods=["POST"])
def add_produce():

    farmer_id = request.form.get("farmer_id")
    crop = request.form.get("crop", "").strip().title()
    quantity = positive_number(
        request.form.get("quantity_kg")
    )

    harvest_date = request.form.get("harvest_date")
    quality = request.form.get("quality")

    if not all([farmer_id, crop, quantity, harvest_date, quality]):
        flash("Complete all produce listing fields.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    farmer = db.execute(
        "SELECT id FROM farmers WHERE id = ?",
        (farmer_id,)
    ).fetchone()

    if not farmer:
        db.close()
        flash("Please select a valid registered farmer.", "error")
        return redirect(url_for("dashboard"))

    db.execute("""
        INSERT INTO produce_listings (
            farmer_id, crop, quantity_kg,
            available_kg, harvest_date, quality
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        farmer_id, crop, quantity,
        quantity, harvest_date, quality
    ))

    db.commit()
    db.close()

    flash("Produce successfully listed.", "success")

    return redirect(url_for("dashboard"))


# -----------------------------
# BUYER DEMAND SUBMISSION
# -----------------------------

@app.route("/demands/add", methods=["POST"])
def add_demand():

    buyer_id = request.form.get("buyer_id")
    crop = request.form.get("crop", "").strip().title()

    quantity = positive_number(
        request.form.get("quantity_kg")
    )

    price = positive_number(
        request.form.get("target_price")
    )

    deadline = request.form.get("deadline")

    location = request.form.get(
        "delivery_location", ""
    ).strip()

    if not all([
        buyer_id, crop, quantity,
        price, deadline, location
    ]):
        flash("Complete all buyer demand fields.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    buyer = db.execute(
        "SELECT id FROM buyers WHERE id = ?",
        (buyer_id,)
    ).fetchone()

    if not buyer:
        db.close()
        flash("Please select a valid registered buyer.", "error")
        return redirect(url_for("dashboard"))

    db.execute("""
        INSERT INTO buyer_demands (
            buyer_id, crop, quantity_kg,
            target_price, deadline, delivery_location
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        buyer_id, crop, quantity,
        price, deadline, location
    ))

    db.commit()
    db.close()

    flash("Buyer demand published successfully.", "success")

    return redirect(url_for("dashboard"))


# -----------------------------
# HARVEST POOL MATCHING ENGINE
# -----------------------------

@app.route("/match/<int:demand_id>", methods=["POST"])
def match_supply(demand_id):

    db = get_db()

    demand = db.execute("""
        SELECT * FROM buyer_demands
        WHERE id = ?
    """, (demand_id,)).fetchone()

    if not demand:
        db.close()
        flash("Buyer demand not found.", "error")
        return redirect(url_for("dashboard"))

    pool = db.execute("""
        SELECT * FROM harvest_pools
        WHERE demand_id = ?
    """, (demand_id,)).fetchone()

    if pool:
        pool_id = pool["id"]
    else:
        cursor = db.execute("""
            INSERT INTO harvest_pools (demand_id)
            VALUES (?)
        """, (demand_id,))

        pool_id = cursor.lastrowid

    already_allocated = db.execute("""
        SELECT COALESCE(SUM(quantity_kg), 0)
        FROM pool_contributions
        WHERE pool_id = ?
    """, (pool_id,)).fetchone()[0]

    remaining = demand["quantity_kg"] - already_allocated

    if remaining <= 0:
        db.close()
        flash("This buyer demand is already fulfilled.", "success")
        return redirect(url_for("dashboard"))

    # Find eligible available produce.
    listings = db.execute("""
        SELECT * FROM produce_listings
        WHERE LOWER(crop) = LOWER(?)
        AND available_kg > 0
        AND harvest_date <= ?
        ORDER BY harvest_date ASC, id ASC
    """, (
        demand["crop"],
        demand["deadline"]
    )).fetchall()

    allocated_now = 0

    for listing in listings:

        if remaining <= 0:
            break

        available = listing["available_kg"]

        allocation = min(available, remaining)

        if allocation <= 0:
            continue

        # Reserve the allocated quantity.
        db.execute("""
            UPDATE produce_listings
            SET available_kg = available_kg - ?
            WHERE id = ?
        """, (allocation, listing["id"]))

        # Record the farmer's contribution.
        db.execute("""
            INSERT INTO pool_contributions (
                pool_id, listing_id, farmer_id,
                quantity_kg, indicative_price
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            pool_id,
            listing["id"],
            listing["farmer_id"],
            allocation,
            demand["target_price"]
        ))

        remaining -= allocation
        allocated_now += allocation

    total = already_allocated + allocated_now

    if total >= demand["quantity_kg"]:
        status = "Fulfilled"

    elif total > 0:
        status = "Partially matched"

    else:
        status = "Open"

    db.execute("""
        UPDATE harvest_pools
        SET total_allocated_kg = ?, status = ?
        WHERE id = ?
    """, (total, status, pool_id))

    db.execute("""
        UPDATE buyer_demands
        SET status = ?
        WHERE id = ?
    """, (status, demand_id))

    db.commit()
    db.close()

    flash(
        f"Harvest Pool updated: {allocated_now:g} kg "
        f"newly allocated. Total: {total:g} kg. "
        f"Status: {status}.",
        "success"
    )

    return redirect(url_for("dashboard"))


# -----------------------------
# START APPLICATION
# -----------------------------

init_db()

if __name__ == "__main__":
    app.run(debug=True)
