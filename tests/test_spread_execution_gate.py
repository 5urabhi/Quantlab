"""Proof the strict shared spread gate does NOT confuse quotes with profit.

All fixtures are fabricated unit-test inputs. No Dhan or Zerodha connections.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from workstation_api import (
    live_market, service, spread_execution_gate as gate)


def recent_receipt():
    return {
        "packet_receipts_120s": 5,
        "distinct_packet_pairs_120s": 4,
        "receipt_span_seconds": 42.,
        "last_receipt_utc": "2026-11-23T08:02:00+00:00",
        "history_is_verified_fills": False,
    }


def recent_trade():
    return {
        "source_distinct_exchange_trade_times": 3,
        "observed_quote_packets_with_recent_trade": 4,
        "cumulative_volume_delta_units": 90,
        "last_quote_receive_utc": "2026-11-23T08:02:00+00:00",
        "user_order_fills_observed": False,
        "full_exchange_trade_tape_available": False,
    }


def capture_row(**updates):
    row = {
        "expiry": "2026-12-01",
        "best_bid": 200., "best_ask": 205.,
        "spread_bps": 246., "lot_size": 30,
        "best_hypothetical_lots": 1,
        "top_bid_quantity": 120, "top_ask_quantity": 120,
        "saved_book_age_seconds": 3.,
        "fresh_original_saved_book": True,
        "required_capital_inr": 6055.,
        "passive_stressed_upper_net_inr": 70.,
        "failed_exit_net_inr": -80.,
    }
    row.update(updates)
    return row


def multileg_candidate(**updates):
    row = {
        "source_age_seconds": 2., "fresh_reference": True,
        "quote_skew_seconds": 0.5, "lots": 1, "units": 30,
        "max_loss_inr": 2000., "max_profit_inr": 700.,
        "estimated_same_book_immediate_roundtrip_net_inr": -120.,
    }
    row.update(updates)
    return row


def legs():
    return [
        {"identity": "NSE_FNO:1001", "bid": 150., "ask": 152.,
         "spread_bps": 132., "bid_top_quantity": 120,
         "ask_top_quantity": 120, "lot_size": 30},
        {"identity": "NSE_FNO:1002", "bid": 105., "ask": 107.,
         "spread_bps": 189., "bid_top_quantity": 120,
         "ask_top_quantity": 120, "lot_size": 30},
    ]


class SpreadExecutionGateTests(TestCase):
    def test_penny_wide_option_from_screenshot_never_gets_green_light(self):
        sample = capture_row(
            best_bid=1.50, best_ask=2.70, spread_bps=5714.,
            best_hypothetical_lots=10,
            required_capital_inr=473.79,
            passive_stressed_upper_net_inr=309.70,
            failed_exit_net_inr=-50.78)
        verdict = gate.capture_feasibility(
            sample, capital_inr=50000, receipt=recent_receipt(),
            trade=recent_trade())
        self.assertFalse(verdict["paper_research_qualified"])
        self.assertFalse(verdict["live_order_approved"])
        self.assertEqual(verdict["trade_action"], "NO_TRADE")
        self.assertIn("PENNY_OPTION_PREMIUM", verdict["reasons"])
        self.assertIn("EXCESSIVE_RELATIVE_SPREAD", verdict["reasons"])
        self.assertEqual(verdict["loss_if_option_worthless_inr"], -473.79)
        self.assertAlmostEqual(
            verdict["conservative_sell_fill_hurdle_if_zero_recovery"],
            473.79/(473.79+309.70), places=5)
        self.assertIsNone(verdict["calibrated_profit_probability"])
        self.assertIsNone(verdict["expected_net_profit_inr"])

    def test_well_formed_depth_still_only_qualifies_for_paper_study(self):
        verdict = gate.capture_feasibility(
            capture_row(), capital_inr=50000, receipt=recent_receipt(),
            trade=recent_trade())
        self.assertTrue(verdict["paper_research_qualified"])
        self.assertEqual(verdict["reasons"], [])
        self.assertIsNotNone(verdict["research_priority_score"])
        self.assertGreater(verdict[
            "conservative_sell_fill_hurdle_if_zero_recovery"], 0.9)
        self.assertEqual(verdict["trade_action"], "NO_TRADE")
        summary = gate.decision_summary([{"feasibility": verdict}])
        self.assertEqual(summary["live_action"], "NO_TRADE")
        self.assertEqual(summary["research_status"], "PAPER_TEST_CANDIDATES")
        self.assertEqual(summary["paper_research_candidates"], 1)
        self.assertIsNone(summary["expected_net_profit_inr"])
        self.assertIsNone(summary["calibrated_fill_probability"])

    def test_capture_rejects_stale_thin_single_snapshot_and_risk_budget(self):
        verdict = gate.capture_feasibility(capture_row(
            saved_book_age_seconds=21., top_bid_quantity=35,
            required_capital_inr=18000.),
            capital_inr=50000,
            receipt={"packet_receipts_120s": 1,
                     "distinct_packet_pairs_120s": 1,
                     "receipt_span_seconds": 0},
            trade=recent_trade())
        self.assertFalse(verdict["paper_research_qualified"])
        for reason in (
            "STALE_OR_HISTORICAL_QUOTE",
            "TOP_OF_BOOK_DEPTH_TOO_THIN",
            "FULL_PREMIUM_LOSS_EXCEEDS_RISK_BUDGET",
            "TOO_FEW_SAVED_PACKETS",
            "NO_DISTINCT_BOOK_UPDATES",
            "TOO_SHORT_OBSERVATION_WINDOW",
        ):
            self.assertIn(reason, verdict["reasons"])

    def test_missing_book_stays_blocked_not_pseudo_zero_fee(self):
        verdict = gate.capture_feasibility(capture_row(
            best_hypothetical_lots=None, required_capital_inr=None,
            passive_stressed_upper_net_inr=None,
            failed_exit_net_inr=None), capital_inr=50000, receipt=None)
        self.assertEqual(verdict["trade_action"], "NO_TRADE")
        self.assertIn("NO_AFFORDABLE_FULL_DEPTH_LOT", verdict["reasons"])
        self.assertIn("MISSING_RECENT_DEPTH_SEQUENCE", verdict["reasons"])
        self.assertIsNone(verdict["loss_if_option_worthless_inr"])

    def test_multileg_uses_same_depth_and_risk_gate(self):
        samples = legs()
        observed = {b["identity"]: recent_receipt() for b in samples}
        trades = {b["identity"]: recent_trade() for b in samples}
        passed = gate.multileg_feasibility(
            multileg_candidate(), books=samples, capital_inr=50000,
            receipts=observed, trades=trades)
        self.assertTrue(passed["paper_research_qualified"])
        self.assertEqual(passed["trade_action"], "NO_TRADE")
        self.assertFalse(passed["broker_margin_verified"])
        self.assertIsNone(passed["required_broker_margin_inr"])
        self.assertIsNone(passed["expected_net_profit_inr"])
        bad = [{**samples[0], "bid": 1.5, "spread_bps": 9000.,
                "bid_top_quantity": 5}, samples[1]]
        failed = gate.multileg_feasibility(
            multileg_candidate(max_loss_inr=20000.,
                               quote_skew_seconds=9.),
            books=bad, capital_inr=50000, receipts=observed,
            trades=trades)
        self.assertFalse(failed["paper_research_qualified"])
        for reason in ("PENNY_OPTION_LEG",
                       "EXCESSIVE_RELATIVE_LEG_SPREAD",
                       "INSUFFICIENT_TOP_LEVEL_LEG_LIQUIDITY",
                       "LEGS_NOT_SUFFICIENTLY_SYNCHRONIZED",
                       "MAX_TERMINAL_LOSS_EXCEEDS_RISK_BUDGET"):
            self.assertIn(reason, failed["reasons"])

    def test_no_trade_if_all_candidates_blocked(self):
        sample = gate.capture_feasibility(
            capture_row(best_bid=1.,spread_bps=8000.),
            capital_inr=50000, receipt=recent_receipt(),
            trade=recent_trade())
        decision = gate.decision_summary([{"feasibility": sample}])
        self.assertEqual(decision["live_action"], "NO_TRADE")
        self.assertEqual(decision["research_status"],
                         "NO_QUALIFIED_CANDIDATES")
        self.assertEqual(decision["paper_research_candidates"], 0)
        self.assertGreater(decision["rejection_reason_counts"][
            "PENNY_OPTION_PREMIUM"], 0)

    def test_recent_depth_packets_are_bounded_by_asof_receive_clock(self):
        temp = TemporaryDirectory(prefix="quantlab_spread_gate_")
        self.addCleanup(temp.cleanup)
        p = patch.object(service, "DATA", Path(temp.name)/"data")
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(live_market, "DB_INITIALIZED", False)
        p.start()
        self.addCleanup(p.stop)
        now = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        live_market._init_db()
        with live_market._database() as db:
            db.executemany(
                """INSERT INTO live_depth_books
                   (identity,received_utc,session_id,book_json,packet_pair_sha256)
                   VALUES(?,?,?,?,?)""",
                [("NSE_FNO:1999",
                  (now-timedelta(seconds=delta)).isoformat(),
                  "synthetic_test", "{}", "sha"+str(i))
                 for i, delta in enumerate((50, 35, 20))]
                + [("NSE_FNO:2999",
                    (now-timedelta(seconds=1000)).isoformat(),
                    "synthetic_test", "{}", "old")])
        with live_market._database() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS dhan_option_live_events(
              identity TEXT, received_utc TEXT, exchange_trade_utc TEXT,
              kind TEXT, volume INTEGER
            )""")
            db.executemany(
                """INSERT INTO dhan_option_live_events
                   (identity,received_utc,exchange_trade_utc,kind,volume)
                   VALUES(?,?,?,?,?)""",
                [("NSE_FNO:1999",
                  (now-timedelta(seconds=delta)).isoformat(),
                  (now-timedelta(seconds=delta+1)).isoformat(),
                  "quote", 1000+30*i)
                 for i, delta in enumerate((50, 35, 20))])
        activity = gate.recent_depth_receipts(
            day="2026-11-23", now=now, window_seconds=120)
        self.assertEqual(activity["NSE_FNO:1999"][
            "packet_receipts_120s"], 3)
        self.assertGreaterEqual(activity["NSE_FNO:1999"][
            "receipt_span_seconds"], 30)
        self.assertEqual(activity["NSE_FNO:1999"][
            "distinct_packet_pairs_120s"], 3)
        self.assertNotIn("NSE_FNO:2999", activity)
        trades = gate.recent_trade_activity(
            day="2026-11-23", now=now, window_seconds=120)
        self.assertEqual(trades["NSE_FNO:1999"][
            "source_distinct_exchange_trade_times"], 3)
        self.assertEqual(trades["NSE_FNO:1999"][
            "cumulative_volume_delta_units"], 60)
        self.assertIs(trades["NSE_FNO:1999"]["user_order_fills_observed"], False)
        self.assertEqual(gate.recent_depth_receipts(
            day="2026-11-22", now=now), {})
        self.assertEqual(gate.recent_trade_activity(
            day="2026-11-22", now=now), {})

    def test_no_trade_when_source_trade_activity_is_missing(self):
        assessment = gate.capture_feasibility(
            capture_row(), capital_inr=50000, receipt=recent_receipt(),
            trade=None)
        self.assertFalse(assessment["paper_research_qualified"])
        self.assertIn("MISSING_FRESH_SOURCE_TRADE_ACTIVITY",
                      assessment["reasons"])
        self.assertEqual(assessment["trade_action"], "NO_TRADE")

    def test_minimum_live_volume_requires_at_least_one_verified_lot(self):
        assessment = gate.capture_feasibility(
            capture_row(), capital_inr=50000, receipt=recent_receipt(),
            trade={**recent_trade(), "cumulative_volume_delta_units": 5})
        self.assertFalse(assessment["paper_research_qualified"])
        self.assertIn("TOO_LITTLE_RECORDED_TRADE_VOLUME",
                      assessment["reasons"])
