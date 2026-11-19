"""Create synthetic demo accounts in a new, isolated local database."""
import getpass
import os
import secrets
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "instance" / "demo"
sys.path.insert(0, str(ROOT))


def main():
    password = getpass.getpass("New demo-only password (at least 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters.")
    try:
        WORKSPACE.mkdir(parents=True)
    except FileExistsError:
        raise SystemExit("instance/demo already exists. Its records were left intact.") from None
    os.environ["HARVEST_DATABASE"] = str(WORKSPACE / "demo.db")
    os.environ["HARVEST_UPLOAD_DIR"] = str(WORKSPACE / "photos")
    os.environ["HARVEST_ROTATED_SECRET_KEY"] = secrets.token_hex(32)
    from app import get_db
    from werkzeug.security import generate_password_hash

    today = date.today()
    expires = today + timedelta(days=14)
    with closing(get_db()) as db, db:
        db.execute("INSERT INTO subscription_demo(id) VALUES (1)")
        for index, name, village in ((1, "Demo Tshisaulu Grower", "Tshisaulu"),
                                     (2, "Demo Makwarela Grower", "Makwarela")):
            farmer = db.execute("""INSERT INTO farmers(name,phone,village,demo_account)
                VALUES (?,?,?,1)""", (name, f"+2700000000{index}", village)).lastrowid
            db.execute("INSERT INTO users(email,password_hash,role,profile_id) VALUES (?,?,'farmer',?)",
                       (f"farmer{index}@demo.invalid", generate_password_hash(password), farmer))
            if index == 1:
                db.execute("""INSERT INTO produce_listings
                    (farmer_id,crop,quantity_kg,available_kg,harvest_date,available_until,quality,asking_price)
                    VALUES (?,'Potatoes',650,650,?,?,'Grade A',15)""",
                    (farmer, today.isoformat(), expires.isoformat()))
        buyer = db.execute("""INSERT INTO buyers(business_name,contact_name,phone,location)
            VALUES ('Demo Vhembe Buyer','Demo Buyer','+27000000003','Thohoyandou')""").lastrowid
        db.execute("INSERT INTO users(email,password_hash,role,profile_id) VALUES (?,?,'buyer',?)",
                   ("buyer@demo.invalid", generate_password_hash(password), buyer))
        db.execute("INSERT INTO admin_accounts(email,password_hash) VALUES (?,?)",
                   ("admin@demo.invalid", generate_password_hash(password)))
    print("Synthetic accounts saved to instance/demo/demo.db.")


if __name__ == "__main__":
    main()
