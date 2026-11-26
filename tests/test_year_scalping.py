import unittest
from datetime import date,datetime,timedelta,timezone
from unittest.mock import patch
from workstation_api import year_scalping as y, expired_options_backtest as exp


class YearScalpingTests(unittest.TestCase):
    def test_grid_and_development_only_choice(self):
        configs=y.candidates(3,True)
        self.assertEqual(len(configs),198)
        c1,c2=configs[:2]
        row={"complete":True,"net":100,"trades":2,"wins":2,"losses":0,"positive":100,"negative":0,"fees":80,"drawdown_pct":0,"unscored":{}}
        records={c1["id"]:{str(i):row for i in range(15)},
                 c2["id"]:{str(i):{**row,"net":90} for i in range(15)}}
        days=y._matched(records,[c1,c2])
        self.assertEqual(len(days),15)
        self.assertEqual(y._winner([c1,c2],records,days),c1)
        self.assertIsNone(y._winner([c1,c2],records,days[:14]))

    def test_no_data_not_positive_profit(self):
        with patch.object(y.market_patterns,"_history",return_value={"complete":{},"days":{}}),patch.object(y,"_catalog",return_value=([],0)):
            r=y.run(start_date="2026-11-20",end_date="2026-11-24",today=date(2026,11,26),save=False)
        self.assertIsNone(r["selected"])
        self.assertIsNone(r["test"]["net_inr"])
        self.assertEqual(r["state"],"insufficient_heldout_evidence")

    def test_target_stop_next_open_not_trigger_price(self):
        t=datetime(2026,11,24,4,0,tzinfo=timezone.utc)
        candles={(t.isoformat(),"CALL"):{63000.:{"session_ist":"2026-11-24","close":182.}}}
        exit_at,reason=exp._exit_decision("fixed",entry_at=t,entry_premium=180.,side="CALL",
            strike=63000.,day="2026-11-24",signals={},candles=candles,hold=5,cap=5,
            stop_pct=2.5,target_pct=5,target_points=2.,stop_points=2.)
        self.assertEqual(exit_at,t+timedelta(minutes=1))
        self.assertEqual(reason,"target_close_next_open")

    def test_censored_trade_path_not_zero_profit(self):
        c=y.candidates(1,False)[0]
        with patch.object(exp,"simulate_options",return_value={"trades":[],"unscored":{"missing_exact_contract_path":1},
                "net_pnl_inr":0,"total_assumed_fees_inr":0,"max_closed_trade_drawdown_pct":0}):
            r=y._daily([],{},[],c,{"target_premium":180,"tolerance":60,"lot_size":30,"capital":17000,"slippage_bps":5})
        self.assertFalse(r["complete"])
        self.assertIsNone(y._summary([r])["net_inr"])


if __name__=="__main__":
    unittest.main()
