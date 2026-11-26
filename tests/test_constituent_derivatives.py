from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch
import sqlite3
from workstation_api import constituent_derivatives as d, service, shared_market_data, market_inventory

class StockDerivativeTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        p=patch.object(service,"DATA",self.root/"data")
        p.start();self.addCleanup(p.stop)
        self.cut=datetime(2026,11,23,4,10,tzinfo=timezone.utc)
        self.fut={"identity":"NSE_FNO:100","underlying":"BANKA","instrument":"FUTSTK","expiry":"2026-11-30","lot_size":100,"strike":None,"option_type":None}
        self.opt={"identity":"NSE_FNO:101","underlying":"BANKA","instrument":"OPTSTK","expiry":"2026-11-30","lot_size":100,"strike":120.,"option_type":"CE"}
        self.info={"symbols":["BANKA"],"resolved":{"BANKA":"NSE_EQ:10"},"source_sha256":"a"*64}

    def test_exact_master_and_spare_capacity(self):
        p=self.root/"master.csv"
        p.write_text("EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,EXPIRY_DATE,LOT_SIZE,UNDERLYING_SYMBOL,UNDERLYING_SECURITY_ID,STRIKE_PRICE,OPTION_TYPE\nNSE,D,100,FUTSTK,2026-11-30,100,BANKA,10,,\nNSE,D,101,OPTSTK,2026-11-30,100,BANKA,10,120,CE\nNSE,D,102,FUTSTK,2026-11-30,100,BANKAOTHER,11,,\nNSE,D,103,FUTSTK,2026-11-30,100,BANKA,999,,\nNSE,D,104,OPTIDX,2026-11-30,30,BANKA,10,120,CE\n")
        st=p.stat()
        items=d._catalog(str(p),st.st_mtime_ns,st.st_size,"2026-11-23",(("BANKA","NSE_EQ:10"),))
        self.assertEqual([x["identity"] for x in items],["NSE_FNO:100","NSE_FNO:101"])
        with patch.object(d,"enabled",return_value=True),patch.object(d,"_config",return_value={"enabled":True,"option_ids":["NSE_FNO:101"]}),patch.object(d,"discover",return_value=(self.info,[self.fut],[self.opt],[])):
            msg,mapping,state=d.plan(4998)
            self.assertEqual(len(mapping),2)
            self.assertEqual(msg[0]["InstrumentCount"],2)
            self.assertEqual(state,"awaiting_quotes")
            self.assertEqual(d.plan(4999)[2],"insufficient_spare_capacity")
            self.assertEqual(d.plan(0,allowed=False)[2],"not_enabled")

    def test_independent_capture_and_oi_receipts(self):
        c=d.Capture()
        mapping={self.fut["identity"]:{**self.fut,"membership_sha256":"a"*64}}
        c.begin("fixture",mapping,"awaiting_quotes")
        start=self.cut-timedelta(minutes=5)
        def quote(at,price,volume,digest):
            return {"kind":"quote","security_id":"100","trade_epoch":int(at.timestamp()),"price":price,"volume":volume,"packet_sha256":digest}
        c.submit(quote(start,100.,1000,"b"*64),start,"fixture")
        c.submit(quote(self.cut,101.,1250,"c"*64),self.cut,"fixture")
        for at,oi,digest in [(start,100,"d"*64),(self.cut-timedelta(seconds=5),150,"e"*64),(self.cut,150,"e"*64)]:
            c.submit({"kind":"oi","security_id":"100","oi":oi,"packet_sha256":digest},at,"fixture")
        self.assertEqual(c.queue.qsize(),5)
        c.disconnect()
        self.assertTrue(c.owns(quote(self.cut,101.,1250,"c"*64),"fixture"))
        c.submit(quote(self.cut,101.,1250,"c"*64),self.cut,"fixture")
        self.assertEqual(c.queue.qsize(),5)
        stop=Event();stop.set()
        with patch.object(d.recorder_storage,"allow",return_value=True),patch.object(d.recorder_storage,"saved"):
            c.writer(stop)
        self.assertEqual(c.saved,5)
        with patch.object(d,"_now",return_value=self.cut+timedelta(seconds=1)):
            out=d.analysis(5,d.bank._iso(self.cut))
        self.assertEqual(len(out["rows"]),1)
        row=out["rows"][0]
        self.assertAlmostEqual(row["return_pct"],1)
        self.assertEqual(row["volume_delta"],250)
        self.assertEqual(row["oi_delta"],50)
        self.assertEqual(row["oi"]["received_utc"],d.bank._iso(self.cut))
        self.assertEqual(len(market_inventory.records("constituent_derivative_oi","NSE_FNO:100")["rows"]),3)
