"""Import approved JForex exports into the existing QuantLab store; inspect features."""
import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sqlite3

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
    if args.action=="import":
        result=g.import_directory(args.inbox,mode=args.mode,
            confirm_reviewed=args.confirm_reviewed,archive_lag_minutes=args.archive_lag_minutes,
            max_new_files=args.max_new_files)
    elif args.action=="inventory":
        result=g.inventory()
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
