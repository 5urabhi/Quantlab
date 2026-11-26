"""Saved-only chronological BANKNIFTY minute-option scalping grid.

No provider calls, live-recorder changes, executable fill claims, or order
submission. Process bounded date blocks and reuse the original fee engine.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from statistics import mean
from threading import Lock
import json
import math
import os
import re
import uuid

from . import expired_options_backtest as exp, market_patterns, depth_replay, service, liquidity_spreads as fees

RULES=("EMA_CROSSOVER","MEAN_REVERSION","RANGE_REVERSION")
HOLDS=(1,2,3,5,10,15,30)
TARGETS=((1.,1.),(2.,2.),(3.,2.),(5.,3.),(10.,5.))
MAX_RECEIPTS=4096
MAX_SCAN_BYTES=2*1024**3
MIN_COVERAGE=338 # 90% of 375 regular minutes on EACH side
LOCK=Lock()
VERSION="saved_minute_scalping_grid_v1"
MISSING={"missing_underlying_entry","missing_option_entry","missing_exact_contract_path","zero_exit_volume","invalid_exit_time"}


def _scope(start_date,end_date,today):
    a,b=date.fromisoformat(start_date),date.fromisoformat(end_date)
    if a.isoformat()!=start_date or b.isoformat()!=end_date or not today-timedelta(days=365)<=a<=b<today:
        raise ValueError("Choose completed IST dates inside the preceding 365 calendar days")
    return a,b


def candidates(max_lots,compare_lots):
    lots=range(1,max_lots+1) if compare_lots else (max_lots,)
    return [{"id":f"{rule}:{qty}:{hold}:{target or 0}:{stop or 0}",
             "rule":rule,"lots":qty,"hold_minutes":hold,
             "target_points":target,"stop_points":stop}
            for rule in RULES for qty in lots
            for hold,target,stop in ([(h,None,None) for h in HOLDS]+
                [(h,t,s) for h in (3,5,10) for t,s in TARGETS])]


def _catalog(a,b,wings):
    root=Path(service.DATA)/"dhan_expired_options"
    if not root.exists():
        return [],0
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid local expired-options cache")
    paths=[p for p in root.iterdir() if re.fullmatch(r"[0-9a-f]{64}\.json",p.name)]
    if len(paths)>MAX_RECEIPTS:
        raise ValueError("Expired-option receipt count exceeds bounded study scope")
    total=0
    result=[]
    rejected=0
    for p in sorted(paths):
        try:
            if p.is_symlink() or not p.is_file() or p.stat().st_size>exp.MAX_RESPONSE_BYTES+5000:
                raise ValueError("Invalid receipt path or size")
            total+=p.stat().st_size
            if total>MAX_SCAN_BYTES:
                raise RuntimeError("Saved option cache exceeds 2 GiB catalog scan limit")
            item=json.loads(p.read_text(encoding="utf-8"))
            body=item["request"]
            if body.get("expiryFlag")!="MONTH" or body.get("expiryCode")!=1 or body.get("strike") not in exp._offsets(wings) or body.get("drvOptionType") not in ("CALL","PUT"):
                continue
            lo,hi=date.fromisoformat(body["fromDate"]),date.fromisoformat(body["toDate"])
            if hi<=a or lo>b:
                continue
            if body!=exp._request_body(lo,hi,"MONTH",0,body["strike"],body["drvOptionType"]) or p!=exp._cache_path(body) or item.get("source")!="Dhan v2 /charts/rollingoption":
                raise ValueError("Unexpected receipt scope")
            payload=item["payload"]
            digest=sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            if item["sha256"]!=digest:
                raise ValueError("Receipt digest mismatch")
            result.append((lo,hi,body,digest))
        except (ValueError,TypeError,AttributeError,KeyError,OSError,UnicodeError):
            rejected+=1
    return result,rejected


def _block(catalog,a,b):
    prices={}
    conflicts=set()
    rejected=0
    for lo,hi,body,digest in catalog:
        if lo>=b or hi<=a:
            continue
        try:
            payload=exp._get_cached(body)
            if payload is None or sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=digest:
                raise ValueError("Source changed during research")
            rows=exp._normalize(payload,body)
        except (ValueError,TypeError,KeyError,OSError):
            rejected+=1
            continue
        for row in rows:
            if not a.isoformat()<=row["session_ist"]<b.isoformat():
                continue
            k=(row["session_ist"],row["timestamp_utc"],row["side"],row["strike"])
            if k in conflicts:
                continue
            old=prices.get(k)
            if old and (any(abs(old[x]-row[x])>.011 for x in ("open","high","low","close")) or old["volume"]!=row["volume"]):
                conflicts.add(k)
                prices.pop(k,None)
            else:
                prices[k]=row
    days=defaultdict(lambda:defaultdict(dict))
    for (day,stamp,side,strike),row in prices.items():
        days[day][stamp,side][strike]=row
    return days,len(conflicts),rejected


def _spot(day,bars):
    opening=datetime.combine(date.fromisoformat(day),time(9,15),exp.IST)
    return [{"timestamp_utc":(opening+timedelta(minutes=i)).astimezone(timezone.utc).isoformat(),
             "session_ist":day,"open":v[0],"high":v[1],"low":v[2],"close":v[3]}
            for i,v in sorted(bars.items())]


def _events(rows,rule):
    if rule=="EMA_CROSSOVER":
        return exp._signals(rows,signal_model="ema_crossover")
    signals=depth_replay.rule_signals(rows,rule,9,21,30,.2 if rule=="RANGE_REVERSION" else 1.5)
    return [{"bar_utc":r["timestamp_utc"],"session_ist":r["session_ist"],
             "direction":signal if signal in ("UP","DOWN") else "NO_TRADE","underlying_close":r["close"]}
            for r,signal in zip(rows,signals)]


def _daily(rows,candles,events,cfg,settings):
    result=exp.simulate_options(events,rows,candles,policy="fixed",
        hold=cfg["hold_minutes"],target_points=cfg["target_points"],stop_points=cfg["stop_points"],
        target_ltp=settings["target_premium"],tolerance=settings["tolerance"],
        lot_size=settings["lot_size"],lots=cfg["lots"],starting_capital=settings["capital"],
        slippage_bps=settings["slippage_bps"],fee_mode="zerodha",retain_all_trades=True)
    trades=result["trades"]
    pnls=[t["net_pnl_inr"] for t in trades]
    unscored=result["unscored"]
    incomplete=bool(MISSING.intersection(k for k,v in unscored.items() if v))
    return {"complete":not incomplete,"net":result["net_pnl_inr"] if not incomplete else None,
            "resolved_net":result["net_pnl_inr"],"trades":len(trades),
            "wins":sum(x>0 for x in pnls),"losses":sum(x<0 for x in pnls),
            "positive":sum(x for x in pnls if x>0),"negative":-sum(x for x in pnls if x<0),
            "fees":result["total_assumed_fees_inr"],"drawdown_pct":result["max_closed_trade_drawdown_pct"],
            "unscored":unscored}


def _summary(items):
    scored=[r for r in items if r["complete"]]
    total=sum(r["trades"] for r in scored)
    net=sum(r["net"] for r in scored)
    losses=sum(r["negative"] for r in scored)
    return {"sessions":len(scored),"censored_sessions":len(items)-len(scored),
            "trades":total,"net_inr":round(net,2) if scored else None,
            "mean_net_per_day":net/len(scored) if scored else None,
            "mean_net_per_trade":net/total if total else None,
            "win_pct":100*sum(r["wins"] for r in scored)/total if total else None,
            "profit_factor":sum(r["positive"] for r in scored)/losses if losses>0 else None,
            "fees_inr":round(sum(r["fees"] for r in scored),2) if scored else None,
            "max_daily_drawdown_pct":max((r["drawdown_pct"] for r in scored),default=None),
            "stress_extra_25_inr":round(net-25*total,2) if scored else None,
            "no_near_target":sum(r["unscored"].get("no_option_near_target_at_signal",0) for r in scored)}


def _matched(records,configs):
    return sorted(set.intersection(*(set(d for d,r in records[c["id"]].items() if r["complete"]) for c in configs))) if configs else []


def _winner(configs,records,matched):
    # Selection uses development only; no evidence claim for tiny samples.
    if len(matched)<15:
        return None
    eligible=[]
    for c in configs:
        s=_summary([records[c["id"]][d] for d in matched])
        if s["trades"]>=30:
            eligible.append((s["mean_net_per_day"],c["id"],c))
    return max(eligible,key=lambda x:(x[0],x[1]))[-1] if eligible else None


def run(*,start_date,end_date,capital=17000.,max_lots=3,compare_lots=False,lot_size=30,
        target_premium=180.,tolerance=60.,wings=3,slippage_bps=5.,progress=None,today=None,save=True):
    today=today or exp._ist_today()
    a,b=_scope(start_date,end_date,today)
    if type(max_lots) is not int or not 1<=max_lots<=3 or type(lot_size) is not int or not 1<=lot_size<=100 or type(wings) is not int or not 0<=wings<=5:
        raise ValueError("Choose 1–3 lots, assumed lot size 1–100, and ATM wings 0–5")
    for v,lo,hi in ((capital,1000,1e7),(target_premium,10,20000),(tolerance,0,5000),(slippage_bps,0,500)):
        if not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError("Invalid research capital, premium or cost settings")
    if not LOCK.acquire(blocking=False):
        raise ValueError("A year scalping study is already running")
    try:
        settings=dict(capital=capital,max_lots=max_lots,compare_lots=compare_lots,lot_size=lot_size,
                      target_premium=target_premium,tolerance=tolerance,wings=wings,slippage_bps=slippage_bps,
                      fee_mode="zerodha",fee_version=fees.FEE_VERSION)
        configs=candidates(max_lots,compare_lots)
        if progress: progress(1,"Verifying saved index receipts")
        history=market_patterns._history("INDEX:BANKNIFTY",today)
        if progress: progress(3,"Cataloging saved option receipts")
        catalog,rejected=_catalog(a,b,wings)
        days=[a+timedelta(days=i) for i in range((b-a).days+1) if (a+timedelta(days=i)).weekday()<5]
        cut1=int(.6*len(days))
        cut2=int(.8*len(days))
        dev=defaultdict(dict)
        val=defaultdict(dict)
        test={}
        selected=None
        picked=False
        coverage=[]
        conflicts=0
        idx=0
        for lo,hi in exp._chunks(a,b+timedelta(days=1)):
            block,conflict,bad=_block(catalog,lo,hi)
            conflicts+=conflict
            rejected+=bad
            for d in (d for d in days if lo<=d<hi):
                cohort="development" if idx<cut1 else "validation" if idx<cut2 else "test"
                idx+=1
                if cohort=="test" and not picked:
                    selected=_winner(configs,dev,_matched(dev,configs))
                    picked=True
                if progress: progress(5+92*idx/max(1,len(days)),f"{cohort}: {d.isoformat()} ({idx}/{len(days)} weekdays)")
                day=d.isoformat()
                bars=history["complete"].get(day)
                candles=block.get(day,{})
                counts={side:sum(any(r["volume"] is not None and r["volume"]>0 for r in choices.values()) for (_,s),choices in candles.items() if s==side) for side in ("CALL","PUT")}
                record={"date":day,"cohort":cohort,"index_minutes":len(history["days"].get(day,{})),
                        "ce_minutes":counts["CALL"],"pe_minutes":counts["PUT"],"state":"eligible"}
                coverage.append(record)
                if bars is None:
                    record["state"]="missing_or_partial_index"
                elif not exp._expired_eligible(d,expiry_flag="MONTH",expiry_code=0,today=today):
                    record["state"]="potentially_active_expiry"
                elif min(counts.values())<MIN_COVERAGE:
                    record["state"]="insufficient_option_minutes"
                if record["state"]!="eligible":
                    continue
                rows=_spot(day,bars)
                active=configs if cohort!="test" else [selected] if selected else []
                events={rule:_events(rows,rule) for rule in set(c["rule"] for c in active)}
                for c in active:
                    v=_daily(rows,candles,events[c["rule"]],c,settings)
                    if cohort=="development": dev[c["id"]][day]=v
                    elif cohort=="validation": val[c["id"]][day]=v
                    else: test[day]=v
        matched_dev=_matched(dev,configs)
        matched_val=_matched(val,configs)
        if not picked:
            selected=_winner(configs,dev,matched_dev)
        comparison=[]
        for c in configs:
            # Common dates only for parameter ranking/comparison; independent
            # coverage counts still visible to avoid hiding missing evidence.
            comparison.append({**c,"development":_summary([dev[c["id"]][d] for d in matched_dev]),
                "validation":_summary([val[c["id"]][d] for d in matched_val]),
                "development_eligible_days":len(dev[c["id"]]),
                "development_censored_days":sum(not r["complete"] for r in dev[c["id"]].values()),
                "validation_censored_days":sum(not r["complete"] for r in val[c["id"]].values())})
        comparison.sort(key=lambda c:(c["development"]["mean_net_per_day"] is None,-(c["development"]["mean_net_per_day"] or 0),c["id"]))
        test_summary=_summary(list(test.values()))
        result={"version":VERSION,"start_date":start_date,"end_date":end_date,"settings":settings,
                "state":"conditional_research" if selected and test_summary["sessions"] else "insufficient_heldout_evidence",
                "requested_weekdays":len(days),"coverage":coverage,"coverage_states":dict(Counter(r["state"] for r in coverage)),
                "verified_option_receipts":len(catalog),"rejected_receipt_reads":rejected,"excluded_conflicts":conflicts,
                "candidate_count":len(configs),"development_matched_days":len(matched_dev),"validation_matched_days":len(matched_val),
                "comparison":comparison,"selected":selected,"test":test_summary,
                "selected_test_days":[{"date":d,**r} for d,r in sorted(test.items())],
                "read_only":True,"orders_enabled":False,
                "warning":"Minute OHLC next-open proxy, not executable quotes. Rolling near-monthly expiry and strike/side are not immutable contract IDs; historical lot size is assumed. Current Zerodha tariff counterfactual; adverse slippage per side, no actual historical spreads. Each day starts with the same independent capital; totals are not compounded account returns. Weekdays are not an exchange calendar. At least 338 valid-volume minute slots on each side; unavailable near-target candidates are skipped and reported; unresolved entry/exit paths censor the day. Development and validation use common complete dates across configurations; this can introduce coverage selection bias. Fixed chronological 60/20/20 date split, development-only selection requiring 15 common sessions and 30 trades. Test is only for that selected configuration, not proof of profitability; repeated studies reuse historical test data. No sub-minute or passive fill simulation."}
        if save:
            root=Path(service.DATA)/"trading_cockpit"/"scalping_studies"
            root.mkdir(parents=True,exist_ok=True)
            sid="year_"+uuid.uuid4().hex[:20]
            result["study_id"]=sid
            temp=root/(sid+".tmp")
            try:
                temp.write_text(json.dumps(result,allow_nan=False,separators=(",",":")),encoding="utf-8")
                os.replace(temp,root/(sid+".json"))
            finally:
                temp.unlink(missing_ok=True)
        if progress: progress(100,"Saved chronological scalping grid report")
        return result
    finally:
        LOCK.release()


def latest():
    root=Path(service.DATA)/"trading_cockpit"/"scalping_studies"
    if not root.is_dir() or root.is_symlink():
        return {"study":None}
    paths=[p for p in root.glob("year_*.json") if re.fullmatch(r"year_[0-9a-f]{20}\.json",p.name) and p.is_file() and not p.is_symlink()]
    if not paths:
        return {"study":None}
    p=max(paths,key=lambda p:p.stat().st_mtime_ns)
    if p.stat().st_size>10_000_000:
        raise ValueError("Saved study exceeds report size limit")
    r=json.loads(p.read_text(encoding="utf-8"))
    if r.get("version")!=VERSION or r.get("study_id")!=p.stem:
        raise ValueError("Saved study identity mismatch")
    return {"study":r}
