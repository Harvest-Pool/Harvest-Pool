import io
import os
import re
import secrets
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash


class HarvestPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        settings = patch.dict(os.environ, {
            "HARVEST_ROTATED_SECRET_KEY": secrets.token_hex(32),
            "HARVEST_ROTATED_OPENAI_KEY": "",
            "HARVEST_ROTATED_PAYSTACK_TEST_KEY": "",
            "HARVEST_DATABASE": str(Path(cls.workspace.name) / "startup.db"),
            "HARVEST_UPLOAD_DIR": str(Path(cls.workspace.name) / "photos"),
            "COOKIE_SECURE": "false",
        })
        settings.start()
        cls.addClassCleanup(settings.stop)
        import app
        cls.module = app
        app.app.config["TESTING"] = True

    def setUp(self):
        self.module.DATABASE = str(Path(self.workspace.name) / (secrets.token_hex(8) + ".db"))
        self.module.init_db()
        self.module.limiter.reset()
        self.app = self.module.app
        self.password = secrets.token_urlsafe(18)
        self.expiry = (date.today() + timedelta(days=10)).isoformat()
        self.today = date.today().isoformat()
        with closing(self.module.get_db()) as db, db:
            db.execute("INSERT INTO admin_accounts(email,password_hash) VALUES (?,?)",
                       ("admin@demo.invalid", generate_password_hash(self.password)))
        self.admin = self.login("admin@demo.invalid", admin=True)

    def form(self, client, path, fields, token_path=None, **options):
        page = client.get(token_path or "/")
        token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data).group(1).decode()
        return client.post(path, data={"csrf_token": token, **fields}, **options)

    def login(self, email, admin=False, client=None):
        client = client or self.app.test_client()
        route = "/admin/login" if admin else "/login"
        result = self.form(client, route, dict(email=email, password=self.password))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.location, "/admin" if admin else "/dashboard")
        return client

    def account(self, role, index):
        client = self.app.test_client()
        email = f"{role}{index}@demo.invalid"
        response = self.form(client, "/register", {
            "role": role, "email": email, "password": self.password,
            "confirm_password": self.password, "name": f"Test {role} {index}",
            "phone": f"+27000000{index:03}", "place": "Vhembe", "business_name": "Test grocery",
        }, token_path="/register")
        self.assertEqual(response.location, "/login", response.get_data(as_text=True))
        row = self.row("SELECT password_hash,profile_id FROM users WHERE email=?", email)
        self.assertNotEqual(row["password_hash"], self.password)
        self.assertTrue(check_password_hash(row["password_hash"], self.password))
        return self.login(email, client=client), row["profile_id"]

    def listing(self, farmer, farmer_id, qty=650, crop="Potatoes", asking="15", photo=False):
        data = dict(quantity_kg=qty, crop=crop, asking_price=asking, quality="Grade A",
                    harvest_date=self.today, available_until=self.expiry)
        if photo:
            img = io.BytesIO()
            Image.new("RGB", (32, 32), "#a2693b").save(img, "PNG")
            img.seek(0)
            data["photo"] = (img, "harvest.png")
        self.assertEqual(self.form(farmer, "/produce/add", data).status_code, 302)
        return self.row("SELECT id FROM produce_listings WHERE farmer_id=? ORDER BY id DESC", farmer_id)[0]

    def row(self, query, *values):
        with closing(self.module.get_db()) as db:
            return db.execute(query, values).fetchone()

    def execute(self, query, *values):
        with closing(self.module.get_db()) as db, db:
            db.execute(query, values)

    def approve(self, farmer_id):
        route = f"/admin/sellers/{farmer_id}/review"
        self.form(self.admin, route, dict(decision="Approved", note="Synthetic fixture account"))
        self.assertEqual(self.row("SELECT verification_status FROM farmers WHERE id=?", farmer_id)[0], "Pending")
        self.form(self.admin, route, dict(decision="Approved", note="Synthetic fixture independently confirmed", attest="yes"))
        self.assertEqual(self.row("SELECT verification_status FROM farmers WHERE id=?", farmer_id)[0], "Approved")

    def test_seller_review_search_expiry_photo_auth_and_csrf(self):
        public = self.app.test_client()
        for url in ("/", "/login", "/admin/login", "/marketplace", "/packaging", "/api/discover"):
            self.assertEqual(public.get(url).status_code, 200)
        self.assertIn(b"Administrator sign in", public.get("/login").data.split(b"</title>")[1])
        self.assertEqual(public.post("/login").status_code, 400)
        farmer, farmer_id = self.account("farmer", 1)
        potato = self.listing(farmer, farmer_id, photo=True)
        cheap = self.listing(farmer, farmer_id, asking="12")
        carrot = self.listing(farmer, farmer_id, crop="Carrots")
        self.assertIn(b"Hidden from marketplace", farmer.get("/dashboard").data)
        self.assertEqual(public.get(f"/produce/{potato}").status_code, 404)
        self.assertEqual(public.get(f"/produce-photo/{potato}").status_code, 404)
        self.assertEqual(farmer.get(f"/produce/{potato}").status_code, 200)
        self.assertEqual(self.form(farmer, f"/admin/sellers/{farmer_id}/review", {}).status_code, 403)
        self.assertIn(b"0 public of 3", self.admin.get("/admin").data)
        self.approve(farmer_id)
        self.assertEqual(self.row("SELECT COUNT(*) FROM seller_review_events")[0], 1)
        html = public.get("/marketplace?q=Grade+A&crop=Potatoes&sort=price-asc").data
        self.assertLess(html.index(f"/produce/{cheap}".encode()), html.index(f"/produce/{potato}".encode()))
        self.assertNotIn(f"/produce/{carrot}".encode(), html)
        self.assertNotIn(f"/produce/{potato}".encode(), public.get("/marketplace?q=definitely%25missing").data)
        with public.get(f"/produce-photo/{potato}") as photo:
            self.assertEqual(photo.mimetype, "image/jpeg")
            self.assertTrue(photo.data.startswith(b"\xff\xd8"))
        self.execute("UPDATE produce_listings SET available_until='2000-01-01' WHERE id=?", potato)
        self.assertEqual(public.get(f"/produce/{potato}").status_code, 404)
        self.assertEqual(public.get(f"/produce-photo/{potato}").status_code, 404)
        self.assertNotIn(f"/produce/{potato}".encode(), public.get("/marketplace").data)
        self.form(farmer, "/logout", {})
        self.assertEqual(farmer.get("/dashboard").status_code, 302)

    def test_logout_returns_a_blank_uncached_sign_in_form(self):
        for client in (self.account("buyer", 1)[0], self.admin):
            result = self.form(client, "/logout", {})
            self.assertEqual(result.location, "/login")
            self.assertTrue(result.cache_control.no_store)
            for route in ("/login", "/admin/login"):
                page = client.get(route)
                self.assertTrue(page.cache_control.no_store)
                self.assertIn(b'autocomplete="off" data-sign-in', page.data)
                self.assertNotIn(b'autocomplete="current-password"', page.data)
                self.assertNotIn(b"@demo.invalid", page.data)
            self.assertEqual(client.get("/dashboard").status_code, 302)

    def test_designated_demo_approval_audit(self):
        _, farmer_id = self.account("farmer", 1)
        self.execute("UPDATE farmers SET demo_account=1 WHERE id=?", farmer_id)
        route = f"/admin/sellers/{farmer_id}/review"
        data = dict(decision="Approved", note="Designated synthetic demo seller", demo_attest="yes")
        with patch.dict(self.app.config, {"DEMO_MODE": False}):
            self.form(self.admin, route, data)
            self.assertEqual(self.row("SELECT COUNT(*) FROM seller_review_events")[0], 0)
        with patch.dict(self.app.config, {"DEMO_MODE": True}):
            self.assertIn(b"designated test account", self.admin.get("/admin").data)
            self.form(self.admin, route, data)
        self.assertTrue(self.row("SELECT review_note FROM seller_review_events")[0].startswith("DEMO ACCOUNT"))

    def test_two_farmer_consent_checkout_and_idempotent_test_reconciliation(self):
        first, first_id = self.account("farmer", 1)
        second, second_id = self.account("farmer", 2)
        buyer, buyer_id = self.account("buyer", 3)
        other, _ = self.account("buyer", 4)
        first_listing = self.listing(first, first_id, 650)
        second_listing = self.listing(second, second_id, 450)
        self.approve(first_id)
        self.approve(second_id)
        demand_data = dict(crop="Potatoes", quantity_kg=1000, target_price=15,
                           deadline=self.expiry, delivery_location="Test receiving dock")
        self.form(buyer, "/demands/add", demand_data)
        demand_id = self.row("SELECT id FROM buyer_demands WHERE buyer_id=?", buyer_id)[0]
        self.assertEqual(self.form(other, f"/match/{demand_id}", {}).status_code, 404)
        self.form(buyer, f"/match/{demand_id}", {})
        supply = self.row("SELECT SUM(quantity_kg), COUNT(*) FROM pool_contributions")
        self.assertEqual(tuple(supply), (1000, 2))
        self.assertEqual(self.row("SELECT available_kg FROM produce_listings WHERE id=?", first_listing)[0], 650)
        self.form(buyer, f"/demo-orders/create/{demand_id}", {})
        self.assertEqual(self.row("SELECT COUNT(*) FROM demo_orders")[0], 0)
        for client, farmer in ((first, first_id), (second, second_id)):
            offer = self.row("SELECT id FROM pool_contributions WHERE farmer_id=?", farmer)[0]
            costs = dict(transport_cost=0, packaging_cost=0)
            self.assertEqual(self.form(buyer, f"/offers/{offer}/accept", costs).status_code, 403)
            self.form(client, f"/offers/{offer}/accept", costs)
            self.form(client, f"/offers/{offer}/accept", costs)
        self.assertEqual(self.row("SELECT available_kg FROM produce_listings WHERE id=?", first_listing)[0], 0)
        self.assertEqual(self.row("SELECT available_kg FROM produce_listings WHERE id=?", second_listing)[0], 100)
        self.assertIn(b'<progress class="pool-progress"', buyer.get("/dashboard").data)
        self.form(buyer, f"/demo-orders/create/{demand_id}", {})
        order = self.row("SELECT * FROM demo_orders")
        order_id = order["id"]
        self.assertEqual(order["indicative_total_cents"], 1500000)
        self.assertEqual(self.row("SELECT SUM(gross_cents) FROM order_farmer_allocations")[0], 1500000)
        self.assertEqual(other.get(f"/orders/{order_id}/allocations").status_code, 404)
        self.assertEqual(self.form(other, f"/payments/paystack/test/{order_id}/start", {}).status_code, 404)
        self.assertEqual(first.get(f"/orders/{order_id}/allocations").status_code, 200)
        self.assertEqual(buyer.get(f"/orders/{order_id}/allocations").status_code, 200)

        def provider(method, endpoint, data=None):
            if method == "POST":
                self.assertEqual(data["amount"], "1500000")
                self.assertEqual(data["currency"], "ZAR")
                return {"reference": data["reference"], "authorization_url": "https://checkout.paystack.com/test-demo"}
            return verification

        with patch.dict(os.environ, {"HARVEST_ROTATED_PAYSTACK_TEST_KEY": "sk_test_fixture"}), \
                patch.object(self.module, "provider_request", side_effect=provider) as mocked:
            response = self.form(buyer, f"/payments/paystack/test/{order_id}/start", {})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(self.form(buyer, f"/payments/paystack/test/{order_id}/start", {}).status_code, 303)
            self.assertEqual(mocked.call_count, 1)
            reference = self.row("SELECT reference FROM paystack_test_payments")[0]
            verification = dict(reference=reference, amount=1500001, currency="ZAR", domain="test", status="success")
            self.assertEqual(self.module.verify_reference(reference, "test"), "review_required")
            verification["amount"] = 1500000
            callback = f"/payments/paystack/test/callback?reference={reference}"
            self.assertEqual(other.get(callback).status_code, 404)
            self.assertEqual(buyer.get(callback).status_code, 302)
            self.assertEqual(self.module.verify_reference(reference, "test"), "already_verified")
        sums = self.row("SELECT COUNT(*), SUM(gross_cents), SUM(platform_fee_cents) FROM test_settlement_allocations")
        self.assertEqual(tuple(sums), (2, 1500000, 0))
        self.assertEqual(self.row("SELECT COUNT(*) FROM paystack_test_events WHERE provider_status='success' AND event_type='verification'")[0], 1)

    def test_quote_scope_review_and_finance_rates(self):
        farmer, farmer_id = self.account("farmer", 1)
        another_farmer, _ = self.account("farmer", 2)
        buyer, _ = self.account("buyer", 3)
        listing = self.listing(farmer, farmer_id)
        payload = dict(listing_id=listing, quantity_kg=100, service="combined",
                       labelled_units=50, requirements="Print the demo grower logo on fifty bags", new_design="yes")
        self.assertEqual(self.form(another_farmer, "/packaging/request", payload).status_code, 404)
        self.assertEqual(self.form(buyer, "/packaging/request", payload).status_code, 403)
        self.form(farmer, "/packaging/request", payload | {"quantity_kg": 651})
        self.assertEqual(self.row("SELECT COUNT(*) FROM packaging_quotes")[0], 0)
        self.form(farmer, "/packaging/request", payload)
        quote = self.row("SELECT * FROM packaging_quotes")
        self.assertEqual(quote["estimate_cents"], 45000)
        self.assertEqual(self.row("SELECT available_kg FROM produce_listings WHERE id=?", listing)[0], 650)
        self.assertIn(b"R450.00", farmer.get("/packaging").data)
        self.assertNotIn(b"R450.00", another_farmer.get("/packaging").data)
        self.assertEqual(another_farmer.get("/admin/packaging").status_code, 403)
        self.assertEqual(self.admin.get("/admin/packaging").status_code, 200)
        url = f"/admin/packaging/{quote['id']}"
        self.form(self.admin, url, dict(revision=0, status="Quoted", amount="430", note="Reviewed pilot service estimate"))
        self.form(self.admin, url, dict(revision=0, status="Rejected", note="Concurrent stale review"))
        self.form(self.admin, url, dict(revision=1, status="Accepted", note="Approved for capacity planning"))
        self.assertEqual(self.row("SELECT COUNT(*) FROM packaging_quote_events")[0], 2)
        self.assertIn(b"R430.00", farmer.get("/packaging").data)
        self.assertEqual(buyer.get("/admin/finance").status_code, 403)
        for name in ("conservative", "base", "growth"):
            result = self.admin.get(f"/admin/finance?scenario={name}")
            self.assertEqual(result.status_code, 200)
            self.assertIn(b"R2,140.00", result.data)
        self.form(self.admin, "/admin/finance?scenario=growth", {"pack_price": "3", "orders": "42"})
        self.assertIn(b'name="orders" value="42"', self.admin.get("/admin/finance?scenario=growth").data)
        self.assertIn(b"From R3.00/kg", farmer.get("/packaging").data)
        self.assertEqual(self.row("SELECT estimate_cents FROM packaging_quotes")[0], 45000)

    def test_assistant_languages_and_provider_error(self):
        client = self.app.test_client()
        token = re.search(rb'name="csrf-token" content="([^"]+)"', client.get("/").data).group(1).decode()

        def ask(language, message):
            return client.post("/api/assistant/ask", json=dict(language=language, message=message),
                               headers={"X-CSRFToken": token})

        self.assertIn("Several farmers", ask("en-ZA", "How does pooling work?").json["answer"])
        local = ask("ve-ZA", "Vhalimi vha nga ṱanganya zwibveledzwa hani?")
        self.assertIn("Vhalimi vho fhambanaho", local.json["answer"])
        self.assertIn("ṱanganya", local.json["answer"])
        self.assertIn(b'value="ve-ZA">Tshivenda</option>', client.get("/").data)
        self.assertEqual(ask("ve-ZA", "Vhalimi vha nga tanganya zwibveledzwa hani?").json["answer"],
                         local.json["answer"])
        self.assertFalse(local.json["ai_active"])
        self.assertEqual(ask("zu-ZA", "Sawubona").status_code, 503)
        self.assertEqual(ask({}, "bad language type").status_code, 400)
        with patch.dict(os.environ, {"HARVEST_ROTATED_OPENAI_KEY": "injected-test-placeholder"}):
            with patch.object(requests, "post") as post:
                post.return_value.json.return_value = {
                    "output": [{"content": [{"type": "output_text", "text": "ṱanganyani zwibveledzwa."}]}],
                }
                result = ask("ve-ZA", "Vhalimi vha nga ṱanganya zwibveledzwa hani?")
                self.assertTrue(result.json["ai_active"])
                self.assertIn("Tshivenda", post.call_args.kwargs["json"]["instructions"])
                self.assertEqual(post.call_args.kwargs["timeout"], (3.05, 15))
                post.side_effect = requests.Timeout
                result = ask("ve-ZA", "Vhalimi vha nga ṱanganya zwibveledzwa hani?")
                self.assertEqual(result.status_code, 503)
                self.assertNotIn("answer", result.json)
