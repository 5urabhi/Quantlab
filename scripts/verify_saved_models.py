#!/usr/bin/env python3
"""Full, source-aware local verification of QuantLab's 35 registered models.

Reads saved original-source price panels and saved provider option-chain
observations. It can idempotently *link a copy* of an existing Dhan option
quote into the model catalog; never calls brokers, downloads prices,
changes source observations or places orders. Scenarios are labeled
mathematical; blocked original inputs are not counted as passing.

Invoke via: bash run.sh verify-saved [--dataset dhan_shared] [--strict]
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from workstation_api import (
    model_registry, option_quotes, recorded_chain_model_quotes, service,
)
from . import audit_all_models


def selected_dataset_ids(dataset_ids: list[str] | None) -> list[str]:
    found = service.datasets()
    ids = {row["id"] for row in found}
    if dataset_ids:
        missing = sorted(set(dataset_ids) - ids)
        if missing:
            raise ValueError("Unavailable original dataset(s): " + ", ".join(missing))
        return list(dict.fromkeys(dataset_ids))
    # Reuse the same non-synthetic active inventory as audit-models. Keep
    # genuinely prepared but incomplete datasets visible: a blocker matters.
    return [
        row["id"] for row in found
        if row.get("kind") != "synthetic"
        and not (row["id"] == "dhan_monthly"
                 and not (row.get("has_prices") or row.get("has_daily_prices")))
    ]


def link_existing_chain(selected: list[str], *, enabled: bool) -> dict:
    """Opt-in to a derived source-bound quote catalog entry, not a broker call."""
    result = {
        "attempted": False, "status": "disabled" if not enabled else "not_applicable",
        "source": "saved_local_normalized_dhan_option_chain",
        "provider_calls": 0, "orders": 0,
    }
    if not enabled or "dhan_shared" not in selected:
        return result
    try:
        original = option_quotes.list_for("dhan_shared")
        if any(snapshot.get("contracts") for snapshot in original):
            result["status"] = "already_saved_quotes_available"
            result["saved_quote_snapshots"] = len(original)
            return result
        stock = recorded_chain_model_quotes.available()
        digest = stock.get("recommended_snapshot_sha256")
        if not digest:
            result["status"] = "no_eligible_saved_chain"
            result["action"] = (
                "Capture an authorized read-only original Dhan chain when open; "
                "do not synthesize BANKNIFTY options from index prices."
            )
            return result
        result["attempted"] = True
        receipt = recorded_chain_model_quotes.use_saved(
            "dhan_shared", digest, confirm_reuse=True)
        result.update({
            "status": "source_bound_quote_reused",
            "saved_chain_sha256": digest,
            "model_quote_id": receipt["id"],
            "contract_count": receipt["contracts"],
            "idempotent_existing_entry": receipt["reused_existing"],
            "assumptions": (
                "Dhan normalized locally received bid/ask; original vendor JSON "
                "not retained; exact option expiry time assumed at 15:30 IST. "
                "A historical quote is not executable."
            ),
        })
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result["status"] = "link_unavailable"
        result["reason"] = audit_all_models.safe_message(exc)
    return result


def verification_summary(audit: dict, detail: list[dict],
                         linked: dict) -> dict:
    """Do not equate a fixture/model dispatch pass with market certification."""
    model_ids = [m["id"] for m in model_registry.MODELS]
    if len(model_ids) != len(set(model_ids)):
        raise ValueError("Duplicate registered model IDs")
    if audit["registered_models"] != len(model_ids):
        raise ValueError("Model audit did not cover the exact current registry")
    math_results = audit["mathematics"]
    math_ids = {m["id"] for m in model_registry.MODELS
                if m["mode"] in audit_all_models.MATH_MODES}
    if {r["model_id"] for r in math_results} != math_ids:
        raise ValueError("One or more mathematical model IDs were not audited")
    observed_ids = {m["id"] for m in model_registry.MODELS
                    if m["mode"] not in audit_all_models.MATH_MODES}
    by_dataset: list[dict] = []
    issues: list[dict] = []
    for ds in audit["datasets"]:
        rows = [r for r in detail if r["dataset_id"] == ds["dataset_id"]]
        if len(rows) != len(observed_ids) or {r["model_id"] for r in rows} != observed_ids:
            raise ValueError("Observed model matrix is missing registered models for "
                             + ds["dataset_id"])
        summary = {
            "dataset_id": ds["dataset_id"],
            "total_observed_models": len(observed_ids),
            "verified_calculations": sum(r["status"] == "observed_input_pass"
                                         for r in rows),
            "missing_original_inputs": sum(r["status"] == "blocked_input"
                                           for r in rows),
            "software_failures": sum(r["status"] == "software_fail"
                                     for r in rows),
            "source_changed": bool(ds.get("source_changed")),
            "historical_models_passed": sum(
                r["mode"] == "historical" and r["status"] == "observed_input_pass"
                for r in rows),
            "option_quote_models_passed": sum(
                r["mode"] == "market" and r["status"] == "observed_input_pass"
                for r in rows),
        }
        by_dataset.append(summary)
        for row in rows:
            if row["status"] != "observed_input_pass":
                issues.append({
                    "dataset_id": ds["dataset_id"],
                    "model": row["model_id"],
                    "mode": row["mode"],
                    "status": row["status"],
                    "reason": row["reason"],
                    "next_action": row["next_action"],
                    "selected_ticker": row.get("selected_ticker") or None,
                    "observed_returns": int(row["observed_returns"])
                        if row.get("observed_returns") else None,
                    "minimum_returns": int(row["minimum_returns"])
                        if row.get("minimum_returns") else None,
                    "preferred_returns": int(row["preferred_returns"])
                        if row.get("preferred_returns") else None,
                    "missing_minimum": int(row["missing_minimum"])
                        if row.get("missing_minimum") else None,
                    "missing_to_target": int(row["missing_to_target"])
                        if row.get("missing_to_target") else None,
                })
    failed = bool(audit["math_fail"] or audit["software_fail"] or
                  audit["source_changed"])
    blocked = bool(audit["blocked_input"])
    return {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "registered_models": len(model_ids),
        "mathematical_models": len(math_ids),
        "historical_models": sum(m["mode"] == "historical"
                                 for m in model_registry.MODELS),
        "observed_quote_models": sum(m["mode"] == "market"
                                     for m in model_registry.MODELS),
        "math_pass": audit["math_pass"],
        "math_fail": audit["math_fail"],
        "datasets": by_dataset,
        "total_saved_observed_model_runs": audit["observed_input_pass"],
        "total_blocked_source_inputs": audit["blocked_input"],
        "software_fail": audit["software_fail"],
        "source_changed_count": audit["source_changed"],
        "issues": issues,
        "saved_chain_reuse": linked,
        "verdict": ("SOFTWARE_OR_SOURCE_CHANGED" if failed else
                    "SOURCE_DATA_INCOMPLETE" if blocked else
                    "ALL_REGISTERED_MODELS_EXECUTED"),
        "real_market_source_certified": False,
        "backtesting_quality_certified": False,
        "broker_requests": 0,
        "broker_orders": 0,
        "market_source_file_edits": 0,
        "notice": audit_all_models.UNVERIFIED,
    }


def write_digest(output: Path, summary: dict) -> None:
    (output / "FULL_SAVED_VERIFICATION.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    lines = [
        "# QuantLab — full saved-data model verification",
        "",
        "**Outcome:** " + summary["verdict"],
        "**Checked (UTC):** " + summary["checked_utc"],
        "",
        "- Registered models: " + str(summary["registered_models"]),
        "- Mathematical models passed: " + str(summary["math_pass"]) +
        " / " + str(summary["mathematical_models"]),
        "- Historical model IDs: " + str(summary["historical_models"]),
        "- Source option-quote model IDs: " + str(summary["observed_quote_models"]),
        "- Observed-input calculations passed across datasets: " +
        str(summary["total_saved_observed_model_runs"]),
        "- Missing original-data inputs: " + str(summary["total_blocked_source_inputs"]),
        "- Model software failures: " + str(summary["software_fail"]),
        "- Original files changed during checks: " + str(summary["source_changed_count"]),
        "- Saved chain integration: " + str(summary["saved_chain_reuse"]["status"]),
        "",
        "| Local dataset | Historical models passed | Quoted models passed | All observed calculations | Blocked | Software errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["datasets"]:
        lines.append(
            f'| {row["dataset_id"]} | {row["historical_models_passed"]} | '
            f'{row["option_quote_models_passed"]} | {row["verified_calculations"]}'
            f' / {row["total_observed_models"]} | {row["missing_original_inputs"]}'
            f' | {row["software_failures"]} |'
        )
    if summary["issues"]:
        lines += ["", "## Exact remaining source or numerical blockers", ""]
        for issue in summary["issues"]:
            extra = ""
            if issue["model"] == "heston_proxy":
                extra = (f' — ticker: {issue["selected_ticker"]}; '
                         f'observed: {issue["observed_returns"]}; '
                         f'minimum: {issue["minimum_returns"]}; '
                         f'preferred: {issue["preferred_returns"]}; '
                         f'missing minimum: {issue["missing_minimum"]}; '
                         f'missing preferred: {issue["missing_to_target"]}')
            lines.append(
                "- **" + issue["dataset_id"] + " · " + issue["model"]
                + "** [" + issue["status"] + "] "
                + audit_all_models.safe_message(issue["reason"]) + extra +
                ". **Next:** " + audit_all_models.safe_message(issue["next_action"])
            )
    lines += [
        "",
        "## Evidence boundaries",
        "",
        "No network market requests, live brokerage orders or original market "
        "file edits were performed by this verification command.",
        "",
        "Mathematical scenarios are assumption-only. A passing numerical model "
        "does NOT establish vendor rights, original market accuracy, financial "
        "profitability, historical membership, corporate-action adjustments, "
        "or honest out-of-sample strategy returns.",
        "",
        "The full per-model matrix, source SHA-256 and index/PIT research "
        "blockers remain available in ALL_MODEL_RESULTS.csv and MODEL_AUDIT.md.",
    ]
    (output / "FULL_SAVED_VERIFICATION.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def verify(*, dataset_ids: list[str] | None, output: Path,
           link_quotes: bool = True) -> dict:
    selected = selected_dataset_ids(dataset_ids)
    if not selected:
        raise ValueError("No active original-source datasets are saved locally")
    if output.exists():
        raise ValueError("Output directory already exists")
    quote_link = link_existing_chain(selected, enabled=link_quotes)
    # Audit writes a COMPLETE 35-ID numerical matrix with original-source
    # checksums and before/after data file hash guards.
    report = audit_all_models.audit(
        datasets=selected, execute=True, output=output)
    with (output / "ALL_MODEL_RESULTS.csv").open(
            newline="", encoding="utf-8") as handle:
        detail = list(csv.DictReader(handle))
    summary = verification_summary(report, detail, quote_link)
    write_digest(output, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append",
                        help="Exact saved dataset ID (repeatable); default all non-synthetic")
    parser.add_argument("--no-link-recorded", action="store_true",
                        help="Do not create an idempotent derived quote catalog entry")
    parser.add_argument("--strict", action="store_true",
                        help="Return nonzero if any model requires unavailable original data")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output = args.output_dir or (service.ROOT / "results" /
                                 ("full_saved_verification_" + stamp))
    try:
        summary = verify(
            dataset_ids=args.dataset, output=output,
            link_quotes=not args.no_link_recorded)
    except Exception as exc:
        print("SAVED MODEL VERIFICATION ERROR: " +
              audit_all_models.safe_message(exc), file=sys.stderr)
        return 3
    print("")
    print("=== QUANTLAB SAVED-DATA MODEL VERIFICATION ===")
    print("Verdict:", summary["verdict"])
    print("Mathematical:", summary["math_pass"], "/",
          summary["mathematical_models"])
    for row in summary["datasets"]:
        print(row["dataset_id"] + ": " +
              str(row["verified_calculations"]) + "/" +
              str(row["total_observed_models"]) + " original-input models; " +
              str(row["missing_original_inputs"]) + " blocked; " +
              str(row["software_failures"]) + " errors")
    print("Stored option chains:", summary["saved_chain_reuse"]["status"])
    print("Report:", output / "FULL_SAVED_VERIFICATION.md")
    print("Model matrix:", output / "ALL_MODEL_RESULTS.csv")
    print("Source rights / market accuracy / actual P&L: NOT CERTIFIED")
    if summary["verdict"] == "SOFTWARE_OR_SOURCE_CHANGED":
        return 3
    return 2 if summary["verdict"] == "SOURCE_DATA_INCOMPLETE" and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
