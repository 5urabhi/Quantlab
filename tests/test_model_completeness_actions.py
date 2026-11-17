"""Model completeness is code availability, not real-market certification.

These offline tests verify that *every* advertised model has executable
Python dispatch or a source-specific setup path. No financial data is
invented and no external API/credentials are needed.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from workstation_api import model_readiness, model_registry, service
from workstation_api.app import app

class RegisteredModelCompletenessTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(prefix="quantlab_model_completion_")
        self.addCleanup(tmp.cleanup)
        change=patch.object(service,"DATA",Path(tmp.name)/"data")
        change.start();self.addCleanup(change.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_all_catalog_models_have_explicit_implementation_and_provenance(self):
        response=self.client.get("/api/lab/catalog")
        self.assertEqual(response.status_code,200,response.text)
        models=response.json()["models"]
        self.assertGreaterEqual(len(models),30)
        self.assertEqual(len(models),len(set(m["id"] for m in models)))
        for item in models:
            with self.subTest(model=item["id"]):
                self.assertEqual(item["status"],"runnable")
                self.assertEqual(item["implementation_status"],"implemented")
                self.assertIn(item["evidence_type"],
                    {"simulation","theory","observed_history","observed_quote"})
                self.assertTrue(item["setup_steps"])
                self.assertTrue(all(isinstance(s,str) and len(s)>12
                                    for s in item["setup_steps"]))
                self.assertNotIn("DEMO",item["implementation_status"].upper())
                if item["mode"] in {"historical","market"}:
                    self.assertTrue(any("original" in x.lower() or
                                        "observed" in x.lower()
                                        for x in item["setup_steps"]))

    def test_every_model_has_actionable_readiness_steps_without_sources(self):
        response=self.client.get("/api/lab/model-readiness")
        self.assertEqual(response.status_code,200,response.text)
        matrix=response.json()
        self.assertEqual(matrix["implemented_models"],len(model_registry.MODELS))
        self.assertEqual(matrix["total_models"],len(model_registry.MODELS))
        self.assertEqual(len(matrix["models"]),len(model_registry.MODELS))
        self.assertEqual(matrix["historical_source_ready"],0)
        self.assertEqual(matrix["option_source_ready"],0)
        for item in matrix["models"]:
            with self.subTest(model=item["id"]):
                self.assertTrue(item["implementation_ready"])
                self.assertEqual(item["implementation_status"],"implemented")
                self.assertIn(item["next_action_kind"],
                    {"run_math","select_dataset","option_quotes",
                     "select_quote","select_stock","get_history","open_model"})
                self.assertGreaterEqual(len(item["setup_steps"]),3)
                for step in item["setup_steps"]:
                    self.assertIn(step["state"],{"ready","action_required"})
                    self.assertTrue(step["title"])
                    self.assertTrue(step["detail"])
                    self.assertTrue(step["action_kind"])
                if item["mode"] in {"synthetic","theoretical"}:
                    self.assertTrue(item["run_ready_now"])
                    self.assertFalse(item["source_ready"])
                    self.assertEqual(item["next_action_kind"],"run_math")
                else:
                    self.assertFalse(item["run_ready_now"])
                    self.assertFalse(item["source_ready"])
                    self.assertFalse(all(s["state"]=="ready" for s in item["setup_steps"]))

    def test_historical_setup_requires_exact_stock_or_asset_list(self):
        matrix=model_readiness.overview()
        models={x["id"]:x for x in matrix["models"]}
        for name in ("gbm_fit","ou_fit","merton_fit","heston_proxy"):
            with self.subTest(name=name):
                step={s["action_kind"] for s in models[name]["setup_steps"]}
                self.assertIn("select_stock",step)
                self.assertIn("get_history",step)
                self.assertFalse(models[name]["source_ready"])
        for name in ("garch","min_variance","pca","risk_surface",
                     "historical_tail","rolling_vol"):
            with self.subTest(name=name):
                actions={s["action_kind"] for s in models[name]["setup_steps"]}
                self.assertIn("configure_assets",actions)
                self.assertIn("get_history",actions)
                self.assertFalse(models[name]["source_ready"])

    def test_quote_models_never_mark_quotes_available_without_real_contract(self):
        matrix=model_readiness.overview()
        for item in matrix["models"]:
            if item["mode"]!="market":
                continue
            self.assertEqual(item["next_action_kind"],"select_dataset")
            stages={s["action_kind"]:s["state"] for s in item["setup_steps"]}
            self.assertEqual(stages["option_quotes"],"action_required")
            self.assertEqual(stages["select_quote"],"action_required")

    def test_readiness_center_carries_same_model_setup_instructions(self):
        r=self.client.get("/api/data-manager/research/overview")
        self.assertEqual(r.status_code,200,r.text)
        matrix=r.json()
        self.assertEqual(matrix["implemented_models"],len(model_registry.MODELS))
        self.assertEqual(len(matrix["models"]),len(model_registry.MODELS))
        for item in matrix["models"]:
            self.assertTrue(item["setup_steps"])
            self.assertTrue(item["implementation_ready"])
            self.assertIn(item["action"]["kind"],{"run","open_model","option_quotes",
                                                  "select_dataset"})
            self.assertFalse(item["tested_for_real_market_performance"])


if __name__=="__main__":
    unittest.main()
