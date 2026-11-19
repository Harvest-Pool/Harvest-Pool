# Harvest Pool demo guide

Use a fresh isolated database with the synthetic accounts in the [README](README.md). Keep separate browser profiles or sign out before switching roles. Set the deadline a few days ahead and use dates within the selling window.

## Three-minute pitch

**0:00?0:45 ? The problem.** Better markets. Stronger harvests. A buyer in Limpopo needs a tonne of potatoes. One small grower has 650 kg and another can spare 350 kg. The buyer needs one order, a clear price and confidence in the supply. The growers need to know what they will be paid and decide for themselves whether to participate.

**0:45?1:30 ? How it works.** Harvest Pool checks approved listings against the buyer?s crop, price and deadline. It asks each farmer before allocating their stock. When both accept, the buyer can create one 1,000 kg order. The allocation ledger shows exactly how much each grower contributed and what the order total represents. Harvest Guide helps farmers and buyers navigate in their chosen language.

**1:30?2:15 ? Why packaging matters.** Some buyers need produce in a consistent pack size with a clear label. Growers can request packaging, printed labels and new artwork on the same platform. Each quote is reviewed against requirements, partner capacity and price. That gives the pilot a way to test demand before taking on infrastructure costs.

**2:15?3:00 ? How it earns.** The proposed buyer fee is 4%. Packing starts at R2.50 per kg and labels at R1 per unit. New artwork is R150. On the full-service example, R15,000 of produce value goes in the grower column and R4,250 goes in the service-revenue column. Illustrative direct production costs are R2,110. Start with a focused pilot in Vhembe, measure repeat orders and margins, then expand with confirmed partners.

## Five-minute technical walkthrough

| Time | Action and expected state |
|---|---|
| 0:00?0:45 | Show the home page, before/after and packaging flow. Open Marketplace. Sign in via **Administrator sign in** and show the two pending test sellers. Approve each with the designated-demo attestation and a note. Refresh Marketplace. The first listing appears and the decision is in the audit log. |
| 0:45?1:30 | Sign in as farmer 2 and list **Potatoes**, **450 kg**, **R15/kg**, **Grade A**, harvest today and available through the next two weeks. Upload a test image if prepared. The dashboard explains publishing status. Show both listings in Marketplace and filter by crop. |
| 1:30?2:25 | Sign in as buyer and request **1,000 kg** of **Potatoes** at **R15/kg** for delivery in a few days. Select **Find growers**. See 1,000 kg pending and no stock deductions. Sign in to each farmer account and accept with zero illustrative cost inputs. The buyer?s progress reaches 1,000 kg accepted. Create the order. |
| 2:25?3:05 | Open allocations. Show **650 kg / R9,750** and **350 kg / R5,250**, total **R15,000**. If a fresh Paystack test key and hosted checkout have been rehearsed, take the test checkout and check verification. Otherwise show the reconciled order, say provider checkout is pending key configuration and move on. |
| 3:05?3:40 | Ask Harvest Guide ?How does pooling work?? in English. Switch to Tshivenda and ask ?Vhalimi vha nga ṱanganya zwibveledzwa hani?? With no API configured both are built-in platform answers. Show the labeled AI status only if the API was verified in rehearsal. |
| 3:40?4:25 | As farmer 2, request combined service on the remaining 100 kg. Use **50 units** and request **one new design** for an indicative **R450**. As admin, quote **R430** with a review note. Return to the grower?s quote page to show the updated status. |
| 4:25?5:00 | In admin Financial Planning, show the R15,000 produce GMV and R4,250 service revenue example. Compare base and growth scenarios, break-even and cash lag. Close with the Vhembe pilot target. |

## Rehearsal checklist

- Start with unused fixtures so both farmers are pending. For replay, use a separate fresh demo directory and preserve the previous run.
- Take a synthetic crop image or use the optional no-photo listing path. Keep any real accounts, photographs and secrets outside the demonstration.
- If showing Paystack, open the hosted checkout in a test environment with a newly issued test credential and Paystack test instrument. Verification must report **verified test** and allocations must sum to R15,000.
- If OpenAI is unavailable, clear its demo credential and restart before rehearsal to use the labeled English and Tshivenda platform guide.
