"""Explicit one-click historical download + model calculation; never invent source data."""
from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from workstation_api import app as api


class HistoricalCompletionAndRunTests(TestCase):
    def setUp(self):
        self.params = {"target": "stock", "ticker": "NSE_EQ_1023"}
        self.acquired = {
            "status": "ready", "dataset_id": "dhan_shared",
            "selected_ticker": "NSE_EQ_1023",
            "message": "Cached originals and uncovered Dhan windows prepared",
            "after": {"runnable": True, "missing_to_target": 0},
        }

    def test_one_explicit_job_backfills_rechecks_runs_and_saves(self):
        progress = []
        with patch.object(api.data_acquisition, "execute", return_value=self.acquired) as acquire, \
             patch.object(api.model_data_manager, "inspect",
                          return_value={"runnable": True, "missing_to_target": 0}) as audit, \
             patch.object(api.model_lab, "run_model",
                          return_value={"model_id": "heston_proxy"}) as run, \
             patch.object(api.model_lab, "save_result",
                          return_value={"run_id": "model_123"}) as save:
            result = api._complete_lab_history_and_run(
                "heston_proxy", "dhan_shared", self.params,
                progress=lambda n, msg: progress.append((n, msg)))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["run_id"], "model_123")
        self.assertEqual(result["dataset_id"], "dhan_shared")
        self.assertEqual(result["selected_ticker"], "NSE_EQ_1023")
        acquire.assert_called_once()
        audit.assert_called_once_with("heston_proxy", "dhan_shared", self.params)
        run.assert_called_once_with("heston_proxy", "dhan_shared", self.params)
        save.assert_called_once()
        self.assertEqual(progress[-1][0], 99)

    def test_selected_stock_follows_verified_dhan_identity(self):
        original = {"target": "stock", "ticker": "FEDERALBNK"}
        with patch.object(api.data_acquisition, "execute", return_value=self.acquired), \
             patch.object(api.model_data_manager, "inspect",
                          return_value={"runnable": True, "missing_to_target": 0}), \
             patch.object(api.model_lab, "run_model",
                          return_value={"model_id": "heston_proxy"}) as run, \
             patch.object(api.model_lab, "save_result", return_value={"run_id": "model_123"}):
            result = api._complete_lab_history_and_run(
                "heston_proxy", "dhan_shared", original)
        self.assertEqual(result["run_id"], "model_123")
        run.assert_called_once_with(
            "heston_proxy", "dhan_shared",
            {"target": "stock", "ticker": "NSE_EQ_1023"})

    def test_insufficient_observed_history_never_runs_model(self):
        incomplete = {**self.acquired, "status": "incomplete",
                      "after": {"runnable": False, "missing_to_target": 72}}
        with patch.object(api.data_acquisition, "execute", return_value=incomplete), \
             patch.object(api.model_data_manager, "inspect",
                          return_value={"runnable": False, "missing_to_target": 72}), \
             patch.object(api.model_lab, "run_model") as run, \
             patch.object(api.model_lab, "save_result") as save:
            result = api._complete_lab_history_and_run(
                "heston_proxy", "dhan_shared", self.params)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["run_id"])
        run.assert_not_called()
        save.assert_not_called()

    def test_provider_failure_does_not_execute_or_archive(self):
        with patch.object(api.data_acquisition, "execute",
                          side_effect=ValueError("Provider history not available")), \
             patch.object(api.model_lab, "run_model") as run, \
             patch.object(api.model_lab, "save_result") as save:
            with self.assertRaisesRegex(ValueError, "Provider history"):
                api._complete_lab_history_and_run(
                    "heston_proxy", "dhan_shared", self.params)
        run.assert_not_called()
        save.assert_not_called()

    def test_getting_missing_history_requires_explicit_confirmation(self):
        with TestClient(api.app, base_url="http://localhost") as client:
            response = client.post("/api/lab/data-requirements/extend", json={
                "model_id": "heston_proxy", "dataset_id": "dhan_shared",
                "params": self.params, "run_after_download": True,
                "confirm_download": False})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Explicit download confirmation", response.text)

    def test_explicit_run_flag_selects_single_download_and_run_job(self):
        seen = []
        def fake_spawn(kind, action, *args):
            seen.append((kind, action, args))
            return {"job_id": "queued_test", "status": "queued"}
        with patch.object(api.model_data_manager, "inspect",
                          return_value={"can_download": True}), \
             patch.object(api, "_spawn", side_effect=fake_spawn), \
             TestClient(api.app, base_url="http://localhost") as client:
            for run_after_download in (False, True):
                response = client.post("/api/lab/data-requirements/extend", json={
                    "model_id": "heston_proxy", "dataset_id": "dhan_shared",
                    "params": self.params, "run_after_download": run_after_download,
                    "confirm_download": True})
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item[0] for item in seen],
                         ["lab_shared_data_extension", "lab_shared_data_extension_and_run"])
        self.assertIs(seen[0][1], api.data_acquisition.execute)
        self.assertIs(seen[1][1], api._complete_lab_history_and_run)
