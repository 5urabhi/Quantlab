"""Synthetic causal, cap accounting, provenance, and ML support checks."""
from datetime import date,timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import numpy as np
import pandas as pd
from workstation_api import banknifty_target_capped_ml as m, banknifty_math_target as math


class CappedMathTests(TestCase):
    def test_large_winner_capped_without_clipping_loss(self):
        op=np.array([[100,100,100,140,140,140,140],[100,100,100,80,80,80,80]],float)
        cl=np.array([[100,120,120,120,120,120,120],[100,90,90,90,90,90,90]],float)
        got=math._forecast_returns(op,cl,5,30,30)
        self.assertAlmostEqual(got["expected_net_return"],.08)
        self.assertAlmostEqual(got["expected_target_capped_return"],-.06)
        self.assertEqual(got["realized_target_probability"],.5)

    def test_capped_account_retains_gap_stress(self):
        a={"session":"2026-10-01","decision_utc":"a","debit":10000.,"planned_funding":10060.}
        b={"session":"2026-10-02","decision_utc":"b","debit":9000.,"planned_funding":9060.}
        c={"session":"2026-10-02","decision_utc":"c","debit":9000.,"planned_funding":9060.}
        journal=[{"session":a["session"],"decision_utc":"a","state":"complete","reason":"target","net":3000.},
                 {"session":b["session"],"decision_utc":"b","state":"complete","reason":"monitoring_gap_exit","net":100.},
                 {"session":c["session"],"decision_utc":"c","state":"complete","reason":"stop","net":-700.}]
        v=m.capped_account({"scored_trades":3},journal,[a,b,c])
        self.assertEqual(v["target_capped_net_inr"],400.)
        self.assertEqual(v["profit_above_target_inr"],2000.)
        self.assertEqual(v["target_capped_stress_inr"],-8760.)
        self.assertEqual(v["capped_stress_without_best_day_inr"],-9760.)

    def test_daily_provenance_and_prior_day_only(self):
        with TemporaryDirectory() as d:
            folder=Path(d)
            dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(100)]
            names=[f"NSE_EQ_{i}" for i in range(20)]
            frame=pd.DataFrame({"date":dates,**{s:[100.+i*.1+(i%7)*.1+j*.01 for i in range(100)] for j,s in enumerate(names)}})
            path=folder/"daily_prices.csv"
            manifest=folder/"SHARED_MARKET_PROVENANCE.json"
            def publish():
                frame.to_csv(path,index=False)
                manifest.write_text(json.dumps({"daily_sha256":sha256(path.read_bytes()).hexdigest(),
                    "columns":[{"column":s,"exchange_segment":"NSE_EQ"} for s in names]}))
            publish()
            with patch.object(m.shared,"shared_folder",return_value=folder), patch.object(m.equity,"original_panel",return_value=(pd.DataFrame(),{"state":"unavailable"})):
                first,meta=m.daily_context([dates[90],dates[91]])
                self.assertEqual(meta["state"],"loaded")
                self.assertIn(dates[90],first)
                frame.loc[90:,names]=100000.
                publish()
                second,_=m.daily_context([dates[90],dates[91]])
                self.assertEqual(first[dates[90]],second[dates[90]])
                path.write_text("changed without provenance")
                self.assertEqual(m.daily_context([dates[90]])[1]["state"],"unavailable")

    def test_regularized_models_require_real_target_support(self):
        rows=[]
        for day in range(12):
            for i in range(10):
                y=i%2
                rows.append({"day":str(day),"x":[float(y),float(i)],
                             "daily":[float(day)],"target":y,"utility":.02 if y else -.03})
        model,meta=m.fit(rows)
        self.assertEqual(meta["state"],"fitted")
        self.assertAlmostEqual(meta["training_day_weighted_base_rate"],.5)
        self.assertAlmostEqual(model[2],.5)
        self.assertIsNotNone(model)
        daily,meta=m.fit(rows,daily=True)
        self.assertEqual(meta["state"],"fitted")
        self.assertIsNotNone(daily)
        model,meta=m.fit([{**x,"target":0} for x in rows])
        self.assertIsNone(model)
        self.assertEqual(meta["state"],"insufficient_support")
        self.assertIsNone(m.fit(rows[:20])[0])

    def test_missing_and_limit_rejected_labels_differ(self):
        for state,utility in (("missing_entry",-1.),("entry_limit_exceeded",0.)):
            result=m.label({"state":state,"planned_funding":10000.})
            self.assertEqual(result,(0,utility,False))

    def test_iv_stress_leaves_entry_unchanged(self):
        hold=30
        scenario={"opens":np.full((2,hold+2),63000.),"closes":np.full((2,hold+2),63000.)}
        t=np.full(hold+2,10/365)
        base=math.price(scenario["opens"],63000.,t,.2,"CALL")
        down,up=math.iv_stress_paths(scenario,63000.,t,t,.2,"CALL",hold)
        np.testing.assert_allclose(down[0][:,1],base[:,1])
        np.testing.assert_allclose(up[0][:,1],base[:,1])
        self.assertTrue(np.all(down[0][:,-1]<base[:,-1]))
        self.assertTrue(np.all(up[0][:,-1]>base[:,-1]))

    def test_standing_target_touch_does_not_claim_ambiguous_fill(self):
        day="2026-10-06";strike=63000
        ep={"state":"entered","entry":300.,"units":30,"session":day,"minute":4,"side":"CALL","strike":strike}
        result={"state":"complete","exit_request_utc":m.r._stamp(day,9)}
        def quote(high,low):
            return {"session_ist":day,"expiry_flag":"MONTH","expiry_code":1,"open":300.,"close":300.,"volume":100,
                    "high":high,"low":low}
        table={m.r._stamp(day,6):{("CALL",strike):quote(335.,285.)}}
        self.assertEqual(m.limit_touch(ep,result,table),"ambiguous_both_touched")
        table[m.r._stamp(day,6)][("CALL",strike)]=quote(335.,290.)
        self.assertEqual(m.limit_touch(ep,result,table),"target_traded_through_first")
        table[m.r._stamp(day,6)][("CALL",strike)]=quote(331.,290.)
        self.assertEqual(m.limit_touch(ep,result,table),"monitoring_gap")

    def test_shared_fourteen_columns_uses_verified_original_fallback(self):
        clocks=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(110)]
        raw=pd.DataFrame({f"NSE_EQ_{i}":[100.+j*.1+(j%7)*.1+i*.01 for j in range(len(clocks))]
                          for i in range(22)},index=clocks)
        raw_meta={"state":"loaded","source":"original_verified_equity_cache"}
        with patch.object(m,"_shared_daily_panel",return_value=(pd.DataFrame(),{"state":"unavailable","nse_equity_columns":14})), \
             patch.object(m.equity,"original_panel",return_value=(raw,raw_meta)):
            context,meta=m.daily_context(clocks[100:105])
        self.assertEqual(meta["state"],"loaded")
        self.assertEqual(meta["source"],"original_verified_equity_cache")
        self.assertEqual(meta["shared_view"]["nse_equity_columns"],14)
        self.assertEqual(meta["matched_days"],5)
        self.assertEqual(meta["context_source_dates"][clocks[101]],clocks[100])

    def test_daily_context_refuses_missing_known_index_session(self):
        clocks=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(110)]
        frame=pd.DataFrame({f"NSE_EQ_{i}":[100.+j*.1+(j%7)*.1+i*.01 for j in range(len(clocks))]
                            for i in range(22)},index=clocks)
        frame=frame.drop(index=clocks[101])
        context,_=m._context_features(frame,clocks[100:105])
        self.assertIn(clocks[101],context)
        self.assertNotIn(clocks[102],context)
        self.assertNotIn(clocks[103],context)

    def test_training_constant_rate_weights_sessions_not_rows(self):
        rows=[]
        for day in range(10):
            n=20 if day==0 else 10
            y=1 if day==0 else 0
            for i in range(n):
                rows.append({"day":str(day),"x":[float(i),float(day)],"daily":None,
                             "target":y,"utility":.02 if y else -.03})
        model,meta=m.fit(rows)
        self.assertIsNotNone(model)
        self.assertAlmostEqual(model[2],.1)
        self.assertAlmostEqual(meta["training_day_weighted_base_rate"],.1)
