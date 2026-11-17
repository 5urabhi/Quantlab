"""User-authorized Zerodha Kite Connect historical daily closes for Dhan fallback.

No orders or trading endpoints are used. A current instrument master is
downloaded only on explicit in-app request, and matching requires the exact
exchange-issued security token AND exact canonical trading symbol. Zerodha's
master does not publish an ISIN. New prices still pass immutable 3-session
Dhan overlap checks before insertion. Broker tokens never reach the browser.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo
import csv
import gzip
import io
import json
import math
import os
import re
import secrets
import time

from . import compatible_sources, dhan_workspace, service, shared_market_data

KITE = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login"
IST = ZoneInfo("Asia/Kolkata")
MAX_RESPONSE = 20 * 1024 * 1024
MAX_MASTER_UNCOMPRESSED = 60 * 1024 * 1024
MAX_WINDOW_DAYS = 15 * 366
MAX_WINDOWS = 18
REQUEST_INTERVAL = .42  # Kite historical API is capped at 3 requests/second.
TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
KEY = re.compile(r"^[A-Za-z0-9_-]{5,128}$")
SYMBOL = re.compile(r"^[A-Z0-9&_.-]{1,80}$")
_MASTER_LOCK = Lock()
_CALL_LOCK = Lock()
_LOGIN_LOCK = Lock()
_PENDING: dict[str, float] = {}
_LAST_CALL = 0.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Kite endpoint redirected; no credentials were forwarded")


def _base() -> Path:
    base = service.DATA / "research_workspace" / "zerodha"
    if base.is_symlink() or base.parent.is_symlink():
        raise ValueError("Unsafe local Zerodha credentials folder")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base


def _read_session() -> dict:
    path = _base() / "session.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 6000:
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return body if isinstance(body, dict) else {}
    except (ValueError, OSError, UnicodeError):
        return {}


def _api_key() -> str:
    return (os.getenv("KITE_API_KEY") or os.getenv("ZERODHA_API_KEY") or "").strip()


def _secret() -> str:
    return (os.getenv("KITE_API_SECRET") or os.getenv("ZERODHA_API_SECRET") or "").strip()


def _access_token() -> str:
    current = datetime.now(IST)
    saved = _read_session()
    # Expiry is 06:00 IST the day after login. Never reuse a previous day's
    # stored session as if it were still authenticated.
    created = saved.get("created_utc")
    if isinstance(created, str) and saved.get("api_key") == _api_key():
        try:
            login = datetime.fromisoformat(created).astimezone(IST)
            expiry = (login + timedelta(days=1)).replace(hour=6, minute=0,
                                                          second=0, microsecond=0)
            if current < expiry and login <= current:
                return str(saved.get("access_token") or "").strip()
        except ValueError:
            pass
    return (os.getenv("KITE_ACCESS_TOKEN") or
            os.getenv("ZERODHA_ACCESS_TOKEN") or "").strip()


def configured() -> bool:
    return bool(KEY.fullmatch(_api_key()) and TOKEN.fullmatch(_access_token()))


def _request(path: str, *, method: str = "GET",
             form: dict[str, str] | None = None, timeout: int = 25,
             need_auth: bool = True) -> bytes:
    global _LAST_CALL
    if not path.startswith("/") or "//" in path or len(path) > 600:
        raise ValueError("Invalid fixed-host Kite endpoint")
    if method not in ("GET", "POST"):
        raise ValueError("Kite fallback is read-only; unsupported HTTP method")
    if method == "POST" and path != "/session/token":
        raise ValueError("Only the Kite login token exchange may POST")
    key = _api_key()
    token = _access_token()
    if not KEY.fullmatch(key) or (need_auth and not TOKEN.fullmatch(token)):
        raise ValueError("Connect your Kite app and log in from QuantLab")
    data = urlencode(form).encode("ascii") if form else None
    headers = {"X-Kite-Version": "3", "Accept": "application/json",
               "User-Agent": "QuantLabLocalReadOnly/1.0"}
    if need_auth:
        headers["Authorization"] = "token " + key + ":" + token
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    opener = build_opener(_NoRedirect)
    url = KITE + path
    for attempt in range(4):
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with _CALL_LOCK:
                if path.startswith("/instruments/historical/"):
                    delta = REQUEST_INTERVAL - (time.monotonic() - _LAST_CALL)
                    if delta > 0:
                        time.sleep(delta)
                _LAST_CALL = time.monotonic()
                with opener.open(request, timeout=timeout) as response:
                    body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise ValueError("Kite original source response exceeds local size limit")
            return body
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ValueError("Zerodha session expired or historical-data entitlement absent; log in again") from None
            if exc.code in (400, 404, 422):
                raise ValueError("Zerodha cannot provide the exact instrument and historical date window") from None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise ValueError("Zerodha historical provider unavailable; original Dhan prices unchanged") from None
            wait = exc.headers.get("Retry-After", "1")
            try:
                seconds = min(10., max(1., float(wait)))
            except ValueError:
                seconds = 2.
            time.sleep(seconds * (attempt + 1))
        except (TimeoutError, OSError, URLError):
            if attempt == 3:
                raise ValueError("Zerodha network connection failed after bounded retries") from None
            time.sleep(1.5 * (attempt + 1))
    raise ValueError("Zerodha historical request retry budget exhausted")


def _master_file() -> Path:
    return _base() / "instruments.json"


def _parsed_master() -> dict:
    file = _master_file()
    if not file.is_file() or file.is_symlink() or file.stat().st_size > 25_000_000:
        return {}
    try:
        record = json.loads(file.read_text(encoding="utf-8"))
        rows = record.get("instruments", [])
        if not isinstance(record, dict) or not isinstance(rows, list):
            return {}
        if record.get("sha256") != sha256(json.dumps(
                rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
            return {}
        return record
    except (OSError, ValueError, UnicodeError, TypeError):
        return {}


def _master_fresh(record: dict) -> bool:
    try:
        updated = datetime.fromisoformat(record["created_utc"]).astimezone(IST)
        now = datetime.now(IST)
        # A market-open refresh is preferable; last day's master is not
        # a reliable source for changed or renamed securities.
        return updated.date() == now.date() and updated <= now
    except (KeyError, ValueError, TypeError):
        return False


def status() -> dict:
    record = _parsed_master()
    token_present = configured()
    return {
        "provider": "zerodha_kite",
        "primary_provider": False,
        "api_key_configured": bool(KEY.fullmatch(_api_key())),
        "api_secret_configured": bool(_secret()),
        "token_present": token_present,
        "login_required": not token_present,
        "master_available": bool(record),
        "master_current": _master_fresh(record) if record else False,
        "master_generated_utc": record.get("created_utc") if record else None,
        "master_instruments": len(record.get("instruments", [])),
        "callback_url": "http://127.0.0.1:8765/api/data-manager/zerodha/auth/callback",
        "historical_entitlement_verified": False,
        "note": ("Kite historical market data needs an eligible paid subscription. "
                 "Sessions expire after each trading day. Login must be completed "
                 "on Zerodha's official site; QuantLab cannot bypass 2FA."),
    }


def start_login() -> dict:
    if not KEY.fullmatch(_api_key()) or not _secret():
        raise ValueError("Configure KITE_API_KEY and KITE_API_SECRET in the ignored local .env")
    nonce = secrets.token_urlsafe(24)
    with _LOGIN_LOCK:
        _PENDING.clear()
        _PENDING[nonce] = time.monotonic() + 300
    # Kite returns redirect_params as URL query params on the registered
    # callback. This nonce prevents unsolicited callbacks setting a token.
    params = urlencode({"api_key": _api_key(), "v": "3",
                        "redirect_params": urlencode({"quantlab_state": nonce})})
    return {"login_url": LOGIN + "?" + params,
            "callback_url": status()["callback_url"],
            "message": "Complete official Zerodha login in the opened tab."}


def finish_login(request_token: str, state: str) -> dict:
    if not isinstance(request_token, str) or not TOKEN.fullmatch(request_token):
        raise ValueError("Kite did not provide a valid one-time request token")
    with _LOGIN_LOCK:
        known = next((k for k in _PENDING if compare_digest(k, state)), None)
        if not known or _PENDING.pop(known, 0) < time.monotonic():
            raise ValueError("Login expired or unsolicited callback; restart from QuantLab")
    key = _api_key()
    checksum = sha256((key + request_token + _secret()).encode()).hexdigest()
    raw = _request("/session/token", method="POST", need_auth=False,
                   form={"api_key": key, "request_token": request_token,
                         "checksum": checksum})
    try:
        response = json.loads(raw)
        access = response["data"]["access_token"]
        if response.get("status") != "success" or not TOKEN.fullmatch(access):
            raise ValueError("Kite returned an invalid session")
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Kite did not approve the session exchange") from exc
    session = {"api_key": key, "access_token": access,
               "created_utc": datetime.now(timezone.utc).isoformat()}
    path = _base() / "session.json"
    temp = path.with_suffix(".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(session, output)
    finally:
        if temp.is_file():
            os.chmod(temp, 0o600)
    os.replace(temp, path)
    return {"connected": True, "provider": "zerodha_kite",
            "next_action": "Refresh the Kite instrument master in QuantLab"}


def verify_session() -> dict:
    data = _request("/user/profile")
    try:
        parsed = json.loads(data)
        if parsed.get("status") != "success":
            raise ValueError("Kite did not confirm an authenticated session")
        details = parsed.get("data", {})
        return {"authenticated": True,
                "user_id_suffix": str(details.get("user_id", ""))[-3:],
                "historical_entitlement_verified": False,
                "note": "Account login verified; history entitlement is checked by the actual data request."}
    except (TypeError, ValueError):
        raise ValueError("Kite session profile verification failed") from None


def _parse_master(body: bytes, exchange: str) -> list[dict]:
    if len(body) > MAX_RESPONSE:
        raise ValueError("Kite instrument master exceeds bounded response size")
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    if len(body) > MAX_MASTER_UNCOMPRESSED:
        raise ValueError("Kite instrument master decompressed beyond the size limit")
    try:
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""))
        expected = {"instrument_token", "exchange_token", "tradingsymbol",
                    "instrument_type", "segment", "exchange"}
        if not expected.issubset(reader.fieldnames or []):
            raise ValueError("Kite instrument master is missing official columns")
        result = []
        seen = set()
        for row in reader:
            if row.get("exchange") != exchange or row.get("segment") != exchange:
                continue
            if row.get("instrument_type") != "EQ" or row.get("expiry", ""):
                continue
            ident = str(row["exchange_token"]).strip()
            token = str(row["instrument_token"]).strip()
            symbol = str(row["tradingsymbol"]).strip().upper()
            if not ident.isdigit() or not token.isdigit() or not SYMBOL.fullmatch(symbol):
                continue
            key = exchange + ":" + ident
            if key in seen:
                raise ValueError("Kite master has conflicting duplicate exchange tokens")
            seen.add(key)
            result.append({"exchange": exchange, "exchange_token": ident,
                           "instrument_token": token, "tradingsymbol": symbol})
            if len(result) > 20_000:
                raise ValueError("Unexpectedly large Kite equity instrument master")
        return result
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Kite instrument master could not be parsed") from exc


def refresh_master(*, progress=None) -> dict:
    if not configured():
        raise ValueError("Log in to Kite Connect before refreshing its instrument master")
    with _MASTER_LOCK:
        records = []
        for i, exchange in enumerate(("NSE", "BSE")):
            if progress:
                progress(10 + i * 35, "Loading authorized " + exchange + " cash-equity master")
            data = _request("/instruments/" + exchange, timeout=45)
            records.extend(_parse_master(data, exchange))
        if not records:
            raise ValueError("Zerodha supplied no authentic NSE/BSE equity instruments")
        records.sort(key=lambda row: (row["exchange"], int(row["exchange_token"])))
        signature = sha256(json.dumps(records, sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest()
        record = {"version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                  "sha256": signature, "instruments": records}
        path = _master_file()
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(record, output, separators=(",", ":"))
        os.replace(temporary, path)
    if progress:
        progress(100, "Exact equity exchange-token index refreshed")
    return {"ready": True, "instruments": len(records),
            "sha256": signature, "timestamp_utc": record["created_utc"],
            "includes_nse": True, "includes_bse": True,
            "warning": "Kite instrument tokens are not historical constituent certificates."}


def _map_instrument(original: dict, *, allow_stale: bool = False) -> dict:
    exchange_segment = str(original.get("exchange_segment", ""))
    security = str(original.get("security_id", ""))
    symbol = str(original.get("symbol", "")).strip().upper()
    if exchange_segment not in ("NSE_EQ", "BSE_EQ") or not security.isdigit():
        raise ValueError("Kite fallback supports exact NSE/BSE cash equity IDs only")
    if not original.get("trading_symbol_verified", False) or not original.get("regular_eq", False):
        raise ValueError("Dhan trading symbol or EQ series not independently identified")
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("Dhan master lacks a canonical exchange-traded symbol")
    master = _parsed_master()
    if not master:
        raise ValueError("Download the authenticated Kite equity instrument master first")
    if not allow_stale and not _master_fresh(master):
        raise ValueError("Kite equity master is stale; refresh it before using tokens")
    exchange = exchange_segment[:3]
    matches = [r for r in master["instruments"]
               if r["exchange"] == exchange and
               r["exchange_token"] == security]
    if len(matches) != 1 or matches[0]["tradingsymbol"] != symbol:
        raise ValueError("Kite exchange token and exact Dhan symbol do not agree")
    return {"canonical_identity": exchange_segment + ":" + security,
            "kite_instrument_token": matches[0]["instrument_token"],
            "exchange": exchange, "exchange_token": security,
            "trading_symbol": symbol,
            "matched_by": "exchange+exchange_token+exact_tradingsymbol"}


def eligibility(original: dict) -> dict:
    try:
        record = _map_instrument(original)
        return {"eligible": configured(), "configured": configured(),
                "identity_verified": True,
                "provider": "zerodha_kite",
                "source_instrument_token_suffix": record["kite_instrument_token"][-4:],
                "reason": ("Exact Dhan/Kite equity mapping available" if configured()
                           else "Log in to the paid market-data-enabled Kite API")}
    except (ValueError, OSError) as exc:
        return {"eligible": False, "configured": configured(),
                "identity_verified": False, "provider": "zerodha_kite",
                "reason": str(exc)[:180]}


def _normalize(body: bytes) -> list[tuple[str, float]]:
    try:
        data = json.loads(body)
        candles = data.get("data", {}).get("candles", [])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Zerodha returned invalid historical candle JSON") from exc
    if not isinstance(data, dict) or data.get("status") != "success" or not isinstance(candles, list):
        raise ValueError("Zerodha historical provider did not return candle records")
    if len(candles) > 510:
        raise ValueError("Zerodha returned an unexpectedly large daily candle window")
    rows = {}
    for item in candles:
        if not isinstance(item, list) or len(item) < 6:
            raise ValueError("Zerodha candle lacks original daily OHLCV fields")
        try:
            timestamp = datetime.fromisoformat(str(item[0]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Zerodha source timestamp has no timezone")
            day = timestamp.astimezone(IST).date()
            op, high, low, close, volume = [float(item[i]) for i in (1,2,3,4,5)]
        except (ValueError, TypeError, OverflowError) as exc:
            if isinstance(exc, ValueError) and "timezone" in str(exc):
                raise ValueError("Zerodha source timestamp has no timezone") from exc
            raise ValueError("Zerodha source contains invalid OHLCV/timestamp") from exc
        if (day > datetime.now(IST).date() or day.year < 1990
                or not all(math.isfinite(v) and v > 0 for v in (op, high, low, close))
                or high < max(op, close, low) or low > min(op, high, close)
                or not math.isfinite(volume) or volume < 0):
            raise ValueError("Zerodha original daily candle violates OHLCV integrity")
        if day.isoformat() in rows:
            raise ValueError("Zerodha sent multiple bars for one trading session")
        rows[day.isoformat()] = close
    return sorted(rows.items())


def retrieve(original: dict, start: date, stop: date, *,
             confirm_authorized: bool, progress=None) -> dict:
    if not confirm_authorized:
        raise ValueError("Confirm authorized read-only Zerodha fallback first")
    if not configured():
        raise ValueError("Zerodha API session missing or expired; log in from Data Manager")
    mapping = _map_instrument(original)
    if start >= stop or (stop-start).days > MAX_WINDOW_DAYS:
        raise ValueError("Invalid Zerodha historical window (max 15 years)")
    first = max(date(2000, 1, 1), start - timedelta(days=60))
    windows = []
    cursor = first
    while cursor < stop:
        end = min(stop, cursor + timedelta(days=365))
        windows.append((cursor, end))
        cursor = end
    if len(windows) > MAX_WINDOWS:
        raise ValueError("Too many Zerodha historical date windows")
    rows: dict[str, float] = {}
    token = mapping["kite_instrument_token"]
    for i, (begin, end) in enumerate(windows):
        params = urlencode({"from": begin.isoformat() + " 00:00:00",
                            "to": (end - timedelta(days=1)).isoformat() + " 23:59:59",
                            "continuous": "0", "oi": "0"})
        raw = _request("/instruments/historical/" + quote(token, safe="") +
                       "/day?" + params)
        for day, close in _normalize(raw):
            if not begin.isoformat() <= day < end.isoformat():
                raise ValueError("Zerodha returned data outside the approved date range")
            if day in rows and not math.isclose(rows[day], close, rel_tol=1e-10):
                raise ValueError("Zerodha returned contradictory daily close observations")
            rows[day] = close
        if progress:
            progress(25 + 65 * (i+1)/len(windows),
                     "Original Zerodha daily windows " + str(i+1) + "/" + str(len(windows)))
    if not rows:
        raise ValueError("Zerodha supplied no daily closes for the requested security")
    payload = ("date,close\n" + "".join(
        d + "," + format(p, ".12g") + "\n" for d,p in sorted(rows.items()))).encode()
    result = compatible_sources.import_original(
        payload=payload, identity=mapping["canonical_identity"],
        provider="zerodha_kite", confirm_authorized=True, confirm_unadjusted=True)
    if result["status"] != "imported":
        raise ValueError("Zerodha original history blocked by Dhan-overlap gate: " +
                         "; ".join(result.get("blockers", []))[:200])
    return {"provider": "zerodha_kite", "identity": mapping["canonical_identity"],
            "rows_added": result.get("rows_added", 0),
            "matched_sessions": result["matched_sessions"],
            "source_receipt_id": result["id"],
            "source_sha256": result["source_sha256"],
            "identity_match": mapping["matched_by"]}
