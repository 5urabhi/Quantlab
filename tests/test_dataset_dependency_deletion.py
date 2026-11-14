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
        first, p1 = self._model_run("abb0000001")
        plan = self._plan()
        refused = self._trash(plan["preview_token"], confirm=False)
        self.assertEqual(refused.status_code, 400)
        self.assertTrue(p1.exists() and self.folder.exists())
        _, p2 = self._model_run("abb0000002")
        changed = self._trash(plan["preview_token"])
        self.assertEqual(changed.status_code, 400)
        self.assertIn("changed", changed.json()["detail"])
        self.assertTrue(p1.exists() and p2.exists())
        self.assertTrue(self.folder.exists())

    def test_notebook_report_and_saved_run_move_together_with_one_confirmation(self):
        run_id, file = self._model_run("c0ffee0001")
        notebook = research_library.create(
            "notebook", "Notebook using this run",
            {"cells": [{"run_id": run_id}]})
        report = research_library.create(
            "report", "Report based on notebook",
            {"notebook_id": notebook["id"]})
        plan = self._plan()
        self.assertTrue(plan["can_delete_all"])
        self.assertEqual(plan["dependent_run_count"], 1)
        self.assertEqual(plan["dependent_count"], 3)
        self.assertEqual({item["id"] for item in plan["dependent_items"]},
                         {run_id, notebook["id"], report["id"]})
        self.assertEqual(plan["blocking_references"], [])
        self.assertTrue(self.folder.exists())
        self.assertFalse(research_library.get(notebook["id"])["trashed"])
        response = self._trash(plan["preview_token"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(file.exists())
        self.assertFalse(self.folder.exists())
        self.assertTrue(research_library.get(notebook["id"])["trashed"])
        self.assertTrue(research_library.get(report["id"])["trashed"])
        self.assertTrue(self.shared.exists())
        # All can be restored from local recoverable Trash.
        research_library.resource_action("dataset", self.dataset_id, "restore")
        research_library.resource_action("model_run", run_id, "restore")
        research_library.action(notebook["id"], "restore")
        research_library.action(report["id"], "restore")
        self.assertTrue(file.exists())
        self.assertTrue(self.folder.exists())

    def test_linked_derived_tri_version_and_its_results_move_together(self):
        child = service.DATA / "workstation_imports" / "derived_tri_case"
        child.mkdir()
        (child / "workstation_source.json").write_text(
            json.dumps({"parent_dataset_id": self.dataset_id}))
        run_id, path = self._model_run("f00dcafe01")
        payload = json.loads(path.read_text())
        payload["source"]["dataset_id"] = "upload_derived_tri_case"
        path.write_text(json.dumps(payload))
        plan = self._plan()
        self.assertTrue(plan["can_delete_all"])
        self.assertTrue(any(x["kind"] == "dataset" and "derived" in x["id"]
                            for x in plan["dependent_items"]))
        self.assertTrue(any(x["id"] == run_id for x in plan["dependent_items"]))
        receipt = self._trash(plan["preview_token"])
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertFalse(child.exists())
        self.assertFalse(path.exists())
        self.assertFalse(self.folder.exists())
        self.assertTrue(self.shared.exists())
        research_library.resource_action("dataset", self.dataset_id, "restore")
        research_library.resource_action("dataset", "upload_derived_tri_case", "restore")
        research_library.resource_action("model_run", run_id, "restore")
        self.assertTrue(child.exists() and path.exists() and self.folder.exists())

    def test_old_archive_option_keeps_every_saved_reference_unchanged(self):
        run_id, path = self._model_run("abcde00123")
        notebook = research_library.create(
            "notebook", "Keep notebook", {"run_id": run_id})
        research_library.resource_action("dataset", self.dataset_id, "archive")
        self.assertTrue(path.exists())
        self.assertTrue(self.folder.exists())
        self.assertFalse(research_library.get(notebook["id"])["trashed"])
        self.assertFalse(any(x["id"] == self.dataset_id for x in service.datasets()))
        research_library.resource_action("dataset", self.dataset_id, "unarchive")
        self.assertTrue(any(x["id"] == self.dataset_id for x in service.datasets()))

    def test_direct_existing_delete_still_refuses_unsafe_or_protected_sources(self):
        self._model_run("deface1234")
        direct = self.client.post("/api/workspace/resources/action", json={
            "kind": "dataset", "item_id": self.dataset_id,
            "action": "trash", "confirm": True})
        self.assertEqual(direct.status_code, 400)
        self.assertIn("referenced", direct.json()["detail"])
        other = self.client.get("/api/workspace/datasets/synthetic/delete-plan")
        self.assertEqual(other.status_code, 400)

    def test_failed_cascade_restores_prior_run_moves(self):
        run_id, path = self._model_run("badc0de001")
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
