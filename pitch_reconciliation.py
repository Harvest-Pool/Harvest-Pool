"""Reproducible investor scenario. Planning only; checkout pricing is untouched."""
import json
from pathlib import Path

from financial_model import D, INPUTS, RATES, money, project, read_fields, service_lines

ORDERS = (8, 10, 12, 12, 14, 14, 16, 16, 18, 20, 22, 26)
DECK = {
    "order_revenue": 1215, "order_contribution": 347, "orders": 188, "gmv": 2820000,
    "revenue": 254486, "operating_result": -272794, "funding_ask": 180000,
    "pilot_growers": 30, "pilot_buyer_leads": 10, "pilot_orders": 12,
}


def card_fee(amount):
    """Published SA local card fee, incl. VAT. The R1 component is waived below R10."""
    if amount <= 0:
        return D("0.00")
    fixed = D(1) if amount >= 10 else D(0)
    return money((amount * D("0.029") + fixed) * D("1.15"))


def forecast(orders=ORDERS, farmer_new=0, buyer_new=0, monthly_churn=D(0)):
    if not 0 <= monthly_churn <= 1 or farmer_new < 0 or buyer_new < 0:
        raise ValueError("Use non-negative starts and churn between zero and one.")
    rates, base = read_fields(RATES, {}), read_fields(INPUTS, {})
    produce_per_order = base["order_value"]
    revenue, direct = service_lines(
        rates, produce_per_order, base["pack_kg"] * base["pack_adoption"] / 100,
        base["label_units"] * base["label_adoption"] / 100, base["designs"],
    )
    per_order_revenue = sum(revenue.values())
    per_order_service_cost = sum(direct.values())
    gateway = card_fee(produce_per_order + per_order_revenue)
    transport, other = base["transport"], base["other_variable"]
    contribution = per_order_revenue - per_order_service_cost - gateway - transport - other
    fixed = sum(base[k] for k in ("staff", "utilities", "marketing", "infrastructure", "insurance", "other_fixed"))
    prior_order_receipts = D(0)
    farmer_count = buyer_count = cash_total = D(0)
    rows = []
    for month, count in enumerate(orders, 1):
        farmer_count = farmer_count * (1-monthly_churn) + farmer_new
        buyer_count = buyer_count * (1-monthly_churn) + buyer_new
        subscription = money(farmer_count * 99 + buyer_count * 499)
        subscription_fees = money(farmer_count * card_fee(D(99)) + buyer_count * card_fee(D(499)))
        services = count * per_order_revenue
        costs = count * (per_order_service_cost + transport + other)
        fees = count * gateway + subscription_fees
        result = services + subscription - costs - fees - fixed
        flow = prior_order_receipts + subscription - costs - fees - fixed
        cash_total += flow
        rows.append(dict(month=month, orders=count, gmv=count*produce_per_order, gross_farmer_proceeds=count*produce_per_order,
                         coordination_revenue=count*revenue["coordination"], packaging_revenue=count*revenue["packaging"],
                         branding_revenue=count*revenue["branding"], artwork_revenue=count*revenue["artwork"],
                         service_revenue=services, subscription_revenue=subscription, platform_revenue=services+subscription,
                         service_production_cost=count*per_order_service_cost, transport=count*transport, other_variable=count*other,
                         payment_fees=fees, fixed_cost=fixed, contribution=services+subscription-costs-fees,
                         operating_result=result, operating_cash_flow=flow, cumulative_cash=cash_total))
        prior_order_receipts = services
    keys = ("orders", "gmv", "gross_farmer_proceeds", "coordination_revenue", "packaging_revenue",
            "branding_revenue", "artwork_revenue", "service_revenue", "subscription_revenue", "platform_revenue",
            "service_production_cost", "transport", "other_variable", "payment_fees", "fixed_cost", "contribution",
            "operating_result", "operating_cash_flow")
    annual = {key: sum(row[key] for row in rows) for key in keys}
    annual["peak_funding_gap"] = max(0, -min((row["cumulative_cash"] for row in rows), default=0))
    return {
        "assumptions": {"average_produce_per_order": produce_per_order, "packaging_adoption_pct": base["pack_adoption"],
                        "branding_adoption_pct": base["label_adoption"], "packaged_kg_if_adopted": base["pack_kg"],
                        "labelled_units_if_adopted": base["label_units"], "new_artwork_per_order": base["designs"],
                        "service_receipt_lag_months": 1, "subscription_farmer_price": 99, "subscription_buyer_price": 499,
                        "new_farmer_subscribers_per_month": farmer_new, "new_buyer_subscribers_per_month": buyer_new,
                        "subscription_monthly_churn": monthly_churn, "opening_cash": 0,
                        "gateway_card_percent_ex_vat": D("2.9"), "gateway_card_flat_ex_vat": 1, "provider_fee_vat_percent": 15,
                        "passthrough_produce_cash_excluded": True, "funding_excluded_from_operating_revenue": True},
        "per_order": {"gmv": produce_per_order, "service_revenue_breakdown": revenue,
                      "service_revenue": per_order_revenue, "direct_service_cost_breakdown": direct,
                      "direct_service_cost": per_order_service_cost, "gateway_fee": gateway, "transport": transport,
                      "other_variable": other, "contribution": contribution},
        "annual": annual, "months": rows,
    }


def export(path):
    rates, inputs = read_fields(RATES, {}), read_fields(INPUTS, {})
    coded = project(rates, inputs)
    pilot = forecast((4, 4, 4))
    data = {
        "currency": "ZAR",
        "classification": "planning_only",
        "deck_baseline": DECK,
        "coded_commercial_assumptions": {"coordination_pct": rates["coordination"],
            "packaging_per_kg": rates["pack_price"], "branding_per_unit": rates["label_price"],
            "artwork_per_new_design": rates["art_price"], "farmer_pro_monthly": 99, "buyer_pro_monthly": 499,
            "checkout_coordination_enabled": False, "subscription_billing": "isolated_mock"},
        "coded_base_monthly": {key: coded[key] for key in
            ("gmv", "sales", "gateway", "direct_costs", "fixed", "contribution", "profit")},
        "audit_snapshot": {"database": "pre-change backup 2026-11-19", "investor_pptx_found": False,
            "produce_orders": 0, "verified_test_payments": 0, "test_settlement_allocations": 0,
            "packaging_quotes": 0, "verified_subscription_revenue": 0},
        "year_one": forecast(),
        "pilot_at_12_orders": pilot,
        "pilot_funding": {"proposed_ask": DECK["funding_ask"],
            "modelled_operating_gap": pilot["annual"]["peak_funding_gap"],
            "unallocated_ask": DECK["funding_ask"] - pilot["annual"]["peak_funding_gap"],
            "targets": {"vetted_growers": 30, "buyer_leads": 10, "completed_orders": 12}},
        "subscription_sensitivity_not_in_baseline": forecast(farmer_new=2, buyer_new=1, monthly_churn=D("0.05"))["annual"],
        "sources": {"paystack_pricing": "https://paystack.com/za/pricing",
                    "fee_vat": "https://support.paystack.com/en/articles/2124418"},
    }
    Path(path).write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export("financial_model.json")
