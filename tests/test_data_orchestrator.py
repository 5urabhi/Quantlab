"""End-to-end tests for the unified local-first Database Manager.

All fixtures are local. No Dhan requests, credentials, exchange scraping,
broker orders, or synthetic claims of original market validation.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workstation_api import data_orchestrator as manager, service
from workstation_api.app import app


class DataManagerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="quantlab_database_manager_")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        data_patch = patch.object(service, "DATA", self.root / "data")
        data_patch.start()
        self.addCleanup(data_patch.stop)
        result_patch = patch.object(service, "RESULTS", self.root / "results")
        result_patch.start()
        self.addCleanup(result_patch.stop)
        self.folder = service.DATA / "dhan" / "monthly_research" / "batch_aaaaaaaaaaaaaaaa"
        self.folder.mkdir(parents=True)
        (self.folder / "prices.csv").write_text(
            "date,AAA,BBB\n2026-01-30,100,200\n2026-02-27,101,201\n"
            "2026-03-31,102,202\n2026-04-30,103,203\n", encoding="utf-8")
        (self.folder / "membership.csv").write_text(
            "date,ticker,eligible\n2026-01-30,AAA,True\n", encoding="utf-8")
        self.id = "dhan_batch_aaaaaaaaaaaaaaaa"
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_inventory_row_explorer_and_pagination(self):
        board = self.client.get("/api/data-manager/overview")
        self.assertEqual(board.status_code, 200, board.text)
        self.assertIn(self.id, [x["id"] for x in board.json()["datasets"]])
        details = self.client.get("/api/data-manager/datasets/" + self.id)
        self.assertEqual(details.status_code, 200, details.text)
        self.assertIn("prices.csv", details.json()["available_tables"])
        rows = self.client.get("/api/data-manager/datasets/" + self.id + "/table",
                               params={"file": "prices.csv", "page": 1, "per_page": 2})
        self.assertEqual(rows.status_code, 200, rows.text)
        self.assertEqual(len(rows.json()["rows"]), 2)
        self.assertTrue(rows.json()["has_more"])
        next_page = self.client.get("/api/data-manager/datasets/" + self.id + "/table",
                                    params={"page": 2, "per_page": 2})
        self.assertEqual(next_page.status_code, 200, next_page.text)
        self.assertEqual(next_page.json()["rows"][0]["AAA"], "102")
        self.assertFalse(next_page.json()["has_more"])
        filtered = self.client.get("/api/data-manager/datasets/" + self.id + "/table",
                                   params={"query": "2026-04", "columns": "date,AAA"})
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(len(filtered.json()["rows"]), 1)

    def test_reject_unapproved_table_and_invalid_column(self):
        blocked = self.client.get("/api/data-manager/datasets/" + self.id + "/table",
                                  params={"file": "../../.env"})
        self.assertEqual(blocked.status_code, 400)
        bad_column = self.client.get("/api/data-manager/datasets/" + self.id + "/table",
                                     params={"columns": "password"})
        self.assertEqual(bad_column.status_code, 400)
        self.assertNotIn("DHAN_ACCESS_TOKEN", blocked.text)

    def test_profile_sources_and_activity_are_source_safe(self):
        profile = self.client.get("/api/data-manager/datasets/" + self.id + "/quality")
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["status"], "sample_pass")
        self.assertEqual(profile.json()["sampled_rows"], 4)
        sources = self.client.get("/api/data-manager/sources")
        self.assertEqual(sources.status_code, 200)
        self.assertEqual(sources.json()["sources"]["nse_mcp"]["research_data_import"], False)
        manager.event("maintenance", "complete", "Validated derived view metadata")
        recent = self.client.get("/api/data-manager/activity")
        self.assertEqual(recent.status_code, 200)
        self.assertEqual(recent.json()["events"][0]["category"], "maintenance")

    def test_maintenance_does_not_touch_original_market_rows(self):
        before = (self.folder / "prices.csv").read_bytes()
        result = manager.safe_maintenance()
        self.assertEqual(result["repaired"], [])
        self.assertFalse(result["original_observations_changed"])
        self.assertEqual(before, (self.folder / "prices.csv").read_bytes())

    def test_duplicate_automatic_replay_claim_is_idempotent(self):
        self.assertTrue(manager.claim_automatic_retry("0123456789abcdef"))
        self.assertFalse(manager.claim_automatic_retry("0123456789abcdef"))
        manager.record_automatic_retry("0123456789abcdef", "queued")


if __name__ == "__main__":
    unittest.main()
