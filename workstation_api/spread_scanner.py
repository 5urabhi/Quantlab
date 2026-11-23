"""Bounded source-only BANKNIFTY option spread and lot-size scanner.

This reads the original Dhan saved 20-level books for every instrument with
one on the requested IST date. It DOES NOT acquire quotes, place orders,
predict profitable fills, or hallucinate missing books for all Dhan Quote/OI
subscriptions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
from math import isfinite
import json

from . import live_market, liquidity_spreads as spreads, spread_execution_gate as gate

MAX_SOURCE_IDENTITIES = 3000
MAX_LOTS = 10


def _last_books_on_date(day: str | None):
    chosen, start, stop = spreads._day_bounds(day)
    live_market._init_db()
    # Single bounded read of the latest persisted packet per contract.
    # The current Dhan recorder uses the same local market-library store;
    # it is not reconfigured or restarted by this query.
    with live_market._database() as db:
        values = db.execute(
            """SELECT b.identity, b.received_utc, b.book_json,
                      b.packet_pair_sha256
               FROM live_depth_books AS b
               JOIN (
                 SELECT identity, MAX(received_utc) AS newest
                 FROM live_depth_books
                 WHERE received_utc >= ? AND received_utc < ?
                 GROUP BY identity
               ) AS last
                 ON last.identity = b.identity AND last.newest = b.received_utc
               ORDER BY b.identity LIMIT ?""",
            (start, stop, MAX_SOURCE_IDENTITIES + 1)).fetchall()
    return chosen, values[:MAX_SOURCE_IDENTITIES], len(values) > MAX_SOURCE_IDENTITIES


def _original_book(identity: str, received: str, raw: str, digest: str):
    """Reject non-auto/non-original, mismatched or tampered raw book data."""
    if not spreads.ID.fullmatch(identity) or not isinstance(digest, str):
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            return None
        bid_digest = value.get("bid_packet_sha256")
        ask_digest = value.get("ask_packet_sha256")
        if (value.get("identity") != identity or
            value.get("received_utc") != received or
            value.get("source") != "original_Dhan_full_market_depth_websocket" or
            value.get("collection_mode") != "auto_banknifty_20_level" or
            not isinstance(bid_digest, str) or len(bid_digest) != 64 or
            not isinstance(ask_digest, str) or len(ask_digest) != 64 or
            len(digest) != 64 or
            not compare_digest(
                sha256((bid_digest + ask_digest).encode()).hexdigest(),
                digest)):
            return None
        feature = value.get("computed_features") or {}
        lot = feature.get("lot_size_verified")
        if not isinstance(lot, int) or not 1 <= lot <= 1000:
            return None
        # Full price/quantity/order-level validation; originals only.
        verified = spreads._book_stats(value, lot_size=lot)
        return value, verified, feature
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _lot_outcomes(book: dict, stats: dict, budget: float, max_lots: int,
                  profile: str, orders: int, adverse_bps: float,
                  exit_slippage_bps: float = 10.0):
    eligible = []
    trace = []
    for lots in range(1, max_lots + 1):
        calc = spreads.scenario(
            book, lots=lots, executed_orders_per_side=orders,
            adverse_move_bps=adverse_bps, broker_profile=profile)
        risk = spreads.execution_risk(
            book, calc, executed_orders_per_side=orders,
            broker_profile=profile, adverse_move_bps=adverse_bps,
            exit_slippage_bps=exit_slippage_bps)
        passive = calc["passive_capture_upper_bound"]
        market = calc["marketable_roundtrip"]
        fees = passive["fees"]
        required = passive["premium_capital_required"]
        under_budget = required <= budget
        marketable_full = bool(
            calc["marketable_buy"]["fillable"] and
            calc["marketable_sell"]["fillable"])
        top_depth = passive["top_of_book_quantity_sufficient_both_sides"]
        severe_sell = spreads._money(stats["bid"] * lots * stats["lot_size"] * 0.5)
        severe_fees = spreads.fee_schedule(
            spreads._money(stats["bid"] * lots * stats["lot_size"]),
            severe_sell, executed_orders_per_side=orders,
            broker_profile=profile)
        trace.append({
            "lots": lots, "units": lots * stats["lot_size"],
            "half_premium_exit_net_inr": spreads._money(
                severe_sell - stats["bid"] * lots * stats["lot_size"] -
                severe_fees["total_estimated"]),
            "loss_if_option_worthless_inr": spreads._money(-required),
            "sell_fill_hurdle_if_zero_recovery": round(
                required / (required + passive["after_adverse_move_stress_inr"]), 6)
                if passive["after_adverse_move_stress_inr"] > 0 else None,
            "capital_required_inr": required,
            "within_budget": under_budget,
            "marketable_full_depth": marketable_full,
            "top_of_book_both_sides_sufficient": top_depth,
            "hypothetical_buy_cash_debit_inr": fees["buy_leg"]["cash_debit"],
            "hypothetical_sell_cash_credit_inr": fees["sell_leg"]["cash_credit"],
            "buy_fees_inr": fees["buy_leg"]["fees_total"],
            "sell_fees_inr": fees["sell_leg"]["fees_total"],
            "total_fees_inr": fees["total_estimated"],
            "passive_gross_inr": passive["gross_inr"],
            "passive_upper_net_inr": passive[
                "upper_bound_net_inr_before_unmodelled_costs"],
            "passive_stressed_upper_net_inr": passive[
                "after_adverse_move_stress_inr"],
            "marketable_net_inr": market["estimated_net_inr"],
            "failed_exit_net_inr": risk[
                "buy_fills_sell_misses_forced_exit_net_inr"],
            "break_even_exit_fill_probability": risk[
                "break_even_sell_fill_probability_given_buy"],
            "execution_risk_status": risk["status"],
            "marketable_buy_cash_debit_inr": (
                market["fees"]["buy_leg"]["cash_debit"]
                if market.get("fees") else None),
            "marketable_sell_cash_credit_inr": (
                market["fees"]["sell_leg"]["cash_credit"]
                if market.get("fees") else None),
            "marketable_buy_fees_inr": (
                market["fees"]["buy_leg"]["fees_total"]
                if market.get("fees") else None),
            "marketable_sell_fees_inr": (
                market["fees"]["sell_leg"]["fees_total"]
                if market.get("fees") else None),
        })
        if under_budget and marketable_full and top_depth:
            eligible.append(trace[-1])
    if not eligible:
        return trace, None
    # Optimize conditional surplus per rupee of entry capital and the
    # break-even exit-fill hurdle, not the largest absolute quoted spread.
    # These are *structural* heuristics, never observed fill probabilities.
    bounded = [row for row in eligible if row["capital_required_inr"] <=
               budget * gate.CAPTURE_POLICY["max_loss_to_zero_fraction_of_budget"]]
    best = max(bounded or eligible, key=lambda row: (
        row["passive_stressed_upper_net_inr"] /
        max(1.0, row["capital_required_inr"]),
        -(row["break_even_exit_fill_probability"] if
          row["break_even_exit_fill_probability"] is not None else 1),
        -row["lots"]))
    return trace, best


def scan(*, day: str | None = None, broker_profile: str = "zerodha",
         capital_inr: float = 50000.0, max_lots: int = 10,
         executed_orders_per_side: int = 1, adverse_move_bps: float = 25.0,
         exit_slippage_bps: float = 10.0):
    """Rank ALL saved depth-bearing identities, not just nearest 200 slots.

    The archive can include prior 20-level rotation identities. Dhan's
    ~2,850 Quote/OI identities are not the same as 20-level identities:
    contracts without original valid depth remain unevaluable.
    """
    if broker_profile not in spreads.BROKER_PROFILES:
        raise ValueError("Select a supported Dhan or Zerodha pricing profile")
    if (not isinstance(capital_inr, (int, float))
            or not isfinite(capital_inr)
            or not 1000 <= capital_inr <= 10_000_000):
        raise ValueError("Choose a capital budget between ₹1,000 and ₹1 crore")
    if not isinstance(max_lots, int) or not 1 <= max_lots <= MAX_LOTS:
        raise ValueError("Choose between 1 and 10 lots")
    if (not isinstance(executed_orders_per_side, int)
            or not 1 <= executed_orders_per_side <= 20):
        raise ValueError("Choose between 1 and 20 executed orders per side")
    if (not isinstance(adverse_move_bps, (int, float))
            or not isfinite(adverse_move_bps)
            or not 0 <= adverse_move_bps <= 1000):
        raise ValueError("Choose an adverse-move stress of 0–1000 bps")

    if not isinstance(exit_slippage_bps, (int, float)) or (
            not isfinite(exit_slippage_bps) or
            not 0 <= exit_slippage_bps <= 1000):
        raise ValueError("Exit slippage must be 0–1000 bps")
    selected_day, source_rows, scan_limited = _last_books_on_date(day)
    activity = gate.recent_depth_receipts(
        day=selected_day, window_seconds=gate.CAPTURE_POLICY[
            "receipt_window_seconds"])
    now = datetime.now(timezone.utc)
    outcomes = []
    rejected_original = 0
    counters = {
        "evaluated_source_books": 0, "rankable_with_budget_and_depth": 0,
        "positive_stressed_upper_bounds": 0, "negative_stressed_upper_bounds": 0,
        "positive_even_without_stress": 0, "negative_even_optimistic": 0,
        "no_feasible_lots": 0, "recent_saved_books_60s": 0,
        "source_fresh_risk_screened": 0,
    }
    for identity, received_utc, json_blob, packet_digest in source_rows:
        validated = _original_book(
            identity, received_utc, json_blob, packet_digest)
        if not validated:
            rejected_original += 1
            continue
        original, stats, features = validated
        counters["evaluated_source_books"] += 1
        stamp = datetime.fromisoformat(received_utc)
        if stamp.tzinfo is None:
            rejected_original += 1
            counters["evaluated_source_books"] -= 1
            continue
        age = (now - stamp).total_seconds()
        fresh = 0 <= age <= 60
        if fresh:
            counters["recent_saved_books_60s"] += 1
        trace, best = _lot_outcomes(
            original, stats, capital_inr, max_lots,
            broker_profile, executed_orders_per_side, adverse_move_bps,
            exit_slippage_bps)
        if best is None:
            counters["no_feasible_lots"] += 1
        else:
            counters["rankable_with_budget_and_depth"] += 1
            if best["passive_stressed_upper_net_inr"] > 0:
                counters["positive_stressed_upper_bounds"] += 1
            else:
                counters["negative_stressed_upper_bounds"] += 1
            if best["passive_upper_net_inr"] > 0:
                counters["positive_even_without_stress"] += 1
            else:
                counters["negative_even_optimistic"] += 1
        hurdle = best["break_even_exit_fill_probability"] if best else None
        # The old two-outcome hurdle uses a small same-book haircut. It is
        # informational; the shared feasibility gate uses full loss-to-zero.
        screened = False
        score = None
        # For unavailable lots we still expose truthful source quote data,
        # but not a fabricated P&L ranking.
        result = {
            "identity": identity,
            "expiry": features.get("expiry"),
            "strike": features.get("strike"),
            "option_type": features.get("side"),
            "lot_size": stats["lot_size"],
            "received_utc": received_utc,
            "saved_book_age_seconds": round(age, 1),
            "fresh_original_saved_book": fresh,
            "spread_inr": stats["spread_inr"],
            "spread_bps": stats["spread_bps"],
            "best_bid": stats["bid"],
            "best_ask": stats["ask"],
            "top_bid_quantity": stats["top_bid_quantity"],
            "top_ask_quantity": stats["top_ask_quantity"],
            "bid_quantity_20": stats["bid_quantity_20"],
            "ask_quantity_20": stats["ask_quantity_20"],
            "max_tested_lots": max_lots,
            "tested_lot_count": len(trace),
            "best_hypothetical_lots": best["lots"] if best else None,
            "required_capital_inr": (
                best["capital_required_inr"] if best else None),
            "passive_upper_net_inr": (
                best["passive_upper_net_inr"] if best else None),
            "passive_stressed_upper_net_inr": (
                best["passive_stressed_upper_net_inr"] if best else None),
            "marketable_net_inr": (
                best["marketable_net_inr"] if best else None),
            "estimated_buy_fees_inr": (
                best["buy_fees_inr"] if best else None),
            "estimated_sell_fees_inr": (
                best["sell_fees_inr"] if best else None),
            "estimated_total_fees_inr": (
                best["total_fees_inr"] if best else None),
            "lot_scenarios": trace,
            "risk_screen_score": score,
            "source_fresh_risk_screened": screened,
            "break_even_sell_fill_given_buy": hurdle,
            "failed_exit_net_inr": (
                best["failed_exit_net_inr"] if best else None),
            "loss_if_option_worthless_inr": (
                best["loss_if_option_worthless_inr"] if best else None),
            "half_premium_exit_net_inr": (
                best["half_premium_exit_net_inr"] if best else None),
            "conservative_sell_fill_hurdle": (
                best["sell_fill_hurdle_if_zero_recovery"] if best else None),
            "risk_screen_reason": (
                "MISSING_BUDGET_OR_DEPTH" if best is None else
                "STALE_OR_EXPIRED_SOURCE" if not quote_age_ok else
                "NO_POSITIVE_STRESSED_BOUND" if best[
                    "passive_stressed_upper_net_inr"] <= 0 else
                "UNKNOWN_OR_HIGH_EXIT_HURDLE" if not screened else
                "RESEARCH_ONLY_NO_CALIBRATED_FILLS"),
            "classification": (
                "NO_AFFORDABLE_VERIFIED_DEPTH" if best is None
                else "POSITIVE_HYPOTHETICAL_STRESS_BOUND"
                if best["passive_stressed_upper_net_inr"] > 0
                else "NEGATIVE_HYPOTHETICAL_STRESS_BOUND"),
            "two_passive_fills_observed": False,
            "actual_executed_orders": 0,
            "actual_profit_inr": None,
            "read_only": True,
        }
        assessment = gate.capture_feasibility(
            result, capital_inr=capital_inr, receipt=activity.get(identity))
        result["feasibility"] = assessment
        result["source_fresh_risk_screened"] = assessment[
            "paper_research_qualified"]
        result["risk_screen_score"] = assessment[
            "research_priority_score"]
        result["risk_screen_reason"] = (
            "PAPER_RESEARCH_ONLY" if assessment["paper_research_qualified"]
            else assessment["reasons"][0])
        if assessment["paper_research_qualified"]:
            counters["source_fresh_risk_screened"] += 1
        outcomes.append(result)
    # Rank source-fresh, risk-screened research first; never sort stale
    # inflated theoretical spread capture ahead of evidence quality.
    outcomes.sort(key=lambda row: (
        not row["source_fresh_risk_screened"],
        -(row["risk_screen_score"] or 0),
        row["passive_stressed_upper_net_inr"] is None,
        -(row["passive_stressed_upper_net_inr"] or 0),
        row["identity"],
    ))
    return {
        "day_ist": selected_day, "broker_profile": broker_profile,
        "broker_profile_name": spreads.BROKER_PROFILES[broker_profile]["name"],
        "brokerage_per_executed_order_inr": spreads.BROKER_PROFILES[
            broker_profile]["brokerage"],
        "capital_inr": capital_inr, "max_lots": max_lots,
        "executed_orders_per_side": executed_orders_per_side,
        "adverse_move_bps": adverse_move_bps,
        "exit_slippage_bps": exit_slippage_bps,
        "original_depth_contracts_found": len(source_rows),
        "source_scan_truncated": scan_limited,
        "invalid_or_nonoriginal_books": rejected_original,
        **counters, "rows": outcomes,
        "execution_decision": gate.decision_summary(outcomes),
        "execution_policy": dict(gate.CAPTURE_POLICY),
        "total_rows": len(outcomes),
        "scan_completed_utc": now.isoformat(),
        "read_only": True,
        "fills_observed": False,
        "net_realized_profit_inr": None,
        "source": "Dhan original 20-level saved depth books (not all Quote/OI subscriptions)",
        "warning": "NO TRADE is the only live action. The risk gate excludes "
                   "extreme percentage spreads, penny premiums, stale books, "
                   "thin depth, insufficient repeated source packets, "
                   "and premium loss-to-zero above the exposure budget. "
                   "A paper-research-qualified row is NOT broker approved "
                   "or an estimated profitable trade. "
                   "Research priority is an explainable heuristic based on "
                   "capital-normalized two-fill bounds, stressed failed-exit "
                   "loss and required conditional sell-fill hurdle. It is "
                   "NOT a calibrated profit forecast. POSITIVE is only an "
                   "optimistic conditional two-passive-fill "
                   "upper bound after estimated charges and stress, NOT an "
                   "observed trade or expected profit. No exchange queue or "
                   "future price path is observable from this static book. "
                   "Contracts without original Dhan 20-level depth cannot "
                   "be evaluated. Executable source freshness matters. "
                   "Broker tariffs are estimates until checked against "
                   "your actual Zerodha/Dhan contract note.",
    }
