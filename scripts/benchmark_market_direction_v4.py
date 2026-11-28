"""Resumable research-only V4 experiment, fixed selection and final ensemble.

Build one verified underlying grid. Three expanding folds inside old training
select a dedicated-sign candidate; the final three seeds never select on the
old evaluation period. All files stay local, no provider requests or orders.
"""
import argparse
import csv
from datetime import date,datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import numpy as np

from scripts import benchmark_market_dynamics as d
from scripts import market_dynamics_history as hist
from scripts import market_direction_v4 as v4
from scripts.run_banknifty_candle_forecast import write_atomic

VERSION="market_direction_v4_fixed_walk_forward_v1"
SCREEN={"pre_epochs":2,"epochs":6,"patience":3,"stride":5,"seed":42}
FINAL={"pre_epochs":10,"epochs":30,"patience":6,"stride":1,"seeds":list(v4.SEEDS)}
CODE_FILES=("scripts/benchmark_market_direction_v4.py","scripts/market_direction_v4.py",
            "scripts/benchmark_market_dynamics.py","scripts/market_dynamics_v3.py",
            "scripts/market_dynamics_history.py","workstation_api/market_direction_v4.py",
            "workstation_api/market_dynamics_v3.py")


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def digest(value):return sha256(canonical(value)).hexdigest()


def file_digest(path):
    h=sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def save_json(path,value):
    write_atomic(path,lambda f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False))


def load_json(path):return json.loads(path.read_text(encoding="utf-8"))


def save_binary(path,writer):
    tmp=path.with_suffix(path.suffix+".tmp")
    try:
        with tmp.open("wb") as f:writer(f)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def bind_manifest(folder,manifest):
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/"manifest.json"
    if path.exists():
        if load_json(path)!=manifest:
            raise ValueError("Existing V4 run differs in source evidence, code, settings or splits; use a new run-id")
    else:save_json(path,manifest)
    return digest(manifest)


def record(path,identity):
    if not path.exists():return None
    result=load_json(path)
    if result.get("identity")!=identity:raise ValueError("Mismatched V4 completed record "+path.name)
    return result


def get_data(root,stop,scratch,progress):
    d.service.DATA=root/"data"
    if not d.service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=hist.archive_start(stop)
    index,stocks,membership,weights,peers,_,meta=d.m.load_sources(start,stop,wings=None,index_only=False,progress=progress)
    dates=sorted(index);splits=hist.full_splits(dates)
    stocks,meta["all_equities"]=hist.load_equities(start,stop,dates,stocks,progress)
    global_archive=hist.load_global(start,stop,dates,progress)
    meta["all_global"]=global_archive.evidence
    meta["options"]={"state":"excluded_from_underlying_direction"}
    data=d.build(index,stocks,membership,weights,peers,{}, {},{},(),(),splits,
                 all_history=True,scratch=scratch,include_options=False,pretraining=True,
                 global_archive=global_archive,horizons=v4.HORIZONS,extended_features=True,progress=progress)
    meta["all_global"]["factor_receipt_hashes"]=sorted(global_archive.receipts)
    meta["all_equities_excluded_from_embedding"]=sorted(set(stocks)-set(data["equity_identities"]))
    return data,splits,meta,start


def screen(data,splits,folder,manifest_id,device,batch,accumulate,progress):
    records=[]
    for fold,split in enumerate(v4.folds(splits[0]),1):
        pending=[]
        for variant,width in v4.CANDIDATES:
            identity={"manifest":manifest_id,"fold":fold,"variant":variant,"width":width}
            path=folder/f"screen_{fold}_{variant}_{width}.json"
            old=record(path,identity)
            if old is not None:
                progress("REUSED "+path.name);records.append(old)
            else:pending.append((variant,width,identity,path))
        if not pending:continue
        progress(f"V4 FOLD {fold} train {split[0][0]}..{split[0][-1]} validation {split[1][0]}..{split[1][-1]} score {split[2][0]}..{split[2][-1]}")
        part=v4.prepare(data,split,stride=SCREEN["stride"],progress=progress)
        refs=v4.reference_predictions(data,part)
        for variant,width,identity,path in pending:
            progress(f"V4 SCREEN fold={fold} variant={variant} width={width}")
            vp,ep,diag,_=v4.fit_model(data,part,variant,width,SCREEN["seed"],pre_epochs=SCREEN["pre_epochs"],
                epochs=SCREEN["epochs"],patience=SCREEN["patience"],batch=batch,accumulate=accumulate,device=device,progress=progress)
            p,cal=v4.calibrated(data,part,vp,ep)
            assessed=v4.assessment(data,part["te"],p,refs)
            raw=v4.assessment(data,part["te"],ep,refs)
            row={"identity":identity,"fold":fold,"variant":variant,"width":width,"dates":part["dates"],
                 "assessment":assessed,"raw_assessment":raw,"calibration":cal,"training":diag}
            save_json(path,row);records.append(row)
            progress(f"V4_SCREEN_RESULT {fold} {variant} {width} sign_brier={assessed['macro_sign_brier']:.8f}")
    selected,ranking=v4.choose(records)
    summary={"manifest":manifest_id,"selected":selected,"ranking":ranking,
             "records":sorted([r["identity"] for r in records],key=lambda r:(r["fold"],r["variant"],r["width"])),
             "selection_rule":"minimum mean of calibrated conditional sign Brier equally over nine horizons and three disjoint historical score folds; tie smaller width then fixed order",
             "trade_qualified":False}
    save_json(folder/"screen_summary.json",summary)
    progress("V4_SELECTED "+json.dumps(summary["selected"]))
    progress("V4_RANKING "+json.dumps(ranking))
    return summary


def read_screen(folder,manifest_id):
    records=[]
    for fold in (1,2,3):
        for variant,width in v4.CANDIDATES:
            path=folder/f"screen_{fold}_{variant}_{width}.json"
            identity={"manifest":manifest_id,"fold":fold,"variant":variant,"width":width}
            row=record(path,identity)
            if row is None:raise ValueError("Complete fixed screening before final fitting")
            records.append(row)
    selected,ranking=v4.choose(records)
    return {"manifest":manifest_id,"selected":selected,"ranking":ranking,"trade_qualified":False}


def journal(data,rows,p,raw):
    for i,row in enumerate(rows):
        day=str(data["days"][row]);minute=int(data["minutes"][row]);entry=minute+1+d.DELAY
        for k,horizon in enumerate(data["horizons"]):
            if not data["scheduled"][row,k]:continue
            observed=bool(data["mask"][row,k]);prob=float(p[i,k])
            end=d.MINUTES if horizon=="EOD" else entry+horizon
            call="UP" if prob>=v4.CONFIDENCE else "DOWN" if prob<=1-v4.CONFIDENCE else "ABSTAIN"
            yield {"session":day,"decision_utc":d.r._stamp(day,minute+1),"entry_reference_utc":d.r._stamp(day,entry),
                   "exit_reference_utc":d.r._stamp(day,end),"exit_reference_type":"session_close" if horizon=="EOD" else "minute_open",
                   "horizon":horizon,"conditional_up_probability":prob,"raw_conditional_up_probability":float(raw[i,k]),
                   "research_sign_call":call,"outcome_observed":observed,
                   "material_move":bool(abs(data["y"][row,k,0])>d.DEADBAND_BPS) if observed else None,
                   "actual_return_bps":float(data["y"][row,k,0]) if observed else None,
                   "actual_class":int(data["classes"][row,k]-1) if observed else None,
                   **{name+"_available":bool(data["available"][data["day_index"][row],minute,n]) for n,name in enumerate(data["availability_names"])}}


def final(data,splits,summary,folder,manifest_id,device,batch,accumulate,progress,meta):
    torch,_=d.seq._torch()
    selected=summary["selected"];variant=selected["variant"];width=selected["width"]
    part=v4.prepare(data,splits,stride=FINAL["stride"],progress=progress)
    validation=[];evaluation=[];seeds=[]
    for seed in v4.SEEDS:
        identity={"manifest":manifest_id,"variant":variant,"width":width,"seed":seed}
        path=folder/f"final_seed_{seed}.json";pred=folder/f"final_seed_{seed}.npz";weights=folder/f"final_seed_{seed}_research_only.pt"
        old=record(path,identity)
        if old is not None:
            if not pred.is_file() or not weights.is_file() or file_digest(pred)!=old["predictions_sha256"] or file_digest(weights)!=old["checkpoint_sha256"]:
                raise ValueError("Completed V4 seed artifacts missing or changed: "+str(seed))
            with np.load(pred,allow_pickle=False) as f:vp=f["validation"];ep=f["evaluation"]
            if vp.shape!=(len(part["va"]),len(data["horizons"])) or ep.shape!=(len(part["te"]),len(data["horizons"])) or not np.isfinite(vp).all() or not np.isfinite(ep).all():
                raise ValueError("Invalid completed V4 seed predictions")
            row=old;progress("REUSED "+path.name)
        else:
            progress(f"V4 FINAL {variant} width={width} seed={seed}")
            vp,ep,diag,checkpoint=v4.fit_model(data,part,variant,width,seed,pre_epochs=FINAL["pre_epochs"],epochs=FINAL["epochs"],
                 patience=FINAL["patience"],batch=batch,accumulate=accumulate,device=device,progress=progress)
            checkpoint["manifest_sha256"]=manifest_id
            save_binary(weights,lambda f:torch.save(checkpoint,f))
            save_binary(pred,lambda f:np.savez_compressed(f,validation=vp,evaluation=ep))
            row={"identity":identity,"training":diag,"checkpoint":weights.name,"checkpoint_sha256":file_digest(weights),
                 "predictions":pred.name,"predictions_sha256":file_digest(pred)}
            save_json(path,row)
        validation.append(vp);evaluation.append(ep);seeds.append(row)
    # All three seeds contribute equally, no selection based on old evaluation.
    vp=np.mean(validation,axis=0);ep=np.mean(evaluation,axis=0)
    p,cal=v4.calibrated(data,part,vp,ep)
    refs=v4.reference_predictions(data,part)
    report={"version":VERSION,"manifest_sha256":manifest_id,"selected":selected,"ranking":summary["ranking"],
            "training_dates":part["dates"][0],"validation_dates":part["dates"][1],"evaluation_dates":part["dates"][2],
            "horizons":list(data["horizons"]),"deadband_bps":d.DEADBAND_BPS,"delay_minutes":d.DELAY,
            "confidence_conditional_on_material":v4.CONFIDENCE,"research_only":True,"trade_qualified":False,
            "seeds":seeds,"ensemble_calibration":cal,"evaluation":v4.assessment(data,part["te"],p,refs),
            "evaluation_raw":v4.assessment(data,part["te"],ep,refs),
            "session_audit":data["audit"],"source_evidence":meta,
            "warning":"Exploratory previously examined dates, overlapping outcomes, descriptive block intervals without multiplicity correction. Conditional sign is not unconditional movement probability. Calls include flat and unresolved outcomes; illustrative index move less 5 bps is NOT executable P&L. V3 remains separate movement/range research. No options, live orders, prospective validation, model promotion or automatic trading. EOD label is delayed entry open to last regular-session close. VWAP proxy uses completed candle typical price times volume, not actual trade VWAP. Futures, verified tick depth and announcement-time inputs not yet integrated."}
    path=folder/"ensemble_predictions.csv"
    def writer(f):
        rows=journal(data,part["te"],p,ep);first=next(rows)
        w=csv.DictWriter(f,fieldnames=list(first));w.writeheader();w.writerow(first);w.writerows(rows)
    write_atomic(path,writer)
    report["prediction_csv"]=path.name;report["prediction_sha256"]=file_digest(path)
    save_json(folder/"final_report.json",report)
    progress("V4_FINAL "+json.dumps(report["evaluation"]))
    progress("REPORT "+str(folder/"final_report.json"))
    progress("PREDICTIONS "+str(path))
    return report


def run(root,stop,run_id,stage,batch,accumulate,device_name,progress=print):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",run_id):raise ValueError("Invalid run-id")
    if not 1<=batch<=64 or not 1<=accumulate<=32:raise ValueError("Invalid GPU batch/accumulation")
    if stop>datetime.now(d.h.IST).date():raise ValueError("Use completed dates")
    torch,_=d.seq._torch()
    if device_name=="cuda" and not torch.cuda.is_available():raise ValueError("CUDA unavailable")
    torch.set_num_threads(min(4,os.cpu_count() or 1));device=torch.device(device_name)
    results=root/"results";results.mkdir(exist_ok=True)
    folder=results/("market_direction_v4_"+run_id)
    code_root=Path(__file__).resolve().parent.parent
    with TemporaryDirectory(prefix="market_direction_v4_scratch_",dir=results) as scratch:
        data,splits,meta,start=get_data(root,stop,Path(scratch),progress)
        manifest={"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
                  "source_digest":digest(meta),"code_hashes":{p:file_digest(code_root/p) for p in CODE_FILES},
                  "dates":[list(x) for x in splits],"screen_folds":[[list(x) for x in split] for split in v4.folds(splits[0])],
                  "candidates":[list(x) for x in v4.CANDIDATES],"screen":SCREEN,"final":FINAL,"batch":batch,
                  "accumulate":accumulate,"device":device_name,"torch_version":str(torch.__version__),
                  "gpu":torch.cuda.get_device_name(0) if device.type=="cuda" else None,
                  "identities":data["identities"],"asset_fields":list(data["asset_fields"]),"aux_names":list(data["aux_names"]),
                  "horizons":list(data["horizons"]),"grid_shape":list(data["grid"].shape)}
        manifest_id=bind_manifest(folder,manifest)
        progress(f"V4_GRID {data['grid'].shape} bytes={data['grid'].nbytes} run={folder}")
        if stage in ("screen","all"):summary=screen(data,splits,folder,manifest_id,device,batch,accumulate,progress)
        else:summary=read_screen(folder,manifest_id)
        if stage in ("final","all"):return final(data,splits,summary,folder,manifest_id,device,batch,accumulate,progress,meta)
        return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=d.service.ROOT)
    ap.add_argument("--to-date",default="2026-11-27")
    ap.add_argument("--run-id",default="20261127")
    ap.add_argument("--stage",choices=("screen","final","all"),default="screen")
    ap.add_argument("--batch",type=int,default=16)
    ap.add_argument("--accumulate",type=int,default=8)
    ap.add_argument("--device",choices=("cpu","cuda"),default="cuda")
    args=ap.parse_args()
    try:
        run(args.shared_root.resolve(),date.fromisoformat(args.to_date),args.run_id,args.stage,args.batch,args.accumulate,args.device,
            lambda s:print(s,flush=True))
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("V4 unavailable:",str(exc)[:500],flush=True);return 2


if __name__=="__main__":raise SystemExit(main())
