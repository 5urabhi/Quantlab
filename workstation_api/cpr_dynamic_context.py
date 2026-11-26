"""Five-minute retrospective context updates for an offline Q ablation.

Every snapshot uses the completed index candle, neutral fixed-bank context
and as-of global observations. Missing snapshots do not forward fill beyond
the current five-minute interval. Not a live policy or an order service.
"""
from collections import Counter,defaultdict
from . import cpr_context_features as cx


def snapshots(index,dates,stamp,*,mode,batch_id):
    anchors=[]
    for day in dates:
        bars=index[day]
        for minute in range(19,365,5):
            if any(k not in bars for k in range(minute-5,minute+1)):
                continue
            previous=bars[minute-5][3];current=bars[minute][3]
            if min(previous,current)<=0:
                continue
            anchors.append({"session":day,"minute":minute,"side":"CALL",
                            "decision_utc":stamp(day,minute+1),
                            "index_return_5m_bps":10000*(current/previous-1)})
    audit=cx.attach(anchors,mode=mode,batch_id=batch_id,fixed_panel=True)
    states=defaultdict(dict);counts=Counter()
    for s in anchors:
        context=cx.context_state(s,"panel_global")
        if context is None:
            counts["missing_context"]+=1
            continue
        move=s["index_return_5m_bps"]
        state=1 if context==1 and move>1 else -1 if context==-1 and move<-1 else 0
        states[s["session"]][s["minute"]]=state
        counts["available"]+=1
    return dict(states),{"clock_minutes":5,"snapshot_counts":dict(counts),
                         "available_by_session":{d:len(states.get(d,{})) for d in dates},
                         "source_audit":{k:v for k,v in audit.items() if k!="anchors"},
                         "warning":"Retrospective index and fixed-panel bars, reviewed archive or actual global receipts. Missing snapshots use fixed exit rules."}


def state_at(signal,minute):
    # minute is a completed one-minute bar, so this five-minute anchor
    # closes no later than the current observed decision.
    anchor=minute-(minute+1)%5
    state=signal.get("_dynamic_states",{}).get(anchor)
    if state is None:
        return None
    return state if signal["side"]=="CALL" else -state
