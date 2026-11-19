"""Deterministic offline regression for read-only intraday model and audit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from hashlib import sha256
import json
import csv
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from workstation_api import service, trading_cockpit, cockpit_sources, manual_trade_journal
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

    def test_late_completed_bar_cannot_be_claimed_as_fresh_prediction(self):
        original = candles()
        age_75 = trading_cockpit.snapshot("NSE_EQ:1001", original,
                   now=START + timedelta(minutes=45, seconds=15))
        self.assertEqual(age_75["quote_mode"], "RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE")
        age_120 = trading_cockpit.snapshot("NSE_EQ:1001", original,
                    now=START + timedelta(minutes=46))
        self.assertEqual(age_120["quote_mode"], "HISTORICAL_ONLY")

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


    def test_horizon_requires_exact_original_minute(self):
        observed = candles()
        event = trading_cockpit.record(trading_cockpit.snapshot(
            "NSE_EQ:1001", observed, now=START + timedelta(minutes=45)), 3)
        self.assertEqual(event["evaluation"], "PENDING")
        # Prediction bar 44m + 3m => 47m. No observation at 47m;
        # 48m exists, but must not stand in for the missing horizon bar.
        next_rows = [row for row in candles(50)
                     if row["timestamp_utc"] !=
                     (START + timedelta(minutes=47)).isoformat()]
        scored = trading_cockpit.evaluate("NSE_EQ:1001", next_rows)
        self.assertEqual(scored["predictions"][0]["evaluation"], "UNVERIFIABLE_GAP")

    def test_session_boundary_suppresses_signal_and_replay_reports_no_trade(self):
        rows = candles(50)
        second = candles(10, start=START+timedelta(days=1), drift=1)
        for row in second:
            row["session_ist"] = "2026-11-19"
        snapshot = trading_cockpit.snapshot(
            "NSE_EQ:1001", rows+second,
            now=START+timedelta(days=1,minutes=10))
        self.assertEqual(snapshot["contiguous_session_bars"], 10)
        self.assertEqual(snapshot["direction"], "NO_TRADE")
        self.assertEqual(snapshot["signal_suppression"], "insufficient_consecutive_bars")
        replay = trading_cockpit.historical_replay("NSE_EQ:1001", rows, 6)
        self.assertEqual(replay["mode"], "RETROSPECTIVE_HISTORICAL_RULE_REPLAY")
        self.assertEqual(replay["overall"]["scored"], 0)
        self.assertGreater(replay["overall"]["no_trade"], 0)

    def test_day_report_counts_prospective_no_trades_separately(self):
        observed = trading_cockpit.snapshot(
            "NSE_EQ:1001", candles(), now=START + timedelta(minutes=45))
        trading_cockpit.record(observed, 3)
        trading_cockpit.record(observed, 6)
        report = trading_cockpit.day_report("NSE_EQ:1001", "2026-11-18")
        self.assertEqual(report["overall"]["total"], 2)
        self.assertEqual(report["overall"]["pending"], 2)
        self.assertIsNone(report["overall"]["directional_accuracy"])
        self.assertEqual(report["days"][0]["session_ist"], "2026-11-18")
        with self.assertRaisesRegex(ValueError, "valid YYYY-MM-DD"):
            trading_cockpit.day_report("NSE_EQ:1001", "wrong")

    def test_original_index_spot_sha_and_manifest_are_required(self):
        batch = service.DATA / "dhan" / "index_spot" / "batch_000000000000abcd"
        batch.mkdir(parents=True)
        source = batch / "BANKNIFTY_INDEX_intraday_1m.csv"
        rows = candles(40)
        with source.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "datetime", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for row in rows:
                writer.writerow({"datetime": row["timestamp_utc"], **{
                    k:row[k] for k in ("open","high","low","close","volume")}})
        meta = {
            "source":"DhanHQ REST API v2", "interval_minutes":1,
            "retrieved_utc":"2026-11-18T12:00:00+00:00",
            "row_count":40, "sha256":sha256(source.read_bytes()).hexdigest(),
            "instrument":{"label":"BANKNIFTY_INDEX","exchange_segment":"IDX_I",
                          "instrument":"INDEX","security_id":"25"},
        }
        manifest = batch / "BANKNIFTY_INDEX_intraday_1m.manifest.json"
        manifest.write_text(json.dumps(meta))
        self.assertTrue(next(x for x in cockpit_sources.catalog()["instruments"]
                             if x["identity"]=="INDEX:BANKNIFTY")["ready"])
        response = cockpit_sources.series("INDEX:BANKNIFTY", limit=30)
        self.assertEqual(response["rows"][-1]["close"], rows[-1]["close"])
        self.assertEqual(len(response["rows"]), 30)
        self.assertEqual(response["basis"], "original_Dhan_IDX_I_unadjusted_spot_index")
        source.write_text(source.read_text().replace("62000", "62001", 1))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            cockpit_sources.series("INDEX:BANKNIFTY")

    def test_manual_option_journal_is_explicitly_unverified_and_immutable(self):
        entry = manual_trade_journal.enter("BANKNIFTY23NOV61900PE", "PUT", 90, 460)
        self.assertEqual(entry["status"], "OPEN")
        self.assertIsNone(entry["net_pnl_inr"])
        closed = manual_trade_journal.exit_trade(entry["id"], 300, fees_inr=40)
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(closed["net_pnl_inr"], -14440)
        self.assertIn("UNVERIFIED", closed["data_quality"])
        with self.assertRaisesRegex(ValueError, "already closed"):
            manual_trade_journal.exit_trade(entry["id"], 500)
        daily = manual_trade_journal.list_trades()
        self.assertEqual(daily["summary"]["closed"], 1)
        self.assertEqual(daily["summary"]["closed_net_pnl_inr"], -14440)

    def test_trade_journal_endpoints_never_accept_order_requests(self):
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            payload={"symbol":"BANKNIFTY23NOV61900PE","direction":"PUT",
                     "quantity":90,"entry_price":460}
            result=client.post("/api/trading-cockpit/trades", json=payload)
            self.assertEqual(result.status_code, 200, result.text)
            trade_id=result.json()["id"]
            bad=client.post("/api/trading-cockpit/trades",
                            json={**payload,"submit_order":True})
            self.assertEqual(bad.status_code,422)
            outcome=client.post(f"/api/trading-cockpit/trades/{trade_id}/exit",
                                json={"exit_price":300,"fees_inr":50})
            self.assertEqual(outcome.status_code,200,outcome.text)
            self.assertEqual(outcome.json()["net_pnl_inr"], -14450)



if __name__ == "__main__":
    unittest.main()
