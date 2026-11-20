"""Offline acceptance for the unified user-approved market data workflow.

No HTTP request leaves these tests. Original Dhan candles are never fetched.
"""
from __future__ import annotations

from datetime import date, timedelta
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import dhan_workspace, market_data_workflow as market, service
from workstation_api.app import app

api_module = importlib.import_module("workstation_api.app")


class UnifiedMarketDataTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="quantlab_market_workspace_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        p = patch.object(service, "DATA", self.root / "data")
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        master = service.DATA / "dhan" / "instrument_master.csv"
        master.parent.mkdir(parents=True)
        pd.DataFrame([
            {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "E",
             "SEM_SMST_SECURITY_ID": "1333", "SEM_INSTRUMENT_NAME": "EQUITY",
             "SEM_TRADING_SYMBOL": "RELIANCE", "SEM_CUSTOM_SYMBOL": "Reliance Industries",
             "SEM_SERIES": "EQ"},
            {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "E",
             "SEM_SMST_SECURITY_ID": "11536", "SEM_INSTRUMENT_NAME": "EQUITY",
             "SEM_TRADING_SYMBOL": "TCS", "SEM_CUSTOM_SYMBOL": "TCS Ltd",
             "SEM_SERIES": "EQ"},
        ]).to_csv(master, index=False)
        dhan_workspace._catalog_cached.cache_clear()
        self.addCleanup(dhan_workspace._catalog_cached.cache_clear)
        self.from_date = "2026-01-01"
        self.to_date = "2026-03-01"

    def _params(self, **kw):
        return {"selection": "watchlist", "from_date": self.from_date,
                "to_date": self.to_date, "tickers": "RELIANCE,TCS", **kw}

    def _approved(self):
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "LOCAL_FIXTURE_SECRET"}):
            result = self.client.get("/api/market-data/plan", params=self._params())
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_empty_workspace_plan_is_read_only_and_explains_missing_credentials(self):
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": ""}):
            result = self.client.get("/api/market-data/plan", params=self._params())
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data["instrument_count"], 2)
        self.assertFalse(data["can_start"])
        self.assertIn("Connect Dhan", str(data["next_actions"]))
        self.assertFalse((service.DATA / "dhan" / "batches").exists())
        self.assertNotIn("LOCAL_FIXTURE_SECRET", str(data))

    def test_model_preview_includes_true_plus_twenty_percent_target(self):
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "TEST_VALUE"}):
            value = self.client.get("/api/market-data/plan",
                                    params=self._params(model_id="garch")).json()
        req = value["model_requirements"]
        self.assertEqual(req["minimum"], 60)
        self.assertEqual(req["preferred"], 72)
        self.assertTrue(req["suggested_from"])
        self.assertFalse(value["dhan"]["credential_verified"])

    def test_unmapped_symbols_never_get_guessed(self):
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "TEST_VALUE"}):
            value = self.client.get("/api/market-data/plan",
                                    params=self._params(tickers="RELIANCE,UNKNOWN"))
        self.assertEqual(value.status_code, 200)
        self.assertFalse(value.json()["can_start"])
        self.assertIn("Unknown", str(value.json()["blockers"]))
        bad_symbol = self.client.get("/api/market-data/plan",
                                     params=self._params(tickers="../../.env"))
        self.assertEqual(bad_symbol.status_code, 400)

    def test_plan_changes_invalidate_approval_before_any_live_check(self):
        current = self._approved()
        body = {
            "selection": "watchlist", "from_date": self.from_date,
            "to_date": self.to_date, "tickers": ["RELIANCE", "TCS"],
            "interval": None, "preview_token": current["preview_token"],
            "confirm_readonly": True,
        }
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "LOCAL_FIXTURE_SECRET"}):
            with patch.object(api_module.dhan_auth, "check_profile") as verify:
                result = self.client.post("/api/market-data/start",
                                          json={**body, "tickers": ["RELIANCE"]})
                self.assertEqual(result.status_code, 400)
                self.assertIn("Review", result.text)
                verify.assert_not_called()
        self.assertFalse((service.DATA / "dhan" / "batches").exists())

    def test_preflight_refuses_expired_credentials_and_does_not_create_batch(self):
        current = self._approved()
        body = {
            "selection": "watchlist", "from_date": self.from_date,
            "to_date": self.to_date, "tickers": ["RELIANCE", "TCS"],
            "preview_token": current["preview_token"], "confirm_readonly": True
        }
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "LOCAL_FIXTURE_SECRET"}):
            with patch.object(api_module.dhan_auth, "check_profile",
                              return_value={"ok": False, "message": "Dhan Data API inactive"}):
                response = self.client.post("/api/market-data/start", json=body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Data API inactive", response.text)
        self.assertFalse((service.DATA / "dhan" / "batches").exists())

    def test_explicit_approval_uses_existing_single_dhan_batch_engine(self):
        plan = self._approved()
        body = {
            "selection": "watchlist", "from_date": self.from_date,
            "to_date": self.to_date, "tickers": ["RELIANCE", "TCS"],
            "preview_token": plan["preview_token"], "confirm_readonly": True,
        }
        captured = []
        def pretend_to_queue(request):
            captured.append(request)
            return {"job_id": "offline_fake_job", "status": "queued",
                    "batch": {"id": "batch_offline"}}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "LOCAL_FIXTURE_SECRET"}):
            with patch.object(api_module.dhan_auth, "check_profile",
                              return_value={"ok": True}):
                with patch.object(api_module, "create_dhan_batch", side_effect=pretend_to_queue):
                    response = self.client.post("/api/market-data/start", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].selection, "watchlist")
        self.assertEqual(captured[0].tickers, ["RELIANCE", "TCS"])
        self.assertFalse(captured[0].include_index_spot)

    def test_index_membership_gap_cannot_silently_truncate_date_range(self):
        past = {"available": True, "first_date": "2015-01-01",
                "covered_through": "2026-02-10", "source_commit": "original_version"}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "LOCAL_FIXTURE_SECRET"}):
            with patch.object(market.pit_index, "status", return_value=past):
                value = market.plan("banknifty_pit", "2026-01-01", "2026-03-01")
        self.assertFalse(value["can_start"])
        self.assertEqual(value["membership"]["state"], "needs_source")
        self.assertIn("Historical index membership", str(value["blockers"]))
        self.assertEqual(value["to_date"], "2026-03-01")

    def test_unresolved_constituents_require_separate_incomplete_consent(self):
        source = {"available": True, "first_date": "2015-01-01",
                  "covered_through": "2026-11-10", "source_commit": "fixture_version"}
        members = {"resolved_count": 2, "union_count": 3, "change_count": 1,
                   "unresolved": [{"symbol": "DELISTED", "reason": "Not in present-day master"}]}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "LOCAL_FIXTURE_SECRET"}):
            with patch.object(market.pit_index, "status", return_value=source):
                with patch.object(market.pit_index, "query", return_value=members):
                    value = market.plan("nifty50_pit", self.from_date, self.to_date)
                    self.assertEqual(value["unresolved_count"], 1)
                    self.assertTrue(value["can_start"])
                    with self.assertRaisesRegex(ValueError, "incomplete"):
                        market.approve(
                            value["preview_token"], "nifty50_pit",
                            self.from_date, self.to_date, None, [], "",
                            allow_incomplete=False, confirm_bulk=True)
                    approved = market.approve(
                        value["preview_token"], "nifty50_pit",
                        self.from_date, self.to_date, None, [], "",
                        allow_incomplete=True, confirm_bulk=True)
        self.assertEqual(approved["instrument_count"], 2)

    def test_dhan_in_app_token_requires_read_only_verification_and_private_storage(self):
        import os
        import stat
        secret = "LOCAL_OFFLINE_DHAN_TEST_TOKEN_1234567"
        target = self.root / ".env"
        with patch.object(service, "ROOT", self.root):
            with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": ""}):
                payload = {"access_token": secret,
                           "confirm_local_storage": True}
                with patch.object(market.dhan_auth, "check_profile",
                                  return_value={"ok": False,
                                                "message": "Dhan Data API not active"}):
                    denied = self.client.post(
                        "/api/market-data/providers/dhan/connect", json=payload)
                self.assertEqual(denied.status_code, 400)
                self.assertNotIn(secret, denied.text)
                self.assertFalse(target.exists())
                with patch.object(market.dhan_auth, "check_profile",
                                  return_value={"ok": True,
                                                "data_plan_active": True}) as verify, \
                     patch.object(api_module.auto_option_depth, "resume_if_armed") as depth_start, \
                     patch.object(api_module.auto_option_chain, "resume_if_armed") as chain_start:
                    response = self.client.post(
                        "/api/market-data/providers/dhan/connect", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                depth_start.assert_called_once()
                chain_start.assert_called_once()
                self.assertTrue(response.json()["automatic_recording"])
                self.assertNotIn(secret, response.text)
                self.assertEqual(verify.call_args.kwargs["token_override"], secret)
                self.assertTrue(target.is_file())
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertIn('DHAN_ACCESS_TOKEN=', target.read_text())
                self.assertEqual(os.getenv("DHAN_ACCESS_TOKEN"), secret)
                initial = target.read_bytes()
                bad = self.client.post("/api/market-data/providers/dhan/connect",
                                       json={"access_token": "INJECTED\nVALUE",
                                             "confirm_local_storage": True})
                self.assertEqual(bad.status_code, 400)
                self.assertEqual(target.read_bytes(), initial)

    def test_public_sources_require_explicit_confirmation(self):
        response = self.client.post("/api/market-data/sources/prepare",
                                    json={"selection": "nifty50_pit",
                                          "to_date": self.to_date})
        self.assertEqual(response.status_code, 400)
        with patch.object(api_module, "_spawn", return_value={
                "job_id": "offline_source_job", "status": "queued"}) as worker:
            confirmed = self.client.post("/api/market-data/sources/prepare", json={
                "selection": "nifty50_pit", "to_date": self.to_date,
                "confirm_public_sources": True})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(worker.call_args.args[0], "market_source_setup")


if __name__ == "__main__":
    unittest.main()
