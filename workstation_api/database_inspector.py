"""Allowlisted, read-only SQLite table explorer for QuantLab.

The browser cannot supply SQL, paths, or arbitrary table names. Sensitive
payloads, local file paths, credentials and saved provider bodies are never
exposed. Large price tables are paginated; filters use bound parameters.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from . import service

# Expose only approved *columns* and only known, locally managed SQLite files.
# records.payload, job_history.error, resources.original_path and trash_path
# are deliberately excluded from every query and the schema response.
DATABASES = {
    "market_data": {
        "label": "Original shared Dhan market history",
        "relative_path": "dhan/shared_market.sqlite3",
        "tables": {
            "instruments": ("identity","exchange_segment","security_id","display_symbol"),
            "daily_closes": ("identity","session_date","close","source_sha256"),
            "ingestions": ("origin","identity","source_sha256","observed_rows","ingested_utc"),
        },
    },
    "research_library": {
        "label": "Saved research metadata",
        "relative_path": "research_workspace/library.sqlite3",
        "tables": {
            "records": ("id","kind","title","tags","favorite","archived","trashed",
                        "created_utc","updated_utc"),
            "resources": ("key","kind","item_id","archived","trashed","updated_utc"),
            "job_history": ("id","kind","status","created_utc","updated_utc"),
            "resource_labels": ("key","title","description","tags","favorite","updated_utc"),
        },
    },
    "operations": {
        "label": "Automatic recovery and activity history",
        "relative_path": "research_workspace/data_orchestrator.sqlite3",
        "tables": {
            "activity": ("id","occurred_utc","category","status","summary"),
            "auto_recovery": ("original_id","attempted_utc","status"),
        },
    },
}


def _path(database_id: str) -> Path:
    item = DATABASES.get(database_id)
    if item is None:
        raise ValueError("Unknown managed database")
    root = service.DATA.resolve()
    relative = Path(item["relative_path"])
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Managed database path escapes the data directory")
    # No symlink to a different file, even when it stays inside the root.
    raw = service.DATA / relative
    if raw.is_symlink() or raw.parent.is_symlink():
        raise ValueError("Unsafe managed database path")
    return raw


@contextmanager
def _read_only(database_id: str):
    path = _path(database_id)
    if not path.is_file():
        raise ValueError("Database has not been created on this machine")
    if path.is_symlink():
        raise ValueError("Unsafe managed database")
    # URI opens SQLite in read-only mode. A second layer forbids writes.
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def _schema(conn: sqlite3.Connection, table_name: str,
            approved: tuple[str, ...]) -> list[dict]:
    # This identifier comes only from the fixed backend allowlist.
    existing = conn.execute('PRAGMA table_info("' + table_name + '")').fetchall()
    mapping = {r["name"]: r for r in existing}
    return [{"name": key, "type": mapping[key]["type"] or "TEXT",
             "primary_key": bool(mapping[key]["pk"])}
            for key in approved if key in mapping]


def catalog() -> dict:
    databases = []
    for database_id, item in DATABASES.items():
        path = _path(database_id)
        info = {
            "id": database_id, "label": item["label"],
            "available": path.is_file() and not path.is_symlink(),
            "read_only": True, "tables": [],
        }
        if info["available"]:
            try:
                with _read_only(database_id) as conn:
                    for name, approved in item["tables"].items():
                        schema = _schema(conn, name, approved)
                        if schema:
                            info["tables"].append({
                                "name": name, "columns": schema,
                                "filterable": [v["name"] for v in schema],
                            })
            except (sqlite3.Error, ValueError):
                info["available"] = False
                info["warning"] = "Unable to safely inspect this managed database."
        databases.append(info)
    return {"databases": databases,
            "privacy": "Only allowlisted columns. No arbitrary SQL, original paths, "
                       "saved research payloads, broker credentials or destructive commands."}


def page(database_id: str, table_name: str, *, page: int = 1,
         per_page: int = 50, filter_column: str = "",
         filter_value: str = "") -> dict:
    tables = DATABASES.get(database_id, {}).get("tables", {})
    if table_name not in tables:
        raise ValueError("Unknown or restricted managed database table")
    if not isinstance(page, int) or not 1 <= page <= 1000 or not 1 <= per_page <= 100:
        raise ValueError("Invalid table pagination")
    if len(filter_column) > 80 or len(filter_value) > 160:
        raise ValueError("Invalid database filter")
    approved = tables[table_name]
    if filter_column and filter_column not in approved:
        raise ValueError("Filter column is not allowed")
    if filter_value and not filter_column:
        raise ValueError("Choose a specific column to filter")
    with _read_only(database_id) as conn:
        fields = _schema(conn, table_name, approved)
        columns = [f["name"] for f in fields]
        if not columns:
            raise ValueError("Managed database table not available")
        selected = ", ".join('"' + k + '"' for k in columns)
        statement = 'SELECT ' + selected + ' FROM "' + table_name + '"'
        values: list[object] = []
        if filter_column and filter_value:
            statement += ' WHERE "' + filter_column + '" = ?'
            values.append(filter_value)
        # First approved column is an indexed identity or stable ID in
        # the managed schema, not an arbitrary user-chosen expression.
        statement += ' ORDER BY "' + columns[0] + '" LIMIT ? OFFSET ?'
        values.extend([per_page + 1, (page-1)*per_page])
        conn.set_progress_handler(lambda: 1, 200_000)
        try:
            records = conn.execute(statement, values).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError("Query exceeded the bounded read-only explorer budget") from exc
    has_more = len(records) > per_page
    rows = []
    for record in records[:per_page]:
        rows.append({key: (record[key][:500] if isinstance(record[key], str)
                           else record[key]) for key in columns})
    return {
        "database_id": database_id, "table": table_name,
        "columns": fields, "rows": rows, "page": page, "per_page": per_page,
        "has_more": has_more, "filter_column": filter_column,
        "filter_value": filter_value, "read_only": True,
        "no_raw_sql": True,
        "note": "These are locally stored records, not a certification of source data.",
    }
