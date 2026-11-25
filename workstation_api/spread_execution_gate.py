"""Shared, conservative spread execution-feasibility research gate.

This is a deterministic *negative screen*, NOT an execution fill model, trade
recommendation, calibrated probability, trading signal or expected-return model.
Only original saved Dhan 20-level depth can enter either spread engine.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from math import isfinite
import sqlite3

from . import live_market, liquidity_spreads as spreads


CAPTURE_POLICY = {
    "max_age_seconds": 8.0,
    "min_bid_inr": 20.0,
    "max_relative_spread_bps": 250.0,
    "minimum_top_depth_multiple": 2.0,
    "max_loss_to_zero_fraction_of_budget": 0.25,
    "min_receipts": 3,
    "min_distinct_packets": 2,
    "min_receipt_span_seconds": 15.0,
    "receipt_window_seconds": 120,
    "min_source_trade_times": 2,
    "min_volume_increase_lots": 1.0,
}
MULTILEG_POLICY = {
    "max_age_seconds": 8.0,
    "min_leg_bid_inr": 5.0,
    "max_leg_relative_spread_bps": 1000.0,
    "minimum_top_depth_multiple": 2.0,
    "max_theoretical_loss_fraction_of_budget": 0.25,
    "max_entry_crossing_drag_to_terminal_max_gain": 0.50,
    "max_leg_quote_skew_seconds": 2.0,
    "min_source_trade_times": 2,
    "min_volume_increase_lots": 1.0,
    "min_receipts": 3,
    "min_distinct_packets": 2,
    "min_receipt_span_seconds": 15.0,
    "receipt_window_seconds": 120,
}
POLICY_VERSION = "spread_feasibility_source_gate_v1"


def recent_depth_receipts(*, day: str | None,
                          now: datetime | None = None,
                          window_seconds: int = 120) -> dict[str, dict]:
    """A single bounded GROUP BY query; does not interrupt Dhan recording.

    Counts distinct saved local-receive packets, *not* exchange trade prints.
    Historical/day-mismatched observations are never promoted to live status.
    """
    if (not isinstance(window_seconds, int) or
            not 30 <= window_seconds <= 600):
        raise ValueError("Window must be 30–600 seconds")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Clock must be timezone aware")
    chosen, _, _ = spreads._day_bounds(day)
    if chosen != now.astimezone(spreads.IST).date().isoformat():
        return {}
    start = (now - timedelta(seconds=window_seconds)).isoformat()
    stop = now.isoformat()
    live_market._init_db()
    with live_market._database() as db:
        rows = db.execute(
            """SELECT identity, COUNT(*) AS packets,
                      COUNT(DISTINCT packet_pair_sha256) AS distinct_packets,
                      MIN(received_utc), MAX(received_utc)
               FROM live_depth_books
               WHERE received_utc >= ? AND received_utc <= ?
               GROUP BY identity""",
            (start, stop)).fetchall()
    observed = {}
    for identity, count, distinct, first, last in rows:
        try:
            span = max(0.0, (datetime.fromisoformat(last) -
                             datetime.fromisoformat(first)).total_seconds())
        except (ValueError, TypeError):
            continue
        observed[identity] = {
            "packet_receipts_120s": count,
            "distinct_packet_pairs_120s": distinct,
            "receipt_span_seconds": round(span, 3),
            "last_receipt_utc": last,
            "history_is_verified_fills": False,
        }
    return observed


def recent_trade_activity(*, day: str | None,
                          now: datetime | None = None,
                          window_seconds: int = 120) -> dict[str, dict]:
    """Aggregate *other participants'* fresh Dhan exchange-trade observations.

    Original Dhan quote events include cumulative session volume and the
    exchange's last-trade timestamp. They are NOT order fills for our user,
    queue statistics, or a matched trade tape. Missing table/feed is a
    blocked evidence state, never synthetic volume.
    """
    if not isinstance(window_seconds, int) or not 30 <= window_seconds <= 600:
        raise ValueError("Trade window must be 30–600 seconds")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Clock must be timezone aware")
    chosen, _, _ = spreads._day_bounds(day)
    if chosen != now.astimezone(spreads.IST).date().isoformat():
        return {}
    cutoff = (now - timedelta(seconds=window_seconds)).isoformat()
    live_market._init_db()
    try:
        with live_market._database() as db:
            rows = db.execute(
                """WITH observed AS (
                     SELECT identity, received_utc, exchange_trade_utc, volume,
                            LAG(volume) OVER (
                              PARTITION BY identity
                              ORDER BY exchange_trade_utc, received_utc
                            ) AS previous_volume
                     FROM dhan_option_live_events
                     WHERE kind = 'quote' AND received_utc >= ?
                       AND received_utc <= ?
                       AND exchange_trade_utc >= ?
                       AND exchange_trade_utc <= ?
                       AND volume IS NOT NULL AND volume >= 0
                   )
                   SELECT identity, COUNT(DISTINCT exchange_trade_utc), COUNT(*),
                          CASE WHEN MAX(CASE WHEN volume < previous_volume
                                             THEN 1 ELSE 0 END) = 1
                               THEN 0 ELSE MAX(volume) - MIN(volume) END,
                          MAX(received_utc)
                   FROM observed GROUP BY identity""",
                (cutoff, now.isoformat(), cutoff, now.isoformat())).fetchall()
    except sqlite3.OperationalError:
        # The optional full options Quote/OI feed may never have been armed.
        return {}
    return {
        identity: {
            "source_distinct_exchange_trade_times": max(0, ticks or 0),
            "observed_quote_packets_with_recent_trade": count,
            "cumulative_volume_delta_units": max(0, volume_change or 0),
            "last_quote_receive_utc": last,
            "user_order_fills_observed": False,
            "full_exchange_trade_tape_available": False,
        }
        for identity, ticks, count, volume_change, last in rows
    }


def _trade_reasons(trade: dict | None, lot_size: int, policy: dict) -> list[str]:
    if trade is None:
        return ["MISSING_FRESH_SOURCE_TRADE_ACTIVITY"]
    reasons = []
    if trade.get("source_distinct_exchange_trade_times", 0) < policy[
            "min_source_trade_times"]:
        reasons.append("TOO_FEW_DISTINCT_SOURCE_TRADE_TIMES")
    minimum_units = max(1, lot_size) * policy["min_volume_increase_lots"]
    if trade.get("cumulative_volume_delta_units", 0) < minimum_units:
        reasons.append("TOO_LITTLE_RECORDED_TRADE_VOLUME")
    return reasons


def _receipt_reasons(receipt: dict | None, policy: dict) -> list[str]:
    if receipt is None:
        return ["MISSING_RECENT_DEPTH_SEQUENCE"]
    reasons = []
    if receipt.get("packet_receipts_120s", 0) < policy["min_receipts"]:
        reasons.append("TOO_FEW_SAVED_PACKETS")
    if receipt.get("distinct_packet_pairs_120s", 0) < policy["min_distinct_packets"]:
        reasons.append("NO_DISTINCT_BOOK_UPDATES")
    if receipt.get("receipt_span_seconds", 0) < policy["min_receipt_span_seconds"]:
        reasons.append("TOO_SHORT_OBSERVATION_WINDOW")
    return reasons


def _safe_positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        isfinite(value) and value > 0)


def capture_feasibility(row: dict, *, capital_inr: float,
                        receipt: dict | None,
                        trade: dict | None = None,
                        policy: dict | None = None) -> dict:
    """Exclude penny/illiquid/stale/liquidity-poor quotes from top choices.

    Full premium cash debit is explicitly the loss-to-zero exposure of a
    long option; previous small adverse-move haircut is not maximum loss.
    """
    policy = CAPTURE_POLICY if policy is None else policy
    reasons = []
    age = row.get("saved_book_age_seconds")
    if (not isinstance(age, (float, int)) or
            not 0 <= age <= policy["max_age_seconds"] or
            not row.get("fresh_original_saved_book")):
        reasons.append("STALE_OR_HISTORICAL_QUOTE")
    expiry = row.get("expiry")
    if not isinstance(expiry, str):
        reasons.append("UNKNOWN_EXPIRY")
    elif expiry < datetime.now(timezone.utc).astimezone(spreads.IST).date().isoformat():
        reasons.append("EXPIRED_CONTRACT")
    if row.get("best_hypothetical_lots") is None:
        reasons.append("NO_AFFORDABLE_FULL_DEPTH_LOT")
    if not _safe_positive(row.get("best_bid")) or row["best_bid"] < policy["min_bid_inr"]:
        reasons.append("PENNY_OPTION_PREMIUM")
    if not _safe_positive(row.get("spread_bps")) or (
            row["spread_bps"] > policy["max_relative_spread_bps"]):
        reasons.append("EXCESSIVE_RELATIVE_SPREAD")
    lots = row.get("best_hypothetical_lots") or 0
    size = row.get("lot_size") or 0
    units = lots * size
    if (units <= 0 or
            row.get("top_bid_quantity", 0) < policy["minimum_top_depth_multiple"] * units
            or row.get("top_ask_quantity", 0) <
            policy["minimum_top_depth_multiple"] * units):
        reasons.append("TOP_OF_BOOK_DEPTH_TOO_THIN")
    entry_debit = row.get("required_capital_inr")
    if not _safe_positive(entry_debit):
        reasons.append("ENTRY_PREMIUM_RISK_UNKNOWN")
    elif entry_debit > capital_inr * policy["max_loss_to_zero_fraction_of_budget"]:
        reasons.append("FULL_PREMIUM_LOSS_EXCEEDS_RISK_BUDGET")
    stressed = row.get("passive_stressed_upper_net_inr")
    if not _safe_positive(stressed):
        reasons.append("NO_POSITIVE_COST_ADJUSTED_SPREAD_BOUND")
    if row.get("failed_exit_net_inr") is None:
        reasons.append("NO_RECORDED_FORCED_EXIT_DEPTH")
    reasons.extend(_receipt_reasons(receipt, policy))
    reasons.extend(_trade_reasons(trade, row.get("lot_size") or 0, policy))
    qualified = not reasons
    conservative_hurdle = None
    if _safe_positive(entry_debit) and _safe_positive(stressed):
        # If the option becomes worthless after entry, cash debit is lost.
        # This is NOT a calibrated event probability, only a stress ratio.
        conservative_hurdle = round(
            entry_debit / (entry_debit + stressed), 6)
    score = None
    if qualified:
        upper_per_debit = stressed / max(1., entry_debit)
        depth_multiple = min(
            row["top_bid_quantity"], row["top_ask_quantity"]) / units
        score = round(min(100., max(0.,
            25 * (1. - row["spread_bps"] / policy["max_relative_spread_bps"]) +
            25 * min(1., depth_multiple / 5.) +
            20 * min(1., receipt["packet_receipts_120s"] / 8.) +
            20 * min(1., upper_per_debit * 50.) +
            10 * (1. - conservative_hurdle))), 2)
    return {
        "policy_version": POLICY_VERSION,
        "engine": "BID_ASK_CAPTURE",
        "paper_research_qualified": qualified,
        "live_order_approved": False,
        "trade_action": "NO_TRADE",
        "status": "PAPER_RESEARCH_ONLY" if qualified else "REJECTED_BY_EXECUTION_GATE",
        "reasons": reasons,
        "research_priority_score": score,
        "loss_if_option_worthless_inr": (
            spreads._money(-entry_debit) if _safe_positive(entry_debit) else None),
        "conservative_sell_fill_hurdle_if_zero_recovery": conservative_hurdle,
        "assumed_sell_fill_probability": None,
        "calibrated_profit_probability": None,
        "expected_net_profit_inr": None,
        "receipt_evidence": receipt or {
            "packet_receipts_120s": 0, "distinct_packet_pairs_120s": 0,
            "receipt_span_seconds": 0, "history_is_verified_fills": False},
        "trade_activity_evidence": trade,
        "policy": dict(policy),
    }


def multileg_feasibility(candidate: dict, *, books: list[dict],
                         capital_inr: float,
                         receipts: dict[str, dict],
                         trades: dict[str, dict] | None = None,
                         policy: dict | None = None) -> dict:
    """Same negative evidence gate for hedged multi-leg structures.

    Even qualified candidates are explicitly NOT margin-verified and
    cannot be called executable or profitable. No atomic leg fill exists.
    """
    policy = MULTILEG_POLICY if policy is None else policy
    reasons = []
    age = candidate.get("source_age_seconds")
    if (not isinstance(age, (int, float)) or not 0 <= age <=
            policy["max_age_seconds"] or
            not candidate.get("fresh_reference")):
        reasons.append("STALE_OR_HISTORICAL_LEG_QUOTE")
    if candidate.get("quote_skew_seconds", float("inf")) > policy[
            "max_leg_quote_skew_seconds"]:
        reasons.append("LEGS_NOT_SUFFICIENTLY_SYNCHRONIZED")
    lots = candidate["lots"]
    units = candidate["units"]
    spreads_bps = []
    for b in books:
        if b["bid"] < policy["min_leg_bid_inr"]:
            reasons.append("PENNY_OPTION_LEG")
        if b["spread_bps"] > policy["max_leg_relative_spread_bps"]:
            reasons.append("EXCESSIVE_RELATIVE_LEG_SPREAD")
        if (min(b["bid_top_quantity"], b["ask_top_quantity"]) <
                policy["minimum_top_depth_multiple"] * units):
            reasons.append("INSUFFICIENT_TOP_LEVEL_LEG_LIQUIDITY")
        reasons.extend(_receipt_reasons(receipts.get(b["identity"]), policy))
        reasons.extend(_trade_reasons(
            (trades or {}).get(b["identity"]), b["lot_size"], policy))
        spreads_bps.append(b["spread_bps"])
    loss = candidate.get("max_loss_inr")
    gain = candidate.get("max_profit_inr")
    if not _safe_positive(loss):
        reasons.append("UNKNOWN_TERMINAL_RISK")
    elif loss > capital_inr * policy["max_theoretical_loss_fraction_of_budget"]:
        reasons.append("MAX_TERMINAL_LOSS_EXCEEDS_RISK_BUDGET")
    if not _safe_positive(gain):
        reasons.append("NO_POSITIVE_TERMINAL_GAIN_AFTER_FEES")
    drag = -min(0., candidate["estimated_same_book_immediate_roundtrip_net_inr"])
    if _safe_positive(gain) and (
            drag > gain * policy["max_entry_crossing_drag_to_terminal_max_gain"]):
        reasons.append("ENTRY_EXIT_CROSSING_COST_TOO_LARGE")
    reasons = list(dict.fromkeys(reasons))
    qualified = not reasons
    quality_score = None
    if qualified:
        quality_score = round(min(100., max(0.,
            30 * (1 - max(spreads_bps) /
                  policy["max_leg_relative_spread_bps"]) +
            30 * min(1., gain / max(1., loss)) +
            25 * (1. - min(1., drag / gain)) +
            15 * (1. - min(1., candidate["quote_skew_seconds"] / 2.)))), 2)
    return {
        "policy_version": POLICY_VERSION,
        "engine": "MULTI_LEG_OPTIONS",
        "paper_research_qualified": qualified,
        "live_order_approved": False,
        "trade_action": "NO_TRADE",
        "status": "PAPER_RESEARCH_ONLY" if qualified else "REJECTED_BY_EXECUTION_GATE",
        "reasons": reasons,
        "research_priority_score": quality_score,
        "max_theoretical_loss_inr": loss,
        "required_broker_margin_inr": None,
        "broker_margin_verified": False,
        "calibrated_profit_probability": None,
        "expected_net_profit_inr": None,
        "receipt_evidence_by_leg": {
            b["identity"]: receipts.get(b["identity"]) for b in books},
        "trade_evidence_by_leg": {
            b["identity"]: (trades or {}).get(b["identity"]) for b in books},
        "policy": dict(policy),
        "note": "Payoff and source-depth quality only. Actual broker margin, "
                "sequenced fills, pin/expiry settlement and profit odds UNKNOWN.",
    }


def decision_summary(rows: list[dict], *, field: str = "feasibility") -> dict:
    """The system can surface paper candidates but never suggest live trade."""
    screened = [row[field] for row in rows if row.get(field)]
    qualifying = sum(bool(r["paper_research_qualified"]) for r in screened)
    counts = Counter(reason for r in screened for reason in r["reasons"])
    return {
        "live_action": "NO_TRADE",
        "research_status": (
            "PAPER_TEST_CANDIDATES" if qualifying
            else "NO_QUALIFIED_CANDIDATES"),
        "paper_research_candidates": qualifying,
        "screened_candidates": len(screened),
        "rejection_reason_counts": dict(counts.most_common()),
        "expected_net_profit_inr": None,
        "calibrated_fill_probability": None,
        "live_orders_authorized": False,
        "explanation": (
            "No trade authorized: saved quotes cannot establish queue "
            "position, passive fill probability, sequencing, or real profit. "
            "Passing the negative screen only permits further paper research."
            if qualifying else
            "NO TRADE: No recorded original-depth candidate passes the "
            "conservative premium/spread/quantity/recency/repeated-packet/"
            "risk filters. Loosening filters does not prove profitability."),
        "policy_version": POLICY_VERSION,
    }
