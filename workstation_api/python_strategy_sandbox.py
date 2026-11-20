"""Local-only untrusted Python strategy execution in a filesystem/network sandbox.

User-pasted Python is NEVER exec'ed inside FastAPI or the live Dhan recorder.
Ubuntu bubblewrap namespaces + prlimit are mandatory; execution fails closed
when isolation cannot be established. No root project/data directory or Dhan
tokens are mounted into the child, only a copied verified candle JSON input.

Only Python standard-library modules are available. The public callback is:
    def signal(history): return "UP" | "DOWN" | "HOLD"
It receives ONLY the current session's original candles up through the
completed bar, independently on each candle. No future bars are passed.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

MAX_SOURCE_CHARS = 20000
MAX_SANDBOX_BARS = 1500
MAX_OUTPUT_BYTES = 2_000_000
WALL_TIMEOUT = 25

RUNNER = r'''
import contextlib, io, json, os, sys
def output(value):
    with open("/work/result.json","w",encoding="utf-8") as file:
        json.dump(value,file,ensure_ascii=False,allow_nan=False)
try:
    with open("/work/candles.json",encoding="utf-8") as source:
        bars=json.load(source)
    with open("/work/strategy.py",encoding="utf-8") as source:
        code=source.read()
    env={"__name__":"__user_strategy__"}
    with open(os.devnull,"w") as discard, contextlib.redirect_stdout(discard):
        exec(compile(code,"strategy.py","exec"),env)
        fn=env.get("signal")
        if not callable(fn):
            raise ValueError("Define callable def signal(history): ...")
        result=[]
        session=None
        history=[]
        for bar in bars:
            if session != bar["session_ist"]:
                session=bar["session_ist"]
                history=[]
            history.append(dict(bar))
            # A copy prevents malicious/accidental in-place mutation of the
            # original source or later callback inputs.
            decision=fn([dict(value) for value in history])
            if isinstance(decision,bool):
                raise ValueError("Signal must be UP, DOWN or HOLD")
            if decision == 1: decision="UP"
            elif decision == -1: decision="DOWN"
            elif decision == 0: decision="HOLD"
            if decision not in ("UP","DOWN","HOLD"):
                raise ValueError("Signal must be UP, DOWN or HOLD")
            result.append(decision)
    output({"signals":result})
except BaseException as exc:
    output({"error":type(exc).__name__,"detail":str(exc)[:180]})
'''


def availability() -> dict:
    sandbox = shutil.which("bwrap")
    limiter = shutil.which("prlimit")
    runtime = Path("/usr/bin/python3")
    ok = bool(sandbox and limiter and runtime.is_file())
    return {
        "available": ok, "engine": "bubblewrap_user_namespace_network_isolated",
        "python_packages": "standard_library_only",
        "sandbox_network": False, "broker_token_in_sandbox": False,
        "requires": ([] if ok else
                     ["Ubuntu bubblewrap (bwrap), prlimit, /usr/bin/python3"]),
        "note": ("Python runs in a separate, time-bounded, network-isolated "
                 "process with only a copied candle file mounted. Kernel "
                 "user namespaces must permit bubblewrap execution.")
    }


def _command(directory: Path) -> list[str]:
    """Fail closed when Linux user-namespace sandbox or CPU cap unavailable."""
    env = availability()
    if not env["available"]:
        raise ValueError(
            "Isolated Python runner unavailable: install bubblewrap and "
            "util-linux prlimit on Ubuntu. No unsafe in-process fallback.")
    cmd = [
        shutil.which("prlimit"), "--as=536870912", "--cpu=12",
        "--fsize=8388608", "--nofile=64", "--",
        shutil.which("bwrap"), "--die-with-parent", "--new-session",
        "--unshare-all",
    ]
    for path in ("/usr", "/lib", "/lib64"):
        if Path(path).exists():
            cmd.extend(["--ro-bind", path, path])
    cmd.extend([
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--bind", str(directory), "/work", "--chdir", "/work",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/tmp", "--setenv", "PYTHONPATH", "",
        "--", "/usr/bin/python3", "-I", "-S", "/work/runner.py"
    ])
    return cmd


def run_python(code: str, rows: list[dict]) -> tuple[list[str], dict]:
    if not isinstance(code, str) or not 1 <= len(code) <= MAX_SOURCE_CHARS:
        raise ValueError("Paste 1-20,000 characters of Python strategy code")
    if not 1 <= len(rows) <= MAX_SANDBOX_BARS:
        raise ValueError("Custom Python supports 1,500 source bars per run")
    if "def signal(" not in code:
        raise ValueError("Define def signal(history): returning UP/DOWN/HOLD")
    with tempfile.TemporaryDirectory(prefix="quantlab_strategy_isolated_") as directory:
        work = Path(directory)
        work.chmod(0o700)
        (work / "runner.py").write_text(RUNNER, encoding="utf-8")
        (work / "strategy.py").write_text(code, encoding="utf-8")
        (work / "candles.json").write_text(
            json.dumps(rows, ensure_ascii=False, allow_nan=False),
            encoding="utf-8")
        for file in work.iterdir():
            file.chmod(0o600)
        command = _command(work)
        try:
            process = subprocess.run(
                command, cwd=work, env={"PATH": "/usr/bin:/bin",
                                        "HOME": "/tmp", "PYTHONPATH": ""},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=WALL_TIMEOUT, start_new_session=True, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "Python strategy exceeded the 25-second isolation limit. "
                "Reduce work per candle; live Dhan recording was not changed."
            ) from exc
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Cannot launch the isolated Python strategy runner; "
                "no unsafe fallback was attempted.") from exc
        result_file = work / "result.json"
        if process.returncode != 0 or not result_file.is_file():
            raise ValueError(
                "Ubuntu blocked the isolated Python process or the runner "
                "failed. Verify bubblewrap user-namespace permission. "
                "The main API and Dhan recorder are unchanged.")
        if result_file.is_symlink() or result_file.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("Sandbox result file exceeded safe limits")
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ValueError("Sandbox returned invalid JSON") from exc
    if isinstance(result, dict) and result.get("error"):
        error = str(result["error"])[:80]
        description = str(result.get("detail", ""))[:160]
        raise ValueError("Python strategy " + error + ": " + description)
    decisions = result.get("signals") if isinstance(result, dict) else None
    if not isinstance(decisions, list) or len(decisions) != len(rows):
        raise ValueError("Python code must return one signal per original candle")
    if any(value not in ("UP", "DOWN", "HOLD") for value in decisions):
        raise ValueError("Python signals must be UP, DOWN or HOLD")
    return decisions, {
        "engine": "isolated_python_stdlib",
        "source_sha256": sha256(code.encode("utf-8")).hexdigest(),
        "input_candles": len(rows),
        "network_allowed": False, "broker_access_allowed": False,
        "orders_placed": 0,
    }
