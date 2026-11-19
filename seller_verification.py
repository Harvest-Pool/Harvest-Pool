"""Private, human-reviewed seller and listing evidence."""
import io
import json
import re
import secrets
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import click
from cryptography.fernet import Fernet, InvalidToken
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_fresh
from PIL import Image, ImageOps, UnidentifiedImageError

DIMENSIONS = {"identity": "Identity", "supply": "Farming and supply", "batch": "Listing or batch"}
DECISIONS = {"More Evidence Required", "Approved", "Rejected", "Suspended"}
POTATO_CLASSES = ("Class 1", "Class 2", "Class 3", "Lowest Class")
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 8_000_000
BASIS = {
    "contract": "Steps to assess and establish the seller relationship (POPIA section 11(1)(b)).",
    "legitimate_interest": "Protection of legitimate marketplace interests (POPIA section 11(1)(f)).",
}


def today():
    # South Africa uses UTC+02:00 year-round. Avoid Windows tzdata dependency.
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=2))).date()


def migrate_verification(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(farmers)")}
    if "kyc_enrolled" not in columns:
        db.execute("ALTER TABLE farmers ADD COLUMN kyc_enrolled INTEGER NOT NULL DEFAULT 0")
    statements = (
        """CREATE TABLE IF NOT EXISTS kyc_cases (
            id INTEGER PRIMARY KEY, farmer_id INTEGER NOT NULL REFERENCES farmers(id),
            listing_id INTEGER REFERENCES produce_listings(id),
            dimension TEXT NOT NULL CHECK(dimension IN ('identity','supply','batch')),
            account_name TEXT NOT NULL, account_village TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN
               ('Pending','More Evidence Required','Approved','Rejected','Suspended')),
            expires_on TEXT, stock_verified INTEGER NOT NULL DEFAULT 0,
            grade_verified TEXT, feedback TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK((dimension='batch')=(listing_id IS NOT NULL)))""",
        """CREATE INDEX IF NOT EXISTS kyc_case_scope ON kyc_cases(farmer_id,dimension,listing_id,id)""",
        """CREATE TABLE IF NOT EXISTS kyc_vault (
            case_id INTEGER PRIMARY KEY REFERENCES kyc_cases(id),
            token TEXT NOT NULL UNIQUE, image_count INTEGER NOT NULL,
            retain_until TEXT NOT NULL, purged_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS kyc_events (
            id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES kyc_cases(id),
            farmer_id INTEGER NOT NULL REFERENCES farmers(id), admin_id INTEGER REFERENCES admin_accounts(id),
            action TEXT NOT NULL, reason TEXT NOT NULL, occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TRIGGER IF NOT EXISTS kyc_events_block_update BEFORE UPDATE ON kyc_events
            BEGIN SELECT RAISE(ABORT, 'Verification audit is append only'); END""",
        """CREATE TRIGGER IF NOT EXISTS kyc_events_block_delete BEFORE DELETE ON kyc_events
            BEGIN SELECT RAISE(ABORT, 'Verification audit is append only'); END""",
        """CREATE TABLE IF NOT EXISTS kyc_privacy_requests (
            id INTEGER PRIMARY KEY, farmer_id INTEGER NOT NULL REFERENCES farmers(id),
            kind TEXT NOT NULL CHECK(kind IN ('access','correction','deletion','objection')),
            status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Resolved')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT)""",
        """CREATE VIEW IF NOT EXISTS kyc_current AS
            SELECT c.* FROM kyc_cases c WHERE c.id=(
                SELECT MAX(x.id) FROM kyc_cases x WHERE x.farmer_id=c.farmer_id
                AND x.dimension=c.dimension AND x.listing_id IS c.listing_id)""",
        """CREATE VIEW IF NOT EXISTS kyc_valid AS
            SELECT c.* FROM kyc_current c JOIN farmers f ON f.id=c.farmer_id
            WHERE c.status='Approved' AND c.expires_on>=date('now','+2 hours')
            AND c.account_name=f.name AND c.account_village=f.village""",
        """CREATE VIEW IF NOT EXISTS seller_eligibility AS
            WITH checks AS (
                SELECT f.id, f.verification_status, f.kyc_enrolled,
                    (SELECT COUNT(*) FROM kyc_valid c WHERE c.farmer_id=f.id
                      AND c.dimension IN ('identity','supply'))=2 AS checked
                FROM farmers f
            )
            SELECT id AS farmer_id, (verification_status='Approved' AND (kyc_enrolled=0 OR checked)) AS eligible,
                   (verification_status='Approved' AND kyc_enrolled=1 AND checked) AS verified
            FROM checks""",
    )
    for statement in statements:
        db.execute(statement)


def event(db, farmer_id, action, reason, case_id=None, admin_id=None):
    db.execute("INSERT INTO kyc_events(case_id,farmer_id,admin_id,action,reason) VALUES (?,?,?,?,?)",
               (case_id, farmer_id, admin_id, action, reason))


def display_state(row, farmer):
    if row["status"] == "Approved" and (row["expires_on"] < today().isoformat()
                                        or row["account_name"] != farmer["name"]
                                        or row["account_village"] != farmer["village"]):
        return "Expired"
    return row["status"]


def clean_image(upload):
    raw = upload.stream.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Each evidence image must be 2 MB or smaller.")
    try:
        with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG")) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Upload a still image with at most 8 megapixels.")
            image.load()
            # Re-encode pixels and strip metadata and appended data.
            pixels = ImageOps.exif_transpose(image).convert("RGB")
            pixels.info.clear()
            output = io.BytesIO()
            pixels.save(output, format="JPEG", quality=84)
            if output.tell() > MAX_IMAGE_BYTES:
                raise ValueError("The processed image exceeds 2 MB.")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise ValueError("Upload a valid JPEG or PNG evidence image.") from exc


def vault(app):
    raw = app.config.get("KYC_PRIVATE_DIR")
    secret = app.config.get("KYC_ENCRYPTION_KEY")
    if not raw or not secret:
        raise ValueError
    path = Path(raw)
    directory = path.resolve()
    public = (Path(app.root_path).resolve(), Path(app.static_folder).resolve(),
              Path(app.config["KYC_PUBLIC_MEDIA"]).resolve())
    if not path.is_absolute() or not directory.is_dir() or any(directory == root or root in directory.parents for root in public):
        raise ValueError
    return directory, Fernet(secret)


def enabled(app):
    try:
        vault(app)
    except (ValueError, OSError, TypeError):
        return False
    return bool(app.config.get("KYC_PRIVACY_CONTACT") and app.config.get("KYC_CONTROLLER")
                and app.config.get("KYC_BASIS") in BASIS
                and (request.is_secure or app.testing))


def sealed_path(directory, token):
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError
    return directory / (token + ".sealed")


def load_packet(app, entry):
    from base64 import b64decode
    directory, box = vault(app)
    try:
        packet = json.loads(box.decrypt(sealed_path(directory, entry["token"]).read_bytes()))
        return packet["details"], [b64decode(image, validate=True) for image in packet["images"]]
    except (InvalidToken, OSError, ValueError, KeyError) as exc:
        raise LookupError from exc


def submission_fields(dimension, uploads):
    from financial_model import number
    fields = {}
    names = {
        "identity": ("route", "document_type"),
        "supply": ("location", "relationship", "photo_date", "quantity", "harvest_date",
                   "supporting_record"),
        "batch": ("batch", "declaration", "issuer", "reference", "certificate_date"),
    }
    for key in names[dimension]:
        fields[key] = request.form.get(key, "").strip()
        if len(fields[key]) > 180:
            raise ValueError("Keep evidence details within 180 characters per field.")
    if dimension == "identity":
        if fields["route"] == "assisted":
            if uploads:
                raise ValueError("The assisted identity route does not need a document upload.")
        elif (fields["route"] != "document" or fields["document_type"] not in
              {"sa-id", "passport", "certified-sa-id", "certified-passport"} or not uploads):
            raise ValueError("Choose an identity evidence route and attach an image when required.")
    if dimension == "supply":
        if not fields["location"] or fields["relationship"] not in {"owner","lease","communal","permission","cooperative","supplier"} or not uploads:
            raise ValueError("Supply evidence requires location, relationship and a dated photo.")
        try:
            pictured = date.fromisoformat(fields["photo_date"])
            date.fromisoformat(fields["harvest_date"])
            if not today() - timedelta(days=90) <= pictured <= today() or not number(fields["quantity"],"1000000"):
                raise ValueError
        except ValueError as exc:
            raise ValueError("Enter a recent photo date, harvest date and positive quantity.") from exc
    if dimension == "batch":
        if not fields["batch"] or not fields["declaration"] or not uploads:
            raise ValueError("Batch evidence requires a batch reference, seller declaration and supporting image.")
        if fields["certificate_date"]:
            try:
                date.fromisoformat(fields["certificate_date"])
            except ValueError as exc:
                raise ValueError("Enter a valid certificate expiry date.") from exc
    return fields


def register_verification(app, get_db, require_role, limiter):
    def reviewer():
        allowlist = app.config.get("KYC_REVIEWERS", ())
        if not login_fresh() or current_user.email.casefold() not in allowlist:
            abort(403)

    def safe_response(response):
        response.headers.update({"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Cross-Origin-Resource-Policy": "same-origin"})
        return response

    @app.after_request
    def private_headers(response):
        if request.endpoint in {"seller_verification", "submit_kyc", "kyc_image", "admin_kyc",
                                 "admin_kyc_case", "kyc_decide", "kyc_privacy", "resolve_kyc_privacy"}:
            safe_response(response)
        return response

    @app.get("/verification")
    @require_role("farmer")
    def seller_verification():
        with closing(get_db()) as db:
            farmer = db.execute("SELECT * FROM farmers WHERE id=?", (current_user.profile_id,)).fetchone()
            cases = db.execute("""SELECT c.*,p.crop,v.image_count,v.retain_until,v.purged_at
                FROM kyc_cases c LEFT JOIN produce_listings p ON p.id=c.listing_id
                LEFT JOIN kyc_vault v ON v.case_id=c.id WHERE c.farmer_id=? ORDER BY c.id DESC LIMIT 60""",
                               (farmer["id"],)).fetchall()
            listings = db.execute("SELECT id,crop FROM produce_listings WHERE farmer_id=? ORDER BY id DESC",
                                  (farmer["id"],)).fetchall()
            current = db.execute("SELECT * FROM kyc_current WHERE farmer_id=? AND listing_id IS NULL",
                                 (farmer["id"],)).fetchall()
            privacy = db.execute("SELECT * FROM kyc_privacy_requests WHERE farmer_id=? ORDER BY id DESC LIMIT 20",
                                 (farmer["id"],)).fetchall()
            flags = db.execute("SELECT * FROM seller_eligibility WHERE farmer_id=?", (farmer["id"],)).fetchone()
        return render_template("verification.html", farmer=farmer, cases=cases, listings=listings, flags=flags,
                               case_states={row["id"]: display_state(row, farmer) for row in cases},
                               states={row["dimension"]: display_state(row, farmer) for row in current},
                               dimensions=DIMENSIONS, enabled=enabled(app), privacy=privacy,
                               basis=BASIS.get(app.config.get("KYC_BASIS")), controller=app.config.get("KYC_CONTROLLER"),
                               privacy_contact=app.config.get("KYC_PRIVACY_CONTACT"))

    @app.post("/verification/<dimension>")
    @require_role("farmer")
    @limiter.limit("8 per day")
    def submit_kyc(dimension):
        from base64 import b64encode
        if not login_fresh():
            abort(403)
        if not enabled(app):
            abort(503)
        if dimension not in DIMENSIONS:
            abort(404)
        if request.form.get("privacy_notice") != "read":
            flash("Read the verification privacy notice before submitting.", "error")
            return redirect(url_for("seller_verification"))
        uploads = [item for item in request.files.getlist("evidence") if item.filename]
        listing_id = request.form.get("listing_id", type=int) if dimension == "batch" else None
        if dimension == "batch" and (listing_id is None or not 1 <= listing_id < 2**63):
            abort(400)
        with closing(get_db()) as db:
            if listing_id and not db.execute("SELECT 1 FROM produce_listings WHERE id=? AND farmer_id=?",
                                             (listing_id,current_user.profile_id)).fetchone():
                abort(404)
        try:
            if len(uploads) > 2:
                raise ValueError("Upload at most two evidence images per submission.")
            fields = submission_fields(dimension, uploads)
            images = [b64encode(clean_image(item)).decode("ascii") for item in uploads]
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("seller_verification"))
        directory, box = vault(app)
        token = secrets.token_hex(32)
        path = sealed_path(directory, token)
        try:
            with closing(get_db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                farmer = db.execute("SELECT * FROM farmers WHERE id=?", (current_user.profile_id,)).fetchone()
                current = db.execute("""SELECT id,status FROM kyc_current WHERE farmer_id=?
                    AND dimension=? AND listing_id IS ?""", (farmer["id"],dimension,listing_id)).fetchone()
                if current and current["status"] == "Pending":
                    flash("This evidence is already awaiting review.", "error")
                    return redirect(url_for("seller_verification"))
                with path.open("xb") as file:
                    file.write(box.encrypt(json.dumps({"details": fields, "images": images}).encode()))
                case_id = db.execute("""INSERT INTO kyc_cases(farmer_id,listing_id,dimension,account_name,account_village)
                    VALUES (?,?,?,?,?)""", (farmer["id"],listing_id,dimension,farmer["name"],farmer["village"])).lastrowid
                db.execute("INSERT INTO kyc_vault(case_id,token,image_count,retain_until) VALUES (?,?,?,?)",
                           (case_id,token,len(images),(today()+timedelta(days=90)).isoformat()))
                event(db,farmer["id"],"submitted","Privacy notice acknowledged; evidence queued for manual review.",case_id)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            abort(503)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        flash("Evidence submitted for review.", "success")
        return redirect(url_for("seller_verification"))

    @app.get("/verification/evidence/<int:case_id>/<int:image_index>")
    @limiter.limit("60 per minute")
    def kyc_image(case_id, image_index):
        if not current_user.is_authenticated or not login_fresh():
            abort(404)
        if current_user.role == "admin":
            reviewer()
        elif current_user.role != "farmer":
            abort(404)
        if not enabled(app):
            abort(404)
        with closing(get_db()) as db, db:
            entry = db.execute("""SELECT c.farmer_id,v.* FROM kyc_vault v JOIN kyc_cases c ON c.id=v.case_id
                WHERE v.case_id=? AND v.purged_at IS NULL AND v.retain_until>=?""", (case_id,today().isoformat())).fetchone()
            if (not entry or image_index >= entry["image_count"]
                    or (current_user.role == "farmer" and entry["farmer_id"] != current_user.profile_id)):
                abort(404)
            try:
                _, images = load_packet(app, entry)
            except LookupError:
                abort(404)
            if current_user.role == "admin":
                event(db,entry["farmer_id"],"evidence_viewed","Authorised image access.",case_id,current_user.db_id)
        response = Response(images[image_index], mimetype="image/jpeg")
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; sandbox"
        return response

    @app.get("/admin/verification")
    @require_role("admin")
    def admin_kyc():
        reviewer()
        with closing(get_db()) as db:
            cases = db.execute("""SELECT c.*,f.name,p.crop FROM kyc_current c JOIN farmers f ON f.id=c.farmer_id
                LEFT JOIN produce_listings p ON p.id=c.listing_id
                ORDER BY (c.status='Pending') DESC,c.id DESC LIMIT 100""").fetchall()
            privacy = db.execute("""SELECT r.*,f.name FROM kyc_privacy_requests r JOIN farmers f ON f.id=r.farmer_id
                ORDER BY (r.status='Open') DESC,r.id DESC LIMIT 60""").fetchall()
        return render_template("admin_verification.html", cases=cases, privacy=privacy, dimensions=DIMENSIONS,
                               today=today().isoformat())

    @app.get("/admin/verification/<int:case_id>")
    @require_role("admin")
    def admin_kyc_case(case_id):
        reviewer()
        with closing(get_db()) as db, db:
            case = db.execute("""SELECT c.*,f.name AS current_name,f.village AS current_village,p.crop,
                    v.token,v.image_count,v.retain_until,v.purged_at,
                    EXISTS(SELECT 1 FROM kyc_current x WHERE x.id=c.id) AS is_current
                FROM kyc_cases c JOIN farmers f ON f.id=c.farmer_id LEFT JOIN produce_listings p ON p.id=c.listing_id
                LEFT JOIN kyc_vault v ON v.case_id=c.id WHERE c.id=?""", (case_id,)).fetchone()
            if not case:
                abort(404)
            details = None
            if enabled(app) and not case["purged_at"] and case["retain_until"] >= today().isoformat():
                try:
                    details, _ = load_packet(app,case)
                except LookupError:
                    pass
                else:
                    event(db,case["farmer_id"],"details_viewed","Authorised evidence details access.",case_id,current_user.db_id)
            revision = db.execute("SELECT COALESCE(MAX(id),0) FROM kyc_events WHERE case_id=? AND action IN "
                                  "('Approved','Rejected','More Evidence Required','Suspended')", (case_id,)).fetchone()[0]
            history = db.execute("""SELECT e.*,a.email FROM kyc_events e LEFT JOIN admin_accounts a ON a.id=e.admin_id
                WHERE e.farmer_id=? ORDER BY e.id DESC LIMIT 100""", (case["farmer_id"],)).fetchall()
        potatoes = (case["crop"] or "").casefold() in {"potato","potatoes"}
        return render_template("verification_case.html", case=case, details=details, history=history,
                               dimension=DIMENSIONS[case["dimension"]], classes=POTATO_CLASSES if potatoes else (),
                               decisions=sorted(DECISIONS), revision=revision, today=today().isoformat())

    @app.post("/admin/verification/<int:case_id>")
    @require_role("admin")
    @limiter.limit("40 per hour")
    def kyc_decide(case_id):
        reviewer()
        status = request.form.get("decision")
        note = request.form.get("reason", "").strip()
        if status not in DECISIONS or not 12 <= len(note) <= 500:
            abort(400)
        with closing(get_db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            case = db.execute("""SELECT c.*,f.name,f.village,f.verification_status,p.crop,v.*
                FROM kyc_current c JOIN farmers f ON f.id=c.farmer_id
                LEFT JOIN produce_listings p ON p.id=c.listing_id
                JOIN kyc_vault v ON v.case_id=c.id WHERE c.id=?""", (case_id,)).fetchone()
            if not case:
                abort(404)
            revision = db.execute("SELECT COALESCE(MAX(id),0) FROM kyc_events WHERE case_id=? AND action IN "
                                  "('Approved','Rejected','More Evidence Required','Suspended')", (case_id,)).fetchone()[0]
            if (request.form.get("revision", type=int) != revision
                    or (case["status"] != "Pending" and status not in {"Suspended","More Evidence Required"})):
                abort(409)
            expires = grade = None
            stock = 0
            if status == "Approved":
                if not enabled(app) or case["purged_at"] or case["retain_until"] < today().isoformat():
                    abort(409)
                try:
                    details, _ = load_packet(app,case)
                    deadline = date.fromisoformat(request.form.get("expires_on",""))
                except (ValueError, LookupError):
                    abort(400)
                if (not today() <= deadline <= today()+timedelta(days=365)
                        or case["account_name"] != case["name"] or case["account_village"] != case["village"]):
                    abort(400)
                expires = deadline.isoformat()
                if case["dimension"] in {"identity","supply"}:
                    if request.form.get("primary_check") != "yes" or request.form.get("independent_check") != "yes":
                        abort(400)
                else:
                    stock = int(request.form.get("stock_check") == "yes")
                    grade = request.form.get("grade") or None
                    if grade and ((case["crop"] or "").casefold() not in {"potato","potatoes"}
                                  or grade not in POTATO_CLASSES or request.form.get("grade_check") != "yes"
                                  or not details["issuer"] or not details["reference"]
                                  or not details["certificate_date"] or expires > details["certificate_date"]):
                        abort(400)
                    if not stock and not grade:
                        abort(400)
            db.execute("""UPDATE kyc_cases SET status=?,expires_on=?,stock_verified=?,grade_verified=?,feedback=? WHERE id=?""",
                       (status,expires,stock,grade,note,case_id))
            event(db,case["farmer_id"],status,note,case_id,current_user.db_id)
            if case["dimension"] != "batch" and status == "Approved":
                required = db.execute("""SELECT count(*) FROM kyc_valid WHERE farmer_id=?
                    AND dimension IN ('identity','supply')""", (case["farmer_id"],)).fetchone()[0]
                if required == 2 and case["verification_status"] != "Suspended":
                    db.execute("""UPDATE farmers SET verification_status='Approved',kyc_enrolled=1,
                        verified_at=CURRENT_TIMESTAMP WHERE id=?""", (case["farmer_id"],))
                    event(db,case["farmer_id"],"seller_checks_passed","Identity and supply checks are current.",
                          case_id,current_user.db_id)
            elif case["dimension"] != "batch" and status == "Suspended":
                db.execute("UPDATE farmers SET verification_status='Suspended',verified_at=NULL WHERE id=?",
                           (case["farmer_id"],))
        flash("Verification decision recorded.", "success")
        return redirect(url_for("admin_kyc_case",case_id=case_id))

    @app.post("/verification/privacy")
    @require_role("farmer")
    @limiter.limit("6 per day")
    def kyc_privacy():
        kind = request.form.get("kind")
        if kind not in {"access","correction","deletion","objection"}:
            abort(400)
        with closing(get_db()) as db, db:
            db.execute("INSERT INTO kyc_privacy_requests(farmer_id,kind) VALUES (?,?)",
                       (current_user.profile_id,kind))
            event(db,current_user.profile_id,"privacy_request","Privacy rights request submitted.")
        return redirect(url_for("seller_verification"))

    @app.post("/admin/verification/privacy/<int:request_id>")
    @require_role("admin")
    def resolve_kyc_privacy(request_id):
        reviewer()
        note = request.form.get("reason","").strip()
        if not 12 <= len(note) <= 500:
            abort(400)
        with closing(get_db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM kyc_privacy_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                abort(404)
            if row["status"] == "Open":
                db.execute("UPDATE kyc_privacy_requests SET status='Resolved',resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                           (request_id,))
                event(db,row["farmer_id"],"privacy_resolved",note,admin_id=current_user.db_id)
        return redirect(url_for("admin_kyc"))

    @app.cli.command("purge-verification-evidence")
    @click.option("--case-id", type=click.IntRange(min=1), help="Target a case after an authorised deletion decision.")
    @click.option("--apply", is_flag=True, help="Delete scoped encrypted evidence and keep audit metadata.")
    def purge_evidence(case_id, apply):
        try:
            directory, _ = vault(app)
        except (OSError, ValueError, TypeError) as exc:
            raise click.ClickException("Configure the encrypted evidence vault first.") from exc
        with closing(get_db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            scope, value = ("v.case_id=?", case_id) if case_id else ("v.retain_until<?", today().isoformat())
            rows = db.execute("""SELECT v.case_id,v.token,c.farmer_id FROM kyc_vault v JOIN kyc_cases c ON c.id=v.case_id
                WHERE v.purged_at IS NULL AND """ + scope, (value,)).fetchall()
            if apply:
                for row in rows:
                    sealed_path(directory,row["token"]).unlink(missing_ok=True)
                    db.execute("UPDATE kyc_vault SET purged_at=CURRENT_TIMESTAMP WHERE case_id=?", (row["case_id"],))
                    reason = "Authorised targeted deletion." if case_id else "Evidence retention window expired."
                    event(db,row["farmer_id"],"purged",reason,row["case_id"])
        click.echo(f"{len(rows)} evidence packets {'purged' if apply else 'eligible for purge'}.")
