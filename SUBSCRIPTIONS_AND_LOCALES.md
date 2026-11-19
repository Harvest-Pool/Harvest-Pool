# Subscriptions and language switching

## Plans

| Plan | Proposed price | Active resources | Harvest Guide requests/day |
|---|---:|---|---:|
| Free | R0 | 3 farmer listings or 2 buyer sourcing requests | 20 |
| Farmer Pro | R99/month | Unlimited active farmer listings, subject to request throttling | 100 |
| Buyer Pro | R499/month | Unlimited active buyer requests, subject to request throttling | 100 |

The applicable allowance is checked server-side. A listing counts while its availability date is current and it has remaining stock, even when seller approval is pending. A sourcing request counts through its deadline until it has an order. A downgrade keeps existing records and blocks new active records and expired listing reactivation while the account is at or above the applicable limit. Order, checkout, seller review and packaging quote access remain part of Free.

**Farmer Pro** has listing and offer analytics, a saved demand watch, an in-app match count, a packaging quote status summary and CSV export. **Buyer Pro** has multi-grower order analytics, saved supply comparisons, an in-app match count, a repeat-request template and CSV export. Profile changes leave reviewed seller identity fields protected. Subscription administration and plan changes are audited.

## Isolated mock billing

Follow the README to create a fresh isolated demo database. Set both `HARVEST_DEMO_MODE=1` and `HARVEST_SUBSCRIPTION_DEMO=1`, then open **My subscription** using a demo farmer or buyer. The fixture database must contain its seed marker. Expected flow:

1. Simulate a failed payment and check that Free is still current.
2. Simulate a new successful attempt to start one mock calendar-month access period.
3. Open Pro tools, save a crop watch or sourcing template and download CSV.
4. Record renewal cancellation and confirm that Pro remains accessible through the current access period. The simulator never renews or charges automatically. A separate manual attempt can start a new period after expiry.
5. As administrator, review plans, mock access periods, mock failures and audit events. Verified subscription revenue stays R0.

Mocks cannot activate entitlements in a normal database. Subscription billing and produce-order Paystack records are separate. Live subscription billing still requires mapped Paystack customers and plans, verified recurring-period handling, signed webhook processing, and provider test-mode acceptance testing. The existing Paystack order flow remains separate. [Paystack subscriptions](https://paystack.com/docs/payments/subscriptions/) · [Paystack webhooks](https://paystack.com/docs/payments/webhooks/)

## Language coverage

The site selector affects interface text and sets the default language in Harvest Guide. Visitors keep the choice in their session and signed-in accounts save changes to their profile. Harvest Guide retains a separate override for the current site language. English is the source interface. The isiZulu and Tshivenda catalogs are partial previews and have not been independently reviewed by native-language reviewers. The other eight choices are explicitly marked as untranslated and show the English interface. All eleven choices can set the Harvest Guide language, subject to its provider configuration.

Catalogs are UTF-8 JSON under `locales/` and are referenced through `_()` in templates. Keep user-entered text and stored identifiers outside translation calls. Preserve explicit form option values if their display labels are translated. Review commercial, security, payment and consent language before releasing the previews as complete. The Accessibility page describes the current written pathways and the absence of signed video or live SASL interpretation.
