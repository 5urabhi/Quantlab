"""Recover interrupted Dhan CSV + manifest commits without network or fake OHLCV.

All original market observations below are synthetic offline fixtures. The
fault injection simulates a Python process interruption precisely between
the two canonical file renames, including cold-start and existing-cache cases.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from workstation_api import dhan_workspace as dw, dhan_checkpoint, service


class OriginalDhanCheckpointTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="quantlab_dhan_checkpoint_")
        self.addCleanup(t.cleanup)
        p = patch.object(service, "DATA", Path(t.name) / "data")
        p.start()
        self.addCleanup(p.stop)
        self.row = {
            "id": "NSE_EQ:1333", "security_id": "1333",
            "exchange_segment": "NSE_EQ", "symbol": "RELIANCE",
        }
        self.target = dw._history_file(self.row, None)
        self.manifest = self.target.with_suffix(".json")
        self.pending = self.target.with_suffix(".pending.json")

    @staticmethod
    def candles(inst, first, last, **kwargs):
        start = pd.Timestamp(first)
        end = pd.Timestamp(last)
        dates = pd.date_range(start, end - pd.Timedelta(days=1), freq="B")
        if dates.empty:
            raise ValueError("No candles returned for " + inst.label)
        count = len(dates)
        return pd.DataFrame({
            "datetime": dates.tz_localize("Asia/Kolkata"),
            "open": 100 + pd.Series(range(count)),
            "high": 105 + pd.Series(range(count)),
            "low": 95 + pd.Series(range(count)),
            "close": 102 + pd.Series(range(count)),
            "volume": [1000] * count,
            "security_id": [inst.security_id] * count,
            "exchange_segment": [inst.exchange_segment] * count,
        })

    def _interrupt_on(self, target: Path):
        """Leave the exact on-disk state Python would leave if killed."""
        actual = os.replace
        def fault(src, dest):
            if Path(dest) == target:
                raise RuntimeError("Simulated process stopped between publication renames")
            return actual(src, dest)
        return patch.object(dw.os, "replace", side_effect=fault)

    def test_first_window_interruption_recovers_exact_csv_without_broker_call(self):
        with patch.object(dw, "download_candles", side_effect=self.candles):
            with self._interrupt_on(self.manifest):
                with self.assertRaisesRegex(RuntimeError, "Simulated process"):
                    dw._fetch_history(self.row, "2025-01-01", "2025-02-01", None)
        self.assertTrue(self.target.is_file())
        self.assertFalse(self.manifest.exists())
        self.assertTrue(self.pending.is_file())
        original = self.target.read_bytes()
        with patch.object(dw, "download_candles",
                          side_effect=AssertionError("Never redownload already verified original bytes")):
            done = dw._fetch_history(self.row, "2025-01-01", "2025-02-01", None)
        self.assertEqual(done["status"], "cached")
        self.assertEqual(done["recovered_checkpoints"], 1)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(self.pending.exists())
        self.assertEqual(json.loads(self.manifest.read_text())["sha256"],
                         dhan_checkpoint.digest(self.target))
        self.assertEqual(len(json.loads(self.manifest.read_text())["coverage"]), 1)

    def test_extended_history_preserves_prior_original_and_recovers_new_window(self):
        with patch.object(dw, "download_candles", side_effect=self.candles):
            initial = dw._fetch_history(self.row, "2025-01-01", "2025-02-01", None)
        self.assertEqual(initial["status"], "complete")
        old_bytes = self.target.read_bytes()
        old_receipt = json.loads(self.manifest.read_text())
        with patch.object(dw, "download_candles", side_effect=self.candles):
            with self._interrupt_on(self.manifest):
                with self.assertRaisesRegex(RuntimeError, "Simulated process"):
                    dw._fetch_history(self.row, "2025-01-01", "2025-03-01", None)
        new_bytes = self.target.read_bytes()
        self.assertNotEqual(old_bytes, new_bytes)
        self.assertEqual(json.loads(self.manifest.read_text()), old_receipt)
        with patch.object(dw, "download_candles",
                          side_effect=AssertionError("Already published source must not refetch")):
            done = dw._fetch_history(self.row, "2025-01-01", "2025-03-01", None)
        self.assertEqual(done["status"], "cached")
        self.assertEqual(done["recovered_checkpoints"], 1)
        self.assertEqual(self.target.read_bytes(), new_bytes)
        self.assertEqual(len(json.loads(self.manifest.read_text())["coverage"]), 2)
        self.assertGreater(len(pd.read_csv(self.target)), len(pd.read_csv(
            self.target.with_name("never_created.csv"))) if False else 0)

    def test_journal_mismatch_blocks_and_preserves_all_conflicting_source_bytes(self):
        with patch.object(dw, "download_candles", side_effect=self.candles):
            dw._fetch_history(self.row, "2025-01-01", "2025-02-01", None)
        with patch.object(dw, "download_candles", side_effect=self.candles):
            with self._interrupt_on(self.manifest):
                with self.assertRaisesRegex(RuntimeError, "Simulated process"):
                    dw._fetch_history(self.row, "2025-01-01", "2025-03-01", None)
        self.target.write_bytes(self.target.read_bytes() + b"\n# TAMPERED")
        damaged = self.target.read_bytes()
        journal = self.pending.read_bytes()
        with patch.object(dw, "download_candles",
                          side_effect=AssertionError("No redownload on source conflict")):
            with self.assertRaisesRegex(ValueError, "receipts disagree"):
                dw._fetch_history(self.row, "2025-01-01", "2025-03-01", None)
        self.assertEqual(self.target.read_bytes(), damaged)
        self.assertEqual(self.pending.read_bytes(), journal)

    def test_crash_before_csv_replace_keeps_old_checkpoint_and_resumes_missing(self):
        with patch.object(dw, "download_candles", side_effect=self.candles):
            dw._fetch_history(self.row, "2025-01-01", "2025-02-01", None)
        original = self.target.read_bytes()
        with patch.object(dw, "download_candles", side_effect=self.candles):
            with self._interrupt_on(self.target):
                with self.assertRaisesRegex(RuntimeError, "Simulated process"):
                    dw._fetch_history(self.row, "2025-01-01", "2025-03-01", None)
        self.assertEqual(original, self.target.read_bytes())
        self.assertTrue(self.pending.is_file())
        with patch.object(dw, "download_candles", side_effect=self.candles) as vendor:
            done = dw._fetch_history(self.row, "2025-01-01", "2025-03-01", None)
        self.assertEqual(vendor.call_count, 1)
        self.assertEqual(done["status"], "complete")
        self.assertEqual(done["recovered_checkpoints"], 0)
        self.assertFalse(self.pending.exists())
        self.assertEqual(len(json.loads(self.manifest.read_text())["coverage"]), 2)

    def test_live_os_error_after_csv_replace_can_recover_without_failure(self):
        orig = os.replace
        failed = [False]
        def once(src, dst):
            if Path(dst) == self.manifest and not failed[0]:
                failed[0] = True
                raise OSError("Simulated transient filesystem rename interruption")
            return orig(src, dst)
        with patch.object(dw, "download_candles", side_effect=self.candles):
            with patch.object(dw.os, "replace", side_effect=once):
                done = dw._fetch_history(self.row, "2025-01-01", "2025-02-01", None)
        self.assertEqual(done["status"], "complete")
        self.assertTrue(done["recovered_checkpoints"])
        self.assertEqual(json.loads(self.manifest.read_text())["sha256"],
                         dhan_checkpoint.digest(self.target))
        self.assertFalse(self.pending.exists())


if __name__ == "__main__":
    unittest.main()
