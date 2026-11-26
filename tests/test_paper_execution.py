"""Synthetic deterministic execution tests; no broker or actual market trades."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
from workstation_api import paper_execution as paper, depth_replay as replay
from workstation_api import live_market, service, option_chain_live

NOW=datetime(2026,11,24,5,0,tzinfo=timezone.utc)
EXPIRY="2026-11-24"
CE="NSE_FNO:1001"
PE="NSE_FNO:1002"
HIGH="NSE_FNO:1003"

def terms(identity):
    return {"identity":identity,"symbol":"FIXTURE"+identity,
            "expiry":EXPIRY,"strike":63100. if identity==HIGH else 63000.,
            "option_type":"PE" if identity==PE else "CE","lot_size":30}

class PaperExecutionTests(TestCase):
    def setUp(self):
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p=patch.object(service,"DATA",Path(folder.name)/"data")
        p.start();self.addCleanup(p.stop)
        p=patch.object(live_market,"DB_INITIALIZED",False)
        p.start();self.addCleanup(p.stop)
        p=patch.object(option_chain_live,"_contracts",return_value={
            "fresh":True,"by_id":{i.split(":")[1]:terms(i) for i in (CE,PE,HIGH)}})
        p.start();self.addCleanup(p.stop)
        live_market._init_db()

    def save(self,t,identity=CE,*,bid=99.,ask=100.,qty=600,key=None):
        c=terms(identity)
        stamp=paper._iso(t)
        key=key or identity+stamp
        bd=sha256(("bid"+key).encode()).hexdigest()
        ad=sha256(("ask"+key).encode()).hexdigest()
        digest=sha256((bd+ad).encode()).hexdigest()
        book={"identity":identity,"received_utc":stamp,"timestamp_kind":"local_receive",
              "source":"original_Dhan_full_market_depth_websocket",
              "collection_mode":"auto_banknifty_20_level",
              "bid_packet_sha256":bd,"ask_packet_sha256":ad,
              "bid":[{"price":round(bid-.05*i,2),"quantity":qty,"orders":1} for i in range(20)],
              "ask":[{"price":round(ask+.05*i,2),"quantity":qty,"orders":1} for i in range(20)],
              "computed_features":{"lot_size_verified":30,"expiry":EXPIRY,
                  "strike":c["strike"],"side":c["option_type"]}}
        with live_market._database() as db:
            db.execute("INSERT INTO live_depth_books VALUES(?,?,?,?,?)",
                       (identity,stamp,"fixture",json.dumps(book),digest))
        return book

    def account(self,risk=100):
        return paper.create_account("Offline fixture",17000,risk_pct=risk,now=NOW)["id"]

    def test_protected_market_uses_first_future_book_and_cancels_partial_remainder(self):
        aid=self.account()
        self.save(NOW-timedelta(seconds=1),ask=95.,bid=94.)
        o=paper.submit(aid,CE,"BUY","PROTECTED_MARKET",2,100.21,
                       latency_ms=1000,participation_pct=100,slippage_bps=0,now=NOW)
        before=paper.overview(aid,now=NOW)
        self.assertGreater(before["reserved_cash"],6000)
        self.assertEqual(before["account"]["cash"],17000)
        self.save(NOW+timedelta(milliseconds=500),ask=95.,bid=94.)
        self.save(NOW+timedelta(seconds=2),qty=6)
        self.save(NOW+timedelta(seconds=3),qty=600,ask=90,bid=89)
        paper.cycle(now=NOW+timedelta(seconds=4))
        x=paper.overview(aid,now=NOW+timedelta(seconds=4))
        order=next(r for r in x["orders"] if r["id"]==o["id"])
        self.assertEqual(order["filled"],30)
        self.assertEqual(order["state"],"cancelled_partial")
        self.assertEqual(x["positions"][0]["quantity"],30)
        self.assertEqual(x["reserved_cash"],0)
        self.assertEqual(len(x["fills"]),1)
        self.assertEqual(x["fills"][0]["book_received_utc"],paper._iso(NOW+timedelta(seconds=2)))
        self.assertAlmostEqual(17000-x["account"]["cash"],x["positions"][0]["cost_basis"])
        self.assertFalse(x["broker_orders_enabled"])

    def test_limit_partial_repeated_packet_not_reused_and_sell_net_accounting(self):
        aid=self.account()
        o=paper.submit(aid,CE,"BUY","LIMIT",2,100.21,latency_ms=1000,
                       participation_pct=100,slippage_bps=0,now=NOW)
        self.save(NOW+timedelta(seconds=2),qty=6,key="first")
        paper.cycle(now=NOW+timedelta(seconds=3))
        x=paper.overview(aid,now=NOW+timedelta(seconds=3))
        self.assertEqual(x["orders"][0]["state"],"partially_filled")
        self.assertEqual(x["orders"][0]["filled"],30)
        self.assertGreater(x["reserved_cash"],0)
        self.save(NOW+timedelta(seconds=4),qty=6,key="first")
        paper.cycle(now=NOW+timedelta(seconds=5))
        self.assertEqual(paper.overview(aid,now=NOW+timedelta(seconds=5))["orders"][0]["filled"],30)
        self.save(NOW+timedelta(seconds=6),qty=6,key="second")
        paper.cycle(now=NOW+timedelta(seconds=7))
        x=paper.overview(aid,now=NOW+timedelta(seconds=7))
        self.assertEqual(x["orders"][0]["state"],"filled")
        self.assertEqual(x["positions"][0]["quantity"],60)
        self.assertEqual(x["reserved_cash"],0)
        buy_fees=paper._fees("BUY",x["orders"][0]["turnover"],"zerodha")
        self.assertAlmostEqual(sum(f["incremental_fees"] for f in x["fills"]),buy_fees)
        with self.assertRaises(ValueError):
            paper.submit(aid,CE,"SELL","LIMIT",3,90.,now=NOW+timedelta(seconds=7))
        paper.submit(aid,CE,"SELL","PROTECTED_MARKET",2,90.,now=NOW+timedelta(seconds=8),
                     participation_pct=100,slippage_bps=0)
        self.save(NOW+timedelta(seconds=10),bid=110.,ask=111.)
        paper.cycle(now=NOW+timedelta(seconds=11))
        closed=paper.overview(aid,now=NOW+timedelta(seconds=11))
        self.assertEqual(closed["positions"],[])
        self.assertAlmostEqual(closed["account"]["cash"]-17000,closed["account"]["realized"],places=2)
        self.assertEqual(closed["equity"],closed["account"]["cash"])

    def test_cancel_excludes_later_book_and_missing_window_is_not_fill(self):
        aid=self.account()
        o=paper.submit(aid,CE,"BUY","LIMIT",1,120.,now=NOW)
        paper.request_cancel(o["id"],now=NOW+timedelta(seconds=3))
        self.save(NOW+timedelta(seconds=4))
        paper.cycle(now=NOW+timedelta(seconds=19))
        x=paper.overview(aid,now=NOW+timedelta(seconds=19))
        self.assertEqual(x["orders"][0]["state"],"cancelled")
        self.assertEqual(x["account"]["cash"],17000)
        paper.submit(aid,PE,"BUY","LIMIT",1,120.,ttl_seconds=2,now=NOW+timedelta(seconds=20))
        paper.cycle(now=NOW+timedelta(seconds=40))
        x=paper.overview(aid,now=NOW+timedelta(seconds=40))
        self.assertEqual(x["orders"][0]["state"],"unobservable")
        self.assertEqual(x["available_cash"],17000)
        self.assertEqual(x["fills"],[])

    def test_risk_and_inventory_rejection(self):
        aid=self.account(risk=25)
        with self.assertRaises(ValueError):
            paper.submit(aid,CE,"BUY","LIMIT",2,100.,now=NOW)
        with self.assertRaises(ValueError):
            paper.submit(aid,CE,"SELL","LIMIT",1,100.,now=NOW)
        self.assertEqual(paper.overview(aid,now=NOW)["orders"],[])

    def test_single_replay_first_windows_and_fees(self):
        self.save(NOW+timedelta(milliseconds=500),bid=49,ask=50)
        self.save(NOW+timedelta(seconds=2),bid=99,ask=100)
        self.save(NOW+timedelta(seconds=4),bid=79,ask=80)
        self.save(NOW+timedelta(seconds=64),bid=110,ask=111)
        self.save(NOW+timedelta(seconds=66),bid=149,ask=150)
        x=replay.replay(strategy="LONG_OPTION",identities=[CE],
            decision_utc=paper._iso(NOW),hold_minutes=1,window_seconds=10,
            participation_pct=100,slippage_bps=0,now=NOW+timedelta(minutes=3))
        self.assertEqual(x["state"],"complete_conditional_quote_replay")
        self.assertEqual(x["entries"][0]["vwap"],100)
        self.assertEqual(x["exits"][0]["vwap"],110)
        self.assertAlmostEqual(x["net_pnl_inr"],300-x["total_fees_inr"],places=2)
        self.assertFalse(x["broker_margin_verified"])

    def test_subminute_replay_does_not_select_best_later_exit(self):
        self.save(NOW+timedelta(seconds=2),bid=99,ask=100)
        self.save(NOW+timedelta(seconds=8),bid=110,ask=111)
        self.save(NOW+timedelta(seconds=9),bid=140,ask=141)
        x=replay.replay(strategy="LONG_OPTION",identities=[CE],decision_utc=paper._iso(NOW),
            hold_seconds=5,window_seconds=5,participation_pct=100,slippage_bps=0,
            now=NOW+timedelta(minutes=1))
        self.assertTrue(x["exit_complete"])
        self.assertEqual(x["entries"][0]["original_best_bid"],99)
        self.assertEqual(x["exits"][0]["vwap"],110)

    def test_multi_leg_replay_requires_synchronized_terms_and_full_exit(self):
        self.save(NOW+timedelta(seconds=2),CE,bid=99,ask=100)
        self.save(NOW+timedelta(seconds=3),HIGH,bid=49,ask=50)
        self.save(NOW+timedelta(seconds=65),CE,bid=110,ask=111)
        self.save(NOW+timedelta(seconds=66),HIGH,bid=54,ask=55)
        args=dict(strategy="bull_call_debit",identities=[CE,HIGH],
            decision_utc=paper._iso(NOW),hold_minutes=1,window_seconds=10,
            participation_pct=100,slippage_bps=0,now=NOW+timedelta(minutes=3))
        x=replay.replay(**args)
        self.assertEqual(x["state"],"complete_conditional_quote_replay")
        self.assertEqual(x["entries"][1]["action"],"SELL")
        self.assertEqual(x["exits"][1]["action"],"BUY")
        self.assertAlmostEqual(x["net_pnl_inr"],120-x["total_fees_inr"],places=2)
        y=replay.replay(**args,max_skew_seconds=.5)
        self.assertEqual(y["state"],"entry_leg_skew_exceeded")
        self.assertIsNone(y["net_pnl_inr"])
        z=replay.replay(**{**args,"hold_minutes":2})
        self.assertEqual(z["state"],"exit_unobservable")
        self.assertIsNone(z["net_pnl_inr"])

    def test_rule_flip_submits_only_after_previous_observed_exit(self):
        rows=[{"decision":NOW+timedelta(minutes=i),"timestamp_utc":paper._iso(NOW+timedelta(minutes=i-1)),
               "session_ist":EXPIRY,"close":63000.+i} for i in range(4)]
        after=NOW+timedelta(minutes=2,seconds=5)
        complete={"entries":[{"option_type":"CE"}],"net_pnl_inr":100.,
                  "state":"complete_conditional_quote_replay","exit_received_utc":paper._iso(after),
                  "entry_complete":True}
        unresolved={"entries":[{"option_type":"PE"}],"net_pnl_inr":None,
                    "state":"exit_unobservable","entry_complete":True}
        with patch.object(replay,"_bars",return_value=rows),patch.object(replay,"rule_signals",
            return_value=["HOLD","UP","DOWN","HOLD"]),patch.object(replay,"replay",
            side_effect=[complete,unresolved]) as run:
            x=replay.rule_replay(day=EXPIRY,call_identity=CE,put_identity=PE,
                                 hold_rule="FLIP",now=NOW+timedelta(hours=1))
        self.assertEqual(run.call_count,2)
        self.assertEqual(run.call_args_list[1].kwargs["identities"],[PE])
        self.assertGreater(datetime.fromisoformat(run.call_args_list[1].kwargs["decision_utc"]),after)
        self.assertTrue(x["unresolved"])
        self.assertIsNone(x["net_pnl_inr"])
        self.assertEqual(x["completed_subset_net_pnl_inr"],100.)
