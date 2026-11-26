import unittest
from workstation_api import zerodha_execution_costs as z, liquidity_spreads as fees


class ZerodhaExecutionCostTests(unittest.TestCase):
    def test_current_tariff_and_tick_targets(self):
        r=z.estimate(buy_premium=180,sell_premium=182,quantity=90)
        self.assertAlmostEqual(r["fees"]["total_estimated"],85.90)
        self.assertAlmostEqual(r["net_pnl_inr"],94.10)
        self.assertEqual(r["break_even_sell_premium"],180.95)
        self.assertGreater(r["target_sell_premium"],182)
        b=r["break_even_sell_premium"]
        before=z.estimate(buy_premium=180,sell_premium=b-.05,quantity=90)
        self.assertLess(before["net_pnl_inr"],0)
    def test_order_counts_and_debit_profile(self):
        a=fees.fee_schedule(16200,16380,broker_profile="zerodha",buy_orders=1,sell_orders=2)
        self.assertEqual(a["brokerage"],60)
        self.assertEqual(a["buy_leg"]["brokerage"],20)
        self.assertEqual(a["sell_leg"]["brokerage"],40)
        b=z.estimate(buy_premium=180,sell_premium=182,quantity=90,broker_profile="zerodha_debit_balance")
        self.assertEqual(b["fees"]["brokerage"],80)
        self.assertAlmostEqual(b["fees"]["total_estimated"],133.10)
    def test_extra_spread_and_invalid_quantity(self):
        r=z.estimate(buy_premium=180,sell_premium=182,quantity=90,extra_spread_points=1)
        self.assertAlmostEqual(r["net_pnl_inr"],4.10)
        with self.assertRaises(ValueError):
            z.estimate(buy_premium=180,sell_premium=182,quantity=0)


if __name__=="__main__":
    unittest.main()
