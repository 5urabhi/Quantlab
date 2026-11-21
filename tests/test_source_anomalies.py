"""Read-only anomaly detection on isolated synthetic price fixtures."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import service, source_anomalies
from workstation_api.app import app


class SourceAnomalyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="quantlab_anomaly_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = patch.object(service, "DATA", self.root)
        source.start()
        self.addCleanup(source.stop)
        self.folder = self.root / "workstation_imports" / "anom_fixture"
        self.folder.mkdir(parents=True)
        rng = np.random.default_rng(129)
        n = 340
        dates = pd.bdate_range("2024-01-01", periods=n)
        a = 100 * np.exp(np.cumsum(rng.normal(.0002, .008, n)))
        b = 85 * np.exp(np.cumsum(rng.normal(.0001, .006, n)))
        a[265:] *= 1.8  # Deliberate large change in synthetic observed fixture.
        b[145] = np.nan  # It must not be forward filled or crossed in returns.
        self.jump_date = dates[265].date().isoformat()
        frame = pd.DataFrame({"date": dates, "A": a, "B": b})
        self.file = self.folder / "daily_prices.csv"
        frame.to_csv(self.file, index=False)
        frame.set_index("date")[["A", "B"]].resample("ME").last().to_csv(
            self.folder / "prices.csv", index_label="date")
        self.id = "upload_anom_fixture"

    def test_scans_original_and_does_not_write_or_fetch(self):
        before = sha256(self.file.read_bytes()).hexdigest()
        report = source_anomalies.scan(self.id, symbol="A")
        self.assertEqual(report["source_sha256"], before)
        self.assertEqual(sha256(self.file.read_bytes()).hexdigest(), before)
        self.assertEqual(report["source_file"], "daily_prices.csv")
        self.assertFalse(report["method"]["original_bytes_modified"])
        self.assertFalse(report["method"]["provider_requests"])
        self.assertEqual(report["inspected_assets"][0]["symbol"], "A")
        self.assertTrue(any(event["date"] == self.jump_date and
                            event["type"] == "unusual_observed_return"
                            for event in report["events"]))
        self.assertEqual(report["frequency"], "daily")

    def test_training_chronology_and_determinism(self):
        a = source_anomalies.scan(self.id, symbol="A", max_events=100)
        b = source_anomalies.scan(self.id, symbol="A", max_events=100)
        self.assertEqual(a["events"], b["events"])
        row = a["inspected_assets"][0]
        self.assertEqual(row["ml_status"], "trained_and_scored")
        self.assertEqual(row["ml_train_observations"] +
                         row["ml_holdout_observations"],
                         row["eligible_adjacent_returns"])
        self.assertGreater(row["ml_holdout_observations"], 20)
        self.assertTrue(a["method"]["unsupervised_ml"].startswith("IsolationForest"))

    def test_missing_values_reported_and_no_cross_gap_return(self):
        report = source_anomalies.scan(self.id, symbol="B", max_events=100)
        self.assertTrue(any(x["type"] == "invalid_or_missing_price"
                            for x in report["events"]))
        self.assertEqual(report["inspected_assets"][0]["invalid_or_missing"], 1)
        # One NaN eliminates two adjacent return pairs; it is not imputed.
        self.assertEqual(report["inspected_assets"][0]["eligible_adjacent_returns"], 337)

    def test_rejects_unknown_symbol_bad_budgets_and_source_dates(self):
        for kwargs in ({"symbol": "../outside"}, {"symbol": "UNKNOWN"},
                       {"max_assets": 100}, {"max_events": 0},
                       {"lookback": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                source_anomalies.scan(self.id, **kwargs)
        original = pd.read_csv(self.file)
        original.loc[8, "date"] = original.loc[7, "date"]
        original.to_csv(self.file, index=False)
        with self.assertRaisesRegex(ValueError, "duplicated|Ambiguous"):
            source_anomalies.scan(self.id)

    def test_api_returns_cited_candidates_without_credentials(self):
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            url = "/api/workspace/quality/" + self.id + "/anomalies"
            response = client.get(url, params={"symbol": "A"})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertIn("source_sha256", data)
            self.assertTrue(data["events"])
            self.assertNotIn("DHAN_ACCESS_TOKEN", response.text)
            self.assertEqual(client.get(url, params={"max_events": 101}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
