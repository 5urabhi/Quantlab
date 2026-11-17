"""Bounded, secret-free operational job messages and stage receipts.

Jobs are shown in the local UI and sometimes written to SQLite/terminal.
Provider exceptions must not expose authentication URLs, secrets, response
bodies or request-token query parameters. This module never records raw input.
"""
from __future__ import annotations

import os
import re
from typing import Any

MAX_STAGE = 140
MAX_ERROR = 350
_SECRET_KEY = re.compile(
    r"(?i)\b(access[_-]?token|api[_-]?key|api[_-]?secret|request[_-]?token|"
    r"client[_-]?secret|password|authorization|bearer|secret)\b"
    r"(\s*[:=]\s*|\s+)(?:\"|')?[^\s,;&\"']+")
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;&\"']+")
_QUERY = re.compile(
    r"(?i)([?&](?:token|access_token|request_token|api_key|api_secret|"
    r"client_secret|authorization|password)=)[^&#\s]+")
_URL = re.compile(r"(?i)https?://[^\s\"'<>]+")


def _known_secrets() -> list[str]:
    names = (
        "DHAN_ACCESS_TOKEN", "DHAN_CLIENT_ID", "KITE_ACCESS_TOKEN",
        "KITE_API_KEY", "KITE_API_SECRET", "ZERODHA_ACCESS_TOKEN",
        "ZERODHA_API_KEY", "ZERODHA_API_SECRET", "UPSTOX_ACCESS_TOKEN",
    )
    values = [os.getenv(name, "") for name in names]
    try:
        from . import zerodha_fallback
        saved = zerodha_fallback._read_session()
        values.extend((str(saved.get("access_token") or ""),))
        app = zerodha_fallback._app_credentials()
        values.extend((str(app.get("api_key") or ""),
                       str(app.get("api_secret") or "")))
    except (ValueError, OSError, TypeError):
        # Missing or unreadable broker config must not block job diagnostics.
        pass
    return sorted(set(x for x in values if len(x) >= 8), key=len, reverse=True)


def scrub(message: Any, *, limit: int = MAX_ERROR) -> str:
    if not 1 <= limit <= 500:
        raise ValueError("Invalid operational diagnostic bound")
    raw = str(message)
    # Removing absolute URLs also removes unknown vendor query parameter names
    # that might carry credentials, cookies or signed URLs.
    raw = _URL.sub("[URL REDACTED]", raw)
    raw = _BEARER.sub("Bearer [REDACTED]", raw)
    raw = _QUERY.sub(r"\1[REDACTED]", raw)
    raw = _SECRET_KEY.sub(lambda m: m.group(1) + "=[REDACTED]", raw)
    for token in _known_secrets():
        raw = raw.replace(token, "[REDACTED]")
    # Some third-party libraries stringify an embedded dict, newline or
    # control character. Keep all persisted user-facing stages single-line.
    raw = " ".join(raw.split())
    return raw[:limit]


def stage(message: Any) -> str:
    return scrub(message, limit=MAX_STAGE)
