import unittest
from decimal import Decimal as D

from financial_model import INPUTS, RATES, read_fields
from pitch_reconciliation import card_fee, forecast


class PitchReconciliationTests(unittest.TestCase):
    def test_local_card_fee_and_flat_fee_waiver(self):
        self.assertEqual(card_fee(D("1000")), D("34.50"))
        self.assertEqual(card_fee(D("9.99")), D("0.33"))
        self.assertEqual(card_fee(D("10")), D("1.48"))

    def test_year_one_reconciles_service_gmv_costs_and_cash(self):
        model = forecast()
        year = model["annual"]
        self.assertEqual(year["orders"], 188)
        self.assertEqual(year["gmv"], D("2820000"))
        self.assertEqual(year["gmv"], year["gross_farmer_proceeds"])
        self.assertEqual(model["per_order"]["service_revenue"], D("1127.50"))
        self.assertEqual(model["per_order"]["contribution"], D("138.75"))
        self.assertEqual(year["platform_revenue"], D("211970"))
        self.assertEqual(year["operating_result"], D("-153915"))
        self.assertEqual(year["operating_cash_flow"], year["operating_result"]-model["months"][-1]["service_revenue"])
        self.assertEqual(year["peak_funding_gap"], D("183230"))
        self.assertEqual(year["subscription_revenue"], 0)

    def test_subscriptions_and_commission_remain_planning_inputs(self):
        from subscriptions import PLANS
        self.assertEqual([plan[3] for plan in PLANS], [0, 9900, 49900])
        self.assertEqual(read_fields(RATES, {})["coordination"], D(4))
        self.assertEqual(read_fields(INPUTS, {})["gateway"], D(2))
        scenario = forecast((4, 4), farmer_new=2, buyer_new=1, monthly_churn=D(1))
        self.assertEqual([m["subscription_revenue"] for m in scenario["months"]], [697, 697])
        self.assertEqual(scenario["annual"]["gmv"], D(120000))
        self.assertEqual(scenario["annual"]["subscription_revenue"], 1394)
