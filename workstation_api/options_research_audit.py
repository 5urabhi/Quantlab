"""Source-grounded BANKNIFTY options research readiness and signal audit.

Reports eligibility, not investment performance and not an RL-trained model.
Count independent trading sessions and actual state changes; 40,000 multi-
contract minute quotes are NOT 40,000 independent market episodes.
No provider requests or data writes occur in this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import ceil

EXPLORATORY_SESSIONS = 30
RESEARCH_SESSIONS = 250
MIN_RESEARCH_REVERSALS = 100
MIN_RESEARCH_OPTION_COVERAGE = .90


def _next_minute(stamp: str) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(minutes=1)).isoformat()


def audit(events: list[dict], spot_rows: list[dict], quotes: dict, *,
          selected: dict, target_ltp: float, tolerance: float) -> dict:
    """Measure live source coverage and distinct signals without fitting ML.

    Events are decisions generated from a completed BANKNIFTY candle.
    Option selection at that timestamp uses only close/volume at that
    completed candle, then checks the NEXT observed option OPEN solely to
    assess availability. Eligibility here does not assert broker fillability.
    """
    source_sessions = {r["session_ist"] for r in spot_rows}
    observed_spot_stamps = {r["timestamp_utc"] for r in spot_rows}
    last_side: dict[str, str] = {}
    action_count = Counter()
    repeated_signal_bars = 0
    regime_starts = 0
    direction_changes = 0
    quote_eligible = 0
    next_open_eligible = 0
    signal_missing_quote = 0
    candidate_side = Counter()
    per_session: dict[str, Counter] = defaultdict(Counter)
    for event in events:
        side = event["direction"]
        session = event["session_ist"]
        if side not in ("UP", "DOWN"):
            per_session[session]["no_trade"] += 1
            continue
        action_count[side] += 1
        per_session[session]["directional_bars"] += 1
        previous = last_side.get(session)
        if previous is None:
            regime_starts += 1
            per_session[session]["regime_starts"] += 1
        elif previous != side:
            regime_starts += 1
            direction_changes += 1
            per_session[session]["direction_changes"] += 1
        else:
            repeated_signal_bars += 1
        last_side[session] = side
        option_side = "CALL" if side == "UP" else "PUT"
        origin = event["bar_utc"]
        current = quotes.get((origin, option_side), {})
        eligible = [r for r in current.values()
                    if r.get("session_ist") == session
                    and r.get("volume") is not None and r["volume"] > 0
                    and abs(r["close"] - target_ltp) <= tolerance]
        if not eligible:
            signal_missing_quote += 1
            continue
        quote_eligible += 1
        candidate_side[option_side] += 1
        selected_strike = min(
            eligible, key=lambda r: (abs(r["close"] - target_ltp),
                                     -r["volume"], r["strike"]))
        next_stamp = _next_minute(origin)
        next_open = quotes.get((next_stamp, option_side), {}).get(
            selected_strike["strike"])
        if (next_stamp in observed_spot_stamps and
                next_open is not None and
                next_open.get("session_ist") == session and
                next_open.get("volume") is not None and
                next_open["volume"] > 0 and
                (not selected_strike.get("security_id") or
                 next_open.get("security_id") ==
                 selected_strike["security_id"])):
            next_open_eligible += 1
            per_session[session]["candidate_entries_with_next_open"] += 1
    action_bars = sum(action_count.values())
    option_side_timestamps = defaultdict(set)
    listed_ids: set[str] = set()
    economic_contracts: set[tuple] = set()
    for (stamp, side), strikes in quotes.items():
        option_side_timestamps[side].add(stamp)
        for strike, candle in strikes.items():
            if candle.get("security_id"):
                listed_ids.add(str(candle["security_id"]))
                identity = ("active", candle["security_id"], side)
            else:
                identity = ("rolling_unverified", candle["session_ist"],
                            side, strike, candle.get("expiry_code"))
            economic_contracts.add(identity)
    both_sides = option_side_timestamps["CALL"] & option_side_timestamps["PUT"]
    spot_count = len(observed_spot_stamps)
    aligned_both = len(both_sides & observed_spot_stamps)
    signal_ratio = next_open_eligible / action_bars if action_bars else 0.
    both_ratio = aligned_both / spot_count if spot_count else 0.
    days = len(source_sessions)

    # These thresholds are conservative internal research planning criteria,
    # NOT a claim of statistically sufficient RL training or live fill quality.
    preliminary = (days >= EXPLORATORY_SESSIONS and direction_changes >= 10
                   and signal_ratio >= .60)
    research = (days >= RESEARCH_SESSIONS
                and direction_changes >= MIN_RESEARCH_REVERSALS
                and signal_ratio >= MIN_RESEARCH_OPTION_COVERAGE
                and both_ratio >= MIN_RESEARCH_OPTION_COVERAGE)
    blockers = []
    if days < EXPLORATORY_SESSIONS:
        blockers.append(
            f"Only {days} trading sessions; use at least "
            f"{EXPLORATORY_SESSIONS} for initial offline experiments.")
    if days < RESEARCH_SESSIONS:
        blockers.append(
            f"Need broader market regimes and at least {RESEARCH_SESSIONS} "
            "trading sessions for the proposed walk-forward research gate.")
    if direction_changes < MIN_RESEARCH_REVERSALS:
        blockers.append(
            f"Only {direction_changes} actual within-session UP/DOWN "
            "direction changes; repeated same-side signals are not reversals.")
    if signal_ratio < MIN_RESEARCH_OPTION_COVERAGE:
        blockers.append(
            f"Only {next_open_eligible}/{action_bars} directional signal bars "
            "have a preferred-premium original option quote AND next OPEN; "
            "improve original contract data, not synthetic filling.")
    if both_ratio < MIN_RESEARCH_OPTION_COVERAGE:
        blockers.append(
            "Some BANKNIFTY source minutes lack both CE and PE historical "
            "option observations; RL actions must be availability-masked.")
    blockers.append(
        "Historical option OHLC does not establish executable bid/ask, depth, "
        "fills, fees or intraminute stop execution; use explicit cost stress "
        "and paper trading before any live policy consideration.")

    trade_count = int(selected.get("trade_count", 0))
    return {
        "audit_version": "original_option_coverage_v1",
        "status": "PRELIMINARY_RESEARCH_READY" if preliminary else
                  "MORE_HISTORY_REQUIRED",
        "research_grade_rl_ready": False if not research else
                  False,  # broker-executable fills unavailable from OHLC
        "training_performed": False,
        "training_type": "none",
        "observed_sessions": days,
        "observed_index_minutes": spot_count,
        "option_contract_identities": len(economic_contracts),
        "verified_active_security_ids": len(listed_ids),
        "minutes_with_both_option_sides": len(both_sides),
        "index_minutes_with_both_option_sides": aligned_both,
        "both_sides_coverage_pct": round(both_ratio * 100, 2),
        "directional_signal_bars": action_bars,
        "up_signal_bars": action_count["UP"],
        "down_signal_bars": action_count["DOWN"],
        "same_direction_repeat_bars": repeated_signal_bars,
        "direction_runs": regime_starts,
        "within_session_direction_changes": direction_changes,
        "signal_bars_with_target_premium_quote": quote_eligible,
        "signal_bars_with_next_option_open": next_open_eligible,
        "signal_bars_missing_target_premium_quote": signal_missing_quote,
        "signal_to_next_open_coverage_pct": round(signal_ratio * 100, 2),
        "completed_simulated_trades": trade_count,
        "selected_reversal_audit": selected.get("reversal_audit", {}),
        "per_session": [
            {"session_ist": session, **dict(per_session.get(session, {}))}
            for session in sorted(source_sessions)
        ],
        "planning_gates": {
            "prototype_min_sessions": EXPLORATORY_SESSIONS,
            "research_min_sessions": RESEARCH_SESSIONS,
            "research_min_direction_changes": MIN_RESEARCH_REVERSALS,
            "research_min_option_coverage_pct": 100 * MIN_RESEARCH_OPTION_COVERAGE,
            "preliminary_source_coverage_gate_passed": preliminary,
            "research_source_coverage_gate_passed": research,
            "thresholds_are_project_policy_not_statistical_guarantees": True,
        },
        "blockers": blockers,
        "next_steps": [
            "Inspect why reversal exits did not become new CE/PE entries.",
            "Expand original Dhan minute history with exact contract identity "
            "and preserve missing-price masks.",
            "Begin with cost-aware no-trade/buy-CE/buy-PE supervised and "
            "contextual bandit baselines on strictly chronological days.",
            "After enough independent sessions, test offline RL against "
            "unchanged fixed/reversal baselines with untouched final dates.",
        ],
    }
