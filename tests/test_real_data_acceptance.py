"""End-to-end acceptance receipts refuse certification on software evidence alone."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from fastapi.testclient import TestClient
from workstation_api import real_data_acceptance, research_acceptance, service
from workstation_api.app import app


class RealSourceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_evidence_acceptance_")
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        for key,name in (("DATA","data"),("RESULTS","results")):
            p=patch.object(service,key,root/name)
            p.start();self.addCleanup(p.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def _evidence(self,ready=False,synthetic=False):
        return {
            "dataset_id":"example_observed","dataset_kind":"synthetic" if synthetic else "dhan",
            "structural_run_ready":ready,
            "independent_source_certified":False,
            "publication_certified":False,
            "checks":[
                {"name":"Monthly price panel","status":"pass" if ready else "blocked",
                 "detail":"Original required months","next_action":"Append observed sessions"},
                {"name":"Total-return benchmark provenance","status":"review",
                 "detail":"TRI levels imported locally, not issuer certified",
                 "next_action":"Compare issuer source and return convention"},
                {"name":"Corporate-action return parity","status":"blocked",
                 "detail":"Original ex-date dividends are absent",
                 "next_action":"Import and reconcile original dividend events"},
                {"name":"Chronological frozen test design","status":"pass" if ready else "blocked",
                 "detail":"Separate train/validation/final periods",
                 "next_action":"Choose a valid untouched final-test holdout"}
            ],
            "timing":{"validation_start":"2024-01-01",
                      "final_test_start":"2025-01-01","months_before_validation":48,
                      "months_in_final_test":15},
            "source_hashes":{"prices.csv":"a"*64},
        }

    def test_real_acceptance_never_promotes_source_certification(self):
        with patch.object(real_data_acceptance.historical_readiness,"inspect",
                          return_value=self._evidence(ready=True)), \
             patch.object(research_acceptance,"verify",
                          return_value={"id":"audit_fake","software_pass":3,
                                        "software_fail":0,"checks":[
                                            {"model_id":"min_variance","state":"software_pass"}]}) as verify:
            report=real_data_acceptance.execute(
                "example_observed","2024-01-01","2025-01-01")
        self.assertEqual(report["status"],
                         "structurally_runnable_not_independently_certified")
        self.assertFalse(report["independently_certified"])
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["model_software_pass"],3)
        self.assertEqual(report["source_checks_blocked"],1)
        self.assertGreaterEqual(len(report["blockers"]),2)
        self.assertTrue(any("dividend" in b["detail"].lower()
                            for b in report["blockers"]))
        verify.assert_called_once()
        saved=real_data_acceptance.report(report["id"])
        self.assertEqual(saved["id"],report["id"])
        self.assertEqual(real_data_acceptance.recent()["reports"][0]["id"],report["id"])

    def test_missing_structural_input_remains_blocked(self):
        with patch.object(real_data_acceptance.historical_readiness,"inspect",
                          return_value=self._evidence(ready=False)), \
             patch.object(research_acceptance,"verify",
                          return_value={"software_pass":0,"software_fail":1,
                                        "checks":[]}) as verify:
            report=real_data_acceptance.execute(
                "example_observed","2024-01-01","2025-01-01")
        self.assertEqual(report["status"],"original_sources_or_models_incomplete")
        self.assertFalse(report["structural_ready"])
        self.assertEqual(report["model_software_fail"],1)
        verify.assert_called_once()

    def test_synthetic_fixtures_never_run_as_original_empirical_models(self):
        with patch.object(real_data_acceptance.historical_readiness,"inspect",
                          return_value=self._evidence(synthetic=True)), \
             patch.object(research_acceptance,"verify") as never:
            report=real_data_acceptance.execute(
                "example_observed","2024-01-01","2025-01-01")
        self.assertEqual(report["model_software_pass"],0)
        self.assertFalse(report["independently_certified"])
        never.assert_not_called()

    def test_previous_source_hash_report_cannot_be_called_current_after_changes(self):
        # Exercise the actual report-fetch freshness gate; no real broker data.
        original=service.DATA.parent/"observed"
        original.mkdir(exist_ok=True)
        (original/"prices.csv").write_text("date,SECURITY_A\\n2021-01-31,100\\n")
        with patch.object(real_data_acceptance.historical_readiness,"inspect",
                          return_value=self._evidence(ready=True)), \
             patch.object(research_acceptance,"verify",return_value={
                 "attempted_models":1,"software_pass":1,
                 "software_fail":0,"checks":[{"state":"software_pass"}]}) as verify, \
             patch.object(service,"dataset_path",
                          return_value=(original,{"kind":"dhan"})):
            snap=real_data_acceptance.execute(
                "example_observed","2024-01-01","2025-01-01")
            read=real_data_acceptance.report(snap["id"])
            self.assertFalse(read["current_source_match"])
            self.assertFalse(read["current_evidence_usable"])
            self.assertIn("changed",read["current_source_status"])
            self.assertFalse(read["independently_certified"])
            verify.assert_called_once()
            # Return the actual current hash to mark only a matching snapshot
            # as current, without granting external exchange certification.
            from workstation_api import historical_readiness
            with patch.object(historical_readiness,"source_hashes",
                              return_value=snap["source_hashes"]):
                matching=real_data_acceptance.report(snap["id"])
            self.assertTrue(matching["current_source_match"])
            self.assertFalse(matching["independently_certified"])

    def test_api_requires_consent_and_nonoverlapping_chronology(self):
        data={"dataset_id":"not_real","validation_start":"2025-01-01",
              "final_test_start":"2024-01-01","confirm_real_data_audit":False}
        r=self.client.post("/api/data-manager/research/acceptance/run",json=data)
        self.assertEqual(r.status_code,400)
        r=self.client.get("/api/data-manager/research/acceptance/report/../")
        self.assertNotEqual(r.status_code,200)
        self.assertEqual(real_data_acceptance.recent()["reports"],[])

if __name__=="__main__":
    unittest.main()
