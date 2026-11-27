"""Read-only rolling-option execution evidence and development horizon screen.

No provider calls, historical quote fabrication, strategy approval or use
of previously inspected later dates for economic model selection.
"""
from collections import Counter, defaultdict
from datetime import date,datetime,timedelta,timezone
from . import cpr_hybrid_research as r, historical_alpha as h
from . import predictive_option_research as p, expired_options_backtest as exp
from . import alpha_retraining, cpr_direct_utility as utility

VERSION="option_evidence_horizon_v1"
HOLDS=(5,15,30,60,0)
COSTS=(35.,75.)
WINGS=5
LOT=30
CAPITAL=17000.
BUDGET=12000.


def window_status(evidence,day,side,today):
    expected=set(evidence["expected_offsets"])
    seen=evidence["checked_offsets"].get((day,side),set())
    eligible=exp._expired_eligible(date.fromisoformat(day),expiry_flag="MONTH",expiry_code=0,today=today)
    missing=sorted(expected-seen)
    return {"state":"checked" if not missing else "missing_request_windows" if eligible else "not_yet_expired",
            "checked_offsets":len(expected&seen),"missing_offsets":missing,"expired_eligible":eligible}


def quote_status(table,evidence,day,minute,side,strike):
    stamp=r._stamp(day,minute)
    rows=table.get(stamp,{})
    if (stamp,side,strike) in evidence["conflicts"]:
        return "conflicting_original_bars"
    row=rows.get((side,strike))
    if row is not None:
        if r._observed(table,day,minute,side,strike) is not None:
            return "observed_positive_volume"
        if row.get("session_ist")!=day or row.get("expiry_flag")!="MONTH" or row.get("expiry_code")!=1:
            return "identity_mismatch"
        volume=row.get("volume")
        if volume is None:
            return "volume_unavailable"
        if volume==0:
            return "zero_volume"
        return "invalid_observation"
    same=[k for s,k in rows if s==side]
    if not same:
        return "no_side_bars_at_minute"
    if strike<min(same) or strike>max(same):
        return "outside_observed_strike_range"
    return "strike_absent_inside_observed_range"


def observed_coverage(table,day,side):
    counts=Counter()
    for minute in range(375):
        rows=table.get(r._stamp(day,minute),{})
        same=[(k,v) for (s,k),v in rows.items() if s==side]
        if not same:
            counts["minutes_no_side_bars"]+=1
            continue
        counts["minutes_with_any_side_bar"]+=1
        usable=0
        for strike,row in same:
            if r._observed(table,day,minute,side,strike) is not None:
                usable+=1;counts["positive_volume_strike_bars"]+=1
            elif row.get("volume") is None:
                counts["unknown_volume_strike_bars"]+=1
            elif row.get("volume")==0:
                counts["zero_volume_strike_bars"]+=1
            else:
                counts["other_unusable_strike_bars"]+=1
        if usable:
            counts["minutes_with_positive_volume"]+=1
    return dict(counts)


def _minute(day,stamp):
    t=datetime.fromisoformat(stamp).astimezone(h.IST)
    if t.date().isoformat()!=day:
        raise ValueError("Exit evidence clock outside session")
    return t.hour*60+t.minute-555


def events(ep,result,table,evidence,index,today):
    """Audit requested entry, actual triggering monitoring gap and chosen exit.
    A future counterfactual quote not used by this policy is not a failure.
    """
    day=ep["session"];side=ep["side"];strike=ep.get("strike")
    if strike is None:
        return []
    out=[]
    def add(kind,minute):
        status=quote_status(table,evidence,day,minute,side,strike)
        out.append({"session":day,"decision_minute":ep["minute"],"side":side,"strike":strike,
                    "event":kind,"minute":minute,"quote_state":status,
                    "window_state":window_status(evidence,day,side,today)["state"],
                    "index_bar_present":minute in index[day]})
    if result["state"]=="missing_entry":
        add("missing_entry",ep["minute"]+2)
    if (result.get("reason")=="monitoring_gap_exit" or result.get("trigger")=="monitoring_gap_exit") and "path_gap_minute" in ep:
        add("monitoring_gap",ep["path_gap_minute"])
    if (result["state"]=="exit_censored" or result.get("exit_delay_minutes",0)>0) and result.get("exit_request_utc"):
        add("missing_requested_exit",_minute(day,result["exit_request_utc"]))
    return out


def _state_without_candidate(s,diag):
    state=("missing_signal_quotes" if not diag["observed_side_quotes"]
           else "no_qualified_observed_contract" if not diag["qualified_contracts"]
           else "no_affordable_observed_contract")
    return {**s,**diag,"state":state}


def _matched_candidates(s,table):
    # Select using only signal-time prices and the adverse cost lane.
    # Identical strike and units in each cost comparison. No substitution
    # after observing entry or exit data.
    high,diag=r._candidate_pool(s,table,lot_size=LOT,max_lots=1,bps=COSTS[1])
    allowed=[x for x in high if x[4]<=BUDGET]
    if not allowed:
        return None,diag
    candidate=allowed[0]
    base=(*candidate[:4],r._fund(candidate[5],candidate[3],COSTS[0]),candidate[5])
    return (base,candidate),diag


def _screen(signals,index,table,dates):
    # All horizons share the identical signal clock, before the last
    # possible 60-minute holding opportunity. This restricts even EOD.
    eligible=[s for s in signals if s["minute"]+2+60<=r.SQUAREOFF_MINUTE]
    chosen=[(s,*_matched_candidates(s,table)) for s in eligible]
    report={"shared_opportunities":len(eligible),"excluded_late_opportunities":len(signals)-len(eligible),
            "cost_penalty_bps_per_side":COSTS,"holds_minutes":HOLDS,"lanes":{}}
    for hold in HOLDS:
        lanes={}
        for ci,bps in enumerate(COSTS):
            eps=[]
            for s,candidates,diag in chosen:
                if candidates is None:
                    eps.append(_state_without_candidate(s,diag));continue
                signal={**s,"target_utc":r._stamp(s["session"],s["minute"]+2+hold if hold else r.SQUAREOFF_MINUTE)}
                ep=r._episode(signal,table,index[s["session"]],hold=hold,lot_size=LOT,max_lots=1,
                              risk_budget=BUDGET,bps=bps,candidate=candidates[ci])
                eps.append({**ep,**diag})
            result,_=r._evaluate(eps,method="fixed_stop",capital=CAPITAL,risk_budget=BUDGET,
                                  strict_execution=True,dates=dates)
            lanes[str(int(bps))]=result
        report["lanes"][str(hold)]=lanes
    return report


def assess(index,splits,signals,table,evidence,*,today,progress=None):
    days=[d for part in splits for d in part]
    if not days or days!=sorted(set(days)):
        raise ValueError("Unique chronological sessions required")
    part_for={d:name for name,part in zip(("train","validation","recent_audit_only"),splits) for d in part}
    windows={d:{s:{**window_status(evidence,d,s,today),**observed_coverage(table,d,s)} for s in ("CALL","PUT")} for d in days}
    observed=Counter()
    for sides in windows.values():
        for value in sides.values():
            observed.update({k:v for k,v in value.items() if k.startswith("minutes_") or k.endswith("_strike_bars")})
    report={"version":VERSION,"settings":{"capital_inr":CAPITAL,"budget_inr":BUDGET,"assumed_lot":LOT,"wings":(len(evidence["expected_offsets"])-1)//2,
            "hold_minutes":HOLDS,"cost_bps_per_side":COSTS},
            "request_windows":windows,"repairable_missing_offset_session_pairs":sum(
                len(v["missing_offsets"]) for sides in windows.values() for v in sides.values() if v["expired_eligible"]),
            "window_state_counts":dict(Counter(v["state"] for sides in windows.values() for v in sides.values())),
            "observed_quote_coverage":dict(observed),
            "parts":{},"warning":"Checked requests do not certify continuous prices. Absent strikes outside the observed range may be rolling-window limitations, not proof. Positive volume is not executable liquidity. Recent dates audited for data quality only; no new return selection on those dates."}
    if progress:progress(55,"Tracing fixed-strike entry and chosen-exit evidence")
    for name,ds in zip(("train","validation","recent_audit_only"),splits):
        ds_set=set(ds)
        rows=[s for s in signals if s["session"] in ds_set]
        # Match the earlier dense candidate research population in training;
        # audit validation and recent account-nearest paths separately.
        probes=r._dense_anchors(rows) if name=="train" else rows
        counts=Counter();failures=Counter();event_list=[];by_day=defaultdict(Counter)
        funding=Counter();paths=0
        for s in probes:
            pool,diag=r._candidate_pool(s,table,lot_size=LOT,max_lots=1,bps=COSTS[0])
            if not pool:
                funding["no_qualified_or_observed_contract"]+=1
            elif not any(c[4]<=BUDGET for c in pool):
                funding["not_affordable_at_signal"]+=1
            else:
                funding["affordable_at_signal"]+=1
            candidates=pool[:r.MAX_LEARNING_STRIKES] if name=="train" else [c for c in pool if c[4]<=BUDGET][:1]
            for candidate in candidates:
                paths+=1
                ep=r._episode(s,table,index[s["session"]],hold=0,lot_size=LOT,max_lots=1,
                              risk_budget=BUDGET,bps=COSTS[0],candidate=candidate,learning=name=="train")
                result=r._exit(ep,"fixed_stop")
                counts[result["state"]]+=1
                quality=utility.target(r,ep)
                if not quality["timely"]:
                    failures[quality["failure_reason"]]+=1
                for event in events(ep,result,table,evidence,index,today):
                    key=event["event"]+"|"+event["quote_state"]+"|"+event["window_state"]
                    by_day[s["session"]][key]+=1
                    event_list.append(event)
        report["parts"][name]={"dates":ds,"signals":len(rows),"probed_anchors":len(probes),"candidate_paths":paths,
            "funding":dict(funding),"outcome_states":dict(counts),"quality_failures":dict(failures),
            "failure_events":dict(Counter(e["event"]+"|"+e["quote_state"]+"|"+e["window_state"] for e in event_list)),
            "by_session":{d:dict(c) for d,c in sorted(by_day.items())},"events":event_list}
    report["development_screen"]={}
    for i,(name,ds) in enumerate(zip(("train","validation"),splits[:2])):
        if progress:progress(70+15*i,"Screening matched fixed holding periods on "+name)
        report["development_screen"][name]=_screen([s for s in signals if part_for[s["session"]]==name],index,table,ds)
    # This is a descriptive development screen, not a newly frozen or
    # promoted policy. Require positive earlier stress utility and the
    # prior strict development gate at BOTH predetermined cost levels.
    passed=[]
    for hold in HOLDS:
        tr=report["development_screen"]["train"]["lanes"][str(hold)]
        va=report["development_screen"]["validation"]["lanes"][str(hold)]
        if all(tr[c]["stress_utility_inr"]>0 and tr[c]["stress_failed_attempts"]==0 and utility._gate(va[c]) for c in tr):
            passed.append(hold)
    report["development_qualified_holds_minutes"]=passed
    report["live_model_promoted"]=False
    report["forward_policy_frozen"]=False
    if progress:progress(100,"Execution evidence and development horizon screen complete")
    return report


def run(*,sessions=90,to_date=None,wings=WINGS,progress=None,now=None,manual_saved_research=False):
    now=now or datetime.now(timezone.utc)
    today=now.astimezone(h.IST).date()
    if not manual_saved_research and not alpha_retraining.safe_window(now):
        raise ValueError("Run outside Indian market priority hours")
    stop=date.fromisoformat(to_date) if to_date else today
    if type(wings) is not int or not 0<=wings<=10:
        raise ValueError("Audit supports up to ten near-expiry strike wings")
    if sessions not in r.SESSION_SPLITS or stop>today:
        raise ValueError("Use 60/90/120 completed observed sessions")
    start=stop-timedelta(days={60:100,90:150,120:200}[sessions])
    if progress:progress(1,"Verifying BANKNIFTY original index receipts")
    index,hashes,failures=h.shared_index_sources(start-timedelta(days=7),stop,[h.MAX_TOTAL])
    ordered=sorted(index)
    dates=[d for d in ordered if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-sessions:]
    if len(dates)!=sessions:
        raise ValueError(f"Need {sessions} observed sessions; have {len(dates)}. No silent smaller study.")
    ntrain,nval,_=r.SESSION_SPLITS[sessions]
    splits=[dates[:ntrain],dates[ntrain:ntrain+nval],dates[ntrain+nval:]]
    signals=[];day_states={}
    for d in dates:
        i=ordered.index(d)
        if i==0:
            day_states[d]="prior_session_missing";continue
        prior=ordered[i-1]
        rows,state=r._signals(d,index[d],prior,index[prior],frame=5,hold=0,max_signals=375,entry_mode="regime_scan")
        signals.extend(rows);day_states[d]=state
    if not signals:
        raise ValueError("No eligible scanner opportunities")
    # Request all session clocks in the observed date scope so the receipt
    # audit is not restricted to days with profitable signals.
    clock={r._stamp(d,m) for d in dates for m in range(375)}
    evidence={}
    table,meta=p._load_options(signals,wings,progress,needed_stamps=clock,evidence=evidence,evidence_days=dates)
    report=assess(index,splits,signals,table,evidence,today=today,progress=progress)
    report.update(index_sources=hashes,index_failures=failures,day_states=day_states,option_sources=meta,
                  requested_sessions=sessions,training_dates=splits[0],validation_dates=splits[1],recent_audit_dates=splits[2])
    return report
