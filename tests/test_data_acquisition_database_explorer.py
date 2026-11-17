"""Offline acceptance for the next-stage source planner and read-only DB viewer.

All tests use local fixtures and mocks; no Dhan token or market request.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workstation_api import data_acquisition, database_inspector, service
from workstation_api.app import app


class ModelAcquisitionAndDbExplorerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="quantlab_planner_explorer_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        data_patcher = patch.object(service, "DATA", self.root / "data")
        data_patcher.start()
        self.addCleanup(data_patcher.stop)
        results_patcher = patch.object(service, "RESULTS", self.root / "results")
        results_patcher.start()
        self.addCleanup(results_patcher.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def _market_database(self):
        path = service.DATA / "dhan" / "shared_market.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE instruments (
                    identity TEXT PRIMARY KEY,exchange_segment TEXT,
                    security_id TEXT,display_symbol TEXT);
                CREATE TABLE daily_closes (
                    identity TEXT, session_date TEXT, close REAL,
                    source_sha256 TEXT, PRIMARY KEY(identity, session_date));
                INSERT INTO instruments VALUES ('NSE_EQ:1','NSE_EQ','1','RELIANCE');
                INSERT INTO instruments VALUES ('NSE_EQ:2','NSE_EQ','2','INFY');
                INSERT INTO daily_closes VALUES('NSE_EQ:1','2026-11-13',101.5,'abc');
                INSERT INTO daily_closes VALUES('NSE_EQ:2','2026-11-13',201.5,'def');
            """)
        return path

    def _research_database(self):
        path = service.DATA / "research_workspace" / "library.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,title TEXT,
                    payload TEXT,tags TEXT,favorite INTEGER,archived INTEGER,
                    trashed INTEGER,created_utc TEXT,updated_utc TEXT);
                INSERT INTO records VALUES(
                    'run_1','note','Saved factor study','CREDENTIAL_SHOULD_NEVER_APPEAR',
                    '[]',0,0,0,'2026-11-13','2026-11-14');
            """)
        return path

    def test_plan_with_missing_dataset_prompts_for_source(self):
        response = self.client.get("/api/data-manager/acquisition-plan",
                                   params={"model_id":"min_variance"})
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()
        self.assertEqual(plan["phase"], "choose_dataset")
        self.assertEqual(plan["requirements"]["target_returns"], 72)
        self.assertFalse(plan["can_acquire"])
        self.assertEqual(len(plan["preview_token"]), 64)
        self.assertFalse(any(s["id"] == "nse_mcp"
                             and s["state"] == "requires_confirmation"
                             for s in plan["source_chain"]))

    def test_theoretical_plan_does_not_start_market_data(self):
        result = data_acquisition.plan("black_scholes")
        self.assertEqual(result["phase"], "run_without_market_data")
        self.assertEqual(result["estimated_new_dhan_requests"], 0)
        self.assertFalse(result["can_acquire"])

    def test_missing_authorization_and_stale_receipt_block_vendor_use(self):
        fake = {
            "status": "insufficient", "mode": "historical", "runnable": False,
            "can_download": True, "missing_to_target": 50, "missing_minimum": 20,
            "min_returns": 60, "target_returns": 72,
            "estimated_vendor_daily_requests": 3, "suggested_start": "2025-01-01",
            "suggested_end_exclusive": "2026-01-01", "selected_assets": ["AAA"],
        }
        with patch.object(data_acquisition.model_data_manager, "inspect", return_value=fake):
            plan = data_acquisition.plan(
                "min_variance", "dhan_batch_aaaa", {"assets":8}, with_sources=False)
            self.assertTrue(plan["confirmation_required"])
            with self.assertRaisesRegex(ValueError, "Confirm"):
                data_acquisition.check_confirmation(
                    "min_variance","dhan_batch_aaaa",{"assets":8},
                    plan["preview_token"],False)
            fake["missing_to_target"] = 51
            with self.assertRaisesRegex(ValueError, "changed"):
                data_acquisition.check_confirmation(
                    "min_variance","dhan_batch_aaaa",{"assets":8},
                    plan["preview_token"],True)

    def test_only_cache_reuse_does_not_need_new_provider_consent(self):
        fake = {
            "status":"insufficient","mode":"historical","runnable":False,
            "can_download":True,"missing_to_target":25,"missing_minimum":10,
            "min_returns":60,"target_returns":72,
            "estimated_vendor_daily_requests":0,"missing_uncovered_windows":0,
            "selected_assets":["AAA"],
        }
        with patch.object(data_acquisition.model_data_manager,"inspect",return_value=fake):
            plan=data_acquisition.plan("min_variance","dhan_batch_aaaa",
                                       {"assets":8},with_sources=False)
            self.assertEqual(plan["phase"],"reuse_cache")
            self.assertFalse(plan["confirmation_required"])
            verified=data_acquisition.check_confirmation(
                "min_variance","dhan_batch_aaaa",{"assets":8},
                plan["preview_token"],False)
            self.assertEqual(verified["phase"],"reuse_cache")

    def test_broker_api_not_called_by_any_readonly_plan(self):
        with patch("workstation_api.dhan_auth.check_profile",
                   side_effect=AssertionError("No live broker calls in GET")):
            response=self.client.get("/api/data-manager/acquisition-plan",
                                     params={"model_id":"min_variance"})
        self.assertEqual(response.status_code,200,response.text)

    def test_allowlisted_market_table_exact_filter_and_pagination(self):
        self._market_database()
        response = self.client.get("/api/data-manager/database-catalog")
        self.assertEqual(response.status_code,200,response.text)
        market=next(x for x in response.json()["databases"] if x["id"]=="market_data")
        self.assertTrue(market["available"])
        first=self.client.get("/api/data-manager/database-table",params={
            "database_id":"market_data","table":"instruments","page":1,"per_page":1})
        self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(first.json()["has_more"])
        second=self.client.get("/api/data-manager/database-table",params={
            "database_id":"market_data","table":"instruments","page":2,"per_page":1})
        self.assertEqual(second.status_code,200,second.text)
        self.assertFalse(second.json()["has_more"])
        exact=self.client.get("/api/data-manager/database-table",params={
            "database_id":"market_data","table":"daily_closes",
            "filter_column":"identity","filter_value":"NSE_EQ:2"})
        self.assertEqual(exact.status_code,200,exact.text)
        self.assertEqual(len(exact.json()["rows"]),1)
        self.assertEqual(exact.json()["rows"][0]["close"],201.5)

    def test_restricted_payload_and_table_injection_are_never_exposed(self):
        self._research_database()
        catalog=self.client.get("/api/data-manager/database-catalog").json()
        library=next(x for x in catalog["databases"] if x["id"]=="research_library")
        cols=next(x for x in library["tables"] if x["name"]=="records")["columns"]
        self.assertNotIn("payload",[c["name"] for c in cols])
        rows=self.client.get("/api/data-manager/database-table",params={
            "database_id":"research_library","table":"records"})
        self.assertEqual(rows.status_code,200,rows.text)
        self.assertNotIn("CREDENTIAL_SHOULD_NEVER_APPEAR",rows.text)
        invalid=self.client.get("/api/data-manager/database-table",params={
            "database_id":"research_library","table":"records;DROP TABLE records"})
        self.assertEqual(invalid.status_code,400)
        invalid_col=self.client.get("/api/data-manager/database-table",params={
            "database_id":"research_library","table":"records",
            "filter_column":"payload","filter_value":"SECRET"})
        self.assertEqual(invalid_col.status_code,400)
        with sqlite3.connect(service.DATA/"research_workspace"/"library.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM records").fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
