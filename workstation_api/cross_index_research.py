"""Matched-clock, read-only cross-index forecast research.

Index price forecasts are not option P&L. Peer features use completed bars
only; labels use the target's later bars. No provider calls, trades or
automatic strategy selection.
"""
from datetime import date
from . import cpr_regime_research as g, candle_barrier_research as b

TASKS=g.TASKS+(("terminal_direction",("down","flat","up")),)
HORIZONS=(5,15,30)


def _describe(series,day,minute,ordered):
    if day not in series:
        return None
    prior=[d for d in ordered if d<day][-20:]
    return g.describe(series,day,minute,prior)


def _rows(target,peer,splits,horizon):
    target_days=sorted(target)
    peer_days=sorted(peer)
    parts=[];matched=[];coverage={}
    for name,ds in zip(("train","validation","holdout"),splits):
        rows=[];paired=[]
        reserved=0
        for day in ds:
            for minute in range(34,375-horizon,horizon):
                reserved+=1
                desc=_describe(target,day,minute,target_days)
                if desc is None:
                    continue
                outcome=g.outcome(target[day],minute,horizon,desc)
                if outcome is None:
                    continue
                ret=outcome["future_return_bps"]
                labels=outcome["labels"]+[0 if ret<0 else 2 if ret>0 else 1]
                row={"session":day,"minute":minute,**desc,**outcome,"labels":labels}
                rows.append(row)
                other=_describe(peer,day,minute,peer_days)
                if other is not None:
                    paired.append({**row,"peer_features":other["regime_features"]+other["short"]})
        parts.append(rows);matched.append(paired)
        coverage[name]={"reserved":reserved,"target_scored":len(rows),"matched_scored":len(paired),
                        "matched_days":len({r["session"] for r in paired})}
    return parts,matched,coverage


def assess(series,splits,*,progress=None):
    """Two directions on identical chronological session reservations."""
    if len(series)!=2 or len(splits)!=3 or any(not part for part in splits):
        raise ValueError("Select two different original indices and three nonempty splits")
    days=[d for part in splits for d in part]
    if days!=sorted(set(days)):
        raise ValueError("Unique chronological splits required")
    if any(date.fromisoformat(d).weekday()>=5 for d in days):
        raise ValueError("Expected regular weekday sessions")
    if any(d not in s for d in days for s in series.values()):
        raise ValueError("Reserved dates must be present in both source indices")
    report={"version":"cross_index_forecast_v1","targets":{},
            "training_dates":splits[0],"validation_dates":splits[1],"holdout_dates":splits[2],
            "warning":"Exploratory probability forecasts, not causal lead-lag, option fills or profitability. Same historical dates in both directions; no future peer bars, synthetic prices or holdout tuning."}
    names=list(series)
    for i,name in enumerate(names):
        peer=names[1-i]
        out={"peer":peer,"horizons":{}}
        for j,hor in enumerate(HORIZONS):
            if progress:progress(5+int(90*(i*len(HORIZONS)+j)/(2*len(HORIZONS))),f"{name} with {peer}: {hor}-minute forecasts")
            parts,matched,coverage=_rows(series[name],series[peer],splits,hor)
            base=g._fit(matched,tasks=TASKS)
            aug=g._fit(matched,extra_key="peer_features",tasks=TASKS)
            changes={}
            for task in sorted(base["tasks"].keys() & aug["tasks"].keys()):
                a=aug["tasks"][task];z=base["tasks"][task]
                changes[task]=b._paired(a["holdout"][a["selected_on_validation"]],z["holdout"][z["selected_on_validation"]])
            out["horizons"][str(hor)]={"coverage":coverage,"target_only":g._fit(parts,tasks=TASKS),
                                       "matched_baseline":base,"matched_augmented":aug,"comparisons":changes}
        report["targets"][name]=out
    if progress:progress(100,"Cross-index forecasts complete")
    return report
