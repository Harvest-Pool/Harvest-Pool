# Harvest Pool

**Better markets. Stronger harvests.** Harvest Pool is a Flask and SQLite marketplace for farmer-controlled produce pooling. Buyers can make bulk requests, sellers can consent to allocations, and growers can request packaging and branding quotes. Administrators can review seller evidence, audit subscription simulations, and model a Vhembe pilot.

- Farmer and buyer dashboards, accepted-stock pooling, and test checkout with allocation reconciliation
- Packaging and branding quote requests and administrator review
- Seller Verification Centre with an encrypted evidence vault and separate identity, supply, and listing checks
- Free and Pro entitlements with isolated mock subscription billing
- Site language selector with English and partial isiZulu and Tshivenda translations, plus Harvest Guide

## Organisation project brief

> Small scale farmers in the Northern region struggle to access reliable markets

## Run locally on Windows

Install Python 3.15 on Windows, the version used to validate this build. From the project directory, create a virtual environment and install the pinned dependencies.

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:HARVEST_ROTATED_SECRET_KEY = (.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(48))")
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1
```

Open `http://127.0.0.1:5000`. The application uses `harvest_pool.db` and `instance/produce_photos` and applies additive SQLite migrations at import. Use `flask --app app create-admin` through the same Python executable to create an administrator locally. The sign-in page links to the dedicated administrator form.

## Configuration and rotation

Use process environment variables or the ignored local `.env` for these settings.

| Setting | Purpose |
|---|---|
| `HARVEST_ROTATED_SECRET_KEY` | Required fresh random Flask signing key of at least 32 characters. Generate one locally with `secrets.token_hex(48)`. |
| `HARVEST_ROTATED_PAYSTACK_TEST_KEY` | Fresh Paystack test key with the `sk_test_` prefix. Empty disables external test checkout. |
| `HARVEST_ROTATED_PAYSTACK_WEBHOOK_SECRET` | Optional rotated signing secret where a timestamped webhook signing secret is provisioned. Legacy test signatures use the rotated test API key. |
| `HARVEST_ROTATED_OPENAI_KEY` | Fresh server-only OpenAI key. With no key, the English, Tshivenda and isiZulu built-in platform guide is available. |
| `HARVEST_AI_MODEL` | Text model override. |
| `COOKIE_SECURE` | Set to `true` for HTTPS. Local loopback testing uses the default `false`. |

The previous Flask signing key has been replaced locally. Revoke the previously exposed Paystack and OpenAI credentials at their providers and install replacements locally. The application ignores the legacy secret names. Keep `.env`, uploaded media, databases and backups private. Restart the application after configuration changes. Keep a stable signing key in your deployment secret manager so routine restarts preserve sessions.

## Isolated demo

```powershell
.\.venv\Scripts\python.exe scripts/seed_demo.py
$env:HARVEST_DATABASE = "$PWD\instance\demo\demo.db"
$env:HARVEST_UPLOAD_DIR = "$PWD\instance\demo\photos"
$env:HARVEST_DEMO_MODE = "1"
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5001
```

Enter a dedicated demo-only password when prompted. The fixture accounts are `farmer1@demo.invalid`, `farmer2@demo.invalid`, `buyer@demo.invalid` and `admin@demo.invalid`. Use a fresh PowerShell session to return to the normal database. The seed script refuses to overwrite an existing demo directory. Demo approval applies only to designated synthetic sellers when demo mode is enabled. For real accounts, perform and record independent verification without placing sensitive documents or identifiers in review notes.

## Tests and recovery

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

The suite uses temporary databases, synthetic accounts, images and mocked provider responses. Back up the deployed SQLite database using the SQLite backup API and preserve private media according to its access and retention policy. Rehearse migrations on a copy and check database integrity and foreign keys before applying a release. Store backups separately and restrict access.

- [Demo guide](DEMO_GUIDE.md)
- [Business plan](BUSINESS_PLAN.md)
- [Financial model](FINANCIAL_MODEL.md)
- [Known limitations](KNOWN_LIMITATIONS.md)

## Packaging imagery

The product mock-up was made with the built-in image generator and published in project-local WebP variants at 600 and 1200 pixels wide. Prompt used:

> Product mock-up for the Harvest Pool packaging service page. Wide 3:2 editorial product photograph on a warm off-white tabletop against a muted olive studio backdrop. Show a kraft paper potato bag with a small deep green label reading ?VHEMBE GROWN?, a recyclable berry punnet and a neat kraft produce carton with a small blank cream label. Include only a few clean loose potatoes close to the bag. Natural side light, realistic paper texture, understated agricultural branding, no people or facilities, no additional text or watermark. Make the packages large and centered.

## Subscriptions and localisation

See [Subscriptions and language switching](SUBSCRIPTIONS_AND_LOCALES.md) for plan limits, test billing, admin controls and translation coverage. To enable mock subscriptions when starting a freshly seeded demo, also set `$env:HARVEST_SUBSCRIPTION_DEMO = "1"` in the demo PowerShell session.

## Seller verification and investor model

See [Verification Centre operations](VERIFICATION_OPERATIONS.md) before enabling private evidence intake. See [Investor numbers](PITCH_NUMBERS.md) for reconciled planning figures and the assumptions behind them.

## Deployment requirements

- Run a production WSGI server behind HTTPS. Flask's built-in server is for local development. Set `COOKIE_SECURE=true` and configure forwarded headers only from a trusted reverse proxy.
- Set `HARVEST_DATABASE` and `HARVEST_UPLOAD_DIR` to persistent, writable service storage. Use a release window for startup migrations and restore rehearsals. The bundled in-memory rate limiter is suitable for local or single-process use. Adopt a shared rate-limit store before scaling to multiple workers.
- Keep mock billing and demo fixtures disabled on deployments with real users. Paystack order checkout is test-only, while subscriptions use separate mock billing. Verify sandbox credentials and callback URLs before provider testing.
- Keep real seller evidence intake disabled until the [verification operations requirements](VERIFICATION_OPERATIONS.md) are met. Use an external, access-controlled vault and a dedicated encryption key. Approve the privacy notice, retention process, reviewer access, and incident response before intake.
- [Known limitations](KNOWN_LIMITATIONS.md) lists the remaining shipping constraints, including incomplete translations and provider-dependent Harvest Guide speech and AI.
