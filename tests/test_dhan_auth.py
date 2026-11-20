"""Dhan profile preflight tests; no live brokerage network or tokens."""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo
import json

from fastapi.testclient import TestClient
from workstation_api.app import app
from workstation_api import dhan_auth


class MockResponse:
    def __init__(self, document):
        self.data = json.dumps(document).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self, size=-1):
        return self.data[:size] if size >= 0 else self.data


class DhanAuthTests(TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
    def tearDown(self):
        self.client.close()

    def test_missing_token(self):
        with patch.dict("os.environ", {}, clear=True):
            state = dhan_auth.check_profile()
        self.assertEqual(state["code"], "token_missing")
        self.assertFalse(state["ok"])

    def test_profile_reports_active_data_plan_without_exposing_account(self):
        future = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=15))
        document = {"dhanClientId": "SECRET_PRIVATE_ACCOUNT",
                    "tokenValidity": future.strftime("%d/%m/%Y %H:%M"),
                    "dataPlan": "Active", "dataValidity": "2027-01-01"}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "SECRET_PRIVATE_TOKEN"}):
            result = dhan_auth.check_profile(opener=lambda *a, **kw: MockResponse(document))
        self.assertTrue(result["ok"])
        self.assertTrue(result["token_valid"])
        self.assertTrue(result["data_plan_active"])
        self.assertNotIn("SECRET_PRIVATE_ACCOUNT", str(result))
        self.assertNotIn("SECRET_PRIVATE_TOKEN", str(result))
        self.assertIsInstance(result["seconds_remaining"], int)
        self.assertGreater(result["seconds_remaining"], 0)
        self.assertIsNotNone(result["expires_at_utc"])
        self.assertNotIn("SECRET_PRIVATE_ACCOUNT", result["expires_at_utc"])

    def test_client_id_match_is_checked_without_exposing_identity(self):
        future = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=12)
        payload = {"dhanClientId":"1000001234",
                   "tokenValidity":future.strftime("%d/%m/%Y %H:%M"),
                   "dataPlan":"Active"}
        good=dhan_auth.check_profile(
            opener=lambda *a,**kw:MockResponse(payload),
            token_override="PRIVATE_TEST_TOKEN",
            client_id_override="1000001234")
        self.assertTrue(good["ok"])
        self.assertTrue(good["client_id_matches"])
        self.assertNotIn("1000001234",str(good))
        mismatch=dhan_auth.check_profile(
            opener=lambda *a,**kw:MockResponse(payload),
            token_override="PRIVATE_TEST_TOKEN",
            client_id_override="1000009999")
        self.assertFalse(mismatch["ok"])
        self.assertFalse(mismatch["client_id_matches"])
        self.assertEqual(mismatch["code"],"client_id_mismatch")
        self.assertNotIn("1000001234",str(mismatch))

    def test_profile_client_id_is_resolvable_without_manual_entry(self):
        future = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=12)
        document = {"dhanClientId": "1000001234",
                    "tokenValidity": future.strftime("%d/%m/%Y %H:%M"),
                    "dataPlan": "Active"}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "SECRET_PRIVATE_TOKEN",
                                     "DHAN_CLIENT_ID": ""}):
            result = dhan_auth.check_profile(
                opener=lambda *args, **kwargs: MockResponse(document))
        self.assertTrue(result["client_id_auto_available"])
        self.assertTrue(result["client_id_ready"])
        self.assertEqual(result["client_id_source"], "authenticated_profile")
        self.assertFalse(result["client_id_configured"])
        self.assertNotIn("1000001234", str(result))
        self.assertNotIn("SECRET_PRIVATE_TOKEN", str(result))

    def test_expired_token_is_not_truthy_validity(self):
        past = (datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(days=3))
        document = {"tokenValidity": past.strftime("%d/%m/%Y %H:%M"),
                    "dataPlan": "Active"}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "mock"}):
            result = dhan_auth.check_profile(opener=lambda *a, **kw: MockResponse(document))
        self.assertEqual(result["code"], "token_expired")
        self.assertFalse(result["token_valid"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["seconds_remaining"], 0)

    def test_data_api_inactive_does_not_pass(self):
        future = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)
        doc = {"tokenValidity": future.strftime("%d/%m/%Y %H:%M"),
               "dataPlan": "Deactive"}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "mock"}):
            result = dhan_auth.check_profile(opener=lambda *a, **kw: MockResponse(doc))
        self.assertEqual(result["code"], "data_plan_inactive")
        self.assertFalse(result["ok"])

    def test_terminal_logs_status_without_account_secrets(self):
        future = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=10)
        profile = {"dhanClientId": "HIDDEN_ACCOUNT", "tokenValidity":
                   future.strftime("%d/%m/%Y %H:%M"), "dataPlan": "Active"}
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "HIDDEN_TOKEN"}):
            with self.assertLogs("quantlab.dhan.auth", level="INFO") as events:
                state = dhan_auth.check_profile(
                    opener=lambda *a, **kw: MockResponse(profile))
        text = "\\n".join(events.output)
        self.assertTrue(state["ok"])
        self.assertIn("code=ready", text)
        self.assertNotIn("HIDDEN_ACCOUNT", text)
        self.assertNotIn("HIDDEN_TOKEN", text)

    def test_401_is_rejected_without_exposing_vendor_body(self):
        def opener(req, timeout):
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, BytesIO(b"PRIVATE"))
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "mock"}):
            result = dhan_auth.check_profile(opener=opener)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "auth_rejected")
        self.assertNotIn("PRIVATE", str(result))

    def test_loopback_endpoint_missing_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            response = self.client.get("/api/dhan/credentials/check")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["code"], "token_missing")
