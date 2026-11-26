"""Offline synthetic evidence tests; no broker calls, real orders or real P&L."""
from collections import Counter
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from workstation_api import auto_paper_engine as engine, auto_paper_selection as selector
from workstation_api import paper_execution as paper, advanced_options as ao

NOW=datetime(2026,11,26,5,0,5,tzinfo=timezone.utc)
EXPIRY="2026-11-26"
CONFIG={**engine.DEFAULTS,"enabled":True,"capital":17000.,"max_loss":4250.,
        "target_net":100.,"hold_seconds":60,"exit_mode":"target_stop"}


def make_book(identity,strike,side,stamp=NOW,mid=None):
    years=(datetime.combine(NOW.astimezone(paper.IST).date(),time(15,30),paper.IST)-NOW).total_seconds()/ao.YEAR_SECONDS
    model=ao.bsm(63000.,strike,years,selector.RATE,.22,side,selector.DIVIDEND)
    mid=model["price"] if mid is None else mid
    bid=max(.05,mid-.25);ask=mid+.25
    return {"identity":identity,"strike":strike,"option_type":side,"expiry":EXPIRY,
        "lot_size":30,"stamp":stamp,"received_utc":paper._iso(stamp),"digest":"a"*64,
        "bid":bid,"ask":ask,"spread_bps":(ask-bid)/mid*10000,
        "book":{"bid":[{"price":bid,"quantity":3000,"orders":10}],
                "ask":[{"price":ask,"quantity":3000,"orders":10}]},
        "sigma":.22,"years":years,"greeks":model,"oi":1000,"volume":2000,
        "activity":{"receipts_120s":12,"distinct_trade_times_120s":6}}


def signal(now,direction="UP"):
    return {"direction":direction,"spot":63000.,"scenario_move_points":200.,
        "chain_utc":paper._iso(now),"bar_utc":paper._iso(now-timedelta(seconds=65)),
        "valid_contracts":3,"subscribed_contracts":3,"rejections":{}}


class SelectionTests(TestCase):
    def test_selects_directional_and_vertical_with_budget_and_stress_gates(self):
        books=[make_book("NSE_FNO:1",63000.,"CE"),make_book("NSE_FNO:2",63100.,"CE"),
               make_book("NSE_FNO:3",63000.,"PE")]
        with patch.object(selector,"_source",return_value=(signal(NOW),books,None)):
            report,lanes=selector.select(NOW,CONFIG)
            for lane in lanes.values():
                self.assertEqual(lane["action"],"PAPER_ENTRY")
                chosen=lane["selected"]
                self.assertLessEqual(chosen["modeled_risk_inr"],4250.)
                self.assertGreaterEqual(chosen["stress_favorable_net_inr"],100.)
                self.assertTrue(1<=chosen["lots"]<=3)
            self.assertEqual(lanes["directional"]["selected"]["strategy"],"LONG_OPTION")
            self.assertEqual(lanes["directional"]["selected"]["legs"][0]["side"],"CE")
            self.assertEqual(lanes["spread"]["selected"]["strategy"],"bull_call_debit")
            _,blocked=selector.select(NOW,CONFIG,lane_caps={"directional":0.,"spread":1.})
            self.assertEqual(blocked["directional"]["reason"],"session_loss_budget_exhausted")
            self.assertEqual(blocked["spread"]["action"],"NO_TRADE")

    def test_missing_source_never_creates_entry(self):
        with patch.object(selector,"_source",return_value=(signal(NOW),[],"missing_fresh_chain")):
            _,result=selector.select(NOW,CONFIG)
        self.assertTrue(all(r["action"]=="NO_TRADE" and "selected" not in r for r in result.values()))


class JournalTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path=Path(self.tmp.name)/"paper.sqlite3"
        context=patch.object(engine,"_path",return_value=path)
        context.start();self.addCleanup(context.stop)
        self.config=dict(CONFIG)
        self.base=make_book("NSE_FNO:1",63000.,"CE",mid=90.)
        rejects=Counter()
        self.candidate=selector._candidate("LONG_OPTION",[self.base],self.config,signal(NOW),rejects)
        self.assertIsNotNone(self.candidate)
        self.report=signal(NOW)
        self.picks={"directional":{"action":"PAPER_ENTRY","reason":"test_eligible","selected":self.candidate,
                                   "candidates":[self.candidate],"rejections":{}},
                    "spread":{"action":"NO_TRADE","reason":"no_candidate_passed","candidates":[],"rejections":{}}}
        def source(now,config,lane_caps=None):
            return self.report,self.picks
        context=patch.object(selector,"select",side_effect=source)
        self.mock=context.start();self.addCleanup(context.stop)

    def get(self,now=NOW):
        return engine.status(now)

    def entry(self,identity,ready,end,now):
        self.assertEqual(identity,"NSE_FNO:1")
        self.assertLessEqual(ready,end)
        self.assertLessEqual(end,now)
        return make_book(identity,63000.,"CE",stamp=ready,mid=90.),None

    def test_enable_pause_and_causal_target_exit(self):
        engine.cycle(NOW)
        self.assertFalse(self.mock.called)
        engine.configure(self.config)
        engine.cycle(NOW)
        self.assertEqual(self.get()["lanes"]["directional"]["active"]["state"],"awaiting_entry")
        engine.cycle(NOW)
        self.assertEqual(self.get()["lanes"]["directional"]["decisions"],1)
        with patch.object(engine.replay,"_first",side_effect=self.entry):
            engine.cycle(NOW+timedelta(seconds=7))
        self.assertEqual(self.get()["lanes"]["directional"]["active"]["state"],"paper_open")
        engine.pause()
        mark={"mark_net_inr":150.,"mark_observed_utc":paper._iso(NOW+timedelta(seconds=10)),
              "mark_book_utc":paper._iso(NOW+timedelta(seconds=10))}
        with patch.object(engine,"_mark",return_value=mark):
            engine.cycle(NOW+timedelta(seconds=10))
        row=self.get()["lanes"]["directional"]["active"]
        self.assertEqual(row["exit_trigger"],"target_mark")
        self.assertEqual(row["state"],"awaiting_exit")
        # The mark is not the fill; use a later first-book receipt.
        def close(identity,ready,end,now):
            self.assertGreater(ready,NOW+timedelta(seconds=10))
            return make_book(identity,63000.,"CE",stamp=ready,mid=100.),None
        with patch.object(engine.replay,"_first",side_effect=close):
            engine.cycle(NOW+timedelta(seconds=17))
        row=self.get()["lanes"]["directional"]["latest"]
        self.assertEqual(row["state"],"complete")
        self.assertGreater(row["net_pnl_inr"],100.)
        self.assertNotEqual(row["net_pnl_inr"],150.)
        self.assertFalse(self.get()["broker_orders_enabled"])
        engine.cycle(NOW+timedelta(minutes=2))
        self.assertEqual(self.get()["lanes"]["directional"]["decisions"],1)

    def test_missing_exit_remains_unscored_and_blocks_lane(self):
        engine.configure(self.config)
        engine.cycle(NOW)
        with patch.object(engine.replay,"_first",side_effect=self.entry):
            engine.cycle(NOW+timedelta(seconds=7))
        engine.pause()
        engine.cycle(NOW+timedelta(seconds=62))
        self.assertEqual(self.get()["lanes"]["directional"]["active"]["exit_trigger"],"maximum_hold")
        with patch.object(engine.replay,"_first",return_value=(None,"no_book_in_fixed_window")):
            engine.cycle(NOW+timedelta(seconds=70))
        lane=self.get()["lanes"]["directional"]
        self.assertEqual(lane["censored"],1)
        self.assertIsNone(lane["conditional_net_inr"])
        self.assertTrue(lane["halted"])
        engine.configure(self.config)
        engine.cycle(NOW+timedelta(minutes=2))
        self.assertEqual(self.get()["lanes"]["directional"]["decisions"],1)

    def test_entry_reprice_rejects_over_budget(self):
        engine.configure(self.config)
        engine.cycle(NOW)
        def expensive(identity,ready,end,now):
            return make_book(identity,63000.,"CE",stamp=ready,mid=1000.),None
        with patch.object(engine.replay,"_first",side_effect=expensive):
            engine.cycle(NOW+timedelta(seconds=7))
        row=self.get()["lanes"]["directional"]["latest"]
        self.assertEqual(row["state"],"entry_rejected")
        self.assertEqual(row["entry_reason"],"entry_risk_or_cashflow_changed")

    def test_session_losses_reduce_risk_without_compounding_wins(self):
        day=NOW.astimezone(paper.IST).date().isoformat()
        with engine._db() as db:
            for i,pnl in enumerate((-1200.,700.)):
                minute=paper._iso(NOW+timedelta(minutes=i))
                db.execute("INSERT INTO decisions(lane,minute_utc,session_ist,state,body) VALUES(?,?,?,?,?)",
                    ("directional",minute,day,"complete",engine._encode({"net_pnl_inr":pnl})))
            self.assertEqual(engine._remaining_budget(db,NOW,self.config,"directional"),3050.)
            self.assertEqual(engine._remaining_budget(db,NOW,self.config,"spread"),4250.)

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            engine.configure({**self.config,"max_loss":20000})


    def test_no_trade_does_not_block_later_fresh_entry_same_minute(self):
        engine.configure(self.config)
        original=self.picks
        no={"action":"NO_TRADE","reason":"missing_fresh_book","candidates":[],"rejections":{}}
        self.picks={"directional":no,"spread":no}
        engine.cycle(NOW)
        self.assertEqual(self.get()["lanes"]["directional"]["no_trade"],1)
        self.picks=original
        engine.cycle(NOW+timedelta(seconds=5))
        lane=self.get()["lanes"]["directional"]
        self.assertEqual(lane["decisions"],2)
        self.assertEqual(lane["active"]["state"],"awaiting_entry")
        engine.cycle(NOW+timedelta(seconds=5))
        self.assertEqual(self.get()["lanes"]["directional"]["decisions"],2)

    def test_reversal_trigger_uses_later_observation_not_entry_mark(self):
        self.config["exit_mode"]="signal_reversal"
        engine.configure(self.config)
        engine.cycle(NOW)
        with patch.object(engine.replay,"_first",side_effect=self.entry):
            engine.cycle(NOW+timedelta(seconds=7))
        observed=NOW+timedelta(seconds=15)
        opposite={"last_observed_utc":paper._iso(observed-timedelta(seconds=70)),
                  "contiguous_session_bars":40,"ema9":62900.,"ema21":63000.}
        mark={"mark_net_inr":20.,"mark_observed_utc":paper._iso(observed),"mark_book_utc":paper._iso(observed)}
        row=self.get()["lanes"]["directional"]["active"]
        engine._monitor(row,observed,mark_lookup=lambda *_:mark,signal_lookup=lambda _:opposite)
        row=self.get()["lanes"]["directional"]["active"]
        self.assertEqual(row["exit_trigger"],"signal_reversal")
        self.assertEqual(row["exit_decision_utc"],paper._iso(observed))
        self.assertNotIn("net_pnl_inr",row)

    def test_legacy_enabled_settings_are_not_silently_changed(self):
        old={k:v for k,v in self.config.items() if k not in engine.policy.DEFAULTS}
        with engine._db() as db:
            db.execute("INSERT INTO settings VALUES(1,?)",(engine._encode(old),))
            current=engine._settings(db)
        self.assertEqual(current["exit_mode"],"target_stop")
        self.assertEqual(current["slippage_bps"],5.)
        self.assertEqual(current["hold_seconds"],old["hold_seconds"])
        self.assertEqual(current["stop_net"],old["max_loss"])
