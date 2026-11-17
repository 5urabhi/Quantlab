"""One authoritative, source-aware research readiness and software audit.

Numerical smoke success is deliberately distinct from external historical
evidence. A missing historical NIFTY/BANKNIFTY constituent, TRI level or
dividend is never declared complete because Python tests pass. Audit results
are stored locally without raw licensed prices or broker credentials.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
import json
import os
import uuid

from . import (data_acquisition, model_data_manager, model_input_selector,
               model_lab, model_readiness, model_registry, pit_index,
               service, source_completion)

LOCK=RLock()
MAX_MODELS=80


def _benchmark(dataset_id: str | None) -> dict:
    if not dataset_id:
        return {"status":"choose_dataset","next_action":"Select an observed research dataset."}
    try:
        folder,record=service.dataset_path(dataset_id)
        meta=source_completion.existing_benchmark_status(folder)
        corporate=folder/"corporate_actions.csv"
        pit=folder/"PIT_MEMBERSHIP_PROVENANCE.json"
        return {
            "tri":meta,
            "corporate_actions_present":corporate.is_file() and not corporate.is_symlink(),
            "corporate_actions_certified":False,
            "pit_snapshot_present":pit.is_file() and not pit.is_symlink(),
            "pit_officially_certified":False,
            "next_action":("Review ex-date/source rights and benchmark TRI chronology "
                           "with original NSE Indices evidence; never substitute spot index."),
        }
    except (ValueError,OSError) as exc:
        return {"status":"unavailable","reason":str(exc)[:170]}


def sources(dataset_id: str | None=None) -> dict:
    try:
        membership=pit_index.status()
    except (ValueError,OSError) as exc:
        membership={"available":False,"reason":str(exc)[:180]}
    return {
        "historical_membership":membership,
        "benchmark_and_actions":_benchmark(dataset_id),
        "membership_status":(
            "independent_reconstruction_not_exchange_certified"
            if membership.get("available") else "missing_or_invalid"),
        "requirements":[
            {"id":"pit_nifty50", "label":"NIFTY 50 historical constituent evidence",
             "verified_by_exchange":False,
             "available":bool(membership.get("available")),
             "action":"Sync pinned point-in-time reconstruction, resolve missing delisted IDs, audit official notices."},
            {"id":"pit_banknifty", "label":"BANK NIFTY historical constituent evidence",
             "verified_by_exchange":False,
             "available":bool(membership.get("available")),
             "action":"Verify every effective-date change and historical membership size."},
            {"id":"nifty_tri", "label":"Genuine NIFTY total-return benchmark",
             "verified_by_exchange":False,
             "available":_benchmark(dataset_id).get("tri",{}).get("is_tri",False),
             "action":"Import an authorized original TRI level/return history with source receipt."},
            {"id":"corporate_actions", "label":"Dividends, splits, delistings and publication-vintage events",
             "verified_by_exchange":False,
             "available":_benchmark(dataset_id).get("corporate_actions_present",False),
             "action":"Import audited original corporate action events and verify ex-dates."},
        ],
        "no_unverified_history_promoted":True,
    }


def overview(dataset_id: str | None=None) -> dict:
    original=model_readiness.overview(dataset_id)
    dataset_id=original["dataset_id"]
    rows=[]
    for existing in original["models"]:
        spec=model_registry.CATALOG[existing["id"]]
        try:
            needed=model_data_manager.requirement(existing["id"],{})
        except (ValueError,TypeError):
            needed={"min_returns":spec["min_observations"],
                    "target_returns":int(spec["min_observations"]*1.2+.999)}
        if existing["status"]=="math_ready":
            action={"kind":"run","label":"Run mathematical model","automatable":True}
        elif existing["status"]=="source_available":
            action={"kind":"open_model",
                    "label":("Select one original quote and run"
                             if existing["mode"]=="market" else
                             "Configure exact stocks and run"),
                    "automatable":False}
        elif existing["status"]=="need_option_quote":
            action={"kind":"option_quotes","label":"Connect or import original quote",
                    "automatable":False}
        elif existing["status"]=="fixture_only":
            action={"kind":"select_dataset","label":"Use genuine observed market data",
                    "automatable":False}
        else:
            action={"kind":"open_model","label":"Inspect exact requirements and +20% completion",
                    "automatable":False}
        rows.append({**existing,"requirement":{
            "minimum_observed_returns":needed.get("min_returns",0),
            "preferred_with_20_percent":needed.get("target_returns",0),
            "frequency":needed.get("frequency","observed returns"),
        },"action":action,
        "tested_for_real_market_performance":False})
    return {
        "dataset_id":dataset_id,"dataset_label":original["dataset_label"],
        "total_models":len(rows),
        "implemented_models":original["implemented_models"],
        "math_ready":original["math_ready"],
        "historical_source_ready":original["historical_source_ready"],
        "option_source_ready":original["option_source_ready"],
        "blocked":original["input_blocked"],
        "synthetic_fixture":original["synthetic_fixture_selected"],
        "models":rows,"sources":sources(dataset_id),
        "next_step":"Select original data, resolve one model, run model, verify result.",
        "warning":"Source readiness is not external market-data certification. "
                  "Model execution success is not a profitable strategy or PIT backtest.",
    }


def _audit_root() -> Path:
    path=service.DATA/"research_workspace"/"model_software_audits"
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe model verification storage")
    return path


def verify(dataset_id: str | None=None, *,
           include_historical: bool=True,
           progress=None) -> dict:
    """Run each eligible model once with default params; never fetch broker data.

    Independent of normal save_result: verification is a read-only smoke test.
    User-selected tickers remain mandatory for publishing a new research run.
    """
    matrix=overview(dataset_id)
    candidates=[x for x in matrix["models"] if
                x["status"] in ("math_ready","source_available")]
    if not include_historical:
        candidates=[x for x in candidates if x["mode"] in ("synthetic","theoretical")]
    if len(candidates)>MAX_MODELS:
        raise ValueError("Too many model software checks")
    checks=[]
    for i,item in enumerate(candidates):
        key=item["id"]
        config={}
        if item["mode"]=="historical":
            if not dataset_id:
                continue
            if key in model_input_selector.MINIMUM:
                selection=model_input_selector.inspect(dataset_id,key)
                eligible=next((x for x in selection["candidates"] if x["runnable"]),None)
                if not eligible:
                    checks.append({"model_id":key,"state":"blocked",
                                   "reason":"No original stock passes the exact fitting checks."})
                    continue
                config={"target":"stock","ticker":eligible["ticker"]}
        try:
            result=model_lab.run_model(key,dataset_id,config)
            if not isinstance(result,dict):
                raise ValueError("Algorithm did not return a structured result")
            checks.append({
                "model_id":key,"state":"software_pass",
                "uses_original_market_data":item["mode"]=="historical",
                "qa_only_stock_selection":config.get("ticker"),
                "result_kind":str(result.get("model_id",key))[:70],
                "not_an_empirical_certification":True,
            })
        except (ValueError,TypeError,KeyError,OSError,
                ArithmeticError,RuntimeError) as exc:
            # No raw dataset values, provider bodies or credentials in audit.
            checks.append({"model_id":key,"state":"software_fail",
                           "reason":type(exc).__name__+
                                    ": "+str(exc)[:200]})
        if progress:
            progress(3+95*(i+1)/max(1,len(candidates)),
                     "Checked "+str(i+1)+"/"+str(len(candidates))+" model algorithms")
    report={
        "id":"audit_"+uuid.uuid4().hex[:16],
        "dataset_id":dataset_id,
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "total_catalog_models":matrix["total_models"],
        "attempted_models":len(checks),
        "software_pass":sum(x["state"]=="software_pass" for x in checks),
        "software_fail":sum(x["state"]=="software_fail" for x in checks),
        "source_blocked":matrix["blocked"],
        "checks":checks,
        "historical_data_externally_verified":False,
        "note":"Observed data access does not imply original-source or PIT certification. "
               "This smoke suite does not estimate model profitability.",
    }
    folder=_audit_root()
    with LOCK:
        folder.mkdir(parents=True,exist_ok=True)
        final=folder/(report["id"]+".json")
        tmp=folder/("."+report["id"]+".tmp")
        tmp.write_text(json.dumps(report,indent=2,allow_nan=False),
                       encoding="utf-8")
        os.replace(tmp,final)
    return report


def audit_list(limit: int=15) -> dict:
    if not 1<=limit<=50:
        raise ValueError("Invalid model-audit limit")
    root=_audit_root()
    if not root.is_dir():
        return {"audits":[]}
    found=[]
    for p in sorted(root.glob("audit_*.json"),reverse=True):
        if p.is_symlink() or p.stat().st_size>1_000_000:
            continue
        try:
            result=json.loads(p.read_text(encoding="utf-8"))
            found.append({k:result.get(k) for k in (
                "id","dataset_id","checked_utc","attempted_models",
                "software_pass","software_fail","source_blocked")})
        except (ValueError,OSError):
            continue
        if len(found)>=limit:
            break
    return {"audits":found}
