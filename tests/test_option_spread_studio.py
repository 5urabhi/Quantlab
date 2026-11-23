"""Offline regression for automatic bid/ask and defined-risk multi-leg research.

Fixtures are synthetic *valid protocol shapes*, not market evidence or executions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from fastapi.testclient import TestClient

from workstation_api import live_market, option_spread_studio as studio, service
from workstation_api.app import app


def book(stamp, identity, side, strike, bid, *, size=30, ask_gap=.10,
         quantity=150, expiry="2026-11-23"):
    ask = bid + ask_gap
    return {
        "identity": identity, "received_utc": stamp.isoformat(),
        "timestamp_kind": "local_receive",
        "bid": [{"price": round(bid-i*.05, 2),
                 "quantity": quantity, "orders": 3} for i in range(20)],
        "ask": [{"price": round(ask+i*.05, 2),
                 "quantity": quantity, "orders": 3} for i in range(20)],
        "bid_packet_sha256": "a"*64, "ask_packet_sha256": "b"*64,
        "source": "original_Dhan_full_market_depth_websocket",
        "collection_mode": "auto_banknifty_20_level",
        "computed_features": {
            "lot_size_verified": size, "expiry": expiry,
            "strike": float(strike), "side": side,
        },
    }


class OptionSpreadStudioTest(TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix="quantlab_multileg_source_test_")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        p = patch.object(service, "DATA", root/"data")
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(live_market, "DB_INITIALIZED", False)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        live_market._init_db()
        self.stamp = datetime(2026, 11, 23, 4, 5, tzinfo=timezone.utc)
        self.rows = [
            book(self.stamp, "NSE_FNO:1001", "CE", 100, 29),
            book(self.stamp, "NSE_FNO:1002", "CE", 110, 23),
            book(self.stamp, "NSE_FNO:1003", "CE", 120, 16),
            book(self.stamp, "NSE_FNO:1004", "CE", 130, 10),
            book(self.stamp, "NSE_FNO:2001", "PE", 90, 2),
            book(self.stamp, "NSE_FNO:2002", "PE", 100, 5),
            book(self.stamp, "NSE_FNO:2003", "PE", 110, 10),
            book(self.stamp, "NSE_FNO:2004", "PE", 120, 18),
        ]
        self._insert(self.rows)

    def _insert(self, rows):
        digest = sha256(("a"*64+"b"*64).encode()).hexdigest()
        with live_market._database() as db:
            db.executemany(
                "INSERT INTO live_depth_books "
                "(identity,received_utc,session_id,book_json,packet_pair_sha256) "
                "VALUES(?,?,?,?,?)",
                [(r["identity"], r["received_utc"], "multileg_synthetic",
                  json.dumps(r), digest) for r in rows],
            )

    def _chosen(self, strategy, ids, lots=1):
        return studio.build(day="2026-11-23", strategy=strategy,
                            identities=ids, lots=lots,
                            broker_profile="zerodha",
                            max_quote_skew_seconds=10)

    def test_source_scan_finds_six_hedged_strategies_automatically(self):
        value = studio.scan(day="2026-11-23", capital_inr=50000, max_lots=3,
                            max_quote_skew_seconds=10, limit=100)
        self.assertEqual(value["valid_unique_contracts"], 8)
        self.assertEqual(value["original_depth_id_count"], 8)
        self.assertEqual(len(value["strategies"]), 6)
        self.assertGreater(value["discovered_candidates"], 0)
        self.assertTrue(value["read_only"])
        self.assertFalse(value["broker_margin_verified"])
        self.assertIsNone(value["realized_pnl_inr"])
        self.assertEqual(value["executed_orders"], 0)
        names = {item["strategy"] for item in value["ranked_candidates"]}
        self.assertIn("bull_call_debit", names)
        self.assertIn("bear_put_debit", names)
        self.assertIn("iron_condor", names)
        self.assertIn("iron_butterfly", names)
        for item in value["ranked_candidates"]:
            self.assertTrue(item["risk_budget_proxy_pass"])
            self.assertLessEqual(item["risk_capital_proxy_inr"], 50000)
            self.assertGreater(item["max_profit_inr"], 0)
            self.assertGreater(item["max_loss_inr"], 0)
            self.assertFalse(item["broker_margin_verified"])
            self.assertIsNone(item["required_initial_broker_margin_inr"])
            self.assertLessEqual(item["quote_skew_seconds"], 10)

    def test_bull_call_terminal_payoff_and_broker_entry_costs(self):
        result = self._chosen("bull_call_debit", ["NSE_FNO:1001", "NSE_FNO:1002"])
        self.assertEqual(result["lots"], 1)
        self.assertEqual(result["units"], 30)
        self.assertEqual([leg["action"] for leg in result["legs"]],
                         ["BUY", "SELL"])
        self.assertEqual(result["entry_fee_breakdown"]["brokerage"], 40.)
        self.assertLess(result["entry_premium_cashflow_inr"], 0)
        self.assertLess(result["estimated_same_book_immediate_roundtrip_net_inr"], 0)
        self.assertIsNone(result["realized_pnl_inr"])
        self.assertFalse(result["broker_margin_verified"])
        path = result["payoff_points"]
        self.assertAlmostEqual(
            path[-1]["net_payoff_inr"]-path[0]["net_payoff_inr"],
            10*30, places=2)
        self.assertAlmostEqual(
            result["max_profit_inr"]+result["max_loss_inr"], 10*30, places=2)
        self.assertEqual(len(path), 61)

    def test_credit_and_four_leg_condor_have_bounded_losses(self):
        credit = self._chosen("bull_put_credit",
                              ["NSE_FNO:2001", "NSE_FNO:2002"])
        self.assertEqual(credit["entry_fee_breakdown"]["brokerage"], 40.)
        condor = self._chosen("iron_condor", [
            "NSE_FNO:2001", "NSE_FNO:2002",
            "NSE_FNO:1002", "NSE_FNO:1003"])
        self.assertEqual(condor["entry_fee_breakdown"]["brokerage"], 80.)
        self.assertEqual(len(condor["legs"]), 4)
        self.assertGreater(condor["max_loss_inr"], 0)
        self.assertTrue(all(leg["original_depth_verified"]
                            for leg in condor["legs"]))
        self.assertEqual(condor["max_loss_inr"],
                         max(-p["net_payoff_inr"] for p in condor["payoff_points"]))
        butterfly = self._chosen("iron_butterfly", [
            "NSE_FNO:2001", "NSE_FNO:2002",
            "NSE_FNO:1001", "NSE_FNO:1002"])
        self.assertEqual(butterfly["entry_fee_breakdown"]["brokerage"], 80.)
        self.assertEqual(butterfly["legs"][1]["strike"],
                         butterfly["legs"][2]["strike"])

    def test_invalid_leg_shapes_not_silently_reinterpreted(self):
        for strategy, ids in (
                ("bull_call_debit", ["NSE_FNO:1002", "NSE_FNO:1001"]),
                ("bear_put_debit", ["NSE_FNO:2001", "NSE_FNO:2002"]),
                ("bear_call_credit", ["NSE_FNO:1001", "NSE_FNO:1002"]),
                ("iron_condor", ["NSE_FNO:2002", "NSE_FNO:2001",
                                 "NSE_FNO:1002", "NSE_FNO:1003"]),
                ("bull_put_credit", ["NSE_FNO:2001", "NSE_FNO:1001"]),
                ("bull_call_debit", ["NSE_FNO:1001", "NSE_FNO:1001"]),
        ):
            with self.subTest(strategy=strategy, ids=ids):
                with self.assertRaises(ValueError):
                    self._chosen(strategy, ids)

    def test_unsynchronized_quotes_rejected(self):
        delayed = book(self.stamp+timedelta(minutes=3), "NSE_FNO:1005",
                       "CE", 140, 6)
        self._insert([delayed])
        with self.assertRaisesRegex(ValueError, "synchronized"):
            self._chosen("bull_call_debit",
                         ["NSE_FNO:1001", "NSE_FNO:1005"])
        value = studio.scan(day="2026-11-23", capital_inr=50000,
                            max_quote_skew_seconds=1)
        self.assertGreater(value["discovered_candidates"], 0)
        self.assertTrue(value["read_only"])

    def test_missing_original_and_incomplete_legs_blocked(self):
        with self.assertRaises(ValueError):
            self._chosen("bull_call_debit",
                         ["NSE_FNO:1001", "NSE_FNO:999999"])
        invalid = self.client.post(
            "/api/trading-cockpit/spreads/multileg/evaluate",
            json={"day": "2026-11-23", "strategy": "iron_condor",
                  "identities": ["NSE_FNO:1001"], "lots": 1})
        self.assertEqual(invalid.status_code, 422)
        wrong = self.client.post(
            "/api/trading-cockpit/spreads/multileg/evaluate",
            json={"day": "2026-11-23", "strategy": "bull_call_debit",
                  "identities": ["../../etc/passwd", "NSE_FNO:1001"],
                  "lots": 1, "live_execution": True})
        self.assertEqual(wrong.status_code, 422)
        self.assertRaises(ValueError, studio.scan, day="2026-11-23",
                          capital_inr=999)
        self.assertRaises(ValueError, studio.scan, day="2026-11-23",
                          max_quote_skew_seconds=121)

    def test_scan_and_evaluate_routes_are_read_only(self):
        response = self.client.get(
            "/api/trading-cockpit/spreads/multileg/scan",
            params={"day": "2026-11-23", "max_lots": 2,
                    "capital_inr": 50000})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["read_only"])
        self.assertEqual(data["executed_orders"], 0)
        self.assertGreater(len(data["ranked_candidates"]), 0)
        response = self.client.post(
            "/api/trading-cockpit/spreads/multileg/evaluate",
            json={"day": "2026-11-23", "strategy": "bull_call_debit",
                  "identities": ["NSE_FNO:1001", "NSE_FNO:1002"],
                  "lots": 2, "broker_profile": "zerodha"})
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()
        self.assertEqual(item["lots"], 2)
        self.assertTrue(item["read_only"])
        self.assertEqual(item["executed_orders"], 0)
        self.assertIsNone(item["realized_pnl_inr"])
