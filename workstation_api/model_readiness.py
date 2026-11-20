"""One-pass model-specific data readiness; never call synthetic runs empirical.

Source sufficiency is a preflight, not a guarantee that an optimizer or
stochastic estimator converges on every numerically pathological series.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from index_research.data import read_matrix, read_returns
from . import model_registry, model_input_selector, service, option_quotes


MATH = {"synthetic":"simulation", "theoretical":"theory"}


def _step(title: str, ready: bool, detail: str, action: str) -> dict:
    return {"title":title,"state":"ready" if ready else "action_required",
            "detail":detail,"action_kind":action}


def _setup_for(spec: dict, *, dataset_id: str | None,
               original_prices: bool, quote_count: int,
               source_ready: bool, status: str, detail: str) -> tuple[list[dict],str]:
    """Every catalog model gets an honest, executable in-app route.

    Source-ready is NOT the same as runnable with as-yet-unselected parameter
    values. A successful preflight cannot certify a real historical backtest.
    """
    mode=spec["mode"]
    if mode in MATH:
        return ([
            _step("Mathematical implementation",True,
                  "Python solver implemented and covered by software tests.","run_math"),
            _step("Parameter values",True,
                  "Editable assumed inputs are available; use defaults or change them.","edit_parameters"),
            _step("Generate calculation",False,
                  "Run in Model Laboratory. Any simulated path remains hypothetical.","run_math"),
        ],"run_math")
    if mode=="market":
        return ([
            _step("Python numerical valuation",True,
                  "Quote-based option model implementation is available.","open_model"),
            _step("Local source dataset",bool(dataset_id),
                  "Choose the shared market library or a source-backed saved dataset.","select_dataset"),
            _step("Actual option bid/ask and expiry",quote_count>0,
                  f"{quote_count} saved original contracts. Capture Dhan's current chain "
                  "or import a provider CSV if none are available.","option_quotes"),
            _step("Exact contract selection",False,
                  "Select an individual saved quote; check its expiry and set rate/yield assumptions.",
                  "select_quote"),
            _step("Calculate source-anchored model values",False,
                  "Run in Model Laboratory. Output is theoretical even when the input is real.",
                  "open_model"),
        ],("select_dataset" if not dataset_id else
           "option_quotes" if not quote_count else "select_quote"))
    single=spec["id"] in model_input_selector.MINIMUM
    minimum=int(spec["min_observations"])
    count=1 if single else 8
    steps=[
        _step("Python research implementation",True,
              "Numerical algorithm is implemented; convergence depends on valid inputs.","open_model"),
        _step("Observed price library",bool(dataset_id and original_prices),
              "Use real, original stock history. The shared library is selected by default.",
              "select_dataset"),
    ]
    if single:
        steps.append(_step("Exact stock or original TRI selection",False,
            "Pick one named stock from eligible instruments. Only GBM/Merton accept "
            "original dividend-reinvested NIFTY TRI when explicitly selected.",
            "select_stock"))
    else:
        steps.append(_step("Required asset selection",bool(source_ready),
            "Default is eight aligned stocks, configurable to 2–18 in the model. "
            "Choose an actual source-backed universe; do not fabricate missing members.",
            "configure_assets"))
    steps.extend([
        _step("Observed return sample",bool(source_ready),
              f"At least {minimum} usable returns "
              f"({math.ceil(minimum*1.2)} preferred with +20% buffer). {detail}",
              "get_history"),
        _step("Run and inspect result",False,
              "After inputs pass the exact model preflight, run and inspect source "
              "lineage, assumptions and limitations.","open_model"),
    ])
    if not dataset_id or not original_prices:
        action="select_dataset"
    elif single:
        action="select_stock" if source_ready else "get_history"
    else:
        action="open_model" if source_ready else "get_history"
    if status=="fixture_only":
        action="select_dataset"
    return steps,action


def overview(dataset_id: str | None = None) -> dict:
    # Model-first default: use the one source-backed shared library when saved.
    # No auto-broker call, synthetic fallback, or mutation on a readiness GET.
    if not dataset_id:
        try:
            dataset_id=next((row["id"] for row in service.datasets()
                             if row["id"]=="dhan_shared" and
                             (row.get("has_prices") or row.get("has_daily_prices")) and row.get("kind")=="dhan"),None)
        except (ValueError,OSError,KeyError):
            dataset_id=None
    prices: pd.DataFrame | None=None
    daily=False
    tri=False
    tri_count=0
    snapshot_count=0
    dataset_label="No dataset selected"
    data_problem=""
    synthetic_fixture=False
    if dataset_id:
        try:
            folder,info=service.dataset_path(dataset_id)
            dataset_label=info.get("label",dataset_id)
            synthetic_fixture=info.get("kind")=="synthetic" or (folder/"DO_NOT_CITE.txt").exists()
            file="daily_prices.csv" if info.get("has_daily_prices") else "prices.csv"
            daily=file=="daily_prices.csv"
            if info.get("has_prices") or info.get("has_daily_prices"):
                prices=read_matrix(folder/file,positive=True)
            benchmark=folder/"benchmark.csv"
            proof=folder/"BENCHMARK_SOURCE.json"
            if benchmark.is_file() and proof.is_file() and not (
                    benchmark.is_symlink() or proof.is_symlink()):
                import json
                meta=json.loads(proof.read_text(encoding="utf-8"))
                if meta.get("return_convention") in {"gross_total_return","net_total_return"}:
                    series=read_returns(benchmark)
                    tri_count=len(series)
                    tri=tri_count>=10
            snapshot_count=sum(len(s["contracts"]) for s in option_quotes.list_for(dataset_id))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            data_problem=str(exc)[:160]
    returns=None if prices is None else prices.pct_change(fill_method=None).replace(
        [np.inf,-np.inf],np.nan)
    assets_with10=0 if returns is None else int((returns.notna().sum()>=10).sum())
    source_counts={}

    def historical_ready(model_id: str, minimum: int) -> tuple[bool,str,str]:
        if model_id in model_input_selector.MINIMUM:
            need=model_input_selector.MINIMUM[model_id]
            eligible=model_input_selector.rank_stocks(
                prices,"daily" if daily else "monthly",need,
                daily_only=model_id in model_input_selector.DAILY_ONLY)
            good=[row for row in eligible if row["runnable"]]
            # Source-linked TRI is a separate valid target for GBM/Merton;
            # a TRI-only dataset must not be mislabeled as missing prices.
            if model_id in {"gbm_fit","merton_fit"} and dataset_id:
                folder,_=service.dataset_path(dataset_id)
                tri_status=model_input_selector.tri_source_info(folder,need)
                if tri_status["runnable"]:
                    return (True,tri_status["reason"],
                            "Select target=NIFTY TRI; no individual stock candle required")
            if good:
                return (True, f"{len(good)} original ticker(s) pass {need}+ returns "
                        "and continuity checks",
                        "Choose one of the explicitly listed eligible tickers")
            if prices is None:
                return (False,"No original historical stock price panel",
                        "Import actual Dhan stock prices or original NIFTY TRI")
            if model_id in model_input_selector.DAILY_ONLY and not daily:
                return (False,"This stochastic model needs original daily stock closes",
                        "Select a daily Dhan dataset, not monthly-only returns")
            best=next((candidate for candidate in eligible if candidate.get("extendable")),None)
            if best:
                target=math.ceil(need*1.2)
                return (False,f"{best['ticker']} has {best['returns']} observed returns; "
                        f"{target} preferred (+20%), "
                        f"{max(0,target-best['returns'])} more needed",
                        "Open this model and click Get missing data (+20%) for a named stock")
            return (False, f"No ticker passes the {need}-return/gap/no-imputation checks",
                    "Inspect source gaps in Data Library before extending")
        if prices is None or returns is None:
            return (False, "No historical price panel available",
                    "Import or download original Dhan stock prices")
        count=8
        rows=sorted(returns.columns,
            key=lambda c:(-int(returns[c].notna().sum()),str(c)))[:count]
        if len(rows)<count:
            return (False,f"{len(rows)}/{count} required stock series present",
                    "Select a dataset with more securities")
        common=returns[rows].dropna()
        required=max(minimum,90) if model_id=="rolling_vol" else minimum
        if len(common)<required:
            return (False,f"{len(common)}/{required} aligned return observations for {count} stocks",
                    "Extend common observed Dhan returns or lower configured asset count")
        if (common.std(ddof=1)<=1e-10).any():
            return (False,"Constant or unusable return series in the selected subset",
                    "Review stock mappings and price history")
        return (True,f"{len(common)} aligned observed returns for {count} stocks",
                "Choose parameters and run; this is a source preflight, not validation")

    for spec in model_registry.MODELS:
        key=spec["id"]; mode=spec["mode"]
        if mode in MATH:
            status="math_ready"
            detail=("Numerical/analytical algorithm runs with explicit parameters."
                    " Simulated curves remain hypothetical.")
            action="Run mathematics mode or switch to its market-data companion"
            source_ready=False
        elif mode=="market":
            source_ready=snapshot_count>0
            status="source_available" if source_ready else "need_option_quote"
            detail=(f"{snapshot_count} original provider option contracts available"
                    if source_ready else "No timestamped original option bid/ask snapshot imported")
            action=("Select one stored quote and choose rate/dividend assumptions"
                    if source_ready else
                    "Use original option quote CSV importer; don't fabricate a premium")
        else:
            source_ready,detail,action=historical_ready(key,int(spec["min_observations"]))
            if synthetic_fixture:
                source_ready=False
                detail=("SYNTHETIC FIXTURE ONLY — model can execute, but this is not "
                        "observed historical market evidence")
                action="Choose an actual observed Dhan or source-linked NIFTY TRI dataset"
                status="fixture_only"
            else:
                status="source_available" if source_ready else "need_historical_data"
            if key=="heston_proxy":
                detail+="; proxy only — latent risk-neutral Heston NOT calibrated"
        setup_steps, next_action_kind=_setup_for(
            spec,dataset_id=dataset_id,
            original_prices=prices is not None and not synthetic_fixture,
            quote_count=snapshot_count,source_ready=source_ready,
            status=status,detail=detail)
        source_counts[key]={
            "id":key,"group":spec["group"],"title":spec["title"],"mode":mode,
            "status":status,"source_ready":source_ready,
            "mathematics_ready":mode in MATH,
            "implementation_status":spec["implementation_status"],
            "implementation_ready":spec["status"]=="runnable",
            "evidence_type":spec["evidence_type"],
            "setup_steps":setup_steps,
            "next_action_kind":next_action_kind,
            "run_ready_now":mode in MATH,
            "exact_selection_required":mode in {"historical","market"},
            "detail":detail,"next_action":action,
            "warning":"Preflight does not claim external certification or successful numerical convergence.",
        }
    values=list(source_counts.values())
    return {
        "dataset_id":dataset_id,"dataset_label":dataset_label,
        "total_models":len(values),
        "implemented_models":sum(x["implementation_ready"] for x in values),
        "implemented_not_market_validated":True,
        "math_ready":sum(x["status"]=="math_ready" for x in values),
        "historical_source_ready":sum(x["status"]=="source_available" and
                                      x["mode"]=="historical" for x in values),
        "option_source_ready":sum(x["status"]=="source_available" and
                                  x["mode"]=="market" for x in values),
        "input_blocked":sum(x["status"] in {
            "need_option_quote","need_historical_data","fixture_only"} for x in values),
        "synthetic_fixture_selected":synthetic_fixture,
        "available_original_option_contracts":snapshot_count,
        "data_problem":data_problem,
        "models":values,
        "not_a_market_performance_certification":True,
    }
