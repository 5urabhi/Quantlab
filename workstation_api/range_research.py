"""Fixed, causal range regime and mean-reversion research.

Price-close efficiency is a descriptive heuristic, not a calibrated forecast.
No implied option returns, synthetic quotes or assumed execution.
"""
from math import isfinite
from statistics import mean, median

LOOKBACK = 30
SIDEWAYS_ER = .30
TREND_ER = .65
EDGE = .20
MIN_RANGE_PCT = .10


def regime(closes):
    if len(closes) < LOOKBACK+1:
        return {"state":"insufficient_contiguous_bars","efficiency":None,
                "low":None,"high":None,"range_pct":None,"location_pct":None}
    x = closes[-LOOKBACK-1:]
    if not all(isfinite(v) and v > 0 for v in x):
        raise ValueError("Invalid observed close")
    path = sum(abs(b-a) for a,b in zip(x,x[1:]))
    net = x[-1]-x[0]
    lo,hi=min(x),max(x)
    width=100*(hi-lo)/x[0]
    er=abs(net)/path if path else 0.
    state=("compressed" if width<MIN_RANGE_PCT else
           "range_bound" if er<=SIDEWAYS_ER else
           "trend_up" if er>=TREND_ER and net>0 else
           "trend_down" if er>=TREND_ER and net<0 else "mixed")
    return {"state":state,"efficiency":er,"low":lo,"high":hi,
            "range_pct":width,"location_pct":100*(x[-1]-lo)/(hi-lo) if hi>lo else None}


def reversion_signal(previous, current, edge=EDGE):
    """Only range-bound preceding 30 completed close changes.

    A lower/upper-band observation followed by an inward move is a
    research trigger; breaks beyond the prior boundary are not faded.
    """
    if not 0 < edge <= .49:
        raise ValueError("Range edge fraction must be >0 and <=0.49")
    r=regime(previous)
    if r["state"]!="range_bound":
        return "HOLD"
    lo,hi=r["low"],r["high"]
    width=hi-lo
    last=previous[-1]
    if lo<=last<=lo+edge*width and last<current<=lo+width*.5:
        return "UP"
    if hi-edge*width<=last<=hi and hi-width*.5<=current<last:
        return "DOWN"
    return "HOLD"


def current_regime(bars):
    if not bars:
        return regime([])
    end=max(bars)
    keys=range(end-LOOKBACK,end+1)
    return regime([bars[k][3] for k in keys]) if all(k in bars for k in keys) else regime([])


def historical(complete):
    dates=sorted(complete)
    cut=int(.7*len(dates))
    if cut<20 or len(dates)-cut<5:
        return {"state":"insufficient_sessions","development_sessions":cut,
                "evaluation_sessions":len(dates)-cut,"rows":[]}
    rows=[]
    for cohort,sample in (("development",dates[:cut]),("evaluation",dates[cut:])):
        for hold in (1,3,5,10,15):
            trades=[]
            counts=[]
            for d in sample:
                bars=complete[d]
                closes=[bars[i][3] for i in range(375)]
                next_allowed=LOOKBACK+1
                count=0
                for i in range(LOOKBACK+1,375-hold):
                    if i<next_allowed:
                        continue
                    side=reversion_signal(closes[i-LOOKBACK-1:i],closes[i])
                    if side=="HOLD":
                        continue
                    entry=bars[i+1][0]
                    future=[bars[j] for j in range(i+1,i+hold+1)]
                    last=future[-1][3]
                    hi=max(b[1] for b in future)
                    lo=min(b[2] for b in future)
                    sign=1 if side=="UP" else -1
                    trades.append((sign*(last-entry),
                                   max(0,hi-entry if sign>0 else entry-lo),
                                   max(0,entry-lo if sign>0 else hi-entry)))
                    next_allowed=i+hold+1
                    count+=1
                counts.append(count)
            n=len(trades)
            rows.append({"cohort":cohort,"hold_minutes":hold,"sessions":len(sample),
                         "signals":n,"mean_signals_per_session":mean(counts),
                         "positive_pct":100*sum(t[0]>0 for t in trades)/n if n else None,
                         "mean_signed_points":mean(t[0] for t in trades) if n else None,
                         "median_mfe":median(t[1] for t in trades) if n else None,
                         "median_mae":median(t[2] for t in trades) if n else None})
    return {"state":"descriptive","development_sessions":cut,
            "evaluation_sessions":len(dates)-cut,"evaluation_from":dates[cut],"rows":rows}
