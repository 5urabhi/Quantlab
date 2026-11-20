"""One-shot low-priority BANKNIFTY index backtest process entrypoint.

This process is spawned by the local research API. It does not import FastAPI,
start a live subscription, load Dhan credentials, or submit broker orders.
Input is a private, bounded local JSON request; results go to the separate
Research Lab archive, not the Dhan source database.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import sys

from . import strategy_lab


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    request = Path(sys.argv[1])
    response = Path(sys.argv[2])
    if not request.is_file() or request.is_symlink() or request.stat().st_size > 16384:
        return 2
    try:
        payload = json.loads(request.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"kind", "params"}:
            raise ValueError("Unrecognized bounded EMA research request")
        params = payload["params"]
        if not isinstance(params, dict):
            raise ValueError("Invalid EMA research arguments")
        if payload["kind"] == "ema_sweep":
            result = strategy_lab.run_sweep(**params)
        elif payload["kind"] == "ema_pair":
            result = strategy_lab.run_pair(**params)
        else:
            raise ValueError("Only built-in read-only EMA analysis is allowed")
        output = {"run_id": result["run_id"]}
    except (ValueError, TypeError, KeyError, OSError) as exc:
        output = {"error": type(exc).__name__, "detail": str(exc)[:180]}
    content = json.dumps(output, allow_nan=False).encode("utf-8")
    descriptor = os.open(response, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    return 0 if "run_id" in output else 1


if __name__ == "__main__":
    raise SystemExit(main())
