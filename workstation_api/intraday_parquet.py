"""SHA-locked, partitioned one-minute Dhan OHLCV analytics mirror.

Original 1-minute CSV + sidecar remain immutable. The analytical parquet cache
can be deleted and regenerated; a changed source checksum invalidates every
query. Timezone-aware candle times are converted to UTC for partitioning and
to Asia/Kolkata dates for session reporting. Missing bars are never filled.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo
import csv
import importlib.util
import json
import math
import os
import re
import shutil
import uuid

from . import service, shared_market_data, dhan_workspace

LOCK = RLock()
MAX_INPUT_BYTES = 2_000_000_000
MAX_ROWS = 6_000_000
MAX_PER_QUERY = 5_000
GEN_ID = re.compile(r"^[a-f0-9]{20}$")
IST = ZoneInfo("Asia/Kolkata")
COLUMNS = {
    "timestamp_utc": "VARCHAR", "session_ist": "DATE",
    "open": "DOUBLE", "high": "DOUBLE", "low": "DOUBLE", "close": "DOUBLE",
    "volume": "BIGINT",
}


def _identity(key: str) -> tuple[str, str]:
    if not shared_market_data.SAFE_IDENTITY.fullmatch(key or ""):
        raise ValueError("Select an exact NSE/BSE original Security ID")
    return tuple(key.split(":"))


def _root(key: str) -> Path:
    segment, ident = _identity(key)
    root = service.DATA / "research_workspace" / "intraday_parquet" / segment / ident
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Unsafe intraday cache directory")
    return root


def _raw(key: str) -> tuple[Path, Path]:
    seg, sid = _identity(key)
    source = dhan_workspace._history_file(
        {"exchange_segment": seg, "security_id": sid}, 1)
    manifest = source.with_suffix(".json")
    if source.is_symlink() or manifest.is_symlink():
        raise ValueError("Unsafe original one-minute source")
    return source, manifest


def _source_signature(key: str, *, verify_sha: bool = False) -> dict:
    source, sidecar = _raw(key)
    if not source.is_file() or not sidecar.is_file():
        return {}
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("One-minute source exceeds bounded local cache")
    info = json.loads(sidecar.read_text(encoding="utf-8"))
    if info.get("instrument_id") != key or info.get("interval_minutes") != 1:
        raise ValueError("One-minute source identity/interval mismatch")
    digest = info.get("sha256")
    if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise ValueError("One-minute cache has no SHA-256 provenance")
    if verify_sha:
        h = sha256()
        with source.open("rb") as fd:
            for chunk in iter(lambda: fd.read(1024*1024), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise ValueError("Original one-minute CSV checksum mismatch")
    return {
        "identity": key, "source_sha256": digest,
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "manifest_size": sidecar.stat().st_size,
        "manifest_mtime_ns": sidecar.stat().st_mtime_ns,
    }


def _active(key: str) -> dict | None:
    path = _root(key) / "active.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 30_000:
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(info,dict) and GEN_ID.fullmatch(str(info.get("generation",""))):
            return info
    except (OSError, ValueError, UnicodeError):
        return None
    return None


def _files(key: str, record: dict) -> list[Path]:
    directory = _root(key) / "generations" / record["generation"]
    years = record.get("years", [])
    if not isinstance(years,list) or not 1 <= len(years) <= 80:
        return []
    paths = []
    for year in years:
        if not isinstance(year,int) or not 1990 <= year <= 2200:
            return []
        path = directory / f"year={year}" / "candles.parquet"
        if not path.is_file() or path.is_symlink():
            return []
        paths.append(path)
    return paths


def status(identity: str) -> dict:
    signature = _source_signature(identity)
    record = _active(identity)
    files = _files(identity,record) if record else []
    ready = bool(signature and record and files and
                 record.get("source_signature") == signature and
                 len(files) == len(record.get("years",[])))
    engine = importlib.util.find_spec("duckdb") is not None
    return {
        "identity": identity, "source_available": bool(signature),
        "engine_available": engine, "built": bool(record), "ready": ready,
        "state": ("original_missing" if not signature else "engine_missing"
                  if not engine else "ready" if ready else
                  "stale" if record else "not_built"),
        "interval_minutes": 1,
        "source_bytes": signature.get("source_size",0),
        "parquet_bytes": sum(p.stat().st_size for p in files),
        "observations": record.get("observations",0) if record else 0,
        "first_utc": record.get("first_utc") if record else None,
        "last_utc": record.get("last_utc") if record else None,
        "years": record.get("years",[]) if record else [],
        "note": "Original one-minute bars; no missing bar imputation, "
                "depth reconstruction, historical order book, or total return adjustment.",
    }


def catalog(limit: int = 100) -> dict:
    if not 1 <= limit <= 300:
        raise ValueError("Invalid one-minute catalog bound")
    root = service.DATA / "dhan" / "history"
    found = []
    if root.is_symlink() or not root.is_dir():
        return {"instruments": [], "interval_minutes": 1}
    for segment in ("NSE_EQ","BSE_EQ"):
        folder = root / segment
        if not folder.is_dir() or folder.is_symlink():
            continue
        for child in sorted(folder.iterdir()):
            if len(found) >= limit:
                break
            if child.is_symlink() or not child.is_dir() or not child.name.isdigit():
                continue
            key = segment + ":" + child.name
            try:
                info = status(key)
            except (OSError, ValueError):
                continue
            if info["source_available"]:
                found.append(info)
    return {"instruments": found, "interval_minutes": 1,
            "note": "Only instruments with an existing local 1-minute CSV+manifest are listed."}


def _engine():
    if importlib.util.find_spec("duckdb") is None:
        raise ValueError("Install local DuckDB from requirements.txt")
    import duckdb
    return duckdb


def _decode(row: dict) -> tuple[str,str,float,float,float,float,int]:
    from decimal import Decimal, InvalidOperation
    raw = str(row.get("datetime") or "")
    try:
        timestamp = datetime.fromisoformat(raw.replace("Z","+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Naive timestamps cannot be treated as NSE sessions")
        stamp = timestamp.astimezone(timezone.utc).replace(microsecond=0)
        values = [float(row[x]) for x in ("open","high","low","close")]
        vol = Decimal(str(row.get("volume") or ""))
        if not vol.is_finite() or vol < 0 or vol > 10**15 or vol != int(vol):
            raise ValueError("Invalid one-minute volume")
    except (ValueError,TypeError,InvalidOperation,OverflowError,KeyError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "Naive timestamps cannot be treated as NSE sessions":
            raise ValueError("Naive timestamps cannot be treated as NSE sessions") from exc
        raise ValueError("Original one-minute CSV has invalid OHLCV/timestamp") from exc
    if not all(math.isfinite(x) and x > 0 for x in values):
        raise ValueError("Original one-minute prices must be positive/finite")
    o,h,l,c = values
    if h < max(o,c,l) or l > min(o,c,h):
        raise ValueError("Original one-minute OHLC ordering violated")
    return (stamp.isoformat().replace("+00:00","Z"),
            stamp.astimezone(IST).date().isoformat(), o,h,l,c,int(vol))


def build(identity: str, *, progress=None) -> dict:
    _identity(identity)
    duckdb = _engine()
    with LOCK:
        initial = _source_signature(identity,verify_sha=True)
        if not initial:
            raise ValueError("Download one-minute original Dhan candles first")
        raw,_ = _raw(identity)
        base = _root(identity)
        gen = uuid.uuid4().hex[:20]
        staging = base / "generations" / ("."+gen+".tmp")
        if base.is_symlink():
            raise ValueError("Unsafe intraday cache path")
        staging.mkdir(parents=True,exist_ok=False)
        duck = duckdb.connect(database=":memory:")
        counts = 0
        years: list[int] = []
        active_file = None
        writer = None
        current_year = None
        temporary = None
        previous = ""
        first_timestamp = ""
        last_timestamp = ""
        def finalize():
            nonlocal active_file
            if active_file is None or temporary is None:
                return
            active_file.close()
            active_file = None
            part = staging / f"year={current_year}" / "candles.parquet"
            part.parent.mkdir(parents=True,exist_ok=True)
            duck.read_csv(str(temporary),header=True,columns=COLUMNS).write_parquet(
                str(part),compression="zstd")
            temporary.unlink(missing_ok=True)
        try:
            duck.execute("SET threads=2")
            duck.execute("SET memory_limit='512MB'")
            with raw.open("r",encoding="utf-8-sig",newline="") as fd:
                reader = csv.DictReader(fd)
                if not set(("datetime","open","high","low","close","volume")).issubset(
                        reader.fieldnames or []):
                    raise ValueError("One-minute original lacks required OHLCV columns")
                for row in reader:
                    normalized = _decode(row)
                    stamp,ist_date=normalized[:2]
                    if previous and stamp <= previous:
                        raise ValueError("Source timestamps are repeated or unsorted")
                    previous = stamp
                    if not first_timestamp:
                        first_timestamp = stamp
                    last_timestamp = stamp
                    year = int(ist_date[:4])
                    if year != current_year:
                        finalize()
                        if year in years:
                            raise ValueError("Intraday source returned to an earlier calendar year")
                        years.append(year)
                        if len(years) > 80:
                            raise ValueError("Too many intraday year partitions")
                        current_year=year
                        temporary=staging/(f"normalize_{year}.csv")
                        active_file=temporary.open("w",encoding="utf-8",newline="")
                        writer=csv.writer(active_file)
                        writer.writerow(COLUMNS.keys())
                    writer.writerow(normalized)
                    counts += 1
                    if counts > MAX_ROWS:
                        raise ValueError("Single-instrument intraday limit exceeded (6m bars)")
                    if progress and counts%25000==0:
                        progress(min(83,3+80*counts/max(1,MAX_ROWS)),
                                 f"Verified {counts:,} original minute candles")
                finalize()
            if not counts:
                raise ValueError("Source one-minute CSV has no valid market observations")
            parts=[staging/f"year={year}"/"candles.parquet" for year in years]
            total=duck.read_parquet([str(p) for p in parts]).aggregate(
                "count(*)").fetchone()[0]
            if total != counts:
                raise ValueError("Parquet row count differs from original minute candles")
            if _source_signature(identity,verify_sha=True) != initial:
                raise ValueError("Original minute candles changed during materialization")
            if progress:
                progress(95,"Publishing verified one-minute Parquet partitions")
            destination=base/"generations"/gen
            staging.rename(destination)
            record={
                "generation":gen,
                "source_signature":initial,
                "observations":counts,"years":years,
                "first_utc":first_timestamp,"last_utc":last_timestamp,
                "created_utc":datetime.now(timezone.utc).isoformat(),
                "price_basis":"original_ohlcv","interval_minutes":1,
                "no_interpolation":True,"version":1,
            }
            temp=base/("."+gen+".json")
            temp.write_text(json.dumps(record,indent=2),encoding="utf-8")
            os.replace(temp,base/"active.json")
            # Remove older generations after a successful atomic pointer flip.
            try:
                others=sorted([p for p in (base/"generations").iterdir()
                               if p.is_dir() and GEN_ID.fullmatch(p.name)],
                              key=lambda p:p.stat().st_mtime_ns,reverse=True)
                for old in others[2:]:
                    shutil.rmtree(old)
            except OSError:
                pass
            if progress:
                progress(100,"One-minute analytical cache verified")
            return {"build_complete":True,**status(identity)}
        except Exception:
            if active_file is not None:
                active_file.close()
            shutil.rmtree(staging,ignore_errors=True)
            raise
        finally:
            duck.close()


def series(identity: str, start: str = "", end: str = "", limit: int = 500) -> dict:
    if not 1 <= limit <= MAX_PER_QUERY:
        raise ValueError("Minute-candle query exceeds limit")
    state=status(identity)
    if not state["ready"]:
        raise ValueError("One-minute Parquet is "+state["state"]+
                         "; build or refresh after checking original source")
    record=_active(identity)
    files=_files(identity,record)
    first = datetime.fromisoformat(start.replace("Z","+00:00")) if start else None
    last = datetime.fromisoformat(end.replace("Z","+00:00")) if end else None
    if first is not None and first.tzinfo is None or last is not None and last.tzinfo is None:
        raise ValueError("Filter timestamps must include an explicit UTC offset")
    if first is not None and last is not None and first > last:
        raise ValueError("Invalid minute series timestamp range")
    lower=first.astimezone(timezone.utc).isoformat().replace("+00:00","Z") if first else "1990-01-01T00:00:00Z"
    upper=last.astimezone(timezone.utc).isoformat().replace("+00:00","Z") if last else "2200-01-01T00:00:00Z"
    duckdb=_engine()
    with duckdb.connect(database=":memory:") as conn:
        conn.execute("SET threads=2")
        conn.execute("SET memory_limit='512MB'")
        rows=conn.execute(
            "SELECT timestamp_utc,session_ist,open,high,low,close,volume "
            "FROM read_parquet(?) WHERE timestamp_utc>=? AND timestamp_utc<=? "
            "ORDER BY timestamp_utc DESC LIMIT ?",
            [[str(f) for f in files],lower,upper,limit+1]).fetchall()
    if _source_signature(identity) != record["source_signature"]:
        raise ValueError("Original one-minute source changed during query")
    selected=list(reversed(rows[:limit]))
    return {
        "identity":identity,"rows":[{
            "timestamp_utc":ts,"session_ist":day.isoformat() if isinstance(day,date) else str(day),
            "open":o,"high":h,"low":l,"close":c,"volume":vol,
        } for ts,day,o,h,l,c,vol in selected],
        "has_more":len(rows)>limit,"interval_minutes":1,
        "basis":"original_unadjusted_ohlcv",
        "warning":"Bars are observed original Dhan candles; no fabricated missing minutes "
                  "or historical depth-of-book is inferred.",
    }


def refresh_enabled(identity: str, *, max_raw_bytes: int = 250*1024*1024) -> dict:
    state=status(identity)
    if not state["built"]:
        return {"status":"not_enabled"}
    if state["ready"]:
        return {"status":"current"}
    if state["source_bytes"] > max_raw_bytes:
        return {"status":"manual_refresh_needed","reason":"Source is large"}
    try:
        return {"status":"refreshed","result":build(identity)}
    except (ValueError,OSError):
        return {"status":"manual_refresh_needed"}
