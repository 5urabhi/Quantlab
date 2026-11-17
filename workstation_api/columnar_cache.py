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


def _digest_part(path: Path) -> str:
    """Stream a generated Parquet partition without loading it into memory."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Analytical partition is not a regular, original-derived file")
    h = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _part_receipts(manifest: dict, files: list[Path]) -> bool:
    """Conservative cheap manifest validation; no costly hash on page loads."""
    receipts = manifest.get("partition_sha256")
    if not isinstance(receipts, dict) or len(receipts) != len(files):
        return False
    expected = {str(f.relative_to(_root() / "generations" / manifest["generation"]))
                for f in files}
    return set(receipts) == expected and all(
        isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
        for v in receipts.values())


def _verify_parts(manifest: dict, files: list[Path]) -> None:
    """Before numerical reads, check each cache partition's complete bytes."""
    if not files or not _part_receipts(manifest, files):
        raise ValueError("Analytical Parquet partition receipt missing or incomplete")
    root = _root() / "generations" / manifest["generation"]
    for file in files:
        name = str(file.relative_to(root))
        if _digest_part(file) != manifest["partition_sha256"][name]:
            raise ValueError("Analytical Parquet partition checksum changed: " + name +
                             "; rebuild the optional mirror. Original SQL is unchanged.")


def status() -> dict:
    original = _signature()
    exists = bool(original)
    manifest = _manifest()
    installed = importlib.util.find_spec("duckdb") is not None
    files = _parts(manifest) if manifest else []
    same = bool(manifest and manifest.get("source_signature") == original)
    ready = bool(exists and same and files and
                 len(files) == len(manifest.get("years", [])) and
                 _part_receipts(manifest, files))
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
            # Pin every generated partition's exact bytes before activation.
            # Subsequent numerical reads recheck these digests, preventing a
            # valid-looking but silently edited analytical mirror.
            partition_sha256 = {
                str(p.relative_to(staging)): _digest_part(p) for p in parts
            }
            staging.rename(dest)
            manifest = {
                "generation": generation, "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_signature": initial, "rows": total, "years": years,
                "partition_sha256": partition_sha256,
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
    _verify_parts(manifest, parts)
    duckdb = _engine()
    with duckdb.connect(database=":memory:") as conn:
        conn.execute("SET threads=2")
        conn.execute("SET memory_limit='512MB'")
        paths = [str(p) for p in parts]
        result = conn.execute(
            "SELECT session_date,close,source_sha256 FROM read_parquet(?) "
            "WHERE identity=? AND session_date>=? AND session_date<=? "
            "ORDER BY session_date DESC LIMIT ?",
            [paths, identity, first.isoformat(), last.isoformat(), limit + 1],
        ).fetchall()
    # A write concurrent with the query invalidates this result.
    if _signature() != manifest["source_signature"]:
        raise ValueError("Original market data changed during query; refresh the cache")
    # Fetch most recent requested observations, then display them oldest→newest.
    selected = list(reversed(result[:limit]))
    return {
        "identity": identity,
        "rows": [{"date": day.isoformat(), "close": close,
                  "source_sha256": checksum} for day, close, checksum in selected],
        "has_more": len(result) > limit, "limit": limit, "source": "canonical_unadjusted_original_closes",
        "basis": "unadjusted_close", "source_unchanged": True,
        "note": "Columnar results are original unadjusted closes, not dividend-inclusive TRI.",
    }


def model_matrix(view: str = "daily_prices.csv"):
    """Rebuild the exact canonical wide price panel from source-locked Parquet.

    Unlike a display-series endpoint, this includes every original security
    and trading date, with genuinely missing security-days still NaN. The
    monthly view takes the final *observed union session* of each calendar
    month; it never forward-fills a security missing on that session.
    """
    import pandas as pd
    import numpy as np
    if view not in ("daily_prices.csv", "prices.csv"):
        raise ValueError("Unsupported authoritative shared model-price view")
    state = status()
    if not state["ready"] or not state["engine_available"]:
        raise ValueError("Verified columnar cache is " + state["state"])
    manifest = _manifest()
    if manifest is None:
        raise ValueError("Canonical Parquet source receipt unavailable")
    parts = _parts(manifest)
    _verify_parts(manifest, parts)
    duckdb = _engine()
    with duckdb.connect(database=":memory:") as conn:
        conn.execute("SET threads=2")
        conn.execute("SET memory_limit='512MB'")
        rows = conn.execute(
            "SELECT session_date, identity, close FROM read_parquet(?) "
            "ORDER BY session_date, identity",
            [[str(p) for p in parts]]
        ).fetch_df()
    if _signature() != manifest["source_signature"]:
        raise ValueError("Original SQLite changed while reading the analytical cache")
    if rows.empty or len(rows) != manifest.get("rows",0):
        raise ValueError("Original and Parquet market row counts disagree")
    if rows[["session_date","identity"]].duplicated().any():
        raise ValueError("Duplicate canonical security session in analytical mirror")
    # DuckDB/Pandas may expose DATE as datetime64[us]. Original
    # index_research.read_matrix produces datetime64[ns]; preserve exact
    # model index dtype as well as values, timestamps and missing rows.
    rows["date"] = pd.to_datetime(
        rows["session_date"], errors="raise").astype("datetime64[ns]")
    if rows["date"].isna().any() or not rows["date"].is_monotonic_increasing:
        raise ValueError("Invalid date ordering in analytical mirror")
    rows["symbol"] = rows["identity"].str.replace(":", "_", regex=False)
    matrix = rows.pivot(index="date", columns="symbol", values="close")
    matrix = matrix.sort_index().sort_index(axis=1)
    if view == "prices.csv":
        matrix = matrix.groupby(matrix.index.to_period("M")).tail(1)
    if (len(matrix) < 2 or matrix.empty or
            (matrix.le(0) & matrix.notna()).any().any() or
            np.isinf(matrix.to_numpy(dtype=float)).any()):
        raise ValueError("Analytical model matrix violates original-price constraints")
    return matrix.astype(float)


def refresh_if_enabled(*, progress=None) -> dict:
    """Keep a previously enabled cache fresh after verified source ingestion.

    Never generate a cache for users who have not opted in. Avoid a surprise
    multi-gigabyte rebuild on a small Ubuntu machine; keep the explicit Build
    button available for large sources. Original ingest success is never
    invalidated if optional analytical caching fails.
    """
    state = status()
    if not state["built"]:
        return {"state": "not_enabled"}
    if state["ready"]:
        return {"state": "already_current"}
    if not state["engine_available"]:
        return {"state": "engine_missing"}
    if state["source_database_bytes"] > 750 * 1024 * 1024:
        return {"state": "manual_refresh_needed", "reason": "Source is larger than 750 MB"}
    try:
        return {"state": "refreshed", "cache": build(progress=progress)}
    except (ValueError, OSError, sqlite3.Error) as exc:
        return {"state": "manual_refresh_needed", "reason": str(exc)[:180]}
