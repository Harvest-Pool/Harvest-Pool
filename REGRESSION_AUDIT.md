# Harvest Pool regression audit

The audit started from application commit `cca8ea6`. PR #1 had already merged, so the fixes are on `fix/full-application-regression` from organisation main. A local Git bundle, integrity-checked database copy and uploaded produce-media backup were created before editing. All test activity used synthetic accounts and temporary databases.

## Defects and fixes

| Issue | Root cause | Fix and files |
|---|---|---|
| Public header showed literal HTML entities and an inconsistent brand in translated views | Translation keys contained pre-escaped HTML and reused the translation of the packaging process verb in the brand name | Use plain-text keys and Jinja autoescaping, update both preview catalogs, preserve the Harvest Pool brand. `templates/base.html`, `templates/packaging.html`, `templates/packaging_intro.html`, `locales/*.json` |
| Public header cramped at intermediate widths and the mobile workspace hid sign-out | Overlapping header flex styles and the legacy mobile rule hiding the entire workspace account footer | Align the brand and menu, collapse the public header earlier, and use an accessible workspace menu with sign-out and language selection. Reduce the small-screen assistant button footprint. `templates/base.html`, `static/css/pilot.css`, `static/js/site-interactions.js` |
| Marketplace and dashboard text contained question marks where separators or progress text belonged | Garbled text literals survived earlier edits and marketplace loading ignored its translated data attribute | Correct separators and use the localized loading message. Clarify that a public listing’s declaration is separate from verified grade. `static/js/market-live.js` and affected templates |
| Expired pending offers blocked available stock or could still be accepted | Matching counted pending offers without the buyer request’s deadline and consent did not recheck it | Reject new matching and acceptance on expired requests and exclude those pending commitments from new supply calculations. Keep historical records. `app.py`, `templates/index.html` |
| Verified Paystack test checkout could strand fulfilment | The demo fulfilment controller and dashboard required a separate manual payment status even when the verified test ledger existed | Allow verified test payment to unlock farmer readiness, show the verified status, and keep delivery confirmation and money records separate. `app.py`, `templates/index.html`, `templates/order_allocations.html` |

## Verification

- All 21 Flask and unit tests passed. The suite covers translation escaping, expired pending offers, Free limits and Pro restrictions, mock billing, KYC ownership and encryption, seller approval visibility, pooling and test checkout idempotency, verified checkout through demo delivery, packaging quotes, and finance.
- The opt-in Playwright suite exercises public pages at 1440×900, 768×1024 and 375×812 in Chrome. It checks page overflow, image decoding, unexpected same-origin HTTP errors, JavaScript errors, language switching, marketplace filtering and the Harvest Guide fallback and error path.
- The connected workflow registers a farmer and buyer, uploads synthetic KYC images, authorises administrator review, publishes approved stock, requests a packaging quote, creates a two-farmer 1,000 kg pool, verifies mocked ZAR test checkout, marks contributions ready and confirms demo delivery. It also exercises both Pro plans in the isolated mock database and checks restricted KYC and Pro access.
- The successful run captured 43 screenshots. Screenshots are kept locally under `backups/browser-regression-final/`. The browser runner is `tests/browser_regression.py`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe tests/browser_regression.py backups/browser-regression-final
```

## Limits of the audit

Chrome was tested at three viewport sizes. Other browsers, physical devices, browser microphones and real OpenAI calls were outside the verification. Provider checkout and verification used a synthetic Paystack contract. A first Chrome run followed the placeholder checkout URL to a provider interstitial. The final runner rewrites only the synthetic redirect to localhost and prevents the browser from reaching that host. No real payment was attempted.

Subscription billing remains mock-only. Real KYC intake still requires a secure deployment and approved privacy operations. Translation coverage remains partial. These are deployment constraints even when the regression suite passes.
