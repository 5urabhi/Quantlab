"""Offline safety regression for opt-in Dhan-Web token renewal."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
import json
import os

from dotenv import dotenv_values

from workstation_api import dhan_session_maintenance as session


class MockResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self, limit=-1):
        return self.payload[:limit]


class RenewalTests(TestCase):
    def setUp(self):
        session.BLOCKED_FINGERPRINT = ""
        session.BLOCKED_UNTIL = 0

    def test_explicit_opt_in_is_required(self):
        with patch.object(session.auto_option_depth, "_config",
                          return_value={"enabled": True,
                                        "allow_token_renewal": False}), \
             patch.object(session.dhan_auth, "check_profile") as check:
            value = session.maintain()
        self.assertEqual(value["state"], "not_authorized")
        check.assert_not_called()

    def test_long_valid_token_never_renewed(self):
        with patch.object(session.auto_option_depth, "_config",
                          return_value={"enabled": True,
                                        "allow_token_renewal": True}), \
             patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "VALID_OLD_TOKEN_123456789"}), \
             patch.object(session.dhan_auth, "check_profile",
                          return_value={"ok": True, "token_valid": True,
                                        "seconds_remaining": 36000}), \
             patch.object(session.dhan_option_chain, "_client_id") as ident:
            value = session.maintain()
        self.assertEqual(value["state"], "valid")
        ident.assert_not_called()

    def test_expired_token_requires_user_reauthentication(self):
        with patch.object(session.auto_option_depth, "_config",
                          return_value={"enabled": True,
                                        "allow_token_renewal": True}), \
             patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "EXPIRED_TOKEN_123456789"}), \
             patch.object(session.dhan_auth, "check_profile",
                          return_value={"ok": False, "token_valid": False}):
            value = session.maintain()
        self.assertEqual(value["state"], "reauthorization_required")

    def test_pre_expiry_web_token_rotates_only_private_local_file(self):
        old = "VALID_OLD_DHAN_WEB_TOKEN_123456789"
        new = "VALID_NEW_DHAN_WEB_TOKEN_123456789"
        with TemporaryDirectory() as temp:
            target = Path(temp) / ".env"
            target.write_text('DHAN_ACCESS_TOKEN="' + old + '"\n', encoding="utf-8")
            target.chmod(0o600)
            with patch.object(session.service, "ROOT", Path(temp)), \
                 patch.object(session.auto_option_depth, "_config",
                              return_value={"enabled": True,
                                            "allow_token_renewal": True}), \
                 patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": old}), \
                 patch.object(session.dhan_auth, "check_profile",
                              return_value={"ok": True, "token_valid": True,
                                            "seconds_remaining": 2400}), \
                 patch.object(session.dhan_option_chain, "_client_id",
                              return_value="1000001234"):
                def vendor(request, timeout):
                    self.assertEqual(request.full_url, session.RENEW_URL)
                    self.assertEqual(request.get_method(), "GET")
                    self.assertEqual(timeout, 15)
                    return MockResponse({"accessToken": new})
                value = session.maintain(opener=vendor)
                self.assertEqual(value["state"], "renewed")
                self.assertEqual(os.environ["DHAN_ACCESS_TOKEN"], new)
                self.assertEqual(dotenv_values(target)["DHAN_ACCESS_TOKEN"], new)
                self.assertNotIn(old, target.read_text())
                self.assertNotIn(old, str(value))
                self.assertNotIn(new, str(value))

    def test_missing_private_file_never_invalidates_valid_token(self):
        token = "VALID_OLD_DHAN_WEB_TOKEN_123456789"
        with TemporaryDirectory() as temp:
            with patch.object(session.service, "ROOT", Path(temp)), \
                 patch.object(session.auto_option_depth, "_config",
                              return_value={"enabled": True,
                                            "allow_token_renewal": True}), \
                 patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": token}), \
                 patch.object(session.dhan_auth, "check_profile",
                              return_value={"ok": True, "token_valid": True,
                                            "seconds_remaining": 2400}), \
                 patch.object(session.dhan_option_chain, "_client_id") as ident:
                value = session.maintain()
                self.assertEqual(value["state"], "private_storage_needed")
                ident.assert_not_called()

    def test_rejected_renewal_does_not_leak_provider_body_or_token(self):
        old = "VALID_OLD_DHAN_WEB_TOKEN_123456789"
        with TemporaryDirectory() as temp:
            target = Path(temp) / ".env"
            target.write_text('DHAN_ACCESS_TOKEN="' + old + '"\n')
            target.chmod(0o600)
            with patch.object(session.service, "ROOT", Path(temp)), \
                 patch.object(session.auto_option_depth, "_config",
                              return_value={"enabled": True,
                                            "allow_token_renewal": True}), \
                 patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": old}), \
                 patch.object(session.dhan_auth, "check_profile",
                              return_value={"ok": True, "token_valid": True,
                                            "seconds_remaining": 2400}), \
                 patch.object(session.dhan_option_chain, "_client_id",
                              return_value="1000001234"):
                def denied(request, timeout):
                    raise HTTPError(request.full_url, 401, "secret broker response",
                                    {}, None)
                value = session.maintain(opener=denied)
            self.assertEqual(value["state"], "provider_renewal_unavailable")
            self.assertNotIn(old, str(value))
            self.assertNotIn("secret broker response", str(value))
            self.assertEqual(dotenv_values(target)["DHAN_ACCESS_TOKEN"], old)
