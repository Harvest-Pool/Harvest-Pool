import unittest
from decimal import Decimal as D

from financial_model import INPUTS, RATES, number, project, read_fields, service_lines


class FinancialModelTests(unittest.TestCase):
    def test_potato_example_and_artwork_reuse(self):
        rates = read_fields(RATES, {})
        revenue, costs = service_lines(rates, D(15000), D(1000), 1000, 1)
        self.assertEqual(list(revenue.values()), [600, 2500, 1000, 150])
        self.assertEqual(sum(costs.values()), 2110)
        self.assertEqual(sum(revenue.values()) - sum(costs.values()), 2140)
        revenue, costs = service_lines(rates, D(0), D(50), 20, 0)
        self.assertEqual(sum(revenue.values()), 145)
        self.assertEqual(sum(costs.values()), 89)

    def test_monthly_economics_and_cash_timing(self):
        rates = read_fields(RATES, {})
        inputs = read_fields(INPUTS, {"orders": "10", "order_value": "15000",
                                      "pack_adoption": "100", "label_adoption": "100",
                                      "pack_kg": "1000", "label_units": "1000",
                                      "designs": "1", "cost_lag": "1"})
        model = project(rates, inputs)
        self.assertEqual(model["gmv"], 150000)
        self.assertEqual(model["sales"], 42500)
        self.assertEqual(model["gateway"], 3850)
        self.assertEqual(model["contribution"], 16250)
        self.assertEqual(model["profit"], 1250)
        self.assertEqual(model["break_even"], 10)
        self.assertEqual(len(model["months"]), 12)
        self.assertEqual(model["months"][0][-2], -18850)
        self.assertEqual(model["months"][1][-2], 1250)
        self.assertEqual(model["months"][-1][-1], -5100)

    def test_no_break_even_for_zero_orders_or_negative_contribution(self):
        rates = read_fields(RATES, {})
        for values in ({"orders": "0"}, {"gateway": "100"}):
            model = project(rates, read_fields(INPUTS, values))
            self.assertIsNone(model["break_even"])
            self.assertLess(model["profit"], 0)

    def test_rejects_non_finite_negative_out_of_range_and_fractional_units(self):
        for text in ("NaN", "Infinity", "-1", "101", "3.5", "1e9999"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                number(text, "100", 0)
