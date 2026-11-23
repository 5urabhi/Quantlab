"""Offline tests for bounded automatic complete BANKNIFTY option chains.

No live HTTP requests, broker orders, secrets, or sleeping worker threads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from fastapi.testclient import TestClient

from workstation_api.app import app
from workstation_api import auto_option_chain as chains
from workstation_api import auto_option_depth as depth


class AutomaticCompleteChainTests(TestCase):
    def test_cadences_keep_near_expiries_fresher_than_distant(self):
        self.assertEqual(chains._period(0), 30)
        self.assertEqual(chains._period(1), 60)
        self.assertEqual(chains._period(2), 300)
        self.assertEqual(chains._period(5), 300)
        self.assertEqual(chains._period(6), 1800)

    def test_overdue_nearest_is_not_starved_by_far_expiry(self):
        expiries = ["2026-11-24", "2026-12-29", "2027-03-30",
                    "2027-06-29", "2027-12-28", "2028-06-27",
                    "2028-12-26"]
        schedule = {expiry: 100.0 for expiry in expiries}
        self.assertEqual(chains._choose_due(expiries, schedule, 200.0),
                         expiries[0])
        # A future-due near option does not block an overdue distant expiry.
        schedule[expiries[0]] = 260.0
        schedule[expiries[1]] = 260.0
        self.assertEqual(chains._choose_due(expiries, schedule, 200.0),
                         expiries[2])
        self.assertIsNone(chains._choose_due(expiries,
                                            {e: 300 for e in expiries}, 200))

    def test_archive_is_not_started_without_saved_user_consent(self):
        with patch.object(chains, "_enabled", return_value=False):
            with patch.object(chains.Thread, "start") as start:
                chains.resume_if_armed()
                start.assert_not_called()
            self.assertFalse(chains.status()["armed"])

    def test_capture_status_never_returns_token_or_client_id(self):
        with patch.object(chains, "_enabled", return_value=True), \
             patch.object(chains, "_market_open", return_value=False), \
             patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "SECRET123",
                                      "DHAN_CLIENT_ID": "12345678"}):
            response = chains.status()
        self.assertTrue(response["armed"])
        self.assertTrue(response["read_only"])
        self.assertFalse(response["depth_all_contracts"])
        self.assertNotIn("SECRET123", str(response))
        self.assertNotIn("12345678", str(response))

    def test_status_endpoint_has_no_vendor_side_effects(self):
        with patch.object(chains, "_enabled", return_value=False), \
             patch.object(chains, "_market_open", return_value=False):
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                response = client.get("/api/trading-cockpit/auto-chain/status")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["read_only"])
        self.assertFalse(response.json()["armed"])

    def test_daily_archive_count_uses_ist_not_host_local_time(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "shared_market.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE option_chain_observations("
                           "underlying TEXT, captured_utc TEXT)")
                db.executemany("INSERT INTO option_chain_observations VALUES (?,?)", [
                    ("BANKNIFTY", "2026-11-18T18:29:59+00:00"),
                    ("BANKNIFTY", "2026-11-18T18:30:00+00:00"),
                    ("BANKNIFTY", "2026-11-19T08:00:00+00:00"),
                    ("BANKNIFTY", "2026-11-19T18:29:59+00:00"),
                    ("BANKNIFTY", "2026-11-19T18:30:00+00:00"),
                    ("NIFTY50", "2026-11-19T08:00:00+00:00"),
                ])
            now = datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc)
            with patch.object(chains.shared_market_data, "database_path",
                              return_value=path), \
                 patch.object(chains, "_now", return_value=now):
                self.assertEqual(chains._daily_total(), 3)

    def test_arm_endpoint_starts_both_read_only_collectors(self):
        with patch.object(depth, "arm", return_value={"armed": True}), \
             patch.object(chains, "resume_if_armed") as resume, \
             patch.object(chains, "status",
                          return_value={"armed": True, "read_only": True}):
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                resume.reset_mock()  # Exclude FastAPI startup hook from endpoint assertion.
                response = client.post("/api/trading-cockpit/auto-depth/arm",
                                       json={"confirm_live_data": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["option_chain_capture"]["armed"])
        resume.assert_called_once()

    def test_disarm_endpoint_stops_both_data_collectors(self):
        with patch.object(depth, "disarm", return_value={"armed": False}), \
             patch.object(chains, "disarmed") as disarmed, \
             patch.object(chains, "status",
                          return_value={"armed": False, "read_only": True}):
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                response = client.post("/api/trading-cockpit/auto-depth/disarm",
                                       json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["option_chain_capture"]["armed"])
        disarmed.assert_called_once()
