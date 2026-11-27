"""Bounded, resumable preparation of original BANKNIFTY research data.

Use the running loopback workstation for Dhan writes, so no second broker
history writer or recorder restart is needed. Public/authorized archive
adapters preserve their original availability semantics. No model training.
"""
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, time as clock, timezone
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
import argparse
import csv
import json
import os
import time
import uuid

from dotenv import load_dotenv
from workstation_api import (service, cockpit_sources as cs, index_spot,
    market_patterns as mp, historical_alpha as h, pit_index, dhan_workspace as dw,
    dhan_checkpoint, verified_equity_context as equity, options_history_sync as opt,
    cpr_context_archive as fred, cpr_alpaca_archive as alpaca, market_inventory,
    context_feeds, predictive_option_research as po, cpr_hybrid_research as r)

API="http://127.0.0.1:8765"
IDENTITIES=("INDEX:BANKNIFTY","INDEX:NIFTY50",*sorted(index_spot.RESEARCH_INDEXES))
MAX_RESPONSE=32*1024*1024
MINUTES=375


class Pause(RuntimeError):pass
class Failed(RuntimeError):pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def api(path,body=None,*,post=False):
    if not path.startswith("/api/"):raise ValueError("Only local workstation API paths")
    req=Request(API+path,data=json.dumps(body if body is not None else {}).encode() if post else None,
                headers={"Content-Type":"application/json","Accept":"application/json"},
                method="POST" if post else "GET")
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=60) as response:
            payload=response.read(MAX_RESPONSE+1)
            if len(payload)>MAX_RESPONSE:raise Failed("Local API response exceeds bound")
            return json.loads(payload)
    except HTTPError as exc:
        # Do not print arbitrary response bodies, tokens, or request URLs.
        error=Pause if exc.code in (401,403,409,429) else Failed
        raise error("Local workstation HTTP "+str(exc.code)+" at "+path.split("?")[0]) from None
    except (URLError,TimeoutError,OSError) as exc:
        raise Pause("Local workstation connection unavailable; inspect the running Jobs page before retrying a submitted write") from None


def local_now():return datetime.now(h.IST)


def offhours(now=None):
    now=now or local_now()
    return now.weekday()>=5 or now.time()<clock(8,30) or now.time()>=clock(16)


def require_offhours():
    if not offhours():raise Pause("Heavy history acquisition paused during 08:30–16:00 IST weekday priority window; rerun outside it")


def priority_blocker(parallel_live,*,dhan=True):
    if not parallel_live:
        return None if offhours() else "Market-priority window began"
    # Always respect the backend's shared cooldown; do not start a separate
    # Dhan process to bypass either queue admission or the historical budget.
    if offhours() and not dhan:return None
    status=api("/api/data-manager/maintenance")
    if status.get("error"):return "Maintenance pressure status unavailable"
    if not offhours():
        if (status.get("config") or {}).get("enabled") is not True or "live_pressure" not in status:
            return "Live recorder pressure monitoring unavailable; enable authorized automatic maintenance"
        if status["live_pressure"]:
            return "Recorder pressure: "+str(status["live_pressure"])[:100]
    if dhan and status.get("next_due_reason")=="provider_rate_limit" and status.get("next_due_utc"):
        try:
            due=datetime.fromisoformat(status["next_due_utc"].replace("Z","+00:00"))
            if due>datetime.now(timezone.utc):return "Provider cooldown until "+due.isoformat()
        except (TypeError,ValueError):return "Provider cooldown schedule unverified"
    return None


def require_priority(parallel_live,*,dhan=True):
    reason=priority_blocker(parallel_live,dhan=dhan)
    if reason:raise Pause(reason)


def live_priority_request():
    """Use only the already-authorized, recorder-aware maintenance worker.

    Do not submit generic history jobs or silently enable recurring collection.
    Its bounded scope is separate from the requested five-year bulk acquisition.
    """
    health=api("/api/health")
    if not health.get("ok") or health.get("mode")!="local" or health.get("read_only_market_data") is not True or health.get("broker_orders_enabled") is not False:
        raise Pause("Expected local read-only QuantLab API; no writes submitted")
    path="/api/data-manager/maintenance"
    status=api(path)
    cfg=status.get("config") or {}
    result={"authorized_scope":{k:cfg.get(k) for k in ("enabled","index","constituents","options","bank_panel","index_days","constituent_days","option_days","wings")},
            "live_pressure":status.get("live_pressure"),"next_due_utc":status.get("next_due_utc"),
            "next_due_reason":status.get("next_due_reason"),"job":status.get("job"),
            "heavy_backfill_deferred":True}
    if status.get("error"):
        return {**result,"state":"maintenance_configuration_unavailable"}
    if cfg.get("enabled") is not True:
        return {**result,"state":"maintenance_not_enabled",
                "note":"Enable and authorize automatic maintenance in Data Center, or rerun bulk preparation outside market hours."}
    if not status.get("worker_running"):
        return {**result,"state":"maintenance_worker_unavailable"}
    if status.get("live_pressure"):
        return {**result,"state":"recorder_pressure_yielded"}
    if (status.get("job") or {}).get("status") in ("queued","running"):
        return {**result,"state":"maintenance_already_active"}
    if status.get("next_due_reason")=="provider_rate_limit" and status.get("next_due_utc"):
        try:
            due=datetime.fromisoformat(status["next_due_utc"].replace("Z","+00:00"))
            if due>datetime.now(timezone.utc):
                return {**result,"state":"provider_cooldown_preserved"}
        except (TypeError,ValueError):
            return {**result,"state":"provider_schedule_unverified"}
    updated=api(path+"/check",post=True)
    return {**result,"state":"maintenance_check_requested","next_due_utc":updated.get("next_due_utc"),
            "next_due_reason":updated.get("next_due_reason"),"job":updated.get("job"),
            "note":"Existing worker schedules the bounded pass; this is a request, not verified download completion."}


def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with tmp.open("x",encoding="utf-8") as fd:json.dump(value,fd,indent=2,sort_keys=True,allow_nan=False)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def say(label,value):
    print(label,json.dumps(value,default=str,sort_keys=True),flush=True)


def chunks(start,stop,width):
    while start<stop:
        end=min(stop,start+timedelta(days=width))
        yield start,end
        start=end


def wait_idle(parallel_live=False):
    # A bounded wait is for existing work/actual pressure, not the clock.
    deadline=time.monotonic()+900
    last=None
    while True:
        reason=priority_blocker(parallel_live)
        if reason:
            if not parallel_live or not reason.startswith("Recorder pressure:"):
                raise Pause(reason)
            if time.monotonic()>=deadline:raise Pause(reason)
            if reason!=last:print("YIELD",reason,flush=True);last=reason
            time.sleep(5);continue
        jobs=api("/api/workspace/jobs").get("jobs",[])
        active=[j for j in jobs if j.get("status") in ("queued","running")]
        if not active:return
        if time.monotonic()>=deadline:
            raise Pause("Existing workstation jobs are active; rerun after they finish. No other jobs cancelled.")
        reason="Waiting for existing local data job: "+str(active[0].get("kind","unknown"))
        if reason!=last:print(reason,flush=True);last=reason
        time.sleep(5)


def job(path,body,record,flush,*,cancel_path=None,parallel_live=False):
    wait_idle(parallel_live)
    created=api(path,body,post=True)
    jid=created["job_id"]
    record.update(job_id=jid,state="submitted")
    if created.get("batch"):
        record["batch_id"]=created["batch"]["id"]
    flush()
    print("LOCAL JOB",jid,path,flush=True)
    last=None;cancelled=False;yield_reason=None
    deadline=time.monotonic()+48*3600
    while time.monotonic()<deadline:
        status=api("/api/jobs/"+jid)
        stage=(status.get("status"),status.get("percent"),status.get("stage"))
        if stage!=last:
            say("JOB PROGRESS",{"id":jid,"status":stage[0],"percent":stage[1],"stage":stage[2]})
            last=stage
        if status["status"]=="complete":
            result=status.get("result") or {}
            record.update(state="job_complete",result=result);flush()
            if result.get("status") in ("paused","cancelled","interrupted"):
                raise Pause("Acquisition stopped at a saved checkpoint "+str(record.get("batch_id",jid))+"; "+(yield_reason or "inspect provider status before rerun"))
            if yield_reason:raise Pause(yield_reason+"; submitted job completed, saved receipts retained")
            return result
        if status["status"] not in ("queued","running"):
            record.update(state=status["status"]);flush()
            detail=str(status.get("error","")).lower()
            if status["status"]!="error" or any(s in detail for s in ("429","401","403","rate limit","rate-limit","token","credential","entitlement")):
                raise Pause("Job "+jid+" ended "+status["status"]+"; inspect Jobs. Original completed receipts remain saved.")
            raise Failed("Job "+jid+" failed; inspect Jobs for source details")
        if not cancelled and yield_reason is None:
            yield_reason=priority_blocker(parallel_live)
        if yield_reason and not cancelled:
            # Cancel only this command's own cancellable job, never the
            # recorder or a different user's background job.
            target=cancel_path
            if record.get("batch_id") and path.startswith("/api/dhan/batches"):
                target="/api/dhan/batches/"+record["batch_id"]+"/cancel"
            if target=="job":target="/api/workspace/jobs/"+jid+"/cancel"
            if target:
                try:api(target,post=True)
                except (Pause,Failed):
                    # A completed job may race with cancellation. Poll its
                    # terminal state, not another job or recorder.
                    print("Cancellation unavailable; waiting for submitted job checkpoint",flush=True)
                cancelled=True
            else:
                print("YIELD after current bounded job:",yield_reason,flush=True);cancelled=True
        time.sleep(5)
    raise Pause("Submitted job "+jid+" is still running; inspect Jobs before resuming")


def audit_index(identity,start,stop):
    coverage=[];masks={};hashes={};rejected={}
    for path,_,meta in cs._candidates(identity):
        try:
            a,b=map(date.fromisoformat,(meta["from_inclusive"],meta["to_exclusive"]))
            if a>=stop or b<=start:continue
            bars=mp._receipt(path,meta)
            received=datetime.fromisoformat(meta["retrieved_utc"].replace("Z","+00:00")).astimezone(h.IST)
            if received.hour<16:b=min(b,received.date())
            if a<b:coverage.append((a,b))
            hashes[path.parent.name]=meta["sha256"]
            for day,minutes in bars.items():
                if start.isoformat()<=day<stop.isoformat():
                    mask=masks.get(day,0)
                    for minute in minutes:
                        if 0<=minute<MINUTES:mask|=1<<minute
                    masks[day]=mask
        except (ValueError,OSError,KeyError,TypeError,OverflowError,csv.Error) as exc:
            rejected[path.parent.name]=type(exc).__name__
    complete=sorted(d for d,m in masks.items() if m.bit_count()==MINUTES)
    return {"verified_receipts":len(hashes),"source_hashes":hashes,"rejected_receipts":rejected,
            "first_complete_session":complete[0] if complete else None,"last_complete_session":complete[-1] if complete else None,
            "complete_sessions":len(complete),"partial_sessions":sorted(set(masks)-set(complete)),
            "complete_dates":complete,"observed_minutes":sum(m.bit_count() for m in masks.values()),
            "checked_ranges":[[a.isoformat(),b.isoformat()] for a,b in coverage]}


def index_plan(audit,known,start,stop):
    coverage=[(date.fromisoformat(a),date.fromisoformat(b)) for a,b in audit["checked_ranges"]]
    gaps=[(a,b) for a,b in mp.missing_windows(start,stop,coverage)
          if any((a+timedelta(days=i)).weekday()<5 for i in range((b-a).days))]
    # One explicit repair per known observed trading date; never assume every
    # weekday is an exchange session or mark empty windows as complete.
    repairs=[]
    for d in sorted(known-set(audit["complete_dates"])):
        day=date.fromisoformat(d)
        if start<=day<stop and not any(a<=day<b for a,b in gaps):
            repairs.append((day,day+timedelta(days=1)))
    return sorted(set(gaps+repairs),reverse=True)


def equity_batch(start,stop,interval,plan,record,flush,*,parallel_live=False):
    # Source-hash-matched batch reuse. Existing _fetch_history validates and
    # skips checked canonical windows even when a newer dated batch is needed.
    matching=[]
    for item in dw.list_batches():
        if (item.get("selection")=="banknifty_pit" and item.get("interval")==interval
                and item.get("from_date")==start.isoformat() and item.get("to_date")==stop.isoformat()):
            raw=dw._load_batch(item["id"])
            if raw.get("historical_index",{}).get("source_sha256")==plan["source_sha256"]:
                matching.append(item)
    if matching:
        item=matching[0];record["batch_id"]=item["id"]
        counts=item.get("counts",{})
        if item["status"]=="completed" and counts.get("complete",0)+counts.get("cached",0)==item["total"]:
            record.update(state="existing_completed_batch",counts=counts);flush();return
        job("/api/dhan/batches/"+item["id"]+"/resume",{},record,flush,parallel_live=parallel_live)
    else:
        body={"selection":"banknifty_pit","ids":[],"tickers":[],"from_date":start.isoformat(),
              "to_date":stop.isoformat(),"interval":interval,"acknowledged_bulk":False,
              "acknowledged_gaps":True,"include_index_spot":False}
        job("/api/dhan/batches",body,record,flush,parallel_live=parallel_live)


def equity_audit(plan,stop,bank_days):
    budget=[equity.MAX_TOTAL_BYTES];out={}
    for row in plan["resolved"]:
        identity=row["id"];item={}
        expected={d for d in bank_days if any(x["symbol"]==row["pit_symbol"] and x["valid_from"]<=d
                    and (not x["valid_to"] or d<x["valid_to"]) for x in plan["raw_intervals"])}
        for label,interval in (("1m",1),("daily",None)):
            path=dw._history_file(row,interval).with_suffix(".json")
            try:
                series,info=equity._original_daily(path,identity,interval,stop.isoformat(),budget)
                dates=set(series.index)
                item[label]={**info,"expected_member_sessions":len(expected),
                             "complete_expected_sessions":len(expected&dates),
                             "missing_expected_dates":sorted(expected-dates)}
            except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
                item[label]={"state":"unverified","reason":type(exc).__name__,"missing_expected_dates":sorted(expected)}
        out[identity]=item
    return out


def option_field_audit(start,stop,dates):
    # The bounded original loader reuses checksum-checked option receipts;
    # measure actual observed fields, not just successful request receipts.
    use=sorted(d for d in dates if start.isoformat()<=d<stop.isoformat())[-90:]
    if not use:return {"state":"no_index_dates"}
    stamps={r._stamp(d,m) for d in use for m in range(MINUTES)}
    try:
        table,meta=po._load_options([{"session":d} for d in use],3,needed_stamps=stamps)
        n=oi=iv=volume=0
        for rows in table.values():
            for q in rows.values():
                n+=1;oi+=q.get("oi") is not None;iv+=q.get("iv") is not None
                volume+=q.get("volume") is not None and q["volume"]>0
        return {"state":"observed_field_audit","sessions":len(use),"wings":3,"bars":n,
                "oi_present":oi,"iv_present":iv,"positive_volume":volume,"source":meta}
    except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
        return {"state":"unavailable","reason":type(exc).__name__}


def archive_windows(start,stop,root,report,flush,feed,*,parallel_live=False):
    # Durable receipt-hash journal. On resume, skip only completed windows
    # whose import receipts still exist in the canonical database.
    import sqlite3
    from contextlib import closing
    from workstation_api import shared_market_data
    path=root/"results"/"banknifty_context_backfill_progress.json"
    try:ledger=json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
    except (OSError,ValueError):ledger={}
    def verified(key):
        hashes=ledger.get(key,[])
        if not hashes or not shared_market_data.database_path().is_file():return False
        try:
            with closing(sqlite3.connect(shared_market_data.database_path().resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
                return all(db.execute("SELECT 1 FROM market_context_imports WHERE receipt_sha256=?",(sha,)).fetchone()
                           and db.execute("SELECT 1 FROM market_context_raw_reports WHERE receipt_sha256=?",(sha,)).fetchone() for sha in hashes)
        except sqlite3.Error:return False
    guard=(lambda:require_priority(True,dhan=False)) if parallel_live else None
    providers=[]
    if os.getenv("FRED_API_KEY","").strip():providers.append(("fred",lambda a,b:fred.backfill(a,b,confirmed=True,live_guard=guard)))
    else:report["context"].append({"provider":"fred","state":"credentials_missing"})
    if alpaca.credentials():providers.append(("alpaca:"+feed,lambda a,b:alpaca.backfill(a,b,feed=feed,confirmed=True,live_guard=guard)))
    else:report["context"].append({"provider":"alpaca","state":"credentials_missing"})
    for name,fetch in providers:
        for a,b in reversed(list(chunks(start,stop,120))):
            require_priority(parallel_live,dhan=False)
            key=f"{name}|{a}|{b}"
            if verified(key):
                report["context"].append({"scope":key,"state":"existing_receipts"});continue
            print("ARCHIVE",key,flush=True)
            result=fetch(a,b)
            report["context"].append({"scope":key,"result":result});flush()
            factors=result.get("factors",{})
            if factors and all(v.get("state") in ("saved","already_present") and v.get("receipt_sha256") for v in factors.values()):
                ledger[key]=[v["receipt_sha256"] for v in factors.values()]
                save_json(path,ledger)
            say("ARCHIVE RESULT",{"scope":key,"states":{k:v.get("state") for k,v in factors.items()},"state":result.get("state")})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shared-root",type=Path,default=service.ROOT)
    p.add_argument("--years",type=int,choices=(1,2,3,4,5),default=5)
    p.add_argument("--option-days",type=int,default=365)
    p.add_argument("--context-days",type=int,default=365)
    p.add_argument("--wings",type=int,default=10)
    p.add_argument("--max-index-windows",type=int,default=240)
    p.add_argument("--alpaca-feed",choices=("iex","sip"),default="iex")
    p.add_argument("--audit-only",action="store_true")
    p.add_argument("--parallel-live",action="store_true",help="Allow full history preparation alongside live recording, guarded by backend recorder pressure and shared Dhan budget")
    p.add_argument("--confirm-reviewed",action="store_true",help="Authorize existing provider read-only downloads and reviewed archive assumptions")
    args=p.parse_args()
    if not 1<=args.option_days<=366 or not 1<=args.context_days<=1825 or not 0<=args.wings<=10 or not 1<=args.max_index_windows<=250:
        p.error("Invalid bounded scope")
    if not args.audit_only and not args.confirm_reviewed:p.error("Use --confirm-reviewed after reviewing data provider terms and archive assumptions")
    root=args.shared_root.resolve()
    if not (root/"data").is_dir():p.error("Original QuantLab shared data directory missing")
    service.DATA=root/"data"
    load_dotenv(root/".env",override=False)
    stop=local_now().date();start=stop-timedelta(days=365*args.years)
    option_start=stop-timedelta(days=args.option_days)
    report={"version":"banknifty_data_preparation_v2","parallel_live":args.parallel_live,"from_inclusive":str(start),"to_exclusive":str(stop),
            "index":{},"index_jobs":[],"equity_jobs":[],"options":[],"context":[],
            "blocked_sources":{"historical_weights":"Exact dated official/reviewed weight files required; no fabricated weights",
             "expired_futures":"Exact contract identity, expiry and authorized historical futures source required; no reconstructed futures",
             "fii_dii_participant_history":"Authorized dated source exports and availability evidence required; inspect existing participant inbox",
             "gift_nifty_asian_european_intraday":"Explicit licensed symbol/exchange mapping and historical entitlement required",
             "historical_bid_ask_depth":"Previously recorded original packets or authorized historical book archive required"},
            "state":"running","warning":"Requested intervals and checked receipts are not continuous complete market history. Archive availability assumptions are not actual historical receipt proof. No training or orders. Previously examined dates remain exploratory."}
    dest=root/"results"/("banknifty_data_preparation_"+uuid.uuid4().hex+".json")
    flush=lambda:save_json(dest,report)
    print("REPORT",dest,flush=True);flush()
    def audit_all():
        for identity in IDENTITIES:
            print("AUDIT",identity,flush=True)
            report["index"][identity]=audit_index(identity,start,stop)
        flush()
        say("INDEX COVERAGE",{k:{x:v[x] for x in ("complete_sessions","first_complete_session","last_complete_session","verified_receipts")} for k,v in report["index"].items()})
    try:
        if not args.audit_only and not args.parallel_live and not offhours():
            live=live_priority_request()
            report["live_priority"]=live
            report["state"]="live_priority_only_bulk_deferred"
            say("LIVE PRIORITY",live)
            print("Five-year bulk downloads and external historical archives remain deferred until outside 08:30–16:00 IST. Run the same command again then.",flush=True)
            return 0 if live["state"] in ("maintenance_check_requested","maintenance_already_active") else 2
        if not args.audit_only:
            health=api("/api/health")
            if not health.get("ok") or health.get("mode")!="local" or health.get("read_only_market_data") is not True or health.get("broker_orders_enabled") is not False:
                raise Pause("Expected local read-only QuantLab API; no writes submitted")
            if args.parallel_live:print("PARALLEL LIVE: full requested backfill; shared backend queue and recorder-pressure checks active",flush=True)
            for label,path in (("master","/api/dhan/instruments/refresh"),("membership","/api/indices/sync")):
                record={};report[label+"_refresh"]=record
                try:job(path,{},record,flush,parallel_live=args.parallel_live)
                except Failed as exc:
                    record["state"]="refresh_failed";record["reason"]=str(exc);flush()
        audit_all()
        known=set().union(*(set(x["complete_dates"]) for x in report["index"].values()))
        if not args.audit_only:
            require_priority(args.parallel_live)
            auth=api("/api/dhan/credentials/check")
            report["dhan_profile"]={"ok":bool(auth.get("ok")),"code":auth.get("code")};flush()
            if auth.get("ok"):
                # Use the serialized generic original IDX_I endpoint for all
                # indices; this branch reads those raw receipts in place.
                total=0
                for identity in IDENTITIES:
                    mode=index_spot.CORE_RESEARCH_MODES.get(identity,identity)
                    inst=index_spot.resolve(mode)
                    if inst is None:
                        report["index"][identity]["download_blocker"]="Exact index SID unavailable";continue
                    planned=index_plan(report["index"][identity],known,start,stop)
                    for a,b in planned:
                        if total>=args.max_index_windows:break
                        record={"identity":identity,"from":str(a),"to_exclusive":str(b)}
                        report["index_jobs"].append(record)
                        total+=1
                        try:job("/api/dhan/download",{"instruments":[asdict(inst)],"from_date":str(a),"to_date":str(b),"interval":1},record,flush,parallel_live=args.parallel_live)
                        except Failed as exc:
                            record.update(state="source_unavailable",reason=str(exc));flush()
                            break
                audit_all()
                known=set(report["index"]["INDEX:BANKNIFTY"]["complete_dates"])
            else:report["blocked_sources"]["dhan"]="Profile unavailable; renew credentials locally in QuantLab"
        else:known=set(report["index"]["INDEX:BANKNIFTY"]["complete_dates"])
        info=pit_index.status()
        report["membership"]=info
        if info.get("available"):
            a=max(start,date.fromisoformat(info["first_date"]))
            b=min(stop,date.fromisoformat(info["covered_through"])+timedelta(days=1))
            if a<b:
                plan=pit_index.query("banknifty_pit",str(a),str(b),dw.catalog())
                report["membership_gaps"]={"undocumented_banknifty_sessions":sorted(d for d in known if not a.isoformat()<=d<b.isoformat()),
                                           "unresolved_symbols":plan["unresolved"]}
                if not args.audit_only and report.get("dhan_profile",{}).get("ok") and plan["resolved"]:
                    for interval in (1,None):
                        record={"interval":interval,"from":str(a),"to_exclusive":str(b)}
                        report["equity_jobs"].append(record)
                        try:equity_batch(a,b,interval,plan,record,flush,parallel_live=args.parallel_live)
                        except Failed as exc:record.update(state="source_unavailable",reason=str(exc));flush()
                report["equities"]=equity_audit(plan,b,sorted(d for d in known if a.isoformat()<=d<b.isoformat()))
        if not args.audit_only and report.get("dhan_profile",{}).get("ok"):
            # Shorter option scopes during live-parallel work bound each
            # queued job and give other maintenance a chance between jobs.
            for a,b in reversed(list(chunks(option_start,stop,7 if args.parallel_live else 90))):
                record={"from":str(a),"through":str(b-timedelta(days=1)),"wings":args.wings}
                report["options"].append(record)
                try:
                    job("/api/data-manager/options-history/start",
                        {"start_date":record["from"],"end_date":record["through"],"wings":args.wings,"confirm_readonly":True},
                        record,flush,cancel_path="job",parallel_live=args.parallel_live)
                except Failed as exc:record.update(state="source_unavailable",reason=str(exc));flush();break
        report["option_fields_recent_sample"]=option_field_audit(option_start,stop,known);flush()
        if not args.audit_only:
            archive_windows(stop-timedelta(days=args.context_days),stop,root,report,flush,args.alpaca_feed,parallel_live=args.parallel_live)
        report["context_inventory"]=fred.inventory()
        report["configured_context_feeds"]={k:v for k,v in context_feeds.status().items() if k in ("fred_key_configured","alpaca_credentials_configured","twelve_key_configured","fred_catalog")}
        report["live_inventory"]=market_inventory.collect()["sources"]
        known=set().union(*(set(v["complete_dates"]) for v in report["index"].values()))
        for identity,v in report["index"].items():
            v["remaining_planned_windows"]=[[str(a),str(b)] for a,b in index_plan(v,known,start,stop)]
        report["state"]="audit_complete" if args.audit_only else "acquisition_attempt_complete_review_gaps"
    except (Pause,Failed,ValueError,OSError,KeyError,TypeError,RuntimeError) as exc:
        report["state"]="paused_or_blocked"
        report["blocker"]=str(exc)[:220] if isinstance(exc,(Pause,Failed)) else type(exc).__name__
        print("PAUSED:",report["blocker"],flush=True)
    finally:
        flush()
        say("STATE",report["state"]);say("REMAINING SOURCE LIMITATIONS",report["blocked_sources"])
        print("REPORT",dest,flush=True)
    return 0 if report["state"]!="paused_or_blocked" else 2


if __name__=="__main__":
    raise SystemExit(main())
