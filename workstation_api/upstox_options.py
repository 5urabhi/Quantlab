"""Optional Upstox read-only current option chains; no order or account endpoints.

Supports two index underlyings through fixed first-party Upstox API URLs.
Local manual access tokens (or UPSTOX_ACCESS_TOKEN) never appear in HTTP
responses, logs, source receipts, browser storage or GitHub.
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from hashlib import sha256
from pathlib import Path
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo
import json
import math
import os
import re
import time

from . import option_chain_live, service

IST = ZoneInfo("Asia/Kolkata")
UNDERLYINGS = {
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "NIFTY50": "NSE_INDEX|Nifty 50",
}
HOST = "https://api.upstox.com"
ENDPOINTS = {
    "contracts": "/v2/option/contract",
    "chain": "/v2/option/chain",
}
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~+/-]{16,4096}$")
OPTION_KEY = re.compile(r"^NSE_FO\|[0-9]{1,12}$")
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
MAX_CONTRACTS = 18_000
MAX_CHAIN_STRIKES = 4000
CONTRACT_TTL = 300
CHAIN_TTL = 20
LOCK = RLock()
_CACHE: dict[tuple, tuple[float, dict]] = {}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Upstox endpoint redirected; credentials not forwarded")


def _root() -> Path:
    base = service.DATA / "research_workspace" / "upstox"
    if base.is_symlink() or base.parent.is_symlink():
        raise ValueError("Unsafe Upstox credential folder")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    return base


def _token() -> str:
    path = _root() / "read_only_token.json"
    if path.is_symlink():
        raise ValueError("Unsafe Upstox credential path")
    if path.is_file() and path.stat().st_size <= 5000:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            candidate = record.get("token", "") if isinstance(record, dict) else ""
            if isinstance(candidate, str) and TOKEN_PATTERN.fullmatch(candidate):
                return candidate
        except (OSError, ValueError, UnicodeError):
            pass
    value = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    return value if TOKEN_PATTERN.fullmatch(value) else ""


def configured() -> bool:
    """Local configuration only; not a claim that the session is authenticated."""
    return bool(_token())


def configure(token: str, *, confirm_local_storage: bool) -> dict:
    if not confirm_local_storage:
        raise ValueError("Explicit consent to private local token storage is required")
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Enter a valid manually generated Upstox API access token")
    path = _root() / "read_only_token.json"
    temp = path.with_name("read_only_token.tmp")
    if path.is_symlink() or temp.is_symlink():
        raise ValueError("Unsafe Upstox credential path")
    with LOCK:
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"token": token}, stream)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        _CACHE.clear()
    return {"provider": "upstox", "configured": True,
            "session_verified": False, "local_private_storage": True,
            "read_only": True, "secrets_returned": False,
            "next_action": "Refresh expiries to check whether this token can read option contracts."}


def disconnect(*, confirm: bool) -> dict:
    if not confirm:
        raise ValueError("Confirm disconnecting Upstox")
    with LOCK:
        path = _root() / "read_only_token.json"
        if path.is_symlink():
            raise ValueError("Unsafe Upstox credential path")
        if path.is_file():
            path.unlink()
        _CACHE.clear()
    return {"provider": "upstox", "local_token_removed": True,
            "environment_token_still_configured": bool(
                TOKEN_PATTERN.fullmatch(os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()))}


def status() -> dict:
    return {"id": "upstox", "label": "Upstox",
            "configured": configured(), "session_verified": False,
            "mode": "current_option_chain_and_active_contracts",
            "read_only": True,
            "historical_expired_entitlement": "not_verified",
            "note": "Current option contract and chain API only; historical expired "
                    "contracts/candles require separate availability and plan checks."}


def _http(kind: str, underlying: str, expiry: str = "") -> dict:
    """Fixed host + bounded fixed path and supplied source date only."""
    if kind not in ENDPOINTS or underlying not in UNDERLYINGS:
        raise ValueError("Unsupported authorized option chain source")
    if kind == "chain":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry):
                raise ValueError("Select an original, valid expiry date")
            date.fromisoformat(expiry)
        except ValueError:
            raise ValueError("Select an original, valid expiry date") from None
    token = _token()
    if not token:
        raise ValueError("Connect an Upstox access token in the QuantLab Option Chain panel")
    query = {"instrument_key": UNDERLYINGS[underlying]}
    if kind == "chain":
        query["expiry_date"] = expiry
    url = HOST + ENDPOINTS[kind] + "?" + urlencode(query)
    request = Request(url, headers={"Authorization": "Bearer " + token,
                                   "Accept": "application/json",
                                   "User-Agent": "QuantLab-ReadOnly-OptionCoverage/1.0"},
                      method="GET")
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=18)
        with response as stream:
            if stream.status != 200:
                raise ValueError("Upstox did not approve this read-only market-data request")
            raw = stream.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Upstox returned an unexpectedly large option-chain response")
        parsed = json.loads(raw)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("Upstox session expired, access denied, or required plan unavailable") from None
        if exc.code == 429:
            raise ValueError("Upstox rate limit reached; cached sources are preserved") from None
        raise ValueError("Upstox option-chain request failed (HTTP status "
                         + str(exc.code) + ")") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Cannot reach Upstox; cached original Dhan observations remain unchanged") from None
    except (UnicodeError, ValueError, TypeError):
        raise ValueError("Upstox returned an unreadable market-data response") from None
    if not isinstance(parsed, dict) or parsed.get("status") != "success":
        raise ValueError("Upstox did not return a successful option-chain response")
    return parsed


def _float(raw: object, positive: bool = False) -> float | None:
    try:
        number = float(raw)
        if math.isfinite(number) and (not positive or number > 0):
            return number
    except (TypeError, ValueError):
        pass
    return None


def _integer(raw: object, positive: bool = False) -> int | None:
    number = _float(raw)
    if number is not None and number.is_integer() and (number > 0 if positive else number >= 0) and number <= 2**53-1:
        return int(number)
    return None


def _catalog(raw: dict, underlying: str, *, captured: datetime) -> dict:
    records = raw.get("data")
    if not isinstance(records, list) or len(records) > MAX_CONTRACTS:
        raise ValueError("Upstox option catalog is unavailable or unexpectedly large")
    valid = {}
    now = captured.astimezone(IST).date()
    for row in records:
        if not isinstance(row, dict):
            continue
        if (row.get("exchange") != "NSE" or row.get("segment") != "NSE_FO"
                or row.get("underlying_key") != UNDERLYINGS[underlying]
                or row.get("instrument_type") not in ("CE", "PE")):
            continue
        key = row.get("instrument_key")
        exchange_token = str(row.get("exchange_token", "")).strip()
        exp = row.get("expiry")
        strike = _float(row.get("strike_price"), positive=True)
        lot = _integer(row.get("lot_size"), positive=True)
        try:
            expiry_date = date.fromisoformat(exp) if isinstance(exp, str) else None
        except ValueError:
            continue
        if (not isinstance(key, str) or not OPTION_KEY.fullmatch(key)
                or key.rsplit("|", 1)[-1] != exchange_token
                or expiry_date is None or expiry_date < now or strike is None
                or lot is None or lot > 1_000_000):
            continue
        valid[key] = {
            "instrument_key": key, "exchange_token": exchange_token,
            "strike": round(strike, 4), "expiry": expiry_date.isoformat(),
            "option_type": row["instrument_type"], "lot_size": lot,
            "symbol": str(row.get("trading_symbol", ""))[:100],
        }
    return {"underlying": underlying, "contracts": valid,
            "expiries": sorted({row["expiry"] for row in valid.values()}),
            "received_utc": captured.isoformat(),
            "source": "Upstox v2 original option contract catalog",
            "read_only": True}


def contracts(underlying: str = "BANKNIFTY") -> dict:
    if underlying not in UNDERLYINGS:
        raise ValueError("Supported indices: BANKNIFTY and NIFTY50")
    token = _token()
    if not token:
        raise ValueError("Upstox local token is not configured")
    key = ("contracts", underlying, sha256(token.encode()).hexdigest())
    now = time.monotonic()
    with LOCK:
        stored = _CACHE.get(key)
        if stored and now - stored[0] < CONTRACT_TTL:
            return {**stored[1], "cache_hit": True}
        result = _catalog(_http("contracts", underlying), underlying,
                          captured=datetime.now(timezone.utc))
        if not result["expiries"]:
            raise ValueError("Upstox returned no verified active option contracts for this index")
        _CACHE[key] = (now, result)
        return {**result, "cache_hit": False}


def _normalize_chain(raw: dict, underlying: str, expiry: str,
                     catalog: dict, master: dict,
                     captured: datetime) -> dict:
    rows = raw.get("data")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_CHAIN_STRIKES:
        raise ValueError("Upstox returned an empty or oversized original option chain")
    saved = []
    source_spot = None
    for row in rows:
        if not isinstance(row, dict) or row.get("expiry") != expiry:
            continue
        if row.get("underlying_key") != UNDERLYINGS[underlying]:
            continue
        strike = _float(row.get("strike_price"), positive=True)
        spot = _float(row.get("underlying_spot_price"), positive=True)
        if strike is None or spot is None:
            continue
        if source_spot is None:
            source_spot = spot
        for direction, field in (("CE", "call_options"), ("PE", "put_options")):
            option = row.get(field)
            if not isinstance(option, dict):
                continue
            key = option.get("instrument_key")
            official = catalog["contracts"].get(key)
            if (not isinstance(key, str) or not official
                    or official["expiry"] != expiry
                    or official["strike"] != round(strike, 4)
                    or official["option_type"] != direction):
                continue
            quote = option.get("market_data")
            greeks = option.get("option_greeks")
            quote = quote if isinstance(quote, dict) else {}
            greeks = greeks if isinstance(greeks, dict) else {}
            bid = _float(quote.get("bid_price"), positive=True)
            ask = _float(quote.get("ask_price"), positive=True)
            valid = bool(bid is not None and ask is not None and bid <= ask)
            candidate = master.get("by_id", {}).get(official["exchange_token"])
            corroborated = bool(
                master.get("fresh") and candidate
                and candidate["expiry"] == expiry
                and candidate["option_type"] == direction
                and candidate["strike"] == round(strike, 4)
                and candidate["lot_size"] == official["lot_size"])
            size = official["lot_size"] if corroborated else None
            saved.append({
                "identity": candidate["identity"] if corroborated else None,
                "provider_instrument_key": key,
                "symbol": official["symbol"],
                "strike": strike, "expiry": expiry, "option_type": direction,
                "lot_size": size, "provider_lot_size": official["lot_size"],
                "contract_master_verified": corroborated,
                "bid": bid, "ask": ask, "ltp": _float(quote.get("ltp"), positive=True),
                "top_bid_quantity": _integer(quote.get("bid_qty")),
                "top_ask_quantity": _integer(quote.get("ask_qty")),
                "oi": _integer(quote.get("oi")),
                "volume": _integer(quote.get("volume")),
                "iv": _float(greeks.get("iv")),
                "delta": _float(greeks.get("delta")),
                "theta": _float(greeks.get("theta")),
                "gamma": _float(greeks.get("gamma")),
                "vega": _float(greeks.get("vega")),
                "quote_valid": valid, "one_lot_ask_inr": round(ask*size, 2)
                    if valid and size is not None else None,
                "one_lot_bid_inr": round(bid*size, 2)
                    if valid and size is not None else None,
                "spread_inr_per_lot": round((ask-bid)*size, 2)
                    if valid and size is not None else None,
                "quote_provider": "upstox",
                "source_received_utc": captured.isoformat(),
                "available_sources": ["upstox"],
            })
    if not saved or source_spot is None:
        raise ValueError("Upstox returned no source-catalog-matched current CE/PE contracts")
    return {
        "underlying": underlying, "underlying_identity": "INDEX:"+underlying,
        "underlying_spot": source_spot, "expiry": expiry,
        "received_utc": captured.isoformat(),
        "source": "Upstox v2 original read-only option chain",
        "source_clock": "local_received_utc_not_exchange_quote_time",
        "not_live_stream": True,
        "market_master_fresh": bool(master.get("fresh")),
        "master_message": master.get("message", ""),
        "master_age_hours": master.get("age_hours"),
        "contracts": saved,
        "quote_count": len(saved),
        "strike_count": len({row["strike"] for row in saved}),
        "read_only": True,
        "warning": ("Provider quotes are not broker fills. Dhan 20-level depth identity and "
                    "lot-based previews require exact exchange-token AND fresh Dhan "
                    "instrument-master agreement."),
    }


def chain(underlying: str, expiry: str, *, force_refresh: bool = False) -> dict:
    if underlying not in UNDERLYINGS:
        raise ValueError("Unsupported index option underlying")
    if not isinstance(expiry, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry):
        raise ValueError("Invalid option expiry")
    record = contracts(underlying)
    if expiry not in record["expiries"]:
        raise ValueError("Expiry not reported in Upstox's current original contract catalog")
    token = _token()
    cache_key = ("chain", underlying, expiry, sha256(token.encode()).hexdigest())
    now = time.monotonic()
    with LOCK:
        stored = _CACHE.get(cache_key)
        if stored and not force_refresh and now-stored[0] < CHAIN_TTL:
            return {**stored[1], "cache_hit": True}
        master = option_chain_live._contracts() if underlying == "BANKNIFTY" else {
            "available": False, "fresh": False, "by_id": {},
            "message": "NIFTY50 Dhan lot/depth identity cross-check is not yet available",
            "age_hours": None,
        }
        normalized = _normalize_chain(
            _http("chain", underlying, expiry), underlying, expiry, record,
            master, datetime.now(timezone.utc))
        _CACHE[cache_key] = (now, normalized)
        return {**normalized, "cache_hit": False}


def reset_for_tests() -> None:
    with LOCK:
        _CACHE.clear()
