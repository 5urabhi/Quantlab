"""Offline acceptance tests for the read-only all-dataset model audit.

These tests use synthetic and in-memory fixtures. They never claim original
Dhan/NSE data quality or contact a broker.
"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import audit_all_models
from workstation_api import (
    model_data_manager, model_input_selector, model_lab, model_registry, option_market, option_quotes, research_acceptance, service,
)


class ModelAuditAllDatasetsTests(unittest.TestCase):
    def test_matrix_has_every_registered_model_and_blocks_synthetic_as_real(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "synthetic"
            folder.mkdir()
            dataset = {
                "id": "synthetic", "label": "SYNTHETIC TEST DATA ONLY",
                "kind": "synthetic", "has_prices": False,
                "has_daily_prices": False, "return_basis": "simulation",
            }
            output = Path(temp) / "audit"
            with patch.object(service, "datasets", return_value=[dataset]), \
                 patch.object(service, "dataset_path", return_value=(folder, dataset)), \
                 patch.object(model_lab, "run_model") as run:
                result = audit_all_models.audit(
                    datasets=["synthetic"], execute=False, output=output
                )
            run.assert_not_called()
            self.assertEqual(result["registered_models"], len(model_registry.MODELS))
            self.assertEqual(result["math_pass"], 0)
            self.assertEqual(result["software_fail"], 0)
            self.assertEqual(result["blocked_input"], 26)
            with (output / "ALL_MODEL_RESULTS.csv").open(newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), len(model_registry.MODELS))
            self.assertEqual({r["model_id"] for r in rows},
                             {m["id"] for m in model_registry.MODELS})
            self.assertEqual(
                sum(r["status"] == "blocked_input" for r in rows), 26
            )
            self.assertTrue((output / "MODEL_AUDIT.md").is_file())

    def test_default_skips_builtin_synthetic_when_real_dataset_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            synthetic = {"id": "synthetic", "kind": "synthetic"}
            genuine = {
                "id": "upload_original", "kind": "uploaded",
                "has_prices": False, "has_daily_prices": False,
                "label": "Test original source (no price panel)",
            }
            folder = Path(temp)
            with patch.object(service, "datasets",
                              return_value=[synthetic, genuine]), \
                 patch.object(service, "dataset_path",
                              return_value=(folder, genuine)):
                result = audit_all_models.audit(
                    datasets=None, execute=False, output=folder / "audit"
                )
        self.assertEqual([x["dataset_id"] for x in result["datasets"]],
                         ["upload_original"])
        self.assertEqual(result["blocked_input"], 26)

    def test_math_models_only_claim_assumptions(self):
        theory = model_registry.CATALOG["black_scholes"]
        with patch.object(model_lab, "run_model", return_value={
            "model_id": "black_scholes", "mode": "theoretical",
            "source": None, "metrics": [{"label": "price", "value": 1}],
            "plots": [], "table": []
        }) as run:
            row = audit_all_models.run_math(theory, execute=True)
        self.assertEqual(row["status"], "math_pass")
        self.assertEqual(row["dataset_id"], "(no dataset)")
        run.assert_called_once()
        with self.assertRaisesRegex(ValueError, "exact selected source"):
            audit_all_models.verify_output({
                "model_id": "garch", "mode": "historical",
                "source": {"dataset_id": "wrong"},
                "metrics": [{"value": 1}], "plots": [], "table": []
            }, model_registry.CATALOG["garch"], "dhan_shared")

    def test_adapts_portfolio_asset_count_and_weight_cap_explicitly(self):
        spec = model_registry.CATALOG["min_variance"]
        with patch.object(model_lab, "readiness", return_value={
            "available_symbols": ["A", "B"]
        }), patch.object(model_lab, "_historical_input", return_value=(
            pd.DataFrame({"A": [0.01] * 70, "B": [0.015] * 70}), {}
        )) as fetch:
            params, observations, count, ticker = audit_all_models.historical_input(
                spec, "local_dataset", {"has_prices": True}
            )
        self.assertEqual(count, 2)
        self.assertEqual(observations, 70)
        self.assertEqual(ticker, "")
        self.assertEqual(params["assets"], 2)
        self.assertEqual(params["max_weight"], .5)
        fetch.assert_called_once_with("local_dataset", 60, 2)

    def test_original_daily_only_stock_panel_is_eligible_for_market_models(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            dates = pd.bdate_range("2026-01-01", periods=100)
            alpha, beta = [100.0], [90.0]
            for n in range(1, 100):
                alpha.append(alpha[-1] * (1.0004 + ((n % 7) - 3) * .001))
                beta.append(beta[-1] * (1.0008 + ((n % 11) - 5) * .0007))
            prices = pd.DataFrame({
                "ALPHA": alpha, "BETA": beta,
            }, index=dates)
            prices.to_csv(folder / "daily_prices.csv", index_label="date")
            dataset = {
                "id": "upload_daily_only", "kind": "uploaded",
                "label": "Actual source daily-only test fixture",
                "has_prices": False, "has_daily_prices": True,
                "benchmark_kind": "missing",
            }
            with patch.object(service, "dataset_path", return_value=(folder, dataset)):
                source_readiness = model_lab.readiness("upload_daily_only")
                aligned, source = model_lab._historical_input(
                    "upload_daily_only", 60, 2
                )
                single = model_input_selector.inspect(
                    "upload_daily_only", "gbm_fit"
                )
                prepared = model_data_manager._observed(
                    "upload_daily_only", 2, 60
                )
        self.assertTrue(source_readiness["has_prices"])
        self.assertEqual(source_readiness["frequency"], "daily")
        self.assertEqual(len(aligned), 99)
        self.assertEqual(source["source_file"], "daily_prices.csv")
        self.assertEqual(prepared["common_returns"], 99)
        self.assertEqual(single["eligible_count"], 2)

    def test_valid_original_tri_can_run_without_separate_stock_prices(self):
        with patch.object(model_input_selector, "inspect", return_value={
            "candidates": [],
            "tri": {"runnable": True, "returns": 135},
        }) as inspect:
            params, actual, assets, ticker = audit_all_models.historical_input(
                model_registry.CATALOG["gbm_fit"], "tri_only",
                {"has_prices": False}
            )
        self.assertEqual(params["target"], "benchmark_tri")
        self.assertEqual(actual, 135)
        self.assertEqual(assets, 1)
        self.assertEqual(ticker, "source-linked NIFTY TRI")
        inspect.assert_called_once_with("tri_only", "gbm_fit")

    def test_quote_candidate_ref_requires_exact_saved_contract(self):
        snapshots = [{
            "id": "oq_0123456789abcdef0123",
            "contracts": [{"row_index": 1}]
        }]
        with patch.object(option_quotes, "list_for", return_value=snapshots), \
             patch.object(option_market, "inspect",
                          return_value={"runnable": True}) as inspect:
            found = audit_all_models.actual_quote_refs("dhan_shared")
        self.assertEqual(found, ["oq_0123456789abcdef0123:1"])
        inspect.assert_called_once_with(
            "dhan_shared", "oq_0123456789abcdef0123:1"
        )

    def test_unauthorized_or_missing_quote_never_runs_as_original(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            record = {"id": "dhan_shared", "kind": "dhan", "has_prices": False}
            with patch.object(audit_all_models, "actual_quote_refs",
                              return_value=[]), \
                 patch.object(model_lab, "run_model") as runner:
                row = audit_all_models.run_observed(
                    model_registry.CATALOG["implied_vol_quote"],
                    "dhan_shared", record, folder, {}, execute=True,
                )
            runner.assert_not_called()
            self.assertEqual(row["status"], "blocked_input")
            self.assertIn("option", row["next_action"].lower())

    def test_existing_source_digest_is_never_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "daily_prices.csv").write_text("date,A\n2025-01-01,100\n")
            first = audit_all_models.dataset_digests(path)
            self.assertIn("daily_prices.csv", first)
            (path / "daily_prices.csv").write_text("date,A\n2025-01-01,101\n")
            second = audit_all_models.dataset_digests(path)
            self.assertNotEqual(first, second)
            (path / "prices.csv").symlink_to(path / "daily_prices.csv")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                audit_all_models.dataset_digests(path)



class ExistingResearchVerifierTests(unittest.TestCase):
    def test_original_quote_is_selected_and_bound_to_effective_dataset(self):
        matrix = {
            "dataset_id": "dhan_shared", "total_models": 35,
            "blocked": 0, "models": [{
                "id": "implied_vol_quote",
                "mode": "market", "status": "source_available"
            }]
        }
        quote = [{
            "id": "oq_0123456789abcdef0123",
            "contracts": [{"row_index": 0}]
        }]
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(research_acceptance, "overview", return_value=matrix), \
             patch.object(research_acceptance, "_audit_root",
                          return_value=Path(temp)), \
             patch.object(option_quotes, "list_for", return_value=quote), \
             patch.object(option_market, "inspect",
                          return_value={"runnable": True}), \
             patch.object(model_lab, "run_model",
                          return_value={"model_id": "implied_vol_quote"}) as run:
            report = research_acceptance.verify(None, include_historical=True)
        run.assert_called_once_with(
            "implied_vol_quote", "dhan_shared",
            {"quote": "oq_0123456789abcdef0123:0"},
        )
        self.assertEqual(report["software_pass"], 1)
        self.assertEqual(report["checks"][0]["qa_only_option_quote_selection"],
                         "oq_0123456789abcdef0123:0")
        self.assertTrue(report["checks"][0]["uses_original_market_data"])


if __name__ == "__main__":
    unittest.main()
