"""Durable operation progress, safe diagnostics and Dhan queue-state regressions."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from workstation_api import app as api, dhan_workspace, job_safety, research_library, service


class DurableOperationsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="quantlab_durable_jobs_")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        p = patch.object(service, "DATA", root / "data")
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(api.app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_upgrade_previous_library_schema_without_losing_jobs(self):
        file = research_library.root() / "library.sqlite3"
        file.parent.mkdir(parents=True)
        with sqlite3.connect(file) as db:
            db.executescript("""
                CREATE TABLE job_history(
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                  created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
                  error TEXT, result_excerpt TEXT
                );
                INSERT INTO job_history VALUES (
                  '1111222233334444','workspace_validation','complete',
                  '2026-11-17T00:00:00Z','2026-11-17T00:00:00Z',NULL,NULL);
            """)
        research_library.store_job({
            "id": "aaaabbbbccccdddd", "kind": "workspace_validation",
            "status": "running", "created_utc": "2026-11-17T01:00:00Z",
            "percent": 34.1, "stage": "Reading original stock dates",
        })
        rows = {j["id"]: j for j in research_library.list_job_history()}
        self.assertIn("1111222233334444", rows)
        self.assertEqual(rows["aaaabbbbccccdddd"]["percent"], 34.1)
        self.assertEqual(rows["aaaabbbbccccdddd"]["status"], "interrupted")
        self.assertEqual(rows["aaaabbbbccccdddd"]["stage"],
                         "Interrupted after last safely saved checkpoint")
        self.assertEqual(rows["1111222233334444"]["status"], "complete")

    def test_old_job_link_survives_restart_without_fabricated_result(self):
        research_library.store_job({
            "id": "1234567890abcdef", "kind": "workspace_validation",
            "status": "running", "percent": 72,
            "stage": "Writing bounded source diagnostics",
        })
        with patch.object(api, "JOBS", {}):
            response = self.client.get("/api/jobs/1234567890abcdef")
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()
        self.assertEqual(item["status"], "interrupted")
        self.assertEqual(item["percent"], 72)
        self.assertFalse(item["retryable"])
        self.assertIn("restart", item["error"])
        self.assertNotIn("result", item)
        missing = self.client.get("/api/jobs/1111111111111111")
        self.assertEqual(missing.status_code, 404)

    def test_job_error_secret_redaction_both_disk_and_browser(self):
        secret = "sample_kite_access_123456789"
        with patch.dict("os.environ", {"KITE_ACCESS_TOKEN": secret,
                                      "DHAN_ACCESS_TOKEN": "dhansecret_123456"}):
            sanitized = job_safety.scrub(
                "Kite expired: access_token=" + secret + " "
                "https://api.kite.trade/path?request_token=EXPOSEME "
                "authorization: Bearer topsecret "
                "Dhan dhansecret_123456")
            self.assertNotIn(secret, sanitized)
            self.assertNotIn("EXPOSEME", sanitized)
            self.assertNotIn("topsecret", sanitized)
            self.assertNotIn("dhansecret_123456", sanitized)
            self.assertIn("REDACTED", sanitized)
            api._persist_job({
                "id": "feedefee11223344", "kind": "provider_qa",
                "status": "error", "error": "Error access_token=" + secret,
                "stage": "Waiting: api_secret=SUPERSECRET",
            })
        entries = {x["id"]: x for x in research_library.list_job_history()}
        self.assertNotIn(secret, entries["feedefee11223344"]["error"])
        self.assertNotIn("SUPERSECRET", entries["feedefee11223344"]["stage"])

    def test_scheduled_batch_never_appears_interrupted_before_worker_starts(self):
        batch_id = "batch_0123456789abcdef"
        data = {
            "id": batch_id, "status": "queued",
            "created_utc": "2026-11-17T08:00:00Z",
            "from_date": "2026-11-01", "to_date": "2026-11-17",
            "selection": "watchlist", "interval": None,
            "items": [{"symbol": "RELIANCE", "security_id": "1333",
                       "status": "pending", "rows": 0}],
        }
        self.assertEqual(dhan_workspace._summarize(data)["status"], "interrupted")
        dhan_workspace.schedule_batch(batch_id)
        try:
            self.assertEqual(dhan_workspace._summarize(data)["status"], "queued")
            with self.assertRaisesRegex(ValueError, "already scheduled"):
                dhan_workspace.schedule_batch(batch_id)
        finally:
            dhan_workspace.unschedule_batch(batch_id)
        self.assertEqual(dhan_workspace._summarize(data)["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
