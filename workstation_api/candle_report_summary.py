"""Read-only compact summaries of locally generated first-passage reports."""
from pathlib import Path
from math import isfinite
import json
import re

NAME=re.compile(r"candle_barriers_[a-f0-9]{32}\.json")
MAX_BYTES=16*1024*1024
MAX_FILES=500


def _number(value):
    return float(value) if type(value) in (int,float) and isfinite(value) else None


def _compact(report):
    if not isinstance(report,dict) or report.get("version")!="sequence_first_passage_v1":
        raise ValueError("Unknown report version")
    def rows(scope):
        out=[]
        comparisons=scope.get("selected_model_comparison",{})
        for name,t in scope["augmented"]["tasks"].items():
            if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9_]{1,60}",name):
                continue
            chosen=t["selected_on_validation"]
            if chosen not in ("training_prior","random_forest"):
                continue
            h=t["holdout"][chosen]
            diff=comparisons.get(name) or {}
            out.append({"task":name,"selected":chosen,"brier":_number(h.get("brier")),
                        "accuracy":_number(h.get("accuracy")),"scored":_number(h.get("scored")),
                        "predicted":{k:_number(v) for k,v in h["predicted"].items() if k in (
                            "lower_first","upper_first","neither","ambiguous","down_at_least","within_band","up_at_least","down","flat","up")},
                        "observed":{k:_number(v) for k,v in h["observed"].items() if k in (
                            "lower_first","upper_first","neither","ambiguous","down_at_least","within_band","up_at_least","down","flat","up")},
                        "matched_brier_difference":_number(diff.get("brier_difference"))})
        return {"state":scope["augmented"]["state"],"coverage":{k:_number(v) for k,v in scope["matched_coverage"].items()
                    if k in ("train","validation","holdout")},"tasks":out[:12]}
    horizons={}
    for width in ("5","15","30"):
        item=report["horizons"].get(width)
        if item is None:
            continue
        scopes={key:rows(item["scopes"][key]) for key in ("sequence","global","panel","panel_global") if key in item["scopes"]}
        bank=report.get("bank_directions",{}).get(width)
        if bank is not None:
            scopes["bank_directions"]=rows(bank)
        horizons[width]=scopes
    dates={}
    for key in ("training_dates","validation_dates","holdout_dates"):
        values=report[key]
        if not isinstance(values,list) or len(values)>120 or any(not isinstance(x,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",x) for x in values):
            raise ValueError("Invalid report dates")
        dates[key]=values
    return {"horizons":horizons,**dates,"bank_target_state":report.get("bank_target_state","unavailable")
            if report.get("bank_target_state") in ("disabled","unavailable","observed_fixed_panel","source_changed_during_research") else "unavailable"}


def latest(root):
    directory=Path(root)
    if not directory.exists():
        return {"state":"no_saved_report"}
    if directory.is_symlink() or not directory.is_dir():
        return {"state":"unavailable"}
    candidates=[]
    try:
        for path in directory.glob("candle_barriers_*.json"):
            if not NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            stat=path.stat()
            candidates.append((stat.st_mtime_ns,path))
            if len(candidates)>MAX_FILES:
                return {"state":"report_limit_exceeded"}
        for _,path in sorted(candidates,reverse=True):
            if path.stat().st_size>MAX_BYTES:
                continue
            try:
                result=_compact(json.loads(path.read_text(encoding="utf-8")))
                return {"state":"available","report_name":path.name,**result}
            except (ValueError,TypeError,KeyError,AttributeError,OSError):
                continue
        return {"state":"no_saved_report" if not candidates else "no_valid_saved_report"}
    except OSError:
        return {"state":"unavailable"}
