"""Offline constituent analytics acceptance: fixtures are synthetic, never Dhan fills."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import struct
import tempfile

from workstation_api import banknifty_constituents as b, full_option_feed, service, shared_market_data, market_inventory


class ConstituentTests(TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        p=patch.object(service,"DATA",self.root/"data")
        p.start()
        self.addCleanup(p.stop)
        self.target=datetime(2026,11,23,4,10,tzinfo=timezone.utc)
        self.members={"date":"2026-11-23","symbols":["BANKA","BANKB"],
                      "resolved":{"BANKA":"NSE_EQ:10","BANKB":"NSE_EQ:20"},
                      "source_sha256":"a"*64,"covered_through":"2026-11-23"}

    def packet(self,sid=10,price=101.,volume=100,trade=None,segment=1):
        trade=trade or self.target
        raw=struct.pack("<fHIfIIIffff",price,10,int(trade.timestamp()),100.,volume,20,60,100.,100.,101.,99.)
        return struct.pack("<BHBI",4,50,segment,sid)+raw

    def test_mixed_parser_and_spare_capacity(self):
        eq=self.packet()
        opt=self.packet(sid=12,segment=2)
        self.assertEqual(len(full_option_feed.decode_quote_frames(eq+opt)),1)
        mixed=full_option_feed.decode_quote_frames(eq+opt,include_equity=True)
        self.assertEqual([x["kind"] for x in mixed],["constituent_quote","quote"])
        self.assertEqual(mixed[0]["identity"],"NSE_EQ:10")
        self.assertEqual(mixed[0]["volume"],100)
        with patch.object(b.dhan_workspace,"catalog",return_value=[]),patch.object(b,"membership",return_value=self.members):
            req,info,state=b.subscription_plan(4998,capture_allowed=True)
            self.assertEqual(req["InstrumentCount"],2)
            self.assertEqual(req["RequestCode"],17)
            self.assertTrue(all(x["ExchangeSegment"]=="NSE_EQ" for x in req["InstrumentList"]))
            self.assertEqual(state,"awaiting_quotes")
            self.assertEqual(b.subscription_plan(4999,capture_allowed=True)[2],"insufficient_spare_capacity")
            self.assertEqual(b.subscription_plan(0,capture_allowed=False)[2],"not_enabled")

    def test_capture_sampling_stale_and_persistence(self):
        c=b.Capture()
        c.begin("fixture",self.members,"awaiting_quotes")
        event=b.decode_quote(self.packet(),4,1,10)
        c.submit(event,self.target,"wrong_session")
        self.assertEqual(c.queue.qsize(),0)
        c.submit(event,self.target,"fixture")
        c.submit(event,self.target+timedelta(seconds=1),"fixture")
        c.submit(event,self.target+timedelta(seconds=60),"fixture")
        self.assertEqual(c.queue.qsize(),1)
        self.assertEqual(c.sampled_out,1)
        self.assertEqual(c.stale,1)
        stop=Event();stop.set()
        with patch.object(b.recorder_storage,"allow",return_value=True),patch.object(b.recorder_storage,"saved"):
            c.writer(stop)
        self.assertEqual(c.saved,1)
        with sqlite3.connect(shared_market_data.database_path()) as db:
            row=db.execute("SELECT identity,symbol,volume,buy_quantity,sell_quantity FROM banknifty_constituent_quotes").fetchone()
            self.assertEqual(row,("NSE_EQ:10","BANKA",100,60,20))
        rows=market_inventory.records("constituent_quotes","NSE_EQ:10")
        self.assertEqual(len(rows["rows"]),1)
        c.disconnect()
        c.submit(event,self.target,"fixture")
        self.assertTrue(c.queue.empty())

    def test_weights_reject_incomplete_future_and_late_evidence(self):
        text="symbol,weight_pct\nBANKA,60\nBANKB,40\n"
        before=self.target-timedelta(minutes=10)
        with patch.object(b,"membership",return_value=self.members),patch.object(b,"_now",return_value=before):
            snap=b.save_weights("2026-11-23",text,"Synthetic unit-test weight report",True)
            self.assertFalse(snap["independently_verified"])
            self.assertIsNone(b._weights_for(date(2026,11,23),before-timedelta(seconds=1),self.members["symbols"]))
            self.assertEqual(b._weights_for(date(2026,11,23),self.target,self.members["symbols"])["weights_pct"],{"BANKA":60.,"BANKB":40.})
            with self.assertRaises(ValueError):
                b.save_weights("2026-11-23","symbol,weight_pct\nBANKA,100\n","Incomplete fixture",True)
            with self.assertRaises(ValueError):
                b.save_weights("2026-11-24",text,"Future fixture",True)

    def test_aligned_returns_and_relative_volume_no_future(self):
        end=self.target;start=end-timedelta(minutes=5)
        text="symbol,weight_pct\nBANKA,60\nBANKB,40\n"
        with patch.object(b,"membership",return_value=self.members),patch.object(b,"_now",return_value=start-timedelta(minutes=1)):
            b.save_weights("2026-11-23",text,"Synthetic weight test",True)
        with b.live_market._database() as db:
            b._setup(db)
            def add(symbol,identity,at,price,volume):
                db.execute("INSERT INTO banknifty_constituent_quotes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (identity,symbol,b._local_day(at).isoformat(),b._iso(at),b._iso(at),price,volume,100.,60,20,"b"*64,"fixture","a"*64))
            for k in (3,4,5,6,7):
                a=start-timedelta(days=k);z=end-timedelta(days=k)
                add("BANKA","NSE_EQ:10",a,100.,1000)
                add("BANKA","NSE_EQ:10",z,100.,1100)
            add("BANKA","NSE_EQ:10",start,100.,1000)
            add("BANKA","NSE_EQ:10",end,101.,1200)
            add("BANKB","NSE_EQ:20",start,200.,3000)
            add("BANKB","NSE_EQ:20",end,198.,3100)
            add("BANKA","NSE_EQ:10",end+timedelta(seconds=1),500.,9999)
        with patch.object(b,"membership",return_value=self.members),patch.object(b,"_now",return_value=end+timedelta(seconds=2)):
            out=b.analyze(5,b._iso(end))
            self.assertTrue(out["complete_weighted_coverage"])
            self.assertEqual(out["observed_members"],2)
            self.assertAlmostEqual(out["weighted_return_pct"],.2)
            self.assertAlmostEqual(out["weighted_breadth_pct"],20.)
            self.assertEqual(out["rows"][0]["current"]["price"],101.)
            self.assertEqual(out["rows"][0]["relative_volume"],2.)
            self.assertEqual(out["rows"][0]["baseline_sessions"],5)
            self.assertEqual(out["rows"][0]["displayed_quantity_imbalance"],.5)
            self.assertIsNone(out["rows"][0]["approx_index_points"])
        with b.live_market._database() as db:
            db.execute("DELETE FROM banknifty_constituent_quotes WHERE symbol='BANKB' AND received_utc=?",(b._iso(end),))
        with patch.object(b,"membership",return_value=self.members),patch.object(b,"_now",return_value=end+timedelta(seconds=2)):
            out=b.analyze(5,b._iso(end))
            self.assertFalse(out["complete_weighted_coverage"])
            self.assertIsNone(out["weighted_return_pct"])
            self.assertAlmostEqual(out["partial_contribution_pp"],.6)
            self.assertEqual(out["observed_weight_pct"],60.)
