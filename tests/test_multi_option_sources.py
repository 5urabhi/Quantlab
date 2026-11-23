"""Offline vendor fixture tests for multiple option-market connections and sources."""
from __future__ import annotations

from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import json
import os
import stat
import tempfile

from fastapi.testclient import TestClient

from workstation_api import option_source_coverage, upstox_options, option_chain_live, service
from workstation_api.app import app

EXPIRY = (date.today() + timedelta(days=12)).isoformat()
ID_CE = "58742"
ID_PE = "58743"


def catalog_fixture():
    records = []
    for identity, side, strike in ((ID_CE, "CE", 63000),
                                    (ID_PE, "PE", 63000),
                                    ("58744", "CE", 64000)):
        records.append({
            "exchange": "NSE", "segment": "NSE_FO",
            "underlying_key": "NSE_INDEX|Nifty Bank",
            "instrument_type": side,
            "instrument_key": "NSE_FO|" + identity,
            "exchange_token": identity,
            "expiry": EXPIRY,
            "strike_price": strike, "lot_size": 30,
            "trading_symbol": f"BANKNIFTY {strike} {side}",
        })
    return {"status": "success", "data": records}


def chain_fixture():
    return {"status": "success", "data": [
        {
            "expiry": EXPIRY, "underlying_key": "NSE_INDEX|Nifty Bank",
            "underlying_spot_price": 62999,
            "strike_price": 63000,
            "call_options": {"instrument_key": "NSE_FO|" + ID_CE,
                             "market_data": {"ltp": 299.9, "bid_price": 299,
                                             "ask_price": 301, "bid_qty": 30,
                                             "ask_qty": 40, "oi": 1200,
                                             "volume": 200},
                             "option_greeks": {"iv": 13.4, "delta": .5}},
            "put_options": {"instrument_key": "NSE_FO|" + ID_PE,
                            "market_data": {"ltp": 310.9, "bid_price": 310,
                                            "ask_price": 311},
                            "option_greeks": {"iv": 15.5}},
        },
        {
            "expiry": EXPIRY, "underlying_key": "NSE_INDEX|Nifty Bank",
            "underlying_spot_price": 62999,
            "strike_price": 64000,
            "call_options": {"instrument_key": "NSE_FO|58744",
                             "market_data": {"ltp": 75, "bid_price": 74,
                                             "ask_price": 76}},
        }
    ]}


def master_fixture():
    lookup = {}
    for identity, side, strike in ((ID_CE, "CE", 63000),
                                    (ID_PE, "PE", 63000),
                                    ("58744", "CE", 64000)):
        lookup[identity] = {
            "identity": "NSE_FNO:" + identity,
            "expiry": EXPIRY, "strike": strike,
            "option_type": side, "lot_size": 30,
        }
    return {"fresh": True, "by_id": lookup, "message": "Original current master",
            "age_hours": 0}


def dhan_fixture():
    contract = {
        "identity": "NSE_FNO:"+ID_CE, "expiry": EXPIRY,
        "strike": 63000, "option_type": "CE", "symbol": "BANKNIFTY63000CE",
        "lot_size": 30, "contract_master_verified": True,
        "bid": 300.5, "ask": 300, "ltp": 300,
        "quote_valid": False,
        "iv": 13, "oi": 1300, "volume": 400,
    }
    return {
        "underlying": "BANKNIFTY", "underlying_spot": 63000,
        "expiry": EXPIRY, "received_utc": "2026-11-22T00:00:00+00:00",
        "market_master_fresh": True, "master_message": "Good Dhan master",
        "master_age_hours": 0.2,
        "contracts": [contract], "quote_count": 1,
        "cache_hit": False, "read_only": True,
    }


class UpstoxMarketOptionTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="quantlab_upstox_options_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.addCleanup(upstox_options.reset_for_tests)
        source = patch.object(service, "DATA", self.root / "data")
        source.start()
        self.addCleanup(source.stop)
        env = patch.dict(os.environ, {"UPSTOX_ACCESS_TOKEN": "",
                                      "DHAN_ACCESS_TOKEN": ""}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def configure(self):
        token = "read_only_ABC_xyz.12345_notreal"
        result = upstox_options.configure(token, confirm_local_storage=True)
        self.assertTrue(result["configured"])
        self.assertNotIn(token, json.dumps(result))
        self.assertTrue(upstox_options.configured())
        return token

    def test_local_explicit_connect_requires_consent_and_private_storage(self):
        token = "read_only_ABC_xyz.12345_notreal"
        with self.assertRaisesRegex(ValueError, "Explicit consent"):
            upstox_options.configure(token, confirm_local_storage=False)
        self.assertFalse(upstox_options.configured())
        self.configure()
        file = self.root/"data"/"research_workspace"/"upstox"/"read_only_token.json"
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        status = self.client.get("/api/trading-cockpit/options/providers")
        self.assertEqual(status.status_code, 200)
        self.assertNotIn(token, status.text)
        self.assertNotIn("client_id", status.text)
        self.assertTrue(next(p for p in status.json()["providers"]
                             if p["id"] == "upstox")["configured"])

    def test_contract_catalog_all_expiries_and_deduped_identity(self):
        self.configure()
        with patch.object(upstox_options, "_http", return_value=catalog_fixture()) as fetch:
            record = upstox_options.contracts()
            again = upstox_options.contracts()
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(again["cache_hit"])
        self.assertEqual(record["expiries"], [EXPIRY])
        self.assertEqual(len(record["contracts"]), 3)
        self.assertEqual(record["contracts"]["NSE_FO|58744"]["lot_size"], 30)

    def test_quote_mapping_only_with_matching_real_dhan_master(self):
        catalog = upstox_options._catalog(
            catalog_fixture(), "BANKNIFTY",
            captured=datetime.now(timezone.utc))
        matched = upstox_options._normalize_chain(
            chain_fixture(), "BANKNIFTY", EXPIRY, catalog, master_fixture(),
            datetime.now(timezone.utc))
        self.assertEqual(matched["quote_count"], 3)
        self.assertEqual(matched["strike_count"], 2)
        self.assertTrue(all(x["contract_master_verified"] for x in matched["contracts"]))
        call = next(x for x in matched["contracts"]
                    if x["option_type"] == "CE" and x["strike"] == 63000)
        self.assertEqual(call["identity"], "NSE_FNO:"+ID_CE)
        self.assertEqual(call["one_lot_ask_inr"], 9030)
        self.assertEqual(call["iv"], 13.4)
        unverified = upstox_options._normalize_chain(
            chain_fixture(), "BANKNIFTY", EXPIRY, catalog,
            {"fresh": False, "by_id": {}, "message": "stale"},
            datetime.now(timezone.utc))
        self.assertTrue(all(not x["contract_master_verified"]
                            and x["identity"] is None
                            and x["one_lot_ask_inr"] is None
                            for x in unverified["contracts"]))

    def test_non_matching_provider_exchange_contract_is_not_promoted(self):
        raw = chain_fixture()
        raw["data"][0]["call_options"]["instrument_key"] = "NSE_FO|99999"
        catalog = upstox_options._catalog(catalog_fixture(), "BANKNIFTY",
                                          captured=datetime.now(timezone.utc))
        normalized = upstox_options._normalize_chain(
            raw, "BANKNIFTY", EXPIRY, catalog, master_fixture(),
            datetime.now(timezone.utc))
        self.assertEqual(normalized["quote_count"], 2)
        self.assertNotIn("NSE_FNO:"+ID_CE,
                         {x["identity"] for x in normalized["contracts"]})

    def test_multi_provider_union_keeps_source_bid_ask_together(self):
        catalog = upstox_options._catalog(catalog_fixture(), "BANKNIFTY",
                                          captured=datetime.now(timezone.utc))
        upstox = upstox_options._normalize_chain(
            chain_fixture(), "BANKNIFTY", EXPIRY, catalog, master_fixture(),
            datetime.now(timezone.utc))
        combined = option_source_coverage._combine(
            {"dhan": dhan_fixture(), "upstox": upstox},
            "BANKNIFTY", EXPIRY, {})
        self.assertEqual(combined["quote_count"], 3)
        self.assertEqual(combined["provider_contract_counts"]["upstox"], 3)
        self.assertEqual(combined["secondary_verified_quote_replacements"], 1)
        first = next(c for c in combined["contracts"] if c["strike"] == 63000
                     and c["option_type"] == "CE")
        self.assertEqual(first["quote_provider"], "upstox")
        self.assertEqual(first["bid"], 299)
        self.assertEqual(first["ask"], 301)
        self.assertEqual(first["available_sources"], ["dhan", "upstox"])
        self.assertEqual(combined["source_identity_conflicts"], 0)

    def test_conflicting_verified_security_ids_do_not_get_blended(self):
        d = dhan_fixture()
        u = dhan_fixture()
        u["contracts"][0] = {**u["contracts"][0],
                             "identity": "NSE_FNO:99999",
                             "bid": 305, "ask": 306,
                             "quote_valid": True}
        result = option_source_coverage._combine(
            {"dhan": d, "upstox": u}, "BANKNIFTY", EXPIRY, {})
        self.assertEqual(result["source_identity_conflicts"], 1)
        self.assertEqual(result["contracts"][0]["identity"], "NSE_FNO:"+ID_CE)
        self.assertFalse(result["contracts"][0]["quote_valid"])

    def test_only_upstox_connection_is_useful_and_does_not_claim_dhan_depth(self):
        self.configure()
        with patch.object(upstox_options, "contracts",
                          return_value={"expiries": [EXPIRY]}) as get_catalog:
            result = option_source_coverage.expiries()
        self.assertEqual(result["expiries"], [EXPIRY])
        self.assertEqual(result["providers_used"], ["upstox"])
        get_catalog.assert_called_once()
        self.assertTrue(result["read_only"])

    def test_expiry_union_retains_nonoverlapping_dates_and_failed_sources(self):
        self.configure()
        os.environ["DHAN_ACCESS_TOKEN"] = "fake"
        another = (date.today()+timedelta(days=20)).isoformat()
        with patch.object(option_chain_live, "expiries",
                          return_value={"expiries": [EXPIRY]}), \
             patch.object(upstox_options, "contracts",
                          return_value={"expiries": [EXPIRY, another]}):
            result = option_source_coverage.expiries()
        self.assertEqual(result["expiry_sources"][EXPIRY], ["dhan", "upstox"])
        self.assertEqual(result["expiry_sources"][another], ["upstox"])

    def test_endpoint_requires_local_consent_and_does_not_expose_token(self):
        token = "read_only_ABC_xyz.12345_notreal"
        blocked = self.client.post(
            "/api/trading-cockpit/options/upstox/connect", json={
                "access_token": token, "confirm_local_storage": False})
        self.assertEqual(blocked.status_code, 400)
        accepted = self.client.post(
            "/api/trading-cockpit/options/upstox/connect", json={
                "access_token": token, "confirm_local_storage": True})
        self.assertEqual(accepted.status_code, 200)
        self.assertNotIn(token, accepted.text)
        with patch.object(upstox_options, "contracts",
                          return_value={"expiries": [EXPIRY]}):
            r = self.client.get("/api/trading-cockpit/options/coverage/expiries",
                                params={"underlying": "BANKNIFTY"})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(token, r.text)
        rejected = self.client.get(
            "/api/trading-cockpit/options/coverage/chain",
            params={"expiry": EXPIRY, "underlying": "NOT_AN_INDEX"})
        self.assertEqual(rejected.status_code, 422)
        gone = self.client.post(
            "/api/trading-cockpit/options/upstox/disconnect",
            json={"confirm_disconnect": True})
        self.assertEqual(gone.status_code, 200)
        self.assertFalse(upstox_options.configured())
