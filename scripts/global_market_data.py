"""Use existing market feeds and import authorized CSV exports; no JForex requirement."""
import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sqlite3
from dotenv import load_dotenv

from workstation_api import service, shared_market_data, global_market_archive as g


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shared-root",type=Path,default=service.ROOT)
    sub=p.add_subparsers(dest="action",required=True)
    imp=sub.add_parser("import")
    imp.add_argument("--inbox",type=Path,required=True)
    imp.add_argument("--mode",choices=("receipt","archive"),default="receipt")
    imp.add_argument("--archive-lag-minutes",type=int)
    imp.add_argument("--max-new-files",type=int,default=20)
    imp.add_argument("--confirm-reviewed",action="store_true")
    direct=sub.add_parser("import-export",help="Import a reviewed direct BID CSV (no JForex)")
    direct.add_argument("--file",type=Path,required=True)
    direct.add_argument("--instrument",choices=tuple(g.INSTRUMENTS),required=True)
    direct.add_argument("--minutes",type=int,choices=(1,5),default=5)
    direct.add_argument("--mode",choices=("receipt","archive"),default="receipt")
    direct.add_argument("--archive-lag-minutes",type=int)
    direct.add_argument("--confirm-reviewed",action="store_true")
    existing=sub.add_parser("enable-existing",help="Enable already-configured FRED and Alpaca daily feeds")
    existing.add_argument("--confirm-reviewed",action="store_true")
    sub.add_parser("inventory")
    enable=sub.add_parser("enable-live")
    enable.add_argument("--inbox",type=Path,required=True)
    enable.add_argument("--confirm-reviewed",action="store_true")
    sub.add_parser("disable-live")
    feat=sub.add_parser("features")
    feat.add_argument("--date",type=date.fromisoformat,required=True)
    feat.add_argument("--cutoff",choices=("09:00","09:10","09:15"),default="09:10")
    feat.add_argument("--resolution",choices=("1m","5m"),default="5m")
    feat.add_argument("--mode",choices=("archive","receipt"),default="archive")
    args=p.parse_args()
    root=args.shared_root.resolve()
    if not (root/"data").is_dir():
        p.error("Original shared data directory is missing")
    service.DATA=root/"data"
    load_dotenv(root/".env",override=False)
    if args.action=="import":
        result=g.import_directory(args.inbox,mode=args.mode,
            confirm_reviewed=args.confirm_reviewed,archive_lag_minutes=args.archive_lag_minutes,
            max_new_files=args.max_new_files)
    elif args.action=="import-export":
        from workstation_api import recorder_storage
        path=args.file.expanduser()
        if not args.confirm_reviewed:
            p.error("Confirm exact BID instrument, UTC timestamps, resolution and authorized storage")
        if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=g.MAX_BYTES:
            p.error("Select a bounded original CSV file")
        if not recorder_storage.allow("global_market_bars"):
            p.error("Shared disk reserve; no data imported")
        result=g.import_direct_csv(path.read_bytes(),symbol=args.instrument,minutes=args.minutes,
            mode=args.mode,confirm_reviewed=True,archive_lag_minutes=args.archive_lag_minutes)
        if result["inserted"]:
            recorder_storage.saved("global_market_bars",g._iso(g._now()),count=result["inserted"])
    elif args.action=="enable-existing":
        from workstation_api import context_feeds
        if not args.confirm_reviewed:
            p.error("Review existing FRED/Alpaca permission and archive assumptions")
        status=context_feeds.status()
        if status["configuration_error"]:
            p.error("Existing context configuration is invalid; no changes made")
        config=status["config"]
        # Preserve explicit provider mappings and selected Alpaca feed.
        # Never overwrite an existing Twelve mapping with a FRED series.
        conflicts=set(context_feeds.FRED_SERIES)&{r["factor"] for r in config["mappings"]}
        if status["fred_key_configured"] and not conflicts:
            config["fred"]=True
        if status["alpaca_credentials_configured"]:
            config["alpaca"]=True
        if not (status["fred_key_configured"] or status["alpaca_credentials_configured"]):
            p.error("Neither existing key was found; no configuration changed")
        config["enabled"]=True
        result=context_feeds.configure(config,True)
        result["note"]="Existing authorized daily sources enabled. The running QuantLab context worker reads this configuration; no external brokerage installation. Asian ETF proxies are previous US-market observations, not local opening prices."
    elif args.action=="inventory":
        from workstation_api import cpr_context_archive, context_feeds
        result={"global_intraday_proxies":g.inventory(),"existing_context":cpr_context_archive.inventory(),
                "configured_sources":context_feeds.status()}
    elif args.action=="enable-live":
        result=g.configure_live_inbox(args.inbox,confirm_reviewed=args.confirm_reviewed)
    elif args.action=="disable-live":
        result=g.disable_live_inbox()
    else:
        path=shared_market_data.database_path()
        if not path.is_file():
            p.error("No canonical database")
        cutoff=datetime.combine(args.date,time.fromisoformat(args.cutoff),g.IST)
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            result=g.reference_features(db,args.date,cutoff,mode=args.mode,resolution=args.resolution)
    print(json.dumps(result,indent=2))
    if args.action=="import" and any(r["state"]=="rejected_or_paused" or r["state"]=="rejected" for r in result["files"]):
        return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
