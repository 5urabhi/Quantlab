"""Read-only, contract-master reconciled BANKNIFTY option chain.

The Dhan chain is a snapshot, not a continuous WebSocket and not a fill.
The 20-level order book is provided separately by live_market and must match
the exact NSE_FNO security ID chosen here. No orders, credentials or
personal account data are exposed to the browser.
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo
import csv
import json
import math
import os
import re
import sqlite3
import time

from . import dhan_option_chain, dhan_workspace, shared_market_data

IST = ZoneInfo("Asia/Kolkata")
LOCK = RLock()
EXPIRY_TTL_SECONDS = 300
CHAIN_TTL_SECONDS = 10
MIN_CHAIN_INTERVAL_SECONDS = 3.15
MAX_MASTER_BYTES = 100_000_000
_EXPIRY_CACHE: dict = {}
_CHAIN_CACHE: dict = {}
_LAST_VENDOR_CALL = 0.0
_LAST_PERSISTED: dict = {}


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _credentials() -> tuple[str, str]:
    token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    if not token or len(token) > 4096:
        raise ValueError("Connect a valid Dhan access token in Trading Cockpit > Connections")
    return token, dhan_option_chain._client_id(token)


def _auth_key(token: str) -> str:
    # Not returned; prevents accidental reuse across credential rotations.
    return sha256(token.encode()).hexdigest()


def _fields(reader: csv.DictReader) -> dict[str, str]:
    return {str(field).strip().upper(): field for field in (reader.fieldnames or [])}


def _get_field(columns: dict[str, str], *names: str) -> str | None:
    return next((columns[name] for name in names if name in columns), None)


@lru_cache(maxsize=4)
def _master_lookup(name: str, mtime_ns: int, size: int) -> dict:
    """Reconcile exactly listed NSE BANKNIFTY OPTIDX contracts by security ID."""
    entries = {}
    by_terms: dict[tuple[str, float, str], list[dict]] = {}
    with Path(name).open("r", encoding="utf-8-sig", newline="") as fd:
        reader = csv.DictReader(fd)
        c = _fields(reader)
        sec = _get_field(c, "SECURITY_ID", "SEM_SMST_SECURITY_ID")
        exch = _get_field(c, "EXCH_ID", "SEM_EXM_EXCH_ID")
        seg = _get_field(c, "SEGMENT", "SEM_SEGMENT")
        kind = _get_field(c, "INSTRUMENT", "SEM_INSTRUMENT_NAME")
        sym = _get_field(c, "TRADING_SYMBOL", "SEM_TRADING_SYMBOL",
                         "SYMBOL_NAME", "SM_SYMBOL_NAME", "SEM_CUSTOM_SYMBOL", "DISPLAY_NAME")
        # Compact scrip master has several human-readable columns. A field
        # may exist in the header but be blank for BANKNIFTY derivatives.
        # Do not discard a legitimate F&O contract just because the first
        # preferred field is blank or uses the display alias 'NIFTY BANK'.
        name_fields = [c[name] for name in (
            "SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "SM_SYMBOL_NAME",
            "SYMBOL_NAME", "SEM_CUSTOM_SYMBOL", "DISPLAY_NAME",
            "UNDERLYING_SYMBOL") if name in c]
        lot = _get_field(c, "LOT_SIZE", "SEM_LOT_UNITS")
        expiry = _get_field(c, "SM_EXPIRY_DATE", "EXPIRY_DATE", "SEM_EXPIRY_DATE")
        strike = _get_field(c, "STRIKE_PRICE", "SEM_STRIKE_PRICE")
        opt = _get_field(c, "OPTION_TYPE", "SEM_OPTION_TYPE")
        underlying = _get_field(c, "UNDERLYING_SYMBOL")
        if not all((sec, exch, seg, kind, sym, lot, expiry, strike, opt)):
            return {"available": False, "by_id": {}, "by_terms": {},
                    "message": "The local Dhan master lacks derivative lot, expiry, strike or security ID columns. Refresh the detailed/compact master."}
        for row in reader:
            if (row[exch].strip().upper() != "NSE"
                    or row[seg].strip().upper() not in ("D", "NSE_FNO", "FNO", "F")
                    or row[kind].strip().upper() != "OPTIDX"):
                continue
            labels = [str(row[field]).strip() for field in name_fields]
            label = next((value for value in ([str(row[sym]).strip()] + labels)
                          if value), "")
            joined = " ".join(labels).upper().replace("-", " ").replace("_", " ")
            if "BANKNIFTY" not in joined and "NIFTY BANK" not in joined:
                continue
            identifier = row[sec].strip()
            direction = row[opt].strip().upper()
            if direction not in ("CE", "PE") or not re.fullmatch(r"[0-9]{1,12}", identifier):
                continue
            try:
                exp = date.fromisoformat(row[expiry].strip()[:10]).isoformat()
                price = float(row[strike])
                size = int(float(row[lot]))
            except (ValueError, TypeError):
                continue
            if not math.isfinite(price) or price <= 0 or not 1 <= size <= 1_000_000:
                continue
            item = {"identity": "NSE_FNO:" + identifier,
                    "security_id": identifier, "symbol": label[:100],
                    "strike": round(price, 4), "option_type": direction,
                    "expiry": exp, "lot_size": size}
            entries[identifier] = item
            by_terms.setdefault((exp, round(price, 4), direction), []).append(item)
    return {
        "available": bool(entries), "by_id": entries, "by_terms": by_terms,
        "matched_banknifty_option_contracts": len(entries),
        "message": ("Official Dhan instrument master contains verified "
                    f"BANKNIFTY contract IDs ({len(entries)} records)."
                    if entries else
                    "The Dhan instrument master parsed successfully but "
                    "contained ZERO matching NSE_FNO BANKNIFTY OPTIDX contracts. "
                    "Check option symbols, expiry, strike, and lot-size columns "
                    "or refresh the official master."),
    }


def _contracts() -> dict:
    path = dhan_workspace._master()
    if not path.is_file() or path.is_symlink():
        return {"available": False, "by_id": {}, "by_terms": {},
                "message": "Download the official Dhan instrument master in Data Library to verify lot size and exact security IDs."}
    stat = path.stat()
    if stat.st_size > MAX_MASTER_BYTES:
        raise ValueError("Dhan master file is too large; refresh the source in Data Library")
    found = _master_lookup(str(path), stat.st_mtime_ns, stat.st_size)
    # Market lot can change at expiry; an old master must never silently
    # authorize a capital/quantity estimate on a current instrument.
    age_hours = max(0, (_clock().timestamp() - stat.st_mtime) / 3600)
    return {**found, "age_hours": round(age_hours, 1),
            "fresh": age_hours <= 48}


def _finite(value: object, *, positive: bool = False) -> float | None:
    try:
        x = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(x) or (positive and x <= 0):
        return None
    return x


def _count(value: object) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and 0 <= number <= 2**53 - 1 else None


def _safe_contract(quote: dict, expiry: str, strike: float,
                   side: str, master: dict) -> dict | None:
    identity = None
    raw_id = str(quote.get("security_id", "")).strip()
    candidate = None
    if re.fullmatch(r"[0-9]{1,12}", raw_id):
        candidate = master["by_id"].get(raw_id)
    elif not raw_id:
        matches = master["by_terms"].get((expiry, round(strike, 4), side), [])
        candidate = matches[0] if len(matches) == 1 else None
    if candidate and (candidate["expiry"] == expiry and
                      candidate["strike"] == round(strike, 4) and
                      candidate["option_type"] == side):
        identity = candidate["identity"]
    bid = _finite(quote.get("top_bid_price"), positive=True)
    ask = _finite(quote.get("top_ask_price"), positive=True)
    tradable_quote = bool(bid is not None and ask is not None and bid <= ask)
    # A stale master is useful for display but not a verified lot preview.
    master_ok = bool(candidate and master.get("fresh") and identity)
    size = candidate["lot_size"] if master_ok else None
    iv = _finite(quote.get("implied_volatility"))
    greeks = quote.get("greeks") if isinstance(quote.get("greeks"), dict) else {}
    return {
        "identity": identity if master_ok else None,
        "symbol": candidate["symbol"] if candidate else "",
        "strike": strike, "expiry": expiry, "option_type": side,
        "lot_size": size, "contract_master_verified": master_ok,
        "bid": bid, "ask": ask, "ltp": _finite(quote.get("last_price"), positive=True),
        "top_bid_quantity": _count(quote.get("top_bid_quantity")),
        "top_ask_quantity": _count(quote.get("top_ask_quantity")),
        "oi": _count(quote.get("oi")), "volume": _count(quote.get("volume")),
        "iv": iv, "delta": _finite(greeks.get("delta")),
        "theta": _finite(greeks.get("theta")),
        "gamma": _finite(greeks.get("gamma")),
        "vega": _finite(greeks.get("vega")),
        "quote_valid": tradable_quote,
        "one_lot_ask_inr": round(ask * size, 2)
        if tradable_quote and size is not None else None,
        "one_lot_bid_inr": round(bid * size, 2)
        if tradable_quote and size is not None else None,
        "spread_inr_per_lot": round((ask - bid) * size, 2)
        if tradable_quote and size is not None else None,
    }


def _normalize(raw: dict, expiry: str, captured: datetime, master: dict) -> dict:
    data = raw.get("data")
    if not isinstance(data, dict):
        raise ValueError("Dhan did not return a valid BANKNIFTY option-chain snapshot")
    spot = _finite(data.get("last_price"), positive=True)
    book = data.get("oc")
    if spot is None or not isinstance(book, dict) or len(book) > 3000 or not book:
        raise ValueError("Dhan returned no valid underlying spot or option strikes")
    strikes = []
    for value, pair in book.items():
        strike = _finite(value, positive=True)
        if strike is not None and isinstance(pair, dict):
            strikes.append((abs(strike - spot), strike, pair))
    strikes.sort(key=lambda item: (item[0], item[1]))
    normalized = []
    for _, strike, pair in strikes:
        for field, side in (("ce", "CE"), ("pe", "PE")):
            quote = pair.get(field)
            if not isinstance(quote, dict):
                continue
            normalized.append(_safe_contract(quote, expiry, strike, side, master))
    if not normalized:
        raise ValueError("Dhan option chain has no usable call or put contracts")
    return {
        "underlying": "BANKNIFTY", "underlying_identity": "INDEX:BANKNIFTY",
        "underlying_spot": spot, "expiry": expiry,
        "received_utc": captured.isoformat(), "source": "Dhan v2 read-only optionchain snapshot",
        "source_clock": "local_received_utc_not_exchange_quote_time",
        "not_live_stream": True, "market_master_fresh": bool(master.get("fresh")),
        "master_message": master.get("message", ""), "master_age_hours": master.get("age_hours"),
        "contracts": normalized, "quote_count": len(normalized),
        "strike_count": len(strikes), "source_strike_count": len(book),
        "read_only": True,
        "warning": "Dhan chain is a REST snapshot, NOT a 20-level WebSocket; option bid/ask may already have changed. Exact lot size and security ID require the current official local master.",
    }


def _save_snapshot(value: dict) -> None:
    """Append bounded normalized evidence to the existing one Market Library."""
    now = _clock().timestamp()
    key = ("BANKNIFTY", value["expiry"])
    if now - _LAST_PERSISTED.get(key, 0.0) < 30:
        return
    path = shared_market_data.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=8) as db:
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("""CREATE TABLE IF NOT EXISTS option_chain_observations(
          underlying TEXT NOT NULL, expiry TEXT NOT NULL,
          captured_utc TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
          normalized_json TEXT NOT NULL,
          PRIMARY KEY(underlying,expiry,captured_utc))""")
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        db.execute("""INSERT OR IGNORE INTO option_chain_observations
            VALUES(?,?,?,?,?)""", ("BANKNIFTY", value["expiry"],
            value["received_utc"], sha256(payload.encode()).hexdigest(), payload))
        db.commit()
    _LAST_PERSISTED[key] = now


def expiries(*, sleep=time.sleep) -> dict:
    """Read-only expiry discovery, cached. No trading API and no market inference."""
    global _LAST_VENDOR_CALL
    token, client = _credentials()
    auth = _auth_key(token)
    now = time.monotonic()
    key = ("BANKNIFTY", auth)
    with LOCK:
        prior = _EXPIRY_CACHE.get(key)
        if prior and now - prior[0] < EXPIRY_TTL_SECONDS:
            return {**prior[1], "cache_hit": True}
        body = {"UnderlyingScrip": 25, "UnderlyingSeg": "IDX_I"}
        delay = MIN_CHAIN_INTERVAL_SECONDS - (time.monotonic() - _LAST_VENDOR_CALL)
        if _LAST_VENDOR_CALL and delay > 0:
            sleep(delay)
        raw, _ = dhan_option_chain._json_http(
            dhan_option_chain.EXPIRY_ENDPOINT, token=token,
            client_id=client, body=body)
        _LAST_VENDOR_CALL = time.monotonic()
        candidates = raw.get("data")
        if not isinstance(candidates, list):
            raise ValueError("Dhan expirylist response is not a date list")
        current = _clock().astimezone(IST).date()
        expirations = sorted({
            val for val in candidates
            if isinstance(val, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", val)
            and _valid_expiry(val, current)
        })
        if not expirations:
            raise ValueError("Dhan provided no current BANKNIFTY expiries")
        result = {"underlying": "BANKNIFTY", "expiries": expirations[:40],
                  "nearest_expiry": expirations[0],
                  "received_utc": _clock().isoformat(),
                  "source": "Dhan v2 original expirylist",
                  "read_only": True, "cache_hit": False}
        _EXPIRY_CACHE[key] = (now, result)
        return result


def _valid_expiry(text: str, current: date) -> bool:
    try:
        return date.fromisoformat(text) >= current
    except ValueError:
        return False


def chain(expiry: str, *, force_refresh: bool = False, sleep=time.sleep) -> dict:
    global _LAST_VENDOR_CALL
    if not isinstance(expiry, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry):
        raise ValueError("Select an original Dhan expiry in YYYY-MM-DD form")
    token, client = _credentials()
    auth = _auth_key(token)
    now = time.monotonic()
    key = ("BANKNIFTY", expiry, auth)
    with LOCK:
        cached = _CHAIN_CACHE.get(key)
        if cached and not force_refresh and now - cached[0] < CHAIN_TTL_SECONDS:
            return {**cached[1], "cache_hit": True}
        if not _valid_expiry(expiry, _clock().astimezone(IST).date()):
            raise ValueError("Selected Dhan BANKNIFTY option has already expired")
        # Check against authoritative Dhan expirylist (cached) rather than
        # generating monthly/weekly dates from a calendar assumption.
        observed = expiries(sleep=sleep)
        if expiry not in observed["expiries"]:
            raise ValueError("Expiry is not in Dhan's current BANKNIFTY contract list")
        delay = MIN_CHAIN_INTERVAL_SECONDS - (time.monotonic() - _LAST_VENDOR_CALL)
        if delay > 0:
            sleep(delay)
        response, _ = dhan_option_chain._json_http(
            dhan_option_chain.CHAIN_ENDPOINT, token=token, client_id=client,
            body={"UnderlyingScrip": 25, "UnderlyingSeg": "IDX_I", "Expiry": expiry})
        _LAST_VENDOR_CALL = time.monotonic()
        source = _normalize(response, expiry, _clock(), _contracts())
        _CHAIN_CACHE[key] = (_LAST_VENDOR_CALL, source)
        _save_snapshot(source)
        return {**source, "cache_hit": False}


def _reset_for_tests() -> None:
    global _LAST_VENDOR_CALL
    with LOCK:
        _EXPIRY_CACHE.clear()
        _CHAIN_CACHE.clear()
        _LAST_PERSISTED.clear()
        _LAST_VENDOR_CALL = 0
        _master_lookup.cache_clear()
