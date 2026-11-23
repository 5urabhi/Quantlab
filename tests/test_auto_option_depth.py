"""Offline acceptance for opt-in BANKNIFTY 20-level automatic collection."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch
import json
import os
import sqlite3
import struct
import tempfile
import unittest

from fastapi.testclient import TestClient
from workstation_api import auto_option_depth as auto
from workstation_api import live_market
from workstation_api.app import app


def candidate(side="CE", sec="12345", ltp=301.0, *, strike=62000.0,
              volume=100, verified=True, lot=30):
    return {
        "identity": "NSE_FNO:" + sec if verified else None,
        "strike": strike, "expiry": "2026-11-23",
        "option_type": side, "ltp": ltp, "bid": ltp - .25,
        "ask": ltp + .25, "volume": volume, "lot_size": lot,
        "contract_master_verified": verified, "quote_valid": True,
    }


def fixture_chain(contracts=None):
    return {
        "expiry": "2026-11-23", "received_utc": "2026-11-19T04:00:00+00:00",
        "underlying_spot": 63000.0,
        "contracts": contracts if contracts is not None else [
            candidate("CE", "12345", 302.0),
            candidate("CE", "12346", 313.0, strike=62100),
            candidate("CE", "12347", 390.0, strike=62200),
            candidate("PE", "12348", 300.0),
            candidate("PE", "12349", 311.0, strike=61900),
        ],
    }


def quote_packet(sec, side):
    prices = [300 - i * .05 for i in range(20)] if side == "bid" else [
        301 + i * .05 for i in range(20)]
    levels = b"".join(struct.pack("<dII", p, 10, 3) for p in prices)
    return (struct.pack("<hBBiI", 332, 41 if side == "bid" else 51,
                        2, int(sec), 17) + levels)


class AutomaticDepthRecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="auto20_offline_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch_root = patch.object(auto, "_root", return_value=self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    def test_regular_nse_hours_gate_and_weekends(self):
        def at(hour, minute, weekday=19):
            return datetime(2026, 11, weekday, hour, minute, tzinfo=timezone.utc)
        # UTC 03:45 is 09:15 IST
        self.assertFalse(auto._market_open(at(3, 44)))
        self.assertTrue(auto._market_open(at(3, 45)))
        self.assertTrue(auto._market_open(at(9, 59)))
        # 10:00 UTC is 15:30 IST
        self.assertFalse(auto._market_open(at(10, 0)))
        self.assertFalse(auto._market_open(at(3, 45, 21)))

    def test_both_ce_pe_near_premium_and_verified_master_only(self):
        config = dict(auto.DEFAULTS)
        chain = fixture_chain()
        chain["contracts"] += [
            candidate("CE", "55555", 299, verified=False),
            candidate("PE", "55556", 299, volume=0),
            candidate("CE", "55557", 301, lot=0),
        ]
        selected = auto.select_contracts(chain, config)
        self.assertEqual(len(selected), 4)
        self.assertEqual([row["side"] for row in selected], [
            "CE", "CE", "PE", "PE"])
        self.assertEqual({row["security_id"] for row in selected},
                         {"12345", "12346", "12348", "12349"})
        self.assertEqual(selected[0]["lot_size"], 30)
        self.assertEqual(selected[2]["ltp"], 300)
        self.assertEqual(auto._subscription(selected)["InstrumentCount"], 4)
        self.assertEqual(auto._subscription(selected)["RequestCode"], 23)

    def test_premium_tolerance_and_missing_side_do_not_invent_contract(self):
        cfg = {**auto.DEFAULTS, "tolerance": 5}
        selected = auto.select_contracts(fixture_chain(), cfg)
        self.assertEqual(len(selected), 2)
        self.assertEqual({r["side"] for r in selected}, {"CE", "PE"})
        none = auto.select_contracts(fixture_chain([candidate(
            "CE", "12345", 500)]), cfg)
        self.assertEqual(none, [])

    def test_premium_hysteresis_keeps_near_existing_contract(self):
        c = fixture_chain([
            candidate("CE", "10001", 301),
            candidate("CE", "10002", 308),
            candidate("PE", "10003", 298)])
        cfg = {**auto.DEFAULTS, "per_side": 1}
        selected = auto.select_contracts(c, cfg, previous_ids={"NSE_FNO:10002"})
        self.assertEqual([c["security_id"] for c in selected],
                         ["10002", "10003"])

    def test_mixed_stacked_binary_packets_are_paired_per_security_id_only(self):
        now = datetime(2026, 11, 19, 4, 15, tzinfo=timezone.utc)
        picked = {
            "12345": {"identity": "NSE_FNO:12345"},
            "12348": {"identity": "NSE_FNO:12348"},
        }
        pending = {}
        frames = (quote_packet("12345", "bid") +
                  quote_packet("12348", "ask") +
                  quote_packet("12345", "ask") +
                  quote_packet("12348", "bid"))
        paired = auto._paired_books(frames, picked, pending, now)
        self.assertEqual(len(paired), 2)
        self.assertEqual({book["identity"] for book, _ in paired},
                         {"NSE_FNO:12345", "NSE_FNO:12348"})
        self.assertTrue(all(book["full_depth"] for book, _ in paired))
        self.assertEqual(pending, {})

    def test_one_dhan_50_contract_message_contains_100_valid_depth_halves(self):
        """Official 20-depth stacking: each of 50 securities has bid+ask.

        A genuine 50-ID socket can deliver 33,200 bytes (100 x 332).
        Earlier code incorrectly rejected any frame larger than 16,600.
        No synthetic historical fill or relaxed bid-ask book rules here.
        """
        now = datetime(2026, 11, 23, 5, 32, tzinfo=timezone.utc)
        ids = [str(62000 + index) for index in range(50)]
        selected = {
            sec: {"identity": "NSE_FNO:" + sec}
            for sec in ids
        }
        # Fifty unique original packet identities; exactly two Dhan
        # protocol-shaped side packets for each selected security.
        stream = b"".join(
            quote_packet(sec, "bid") + quote_packet(sec, "ask")
            for sec in ids
        )
        self.assertEqual(len(stream), 332 * 2 * 50)
        observed_sides = {}
        diagnostics = {}
        pending = {}
        accepted = auto._paired_books(
            stream, selected, pending, now,
            observed_sides=observed_sides, diagnostics=diagnostics)
        self.assertEqual(len(accepted), 50)
        self.assertEqual(len({b["identity"] for b, _ in accepted}), 50)
        self.assertTrue(all(book["full_depth"] for book, _ in accepted))
        self.assertEqual(len(observed_sides), 50)
        self.assertTrue(all(sides == {"bid", "ask"}
                            for sides in observed_sides.values()))
        self.assertEqual(diagnostics, {})
        self.assertEqual(pending, {})

        # More than 50 identities (101+ half packets) remains forbidden,
        # and can never become a fabricated accepted book.
        oversized = stream + quote_packet("62999", "bid")
        error_counts = {}
        rejected = auto._paired_books(
            oversized, selected, {}, now, diagnostics=error_counts)
        self.assertEqual(rejected, [])
        self.assertEqual(error_counts["rejected_frame_count"], 1)
        self.assertEqual(error_counts["oversized_depth_stack_frames"], 1)

    def test_three_lot_depth_weighted_prices_require_real_90_units(self):
        now = datetime(2026, 11, 19, 4, 15, tzinfo=timezone.utc)
        selected = auto.select_contracts(fixture_chain(), auto.DEFAULTS)[0]
        pairs = auto._paired_books(
            quote_packet("12345", "bid") +
            quote_packet("12345", "ask"),
            {"12345": selected}, {}, now)
        book = pairs[0][0]
        features = auto._features(book, selected, lots=3)
        self.assertEqual(features["units"], 90)
        self.assertIsNotNone(features["buy_vwap_for_units"])
        self.assertIsNotNone(features["sell_vwap_for_units"])
        self.assertEqual(features["bid_quantity_20"], 200)
        self.assertEqual(features["ask_quantity_20"], 200)
        self.assertGreater(features["spread_bps"], 0)
        scarce = [dict(level, quantity=1) for level in book["ask"]]
        self.assertIsNone(auto._depth_vwap(scarce, 90))
        self.assertNotIn("fill_price", features)

    def test_auto_starts_with_local_token_and_respects_persisted_stop(self):
        """BANKNIFTY CE and PE are recorded without an Arm click."""
        with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "LOCAL-READONLY-TOKEN"}):
            self.assertFalse(auto._settings_path().exists())
            self.assertTrue(auto._config()["enabled"])
            self.assertEqual(auto._config()["per_side"], 2)
            self.assertFalse(auto._config()["allow_token_renewal"])
            with patch.object(auto, "_ensure_worker") as run:
                auto.resume_if_armed()
                run.assert_called_once()
            # Stopping explicitly persists across subsequent server startups.
            with patch.object(auto, "_ensure_worker") as run:
                disabled = auto.disarm()
                self.assertFalse(disabled["armed"])
                self.assertFalse(auto._config()["enabled"])
                auto.resume_if_armed()
                run.assert_not_called()
        auto.STOP = Event()

    def test_missing_token_never_auto_arms_and_malformed_settings_are_safe(self):
        with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": ""}):
            self.assertFalse(auto._config()["enabled"])
        auto._settings_path().write_text(
            '{"enabled":true,"target_premium":"invalid"}', encoding="utf-8")
        with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "TOKEN_PRESENT"}):
            self.assertFalse(auto._config()["enabled"])

    def test_settings_require_consent_save_locally_and_disarm(self):
        cfg = {**auto.DEFAULTS, "target_premium": 310}
        with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "LOCAL-TEST-SECRET"}):
            with self.assertRaisesRegex(ValueError, "Explicitly authorize"):
                auto.arm(cfg, confirm_live_data=False)
            with patch.object(auto, "_ensure_worker"):
                armed = auto.arm(cfg, confirm_live_data=True)
                self.assertTrue(armed["armed"])
                text = auto._settings_path().read_text(encoding="utf-8")
                self.assertNotIn("LOCAL-TEST-SECRET", text)
                self.assertTrue(json.loads(text)["enabled"])
                disarmed = auto.disarm()
                self.assertFalse(disarmed["armed"])
                self.assertFalse(auto._config()["enabled"])
        auto.STOP = Event()

    def test_bad_configuration_never_rearms_and_rejects_oversized_universe(self):
        auto._settings_path().write_text(
            '{"enabled":true,"target_premium":-1}',
            encoding="utf-8")
        self.assertFalse(auto._config()["enabled"])
        with self.assertRaisesRegex(ValueError, "1–6"):
            auto._subscription([{"security_id": str(i)}
                                for i in range(100, 107)])

    def test_original_paired_books_and_features_are_saved_together(self):
        dbpath = self.root / "shared_market.sqlite3"
        with sqlite3.connect(dbpath) as db:
            db.executescript("""
            CREATE TABLE live_depth_books(identity TEXT NOT NULL,
              received_utc TEXT NOT NULL,session_id TEXT NOT NULL,
              book_json TEXT NOT NULL,packet_pair_sha256 TEXT NOT NULL,
              PRIMARY KEY(identity,received_utc));
            CREATE TABLE auto_banknifty_depth_features(identity TEXT NOT NULL,
              received_utc TEXT NOT NULL,session_id TEXT NOT NULL,
              feature_json TEXT NOT NULL,book_pair_sha256 TEXT NOT NULL,
              PRIMARY KEY(identity,received_utc));
            """)
        @contextmanager
        def local_db():
            with sqlite3.connect(dbpath) as db:
                yield db
                db.commit()
        now = datetime(2026, 11, 19, 4, 15, tzinfo=timezone.utc)
        selected = auto.select_contracts(fixture_chain(), auto.DEFAULTS)[0]
        book, _ = auto._paired_books(
            quote_packet("12345", "bid") + quote_packet("12345", "ask"),
            {"12345": selected}, {}, now)[0]
        with patch.object(auto, "_storage"), patch.object(
                live_market, "_database", local_db):
            feature = auto._features(book, selected, 3)
            self.assertTrue(auto._store_book("auto20_20261119_abc",
                                             book, feature))
            self.assertFalse(auto._store_book("auto20_20261119_abc",
                                              book, feature))
        with sqlite3.connect(dbpath) as db:
            original = db.execute("SELECT book_json,packet_pair_sha256 "
                                  "FROM live_depth_books").fetchone()
            derived = db.execute("SELECT feature_json,book_pair_sha256 "
                                 "FROM auto_banknifty_depth_features").fetchone()
        self.assertEqual(original[1], derived[1])
        self.assertEqual(len(json.loads(original[0])["bid"]), 20)
        self.assertEqual(json.loads(derived[0])["units"], 90)
        self.assertEqual(json.loads(original[0])["source"],
                         "original_Dhan_full_market_depth_websocket")

    def test_routes_require_explicit_consent_and_are_read_only(self):
        with patch.object(auto, "status", return_value={"armed": False}),              patch.object(auto, "arm", return_value={"armed": True}),              patch.object(auto, "disarm", return_value={"armed": False}):
            # QuantLab deliberately rejects TestClient's default "testserver"
            # Host; exercise the real loopback-only API policy instead.
            with TestClient(app, base_url="http://localhost") as client:
                current = client.get("/api/trading-cockpit/auto-depth/status")
                self.assertEqual(current.status_code, 200)
                body = client.post("/api/trading-cockpit/auto-depth/arm",
                                   json={"confirm_live_data": True})
                self.assertEqual(body.status_code, 200)
                stopped = client.post("/api/trading-cockpit/auto-depth/disarm",
                                      json={})
                self.assertEqual(stopped.status_code, 200)
                refused = client.post("/api/trading-cockpit/auto-depth/arm",
                                      json={"target_premium": -5,
                                            "confirm_live_data": True})
                self.assertEqual(refused.status_code, 422)


if __name__ == "__main__":
    unittest.main()
