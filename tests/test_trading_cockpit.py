"""Deterministic offline regression for read-only intraday model and audit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from workstation_api import service, trading_cockpit
from workstation_api.app import app


START = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)


def candles(count: int = 45, *, start=START, drift=2.0) -> list[dict]:
    rows = []
    for index in range(count):
        price = 62000 + index * drift
        rows.append({
            "timestamp_utc": (start + timedelta(minutes=index)).isoformat(),
            "session_ist": "2026-11-18",
            "open": price - .3, "high": price + 1,
            "low": price - 1, "close": price, "volume": 100 + index,
        })
    return rows


class TradingCockpitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="quantlab_intraday_")
        self.addCleanup(temp.cleanup)
        self.patch = patch.object(service, "DATA", Path(temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_deterministic_up_and_down_baselines(self):
        up = trading_cockpit.snapshot("NSE_EQ:1001", candles(),
                                     now=START + timedelta(minutes=46))
        self.assertEqual(up["direction"], "NO_TRADE")  # RSI 100 is overextended
        self.assertEqual(up["validation"], "UNVALIDATED_RULE_BASELINE")
        self.assertIsNone(up["confidence"])
        down = trading_cockpit.snapshot("NSE_EQ:1001", candles(drift=-2),
                                       now=START + timedelta(minutes=46))
        self.assertEqual(down["direction"], "NO_TRADE")  # RSI 0 overextended
        self.assertTrue(all("ema9" in row for row in down["rows"]))

    def test_gap_invalidity_and_stale_label(self):
        original = candles()
        stale = trading_cockpit.snapshot("NSE_EQ:1001", original,
                                         now=START + timedelta(days=1))
        self.assertEqual(stale["quote_mode"], "HISTORICAL_ONLY")
        original[1]["timestamp_utc"] = original[0]["timestamp_utc"]
        with self.assertRaisesRegex(ValueError, "unique"):
            trading_cockpit.snapshot("NSE_EQ:1001", original)

    def test_immutable_record_and_source_anchored_evaluation(self):
        observed = candles()
        analysis = trading_cockpit.snapshot("NSE_EQ:1001", observed,
                                           now=START + timedelta(minutes=45))
        first = trading_cockpit.record(analysis)
        second = trading_cockpit.record(analysis)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["evaluation"], "PENDING")
        extended = observed + candles(7, start=START+timedelta(minutes=45),
                                      drift=2.0)
        outcome = trading_cockpit.evaluate("NSE_EQ:1001", extended)
        self.assertEqual(outcome["updated"], 1)
        self.assertEqual(outcome["predictions"][0]["evaluation"], "NO_TRADE_REVIEWED")
        self.assertEqual(trading_cockpit.evaluate("NSE_EQ:1001", extended)["updated"], 0)

    def test_api_rejects_stale_prediction(self):
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        with patch("workstation_api.intraday_parquet.series",
                   return_value={"rows": candles(), "warning": "source", "has_more": False}):
            response = client.post("/api/trading-cockpit/predictions",
                                   json={"identity": "NSE_EQ:1001", "horizon_minutes": 6})
        self.assertEqual(response.status_code, 400)
        self.assertIn("stale", response.json()["detail"])

    def test_api_snapshot_no_future_data(self):
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        with patch("workstation_api.intraday_parquet.series",
                   return_value={"rows": candles(), "warning": "source", "has_more": False}):
            response = client.get("/api/trading-cockpit/snapshot",
                                  params={"identity": "NSE_EQ:1001"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["rows"]), 45)
        self.assertEqual(data["model_version"], trading_cockpit.VERSION)
        self.assertEqual(data["quote_mode"], "HISTORICAL_ONLY")


if __name__ == "__main__":
    unittest.main()
