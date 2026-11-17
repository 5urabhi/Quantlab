"""One approved in-app flow: resolve original data -> run algorithm -> save result.

Only original source-backed historical models become empirical runs. If an
external dependency cannot be fulfilled, this returns a precise blocker rather
than a seeded simulation or hardcoded model result. Stored run artifacts keep
existing model_lab source and engine hashes.
"""
from __future__ import annotations

from . import (data_acquisition, model_data_manager, model_lab, model_registry,
               service, shared_market_data)

SINGLE=frozenset({"gbm_fit","ou_fit","merton_fit","heston_proxy"})


def execute(model_id: str, dataset_id: str | None, params: dict | None = None,
            *, preview_token: str = "",
            confirm_download: bool = False,
            allow_upstox: bool = False,
            prepare_buffer: bool = True,
            progress=None) -> dict:
    if model_id not in model_registry.CATALOG:
        raise ValueError("Select a registered research algorithm")
    model=model_registry.CATALOG[model_id]
    provided=params or {}
    if not isinstance(provided,dict):
        raise ValueError("Model parameters must be an object")
    settings=model_registry.validate_parameters(model_id,provided)
    if model["mode"]=="market":
        return {"status":"blocked","action":"option_quotes",
                "message":"Import or capture a source-original bid/ask quote, "
                          "then run the contract model from Model Laboratory."}
    if model["mode"] in {"synthetic","theoretical"}:
        if progress:
            progress(15,"Running mathematical model with explicit assumptions")
        result=model_lab.run_model(model_id,dataset_id,settings)
        saved=model_lab.save_result(result)
        if progress:
            progress(100,"Mathematical model saved with simulation/theory label")
        return {"status":"complete","dataset_id":dataset_id,
                "model_id":model_id,"run":saved,
                "data_kind":model["mode"],
                "warning":"Synthetic/theoretical mathematics is not historical trading evidence."}
    if not dataset_id:
        return {"status":"blocked","action":"choose_dataset",
                "message":"Select an original observed dataset before running."}
    folder, dataset_record = service.dataset_path(dataset_id)
    if (dataset_record.get("kind") == "synthetic" or
            (folder / "DO_NOT_CITE.txt").exists()):
        return {
            "status": "blocked", "action": "choose_original_dataset",
            "dataset_id": dataset_id, "model_id": model_id,
            "message": "Synthetic demonstration fixtures cannot be promoted to "
                       "observed empirical market research. Choose an original "
                       "provider dataset or genuine total-return history.",
        }
    if progress:
        progress(5,"Checking exact original model inputs and data buffer")
    acquisition_params={k:v for k,v in settings.items()
                        if k in data_acquisition.PARAMETERS}
    current=data_acquisition.plan(
        model_id,dataset_id,acquisition_params,with_sources=False)
    source=current["requirements"]
    acquisition=None
    needs_extension=(not source.get("runnable") or
                     (prepare_buffer and current.get("can_acquire") and
                      (source.get("missing_to_target") or 0)>0))
    if needs_extension:
        if not current["can_acquire"]:
            return {"status":"blocked","action":current["next_action"]["kind"],
                    "dataset_id":dataset_id,"model_id":model_id,
                    "message":source.get("download_explanation") or
                              source.get("message") or "No eligible original historical source.",
                    "minimum_observed_returns":source.get("min_returns"),
                    "required_with_20_percent":source.get("target_returns")}
        if not confirm_download:
            return {"status":"needs_confirmation","action":"acquisition",
                    "message":"Approve original historical download before starting."}
        # Plan is reconfirmed with identical source, parameters and sample
        # scope; stale approvals cannot launch new provider requests.
        if not preview_token:
            raise ValueError("Missing original-data plan receipt")
        checked=data_acquisition.check_confirmation(
            model_id,dataset_id,acquisition_params,preview_token,True)
        if allow_upstox and not checked["upstox_fallback_eligible"]:
            raise ValueError("Secondary historical provider requires token, exact ISIN "
                             "mapping and explicit user authorization")
        if progress:
            progress(12,"Reusing cached original candles and authorized missing windows")
        def stage(percent,message):
            if progress:
                progress(12+70*percent/100,message)
        acquisition=data_acquisition.execute(
            model_id,dataset_id,acquisition_params,
            allow_upstox=allow_upstox,progress=stage)
        dataset_id=acquisition.get("dataset_id") or dataset_id
        if model_id in SINGLE and acquisition.get("selected_ticker"):
            settings={**settings,"ticker":acquisition["selected_ticker"]}
        after=model_data_manager.inspect(model_id,dataset_id,settings)
        if not after.get("runnable"):
            return {"status":"incomplete","action":"source_review",
                    "dataset_id":dataset_id,"model_id":model_id,
                    "message":"Original data was updated, but actual observations "
                              "still cannot satisfy this model. No simulation substituted.",
                    "data_completion":acquisition,"after":after}
    if progress:
        progress(86,"Executing numerical model with verified input selection")
    result=model_lab.run_model(model_id,dataset_id,settings)
    if progress:
        progress(96,"Saving source-bound model run and figures")
    saved=model_lab.save_result(result)
    if progress:
        progress(100,"Source-bound model run saved")
    return {"status":"complete","dataset_id":dataset_id,
            "model_id":model_id,"data_kind":"observed_original",
            "run":saved,"data_completion":acquisition,
            "warning":"Executable model inputs do not independently certify "
                      "corporate actions, TRI, historical membership or profitability."}
