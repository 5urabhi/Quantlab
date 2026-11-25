"""Versioned local scripts and isolated, snapshot-bound custom chart research."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import math
import os
import re
import sqlite3
import stat
import signal
import subprocess
import time
import tempfile
import uuid

from . import python_strategy_sandbox, service

KINDS = {"strategy", "indicator", "chart", "research", "model", "scanner", "risk", "transform"}
MAX_SCRIPTS = 500
MAX_REVISIONS = 100
MAX_CHART_RUNS = 500
MAX_ROWS = 3000
MAX_COLUMNS = 40
MAX_INPUT_BYTES = 2_000_000
ID = re.compile(r"^[a-f0-9]{32}$")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _db_path():
    return service.DATA / "quantlab_scripts" / "library.sqlite3"


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe script library path")
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS scripts (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            revision INTEGER NOT NULL, updated_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS versions (
            script_id TEXT NOT NULL REFERENCES scripts(id),
            revision INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
            code TEXT NOT NULL, source_sha256 TEXT NOT NULL, created_utc TEXT NOT NULL,
            PRIMARY KEY(script_id, revision)
        );
        CREATE TABLE IF NOT EXISTS script_monitors (
            id TEXT PRIMARY KEY, script_id TEXT NOT NULL REFERENCES scripts(id),
            revision INTEGER NOT NULL, source TEXT NOT NULL, profile TEXT NOT NULL,
            enabled INTEGER NOT NULL, created_utc TEXT NOT NULL,
            state TEXT NOT NULL, last_key TEXT, last_utc TEXT, output TEXT,
            message TEXT, FOREIGN KEY(script_id, revision) REFERENCES versions(script_id, revision)
        );
        CREATE TABLE IF NOT EXISTS chart_runs (
            id TEXT PRIMARY KEY, created_utc TEXT NOT NULL,
            title TEXT NOT NULL, input_rows INTEGER NOT NULL, payload TEXT NOT NULL
        );
    """)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def list_scripts():
    from contextlib import closing
    with closing(_connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM scripts ORDER BY updated_utc DESC, id")]


def read_script(script_id, revision=None):
    from contextlib import closing
    if not isinstance(script_id, str) or not ID.fullmatch(script_id):
        raise ValueError("Invalid script ID")
    with closing(_connect()) as db:
        if revision is None:
            row = db.execute(
                "SELECT v.* FROM versions v JOIN scripts s ON v.script_id=s.id "
                "AND v.revision=s.revision WHERE s.id=?", (script_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM versions WHERE script_id=? AND revision=?",
                             (script_id, revision)).fetchone()
        if row is None:
            raise ValueError("Script or revision not found")
        result = dict(row)
        result["revisions"] = [dict(v) for v in db.execute(
            "SELECT revision,name,kind,created_utc,source_sha256 FROM versions "
            "WHERE script_id=? ORDER BY revision DESC", (script_id,))]
        return result


def save_script(*, name, kind, code, script_id=None, expected_revision=None):
    from contextlib import closing
    name = name.strip()
    if not 1 <= len(name) <= 100 or kind not in KINDS:
        raise ValueError("Choose a script name and a supported script category")
    if not isinstance(code, str) or not 1 <= len(code) <= python_strategy_sandbox.MAX_SOURCE_CHARS:
        raise ValueError("Save 1-20,000 characters of Python")
    # Syntax check does not execute or import user code.
    try:
        compile(code, "<saved script>", "exec")
    except SyntaxError as exc:
        raise ValueError(f"Python syntax error at line {exc.lineno}: {exc.msg}") from exc
    with closing(_connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if script_id is None:
            if expected_revision is not None:
                raise ValueError("A new script cannot have an expected revision")
            if db.execute("SELECT count(*) FROM scripts").fetchone()[0] >= MAX_SCRIPTS:
                raise ValueError("Script library is full; export scripts before adding more")
            script_id = uuid.uuid4().hex
            rev = 1
            db.execute("INSERT INTO scripts VALUES (?,?,?,?,?)",
                       (script_id, name, kind, rev, _now()))
        else:
            if not ID.fullmatch(script_id):
                raise ValueError("Invalid script ID")
            row = db.execute("SELECT revision FROM scripts WHERE id=?", (script_id,)).fetchone()
            if row is None:
                raise ValueError("Script not found")
            if expected_revision != row["revision"]:
                raise ValueError("Script was updated elsewhere; reload or Save as new")
            rev = row["revision"] + 1
            if rev > MAX_REVISIONS:
                raise ValueError("Revision limit reached; Save as new to preserve history")
            db.execute("UPDATE scripts SET name=?,kind=?,revision=?,updated_utc=? WHERE id=?",
                       (name, kind, rev, _now(), script_id))
        db.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?)",
                   (script_id, rev, name, kind, code, sha256(code.encode()).hexdigest(), _now()))
    return read_script(script_id)


def list_chart_runs():
    from contextlib import closing
    with closing(_connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT id,created_utc,title,input_rows FROM chart_runs ORDER BY created_utc DESC")]


def read_chart_run(run_id):
    from contextlib import closing
    if not isinstance(run_id, str) or not ID.fullmatch(run_id):
        raise ValueError("Invalid custom run ID")
    with closing(_connect()) as db:
        row = db.execute("SELECT payload FROM chart_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Custom chart result not found")
        return json.loads(row["payload"])


def _save_chart_run(result):
    from contextlib import closing
    run_id = uuid.uuid4().hex
    result = {**result, "run_id": run_id, "created_utc": _now()}
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 3_000_000:
        raise ValueError("Custom chart result exceeds local storage limit")
    with closing(_connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM chart_runs").fetchone()[0] >= MAX_CHART_RUNS:
            raise ValueError("Custom chart run library is full; export existing results")
        db.execute("INSERT INTO chart_runs VALUES (?,?,?,?,?)",
                   (run_id, result["created_utc"], result["plot"]["title"],
                    result["input_rows"], encoded))
    return result


def snapshot_json(snapshot):
    """Untrusted client snapshot, not independent market-source verification."""
    columns, rows = snapshot.get("columns"), snapshot.get("rows")
    if (not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLUMNS
            or any(not isinstance(c, str) or not 1 <= len(c) <= 160 for c in columns)
            or len(set(columns)) != len(columns)):
        raise ValueError("Snapshot requires unique, named columns")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("Snapshot requires 1-3,000 rows; select a smaller range")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("Snapshot rows must match the named columns")
        for value in row:
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, str) and len(value) <= 512:
                continue
            if isinstance(value, (int, float)):
                try:
                    if math.isfinite(value):
                        continue
                except OverflowError:
                    pass
            raise ValueError("Snapshot cells must be finite numbers, text, booleans or null")
    if any(type(row[0]) not in (str, int, float) for row in rows):
        raise ValueError("First snapshot column must contain numeric or text coordinates")
    safe = {"title": str(snapshot.get("title", ""))[:200],
            "provenance": str(snapshot.get("provenance", ""))[:300],
            "columns": columns, "rows": rows}
    encoded = json.dumps(safe, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_INPUT_BYTES:
        raise ValueError("Snapshot exceeds the 2 MB research limit")
    return encoded


def validate_output(result, count):
    if not isinstance(result, dict):
        raise ValueError("analyze(data) must return a dictionary")
    for key in ("title", "x_label", "y_label"):
        if not isinstance(result.get(key), str) or not 1 <= len(result[key].strip()) <= 150:
            raise ValueError("Provide a nonempty title, x_label and y_label including units")
    traces = result.get("traces")
    if not isinstance(traces, list) or not 1 <= len(traces) <= 8:
        raise ValueError("Return 1-8 traces with name and y values")
    clean = []
    names = set()
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError("Each trace must be a dictionary")
        name, values = trace.get("name"), trace.get("y")
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 100
                or name in names or not isinstance(values, list) or len(values) != count):
            raise ValueError("Unique trace names and one value per input row are required")
        names.add(name)
        for value in values:
            if value is not None:
                try:
                    valid = type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e100
                except OverflowError:
                    valid = False
                if not valid:
                    raise ValueError("Trace values must be finite numbers or null")
        clean.append({"name": name, "y": values})
    return {"title": result["title"], "x_label": result["x_label"],
            "y_label": result["y_label"], "traces": clean}


RUNNER = r'''
import contextlib, json, os
try:
    with open("/work/snapshot.json",encoding="utf-8") as f:
        data=json.load(f)
    with open("/work/strategy.py",encoding="utf-8") as f:
        code=f.read()
    env={"__name__":"__user_research__"}
    with open(os.devnull,"w") as discard,contextlib.redirect_stdout(discard):
        exec(compile(code,"research.py","exec"),env)
        fn=env.get("analyze")
        if not callable(fn):
            raise ValueError("Define def analyze(data):")
        result=fn(data)
    output={"result":result}
except BaseException as exc:
    output={"error":type(exc).__name__, "detail":str(exc)[:180]}
with open("/work/result.json","w",encoding="utf-8") as f:
    json.dump(output,f,ensure_ascii=False,allow_nan=False)
'''


def rank_snapshot(plot, snapshot):
    """Rank actual input rows by the first validated custom output trace."""
    scores = plot["traces"][0]["y"]
    ranked = sorted(((i, score) for i, score in enumerate(scores) if score is not None),
                    key=lambda pair: (-pair[1], pair[0]))[:50]
    return {"ranking": [{"rank": j+1, "key": str(snapshot["rows"][i][0]), "score": score,
                         "row": snapshot["rows"][i]} for j, (i, score) in enumerate(ranked)],
            "ranking_columns": snapshot["columns"],
            "ranking_note": "First output trace is the custom score; descending, not certified profit."}


def run_chart(*, code, snapshot, profile="stdlib", kind="chart", persist=True, progress=None):
    """Only copied snapshots enter the same fail-closed sandbox as strategies."""
    if not isinstance(code, str) or not 1 <= len(code) <= python_strategy_sandbox.MAX_SOURCE_CHARS:
        raise ValueError("Paste 1-20,000 characters of Python")
    payload = snapshot_json(snapshot)
    count = len(snapshot["rows"])
    with tempfile.TemporaryDirectory(prefix="quantlab_chart_isolated_") as directory:
        work = Path(directory)
        for name, value in (("runner.py", RUNNER.encode()), ("strategy.py", code.encode()),
                            ("snapshot.json", payload)):
            path = work / name
            path.write_bytes(value)
            path.chmod(0o600)
        command = (python_strategy_sandbox._command(work) if profile == 'stdlib'
                   else python_strategy_sandbox._command(work, profile))
        if progress:
            progress(10, "Starting isolated snapshot analysis")
        process = None
        try:
            process = subprocess.Popen(command, cwd=work,
                env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHONPATH": ""},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            started = time.monotonic()
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= python_strategy_sandbox.WALL_TIMEOUT:
                    raise ValueError("Isolated chart worker exceeded its time limit")
                if progress:
                    progress(min(85, 15 + 70 * elapsed / python_strategy_sandbox.WALL_TIMEOUT),
                             "Running isolated snapshot analysis")
                time.sleep(0.2)
        except OSError as exc:
            raise ValueError("Isolated chart worker could not start") from exc
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        if process.returncode != 0:
            raise ValueError("Ubuntu sandbox or chart worker failed; no unsafe fallback")
        try:
            fd = os.open(work / "result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > python_strategy_sandbox.MAX_OUTPUT_BYTES:
                    raise ValueError("Invalid sandbox output file")
                result = json.loads(f.read(python_strategy_sandbox.MAX_OUTPUT_BYTES + 1))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ValueError("Sandbox returned invalid or oversized JSON") from exc
    if not isinstance(result, dict) or "error" in result:
        raise ValueError("Custom analysis failed: " + str(result.get("error", "invalid output") if isinstance(result, dict) else "invalid output")[:80])
    if progress:
        progress(90, "Validating custom numeric output")
    plot = validate_output(result.get("result"), count)
    # The input's first column is the only supported x coordinate. Do not allow
    # user code to replace timestamps or silently interpolate missing points.
    plot.update(kind="line2d", x=[row[0] for row in snapshot["rows"]])
    if any(type(v) not in (str, int, float) for v in plot["x"]):
        raise ValueError("First snapshot column must contain numeric or text coordinates")
    output = {"plot": plot, "profile": profile, "source_sha256": sha256(code.encode()).hexdigest(),
            "snapshot_sha256": sha256(payload).hexdigest(),
            "input_rows": count, "provenance": "user_snapshot_custom_python",
            "warning": "Custom Python output from client-provided snapshot; not source-verified market history, not a causal trading signal."}
    if kind == "scanner":
        output.update(rank_snapshot(plot, snapshot))
    return _save_chart_run(output) if persist else output
