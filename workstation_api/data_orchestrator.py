"""Local-first, source-safe QuantLab Data Orchestrator.

One read-only inventory/explorer for every research dataset. Only derived,
reconstructible views may be repaired automatically; original observations,
broker tokens, TRI evidence, and historical memberships are never invented or
overwritten. Jobs and automatic recovery attempts have durable receipts.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
import csv
import json
import re
import sqlite3

from . import dhan_workspace, materialized_view_recovery, model_data_manager, research_library, service, shared_market_data

LOCK = RLock()
MAX_TABLE_SCAN = 100_000
MAX_PROFILE_SCAN = 20_000
MAX_PAGE = 100
ALLOWED_TABLES = frozenset({
    "prices.csv", "daily_prices.csv", "membership.csv", "benchmark.csv",
    "fundamentals.csv", "sectors.csv", "corporate_actions.csv",
    "factor_returns.csv", "benchmark_weights.csv", "liquidity.csv",
})
SOURCE_MANIFESTS = frozenset({
    "BENCHMARK_PROVENANCE.json", "PIT_MEMBERSHIP_PROVENANCE.json",
    "DAILY_AGGREGATION_PROVENANCE.json", "RETURN_METHODOLOGY.json",
    "SHARED_MARKET_PROVENANCE.json", "workstation_source.json",
})
SAFE_EVENT = re.compile(r"^[a-z][a-z0-9_]{1,59}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _db():
    folder = service.DATA / "research_workspace"
    if folder.is_symlink():
        raise ValueError("Unsafe application data directory")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "data_orchestrator.sqlite3"
    if path.is_symlink():
        raise ValueError("Unsafe orchestration database")
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_utc TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auto_recovery(
                original_id TEXT PRIMARY KEY,
                attempted_utc TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS activity_time ON activity(occurred_utc DESC);
        """)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def event(category: str, status: str, summary: str) -> None:
    """Store bounded, server-authored operational messages; never provider bodies."""
    if not SAFE_EVENT.fullmatch(category) or status not in {"complete", "warning", "blocked"}:
        raise ValueError("Invalid activity category or status")
    with LOCK, _db() as conn:
        conn.execute(
            "INSERT INTO activity(occurred_utc,category,status,summary) VALUES(?,?,?,?)",
            (_now(), category, status, summary[:240]),
        )
        # Bound persistent activity even after years of local use.
        conn.execute("DELETE FROM activity WHERE id NOT IN "
                     "(SELECT id FROM activity ORDER BY id DESC LIMIT 500)")


def activity(limit: int = 40) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError("Invalid activity limit")
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT id,occurred_utc,category,status,summary "
            "FROM activity ORDER BY id DESC LIMIT ?", (limit,))]


def claim_automatic_retry(original_id: str) -> bool:
    """At most one replay of an interrupted source-locked job, across restarts."""
    if not re.fullmatch(r"[0-9a-f]{16}", original_id):
        raise ValueError("Invalid original job ID")
    with LOCK, _db() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO auto_recovery(original_id,attempted_utc,status) "
            "VALUES(?,?,?)", (original_id, _now(), "claimed"))
        return cursor.rowcount == 1


def record_automatic_retry(original_id: str, status: str) -> None:
    if status not in {"queued", "blocked", "failed"}:
        raise ValueError("Invalid recovery status")
    with LOCK, _db() as conn:
        conn.execute("UPDATE auto_recovery SET status=? WHERE original_id=?",
                     (status, original_id))


def _table_path(dataset_id: str, file_name: str) -> tuple[Path, dict]:
    folder, dataset = service.dataset_path(dataset_id)
    if file_name not in ALLOWED_TABLES:
        raise ValueError("Select an allowed dataset CSV table")
    if folder.is_symlink():
        raise ValueError("Unsafe dataset directory")
    path = folder / file_name
    if path.is_symlink() or not path.is_file():
        raise ValueError("This dataset does not contain " + file_name)
    return path, dataset


def _columns(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader, [])
    if not header or len(header) != len(set(header)) or len(header) > 10_000:
        raise ValueError("Invalid or duplicate dataset column names")
    return header


def table(dataset_id: str, file_name: str = "prices.csv", *, page: int = 1,
          per_page: int = 50, columns: str = "", query: str = "") -> dict:
    """Bounded streaming browser table; no SQL execution or unbounded JSON."""
    if not 1 <= page <= 1000 or not 1 <= per_page <= MAX_PAGE:
        raise ValueError("Invalid table pagination")
    if len(query) > 100 or len(columns) > 1500:
        raise ValueError("Table query exceeds the safe limit")
    path, dataset = _table_path(dataset_id, file_name)
    header = _columns(path)
    requested = [c.strip() for c in columns.split(",") if c.strip()]
    if len(requested) > 24 or len(set(requested)) != len(requested):
        raise ValueError("Select at most 24 unique columns")
    if requested and not set(requested).issubset(header):
        raise ValueError("Unknown dataset column")
    selected = requested or header[:min(12, len(header))]
    if header[0] not in selected:
        selected = [header[0], *selected[:23]]
    offset = (page - 1) * per_page
    found = 0
    scanned = 0
    output = []
    needle = query.casefold().strip()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            scanned += 1
            if scanned > MAX_TABLE_SCAN:
                break
            if needle and not any(needle in str(row.get(k) or "").casefold() for k in selected):
                continue
            if found >= offset and len(output) < per_page + 1:
                output.append({key: (row.get(key) or "")[:350] for key in selected})
            found += 1
            if len(output) > per_page:
                break
    has_more = len(output) > per_page
    return {
        "dataset_id": dataset["id"], "file": file_name,
        "page": page, "per_page": per_page, "columns": header[:1000],
        "total_columns": len(header), "selected_columns": selected,
        "rows": output[:per_page], "has_more": has_more,
        "scanned_rows": min(scanned, MAX_TABLE_SCAN),
        "scan_limit_reached": scanned > MAX_TABLE_SCAN,
        "warning": ("Showing a bounded source-file scan; refine columns or search. "
                    "Raw market evidence is never changed." if scanned > MAX_TABLE_SCAN else ""),
    }


def _manifest(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 512_000:
        return {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return {}
        # No arbitrary manifest fields in the browser: source metadata only.
        return {k: record.get(k) for k in (
            "dataset_id", "source_dataset_id", "source_batch", "source_commit",
            "generated_utc", "updated_utc", "index_name", "kind",
            "source_sha256", "is_total_return_index", "source_interval_minutes",
            "daily_sessions", "securities", "timezone", "warning",
        ) if k in record and k != "securities"}
    except (OSError, ValueError, UnicodeError):
        return {}


def detail(dataset_id: str) -> dict:
    folder, dataset = service.dataset_path(dataset_id)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Unsafe dataset folder")
    files = []
    for child in sorted(folder.iterdir()):
        if child.is_symlink():
            continue
        if child.is_file():
            stat = child.stat()
            files.append({
                "name": child.name, "bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc).isoformat(),
                "inspectable": child.name in ALLOWED_TABLES,
                "manifest": child.name in SOURCE_MANIFESTS,
            })
    manifests = {name: _manifest(folder / name) for name in SOURCE_MANIFESTS
                 if (folder / name).is_file() and not (folder / name).is_symlink()}
    return {
        "dataset": dataset, "files": files,
        "manifests": manifests,
        "dependencies": research_library.resource_dependencies("dataset", dataset_id),
        "raw_shared_cache_protected": True,
        "available_tables": [r["name"] for r in files if r["inspectable"]],
        "folder_category": dataset["kind"],
    }


def profile(dataset_id: str, file_name: str = "prices.csv") -> dict:
    """Sample-based quality checks, not an external certification."""
    path, _ = _table_path(dataset_id, file_name)
    header = _columns(path)
    selected = header[1:21]
    checks = Counter()
    observed = 0
    seen_dates: set[str] = set()
    first_date, last_date = None, None
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            observed += 1
            if observed > MAX_PROFILE_SCAN:
                break
            stamp = str(row.get("date") or row.get("datetime") or "")
            if stamp:
                first_date = min(stamp, first_date) if first_date else stamp
                last_date = max(stamp, last_date) if last_date else stamp
                if stamp in seen_dates:
                    checks["duplicate_dates"] += 1
                seen_dates.add(stamp)
            for field in selected:
                raw = str(row.get(field) or "").strip()
                if raw == "":
                    checks["empty_cells"] += 1
                elif field.lower() in {"open", "high", "low", "close", "price"}:
                    try:
                        if float(raw) <= 0:
                            checks["nonpositive_prices"] += 1
                    except ValueError:
                        checks["invalid_numeric_prices"] += 1
    return {
        "file": file_name, "sampled_rows": min(observed, MAX_PROFILE_SCAN),
        "sample_limit_reached": observed > MAX_PROFILE_SCAN,
        "sampled_columns": selected, "first_date_in_sample": first_date,
        "last_date_in_sample": last_date, "checks": dict(checks),
        "status": "review" if any(checks.values()) else "sample_pass",
        "caveat": "A bounded structural sample is not an audit of market completeness, "
                  "dividends, PIT memberships, or exchange provenance.",
    }


def sources() -> dict:
    master = service.DATA / "dhan" / "instrument_master.csv"
    result = {
        "dhan": {
            "token_configured": bool(__import__("os").getenv("DHAN_ACCESS_TOKEN")),
            "instrument_master": master.is_file() and not master.is_symlink(),
            "historical_data": "authenticated_read_only",
            "price_basis": "raw_ohlcv_not_total_return",
        },
        "nse_mcp": {
            "configured": True,
            "usage": "information_only",
            "research_data_import": False,
            "note": "MCP lookup is not a license to harvest or substitute TRI.",
        },
        "local_import": {"available": True, "source_verification": "required"},
    }
    return {"sources": result}


def overview() -> dict:
    datasets = service.datasets()
    batches = dhan_workspace.list_batches()
    jobs = research_library.list_job_history(40)
    root = service.DATA
    total_bytes = 0
    # Known local databases only; no recursive whole-drive scan during page load.
    for path in (shared_market_data.database_path(),
                 root / "research_workspace" / "library.sqlite3",
                 root / "research_workspace" / "data_orchestrator.sqlite3"):
        if path.is_file() and not path.is_symlink():
            total_bytes += path.stat().st_size
    return {
        "datasets": datasets,
        "statistics": {
            "datasets": len(datasets),
            "file_ready": sum(1 for row in datasets if row["ready"]),
            "needs_attention": sum(1 for row in datasets if not row["ready"]),
            "active_batches": sum(1 for row in batches if row["status"] in
                                  {"running", "queued", "interrupted"}),
            "recent_failed_jobs": sum(1 for row in jobs if row["status"] in
                                      {"error", "interrupted"}),
            "catalog_database_bytes": total_bytes,
        },
        "batches": batches[:20], "jobs": jobs[:20],
        "events": activity(25),
        "source_status": sources()["sources"],
    }


def requirements(model_id: str, dataset_id: str = "") -> dict:
    """Existing authoritative model-input checks exposed via one common API."""
    return model_data_manager.inspect(model_id, dataset_id or None)


def safe_maintenance() -> dict:
    """Verify and rebuild only bounded, provably derived views.

    Never rewrites original broker observations, historical memberships,
    benchmark TRI, or research reports. Corrupt authoritative SQLite fails
    closed with a visible, actionable blocked maintenance receipt.
    """
    repaired = []
    blocked = []
    result = materialized_view_recovery.repair()
    if result["state"] == "repaired":
        message = ("Rebuilt missing or inconsistent generated daily/monthly "
                   "shared price views from intact canonical SQLite.")
        repaired.append(message)
        event("materialized_views", "complete", message)
    elif result["state"] == "blocked" and result["health"]["state"] != "not_initialized":
        reason = result["health"]["reason"]
        blocked.append(reason)
        event("materialized_views", "blocked",
              "Derived shared price recovery blocked: " + reason[:160])
    else:
        event("maintenance", "complete",
              "Source-safe health check finished; no repairs needed.")
    return {"repaired": repaired, "blocked": blocked,
            "derived_views": result,
            "original_observations_changed": False,
            "note": "Maintenance never rewrites broker candles, original SQL rows, "
                    "TRI, PIT membership, or archived research evidence."}
