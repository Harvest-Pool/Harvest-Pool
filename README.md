# Harvest Pool

**Better markets. Stronger harvests.** Harvest Pool is a Flask and SQLite marketplace for farmer-controlled produce pooling. Buyers can make bulk requests, sellers can consent to allocations, and growers can request packaging and branding quotes. An administrator can review sellers and model a Vhembe pilot.

## Run locally on Windows

Reuse the project virtual environment or create one with an installed Python supported by the pinned dependencies.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1
```

Open `http://127.0.0.1:5000`. The application uses `harvest_pool.db` and `instance/produce_photos` and applies additive SQLite migrations at import. Use `flask --app app create-admin` through the same Python executable to create an administrator locally. The sign-in page links to the dedicated administrator form.

## Configuration and rotation

Use process environment variables or the ignored local `.env` for these settings.

| Setting | Purpose |
|---|---|
| `HARVEST_ROTATED_SECRET_KEY` | Required fresh random Flask signing key of at least 32 characters. A local key was installed in this workspace. On a new machine generate one locally with `secrets.token_hex(48)`. |
| `HARVEST_ROTATED_PAYSTACK_TEST_KEY` | Fresh Paystack test key with the `sk_test_` prefix. Empty disables external test checkout. |
| `HARVEST_ROTATED_PAYSTACK_WEBHOOK_SECRET` | Optional rotated signing secret where a timestamped webhook signing secret is provisioned. Legacy test signatures use the rotated test API key. |
| `HARVEST_ROTATED_OPENAI_KEY` | Fresh server-only OpenAI key. With no key, the English and Tshivenda built-in platform guide is available. |
| `HARVEST_AI_MODEL` | Text model override. |
| `COOKIE_SECURE` | Set to `true` for HTTPS. Local loopback testing uses the default `false`. |

The previous Flask signing key has been replaced locally. Revoke the previously exposed Paystack and OpenAI credentials at their providers and install replacements locally. The application ignores the legacy secret names. Keep `.env`, uploaded media, databases and backups private. Restart the application after configuration changes.

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

The automated suite passed all nine tests. It uses temporary databases, synthetic accounts, test uploads and mocked provider responses. A restored copy of the existing database passed repeated migration, integrity and foreign key checks. Headless Chrome passed narrow and wide packaging layout, image loading and Harvest Guide language checks. The pre-build backup lives at `backups/hackathon-20261118-170917-018849`. It contains a consistent SQLite snapshot, uploaded media, the original Git HEAD and binary working-tree patch, and an independent Git checkpoint commit `627ed36` under `git-checkpoint`. Recover into a separate directory to inspect and compare before replacing live files.

- [Demo guide](DEMO_GUIDE.md)
- [Business plan](BUSINESS_PLAN.md)
- [Financial model](FINANCIAL_MODEL.md)
- [Known limitations](KNOWN_LIMITATIONS.md)

## Packaging imagery

The product mock-up was made with the built-in image generator and published in project-local WebP variants at 600 and 1200 pixels wide. Prompt used:

> Product mock-up for the Harvest Pool packaging service page. Wide 3:2 editorial product photograph on a warm off-white tabletop against a muted olive studio backdrop. Show a kraft paper potato bag with a small deep green label reading ?VHEMBE GROWN?, a recyclable berry punnet and a neat kraft produce carton with a small blank cream label. Include only a few clean loose potatoes close to the bag. Natural side light, realistic paper texture, understated agricultural branding, no people or facilities, no additional text or watermark. Make the packages large and centered.
