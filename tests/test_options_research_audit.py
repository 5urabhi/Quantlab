"""Offline tests for real signal-transition accounting and honest RL data gates."""
from datetime import datetime, timedelta, timezone
import unittest

from workstation_api import options_research_audit as audit

START = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)
DAY = "2026-11-18"


def stamp(i):
    return (START + timedelta(minutes=i)).isoformat()


def index_rows(length=70):
    return [{"session_ist": DAY, "timestamp_utc": stamp(i),
             "close": 62000 + i} for i in range(length)]


def events(*signals):
    return [{"session_ist": DAY, "bar_utc": stamp(i), "direction": direction}
            for i, direction in signals]


def option_quotes(length=70, sides=("CALL", "PUT")):
    quotes = {}
    for i in range(length):
        for side in sides:
            quotes[(stamp(i), side)] = {62000.: {
                "session_ist": DAY, "strike": 62000.,
                "close": 300., "open": 300., "volume": 100,
                "side": side, "expiry_code": 1}}
    return quotes


class OptionsAuditTests(unittest.TestCase):
    def test_1043_repeated_direction_labels_do_not_count_as_reversals(self):
        all_events = events(*(
            [(i, "UP") for i in range(29, 40)]
            + [(40, "NO_TRADE"), (41, "DOWN"), (42, "DOWN"),
               (43, "NO_TRADE"), (44, "UP")]))
        summary = audit.audit(
            all_events, index_rows(), option_quotes(),
            selected={"trade_count": 2}, target_ltp=300, tolerance=50)
        self.assertEqual(summary["directional_signal_bars"], 14)
        self.assertEqual(summary["same_direction_repeat_bars"], 11)
        self.assertEqual(summary["within_session_direction_changes"], 2)
        self.assertEqual(summary["direction_runs"], 3)
        self.assertEqual(summary["signal_bars_with_next_option_open"], 14)
        self.assertEqual(summary["observed_sessions"], 1)
        self.assertFalse(summary["research_grade_rl_ready"])
        self.assertFalse(summary["training_performed"])
        self.assertEqual(summary["status"], "MORE_HISTORY_REQUIRED")

    def test_missing_put_or_next_open_is_not_counted_as_available(self):
        quotes = option_quotes(sides=("CALL",))
        summary = audit.audit(
            events((29, "UP"), (35, "DOWN")),
            index_rows(), quotes, selected={"trade_count": 1},
            target_ltp=300, tolerance=50)
        self.assertEqual(summary["signal_bars_with_target_premium_quote"], 1)
        self.assertEqual(summary["signal_bars_with_next_option_open"], 1)
        self.assertEqual(summary["signal_bars_missing_target_premium_quote"], 1)
        self.assertEqual(summary["both_sides_coverage_pct"], 0)
        self.assertFalse(summary["planning_gates"]["research_source_coverage_gate_passed"])

    def test_absent_next_minute_is_a_missing_open_not_a_fill(self):
        quotes = option_quotes()
        quotes.pop((stamp(30), "CALL"))
        summary = audit.audit(
            events((29, "UP")), index_rows(), quotes,
            selected={}, target_ltp=300, tolerance=50)
        self.assertEqual(summary["signal_bars_with_target_premium_quote"], 1)
        self.assertEqual(summary["signal_bars_with_next_option_open"], 0)

    def test_signal_session_resets_and_does_not_create_overnight_reversal(self):
        a = index_rows()
        bstamp = (START + timedelta(days=1)).isoformat()
        b = {"session_ist": "2026-11-19", "timestamp_utc": bstamp,
             "close": 62200}
        signals = events((29, "UP"))
        signals.append({"session_ist": "2026-11-19",
                        "bar_utc": bstamp, "direction": "DOWN"})
        summary = audit.audit(
            signals, a + [b], option_quotes(),
            selected={}, target_ltp=300, tolerance=50)
        self.assertEqual(summary["observed_sessions"], 2)
        self.assertEqual(summary["within_session_direction_changes"], 0)
        self.assertEqual(summary["direction_runs"], 2)

    def test_selected_reversal_evidence_is_passthrough_and_never_training(self):
        evidence = {"opposite_signal_exits": 2,
                    "same_open_reentry_attempts": 2,
                    "completed_flips": 0,
                    "opposite_exits_without_completed_reentry": 2,
                    "rejected_reentry_reasons":
                        {"no_option_near_target_at_signal": 2}}
        result = audit.audit(
            events((29, "UP"), (35, "DOWN")),
            index_rows(), option_quotes(),
            selected={"trade_count": 1, "reversal_audit": evidence},
            target_ltp=300, tolerance=50)
        self.assertEqual(result["selected_reversal_audit"], evidence)
        self.assertFalse(result["training_performed"])
        self.assertIn("250", " ".join(result["blockers"]))


if __name__ == "__main__":
    unittest.main()
