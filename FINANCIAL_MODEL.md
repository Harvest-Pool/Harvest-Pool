# Financial model

The administrator planning dashboard at `/admin/finance` stores three scenario input sets and shared pricing assumptions. All values are in South African rand. The dashboard presents illustrative pilot projections and is separate from Paystack test settlements.

## Starter rates

| Activity | Price | Modeled direct production cost |
|---|---:|---:|
| Buyer coordination | 4% of produce GMV | Gateway, transport and other variable assumptions below |
| Packaging | R2.50/kg | R1.60/kg |
| Printed label | R1.00/unit | R0.45/unit |
| Custom artwork | R150/new design | R60/new design |

An existing design carries zero setup charge. The buyer coordination fee is proposed and excluded from the test checkout. A saved quote estimate keeps the prices used at submission. Quote review and acceptance record planning decisions without collecting money.

## Formulas

- Order produce GMV = kg ? produce price per kg. Monthly GMV = orders ? average produce order value. GMV also represents gross grower produce proceeds before any grower-specific costs.
- Monthly coordination revenue = GMV ? fee percentage. Expected packaging kg = orders ? pack adoption ? average kg per adopting order. Expected branded units = orders ? branding adoption ? average units per adopting order. Expected new designs = orders ? average new designs across all orders.
- Packaging, label and artwork revenue and direct production costs use their own volume and rates. A labelled unit may hold any agreed weight.
- Service revenue is the sum of the four activity lines. Gross profit in the dashboard deducts packaging, printing and artwork production costs before gateway, transport and other variable expenses.
- Gateway expense = modeled GMV plus service revenue, multiplied by gateway rate, plus per-order gateway fees. This models a future collection mix and is configurable. Transport and other variable costs are per-order assumptions.
- Contribution = service revenue less direct production, gateway, transport and other variable expenses. Operating profit = contribution less fixed costs. Fixed costs include staff, utilities, marketing, infrastructure, insurance and other operating costs.
- Break-even = monthly fixed costs ? expected contribution per order, rounded up. Zero volume or a non-positive contribution per order has no modeled break-even quantity. Active farmer and buyer counts are planning context and do not change sales automatically.

## 1,000 kg potato example

| Line | Value |
|---|---:|
| Produce GMV ? 1,000 kg ? R15 | R15,000 |
| Coordination ? 4% ? R15,000 | R600 |
| Packaging ? 1,000 kg ? R2.50 | R2,500 |
| Branding ? 1,000 units ? R1 | R1,000 |
| Artwork ? one new design | R150 |
| **Service revenue** | **R4,250** |
| Packaging, label and artwork production | R2,110 |
| **Contribution before gateway, other variable costs and tax** | **R2,140** |

The example assumes one labelled unit per kg. The quote form takes those two amounts separately.

## Monthly starter projections

| Scenario | Orders | GMV | Service revenue | Direct costs | Contribution | Operating profit or loss | Break-even orders |
|---|---:|---:|---:|---:|---:|---:|---:|
| Conservative | 8 | R120,000 | R7,280 | R5,075.60 | R2,204.40 | ?R12,795.60 | 55 |
| Base case | 20 | R300,000 | R22,550 | R15,446 | R7,104 | ?R7,896 | 43 |
| Growth | 55 | R825,000 | R78,237.50 | R52,714.75 | R25,522.75 | R2,522.75 | 50 |

Default gateway expense is 2% of modeled collections, transport is R100/order, and other variable expense is R30/order. Fixed costs start at R15,000/month for conservative and base cases and R23,000 for growth. Replace figures with supplier quotes, staffing plans and supported payment rates when available.

## Cash timing

The 12-month table repeats monthly volumes and uses separate collection and supplier payment delays, defaulting to one month and zero months respectively. Gateway and fixed costs are paid in the order month. Opening cash and balances are zero. It excludes pass-through produce cash, tax, VAT, financing and capital expenditure. The growth case ends month 12 at ?R47,964.50 operating cash under these assumptions despite modeled operating profit. Confirm tax and VAT with an adviser based on the entity and its actual activities. [SARS VAT](https://www.sars.gov.za/types-of-tax/value-added-tax/)
