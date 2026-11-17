"""Harvest Pool Phase 3: local demo with authenticated farmer/buyer roles.
Not production ready: no payment handling, identity verification, or farmer consent workflow.
"""
import math
import os
import re
import sqlite3
from datetime import date, datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
app = Flask(__name__)
secret = os.environ.get('SECRET_KEY')
if not secret or len(secret) < 32:
    raise RuntimeError('Set a strong SECRET_KEY (at least 32 characters) in .env')
app.config.update(
    SECRET_KEY=secret,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
    MAX_CONTENT_LENGTH=64 * 1024,
)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[], storage_uri='memory://')
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harvest_pool.db')


def get_db():
    db = sqlite3.connect(DATABASE, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA busy_timeout = 15000')
    return db


def init_db():
    db = get_db()
    try:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS farmers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE, village TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS buyers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, business_name TEXT NOT NULL,
                contact_name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
                location TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS produce_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, farmer_id INTEGER NOT NULL,
                crop TEXT NOT NULL, quantity_kg REAL NOT NULL,
                available_kg REAL NOT NULL, harvest_date TEXT NOT NULL,
                quality TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (farmer_id) REFERENCES farmers(id)
            );
            CREATE TABLE IF NOT EXISTS buyer_demands (
                id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER NOT NULL,
                crop TEXT NOT NULL, quantity_kg REAL NOT NULL,
                target_price REAL NOT NULL, deadline TEXT NOT NULL,
                delivery_location TEXT NOT NULL, status TEXT DEFAULT 'Open',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (buyer_id) REFERENCES buyers(id)
            );
            CREATE TABLE IF NOT EXISTS harvest_pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT, demand_id INTEGER NOT NULL UNIQUE,
                total_allocated_kg REAL DEFAULT 0, status TEXT DEFAULT 'Open',
                FOREIGN KEY (demand_id) REFERENCES buyer_demands(id)
            );
            CREATE TABLE IF NOT EXISTS pool_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, pool_id INTEGER NOT NULL,
                listing_id INTEGER NOT NULL, farmer_id INTEGER NOT NULL,
                quantity_kg REAL NOT NULL, indicative_price REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pool_id) REFERENCES harvest_pools(id),
                FOREIGN KEY (listing_id) REFERENCES produce_listings(id),
                FOREIGN KEY (farmer_id) REFERENCES farmers(id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('farmer', 'buyer')),
                profile_id INTEGER, is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        # Preserve older automatic allocations without misrepresenting farmer consent.
        columns = {row['name'] for row in db.execute('PRAGMA table_info(pool_contributions)')}
        if 'offer_status' not in columns:
            db.execute("ALTER TABLE pool_contributions ADD COLUMN offer_status TEXT NOT NULL DEFAULT 'Legacy reservation'")
        # A profile can only be owned by one account within its role.
        db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS unique_user_profile
                      ON users(role, profile_id) WHERE profile_id IS NOT NULL''')
        db.commit()
    finally:
        db.close()


class User(UserMixin):
    def __init__(self, row):
        self.id = row['id']
        self.email = row['email']
        self.role = row['role']
        self.profile_id = row['profile_id']
        self.active = bool(row['is_active'])

    @property
    def is_active(self):
        return self.active


@login_manager.user_loader
def load_user(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE id = ? AND is_active = 1', (user_id,)).fetchone()
        return User(row) if row else None
    finally:
        db.close()


def require_role(role):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role != role:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def positive_number(value):
    try:
        n = float(value)
        return n if n > 0 and math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@app.errorhandler(CSRFError)
def bad_csrf(_):
    return 'Your form expired or failed its security check. Refresh the page and retry.', 400


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit('8 per minute', methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        return render_template('register.html')

    role = request.form.get('role', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    place = request.form.get('place', '').strip()
    business_name = request.form.get('business_name', '').strip()

    if (role not in ('farmer', 'buyer') or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email)
            or len(email) > 254 or len(password) < 12 or len(password) > 128
            or not name or not phone or not place or len(name) > 120
            or len(phone) > 30 or len(place) > 120 or (role == 'buyer' and not business_name)
            or len(business_name) > 120):
        flash('Check your details. Passwords need at least 12 characters.', 'error')
        return render_template('register.html'), 400

    db = get_db()
    try:
        # Single transaction: profile and login account either both succeed or neither does.
        with db:
            if role == 'farmer':
                cursor = db.execute('INSERT INTO farmers(name, phone, village) VALUES (?, ?, ?)',
                                    (name, phone, place))
            else:
                cursor = db.execute('''INSERT INTO buyers(business_name, contact_name, phone, location)
                                       VALUES (?, ?, ?, ?)''', (business_name, name, phone, place))
            profile_id = cursor.lastrowid
            db.execute('''INSERT INTO users(email, password_hash, role, profile_id)
                          VALUES (?, ?, ?, ?)''',
                       (email, generate_password_hash(password), role, profile_id))
    except sqlite3.IntegrityError:
        flash('Email or phone number is already registered.', 'error')
        return render_template('register.html'), 409
    finally:
        db.close()
    flash('Account created. Please sign in.', 'success')
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('8 per minute', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        return render_template('login.html')
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE email = ? AND is_active = 1', (email,)).fetchone()
    finally:
        db.close()
    if not row or not check_password_hash(row['password_hash'], password):
        flash('Incorrect email or password.', 'error')
        return render_template('login.html'), 401
    login_user(User(row), remember=False, fresh=True)
    return redirect(url_for('dashboard'))


@app.post('/logout')
@login_required
def logout():
    logout_user()
    flash('Signed out.', 'success')
    return redirect(url_for('login'))


@app.get('/')
@login_required
def dashboard():
    db = get_db()
    try:
        if current_user.role == 'farmer':
            my_listings = db.execute('''SELECT * FROM produce_listings WHERE farmer_id = ?
                                        ORDER BY id DESC''', (current_user.profile_id,)).fetchall()
            my_contributions = db.execute('''
                SELECT pc.id, pc.quantity_kg, pc.indicative_price, pc.offer_status, p.crop, hp.status,
                       b.business_name
                FROM pool_contributions pc
                JOIN produce_listings p ON p.id = pc.listing_id
                JOIN harvest_pools hp ON hp.id = pc.pool_id
                JOIN buyer_demands d ON d.id = hp.demand_id
                JOIN buyers b ON b.id = d.buyer_id
                WHERE pc.farmer_id = ? ORDER BY pc.id DESC
            ''', (current_user.profile_id,)).fetchall()
            return render_template('index.html', my_listings=my_listings,
                                   my_contributions=my_contributions,
                                   my_demands=[], market_listings=[], my_pools=[])
        my_demands = db.execute('''SELECT * FROM buyer_demands WHERE buyer_id = ?
                                   ORDER BY id DESC''', (current_user.profile_id,)).fetchall()
        market_listings = db.execute('''
            SELECT p.id, p.crop, p.available_kg, p.quality, p.harvest_date,
                   f.village
            FROM produce_listings p JOIN farmers f ON f.id = p.farmer_id
            WHERE p.available_kg > 0 ORDER BY p.id DESC
        ''').fetchall()
        offer_summary = db.execute('''
            SELECT d.id AS demand_id,
              COALESCE(SUM(CASE WHEN pc.offer_status = 'Pending' THEN pc.quantity_kg ELSE 0 END), 0) AS pending_kg,
              COALESCE(SUM(CASE WHEN pc.offer_status = 'Accepted' THEN pc.quantity_kg ELSE 0 END), 0) AS accepted_kg,
              COALESCE(SUM(CASE WHEN pc.offer_status = 'Rejected' THEN pc.quantity_kg ELSE 0 END), 0) AS rejected_kg,
              COALESCE(SUM(CASE WHEN pc.offer_status = 'Legacy reservation' THEN pc.quantity_kg ELSE 0 END), 0) AS legacy_kg
            FROM buyer_demands d
            LEFT JOIN harvest_pools hp ON hp.demand_id = d.id
            LEFT JOIN pool_contributions pc ON pc.pool_id = hp.id
            WHERE d.buyer_id = ? GROUP BY d.id
        ''', (current_user.profile_id,)).fetchall()
        summary = {row['demand_id']: row for row in offer_summary}
        my_pools = db.execute('''
            SELECT hp.*, d.crop, d.quantity_kg, d.target_price
            FROM harvest_pools hp JOIN buyer_demands d ON d.id = hp.demand_id
            WHERE d.buyer_id = ? ORDER BY hp.id DESC
        ''', (current_user.profile_id,)).fetchall()
        return render_template('index.html', my_listings=[], my_contributions=[],
                               my_demands=my_demands, market_listings=market_listings,
                               my_pools=my_pools, summary=summary)
    finally:
        db.close()


@app.post('/produce/add')
@require_role('farmer')
def add_produce():
    crop = request.form.get('crop', '').strip().title()
    qty = positive_number(request.form.get('quantity_kg'))
    harvested = request.form.get('harvest_date', '')
    quality = request.form.get('quality', '')
    if not crop or len(crop) > 100 or not qty or not parse_date(harvested) or quality not in ('Grade A', 'Grade B', 'Mixed'):
        flash('Complete valid produce details.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    try:
        with db:
            db.execute('''INSERT INTO produce_listings
                (farmer_id, crop, quantity_kg, available_kg, harvest_date, quality)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (current_user.profile_id, crop, qty, qty, harvested, quality))
    finally:
        db.close()
    flash('Your produce was listed.', 'success')
    return redirect(url_for('dashboard'))


@app.post('/demands/add')
@require_role('buyer')
def add_demand():
    crop = request.form.get('crop', '').strip().title()
    qty = positive_number(request.form.get('quantity_kg'))
    price = positive_number(request.form.get('target_price'))
    deadline = request.form.get('deadline', '')
    location = request.form.get('delivery_location', '').strip()
    if (not crop or len(crop) > 100 or not qty or not price or not parse_date(deadline)
            or not location or len(location) > 150):
        flash('Complete valid buyer demand details.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    try:
        with db:
            db.execute('''INSERT INTO buyer_demands
                (buyer_id, crop, quantity_kg, target_price, deadline, delivery_location)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (current_user.profile_id, crop, qty, price, deadline, location))
    finally:
        db.close()
    flash('Your buyer demand was published.', 'success')
    return redirect(url_for('dashboard'))


def recalculate_pool(db, pool_id):
    # Only explicit farmer approvals count as accepted supply.
    pool = db.execute('''SELECT hp.demand_id, d.quantity_kg
                         FROM harvest_pools hp JOIN buyer_demands d ON d.id=hp.demand_id
                         WHERE hp.id = ?''', (pool_id,)).fetchone()
    accepted = db.execute('''SELECT COALESCE(SUM(quantity_kg), 0)
        FROM pool_contributions WHERE pool_id=? AND offer_status='Accepted' ''', (pool_id,)).fetchone()[0]
    pending = db.execute('''SELECT COALESCE(SUM(quantity_kg), 0)
        FROM pool_contributions WHERE pool_id=? AND offer_status='Pending' ''', (pool_id,)).fetchone()[0]
    legacy = db.execute('''SELECT COUNT(*) FROM pool_contributions
        WHERE pool_id=? AND offer_status='Legacy reservation' ''', (pool_id,)).fetchone()[0]
    if legacy:
        status = 'Legacy reservation'
    elif accepted >= pool['quantity_kg'] - 0.00001:
        status = 'Supply accepted'
    elif pending > 0:
        status = 'Awaiting farmer approval'
    elif accepted > 0:
        status = 'Partially accepted'
    else:
        status = 'Open'
    db.execute('UPDATE harvest_pools SET total_allocated_kg=?, status=? WHERE id=?',
               (accepted, status, pool_id))
    db.execute('UPDATE buyer_demands SET status=? WHERE id=?', (status, pool['demand_id']))
    return status


@app.post('/match/<int:demand_id>')
@require_role('buyer')
def match_supply(demand_id):
    # Propose offers without deducting farmer stock.
    db = get_db()
    created = 0
    try:
        db.execute('BEGIN IMMEDIATE')
        demand = db.execute('''SELECT * FROM buyer_demands
            WHERE id=? AND buyer_id=?''', (demand_id, current_user.profile_id)).fetchone()
        if not demand:
            db.rollback()
            abort(404)
        pool = db.execute('SELECT * FROM harvest_pools WHERE demand_id=?', (demand_id,)).fetchone()
        if pool:
            pool_id = pool['id']
            # Do not silently turn historical pre-consent allocations into offers.
            legacy_count = db.execute('''SELECT COUNT(*) FROM pool_contributions
                WHERE pool_id=? AND offer_status='Legacy reservation' ''', (pool_id,)).fetchone()[0]
            if legacy_count:
                db.rollback()
                flash('This is an older automatic-reservation pool. Create a new demand to test farmer approval.', 'error')
                return redirect(url_for('dashboard'))
        else:
            pool_id = db.execute('INSERT INTO harvest_pools(demand_id) VALUES (?)',
                                 (demand_id,)).lastrowid
        committed = db.execute('''SELECT COALESCE(SUM(quantity_kg),0)
            FROM pool_contributions WHERE pool_id=? AND offer_status IN ('Pending','Accepted')''',
            (pool_id,)).fetchone()[0]
        remaining = max(0, demand['quantity_kg'] - committed)
        if remaining > 0:
            # For each listing, subtract all pending offers made anywhere, so the demo
            # does not promise the same kilograms to multiple buyers.
            listings = db.execute('''SELECT p.*,
                COALESCE((SELECT SUM(pc.quantity_kg) FROM pool_contributions pc
                          WHERE pc.listing_id=p.id AND pc.offer_status='Pending'),0) AS pending_kg
                FROM produce_listings p
                WHERE LOWER(p.crop)=LOWER(?) AND p.available_kg > 0 AND p.harvest_date <= ?
                ORDER BY p.harvest_date, p.id''',
                (demand['crop'], demand['deadline'])).fetchall()
            for listing in listings:
                if remaining <= 0.00001:
                    break
                offerable = max(0, listing['available_kg']-listing['pending_kg'])
                amount = round(min(offerable, remaining), 4)
                if amount <= 0:
                    continue
                db.execute('''INSERT INTO pool_contributions
                    (pool_id, listing_id, farmer_id, quantity_kg, indicative_price, offer_status)
                    VALUES (?, ?, ?, ?, ?, 'Pending')''',
                    (pool_id, listing['id'], listing['farmer_id'], amount, demand['target_price']))
                created += 1
                remaining -= amount
        status = recalculate_pool(db, pool_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash(f'{created} farmer offer(s) proposed. Status: {status}. No stock has been deducted. '
          'Farmers must accept before supply is allocated.', 'success')
    return redirect(url_for('dashboard'))


@app.post('/offers/<int:contribution_id>/<decision>')
@require_role('farmer')
def respond_to_offer(contribution_id, decision):
    if decision not in ('accept', 'reject'):
        abort(404)
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        offer = db.execute('''SELECT pc.*, p.available_kg
            FROM pool_contributions pc
            JOIN produce_listings p ON p.id=pc.listing_id
            WHERE pc.id=? AND pc.farmer_id=? AND p.farmer_id=?''',
            (contribution_id, current_user.profile_id, current_user.profile_id)).fetchone()
        if not offer:
            db.rollback()
            abort(404)
        if offer['offer_status'] != 'Pending':
            db.rollback()
            flash('This offer has already been handled or belongs to an older test pool.', 'error')
            return redirect(url_for('dashboard'))
        if decision == 'accept':
            updated = db.execute('''UPDATE produce_listings
                SET available_kg=available_kg-?
                WHERE id=? AND farmer_id=? AND available_kg >= ?''',
                (offer['quantity_kg'], offer['listing_id'], current_user.profile_id,
                 offer['quantity_kg'])).rowcount
            if updated != 1:
                db.rollback()
                flash('Not enough available stock to accept this offer.', 'error')
                return redirect(url_for('dashboard'))
            new_status = 'Accepted'
        else:
            new_status = 'Rejected'
        db.execute('UPDATE pool_contributions SET offer_status=? WHERE id=?',
                   (new_status, contribution_id))
        recalculate_pool(db, offer['pool_id'])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash(f'Offer {new_status.lower()}. Buyer request status updated.', 'success')
    return redirect(url_for('dashboard'))


# Old routes were insecure: they cannot create unowned standalone profiles anymore.
@app.post('/farmers/add')
@app.post('/buyers/add')
@login_required
def disabled_legacy_registration():
    abort(403)


init_db()

if __name__ == '__main__':
    app.run(debug=False)
