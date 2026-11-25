import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from workstation_api import market_inventory as inv


class MarketInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.patch=patch.object(inv.service,"DATA",self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        inv.CACHE=None

    def test_canonical_counts_distinguish_quote_and_oi_and_chain_expiry(self):
        dbpath=inv.shared_market_data.database_path()
        dbpath.parent.mkdir(parents=True)
        with sqlite3.connect(dbpath) as db:
            db.executescript("""
            CREATE TABLE instruments(identity TEXT,display_symbol TEXT);
            INSERT INTO instruments VALUES('NSE_EQ:123','Example');
            CREATE TABLE daily_closes(identity TEXT,session_date TEXT,close REAL);
            INSERT INTO daily_closes VALUES('NSE_EQ:123','2025-01-02',100),('NSE_EQ:123','2026-02-03',120);
            CREATE TABLE dhan_option_live_events(identity TEXT,received_utc TEXT,kind TEXT);
            INSERT INTO dhan_option_live_events VALUES('NSE_FNO:7','2026-11-25T04:00:00+00:00','quote'),('NSE_FNO:7','2026-11-25T04:01:00+00:00','oi');
            CREATE TABLE option_chain_observations(underlying TEXT,expiry TEXT,captured_utc TEXT,normalized_json TEXT);
            INSERT INTO option_chain_observations VALUES('BANKNIFTY','2026-12-01','2026-11-25T04:00:00+00:00','private'),('BANKNIFTY','2026-12-08','2026-11-25T04:01:00+00:00','private');
            """)
        report=inv.inventory()
        groups={r["id"]:r for r in report["sources"]}
        self.assertEqual(groups["daily_closes"]["count"],2)
        self.assertEqual(groups["daily_closes"]["first"],"2025-01-02")
        self.assertEqual(groups["daily_closes"]["last"],"2026-02-03")
        self.assertEqual(groups["option_quote"]["count"],1)
        self.assertEqual(groups["option_oi"]["count"],1)
        self.assertEqual(groups["option_chain"]["groups"],2)
        self.assertNotIn("private",json.dumps(report))
        self.assertEqual(groups["live_ticks"]["state"],"not_recorded")
        self.assertEqual(inv.inventory("daily_closes","example")["total"],1)
        self.assertEqual(inv.inventory("option_chain",per_page=1)["has_more"],True)
        self.assertEqual(inv.inventory("option_chain",page=2,per_page=1)["items"][0]["qualifier"],"2026-12-08")

    def test_history_uses_actual_csv_dates_not_requested_window(self):
        folder=self.root/"dhan"/"history"/"NSE_EQ"/"321"
        folder.mkdir(parents=True)
        (folder/"1m.csv").write_text("datetime,open,high,low,close,volume\n2026-01-02T04:00:00+00:00,1,1,1,1,0\n2026-02-02T04:00:00+00:00,2,2,2,2,0\n")
        (folder/"1m.json").write_text(json.dumps({"instrument_id":"NSE_EQ:321","display_symbol":"ABC","interval_minutes":1,"sha256":"0"*64,"rows":2,"coverage":[["2020-01-01","2026-11-26"]]}))
        data=inv.inventory("raw_intraday")
        self.assertEqual(data["total"],1)
        row=data["items"][0]
        self.assertEqual(row["first"],"2026-01-02T04:00:00+00:00")
        self.assertEqual(row["last"],"2026-02-02T04:00:00+00:00")
        self.assertEqual(row["evidence"],"receipt_count_csv_edges")
        self.assertEqual(data["external_requests"],0)

    def test_missing_store_is_not_created_and_invalid_query_is_rejected(self):
        result=inv.inventory()
        self.assertFalse(inv.shared_market_data.database_path().exists())
        self.assertEqual(result["total"],0)
        with self.assertRaises(ValueError):
            inv.inventory("live_ticks;DROP TABLE instruments")
        with self.assertRaises(ValueError):
            inv.inventory(page=0)

    def test_broken_receipt_is_partial_not_zero_verified(self):
        folder=self.root/"dhan"/"history"/"NSE_EQ"/"99"
        folder.mkdir(parents=True)
        (folder/"daily.json").write_text("{}")
        report=inv.inventory()
        row=next(r for r in report["sources"] if r["id"]=="raw_daily")
        self.assertEqual(row["state"],"partial")
        self.assertIsNone(row["count"])
