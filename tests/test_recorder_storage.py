from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from contextlib import contextmanager
import sqlite3
import json
from workstation_api import recorder_storage as guard, market_session_archive as archive
from workstation_api import full_option_feed as feed, live_market, shared_market_data

class RecorderStorageTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/"market.sqlite3"
        p=patch.object(shared_market_data,"database_path",return_value=self.path)
        p.start();self.addCleanup(p.stop)
        guard.STATE.clear();guard.CACHE.clear()
        self.addCleanup(guard.STATE.clear);self.addCleanup(guard.CACHE.clear)

    def test_disk_guard_pause_and_resume_keeps_gap(self):
        with patch.object(guard,"_capacity",return_value=(False,1,100)):
            self.assertFalse(guard.allow("auto_depth",dropped=1))
            self.assertFalse(guard.allow("auto_depth",dropped=1))
        state=guard.status("auto_depth")
        self.assertEqual(state["state"],"paused")
        self.assertEqual(state["dropped"],2)
        self.assertEqual(state["gap_count"],1)
        guard.CACHE.clear()
        with patch.object(guard,"_capacity",return_value=(True,1000,100)):
            self.assertTrue(guard.allow("auto_depth"))
        self.assertEqual(guard.status("auto_depth")["state"],"paused")
        guard.saved("auto_depth","2026-11-23T05:00:00+00:00")
        self.assertEqual(guard.status("auto_depth")["state"],"recording")
        self.assertEqual(guard.status("auto_depth")["gap_count"],1)
        entries=[json.loads(s) for s in (self.path.parent/"recorder_storage_gaps.jsonl").read_text().splitlines()]
        self.assertEqual([s["state"] for s in entries],["paused","resumed"])

    def test_archive_preserves_source_and_detects_tampering(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE live_ticks(identity TEXT,exchange_utc TEXT,received_utc TEXT,packet_sha256 TEXT)")
            for t in ["2026-11-23T04:00:00+00:00","2026-11-24T04:00:00+00:00"]:
                db.execute("INSERT INTO live_ticks VALUES(?,?,?,?)",("INDEX:BANKNIFTY",t,t,"a"*64))
        now=datetime(2026,11,25,tzinfo=timezone.utc)
        x=archive.archive("2026-11-23",now=now)
        self.assertTrue(x["verified"])
        self.assertEqual(x["tables"]["live_ticks"]["rows"],1)
        self.assertEqual(x["tables"]["live_depth_books"]["state"],"table_absent")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0],2)
        folder=self.path.parent/"session_archives"/"2026-11-23"
        self.assertTrue(archive.verify(folder)["verified"])
        with (folder/"live_ticks.jsonl.gz").open("ab") as f:
            f.write(b"tamper")
        with self.assertRaises(ValueError):
            archive.verify(folder)
        with self.assertRaises(ValueError):
            archive.archive("2026-11-25",now=now)

    def test_capacity_check_failure_fails_closed(self):
        with patch.object(guard,"_capacity",side_effect=OSError("fixture")):
            self.assertFalse(guard.allow("option_chain"))
        self.assertEqual(guard.status("option_chain")["state"],"write_error")
