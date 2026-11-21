"""Read-only, source-grounded local acceptance for BANKNIFTY trading research.

No provider requests, downloads, order placement, schema mutation or synthetic
market records. Network Dhan authentication is checked separately via the
existing authenticated /api/dhan/credentials/check endpoint on user action.
This report is intentionally safe to share: no URLs, raw packets, tokens,
client IDs, instrument paths, exact private account data or prices.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import sqlite3

from . import auto_option_depth, cockpit_sources, option_chain_live, shared_market_data

MAX_AUDIT_BOOKS = 200
REQUIRED_TABLES = {"live_depth_books", "auto_banknifty_depth_features"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(stamp: str | None) -> str | None:
    if not isinstance(stamp, str):
        return None
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _pair_rejection_reason(book: dict | None, feature: dict | None,
                           stored_sha: str, derived_sha: str,
                           identity: str, session_id: str,
                           received_utc: str) -> str | None:
    """Return one safe, aggregate-able reason; never reveal original book data.

    Keep the original strict acceptance contract. These codes explain an
    invalid historical receipt, but do not certify or repair it.
    """
    if book is None:
        return "missing_original_book"
    if not isinstance(book, dict):
        return "invalid_book_structure"
    if not isinstance(feature, dict):
        return "invalid_feature_structure"
    if (book.get("identity") != identity
            or feature.get("identity") != identity
            or book.get("received_utc") != received_utc
            or feature.get("received_utc") != received_utc):
        return "identity_or_timestamp_mismatch"
    if (book.get("collection_mode") != "auto_banknifty_20_level"
            or book.get("source") != "original_Dhan_full_market_depth_websocket"
            or not book.get("full_depth")):
        return "source_provenance_mismatch"
    if not (isinstance(stored_sha, str) and isinstance(derived_sha, str)
            and len(stored_sha) == 64 and stored_sha == derived_sha):
        return "stored_receipt_digest_mismatch"
    raw_bid = book.get("bid_packet_sha256")
    raw_ask = book.get("ask_packet_sha256")
    if not (isinstance(raw_bid, str) and isinstance(raw_ask, str)
            and len(raw_bid) == 64 and len(raw_ask) == 64):
        return "missing_packet_digests"
    if sha256((raw_bid + raw_ask).encode()).hexdigest() != stored_sha:
        return "packet_pair_digest_mismatch"
    if (not isinstance(book.get("bid"), list)
            or not isinstance(book.get("ask"), list)
            or len(book["bid"]) != 20 or len(book["ask"]) != 20):
        return "incomplete_twenty_level_book"
    if feature.get("side") not in ("CE", "PE"):
        return "invalid_feature_side"
    if not isinstance(feature.get("units"), int) or feature["units"] <= 0:
        return "invalid_feature_units"
    for side in ("bid", "ask"):
        for level in book[side]:
            if not isinstance(level, dict):
                return "invalid_level_structure"
            price = level.get("price")
            qty = level.get("quantity")
            if (not isinstance(price, (int, float)) or
                    not isinstance(qty, int) or price <= 0 or qty < 0):
                return "invalid_level_values"
    if book["bid"][0]["price"] > book["ask"][0]["price"]:
        return "crossed_top_of_book"
    if not isinstance(session_id, str) or not session_id.startswith("auto20_"):
        return "unexpected_session_id"
    return None


def _valid_pair(book: dict, feature: dict, stored_sha: str, derived_sha: str,
                identity: str, session_id: str, received_utc: str) -> bool:
    """Backward-compatible strict integrity gate."""
    return _pair_rejection_reason(
        book, feature, stored_sha, derived_sha,
        identity, session_id, received_utc) is None

def inspect_saved_books(db_path: Path | None = None) -> dict:
    """Read up to 200 of the latest original automatic 20-level samples.

    The sample is an integrity check, not an audit of every saved record.
    Never initializes or rewrites the shared market database.
    """
    path = Path(db_path) if db_path is not None else shared_market_data.database_path()
    empty = {
        "status": "not_recorded", "total_automatic_books": 0,
        "latest_book_utc": None, "sample_checked": 0,
        "valid_sample_books": 0, "invalid_sample_books": 0,
        "valid_ce_books": 0, "valid_pe_books": 0,
        "invalid_reason_counts": {},
        "observed_trading_dates_in_sample": 0,
        "method": "read-only SQLite; recent paired original packets and SHA-256 receipts",
        "sample_limit": MAX_AUDIT_BOOKS,
        "note": "No exchange depth entitlement can be inferred from an empty local database.",
    }
    if not path.is_file() or path.is_symlink():
        return empty
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                                     uri=True, timeout=3)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=3000")
        present = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if not REQUIRED_TABLES <= present:
            return empty
        count, latest = connection.execute(
            "SELECT COUNT(*), MAX(received_utc) "
            "FROM auto_banknifty_depth_features").fetchone()
        if not count:
            return empty
        data = connection.execute(
            """SELECT f.identity, f.received_utc, f.session_id,
                      f.feature_json, f.book_pair_sha256,
                      b.book_json, b.packet_pair_sha256
               FROM auto_banknifty_depth_features AS f
               LEFT JOIN live_depth_books AS b
                 ON b.identity = f.identity
                AND b.received_utc = f.received_utc
                AND b.session_id = f.session_id
               ORDER BY f.received_utc DESC LIMIT ?""",
            (MAX_AUDIT_BOOKS,),
        ).fetchall()
        sides = Counter()
        dates = set()
        invalid_reasons = Counter()
        for identity, received, session_id, feat_raw, feat_sha, book_raw, book_sha in data:
            try:
                feature = json.loads(feat_raw)
                book = json.loads(book_raw) if book_raw else None
            except (ValueError, TypeError):
                invalid_reasons["unparseable_saved_json"] += 1
                continue
            reason = _pair_rejection_reason(
                book, feature, book_sha, feat_sha,
                identity, session_id, received)
            if reason is not None:
                invalid_reasons[reason] += 1
                continue
            sides[feature["side"]] += 1
            dates.add(received[:10])
        invalid = sum(invalid_reasons.values())
        return {
            **empty, "status": "verified_sample" if not invalid else "integrity_attention",
            "total_automatic_books": int(count),
            "latest_book_utc": _iso(latest),
            "sample_checked": len(data),
            "valid_sample_books": len(data) - invalid,
            "invalid_sample_books": invalid,
            "valid_ce_books": sides["CE"], "valid_pe_books": sides["PE"],
            "invalid_reason_counts": dict(sorted(invalid_reasons.items())),
            "observed_trading_dates_in_sample": len(dates),
            "note": ("Integrity is verified only for the latest sampled records. "
                     "Saved packets prove historical receipt, not current entitlement, "
                     "exchange timestamp accuracy or executable broker fills."),
        }
    except (sqlite3.Error, OSError, ValueError):
        return {**empty, "status": "inspection_unavailable",
                "note": ("The existing local source database could not be read safely. "
                         "Open Data Library > Data Manager > Activity & recovery. "
                         "No source files were modified.")}
    finally:
        if connection is not None:
            connection.close()


def _check(code: str, title: str, state: str,
           detail: str, next_action: str, screen: str) -> dict:
    return {"code": code, "title": title, "status": state,
            "detail": detail, "next_action": next_action, "screen": screen}


def report() -> dict:
    """Generate a small, non-secret, read-only acceptance summary."""
    now = _utc_now()
    checks = []

    try:
        catalog = cockpit_sources.catalog(limit=30)
        bank = next((x for x in catalog["instruments"]
                     if x.get("identity") == "INDEX:BANKNIFTY"), {})
        ready = bool(bank.get("ready"))
        checks.append(_check(
            "banknifty_history", "BANKNIFTY one-minute history",
            "pass" if ready else "action_needed",
            ("Original verified BANKNIFTY one-minute source is prepared."
             if ready else "No prepared original BANKNIFTY spot index source."),
            ("Open Options Backtest and run the selected historical period."
             if ready else "Open Connections > Get missing index spot candles."),
            "backtest" if ready else "connections"))
    except (ValueError, OSError, sqlite3.Error):
        checks.append(_check(
            "banknifty_history", "BANKNIFTY one-minute history", "not_verified",
            "The local index-source catalog was unavailable.",
            "Open Data Library and inspect the original minute source.", "connections"))

    try:
        master = option_chain_live._contracts()
        counts = Counter(row.get("option_type")
                         for row in master.get("by_id", {}).values())
        verified = bool(master.get("available") and master.get("fresh")
                        and counts["CE"] and counts["PE"])
        checks.append(_check(
            "contract_master", "Verified CE/PE instrument master",
            "pass" if verified else "action_needed",
            (f"Local master is fresh; {counts['CE']} CE and {counts['PE']} PE "
             "BANKNIFTY contract IDs are identified."
             if verified else
             "Original Dhan master is stale or lacks verified BANKNIFTY CE/PE identities."),
            ("Open Live Trading > Option Chain to inspect current strikes."
             if verified else
             "Open Data Library to refresh the official Dhan master; "
             "the automatic recorder also refreshes it after arming."),
            "live" if verified else "connections"))
    except (ValueError, OSError):
        checks.append(_check(
            "contract_master", "Verified CE/PE instrument master", "not_verified",
            "The official instrument master could not be safely read.",
            "Open Data Library and refresh the original Dhan master.", "connections"))

    live = auto_option_depth.status()
    armed = bool(live.get("armed"))
    market = bool(live.get("market_regular_hours"))
    pairs = int(live.get("received_pairs") or 0)
    latest = live.get("latest") or {}
    fresh = sum(1 for v in latest.values()
                if v.get("fresh") and v.get("full_20_levels")
                and v.get("bid_levels") == 20 and v.get("ask_levels") == 20)
    if market:
        if fresh:
            state = "pass"
            detail = f"{fresh} selected contracts have fresh original 20+20 depth."
        elif not armed:
            state, detail = "action_needed", "Automatic recorder is disarmed."
        elif live.get("connected") and not pairs:
            state, detail = "waiting", "Socket connected, but no verified bid/ask packet pairs yet."
        else:
            state = "waiting"
            detail = "Recorder is armed, but current original 20-level packets are not verified."
        action = ("Open Live Trading and inspect the 20-level recorder. "
                  "If armed but no packets arrive, check Dhan full-depth entitlement.")
    else:
        state = "waiting"
        detail = ("Outside regular NSE weekday hours; a live 20-level packet "
                  "cannot be verified now." + (" Recorder is armed." if armed
                                               else " Recorder is disarmed."))
        action = ("Arm the recorder in Live Trading and keep this local "
                  "QuantLab server running during the next NSE session.")
    checks.append(_check(
        "live_depth", "Live 20-level CE/PE capture", state,
        detail, action, "live"))

    books = inspect_saved_books()
    total = books["total_automatic_books"]
    if books["status"] == "integrity_attention":
        state = "action_needed"
        counts = books.get("invalid_reason_counts") or {}
        top_causes = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        causes = ", ".join(f"{reason}={count}" for reason, count in top_causes)
        detail = (f"{books['invalid_sample_books']} of the latest "
                  f"{books['sample_checked']} original book receipts failed integrity checks."
                  + (f" Causes: {causes}." if causes else ""))
        action = ("Inspect Data Manager > Activity & recovery. Preserve original "
                  "records; do not discard or reconstruct failed order books.")
    elif books["status"] == "inspection_unavailable":
        state = "not_verified"
        detail = "The local shared database could not be read safely."
        action = "Open Data Manager > Activity & recovery before further collection."
    elif total:
        both_sides = bool(books["valid_ce_books"] and books["valid_pe_books"])
        state = "pass" if both_sides else "partial"
        detail = (
            f"{total} automatic books saved; "
            f"{books['valid_sample_books']}/{books['sample_checked']} latest receipts "
            f"validated, including {books['valid_ce_books']} CE and "
            f"{books['valid_pe_books']} PE books in the inspected sample.")
        action = ("Open Market Replay > Recorded 20-level books and inspect both sides."
                  if both_sides else
                  "Keep recording during market hours until both CE and PE "
                  "source books are represented.")
    else:
        state, detail = "not_recorded", "No original automatically recorded 20-level books found."
        action = "Arm live recording and collect genuine Dhan bid+ask packets."
    checks.append(_check(
        "stored_depth", "Saved original 20-level evidence",
        state, detail, action, "replay"))

    checks.append(_check(
        "options_reversal", "Historical option P&L and CE/PE reversals",
        "requires_backtest",
        "No historical-options backtest is executed by this read-only check.",
        "Open Options Backtest > Run, then download its safe diagnostics. "
        "Inspect opposite-signal exits, replacement attempts and completed flips.",
        "backtest"))

    checks.append(_check(
        "options_learning", "Supervised and reinforcement learning for CE/PE",
        "research_pending",
        "The source audit is implemented. A trained, independently evaluated "
        "CE/PE RL policy is not yet available.",
        "Expand original option history beyond the current sample, test "
        "baselines on later unseen sessions, and collect depth prospectively.",
        "backtest"))

    return {
        "checked_utc": now.isoformat(),
        "version": "banknifty_local_acceptance_v1",
        "safe_to_share": True,
        "read_only": True,
        "external_api_requests": 0,
        "orders_placed": 0,
        "credentials_checked_separately": True,
        "market_regular_hours_ist": market,
        "recorder_armed": armed,
        "recorder_state": str(live.get("state") or "unknown"),
        "saved_books": books,
        "checks": checks,
        "note": ("Only this machine's local original-source evidence was read. "
                 "Live account authentication is checked separately in the UI. "
                 "Market-hours packet receipt is not established by a connected "
                 "WebSocket or by historical one-minute candles."),
    }
