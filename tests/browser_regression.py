"""Opt-in browser regression suite. Run directly with Playwright and Chrome installed."""
import io
import os
import re
import secrets
import sys
import tempfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from threading import Thread
from urllib.parse import quote

from cryptography.fernet import Fernet
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.security import generate_password_hash
from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        if str(code).startswith("5"):
            super().log_request(code,size)


def run(workspace, screenshots):
    os.environ.update(
        HARVEST_ROTATED_SECRET_KEY=secrets.token_hex(48),
        HARVEST_DATABASE=str(workspace / "audit.db"),
        HARVEST_UPLOAD_DIR=str(workspace / "media"),
        HARVEST_ROTATED_OPENAI_KEY="",
        HARVEST_ROTATED_PAYSTACK_TEST_KEY="sk_test_browser_fixture",
        HARVEST_DEMO_MODE="1",
        HARVEST_SUBSCRIPTION_DEMO="1",
        COOKIE_SECURE="false",
    )
    import app as module
    from seller_verification import today

    vault = workspace / "vault"
    vault.mkdir()
    module.app.config.update(TESTING=True, KYC_PRIVATE_DIR=str(vault),
        KYC_ENCRYPTION_KEY=Fernet.generate_key(), KYC_REVIEWERS={"admin@example.invalid"},
        KYC_CONTROLLER="Synthetic browser test", KYC_PRIVACY_CONTACT="privacy@example.invalid",
        KYC_BASIS="contract")
    password = secrets.token_urlsafe(18)
    now = today().isoformat()
    later = (today() + timedelta(days=14)).isoformat()
    with closing(module.get_db()) as db, db:
        db.execute("INSERT INTO subscription_demo VALUES (1)")
        db.execute("INSERT INTO admin_accounts(email,password_hash) VALUES (?,?)",
                   ("admin@example.invalid", generate_password_hash(password)))
        partner = db.execute("""INSERT INTO farmers(name,phone,village,verification_status,demo_account)
            VALUES ('Synthetic Partner','+27701110304','Vhembe','Approved',1)""").lastrowid
        db.execute("INSERT INTO users(email,password_hash,role,profile_id) VALUES (?,?,'farmer',?)",
                   ("partner@example.invalid", generate_password_hash(password), partner))
        db.execute("""INSERT INTO produce_listings(farmer_id,crop,quantity_kg,available_kg,
            harvest_date,available_until,quality,asking_price) VALUES (?,'Potatoes',400,400,?,?,'Class 1',15)""",
            (partner, now, later))

    payment = {}

    def fake_paystack(method, endpoint, payload=None):
        if method == "POST":
            assert endpoint == "/transaction/initialize" and payload["currency"] == "ZAR"
            payment.update(reference=payload["reference"], amount=int(payload["amount"]))
            return {"reference": payment["reference"], "authorization_url": "https://checkout.paystack.com/browser-fixture"}
        assert endpoint == "/transaction/verify/" + quote(payment["reference"], safe="")
        return {**payment, "domain": "test", "currency": "ZAR", "status": "success"}

    module.provider_request = fake_paystack
    server = make_server("127.0.0.1", 0, module.app, threaded=True, request_handler=QuietRequestHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    errors = []
    file = io.BytesIO()
    Image.new("RGB", (120, 90), "#977144").save(file, "PNG")
    image = {"name": "synthetic.png", "mimeType": "image/png", "buffer": file.getvalue()}

    def record_request(response):
        if response.url.startswith(base) and response.status >= 400:
            errors.append(f"HTTP {response.status}: {response.url}")

    def opened(browser, size):
        context = browser.new_context(viewport={"width": size[0], "height": size[1]})
        context.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/"),
                      lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        def local_checkout(route):
            response = route.fetch(max_redirects=0)
            assert response.status == 303
            assert response.headers["location"] == "https://checkout.paystack.com/browser-fixture"
            callback = base + "/payments/paystack/test/callback?reference=" + payment["reference"]
            route.fulfill(response=response, headers={**response.headers, "location": callback})

        context.route(base + "/payments/paystack/test/1/start", local_checkout)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("response", record_request)
        return page

    def open_page(page, path):
        response = page.goto(base + path, wait_until="domcontentloaded")
        assert response and response.ok, (path, response.status if response else None)

    def screen(page, name):
        page.locator("img[loading=lazy]").evaluate_all("(images) => images.forEach(i => i.loading = 'eager')")
        page.locator("img").evaluate_all("async (images) => Promise.all(images.map(i => i.decode()))")
        width = page.evaluate("document.documentElement.scrollWidth - innerWidth")
        assert width <= 2, (name, width, page.url)
        assert not re.search(r"&(?:amp|nbsp|quot);", page.locator("body").inner_text()), name
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=False, animations="disabled")

    def fill(form, values):
        for name, value in values.items():
            field = form.locator(f'[name="{name}"]')
            if isinstance(value, dict):
                field.set_input_files(value)
            elif isinstance(value, bool):
                field.set_checked(value)
            elif field.evaluate("(element) => element.tagName") == "SELECT":
                field.select_option(value)
            else:
                field.click()
                field.fill(str(value))

    def submit(page, form, values, selector='button[type="submit"], button:not([type])'):
        fill(form, values)
        form.locator(selector).first.click()
        page.wait_for_load_state("domcontentloaded")

    def register(page, role, phone, name):
        open_page(page, "/register")
        fields = dict(role=role, email=f"{role}@example.invalid", password=password, name=name,
                      phone=phone, place="Vhembe")
        if role == "buyer":
            fields["business_name"] = "Synthetic Shop"
        submit(page, page.locator("form.modern-form"), fields)
        expect(page).to_have_url(re.compile("/login$"))
        sign_in(page, role)

    def sign_in(page, role):
        open_page(page, "/admin/login" if role == "admin" else "/login")
        submit(page, page.locator("[data-sign-in]"), {"email":f"{role}@example.invalid", "password":password})
        expect(page).to_have_url(re.compile("/admin$" if role == "admin" else "/dashboard$"))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True,
                args=["--host-resolver-rules=MAP checkout.paystack.com ~NOTFOUND"])
            sizes = {"desktop":(1440,900), "tablet":(768,1024), "mobile":(375,812)}
            for device, size in sizes.items():
                page = opened(browser, size)
                for name, path in (("home","/"), ("register","/register"), ("login","/login"),
                    ("pricing","/pricing"), ("market","/marketplace"), ("produce","/produce/1"),
                    ("packaging","/packaging"), ("admin-login","/admin/login")):
                    open_page(page,path)
                    if name == "home" and device != "desktop":
                        page.locator(".site-menu-toggle").click()
                        expect(page.locator("#site-navigation")).to_be_visible()
                    screen(page,f"{device}-{name}")
                open_page(page,"/marketplace?q=Potatoes")
                if device != "desktop":
                    page.locator(".site-menu-toggle").click()
                selector = page.locator(".site-nav .language-selector")
                submit(page,selector,{"locale":"zu-ZA"})
                expect(page.locator("html")).to_have_attribute("lang","zu-ZA")
                assert "q=Potatoes" in page.url
                expect(page.locator("#assistant-lang")).to_have_value("zu-ZA")
                page.locator('.mp-toolbar [name="q"]').fill("No matching crop")
                expect(page.locator("#market-feedback")).to_contain_text("0")
                expect(page.locator(".mp-card")).to_have_count(0)
                page.locator("[data-market-clear]").click()
                expect(page.locator(".mp-card")).to_have_count(1)
                open_page(page,"/pricing")
                expect(page.locator("h1")).to_have_text("Amanani")
                screen(page,f"{device}-pricing-zulu")
                page.locator("#assistant-launch").click()
                page.locator("#assistant-input").fill("Ngingahlanganisa izivuno kanjani?")
                page.locator("#assistant-send").click()
                expect(page.locator("#assistant-chat")).to_contain_text("Abalimi abaningana")
                page.locator("#assistant-lang").select_option("xh-ZA")
                page.locator("#assistant-input").fill("Molo")
                with page.expect_response(lambda r: r.url.endswith("/api/assistant/ask")) as unsupported:
                    page.locator("#assistant-send").click()
                assert unsupported.value.status == 503
                expect(page.locator("#assistant-state")).to_contain_text("requires AI text")
                expected_http = f"HTTP 503: {base}/api/assistant/ask"
                errors.remove(expected_http)
                page.wait_for_timeout(150)
                errors[:] = [e for e in errors if "503 (SERVICE UNAVAILABLE)" not in e and "status of 503" not in e]
                page.context.close()

            farmer = opened(browser,sizes["mobile"])
            buyer = opened(browser,sizes["tablet"])
            admin = opened(browser,sizes["desktop"])
            partner_page = opened(browser,sizes["desktop"])
            register(farmer,"farmer","+27701110301","Synthetic Grower")
            register(buyer,"buyer","+27701110302","Synthetic Buyer")
            sign_in(admin,"admin")
            sign_in(partner_page,"partner")
            workspace_menu = farmer.locator(".workspace-menu-toggle")
            expect(farmer.locator("#workspace-navigation")).to_be_hidden()
            workspace_menu.click()
            expect(farmer.locator('#workspace-navigation form[action="/logout"] button')).to_be_visible()
            expect(farmer.locator("#workspace-navigation .language-selector")).to_be_visible()
            screen(farmer,"mobile-workspace-menu")
            workspace_menu.click()
            screen(farmer,"mobile-farmer-dashboard")
            screen(buyer,"tablet-buyer-dashboard")
            screen(admin,"desktop-admin-dashboard")
            open_page(farmer,"/verification")
            screen(farmer,"mobile-verification")
            submit(farmer,farmer.locator('form[action="/verification/identity"]'),
                   {"route":"document","document_type":"sa-id","privacy_notice":True,"evidence":image})
            submit(farmer,farmer.locator('form[action="/verification/supply"]'),
                   {"location":"Private synthetic location","relationship":"permission","photo_date":now,
                    "quantity":750,"harvest_date":now,"privacy_notice":True,"evidence":image})
            assert buyer.request.get(base+"/verification/evidence/1/0").status == 404
            assert admin.request.get(base+"/verification/evidence/1/0").headers["cache-control"] == "private, no-store"
            for case in (1,2):
                open_page(admin,f"/admin/verification/{case}")
                screen(admin,f"desktop-review-{case}")
                submit(admin,admin.locator("main form"),dict(decision="Approved", expires_on=later,
                       primary_check=True, independent_check=True, reason="Synthetic independent review for browser regression."))
            open_page(farmer,"/dashboard")
            listing = dict(crop="Potatoes",quantity_kg=750,asking_price=14, harvest_date=now,
                           available_until=later,quality="Class 1",photo=image)
            submit(farmer,farmer.locator('form[action="/produce/add"]'), listing)
            expect(farmer.locator("body")).to_contain_text("Your produce was listed.")
            open_page(buyer,"/marketplace?q=Potatoes")
            expect(buyer.locator(".mp-card")).to_have_count(2)
            open_page(buyer,"/produce/2")
            expect(buyer.locator("body")).to_contain_text("Seller verified")
            expect(buyer.locator("body")).not_to_contain_text("Grade independently verified")
            screen(buyer,"tablet-verified-produce")
            open_page(farmer,"/packaging")
            submit(farmer,farmer.locator("#quote-form"),
                   {"listing_id":"2", "service":"combined","quantity_kg":50, "labelled_units":25,
                    "requirements":"Synthetic cartons for the browser regression test."})
            expect(farmer.locator("body")).to_contain_text("R150.00")
            open_page(admin,"/admin/packaging")
            screen(admin,"desktop-packaging-queue")
            expect(admin.locator("body")).to_contain_text("Synthetic cartons")
            open_page(buyer,"/dashboard")
            submit(buyer,buyer.locator('form[action="/demands/add"]'),
                   {"crop":"Potatoes","quantity_kg":1000,"target_price":15,
                    "deadline":later,"delivery_location":"Synthetic receiving depot"})
            submit(buyer,buyer.locator('form[action="/match/1"]'),{})
            for page, number in ((farmer,1),(partner_page,2)):
                open_page(page,"/dashboard")
                submit(page,page.locator(f'form[action="/offers/{number}/accept"]'),{})
            open_page(buyer,"/dashboard")
            submit(buyer,buyer.locator('form[action="/demo-orders/create/1"]'),{})
            open_page(buyer,"/orders/1/allocations")
            assert farmer.request.get(base+"/orders/1/allocations").status == 200
            screen(buyer,"tablet-order")
            submit(buyer,buyer.locator('form[action="/payments/paystack/test/1/start"]'),{})
            expect(buyer.locator("body")).to_contain_text("verified test")
            for page, contribution in ((farmer,1),(partner_page,2)):
                open_page(page,"/dashboard")
                submit(page,page.locator(f'form[action="/demo-orders/1/ready/{contribution}"]'),{})
            open_page(buyer,"/dashboard")
            submit(buyer,buyer.locator('form[action="/demo-orders/1/confirm-delivery"]'),{})
            expect(buyer.locator("body")).to_contain_text("Demo delivery confirmed")

            open_page(admin,"/admin")
            expect(admin.locator("body")).to_contain_text("R15000.00")
            open_page(farmer,"/subscription")
            screen(farmer,"mobile-subscription")
            submit(farmer,farmer.locator('form[action="/subscription/mock"]'),{},
                   'button[value="mock_success"]')
            expect(farmer.locator("body")).to_contain_text("Farmer Pro")
            open_page(farmer,"/subscription/tools")
            screen(farmer,"mobile-pro-tools")
            assert buyer.request.get(base+"/subscription/report.csv").status == 403
            open_page(buyer,"/subscription")
            submit(buyer,buyer.locator('form[action="/subscription/mock"]'),{},
                   'button[value="mock_success"]')
            open_page(buyer,"/subscription/tools")
            screen(buyer,"tablet-pro-tools")
            open_page(admin,"/admin/subscriptions")
            screen(admin,"desktop-subscription-admin")
            open_page(admin,"/admin/finance")
            screen(admin,"desktop-finance")
            open_page(admin,"/admin/verification")
            screen(admin,"desktop-verification-queue")
            with closing(module.get_db()) as db:
                assert db.execute("SELECT SUM(gross_cents),COUNT(*) FROM test_settlement_allocations").fetchone()[:] == (1500000,2)
                assert db.execute("SELECT SUM(available_kg) FROM produce_listings").fetchone()[0] == 150
                assert db.execute("SELECT COUNT(*) FROM subscription_periods").fetchone()[0] == 2
            browser.close()
        assert not errors, errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT / "backups" / "browser-regression"
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        run(Path(temporary),output)
    print(f"Browser regression passed. Screenshots in {output}")
