"""Read-only BANKNIFTY spot-signal -> historical CE/PE candle backtest.

Dhan /v2/charts/rollingoption returns *rolling, ATM-relative* option bars.
We re-key by observed timestamp, actual STRIKE and option side, and never
follow an ATM offset across a trade. The endpoint does not prove a historical
expiry ID or exchange lot size, nor provide historical bid/ask or fills.
Results are conservative OHLC next-open execution proxies, not broker P&L.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time as clock_time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import math
import os
import time

from . import service, cockpit_sources, trading_cockpit, options_research_audit, liquidity_spreads as option_fees

IST = ZoneInfo("Asia/Kolkata")
ENDPOINT = "https://api.dhan.co/v2/charts/rollingoption"
MAX_RESPONSE_BYTES = 9_000_000
MAX_SOURCE_ROWS = 15_000
VALID_HOLDS = (1, 3, 5, 6, 10, 30, 60)
VALID_POLICIES = ("fixed", "signal_reversal", "signal_reversal_or_cap",
                  "premium_target_stop", "hybrid")
MAX_REQUESTS = 48
# Current listed options can span several BANKNIFTY index levels across
# a multi-day window; never reject all of them on the first unavailable ID.
MAX_ACTIVE_REQUESTS = 96
SIGNAL_MODELS = ("ema_rsi", "ema_crossover")
EMA_CROSSOVER_VERSION = "ema9_21_confirmed_cross_1m_v1"
REQUIRED = ("open", "high", "low", "close", "volume", "oi", "iv", "strike", "spot")


def _stamp(text: str) -> datetime:
    return trading_cockpit._ts(text)


def _validate_params(*, limit: int, expiry_flag: str, expiry_code: int,
                     wings: int, lot_size: int, lots: int, target_ltp: float,
                     tolerance: float, starting_capital: float, stop_pct: float,
                     target_pct: float, slippage_bps: float,
                     fee_per_side: float, hold_rule: str,
                     hold_minutes: int, reversal_cap_minutes: int,
                     signal_model: str = "ema_rsi", fee_mode: str = "flat") -> None:
    if fee_mode not in ("flat","zerodha","zerodha_debit_balance"):
        raise ValueError("Choose flat costs or current Zerodha tariff")
    if signal_model not in SIGNAL_MODELS:
        raise ValueError("Choose EMA/RSI or EMA 9/21 crossover for BANKNIFTY index signals")
    if limit not in (500, 1500, 3000, 5000):
        raise ValueError("Choose a supported original index history window")
    if expiry_flag not in ("MONTH", "WEEK") or expiry_code not in (0, 1, 2):
        raise ValueError("Choose original Dhan monthly/weekly and near/next/far expiry")
    if type(wings) is not int or not 0 <= wings <= 5:
        raise ValueError("Option strike wings must be between zero and five")
    if wings > 3 and expiry_code != 0:
        raise ValueError("Dhan permits ATM +/-4 or +/-5 index strikes only for current/near expiry; use ATM +/-3 for next/far expiry")
    if type(lots) is not int or not 1 <= lots <= 20:
        raise ValueError("Option quantity must be a whole number of 1 to 20 lots")
    if type(lot_size) is not int or not 1 <= lot_size <= 100:
        raise ValueError("Historical lot size assumption must be 1 to 100 units")
    vals = (target_ltp, tolerance, starting_capital, stop_pct, target_pct,
            slippage_bps, fee_per_side)
    if any(not math.isfinite(float(v)) for v in vals):
        raise ValueError("Options backtest inputs must be finite")
    if not (10 <= target_ltp <= 20_000 and 0 <= tolerance <= 5000
            and 1000 <= starting_capital <= 100_000_000
            and .1 <= stop_pct <= 50 and .1 <= target_pct <= 100
            and 0 <= slippage_bps <= 500 and 0 <= fee_per_side <= 1000):
        raise ValueError("Option premium, capital or cost settings are out of range")
    if hold_rule not in VALID_POLICIES or hold_minutes not in VALID_HOLDS:
        raise ValueError("Unsupported options exit rule or fixed hold")
    if type(reversal_cap_minutes) is not int or not 1 <= reversal_cap_minutes <= 120:
        raise ValueError("The signal-reversal time cap must be 1 to 120 minutes")


def _offsets(wings: int) -> list[str]:
    return ["ATM"] + [f"ATM{sign}{n}" for n in range(1, wings + 1)
                      for sign in ("+", "-")]


def _ist_today() -> date:
    """Single clock source for source-eligibility checks (testable offline)."""
    return datetime.now(IST).date()


def _calendar_month(year: int, month: int, offset: int = 0) -> tuple[int, int]:
    absolute = year * 12 + month - 1 + offset
    return absolute // 12, absolute % 12 + 1


def _nominal_monthly_expiry(year: int, month: int) -> date:
    """Conservative last-Tuesday bound; holiday moves expiries EARLIER.

    This is NOT proof of a particular NSE listed contract/actual expiry.
    It is only a guard against sending *unexpired* dates to Dhan's
    expired-options endpoint. Exact live expiries use the Dhan master.
    """
    nyear, nmonth = _calendar_month(year, month, 1)
    last = date(nyear, nmonth, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 1) % 7)


def _nominal_selected_expiry(session: date, expiry_code: int) -> date:
    """Earliest plausible monthly expiry for the near/next/far selector."""
    this = _nominal_monthly_expiry(session.year, session.month)
    forward = int(session > this) + expiry_code
    y, m = _calendar_month(session.year, session.month, forward)
    return _nominal_monthly_expiry(y, m)


def _expired_eligible(session: date, *, expiry_flag: str,
                      expiry_code: int, today: date) -> bool:
    """Fail closed: a current contract must never be sent to rollingoption.

    BANKNIFTY is monthly-only for recent dates. Historical weekly requests
    are outside the active-contract backtest workflow and cannot be guessed.
    """
    if expiry_flag != "MONTH":
        # BANKNIFTY weekly expiries were discontinued in 2024. Historic
        # eligible weekly sessions are already safely expired in 2026;
        # current-month weekly contracts must not be synthesized.
        return session < date(2024, 11, 20) and session < today
    # Next/far Bank Nifty expiries can skip calendar months because only
    # quarterly long-dated series are listed. Without archived listing
    # evidence a nominal next/far month is NOT proof of contract expiry.
    # The current Dhan master handles recent genuine listed contracts.
    # For rolling next/far only use substantially aged history rather than
    # risk asking an unexpired far-dated contract from rollingoption.
    if expiry_code in (1, 2) and (today - session).days <= 366:
        return False
    # Near expiry: require the conservative last Tuesday to be strictly in
    # the past; holiday shifts move it earlier, never later.
    return _nominal_selected_expiry(session, expiry_code) < today


def _chunks(first: date, last_exclusive: date):
    current = first
    while current < last_exclusive:
        following = min(last_exclusive, current + timedelta(days=30))
        yield current, following
        current = following


def _request_body(start: date, end: date, flag: str, code: int,
                  offset: str, side: str) -> dict:
    if not start < end or (end - start).days > 30:
        raise ValueError("Dhan expired option requests require up to 30 calendar days")
    # Dhan /charts/rollingoption has its OWN ordinal convention:
    # 1 = near, 2 = next, 3 = far. Other Dhan endpoints use 0/1/2.
    # Confirmed by Dhan support on 2026-01-30 (MadeForTrade #60509).
    # Preserve the 0/1/2 UI value for active-option contract selection.
    if code not in (0, 1, 2):
        raise ValueError("Rolling option expiry must be near, next or far")
    return {
        "exchangeSegment": "NSE_FNO", "interval": "1", "securityId": 25,
        "instrument": "OPTIDX", "expiryFlag": flag, "expiryCode": code + 1,
        "strike": offset, "drvOptionType": side,
        "requiredData": list(REQUIRED),
        "fromDate": start.isoformat(), "toDate": end.isoformat(),
    }


class RollingInputError(ValueError):
    """The provider explicitly rejected a rolling-option request (DH-905)."""


def _original_response(body: dict, *, opener=None, wire_state=None) -> dict:
    """Try equivalent documented REST/SDK encodings only on explicit DH-905.

    Canonical cache identity remains unchanged. Do not switch instruments,
    expiry ordinals, fields or strike semantics to obtain a successful reply.
    Remember the accepted representation for this acquisition job.
    """
    # Match DhanHTTP._send_request: client identity in header AND JSON.
    # Resolve once per acquisition/token; keep credentials out of receipts.
    token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    if not token or len(token) > 4096:
        raise ValueError("Connect your Dhan Data API token under Trading Copilot > Connections")
    from . import dhan_option_chain
    auth_key = sha256(token.encode()).hexdigest()
    cached_auth = wire_state.get("_auth") if wire_state is not None else None
    if cached_auth and cached_auth[0] == auth_key:
        client_id = cached_auth[1]
    else:
        client_id = dhan_option_chain._client_id(token)
        if wire_state is not None:
            wire_state["_auth"] = (auth_key, client_id)
    variants = [
        {**body, "interval": int(body["interval"])},
        dict(body),
        {**body, "interval": int(body["interval"]), "securityId": str(body["securityId"])},
        {**body, "securityId": str(body["securityId"])},
    ]
    preferred = wire_state.get("preferred", 0) if wire_state is not None else 0
    order = [preferred] + [i for i in range(len(variants)) if i != preferred]
    last = None
    for attempt, i in enumerate(order):
        if attempt and opener is None:
            time.sleep(.45)
        try:
            payload = _original_response_once(variants[i], opener=opener, token=token, client_id=client_id)
        except RollingInputError as exc:
            last = exc
            continue
        if wire_state is not None:
            wire_state.update(preferred=i, wire_request=variants[i])
        return payload
    raise RollingInputError(
        str(last) + " Equivalent documented numeric/string encodings were rejected."
    ) from None


def _original_response_once(body: dict, *, opener=None, token: str, client_id: str) -> dict:
    if not client_id.isdigit() or len(client_id) > 30:
        raise ValueError("Dhan client identity unavailable. Check Connections.")
    # Do not mutate body: canonical request and receipt metadata stay private.
    wire = {**body, "dhanClientId": client_id}
    req = Request(ENDPOINT, data=json.dumps(wire, separators=(",", ":")).encode(),
                  headers={"access-token": token, "client-id": client_id,
                           "Accept": "application/json", "Content-Type": "application/json"},
                  method="POST")
    try:
        with (opener or urlopen)(req, timeout=25) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("Dhan expired-options data access denied (401/403). Verify your token and expired-options data subscription") from None
        if exc.code == 429:
            raise ValueError("Dhan rate-limited expired-options history (429); retry later using existing cached calls") from None
        # Never print the access token or the complete provider response.
        # Dhan can return DH-905 for an invalid expiry code or another
        # invalid request value, and DH-907 for unavailable source history.
        detail = ""
        vendor_code = ""
        try:
            failure = json.loads(exc.read(4096))
            if isinstance(failure, dict):
                vendor_code = str(failure.get("errorCode", "")).strip()
                if vendor_code in ("DH-905", "DH-907", "DH-902",
                                   "805", "806", "811", "812", "813", "814"):
                    detail = f" (Dhan {vendor_code})"
                # Show only short, allowlisted API validation messages.
                # Never emit raw JSON, account IDs, tokens, URLs or headers.
                message = str(failure.get("errorMessage", "")).strip()
                if (0 < len(message) <= 160
                        and all(ch.isalpha() or ch in
                                " 0123456789.,:;-_()/+'"
                                for ch in message)
                        and not any(secret in message.lower()
                                    for secret in ("token", "bearer", "secret",
                                                   "password", "client id", "jwt"))
                        and token not in message and client_id not in message
                        and not any(len(word) > 32
                                    for word in message.split())):
                    detail += f": {message}"
        except (ValueError, TypeError, UnicodeError, OSError):
            pass
        context = (f"{body['expiryFlag'].lower()} {body['drvOptionType']} "
                   f"{body['strike']}, expiry={body['expiryCode']}, "
                   f"dates={body['fromDate']}..{body['toDate']}")
        error_type = RollingInputError if exc.code == 400 and vendor_code == "DH-905" else ValueError
        raise error_type(
            f"Dhan expired-options HTTP {exc.code}{detail} for {context}. "
            "This endpoint uses expiryCode 1=near, 2=next, 3=far. "
            "If the expiry is still active, refresh the Dhan instrument master "
            "and use the active-contract history; no option prices have been invented."
        ) from None
    except (URLError, TimeoutError) as exc:
        raise ValueError("Dhan expired-options data connection unavailable; check local network") from None
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Dhan expired-options response was empty or exceeded size limit")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Dhan expired-options response was not valid JSON") from None
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise ValueError("Dhan returned no valid rolling option data; check segment, expiry, and entitlement")
    return result


def _cache_path(body: dict) -> Path:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return service.DATA / "dhan_expired_options" / (sha256(canonical).hexdigest() + ".json")


def _get_cached(body: dict) -> dict | None:
    path = _cache_path(body)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_RESPONSE_BYTES + 5000:
            raise ValueError("Cached expired-option response is oversized")
        item = json.loads(path.read_text(encoding="utf-8"))
        payload = item["payload"]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if item["request"] != body or sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Cached expired-option source failed SHA-256 validation")
        if not (isinstance(payload.get("data"), dict) or
                isinstance(payload.get("timestamp"), list)):
            raise ValueError("Cached option source lacks original timestamped data")
        return payload
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Cached Dhan expired-options receipt is corrupted; remove the affected receipt in your local data library before retrying") from None


def _save_cache(body: dict, payload: dict, *, wire_request=None) -> None:
    path = _cache_path(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Expired-options source is too large to cache")
    envelope = {"source": "Dhan v2 /charts/rollingoption", "request": body,
                "sha256": sha256(raw).hexdigest(), "payload": payload,
                "saved_utc": datetime.now(timezone.utc).isoformat()}
    if wire_request is not None:
        # Record the actual accepted encoding without changing semantic cache keys.
        equivalent = {**wire_request, "interval": str(wire_request["interval"]),
                      "securityId": int(wire_request["securityId"])}
        if equivalent != body:
            raise ValueError("Wire request differs from canonical source scope")
        envelope["wire_request"] = wire_request
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _normalize(payload: dict, body: dict) -> list[dict]:
    which = "ce" if body["drvOptionType"] == "CALL" else "pe"
    segment = payload.get("data", {}).get(which)
    if segment is None:
        return []
    if not isinstance(segment, dict):
        raise ValueError("Dhan expired-options contract data has unexpected shape")
    stamps = segment.get("timestamp")
    if not isinstance(stamps, list) or len(stamps) > MAX_SOURCE_ROWS:
        raise ValueError("Dhan option history timestamps are missing or exceed response limit")
    if not stamps:
        return []
    for key in ("open", "high", "low", "close", "strike"):
        if not isinstance(segment.get(key), list) or len(segment[key]) != len(stamps):
            raise ValueError(f"Dhan expired-options {key} history does not align with timestamps")
    rows = []
    previous = None
    lower = date.fromisoformat(body["fromDate"])
    upper = date.fromisoformat(body["toDate"])
    for index, epoch in enumerate(stamps):
        try:
            timestamp = datetime.fromtimestamp(float(epoch), tz=timezone.utc)
            if previous is not None and timestamp <= previous:
                raise ValueError("Dhan option bars are not uniquely ordered")
            previous = timestamp
            local = timestamp.astimezone(IST)
            if not lower <= local.date() < upper or not clock_time(9, 15) <= local.time().replace(tzinfo=None) <= clock_time(15, 29):
                continue
            op, hi, lo, close, strike = (float(segment[name][index])
                                      for name in ("open", "high", "low", "close", "strike"))
            if (not all(math.isfinite(x) and x > 0 for x in
                        (op, hi, lo, close, strike))
                    or lo > min(op, close) or hi < max(op, close)):
                continue
            volume_field = segment.get("volume")
            volume = (float(volume_field[index])
                      if isinstance(volume_field, list) and len(volume_field) == len(stamps)
                      and volume_field[index] is not None else None)
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                volume = None
            rows.append({
                "timestamp_utc": timestamp.isoformat(),
                "session_ist": local.date().isoformat(),
                "strike": strike,
                "side": body["drvOptionType"],
                "open": op, "high": hi, "low": lo, "close": close,
                "volume": volume,
                "expiry_flag": body["expiryFlag"], "expiry_code": body["expiryCode"],
                "origin_offset": body["strike"],
            })
        except (TypeError, OverflowError, OSError, ValueError):
            # Do not invent a price for an unusable or absent source bar.
            continue
    return rows


def load_option_market(start: date, stop: date, *, expiry_flag: str,
                       expiry_code: int, wings: int, progress=None,
                       fetcher=None, throttle=None) -> tuple[dict, dict]:
    """Fetch only missing Dhan chunks, cache SHA-checked original responses.

    Never cache credentials. A batch is limited in number of vendor calls.
    """
    bodies = [_request_body(a, b, expiry_flag, expiry_code, offset, side)
              for a, b in _chunks(start, stop)
              for side in ("CALL", "PUT") for offset in _offsets(wings)]
    if len(bodies) > MAX_REQUESTS:
        raise ValueError(f"Historical options window requires {len(bodies)} vendor requests; reduce history or ATM wings (maximum {MAX_REQUESTS})")
    prices: dict[tuple[str, str, float], dict] = {}
    conflicted: set[tuple[str, str, float]] = set()
    reused = 0
    downloaded = 0
    empty = 0
    invalid = 0
    wire_state = {}
    for i, body in enumerate(bodies):
        if progress:
            progress(10 + 53 * i / max(1, len(bodies)), "Reading historical option candles and source receipts")
        payload = _get_cached(body)
        if payload is not None:
            reused += 1
        else:
            if fetcher is None:
                if throttle is None:
                    time.sleep(.45)  # modest spacing; no vendor request flood
                else:
                    throttle()
                payload = _original_response(body, wire_state=wire_state)
            else:
                payload = fetcher(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                raise ValueError("Expired-options vendor returned an invalid data payload")
            _save_cache(body, payload, wire_request=wire_state.get("wire_request") if fetcher is None else None)
            downloaded += 1
        rows = _normalize(payload, body)
        if not rows:
            empty += 1
        for row in rows:
            key = (row["timestamp_utc"], row["side"], row["strike"])
            if key in conflicted:
                continue
            old = prices.get(key)
            if old is None:
                prices[key] = row
            elif any(abs(old[field] - row[field]) > .011
                     for field in ("open", "high", "low", "close")):
                prices.pop(key, None)
                conflicted.add(key)
                invalid += 1
    # A contract's identity is (session, strike, CE/PE, rolling expiry family).
    # Never forward-fill an option price or silently change to a new ATM strike.
    lookup: dict[tuple[str, str], dict[float, dict]] = defaultdict(dict)
    for (timestamp, side, strike), row in prices.items():
        lookup[(timestamp, side)][strike] = row
    return lookup, {
        "request_count": len(bodies), "fresh_requests": downloaded,
        "cached_requests": reused, "empty_requests": empty,
        "unique_option_minute_bars": len(prices),
        "conflicted_excluded": invalid,
        "source": "Dhan v2 one-minute rolling expired-options (OHLC, no historical bid/ask)",
        "expiry_flag": expiry_flag,
        "expiry_code": expiry_code,
        "dhan_rolling_expiry_code": expiry_code + 1,
        "strike_wings": wings, "cache": "SHA-256 verified local receipts",
    }


def _active_body(security_id: str, start: date, stop: date) -> dict:
    """Dhan active NSE_FNO option minute history, exact listed security ID."""
    return {"securityId": str(security_id), "exchangeSegment": "NSE_FNO",
            "instrument": "OPTIDX", "interval": "1", "oi": False,
            "fromDate": start.isoformat() + " 00:00:00",
            "toDate": stop.isoformat() + " 00:00:00"}


def _active_response(body: dict, *, opener=None) -> dict:
    token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    if not token or len(token) > 4096:
        raise ValueError("Connect your Dhan Data API token under Trading Copilot > Connections")
    request = Request("https://api.dhan.co/v2/charts/intraday",
                      data=json.dumps(body, separators=(",", ":")).encode(),
                      headers={"access-token": token, "Accept": "application/json",
                               "Content-Type": "application/json"}, method="POST")
    try:
        with (opener or urlopen)(request, timeout=25) as reply:
            raw = reply.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("Dhan current option-history access denied. Verify the Data API subscription and token") from None
        if exc.code == 429:
            raise ValueError("Dhan rate-limited active option candles; reuse existing cached source receipts or retry later") from None
        raise ValueError(f"Dhan active NSE_FNO options minute history failed (HTTP {exc.code})") from None
    except (URLError, TimeoutError):
        raise ValueError("Dhan active options history is unreachable") from None
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Dhan active option history response is empty or oversized")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("Dhan active options history response is not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("timestamp"), list):
        raise ValueError("Dhan active options history has no timestamped candles")
    return data


def _normalize_active(payload: dict, contract: dict, days: set[str]) -> list[dict]:
    stamps = payload.get("timestamp")
    if not isinstance(stamps, list) or len(stamps) > MAX_SOURCE_ROWS:
        raise ValueError("Dhan active option timestamps are missing or exceed source limit")
    for key in ("open", "high", "low", "close"):
        if not isinstance(payload.get(key), list) or len(payload[key]) != len(stamps):
            raise ValueError("Active option candle values do not align with original timestamps")
    volume = payload.get("volume")
    if not isinstance(volume, list) or len(volume) != len(stamps):
        raise ValueError("Active option history has no aligned trade volume")
    rows = []
    seen = set()
    for i, epoch in enumerate(stamps):
        try:
            timestamp = datetime.fromtimestamp(float(epoch), timezone.utc)
            local = timestamp.astimezone(IST)
            day = local.date().isoformat()
            if day not in days or not clock_time(9, 15) <= local.time().replace(tzinfo=None) <= clock_time(15, 29):
                continue
            if timestamp in seen:
                raise ValueError("Repeated active option source timestamp")
            seen.add(timestamp)
            op, hi, lo, cl, vol = (float(payload[key][i])
                                  for key in ("open", "high", "low", "close", "volume"))
            if (any(not math.isfinite(v) for v in (op, hi, lo, cl, vol))
                    or min(op, hi, lo, cl) <= 0 or vol < 0
                    or lo > min(op, cl) or hi < max(op, cl)):
                continue
            rows.append({
                "timestamp_utc": timestamp.isoformat(),
                "session_ist": day, "strike": float(contract["strike"]),
                "side": "CALL" if contract["option_type"] == "CE" else "PUT",
                "open": op, "high": hi, "low": lo, "close": cl,
                "volume": vol, "expiry_flag": "MONTH",
                "expiry_code": 0, "expiry_date": contract["expiry"],
                "origin_offset": None, "security_id": contract["security_id"],
                "lot_size_verified": contract["lot_size"],
            })
        except (ValueError, OverflowError, TypeError, OSError):
            continue
    return rows


def load_active_option_market(spot_rows: list[dict], *,
                              expiry_flag: str, expiry_code: int, wings: int,
                              fetcher=None, progress=None,
                              master_refresher=None) -> tuple[dict, dict]:
    """Supplement rolling expired options with exact active NSE_FNO contracts.

    Uses only fresh ORIGINAL Dhan instrument master. Expired contracts
    removed from today's master are never invented; those need rolling data.
    """
    from . import option_chain_live
    if expiry_flag != "MONTH":
        return {}, {"reason": "BANKNIFTY active options are monthly-only; choose monthly expiry"}
    recent_days = {
        row["session_ist"] for row in spot_rows
        if date.fromisoformat(row["session_ist"]) >= _ist_today() - timedelta(days=30)
    }
    if not recent_days:
        return {}, {"reason": "Historical sample has no currently listed options; using archived expiry series"}
    master = option_chain_live._contracts()
    if (not master.get("available") or not master.get("fresh")
            or not master.get("by_id")) and master_refresher is not None:
        if progress:
            progress(8, "Refreshing Dhan instrument master for current BANKNIFTY option contract IDs")
        try:
            master_refresher()
            master = option_chain_live._contracts()
        except (ValueError, OSError, TimeoutError) as exc:
            return {}, {
                "reason": "Automatic Dhan instrument-master refresh failed",
                "next_action": str(exc)[:200],
            }
    if not master.get("available") or not master.get("fresh") or not master.get("by_id"):
        return {}, {"reason": "Fresh BANKNIFTY options contract data not present in Dhan master",
                    "next_action": master.get("message") or "Refresh the official Dhan instrument master; verify NSE_FNO OPTIDX records, expiry, strike and lot-size columns"}
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in spot_rows:
        by_day[row["session_ist"]].append(row)
    days = sorted(by_day)
    if not days:
        return {}, {"reason": "No original BANKNIFTY source days"}
    all_contracts = list(master["by_id"].values())
    choices: dict[str, dict] = {}
    today = _ist_today()
    for day in days:
        # Today's active master must not retrospectively select a contract
        # that was not the nearest expiry in an old historical session.
        # Older periods always use Dhan's original rolling expired history.
        if date.fromisoformat(day) < today - timedelta(days=30):
            continue
        expiries = sorted({x["expiry"] for x in all_contracts if x["expiry"] >= day})
        if len(expiries) <= expiry_code:
            continue
        expiry = expiries[expiry_code]
        for side in ("CE", "PE"):
            side_rows = [x for x in all_contracts if x["expiry"] == expiry
                         and x["option_type"] == side]
            if not side_rows:
                continue
            reference = by_day[day][0]["close"]
            strikes = sorted({x["strike"] for x in side_rows})
            near = min(range(len(strikes)), key=lambda idx:
                       abs(strikes[idx] - reference))
            permitted = set(strikes[max(0, near-wings):near+wings+1])
            for candidate in side_rows:
                if candidate["strike"] not in permitted:
                    continue
                identity = candidate["security_id"]
                state = choices.setdefault(identity, {
                    "contract": candidate, "days": set(),
                })
                state["days"].add(day)
    if len(choices) > MAX_ACTIVE_REQUESTS:
        return {}, {"reason": "Active contracts exceed bounded request budget",
                    "candidates": len(choices), "limit": MAX_ACTIVE_REQUESTS,
                    "next_action": "Select a shorter historical BANKNIFTY window "
                                   "or reduce ATM strike coverage under Advanced "
                                   "settings to stay within the Dhan API request limit"}
    if not choices:
        return {}, {"reason": "No source-matched BANKNIFTY listed contracts for the index dates"}
    first = date.fromisoformat(days[0])
    last = date.fromisoformat(days[-1]) + timedelta(days=1)
    lookup: dict[tuple[str, str], dict[float, dict]] = defaultdict(dict)
    cache_count = vendor_count = invalid = 0
    unavailable: Counter[str] = Counter()
    for i, (identity, item) in enumerate(sorted(choices.items())):
        if progress:
            progress(10 + i * 36 / len(choices), "Checking currently active Dhan option contracts")
        body = _active_body(identity, first, last)
        # A SHA-invalid cached receipt is a source-integrity failure, NEVER
        # a reason to silently redownload or manufacture a substitute.
        payload = _get_cached(body)
        if payload is None:
            try:
                if fetcher is None:
                    time.sleep(.45)
                    payload = _active_response(body)
                else:
                    payload = fetcher(body)
            except ValueError as exc:
                # A particular NEW strike may not have traded for the whole
                # requested period. Keep other original listed contracts
                # rather than aborting the entire backtest. Fail fast for
                # account-wide entitlement or vendor rate-limit failures.
                reason = str(exc)[:160]
                if "access denied" in reason.lower() or "rate-limited" in reason.lower():
                    raise
                unavailable[reason] += 1
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("timestamp"), list):
                unavailable["Dhan active contract request returned no timestamped minute candles"] += 1
                continue
            _save_cache(body, payload)
            vendor_count += 1
        else:
            cache_count += 1
        try:
            parsed = _normalize_active(payload, item["contract"], item["days"])
        except ValueError:
            unavailable["Dhan active contract candles were not structurally valid"] += 1
            continue
        for row in parsed:
            key = (row["timestamp_utc"], row["side"])
            strike = row["strike"]
            if strike in lookup[key] and lookup[key][strike]["security_id"] != identity:
                lookup[key].pop(strike, None)
                invalid += 1
            else:
                lookup[key][strike] = row
    returned = sum(len(v) for v in lookup.values())
    skipped = sum(unavailable.values())
    result = {
        "source": "Dhan original active NSE_FNO OPTIDX /charts/intraday",
        "requests": len(choices), "fresh_requests": vendor_count,
        "cached_requests": cache_count, "unique_option_minute_bars": returned,
        "failed_contract_requests": skipped,
        "failure_reasons": dict(unavailable.most_common(3)),
        "conflicted_excluded": invalid,
        "identity": "exact current Dhan security_id, expiry date and lot size",
    }
    if not returned:
        result["reason"] = "No original current-contract option minute bars matched the selected dates"
        result["next_action"] = (
            "Check Dhan's active NSE_FNO option-history entitlement and "
            "refresh its official instrument master. "
            "If a specific strike is newly listed, its older minutes "
            "may be unavailable; narrow the window or adjust strike coverage.")
    return lookup, result


def _ema_crossover_signals(source_rows: list[dict]) -> list[dict]:
    """Pure BANKNIFTY 9/21 EMA crossings on completed ORIGINAL 1-minute bars.

    No RSI filter, no same-candle option fill, no synthetic missing minute.
    A crossover is emitted exactly once when fast EMA changes position
    relative to slow EMA. Both EMAs are seeded with an observed SMA and
    reset on each session boundary or missing one-minute observation.
    When no crossover occurs, NO_TRADE means *hold* the current position
    under the reversal strategy, not a forced exit.
    """
    rows = trading_cockpit._validated(source_rows)
    events: list[dict] = []
    closes: list[float] = []
    previous_fast: float | None = None
    previous_slow: float | None = None
    previous_time: datetime | None = None
    previous_session: str | None = None
    for current in rows:
        observed = _stamp(current["timestamp_utc"])
        local = observed.astimezone(IST)
        if (not clock_time(9, 15) <= local.time().replace(tzinfo=None)
                <= clock_time(15, 29)):
            closes = []
            previous_fast = previous_slow = previous_time = None
            previous_session = None
            continue
        if (current["session_ist"] != previous_session
                or previous_time is None
                or observed - previous_time != timedelta(minutes=1)):
            closes = []
            previous_fast = previous_slow = None
        closes.append(current["close"])
        fast = trading_cockpit._ema(closes, 9)[-1]
        slow = trading_cockpit._ema(closes, 21)[-1]
        direction = "NO_TRADE"
        if (fast is not None and slow is not None
                and previous_fast is not None and previous_slow is not None):
            if previous_fast <= previous_slow and fast > slow:
                direction = "UP"
            elif previous_fast >= previous_slow and fast < slow:
                direction = "DOWN"
        events.append({
            "bar_utc": current["timestamp_utc"],
            "session_ist": current["session_ist"],
            "direction": direction,
            "underlying_close": current["close"],
            "ema9": fast, "ema21": slow,
            "signal_kind": ("cross_above" if direction == "UP" else
                            "cross_below" if direction == "DOWN" else None),
        })
        previous_fast, previous_slow = fast, slow
        previous_time = observed
        previous_session = current["session_ist"]
    return events


def _signals(source_rows: list[dict], *, signal_model: str = "ema_rsi") -> list[dict]:
    """Choose pure EMA crossover or the existing EMA+RSI baseline."""
    if signal_model == "ema_crossover":
        return _ema_crossover_signals(source_rows)
    if signal_model != "ema_rsi":
        raise ValueError("Unknown original BANKNIFTY signal model")
    rows = trading_cockpit._validated(source_rows)
    result = []
    for index in range(29, len(rows)):
        current = rows[index]
        observed = _stamp(current["timestamp_utc"])
        local = observed.astimezone(IST)
        if not clock_time(9, 15) <= local.time().replace(tzinfo=None) <= clock_time(15, 29):
            continue
        signal = trading_cockpit.snapshot(
            "INDEX:BANKNIFTY", rows[max(0, index - 200):index + 1],
            now=observed + timedelta(seconds=90), include_chart=False)
        result.append({"bar_utc": current["timestamp_utc"],
                       "session_ist": current["session_ist"],
                       "direction": signal["direction"],
                       "underlying_close": current["close"]})
    return result


def _same_day_close(at: datetime) -> datetime:
    local = at.astimezone(IST)
    return datetime.combine(local.date(), clock_time(15, 29),
                            tzinfo=IST).astimezone(timezone.utc)


def _exit_decision(policy: str, *, entry_at: datetime, entry_premium: float,
                   side: str, strike: float, day: str, signals: dict,
                   candles: dict, hold: int, cap: int, stop_pct: float,
                   target_pct: float, target_points=None, stop_points=None) -> tuple[datetime, str]:
    """Compute causal NEXT-OPEN exit; stop/target checks use completed closes."""
    last = _same_day_close(entry_at)
    fixed = entry_at + timedelta(minutes=hold)
    deadline = last
    reason = "session_end"
    if policy == "fixed":
        deadline, reason = min(fixed, last), ("fixed_hold" if fixed <= last else "session_end")
    elif policy in ("signal_reversal_or_cap", "hybrid"):
        candidate = entry_at + timedelta(minutes=cap)
        if candidate <= deadline:
            deadline, reason = candidate, "time_cap"
    for minute in range(0, max(0, int((deadline - entry_at).total_seconds() // 60))):
        observed = entry_at + timedelta(minutes=minute)
        # We may not exit at this minute's OPEN using information from this
        # minute's close. The signal/close trigger can only exit at +1 OPEN.
        exit_at = observed + timedelta(minutes=1)
        decision = signals.get(observed.isoformat())
        if policy in ("signal_reversal", "signal_reversal_or_cap", "hybrid"):
            opposite = "DOWN" if side == "CALL" else "UP"
            if decision == opposite and exit_at <= deadline:
                return exit_at, "opposite_signal"
        if policy in ("premium_target_stop", "hybrid") or target_points is not None or stop_points is not None:
            quote = candles.get((observed.isoformat(), side), {}).get(strike)
            if quote is None or quote["session_ist"] != day:
                continue
            # A close crossing stop/target produces a NEXT OPEN proxy exit,
            # not a guaranteed trigger fill at the threshold.
            stop_level = entry_premium-stop_points if stop_points is not None else entry_premium*(1-stop_pct/100)
            target_level = entry_premium+target_points if target_points is not None else entry_premium*(1+target_pct/100)
            if quote["close"] <= stop_level and exit_at <= deadline:
                return exit_at, "stop_close_next_open"
            if quote["close"] >= target_level and exit_at <= deadline:
                return exit_at, "target_close_next_open"
    return deadline, reason


def simulate_options(events: list[dict], spot_rows: list[dict], option_rows: dict, *,
                     policy: str, hold: int = 5, cap: int = 10,
                     target_ltp: float = 300, tolerance: float = 50,
                     lot_size: int = 30, lots: int = 3,
                     starting_capital: float = 50_000,
                     stop_pct: float = 2.5, target_pct: float = 5,
                     slippage_bps: float = 5, fee_per_side: float = 20,
                     fee_mode: str = "flat", target_points=None, stop_points=None,
                     retain_all_trades: bool = False) -> dict:
    """Select a contract at completed SIGNAL candle close; trade next open.

    One position at a time. On a confirmed opposite BANKNIFTY signal,
    close the existing long CE/PE and allow the opposite long PE/CE to open
    at that SAME next observed minute's OPEN, using distinct actual contract
    candles. This is a paper fill model, never an actual broker order.
    An unscorable opened position blocks the entire session to avoid bias.
    """
    if policy not in VALID_POLICIES:
        raise ValueError("Unsupported option exit policy")
    if (target_points is None) != (stop_points is None) or any(
            not math.isfinite(v) or v <= 0 for v in (target_points,stop_points) if v is not None):
        raise ValueError("Choose positive paired premium point target and stop")
    spot_map = {_stamp(r["timestamp_utc"]): r for r in
                trading_cockpit._validated(spot_rows)}
    signals_by_stamp = {_stamp(ev["bar_utc"]).isoformat(): ev["direction"]
                        for ev in events}
    balance = float(starting_capital)
    peak = balance
    max_drawdown = 0.0
    busy_until: datetime | None = None
    missing = Counter()
    reversal_rejections = Counter()
    reversal_entry_attempts = 0

    def note_skip(reason: str, *, flip: bool = False) -> None:
        missing[reason] += 1
        if flip:
            reversal_rejections[reason] += 1

    trades = []
    equity = [{"timestamp_utc": spot_rows[0]["timestamp_utc"],
               "equity_inr": round(balance, 2)}] if spot_rows else []
    for event in events:
        direction = event["direction"]
        if direction not in ("UP", "DOWN"):
            continue
        at = _stamp(event["bar_utc"])
        entry_at = at + timedelta(minutes=1)
        session = event["session_ist"]
        prior = trades[-1] if trades else None
        # On a completed DOWN/UP candle at time t, the held CE/PE is
        # closed at (t+1) OPEN. Only that SAME opposite signal may buy the
        # new PE/CE at (t+1) OPEN. A fixed/target/stop/time-cap exit must
        # not accidentally be treated as an opposite-signal switch.
        same_open_flip = bool(
            busy_until is not None
            and entry_at == busy_until
            and prior is not None
            and prior["exit_utc"] == entry_at.isoformat()
            and prior["exit_reason"] == "opposite_signal"
            and prior["session_ist"] == session
            and prior["underlying_direction"] != direction
            and at == entry_at - timedelta(minutes=1)
        )
        if same_open_flip:
            reversal_entry_attempts += 1
        if busy_until is not None and (
                entry_at < busy_until or
                (entry_at == busy_until and not same_open_flip)):
            note_skip("position_open", flip=same_open_flip)
            continue
        if entry_at >= _same_day_close(at):
            note_skip("session_cutoff", flip=same_open_flip)
            continue
        entry_index = spot_map.get(entry_at)
        if entry_index is None or entry_index["session_ist"] != session:
            note_skip("missing_underlying_entry", flip=same_open_flip)
            continue
        side = "CALL" if direction == "UP" else "PUT"
        # Historical contract choice must use only information from the
        # completed signal minute, never the next candle or exit-time data.
        available = option_rows.get((at.isoformat(), side), {})
        eligible = [r for r in available.values()
                    if r["session_ist"] == session and
                    abs(r["close"] - target_ltp) <= tolerance and
                    r["volume"] is not None and r["volume"] > 0]
        if not eligible:
            note_skip("no_option_near_target_at_signal", flip=same_open_flip)
            continue
        chosen = min(eligible, key=lambda r:
                     (abs(r["close"] - target_ltp), -r["volume"], r["strike"]))
        strike = chosen["strike"]
        entry_quote = option_rows.get((entry_at.isoformat(), side), {}).get(strike)
        if (entry_quote is None or entry_quote["session_ist"] != session
                or not entry_quote["volume"] or entry_quote["volume"] <= 0):
            note_skip("missing_option_entry", flip=same_open_flip)
            continue
        entry_premium = entry_quote["open"] * (1 + slippage_bps / 10_000)
        used_lot_size = int(chosen.get("lot_size_verified") or lot_size)
        units = lots * used_lot_size
        outlay = entry_premium * units
        entry_charge = (fee_per_side if fee_mode=="flat" else
            option_fees.fee_schedule(outlay,0.,broker_profile=fee_mode)["buy_leg"]["fees_total"])
        if outlay + entry_charge > balance:
            note_skip("insufficient_capital", flip=same_open_flip)
            continue
        exit_at, reason = _exit_decision(
            policy, entry_at=entry_at, entry_premium=entry_premium,
            side=side, strike=strike, day=session, signals=signals_by_stamp,
            candles=option_rows, hold=hold, cap=cap, stop_pct=stop_pct,
            target_pct=target_pct,target_points=target_points,stop_points=stop_points)
        if exit_at <= entry_at or exit_at > _same_day_close(entry_at):
            note_skip("invalid_exit_time", flip=same_open_flip)
            busy_until = _same_day_close(entry_at)
            continue
        # Verify EVERY observed index minute and EXACT same strike/side
        # exists on the option source throughout the entry/exit interval.
        path_valid = True
        step_count = int((exit_at - entry_at).total_seconds() // 60)
        for step in range(step_count + 1):
            tick = entry_at + timedelta(minutes=step)
            option_tick = option_rows.get((tick.isoformat(), side), {}).get(strike)
            index_tick = spot_map.get(tick)
            if (option_tick is None or index_tick is None
                    or option_tick["session_ist"] != session
                    or index_tick["session_ist"] != session
                    or (chosen.get("security_id") and
                        option_tick.get("security_id") != chosen.get("security_id"))):
                path_valid = False
                break
        if not path_valid:
            note_skip("missing_exact_contract_path", flip=same_open_flip)
            busy_until = _same_day_close(entry_at)
            continue
        exit_quote = option_rows[(exit_at.isoformat(), side)][strike]
        if not exit_quote["volume"] or exit_quote["volume"] <= 0:
            note_skip("zero_exit_volume", flip=same_open_flip)
            busy_until = _same_day_close(entry_at)
            continue
        exit_premium = exit_quote["open"] * (1 - slippage_bps / 10_000)
        gross = (exit_premium - entry_premium) * units
        charges = (2 * fee_per_side if fee_mode=="flat" else
            option_fees.fee_schedule(outlay,exit_premium*units,broker_profile=fee_mode)["total_estimated"])
        net = gross - charges
        balance += net
        peak = max(peak, balance)
        max_drawdown = max(max_drawdown, (peak - balance) * 100 / peak)
        busy_until = exit_at
        trade = {
            "signal_utc": event["bar_utc"], "entry_utc": entry_at.isoformat(),
            "exit_utc": exit_at.isoformat(), "session_ist": session,
            "underlying_direction": direction, "option_side": "CE" if side == "CALL" else "PE",
            "entry_reason": "opposite_signal_flip" if same_open_flip else "signal_entry",
            "flipped_from_option_side": prior["option_side"] if same_open_flip else None,
            "flipped_from_strike": prior["strike"] if same_open_flip else None,
            "strike": strike, "selection_ltp": chosen["close"],
            "entry_premium": round(entry_premium, 4),
            "exit_premium": round(exit_premium, 4),
            "raw_entry_open": entry_quote["open"], "raw_exit_open": exit_quote["open"],
            "lots": lots, "lot_size_assumed": (
                None if chosen.get("security_id") else used_lot_size),
            "lot_size_used": used_lot_size,
            "lot_size_basis": ("ORIGINAL_CURRENT_DHAN_MASTER" if chosen.get("security_id")
                               else "USER_HISTORICAL_ASSUMPTION"),
            "units": units,
            "capital_deployed_inr": round(outlay, 2),
            "gross_pnl_inr": round(gross, 2), "assumed_fees_inr": charges,
            "net_pnl_inr": round(net, 2), "account_balance_inr": round(balance, 2),
            "exit_reason": reason, "hold_minutes": step_count,
            "source_identity": (
                "NSE_FNO:" + chosen["security_id"] if chosen.get("security_id")
                else f"BANKNIFTY_ROLLING_{side}_{strike:g}_{session}"),
            "contract_identity_verified": bool(chosen.get("security_id")),
            "contract_expiry_date": chosen.get("expiry_date"),
        }
        trades.append(trade)
        equity.append({"timestamp_utc": exit_at.isoformat(),
                       "equity_inr": round(balance, 2)})
    opposite_exits = sum(t["exit_reason"] == "opposite_signal" for t in trades)
    completed_flips = sum(t["entry_reason"] == "opposite_signal_flip"
                          for t in trades)
    reversal_audit = {
        "opposite_signal_exits": opposite_exits,
        "same_open_reentry_attempts": reversal_entry_attempts,
        "completed_flips": completed_flips,
        "opposite_exits_without_completed_reentry": max(0, opposite_exits - completed_flips),
        "rejected_reentry_reasons": dict(reversal_rejections),
        "session_end_exits": sum(t["exit_reason"] == "session_end"
                                 for t in trades),
        "time_cap_exits": sum(t["exit_reason"] == "time_cap"
                              for t in trades),
        "fixed_hold_exits": sum(t["exit_reason"] == "fixed_hold"
                                for t in trades),
        "note": (
            "Signals can repeat on every minute, but a CE/PE switch requires "
            "a qualifying opposite signal while holding, the next original "
            "option OPEN, and a complete exact-contract path. An unscored "
            "entry is not a zero-return trade."),
    }
    wins = sum(t["net_pnl_inr"] > 0 for t in trades)
    losses = sum(t["net_pnl_inr"] < 0 for t in trades)
    return {
        "policy": policy, "hold_minutes": hold, "time_cap_minutes": cap,
        "trade_count": len(trades),
        "reversal_switches": completed_flips,
        "reversal_audit": reversal_audit,
        "win_rate": round(wins / (wins + losses), 4) if wins + losses else None,
        "winning_trades": wins, "losing_trades": losses,
        "starting_capital_inr": round(starting_capital, 2),
        "ending_capital_inr": round(balance, 2),
        "net_pnl_inr": round(balance - starting_capital, 2),
        "return_pct": round((balance / starting_capital - 1) * 100, 3),
        "max_closed_trade_drawdown_pct": round(max_drawdown, 3),
        "average_hold_minutes": round(
            sum(t["hold_minutes"] for t in trades) / len(trades), 2) if trades else None,
        "total_assumed_fees_inr": round(sum(t["assumed_fees_inr"] for t in trades), 2),
        "unscored": dict(missing), "equity_curve": equity[-101:],
        "trades": trades if retain_all_trades else trades[-100:],
    }


def run_backtest(*, limit: int = 1500, expiry_flag: str = "MONTH",
                 expiry_code: int = 0, wings: int = 3,
                 target_ltp: float = 300, tolerance: float = 50,
                 lots: int = 3, lot_size: int = 30,
                 starting_capital: float = 50_000,
                 stop_pct: float = 2.5, target_pct: float = 5,
                 slippage_bps: float = 5, fee_per_side: float = 20,
                 hold_rule: str = "fixed", hold_minutes: int = 5,
                 reversal_cap_minutes: int = 10,
                 signal_model: str = "ema_rsi", fee_mode: str = "flat",
                 fetcher=None, active_fetcher=None, throttle=None,
                 master_refresher=None, progress=None) -> dict:
    """One-click original BANKNIFTY signals -> option-contract P&L proxy.

    Will re-use local verified option receipts, automatically requesting
    missing original rolling strikes only when an explicit run is started.
    Does not send orders and cannot use live option chain for historic fills.
    """
    _validate_params(limit=limit, expiry_flag=expiry_flag, expiry_code=expiry_code,
                     wings=wings, lot_size=lot_size, lots=lots,
                     target_ltp=target_ltp, tolerance=tolerance,
                     starting_capital=starting_capital, stop_pct=stop_pct,
                     target_pct=target_pct, slippage_bps=slippage_bps,
                     fee_per_side=fee_per_side, hold_rule=hold_rule,
                     hold_minutes=hold_minutes,
                     reversal_cap_minutes=reversal_cap_minutes,
                     signal_model=signal_model, fee_mode=fee_mode)
    if progress:
        progress(2, "Verifying original BANKNIFTY index minute candles")
    acquired_spot = False
    try:
        spot = cockpit_sources.series("INDEX:BANKNIFTY", limit=limit)
    except ValueError as exc:
        # Only auto-recover a genuinely ABSENT source. Never replace a
        # corrupted manifest, SHA mismatch or intentionally selected history.
        if "Download an original Dhan IDX_I one-minute" not in str(exc):
            raise
        # The user already confirmed this read-only source acquisition when
        # starting the options backtest. One bounded source batch is enough
        # for the requested 500-5000 latest minute bars.
        last = date.today() + timedelta(days=1)
        first = last - timedelta(days=36)
        if progress:
            progress(3, "Missing BANKNIFTY index candles; downloading original Dhan IDX_I source")
        def index_progress(pct: float, stage: str):
            if progress:
                progress(3 + max(0, min(100, float(pct))) * .025, stage)
        cockpit_sources.download_spot(
            "INDEX:BANKNIFTY", first.isoformat(), last.isoformat(),
            progress=index_progress)
        acquired_spot = True
        spot = cockpit_sources.series("INDEX:BANKNIFTY", limit=limit)
    rows = trading_cockpit._validated(spot["rows"])
    if len(rows) < 40:
        raise ValueError("Need at least 40 original one-minute BANKNIFTY candles for signal warmup")
    start = date.fromisoformat(rows[0]["session_ist"])
    stop = date.fromisoformat(rows[-1]["session_ist"]) + timedelta(days=1)
    if (stop - start).days > 90:
        raise ValueError("Selected spot window spans more than 90 days; choose fewer minute candles")
    if progress:
        progress(7, "Checking Dhan expired-option history coverage")
    # Most recent monthly options may still be ACTIVE rather than expired.
    # Use an exact current security ID when a fresh original Dhan master and
    # corresponding active option candles exist. Otherwise use rolling data.
    try:
        active, active_evidence = load_active_option_market(
            rows, expiry_flag=expiry_flag, expiry_code=expiry_code,
            wings=wings, fetcher=active_fetcher, progress=progress,
            master_refresher=master_refresher)
    except ValueError as exc:
        # A missing active entitlement must not prevent reuse of already
        # authenticated and SHA-verified expired source receipts.
        active, active_evidence = {}, {"reason": str(exc)[:220]}
    source_days = {date.fromisoformat(row["session_ist"]) for row in rows}
    as_of = _ist_today()
    active_sides = {(row["session_ist"], row["side"])
                    for choices in active.values() for row in choices.values()}
    all_sides = {(day.isoformat(), side) for day in source_days
                 for side in ("CALL", "PUT")}
    eligible_expired_days = sorted(
        day for day in source_days
        if _expired_eligible(day, expiry_flag=expiry_flag,
                             expiry_code=expiry_code, today=as_of))
    not_yet_expired_days = source_days - set(eligible_expired_days)
    data_evidence = {
        "request_count": 0, "fresh_requests": 0, "cached_requests": 0,
        "empty_requests": 0, "unique_option_minute_bars": 0,
        "conflicted_excluded": 0,
        "source": active_evidence.get(
            "source", "Dhan original active NSE_FNO option contract minute candles"),
        "expiry_flag": expiry_flag, "expiry_code": expiry_code,
        "dhan_rolling_expiry_code": expiry_code + 1, "strike_wings": wings,
        "cache": "SHA-256 verified local receipts",
        "active_source": active_evidence,
        "routing": {
            "expired_eligible_sessions": len(eligible_expired_days),
            "unexpired_or_unavailable_weekly_sessions": len(not_yet_expired_days),
            "active_source_sessions": len({date.fromisoformat(day)
                                           for day, _ in active_sides}),
            "policy": "Only request rolling expired data for dates whose "
                      "selected monthly expiry is demonstrably in the past. "
                      "Never request current-month active contracts from rollingoption.",
        },
    }
    # A missing active contract on November 19 is not evidence that the
    # November option is EXPIRED. Dhan's /charts/rollingoption cannot serve
    # an as-yet-unexpired monthly contract. Do not replay the same HTTP 400
    # by falling back to rolling for the entire index window.
    #
    # Exact active security IDs take precedence when they are available.
    # If all days/sides have genuine active candles, skip unnecessary
    # rolling requests, even if a few older days could use expired history.
    candles = {}
    if eligible_expired_days and not (active and active_sides >= all_sides):
        # Eligibility is monotonic over time for a fixed expiry rank:
        # each candidate expiry rolls forward as sessions progress.
        # Only the prefix ending at the last safely EXPIRED index session
        # may go to the historical rolling endpoint.
        rolling_stop = min(stop, eligible_expired_days[-1] + timedelta(days=1))
        candles, rolling_info = load_option_market(
            start, rolling_stop, expiry_flag=expiry_flag,
            expiry_code=expiry_code, wings=wings, progress=progress,
            fetcher=fetcher, throttle=throttle)
        data_evidence.update(rolling_info)
    for key, entries in active.items():
        candles.setdefault(key, {}).update(entries)
    data_evidence["active_source"] = active_evidence
    data_evidence["unique_option_minute_bars"] = sum(
        len(choices) for choices in candles.values())
    data_evidence["fresh_requests"] += active_evidence.get("fresh_requests", 0)
    data_evidence["cached_requests"] += active_evidence.get("cached_requests", 0)
    data_evidence["request_count"] += active_evidence.get("requests", 0)
    data_evidence["routing"]["expired_vendor_requests"] = (
        data_evidence["request_count"] - active_evidence.get("requests", 0))
    if not candles:
        if expiry_flag == "WEEK" and not_yet_expired_days:
            raise ValueError(
                "BANKNIFTY does not have listed weekly options for this "
                "recent historical window. Choose monthly expiry (MONTH).")
        if not_yet_expired_days:
            detail = str(active_evidence.get("reason") or
                         active_evidence.get("next_action") or
                         "The current Dhan instrument master or original option "
                         "minute history did not provide a matched contract")[:220]
            raise ValueError(
                "These BANKNIFTY option sessions refer to a monthly "
                "contract that has NOT expired as of the requested window. "
                "Dhan's expired-options API is not valid for this period. "
                "QuantLab attempted current-contract NSE_FNO minute data, "
                "but no original CE/PE candles were found. "
                f"Active data status: {detail}. "
                "Open Data Library and refresh the official Dhan "
                "instrument master; no prices or trades were invented.")
        raise ValueError(
            "No original Dhan expired-option minute bars were available "
            "for the eligible historical period. Check the selected "
            "expiry, dates, coverage and vendor error details.")
    if progress:
        progress(67, ("Replaying completed BANKNIFTY EMA 9/21 crossovers"
                      if signal_model == "ema_crossover" else
                      "Replaying original completed BANKNIFTY EMA/RSI directional signals"))
    events = _signals(rows, signal_model=signal_model)
    policies = [("fixed", h, 10) for h in VALID_HOLDS] + [
        ("signal_reversal", hold_minutes, 10),
        ("signal_reversal_or_cap", hold_minutes, 10),
        ("signal_reversal_or_cap", hold_minutes, 30),
        ("premium_target_stop", hold_minutes, 10),
        ("hybrid", hold_minutes, 10),
        (hold_rule, hold_minutes, reversal_cap_minutes),
    ]
    signatures = set()
    comparison = []
    selected_id = ""
    selected_result = None
    for i, (policy, h, cap) in enumerate(policies):
        rid = (f"fixed_{h}" if policy == "fixed" else
               f"{policy}_{cap}" if policy in ("signal_reversal_or_cap", "hybrid")
               else policy)
        if rid in signatures:
            continue
        signatures.add(rid)
        if progress:
            progress(73 + 22 * i / len(policies), "Comparing real option-premium candle exits")
        scenario = simulate_options(
            events, rows, candles, policy=policy, hold=h, cap=cap,
            target_ltp=target_ltp, tolerance=tolerance,
            lots=lots, lot_size=lot_size, starting_capital=starting_capital,
            stop_pct=stop_pct, target_pct=target_pct,
            slippage_bps=slippage_bps, fee_per_side=fee_per_side,fee_mode=fee_mode)
        is_selected = (policy == hold_rule and h == hold_minutes
                       and (policy not in ("signal_reversal_or_cap", "hybrid")
                            or cap == reversal_cap_minutes))
        if is_selected:
            selected_id, selected_result = rid, scenario
        comparison.append({
            "rule_id": rid,
            "label": (f"Fixed {h}m" if policy == "fixed" else
                      "Exit and flip CE/PE on opposite BANKNIFTY signal" if policy == "signal_reversal" else
                      f"Opposite signal or {cap}m" if policy == "signal_reversal_or_cap" else
                      "Option +target/-stop (close-triggered)" if policy == "premium_target_stop" else
                      f"Opposite signal / {cap}m / option stop-target"),
            **{key: val for key, val in scenario.items()
               if key in ("trade_count", "reversal_switches", "win_rate", "net_pnl_inr", "return_pct",
                          "ending_capital_inr", "max_closed_trade_drawdown_pct",
                          "average_hold_minutes", "unscored")},
        })
    if selected_result is None:
        raise ValueError("Selected option policy was not evaluated")
    research_audit = options_research_audit.audit(
        events, rows, candles, selected=selected_result,
        target_ltp=target_ltp, tolerance=tolerance)
    if progress:
        progress(99, "Saving comparable contract-specific options results")
    return {
        "mode": "HISTORICAL_DHAN_OPTION_OHLC_NEXT_OPEN_PROXY",
        "underlying": "INDEX:BANKNIFTY",
        "signal_source": "Original Dhan one-minute BANKNIFTY spot",
        "auto_downloaded_missing_spot": acquired_spot,
        "signal_model": (EMA_CROSSOVER_VERSION if signal_model == "ema_crossover"
                         else trading_cockpit.VERSION),
        "signal_strategy": signal_model,
        "ema_crossover_rules": ({
            "fast": 9, "slow": 21, "timeframe_minutes": 1,
            "up": "fast EMA crosses strictly above slow after completed candle",
            "down": "fast EMA crosses strictly below slow after completed candle",
            "flat": "no crossover, retain current position until exit policy",
            "entry": "original next-minute option OPEN only",
            "session_reset": True,
        } if signal_model == "ema_crossover" else None),
        "signal_events": len(events),
        "actionable_signals": sum(e["direction"] in ("UP", "DOWN") for e in events),
        "historical_window": {"first": start.isoformat(),
                              "through_exclusive": stop.isoformat(),
                              "observed_index_bars": len(rows)},
        "data_evidence": data_evidence,
        "research_readiness": research_audit,
        "selected_rule_id": selected_id, "selected": selected_result,
        "comparison": comparison,
        "assumptions": {
            "premium_target_inr": target_ltp, "premium_tolerance_inr": tolerance,
            "expiry_flag": expiry_flag, "expiry_code": expiry_code,
            "lots": lots, "historical_lot_size_units": lot_size,
            "lot_size_basis": "USER_INPUT_NOT_VERIFIED_FOR_EXPIRED_CONTRACTS",
            "slippage_bps_per_side": slippage_bps,
            "brokerage_inr_per_side": fee_per_side if fee_mode=="flat" else option_fees.BROKER_PROFILES[fee_mode]["brokerage"],
            "fee_mode":fee_mode,"fee_tariff_version":option_fees.FEE_VERSION if fee_mode!="flat" else None,
            "fee_basis":"Current tariff counterfactual on all historical dates; not historical contract-note reconstruction" if fee_mode!="flat" else "User-specified flat all-in cost per side",
            "profit_target_pct": target_pct, "stop_loss_pct": stop_pct,
            "spot_signal_is_not_option_fill": True,
        },
        "limitations": (
            "Active NSE_FNO contracts can use original security ID, expiry and lot size. "
            "Dhan expired rolling expiry code does not supply immutable per-bar expiry/security ID; "
            "results use same-session matching actual strike and CE/PE only. "
            "Historical lot size is assumed for rolling expired contracts. Dhan option minute OHLC "
            "does NOT include historical bid/ask, 20-level depth or executable fills. "
            "Options are selected by their price at the completed signal minute "
            "and bought next minute OPEN with assumed slippage. Profit targets "
            "and stops are detected only on completed option CLOSE and exited "
            "at the NEXT OPEN, never guaranteed trigger prices. "
            "Opposite-direction signals close the prior long option and may "
            "open a newly selected opposite option at that same NEXT OPEN "
            "only when the second contract's complete source data and "
            "purchasing power exist. No actual broker orders are placed. "
            "Historical option taxes and other levies are not included. "
            "A missing quote path excludes the position and blocks further "
            "trading that session; no fabricated option prices or rollover."),
        "read_only": True, "orders_placed": 0,
    }
