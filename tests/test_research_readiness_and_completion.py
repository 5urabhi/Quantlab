"""Actual software readiness vs historical evidence and one-click execution."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from fastapi.testclient import TestClient

from workstation_api import (model_lab, model_readiness, model_registry,
                             research_acceptance, research_workflow, service)
from workstation_api.app import app


class ResearchCompletionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="quantlab_complete_workflow_")
        self.addCleanup(tmp.cleanup)
        for key,name in (("DATA","data"),("RESULTS","results")):
            x=patch.object(service,key,Path(tmp.name)/name)
            x.start();self.addCleanup(x.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_every_registered_model_has_actionable_source_status(self):
        r=self.client.get("/api/data-manager/research/overview")
        self.assertEqual(r.status_code,200,r.text)
        body=r.json()
        self.assertEqual(body["total_models"],len(model_registry.MODELS))
        self.assertEqual(len(body["models"]),len(model_registry.MODELS))
        self.assertTrue(all(m["action"]["kind"] for m in body["models"]))
        self.assertTrue(all("minimum_observed_returns" in m["requirement"]
                            for m in body["models"]))
        self.assertFalse(body["sources"]["requirements"][0]["verified_by_exchange"])
        self.assertEqual(body["historical_source_ready"],0)

    def test_original_membership_and_tri_are_not_falsely_certified(self):
        data=research_acceptance.sources()
        self.assertEqual(data["membership_status"],"missing_or_invalid")
        ids={x["id"] for x in data["requirements"]}
        self.assertEqual(ids,{"pit_nifty50","pit_banknifty","nifty_tri","corporate_actions"})
        self.assertTrue(data["no_unverified_history_promoted"])
        for requirement in data["requirements"]:
            self.assertFalse(requirement["verified_by_exchange"])

    def test_theoretical_model_runs_and_saves_without_historical_dataset(self):
        with patch.object(model_lab,"run_model",
                          return_value={"model_id":"black_scholes","metrics":[]}) as run, \
             patch.object(model_lab,"save_result",
                          return_value={"id":"saved_theory_1"}) as save:
            result=research_workflow.execute("black_scholes",None,params={})
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["data_kind"],"theoretical")
        run.assert_called_once()
        save.assert_called_once()

    def test_historical_model_without_dataset_never_creates_seeded_run(self):
        with patch.object(model_lab,"run_model") as run:
            result=research_workflow.execute("min_variance",None,params={})
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(result["action"],"choose_dataset")
        run.assert_not_called()

    def test_empirical_model_with_no_original_history_never_claims_ready(self):
        with patch.object(model_lab,"run_model") as run:
            r=self.client.get("/api/data-manager/research/overview")
        self.assertEqual(r.status_code,200,r.text)
        historical=[x for x in r.json()["models"] if x["mode"]=="historical"]
        self.assertTrue(historical)
        self.assertTrue(all(x["status"]!="source_available" for x in historical))
        run.assert_not_called()

    def test_software_audit_records_pass_and_separate_external_truth(self):
        only=[
            {"id":"black_scholes","mode":"theoretical","status":"math_ready",
             "group":"Theory","title":"BSM"},
            {"id":"min_variance","mode":"historical","status":"need_historical_data",
             "group":"Optimization","title":"MinVar"},
        ]
        mockmatrix={"models":only,"total_models":2,"blocked":1}
        with patch.object(research_acceptance,"overview",return_value=mockmatrix), \
             patch.object(model_lab,"run_model",
                          return_value={"model_id":"black_scholes","plots":[]}) as run:
            audit=research_acceptance.verify(None,include_historical=False)
        self.assertEqual(audit["software_pass"],1)
        self.assertEqual(audit["source_blocked"],1)
        self.assertFalse(audit["historical_data_externally_verified"])
        run.assert_called_once()
        receipts=research_acceptance.audit_list()["audits"]
        self.assertEqual(receipts[0]["id"],audit["id"])

    def test_research_launch_requires_registered_model(self):
        r=self.client.post("/api/data-manager/research/resolve-run",json={
            "model_id":"made_up","params":{}})
        self.assertEqual(r.status_code,400)
        r2=self.client.post("/api/data-manager/research/verify",json={
            "confirm_software_check":False})
        self.assertEqual(r2.status_code,400)


if __name__=="__main__":
    unittest.main()
