"""Original-depth batch research kernels. No broker calls or actual fills.

Fixed-clock exploration is in-sample. The directional cohort uses only raw
index ticks received by its decision timestamp. Random controls have the
same attempted sample size, not assumed fills or independent observations.
"""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timedelta, time, timezone
from math import ceil, isfinite
from random import Random
from statistics import mean
import sqlite3

from . import depth_replay as replay, paper_execution as paper
from . import spread_speed as speed, trading_cockpit as trend
from . import spread_readiness as readiness, execution_realism as realism, replay_storage

MIN_SCORED = 20
MIN_COMPLETION = .20
MIN_BLOCKS = 4
BLOCK_MINUTES = 30
MAX_SIGNAL_TICKS = 250000
MAX_VERTICAL_PER_TYPE = 12
MAX_VERTICAL_SCREEN_PER_TYPE = 80
VERTICAL_NEIGHBORS = 4
SEED = 419
VERTICALS = ("bull_call_debit","bear_put_debit","bull_put_credit","bear_call_credit")


def _terms(book):
    return {key:book[key] for key in ("identity","strike","option_type","expiry","lot_size")}


def _group(strategy, legs, lots, coverage):
    direction = ("UP" if legs[0]["option_type"]=="CE" else "DOWN") if strategy=="LONG_OPTION" else (
        "UP" if strategy in ("bull_call_debit","bull_put_credit") else "DOWN")
    return {"family":"directional" if strategy=="LONG_OPTION" else "spread",
            "strategy":strategy,"identities":[b["identity"] for b in legs],
            "legs":[_terms(b) for b in legs],"lot_options":list(lots),
            "coverage_pct":coverage,"direction":direction}


def universe(day, cfg, now, progress=None):
    scan=readiness.automatic(day=day,capital=cfg["capital"],lots=cfg["max_lots"],
        participation_pct=cfg["participation_pct"],slippage_bps=cfg["slippage_bps"],
        broker_profile=cfg["broker_profile"],expiry=cfg["expiry"],side=cfg["side"],
        search=cfg["search"],now=now,include_all=True,include_inventory=True,
        progress=(lambda i,n:progress(1+3*i/max(n,1),"Screening recorded contracts")) if progress else None)
    inventory=scan.pop("_inventory")
    by_id={row["identity"]:row for row in inventory}
    groups=[]
    for candidate in scan["candidates"]:
        row=by_id[candidate["identity"]]
        # A smaller whole long-option quantity cannot require more entry
        # depth/capital than the verified larger quantity.
        lots=[n for n in candidate["affordable_lot_options"] if n<=candidate["study_lots"]]
        groups.append(_group("LONG_OPTION",[row["book"]],lots,row["coverage_pct"]))
    counts={"directional_contracts":len(groups),"vertical_candidates_enumerated":0,
            "vertical_candidates_screened":0,"vertical_baskets":0,"vertical_screen_limited":False}
    if cfg["include_spreads"]:
        chains=defaultdict(list)
        for row in inventory:
            book=row["book"]
            chains[(book["expiry"],book["lot_size"],book["option_type"])].append(row)
        pools=defaultdict(list)
        for (_,_,side), rows in sorted(chains.items()):
            rows=sorted(rows,key=lambda r:(r["book"]["strike"],r["identity"]))
            strategies=("bull_call_debit","bear_call_credit") if side=="CE" else ("bull_put_credit","bear_put_debit")
            for i,low in enumerate(rows):
                for high in rows[i+1:i+1+VERTICAL_NEIGHBORS]:
                    if low["book"]["strike"]>=high["book"]["strike"]:
                        continue
                    for strategy, legs in ((strategies[0],[low,high]),(strategies[1],[high,low])):
                        coverage=min(r["coverage_pct"] or 0 for r in legs)
                        books=[r["book"] for r in legs]
                        if abs((books[0]["stamp"]-books[1]["stamp"]).total_seconds())>cfg["max_skew_seconds"]:
                            continue
                        key=(-coverage,sum(b["spread_bps"] for b in books),
                             abs(books[0]["strike"]-books[1]["strike"]),
                             tuple(b["identity"] for b in books))
                        pools[strategy].append((key,legs,coverage))
        counts["vertical_candidates_enumerated"]=sum(map(len,pools.values()))
        for strategy in VERTICALS:
            candidates=sorted(pools[strategy],key=lambda x:x[0])
            if len(candidates)>MAX_VERTICAL_SCREEN_PER_TYPE:
                counts["vertical_screen_limited"]=True
            added=0
            for _,legs,coverage in candidates[:MAX_VERTICAL_SCREEN_PER_TYPE]:
                if progress:
                    progress(4+counts["vertical_candidates_screened"]/(4*MAX_VERTICAL_SCREEN_PER_TYPE)*4,
                             "Screening defined-risk vertical baskets")
                counts["vertical_candidates_screened"]+=1
                books=[r["book"] for r in legs]
                try:
                    replay.studio._validate_structure(strategy,books)
                except ValueError:
                    continue
                actions=replay.studio.STRATEGIES[strategy]["actions"]
                lots=[]
                for n in range(1,cfg["max_lots"]+1):
                    units=n*books[0]["lot_size"]
                    params=(units,cfg["participation_pct"],cfg["slippage_bps"],cfg["broker_profile"])
                    entries=[replay._execute(b,a,*params) for b,a in zip(books,actions)]
                    exits=[replay._execute(b,"SELL" if a=="BUY" else "BUY",*params) for b,a in zip(books,actions)]
                    if any(r["displayed_fill_units"]!=units for r in entries+exits):
                        continue
                    cash,_,risk=replay._entry_risk(strategy,books,actions,entries,units)
                    if risk>cfg["capital"] or (strategy.endswith("debit") and cash>=0) or (strategy.endswith("credit") and cash<=0):
                        continue
                    lots.append(n)
                if lots:
                    groups.append(_group(strategy,books,lots,coverage))
                    added+=1
                    counts["vertical_baskets"]+=1
                    if added>=MAX_VERTICAL_PER_TYPE:
                        counts["vertical_screen_limited"] |= len(candidates)>added
                        break
    # Return metadata, never raw quote books or credentials.
    return groups,{**counts,"scan_scope":scan["scope"],"scanned_contracts":scan["scanned_contracts"],
        "scan_truncated":scan["scan_truncated"],"affordable_contracts":scan["affordable_candidates"],
        "screen_rejections":scan["rejections"]}


def signal_cohorts(day, anchors, now):
    """Rebuild causal observed minute candles from exchange/receipt clocks.

    An index minute bar saved later can contain a late revision; using only
    the final aggregate would leak that revision into earlier decisions.
    Reconstruct using tick events actually received by each anchor.
    """
    if not anchors:
        return {},{"state":"no_elapsed_anchors","valid":0,"up":0,"down":0,"neutral":0,"ticks":0}
    start=datetime.combine(day,time(9,15),paper.IST).astimezone(timezone.utc)
    end=min(now,anchors[-1])
    try:
        with closing(replay.ao._read_database()) as db:
            rows=replay_storage.fetchall(db,"""SELECT exchange_utc,received_utc,price,packet_sha256 FROM live_ticks
                WHERE identity='INDEX:BANKNIFTY' AND exchange_utc>=? AND exchange_utc<?
                AND received_utc<=? ORDER BY received_utc,exchange_utc,packet_sha256 LIMIT ?""",
                (paper._iso(start),paper._iso(end),paper._iso(end),MAX_SIGNAL_TICKS+1))
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc) and "unable to open database file" not in str(exc):
            raise
        rows=[]
    if not rows or len(rows)>MAX_SIGNAL_TICKS:
        return {},{"state":"missing_original_index_ticks" if not rows else "index_tick_scan_limit",
                   "valid":0,"up":0,"down":0,"neutral":0,"ticks":len(rows)}
    ticks=[]
    for exchange,received,price,digest in rows:
        try:
            t=trend._ts(exchange); r=trend._ts(received); price=float(price)
        except (ValueError,TypeError,OverflowError):
            continue
        # Same admissible exchange/receive lag as the original ticker ingest;
        # reject invalid stored digest evidence and nonpositive prices.
        if (not isfinite(price) or price<=0 or not isinstance(digest,str) or len(digest)!=64
                or any(c not in "0123456789abcdef" for c in digest)
                or abs((r-t).total_seconds())>45 or not paper._regular(t)):
            continue
        ticks.append((r,t,price))
    # Explicit timestamp sort handles different equivalent ISO encodings.
    ticks.sort(key=lambda x:(x[0],x[1]))
    bars={}; cursor=0; directions={}
    for i,anchor in enumerate(anchors):
        while cursor<len(ticks) and ticks[cursor][0]<=anchor:
            received,exchange,price=ticks[cursor]; cursor+=1
            minute=exchange.replace(second=0,microsecond=0)
            item=bars.get(minute)
            if item is None:
                bars[minute]={"timestamp_utc":paper._iso(minute),"session_ist":day.isoformat(),
                    "open":price,"high":price,"low":price,"close":price,
                    "_first":exchange,"_last":exchange}
            else:
                item["high"]=max(item["high"],price);item["low"]=min(item["low"],price)
                if exchange<item["_first"]:
                    item["open"]=price;item["_first"]=exchange
                if exchange>=item["_last"]:
                    item["close"]=price;item["_last"]=exchange
        complete=[bars[k] for k in sorted(bars) if k+timedelta(minutes=1)<=anchor]
        if not complete:
            continue
        signal=trend.snapshot("INDEX:BANKNIFTY",complete[-120:],now=anchor,include_chart=False)
        if signal["quote_mode"]=="RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE" and signal["contiguous_session_bars"]>=30:
            directions[i]=signal["direction"]
    counts=Counter(directions.values())
    return directions,{"state":"available" if directions else "insufficient_contiguous_received_ticks",
        "valid":len(directions),"up":counts["UP"],"down":counts["DOWN"],
        "neutral":counts["NO_TRADE"],"ticks":len(ticks),"model":trend.VERSION}


def cohort_indices(day, anchors, directions, direction):
    all_indices=list(range(len(anchors)))
    valid=sorted(directions)
    aligned=[i for i in valid if directions[i]==direction]
    # Reproducible random-time comparator with equal attempted count, using
    # the same source-valid anchor universe. It can overlap aligned anchors.
    seed=SEED+int(day.strftime("%Y%m%d"))+(1 if direction=="DOWN" else 0)
    control=sorted(Random(seed).sample(valid,len(aligned)))
    return all_indices,aligned,control


def summarize(records, indices, anchors, target, *, capital=None):
    selected=[records[i] for i in indices]
    scored=[(i,records[i]) for i in indices if records[i][0] is not None]
    net=[r[0] for _,r in scored]
    blocks=defaultdict(list)
    for i,r in scored:
        local=anchors[i].astimezone(paper.IST)
        block=(local.hour*60+local.minute)//BLOCK_MINUTES
        blocks[block].append(r[0])
    block_means=sorted(mean(v) for v in blocks.values())
    lower=block_means[max(0,ceil(.25*len(block_means))-1)] if block_means else None
    average=mean(net) if net else None
    completion=len(net)/len(indices) if indices else 0.
    rankable=len(net)>=MIN_SCORED and completion>=MIN_COMPLETION and len(blocks)>=MIN_BLOCKS
    out={"attempted":len(indices),"scored":len(net),"unscored":len(indices)-len(net),
        "completion_pct":round(100*completion,2),"entry_complete":sum(r[2] for r in selected),
        "profitable":sum(v>0 for v in net),"losing":sum(v<0 for v in net),
        "target_hits":sum(v>=target for v in net),
        "mean_net":round(average,2) if average is not None else None,
        "total_net":round(sum(net),2) if net else None,
        "worst_net":min(net) if net else None,
        "mean_fees":round(mean(r[3] for _,r in scored),2) if net else None,
        "scored_blocks":len(blocks),"lower_block_mean":round(lower,2) if lower is not None else None,
        "robust_score":round(min(average,lower),2) if rankable else None,
        "rankable":rankable,"states":dict(Counter(r[1] for r in selected))}
    if capital is not None:
        audits=[r[4] for _,r in scored if len(r)>4 and r[4] is not None]
        out["execution_costs"]=realism.aggregate(audits)
        out["sequential_account"]=realism.sequential(records,indices,anchors,capital)
    return out


def evaluate(group, specs, cfg, day, anchors, directions, now, stop, cohorts=("fixed","signal")):
    """One connection per independent structure; cache first books per anchor.

    A configuration is (lots, assumed reaction milliseconds, hold seconds).
    Entries use the existing replay kernel with frozen original identities
    and contract terms. No result-dependent changes to contracts or size.
    """
    series={spec:[] for spec in specs}
    samples={}
    terms={b["identity"]:b for b in group["legs"]}
    expired=any(b["expiry"]<day.isoformat() for b in group["legs"])
    db=None
    if not expired and anchors:
        try:
            db=replay.ao._read_database()
        except sqlite3.OperationalError as exc:
            if "unable to open database file" not in str(exc):
                raise
    try:
        for anchor_index,decision in enumerate(anchors):
            if stop.is_set():
                return []
            cache={}
            def lookup(identity,eligible,end,cutoff):
                key=(identity,eligible,end,cutoff)
                if key not in cache:
                    if db is None:
                        cache[key]=(None,"source_table_unavailable")
                    else:
                        try:
                            book,reason=replay._first_on_db(db,identity,eligible,end,cutoff)
                        except sqlite3.OperationalError as exc:
                            if "no such table" not in str(exc):
                                raise
                            book,reason=None,"source_table_unavailable"
                        if book is not None and _terms(book)!=terms[identity]:
                            book,reason=None,"frozen_contract_terms_mismatch"
                        cache[key]=(book,reason)
                return cache[key]
            # The earliest book is identical across all lots and horizons
            # at a given anchor/delay. Missing entry evidence short-circuits
            # every cell at that delay, preserving the replay's state.
            absent={}
            for delay in {spec[1] for spec in specs}:
                if expired:
                    absent[delay]="expired_frozen_contract";continue
                ready=decision+timedelta(microseconds=max(1,round(delay*1000)))
                end=ready+timedelta(seconds=cfg["window_seconds"])
                errors=[lookup(identity,ready,end,now)[1] for identity in group["identities"]]
                if any(errors):
                    absent[delay]="entry_unobservable"
            for spec in specs:
                if stop.is_set():
                    return []
                lots,delay,hold=spec
                if delay in absent:
                    series[spec].append((None,absent[delay],False,0.));continue
                r=replay.replay(strategy=group["strategy"],identities=group["identities"],lots=lots,
                    decision_utc=paper._iso(decision),capital=cfg["capital"],hold_seconds=hold,
                    latency_ms=delay,window_seconds=cfg["window_seconds"],max_skew_seconds=cfg["max_skew_seconds"],
                    participation_pct=cfg["participation_pct"],slippage_bps=cfg["slippage_bps"],
                    broker_profile=cfg["broker_profile"],now=now,first_book=lookup)
                cash=r.get("entry_cashflow")
                wrong_cash=cash is not None and ((group["strategy"].endswith("debit") and cash>=0) or (
                    group["strategy"].endswith("credit") and cash<=0))
                net=r["net_pnl_inr"] if r["exit_complete"] and not wrong_cash else None
                state="wrong_structure_cashflow" if wrong_cash else r["state"]
                audit=realism.analyze(r,cfg) if net is not None else None
                series[spec].append((net,state,r["entry_complete"] and not wrong_cash,r.get("total_fees_inr") or 0.,audit))
                if audit:
                    for cohort in ("fixed","signal"):
                        if cohort in cohorts and (cohort=="fixed" or directions.get(anchor_index)==group["direction"]):
                            key=(spec,cohort)
                            if key not in samples:
                                samples[key]=realism.sample_trade(r,audit,cfg)
    finally:
        if db is not None:
            db.close()
    fixed,aligned,random=cohort_indices(day,anchors,directions,group["direction"])
    output=[]
    for (lots,delay,hold),records in series.items():
        base={"family":group["family"],"strategy":group["strategy"],"identities":group["identities"],
              "legs":group["legs"],"direction":group["direction"],"selection_coverage_pct":group["coverage_pct"],
              "lots":lots,"latency_ms":delay,"hold_seconds":hold}
        if "fixed" in cohorts:
            output.append({**base,"cohort":"fixed",**summarize(records,fixed,anchors,cfg["target_net"],capital=cfg["capital"]),
                           "sample_trade":samples.get(((lots,delay,hold),"fixed"))})
        if "signal" in cohorts:
            signal=summarize(records,aligned,anchors,cfg["target_net"],capital=cfg["capital"])
            control=summarize(records,random,anchors,cfg["target_net"],capital=cfg["capital"])
            # Not a paired return comparison or a hypothesis test: missing
            # paths and overlapping horizons can differ between cohorts.
            difference=None if signal["mean_net"] is None or control["mean_net"] is None else round(
                signal["mean_net"]-control["mean_net"],2)
            output.append({**base,"cohort":"signal",**signal,"random_control":control,
                           "sample_trade":samples.get(((lots,delay,hold),"signal")),
                           "signal_minus_random_mean":difference,
                           "random_overlap_attempts":len(set(aligned)&set(random))})
    return output


def rank_key(row):
    # Unsupported configurations may be inspected but never outrank
    # minimum-evidence configurations merely because one trade made money.
    value=row["robust_score"] if row["rankable"] else None
    return (not row["rankable"],-value if value is not None else 0,
            -(row["mean_net"] if row["rankable"] and row["mean_net"] is not None else 0),
            -row["scored"],-row["completion_pct"],row["strategy"],
            tuple(row["identities"]),row["lots"],row["latency_ms"],row["hold_seconds"])


def can_freeze(row):
    if not row["rankable"] or row["robust_score"]<=0 or row["mean_net"]<=0:
        return False
    stress=(row.get("execution_costs") or {}).get("stress",{})
    # No freeze if the matched stress cases lose money or drop any baseline
    # scored paths because additional price uncertainty exceeds budget.
    if any(not stress.get(str(int(inc))) or stress[str(int(inc))]["scored"]!=row["scored"]
           or stress[str(int(inc))]["mean_net"] is None or stress[str(int(inc))]["mean_net"]<=0
           for inc in realism.STRESS_BPS):
        return False
    if row["cohort"]=="signal":
        return bool(row["random_control"]["rankable"] and row["signal_minus_random_mean"] is not None
                    and row["signal_minus_random_mean"]>0)
    return True
