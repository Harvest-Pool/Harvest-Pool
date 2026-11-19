"""Illustrative ZAR planning and quote calculations."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

D = Decimal
CENT = D("0.01")

# Label, default, maximum, allowed decimal places.
RATES = {
    "coordination": ("Coordination fee (%)", "4", "100", 2),
    "pack_price": ("Packaging price (R/kg)", "2.50", "10000", 2),
    "pack_cost": ("Packaging direct cost (R/kg)", "1.60", "10000", 2),
    "label_price": ("Branding price (R/unit)", "1", "10000", 2),
    "label_cost": ("Printing cost (R/unit)", "0.45", "10000", 2),
    "art_price": ("Artwork setup price (R/new design)", "150", "100000", 2),
    "art_cost": ("Artwork setup cost (R/new design)", "60", "100000", 2),
}
INPUTS = {
    "farmers": ("Active farmers", "20", "1000000", 0),
    "buyers": ("Active buyers", "10", "1000000", 0),
    "orders": ("Orders per month", "20", "1000000", 0),
    "order_value": ("Average produce order (R)", "15000", "10000000", 2),
    "pack_adoption": ("Packaging adoption (%)", "35", "100", 2),
    "label_adoption": ("Branding adoption (%)", "25", "100", 2),
    "pack_kg": ("Average kg per packaging order", "500", "1000000", 2),
    "label_units": ("Average units per branding order", "300", "1000000", 2),
    "designs": ("Average new designs per order", "0.10", "1000", 4),
    "gateway": ("Gateway fee on modeled collections (%)", "2", "100", 2),
    "gateway_flat": ("Gateway fixed fee per order (R)", "0", "100000", 2),
    "transport": ("Variable transport per order (R)", "100", "100000", 2),
    "other_variable": ("Other variable cost per order (R)", "30", "100000", 2),
    "staff": ("Monthly staff (R)", "10000", "10000000", 2),
    "utilities": ("Monthly utilities (R)", "500", "10000000", 2),
    "marketing": ("Monthly marketing (R)", "1500", "10000000", 2),
    "infrastructure": ("Monthly infrastructure (R)", "750", "10000000", 2),
    "insurance": ("Monthly insurance (R)", "750", "10000000", 2),
    "other_fixed": ("Other monthly fixed costs (R)", "1500", "10000000", 2),
    "collections_lag": ("Service receipts lag (months)", "1", "12", 0),
    "cost_lag": ("Direct supplier cost lag (months)", "0", "12", 0),
}
SCENARIOS = {
    "conservative": {"farmers": "8", "buyers": "4", "orders": "8", "pack_adoption": "20", "label_adoption": "15"},
    "base": {},
    "growth": {"farmers": "50", "buyers": "25", "orders": "55", "pack_adoption": "55", "label_adoption": "40", "staff": "18000"},
}


def number(value, maximum, places=2):
    try:
        raw = str(value).strip()
        if len(raw) > 40:
            raise ValueError
        parsed = D(raw)
        if not parsed.is_finite() or not 0 <= parsed <= D(maximum):
            raise ValueError
        rounded = parsed.quantize(D(1).scaleb(-places))
        if rounded != parsed:
            raise ValueError
        return rounded
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Enter a number from 0 to {maximum}, with up to {places} decimal places.") from exc


def read_fields(fields, values):
    result = {}
    for key, (label, default, maximum, places) in fields.items():
        try:
            result[key] = number(values.get(key, default), maximum, places)
        except ValueError as exc:
            raise ValueError(f"{label}. {exc}") from exc
    return result


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def cents(value):
    return int(money(value) * 100)


def service_lines(rates, gmv, kg, units, designs):
    revenue = {
        "coordination": money(gmv * rates["coordination"] / 100),
        "packaging": money(kg * rates["pack_price"]),
        "branding": money(units * rates["label_price"]),
        "artwork": money(designs * rates["art_price"]),
    }
    costs = {
        "packaging": money(kg * rates["pack_cost"]),
        "branding": money(units * rates["label_cost"]),
        "artwork": money(designs * rates["art_cost"]),
    }
    return revenue, costs


def project(rates, inputs):
    orders = inputs["orders"]
    gmv = orders * inputs["order_value"]
    revenue, service_costs = service_lines(
        rates, gmv,
        orders * inputs["pack_adoption"] / 100 * inputs["pack_kg"],
        orders * inputs["label_adoption"] / 100 * inputs["label_units"],
        orders * inputs["designs"],
    )
    sales = sum(revenue.values())
    gateway = money((gmv + sales) * inputs["gateway"] / 100 + orders * inputs["gateway_flat"])
    transport = orders * inputs["transport"]
    other_variable = orders * inputs["other_variable"]
    supplier_costs = sum(service_costs.values()) + transport + other_variable
    direct_costs = supplier_costs + gateway
    fixed = sum(inputs[key] for key in ("staff", "utilities", "marketing", "infrastructure", "insurance", "other_fixed"))
    contribution = sales - direct_costs
    per_order = contribution / orders if orders else D(0)
    break_even = int((fixed / per_order).to_integral_value(rounding=ROUND_CEILING)) if per_order > 0 else None
    months = []
    cash = D(0)
    for month in range(1, 13):
        receipts = sales if month > inputs["collections_lag"] else D(0)
        supplier_cash = supplier_costs if month > inputs["cost_lag"] else D(0)
        # Gateway expense is assumed paid in the order month.
        flow = receipts - supplier_cash - gateway - fixed
        cash += flow
        months.append((month, gmv, sales, contribution - fixed, flow, cash))
    return dict(gmv=gmv, revenue=revenue, sales=sales, gateway=gateway, transport=transport,
                other_variable=other_variable, service_costs=service_costs, direct_costs=direct_costs,
                fixed=fixed, contribution=contribution, per_order=per_order,
                profit=contribution - fixed, break_even=break_even, months=months)
