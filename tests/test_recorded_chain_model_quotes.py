"""The BANKNIFTY collector-to-model bridge must reuse only recorded source quotes.

All fixtures here are synthetic, in an isolated SQLite file. No vendor/API call,
market data collection, or brokerage order is made in these tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from workstation_api import (model_lab, option_quotes, recorded_chain_model_quotes,
                             service, shared_market_data)
from workstation_api.app import app


class RecordedBankNiftyQuoteBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ql_recorded_chain_fixture_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / "shared_market.sqlite"
        self.folder = self.root / "shared_prices"
        self.folder.mkdir()
        self.dataset = {"id": "dhan_shared", "kind": "dhan", "has_prices": False,
                        "has_daily_prices": True, "label": "TEST ORIGINAL CHAIN"}
        self.env_patches = [
            patch.object(service, "DATA", self.root),
            patch.object(service, "dataset_path",
                         return_value=(self.folder, self.dataset)),
            patch.object(shared_market_data, "database_path",
                         return_value=self.dbpath),
        ]
        for p in self.env_patches:
            p.start()
            self.addCleanup(p.stop)
        captured = datetime.now(timezone.utc) - timedelta(hours=10)
        expiry = (captured + timedelta(days=35)).date().isoformat()
        self.source = {
            "underlying": "BANKNIFTY", "underlying_spot": 60000.0,
            "expiry": expiry, "received_utc": captured.isoformat(),
            "source": "Dhan v2 read-only optionchain snapshot",
            "source_clock": "local_received_utc_not_exchange_quote_time",
            "market_master_fresh": True,
            "contracts": [
                {"expiry": expiry, "strike": 60000.0, "option_type": "CE",
                 "bid": 395.0, "ask": 400.0, "quote_valid": True},
                {"expiry": expiry, "strike": 60000.0, "option_type": "PE",
                 "bid": 392.0, "ask": 402.0, "quote_valid": True},
                {"expiry": expiry, "strike": 61000.0, "option_type": "CE",
                 "bid": 100.0, "ask": 90.0, "quote_valid": False},
            ],
        }
        payload = json.dumps(self.source, sort_keys=True, separators=(",", ":"))
        self.raw = payload
        self.digest = sha256(payload.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.dbpath) as db:
            db.execute("""CREATE TABLE option_chain_observations (
                underlying TEXT NOT NULL, expiry TEXT NOT NULL,
                captured_utc TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
                normalized_json TEXT NOT NULL,
                PRIMARY KEY(underlying,expiry,captured_utc))""")
            db.execute("INSERT INTO option_chain_observations VALUES (?,?,?,?,?)", (
                "BANKNIFTY", expiry, captured.isoformat(), self.digest, payload))
            db.commit()

    def test_available_inventory_makes_no_provider_request(self):
        with patch("workstation_api.dhan_option_chain._json_http",
                   side_effect=AssertionError("No Dhan calls allowed")):
            results = recorded_chain_model_quotes.available()
        self.assertEqual(results["dataset_id"], "dhan_shared")
        self.assertEqual(len(results["snapshots"]), 1)
        self.assertEqual(results["snapshots"][0]["valid_contracts"], 2)
        self.assertTrue(results["snapshots"][0]["expiry_time_is_assumed"])

    def test_explicit_reuse_is_idempotent_and_stores_normalized_provenance(self):
        with self.assertRaisesRegex(ValueError, "Confirm"):
            recorded_chain_model_quotes.use_saved(
                "dhan_shared", self.digest, confirm_reuse=False)
        with self.assertRaisesRegex(ValueError, "shared"):
            recorded_chain_model_quotes.use_saved(
                "market_fixture", self.digest, confirm_reuse=True)
        first = recorded_chain_model_quotes.use_saved(
            "dhan_shared", self.digest, confirm_reuse=True)
        second = recorded_chain_model_quotes.use_saved(
            "dhan_shared", self.digest, confirm_reuse=True)
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(first["reused_existing"])
        self.assertTrue(second["reused_existing"])
        receipt = option_quotes.get(first["id"], "dhan_shared")
        self.assertEqual(len(receipt["contracts"]), 2)
        self.assertEqual(receipt["source_type"], "dhan_cached_normalized_optionchain_v1")
        info = receipt["provider_metadata"]
        self.assertFalse(info["source_expiry_time_is_exact"])
        self.assertFalse(info["original_vendor_response_present"])
        self.assertEqual(info["stored_chain_snapshot_sha256"], self.digest)
        self.assertIn("not", receipt["warning"].lower())

    def test_saved_source_can_run_all_five_quote_models(self):
        imported = recorded_chain_model_quotes.use_saved(
            "dhan_shared", self.digest, confirm_reuse=True)
        quote = imported["id"] + ":0"
        for key in ("black_scholes_quote","binomial_quote",
                    "implied_vol_quote","mc_option_quote",
                    "option_surface_quote"):
            output = model_lab.run_model(key, "dhan_shared", {"quote": quote})
            self.assertEqual(output["mode"], "market", key)
            self.assertEqual(output["source"]["dataset_id"], "dhan_shared", key)
            self.assertEqual(output["source"]["option_quote_id"], imported["id"], key)
            self.assertEqual(output["source"]["market_quote_observed"], True, key)

    def test_tampering_stored_snapshot_fails_closed(self):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("UPDATE option_chain_observations SET normalized_json=?",
                       (self.raw.replace("60000.0", "61000.0"),))
        self.assertEqual(recorded_chain_model_quotes.available()["snapshots"], [])
        with self.assertRaisesRegex(ValueError, "checksum"):
            recorded_chain_model_quotes.use_saved(
                "dhan_shared", self.digest, confirm_reuse=True)

    def test_api_requires_explicit_reuse_consent(self):
        with TestClient(app, base_url="http://127.0.0.1:8765") as api:
            no = api.post("/api/lab/option-quotes/use-recorded", json={
                "dataset_id": "dhan_shared", "snapshot_sha256": self.digest,
                "confirm_reuse": False})
            self.assertEqual(no.status_code, 400, no.text)
            got = api.get("/api/lab/option-quotes/recorded-chains")
            self.assertEqual(got.status_code, 200, got.text)
            self.assertEqual(len(got.json()["snapshots"]), 1)
            yes = api.post("/api/lab/option-quotes/use-recorded", json={
                "dataset_id": "dhan_shared", "snapshot_sha256": self.digest,
                "confirm_reuse": True})
            self.assertEqual(yes.status_code, 200, yes.text)
            self.assertEqual(yes.json()["contracts"], 2)


if __name__ == "__main__":
    unittest.main()
