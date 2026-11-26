from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import csv
import sqlite3

from workstation_api import dynamic_exit_policy as policy, dynamic_strategy_research as research
from workstation_api import auto_paper_engine as engine, auto_paper_selection as select
from workstation_api import paper_execution as paper

NOW=datetime(2026,11,26,5,0,5,tzinfo=timezone.utc)


class PolicyTests(TestCase):
    def row(self,mode="adaptive"):
        return {"config":{**engine.DEFAULTS,"exit_mode":mode,"target_net":100.,"stop_net":250.,
                          "trail_net":50.,"liquidity_grace_seconds":20},
                "risk_budget_inr":4250.,"source":{"direction":"UP"},
                "hold_deadline_utc":paper._iso(NOW+timedelta(minutes=30)),
                "peak_net_inr":None}

    def test_trailing_arms_and_waits_for_retracement(self):
        r=self.row("trailing")
        trigger,updates=policy.evaluate(r,NOW,{"mark_net_inr":150.})
        self.assertIsNone(trigger);self.assertTrue(updates["trail_armed"])
        self.assertEqual(updates["trail_floor_inr"],100.)
        r.update(updates)
        trigger,updates=policy.evaluate(r,NOW+timedelta(seconds=5),{"mark_net_inr":230.})
        self.assertIsNone(trigger);r.update(updates)
        self.assertEqual(r["trail_floor_inr"],180.)
        self.assertEqual(policy.evaluate(r,NOW+timedelta(seconds=10),{"mark_net_inr":179.})[0],"trailing_stop")

    def test_fresh_ema_reversal_not_neutral_or_stale(self):
        r=self.row("signal_reversal")
        signal={"last_observed_utc":paper._iso(NOW-timedelta(seconds=65)),
                "contiguous_session_bars":35,"ema9":62990.,"ema21":63000.}
        self.assertEqual(policy.evaluate(r,NOW,None,signal)[0],"signal_reversal")
        self.assertIsNone(policy.evaluate(r,NOW+timedelta(seconds=40),None,signal)[0])
        self.assertIsNone(policy.evaluate(r,NOW,None,{**signal,"ema9":63000.})[0])
        self.assertIsNone(policy.evaluate(r,NOW,None,{**signal,"contiguous_session_bars":10})[0])

    def test_liquidity_needs_sustained_bad_observations(self):
        r=self.row()
        reason,update=policy.evaluate(r,NOW,None)
        self.assertIsNone(reason);r.update(update)
        self.assertIsNone(policy.evaluate(r,NOW+timedelta(seconds=15),None)[0])
        self.assertEqual(policy.evaluate(r,NOW+timedelta(seconds=20),None)[0],"liquidity_deterioration")
        reason,update=policy.evaluate(r,NOW+timedelta(seconds=20),{"mark_net_inr":10.})
        self.assertIsNone(reason);r.update(update)
        self.assertIsNone(r["liquidity_bad_since_utc"])

    def test_hard_loss_and_hold_guards(self):
        for mode in policy.MODES:
            r=self.row(mode)
            self.assertEqual(policy.evaluate(r,NOW,{"mark_net_inr":-251.})[0],"loss_mark")
            self.assertEqual(policy.evaluate(r,NOW+timedelta(minutes=30),None)[0],"maximum_hold")
        self.assertEqual(policy.evaluate(self.row("target_stop"),NOW,{"mark_net_inr":101.})[0],"target_mark")
        self.assertIsNone(policy.evaluate(self.row("fixed"),NOW,{"mark_net_inr":101.})[0])


def book(stamp,mid):
    return {"identity":"NSE_FNO:1","strike":63000.,"option_type":"CE","expiry":"2026-12-29",
            "lot_size":30,"stamp":stamp,"received_utc":paper._iso(stamp),"digest":"a"*64,
            "bid":mid-.25,"ask":mid+.25,"spread_bps":.5/mid*10000,
            "book":{"bid":[{"price":mid-.25,"quantity":3000,"orders":10}],
                    "ask":[{"price":mid+.25,"quantity":3000,"orders":10}]}}


class HistoricalPolicyTests(TestCase):
    def test_chronological_comparison_uses_shared_transitions_and_isolated_cash(self):
        candidate={"strategy":"LONG_OPTION","identities":["NSE_FNO:1"],"lots":1,"units":30,"lot_size":30,
                   "legs":[{"identity":"NSE_FNO:1","strike":63000.,"expiry":"2026-12-29","side":"CE"}]}
        def signals(day,anchors,end,*,snapshot_sink):
            direction={}
            for i,t in enumerate(anchors):
                if t in (NOW,NOW+timedelta(seconds=20)):
                    up=t==NOW
                    snapshot_sink[i]={"direction":"UP" if up else "DOWN",
                        "last_observed_utc":paper._iso(t-timedelta(seconds=65)),
                        "contiguous_session_bars":40,"ema9":63100. if up else 62900.,"ema21":63000.}
                    direction[i]=snapshot_sink[i]["direction"]
            return direction,{"state":"available","valid":2,"up":1,"down":1,"neutral":0,"ticks":100}
        source_calls=[]
        def source(now,cfg,*,historical,signal_override):
            self.assertTrue(historical);self.assertEqual(now,NOW)
            self.assertEqual(cfg["hold_seconds"],300)
            source_calls.append(now)
            return {"direction":"UP"},[],None
        def picks(report,books,reason,cfg,caps):
            return report,{"directional":{"action":"PAPER_ENTRY","selected":candidate}}
        def first(db,identity,ready,end,observed):
            self.assertLessEqual(ready,end);self.assertLessEqual(end,observed)
            return book(ready,90. if ready<NOW+timedelta(seconds=10) else 100.),None
        with TemporaryDirectory() as tmp, \
             patch.object(research,"_root",return_value=Path(tmp)), \
             patch.object(research.batch,"signal_cohorts",side_effect=signals), \
             patch.object(select,"_source",side_effect=source), \
             patch.object(select,"from_source",side_effect=picks), \
             patch.object(research.replay.ao,"_read_database",side_effect=lambda:sqlite3.connect(":memory:")), \
             patch.object(research.replay,"_first_on_db",side_effect=first), \
             patch.object(select,"latest_book",side_effect=lambda db,identity,t:book(t,100.)):
            # Compare 1m fixed, target, trailing, reversal, adaptive on an
            # actual chronological state machine (not a mock P&L outcome).
            result=research.run(day="2026-11-26",hold_seconds=60,include_spreads=False,
                                now=NOW+timedelta(minutes=2))
            rows={r["policy"]:r for r in result["policies"]}
            self.assertEqual(len(rows),5)
            self.assertEqual(source_calls,[NOW])
            self.assertEqual(rows["signal_reversal"]["scored"],1)
            self.assertEqual(rows["signal_reversal"]["exit_reasons"],{"signal_reversal":1})
            self.assertLess(rows["signal_reversal"]["mean_hold_seconds"],rows["fixed_1m"]["mean_hold_seconds"])
            self.assertEqual(rows["fixed_1m"]["exit_reasons"],{"maximum_hold":1})
            self.assertTrue(all(r["entry_attempts"]==1 for r in rows.values()))
            self.assertFalse(result["broker_orders_enabled"])
            with research.result_path(result["run_id"]).open() as f:
                journal=list(csv.DictReader(f))
            self.assertEqual(len(journal),5)
            self.assertTrue(all(r["entry_utc"]<r["exit_utc"] for r in journal))

    def test_missing_tick_evidence_does_not_invent_trades(self):
        with TemporaryDirectory() as tmp, \
             patch.object(research,"_root",return_value=Path(tmp)), \
             patch.object(research.batch,"signal_cohorts",return_value=({},{"state":"missing_original_index_ticks",
                 "valid":0,"up":0,"down":0,"neutral":0,"ticks":0})):
            result=research.run(day="2026-11-26",now=NOW,hold_seconds=60,include_spreads=False)
            self.assertEqual(result["journal_count"],0)
            self.assertTrue(all(r["conditional_net_inr"] is None for r in result["policies"]))

    def test_historical_selection_ignores_future_chain(self):
        import json
        from hashlib import sha256
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"data.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE option_chain_observations(underlying,expiry,captured_utc,snapshot_sha256,normalized_json)")
                future=(NOW+timedelta(seconds=1)).isoformat()
                raw=json.dumps({"received_utc":future,"expiry":"2026-12-29","contracts":[]})
                db.execute("INSERT INTO option_chain_observations VALUES(?,?,?,?,?)",
                    ("BANKNIFTY","2026-12-29",future,sha256(raw.encode()).hexdigest(),raw))
            signal={"direction":"UP","last_observed_utc":paper._iso(NOW-timedelta(seconds=65)),
                "source_age_seconds":65,"ema9":63100.,"ema21":63000.,"rsi14":60.,"atr14":50.,
                "contiguous_session_bars":40,"quote_mode":"RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE"}
            with patch.object(select.ao,"_read_database",side_effect=lambda:sqlite3.connect(path)):
                _,books,reason=select._source(NOW,engine.DEFAULTS,historical=True,signal_override=signal)
            self.assertEqual(reason,"missing_fresh_chain")
            self.assertEqual(books,[])
