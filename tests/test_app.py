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
        self.execute("UPDATE farmers SET demo_account=1 WHERE id=?", farmer_id)
        with patch.dict(self.app.config, {"DEMO_MODE": True}):
            self.form(self.admin, route, dict(decision="Approved", note="Synthetic fixture independently confirmed",
                                              demo_attest="yes"))
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

    def test_expired_pending_offer_cannot_hold_or_consume_supply(self):
        farmer, farmer_id = self.account("farmer", 1)
        buyer, _ = self.account("buyer", 2)
        other, _ = self.account("buyer", 3)
        listing = self.listing(farmer, farmer_id, qty=100)
        self.approve(farmer_id)
        demand = dict(crop="Potatoes", quantity_kg=100, target_price=15,
                      deadline=self.expiry, delivery_location="Vhembe")
        self.form(buyer, "/demands/add", demand)
        self.form(buyer, "/match/1", {})
        self.assertEqual(self.row("SELECT COUNT(*) FROM pool_contributions")[0], 1)
        self.execute("UPDATE buyer_demands SET deadline='2000-01-01' WHERE id=1")
        response = self.form(farmer, "/offers/1/accept", {"transport_cost":0,"packaging_cost":0},
                             follow_redirects=True)
        self.assertIn(b"This sourcing request has expired.", response.data)
        self.assertEqual(self.row("SELECT available_kg FROM produce_listings WHERE id=?", listing)[0], 100)
        self.assertIn(b"This sourcing request has expired.",
                      self.form(buyer, "/match/1", {}, follow_redirects=True).data)
        self.form(other, "/demands/add", demand)
        self.form(other, "/match/2", {})
        self.assertEqual(self.row("SELECT quantity_kg FROM pool_contributions WHERE id=2")[0], 100)

    def test_packaging_translation_uses_plain_text_catalogue_keys(self):
        client = self.app.test_client()
        for url in ("/", "/packaging"):
            html = client.get(url).data
            self.assertIn(b"Packaging &amp; branding", html)
            self.assertNotIn(b"&amp;amp;", html)
        self.form(client, "/language", {"locale":"zu-ZA","return_to":"/packaging"})
        self.assertIn("Ukupakisha namalebula".encode(), client.get("/packaging").data)

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
        self.assertIn(b"Paystack test verified", buyer.get(f"/orders/{order_id}/allocations").data)
        for farmer_client, farmer_id in ((first, first_id), (second, second_id)):
            contribution = self.row("SELECT id FROM pool_contributions WHERE farmer_id=?", farmer_id)[0]
            ready = f"/demo-orders/{order_id}/ready/{contribution}"
            self.assertIn(ready.encode(), farmer_client.get("/dashboard").data)
            self.form(farmer_client, ready, {})
        self.assertEqual(self.row("SELECT status FROM demo_orders WHERE id=?", order_id)[0], "Ready for demo delivery")
        self.form(buyer, f"/demo-orders/{order_id}/confirm-delivery", {})
        self.assertEqual(self.row("SELECT status FROM demo_orders WHERE id=?", order_id)[0], "Demo delivery confirmed")


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

    def test_verification_privacy_approval_and_expiry(self):
        from cryptography.fernet import Fernet
        from seller_verification import today

        farmer, farmer_id = self.account("farmer", 1)
        other, other_id = self.account("farmer", 2)
        buyer, _ = self.account("buyer", 3)
        listing = self.listing(farmer, farmer_id, photo=True)
        other_listing = self.listing(other, other_id)
        day = today()
        expiry = (day + timedelta(days=14)).isoformat()

        def image():
            stream = io.BytesIO()
            Image.new("RGB", (20, 20), "#a26f3c").save(stream, "PNG")
            stream.write(b"private-appended-marker")
            stream.seek(0)
            return stream, "identity.png"

        def decide(case, **extra):
            fields = {"decision":"Approved", "reason":"Independent verification witnessed and recorded.",
                      "revision":0,"expires_on":expiry} | extra
            return self.form(self.admin, f"/admin/verification/{case}", fields)

        with tempfile.TemporaryDirectory() as vault, patch.dict(self.app.config, {
            "KYC_PRIVATE_DIR":vault,"KYC_ENCRYPTION_KEY":Fernet.generate_key(),
            "KYC_REVIEWERS":{"admin@demo.invalid"},"KYC_CONTROLLER":"Synthetic test",
            "KYC_PRIVACY_CONTACT":"privacy@example.invalid","KYC_BASIS":"contract",
        }):
            self.assertEqual(farmer.get("/verification").status_code,200)
            self.assertEqual(buyer.get("/verification").status_code,403)
            identity = dict(route="document",document_type="sa-id",privacy_notice="read")
            self.form(farmer,"/verification/identity",
                      identity | {"evidence":(io.BytesIO(b"not a photo"),"id.png")})
            self.assertEqual(self.row("SELECT count(*) FROM kyc_cases")[0],0)
            self.form(farmer,"/verification/identity",identity | {"evidence":image()})
            case=self.row("SELECT id FROM kyc_cases")[0]
            self.assertNotIn(b"private-appended-marker", next(Path(vault).glob("*.sealed")).read_bytes())
            path=f"/verification/evidence/{case}/0"
            for client in (buyer,other,self.app.test_client()):
                self.assertEqual(client.get(path).status_code,404)
            self.assertEqual(farmer.get(path).status_code,200)
            admin_image=self.admin.get(path)
            self.assertEqual(admin_image.status_code,200)
            self.assertEqual(admin_image.mimetype,"image/jpeg")
            self.assertTrue(admin_image.cache_control.no_store)
            self.assertNotIn(b"private-appended-marker",admin_image.data)
            with patch.dict(self.app.config, {"KYC_REVIEWERS":set()}):
                self.assertEqual(self.admin.get(path).status_code,403)
                self.assertEqual(self.admin.get(f"/admin/verification/{case}").status_code,403)
            self.assertEqual(decide(case,primary_check="yes").status_code,400)
            self.assertEqual(decide(case,primary_check="yes",independent_check="yes").status_code,302)
            self.assertEqual(self.row("SELECT verification_status FROM farmers WHERE id=?",farmer_id)[0],"Pending")
            self.assertEqual(buyer.get(f"/produce/{listing}").status_code,404)
            batch = dict(privacy_notice="read",listing_id=other_listing,batch="LOT-20",declaration="Seller declaration",evidence=image())
            self.assertEqual(self.form(farmer,"/verification/batch",batch).status_code,404)
            supply = dict(privacy_notice="read",location="private production coordinates",
                          relationship="communal",photo_date=day.isoformat(),harvest_date=day.isoformat(),
                          quantity=300,evidence=image())
            self.form(farmer,"/verification/supply",supply)
            supply_case=self.row("SELECT id FROM kyc_cases WHERE dimension='supply'")[0]
            self.assertEqual(self.admin.get(f"/admin/verification/{supply_case}").status_code,200)
            self.assertEqual(decide(supply_case,primary_check="yes",independent_check="yes").status_code,302)
            html=buyer.get(f"/produce/{listing}").data
            self.assertIn(b"Seller verified",html)
            self.assertNotIn(b"Stock independently checked",html)
            self.assertNotIn(b"Grade independently verified",html)
            self.assertNotIn(b"private production coordinates",html)
            self.form(farmer,"/verification/batch",batch | {"listing_id":listing, "evidence":image()})
            batch_case=self.row("SELECT id FROM kyc_cases WHERE dimension='batch'")[0]
            self.assertEqual(decide(batch_case,grade="Class 1",grade_check="yes").status_code,400)
            self.assertEqual(decide(batch_case,stock_check="yes").status_code,302)
            html=buyer.get(f"/produce/{listing}").data
            self.assertIn(b"Stock independently checked",html)
            self.assertNotIn(b"Grade independently verified",html)
            self.form(farmer, "/verification/batch", batch | {"listing_id":listing, "evidence":image(),
                      "issuer":"Synthetic inspector","reference":"SYN-CLASS-1","certificate_date":expiry})
            grade_case=self.row("SELECT MAX(id) FROM kyc_cases WHERE dimension='batch'")[0]
            self.assertEqual(decide(grade_case,grade="Class 1",grade_check="yes").status_code,302)
            html=buyer.get(f"/produce/{listing}").data
            self.assertIn(b"Grade independently verified",html)
            self.assertNotIn(b"SYN-CLASS-1",html)
            self.assertNotIn(b"Stock independently checked",html)
            runner=self.app.test_cli_runner()
            self.assertEqual(runner.invoke(args=["purge-verification-evidence","--case-id",str(grade_case)]).exit_code,0)
            self.assertEqual(runner.invoke(args=["purge-verification-evidence","--case-id",str(grade_case),"--apply"]).exit_code,0)
            self.assertEqual(farmer.get(f"/verification/evidence/{grade_case}/0").status_code,404)
            self.execute("UPDATE kyc_cases SET expires_on='2000-01-01' WHERE id=?",supply_case)
            self.assertEqual(buyer.get(f"/produce/{listing}").status_code,404)
            self.assertIn(b"Expired",farmer.get("/verification").data)
            supply["evidence"]=image()
            self.assertEqual(self.form(farmer,"/verification/supply",supply).status_code,302)
            self.assertEqual(self.row("SELECT count(*) FROM kyc_cases WHERE dimension='supply'")[0],2)
            self.assertGreater(self.row("SELECT count(*) FROM kyc_events")[0],5)
            self.assertEqual(self.form(farmer,"/verification/privacy",{"kind":"deletion"}).status_code,302)
            self.assertEqual(self.row("SELECT kind FROM kyc_privacy_requests")[0],"deletion")

    def test_free_resource_limits_and_reactivation(self):
        farmer, farmer_id = self.account("farmer", 1)
        self.assertIn(b"Current plan", farmer.get("/dashboard").data)
        self.assertIn(b"Free", farmer.get("/subscription").data)
        expired = self.listing(farmer, farmer_id)
        self.execute("UPDATE produce_listings SET available_until='2000-01-01' WHERE id=?", expired)
        for crop in ("Onions", "Potatoes", "Tomatoes"):
            self.listing(farmer, farmer_id, crop=crop)
        payload = dict(crop="Carrots", quantity_kg=100, asking_price=15, quality="Grade A",
                       harvest_date=self.today, available_until=self.expiry)
        self.assertEqual(self.form(farmer, "/produce/add", payload).location, "/subscription")
        self.assertEqual(self.form(farmer, f"/produce/{expired}/availability",
                                   {"available_until": self.expiry}).location, "/subscription")
        self.assertEqual(self.row("SELECT count(*) FROM produce_listings")[0], 4)
        buyer, buyer_id = self.account("buyer", 2)
        demand = dict(crop="Potatoes", quantity_kg=100, target_price=15,
                      deadline=self.expiry, delivery_location="Vhembe")
        for _ in range(2):
            self.assertEqual(self.form(buyer, "/demands/add", demand).location, "/dashboard")
        self.assertEqual(self.form(buyer, "/demands/add", demand).location, "/subscription")
        self.assertEqual(self.row("SELECT count(*) FROM buyer_demands WHERE buyer_id=?", buyer_id)[0], 2)
        self.assertEqual(buyer.get("/subscription/report.csv").status_code, 403)
        self.assertEqual(buyer.get("/admin/subscriptions").status_code, 403)
        self.assertEqual(self.admin.get("/subscription").status_code, 403)

    def test_mock_subscription_isolated_failure_retry_cancellation_and_expiry(self):
        farmer, farmer_id = self.account("farmer", 1)
        buyer, _ = self.account("buyer", 2)
        form = {"reference": "a" * 32, "plan": "farmer-pro", "outcome": "mock_success"}
        with patch.dict(self.app.config, {"DEMO_MODE": True, "SUBSCRIPTION_DEMO": True}):
            self.assertEqual(self.form(farmer, "/subscription/mock", form).status_code, 403)
            self.execute("INSERT INTO subscription_demo VALUES (1)")
            self.assertEqual(self.form(buyer, "/subscription/mock", form).status_code, 403)
            self.assertEqual(farmer.post("/subscription/mock", data=form).status_code, 400)
            failed = form | {"outcome": "mock_failure"}
            self.form(farmer, "/subscription/mock", failed)
            self.form(farmer, "/subscription/mock", form)
            self.assertEqual(self.row("SELECT count(*) FROM subscription_periods")[0], 0)
            success = form | {"reference": "b" * 32}
            for _ in range(2):
                self.assertEqual(self.form(farmer, "/subscription/mock", success).status_code, 302)
            self.assertEqual(self.row("SELECT count(*) FROM subscription_attempts")[0], 2)
            self.assertEqual(self.row("SELECT count(*) FROM subscription_periods")[0], 1)
            self.assertIn(b"Farmer Pro", farmer.get("/subscription").data)
            self.assertEqual(farmer.get("/subscription/tools").status_code, 200)
            self.assertNotIn(b"mock-", buyer.get("/subscription").data)
            for index in range(4):
                self.listing(farmer, farmer_id, crop=f"Crop {index}")
            with farmer.get("/subscription/report.csv") as csv_report:
                self.assertEqual(csv_report.status_code, 200)
                self.assertIn(b"Crop 3", csv_report.data)
            self.form(farmer, "/subscription/cancel", {})
            self.form(farmer, "/subscription/cancel", {})
            self.assertEqual(self.row("SELECT cancel_renewal FROM subscription_periods")[0], 1)
            self.assertEqual(self.row("SELECT count(*) FROM subscription_events WHERE kind='mock_cancel_renewal'")[0], 1)
            self.assertEqual(farmer.get("/subscription/tools").status_code, 200)
            self.assertEqual(self.admin.get("/admin/subscriptions").status_code, 200)
            with patch.dict(self.app.config, {"SUBSCRIPTION_DEMO": False}):
                self.assertEqual(farmer.get("/subscription/tools").status_code, 403)
            self.execute("UPDATE subscription_periods SET starts_on='2000-01-01',ends_on='2000-02-01'")
            self.assertEqual(farmer.get("/subscription/tools").status_code, 403)
            self.assertEqual(self.row("SELECT count(*) FROM produce_listings")[0], 4)
            over_limit = dict(crop="Carrots", quantity_kg=100, asking_price=15, quality="Grade A",
                              harvest_date=self.today, available_until=self.expiry)
            self.assertEqual(self.form(farmer, "/produce/add", over_limit).location, "/subscription")

    def test_buyer_pro_saved_template_and_profile_ownership(self):
        buyer, buyer_id = self.account("buyer", 1)
        other, other_id = self.account("buyer", 2)
        self.form(buyer, "/account", {"name": "Buyer Contact", "place": "Sibasa", "profile_id": other_id})
        self.assertEqual(self.row("SELECT location FROM buyers WHERE id=?", buyer_id)[0], "Sibasa")
        self.assertNotIn(b"Buyer Contact", other.get("/account").data)
        self.execute("INSERT INTO subscription_demo VALUES (1)")
        with patch.dict(self.app.config, {"DEMO_MODE": True, "SUBSCRIPTION_DEMO": True}):
            self.form(buyer, "/subscription/mock", {"reference": "c"*32, "plan": "buyer-pro",
                                                   "outcome": "mock_success"})
            fields = dict(crop="Potatoes", place="Sibasa", quantity="120", target_price="14", notify="yes")
            self.assertEqual(self.form(buyer, "/subscription/tools", fields).status_code, 302)
            page = buyer.get("/subscription/tools").data
            self.assertIn(b"Repeat sourcing request", page)
            self.assertIn(b'name="delivery_location" type="hidden" value="Sibasa"', page)
            self.assertEqual(other.get("/subscription/tools").status_code, 403)
            self.assertIn(b"produce_value_cents", buyer.get("/subscription/report.csv").data)

    def test_subscription_plan_edits_and_guide_allowance(self):
        buyer, _ = self.account("buyer", 1)
        fields = dict(code="free", farmer_limit=3, buyer_limit=2, guide_daily=1)
        self.assertEqual(self.form(buyer, "/admin/subscriptions", fields).status_code, 403)
        self.assertEqual(self.form(self.admin, "/admin/subscriptions", fields).status_code, 302)
        self.assertEqual(self.row("SELECT count(*) FROM subscription_events WHERE kind='plan_updated'")[0], 1)
        token = re.search(rb'name="csrf-token" content="([^"]+)"', buyer.get("/").data).group(1).decode()
        for code in (200, 429):
            answer = buyer.post("/api/assistant/ask", json={"message": "How does pooling work?"},
                                headers={"X-CSRFToken": token})
            self.assertEqual(answer.status_code, code)

    def test_locale_switching_persists_and_preserves_market_data(self):
        guest = self.app.test_client()
        destination = "/marketplace?q=Potatoes&sort=price-asc"
        change = self.form(guest, "/language", {"locale": "zu-ZA", "return_to": destination})
        self.assertEqual(change.status_code, 303)
        self.assertEqual(change.location, destination)
        marketplace = guest.get(destination).data
        self.assertIn(b'<html lang="zu-ZA">', marketplace)
        self.assertIn(b"Sebenzisa izihlungi", marketplace)
        self.assertIn(b'data-site-locale="zu-ZA"', marketplace)
        self.assertEqual(guest.post("/language", data={"locale": "ve-ZA"}).status_code, 400)
        change = self.form(guest, "/language", {"locale": "xh-ZA", "return_to": "//example.com"})
        self.assertEqual(change.location, "/")
        self.assertIn(b"interface translation is unavailable", guest.get("/").data)
        self.assertEqual(self.form(guest, "/language", {"locale": "invalid"}).status_code, 400)
        buyer, _ = self.account("buyer", 1)
        self.form(buyer, "/language", {"locale": "ve-ZA", "return_to": "/dashboard"})
        self.assertIn(b'<html lang="ve-ZA">', buyer.get("/dashboard").data)
        independent = self.login("buyer1@demo.invalid")
        self.assertIn(b"Mutengo", independent.get("/dashboard").data)
        self.assertEqual(self.row("SELECT preferred_locale FROM users")[0], "ve-ZA")
        self.assertEqual(independent.get("/accessibility").status_code, 200)

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
        self.assertEqual(ask("xh-ZA", "Molo").status_code, 503)
        self.assertIn("Abalimi abaningana", ask("zu-ZA", "Ngingahlanganisa izivuno kanjani?").json["answer"])
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
