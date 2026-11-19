"""Read-only, source-verified candle adapter for intraday research.

Equities reuse the existing SHA-verified minute Parquet view. BANKNIFTY/NIFTY
spot indices reuse Dhan's optional IDX_I historical batch evidence; never
substitute futures or reconstruct missing index candles from today's members.
"""
from __future__ import annotations

from collections import deque
from datetime import date, timedelta
import uuid
from hashlib import sha256
from pathlib import Path
import csv
import json
import re

from . import dhan_workspace, intraday_parquet, index_spot, service

INDEX_IDENTITIES = {
    "INDEX:BANKNIFTY": ("BANKNIFTY_INDEX", "Bank Nifty · Dhan spot index"),
    "INDEX:NIFTY50": ("NIFTY50_INDEX", "Nifty 50 · Dhan spot index"),
}
BATCH = re.compile(r"^batch_[a-f0-9]{16}$")
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024
MAX_CSV_ROWS = 1_200_000


def _root() -> Path:
    return service.DATA / "dhan" / "index_spot"


def _candidates(identity: str) -> list[tuple[Path, Path, dict]]:
    if identity not in INDEX_IDENTITIES:
        raise ValueError("Unknown index identity")
    root = _root()
    if root.is_symlink() or not root.is_dir():
        return []
    basename, _ = INDEX_IDENTITIES[identity]
    results: list[tuple[Path, Path, dict]] = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir() or folder.is_symlink() or not BATCH.fullmatch(folder.name):
            continue
        source = folder / (basename + "_intraday_1m.csv")
        manifest = folder / (basename + "_intraday_1m.manifest.json")
        if (not source.is_file() or source.is_symlink() or not manifest.is_file()
                or manifest.is_symlink() or not 0 < source.stat().st_size <= MAX_FILE_BYTES
                or not 0 < manifest.stat().st_size <= MAX_MANIFEST_BYTES):
            continue
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError, UnicodeError):
            continue
        inst = metadata.get("instrument") or {}
        if (metadata.get("source") != "DhanHQ REST API v2"
                or metadata.get("interval_minutes") != 1
                or inst.get("label") != basename
                or inst.get("exchange_segment") != "IDX_I"
                or inst.get("instrument") != "INDEX"
                or not str(inst.get("security_id", "")).isdigit()
                or not isinstance(metadata.get("row_count"), int)
                or not 0 < metadata["row_count"] <= MAX_CSV_ROWS
                or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("sha256", "")))):
            continue
        results.append((source, manifest, metadata))
    return results


def _selected_index(identity: str) -> tuple[Path, dict] | None:
    candidates = _candidates(identity)
    if not candidates:
        return None
    # Latest original retrieved_utc rather than lexicographic batch ID.
    source, _manifest, metadata = max(
        candidates, key=lambda candidate: (
            str(candidate[2].get("retrieved_utc", "")), candidate[0].name))
    return source, metadata


def catalog(limit: int = 200) -> dict:
    existing = intraday_parquet.catalog(limit)
    try:
        names = {row["id"]: row for row in dhan_workspace.catalog()}
    except (OSError, ValueError):
        names = {}
    result = []
    for identity, (_basename, display) in INDEX_IDENTITIES.items():
        source = _selected_index(identity)
        result.append({
            "identity": identity, "display_name": display, "asset_class": "spot_index",
            "ready": bool(source), "state": "source_available" if source else "not_downloaded",
            "source": "Dhan original IDX_I batch, 1-minute historical" if source else None,
            "needs_download": not bool(source), "needs_preparation": False,
        })
    for item in existing["instruments"]:
        record = names.get(item["identity"], {})
        symbol = record.get("symbol") or item["identity"]
        result.append({**item, "display_name": symbol, "asset_class": "equity",
                       "company_name": record.get("display_name"),
                       "needs_download": False,
                       "needs_preparation": bool(item["source_available"] and not item["ready"])})
    return {
        "instruments": result, "interval_minutes": 1,
        "prepared_equities": sum(1 for item in result if item["asset_class"] == "equity" and item["ready"]),
        "downloaded_equities_pending_preparation": sum(
            1 for item in result if item["asset_class"] == "equity" and item["needs_preparation"]),
        "warning": ("Spot-index candles require a verified original Dhan IDX_I "
                    "one-minute batch. No index volume/VWAP, live streaming or "
                    "broker execution is inferred."),
    }


def series(identity: str, *, limit: int = 500) -> dict:
    if identity not in INDEX_IDENTITIES:
        return intraday_parquet.series(identity, limit=limit)
    if not 1 <= limit <= intraday_parquet.MAX_PER_QUERY:
        raise ValueError("Minute-candle query exceeds limit")
    choice = _selected_index(identity)
    if choice is None:
        raise ValueError("Download an original Dhan IDX_I one-minute Bank Nifty/Nifty index spot batch first")
    source, metadata = choice
    count = 0
    latest: deque[dict] = deque(maxlen=limit+1)
    digest = sha256()
    previous = ""
    # Read only from validated original batch. Recheck after reading to
    # refuse content modified in transit or a changed manifest.
    with source.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES+1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Original index file exceeds source limit")
    digest.update(raw)
    if digest.hexdigest() != metadata["sha256"]:
        raise ValueError("Original index spot SHA-256 mismatch")
    try:
        contents = raw.decode("utf-8-sig").splitlines()
        reader = csv.DictReader(contents)
        required = {"datetime", "open", "high", "low", "close", "volume"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Original index file has invalid OHLCV headers")
        for row in reader:
            timestamp, ist_date, op, hi, lo, close, volume = intraday_parquet._decode(row)
            if timestamp <= previous:
                raise ValueError("Original index spot timestamps are repeated or not increasing")
            previous = timestamp
            count += 1
            if count > MAX_CSV_ROWS:
                raise ValueError("Original index source has too many rows")
            latest.append({
                "timestamp_utc": timestamp, "session_ist": ist_date,
                "open": op, "high": hi, "low": lo, "close": close,
                "volume": volume,
            })
    except UnicodeError as exc:
        raise ValueError("Original index file is not valid UTF-8") from exc
    if count != metadata["row_count"]:
        raise ValueError("Original index source row count differs from manifest")
    if not count:
        raise ValueError("Original index source is empty")
    return {
        "identity": identity, "rows": list(latest)[-limit:],
        "has_more": count > limit, "interval_minutes": 1,
        "basis": "original_Dhan_IDX_I_unadjusted_spot_index",
        "warning": ("SHA-verified historical index spot candles; zero index "
                    "volume has no VWAP meaning. Not live, not an options quote."),
        "source_file_sha256": metadata["sha256"],
    }


def prepare_local(identities: list[str] | None = None, *, progress=None) -> dict:
    """Build disposable one-minute chart views from *existing* SHA-verified caches.

    No vendor calls, dataset duplication, or price reconstruction. An optional
    list restricts automatic post-download preparation to its original batch.
    Bounded work avoids unpredictable CPU/disk costs for large universes.
    """
    if identities is None:
        # Prefer sources that actually need building; a large library of
        # already-ready securities must not starve new missing chart views.
        candidates = [entry["identity"] for entry in intraday_parquet.catalog(300)["instruments"]
                      if entry["source_available"] and not entry["ready"]]
    else:
        candidates = list(dict.fromkeys(identities))
    total_candidates = len(candidates)
    candidates = candidates[:40]
    prepared, reused, skipped = [], [], []
    max_file_bytes = 80 * 1024 * 1024
    max_total_bytes = 500 * 1024 * 1024
    allocated = 0
    for i, identity in enumerate(candidates):
        if progress:
            progress(4 + 90 * i / max(1, len(candidates)),
                     "Preparing existing one-minute charts " + str(i + 1) +
                     "/" + str(len(candidates)))
        try:
            state = intraday_parquet.status(identity)
            if state["ready"]:
                reused.append(identity)
                continue
            if not state["source_available"]:
                skipped.append({"identity": identity, "reason": "original one-minute source missing"})
                continue
            if not state["engine_available"]:
                skipped.append({"identity": identity, "reason": "DuckDB is not installed"})
                continue
            size = state["source_bytes"]
            if size > max_file_bytes or allocated + size > max_total_bytes:
                skipped.append({"identity": identity, "reason":
                                "Existing minute source exceeds automatic preparation budget"})
                continue
            intraday_parquet.build(identity)
            allocated += size
            prepared.append(identity)
        except (ValueError, OSError) as exc:
            skipped.append({"identity": identity, "reason": str(exc)[:160]})
    if progress:
        progress(100, "Shared one-minute chart views checked")
    return {
        "canonical_library_id": "dhan_shared",
        "original_sources_unchanged": True, "external_market_requests": 0,
        "checked": len(candidates), "remaining_unselected": max(0, total_candidates - len(candidates)),
        "prepared_count": len(prepared),
        "already_ready_count": len(reused), "blocked_count": len(skipped),
        "prepared": prepared, "already_ready": reused, "blocked": skipped,
        "note": ("One shared market-data library with per-instrument source-backed "
                 "one-minute chart indexes, not separate datasets."),
    }


def download_spot(identity: str, from_date: str, to_date: str, *, progress=None) -> dict:
    """Only a user-approved Dhan IDX_I download; never synthesize index from stocks."""
    if identity not in INDEX_IDENTITIES:
        raise ValueError("Select BANKNIFTY or NIFTY 50 spot index")
    start, stop = date.fromisoformat(from_date), date.fromisoformat(to_date)
    if not start < stop <= date.today() + timedelta(days=1):
        raise ValueError("Choose a valid historical date window (end exclusive)")
    if (stop - start) > timedelta(days=90):
        raise ValueError("Request up to 90 calendar days of index history at a time")
    if progress:
        progress(10, "Requesting original Dhan spot index candles")
    selection = "banknifty_pit" if identity == "INDEX:BANKNIFTY" else "nifty50_pit"
    result = index_spot.download({
        "id": "batch_" + uuid.uuid4().hex[:16], "selection": selection,
        "from_date": from_date, "to_date": to_date, "interval": 1,
    })
    if result.get("status") != "complete":
        raise ValueError("Original Dhan index spot could not be downloaded: " +
                         str(result.get("error") or result.get("status"))[:160])
    if progress:
        progress(95, "Verifying saved Dhan IDX_I source receipt")
    # An original Dhan candle is not necessarily live; the cockpit checks age.
    response = {
        "identity": identity, "status": "complete", "rows": result["rows"],
        "source": "Dhan original IDX_I one-minute price index",
        "canonical_library_id": "dhan_shared",
        "new_research_dataset_created": False,
        "index_spot_available": bool(_selected_index(identity)),
    }
    if not response["index_spot_available"]:
        raise ValueError("Index download finished but the source receipt is unreadable")
    if progress:
        progress(100, "Original index source available in the shared market-data library")
    return response
