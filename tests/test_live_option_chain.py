"""Offline BANKNIFTY option chain, master lot size, quotes and no-order regressions."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from fastapi.testclient import TestClient
import json
import sqlite3
import tempfile

from workstation_api import service, option_chain_live, dhan_option_chain
from workstation_api.app import app

WHEN = datetime(2026, 11, 19, 10, 30, tzinfo=timezone.utc)
EXPIRY = "2026-11-23"
ID = "58742"


def fixture_chain(security_id=58742, ask=301.0, bid=299.0):
    return {"status": "success", "data": {
        "last_price": 62950.0,
        "oc": {"63000.000000": {
            "ce": {
                "security_id": security_id, "last_price": 300.0,
                "top_bid_price": bid, "top_bid_quantity": 150,
                "top_ask_price": ask, "top_ask_quantity": 180,
                "oi": 12345, "volume": 4500, "implied_volatility": 13.5,
                "greeks": {"delta": 0.5, "theta": -12.4},
            },
            "pe": {
                "security_id": 58743, "last_price": 310,
                "top_bid_price": 305, "top_ask_price": 306,
                "oi": 5000, "volume": 2000,
            },
        }},
    }}


class BankNiftyOptionChainTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="quantlab_option_chain_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        location = patch.object(service, "DATA", self.root / "data")
        location.start()
        self.addCleanup(location.stop)
        env = patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "offline_token",
                                      "DHAN_CLIENT_ID": "123456"}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.now = patch.object(option_chain_live, "_clock", return_value=WHEN)
        self.now.start()
        self.addCleanup(self.now.stop)
        option_chain_live._reset_for_tests()
        self.addCleanup(option_chain_live._reset_for_tests)
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def write_master(self, *, size=30):
        path = self.root / "data" / "dhan" / "instrument_master.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,TRADING_SYMBOL,"
            "LOT_SIZE,SM_EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE\n"
            f"NSE,D,58742,OPTIDX,BANKNIFTY23NOV63000CE,{size},{EXPIRY},63000,CE\n"
            f"NSE,D,58743,OPTIDX,BANKNIFTY23NOV63000PE,{size},{EXPIRY},63000,PE\n"
            "NSE,D,11111,OPTIDX,NIFTY23NOV25000CE,65,2026-11-23,25000,CE\n",
            encoding="utf-8",
        )
        return path

    def vendor(self, chain=None):
        expected = chain or fixture_chain()
        def respond(url, *, token, client_id="", body=None):
            self.assertEqual(token, "offline_token")
            self.assertEqual(client_id, "123456")
            self.assertEqual(body["UnderlyingScrip"], 25)
            self.assertEqual(body["UnderlyingSeg"], "IDX_I")
            if url == dhan_option_chain.EXPIRY_ENDPOINT:
                return {"status": "success", "data": [EXPIRY, "2026-12-29"]}, b"[]"
            self.assertEqual(url, dhan_option_chain.CHAIN_ENDPOINT)
            self.assertEqual(body["Expiry"], EXPIRY)
            return expected, b"{}"
        return patch.object(dhan_option_chain, "_json_http", side_effect=respond)

    def test_live_chain_has_exact_contract_id_and_master_lot_cost(self):
        self.write_master()
        with self.vendor() as calls:
            dates = option_chain_live.expiries(sleep=lambda _: None)
            self.assertEqual(dates["nearest_expiry"], EXPIRY)
            chain = option_chain_live.chain(EXPIRY, sleep=lambda _: None)
            same = option_chain_live.chain(EXPIRY, sleep=lambda _: None)
        self.assertEqual(calls.call_count, 2, "expirylist and chain are cached")
        self.assertTrue(same["cache_hit"])
        self.assertEqual(chain["quote_count"], 2)
        self.assertEqual(chain["underlying_spot"], 62950)
        self.assertTrue(chain["not_live_stream"])
        call = next(row for row in chain["contracts"] if row["option_type"] == "CE")
        self.assertEqual(call["identity"], "NSE_FNO:58742")
        self.assertEqual(call["lot_size"], 30)
        self.assertEqual(call["one_lot_ask_inr"], 9030)
        self.assertEqual(call["one_lot_bid_inr"], 8970)
        self.assertEqual(call["spread_inr_per_lot"], 60)
        self.assertTrue(call["contract_master_verified"])
        self.assertEqual(call["delta"], .5)
        self.assertEqual(call["oi"], 12345)
        self.assertNotIn("offline_token", json.dumps(chain))
        self.assertNotIn("123456", json.dumps(chain))
        with sqlite3.connect(self.root / "data" / "dhan" / "shared_market.sqlite3") as conn:
            records = conn.execute(
                "SELECT COUNT(*) FROM option_chain_observations").fetchone()[0]
        self.assertEqual(records, 1, "save snapshot in one canonical Market Library")

    def test_missing_master_blocks_lot_estimates_and_depth_identity(self):
        with self.vendor():
            result = option_chain_live.chain(EXPIRY, sleep=lambda _: None)
        row = next(row for row in result["contracts"] if row["option_type"] == "CE")
        self.assertIsNone(row["identity"])
        self.assertIsNone(row["lot_size"])
        self.assertIsNone(row["one_lot_ask_inr"])
        self.assertFalse(row["contract_master_verified"])
        self.assertFalse(result["market_master_fresh"])
        self.assertIn("instrument master", result["master_message"].lower())

    def test_provider_security_id_mismatch_cannot_be_falsely_mapped(self):
        self.write_master()
        with self.vendor(fixture_chain(security_id=99999)):
            result = option_chain_live.chain(EXPIRY, sleep=lambda _: None)
        row = next(row for row in result["contracts"] if row["option_type"] == "CE")
        self.assertIsNone(row["identity"])
        self.assertIsNone(row["lot_size"])
        self.assertFalse(row["contract_master_verified"])

    def test_invalid_bid_ask_is_visible_but_not_buyable(self):
        self.write_master()
        with self.vendor(fixture_chain(ask=298, bid=300)):
            row = option_chain_live.chain(EXPIRY, sleep=lambda _: None)["contracts"][0]
        self.assertFalse(row["quote_valid"])
        self.assertIsNone(row["one_lot_ask_inr"])
        self.assertIsNone(row["spread_inr_per_lot"])

    def test_api_endpoints_stay_read_only_and_reject_invalid_expiry(self):
        self.write_master()
        with self.vendor():
            expiry = self.client.get("/api/trading-cockpit/options/expiries")
            self.assertEqual(expiry.status_code, 200, expiry.text)
            result = self.client.get("/api/trading-cockpit/options/chain",
                                     params={"expiry": EXPIRY})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["contracts"][0]["lot_size"], 30)
        self.assertEqual(result.json()["read_only"], True)
        self.assertEqual(self.client.get("/api/trading-cockpit/options/chain",
            params={"expiry": "2000-01-01"}).status_code, 400)
        self.assertEqual(self.client.get("/api/trading-cockpit/options/chain",
            params={"expiry": "2026-11-23%0ADELETE"}).status_code, 400)

    def test_forced_refresh_after_master_replacement_updates_lot_size(self):
        self.write_master(size=35)
        with self.vendor() as calls:
            old = option_chain_live.chain(EXPIRY, sleep=lambda _: None)
            self.assertEqual(old["contracts"][0]["lot_size"], 35)
            self.write_master(size=30)
            new = option_chain_live.chain(
                EXPIRY, force_refresh=True, sleep=lambda _: None)
        self.assertEqual(new["contracts"][0]["lot_size"], 30)
        self.assertEqual(new["contracts"][0]["one_lot_ask_inr"], 9030)
        self.assertEqual(calls.call_count, 3, "one expiry and two original chain captures")

    def test_lot_size_is_from_source_not_fixed_to_30(self):
        self.write_master(size=35)
        with self.vendor():
            row = option_chain_live.chain(EXPIRY, sleep=lambda _: None)["contracts"][0]
        self.assertEqual(row["lot_size"], 35)
        self.assertEqual(row["one_lot_ask_inr"], 10_535)

    def test_all_original_strikes_are_retained_in_snapshot(self):
        """Do not discard distant valid strikes from Dhan's per-expiry chain."""
        expiry = EXPIRY
        source = {"data": {"last_price": 63000.0, "oc": {}}}
        for idx in range(75):
            strike = 59000 + 100 * idx
            source["data"]["oc"][f"{strike:.6f}"] = {
                "ce": {"last_price": 300.0, "top_bid_price": 299.0,
                       "top_ask_price": 301.0},
                "pe": {"last_price": 310.0, "top_bid_price": 309.0,
                       "top_ask_price": 311.0},
            }
        normalized = option_chain_live._normalize(
            source, expiry, WHEN,
            {"fresh": False, "available": False,
             "message": "No source master", "age_hours": None,
             "by_id": {}, "by_terms": {}})
        self.assertEqual(normalized["strike_count"], 75)
        self.assertEqual(normalized["source_strike_count"], 75)
        self.assertEqual(normalized["quote_count"], 150)
        self.assertIn(59000, {c["strike"] for c in normalized["contracts"]})
        self.assertIn(66400, {c["strike"] for c in normalized["contracts"]})
        self.assertTrue(all(not c["contract_master_verified"] for c in normalized["contracts"]))

    def test_all_listed_expiries_are_kept_without_40_date_cap(self):
        dates = [(date(2026, 11, 20) + timedelta(days=7*i)).isoformat()
                 for i in range(55)]
        def original(url, *, token, client_id="", body=None):
            self.assertEqual(url, dhan_option_chain.EXPIRY_ENDPOINT)
            return {"status": "success", "data": dates}, b"{}"
        with patch.object(dhan_option_chain, "_json_http", side_effect=original):
            result = option_chain_live.expiries(sleep=lambda _: None)
        self.assertEqual(len(result["expiries"]), 55)
        self.assertEqual(result["expiries"][-1], dates[-1])
