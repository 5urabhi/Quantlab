"""Opt-in, local-only renewal for unexpired Dhan-Web access tokens.

Dhan GET /v2/RenewToken replaces and invalidates the old token. Never call
without a specific saved local opt-in. Tokens generated through other login
flows may not be renewable via this endpoint. Do not collect PINs or TOTP.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import fcntl
import json
import os
import time

from dotenv import dotenv_values, set_key

from . import auto_option_depth, dhan_auth, dhan_option_chain, service

RENEW_URL = "https://api.dhan.co/v2/RenewToken"
RENEW_BEFORE_SECONDS = 4 * 60 * 60
BLOCKED_FINGERPRINT = ""
BLOCKED_UNTIL = 0.0


def _local_credentials_match(token: str) -> bool:
    target = service.ROOT / ".env"
    if target.is_symlink() or target.parent.is_symlink() or not target.is_file():
        return False
    if target.stat().st_mode & 0o077:
        # Existing local credentials must not be world/group readable.
        return False
    return dotenv_values(target).get("DHAN_ACCESS_TOKEN") == token


def _valid_token(value: object) -> bool:
    return (isinstance(value, str) and 16 <= len(value) <= 8192 and
            value == value.strip() and
            all(33 <= ord(char) <= 126 for char in value))


def maintain(opener=urlopen) -> dict:
    """Check expiry and optionally renew once; never return secrets or IDs."""
    global BLOCKED_FINGERPRINT, BLOCKED_UNTIL
    config = auto_option_depth._config()
    if not config.get("enabled") or not config.get("allow_token_renewal"):
        return {"state": "not_authorized", "message":
                "Automatic token renewal is disabled; market-data recording remains read-only."}
    token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    if not token:
        return {"state": "token_missing", "message":
                "Add a Dhan access token in local Connections."}
    current_hash = sha256(token.encode()).hexdigest()
    if current_hash == BLOCKED_FINGERPRINT and time.monotonic() < BLOCKED_UNTIL:
        return {"state": "provider_renewal_unavailable", "message":
                "Dhan renewal was declined for this token; reauthorize if it expires."}
    verified = dhan_auth.check_profile()
    if not verified.get("ok") or verified.get("token_valid") is not True:
        return {"state": "reauthorization_required", "message":
                "Dhan token is not currently valid; sign in again in the local Connections panel."}
    remaining = verified.get("seconds_remaining")
    if not isinstance(remaining, int):
        return {"state": "expiry_unknown", "message":
                "Dhan did not provide a usable expiry time; no renewal attempted."}
    if remaining > RENEW_BEFORE_SECONDS:
        return {"state": "valid", "message":
                "Dhan token valid; renewal not yet necessary.",
                "seconds_remaining": remaining}
    # No renewal unless the active token can be updated in a private,
    # explicitly saved .env. This avoids silently overwriting shell credentials.
    if not _local_credentials_match(token):
        return {"state": "private_storage_needed", "message":
                "Re-save your token through local Connections for automatic renewal."}
    # Prevent two QuantLab processes from invalidating each other's tokens.
    path = service.ROOT / ".dhan_renewal.lock"
    if path.is_symlink():
        return {"state": "unsafe_storage", "message":
                "Local renewal lock is unsafe; no token renewal attempted."}
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "maintenance_elsewhere", "message":
                    "Another local QuantLab process is checking Dhan renewal."}
        # Recheck after acquiring the lock to avoid invalidating a newer token.
        if not _local_credentials_match(token) or os.getenv("DHAN_ACCESS_TOKEN") != token:
            return {"state": "credentials_changed", "message":
                    "Token changed since verification; next check will use the newer token."}
        try:
            client_id = dhan_option_chain._client_id(token)
            request = Request(RENEW_URL, headers={
                "access-token": token, "dhanClientId": client_id,
                "Accept": "application/json"}, method="GET")
            with opener(request, timeout=15) as response:
                payload = json.loads(response.read(16384))
            if not isinstance(payload, dict):
                raise ValueError("Invalid Dhan renewal response")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            new_token = data.get("accessToken")
            if not _valid_token(new_token) or new_token == token:
                raise ValueError("Dhan did not provide a replacement access token")
        except HTTPError as exc:
            if exc.code in (400, 401, 403):
                BLOCKED_FINGERPRINT = current_hash
                BLOCKED_UNTIL = time.monotonic() + 3 * 3600
                return {"state": "provider_renewal_unavailable", "message":
                        "Dhan refused token renewal. This token may not be Dhan-Web generated."}
            return {"state": "provider_unavailable", "message":
                    "Dhan renewal endpoint temporarily failed; retrying later."}
        except (URLError, TimeoutError, OSError, ValueError, TypeError):
            return {"state": "provider_unavailable", "message":
                    "Dhan renewal response could not be verified. Try local Connections if expiry approaches."}
        # Dhan invalidates the old token on success. Preserve the new one
        # in memory immediately, even if a subsequent file write fails.
        os.environ["DHAN_ACCESS_TOKEN"] = new_token
        try:
            target = service.ROOT / ".env"
            if target.is_symlink() or target.parent.is_symlink():
                raise ValueError("Unsafe local credential path")
            set_key(str(target), "DHAN_ACCESS_TOKEN", new_token, quote_mode="always")
            os.chmod(target, 0o600)
            if dotenv_values(target).get("DHAN_ACCESS_TOKEN") != new_token:
                raise ValueError("Local verification of renewed token failed")
        except (OSError, ValueError):
            return {"state": "renewed_memory_only", "message":
                    "Dhan renewed the token in memory, but private storage failed. Reconnect before a restart."}
        BLOCKED_FINGERPRINT = ""
        BLOCKED_UNTIL = 0.0
        return {"state": "renewed", "message":
                "Dhan-Web token renewed and saved securely for future live data."}
    finally:
        os.close(fd)
