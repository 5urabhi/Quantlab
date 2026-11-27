"""Preflight contextual CPR research without replaying option trajectories."""
from datetime import date, datetime, timedelta, timezone
import argparse
import json
import sqlite3

from dotenv import load_dotenv
from workstation_api import cpr_context_archive as archive, cpr_context_features as cx
from workstation_api import cpr_hybrid_research as r, historical_alpha as h
from workstation_api import context_feeds as feeds, alpha_retraining, service, pit_index
from workstation_api import cpr_alpaca_archive as alpaca


def main():
    today=datetime.now(h.IST).date()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-date",default=(today-timedelta(days=100)).isoformat())
    p.add_argument("--to-date",default=today.isoformat(),help="End exclusive")
    p.add_argument("--context-batch",default="auto")
    p.add_argument("--fixed-panel",action="store_true",help="Audit separate fixed major-bank panel")
    p.add_argument("--hold",type=int,choices=r.HOLDS,default=60)
    p.add_argument("--mode",choices=("receipt","archive"),default="archive")
    p.add_argument("--fetch-fred",action="store_true",help="Opt in to local FRED/ALFRED vintage requests")
    p.add_argument("--fetch-alpaca",action="store_true",help="Opt in to historical US-listed ETF proxy requests")
    p.add_argument("--alpaca-feed",choices=("iex","sip"),default="iex")
    p.add_argument("--confirm-reviewed",action="store_true",help="Confirm reviewed provider permissions and conservative vintage-date availability assumption")
    a=p.parse_args()
    try:
        start,stop=map(date.fromisoformat,(a.from_date,a.to_date))
        if not 0<(stop-start).days<=120 or stop>today:
            raise ValueError("Use a completed historical range up to 120 calendar days")
        if (a.fetch_fred or a.fetch_alpaca) and not alpha_retraining.safe_window(datetime.now(timezone.utc)):
            raise ValueError("External context backfill remains outside Indian market priority hours; saved-source preflight is available now")
        if (a.fetch_fred or a.fetch_alpaca) and (not a.confirm_reviewed or a.mode!="archive"):
            raise ValueError("Historical backfill requires --confirm-reviewed and archive mode")
        load_dotenv(service.ROOT/".env",override=False)
        index,_,failures=h.shared_index_sources(start-timedelta(days=7),stop,[h.MAX_TOTAL])
        ordered=sorted(index)
        dates=[d for d in ordered if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-sum(r.SPLITS):]
        signals=[]
        for day in dates:
            i=ordered.index(day)
            if not i:
                continue
            prev=ordered[i-1]
            rows,_=r._signals(day,index[day],prev,index[prev],frame=5,hold=a.hold,
                               max_signals=375,entry_mode="regime_scan")
            signals.extend(rows)
        if a.fetch_fred:
            print("FRED archive:",json.dumps(archive.backfill(start,stop,confirmed=True)),flush=True)
        if a.fetch_alpaca:
            print("Alpaca archive:",json.dumps(alpaca.backfill(start,stop,feed=a.alpaca_feed,confirmed=True)),flush=True)
        status=feeds.status()
        print("Feed configuration:",json.dumps({"enabled":status["config"]["enabled"],
                    "fred_key_configured":status["fred_key_configured"],
                    "twelve_key_configured":status["twelve_key_configured"],
                    "alpaca_credentials_configured":bool(alpaca.credentials())}),flush=True)
        try:
            membership=pit_index.status()
            print("Membership source:",json.dumps({k:membership.get(k) for k in ("available","first_date","covered_through","synced_utc")}),flush=True)
        except (OSError,ValueError,KeyError,TypeError):
            print("Membership source: unavailable",flush=True)
        print("Stored context inventory:",json.dumps(archive.inventory()),flush=True)
        print("Reserved sessions:",len(dates),"Opportunity anchors:",len(signals),flush=True)
        audit=cx.attach(signals,mode=a.mode,batch_id=a.context_batch,fixed_panel=a.fixed_panel)
        summary={k:v for k,v in audit.items() if k not in ("anchors","bank_feature_names",
            "global_feature_names","factor_receipt_sha256")}
        print("Context readiness:",json.dumps(summary),flush=True)
        split=[dates[:30],dates[30:40],dates[40:60]]
        scopes=["constituents","global","combined"]+list(cx.PANEL_SCOPES if a.fixed_panel else ())
        print("Split matched coverage:",json.dumps({
            name:{scope:sum(all(x in s.get("context_vectors",{}) for x in cx.SCOPE_GROUPS[scope])
                 for s in signals if s["session"] in set(ds)) for scope in scopes}
            for name,ds in zip(("train","validation","holdout"),split)}))
        print("No option replay, orders, or model promotion performed.")
        return 0
    except (ValueError,OSError,sqlite3.Error) as exc:
        print("Context preflight unavailable:",type(exc).__name__)
        if isinstance(exc,ValueError) and str(exc).startswith(("Use a completed","External context","Historical backfill","No usable original")):
            print(str(exc))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
