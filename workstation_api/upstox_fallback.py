"""Optional authenticated Upstox V3 historical daily candles as a safe Dhan fallback.

Uses the currently configured local UPSTOX_ACCESS_TOKEN only, never a browser
credential. An exact Dhan-master ISIN maps to NSE_EQ|ISIN / BSE_EQ|ISIN.
Every Upstox observation must pass the same immutable cross-provider overlap
validator as manual original CSV intake; no ticker guessing, adjustment mixing
or automated provenance waiver is allowed. This adapter is read-only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
import io
import json
import math
import os
import re
import time

from . import compatible_sources, dhan_workspace, shared_market_data

HOST = "https://api.upstox.com"
ISIN = re.compile(r"^IN[A-Z0-9]{10}$")
MAX_DAYS = 365 * 15
MAX_REQUESTS = 18
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
LOCK = RLock()
_LAST_CALL = 0.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Upstox historical endpoint redirected; credential not forwarded")


def configured() -> bool:
    return bool(os.getenv("UPSTOX_ACCESS_TOKEN", "").strip())


def _map_instrument(original: dict) -> dict:
    """ISIN must originate in the official Dhan master, never from ticker."""
    key = str(original.get("id") or
              f"{original.get('exchange_segment','')}:{original.get('security_id','')}")
    if not shared_market_data.SAFE_IDENTITY.fullmatch(key):
        raise ValueError("Exact original NSE/BSE Dhan Security ID is required")
    try:
        master = next(r for r in dhan_workspace.catalog() if r["id"] == key)
    except (StopIteration, FileNotFoundError):
        raise ValueError("Refresh Dhan instrument master; no exact exchange identity found") from None
    isin = str(master.get("isin") or "").strip().upper()
    if not ISIN.fullmatch(isin):
        raise ValueError("Dhan instrument master has no valid original ISIN for " + key)
    segment = master["exchange_segment"]
    if not segment in ("NSE_EQ", "BSE_EQ"):
        raise ValueError("Upstox fallback supports cash equity only")
    if master["security_id"] != str(original["security_id"]):
        raise ValueError("Master security ID changed; refresh and review identity")
    return {
        "canonical_identity": key,
        "instrument_key": f"{segment}|{isin}",
        "isin": isin,
        "dhan_master_security": master["security_id"],
        "symbol": master["symbol"],
    }


def eligibility(original: dict) -> dict:
    try:
        mapping = _map_instrument(original)
    except (ValueError, OSError) as exc:
        return {"eligible": False, "configured": configured(),
                "reason": str(exc)[:180], "identity_verified": False}
    return {
        "eligible": configured(), "configured": configured(),
        "identity_verified": True,
        "provider": "upstox_v3", "source_instrument_key": mapping["instrument_key"],
        "reason": ("Optional authorized secondary API ready" if configured()
                   else "Set UPSTOX_ACCESS_TOKEN in ignored local .env to enable"),
    }


def _download_url(url: str, token: str) -> bytes:
    """Fixed HTTPS Upstox host, no redirects, bounded transport retries."""
    global _LAST_CALL
    if not url.startswith(HOST + "/v3/historical-candle/") or not token:
        raise ValueError("Unapproved historical provider endpoint")
    # Token never appears in URL or logging; redirects are rejected.
    request = Request(
        url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": "QuantLabLocalResearch/1.0",
        })
    opener = build_opener(_NoRedirect)
    for attempt in range(4):
        try:
            with LOCK:
                delay = max(0.0, 0.65 - (time.monotonic() - _LAST_CALL))
                if delay:
                    time.sleep(delay)
                _LAST_CALL = time.monotonic()
                with opener.open(request, timeout=25) as stream:
                    data = stream.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("Upstox historical response exceeds safe byte limit")
            return data
        except HTTPError as exc:
            if exc.code in (401,403):
                raise ValueError("Upstox token expired or Data API entitlement unavailable") from None
            if exc.code in (400,404,422):
                raise ValueError("Upstox cannot supply the selected exact instrument/window") from None
            if exc.code not in (429,500,502,503,504) or attempt == 3:
                raise ValueError("Upstox historical request failed; original data unchanged") from None
            retry_after = exc.headers.get("Retry-After", "1")
            try:
                delay = min(10.0, max(1.0, float(retry_after)))
            except ValueError:
                delay = 2.0
            time.sleep(delay * (attempt + 1))
        except (OSError, URLError, TimeoutError):
            if attempt == 3:
                raise ValueError("Upstox connection unavailable after bounded retry") from None
            time.sleep(1.5 * (attempt + 1))
    raise ValueError("Secondary historical provider retry budget exhausted")


def _normalize(body: bytes) -> list[tuple[str, float]]:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Upstox returned invalid historical JSON") from exc
    if not isinstance(data, dict) or data.get("status") != "success":
        raise ValueError("Upstox historical provider did not report successful data")
    candles = data.get("data", {}).get("candles") if isinstance(data.get("data"), dict) else None
    if not isinstance(candles, list) or len(candles) > 5000:
        raise ValueError("Upstox historical daily window has invalid candle count")
    rows = {}
    from zoneinfo import ZoneInfo
    for candle in candles:
        if not isinstance(candle, list) or len(candle) < 6:
            raise ValueError("Upstox candle is incomplete")
        try:
            stamp = datetime.fromisoformat(str(candle[0]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Upstox candle lacks a timezone")
            session = stamp.astimezone(ZoneInfo("Asia/Kolkata")).date()
            opening, high, low, close, volume = (float(candle[i]) for i in (1,2,3,4,5))
        except (TypeError, ValueError, OverflowError) as exc:
            if isinstance(exc, ValueError) and str(exc) == "Upstox candle lacks a timezone":
                raise ValueError("Upstox candle lacks a timezone") from exc
            raise ValueError("Upstox candle contains an invalid timestamp or OHLCV") from exc
        if (session > date.today() or session.year < 1990
                or not all(math.isfinite(v) and v > 0 for v in (opening, high, low, close))
                or not math.isfinite(volume) or volume < 0
                or high < max(opening, close, low)
                or low > min(opening, close, high)):
            raise ValueError("Upstox candle violates daily OHLCV integrity")
        day = session.isoformat()
        if day in rows:
            raise ValueError("Upstox returned multiple candles for one daily session")
        rows[day] = close
    return sorted(rows.items())


def _windows(first: date, last: date) -> list[tuple[date, date]]:
    windows = []
    cursor = first
    while cursor < last:
        step = min(last, cursor + timedelta(days=365))
        windows.append((cursor,step))
        cursor = step
    return windows


def retrieve(original: dict, start: date, stop: date, *,
             confirm_authorized: bool, progress=None) -> dict:
    """Fetch only approved daily windows plus original overlap anchor.

    stop is exclusive. Extend backwards 45 calendar days to provide a
    real matching Dhan window even when the missing range begins today.
    If three agreeing observations cannot be found, the original source is
    retained as a blocked receipt and no market data are appended.
    """
    if not confirm_authorized:
        raise ValueError("Approve the Upstox read-only fallback before any provider request")
    if not configured():
        raise ValueError("UPSTOX_ACCESS_TOKEN is absent from ignored local .env")
    mapping = _map_instrument(original)
    if start >= stop or (stop - start).days > MAX_DAYS:
        raise ValueError("Fallback historical scope must be positive and at most 15 years")
    first = max(date(2000,1,1), start - timedelta(days=45))
    windows = _windows(first, stop)
    if len(windows) > MAX_REQUESTS:
        raise ValueError("Too many Upstox daily history requests")
    token = os.getenv("UPSTOX_ACCESS_TOKEN","").strip()
    readings = {}
    for i,(begin,end) in enumerate(windows):
        url = (
            HOST + "/v3/historical-candle/" +
            quote(mapping["instrument_key"], safe="") +
            "/days/1/" + (end - timedelta(days=1)).isoformat() +
            "/" + begin.isoformat()
        )
        response = _normalize(_download_url(url, token))
        for day, close in response:
            if day < begin.isoformat() or day >= end.isoformat():
                raise ValueError("Upstox returned observations outside requested dates")
            if day in readings and not math.isclose(readings[day],close,rel_tol=1e-10):
                raise ValueError("Conflicting Upstox candles in retrieved date windows")
            readings[day] = close
        if progress:
            progress(20 + 55 * (i+1)/len(windows),
                     f"Read-only secondary source {i+1}/{len(windows)}")
    if not readings:
        raise ValueError("Upstox provided no original daily observations in requested scope")
    lines = ["date,close"] + [f"{d},{v:.12g}" for d,v in sorted(readings.items())]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    result = compatible_sources.import_original(
        payload=payload, identity=mapping["canonical_identity"],
        provider="upstox_v3",confirm_authorized=True,confirm_unadjusted=True)
    if result["status"] != "imported":
        raise ValueError("Secondary source blocked by original-price overlap gate: " +
                         "; ".join(result.get("blockers",[]))[:220])
    return {
        "provider": "upstox_v3", "identity": mapping["canonical_identity"],
        "rows_added": result.get("rows_added",0),
        "matched_sessions": result["matched_sessions"],
        "source_sha256": result["source_sha256"],
        "source_receipt_id": result["id"],
        "no_unchecked_identity_replacement": True,
    }
