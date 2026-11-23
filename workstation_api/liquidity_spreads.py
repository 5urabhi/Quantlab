"""Read-only, Dhan-only BANKNIFTY liquidity and spread research.

All bid/ask levels originate in original validated 20-level Dhan books.
No broker orders, invented historical books, or simulated fills represented
as actual trades. Every scenario is explicitly a counterfactual.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from hmac import compare_digest
from math import isfinite
from zoneinfo import ZoneInfo
import json
import re
import sqlite3

from . import auto_option_depth, live_market, market_depth

IST = ZoneInfo("Asia/Kolkata")
ID = re.compile(r"^NSE_FNO:[0-9]{1,12}$")
MAX_BOOKS = 800
BROKERAGE_INR_PER_ORDER = 20.0
GST_RATE = 0.18
STT_SELL_RATE = 0.0015             # NSE effective 2026-04-01
NSE_OPTION_EXCHANGE_RATE = 0.0003553  # Indicative 2026; verify contract note
SEBI_RATE = 0.000001
STAMP_BUY_RATE = 0.00003
FEE_VERSION = "research_illustration_nse_options_2026_11"
BROKER_PROFILES = {
    "dhan": {"name": "Dhan regular retail", "brokerage": 20.0,
             "source": "https://dhan.co/pricing/"},
    "zerodha": {"name": "Zerodha regular retail", "brokerage": 20.0,
                "source": "https://zerodha.com/charges/"},
    "zerodha_debit_balance": {
        "name": "Zerodha debit-balance/collateral-shortfall scenario",
        "brokerage": 40.0,
        "source": "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/what-is-the-brokerage-at-zerodha-for-equity"},
}
SOURCE_NOTES = [
    "https://dhan.co/pricing/",
    "https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax",
]
WARN_FEES = (
    "Illustrative NSE equity-options intraday charges, not a broker contract "
    "note: brokerage depends on selected Dhan/Zerodha tariff; sell-side STT 0.15% "
    "effective 1 Apr 2026; indicative NSE option exchange 0.03553%, SEBI "
    "0.0001%, buy-side stamp 0.003%, GST 18% on brokerage/transaction/SEBI. "
    "IPFT, additional levies, clearing/physical delivery, expiry exercise, "
    "partial-fill order counts and actual broker rounding may differ."
)


def _money(amount: float) -> float:
    return float(Decimal(str(amount)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


def _rupee(amount: float) -> float:
    return float(Decimal(str(amount)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def _check_id(identity: str) -> str:
    if not isinstance(identity, str) or not ID.fullmatch(identity):
        raise ValueError("Choose a master-verified exact NSE_FNO contract ID")
    return identity


def _day_bounds(day: str | None):
    if day is None:
        chosen = datetime.now(timezone.utc).astimezone(IST).date()
    else:
        try:
            chosen = date.fromisoformat(day)
        except (ValueError, TypeError):
            raise ValueError("Select a valid YYYY-MM-DD IST trading date") from None
        if chosen.isoformat() != day:
            raise ValueError("Select an ISO YYYY-MM-DD IST trading date")
    start = datetime.combine(chosen, time.min, IST).astimezone(timezone.utc)
    stop = start + timedelta(days=1)
    return chosen.isoformat(), start.isoformat(), stop.isoformat()


def _book_stats(book: dict, *, lot_size: int | None = None) -> dict:
    """Re-check original book ordering and independently derive spread."""
    verified = market_depth._validate_snapshot(book, 20)
    bid = verified["bid"][0]["price"]
    ask = verified["ask"][0]["price"]
    midpoint = (bid + ask) / 2.0
    if not midpoint > 0:
        raise ValueError("Nonpositive original option midpoint")
    return {
        "bid": bid, "ask": ask, "mid": _money(midpoint),
        "spread_inr": _money(ask - bid),
        "spread_bps": round((ask - bid) / midpoint * 10_000, 2),
        "bid_quantity_20": sum(level["quantity"] for level in verified["bid"]),
        "ask_quantity_20": sum(level["quantity"] for level in verified["ask"]),
        "top_bid_quantity": verified["bid"][0]["quantity"],
        "top_ask_quantity": verified["ask"][0]["quantity"],
        "imbalance_20": round(
            (sum(x["quantity"] for x in verified["bid"]) -
             sum(x["quantity"] for x in verified["ask"])) /
            max(1, sum(x["quantity"] for x in verified["bid"]) +
                sum(x["quantity"] for x in verified["ask"])), 4),
        "lot_size": lot_size,
    }


def _read_books(identity: str, *, day: str | None = None,
                limit: int = 300) -> tuple[list[dict], dict]:
    _check_id(identity)
    if not isinstance(limit, int) or not 1 <= limit <= MAX_BOOKS:
        raise ValueError("Choose between 1 and 800 stored original books")
    chosen, start, end = _day_bounds(day)
    # Local database only; never contact or modify Dhan WebSockets.
    live_market._init_db()
    with live_market._database() as db:
        # Prefer the most recent receipts and explicitly report any scan cap.
        fetched = db.execute(
            "SELECT received_utc,book_json,packet_pair_sha256 "
            "FROM live_depth_books WHERE identity=? AND received_utc>=? "
            "AND received_utc<? ORDER BY received_utc DESC LIMIT ?",
            (identity, start, end, min(5001, limit * 8 + 1))).fetchall()
    valid: list[dict] = []
    skipped = 0
    for stamp, raw, packet_digest in fetched:
        try:
            entry = json.loads(raw)
            bid_digest = entry.get("bid_packet_sha256")
            ask_digest = entry.get("ask_packet_sha256")
            if (entry.get("identity") != identity or
                entry.get("received_utc") != stamp or
                entry.get("collection_mode") != "auto_banknifty_20_level" or
                entry.get("source") != "original_Dhan_full_market_depth_websocket" or
                not isinstance(packet_digest, str) or len(packet_digest) != 64 or
                not isinstance(bid_digest, str) or len(bid_digest) != 64 or
                not isinstance(ask_digest, str) or len(ask_digest) != 64 or
                not compare_digest(
                    sha256((bid_digest + ask_digest).encode()).hexdigest(),
                    packet_digest)):
                skipped += 1
                continue
            feature = entry.get("computed_features") or {}
            lot = feature.get("lot_size_verified")
            if not isinstance(lot, int) or not 1 <= lot <= 1000:
                skipped += 1
                continue
            # This is a source validation on read, not a synthetic book build.
            stats = _book_stats(entry, lot_size=lot)
            valid.append({
                "identity": identity, "received_utc": stamp,
                "session_id": None,  # no internal session identifier exposed
                "expiry": feature.get("expiry"),
                "strike": feature.get("strike"),
                "option_type": feature.get("side"),
                "packet_pair_sha256": packet_digest,
                "clock": "local_receive_utc",
                **stats,
                "bid_levels": entry["bid"],
                "ask_levels": entry["ask"],
            })
        except (ValueError, TypeError, KeyError, OverflowError):
            skipped += 1
        if len(valid) >= limit:
            break
    valid.reverse()
    meta = {
        "day_ist": chosen,
        "scanned_records": len(fetched),
        "rejected_or_not_auto_dhan": skipped,
        "more_source_records_possible": len(fetched) >= min(
            5001, limit * 8 + 1),
        "sampled_books_not_continuous": True,
        "source": "validated_original_Dhan_20_level_books_saved_to_dhan_shared",
        "notice": "Only actually saved original depth receipts. Between-book "
                  "intervals may contain unknown bid/ask updates. "
                  "No reconstruction or verified broker fills.",
    }
    return valid, meta


def book_history(identity: str, day: str | None = None,
                 limit: int = 300, include_levels: bool = True) -> dict:
    books, meta = _read_books(identity, day=day, limit=limit)
    if not include_levels:
        for book in books:
            book.pop("bid_levels", None)
            book.pop("ask_levels", None)
    return {
        "identity": identity, "books": books, "count": len(books),
        **meta, "read_only": True,
    }


def overview(expiry: str | None = None, limit: int = 200) -> dict:
    if not 1 <= limit <= 200:
        raise ValueError("Show 1–200 original selected option contracts")
    if expiry and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry):
        raise ValueError("Expiry must be YYYY-MM-DD")
    status = auto_option_depth.status()
    contracts = status.get("contracts") or []
    latest = status.get("latest") or {}
    receipt = status.get("contract_receipts") or {}
    result = []
    valid_spreads = []
    for contract in contracts:
        identity = contract.get("identity")
        if not isinstance(identity, str) or not ID.fullmatch(identity):
            continue
        if expiry and contract.get("expiry") != expiry:
            continue
        sample = latest.get(identity) or {}
        bid, ask = sample.get("best_bid"), sample.get("best_ask")
        observed = (isinstance(bid, (int, float)) and
                    isinstance(ask, (int, float)) and
                    isfinite(bid) and isfinite(ask) and 0 < bid < ask)
        spread_bps = (round((ask - bid) / ((ask + bid) / 2) * 1e4, 2)
                      if observed else None)
        recv = receipt.get(identity) or {}
        row = {
            "identity": identity,
            "expiry": contract.get("expiry"),
            "strike": contract.get("strike"),
            "option_type": contract.get("side") or contract.get("option_type"),
            "lot_size": contract.get("lot_size"),
            "coverage_role": contract.get("coverage_role", "selected"),
            "best_bid": bid if observed else None,
            "best_ask": ask if observed else None,
            "spread_inr": _money(ask - bid) if observed else None,
            "spread_bps": spread_bps,
            "imbalance_20": sample.get("book_imbalance_20"),
            "bid_quantity_20": sample.get("bid_quantity_20"),
            "ask_quantity_20": sample.get("ask_quantity_20"),
            "top_bid_quantity": sample.get("top_bid_quantity"),
            "top_ask_quantity": sample.get("top_ask_quantity"),
            "saved_book_received_utc": sample.get("received_utc"),
            "source_book_age_seconds": sample.get("age_seconds"),
            "recent_original_pair_age_seconds": recv.get("pair_age_seconds"),
            "feed_fresh": bool(sample.get("feed_fresh")),
            "receipt_status": recv.get("status", "not_observed"),
        }
        # A stored sample may be stale even though the source socket is fresh.
        # Never conflate its best bid/ask with an executable live quote.
        if row["feed_fresh"] and observed:
            valid_spreads.append(spread_bps)
        result.append(row)
    result.sort(key=lambda row: (
        not row["feed_fresh"],
        row["spread_bps"] is None,
        row["spread_bps"] if row["spread_bps"] is not None else float("inf"),
        row["identity"],
    ))
    return {
        "rows": result[:limit], "filtered_selected": len(result),
        "configured_depth_contracts": len(contracts),
        "fresh_spread_sample_size": len(valid_spreads),
        "mean_fresh_spread_bps": (
            round(sum(valid_spreads) / len(valid_spreads), 2)
            if valid_spreads else None),
        "expiry_options": sorted({c.get("expiry") for c in contracts
                                  if isinstance(c.get("expiry"), str)}),
        "connected": bool(status.get("connected")),
        "market_regular_hours": bool(status.get("market_regular_hours")),
        "source_status": status.get("state", "unavailable"),
        "source": "Dhan validated original 20-level saved snapshots",
        "read_only": True,
        "warning": (
            "Bid/ask prices may be sampled up to the recorder's configured "
            "interval and are not guaranteed executable at this instant. "
            "Spread metrics are not evidence of fills or profits."),
    }


def _walk(levels: list[dict], units: int) -> dict:
    remaining = units
    paid = 0.0
    used = 0
    for level in levels:
        qty = level["quantity"]
        take = min(remaining, qty)
        if take > 0:
            paid += take * level["price"]
            remaining -= take
            used += 1
        if remaining == 0:
            break
    return {
        "fillable": remaining == 0,
        "observed_units": units - remaining,
        "missing_units": remaining,
        "levels_used": used,
        "vwap": _money(paid / units) if remaining == 0 else None,
        "premium_turnover": _money(paid) if remaining == 0 else None,
    }


def fee_schedule(buy_turnover: float, sell_turnover: float,
                 *, executed_orders_per_side: int = 1,
                 brokerage_inr: float | None = None,
                 broker_profile: str = "dhan") -> dict:
    if broker_profile not in BROKER_PROFILES:
        raise ValueError("Broker profile must be Dhan or a listed Zerodha tariff")
    if brokerage_inr is None:
        brokerage_inr = BROKER_PROFILES[broker_profile]["brokerage"]
    if not (0 <= buy_turnover <= 1e10 and 0 <= sell_turnover <= 1e10):
        raise ValueError("Invalid option premium turnover")
    if (not isinstance(executed_orders_per_side, int) or
            not 1 <= executed_orders_per_side <= 20):
        raise ValueError("Executed-order count must be between 1 and 20")
    if not isfinite(brokerage_inr) or not 0 <= brokerage_inr <= 1000:
        raise ValueError("Unsupported brokerage cost assumption")
    turnover = buy_turnover + sell_turnover
    brokerage = _money(2 * executed_orders_per_side * brokerage_inr)
    exchange = _money(turnover * NSE_OPTION_EXCHANGE_RATE)
    sebi = _money(turnover * SEBI_RATE)
    gst = _money((brokerage + exchange + sebi) * GST_RATE)
    stt = _rupee(sell_turnover * STT_SELL_RATE)
    stamp = _rupee(buy_turnover * STAMP_BUY_RATE)
    fee = {
        "brokerage": brokerage, "exchange_indicative": exchange,
        "sebi": sebi, "gst": gst, "stt_sell": stt,
        "stamp_buy": stamp,
    }
    total = _money(sum(fee.values()))
    # Split already-rounded combined charges across two hypothetical order
    # sides. The final sell-side remainder preserves the original fee total
    # even if rounding each side independently would move one paisa.
    per_order_brokerage = _money(executed_orders_per_side * brokerage_inr)
    buy_exch = _money(buy_turnover * NSE_OPTION_EXCHANGE_RATE)
    buy_sebi = _money(buy_turnover * SEBI_RATE)
    buy_gst = _money((per_order_brokerage + buy_exch + buy_sebi)*GST_RATE)
    buy_fees = {
        "brokerage": per_order_brokerage,
        "exchange_indicative": buy_exch, "sebi": buy_sebi,
        "gst": buy_gst, "stt_sell": 0.0, "stamp_buy": stamp,
    }
    sell_fees = {
        "brokerage": _money(brokerage - per_order_brokerage),
        "exchange_indicative": _money(exchange - buy_exch),
        "sebi": _money(sebi - buy_sebi),
        "gst": _money(gst - buy_gst),
        "stt_sell": stt, "stamp_buy": 0.0,
    }
    buy_total = _money(sum(buy_fees.values()))
    sell_total = _money(total - buy_total)
    return {
        **fee, "total_estimated": total,
        "broker_profile": broker_profile,
        "broker_profile_name": BROKER_PROFILES[broker_profile]["name"],
        "brokerage_inr_per_executed_order": brokerage_inr,
        "buy_leg": {
            **buy_fees, "premium_turnover": _money(buy_turnover),
            "fees_total": buy_total,
            "cash_debit": _money(buy_turnover + buy_total),
        },
        "sell_leg": {
            **sell_fees, "premium_turnover": _money(sell_turnover),
            "fees_total": sell_total,
            "cash_credit": _money(sell_turnover - sell_total),
        },
        "version": FEE_VERSION, "additional_charges_excluded": True,
        "assumptions": WARN_FEES + (
            " Zerodha ₹40/order applies in specified debit-balance or "
            "collateral-shortfall conditions when that profile is selected. "
            "Check actual account-specific contract notes and order fills."),
        "references": SOURCE_NOTES + [BROKER_PROFILES[broker_profile]["source"]],
    }


def scenario(book: dict, lots: int = 1,
             executed_orders_per_side: int = 1,
             brokerage_inr: float | None = None,
             adverse_move_bps: float = 0,
             broker_profile: str = "dhan") -> dict:
    if not isinstance(lots, int) or not 1 <= lots <= 10:
        raise ValueError("Choose 1–10 lots for bounded research")
    if not isfinite(adverse_move_bps) or not 0 <= adverse_move_bps <= 1000:
        raise ValueError("Choose an adverse move from 0 to 1000 bps")
    stats = _book_stats(book, lot_size=book.get("computed_features", {}).get(
        "lot_size_verified"))
    size = stats["lot_size"]
    if not isinstance(size, int) or not 1 <= size <= 1000:
        raise ValueError("Source-verified Dhan lot size is unavailable")
    units = lots * size
    buy = _walk(book["ask"], units)
    sell = _walk(book["bid"], units)
    top_both = (book["bid"][0]["quantity"] >= units and
                book["ask"][0]["quantity"] >= units)
    passive_buy = stats["bid"] * units
    passive_sell = stats["ask"] * units
    passive_fees = fee_schedule(passive_buy, passive_sell,
        executed_orders_per_side=executed_orders_per_side,
        brokerage_inr=brokerage_inr, broker_profile=broker_profile)
    passive_gross = passive_sell - passive_buy
    penalty = units * (stats["mid"] * adverse_move_bps / 10_000)
    optimistic = _money(passive_gross - passive_fees["total_estimated"])
    output = {
        "lots": lots, "units": units, "lot_size": size,
        "observed_bid": stats["bid"], "observed_ask": stats["ask"],
        "spread_inr": stats["spread_inr"],
        "spread_bps": stats["spread_bps"],
        "observed_ask_depth_units": stats["ask_quantity_20"],
        "observed_bid_depth_units": stats["bid_quantity_20"],
        "marketable_buy": buy, "marketable_sell": sell,
        "passive_capture_upper_bound": {
            "hypothetical_buy_at_bid": stats["bid"],
            "hypothetical_sell_at_ask": stats["ask"],
            "gross_inr": _money(passive_gross),
            "fees": passive_fees,
            "buy_cash_debit": passive_fees["buy_leg"]["cash_debit"],
            "sell_cash_credit": passive_fees["sell_leg"]["cash_credit"],
            "premium_capital_required": passive_fees["buy_leg"]["cash_debit"],
            "upper_bound_net_inr_before_unmodelled_costs": optimistic,
            "after_adverse_move_stress_inr": _money(optimistic - penalty),
            "adverse_move_bps_assumption": adverse_move_bps,
            "top_of_book_quantity_sufficient_both_sides": top_both,
            "fills_observed": False,
            "fill_probability": None,
            "classification": "UNEXECUTABLE_OPTIMISTIC_UPPER_BOUND",
            "caveat": "Both passive orders and queue priority are hypothetical. "
                      "A posted order can be adversely selected, partially "
                      "filled or never filled, even if top-book size appears large.",
        },
        "read_only": True, "broker_orders_sent": 0,
        "broker_profile": broker_profile,
        "source": "original Dhan 20-level saved book, local receive-time",
    }
    if buy["fillable"] and sell["fillable"]:
        gross = sell["premium_turnover"] - buy["premium_turnover"]
        fees = fee_schedule(buy["premium_turnover"], sell["premium_turnover"],
            executed_orders_per_side=executed_orders_per_side,
            brokerage_inr=brokerage_inr, broker_profile=broker_profile)
        output["marketable_roundtrip"] = {
            "gross_inr": _money(gross), "fees": fees,
            "buy_cash_debit": fees["buy_leg"]["cash_debit"],
            "sell_cash_credit": fees["sell_leg"]["cash_credit"],
            "estimated_net_inr": _money(gross - fees["total_estimated"]),
            "status": "COUNTERFACTUAL_IMMEDIATE_CROSS_THE_SPREAD",
            "fills_observed": False,
            "caveat": "Both legs are valued against the SAME historical "
                      "saved book. Execution latency, queue depletion and "
                      "market movement remain unobserved.",
        }
    else:
        output["marketable_roundtrip"] = {
            "status": "INSUFFICIENT_RECORDED_20_LEVEL_QUANTITY",
            "fills_observed": False, "gross_inr": None,
            "estimated_net_inr": None, "fees": None,
        }
    return output


def simulate(identity: str, lots: int = 1,
             day: str | None = None,
             received_utc: str | None = None,
             executed_orders_per_side: int = 1,
             brokerage_inr: float | None = None,
             adverse_move_bps: float = 0,
             broker_profile: str = "dhan") -> dict:
    books, meta = _read_books(identity, day=day, limit=300)
    if not books:
        return {"status": "ORIGINAL_BOOK_MISSING", "identity": identity,
                "read_only": True, "count": 0, **meta,
                "note": "No valid saved Dhan 20-level book available. "
                        "Cannot estimate execution from chain LTP or OI alone."}
    matches = [b for b in books if b["received_utc"] == received_utc] if received_utc else books
    if not matches:
        raise ValueError("Selected original saved-book timestamp is unavailable")
    selected = matches[-1]
    original = {
        "bid": selected["bid_levels"],
        "ask": selected["ask_levels"],
        "identity": identity,
        "computed_features": {"lot_size_verified": selected["lot_size"]},
    }
    return {
        "status": "ORIGINAL_BOOK_SCENARIO_ONLY",
        "identity": identity, "selected_book_received_utc": selected["received_utc"],
        "source_age_is_historical": True,
        "packet_pair_sha256": selected["packet_pair_sha256"],
        "assumptions": scenario(original, lots,
            executed_orders_per_side, brokerage_inr, adverse_move_bps,
            broker_profile=broker_profile),
        "read_only": True,
    }


def research(identity: str, day: str | None = None,
             lots: int = 1, limit: int = 300,
             adverse_move_bps: float = 25,
             broker_profile: str = "dhan") -> dict:
    books, meta = _read_books(identity, day=day, limit=limit)
    sampled = []
    for book in books:
        orig = {
            "bid": book["bid_levels"], "ask": book["ask_levels"],
            "computed_features": {"lot_size_verified": book["lot_size"]},
        }
        projection = scenario(orig, lots=lots,
                              adverse_move_bps=adverse_move_bps,
                              broker_profile=broker_profile)
        upper = projection["passive_capture_upper_bound"]
        market = projection["marketable_roundtrip"]
        sampled.append({
            "received_utc": book["received_utc"],
            "spread_bps": book["spread_bps"],
            "spread_inr": book["spread_inr"],
            "optimistic_net_if_two_passive_fills_inr":
                upper["upper_bound_net_inr_before_unmodelled_costs"],
            "stress_net_inr": upper["after_adverse_move_stress_inr"],
            "marketable_same_book_net_inr":
                market.get("estimated_net_inr"),
            "source_bid": book["bid"], "source_ask": book["ask"],
            "source_book_freshness": "historical_saved_local_receipt",
        })
    spreads = [x["spread_bps"] for x in sampled]
    viable = [x for x in sampled
              if x["optimistic_net_if_two_passive_fills_inr"] > 0]
    return {
        "identity": identity, "lots": lots, "broker_profile": broker_profile,
        "adverse_move_bps": adverse_move_bps,
        "observed_saved_books": len(sampled),
        "observed_spread_bps_mean": (
            round(sum(spreads) / len(spreads), 2) if spreads else None),
        "positive_optimistic_upper_bound_snapshots": len(viable),
        "net_profitable_executed_trades": None,
        "executed_trades": 0,
        "fill_rate": None, "sharpe": None, "realized_pnl": None,
        "samples": sampled,
        **meta,
        "status": ("SOURCE_SNAPSHOT_UPPER_BOUND_ONLY" if sampled
                   else "SOURCE_BOOKS_NOT_AVAILABLE"),
        "warning": "NOT a backtest of filled orders. Each row is a "
                   "counterfactual quote-based cost scenario at one original "
                   "saved book, not an independent trade. We have NO "
                   "execution events, queue position or observed two-sided "
                   "fills; do not compound snapshots or calculate realized P&L.",
        "read_only": True,
    }
