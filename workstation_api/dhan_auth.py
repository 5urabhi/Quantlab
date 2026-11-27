"""Read-only Dhan credential and market-data entitlement diagnostics.

Uses Dhan's published GET /v2/profile. Never sends account identifiers,
tokens, names, or raw vendor response bodies to the React interface.
"""
from __future__ import annotations
import json
import logging
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOG = logging.getLogger("quantlab.dhan.auth")


# Documented Dhan error codes only. Never expose arbitrary provider messages,
# unknown code values, account IDs or response bodies.
_PROFILE_ERRORS = {
    "DH-901": ("auth_rejected", False, None, "Dhan rejected the credentials (invalid or expired). Generate a fresh token."),
    "DH-902": ("data_plan_inactive", None, None, "Dhan denied API access. Check the Data API subscription and account permissions."),
    "DH-903": ("profile_account_error", None, None, "Dhan reports an account or segment permission issue."),
    "DH-904": ("profile_rate_limited", None, None, "Dhan rate limit reached. Respect the provider cooldown."),
    "DH-905": ("profile_input_error", None, None, "Dhan rejected a request parameter. Check the documented profile request format."),
    "DH-906": ("profile_http_error", None, None, "Dhan returned an unexpected order-error code on the read-only profile endpoint. Token status is unverified; check the session or contact Dhan."),
    "DH-907": ("profile_http_error", None, None, "Dhan could not retrieve the requested data."),
    "DH-908": ("profile_unreachable", None, None, "Dhan reports a temporary internal server error."),
    "DH-909": ("profile_unreachable", None, None, "Dhan reports a temporary upstream network error."),
    "DH-910": ("profile_http_error", None, None, "Dhan returned an unspecified provider error."),
    "800": ("profile_unreachable", None, None, "Dhan reports an internal server error."),
    "805": ("profile_rate_limited", None, None, "Dhan rate limit reached. Respect the provider cooldown."),
    "806": ("data_plan_inactive", None, False, "Dhan reports that Data APIs are not subscribed."),
    "807": ("token_expired", False, None, "Dhan reports an expired access token. Generate a fresh token."),
    "808": ("auth_rejected", False, None, "Dhan reports invalid credentials. Verify the token and client ID."),
    "809": ("auth_rejected", False, None, "Dhan reports an invalid access token. Generate a fresh token."),
    "810": ("client_id_mismatch", None, None, "Dhan reports an invalid client ID."),
    "814": ("profile_input_error", None, None, "Dhan reports an invalid request."),
}


def _provider_error_code(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("errorCode", "error_code", "code"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            candidate = str(value).strip().upper()
            if candidate in _PROFILE_ERRORS:
                return candidate
    return None


def _profile_error(status, payload=None, headers=None):
    vendor_code = _provider_error_code(payload)
    # A 429 takes precedence even when an inconsistent vendor code is sent.
    if status == 429:
        code, valid, plan, message = _PROFILE_ERRORS["DH-904"]
    elif vendor_code:
        code, valid, plan, message = _PROFILE_ERRORS[vendor_code]
        # DH-906 is documented as an order error, but read-only endpoints
        # also return it with an explicit Invalid Token message. Only use
        # exact known messages for classification; never echo vendor text.
        if vendor_code == "DH-906":
            detail = payload.get("errorMessage", payload.get("error_message", ""))
            if isinstance(detail, str) and detail.strip().casefold().rstrip(".") in {"invalid token", "invalid access token", "access token is invalid"}:
                code, valid, plan, message = "auth_rejected", False, None, "Dhan reports an invalid token on the read-only profile endpoint. Generate a fresh access token."
    elif status in (401, 403):
        code, valid, plan, message = "auth_rejected", False, None, "Dhan rejected this access token. Enter a fresh token in QuantLab's Dhan connection panel."
    elif status >= 500:
        code, valid, plan, message = "profile_unreachable", None, None, "Dhan profile service is temporarily unavailable."
    else:
        code, valid, plan, message = "profile_http_error", None, None, "Token status not verified; Dhan did not return a recognized error code."
    result = {"ok": False, "token_present": True, "token_valid": valid,
              "data_plan_active": plan, "code": code, "http_status": status,
              "provider_error_code": vendor_code,
              "message": f"Dhan profile HTTP {status}" + (f" ({vendor_code})" if vendor_code else "") + ": " + message}
    if code == "profile_rate_limited":
        retry = str(headers.get("Retry-After", "")).strip() if headers else ""
        seconds = 0
        if retry.isdigit() and len(retry) <= 9:
            seconds = int(retry)
        elif retry:
            try:
                from email.utils import parsedate_to_datetime
                when = parsedate_to_datetime(retry)
                if when.tzinfo is not None:
                    seconds = max(0, math.ceil((when - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                pass
        result["provider_retry_after_seconds"] = seconds
    return result


def check_profile(opener=urlopen, *, token_override: str | None = None,
                  client_id_override: str | None = None) -> dict:
    """Verify existing or explicitly supplied one-time token; never return it."""
    token = (token_override if token_override is not None else os.getenv("DHAN_ACCESS_TOKEN", "")).strip()
    if not token:
        LOG.warning("Dhan profile preflight: token is missing from environment")
        return {"ok": False, "token_present": False, "token_valid": False,
                "data_plan_active": False, "code": "token_missing",
                "message": "Connect a Dhan access token in the QuantLab cockpit."}
    req = Request("https://api.dhan.co/v2/profile", headers={
        "access-token": token, "Accept": "application/json",
    }, method="GET")
    LOG.info("Dhan profile preflight started: endpoint=GET /v2/profile token_present=yes")
    try:
        with opener(req, timeout=12) as response:
            payload = json.loads(response.read(65536))
    except HTTPError as exc:
        LOG.warning("Dhan profile preflight HTTP failure: endpoint=GET /v2/profile status=%s", exc.code)
        try:
            payload = json.loads(exc.read(4096))
        except (OSError, ValueError, TypeError, AttributeError):
            payload = None
        return _profile_error(exc.code, payload, exc.headers)
    except (URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
        LOG.warning("Dhan profile preflight failed: endpoint=GET /v2/profile category=%s", type(exc).__name__)
        return {"ok": False, "token_present": True, "token_valid": None,
                "data_plan_active": None, "code": "profile_unreachable",
                "message": "Could not verify Dhan API credentials; check connectivity and retry."}
    if not isinstance(payload, dict):
        LOG.warning("Dhan profile preflight unexpected response type")
        return {"ok": False, "token_present": True, "token_valid": None,
                "data_plan_active": None, "code": "invalid_profile",
                "message": "Dhan returned an unrecognized profile response."}
    if _provider_error_code(payload):
        return _profile_error(200, payload)
    # Dhan V2 documents tokenValidity, dataPlan and dataValidity.
    # Never emit dhanClientId, UCC, account details or token content.
    state = str(payload.get("dataPlan", "")).strip().lower()
    # Dhan documents tokenValidity as DD/MM/YYYY HH:MM (an expiry timestamp),
    # NOT a boolean. Nonempty strings are not evidence of an active token.
    expiry = str(payload.get("tokenValidity", "")).strip()
    try:
        valid_until = datetime.strptime(expiry, "%d/%m/%Y %H:%M").replace(
            tzinfo=ZoneInfo("Asia/Kolkata"))
        remaining_seconds = max(0, int((valid_until - datetime.now(ZoneInfo("Asia/Kolkata"))).total_seconds()))
        token_valid = remaining_seconds > 0
        expires_at_utc = valid_until.astimezone(timezone.utc).isoformat()
    except ValueError:
        token_valid = None
        remaining_seconds = None
        expires_at_utc = None
    plan_active = state == "active"
    broker_client_id = str(payload.get("dhanClientId", "")).strip()
    client_id_auto_available = broker_client_id.isdigit() and 4 <= len(broker_client_id) <= 20
    configured_client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
    client_matches = (client_id_override is None or broker_client_id == client_id_override)
    if not client_matches:
        code, message = "client_id_mismatch", "Dhan profile does not match the provided client ID. Check your account credentials."
    elif token_valid is False:
        code, message = "token_expired", "Dhan access token expired. Enter a fresh token in QuantLab's Dhan connection panel."
    elif token_valid is None:
        code, message = "token_expiry_unknown", "Dhan authenticated, but the token expiry field could not be interpreted."
    elif not plan_active:
        code, message = "data_plan_inactive", "Dhan Data API subscription is not active. Trading API access alone does not enable historical market-data requests."
    else:
        code, message = "ready", "Dhan authenticated and reports an active Data API subscription."
    LOG.log(logging.INFO if code == "ready" else logging.WARNING,
            "Dhan profile preflight result: code=%s token_valid=%s data_plan_active=%s",
            code, token_valid, plan_active)
    return {"ok": bool(token_valid and plan_active and client_matches), "token_present": True,
            "client_id_matches":client_matches if client_id_override is not None else None,
            "client_id_configured":bool(configured_client_id),
            "client_id_auto_available":client_id_auto_available,
            "client_id_ready":bool(configured_client_id or client_id_auto_available),
            "client_id_source":("local_setting" if configured_client_id else
                                "authenticated_profile" if client_id_auto_available else "missing"),
            "token_valid": token_valid, "data_plan_active": plan_active,
            "code": code, "message": message,
            "token_validity": expiry[:40],
            "expires_at_utc": expires_at_utc,
            "seconds_remaining": remaining_seconds,
            "data_validity": str(payload.get("dataValidity", ""))[:40]}
