"""Conservative, source-compatible alternative import for Dhan outages.

An authorized *original daily unadjusted-close CSV* may append missing dates
only when it is explicitly tied to an EXISTING exchange+security identity and
matches at least three overlapping original canonical Dhan closes. Without
overlap, conflicting closes, compatible basis or user source rights, preserve
a quarantined evidence copy but never promote it to research observations.

This is a local verified fallback, NOT a license to scrape Yahoo, NSE MCP,
or any exchange, and not an automatic TRI/index-membership substitute.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
import csv
import io
import json
import math
import os
import re
import sqlite3
import uuid

import pandas as pd

from . import service, shared_market_data, columnar_cache

LOCK = RLock()
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 150_000
MIN_MATCHED = 3
PROVIDERS = {
    "dhan_export": "Dhan original downloaded CSV",
    "licensed_vendor_csv": "Other authorized original daily-close provider",
}
SOURCE_ID = re.compile(r"^[0-9a-f]{20}$")


def _folder() -> Path:
    root = service.DATA / "research_workspace" / "compatible_sources"
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Unsafe compatible-source storage")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parse_csv(payload: bytes) -> tuple[list[tuple[str, float]], str]:
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("Original CSV must be between 1 byte and 20 MB")
    digest = sha256(payload).hexdigest()
    try:
        decoded = payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        if not reader.fieldnames or len(reader.fieldnames) > 30:
            raise ValueError("Original source requires date and close headers")
        fieldnames = [k.strip().lower() for k in reader.fieldnames]
        if len(fieldnames) != len(set(fieldnames)):
            raise ValueError("Duplicate source CSV header names")
        date_idx = next((i for i,k in enumerate(fieldnames) if k in
                         {"date", "session_date", "trading_date"}), None)
        close_idx = next((i for i,k in enumerate(fieldnames) if k in
                          {"close", "closing_price", "close_price"}), None)
        if date_idx is None or close_idx is None:
            raise ValueError("Original source needs date and unadjusted close columns")
        if any(k in fieldnames for k in
               {"adj_close", "adjusted_close", "total_return", "tri", "dividend_adjusted"}):
            raise ValueError("Adjusted/total-return data must not be mixed with Dhan raw closes")
        rows = []
        seen = set()
        for row in reader:
            if len(rows) >= MAX_ROWS:
                raise ValueError("Too many daily observations in one source; split the CSV")
            values = list(row.values())
            day = str(values[date_idx] or "").strip()
            price = str(values[close_idx] or "").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError("Dates must use unambiguous YYYY-MM-DD daily sessions")
            stamp = date.fromisoformat(day)
            if stamp > date.today() or stamp.year < 1990 or day in seen:
                raise ValueError("Future, repeated, or invalid original trading dates")
            seen.add(day)
            value = float(price)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Original closing prices must be positive and finite")
            rows.append((day, value))
        if not rows:
            raise ValueError("Source CSV contains no original daily close observations")
        rows.sort()
        return rows, digest
    except (UnicodeError, csv.Error, IndexError, TypeError) as exc:
        raise ValueError("Source CSV is not a valid UTF-8 daily-close table") from exc


def _canonical_matches(identity: str, rows: list[tuple[str,float]]) -> dict:
    if not shared_market_data.SAFE_IDENTITY.fullmatch(identity or ""):
        raise ValueError("Use an exact NSE/BSE Security ID from the canonical instrument list")
    db = shared_market_data.database_path()
    if not db.is_file() or db.is_symlink():
        raise ValueError("No original Dhan shared market database is available")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        instrument = conn.execute(
            "SELECT exchange_segment,security_id,display_symbol "
            "FROM instruments WHERE identity=?", (identity,)).fetchone()
        if instrument is None:
            raise ValueError("Instrument has no exact canonical Dhan identity")
        # A bounded range lookup is indexed by (identity,session_date).
        baseline = dict(conn.execute(
            "SELECT session_date,close FROM daily_closes "
            "WHERE identity=? AND session_date BETWEEN ? AND ?",
            (identity, rows[0][0], rows[-1][0])).fetchall())
    overlaps = [day for day,price in rows if day in baseline]
    mismatches = [
        day for day,price in rows if day in baseline and
        not math.isclose(price, baseline[day], rel_tol=2e-5, abs_tol=0.02)
    ]
    return {
        "matched_sessions": len(overlaps) - len(mismatches),
        "overlap_sessions": len(overlaps),
        "mismatch_dates": mismatches[:6],
        "conflicting_sessions": len(mismatches),
        "new_sessions": sum(day not in baseline for day,_ in rows),
        "instrument": {
            "exchange_segment": instrument[0],
            "security_id": instrument[1],
            "display_symbol": instrument[2],
        },
    }


def _receipt(id_: str, result: dict) -> None:
    # Metadata excludes local filesystem paths and uploaded source content.
    target = _folder() / id_ / "receipt.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    os.replace(temp, target)


def import_original(*, payload: bytes, identity: str, provider: str,
                    confirm_authorized: bool, confirm_unadjusted: bool) -> dict:
    if provider not in PROVIDERS:
        raise ValueError("Select a registered original data source")
    if not confirm_authorized or not confirm_unadjusted:
        raise ValueError("Confirm source rights and original unadjusted daily closes")
    rows, digest = _parse_csv(payload)
    # Never create a new identity or infer security IDs from ticker aliases.
    policy = _canonical_matches(identity, rows)
    reasons = []
    if policy["conflicting_sessions"]:
        reasons.append("Original closes conflict on " +
                       ", ".join(policy["mismatch_dates"]) + "; data was not merged.")
    if policy["matched_sessions"] < MIN_MATCHED:
        reasons.append(f"Require at least {MIN_MATCHED} agreeing Dhan sessions "
                       "for exact identity and price basis before using another provider.")
    source_id = uuid.uuid4().hex[:20]
    folder = _folder() / source_id
    with LOCK:
        folder.mkdir(exist_ok=False)
        (folder / "original.csv").write_bytes(payload)
        result = {
            "id": source_id, "provider": provider,
            "provider_label": PROVIDERS[provider],
            "identity": identity, "frequency": "daily",
            "price_basis": "unadjusted_close",
            "source_sha256": digest, "source_rights_user_confirmed": True,
            "overlap_sessions": policy["overlap_sessions"],
            "matched_sessions": policy["matched_sessions"],
            "conflicting_sessions": policy["conflicting_sessions"],
            "new_sessions": policy["new_sessions"],
            "source_rows": len(rows), "first_date": rows[0][0],
            "last_date": rows[-1][0],
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "blocked" if reasons else "validated",
            "blockers": reasons,
            "warning": "An overlap check verifies consistency with existing Dhan "
                       "observations; it does not independently certify the external "
                       "vendor, corporate actions, licensing or historical index membership.",
        }
        _receipt(source_id, result)
        if reasons:
            return result
        frame = pd.DataFrame(
            {"close": [price for _,price in rows]},
            index=pd.DatetimeIndex([day for day,_ in rows], name="date"))
        mapping = {
            **policy["instrument"], "source_sha256": digest,
            "display_symbol": policy["instrument"]["display_symbol"],
        }
        try:
            outcome = shared_market_data.ingest(
                [(mapping, frame)], origin="fallback_" + source_id)
            result.update(
                status="imported", rows_added=outcome["rows_appended"],
                reused_rows=outcome["rows_reused"],
                destination_dataset_id=shared_market_data.SHARED_ID)
        except (ValueError, sqlite3.Error, OSError) as exc:
            result["status"] = "blocked"
            result["blockers"] = [
                "Shared market store rejected the source; original evidence preserved. "
                + str(exc)[:160]]
        if result["status"] == "imported":
            try:
                result["analytics_cache"] = columnar_cache.refresh_if_enabled()
            except (ValueError, OSError, sqlite3.Error):
                result["analytics_cache"] = {"state": "manual_refresh_needed"}
        _receipt(source_id, result)
        return result


def list_receipts(limit: int = 50) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("Invalid source receipt page")
    root = _folder()
    receipts = []
    for item in sorted(root.iterdir(), key=lambda p:p.stat().st_mtime_ns,
                       reverse=True):
        if len(receipts) >= limit:
            break
        if not item.is_dir() or item.is_symlink() or not SOURCE_ID.fullmatch(item.name):
            continue
        file = item / "receipt.json"
        if not file.is_file() or file.is_symlink() or file.stat().st_size > 10_000:
            continue
        try:
            body = json.loads(file.read_text(encoding="utf-8"))
            receipts.append(body)
        except (ValueError, OSError, UnicodeError):
            continue
    return {"sources": receipts, "permanent_original_evidence_preserved": True,
            "rule": "No alias-based identity merging, adjusted prices, or unverified sessions."}


def registry() -> dict:
    return {"providers": [
        {"id": "dhan_original", "label": "Dhan historical API + verified candle cache",
         "mode": "automatic_cached_then_authorized_read_only",
         "compatible": True},
        {"id": "dhan_export", "label": PROVIDERS["dhan_export"],
         "mode": "in_app_csv_import_with_overlap_check", "compatible": True},
        {"id": "licensed_vendor_csv", "label": PROVIDERS["licensed_vendor_csv"],
         "mode": "in_app_csv_import_with_overlap_check", "compatible": True},
        {"id": "nse_mcp", "label": "NSE informational MCP",
         "mode": "informational_only_not_raw_history", "compatible": False},
        {"id": "tri", "label": "Official Total Return Index history",
         "mode": "separate_authorized_source_required", "compatible": False},
    ], "source_claims_independently_audited": False}
