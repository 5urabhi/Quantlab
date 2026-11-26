"""Paired near-monthly debit spread paper comparator on saved rolling bars.

Same-minute two-leg prices are not synchronized executable quotes, exact
contracts or proof of broker margin. Net-debit financing is explicitly
counterfactual; gross-long funding is a stricter proxy, not margin proof.
"""
from collections import Counter

from . import predictive_option_research as p


def _prices(r,table,signal,minute,long,short,field):
    side,day=signal["side"],signal["session"]
    a=r._observed(table,day,minute,side,long)
    b=r._observed(table,day,minute,side,short)
    if a is None or b is None:
        return None
    prices=[a[field],b[field]]
    if not 0<=prices[0]-prices[1]<=abs(short-long):
        return None
    return prices


def _funding(prices,units,bps,lane):
    gross=p._funding(prices,units,bps,"zerodha")
    buy,sell=p._cash(prices,units,bps,entry=True)
    debit=buy-sell
    _,fees=p._net(prices,prices,units,bps,"zerodha")
    return (gross if lane=="gross_funding" else debit+fees),gross,debit


def _candidates(r,signal,table,units,bps,lane):
    spot=signal["spot"];side=signal["side"];m=signal["minute"]
    # Fixed decision-time range and deterministic ordering. No later fill
    # availability, realized outcome or best future strike enters ranking.
    strikes=sorted(k for (s,k),v in table.get(r._stamp(signal["session"],m),{}).items()
                   if s==side and abs(k/spot-1)<=.015 and r._observed(table,signal["session"],m,side,k))
    out=[]
    for long in strikes:
        for short in strikes:
            width=abs(short-long)
            if not 0<width<=.01*spot or (side=="CALL" and long>=short) or (side=="PUT" and long<=short):
                continue
            prices=_prices(r,table,signal,m,long,short,"close")
            if prices is None or prices[0]-prices[1]<5:
                continue
            funding,gross,debit=_funding(prices,units,bps,lane)
            if not 0<debit<width*units or funding<=0:
                continue
            out.append((abs(long-spot),funding,width,long,short,gross,debit))
    return strikes,sorted(out)


def episode(r,signal,table,index,*,hold,lot_size,bps,risk_budget,lane):
    strikes,pool=_candidates(r,signal,table,lot_size,bps,lane)
    diagnostics={"observed_side_quotes":len(strikes),"qualified_contracts":len(pool),
                 "minimum_funding_inr":min((x[1] for x in pool),default=None),
                 "structure":"bull_call_debit" if signal["side"]=="CALL" else "bear_put_debit",
                 "spread_funding_lane":lane}
    allowed=[x for x in pool if x[1]<=risk_budget]
    if not allowed:
        state=("missing_signal_quotes" if not strikes else "no_qualified_observed_contract"
               if not pool else "no_affordable_observed_contract")
        return {**signal,**diagnostics,"state":state}
    _,planned,width,long,short,gross,debit=allowed[0]
    ep={**signal,**diagnostics,"strike":long,"short_strike":short,"spread_width":width,
        "planned_funding":planned,"planned_gross_funding":gross,"planned_net_debit":debit,
        "units":lot_size,"lots":1,"state":"missing_entry","path":[]}
    day=signal["session"];first=signal["minute"]+2
    initial=_prices(r,table,signal,first,long,short,"open")
    if initial is None:
        return ep
    funding,gross,debit=_funding(initial,lot_size,bps,lane)
    if not 0<debit<width*lot_size or funding>risk_budget:
        return {**ep,"state":"entry_limit_exceeded","observed_funding":funding}
    ep.update(state="entered",entry=initial,debit=debit,funding=funding,
              observed_gross_funding=gross)
    deadline=min(first+hold,r.SQUAREOFF_MINUTE) if hold else r.SQUAREOFF_MINUTE
    ep["scheduled_exit_utc"]=r._stamp(day,deadline);ep["squareoff_utc"]=r._stamp(day,r.SQUAREOFF_MINUTE)
    def fill(minute):
        prices=_prices(r,table,signal,minute,long,short,"open")
        if prices is None:
            return None
        net,fees=p._net(initial,prices,lot_size,bps,"zerodha")
        return {"exit_net":net,"exit_fees":fees,"exit_utc":r._stamp(day,minute)}
    def recovery(earliest):
        for minute in range(earliest,r.LAST_SESSION_MINUTE+1):
            result=fill(minute)
            if result is not None:
                return {**result,"exit_delay_minutes":minute-earliest}
        return None
    peak=None
    for j in range(first,deadline-1):
        prices=_prices(r,table,signal,j,long,short,"close")
        if prices is None or j not in index:
            ep["path_gap_minute"]=j
            ep["gap_exit_request_utc"]=r._stamp(day,j+2)
            ep["gap_recovery"]=recovery(j+2)
            break
        net,_=p._net(initial,prices,lot_size,bps,"zerodha")
        mark=net/debit;peak=mark if peak is None else max(peak,mark)
        result=fill(j+2)
        retry=recovery(j+3) if result is None else None
        if retry is not None:
            retry["exit_delay_minutes"]+=1
        ep["path"].append({"minute":j,"elapsed":j-first+1,"mark_return":mark,"drawdown":peak-mark,
            "trend":(1 if signal["side"]=="CALL" else -1)*(index[j][3]/signal["spot"]-1),
            "exit_net":result["exit_net"] if result else None,
            "exit_fees":result["exit_fees"] if result else None,"exit_utc":r._stamp(day,j+2),
            "terminal":j==deadline-2,"squareoff":j+2==r.SQUAREOFF_MINUTE,"recovery":retry})
    return ep


def assess(r,signals,table,index,dates,*,hold,lot_size,bps,capital,risk_budget,progress=None):
    out={};journal=[]
    selected=[s for s in signals if s["session"] in set(dates)]
    for lane in ("gross_funding","net_debit_counterfactual"):
        if progress:progress(90,"Paired debit spread comparison: "+lane)
        episodes=[episode(r,s,table,index[s["session"]],hold=hold,lot_size=lot_size,
                          bps=bps,risk_budget=risk_budget,lane=lane) for s in selected]
        item={"episode_states":dict(Counter(e["state"] for e in episodes)),
              "chosen_signal_pairs":sum("short_strike" in e for e in episodes),
              "chosen_pairs_gross_proxy_exceeds_budget":sum(e.get("planned_gross_funding",0)>risk_budget for e in episodes),
              "broker_margin_verified":False,"joint_fill_verified":False,
              "methods":{},"warning":"Two legs are rolling same-session strike proxies, not verified exact expiry contracts. "
                   "Net debit assumes simultaneous funding/offset; actual short-leg margin and legging risk can exceed the budget."}
        out[lane]=item
        for method in ("fixed_stop","trailing_stop"):
            name="debit_spread:"+lane+":"+method
            metrics,rows=r._evaluate(episodes,method=method,capital=capital,risk_budget=risk_budget,dates=dates)
            item["methods"][name]=metrics
            journal.extend({**row,"method":name} for row in rows)
    return out,journal
