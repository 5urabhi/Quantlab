"""Read-only local-workstation operational integrity without provider access."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from workstation_api import operational_health, service, shared_market_data
from workstation_api.app import app


class OperationalHealthTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_operation_health_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        p=patch.object(service,"DATA",self.root/"data")
        p.start();self.addCleanup(p.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_uninitialized_original_source_is_not_a_broker_failure(self):
        with patch.object(operational_health.zerodha_fallback,"_request",
                          side_effect=AssertionError("Provider must never be contacted")):
            response=self.client.get("/api/data-manager/system-health")
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertTrue(data["read_only"])
        self.assertFalse(data["market_data_certified"])
        market=next(x for x in data["databases"] if x["id"]=="market_data")
        self.assertEqual(market["state"],"not_initialized")
        self.assertIn(data["overall_state"],
                      ("operational","needs_attention"))
        self.assertNotIn("access_token",response.text.lower())

    def test_valid_source_database_and_research_library_are_inspected(self):
        with shared_market_data._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA quick_check(1)").fetchone()[0],"ok")
        response=self.client.get("/api/data-manager/system-health")
        self.assertEqual(response.status_code,200,response.text)
        original=next(x for x in response.json()["databases"] if x["id"]=="market_data")
        self.assertEqual(original["state"],"ok")
        self.assertGreater(original["size_bytes"],0)

    def test_broker_config_checks_never_reveal_saved_secrets(self):
        with patch.dict("os.environ",{
            "KITE_API_KEY":"private_key_2026",
            "KITE_API_SECRET":"private_secret_2026",
            "KITE_ACCESS_TOKEN":"private_token_2026",
        }),patch.object(operational_health.zerodha_fallback,"_request",
                       side_effect=AssertionError("No live API requests")):
            result=operational_health.status()
        text=str(result)
        self.assertNotIn("private_secret_2026",text)
        self.assertNotIn("private_token_2026",text)
        self.assertFalse(result["market_data_certified"])


if __name__=="__main__":
    unittest.main()
