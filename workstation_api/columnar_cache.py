"""Optional, reproducible DuckDB/Parquet acceleration for original Dhan closes.

The SQLite daily_closes table remains the single source of truth. This
read-only columnar mirror uses only a local DuckDB Python package, never a
runtime extension download. Each cache generation is written off to the side
and atomically activated after consistency checks. Models and original CSV
views are unchanged; stale cache is NEVER read as current market history.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
import csv
import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3
import uuid

from . import service, shared_market_data

LOCK = RLock()
GENERATION = re.compile(r"^[0-9a-f]{24}$")
IDENTITY = shared_market_data.SAFE_IDENTITY
MAX_ROWS = 20_000_000
MAX_YEARS = 80
MAX_SERIES_ROWS = 5_000
CSV_TYPES = {
    "identity": "VARCHAR", "session_date": "DATE",
    "close": "DOUBLE", "source_sha256": "VARCHAR",
}


def _root() -> Path:
    root = service.DATA / "research_workspace" / "analytics_cache"
    # Avoid writing through any user-created symbolic link.
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Unsafe analytics cache directory")
    return root


def _db_file() -> Path:
    db = shared_market_data.database_path()
    if db.is_symlink() or db.parent.is_symlink():
        raise ValueError("Unsafe original market database")
    return db


def _engine():
    if importlib.util.find_spec("duckdb") is None:
        raise ValueError("DuckDB is unavailable. Install requirements.txt, then retry.")
    import duckdb
    return duckdb


def _signature() -> dict:
    """Cheap invalidation stamp, including an uncheckpointed SQLite WAL."""
    db = _db_file()
    if not db.is_file():
        return {}
    signature = {}
    for name, file in (("main", db), ("wal", Path(str(db) + "-wal"))):
        if file.is_symlink():
            raise ValueError("Unsafe SQLite database sidecar")
        if file.is_file():
            stamp = file.stat()
            signature[name] = {"bytes": stamp.st_size, "modified_ns": stamp.st_mtime_ns}
    return signature


def _manifest() -> dict | None:
    path = _root() / "active.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 40_000:
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict) or not GENERATION.fullmatch(str(body.get("generation", ""))):
            return None
        return body
    except (ValueError, OSError, UnicodeError):
        return None


def _parts(manifest: dict) -> list[Path]:
    root = _root() / "generations" / manifest["generation"]
    files = []
    for year in manifest.get("years", []):
        if not isinstance(year, int) or not 1900 <= year <= 2200:
            return []
        item = root / f"year={year}" / "closes.parquet"
        if not item.is_file() or item.is_symlink():
            return []
        files.append(item)
    return files


def status() -> dict:
    original = _signature()
    exists = bool(original)
    manifest = _manifest()
    installed = importlib.util.find_spec("duckdb") is not None
    files = _parts(manifest) if manifest else []
    same = bool(manifest and manifest.get("source_signature") == original)
    ready = exists and same and bool(files) and len(files) == len(manifest.get("years", []))
    return {
        "state": ("source_missing" if not exists else
                  "engine_missing" if not installed else
                  "ready" if ready else "stale" if manifest else "not_built"),
        "source_available": exists, "engine_available": installed,
        "ready": ready, "built": bool(manifest),
        "source_database_bytes": original.get("main", {}).get("bytes", 0),
        "observations": int(manifest.get("rows", 0)) if manifest else 0,
        "years": manifest.get("years", []) if manifest else [],
        "parquet_bytes": sum(p.stat().st_size for p in files),
        "generated_utc": manifest.get("created_utc") if manifest else None,
        "storage": "local analytical mirror (DuckDB/Parquet)",
        "note": ("Every query checks that the original SQLite source has not changed. "
                 "This cache never rewrites source candles, benchmarks or trading results."),
    }


def _read_only_sqlite():
    db = _db_file()
    if not db.is_file():
        raise ValueError("No original Dhan shared market SQLite data yet")
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    conn.execute("PRAGMA query_only=ON")
    return conn


def build(*, progress=None) -> dict:
    duckdb = _engine()
    with LOCK:
        initial = _signature()
        if not initial:
            raise ValueError("Download or import original Dhan observations first")
        root = _root()
        generations = root / "generations"
        if generations.is_symlink():
            raise ValueError("Unsafe analytics generations directory")
        generations.mkdir(parents=True, exist_ok=True)
        generation = uuid.uuid4().hex[:24]
        staging = generations / ("." + generation + ".tmp")
        dest = generations / generation
        staging.mkdir(exist_ok=False)
        conn = None
        try:
            conn = _read_only_sqlite()
            # The cache mirrors only canonical, validated observations.
            total = conn.execute("SELECT count(*) FROM daily_closes").fetchone()[0]
            if total > MAX_ROWS:
                raise ValueError(
                    "Shared market cache exceeds 20 million rows. Narrow the "
                    "materialization policy before using this machine's storage.")
            if total <= 0:
                raise ValueError("No original daily close observations to materialize")
            if progress:
                progress(3, f"Exporting {total:,} original daily closes by year")
            h = sha256()
            years: list[int] = []
            written = 0
            opened = None
            writer = None
            current_year = None
            csv_path = None
            reader = conn.execute(
                "SELECT identity,session_date,close,source_sha256 "
                "FROM daily_closes ORDER BY session_date,identity")
            duck = duckdb.connect(database=":memory:")
            try:
                duck.execute("SET threads=2")
                duck.execute("SET memory_limit='512MB'")
                def finalize_csv():
                    nonlocal opened
                    if opened is None or csv_path is None:
                        return
                    opened.close()
                    opened = None
                    parquet = staging / f"year={current_year}" / "closes.parquet"
                    parquet.parent.mkdir(parents=True, exist_ok=True)
                    # No plugins, network access or arbitrary user SQL.
                    relation = duck.read_csv(str(csv_path), header=True, columns=CSV_TYPES)
                    relation.write_parquet(str(parquet), compression="zstd")
                    csv_path.unlink(missing_ok=True)
                while True:
                    chunk = reader.fetchmany(8000)
                    if not chunk:
                        break
                    for identity, day, close, source_sha in chunk:
                        if (not IDENTITY.fullmatch(identity or "")
                                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or "")
                                or not isinstance(close, (int, float))
                                or not math.isfinite(float(close)) or close <= 0
                                or not re.fullmatch(r"[0-9a-f]{64}", source_sha or "")):
                            raise ValueError("Original SQLite source contains invalid market data")
                        y = date.fromisoformat(day).year
                        if y != current_year:
                            finalize_csv()
                            current_year = y
                            if y not in years:
                                years.append(y)
                            if len(years) > MAX_YEARS:
                                raise ValueError("Source spans too many year partitions")
                            csv_path = staging / (f"original_{y}.csv")
                            opened = csv_path.open("w", encoding="utf-8", newline="")
                            writer = csv.writer(opened)
                            writer.writerow(list(CSV_TYPES))
                        values = (identity, day, float(close), source_sha)
                        writer.writerow(values)
                        h.update(("\x1f".join(map(str, values)) + "\n").encode("utf-8"))
                        written += 1
                    if progress:
                        progress(min(80, 3 + 77 * written / total),
                                 f"Materialized {written:,} / {total:,} source rows")
                finalize_csv()
                # Assert a complete reconstruction, not a sampled or best-effort cache.
                if written != total:
                    raise ValueError("Market database changed during columnar conversion")
                parts = [staging / f"year={y}" / "closes.parquet" for y in years]
                aggregate = duck.read_parquet([str(p) for p in parts]).aggregate(
                    "count(*) AS row_count").fetchone()[0]
                if aggregate != total:
                    raise ValueError("Parquet rows differ from original SQLite observations")
            finally:
                duck.close()
            if _signature() != initial:
                raise ValueError("Original SQLite database changed; retry from a fresh snapshot")
            if progress:
                progress(93, "Atomically publishing validated Parquet generations")
            staging.rename(dest)
            manifest = {
                "generation": generation, "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_signature": initial, "rows": total, "years": years,
                "source_logical_sha256": h.hexdigest(), "schema": CSV_TYPES,
                "compression": "zstd", "source": "canonical_sqlite_daily_closes",
                "original_data_mutated": False, "version": 1,
            }
            root.mkdir(parents=True, exist_ok=True)
            temporary_manifest = root / ("." + generation + ".json.tmp")
            temporary_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            os.replace(temporary_manifest, root / "active.json")
            # Retain one prior generation to avoid invalidating active readers.
            try:
                versions = sorted((p for p in generations.iterdir()
                                   if p.is_dir() and GENERATION.fullmatch(p.name)),
                                  key=lambda p: p.stat().st_mtime_ns, reverse=True)
                for old in versions[2:]:
                    shutil.rmtree(old)
            except OSError:
                pass
            if progress:
                progress(100, "Verified DuckDB/Parquet cache is ready for analysis")
            return {"built": True, **status(), "source_logical_sha256": h.hexdigest()}
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            if conn is not None:
                conn.close()


def instruments(query: str = "", limit: int = 80) -> dict:
    if len(query) > 80 or not 1 <= limit <= 150:
        raise ValueError("Invalid instrument search")
    with _read_only_sqlite() as conn:
        needle = "%" + query.replace("%", "\\%").replace("_", "\\_") + "%"
        result = conn.execute(
            "SELECT identity,display_symbol FROM instruments "
            "WHERE identity LIKE ? ESCAPE '\\' OR display_symbol LIKE ? ESCAPE '\\' "
            "ORDER BY display_symbol,identity LIMIT ?",
            (needle, needle, limit),
        ).fetchall()
    return {"instruments": [{"identity": x, "label": y} for x, y in result]}


def series(identity: str, start: str = "", end: str = "",
           limit: int = 500) -> dict:
    if not IDENTITY.fullmatch(identity or ""):
        raise ValueError("Select an exact NSE/BSE Security ID from the instrument catalog")
    if not 1 <= limit <= MAX_SERIES_ROWS:
        raise ValueError("Invalid series page size")
    first = date.fromisoformat(start) if start else date(1900, 1, 1)
    last = date.fromisoformat(end) if end else date(2200, 1, 1)
    if first > last:
        raise ValueError("Start date must not be after end date")
    state = status()
    if not state["ready"]:
        raise ValueError("Columnar cache is " + state["state"] + "; refresh the analytical mirror")
    manifest = _manifest()
    parts = _parts(manifest)
    duckdb = _engine()
    with duckdb.connect(database=":memory:") as conn:
        conn.execute("SET threads=2")
        conn.execute("SET memory_limit='512MB'")
        paths = [str(p) for p in parts]
        result = conn.read_parquet(paths).filter(
            "identity = ? AND session_date >= ? AND session_date <= ?",
            params=[identity, first, last],
        ).order("session_date").limit(limit + 1).project(
            "session_date,close,source_sha256").fetchall()
    # A write concurrent with the query invalidates this result.
    if _signature() != manifest["source_signature"]:
        raise ValueError("Original market data changed during query; refresh the cache")
    return {
        "identity": identity,
        "rows": [{"date": day.isoformat(), "close": close,
                  "source_sha256": checksum} for day, close, checksum in result[:limit]],
        "has_more": len(result) > limit, "limit": limit, "source": "original_Dhan_closes",
        "basis": "unadjusted_close", "source_unchanged": True,
        "note": "Columnar results are original unadjusted closes, not dividend-inclusive TRI.",
    }
