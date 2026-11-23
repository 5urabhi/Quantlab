"""Dhan-only full-chain strike coverage and rotating bounded 20-level acceptance.

Offline source fixtures do not certify actual Dhan entitlement or vendor uptime.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from workstation_api import wide_option_depth as wide
from workstation_api import auto_option_depth as auto

EXPIRY = "2026-11-23"
STAMP = "2026-11-22T04:30:00+00:00"


def full_source(spot=63000., above=200, below=200, missing_last=False):
    rows = []
    security = 200000
    for distance in range(-below, above + 1):
        strike = 63000. + distance * 100
        for side in ("CE", "PE"):
            security += 1
            rows.append({
                "identity": "NSE_FNO:" + str(security),
                "strike": strike, "expiry": EXPIRY, "option_type": side,
                "lot_size": 30, "contract_master_verified": True,
                "ltp": None if missing_last and abs(distance) > 70 else 300.,
                "bid": 299, "ask": 301, "volume": 500,
            })
    return {"underlying_spot": spot, "expiry": EXPIRY,
            "received_utc": STAMP, "contracts": rows}


class CompleteDhanStrikeCoverageTests(TestCase):
    def test_200_simultaneous_subscription_limit_including_atm(self):
        source = full_source()
        selected = wide.select_full_chain_rotation(source, auto.DEFAULTS)
        self.assertEqual(len(selected), 200)
        self.assertEqual(len({x["identity"] for x in selected}), 200)
        self.assertEqual(sum(x["coverage_role"] == "core" for x in selected), 120)
        self.assertEqual(sum(x["coverage_role"] == "rotating" for x in selected), 80)
        self.assertEqual(sum(x["wing"] == "atm" for x in selected), 2)
        self.assertEqual([len(g) for g in wide.socket_groups(selected)],
                         [50, 50, 50, 50])
        self.assertEqual(len(wide.subscription(wide.socket_groups(selected)[0])
                             ["InstrumentList"]), 50)

    def test_rotations_eventually_select_every_source_contract(self):
        source = full_source(above=140, below=140, missing_last=True)
        count = len(source["contracts"])
        seen = set()
        core = None
        for cycle in range(12):
            selection = wide.select_full_chain_rotation(
                source, auto.DEFAULTS, rotation_step=cycle)
            self.assertLessEqual(len(selection), 200)
            ids = {item["identity"] for item in selection}
            self.assertEqual(len(ids), len(selection))
            near = {item["identity"] for item in selection
                    if item["coverage_role"] == "core"}
            if core is None:
                core = near
            else:
                self.assertEqual(near, core, "near-ATM books remain subscribed")
            seen |= ids
        self.assertEqual(len(seen), count)
        self.assertEqual(wide._full_chain_coverage(
            source, selection)["not_currently_depth_subscribed"], count-200)
        self.assertEqual(wide._full_chain_coverage(
            source, selection)["source_contracts_reported"], count)
        self.assertIn("ltp", selection[0])
        self.assertTrue(any(item["ltp"] is None for item in selection))

    def test_large_upward_spot_move_recenters_on_previously_far_strikes(self):
        old = full_source(spot=63000., above=170, below=170)
        first = wide.select_full_chain_rotation(old, auto.DEFAULTS)
        new = {**old, "underlying_spot": 74200.}
        shifted = wide.select_full_chain_rotation(new, auto.DEFAULTS,
                                                  rotation_step=1)
        old_cores = {x["identity"] for x in first
                     if x["coverage_role"] == "core"}
        new_cores = {x["identity"] for x in shifted
                     if x["coverage_role"] == "core"}
        self.assertNotEqual(old_cores, new_cores)
        self.assertTrue(any(x["strike"] == 74200.
                            and x["coverage_role"] == "core"
                            for x in shifted))
        self.assertEqual(len(shifted), 200)
        self.assertEqual(len({x["security_id"] for x in shifted}), 200)
        self.assertEqual(wide._full_chain_coverage(
            new, shifted)["source_spot_outside_listed_strikes"], False)

    def test_source_outside_listed_range_is_reported_not_improvised(self):
        src = full_source(spot=98000., above=170, below=170)
        chosen = wide.select_full_chain_rotation(src, auto.DEFAULTS)
        stats = wide._full_chain_coverage(src, chosen)
        self.assertTrue(stats["source_spot_outside_listed_strikes"])
        self.assertEqual(stats["source_strike_max"], 80000.)
        self.assertEqual(stats["subscribed_contracts"], 200)
        self.assertTrue(all(item["strike"] <= 80000 for item in chosen))

    def test_source_verification_and_ambiguous_duplicate_fail_closed(self):
        source = full_source(above=0, below=0)
        original = source["contracts"][0]
        source["contracts"] += [
            {**original},
            {**original, "identity": "NSE_FNO:999999"},
            {**source["contracts"][1], "identity": "NSE_FNO:999998",
             "contract_master_verified": False},
        ]
        chosen = wide.select_full_chain_rotation(source, auto.DEFAULTS)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]["side"], "PE")
        self.assertFalse(any(item["identity"] == original["identity"]
                             for item in chosen))

    def test_one_sided_listed_contract_is_not_discarded(self):
        source = full_source(above=2, below=2)
        source["contracts"] = [x for x in source["contracts"] if
                               not (x["strike"] == 62800. and
                                    x["option_type"] == "PE")]
        chosen = wide.select_full_chain_rotation(source, auto.DEFAULTS)
        self.assertEqual(len(chosen), len(source["contracts"]))
        self.assertTrue(any(x["strike"] == 62800. and x["side"] == "CE"
                            for x in chosen))
        self.assertEqual(wide._full_chain_coverage(
            source, chosen)["not_currently_depth_subscribed"], 0)

    def test_depth_selection_rechecks_real_chain_and_reports_range(self):
        snapshot = full_source(spot=74100., above=170, below=170)
        state = {}
        with patch.object(wide.auto, "_refresh_master_if_needed"), \
             patch.object(wide.option_chain_live, "expiries",
                          return_value={"nearest_expiry": EXPIRY}), \
             patch.object(wide.option_chain_live, "chain",
                          return_value=snapshot) as chain, \
             patch.object(wide.auto, "_now",
                          return_value=datetime.fromisoformat(STAMP)), \
             patch.object(wide.auto, "_status_update",
                          side_effect=lambda **kwargs: state.update(kwargs)):
            selected = wide._select(auto.DEFAULTS, rotation_step=4)
        self.assertEqual(chain.call_count, 1)
        self.assertEqual(chain.call_args.kwargs["force_refresh"], True)
        self.assertEqual(len(selected), 200)
        self.assertEqual(state["rotation_step"], 4)
        self.assertEqual(state["source_contracts_reported"], 682)
        self.assertGreater(state["not_currently_depth_subscribed"], 0)
        self.assertGreater(state["subscribed_strike_max"], 74100)
        self.assertEqual(auto.CHAIN_REFRESH_SECONDS, 20)

    def test_invalid_spot_or_rotation_is_blocked(self):
        source = full_source()
        self.assertEqual(wide.select_full_chain_rotation(
            {**source, "contracts": []}, auto.DEFAULTS), [])
        with self.assertRaisesRegex(ValueError, "spot/expiry"):
            wide.select_full_chain_rotation(
                {**source, "underlying_spot": float("nan")},
                auto.DEFAULTS)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            wide.select_full_chain_rotation(source, auto.DEFAULTS,
                                            rotation_step=-1)
