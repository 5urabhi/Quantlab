import unittest
import json
from unittest.mock import patch
from workstation_api import zerodha_execution_costs as z, liquidity_spreads as fees, zerodha_fallback as kite


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
    def test_virtual_note_uses_only_calculation_endpoint(self):
        def request(path,**kw):
            self.assertEqual(path,"/charges/orders")
            self.assertEqual(kw["method"],"POST")
            rows=[{**r,"price":r["average_price"],"charges":{"brokerage":20,
                   "transaction_tax":0,"exchange_turnover_charge":5,"sebi_turnover_charge":0,
                   "stamp_duty":0,"gst":{"total":4.5},"total":29.5}} for r in kw["json_body"]]
            return json.dumps({"status":"success","data":rows}).encode()
        with patch.object(z,"_guard"),patch.object(kite,"_request",side_effect=request):
            r=z.virtual_note(tradingsymbol="BANKNIFTY26DEC63500CE",quantity=90,buy_premium=180,sell_premium=182)
        self.assertEqual(r["broker_estimated_total"],59.)
        self.assertFalse(r["orders_enabled"])
        with self.assertRaises(ValueError):
            kite._request("/orders/regular",method="POST",json_body=[{}])
    def test_positions_are_separate_and_read_only(self):
        raw=json.dumps({"status":"success","data":{"net":[
            {"exchange":"NFO","tradingsymbol":"BANKNIFTY26DEC63500CE","quantity":-30,"product":"NRML","pnl":12.3},
            {"exchange":"NFO","tradingsymbol":"NIFTY26DEC25000CE","quantity":30},
            {"exchange":"NFO","tradingsymbol":"BANKNIFTY26DEC63500PE","quantity":0}]}}).encode()
        with patch.object(z,"_guard"),patch.object(kite,"_request",return_value=raw) as req:
            r=z.positions()
        req.assert_called_once_with("/portfolio/positions",method="GET")
        self.assertEqual(len(r["rows"]),1)
        self.assertEqual(r["rows"][0]["quantity"],-30)
        self.assertFalse(r["orders_enabled"])
    def test_extra_spread_and_invalid_quantity(self):
        r=z.estimate(buy_premium=180,sell_premium=182,quantity=90,extra_spread_points=1)
        self.assertAlmostEqual(r["net_pnl_inr"],4.10)
        with self.assertRaises(ValueError):
            z.estimate(buy_premium=180,sell_premium=182,quantity=0)


if __name__=="__main__":
    unittest.main()
