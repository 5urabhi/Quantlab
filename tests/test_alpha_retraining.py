from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from workstation_api import alpha_retraining as retrain, constituent_alpha as a
from workstation_api import constituent_prospective as p, alpha_model_registry as registry


NOW = datetime(2026, 11, 26, 13, tzinfo=timezone.utc)  # after IST market hours


def dates(n):
    return [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(n)]


def samples(day):
    return [{"session": day, "decision_utc": day + "T05:%02d:00+00:00" % i,
             "index": [float(i % 3 - 1), float(i)], "full": [float(i % 3 - 1), float(i), 1.],
             "class": i % 3 - 1, "return_bps": float((i % 3 - 1) * 20)}
            for i in range(6)]


class RollingRetrainingTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(a, "_root", return_value=Path(tmp.name)).start()
        patch.object(retrain, "_now", return_value=NOW).start()
        patch.object(retrain, "STOP").start().is_set.return_value = False
        patch.object(retrain, "WAKE").start()

    def test_opt_in_and_session_guard(self):
        self.assertFalse(retrain.config()["enabled"])
        with self.assertRaises(ValueError):
            retrain.configure(enabled=True, horizon=15)
        with self.assertRaises(ValueError):
            retrain.configure(enabled=True, horizon=7, confirm_local_research=True)
        self.assertTrue(retrain.configure(enabled=True, horizon=15, confirm_local_research=True)["config"]["enabled"])
        self.assertEqual(retrain.run(now=datetime(2026,11,26,5,tzinfo=timezone.utc))["state"], "paused")
        retrain.configure(enabled=False, horizon=15)
        self.assertEqual(retrain.run(now=NOW)["state"], "paused")

    def test_latest_sessions_not_earliest_and_excludes_today(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE banknifty_paired_signals (protocol_hash TEXT, horizon_minutes INTEGER, session_ist TEXT)")
        days = dates(70)
        db.executemany("INSERT INTO banknifty_paired_signals VALUES (?, ?, ?)",
                       [(p.protocol_for(15), 15, day) for day in days])
        db.execute("INSERT INTO banknifty_paired_signals VALUES (?, ?, ?)", (p.protocol_for(15), 15, days[-1]))
        self.assertEqual(retrain._recent_days(db,15,days[-1]), days[9:-1])
        self.assertEqual(retrain._recent_days(db,30,days[-1]), [])

    def test_cadence(self):
        ds = dates(70)
        self.assertFalse(retrain._due(ds[:59], {}, 60))
        self.assertTrue(retrain._due(ds[:60], {}, 60))
        self.assertFalse(retrain._due(ds[4:64], {"window_end":ds[59]}, 60))
        self.assertTrue(retrain._due(ds[5:65], {"window_end":ds[59]}, 60))
        self.assertFalse(retrain._due(ds[5:65], {"window_end":ds[59],
            "retry_after_utc":(NOW+timedelta(hours=4)).isoformat()},60))

    def test_freeze_two_models_then_wait_for_new_sessions(self):
        ds = dates(60)
        retrain.configure(enabled=True, horizon=15, confirm_local_research=True)
        with patch.object(retrain, "_latest", return_value=ds), \
             patch.object(a, "_read", side_effect=lambda: sqlite3.connect(":memory:")), \
             patch.object(a, "_rows", side_effect=lambda db, day, h: samples(day)), \
             patch.object(a, "sample_day", side_effect=lambda rows: (rows, {"scored":len(rows)})):
            result = retrain.run(now=NOW)
            self.assertEqual(result["state"], "candidates_saved")
            self.assertEqual(result["training_dates"], ds[:30])
            self.assertEqual(result["calibration_dates"], ds[30:40])
            self.assertEqual(result["holdout_dates"], ds[40:])
            self.assertEqual(len(result["models"]), 2)
            for candidate in result["models"]:
                frozen = registry.load(candidate["model_id"])
                self.assertFalse(frozen["live_approved"])
                self.assertEqual(frozen["reference_holdout_dates"], ds[40:])
                self.assertEqual(frozen["source_policy_sha256"], a.policy_for(15))
            self.assertTrue(a.result_path(result["audit_id"], audit=True).is_file())
            self.assertEqual(retrain.run(now=NOW)["state"], "awaiting_new_sessions")
        self.assertEqual(retrain.status()["last_run"]["state"], "candidates_saved")

    def test_missing_evidence_remains_in_window_and_not_retried_daily(self):
        ds = dates(60)
        retrain.configure(enabled=True, horizon=15, confirm_local_research=True)
        with patch.object(retrain, "_latest", return_value=ds), \
             patch.object(a, "_read", side_effect=lambda: sqlite3.connect(":memory:")), \
             patch.object(a, "_rows", return_value=[]), \
             patch.object(a, "sample_day", return_value=([], {"missing_label":1})):
            result = retrain.run(now=NOW)
            self.assertEqual(result["state"], "insufficient_matched_evidence")
            self.assertEqual(len(result["coverage"]), 60)
            self.assertEqual(result["holdout_dates"], ds[40:])
            self.assertEqual(result["models"], [])
            self.assertEqual(retrain.run(now=NOW)["state"], "awaiting_new_sessions")
