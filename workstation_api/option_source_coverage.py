"""Source-labeled option coverage from independent authorized providers.

Never mix a bid from one provider with an ask from another. An overlapping
expiry/strike/side is one contract only when canonical identity matches, or
when both have no tradeable identity and use the exact NSE_FO index key.
Dhan is the default quote; Upstox can replace invalid Dhan quotes only when
the same fresh Dhan contract master proves the exchange identity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os

from . import option_chain_live, upstox_options, zerodha_fallback

UNDERLYINGS = ("BANKNIFTY", "NIFTY50")
PROVIDERS = ("all", "dhan", "upstox")


def _check(underlying: str, provider: str = "all") -> None:
    if underlying not in UNDERLYINGS or provider not in PROVIDERS:
        raise ValueError("Supported option views are BANKNIFTY/NIFTY50 and all/Dhan/Upstox")


def status() -> dict:
    """Configuration snapshots only: no market API requests on load."""
    dhan = bool(os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    try:
        kite = zerodha_fallback.configured()
    except (OSError, ValueError):
        kite = False
    return {
        "read_only": True, "underlyings": list(UNDERLYINGS),
        "providers": [
            {
                "id": "dhan", "label": "DhanHQ", "configured": dhan,
                "session_verified": False,
                "mode": "current_BANKNIFTY_chains_and_original_depth",
                "note": "Current BANKNIFTY option chain, all source-listed expiries/strikes; "
                        "read-only Dhan 20-level stream is a separate subscription.",
            },
            {
                "id": "zerodha", "label": "Zerodha Kite",
                "configured": kite, "session_verified": False,
                "mode": "authorized_daily_equity_history_fallback",
                "note": "Currently integrated for secondary daily equity candles, "
                        "not a replacement option-chain quote feed.",
            },
            upstox_options.status(),
        ],
        "warning": "Configured is not the same as authenticated, entitled, "
                   "fresh, or a guarantee of complete exchange history.",
    }


def _sources_for(underlying: str, provider: str) -> list[str]:
    sources = []
    if provider in ("all", "dhan") and underlying == "BANKNIFTY" and \
            os.getenv("DHAN_ACCESS_TOKEN", "").strip():
        sources.append("dhan")
    if provider in ("all", "upstox") and upstox_options.configured():
        sources.append("upstox")
    return sources


def expiries(underlying: str = "BANKNIFTY", provider: str = "all") -> dict:
    _check(underlying, provider)
    sources = _sources_for(underlying, provider)
    if not sources:
        raise ValueError("Connect Dhan (BANKNIFTY) or Upstox (BANKNIFTY/NIFTY50) "
                         "to retrieve current listed option expiries")
    by_expiry: dict[str, list[str]] = {}
    problems = {}
    for source in sources:
        try:
            dates = (option_chain_live.expiries()["expiries"] if source == "dhan"
                     else upstox_options.contracts(underlying)["expiries"])
            for day in dates:
                by_expiry.setdefault(day, []).append(source)
        except (ValueError, OSError) as exc:
            problems[source] = str(exc)[:220]
    observed = sorted(by_expiry)
    if not observed:
        raise ValueError("No connected provider returned original active expiries: "
                         + "; ".join(problems.values())[:300])
    return {
        "underlying": underlying, "expiries": observed,
        "nearest_expiry": observed[0],
        "received_utc": datetime.now(timezone.utc).isoformat(),
        "source": "original_provider_expiry_union",
        "expiry_sources": {day: names for day, names in sorted(by_expiry.items())},
        "provider_errors": problems, "providers_used": sorted(set(
            provider for names in by_expiry.values() for provider in names)),
        "read_only": True,
        "warning": "Only source-listed active expiries; not a historical expiry archive.",
    }


def _canonical_key(row: dict) -> tuple[float, str]:
    return round(float(row["strike"]), 4), str(row["option_type"])


def _combine(chains: dict[str, dict], underlying: str, expiry: str,
             errors: dict) -> dict:
    if not chains:
        raise ValueError("No market provider returned an acceptable original option chain")
    primary = chains.get("dhan") or chains.get("upstox")
    assert primary is not None
    merged: dict[tuple[float, str], dict] = {}
    counts: dict[str, int] = {}
    conflicts = 0
    selected = 0
    for provider in ("dhan", "upstox"):
        chain = chains.get(provider)
        if not chain:
            continue
        counts[provider] = len(chain["contracts"])
        for original in chain["contracts"]:
            key = _canonical_key(original)
            row = {**original,
                   "quote_provider": provider,
                   "source_received_utc": chain["received_utc"],
                   "available_sources": [provider]}
            current = merged.get(key)
            if not current:
                merged[key] = row
                continue
            # Never combine price fields from different source clocks.
            if (current.get("identity") and row.get("identity")
                    and current["identity"] != row["identity"]):
                conflicts += 1
                current["source_identity_conflict"] = True
                continue
            current["available_sources"] = sorted(set(
                current["available_sources"] + [provider]))
            if (not current.get("quote_valid") and row.get("quote_valid")
                    and current.get("identity") and row.get("identity")
                    and current["identity"] == row["identity"]
                    and row.get("contract_master_verified")):
                row["available_sources"] = current["available_sources"]
                merged[key] = row
                selected += 1
    values = sorted(merged.values(), key=lambda c: (
        abs(float(c["strike"]) - float(primary["underlying_spot"])),
        float(c["strike"]), str(c["option_type"])))
    return {
        "underlying": underlying, "underlying_spot": primary["underlying_spot"],
        "expiry": expiry, "received_utc": primary["received_utc"],
        "source": "Independent source-labeled Dhan/Upstox option-chain coverage",
        "source_clock": "per_provider_local_received_utc_not_exchange_time",
        "not_live_stream": True,
        "market_master_fresh": primary.get("market_master_fresh", False),
        "master_message": primary.get("master_message", ""),
        "master_age_hours": primary.get("master_age_hours"),
        "contracts": values, "quote_count": len(values),
        "read_only": True, "cache_hit": all(
            item.get("cache_hit", False) for item in chains.values()),
        "provider_contract_counts": counts,
        "providers_used": list(chains),
        "provider_errors": errors,
        "source_identity_conflicts": conflicts,
        "secondary_verified_quote_replacements": selected,
        "warning": "Provider quotes are separate received-time snapshots, "
                   "not synchronized NBBO or actual fills; original historical "
                   "order-book packets are not reconstructed. "
                   "Dhan master governs depth identity.",
    }


def chain(underlying: str, expiry: str, *, provider: str = "all",
          force_refresh: bool = False) -> dict:
    _check(underlying, provider)
    sources = _sources_for(underlying, provider)
    if not sources:
        raise ValueError("Connect a current-chain provider before requesting options")
    records = {}
    problems = {}
    for source in sources:
        try:
            if source == "dhan":
                records[source] = option_chain_live.chain(
                    expiry, force_refresh=force_refresh)
            else:
                records[source] = upstox_options.chain(
                    underlying, expiry, force_refresh=force_refresh)
        except (ValueError, OSError) as exc:
            problems[source] = str(exc)[:220]
    if not records:
        raise ValueError("No connected source returned valid current quotes. "
                         + "; ".join(problems.values())[:300])
    return _combine(records, underlying, expiry, problems)
