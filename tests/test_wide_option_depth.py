"""Offline safety and coverage tests for automatic 200-contract BANKNIFTY depth.

Synthetic source fixtures verify selection and stream bounds; they do NOT
claim successful Dhan depth entitlement or source market observations.
"""
from __future__ import annotations

from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import patch
import os
import sqlite3

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

    def test_one_second_sampling_is_bounded_and_does_not_change_subscriptions(self):
        chain=chain_fixture()
        for row in chain["contracts"]:
            row.update(bid=179.,ask=181.,ltp=180.,volume=100)
        selected=wide.select_full_chain_rotation(chain,auto.DEFAULTS)
        ids=[x["identity"] for x in selected]
        wide._assign_scalp_sampling(selected,auto.DEFAULTS)
        self.assertEqual([x["identity"] for x in selected],ids)
        for side in ("CE","PE"):
            self.assertEqual(sum(x["scalp_fast_depth"] and x["side"]==side for x in selected),6)
        self.assertEqual(sum(wide._sample_interval(x,30)==1 for x in selected),12)
        self.assertTrue(all(wide._sample_interval(x,30) in (1,3,30) for x in selected))
        for row in selected:
            row["bid"]=499.
            row["ask"]=500.
        wide._assign_scalp_sampling(selected,auto.DEFAULTS)
        self.assertEqual(sum(x["scalp_fast_depth"] for x in selected),12)
        self.assertTrue(all(x["scalp_affordable_lots"]==1 for x in selected if x["scalp_fast_depth"]))
        self.assertEqual([x["identity"] for x in selected],ids)
        for row in selected:
            row["ask"]=1000.
        wide._assign_scalp_sampling(selected,auto.DEFAULTS)
        self.assertFalse(any(x["scalp_fast_depth"] for x in selected))

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
        # Invalid unverified strike at 63050 must not move the genuine
        # 63000 ATM anchor (which previously inflated below coverage).
        self.assertTrue(all(x["atm_strike"] == 63000. for x in selected))
        self.assertEqual(sum(x["wing"] == "above" for x in selected), 92)
        self.assertEqual(sum(x["wing"] == "below" for x in selected), 64)
        self.assertFalse(any(x["security_id"] == "999999" for x in selected))
        self.assertFalse(any(x["strike"] == 60700 for x in selected))

    def test_expiry_mismatch_is_rejected_but_no_last_trade_is_allowed(self):
        source = chain_fixture(above=2, below=2)
        source["contracts"][0]["expiry"] = "2027-11-23"
        source["contracts"][2]["ltp"] = 0.
        selected = wide.select_atm_contracts(source, auto.DEFAULTS)
        self.assertFalse(any(x["identity"] == source["contracts"][0]["identity"]
                             for x in selected))
        self.assertTrue(any(x["ltp"] is None for x in selected))
        self.assertEqual(selected[0]["atm_strike"], 63000.)

    def test_untraded_but_master_verified_options_complete_full_wings(self):
        source = chain_fixture()
        # Five far-above strikes, both CE and PE, have not traded; a real
        # verified security ID still qualifies for original depth.
        for option in source["contracts"]:
            if 67600 <= option["strike"] <= 68000:
                option["ltp"] = None
        selected = wide.select_atm_contracts(source, auto.DEFAULTS)
        self.assertEqual(len(selected), 200)
        self.assertEqual(sum(x["wing"] == "above" for x in selected), 100)
        self.assertEqual(wide._coverage_diagnostics(
            source, selected)["missing_ltp_selected"], 10)

    def test_source_limited_45_above_strikes_reports_exact_shortfall(self):
        source = chain_fixture(above=45, below=50)
        selected = wide.select_atm_contracts(source, auto.DEFAULTS)
        counts = wide._coverage_diagnostics(source, selected)
        self.assertEqual(len(selected), 190)
        self.assertEqual(counts["source_pairs_above"], 45)
        self.assertEqual(counts["source_pairs_below"], 50)
        self.assertIn("45/50 strike pairs verified", counts["rejection_explanations"]["above"])

    def test_packet_receipt_health_is_independent_of_disk_sample_age(self):
        now = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
        selected = wide.select_atm_contracts(
            chain_fixture(above=1, below=1), auto.DEFAULTS)
        identity = selected[0]["identity"]
        state = {
            "connected": True, "contracts": [selected[0]],
            "latest": {identity: {"received_utc": (
                now - timedelta(seconds=45)).isoformat()}},
            "received_pairs": 0,
        }
        last_source = now - timedelta(seconds=2)
        with patch.object(auto, "STATE", state):
            wide._record_original_pairs(0, [({}, selected[0])], last_source)
            with patch.object(auto, "_now", return_value=now), \
                 patch.object(auto, "_market_open", return_value=True), \
                 patch.object(auto, "_config", return_value={
                     **auto.DEFAULTS, "enabled": True}):
                report = auto.status()
        self.assertEqual(report["received_pairs"], 1)
        self.assertEqual(report["contracts_with_saved_books"], 1)
        self.assertEqual(report["contracts_with_recent_packets"], 1)
        self.assertEqual(report["sockets_with_recent_pairs"], 1)
        self.assertEqual(report["latest"][identity]["age_seconds"], 45)
        self.assertEqual(report["latest"][identity]["feed_age_seconds"], 2)
        self.assertTrue(report["latest"][identity]["feed_fresh"])
        self.assertNotIn("observed_by_contract", report)
        self.assertNotIn("socket_last_paired_utc", report)
        self.assertFalse(wide._stalled_socket(now.timestamp(), now.timestamp() - 100))
        self.assertTrue(wide._stalled_socket(now.timestamp(), now.timestamp() - 121))

    def test_nullable_ltp_receipt_migration_preserves_real_historical_rows(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE auto_banknifty_depth_selections(
                    session_id TEXT NOT NULL, changed_utc TEXT NOT NULL,
                    identity TEXT NOT NULL, option_side TEXT NOT NULL,
                    expiry TEXT NOT NULL, strike REAL NOT NULL,
                    lot_size INTEGER NOT NULL, selected_ltp REAL NOT NULL,
                    chain_received_utc TEXT NOT NULL,
                    PRIMARY KEY(session_id, changed_utc, identity))""")
                db.execute("""INSERT INTO auto_banknifty_depth_selections
                    VALUES ('old','2026-11-19T05:00:00+00:00',
                    'NSE_FNO:99','CE','2026-11-23',63200,30,201,
                    '2026-11-19T05:00:00+00:00')""")
            @contextmanager
            def mocked_db():
                with sqlite3.connect(path) as db:
                    yield db
            with patch.object(auto.shared_market_data, "database_path",
                              return_value=path), \
                 patch.object(auto.live_market, "_init_db"), \
                 patch.object(auto.live_market, "_database", mocked_db), \
                 patch.object(auto, "STORAGE_READY", None):
                auto._storage()
            with sqlite3.connect(path) as db:
                original = db.execute("SELECT selected_ltp FROM "
                    "auto_banknifty_depth_selections WHERE identity='NSE_FNO:99'"
                ).fetchone()[0]
                self.assertEqual(original, 201)
                db.execute("""INSERT INTO auto_banknifty_depth_selections
                    VALUES ('new','2026-11-20T05:00:00+00:00',
                    'NSE_FNO:100','PE','2026-11-23',63100,30,NULL,
                    '2026-11-20T05:00:00+00:00')""")
                value = db.execute("SELECT selected_ltp FROM "
                    "auto_banknifty_depth_selections WHERE identity='NSE_FNO:100'"
                ).fetchone()[0]
                self.assertIsNone(value)

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
