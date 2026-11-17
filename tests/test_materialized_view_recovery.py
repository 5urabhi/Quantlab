"""Offline crash/derived-view integrity acceptance, without a broker connection."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from workstation_api import (data_orchestrator, materialized_view_recovery as recovery,
                             operational_health, service, shared_market_data as shared)


class DerivedViewRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="quantlab_derived_recovery_")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        p = patch.object(service, "DATA", self.root / "data")
        p.start()
        self.addCleanup(p.stop)
        self.mapping = {
            "exchange_segment": "NSE_EQ",
            "security_id": "1333",
            "display_symbol": "RELIANCE",
            "source_sha256": "a" * 64,
        }
        self.prices = pd.DataFrame(
            {"close": [100.0, 101.0, 102.0]},
            index=pd.to_datetime(["2026-01-29", "2026-01-30", "2026-02-02"]))
        shared.ingest([(self.mapping, self.prices)], origin="offline_fixture")

    def test_healthy_views_are_not_rewritten(self):
        source = shared.database_path()
        folder = shared.shared_folder()
        before = [(folder / name).read_bytes() for name in
                  ("daily_prices.csv", "prices.csv", "SHARED_MARKET_PROVENANCE.json")]
        result = recovery.repair()
        self.assertEqual(result["state"], "already_ready")
        self.assertFalse(result["changed"])
        self.assertEqual(before, [(folder / name).read_bytes() for name in
                                  ("daily_prices.csv", "prices.csv",
                                   "SHARED_MARKET_PROVENANCE.json")])
        self.assertGreater(source.stat().st_size, 0)

    def test_mismatched_derived_csv_is_rebuilt_from_original_sqlite(self):
        original = shared.shared_folder() / "prices.csv"
        correct = original.read_bytes()
        original.write_text("date,NSE_EQ_1333\n2026-02-02,999999\n")
        check = recovery.inspect(verify_content=True)
        self.assertEqual(check["state"], "needs_rebuild")
        result = data_orchestrator.safe_maintenance()
        self.assertTrue(result["repaired"])
        self.assertEqual(original.read_bytes(), correct)
        self.assertFalse(result["original_observations_changed"])
        self.assertEqual(recovery.inspect(verify_content=True)["state"], "ready")

    def test_missing_and_legacy_receipts_recovered_without_touching_broker_rows(self):
        folder = shared.shared_folder()
        with shared._connect() as db:
            before = db.execute("SELECT identity,session_date,close,source_sha256 "
                                "FROM daily_closes ORDER BY identity,session_date").fetchall()
        receipt = folder / "SHARED_MARKET_PROVENANCE.json"
        content = json.loads(receipt.read_text())
        content.pop("close_rows")
        receipt.write_text(json.dumps(content))
        self.assertEqual(recovery.inspect()["state"], "needs_rebuild")
        self.assertEqual(recovery.repair(automatic=True)["state"], "repaired")
        receipt.unlink()
        self.assertEqual(recovery.repair(automatic=True)["state"], "repaired")
        with shared._connect() as db:
            after = db.execute("SELECT identity,session_date,close,source_sha256 "
                               "FROM daily_closes ORDER BY identity,session_date").fetchall()
        self.assertEqual(before, after)

    def test_corrupted_database_does_not_trigger_mutating_repair(self):
        folder = shared.shared_folder()
        snapshot = (folder / "prices.csv").read_bytes()
        shared.database_path().write_bytes(b"this is not SQLite")
        result = recovery.repair()
        self.assertEqual(result["state"], "blocked")
        self.assertFalse(result["changed"])
        self.assertEqual((folder / "prices.csv").read_bytes(), snapshot)
        health = operational_health.status()
        self.assertEqual(health["derived_views"]["state"], "blocked")

    def test_symlink_generated_view_refuses_automatic_repair(self):
        folder = shared.shared_folder()
        original = folder / "prices.csv"
        original.unlink()
        original.symlink_to(folder / "daily_prices.csv")
        result = recovery.repair(automatic=True)
        self.assertEqual(result["state"], "blocked")
        self.assertTrue(original.is_symlink())

    def test_disk_limit_blocks_generated_repair_without_original_mutation(self):
        original = shared.shared_folder() / "prices.csv"
        original.unlink()
        with patch.object(recovery.shutil, "disk_usage",
                          return_value=type("Space", (), {"free": 10})()):
            result = recovery.repair()
        self.assertEqual(result["state"], "blocked")
        self.assertFalse(original.exists())

    def test_source_append_requires_derived_view_rebuild(self):
        original = shared.shared_folder() / "prices.csv"
        old_bytes = original.read_bytes()
        with shared._connect() as db:
            db.execute("INSERT INTO daily_closes VALUES (?,?,?,?)",
                       ("NSE_EQ:1333", "2026-02-03", 103., "a" * 64))
        check = recovery.inspect()
        self.assertEqual(check["state"], "needs_rebuild")
        self.assertEqual(recovery.repair(automatic=True)["state"], "repaired")
        self.assertNotEqual(original.read_bytes(), old_bytes)
        self.assertIn("2026-02-03", (shared.shared_folder() / "daily_prices.csv").read_text())


if __name__ == "__main__":
    unittest.main()
