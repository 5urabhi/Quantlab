from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
import gzip
import json
import sqlite3

from workstation_api import alpaca_overnight as b
from workstation_api import global_market_archive as g


class OvernightTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"shared.sqlite3"
        for obj,key,value in ((g.shared_market_data,"database_path",lambda:self.path),
                              (g.service,"DATA",Path(self.tmp.name)),
                              (g.recorder_storage,"allow",lambda *a,**k:True),
                              (g.recorder_storage,"saved",lambda *a,**k:None),
                              (b.alpaca,"credentials",lambda:("key","secret"))):
            p=mock.patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        self.day=date(2026,11,24)
        self.start,self.stop=b.session(self.day)
        self.now=self.stop+timedelta(hours=1)
        p=mock.patch.object(g,"_now",lambda:self.now);p.start();self.addCleanup(p.stop)

    def raw(self,*,symbol="SPY",n=12,missing=(),token=None,shift=0):
        bars=[]
        for i in range(n):
            if i in missing:continue
            price=100+i+shift
            bars.append({"t":g._iso(self.start+i*b.STEP),"o":price,"h":price+2,
                         "l":price-1,"c":price+1,"v":12})
        return json.dumps({"bars":{symbol:bars},"next_page_token":token}).encode()

    def fetch(self,raw=None,mode="archive"):
        with mock.patch.object(b.alpaca,"_http",return_value=raw or self.raw()) as call:
            result=b.fetch_window(self.start,self.stop,mode=mode,confirmed=True,now=self.now)
            params=call.call_args.args[0]
            self.assertEqual(params["feed"],"boats")
            self.assertEqual(params["end"],g._iso(self.stop-b.STEP))
            return result

    def test_dst_reference_session(self):
        self.assertEqual(self.start.astimezone(g.IST).hour,6)
        self.assertEqual(self.start.astimezone(g.IST).minute,30)
        summer,_=b.session(date(2026,7,20))
        self.assertEqual(summer.astimezone(g.IST).hour,5)
        self.assertEqual(summer.astimezone(g.IST).minute,30)

    def test_original_and_idempotence(self):
        raw=self.raw()
        self.assertEqual(self.fetch(raw)["inserted"],12)
        self.assertEqual(self.fetch(raw)["inserted"],0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM global_market_bars").fetchone()[0],12)
            self.assertEqual(gzip.decompress(db.execute("SELECT original_csv_gzip FROM global_market_receipts").fetchone()[0]),raw)
        self.assertEqual(g.inventory()["series"][0]["identity"],b.identity("SPY"))

    def test_conflict_and_invalid_symbol(self):
        self.fetch()
        with self.assertRaisesRegex(ValueError,"Conflicting OHLCV"):
            self.fetch(self.raw(shift=1))
        with self.assertRaisesRegex(ValueError,"Unexpected BOATS symbols"):
            self.fetch(self.raw(symbol="NOTETF"))

    def test_delay_and_no_future_request(self):
        with self.assertRaisesRegex(ValueError,"completed range"):
            b.fetch_window(self.start,self.stop,mode="receipt",confirmed=True,now=self.stop)
        with self.assertRaisesRegex(ValueError,"not yet available"):
            b.normalize(self.raw(),self.start,self.stop,self.start+timedelta(minutes=4))
        self.assertIsNone(b.live_bounds(self.start+timedelta(minutes=10)))
        self.assertEqual(b.live_bounds(self.start+timedelta(minutes=25)),(self.start,self.start+b.STEP))

    def test_missing_and_asof_features(self):
        self.fetch(self.raw(missing=(5,)))
        cutoff=self.start+timedelta(minutes=80)
        with closing(sqlite3.connect(self.path)) as db:
            x=b.features(db,self.day,cutoff,mode="archive")
            self.assertEqual(x["SPY"]["observed_bars"],11)
            self.assertAlmostEqual(x["SPY"]["coverage_ratio"],11/12)
            self.assertIsNone(x["SPY"]["trailing_30m_bps"])
            self.assertAlmostEqual(x["SPY"]["session_return_bps"],1200)
            self.assertIsNone(x["EWJ"]["session_return_bps"])
            self.assertEqual(b.features(db,self.day,cutoff,mode="receipt")["SPY"]["state"],"missing")

    def test_paginated_and_empty(self):
        first=self.raw(n=6,token="more")
        second=self.raw(missing=tuple(range(6)))
        with mock.patch.object(b.alpaca,"_http",side_effect=[first,second]):
            x=b.fetch_window(self.start,self.stop,mode="archive",confirmed=True,now=self.now)
        self.assertEqual(x["pages"],2);self.assertEqual(x["counts"]["SPY"],12)
        empty=self.fetch(b'{"bars":{},"next_page_token":null}')
        self.assertEqual(empty["state"],"empty_provider_response")

    def test_verified_window_resume(self):
        outcome=self.fetch()
        b._save_window(self.start,self.stop,outcome)
        self.assertEqual(b._existing_window(self.start,self.stop)["state"],"existing_observed_window")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM global_market_receipts")
        self.assertIsNone(b._existing_window(self.start,self.stop))

    def test_configuration_is_opt_in(self):
        self.assertFalse(b.enabled())
        with self.assertRaises(ValueError):b.configure(True)
        b.configure(True,confirmed=True)
        self.assertTrue(b.enabled())
        b.configure(False)
        self.assertFalse(b.enabled())
