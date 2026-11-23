"""Read-only BANKNIFTY multi-leg option-spread discovery.

Only independently validated, original, saved 20-level Dhan books can supply
quotes. No broker order, synthetic fills, inferred margin or future prices.
Payoff at expiry is *theoretical* and excludes settlement/exercise charges.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import product
from math import isfinite
from statistics import median

from . import liquidity_spreads as liquidity, spread_scanner, spread_execution_gate as gate

STRATEGIES = {
    "bull_call_debit": {
        "label": "Bull call debit vertical",
        "actions": ("BUY", "SELL"), "sides": ("CE", "CE"),
        "roles": ("Buy lower CE", "Sell higher CE"), "group": "Directional",
    },
    "bear_put_debit": {
        "label": "Bear put debit vertical",
        "actions": ("BUY", "SELL"), "sides": ("PE", "PE"),
        "roles": ("Buy higher PE", "Sell lower PE"), "group": "Directional",
    },
    "bull_put_credit": {
        "label": "Bull put credit vertical",
        "actions": ("BUY", "SELL"), "sides": ("PE", "PE"),
        "roles": ("Buy lower PE hedge", "Sell higher PE"), "group": "Credit",
    },
    "bear_call_credit": {
        "label": "Bear call credit vertical",
        "actions": ("BUY", "SELL"), "sides": ("CE", "CE"),
        "roles": ("Buy higher CE hedge", "Sell lower CE"), "group": "Credit",
    },
    "iron_condor": {
        "label": "Iron condor",
        "actions": ("BUY", "SELL", "SELL", "BUY"),
        "sides": ("PE", "PE", "CE", "CE"),
        "roles": ("Buy low PE hedge", "Sell higher PE", "Sell lower CE",
                  "Buy high CE hedge"), "group": "Neutral",
    },
    "iron_butterfly": {
        "label": "Iron butterfly",
        "actions": ("BUY", "SELL", "SELL", "BUY"),
        "sides": ("PE", "PE", "CE", "CE"),
        "roles": ("Buy lower PE hedge", "Sell ATM PE", "Sell ATM CE",
                  "Buy higher CE hedge"), "group": "Neutral",
    },
}
MAX_RETURNED = 250
MAX_GROUP_CONTRACTS = 42
MAX_CANDIDATES_EVALUATED = 12000


def _validate_structure(strategy: str, books: list[dict]) -> None:
    if strategy not in STRATEGIES:
        raise ValueError("Unsupported defined-risk option-spread strategy")
    spec = STRATEGIES[strategy]
    if len(books) != len(spec["actions"]):
        raise ValueError("Incorrect number of legs for strategy")
    if len({b["identity"] for b in books}) != len(books):
        raise ValueError("All option legs must be distinct original contracts")
    if tuple(b["option_type"] for b in books) != spec["sides"]:
        raise ValueError("Incorrect CE/PE leg sequence for strategy")
    expiries = {b["expiry"] for b in books}
    lot_sizes = {b["lot_size"] for b in books}
    if len(expiries) != 1 or None in expiries:
        raise ValueError("Every leg must share the same verified expiry")
    if len(lot_sizes) != 1 or any(not size for size in lot_sizes):
        raise ValueError("Every leg must use the same verified lot size")
    k = [float(b["strike"]) for b in books]
    # Do not build a dictionary of conditions: Python evaluates *all*
    # values eagerly, including 4-leg indices for a 2-leg vertical.
    if strategy in ("bull_call_debit", "bull_put_credit"):
        valid = k[0] < k[1]
    elif strategy in ("bear_put_debit", "bear_call_credit"):
        valid = k[0] > k[1]
    elif strategy == "iron_condor":
        valid = k[0] < k[1] < k[2] < k[3]
    else:
        valid = k[0] < k[1] == k[2] < k[3]
    if not valid:
        raise ValueError("Strike ordering does not define the selected spread")


def _book_row(book: dict, stats: dict, features: dict) -> dict | None:
    try:
        expiry = str(features["expiry"])
        datetime.fromisoformat(expiry)
        strike = float(features["strike"])
        side = str(features["side"]).upper()
        stamp = datetime.fromisoformat(book["received_utc"])
        if stamp.tzinfo is None or not isfinite(strike) or strike <= 0:
            return None
        if side not in {"CE", "PE"}:
            return None
        return {
            "identity": book["identity"], "expiry": expiry,
            "strike": strike, "option_type": side,
            "lot_size": stats["lot_size"], "received_utc": book["received_utc"],
            "stamp": stamp, "bid": stats["bid"], "ask": stats["ask"],
            "spread_bps": stats["spread_bps"], "spread_inr": stats["spread_inr"],
            "bid_top_quantity": stats["top_bid_quantity"],
            "ask_top_quantity": stats["top_ask_quantity"],
            "book": book,
        }
    except (KeyError, TypeError, ValueError):
        return None


def _universe(day: str | None) -> tuple[str, list[dict], dict]:
    chosen, source_rows, truncated = spread_scanner._last_books_on_date(day)
    seen: dict[tuple[str, str, float], dict] = {}
    rejected = 0
    for identity, received, raw, digest in source_rows:
        source = spread_scanner._original_book(identity, received, raw, digest)
        if not source:
            rejected += 1
            continue
        original, stats, features = source
        item = _book_row(original, stats, features)
        if not item or item["expiry"] < chosen:
            rejected += 1
            continue
        key = (item["expiry"], item["option_type"], item["strike"])
        current = seen.get(key)
        if current is None or item["stamp"] > current["stamp"]:
            seen[key] = item
    universe = sorted(seen.values(), key=lambda x: (
        x["expiry"], x["option_type"], x["strike"]))
    return chosen, universe, {
        "original_depth_id_count": len(source_rows),
        "valid_unique_contracts": len(universe),
        "invalid_or_expired_contracts": rejected,
        "scan_truncated": truncated,
    }


def _payoff_per_unit(legs: list[dict], spot: float) -> float:
    return sum((1 if leg["action"] == "BUY" else -1) *
               (max(0.0, spot - leg["strike"]) if leg["option_type"] == "CE"
                else max(0.0, leg["strike"] - spot))
               for leg in legs)


def _terminal_payoff(legs: list[dict], entry_cashflow: float, fees: float,
                     units: int) -> dict:
    strikes = sorted({leg["strike"] for leg in legs})
    width = max(1.0, strikes[-1] - strikes[0])
    extremes = [max(0.0, strikes[0] - 2 * width),
                strikes[-1] + 2 * width]
    knots = sorted(set(strikes + extremes))
    def net(spot: float) -> float:
        return liquidity._money(
            entry_cashflow - fees + _payoff_per_unit(legs, spot) * units)
    outcomes = [net(k) for k in knots]
    profit = max(outcomes)
    loss = max(0.0, -min(outcomes))
    breakevens = []
    for i in range(len(knots) - 1):
        y0, y1 = outcomes[i], outcomes[i + 1]
        if y0 * y1 < 0:
            root = knots[i] + (knots[i + 1] - knots[i]) * (
                -y0 / (y1 - y0))
            breakevens.append(round(root, 2))
        elif y0 == 0:
            breakevens.append(round(knots[i], 2))
    if outcomes[-1] == 0:
        breakevens.append(round(knots[-1], 2))
    # The piecewise linear payoff is exact between strike knots; the evenly
    # spaced samples are only a chart display aid, never trade observations.
    lo, hi = extremes
    points = [{"underlying": round(lo + (hi - lo) * i / 60, 2),
               "net_payoff_inr": net(lo + (hi - lo) * i / 60)}
              for i in range(61)]
    return {
        "max_profit_before_expiry_settlement_inr": profit,
        "max_loss_before_expiry_settlement_inr": loss,
        "break_even_underlying": sorted(set(breakevens)),
        "payoff_points": points,
        "payoff_model": "Terminal intrinsic minus initial debit plus initial "
                        "credit minus estimated ENTRY fees only. No expiry "
                        "exercise, settlement, tax adjustment or future fills.",
    }


def evaluate(strategy: str, books: list[dict], *,
             lots: int = 1, broker_profile: str = "zerodha",
             max_skew_seconds: float = 10.0) -> dict:
    """Evaluate known leg books, preserving all 20-level price/depth evidence.

    The entry is a *marketable* hypothetical fill: BUY asks, SELL bids.
    Closing immediately does the opposite. Nothing is an actual execution.
    """
    if not isinstance(lots, int) or not 1 <= lots <= 10:
        raise ValueError("Choose 1–10 lots")
    if broker_profile not in liquidity.BROKER_PROFILES:
        raise ValueError("Select a valid fee profile")
    if (not isinstance(max_skew_seconds, (float, int)) or
            not isfinite(max_skew_seconds) or
            not 0 <= max_skew_seconds <= 120):
        raise ValueError("Choose quote skew between 0 and 120 seconds")
    _validate_structure(strategy, books)
    stamps = [b["stamp"] for b in books]
    skew = (max(stamps) - min(stamps)).total_seconds()
    if skew > max_skew_seconds:
        raise ValueError("Source quotes are not sufficiently synchronized")
    units = lots * books[0]["lot_size"]
    operations = []
    entry_buys = entry_sells = close_buys = close_sells = 0.0
    counts = Counter(STRATEGIES[strategy]["actions"])
    if counts["BUY"] != counts["SELL"]:
        raise ValueError("Unequal leg order counts are not supported")
    for book, action, role in zip(
            books, STRATEGIES[strategy]["actions"],
            STRATEGIES[strategy]["roles"]):
        entry = liquidity._walk(
            book["book"]["ask" if action == "BUY" else "bid"], units)
        close = liquidity._walk(
            book["book"]["bid" if action == "BUY" else "ask"], units)
        if not entry["fillable"] or not close["fillable"]:
            raise ValueError("Insufficient validated 20-level bid/ask depth")
        if action == "BUY":
            entry_buys += entry["premium_turnover"]
            close_sells += close["premium_turnover"]
        else:
            entry_sells += entry["premium_turnover"]
            close_buys += close["premium_turnover"]
        operations.append({
            "role": role, "identity": book["identity"],
            "action": action, "expiry": book["expiry"],
            "option_type": book["option_type"], "strike": book["strike"],
            "lot_size": book["lot_size"], "lots": lots, "units": units,
            "saved_utc": book["received_utc"],
            "best_bid": book["bid"], "best_ask": book["ask"],
            "spread_bps": book["spread_bps"],
            "entry_vwap": entry["vwap"], "exit_vwap": close["vwap"],
            "entry_premium_turnover_inr": entry["premium_turnover"],
            "close_premium_turnover_inr": close["premium_turnover"],
            "entry_depth_levels_used": entry["levels_used"],
            "top_level_units": book["ask_top_quantity"] if action == "BUY"
                               else book["bid_top_quantity"],
            "original_depth_verified": True,
        })
    orders_per_side = counts["BUY"]
    entry_fees = liquidity.fee_schedule(
        entry_buys, entry_sells,
        executed_orders_per_side=orders_per_side,
        broker_profile=broker_profile)
    close_fees = liquidity.fee_schedule(
        close_buys, close_sells,
        executed_orders_per_side=orders_per_side,
        broker_profile=broker_profile)
    entry_cashflow = liquidity._money(entry_sells - entry_buys)
    same_book_roundtrip = liquidity._money(
        entry_cashflow + close_sells - close_buys -
        entry_fees["total_estimated"] - close_fees["total_estimated"])
    payoff = _terminal_payoff(
        operations, entry_cashflow, entry_fees["total_estimated"], units)
    risk_capital = payoff["max_loss_before_expiry_settlement_inr"]
    return {
        "strategy": strategy, "label": STRATEGIES[strategy]["label"],
        "group": STRATEGIES[strategy]["group"],
        "expiry": books[0]["expiry"], "lot_size": books[0]["lot_size"],
        "lots": lots, "units": units,
        "candidate_id": strategy + ":" + ":".join(b["identity"] for b in books),
        "legs": operations, "quote_skew_seconds": round(skew, 3),
        "oldest_saved_utc": min(stamps).isoformat(),
        "newest_saved_utc": max(stamps).isoformat(),
        "entry_premium_cashflow_inr": entry_cashflow,
        "entry_fees_inr": entry_fees["total_estimated"],
        "entry_fee_breakdown": entry_fees,
        "exit_fees_if_immediate_inr": close_fees["total_estimated"],
        "estimated_same_book_immediate_roundtrip_net_inr":
            same_book_roundtrip,
        "max_profit_inr": payoff["max_profit_before_expiry_settlement_inr"],
        "max_loss_inr": risk_capital,
        "risk_capital_proxy_inr": risk_capital,
        "risk_reward_ratio_proxy": round(
            payoff["max_profit_before_expiry_settlement_inr"] /
            max(1.0, risk_capital), 4),
        "break_even_underlying": payoff["break_even_underlying"],
        "payoff_points": payoff["payoff_points"],
        "payoff_model": payoff["payoff_model"],
        "required_initial_broker_margin_inr": None,
        "broker_margin_verified": False,
        "margin_status": "REQUIRES_ZERODHA_BASKET_MARGIN_CHECK",
        "all_legs_filled": False, "partial_fill_risk_unmodeled": True,
        "executed_orders": 0, "realized_pnl_inr": None,
        "read_only": True,
    }


def _candidate_sets(group: dict[tuple[str, int], dict[str, list[dict]]]):
    """Bounded automatic enumerator; avoids cartesian chain explosion."""
    for (expiry, size), sides in sorted(group.items()):
        calls = sorted(sides["CE"], key=lambda x: x["strike"])
        puts = sorted(sides["PE"], key=lambda x: x["strike"])
        for chain, up, down in [
                (calls, "bull_call_debit", "bear_call_credit"),
                (puts, "bull_put_credit", "bear_put_debit")]:
            for i, low in enumerate(chain):
                for high in chain[i + 1:i + 7]:
                    yield up, [low, high]
                    yield down, [high, low]
        if len(puts) < 2 or len(calls) < 2:
            continue
        # Within two neighboring wings of a short put/call: realistic
        # defined-risk shapes, without combinatorial 4-leg explosion.
        put_indices = list(range(max(1, len(puts) - 14), len(puts)))
        call_indices = list(range(0, min(len(calls) - 1, 14)))
        for pi, ci in product(put_indices, call_indices):
            sp, sc = puts[pi], calls[ci]
            if sp["strike"] >= sc["strike"]:
                continue
            for lp in puts[max(0, pi - 2):pi]:
                for lc in calls[ci + 1:ci + 3]:
                    yield "iron_condor", [lp, sp, sc, lc]
        call_at = {row["strike"]: row for row in calls}
        for mid in range(1, len(puts)):
            center = puts[mid]["strike"]
            if center not in call_at:
                continue
            lower = puts[max(0, mid - 2):mid]
            higher = [c for c in calls if c["strike"] > center][:2]
            for low, high in product(lower, higher):
                yield "iron_butterfly", [low, puts[mid], call_at[center], high]


def scan(*, day: str | None = None, capital_inr: float = 50000,
         broker_profile: str = "zerodha", max_lots: int = 5,
         max_quote_skew_seconds: float = 10,
         max_source_age_seconds: float = 60, limit: int = 100) -> dict:
    """Auto-discover, score and sort both debit and hedged-credit spreads."""
    if (not isinstance(capital_inr, (int, float)) or
            not isfinite(capital_inr) or
            not 1000 <= capital_inr <= 10_000_000):
        raise ValueError("Capital must be between 1000 and 1 crore INR")
    if not isinstance(max_lots, int) or not 1 <= max_lots <= 10:
        raise ValueError("Select 1–10 lots")
    if (not isinstance(limit, int) or not 1 <= limit <= MAX_RETURNED):
        raise ValueError("Limit must be 1–250")
    if (not isinstance(max_source_age_seconds, (int, float)) or
            not isfinite(max_source_age_seconds) or
            not 1 <= max_source_age_seconds <= 3600):
        raise ValueError("Source freshness must be 1–3600 seconds")
    if broker_profile not in liquidity.BROKER_PROFILES:
        raise ValueError("Unsupported broker tariff")
    if (not isinstance(max_quote_skew_seconds, (int, float)) or
            not isfinite(max_quote_skew_seconds) or
            not 0 <= max_quote_skew_seconds <= 120):
        raise ValueError("Quote skew must be 0–120 seconds")
    chosen, universe, evidence = _universe(day)
    activity = gate.recent_depth_receipts(
        day=chosen, window_seconds=gate.MULTILEG_POLICY["receipt_window_seconds"])
    trades = gate.recent_trade_activity(
        day=chosen, window_seconds=gate.MULTILEG_POLICY["receipt_window_seconds"])
    now = datetime.now(timezone.utc)
    today = now.astimezone(liquidity.IST).date().isoformat()
    groups = defaultdict(lambda: {"CE": [], "PE": []})
    for row in universe:
        groups[(row["expiry"], row["lot_size"])][row["option_type"]].append(row)
    capped = 0
    for sides in groups.values():
        for side in ("CE", "PE"):
            chain = sides[side]
            if len(chain) > MAX_GROUP_CONTRACTS:
                midpoint = median([x["strike"] for x in chain])
                sides[side] = sorted(
                    sorted(chain, key=lambda x: abs(x["strike"] - midpoint))[
                        :MAX_GROUP_CONTRACTS],
                    key=lambda x: x["strike"])
                capped += len(chain) - MAX_GROUP_CONTRACTS
    generated = set()
    rejections = Counter()
    ranked = []
    for idx, (strategy, books) in enumerate(_candidate_sets(groups)):
        if idx >= MAX_CANDIDATES_EVALUATED:
            rejections["candidate_cap"] += 1
            break
        ident = (strategy, tuple(b["identity"] for b in books))
        if ident in generated:
            continue
        generated.add(ident)
        try:
            candidate = evaluate(
                strategy, books, lots=1, broker_profile=broker_profile,
                max_skew_seconds=max_quote_skew_seconds)
        except (ValueError, TypeError, OverflowError) as exc:
            rejections[str(exc)[:80]] += 1
            continue
        # Pick a lot count automatically, using risk capital as a *proxy*,
        # never asserting that Zerodha SPAN or basket margin is sufficient.
        choice = None
        for lots in range(1, max_lots + 1):
            if lots == 1:
                result = candidate
            else:
                try:
                    result = evaluate(
                        strategy, books, lots=lots,
                        broker_profile=broker_profile,
                        max_skew_seconds=max_quote_skew_seconds)
                except ValueError:
                    break
            if (result["risk_capital_proxy_inr"] > 0 and
                    result["risk_capital_proxy_inr"] <= capital_inr *
                    gate.MULTILEG_POLICY[
                        "max_theoretical_loss_fraction_of_budget"]):
                choice = result
            else:
                break
        if choice is None:
            rejections["risk_capital_budget_or_depth"] += 1
            continue
        if choice["max_profit_inr"] <= 0:
            rejections["no_positive_terminal_payoff_after_entry_fees"] += 1
            continue
        age = (now - min(b["stamp"] for b in books)).total_seconds()
        fresh = (chosen == today and
                 0 <= age <= max_source_age_seconds)
        reward = choice["max_profit_inr"]
        loss = choice["max_loss_inr"]
        ratio = max(0.0, reward) / max(1.0, loss)
        price_drag = abs(min(0.0, choice[
            "estimated_same_book_immediate_roundtrip_net_inr"]))
        drag_ratio = price_drag / max(1.0, loss)
        score = round(
            max(0.0, 40 * min(2.0, ratio) -
                25 * min(2.0, drag_ratio) -
                10 * min(1.0, choice["quote_skew_seconds"] /
                         max(1.0, max_quote_skew_seconds))), 2)
        # The short option introduces margin and leg-execution uncertainty:
        # no quote-only result is a broker-approved or executable trade.
        choice["source_age_seconds"] = round(age, 1)
        choice["fresh_reference"] = fresh
        choice["risk_budget_proxy_pass"] = True
        choice["structural_reward_risk_score"] = score
        assessment = gate.multileg_feasibility(
            choice, books=books, capital_inr=capital_inr, receipts=activity,
            trades=trades)
        choice["feasibility"] = assessment
        choice["paper_research_qualified"] = assessment[
            "paper_research_qualified"]
        choice["research_priority_score"] = assessment[
            "research_priority_score"]
        choice["status"] = (
            "PAPER_RESEARCH_ONLY_MARGIN_UNVERIFIED"
            if assessment["paper_research_qualified"]
            else "BLOCKED_BY_EXECUTION_EVIDENCE_GATE")
        choice["qualification_notes"] = [
            "All entry legs are hypothetically filled against recorded "
            "ask (BUY) / bid (SELL) depth.",
            "A valid expiry payoff is not evidence of future market profit.",
            "No broker SPAN/required basket margin is available.",
            "Quote sync %ss; saved-book age %ss." % (
                choice["quote_skew_seconds"], round(age, 1)),
            "Execution gate: " + (
                "SOURCE_RESEARCH_PASSED" if assessment["paper_research_qualified"]
                else ", ".join(assessment["reasons"])),
        ]
        ranked.append(choice)
    ranked.sort(key=lambda c: (
        not c["paper_research_qualified"],
        not c["fresh_reference"],
        -(c["research_priority_score"] or 0),
        -c["risk_reward_ratio_proxy"],
        c["risk_capital_proxy_inr"], c["candidate_id"]))
    counts = Counter(row["strategy"] for row in ranked)
    return {
        "day_ist": chosen, "capital_inr": capital_inr,
        "max_lots": max_lots, "broker_profile": broker_profile,
        "max_quote_skew_seconds": max_quote_skew_seconds,
        "max_source_age_seconds": max_source_age_seconds,
        "strategies": [
            {"key": key, **{name: value for name, value in info.items()
                            if name in ("label", "group", "roles", "actions",
                                        "sides")}, "qualified_candidates": counts[key]}
            for key, info in STRATEGIES.items()],
        "available_contracts": [
            {k: item[k] for k in (
                "identity", "expiry", "strike", "option_type", "lot_size",
                "received_utc", "bid", "ask", "spread_bps")}
            for item in universe[:750]],
        "discovered_candidates": len(ranked),
        "execution_decision": gate.decision_summary(ranked),
        "execution_policy": dict(gate.MULTILEG_POLICY),
        "ranked_candidates": ranked[:limit],
        "returned_candidates": min(len(ranked), limit),
        "rejected_reason_counts": dict(rejections),
        "truncated_group_contracts": capped,
        **evidence,
        "freshness_mode": ("LIVE_REFERENCE" if chosen == today
                           else "HISTORICAL_REFERENCE"),
        "fill_probabilities_known": False,
        "broker_margin_verified": False,
        "realized_pnl_inr": None, "executed_orders": 0,
        "read_only": True,
        "warning": "NO TRADE: no multi-leg basket is automatically approved "
                   "without verified broker margin, sequenced fills and "
                   "execution probability. The negative screen rejects "
                   "stale/asynchronous quotes, high relative spreads, "
                   "penny legs, thin top levels, insufficient repeated "
                   "packet receipts, excessive loss to budget and costly "
                   "same-book crossing. Automatic ranking is for "
                   "SOURCE-BOUNDED RESEARCH, "
                   "not most-profitable live contracts. Max profit/loss "
                   "are terminal intrinsic payoff bounds after estimated "
                   "entry charges only, excluding exercise/settlement; "
                   "actual Zerodha required/final basket margin, queue, "
                   "leg fills, slippage between legs and stop behavior "
                   "are not known. Dhan depth is only a subset of all "
                   "chain subscriptions. A stale source cannot rank "
                   "as a live executable opportunity.",
    }


def build(*, day: str | None, strategy: str, identities: list[str],
          lots: int, broker_profile: str = "zerodha",
          max_quote_skew_seconds: float = 10,
          capital_inr: float = 50000) -> dict:
    """Evaluate manually chosen optional legs; auto-scan is the main path."""
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    if (not isinstance(capital_inr, (int, float)) or
            not isfinite(capital_inr) or not 1000 <= capital_inr <= 10_000_000):
        raise ValueError("Choose valid risk-capital budget")
    if len(identities) != len(STRATEGIES[strategy]["actions"]):
        raise ValueError("Wrong number of option legs")
    if any(not isinstance(i, str) or not spread_scanner.spreads.ID.fullmatch(i)
           for i in identities):
        raise ValueError("Choose exact verified NSE_FNO IDs only")
    chosen, universe, metadata = _universe(day)
    by_id = {item["identity"]: item for item in universe}
    if any(i not in by_id for i in identities):
        raise ValueError("Selected contract has no validated saved 20-level book")
    result = evaluate(strategy, [by_id[i] for i in identities],
                      lots=lots, broker_profile=broker_profile,
                      max_skew_seconds=max_quote_skew_seconds)
    now = datetime.now(timezone.utc)
    stamps = [b["stamp"] for b in [by_id[i] for i in identities]]
    age = (now - min(stamps)).total_seconds()
    result["source_age_seconds"] = round(age, 1)
    result["fresh_reference"] = (
        chosen == now.astimezone(liquidity.IST).date().isoformat()
        and 0 <= age <= gate.MULTILEG_POLICY["max_age_seconds"])
    receipts = gate.recent_depth_receipts(
        day=chosen, window_seconds=gate.MULTILEG_POLICY["receipt_window_seconds"])
    trades = gate.recent_trade_activity(
        day=chosen, window_seconds=gate.MULTILEG_POLICY["receipt_window_seconds"])
    result["feasibility"] = gate.multileg_feasibility(
        result, books=[by_id[i] for i in identities],
        capital_inr=capital_inr, receipts=receipts, trades=trades)
    result["paper_research_qualified"] = result["feasibility"][
        "paper_research_qualified"]
    result.update({"status": "MANUAL_READ_ONLY_RESEARCH", "day_ist": chosen,
                   "source_metadata": metadata})
    return result
