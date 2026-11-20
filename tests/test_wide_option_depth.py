"""Offline safety and coverage tests for automatic 200-contract BANKNIFTY depth.

Synthetic source fixtures verify selection and stream bounds; they do NOT
claim successful Dhan depth entitlement or source market observations.
"""
from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import patch
import os

from workstation_api import auto_option_depth as auto
from workstation_api import wide_option_depth as wide


def chain_fixture(spot=63031., above=65, below=65):
    pairs = []
    sid = 310000
    for offset in range(-below, above + 1):
        strike = 63000. + offset * 100
        for side in ("CE", "PE"):
            sid += 1
            pairs.append({
                "strike": strike, "option_type": side,
                "identity": "NSE_FNO:" + str(sid),
                "expiry": "2026-11-23", "lot_size": 30,
                "ltp": 300. + offset * .01,
                "bid": 299., "ask": 301.,
                "volume": max(0, 100 + offset),
                "contract_master_verified": True,
            })
    return {"underlying_spot": spot, "expiry": "2026-11-23",
            "received_utc": "2026-11-20T04:30:00+00:00",
            "contracts": pairs}


class WideDepthContractsTests(TestCase):
    def test_exact_100_above_and_100_below_fifty_ce_pe_pairs(self):
        selected = wide.select_atm_contracts(chain_fixture(), auto.DEFAULTS)
        self.assertEqual(len(selected), 200)
        self.assertEqual(sum(x["wing"] == "above" for x in selected), 100)
        self.assertEqual(sum(x["wing"] == "below" for x in selected), 100)
        for wing in ("above", "below"):
            subset = [x for x in selected if x["wing"] == wing]
            self.assertEqual(sum(x["side"] == "CE" for x in subset), 50)
            self.assertEqual(sum(x["side"] == "PE" for x in subset), 50)
            self.assertEqual(len({x["strike"] for x in subset}), 50)
        self.assertTrue(all(x["atm_strike"] == 63000. for x in selected))
        self.assertEqual({x["strike"] for x in selected[:2]}, {63100.})
        self.assertEqual({x["strike"] for x in selected[100:102]}, {62900.})
        self.assertEqual(sum(x["priority_depth"] for x in selected), 4)
        self.assertTrue(all(x["strike"] != 63000 for x in selected))
        self.assertEqual(len({x["security_id"] for x in selected}), 200)

    def test_verified_only_missing_side_never_substituted(self):
        source = chain_fixture(above=46, below=33)
        # Remove a CE from one distant below-ATM strike.
        source["contracts"] = [
            x for x in source["contracts"] if not (
                x["strike"] == 60700. and x["option_type"] == "CE")]
        # Reject unverified and wrong-expiry data even with attractive strikes.
        source["contracts"].append({
            "identity": "NSE_FNO:999999", "strike": 63050,
            "option_type": "CE", "expiry": "2026-11-23",
            "ltp": 300., "lot_size": 30, "contract_master_verified": False})
        selected = wide.select_atm_contracts(source, auto.DEFAULTS)
        self.assertEqual(sum(x["wing"] == "above" for x in selected), 92)
        self.assertEqual(sum(x["wing"] == "below" for x in selected), 64)
        self.assertFalse(any(x["security_id"] == "999999" for x in selected))
        self.assertFalse(any(x["strike"] == 60700 for x in selected))

    def test_only_original_valid_expiry_and_ltp(self):
        source = chain_fixture(above=2, below=2)
        source["contracts"][0]["expiry"] = "2027-11-23"
        source["contracts"][2]["ltp"] = 0.
        selected = wide.select_atm_contracts(source, auto.DEFAULTS)
        self.assertFalse(any(x["identity"] == source["contracts"][0]["identity"]
                             for x in selected))
        self.assertTrue(all(x["ltp"] > 0 for x in selected))
        self.assertEqual(selected[0]["atm_strike"], 63000.)

    def test_exactly_four_websockets_with_50_instruments_each(self):
        selected = wide.select_atm_contracts(chain_fixture(), auto.DEFAULTS)
        groups = wide.socket_groups(selected)
        self.assertEqual([len(g) for g in groups], [50, 50, 50, 50])
        self.assertEqual(sum(len(g) for g in groups), 200)
        for group in groups:
            message = wide.subscription(group)
            self.assertEqual(message["RequestCode"], 23)
            self.assertEqual(message["InstrumentCount"], 50)
            self.assertEqual(len(message["InstrumentList"]), 50)
            self.assertTrue(all(x["ExchangeSegment"] == "NSE_FNO"
                                for x in message["InstrumentList"]))

    def test_prevent_over_subscription_and_duplicate_ids(self):
        choices = wide.select_atm_contracts(chain_fixture(), auto.DEFAULTS)
        with self.assertRaisesRegex(ValueError, "200-contract"):
            wide.socket_groups(choices + [dict(choices[0], security_id="999999")])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            wide.socket_groups(choices[:20] + [dict(choices[0])])
        with self.assertRaisesRegex(ValueError, "1-50"):
            wide.subscription(choices[:51])

    def test_existing_saved_3_second_config_migrates_to_safe_30(self):
        raw = {"enabled": True, "target_premium": 300,
               "tolerance": 75, "per_side": 2, "lots": 3,
               "sample_seconds": 3}
        migrated = auto._validate_config(raw)
        self.assertEqual(migrated["selection_mode"], wide.MODE)
        self.assertEqual(migrated["sample_seconds"], 30)
        self.assertTrue(migrated["enabled"])
        self.assertEqual(auto._validate_config(
            dict(raw, selection_mode="premium"))["sample_seconds"], 3)

    def test_auto_worker_dispatches_to_wide_capture(self):
        with TemporaryDirectory() as tmp:
            with patch.object(auto, "_root", return_value=Path(tmp)), \
                 patch.object(auto, "_config", return_value={
                     "selection_mode": wide.MODE, "enabled": True}), \
                 patch.object(wide, "run") as run:
                auto._run(Event())
            run.assert_called_once()

    def test_no_source_never_creates_fake_contracts(self):
        invalid = {"underlying_spot": 63000., "expiry": "2026-11-23",
                   "contracts": []}
        self.assertEqual(wide.select_atm_contracts(invalid, auto.DEFAULTS), [])
        with self.assertRaisesRegex(ValueError, "spot/expiry"):
            wide.select_atm_contracts(
                dict(invalid, underlying_spot=None), auto.DEFAULTS)
