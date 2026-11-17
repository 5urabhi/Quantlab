"""One-button real-data acceptance for local QuantLab research.

This combines existing strict PIT/TRI/corporate-action/chronological evidence
checks with actual numerical model smoke tests. It does NOT submit orders,
invent missing history or certify an exchange's source. All receipts are
versioned, local and free of raw broker credentials/market price payloads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import uuid

from . import historical_readiness, research_acceptance, service

SAFE_ID = re.compile(r"^acceptance_[0-9a-f]{16}$")


def _folder() -> Path:
    root = service.DATA / "research_workspace" / "real_data_acceptance"
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Unsafe research acceptance report directory")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _previous_limit(limit: int = 20) -> list[dict]:
    if not 1 <= limit <= 60:
        raise ValueError("Invalid real-data acceptance report limit")
    results = []
    for file in sorted(_folder().glob("acceptance_*.json"), reverse=True):
        if file.is_symlink() or file.stat().st_size > 2_000_000:
            continue
        try:
            body = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(body, dict) and SAFE_ID.fullmatch(str(body.get("id", ""))):
                results.append({name: body.get(name) for name in (
                    "id", "dataset_id", "created_utc", "status",
                    "source_checks_passed", "source_checks_blocked",
                    "model_software_pass", "model_software_fail",
                    "independently_certified")})
        except (OSError, ValueError):
            pass
        if len(results) >= limit:
            break
    return results


def recent(limit: int = 20) -> dict:
    return {"reports": _previous_limit(limit),
            "note": "Historical source certification remains a separate, manual evidence review."}


def report(report_id: str) -> dict:
    if not SAFE_ID.fullmatch(report_id or ""):
        raise ValueError("Invalid acceptance report identifier")
    file = _folder() / (report_id + ".json")
    if not file.is_file() or file.is_symlink() or file.stat().st_size > 2_000_000:
        raise ValueError("Original real-data acceptance report is unavailable")
    body = json.loads(file.read_text(encoding="utf-8"))
    if body.get("id") != report_id:
        raise ValueError("Acceptance report ID mismatch")
    # Reports are immutable historical snapshots. If someone replaced a
    # benchmark, price CSV or PIT file later, never display the old report
    # as if its source evidence were still current.
    try:
        folder, _ = service.dataset_path(body["dataset_id"])
        current = historical_readiness.source_hashes(folder)
        unchanged = current == body.get("source_hashes")
        body["current_source_match"] = unchanged
        body["current_source_status"] = (
            "matches_original_audit" if unchanged else
            "changed_since_audit_reverification_required")
    except (OSError, ValueError, KeyError):
        body["current_source_match"] = False
        body["current_source_status"] = "original_dataset_missing_or_unavailable"
    if not body["current_source_match"]:
        body["current_evidence_usable"] = False
        body["warning"] = (
            "Original data changed or is missing since this report was produced. "
            "Run a new source/model acceptance; the saved original receipt is "
            "retained for historical review. " + str(body.get("warning") or ""))
    else:
        body["current_evidence_usable"] = True
    return body


def execute(dataset_id: str, validation_start: str, final_test_start: str, *,
            run_models: bool = True, progress=None) -> dict:
    if not isinstance(dataset_id, str) or not 1 <= len(dataset_id) <= 120:
        raise ValueError("Select an existing original dataset")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", validation_start or "") or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", final_test_start or ""):
        raise ValueError("Choose exact validation and untouched final-test dates")
    if (datetime.fromisoformat(validation_start).date() >=
            datetime.fromisoformat(final_test_start).date()):
        raise ValueError("Final untouched test window must begin after validation")
    if progress:
        progress(5, "Auditing actual PIT, TRI, corporate actions and holdout chronology")
    evidence = historical_readiness.inspect(
        dataset_id, validation_start=validation_start,
        final_test_start=final_test_start)
    # Never elevate source hashes or user declarations into an original-market
    # certificate. Model execution is kept distinct from source acceptance.
    if progress:
        progress(25, "Checking eligible registered models against actual original inputs")
    model_report = None
    if run_models and evidence.get("dataset_kind") != "synthetic":
        model_report = research_acceptance.verify(dataset_id,include_historical=True,
            progress=(lambda n,msg:progress(25 + n*.7,msg)) if progress else None)
    elif run_models:
        model_report = {"attempted_models": 0, "software_pass": 0, "software_fail": 0,
                        "checks": [], "source_blocked": 0,
                        "note": "Synthetic fixtures cannot receive historical acceptance."}
    blocked = [x for x in evidence["checks"] if x["status"] == "blocked"]
    reviewed = [x for x in evidence["checks"] if x["status"] == "review"]
    passed = [x for x in evidence["checks"] if x["status"] == "pass"]
    # A structural data pass alone does not mean model execution passed.
    # A user can deliberately skip model checks; that is a source-only report,
    # never a fully software-ready empirical study.
    tested_models = (model_report.get("attempted_models", 0)
                     if model_report is not None else 0)
    model_passed = (not run_models or (
        tested_models > 0 and model_report is not None and
        model_report.get("software_fail", 0) == 0 and
        model_report.get("software_pass", 0) > 0))
    accepted_software = (
        bool(evidence.get("structural_run_ready", False)) and
        model_passed and run_models
    )
    blockers = [
        {"component":x["name"],"state":x["status"],"detail":x["detail"],
         "next_action":x.get("next_action","")} for x in blocked+reviewed
    ]
    if run_models and tested_models <= 0:
        blockers.append({
            "component": "Observed mathematical model verification",
            "state": "blocked",
            "detail": "No eligible model completed an actual software verification.",
            "next_action": "Resolve original model input requirements and rerun the audit.",
        })
    elif not run_models:
        blockers.append({
            "component": "Observed mathematical model verification",
            "state": "skipped",
            "detail": "Model execution was not requested; only the original data inputs were inspected.",
            "next_action": "Enable model software verification in a new acceptance report.",
        })
    if not blockers:
        blockers.append({
            "component":"External original market-data review",
            "state":"pending","detail":"An automated source hash is not issuer certification.",
            "next_action":"Reconcile licensed issuer files, publication dates and rights independently."})
    status = ("structurally_runnable_not_independently_certified" if accepted_software
              else "original_sources_or_models_incomplete")
    result = {
        "id":"acceptance_"+uuid.uuid4().hex[:16],
        "dataset_id":dataset_id,"created_utc":datetime.now(timezone.utc).isoformat(),
        "status":status,
        "structural_ready":bool(evidence.get("structural_run_ready")),
        "models_verified":bool(tested_models > 0 and
                                 model_report and
                                 model_report.get("software_fail",0) == 0),
        "model_execution_requested":run_models,
        "independently_certified":False,"publication_ready":False,
        "source_checks_passed":len(passed),"source_checks_blocked":len(blocked),
        "source_checks_review":len(reviewed),
        "source_hashes":evidence["source_hashes"],
        "chronological_windows":evidence["timing"],
        "evidence_checks":evidence["checks"],
        "blockers":blockers,
        "model_software_pass":model_report.get("software_pass",0) if model_report else 0,
        "model_software_fail":model_report.get("software_fail",0) if model_report else 0,
        "model_software_checks":model_report.get("checks",[]) if model_report else [],
        "model_audit_id":model_report.get("id") if model_report else None,
        "warning":"Software checks do not certify NIFTY membership, stock total "
                  "returns, TRI, publication-vintage fundamentals, fees, execution "
                  "or genuine untouched final-test performance.",
    }
    file = _folder() / (result["id"] + ".json")
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),
                   encoding="utf-8")
    os.replace(tmp,file)
    if progress:
        progress(100,"Saved reproducible source/model acceptance report with actual blockers")
    return result
