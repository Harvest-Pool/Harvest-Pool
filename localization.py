"""Server-side interface locale and UTF-8 message catalogs."""
import json
from contextlib import closing
from decimal import Decimal
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort, g, redirect, render_template, request, session, url_for
from flask_login import current_user

LANGUAGES = {
    "en-ZA": "English", "zu-ZA": "isiZulu", "xh-ZA": "isiXhosa",
    "af-ZA": "Afrikaans", "nso-ZA": "Sepedi", "st-ZA": "Sesotho", "tn-ZA": "Setswana",
    "ts-ZA": "itsonga", "ss-ZA": "siSwati", "ve-ZA": "Tshivenḓa", "nr-ZA": "isiNdebele",
}
PREVIEW = {"zu-ZA", "ve-ZA"}
DEFAULT = "en-ZA"


def migrate_locales(db):
    for table in ("users", "admin_accounts"):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if "preferred_locale" not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN preferred_locale TEXT")


def locale():
    if "ui_locale" not in g:
        preferred = getattr(current_user, "preferred_locale", None) or session.get("ui_locale")
        g.ui_locale = preferred if preferred in LANGUAGES else DEFAULT
    return g.ui_locale


@cache
def catalog(code):
    if code not in PREVIEW:
        return {}
    path = Path(__file__).with_name("locales") / f"{code}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def translate(message):
    return catalog(locale()).get(message, message)


def money_zar(cents):
    text = f"{Decimal(cents) / 100:,.2f}".replace(",", "\u00a0")
    return "R" + (text.replace(".", ",") if locale() == "af-ZA" else text)


def register_localization(app, get_db):
    @app.context_processor
    def localized_context():
        return {"ui_locale": locale(), "ui_languages": LANGUAGES, "ui_previews": PREVIEW,
                "_": translate, "zar_cents": money_zar}

    @app.post("/language")
    def change_language():
        chosen = request.form.get("locale")
        if chosen not in LANGUAGES:
            abort(400)
        session["ui_locale"] = chosen
        if current_user.is_authenticated:
            admin = current_user.role == "admin"
            with closing(get_db()) as db, db:
                table = "admin_accounts" if admin else "users"
                key = current_user.db_id if admin else current_user.id
                db.execute(f"UPDATE {table} SET preferred_locale=? WHERE id=?", (chosen, key))
        target = request.form.get("return_to", "")
        valid = (target.startswith("/") and not target.startswith("//") and len(target) < 2048
                 and "\\" not in target and all(32 <= ord(ch) != 127 for ch in target))
        if valid:
            parts = urlsplit(target)
            valid = not parts.scheme and not parts.netloc
        if not valid:
            target = url_for("home")
        return redirect(target, code=303)

    @app.get("/accessibility")
    def accessibility():
        return render_template("accessibility.html")
