"""Offline synthetic fixtures, not claims of live fills or actual P&L."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from workstation_api import spread_readiness as r, paper_execution as p

START=datetime(2026,11,26,3,45,tzinfo=timezone.utc)
NOW=START+timedelta(seconds=10,microseconds=500000)
DAY="2026-11-26"


def book(identity,stamp,ask,quantity=2000,strike=63000,side="CE"):
    bid=ask-1
    b="a"*64
    a="b"*64
    return {"identity":identity,"received_utc":p._iso(stamp),
            "source":"original_Dhan_full_market_depth_websocket",
            "collection_mode":"auto_banknifty_20_level",
            "bid_packet_sha256":b,"ask_packet_sha256":a,
            "bid":[{"price":bid,"quantity":quantity,"orders":10}],
            "ask":[{"price":ask,"quantity":quantity,"orders":10}],
            "computed_features":{"lot_size_verified":30,"expiry":DAY,
                                 "strike":strike,"side":side}},sha256((b+a).encode()).hexdigest()


class ReadinessTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/"depth.sqlite3"
        with sqlite3.connect(self.db) as conn:
            conn.execute("""CREATE TABLE live_depth_books(identity TEXT,received_utc TEXT,
                book_json TEXT,packet_pair_sha256 TEXT,PRIMARY KEY(identity,received_utc))""")

    def put(self,identity,seconds,ask,quantity=2000,valid=True,strike=63000,side="CE",bid_quantity=None):
        stamp=START+timedelta(seconds=seconds)
        raw,digest=book(identity,stamp,ask,quantity,strike,side)
        if bid_quantity is not None:
            raw['bid'][0]['quantity']=bid_quantity
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO live_depth_books VALUES (?,?,?,?)",
                         (identity,p._iso(stamp),json.dumps(raw),digest if valid else "0"*64))

    def inspect(self,ids,lots=3,strategy="LONG_OPTION",**kwargs):
        with patch.object(r.replay.ao,"_read_database",
                          side_effect=lambda:sqlite3.connect(self.db.as_uri()+"?mode=ro",uri=True)):
            return r.inspect(day=DAY,strategy=strategy,identities=ids,
                capital=17000,lots=lots,now=NOW,**kwargs)

    def test_budget_and_ranked_candidates_use_original_depth(self):
        for t in (1,2,3,4,5):
            self.put("NSE_FNO:1",t,600)
        for t in (1,1.5,3,5):
            self.put("NSE_FNO:2",t,100)
        for t in (1,2,3,4,5,6,7):
            self.put("NSE_FNO:3",t,200)
        self.put("NSE_FNO:2",10.2,1+1)  # incomplete second, deliberately excluded
        self.put("NSE_FNO:2",20,2)  # future, excluded
        self.put("NSE_FNO:4",8,50,valid=False)
        self.put("NSE_FNO:5",8,50,quantity=10)
        result=self.inspect(["NSE_FNO:1"],lots=3)
        self.assertEqual(result["selected"]["status"],"over_budget")
        self.assertGreater(result["selected"]["one_lot_required_inr"],17000)
        self.assertEqual(result["selected"]["max_affordable_lots"],0)
        self.assertEqual(result["elapsed_seconds"],10)
        self.assertEqual([x["identity"] for x in result["candidates"]],["NSE_FNO:2","NSE_FNO:3"])
        candidate=result["candidates"][0]
        self.assertEqual(candidate["saved_receipts"],4)
        self.assertEqual(candidate["observed_seconds"],3)
        self.assertEqual(candidate["coverage_pct"],30)
        self.assertEqual(candidate["max_affordable_lots"],5)
        self.assertEqual(result["candidates"][1]["max_affordable_lots"],2)
        self.assertEqual(candidate["one_lot_required_inr"],p.fees._money(
            p.fees._money(100*30*1.0005)+p._fees("BUY",p.fees._money(100*30*1.0005),"zerodha")))

    def test_missing_and_invalid_books_never_report_affordability(self):
        self.put("NSE_FNO:1",5,100,valid=False)
        result=self.inspect(["NSE_FNO:1"])
        self.assertEqual(result["selected"]["status"],"missing_or_invalid_original_book")
        self.assertIsNone(result["selected"]["one_lot_required_inr"])
        self.assertEqual(result["affordable_candidates"],0)
        result=self.inspect(["NSE_FNO:99"])
        self.assertEqual(result["selected"]["minimum_leg_coverage_pct"],0)

    def test_depth_shortage_and_unsynchronized_basket(self):
        self.put("NSE_FNO:1",1,100,quantity=50)
        result=self.inspect(["NSE_FNO:1"],lots=1)
        self.assertEqual(result["selected"]["status"],"insufficient_displayed_depth")
        self.assertIsNone(result["selected"]["one_lot_required_inr"])
        self.put("NSE_FNO:2",2,100,strike=63000)
        self.put("NSE_FNO:3",7,70,strike=63100)
        result=self.inspect(["NSE_FNO:2","NSE_FNO:3"],lots=1,strategy="bull_call_debit")
        self.assertEqual(result["selected"]["status"],"latest_legs_not_synchronized")
        self.assertIsNone(result["selected"]["requested_lots_required_inr"])
        self.assertFalse(result["candidates"])
        self.put("NSE_FNO:2",7.5,100,strike=63000)
        result=self.inspect(["NSE_FNO:2","NSE_FNO:3"],lots=1,strategy="bull_call_debit")
        self.assertEqual(result["selected"]["status"],"ready")
        self.assertGreater(result["selected"]["one_lot_required_inr"],0)


    def automatic(self,ids,**kwargs):
        from workstation_api import auto_option_depth as recorder
        with patch.dict(recorder.STATE,{"contracts":[{"identity":i} for i in ids]}), \
             patch.object(r.replay.ao,"_read_database",
                          side_effect=lambda:sqlite3.connect(self.db.as_uri()+"?mode=ro",uri=True)):
            return r.automatic(day=DAY,capital=17000,lots=3,now=NOW,**kwargs)

    def test_automatic_prefers_coverage_and_reduces_lots_without_manual_id(self):
        for t in range(1,9):
            self.put("NSE_FNO:1",t,600,strike=63000)
            self.put("NSE_FNO:2",t,200,strike=63100)
        for t in (1,2,3):
            self.put("NSE_FNO:3",t,100,strike=63200)
        for t in range(1,10):
            self.put("NSE_FNO:4",t,100,strike=63300,bid_quantity=10)
            self.put("NSE_FNO:5",t,100,strike=63400) # not in current watchlist
        result=self.automatic(["NSE_FNO:1","NSE_FNO:2","NSE_FNO:3","NSE_FNO:4"])
        self.assertEqual(result["scope"],"current_depth_watchlist")
        self.assertEqual(result["scanned_contracts"],4)
        self.assertEqual(result["affordable_candidates"],2)
        self.assertEqual(result["automatic_pick"]["identity"],"NSE_FNO:2")
        self.assertEqual(result["automatic_pick"]["study_lots"],2)
        self.assertLessEqual(result["automatic_pick"]["study_entry_inr"],17000)
        self.assertEqual(result["rejections"]["budget_or_roundtrip_depth"],2)
        self.assertFalse(result["scan_truncated"])

    def test_automatic_respects_filters_and_does_not_invent_a_candidate(self):
        self.put("NSE_FNO:1",1,100,strike=63000,side="CE")
        self.put("NSE_FNO:2",2,100,strike=63100,side="PE")
        ids=["NSE_FNO:1","NSE_FNO:2"]
        result=self.automatic(ids,side="PE",search="63100")
        self.assertEqual(result["automatic_pick"]["identity"],"NSE_FNO:2")
        result=self.automatic(ids,side="PE",search="63000")
        self.assertIsNone(result["automatic_pick"])
        self.assertEqual(result["reason"],"no_eligible_recorded_contract")
        self.assertEqual(result["candidates"],[])
