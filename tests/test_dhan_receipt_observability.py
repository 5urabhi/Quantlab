"""Dhan-only per-security receipt diagnostics: never fabricate or relax books.

All fixtures are synthetic and do not represent a real broker entitlement.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import struct
from unittest import TestCase
from unittest.mock import patch

from workstation_api import auto_option_depth as auto


NOW = datetime(2026, 11, 23, 4, 34, tzinfo=timezone.utc)


def _ts(seconds: float) -> str:
    return (NOW - timedelta(seconds=seconds)).isoformat()


def _contract(number: int) -> dict:
    return {
        "identity": "NSE_FNO:" + str(number),
        "security_id": str(number), "side": "CE", "strike": 63400.,
        "expiry": "2026-11-23", "lot_size": 30,
        "coverage_role": "core", "wing": "atm",
    }


class DhanSideReceiptObservabilityTests(TestCase):
    def test_decoder_reports_original_bid_and_ask_halves_without_faking_book(self):
        contract = _contract(62539)
        chosen = {"62539": contract}
        sides = {}
        counts = {}
        frames = [
            {"segment_code": 2, "security_id": "62539", "side": "bid"},
        ]
        with patch.object(auto.market_depth, "packet_stream", return_value=frames):
            accepted = auto._paired_books(
                b"binary", chosen, {}, NOW,
                observed_sides=sides, diagnostics=counts)
        self.assertEqual(accepted, [])
        self.assertEqual(sides, {contract["identity"]: {"bid"}})
        self.assertEqual(counts, {})

    def test_decoder_reports_rejected_pair_without_claiming_accepted(self):
        contract = _contract(62539)
        chosen = {"62539": contract}
        frames = [
            {"segment_code": 2, "security_id": "62539", "side": "bid"},
            {"segment_code": 2, "security_id": "62539", "side": "ask"},
        ]
        observations, counts = {}, {}
        with patch.object(auto.market_depth, "packet_stream", return_value=frames), \
             patch.object(auto.market_depth, "_snapshot",
                          side_effect=ValueError("invalid crossed depth")):
            accepted = auto._paired_books(
                b"binary", chosen, {}, NOW,
                observed_sides=observations, diagnostics=counts)
        self.assertEqual(accepted, [])
        self.assertEqual(observations, {contract["identity"]: {"bid", "ask"}})
        self.assertEqual(counts["rejected_book_pair_count"], 1)

    def test_decoder_detects_aged_half_book_but_never_joins_stale_sides(self):
        contract = _contract(62539)
        chosen = {"62539": contract}
        pending = {}
        with patch.object(auto.market_depth, "packet_stream", return_value=[
            {"segment_code": 2, "security_id": "62539", "side": "bid"}]):
            self.assertEqual(auto._paired_books(
                b"bid", chosen, pending, NOW), [])
        time_after = NOW + timedelta(seconds=2)
        counts = {}
        with patch.object(auto.market_depth, "packet_stream", return_value=[
            {"segment_code": 2, "security_id": "62539", "side": "ask"}]):
            accepted = auto._paired_books(
                b"ask", chosen, pending, time_after,
                diagnostics=counts)
        self.assertEqual(accepted, [])
        self.assertEqual(counts["unpaired_time_window_count"], 1)

    def test_bad_binary_frame_reports_count_without_accepting_fake_packets(self):
        with patch.object(auto.market_depth, "packet_stream",
                          side_effect=ValueError("truncated market frame")):
            diagnostics = {}
            accepted = auto._paired_books(
                b"broken", {"62539": _contract(62539)}, {}, NOW,
                diagnostics=diagnostics)
        self.assertEqual(accepted, [])
        self.assertEqual(diagnostics["rejected_frame_count"], 1)
        self.assertEqual(diagnostics["truncated_or_wrong_size_frames"], 1)

    def test_depth_disconnect_control_is_classified_not_a_fake_book(self):
        contract = _contract(62539)
        chosen = {"62539": contract}
        control = struct.pack("<hBBiI", 12, 50, 2, 62539, 805)
        with patch.object(auto.market_depth, "packet_stream",
                          side_effect=ValueError(
                              "Not a bid/ask full-depth binary packet")):
            diagnostics = {}
            accepted = auto._paired_books(
                control, chosen, {}, NOW, diagnostics=diagnostics)
        self.assertEqual(accepted, [])
        self.assertEqual(diagnostics["rejected_frame_count"], 1)
        self.assertEqual(diagnostics["disconnect_or_control_frames"], 1)
        self.assertNotIn("805", str(diagnostics))

    def test_status_explains_each_missing_book_reason_and_socket_coverage(self):
        contracts = [_contract(62539+i) for i in range(7)]
        source = {
            "state": "recording_original_depth", "connected": True,
            "contracts": contracts, "latest": {
                contracts[0]["identity"]: {
                    "received_utc": _ts(32), "best_bid": 300.,
                    "best_ask": 301.},
            },
            "observed_by_contract": {
                contracts[0]["identity"]: _ts(1),
                contracts[4]["identity"]: _ts(4),
            },
            "observed_sides_by_contract": {
                contracts[0]["identity"]: {"bid": _ts(1), "ask": _ts(1)},
                contracts[1]["identity"]: {"bid": _ts(2)},
                contracts[2]["identity"]: {"ask": _ts(2)},
                contracts[3]["identity"]: {"bid": _ts(2), "ask": _ts(3)},
                contracts[4]["identity"]: {"bid": _ts(4), "ask": _ts(4)},
                contracts[5]["identity"]: {"bid": _ts(120), "ask": _ts(110)},
            },
            "connected_socket_indices": [0],
            "socket_last_paired_utc": {"0": _ts(1)},
            "depth_parser_diagnostics": {
                "rejected_frame_count": 2,
                "unpaired_time_window_count": 3,
                "rejected_book_pair_count": 4,
            },
        }
        cfg = {**auto.DEFAULTS, "enabled": True}
        with patch.object(auto, "STATE", source), \
             patch.object(auto, "_config", return_value=cfg), \
             patch.object(auto, "_now", return_value=NOW), \
             patch.object(auto, "_market_open", return_value=True):
            status = auto.status()
        receipts = status["contract_receipts"]
        keys = [c["identity"] for c in contracts]
        self.assertEqual(receipts[keys[0]]["status"], "valid_book_saved")
        self.assertEqual(receipts[keys[1]]["status"], "bid_only")
        self.assertEqual(receipts[keys[2]]["status"], "ask_only")
        self.assertEqual(receipts[keys[3]]["status"], "bid_ask_seen_no_valid_pair")
        self.assertEqual(receipts[keys[4]]["status"], "valid_pair_not_yet_saved")
        self.assertEqual(receipts[keys[5]]["status"], "no_decoded_depth_yet")
        self.assertEqual(receipts[keys[6]]["status"], "no_decoded_depth_yet")
        self.assertEqual(status["active_contracts_with_no_valid_pairs_60s"], 5)
        self.assertEqual(status["contracts_with_recent_packets"], 2)
        self.assertEqual(status["contracts_with_saved_books"], 1)
        self.assertEqual(status["socket_health"], [{
            "socket": 1, "connected": True, "subscribed": 7,
            "with_recent_pairs_60s": 2,
            "with_recent_bids_60s": 4, "with_recent_asks_60s": 4}])
        self.assertEqual(status["depth_parser_diagnostics"]["rejected_frame_count"], 2)
        self.assertNotIn("observed_by_contract", status)
        self.assertNotIn("observed_sides_by_contract", status)
        self.assertNotIn("socket_last_paired_utc", status)
        self.assertNotIn("connected_socket_indices", status)
        self.assertNotIn("trading_password", str(status))

    def test_legacy_small_subscription_status_unchanged(self):
        contract = _contract(62539)
        cfg = {**auto.DEFAULTS, "selection_mode": "premium"}
        with patch.object(auto, "STATE", {
            "contracts": [contract], "latest": {}, "connected": False,
        }), patch.object(auto, "_config", return_value=cfg), \
             patch.object(auto, "_market_open", return_value=False):
            status = auto.status()
        self.assertNotIn("contract_receipts", status)
        self.assertNotIn("socket_health", status)
