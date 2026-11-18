"""Harvest Pool Phase 5: local demo of consent-led trading, price visibility, and IKS crop discovery.
Not production ready. No live payments, identity verification, or community knowledge submissions.
"""
import math
import io
import secrets
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for, send_from_directory
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.security import check_password_hash, generate_password_hash
import click

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
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[], storage_uri='memory://')
# Public references only. Local/cultural names require community verification before publication.
HERITAGE_CROPS = (
    {'name': 'Amaranth', 'group': 'Traditional leafy vegetable',
     'reference': 'Agricultural Research Council',
     'url': 'https://www.arc.agric.za/arc-vopi/Pages/Crop%20Science/Indigenous-Crops.aspx'},
    {'name': 'Cowpea Leaves', 'group': 'Traditional leafy vegetable',
     'reference': 'Department of Agriculture',
     'url': 'https://nda.gov.za/phocadownloadpap/Brochures_and_Production_Guidelines/Brochure%20Indigenous%20Food%20Crops%202010.pdf'},
    {'name': 'Bambara Groundnut', 'group': 'Traditional pulse',
     'reference': 'Department of Agriculture',
     'url': 'https://nda.gov.za/phocadownloadpap/Brochures_and_Production_Guidelines/Brochure%20Indigenous%20Food%20Crops%202010.pdf'},
    {'name': 'Spider Flower', 'group': 'Traditional leafy vegetable (Cleome)',
     'reference': 'Agricultural Research Council',
     'url': 'https://www.arc.agric.za/arc-vopi/Pages/Crop%20Science/Indigenous-Crops.aspx'},
)
HERITAGE_NAMES = {item['name'].casefold() for item in HERITAGE_CROPS}
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harvest_pool.db')
UPLOAD_DIR = Path(app.instance_path) / 'produce_photos'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
Image.MAX_IMAGE_PIXELS = 20_000_000



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
        # Phase 8 additive migration. Existing listings have no stated sell-by
        # date until their owner sets one; do NOT invent freshness dates.
        listing_fields = {r['name'] for r in db.execute('PRAGMA table_info(produce_listings)')}
        if 'available_until' not in listing_fields:
            db.execute('ALTER TABLE produce_listings ADD COLUMN available_until TEXT')
        if 'photo_filename' not in listing_fields:
            db.execute('ALTER TABLE produce_listings ADD COLUMN photo_filename TEXT')
        db.execute('CREATE INDEX IF NOT EXISTS idx_listings_expiry ON produce_listings(available_until)')
        # Existing farmers are intentionally PENDING: don't certify old test profiles.
        farmer_cols = {r['name'] for r in db.execute('PRAGMA table_info(farmers)')}
        if 'verification_status' not in farmer_cols:
            db.execute("ALTER TABLE farmers ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'Pending'")
        if 'verified_at' not in farmer_cols:
            db.execute('ALTER TABLE farmers ADD COLUMN verified_at TEXT')
        db.execute("""CREATE TABLE IF NOT EXISTS admin_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS seller_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL REFERENCES farmers(id),
            admin_id INTEGER NOT NULL REFERENCES admin_accounts(id),
            previous_status TEXT NOT NULL,
            new_status TEXT NOT NULL,
            review_note TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        # Preserve older automatic allocations without misrepresenting farmer consent.
        columns = {row['name'] for row in db.execute('PRAGMA table_info(pool_contributions)')}
        if 'offer_status' not in columns:
            db.execute("ALTER TABLE pool_contributions ADD COLUMN offer_status TEXT NOT NULL DEFAULT 'Legacy reservation'")
        # Add columns without dropping existing Phase 4 data.
        listing_cols = {row['name'] for row in db.execute('PRAGMA table_info(produce_listings)')}
        if 'asking_price' not in listing_cols:
            db.execute('ALTER TABLE produce_listings ADD COLUMN asking_price REAL')
        contribution_cols = {row['name'] for row in db.execute('PRAGMA table_info(pool_contributions)')}
        if 'farmer_asking_price' not in contribution_cols:
            db.execute('ALTER TABLE pool_contributions ADD COLUMN farmer_asking_price REAL')
        if 'transport_cost' not in contribution_cols:
            db.execute('ALTER TABLE pool_contributions ADD COLUMN transport_cost REAL')
        if 'packaging_cost' not in contribution_cols:
            db.execute('ALTER TABLE pool_contributions ADD COLUMN packaging_cost REAL')
        # Demo order states are NOT real payment or delivery evidence.
        db.execute("""CREATE TABLE IF NOT EXISTS demo_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            demand_id INTEGER NOT NULL UNIQUE REFERENCES buyer_demands(id),
            buyer_id INTEGER NOT NULL REFERENCES buyers(id),
            total_kg REAL NOT NULL CHECK(total_kg > 0),
            indicative_total_cents INTEGER NOT NULL CHECK(indicative_total_cents > 0),
            status TEXT NOT NULL DEFAULT 'Awaiting demo payment' CHECK(status IN
                ('Awaiting demo payment','Demo payment marked','Ready for demo delivery','Demo delivery confirmed')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        # Phase 10: per-farmer allocation snapshot for each buyer order.
        # No disbursements, bank details or real payment events are recorded here.
        db.execute("""CREATE TABLE IF NOT EXISTS order_farmer_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES demo_orders(id),
            contribution_id INTEGER NOT NULL UNIQUE REFERENCES pool_contributions(id),
            farmer_id INTEGER NOT NULL REFERENCES farmers(id),
            quantity_kg TEXT NOT NULL,
            buyer_unit_price_cents INTEGER NOT NULL CHECK (buyer_unit_price_cents > 0),
            gross_cents INTEGER NOT NULL CHECK (gross_cents >= 0),
            farmer_asking_price_cents INTEGER,
            status TEXT NOT NULL DEFAULT 'Allocation recorded'
                CHECK (status IN ('Allocation recorded')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute('CREATE INDEX IF NOT EXISTS idx_order_farmer_allocations_order ON order_farmer_allocations(order_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_order_farmer_allocations_farmer ON order_farmer_allocations(farmer_id)')
        contribution_cols = {row['name'] for row in db.execute('PRAGMA table_info(pool_contributions)')}
        if 'demo_ready' not in contribution_cols:
            db.execute('ALTER TABLE pool_contributions ADD COLUMN demo_ready INTEGER NOT NULL DEFAULT 0')
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


class AdminUser(UserMixin):
    role = 'admin'
    profile_id = None
    def __init__(self, row):
        self.db_id = row['id']
        self.email = row['email']
        self.active = bool(row['is_active'])

    def get_id(self):
        return f'admin:{self.db_id}'

    @property
    def is_active(self):
        return self.active


@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    try:
        if isinstance(user_id, str) and user_id.startswith('admin:'):
            try:
                admin_id = int(user_id.partition(':')[2])
            except ValueError:
                return None
            row = db.execute('SELECT * FROM admin_accounts WHERE id=? AND is_active=1',
                             (admin_id,)).fetchone()
            return AdminUser(row) if row else None
        try:
            numeric_id = int(user_id)
        except (TypeError, ValueError):
            return None
        row = db.execute('SELECT * FROM users WHERE id=? AND is_active=1',
                         (numeric_id,)).fetchone()
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


def nonnegative_money(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and 0 <= n <= 1_000_000 else None
    except (TypeError, ValueError):
        return None


def is_heritage(crop):
    return str(crop).strip().casefold() in HERITAGE_NAMES


def estimated_net(price_per_kg, kg, transport, packaging):
    return round(price_per_kg * kg - transport - packaging, 2)


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
        return redirect(url_for('admin_dashboard' if current_user.role == 'admin' else 'dashboard'))
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
        return redirect(url_for('admin_dashboard' if current_user.role == 'admin' else 'dashboard'))
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


@app.template_filter('expiry_warning_date')
def expiry_warning_date(today_string):
    return (date.fromisoformat(today_string)+timedelta(days=2)).isoformat()


def active_supply_query():
    return '''SELECT p.id,p.crop,p.available_kg,p.asking_price,p.quality,p.harvest_date,
        p.available_until,p.photo_filename,f.village,f.name AS farmer_name
        FROM produce_listings p JOIN farmers f ON f.id=p.farmer_id
        WHERE p.available_kg>0 AND p.asking_price IS NOT NULL
          AND f.verification_status='Approved'
          AND p.available_until >= ?
        '''


@app.get('/')
def home():
    db=get_db()
    try:
        listings=db.execute(active_supply_query()+' ORDER BY p.id DESC LIMIT 6',
                            (date.today().isoformat(),)).fetchall()
        count=db.execute("""SELECT COUNT(*) FROM produce_listings p JOIN farmers f ON f.id=p.farmer_id WHERE p.available_kg>0 AND f.verification_status='Approved' AND p.available_until >= ?""",
                         (date.today().isoformat(),)).fetchone()[0]
    finally:
        db.close()
    return render_template('home.html', featured=listings, listing_count=count,
                           heritage_crops=HERITAGE_CROPS, heritage_check=is_heritage)


@app.get('/marketplace')
def marketplace():
    search=request.args.get('q','').strip()[:80]
    db=get_db()
    try:
        q=active_supply_query()
        params=[date.today().isoformat()]
        if search:
            q+=' AND (p.crop LIKE ? OR f.village LIKE ?)'
            params.extend(['%'+search+'%']*2)
        q+=' ORDER BY p.id DESC LIMIT 60'
        listings=db.execute(q,params).fetchall()
    finally:
        db.close()
    return render_template('marketplace.html', listings=listings, query=search,
                           heritage_check=is_heritage, today=date.today().isoformat())


@app.get('/produce/<int:listing_id>')
def produce_detail(listing_id):
    db=get_db()
    try:
        listing=db.execute('''SELECT p.*,f.name AS farmer_name,f.village,f.verification_status
                              FROM produce_listings p JOIN farmers f ON f.id=p.farmer_id
                              WHERE p.id=?''',(listing_id,)).fetchone()
    finally:
        db.close()
    if not listing:
        abort(404)
    expired=bool(listing['available_until'] and listing['available_until']<date.today().isoformat())
    is_owner=(current_user.is_authenticated and current_user.role=='farmer'
              and current_user.profile_id==listing['farmer_id'])
    if (expired or listing['available_kg']<=0 or listing['verification_status']!='Approved') and not is_owner:
        abort(404)
    return render_template('produce_detail.html', listing=listing,
                           expired=expired, heritage_check=is_heritage)


@app.get('/produce-photo/<int:listing_id>')
def produce_photo(listing_id):
    db=get_db()
    try:
        row=db.execute('''SELECT p.photo_filename,p.farmer_id,f.verification_status
            FROM produce_listings p JOIN farmers f ON f.id=p.farmer_id WHERE p.id=?''',
            (listing_id,)).fetchone()
    finally:
        db.close()
    is_owner=(current_user.is_authenticated and current_user.role=='farmer'
              and current_user.profile_id==row['farmer_id']) if row else False
    if not row or not row['photo_filename'] or (row['verification_status']!='Approved' and not is_owner):
        abort(404)
    # Only generated opaque filenames are served; never accept paths from clients.
    filename=row['photo_filename']
    if not re.fullmatch(r'[0-9a-f]{32}\.jpg',filename):
        abort(404)
    return send_from_directory(str(UPLOAD_DIR), filename, mimetype='image/jpeg',
                               max_age=3600)


def save_produce_photo(upload):
    if not upload or not upload.filename:
        return None
    raw=upload.stream.read(5*1024*1024 + 1)
    if len(raw)>5*1024*1024:
        raise ValueError('Photograph must be smaller than 5 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            if decoded.format not in ('JPEG','PNG','WEBP'):
                raise ValueError('Upload a JPEG, PNG or WebP photo.')
            decoded.verify()
        with Image.open(io.BytesIO(raw)) as decoded:
            photo=ImageOps.exif_transpose(decoded)
            if photo.width*photo.height>20_000_000:
                raise ValueError('Image resolution is too large.')
            photo=photo.convert('RGB')
            photo.thumbnail((1600,1600))
            filename=secrets.token_hex(16)+'.jpg'
            photo.save(UPLOAD_DIR / filename,format='JPEG',quality=82,optimize=True)
            return filename
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValueError('That file is not a supported or valid photograph.') from e


@app.post('/produce/<int:listing_id>/photo')
@require_role('farmer')
@limiter.limit('15/hour')
def upload_produce_photo(listing_id):
    db=get_db()
    try:
        listing=db.execute('SELECT id,photo_filename FROM produce_listings WHERE id=? AND farmer_id=?',
                           (listing_id,current_user.profile_id)).fetchone()
    finally:
        db.close()
    if listing is None:
        abort(404)
    try:
        filename=save_produce_photo(request.files.get('photo'))
    except ValueError as e:
        flash(str(e),'error')
        return redirect(url_for('dashboard'))
    if not filename:
        flash('Select an image to upload.','error')
        return redirect(url_for('dashboard'))
    db=get_db()
    try:
        with db:
            db.execute('UPDATE produce_listings SET photo_filename=? WHERE id=? AND farmer_id=?',
                       (filename,listing_id,current_user.profile_id))
    finally:
        db.close()
    # Avoid automatic deletion of previously referenced images on error.
    flash('Produce photo updated.','success')
    return redirect(url_for('dashboard'))


@app.post('/produce/<int:listing_id>/availability')
@require_role('farmer')
def update_availability(listing_id):
    expiry=request.form.get('available_until','').strip()
    db=get_db()
    try:
        row=db.execute('SELECT harvest_date FROM produce_listings WHERE id=? AND farmer_id=?',
                       (listing_id,current_user.profile_id)).fetchone()
        if not row:
            abort(404)
        if not parse_date(expiry) or expiry<row['harvest_date'] or expiry < date.today().isoformat():
            flash('Choose an availability deadline on or after the harvest-ready date.','error')
            return redirect(url_for('dashboard'))
        with db:
            db.execute('UPDATE produce_listings SET available_until=? WHERE id=? AND farmer_id=?',
                       (expiry,listing_id,current_user.profile_id))
    finally:
        db.close()
    flash('Availability deadline updated.','success')
    return redirect(url_for('dashboard'))


@app.get('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    try:
        if current_user.role == 'farmer':
            farmer_profile = db.execute('SELECT verification_status FROM farmers WHERE id=?',
                                       (current_user.profile_id,)).fetchone()
            my_listings = db.execute('''SELECT * FROM produce_listings WHERE farmer_id = ?
                                        ORDER BY id DESC''', (current_user.profile_id,)).fetchall()
            my_contributions = db.execute('''
                SELECT pc.id, pc.quantity_kg, pc.indicative_price, pc.offer_status,
                       pc.farmer_asking_price, pc.transport_cost, pc.packaging_cost, pc.demo_ready, p.crop, hp.status,
                       b.business_name, o.id AS demo_order_id, o.status AS demo_order_status
                FROM pool_contributions pc
                JOIN produce_listings p ON p.id = pc.listing_id
                JOIN harvest_pools hp ON hp.id = pc.pool_id
                JOIN buyer_demands d ON d.id = hp.demand_id
                JOIN buyers b ON b.id = d.buyer_id
                LEFT JOIN demo_orders o ON o.demand_id = d.id
                WHERE pc.farmer_id = ? ORDER BY pc.id DESC
            ''', (current_user.profile_id,)).fetchall()
            return render_template('index.html', my_listings=my_listings, today=date.today().isoformat(),
                                   my_contributions=my_contributions, seller_verification=farmer_profile['verification_status'],
                                   my_demands=[], market_listings=[], my_pools=[], demo_orders=[],
                                   heritage_crops=HERITAGE_CROPS, heritage_check=is_heritage,
                                   estimated_net=estimated_net)
        my_demands = db.execute('''SELECT * FROM buyer_demands WHERE buyer_id = ?
                                   ORDER BY id DESC''', (current_user.profile_id,)).fetchall()
        market_listings = db.execute('''
            SELECT p.id, p.crop, p.available_kg, p.asking_price, p.quality, p.harvest_date,
                   f.village
            FROM produce_listings p JOIN farmers f ON f.id = p.farmer_id
            WHERE p.available_kg > 0 AND p.available_until >= date('now') AND f.verification_status='Approved' ORDER BY p.id DESC
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
        demo_orders = db.execute("""SELECT o.*, d.crop, d.quantity_kg, d.delivery_location,
                    (SELECT COUNT(*) FROM pool_contributions pc
                     JOIN harvest_pools hp ON hp.id=pc.pool_id
                     WHERE hp.demand_id=o.demand_id AND pc.offer_status='Accepted') AS accepted_count,
                    (SELECT COUNT(*) FROM pool_contributions pc
                     JOIN harvest_pools hp ON hp.id=pc.pool_id
                     WHERE hp.demand_id=o.demand_id AND pc.offer_status='Accepted' AND pc.demo_ready=1) AS ready_count
                    FROM demo_orders o JOIN buyer_demands d ON d.id=o.demand_id
                    WHERE o.buyer_id=? ORDER BY o.id DESC""", (current_user.profile_id,)).fetchall()
        return render_template('index.html', my_listings=[], my_contributions=[],
                               my_demands=my_demands, market_listings=market_listings, today=date.today().isoformat(),
                               my_pools=my_pools, summary=summary, demo_orders=demo_orders,
                               demo_order_demand_ids={o['demand_id'] for o in demo_orders},
                               heritage_crops=HERITAGE_CROPS, heritage_check=is_heritage,
                               estimated_net=estimated_net)
    finally:
        db.close()


@app.post('/produce/add')
@require_role('farmer')
def add_produce():
    crop = request.form.get('crop', '').strip().title()
    qty = positive_number(request.form.get('quantity_kg'))
    harvested = request.form.get('harvest_date', '')
    quality = request.form.get('quality', '')
    asking = positive_number(request.form.get('asking_price'))
    expiry = request.form.get('available_until', '').strip()
    if not asking or asking > 1_000_000:
        flash('Enter a valid asking price per kg.', 'error')
        return redirect(url_for('dashboard'))
    if not crop or len(crop) > 100 or not qty or not parse_date(harvested) or not parse_date(expiry) or expiry < harvested or expiry < date.today().isoformat() or quality not in ('Grade A', 'Grade B', 'Mixed'):
        flash('Complete valid produce details.', 'error')
        return redirect(url_for('dashboard'))
    try:
        filename=save_produce_photo(request.files.get('photo'))
    except ValueError as e:
        flash(str(e),'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    try:
        with db:
            db.execute('''INSERT INTO produce_listings
                (farmer_id, crop, quantity_kg, available_kg, harvest_date, quality, asking_price, available_until, photo_filename)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (current_user.profile_id, crop, qty, qty, harvested, quality, asking, expiry, filename))
    finally:
        db.close()
    flash('Your produce was listed.', 'success')
    return redirect(url_for('dashboard'))


@app.post('/produce/<int:listing_id>/asking-price')
@require_role('farmer')
def set_asking_price(listing_id):
    """Add/edit an asking price; existing offers keep their original snapshot."""
    price = positive_number(request.form.get('asking_price'))
    if price is None or price > 1_000_000:
        flash('Enter a valid asking price per kg.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        listing = db.execute('SELECT id FROM produce_listings WHERE id=? AND farmer_id=?',
                             (listing_id, current_user.profile_id)).fetchone()
        if not listing:
            db.rollback()
            abort(404)
        pending = db.execute("SELECT COUNT(*) FROM pool_contributions WHERE listing_id=? AND offer_status='Pending'",
                             (listing_id,)).fetchone()[0]
        if pending:
            db.rollback()
            flash('Resolve pending offers before changing this listing price.', 'error')
            return redirect(url_for('dashboard'))
        db.execute('UPDATE produce_listings SET asking_price=? WHERE id=? AND farmer_id=?',
                   (price, listing_id, current_user.profile_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash('Your asking price was updated for future offers.', 'success')
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
        if db.execute('SELECT 1 FROM demo_orders WHERE demand_id=?', (demand_id,)).fetchone():
            db.rollback()
            flash('This request is already in the demo order workflow.', 'error')
            return redirect(url_for('dashboard'))
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
                FROM produce_listings p JOIN farmers f ON f.id=p.farmer_id
                WHERE f.verification_status='Approved' AND LOWER(p.crop)=LOWER(?) AND p.available_kg > 0 AND p.harvest_date <= ?
                  AND p.asking_price IS NOT NULL AND p.asking_price <= ?
                  AND p.available_until >= date('now')
                ORDER BY p.asking_price ASC, p.harvest_date ASC, p.id ASC''',
                (demand['crop'], demand['deadline'], demand['target_price'])).fetchall()
            for listing in listings:
                if remaining <= 0.00001:
                    break
                offerable = max(0, listing['available_kg']-listing['pending_kg'])
                amount = round(min(offerable, remaining), 4)
                if amount <= 0:
                    continue
                db.execute('''INSERT INTO pool_contributions
                    (pool_id, listing_id, farmer_id, quantity_kg, indicative_price, farmer_asking_price, offer_status)
                    VALUES (?, ?, ?, ?, ?, ?, 'Pending')''',
                    (pool_id, listing['id'], listing['farmer_id'], amount, demand['target_price'], listing['asking_price']))
                created += 1
                remaining -= amount
        status = recalculate_pool(db, pool_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash(f'{created} price-compatible farmer offer(s) proposed. Status: {status}. No stock has been deducted. '
          'Farmers must accept before supply is allocated.', 'success')
    return redirect(url_for('dashboard'))


@app.post('/offers/<int:contribution_id>/<decision>')
@require_role('farmer')
def respond_to_offer(contribution_id, decision):
    if decision not in ('accept', 'reject'):
        abort(404)
    transport = nonnegative_money(request.form.get('transport_cost')) if decision == 'accept' else 0
    packaging = nonnegative_money(request.form.get('packaging_cost')) if decision == 'accept' else 0
    if transport is None or packaging is None:
        flash('Enter valid non-negative estimated costs.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        offer = db.execute('''SELECT pc.*, p.available_kg, p.available_until, f.verification_status
            FROM pool_contributions pc
            JOIN produce_listings p ON p.id=pc.listing_id
            JOIN farmers f ON f.id=p.farmer_id
            WHERE pc.id=? AND pc.farmer_id=? AND p.farmer_id=?''',
            (contribution_id, current_user.profile_id, current_user.profile_id)).fetchone()
        if not offer:
            db.rollback()
            abort(404)
        linked_order = db.execute('''SELECT 1 FROM demo_orders o JOIN harvest_pools hp
            ON hp.demand_id=o.demand_id WHERE hp.id=?''', (offer['pool_id'],)).fetchone()
        if linked_order:
            db.rollback()
            flash('This pool is already part of a demo order.', 'error')
            return redirect(url_for('dashboard'))
        if offer['offer_status'] != 'Pending':
            db.rollback()
            flash('This offer has already been handled or belongs to an older test pool.', 'error')
            return redirect(url_for('dashboard'))
        if decision == 'accept':
            if offer['verification_status'] != 'Approved':
                db.rollback()
                flash('Seller review approval is required before accepting a new offer.', 'error')
                return redirect(url_for('dashboard'))
            if offer['available_until'] and offer['available_until'] < date.today().isoformat():
                db.rollback()
                flash('This produce listing is no longer available. Reject the offer instead.', 'error')
                return redirect(url_for('dashboard'))
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
        db.execute('''UPDATE pool_contributions
            SET offer_status=?, transport_cost=?, packaging_cost=? WHERE id=?''',
            (new_status, transport if new_status == 'Accepted' else None,
             packaging if new_status == 'Accepted' else None, contribution_id))
        recalculate_pool(db, offer['pool_id'])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash(f'Offer {new_status.lower()}. Buyer request status updated.', 'success')
    return redirect(url_for('dashboard'))




def money_cents(value):
    """Round a non-negative rand amount to whole cents, half up."""
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError('Invalid non-negative amount')
    return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def allocate_buyer_total(rows, total_cents):
    """Deterministic largest-remainder allocation, so shares total exactly.

    Rows are accepted farmer contributions. Their buyer-facing shares are based
    on contributed quantity, not on the farmer's asking price or estimated costs.
    This is an indicative gross allocation only, NOT a payment or payout.
    """
    if not rows or total_cents <= 0:
        raise ValueError('Accepted quantities and positive order total required')
    weights = [Decimal(str(x['quantity_kg'])) for x in rows]
    if any(not x.is_finite() or x <= 0 for x in weights):
        raise ValueError('Invalid accepted quantity')
    total_kg = sum(weights)
    exact = [Decimal(total_cents) * weight / total_kg for weight in weights]
    cents = [int(x.to_integral_value(rounding=ROUND_DOWN)) for x in exact]
    missing = total_cents - sum(cents)
    order = sorted(range(len(rows)), key=lambda i: (-(exact[i]-cents[i]), rows[i]['id']))
    for i in order[:missing]:
        cents[i] += 1
    assert sum(cents) == total_cents
    return cents


def snapshot_order_allocations(db, order_id, demand_id, total_cents):
    rows = db.execute("""SELECT pc.id, pc.farmer_id, pc.quantity_kg,
           pc.farmer_asking_price
        FROM pool_contributions pc
        JOIN harvest_pools hp ON hp.id=pc.pool_id
        WHERE hp.demand_id=? AND pc.offer_status='Accepted'
        ORDER BY pc.id""", (demand_id,)).fetchall()
    amounts = allocate_buyer_total(rows, total_cents)
    demand = db.execute('SELECT target_price FROM buyer_demands WHERE id=?', (demand_id,)).fetchone()
    buyer_cents = money_cents(demand['target_price'])
    for r, amount in zip(rows, amounts):
        asking = (money_cents(r['farmer_asking_price'])
                  if r['farmer_asking_price'] is not None else None)
        db.execute("""INSERT INTO order_farmer_allocations
            (order_id,contribution_id,farmer_id,quantity_kg,buyer_unit_price_cents,gross_cents,farmer_asking_price_cents)
            VALUES(?,?,?,?,?,?,?)""",
            (order_id,r['id'],r['farmer_id'],str(r['quantity_kg']),buyer_cents,amount,asking))
    if sum(amounts) != total_cents:
        raise ValueError('Order total does not reconcile')


# PHASE 6: Simulated orders. Never take payment details or represent a demo
# status as verified payment, delivery, escrow, or farmer payout.
@app.post('/demo-orders/create/<int:demand_id>')
@require_role('buyer')
def create_demo_order(demand_id):
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        demand = db.execute('''SELECT * FROM buyer_demands
            WHERE id=? AND buyer_id=?''', (demand_id, current_user.profile_id)).fetchone()
        if demand is None:
            db.rollback()
            abort(404)
        if db.execute('SELECT 1 FROM demo_orders WHERE demand_id=?', (demand_id,)).fetchone():
            db.rollback()
            flash('A demo order already exists for this request.', 'error')
            return redirect(url_for('dashboard'))
        pool = db.execute('SELECT * FROM harvest_pools WHERE demand_id=?', (demand_id,)).fetchone()
        if pool is None:
            db.rollback()
            flash('Match supply and get farmer approvals first.', 'error')
            return redirect(url_for('dashboard'))
        rows = db.execute('''SELECT offer_status, quantity_kg FROM pool_contributions
            WHERE pool_id=?''', (pool['id'],)).fetchall()
        if (not rows or any(x['offer_status'] in ('Pending', 'Legacy reservation') for x in rows)
                or sum(x['quantity_kg'] for x in rows if x['offer_status']=='Accepted')
                    < demand['quantity_kg'] - 0.00001):
            db.rollback()
            flash('A demo order requires full accepted supply and no pending or legacy reservations.', 'error')
            return redirect(url_for('dashboard'))
        from decimal import Decimal, ROUND_HALF_UP
        total = (Decimal(str(demand['quantity_kg'])) * Decimal(str(demand['target_price'])) * 100)
        cents = int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        cursor = db.execute('''INSERT INTO demo_orders(demand_id,buyer_id,total_kg,indicative_total_cents)
            VALUES (?,?,?,?)''', (demand_id, current_user.profile_id, demand['quantity_kg'], cents))
        snapshot_order_allocations(db, cursor.lastrowid, demand_id, cents)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash('Demo order created. This is an estimate, not an invoice or payment request.', 'success')
    return redirect(url_for('dashboard'))


@app.get('/orders/<int:order_id>/allocations')
@login_required
def order_allocations_detail(order_id):
    db = get_db()
    try:
        order = db.execute("""SELECT o.*, d.crop, d.delivery_location, b.business_name
            FROM demo_orders o
            JOIN buyer_demands d ON d.id=o.demand_id
            JOIN buyers b ON b.id=o.buyer_id WHERE o.id=?""", (order_id,)).fetchone()
        if order is None:
            abort(404)
        if current_user.role == 'buyer' and current_user.profile_id != order['buyer_id']:
            abort(404)
        if current_user.role == 'farmer':
            entitled = db.execute("""SELECT 1 FROM order_farmer_allocations
                WHERE order_id=? AND farmer_id=?""", (order_id,current_user.profile_id)).fetchone()
            if not entitled:
                abort(404)
        elif current_user.role not in ('buyer','admin'):
            abort(403)
        # Farmers see ONLY their own breakdown; buyers/admin see all allocations.
        if current_user.role == 'farmer':
            rows = db.execute("""SELECT a.*, f.name AS farmer_name, pc.offer_status
                FROM order_farmer_allocations a JOIN farmers f ON f.id=a.farmer_id
                JOIN pool_contributions pc ON pc.id=a.contribution_id
                WHERE a.order_id=? AND a.farmer_id=? ORDER BY a.id""",
                (order_id, current_user.profile_id)).fetchall()
        else:
            rows = db.execute("""SELECT a.*, f.name AS farmer_name, pc.offer_status
                FROM order_farmer_allocations a JOIN farmers f ON f.id=a.farmer_id
                JOIN pool_contributions pc ON pc.id=a.contribution_id
                WHERE a.order_id=? ORDER BY a.id""", (order_id,)).fetchall()
        full_sum = db.execute('SELECT COALESCE(SUM(gross_cents),0) FROM order_farmer_allocations WHERE order_id=?',
                              (order_id,)).fetchone()[0]
        return render_template('order_allocations.html', order=order, allocations=rows,
                               allocated_total_cents=full_sum,
                               reconciled=bool(rows) and full_sum==order['indicative_total_cents'],
                               viewing_farmer=current_user.role=='farmer')
    finally:
        db.close()


@app.post('/demo-orders/<int:order_id>/mark-paid')
@require_role('buyer')
def demo_mark_paid(order_id):
    db = get_db()
    try:
        with db:
            changed = db.execute('''UPDATE demo_orders SET status='Demo payment marked',
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND buyer_id=?
                AND status='Awaiting demo payment' ''',
                (order_id, current_user.profile_id)).rowcount
    finally:
        db.close()
    flash('Simulated payment recorded (no money moved).' if changed else 'This demo order cannot be marked paid.',
          'success' if changed else 'error')
    return redirect(url_for('dashboard'))


@app.post('/demo-orders/<int:order_id>/ready/<int:contribution_id>')
@require_role('farmer')
def demo_mark_ready(order_id, contribution_id):
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        order = db.execute('''SELECT o.* FROM demo_orders o WHERE o.id=?''', (order_id,)).fetchone()
        if not order:
            db.rollback()
            abort(404)
        row = db.execute('''SELECT pc.id FROM pool_contributions pc
            JOIN harvest_pools hp ON hp.id=pc.pool_id
            WHERE pc.id=? AND pc.farmer_id=? AND pc.offer_status='Accepted'
            AND hp.demand_id=?''', (contribution_id, current_user.profile_id,
                                 order['demand_id'])).fetchone()
        if not row:
            db.rollback()
            abort(404)
        if order['status'] not in ('Demo payment marked','Ready for demo delivery'):
            db.rollback()
            flash('The buyer must mark demo payment before produce can be marked ready.', 'error')
            return redirect(url_for('dashboard'))
        db.execute('UPDATE pool_contributions SET demo_ready=1 WHERE id=?', (contribution_id,))
        counts = db.execute('''SELECT COUNT(*) AS total,
            SUM(CASE WHEN pc.demo_ready=1 THEN 1 ELSE 0 END) AS ready
            FROM pool_contributions pc JOIN harvest_pools hp ON hp.id=pc.pool_id
            WHERE hp.demand_id=? AND pc.offer_status='Accepted' ''',
            (order['demand_id'],)).fetchone()
        if counts['total'] > 0 and counts['total'] == counts['ready']:
            db.execute('''UPDATE demo_orders SET status='Ready for demo delivery',
                updated_at=CURRENT_TIMESTAMP WHERE id=?''', (order_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash('Your contribution was marked ready (simulation only).', 'success')
    return redirect(url_for('dashboard'))


@app.post('/demo-orders/<int:order_id>/confirm-delivery')
@require_role('buyer')
def demo_confirm_delivery(order_id):
    db = get_db()
    try:
        with db:
            changed = db.execute('''UPDATE demo_orders SET status='Demo delivery confirmed',
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND buyer_id=?
                AND status='Ready for demo delivery' ''',
                (order_id, current_user.profile_id)).rowcount
    finally:
        db.close()
    flash('Delivery marked complete in the demo (not independently verified).' if changed
          else 'All farmer contributions must be marked ready first.',
          'success' if changed else 'error')
    return redirect(url_for('dashboard'))

# Old routes were insecure: they cannot create unowned standalone profiles anymore.
@app.post('/farmers/add')
@app.post('/buyers/add')
@login_required
def disabled_legacy_registration():
    abort(403)



# -----------------------------
# Seller review (not a substitute for legal KYC or onsite produce inspection)
# -----------------------------
@app.cli.command('create-admin')
def create_admin():
    # Create an admin account locally; no public administrator registration.
    email = click.prompt('Administrator email').strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise click.ClickException('Please enter a valid email address.')
    password = click.prompt('Administrator password (minimum 12 characters)', hide_input=True,
                            confirmation_prompt=True)
    if len(password) < 12:
        raise click.ClickException('Password must have at least 12 characters.')
    db = get_db()
    try:
        with db:
            db.execute('INSERT INTO admin_accounts(email,password_hash) VALUES (?,?)',
                       (email, generate_password_hash(password)))
    except sqlite3.IntegrityError:
        raise click.ClickException('Administrator email already exists.')
    finally:
        db.close()
    click.echo('Administrator account created.')


@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard' if current_user.role=='admin' else 'dashboard'))
    if request.method == 'GET':
        return render_template('admin_login.html')
    email = request.form.get('email','').strip().lower()
    password = request.form.get('password','')
    db = get_db()
    try:
        row = db.execute('SELECT * FROM admin_accounts WHERE email=? AND is_active=1',
                         (email,)).fetchone()
    finally:
        db.close()
    if not row or not check_password_hash(row['password_hash'], password):
        flash('Incorrect email or password.','error')
        return render_template('admin_login.html'),401
    login_user(AdminUser(row), remember=False, fresh=True)
    return redirect(url_for('admin_dashboard'))


@app.get('/admin')
@require_role('admin')
def admin_dashboard():
    db = get_db()
    try:
        farmers = db.execute('''SELECT f.id,f.name,f.phone,f.village,f.verification_status,
          f.verified_at,COUNT(p.id) AS listing_count
          FROM farmers f LEFT JOIN produce_listings p ON p.farmer_id=f.id
          GROUP BY f.id ORDER BY CASE f.verification_status
              WHEN 'Pending' THEN 0 WHEN 'Suspended' THEN 1 ELSE 2 END,f.id DESC''').fetchall()
        events = db.execute('''SELECT e.*,f.name AS farmer_name,a.email AS admin_email
          FROM seller_review_events e JOIN farmers f ON f.id=e.farmer_id
          JOIN admin_accounts a ON a.id=e.admin_id ORDER BY e.id DESC LIMIT 40''').fetchall()
    finally:
        db.close()
    return render_template('admin_dashboard.html',farmers=farmers,events=events)


@app.post('/admin/sellers/<int:farmer_id>/review')
@require_role('admin')
@limiter.limit('30 per hour')
def admin_review_seller(farmer_id):
    status = request.form.get('decision','')
    note = request.form.get('note','').strip()
    if status not in ('Approved','Rejected','Suspended','Pending') or not (10<=len(note)<=500):
        flash('Choose a valid decision and enter a review note (10–500 characters).','error')
        return redirect(url_for('admin_dashboard'))
    if status=='Approved' and request.form.get('attest')!='yes':
        flash('Before approval, confirm you personally completed the required checks.','error')
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        farmer = db.execute('SELECT verification_status FROM farmers WHERE id=?',
                            (farmer_id,)).fetchone()
        if not farmer:
            db.rollback()
            abort(404)
        db.execute('''UPDATE farmers SET verification_status=?,
          verified_at=CASE WHEN ?='Approved' THEN CURRENT_TIMESTAMP ELSE NULL END
          WHERE id=?''',(status,status,farmer_id))
        db.execute('''INSERT INTO seller_review_events
          (farmer_id,admin_id,previous_status,new_status,review_note)
          VALUES (?,?,?,?,?)''',(farmer_id,current_user.db_id,farmer['verification_status'],status,note))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    flash('Seller review status updated.','success')
    return redirect(url_for('admin_dashboard'))


init_db()

if __name__ == '__main__':
    app.run(debug=False)
