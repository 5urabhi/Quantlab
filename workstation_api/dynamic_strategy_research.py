"""Historical paper strategy comparison; never invokes live journal writes.

The same entry/mark/exit transitions used by prospective paper monitoring are
called with an in-memory journal and a read-only source. Every selection is
as of its own observation clock; future outcomes cannot select contracts.
"""
from collections import Counter
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
import csv
import json
import sqlite3
import uuid

from . import auto_paper_engine as engine, auto_paper_selection as select
from . import dynamic_exit_policy as policy, spread_batch_core as batch
from . import depth_replay as replay, paper_execution as paper, service

VERSION="chronological_dynamic_strategy_v2"


def _variants(cfg):
    return [(f"fixed_{h//60}m",{**cfg,"exit_mode":"fixed","hold_seconds":h})
            for h in policy.HOLDS if h<=cfg["hold_seconds"]]+[
            (mode,{**cfg,"exit_mode":mode}) for mode in policy.MODES if mode!="fixed"]


def _root():
    root=service.DATA/"research_workspace"/"dynamic_strategy"
    root.mkdir(parents=True,exist_ok=True)
    return root


def result_path(run_id, *, diagnostics=False):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}",run_id):
        raise ValueError("Invalid strategy result identifier")
    path=_root()/("run-"+run_id+("-diagnostics" if diagnostics else "")+".csv")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Strategy journal not found")
    return path


def _summary(account, capital, complete_session):
    rows=account["rows"]
    completed=[r for r in rows if r["state"]=="complete"]
    pnl=[r["net_pnl_inr"] for r in completed]
    missing=sum(r["state"]=="entry_rejected" and r.get("entry_reason")=="missing_entry_books" for r in rows)
    censored=sum(r["state"] in engine.BLOCKED for r in rows)
    pending=sum(r["state"] in engine.PENDING for r in rows)
    rejected=sum(r["state"]=="entry_rejected" for r in rows)
    cash=peak=capital;drawdown=0.
    for value in pnl:
        cash=replay.fees._money(cash+value)
        peak=max(peak,cash)
        drawdown=max(drawdown,peak-cash)
    return {"policy":account["name"],"lane":account["lane"],
        "hold_cap_seconds":account["config"]["hold_seconds"],
        "entry_attempts":len(rows),"scored":len(completed),
        "entry_rejected":rejected,"unknown_entry_attempts":missing,"censored":censored,
        "pending":pending,"profitable":sum(v>0 for v in pnl),"losing":sum(v<0 for v in pnl),
        "target_hits":sum(r.get("target_hit",False) for r in completed),
        "conditional_net_inr":replay.fees._money(sum(pnl)) if pnl else None,
        "fully_observed_session_net_inr":replay.fees._money(sum(pnl)) if pnl and complete_session and not (missing or censored or pending) else None,
        "conditional_ending_cash_inr":cash if pnl else None,
        "closed_drawdown_inr":replay.fees._money(drawdown) if pnl else None,
        "mean_hold_seconds":round(mean(r["hold_realized_seconds"] for r in completed),2) if completed else None,
        "fees_inr":replay.fees._money(sum(r["fees_inr"] for r in completed)) if completed else None,
        "exit_reasons":dict(Counter(r.get("exit_trigger","unavailable") for r in completed)),
        "no_trade_reasons":dict(account["no_trade"]),
        "halted":bool(censored),"remaining_modeled_loss_inr":max(0.,min(capital,account["config"]["max_loss"])-sum(max(0.,-p) for p in pnl))}


def _record(account,row,state,**changes):
    row.update(changes,state=state)
    if state=="complete":
        account["cash"]=replay.fees._money(account["cash"]+row["net_pnl_inr"])
        account["gross_loss"]+=max(0.,-row["net_pnl_inr"])
    if state in engine.BLOCKED:
        account["halted"]=True


def _budget(account,cfg):
    return max(0.,replay.fees._money(min(account["cash"],cfg["max_loss"]-account["gross_loss"])))


def _flatten(row,account):
    return {"policy":account["name"],"lane":account["lane"],"state":row["state"],
            "decision_utc":row["decision_utc"],"direction":row["source"].get("direction"),
            "source_bar_utc":row["source"].get("bar_utc"),"source_chain_utc":row["source"].get("chain_utc"),
            "source_chain_sha256":row["source"].get("chain_sha256"),
            "applied_config":json.dumps(row["config"],sort_keys=True,separators=(",",":")),
            "selection_score":row["selected"].get("score"),"selection_scenario_net_inr":row["selected"].get("stress_favorable_net_inr"),
            "strategy":row["selected"]["strategy"],"contracts":" / ".join(row["selected"]["identities"]),
            "contract_legs":json.dumps(row["selected"]["legs"],separators=(",",":")),
            "lots":row["selected"]["lots"],"units":row["selected"]["units"],
            "entry_utc":row.get("entry_received_utc"),"exit_decision_utc":row.get("exit_decision_utc"),
            "exit_utc":row.get("exit_received_utc"),"hold_seconds":row.get("hold_realized_seconds"),
            "risk_inr":row.get("observed_entry_risk_inr"),"entry_cashflow_inr":row.get("entry_cashflow_inr"),
            "exit_trigger":row.get("exit_trigger"),"entry_reason":row.get("entry_reason"),
            "exit_reason":row.get("exit_reason"),"peak_net_inr":row.get("peak_net_inr"),
            "net_pnl_inr":row.get("net_pnl_inr"),"fees_inr":row.get("fees_inr"),
            "entries":json.dumps(row.get("entries",[]),separators=(",",":")),
            "exits":json.dumps(row.get("exits",[]),separators=(",",":")),
            "missing":json.dumps(row.get("missing",[]),separators=(",",":"))}


def run(*,day,capital=17000.,max_loss=4250.,target_net=100.,stop_net=250.,
        trail_net=50.,max_lots=3,hold_seconds=1800,liquidity_grace_seconds=20,
        slippage_bps=0.,broker_profile="zerodha",include_spreads=True,progress=None,now=None):
    cutoff=now or paper._now()
    chosen=date.fromisoformat(day)
    if chosen.weekday()>=5 or chosen>cutoff.astimezone(paper.IST).date():
        raise ValueError("Choose an observed weekday")
    cfg=engine.validate({**engine.DEFAULTS,"enabled":False,"capital":capital,
        "max_loss":max_loss,"target_net":target_net,"stop_net":stop_net,"trail_net":trail_net,
        "max_lots":max_lots,"hold_seconds":hold_seconds,"liquidity_grace_seconds":liquidity_grace_seconds,
        "slippage_bps":slippage_bps,"broker_profile":broker_profile})
    if type(include_spreads) is not bool:
        raise ValueError("Choose whether to include spreads")
    start=datetime.combine(chosen,time(9,15),paper.IST).astimezone(timezone.utc)
    close=datetime.combine(chosen,time(15,30),paper.IST).astimezone(timezone.utc)
    end=min(cutoff,close)
    anchors=[start+timedelta(seconds=policy.POLL_SECONDS*i)
             for i in range(max(0,int((end-start).total_seconds())//policy.POLL_SECONDS+1))]
    if not anchors:
        raise ValueError("No elapsed regular-session observation clock")
    if progress:
        progress(1,"Reconstructing received BANKNIFTY ticks; no revised candles")
    snapshots={}
    directions,source_stats=batch.signal_cohorts(chosen,anchors,end,snapshot_sink=snapshots)
    accounts=[{"name":name,"lane":lane,"config":variant,"cash":capital,"gross_loss":0.,
               "halted":False,"rows":[],"no_trade":Counter(),"last_attempt_minute":None}
              for name,variant in _variants(cfg) for lane in (engine.LANES if include_spreads else ("directional",))]
    entry_sources=Counter()
    source_rejections=Counter()
    lane_diagnostics={lane:{"evaluations":0,"with_candidate":0,"outcomes":Counter(),"rejections":Counter()}
                      for lane in (engine.LANES if include_spreads else ("directional",))}
    diagnostics=[]
    scan_count=qualified_scans=max_qualified=0
    total_qualified=0
    if snapshots:
        with closing(replay.ao._read_database()) as db:
            for i,tick in enumerate(anchors):
                if progress and i%20==0:
                    progress(5+90*i/len(anchors),f"Strategy clock {i}/{len(anchors)}; {len(accounts)} independent paper policies")
                first_cache={};book_cache={}
                def first(identity,eligible,limit,observed):
                    key=(identity,eligible,limit,observed)
                    if key not in first_cache:
                        first_cache[key]=replay._first_on_db(db,identity,eligible,limit,min(observed,end))
                    return first_cache[key]
                def latest(identity,observed):
                    key=(identity,observed)
                    if key not in book_cache:
                        book_cache[key]=select.latest_book(db,identity,observed)
                    return book_cache[key]
                def mark(row,observed):
                    return engine._mark(row,observed,book_lookup=latest)
                # Advance each account before considering another entry.
                # A path censored by incomplete entry/exit never reuses risk.
                for account in accounts:
                    if not account["rows"]:
                        continue
                    row=account["rows"][-1]
                    state=row["state"]
                    if state not in engine.PENDING:
                        continue
                    def update(row,state,**changes):
                        _record(account,row,state,**changes)
                    if state=="awaiting_entry":
                        engine._entry(row,tick,update=update,first_book=first)
                    elif state=="paper_open":
                        engine._monitor(row,tick,update=update,mark_lookup=mark,signal_lookup=lambda _:snapshots.get(i))
                    else:
                        engine._exit(row,tick,update=update,first_book=first)
                if tick+timedelta(seconds=30)>=close or tick.second>29:
                    continue
                minute=tick.replace(second=0,microsecond=0)
                eligible=[a for a in accounts if not a["halted"] and a["last_attempt_minute"]!=minute
                          and (not a["rows"] or a["rows"][-1]["state"] not in engine.PENDING)]
                if not eligible:
                    continue
                signal=snapshots.get(i)
                if not signal or directions.get(i) not in ("UP","DOWN"):
                    for a in eligible:
                        a["no_trade"]["missing_or_neutral_direction"]+=1
                    continue
                selection_cfg={**cfg,"hold_seconds":300}
                report,books,reason=select._source(tick,selection_cfg,historical=True,signal_override=signal)
                scan_count+=1
                source_reason=reason or "source_eligible"
                entry_sources[source_reason]+=1
                qualified=int(report.get("valid_contracts",len(books)))
                qualified_scans+=int(qualified>0)
                total_qualified+=qualified
                max_qualified=max(max_qualified,qualified)
                source_rejections.update(report.get("rejections",{}))
                diagnostics.append({"record_type":"source_scan","decision_utc":paper._iso(tick),
                    "lane":"","risk_budget_inr":None,"outcome":source_reason,
                    "valid_contracts":qualified,"rejections":report.get("rejections",{}),
                    "evidence":{k:v for k,v in report.items() if k!="rejections"}})
                picks={}
                for a in eligible:
                    cap=_budget(a,cfg)
                    if cap<=0:
                        a["no_trade"]["session_loss_budget_exhausted"]+=1
                        continue
                    key=(a["lane"],cap)
                    if key not in picks:
                        _,lanes=select.from_source(report,books,reason,selection_cfg,{a["lane"]:cap})
                        picks[key]=lanes[a["lane"]]
                        pick=picks[key]
                        d=lane_diagnostics[a["lane"]]
                        d["evaluations"]+=1
                        d["with_candidate"]+=int(pick["action"]=="PAPER_ENTRY")
                        d["outcomes"][pick.get("reason",pick["action"])]+=1
                        d["rejections"].update(pick.get("rejections",{}))
                        diagnostics.append({"record_type":"lane_evaluation","decision_utc":paper._iso(tick),
                            "lane":a["lane"],"risk_budget_inr":cap,"outcome":pick.get("reason",pick["action"]),
                            "valid_contracts":qualified,"rejections":pick.get("rejections",{}),
                            "evidence":{"eligible_candidates":pick.get("eligible_candidates",0),
                                        "selected":pick.get("selected")}})
                    pick=picks[key]
                    if pick["action"]!="PAPER_ENTRY":
                        a["no_trade"][pick["reason"]]+=1
                        continue
                    a["last_attempt_minute"]=minute
                    a["rows"].append({"state":"awaiting_entry","config":a["config"],
                        "source":report,"selected":pick["selected"],"decision_utc":paper._iso(tick),
                        "risk_budget_inr":cap,"policy_version":VERSION})
    if progress:
        progress(96,"Saving policy comparison and conditional trade journal")
    complete=end>=close
    # A completed session with unresolved evidence must not be represented
    # as closed cash. Intraday cutoffs retain genuinely pending paths.
    if complete:
        for a in accounts:
            if a["rows"] and a["rows"][-1]["state"] in engine.PENDING:
                _record(a,a["rows"][-1],"exit_censored",exit_reason="unresolved_at_session_close")
    summaries=[_summary(a,capital,complete) for a in accounts]
    journal=[_flatten(r,a) for a in accounts for r in a["rows"]]
    journal.sort(key=lambda r:(r["decision_utc"],r["policy"],r["lane"]))
    run_id=uuid.uuid4().hex
    final=_root()/("run-"+run_id+".csv")
    temp=final.with_suffix(".tmp")
    fields=list(journal[0]) if journal else ["policy","lane","state","decision_utc","net_pnl_inr"]
    try:
        with temp.open("x",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            writer.writerows(journal)
        temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)
    diagnostic_summary={"scans_with_qualified_contracts":qualified_scans,
        "max_qualified_contracts_per_scan":max_qualified,"total_qualified_contract_observations":total_qualified,
        "source_rejections":dict(source_rejections),
        "lanes":{lane:{**d,"outcomes":dict(d["outcomes"]),"rejections":dict(d["rejections"])}
                 for lane,d in lane_diagnostics.items()}}
    # Keep trade journal semantics intact. The separate diagnostic CSV always
    # contains a run summary, even when no source scans or trades occurred.
    diagnostic_file=final.with_name("run-"+run_id+"-diagnostics.csv")
    diagnostic_temp=diagnostic_file.with_suffix(".tmp")
    diagnostic_fields=["record_type","decision_utc","lane","risk_budget_inr","outcome",
                       "valid_contracts","rejections","evidence"]
    summary_row={"record_type":"run_summary","decision_utc":paper._iso(end),
        "lane":"","risk_budget_inr":cfg["max_loss"],"outcome":"complete",
        "valid_contracts":max_qualified,"rejections":dict(source_rejections),
        "evidence":{"config":cfg,"signal_evidence":source_stats,"candidate_scans":scan_count,
                    "source_reasons":dict(entry_sources),"journal_count":len(journal),
                    "diagnostics":diagnostic_summary}}
    try:
        with diagnostic_temp.open("x",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=diagnostic_fields)
            writer.writeheader()
            for item in [summary_row]+diagnostics:
                writer.writerow({**item,"rejections":json.dumps(item["rejections"],sort_keys=True,allow_nan=False),
                    "evidence":json.dumps(item["evidence"],sort_keys=True,allow_nan=False)})
        diagnostic_temp.replace(diagnostic_file)
    finally:
        diagnostic_temp.unlink(missing_ok=True)
    # Return compact per-policy metrics plus the recent trade outcomes.
    # All original execution evidence for each attempt is in the CSV.
    recent=[{k:v for k,v in row.items() if k not in ("contract_legs","entries","exits","missing")} for row in journal[-80:]]
    if progress:
        progress(100,"Dynamic strategy comparison saved")
    return {"version":VERSION,"run_id":run_id,"day_ist":day,"cutoff_utc":paper._iso(end),
        "complete_session":complete,"config":cfg,"observation_ticks":len(anchors),
        "signal_evidence":source_stats,"candidate_scans":scan_count,"source_reasons":dict(entry_sources),
        "entry_diagnostics":diagnostic_summary,"diagnostic_rows":len(diagnostics)+1,
        "policies":summaries,"recent":recent,"journal_count":len(journal),"broker_orders_enabled":False,
        "warning":"Chronological in-sample conditional paper replay. Each policy/lane has an independent virtual budget, not shared real cash. "
        "Five-second observation checks and fresh completed-minute signals are sampled, not exchange ticks or actual broker latency. "
        "Historical selection intersects contemporaneous chain IDs with fresh saved original depth before the 200-ID cap (up to 4000 chain IDs scanned), not today's watchlist. "
        "Missing source/entry/exit evidence is not zero profit; no actual fills, margin, reliable stop execution or profitability are verified. "
        "Selection horizon is five minutes for every policy; holding caps and exits differ. No parameter is automatically promoted to live trading."}
