# Harvest Pool investor numbers reconciliation

**Planning only.** No investor PPTX was found in the project. The investor column uses the supplied baseline. The audited pre-change SQLite snapshot had no produce orders, verified test payments, settlement allocations, or packaging quotes. There were four sellers marked Pending and one Suspended. No persisted finance overrides or subscription tables were present. The subscription figures below come from the application definitions. Mock periods and test payments are not actual revenue.

## Reconciliation

| Metric | Coded value | Investor-deck value | Recommended value | Reason |
|---|---:|---:|---:|---|
| Coordination | 4% in the planning model; no checkout charge | 4% | 4% planning assumption | Produce checkout still charges only the produce order value. |
| Farmer Pro | R99/month mock plan | R99/month | R99/month proposed | Recurring Paystack billing is unavailable. No subscriber price changed. |
| Buyer Pro | R499/month mock plan | R499/month | R499/month proposed | Same billing limitation. |
| Packaging | R2.50/kg | R2.50/kg | R2.50/kg proposed | Apply to packaged kg only. |
| Branding | R1/unit | R1/unit | R1/unit proposed | Apply to individual labelled units, not kg. |
| Artwork | R150/new design | R150/design | R150/new design | Existing designs have no setup charge. |
| Average order GMV and gross farmer proceeds | R15,000 | R15,000 | R15,000 | 1,000 kg × R15/kg. Produce value passes through to growers. |
| Expected coordination and other service revenue/order | R1,127.50 | R1,215 | R1,127.50 | Apply the existing base service adoption and usage assumptions. The deck uplift of R87.50/order has no supplied bridge. |
| Modelled processing/order | R322.55 at a 2% generic gateway assumption | Not supplied | R539.00 local-card case | 2.9% + R1, plus 15% VAT on the fee, applied to projected collections of R16,127.50 per order. |
| Contribution/order | R355.20 at coded gateway assumption | Approx. R347 | R138.75 local-card case | Revenue less service production, transport, gateway and other variable costs. |
| Year-one completed orders | 240 if the coded monthly base case is repeated | 188 | 188 as a planning target | Forecast uses an explicit monthly ramp of 8, 10, 12, 12, 14, 14, 16, 16, 18, 20, 22, 26. |
| Year-one GMV / gross farmer proceeds | R3,600,000 at 240 orders | R2,820,000 | R2,820,000 | 188 × R15,000. |
| Annual coordination and optional-service revenue | R270,600 at 240 orders | Not separately supplied | R211,970 | Coordination R112,800, packaging R82,250, labels R14,100, and artwork R2,820. |
| Year-one subscription revenue | No verified provider subscription revenue | Not separately supplied | R0 in the base forecast | At 188 orders, R1,215/order would yield R228,420, leaving R26,066 of the deck’s annual revenue unexplained. |
| Year-one platform revenue | R270,600 at 240 orders, excluding subscriptions | R254,486 | R211,970 | Expected services only. Projected subscriptions appear in a separate sensitivity. |
| Year-one fixed operating costs | R180,000 | Not supplied | R180,000 provisional | R15,000/month as coded. Replace with staffing, supplier and operating evidence when available. |
| Year-one operating result | R94,752 loss at 240 orders and coded gateway rate | R272,794 loss | R153,915 loss | R26,085 contribution less R180,000 fixed costs. The deck loss implies R527,280 in combined expenses at its projected revenue. Its underlying expense schedule was unavailable. |
| Year-one peak operating cash gap | R117,302 at 240 orders and coded gateway rate | Not supplied | R183,230 | One month service settlement lag, current-month expenses, zero opening cash, no pass-through float. R29,315 is still outstanding at year end in the model. |
| 90-day pilot funding ask | No funding assumed in operating model | R180,000 | R180,000 only as a separately costed ask | 12 orders at four/month yield a R47,845 modeled operating cash gap. The remaining R132,155 needs a documented use-of-funds breakdown or reserve policy. |
| Pilot milestones | No verified completed orders in the audited snapshot | 30 vetted growers, 10 buyer leads, 12 completed orders | Retain as proposed targets | Use separate measures for vetted growers, buyer leads and completed orders. |

## Assumptions behind the recommended case

- Packaging adoption 35% × 500 kg, label adoption 25% × 300 units, and 0.10 new designs per order. Use R1.60/kg packaging cost, R0.45/label and R60/new artwork. Expected production cost is R319.75 per order. Transport and other variable costs add R100 and R30 per order.
- The illustrative full adoption potato example remains R4,250 in service revenue and R2,140 contribution before payment fees, other costs and tax. The expected-order case uses partially adopted optional services.
- The gateway basis is one hypothetical local card collection including GMV and all services. Actual test checkout collects only the produce order value. Published Paystack pricing quotes 2.9% + R1 before VAT for local cards and 2% without a flat fee for specified EFT methods. The R1 charge is waived below R10. At R15,000 alone the modeled local-card cost is R501.40. At R16,127.50, qualifying EFT would model R370.93 with the same VAT treatment, implying R306.82 contribution per order. Confirm channel, merchant terms, fee incidence and VAT treatment before using this as a cash forecast. [Paystack South Africa pricing](https://paystack.com/za/pricing) · [Paystack fee VAT example](https://support.paystack.com/en/articles/2124418)
- Annual costs are R60,113 service production, R18,800 transport, R5,640 other variable, R101,332 payment fees, and R180,000 fixed overhead. Operating cash excludes settling produce pass-through balances, tax, capex, financing and one-off pilot expenses. The pilot and annual cash gaps come from different volume schedules. Funding is financing, and contingency is only an expense if spent.
- The subscription sensitivity starts from zero, adds two farmers and one buyer/month, and uses 5% monthly churn on existing subscribers before new starts. It yields R45,539.77 of projected subscription revenue and R1,743.85 extra processing costs in year one. It is illustrative, rounded monthly, and excludes incremental subscription support costs. It is outside the recommended operating case.
- Re-run the export with `.venv\Scripts\python.exe pitch_reconciliation.py`. Decimal currency amounts in the JSON export are strings to preserve precision.
