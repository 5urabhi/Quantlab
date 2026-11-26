"""Read-only acceptance: original depth source integrity and actionable gates."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sqlite3
import unittest

from fastapi.testclient import TestClient
from workstation_api import trading_acceptance as doctor
from workstation_api.app import app


STAMP = "2026-11-19T04:10:00+00:00"
SID = "auto20_20261119_abc"


def original(side="CE", identity="NSE_FNO:111"):
    b = sha256(("bid-" + identity).encode()).hexdigest()
    a = sha256(("ask-" + identity).encode()).hexdigest()
    pair = sha256((b+a).encode()).hexdigest()
    bids = [{"price": 300-i*.1, "quantity": 10, "orders": 2}
            for i in range(20)]
    asks = [{"price": 301+i*.1, "quantity": 10, "orders": 3}
            for i in range(20)]
    book = {
        "identity": identity, "received_utc": STAMP,
        "bid": bids, "ask": asks, "full_depth": True,
        "bid_packet_sha256": b, "ask_packet_sha256": a,
        "collection_mode": "auto_banknifty_20_level",
        "source": "original_Dhan_full_market_depth_websocket",
    }
    feature = {
        "identity": identity, "received_utc": STAMP,
        "side": side, "units": 90, "lots": 3,
    }
    return book, feature, pair


class LocalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="trading-doctor-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "shared_market.sqlite3"

    def create_db(self):
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE live_depth_books(
                    identity TEXT NOT NULL,received_utc TEXT NOT NULL,
                    session_id TEXT NOT NULL,book_json TEXT NOT NULL,
                    packet_pair_sha256 TEXT NOT NULL,
                    PRIMARY KEY(identity,received_utc));
                CREATE TABLE auto_banknifty_depth_features(
                    identity TEXT NOT NULL,received_utc TEXT NOT NULL,
                    session_id TEXT NOT NULL,feature_json TEXT NOT NULL,
                    book_pair_sha256 TEXT NOT NULL,
                    PRIMARY KEY(identity,received_utc));
            """)

    def store(self, side, identity, *, corrupt=False):
        book, feature, digest = original(side, identity)
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO live_depth_books VALUES(?,?,?,?,?)", (
                identity, STAMP, SID, json.dumps(book),
                ("0"*64 if corrupt else digest)))
            db.execute("INSERT INTO auto_banknifty_depth_features VALUES(?,?,?,?,?)", (
                identity, STAMP, SID, json.dumps(feature), digest))

    def test_empty_check_is_read_only_and_does_not_create_database(self):
        self.assertFalse(self.path.exists())
        result = doctor.inspect_saved_books(self.path)
        self.assertEqual(result["status"], "not_recorded")
        self.assertFalse(self.path.exists())

    def test_original_both_sides_with_sha_receipts_are_verified(self):
        self.create_db()
        self.store("CE", "NSE_FNO:111")
        self.store("PE", "NSE_FNO:222")
        result = doctor.inspect_saved_books(self.path)
        self.assertEqual(result["status"], "verified_sample")
        self.assertEqual(result["total_automatic_books"], 2)
        self.assertEqual(result["valid_sample_books"], 2)
        self.assertEqual(result["invalid_sample_books"], 0)
        self.assertEqual(result["valid_ce_books"], 1)
        self.assertEqual(result["valid_pe_books"], 1)
        self.assertEqual(result["observed_trading_dates_in_sample"], 1)

    def test_tampered_sha_refuses_source_certificate(self):
        self.create_db()
        self.store("CE", "NSE_FNO:111", corrupt=True)
        result = doctor.inspect_saved_books(self.path)
        self.assertEqual(result["status"], "integrity_attention")
        self.assertEqual(result["valid_sample_books"], 0)
        self.assertEqual(result["invalid_sample_books"], 1)

    def test_missing_original_book_cannot_be_called_genuine_source(self):
        self.create_db()
        book, feature, digest = original()
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO auto_banknifty_depth_features VALUES(?,?,?,?,?)",
                       ("NSE_FNO:111", STAMP, SID, json.dumps(feature), digest))
        report = doctor.inspect_saved_books(self.path)
        self.assertEqual(report["status"], "integrity_attention")
        self.assertEqual(report["valid_sample_books"], 0)

    def test_integrity_diagnostics_classify_bad_receipt_without_prices(self):
        self.create_db()
        self.store("CE", "NSE_FNO:111", corrupt=True)
        result = doctor.inspect_saved_books(self.path)
        self.assertEqual(result["invalid_sample_books"], 1)
        self.assertEqual(result["invalid_reason_counts"],
                         {"stored_receipt_digest_mismatch": 1})
        encoded = json.dumps(result)
        self.assertNotIn("NSE_FNO:111", encoded)
        self.assertNotIn("300.0", encoded)

    def test_consistent_partial_original_is_not_corrupt_or_full_depth(self):
        self.create_db()
        self.store("CE", "NSE_FNO:111")
        book, feature, digest = original("PE", "NSE_FNO:222")
        book["bid"] = book["bid"][:8]
        book["full_depth"] = False
        feature["full_20_levels"] = False
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO live_depth_books VALUES(?,?,?,?,?)",
                       ("NSE_FNO:222", STAMP, SID, json.dumps(book), digest))
            db.execute("INSERT INTO auto_banknifty_depth_features VALUES(?,?,?,?,?)",
                       ("NSE_FNO:222", STAMP, SID, json.dumps(feature), digest))
        report = doctor.inspect_saved_books(self.path)
        self.assertEqual(report["status"], "partial_depth_sample")
        self.assertEqual(report["sample_checked"], 2)
        self.assertEqual(report["valid_sample_books"], 1)
        self.assertEqual(report["partial_sample_books"], 1)
        self.assertEqual(report["invalid_sample_books"], 0)
        self.assertEqual(report["invalid_reason_counts"], {})
        self.assertFalse(doctor._valid_pair(book, feature, digest, digest,
                                          "NSE_FNO:222", SID, STAMP))

    def test_partial_depth_never_masks_invalid_source_or_digest(self):
        book, feature, digest = original()
        book["ask"] = book["ask"][:6]
        book["full_depth"] = False
        args = ("NSE_FNO:111", SID, STAMP)
        self.assertEqual(doctor._pair_rejection_reason(
            {**book, "source": "unknown"}, feature, digest, digest, *args),
            "source_provenance_mismatch")
        self.assertEqual(doctor._pair_rejection_reason(
            book, feature, digest, "0"*64, *args),
            "stored_receipt_digest_mismatch")
        self.assertEqual(doctor._pair_rejection_reason(
            {**book, "full_depth": True}, feature, digest, digest, *args),
            "depth_completeness_flag_mismatch")
        self.assertEqual(doctor._pair_rejection_reason(
            book, {**feature, "full_20_levels": True}, digest, digest, *args),
            "depth_completeness_flag_mismatch")

    def test_missing_book_reports_exact_reason_without_repair(self):
        self.create_db()
        book, feature, digest = original()
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO auto_banknifty_depth_features VALUES(?,?,?,?,?)",
                       ("NSE_FNO:111", STAMP, SID, json.dumps(feature), digest))
        result = doctor.inspect_saved_books(self.path)
        self.assertEqual(result["invalid_reason_counts"],
                         {"missing_original_book": 1})
        self.assertEqual(result["status"], "integrity_attention")

    def test_rejection_reasons_preserve_original_validator_acceptance(self):
        book, feature, digest = original()
        values = ("NSE_FNO:111", SID, STAMP)
        self.assertIsNone(doctor._pair_rejection_reason(
            book, feature, digest, digest, *values))
        self.assertTrue(doctor._valid_pair(
            book, feature, digest, digest, *values))
        changed = {**book, "bid": [{**level} for level in book["bid"]]}
        changed["bid"][0]["price"] = 999
        self.assertEqual(doctor._pair_rejection_reason(
            changed, feature, digest, digest, *values), "crossed_top_of_book")
        self.assertFalse(doctor._valid_pair(
            changed, feature, digest, digest, *values))

    def test_local_report_is_actionable_and_does_not_call_dhan(self):
        book_summary = {**doctor.inspect_saved_books(self.path),
                        "status": "verified_sample",
                        "total_automatic_books": 2, "valid_sample_books": 2,
                        "sample_checked": 2, "valid_ce_books": 1,
                        "valid_pe_books": 1, "latest_book_utc": STAMP}
        source = {"instruments": [{"identity": "INDEX:BANKNIFTY", "ready": True}]}
        master = {"available": True, "fresh": True, "by_id": {
            "111": {"option_type": "CE"}, "222": {"option_type": "PE"}}}
        live = {"armed": True, "market_regular_hours": True,
                "state": "recording_original_depth", "received_pairs": 5,
                "connected": True, "latest": {"NSE_FNO:111": {
                    "fresh": True, "full_20_levels": True,
                    "bid_levels": 20, "ask_levels": 20}}}
        with patch.object(doctor.cockpit_sources, "catalog", return_value=source), \
             patch.object(doctor.option_chain_live, "_contracts", return_value=master), \
             patch.object(doctor.auto_option_depth, "status", return_value=live), \
             patch.object(doctor, "inspect_saved_books", return_value=book_summary):
            with TestClient(app, base_url="http://localhost") as client:
                response = client.get("/api/trading-cockpit/acceptance")
                self.assertEqual(response.status_code, 200)
                report = response.json()
        self.assertTrue(report["safe_to_share"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["external_api_requests"], 0)
        self.assertEqual(report["orders_placed"], 0)
        result = {x["code"]: x["status"] for x in report["checks"]}
        self.assertEqual(result["banknifty_history"], "pass")
        self.assertEqual(result["contract_master"], "pass")
        self.assertEqual(result["live_depth"], "pass")
        self.assertEqual(result["stored_depth"], "pass")
        self.assertEqual(result["options_reversal"], "requires_backtest")
        self.assertEqual(result["options_learning"], "research_pending")
        self.assertNotIn("access_token", json.dumps(report).lower())
        self.assertNotIn("client_id", json.dumps(report).lower())

    def test_after_hours_is_waiting_not_entitlement_failure(self):
        with patch.object(doctor.cockpit_sources, "catalog",
                          return_value={"instruments": []}), \
             patch.object(doctor.option_chain_live, "_contracts",
                          return_value={"available": False, "by_id": {}}), \
             patch.object(doctor.auto_option_depth, "status",
                          return_value={"armed": True, "market_regular_hours": False,
                                        "state": "armed_waiting_for_nse_hours",
                                        "received_pairs": 0, "latest": {}}), \
             patch.object(doctor, "inspect_saved_books",
                          return_value=doctor.inspect_saved_books(self.path)):
            report = doctor.report()
        status = {item["code"]: item["status"] for item in report["checks"]}
        self.assertEqual(status["live_depth"], "waiting")
        self.assertEqual(status["stored_depth"], "not_recorded")
        self.assertEqual(status["contract_master"], "action_needed")


if __name__ == "__main__":
    unittest.main()
