from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import csv
import io
import sqlite3

from workstation_api import global_market_archive as g


class GlobalMarketArchiveTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"shared.sqlite3"
        patch=mock.patch.object(g.shared_market_data,"database_path",return_value=self.path)
        patch.start()
        self.addCleanup(patch.stop)
        self.day=date(2025,3,3)
        self.start=datetime(2025,3,3,0,0,tzinfo=g.UTC) # Japan cash reference
        self.now=datetime(2025,3,4,0,0,tzinfo=g.UTC)

    def raw(self, *, n=12, change=0, missing=(), zero=(), exported=None, symbol="JPN.IDX/JPY"):
        out=io.StringIO()
        w=csv.writer(out,lineterminator="\n");w.writerow(g.HEADER)
        for i in range(n):
            if i in missing: continue
            t=self.start+timedelta(minutes=5*i)
            price=100+i+change
            w.writerow((symbol,5,"BID",int(t.timestamp()*1000),price,price+2,
                        price-1,price+1,0 if i in zero else 1,
                        int((exported or self.now).timestamp()*1000)))
        return out.getvalue().encode()

    def archive(self,raw=None,lag=5):
        return g.ingest(raw or self.raw(),mode="archive",confirm_reviewed=True,
                        archive_lag_minutes=lag,now=self.now)

    def features(self,cutoff,mode="archive"):
        with closing(sqlite3.connect(self.path)) as db:
            return g.reference_features(db,self.day,cutoff,mode=mode)["JPN.IDX/JPY"]

    def test_dedup_and_conflict_atomic(self):
        self.assertEqual(self.archive()["inserted"],12)
        self.assertEqual(self.archive()["state"],"already_imported")
        with self.assertRaisesRegex(ValueError,"Conflicting OHLCV"):
            self.archive(self.raw(change=10))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM global_market_bars").fetchone()[0],12)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM global_market_receipts").fetchone()[0],1)

    def test_opening_windows_and_availability(self):
        self.archive()
        early=self.features(self.start+timedelta(minutes=6))
        self.assertIsNone(early["first_5m_bps"])
        enough=self.features(self.start+timedelta(minutes=20))
        self.assertAlmostEqual(enough["first_15m_bps"],300)
        self.assertIsNone(enough["first_30m_bps"])
        self.assertIsNone(self.features(self.start+timedelta(minutes=65),mode="receipt")["first_60m_bps"])
        self.assertAlmostEqual(self.features(self.start+timedelta(minutes=65))["first_60m_bps"],1200)

    def test_missing_and_zero_not_fabricated(self):
        self.archive(self.raw(missing=(1,),zero=(3,)))
        features=self.features(self.start+timedelta(minutes=65))
        self.assertIsNotNone(features["first_5m_bps"])
        self.assertIsNone(features["first_15m_bps"])
        self.assertIsNone(features["first_60m_bps"])

    def test_receipt_then_reviewed_archive(self):
        raw=self.raw()
        g.ingest(raw,confirm_reviewed=True,now=self.now)
        self.assertEqual(self.archive(raw)["archive_upgraded"],12)
        self.assertEqual(g.inventory()["series"][0]["rows"],12)
        self.assertEqual(g.inventory()["series"][0]["archive_rows"],12)
        with self.assertRaisesRegex(ValueError,"Conflicting reviewed archive lag"):
            self.archive(raw,lag=6)

    def test_reject_wrong_source_and_future_and_unreviewed(self):
        for raw in (self.raw(symbol="NIKKEI"),self.raw(exported=self.start)):
            with self.assertRaises(ValueError):
                self.archive(raw)
        with self.assertRaises(ValueError):
            g.ingest(self.raw(),now=self.now)
        with self.assertRaises(ValueError):
            g.ingest(self.raw(),mode="archive",confirm_reviewed=True,now=self.now)

    def test_prior_import_not_backdated(self):
        g.ingest(self.raw(),confirm_reviewed=True,now=self.now)
        result=self.features(self.start+timedelta(minutes=65),mode="receipt")
        self.assertEqual(result["state"],"missing")


    def test_live_import_opt_in_and_restart_safe(self):
        raw=self.raw()
        folder=Path(self.tmp.name)/"quantlab_global_live"
        day=folder/str(self.now.date())
        day.mkdir(parents=True)
        (day/"japan.csv").write_bytes(raw)
        # Keep source file unchanged, and avoid touching real configuration.
        with mock.patch.object(g.service,"DATA",Path(self.tmp.name)), \
             mock.patch.object(g.recorder_storage,"allow",return_value=True), \
             mock.patch.object(g.recorder_storage,"saved"):
            self.assertIsNone(g.scan_live_inbox(now=self.now))
            with self.assertRaises(ValueError):
                g.configure_live_inbox(folder)
            g.configure_live_inbox(folder,confirm_reviewed=True)
            self.assertEqual(g.scan_live_inbox(now=self.now)["inserted"],12)
            self.assertEqual(g.scan_live_inbox(now=self.now)["inserted"],0)
            self.assertEqual(g.inventory()["series"][0]["archive_rows"],0)
            self.assertTrue((day/"japan.csv").exists())
            g.disable_live_inbox()
            self.assertIsNone(g.scan_live_inbox(now=self.now))
