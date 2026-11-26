from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from workstation_api import scalping_validation as s


class ScalpingValidationTests(unittest.TestCase):
    def test_selection_uses_prior_quote_affordability_and_exact_terms(self):
        day=date(2026,11,24)
        def row(side,identity,ask):
            return {"identity":identity,"option_type":side,"expiry":"2026-12-29",
                    "strike":63000,"lot_size":30,"contract_master_verified":True,
                    "bid":ask-1,"ask":ask,"top_bid_quantity":300,"top_ask_quantity":300,"quote_valid":True}
        snapshot={"expiry":"2026-12-29","underlying_spot":63000,"market_master_fresh":True,
                  "contracts":[row("CE","NSE_FNO:1",180),row("PE","NSE_FNO:2",175),row("CE","NSE_FNO:3",200)]}
        selected=s._select(snapshot,day,capital=17000,lots=3,target_premium=180,tolerance=60,
                          max_spread_bps=150,fee_floor_per_side=50)
        self.assertEqual(selected["CE"]["identity"],"NSE_FNO:1")
        self.assertEqual(selected["PE"]["identity"],"NSE_FNO:2")
        self.assertIsNone(s._select(snapshot,day,capital=1000,lots=3,target_premium=180,tolerance=60,
                          max_spread_bps=150,fee_floor_per_side=50))

    def test_missing_entry_censors_instead_of_reallocating(self):
        start=datetime(2026,11,24,4,15,tzinfo=timezone.utc)
        rows=[{"decision":start+timedelta(minutes=i)} for i in (1,10)]
        sel={"CE":{"identity":"NSE_FNO:1","option_type":"CE","expiry":"2026-12-29","strike":63000,"lot_size":30}}
        with patch.object(s.replay,"rule_signals",return_value=["UP","UP"]),patch.object(s.replay,"replay",return_value={
             "state":"entry_unobservable","entries":[],"exits":[],"net_pnl_inr":None,"missing":[{"reason":"no_book"}]}) as mock:
            r=s._replay_day(rows,sel,rule="RANGE_REVERSION",start=start,close=start+timedelta(hours=5),
               now=start+timedelta(days=1),capital=17000,lots=3,hold_minutes=5,latency_ms=1000,
               window_seconds=30,participation_pct=25,slippage_bps=5,broker_profile="zerodha",
               fee_floor_per_side=50,daily_loss_limit_pct=10)
        self.assertEqual(mock.call_count,1)
        self.assertFalse(r["complete"])
        self.assertIsNone(r["session_net_inr"])
        self.assertEqual(r["reasons"]["no_book"],1)

    def test_aggregate_matched_subset_and_stress(self):
        def day(complete):
            return {"matched_complete":complete,"rules":[{"rule":rule,"session_net_inr":100.,
                    "max_closed_trade_drawdown_inr":5.,"trades":[{"net_pnl_inr":100.,"fees_inr":100.}]}
                    for rule in s.RULES]}
        report=s._aggregate([day(True),day(False)])
        self.assertEqual(len(report),3)
        self.assertTrue(all(r["matched_sessions"]==1 and r["net_pnl_inr"]==100 and r["stress_extra_50_inr"]==50 for r in report))

    def test_missing_dates_no_profit_claim(self):
        now=datetime(2026,11,26,4,0,tzinfo=timezone.utc)
        with patch.object(s,"_index",return_value=([],"partial_or_missing_index_minutes")):
            r=s.run(start_date="2026-11-23",end_date="2026-11-25",now=now,save=False)
        self.assertEqual(r["matched_days"],0)
        self.assertEqual(r["state"],"insufficient_evaluation_evidence")
        self.assertTrue(all(x["net_pnl_inr"] is None for x in r["evaluation"]))


if __name__=="__main__":
    unittest.main()
