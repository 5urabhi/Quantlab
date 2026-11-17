"""Regression tests for *retrospective*, source-bound model selection inference."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import selection_diagnostics, service
from workstation_api.app import app


def sample(n=72):
    rng = np.random.default_rng(1917)
    benchmark = rng.normal(.004, .031, n)
    strategies = np.column_stack([
        benchmark + rng.normal(.003, .027, n),
        benchmark + rng.normal(.002, .023, n),
        benchmark + rng.normal(.001, .020, n)])
    return strategies, benchmark


class SelectionMathTest(unittest.TestCase):
    def test_symmetry_combinations_and_determinism(self):
        x, _ = sample()
        a = selection_diagnostics.cscv(x, folds=4)
        b = selection_diagnostics.cscv(x, folds=4)
        self.assertEqual(a, b)
        self.assertEqual(a["combinations"], math.comb(4, 2))
        self.assertGreaterEqual(a["pbo_fraction"], 0)
        self.assertLessEqual(a["pbo_fraction"], 1)
        self.assertEqual(sum(a["winner_counts"]), 6)
        self.assertTrue(all(row["logit_oos_rank"] is not None for row in a["rows"]))
        self.assertIn("NOT an untouched", a["limitation"])

    def test_more_unlogged_trials_cannot_improve_deflated_statistic(self):
        x, _ = sample()
        a = selection_diagnostics.deflated_sharpe(x, trials=3)
        b = selection_diagnostics.deflated_sharpe(x, trials=100)
        self.assertLessEqual(b["deflated_sharpe_probability"],
                             a["deflated_sharpe_probability"])
        self.assertLess(a["threshold_annualized_zero_rate_sharpe"],
                        b["threshold_annualized_zero_rate_sharpe"])
        self.assertEqual(a["declared_number_of_trials"], 3)
        self.assertIn("retrospective", a["limitation"])

    def test_cscv_observation_and_fold_guards(self):
        x, _ = sample(48)
        self.assertEqual(selection_diagnostics.cscv(x, folds=4)["combinations"], 6)
        with self.assertRaisesRegex(ValueError, "72 common"):
            selection_diagnostics.cscv(x, folds=6)
        with self.assertRaisesRegex(ValueError, "4, 6 or 8"):
            selection_diagnostics.cscv(x, folds=5)

    def test_regime_uses_prior_months_only_for_each_observation(self):
        x, b = sample()
        output = selection_diagnostics.regimes(x, b, trail=6)
        self.assertEqual(len(output["regime_by_month"]), 66)
        self.assertEqual(output["regime_by_month"][0]["index"], 6)
        self.assertAlmostEqual(output["regime_by_month"][0]
                               ["trailing_benchmark_vol_annualized"],
                               float(np.std(b[:6], ddof=1) * math.sqrt(12)))
        self.assertEqual(sum(row["observations"] for row in output["summary"]
                             if row["candidate_index"] == 0), 66)
        self.assertIn("retrospective", output["limitation"].lower())

    def test_invalid_trial_count_and_constant_sharpe(self):
        x, _ = sample()
        with self.assertRaisesRegex(ValueError, "Declared tested configurations"):
            selection_diagnostics.deflated_sharpe(x, trials=2)
        with self.assertRaisesRegex(ValueError, "finite observed skew"):
            selection_diagnostics.deflated_sharpe(np.full((72,3),.01),trials=3)


    def test_chronological_walk_forward_selection_uses_only_past_data(self):
        strategies, benchmark = sample(72)
        dates = [d.date().isoformat() for d in
                 pd.date_range("2020-01-31", periods=72, freq="ME")]
        first = selection_diagnostics.chronological_selection(
            strategies, benchmark, dates, ["A","B","C"],
            train_months=36, test_months=6, embargo_months=1)
        self.assertGreaterEqual(first["fold_count"],2)
        self.assertEqual(first["folds"][0]["train_last"],dates[35])
        self.assertEqual(first["folds"][0]["embargo_first"],dates[36])
        self.assertEqual(first["folds"][0]["test_first"],dates[37])
        self.assertEqual(first["test_months_evaluated"],len(first["selected_forward_months"]))
        self.assertFalse(first["certifies_real_market_performance"])
        # Changing every future observation cannot affect the first winner,
        # proving the selection rule only inspects the past training prefix.
        altered = strategies.copy()
        altered[36:, :] = np.array([.20, -.03, -.05])
        second = selection_diagnostics.chronological_selection(
            altered, benchmark, dates, ["A","B","C"],
            train_months=36, test_months=6, embargo_months=1)
        self.assertEqual(first["folds"][0]["selected_run_id"],
                         second["folds"][0]["selected_run_id"])

    def test_chronological_blocks_refuse_calendar_gaps_and_flat_training(self):
        returns, bench = sample(72)
        dates = [d.date().isoformat() for d in
                 pd.date_range("2020-01-31", periods=72, freq="ME")]
        missing = dates.copy()
        missing[42] = "2033-01-31"
        with self.assertRaisesRegex(ValueError,"consecutive original months"):
            selection_diagnostics.chronological_selection(
                returns,bench,missing,["A","B","C"])
        with self.assertRaisesRegex(ValueError,"two untouched-at-step"):
            selection_diagnostics.chronological_selection(
                returns[:44],bench[:44],dates[:44],["A","B","C"])
        with self.assertRaisesRegex(ValueError,"undefined in-training"):
            selection_diagnostics.chronological_selection(
                np.full((72,3),.003),bench,dates,["A","B","C"])

    def test_chronological_summary_is_bounded_and_consistent(self):
        returns, bench = sample(96)
        dates = [d.date().isoformat() for d in
                 pd.date_range("2018-01-31", periods=96, freq="ME")]
        result = selection_diagnostics.chronological_selection(
            returns,bench,dates,["A","B","C"],
            train_months=48,test_months=12,embargo_months=2)
        self.assertTrue(np.isfinite(result["aggregate"]
                                   ["compounded_selected_net_return_fraction"]))
        self.assertLessEqual(result["test_months_evaluated"],96-48-2)
        self.assertEqual(sum(x["selected_folds"] for x in
            result["candidate_selection_counts"]),result["fold_count"])
        self.assertTrue(all(x["test_first"]>x["train_last"] for x in result["folds"]))


class SourceBoundSelectionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quantlab_selection_")
        self.folder = Path(self.temp.name)
        self.patcher = patch.object(service,"RESULTS",self.folder)
        self.patcher.start()
        self.client = TestClient(app,base_url="http://127.0.0.1:8765")
        x, b = sample()
        dates = pd.date_range("2019-01-31",periods=len(b),freq="ME")
        for j in range(x.shape[1]):
            run_id = f"candidate_{j}"
            folder = self.folder / run_id
            folder.mkdir()
            (folder/"research_manifest.json").write_text(json.dumps({
                "generated_utc":"2026-11-01T00:00:00Z",
                "config":{"name":run_id,"validation_start":"2021-01-01",
                          "final_test_start":"2023-01-01"},
                "metrics_by_split":{"development":{"observations":40}},
                "input_sha256":{"prices.csv":"unchanged_original_sha"},
            }),encoding="utf-8")
            (folder/"workstation_run.json").write_text(json.dumps({
                "dataset_id":"synthetic","dataset_kind":"synthetic",
            }),encoding="utf-8")
            pd.DataFrame({"date":[d.date().isoformat() for d in dates],
                          "strategy_net":x[:,j],"benchmark":b,
                          "turnover":np.full(len(b),.05)}).to_csv(
                folder/"monthly_results.csv",index=False)

    def tearDown(self):
        self.client.close()
        self.patcher.stop()
        self.temp.cleanup()

    def test_endpoint_emits_observed_facts_but_never_audits_synthetic(self):
        response = self.client.post("/api/workspace/results/selection-audit",json={
            "run_ids":["candidate_0","candidate_1","candidate_2"],
            "folds":6,"declared_trials":24,"benchmark_trail":6})
        self.assertEqual(response.status_code,200,response.text)
        data = response.json()
        self.assertEqual(data["common_months"],72)
        self.assertEqual(data["source_hashes"]["prices.csv"],
                         "unchanged_original_sha")
        self.assertEqual(data["evidence_class"],"synthetic_demo")
        self.assertEqual(data["pbo"]["combinations"],20)
        self.assertEqual(data["deflated_sharpe"]["declared_number_of_trials"],24)
        self.assertEqual(len(data["regimes"]["summary"]),9)
        self.assertIn("NOT an untouched",data["pbo"]["limitation"])
        self.assertTrue(data["never_certified"])
        self.assertNotIn("DHAN_ACCESS_TOKEN",response.text)

    def test_chronological_selection_endpoint_preserves_source_gate(self):
        response=self.client.post("/api/workspace/results/chronological-selection",json={
            "run_ids":["candidate_0","candidate_1","candidate_2"],
            "train_months":36,"test_months":6,"embargo_months":1})
        self.assertEqual(response.status_code,200,response.text)
        body=response.json()
        self.assertEqual(body["dataset_id"],"synthetic")
        self.assertEqual(body["evidence_class"],"synthetic_demo")
        self.assertEqual(body["training_months_initial"],36)
        self.assertFalse(body["certifies_real_market_performance"])
        self.assertIn("re-fit each archived strategy",body["warning"])
        self.assertGreaterEqual(body["fold_count"],2)
        # Refuse an unsupported embargo without silently dropping it.
        bad=self.client.post("/api/workspace/results/chronological-selection",json={
            "run_ids":["candidate_0","candidate_1"],"embargo_months":0})
        self.assertEqual(bad.status_code,422)

    def test_requires_consistent_saved_original_sources(self):
        folder = self.folder / "candidate_2"
        config = json.loads((folder/"research_manifest.json").read_text())
        config["input_sha256"]["prices.csv"] = "tampered_original"
        (folder/"research_manifest.json").write_text(json.dumps(config))
        response = self.client.post("/api/workspace/results/selection-audit",json={
            "run_ids":["candidate_0","candidate_1","candidate_2"]})
        self.assertEqual(response.status_code,400,response.text)
        self.assertIn("checksums",response.text)

    def test_strict_input_and_short_common_sample(self):
        url = "/api/workspace/results/selection-audit"
        bad = self.client.post(url,json={
            "run_ids":["candidate_0","candidate_1"],"folds":7})
        self.assertEqual(bad.status_code,422)
        bad = self.client.post(url,json={
            "run_ids":["candidate_0","candidate_1"],"declared_trials":1})
        self.assertEqual(bad.status_code,422)
        bad = self.client.post(url,json={
            "run_ids":["candidate_0","candidate_1"],
            "extra_source_token":"never"})
        self.assertEqual(bad.status_code,422)
        bad = self.client.post(url,json={"run_ids":["candidate_0","candidate_0"]})
        self.assertEqual(bad.status_code,400)
