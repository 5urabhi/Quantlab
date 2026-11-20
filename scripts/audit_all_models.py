#!/usr/bin/env python3
"""Read-only, source-aware acceptance of ALL registered QuantLab models.

No broker requests, market-data edits, order submission, source invention or
model-result archival. This deliberately separates software passes from input
availability and from independently audited financial-market evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from workstation_api import (
    historical_readiness, model_input_selector, model_lab, model_registry,
    option_market, option_quotes, service,
)

MATH_MODES = {"synthetic", "theoretical"}
SOURCE_NAMES = (
    "daily_prices.csv", "prices.csv", "benchmark.csv",
    "BENCHMARK_SOURCE.json", "SHARED_MARKET_PROVENANCE.json",
    "DHAN_BATCH_PROVENANCE.json", "PIT_MEMBERSHIP_PROVENANCE.json",
    "RETURN_METHODOLOGY.json",
)
COLUMNS = (
    "dataset_id", "dataset_kind", "model_id", "model_name", "mode",
    "status", "minimum_returns", "preferred_returns", "observed_returns",
    "missing_minimum", "missing_to_target", "assets", "selected_ticker",
    "quote_reference", "source_file",
    "source_sha256", "reason", "next_action", "duration_seconds",
)
UNVERIFIED = (
    "Numerical output is NOT independent verification of source rights, "
    "corporate actions, point-in-time membership, financial profitability, "
    "model adequacy or a trading signal. Mathematical scenario models remain "
    "assumption-based even when observed market data exists elsewhere."
)
REDACT = re.compile(
    r"(?i)(access[_ -]?token|authorization|password|api[_ -]?key|secret)\s*[:=]\s*\S+"
)


def safe_message(value: object) -> str:
    message = REDACT.sub(r"\1=[REDACTED]", str(value))
    return " ".join(message.split())[:240]


def file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Original source file is unavailable or unsafe: " + path.name)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dataset_digests(folder: Path) -> dict[str, str]:
    return {name: file_digest(folder / name) for name in SOURCE_NAMES
            if (folder / name).exists() or (folder / name).is_symlink()}


def required_count(spec: dict) -> int:
    minimum = int(spec["min_observations"])
    if spec["id"] == "rolling_vol":
        minimum = max(minimum, 90)
    return minimum


def make_row(spec: dict, dataset_id: str, kind: str) -> dict:
    minimum = required_count(spec) if spec["mode"] == "historical" else 0
    return {
        "dataset_id": dataset_id, "dataset_kind": kind,
        "model_id": spec["id"], "model_name": spec["title"],
        "mode": spec["mode"], "status": "blocked_input",
        "minimum_returns": minimum,
        "preferred_returns": math.ceil(minimum * 1.2) if minimum else 0,
        "observed_returns": "", "missing_minimum": "", "missing_to_target": "",
        "assets": "", "selected_ticker": "",
        "quote_reference": "", "source_file": "", "source_sha256": "",
        "reason": "", "next_action": "", "duration_seconds": "",
    }


def verify_output(result: object, spec: dict, dataset_id: str | None) -> None:
    if not isinstance(result, dict):
        raise ValueError("Model did not return a structured result")
    if result.get("model_id") != spec["id"] or result.get("mode") != spec["mode"]:
        raise ValueError("Model dispatch returned an inconsistent identity or mode")
    if not any(result.get(key) for key in ("metrics", "plots", "table")):
        raise ValueError("Model returned no numerical results or figures")
    # Some stochastic and quote-anchored branches return early from the
    # shared dispatch. Verify their entire output is finite as well.
    def finite(value: object) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                finite(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                finite(nested)
        elif isinstance(value, (float, int)) and not isinstance(value, bool):
            if not math.isfinite(float(value)):
                raise ValueError("Nonfinite numerical output, including model plots")
    finite(result)
    source = result.get("source")
    if spec["mode"] in MATH_MODES:
        if source is not None:
            raise ValueError("Assumption-only calculation unexpectedly claims a dataset")
    elif not isinstance(source, dict) or source.get("dataset_id") != dataset_id:
        raise ValueError("Market model did not retain the exact selected source ID")


def light_math_parameters(spec: dict) -> dict:
    keys = {p["key"] for p in spec["parameters"]}
    return {key: value for key, value in (("paths", 40), ("steps", 40))
            if key in keys}


def run_math(spec: dict, *, execute: bool) -> dict:
    row = make_row(spec, "(no dataset)", "assumptions")
    row["reason"] = "Mathematical inputs are assumed; not real observed history"
    row["next_action"] = "Supply assumptions and inspect limitations; no market history required"
    if not execute:
        row["status"] = "ready_not_executed"
        return row
    start = time.monotonic()
    try:
        result = model_lab.run_model(spec["id"], None, light_math_parameters(spec))
        verify_output(result, spec, None)
        row["status"] = "math_pass"
    except Exception as exc:  # Explicit software-failure report, not suppressed
        row["status"] = "software_fail"
        row["reason"] = type(exc).__name__ + ": " + safe_message(exc)
        row["next_action"] = "Fix the numerical model or its regression coverage"
    row["duration_seconds"] = round(time.monotonic() - start, 3)
    return row


def historical_input(spec: dict, dataset_id: str, record: dict) -> tuple[dict, int, int, str]:
    """Exact eligibility uses the same numerical input loader as execution."""
    key = spec["id"]
    minimum = required_count(spec)
    # A genuine, source-linked NIFTY TRI can be a valid single-series
    # input even if the folder has no separate multi-stock price panel.
    if not (record.get("has_prices") or record.get("has_daily_prices")) and key not in {"gbm_fit", "merton_fit"}:
        raise ValueError("No usable prepared source price panel; open Data Center to prepare original prices")
    if key in model_input_selector.MINIMUM:
        suggestions = model_input_selector.inspect(dataset_id, key)
        stock = next((item for item in suggestions.get("candidates", [])
                      if item.get("runnable")), None)
        if stock:
            return ({"target": "stock", "ticker": stock["ticker"]},
                    int(stock["returns"]), 1, stock["ticker"])
        tri = suggestions.get("tri", {})
        if key in {"gbm_fit", "merton_fit"} and tri.get("runnable"):
            return ({"target": "benchmark_tri"}, int(tri["returns"]), 1,
                    "source-linked NIFTY TRI")
        extendable = [candidate for candidate in suggestions.get("candidates", [])
                      if candidate.get("extendable")]
        if extendable:
            best = max(extendable, key=lambda item: int(item.get("returns", 0)))
            observed = int(best["returns"])
            needed_min = max(0, minimum - observed)
            needed_target = max(0, math.ceil(minimum * 1.2) - observed)
            raise ValueError(
                "No eligible observed stock or TRI for " + key + ". Best extendable "
                "ticker " + str(best.get("display_name") or best["ticker"]) +
                " (" + str(best["ticker"]) + ") has " + str(observed) +
                " observed returns, " + str(needed_min) +
                " short of the " + str(minimum) + "-return minimum and " +
                str(needed_target) + " short of the preferred " +
                str(math.ceil(minimum * 1.2)) + "-return +20% target. "
                "Select this exact stock and append authorized original history."
            )
        raise ValueError(
            "No stock or admissible TRI satisfies the " + str(minimum) +
            "-return requirement. Check observed daily-price continuity and source integrity."
        )

    readiness = model_lab.readiness(dataset_id)
    maximum = min(8, len(readiness.get("available_symbols", [])))
    if maximum < 2:
        raise ValueError("Portfolio models need at least two actual stock return series")
    last_reason = ""
    for assets in range(maximum, 1, -1):
        parameters = {"assets": assets}
        if key == "pca":
            parameters["components"] = min(3, assets)
        if key in {"min_variance", "risk_parity", "max_diversification",
                   "cvar", "efficient_frontier"}:
            parameters["max_weight"] = max(.30, math.ceil(100 / assets) / 100)
        try:
            # This checks the exact eligible-column ranking and aligned
            # common-return rule used by model_lab.run_model.
            aligned, _ = model_lab._historical_input(dataset_id, minimum, assets)
            model_registry.validate_parameters(key, parameters)
            return parameters, len(aligned), assets, ""
        except (ValueError, KeyError, OSError) as exc:
            last_reason = safe_message(exc)
    raise ValueError(last_reason or "No eligible aligned price-history sample")


def actual_quote_refs(dataset_id: str) -> list[str]:
    """Quote candidates are original saved provider observations, not synthetic prices."""
    snapshots = option_quotes.list_for(dataset_id)
    refs = []
    for snapshot in snapshots:
        for contract in snapshot.get("contracts", []):
            reference = snapshot["id"] + ":" + str(contract["row_index"])
            if option_market.inspect(dataset_id, reference).get("runnable"):
                refs.append(reference)
            if len(refs) >= 15:
                return refs
    return refs


def run_observed(spec: dict, dataset_id: str, record: dict, folder: Path,
                 digests: dict[str, str], *, execute: bool) -> dict:
    row = make_row(spec, dataset_id, record.get("kind", "unknown"))
    if (record.get("kind") == "synthetic" or
            (folder / "DO_NOT_CITE.txt").exists()):
        row["reason"] = "Synthetic fixture is not genuine observed market evidence"
        row["next_action"] = "Use Dhan original history or a documented authorized source"
        return row
    if spec["mode"] == "historical":
        try:
            parameters, observed, assets, ticker = historical_input(spec, dataset_id, record)
            row["observed_returns"] = observed
            row["missing_minimum"] = max(0, row["minimum_returns"] - observed)
            row["missing_to_target"] = max(0, row["preferred_returns"] - observed)
            row["assets"] = assets
            row["selected_ticker"] = ticker
        except Exception as exc:
            row["reason"] = type(exc).__name__ + ": " + safe_message(exc)
            if spec["id"] in model_input_selector.MINIMUM:
                try:
                    evidence = model_input_selector.inspect(dataset_id, spec["id"])
                    extendable = [item for item in evidence.get("candidates", [])
                                  if item.get("extendable")]
                    if extendable:
                        best = max(extendable,
                                   key=lambda item: int(item.get("returns", 0)))
                        row["selected_ticker"] = best["ticker"]
                        row["observed_returns"] = int(best["returns"])
                        row["missing_minimum"] = int(best["missing_minimum"])
                        row["missing_to_target"] = int(best["missing_to_target"])
                except (ValueError, KeyError, TypeError, OSError):
                    pass
            row["next_action"] = (
                "Models → Heston historical variance proxy → choose the named "
                "stock → Complete recommended stock (+20%). Original Dhan "
                "cache is reused before downloading uncovered windows."
                if spec["id"] == "heston_proxy" and row["selected_ticker"] else
                "Data Center → Get Market Data: select exact stocks, append missing "
                "observations with the +20% buffer, and resolve gaps"
            )
            return row
        # The original dataset remains the only source of historical returns.
        source_name = ("benchmark.csv" if ticker == "source-linked NIFTY TRI"
                       else "daily_prices.csv" if record.get("has_daily_prices")
                       else "prices.csv")
        row["source_file"] = source_name
        row["source_sha256"] = digests.get(source_name, "")
        if not row["source_sha256"]:
            row["reason"] = "Original model input has no source checksum"
            row["next_action"] = "Repair original source file before model execution"
            return row
        candidates = [parameters]
    elif spec["mode"] == "market":
        try:
            references = actual_quote_refs(dataset_id)
        except Exception as exc:
            references = []
            row["reason"] = "Option quote catalog error: " + safe_message(exc)
        if not references:
            if not row["reason"]:
                row["reason"] = "No original saved option bid/ask contract is available"
            row["next_action"] = (
                "Models → Observed option-quote model → Reuse existing BANKNIFTY "
                "recording (no new Dhan request), if available; otherwise capture "
                "one authorized read-only Dhan chain or import a source CSV"
                if dataset_id == "dhan_shared" else
                "Data Center / Model Catalog: capture an original read-only Dhan "
                "option chain or import an authorized option quote CSV"
            )
            return row
        candidates = [{"quote": ref} for ref in references]
    else:
        raise ValueError("Unexpected market-data mode")
    if not execute:
        row["status"] = "ready_not_executed"
        row["reason"] = "Original input selected; executable calculation not yet run"
        row["next_action"] = "Run the full audit without --preflight-only"
        if spec["mode"] == "market":
            row["quote_reference"] = candidates[0]["quote"]
        return row

    start = time.monotonic()
    quote_errors = []
    for config in candidates:
        try:
            result = model_lab.run_model(spec["id"], dataset_id, config)
            verify_output(result, spec, dataset_id)
            result_source = result["source"]
            if spec["mode"] == "historical":
                if result_source.get("source_file") != row["source_file"]:
                    raise ValueError("Model consumed a different historical source file")
            else:
                quote_id = config["quote"].partition(":")[0]
                receipt = option_quotes.get(quote_id, dataset_id)
                if (result_source.get("source_sha256") !=
                        receipt.get("source_sha256")):
                    raise ValueError("Market quote source digest changed during evaluation")
            row["status"] = "observed_input_pass"
            row["reason"] = (
                "Ran against a local original-source input. Neither source authenticity "
                "nor real-market predictive performance is independently certified"
            )
            row["next_action"] = "Review model limitations, source rights, and untouched holdout"
            if spec["mode"] == "market":
                row["quote_reference"] = config["quote"]
                row["source_file"] = "original option quote"
                row["source_sha256"] = str(result.get("source_sha256")
                                           or result.get("calibration", {}).get(
                                               "market_source_sha256") or "")
            break
        except ValueError as exc:
            # A saved bid/ask may be structurally valid yet inconsistent with
            # European BSM inversion for the assumed rate/yield.
            if spec["mode"] == "market":
                quote_errors.append(safe_message(exc))
                continue
            row["status"] = "software_fail"
            row["reason"] = type(exc).__name__ + ": " + safe_message(exc)
            row["next_action"] = "Investigate this model with the named observed dataset"
            break
        except Exception as exc:
            row["status"] = "software_fail"
            row["reason"] = type(exc).__name__ + ": " + safe_message(exc)
            row["next_action"] = "Investigate this model with original-source inputs"
            break
    if spec["mode"] == "market" and row["status"] == "blocked_input":
        row["reason"] = (
            "Saved quote candidates are not usable under the selected BSM "
            "convention/rate/yield assumptions: "
            + (quote_errors[-1] if quote_errors else "no valid candidates")
        )
        row["next_action"] = (
            "Inspect exact quote, exercise style, expiry, timestamp and assumptions; "
            "capture or import another admissible original contract"
        )
    row["duration_seconds"] = round(time.monotonic() - start, 3)
    return row


def inspect_dataset(record: dict, *, execute: bool) -> tuple[dict, list[dict]]:
    dataset_id = record["id"]
    folder, found = service.dataset_path(dataset_id)
    entry = {
        "dataset_id": dataset_id,
        "kind": found.get("kind", "unknown"),
        "label": found.get("label", dataset_id),
        "has_prices": bool(found.get("has_prices")),
        "has_daily_prices": bool(found.get("has_daily_prices")),
        "return_basis": found.get("return_basis", "unknown"),
        "benchmark_kind": found.get("benchmark_kind", "unknown"),
        "data_file_digests": {},
        "source_mutated_during_audit": False,
        "independently_source_certified_by_this_audit": False,
    }
    before = dataset_digests(folder)
    entry["data_file_digests"] = before
    # Index-study truth is separate from individual numerical-model readiness.
    # A stock-return GARCH can run without PIT membership, whereas publishable
    # multifactor NIFTY research cannot. Report both dimensions separately.
    try:
        evidence = historical_readiness.inspect(dataset_id)
        checks = evidence.get("checks", [])
        entry["index_research_evidence_status"] = evidence.get("status")
        entry["index_research_structural_ready"] = bool(
            evidence.get("structural_run_ready", False))
        entry["index_research_blockers"] = [
            {"name": x.get("name"), "detail": safe_message(x.get("detail", "")),
             "next_action": safe_message(x.get("next_action", ""))}
            for x in checks if x.get("status") == "blocked"
        ]
        entry["index_research_source_review_needed"] = [
            {"name": x.get("name"), "next_action": safe_message(x.get("next_action", ""))}
            for x in checks if x.get("status") == "review"
        ]
    except Exception as exc:
        entry["index_research_evidence_status"] = "unable_to_audit"
        entry["index_research_structural_ready"] = False
        entry["index_research_evidence_error"] = (
            type(exc).__name__ + ": " + safe_message(exc))
        entry["index_research_blockers"] = []
        entry["index_research_source_review_needed"] = []
    rows = []
    for spec in model_registry.MODELS:
        if spec["mode"] in MATH_MODES:
            continue
        row = run_observed(spec, dataset_id, found, folder, before, execute=execute)
        rows.append(row)
    after = dataset_digests(folder)
    if before != after:
        entry["source_mutated_during_audit"] = True
        for row in rows:
            if row["status"] == "observed_input_pass":
                row["status"] = "source_changed"
                row["reason"] = "Canonical data or provenance changed during this audit"
                row["next_action"] = "Re-run against a stable, immutable original snapshot"
    entry["observed_input_pass"] = sum(x["status"] == "observed_input_pass" for x in rows)
    entry["blocked_input"] = sum(x["status"] == "blocked_input" for x in rows)
    entry["software_fail"] = sum(x["status"] == "software_fail" for x in rows)
    entry["source_changed"] = bool(entry["source_mutated_during_audit"])
    return entry, rows


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_report(output: Path, body: dict, rows: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "SUMMARY.json").write_text(
        json.dumps(body, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_csv(output / "ALL_MODEL_RESULTS.csv", rows, COLUMNS)
    write_csv(output / "DATASET_SUMMARY.csv", body["datasets"], (
        "dataset_id", "kind", "label", "has_prices", "has_daily_prices",
        "return_basis", "benchmark_kind", "observed_input_pass",
        "blocked_input", "software_fail", "source_changed",
    ))
    by_dataset = {}
    for row in rows:
        by_dataset.setdefault(row["dataset_id"], []).append(row)
    lines = [
        "# QuantLab — all-model, all-dataset acceptance",
        "",
        "**Checked (UTC):** " + body["checked_utc"],
        "",
        "**Scope:** Read-only local model execution; no broker calls, no"
        " original-file changes, no orders and no simulated history passed"
        " off as real data.",
        "",
        "**Not a market certification.** " + UNVERIFIED,
        "",
        "## Summary",
        "",
        "- Registered models: " + str(body["registered_models"]),
        "- Mathematical models tested once (without market history): "
        + str(body["math_pass"]) + " pass / " + str(body["math_fail"]) + " fail",
        "- Local datasets audited: " + str(len(body["datasets"])),
        "- Actual-source model calculations passed: " + str(body["observed_input_pass"]),
        "- Blocked by data/quotes: " + str(body["blocked_input"]),
        "- Actual-source model calculations failed: " + str(body["software_fail"]),
        "- Datasets changed while checking: " + str(body["source_changed"]),
        "- Empty legacy data containers excluded from default totals: " +
        ", ".join(body.get("excluded_unprepared_legacy_containers", [])),
        "",
        "A blocked model is **not** a passing calculation. A numerical software "
        "failure is **not** automatically a missing-data failure.",
        "",
        "## Math-only model executions",
        "",
    ]
    for row in body["mathematics"]:
        lines.append("- **" + row["model_name"] + "**: " + row["status"] +
                     " — " + row["reason"])
    for dataset in body["datasets"]:
        did = dataset["dataset_id"]
        lines += [
            "",
            "## Dataset: " + did,
            "",
            "Kind: " + dataset["kind"] + "; return basis: "
            + str(dataset["return_basis"]) + "; benchmark: "
            + str(dataset["benchmark_kind"]),
            "",
            "| Model | Result | Observed returns | Minimum / target | Missing min / target | Action / explanation |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
        for row in by_dataset.get(did, []):
            action = row["reason"] if row["status"] == "observed_input_pass" else (
                row["reason"] + " — " + row["next_action"])
            action = action.replace("|", "/")
            lines.append(
                "| " + row["model_name"].replace("|", "/") + " | " + row["status"]
                + " | " + str(row["observed_returns"] or "—")
                + " | " + str(row["minimum_returns"]) + " / " +
                str(row["preferred_returns"]) + " | " +
                str(row["missing_minimum"] if row["missing_minimum"] != "" else "—") + " / " +
                str(row["missing_to_target"] if row["missing_to_target"] != "" else "—") + " | " + action + " |"
            )
        lines += [
            "",
            "**Index/PIT research evidence:** " +
            str(dataset.get("index_research_evidence_status", "unavailable")) +
            " · source blockers: " +
            str(len(dataset.get("index_research_blockers", []))) +
            " · additional reviews: " +
            str(len(dataset.get("index_research_source_review_needed", []))),
            "",
        ]
        for evidence in dataset.get("index_research_blockers", [])[:12]:
            lines.append("- **Missing source:** " + str(evidence["name"]) +
                         " — " + str(evidence["next_action"]))
        lines += [
            "",
            "Original CSV/manifest SHA-256 digests are in SUMMARY.json and "
            "ALL_MODEL_RESULTS.csv. SHA-256 confirms local file stability, "
            "not vendor authenticity.",
        ]
    lines += [
        "",
        "## Next steps",
        "",
        "1. For blocked historical models, open Data Center → Get Market Data, "
        "select missing source-backed securities, and request the +20% history "
        "buffer. Re-run this command after acquisition finishes.",
        "2. For blocked quote models, use a dated original Dhan bid/ask "
        "snapshot with an exact contract, not a spot/index proxy.",
        "3. Review any software_fail entry individually; a passed synthetic "
        "unit test does not override a real-input numerical failure.",
        "4. For publication-grade NIFTY/index claims, separately audit "
        "historical membership, corporate actions, genuine TRI and frozen "
        "holdout data. A model audit does not certify them.",
        "",
    ]
    (output / "MODEL_AUDIT.md").write_text(
        "\n".join(lines), encoding="utf-8")


def audit(*, datasets: list[str] | None, execute: bool, output: Path) -> dict:
    entries = service.datasets()
    # The built-in synthetic demonstration is not an original market-data
    # source. Do not make normal real-data totals look blocked by this fixture.
    # Users may still explicitly request --dataset synthetic for diagnostics.
    skipped_legacy = []
    if not datasets:
        skipped_legacy = [
            e["id"] for e in entries
            if e["id"] == "dhan_monthly" and
            not (e.get("has_prices") or e.get("has_daily_prices"))
        ]
        entries = [
            e for e in entries if e.get("kind") != "synthetic"
            and e["id"] not in skipped_legacy
        ]
    if datasets:
        missing = sorted(set(datasets) - {entry["id"] for entry in entries})
        if missing:
            raise ValueError("Dataset not found or archived: " + ", ".join(missing))
        entries = [entry for entry in entries if entry["id"] in datasets]
    if not entries:
        raise ValueError(
            "No active non-synthetic datasets found. Open Data Center and add original sources, "
            "then rerun. Mathematical software tests can still be run using "
            "python -m unittest tests.test_every_registered_model_runs"
        )
    mathematics = [run_math(spec, execute=execute)
                   for spec in model_registry.MODELS
                   if spec["mode"] in MATH_MODES]
    datasets_out = []
    rows = []
    for entry in entries:
        print("[DATASET]", entry["id"], "-", entry.get("label", ""))
        try:
            summary, outcomes = inspect_dataset(entry, execute=execute)
        except Exception as exc:
            summary = {
                "dataset_id": entry["id"], "kind": entry.get("kind", "unknown"),
                "label": entry.get("label", entry["id"]),
                "has_prices": bool(entry.get("has_prices")),
                "has_daily_prices": bool(entry.get("has_daily_prices")),
                "return_basis": entry.get("return_basis", "unknown"),
                "benchmark_kind": entry.get("benchmark_kind", "unknown"),
                "observed_input_pass": 0, "blocked_input": 0,
                "software_fail": 1, "source_changed": False,
                "dataset_error": type(exc).__name__ + ": " + safe_message(exc),
                "independently_source_certified_by_this_audit": False,
            }
            outcomes = []
            for spec in model_registry.MODELS:
                if spec["mode"] in MATH_MODES:
                    continue
                row = make_row(spec, entry["id"], entry.get("kind", "unknown"))
                row["status"] = "software_fail"
                row["reason"] = "Dataset audit error: " + summary["dataset_error"]
                row["next_action"] = "Inspect source inventory and corrupted files"
                outcomes.append(row)
            summary["software_fail"] = len(outcomes)
        datasets_out.append(summary)
        rows.extend(outcomes)
        tally = {status: sum(x["status"] == status for x in outcomes)
                 for status in ("observed_input_pass", "blocked_input",
                                "software_fail", "source_changed")}
        print("          ", tally)
    report = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "registered_models": len(model_registry.MODELS),
        "model_ids": [spec["id"] for spec in model_registry.MODELS],
        "mode_counts": {mode: sum(spec["mode"] == mode
                                 for spec in model_registry.MODELS)
                        for mode in ("synthetic", "theoretical", "historical", "market")},
        "mathematics": mathematics,
        "math_pass": sum(x["status"] == "math_pass" for x in mathematics),
        "math_fail": sum(x["status"] == "software_fail" for x in mathematics),
        "datasets": datasets_out,
        "excluded_unprepared_legacy_containers": skipped_legacy,
        "observed_input_pass": sum(x["status"] == "observed_input_pass" for x in rows),
        "blocked_input": sum(x["status"] == "blocked_input" for x in rows),
        "software_fail": sum(x["status"] == "software_fail" for x in rows),
        "source_changed": sum(bool(x["source_changed"]) for x in datasets_out),
        "no_market_data_download": True,
        "no_order_submission": True,
        "external_market_evidence_certified": False,
        "caveat": UNVERIFIED,
    }
    # Include math-only models once, without falsely associating them with data.
    write_report(output, report, rows + mathematics)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", help=(
        "Audit only this dataset ID (repeatable). Default: all active datasets"))
    parser.add_argument("--preflight-only", action="store_true",
                        help="Check exact source eligibility without executing models")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 2 if even one observed input is blocked")
    parser.add_argument("--output-dir", type=Path,
                        help="New report directory; default results/model_audit_UTC")
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output = args.output_dir or (service.ROOT / "results" /
                                 ("model_audit_" + stamp))
    if output.exists():
        parser.error("Output directory already exists; choose an unused path")
    try:
        report = audit(datasets=args.dataset, execute=not args.preflight_only,
                       output=output)
    except Exception as exc:
        print("MODEL AUDIT ERROR: " + safe_message(exc), file=sys.stderr)
        return 2
    print("")
    print("QuantLab: " + str(report["registered_models"]) + " registered models / "
          + str(len(report["datasets"])) + " datasets")
    if report["excluded_unprepared_legacy_containers"]:
        print("Skipped unprepared legacy container(s):",
              ", ".join(report["excluded_unprepared_legacy_containers"]))
    print("Math pass:", report["math_pass"], "  Actual-input pass:",
          report["observed_input_pass"], "  Data blocked:", report["blocked_input"],
          "  Software failures:", report["software_fail"])
    print("Report:", output / "MODEL_AUDIT.md")
    print("Matrix:", output / "ALL_MODEL_RESULTS.csv")
    print("Source truth is NOT independently certified by numerical tests.")
    failed = report["math_fail"] or report["software_fail"] or report["source_changed"]
    return 2 if failed or (args.strict and report["blocked_input"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
