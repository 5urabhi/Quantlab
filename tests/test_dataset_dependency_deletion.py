"""Deletion UX: explicit dependency preview and reversible, safe cascade."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import unittest

from fastapi.testclient import TestClient

from workstation_api import research_library, service, model_lab
from workstation_api.app import app


class DatasetDeletionPlanTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="quantlab_delete_preview_")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        data = root / "data"
        results = root / "results" / "workstation_runs"
        p1 = patch.object(service, "DATA", data)
        p2 = patch.object(service, "RESULTS", results)
        p1.start()
        p2.start()
        self.addCleanup(p2.stop)
        self.addCleanup(p1.stop)
        self.folder = data / "workstation_imports" / "delete_preview_case"
        self.folder.mkdir(parents=True)
        self.dataset_id = "upload_delete_preview_case"
        (self.folder / "prices.csv").write_text("date,A\n2026-10-30,123\n")
        (self.folder / "membership.csv").write_text("date,ticker,eligible\n2026-10-30,A,true\n")
        (self.folder / "benchmark.csv").write_text("date,benchmark\n2026-10-30,0.01\n")
        self.original_sha = hashlib.sha256((self.folder / "benchmark.csv").read_bytes()).hexdigest()
        self.shared = data / "dhan" / "history" / "persistent.csv"
        self.shared.parent.mkdir(parents=True)
        self.shared.write_text("stock,close\nA,123\n")
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def _model_run(self, suffix):
        run_id = "20261113T174650Z_" + suffix
        root = model_lab._run_root()
        root.mkdir(parents=True, exist_ok=True)
        file = root / (run_id + ".json")
        file.write_text(json.dumps({
            "run_id": run_id,
            "model_id": "gbm", "source": {"dataset_id": self.dataset_id},
            "title": "Saved model " + suffix, "plots": [],
        }))
        return run_id, file

    def _plan(self):
        response = self.client.get(
            "/api/workspace/datasets/" + self.dataset_id + "/delete-plan")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _trash(self, token, confirm=True):
        return self.client.post(
            "/api/workspace/datasets/" + self.dataset_id + "/trash-with-saved-runs",
            json={"preview_token": token, "confirm": confirm})

    def test_plan_is_readonly_and_cascade_moves_two_runs_to_recoverable_trash(self):
        first, p1 = self._model_run("a43558ab6c")
        second, p2 = self._model_run("63a6ea6de9")
        plan = self._plan()
        self.assertTrue(plan["can_archive"])
        self.assertTrue(plan["can_trash_with_saved_runs"])
        self.assertEqual(plan["dependent_run_count"], 2)
        self.assertEqual({x["id"] for x in plan["dependent_runs"]}, {first, second})
        self.assertEqual(plan["blocking_references"], [])
        self.assertEqual(len(plan["preview_token"]), 64)
        self.assertTrue(self.folder.exists())
        self.assertTrue(p1.exists() and p2.exists())
        response = self._trash(plan["preview_token"])
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()
        self.assertFalse(receipt["permanently_purged"])
        self.assertEqual(receipt["dependent_run_count"], 2)
        self.assertFalse(self.folder.exists())
        self.assertFalse(p1.exists() or p2.exists())
        self.assertTrue(self.shared.exists())
        self.assertTrue(research_library.resource_status("dataset", self.dataset_id)["trashed"])
        for run_id in (first, second):
            self.assertTrue(research_library.resource_status("model_run", run_id)["trashed"])
        # Both saved runs and the original uploaded TRI dataset are recoverable.
        research_library.resource_action("dataset", self.dataset_id, "restore")
        research_library.resource_action("model_run", first, "restore")
        research_library.resource_action("model_run", second, "restore")
        self.assertTrue(p1.exists() and p2.exists())
        self.assertEqual(hashlib.sha256((self.folder/"benchmark.csv").read_bytes()).hexdigest(),
                         self.original_sha)

    def test_cancel_or_stale_preview_never_deletes_data(self):
        first, p1 = self._model_run("old000001")
        plan = self._plan()
        refused = self._trash(plan["preview_token"], confirm=False)
        self.assertEqual(refused.status_code, 400)
        self.assertTrue(p1.exists() and self.folder.exists())
        _, p2 = self._model_run("new000002")
        changed = self._trash(plan["preview_token"])
        self.assertEqual(changed.status_code, 400)
        self.assertIn("changed", changed.json()["detail"])
        self.assertTrue(p1.exists() and p2.exists())
        self.assertTrue(self.folder.exists())

    def test_notebook_reference_blocks_cascade_but_archive_is_available(self):
        run_id, p1 = self._model_run("notebook01")
        research_library.create("notebook", "Do not orphan this notebook",
                                {"cells": [{"run_id": run_id}]})
        plan = self._plan()
        self.assertFalse(plan["can_trash_with_saved_runs"])
        self.assertTrue(plan["blocking_references"])
        self.assertEqual(self._trash(plan["preview_token"]).status_code, 400)
        self.assertTrue(p1.exists() and self.folder.exists())
        research_library.resource_action("dataset", self.dataset_id, "archive")
        self.assertTrue(self.folder.exists())
        self.assertFalse(any(x["id"] == self.dataset_id for x in service.datasets()))
        self.assertTrue(any(x["id"] == self.dataset_id
                            for x in service.datasets(include_archived=True)))
        research_library.resource_action("dataset", self.dataset_id, "unarchive")

    def test_linked_derived_tri_version_protects_original_source(self):
        child = service.DATA / "workstation_imports" / "derived_tri_case"
        child.mkdir()
        (child / "workstation_source.json").write_text(
            json.dumps({"parent_dataset_id": self.dataset_id}))
        plan = self._plan()
        self.assertFalse(plan["can_trash_with_saved_runs"])
        self.assertTrue(any(x["kind"] == "dataset" and "derived" in x["id"]
                            for x in plan["blocking_references"]))
        self.assertEqual(self._trash(plan["preview_token"]).status_code, 400)
        self.assertTrue(self.folder.exists())

    def test_direct_existing_delete_still_refuses_unsafe_or_protected_sources(self):
        self._model_run("other1234")
        direct = self.client.post("/api/workspace/resources/action", json={
            "kind": "dataset", "item_id": self.dataset_id,
            "action": "trash", "confirm": True})
        self.assertEqual(direct.status_code, 400)
        self.assertIn("referenced", direct.json()["detail"])
        other = self.client.get("/api/workspace/datasets/synthetic/delete-plan")
        self.assertEqual(other.status_code, 400)

    def test_failed_cascade_restores_prior_run_moves(self):
        run_id, path = self._model_run("rollback01")
        plan = self._plan()
        original = research_library.resource_action

        def faulty_action(kind, item_id, operation, *, confirm=False):
            if kind == "dataset" and operation == "trash":
                raise ValueError("Injected dataset move failure")
            return original(kind, item_id, operation, confirm=confirm)

        with patch.object(research_library, "resource_action", side_effect=faulty_action):
            response = self._trash(plan["preview_token"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("restored", response.json()["detail"])
        self.assertTrue(self.folder.exists())
        self.assertTrue(path.exists())
        self.assertFalse(research_library.resource_status("model_run", run_id)["trashed"])
        self.assertTrue(self.shared.exists())


if __name__ == "__main__":
    unittest.main()
