"""Receipt-time event evidence. No NLP sentiment or inferred release surprises."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
from email.utils import parsedate_to_datetime
from hashlib import sha256
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re
import sqlite3
import xml.etree.ElementTree as ET

from . import market_context as m, advanced_options as ao, shared_market_data, replay_storage

SOURCES={"fed_monetary":"https://www.federalreserve.gov/feeds/press_monetary.xml",
         "fed_banking":"https://www.federalreserve.gov/feeds/press_bcreg.xml",
         "rbi_press":"https://rbi.org.in/pressreleases_rss.xml"}
CALENDAR="fred_calendar"
FEATURE_NAMES=("rbi_rate_news_24h","rbi_banking_news_24h","fed_monetary_news_24h",
               "fed_banking_news_24h","release_dates_today","release_dates_tomorrow",
               "release_dates_next_7d","calendar_missing","rbi_missing","fed_missing")
VERSION="official_context_events_v1"
MAX_BODY=2_000_000
ET_ZONE=ZoneInfo("America/New_York")


def _topic(title):
    if re.search(r"monetary policy|repo rate|interest rate|policy rate|fomc|mpc|liquidity|cash reserve",title,re.I):
        return "rates_liquidity"
    if re.search(r"bank|capital|regulat|credit|supervis|financial stability",title,re.I):
        return "banking"
    return "other"


def _safe_link(url,source):
    if not url or len(url)>1500:
        return ""
    u=urlsplit(url)
    host=u.hostname or ""
    allowed=("rbi.org.in",) if source=="rbi_press" else ("federalreserve.gov",)
    return url if u.scheme=="https" and any(host==h or host.endswith("."+h) for h in allowed) and not u.username and not u.password else ""


def parse_rss(raw,source,received):
    if source not in SOURCES or not 0<len(raw)<=MAX_BODY or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Invalid official RSS payload")
    root=ET.fromstring(raw)
    channel=root.find("channel")
    if channel is None:
        raise ValueError("Unrecognized official RSS channel")
    items=channel.findall("item")
    if len(items)>500:
        raise ValueError("RSS item cap exceeded")
    rows=[]
    for item in items:
        title=" ".join((item.findtext("title") or "").split())[:350]
        link=_safe_link((item.findtext("link") or "").strip(),source)
        try:
            published=parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                raise ValueError("Missing publication offset")
            published=published.astimezone(timezone.utc)
        except (ValueError,TypeError,OverflowError):
            continue
        if not title or published>received:
            continue
        key=sha256((source+"|"+(link or title)+"|"+m._iso(published)).encode()).hexdigest()
        rows.append({"event_id":key,"title":title,"link":link,"topic":_topic(title),
                     "published_utc":m._iso(published)})
    if items and not rows:
        raise ValueError("No timestamp-qualified headlines")
    return list({r["event_id"]:r for r in rows}.values())


def parse_calendar(raw,received):
    if not 0<len(raw)<=MAX_BODY:
        raise ValueError("Invalid calendar payload")
    value=json.loads(raw)
    rows=value.get("release_dates")
    if not isinstance(rows,list) or len(rows)>1000:
        raise ValueError("Unrecognized FRED release dates")
    count=int(value.get("count",len(rows)))
    if count>len(rows):
        raise ValueError("Calendar response truncated; cannot infer empty days")
    today=received.astimezone(ET_ZONE).date()
    out=[]
    for r in rows:
        day=date.fromisoformat(r["date"])
        name=" ".join(str(r["release_name"]).split())[:350]
        # Narrow event universe: selected macro release families; date only.
        if not today<=day<=today+timedelta(days=14) or not re.search(
            r"consumer price|producer price|employment situation|gross domestic product|personal income|retail sales|federal open market|industrial production",name,re.I):
            continue
        out.append({"release_id":int(r["release_id"]),"title":name,"date":day.isoformat()})
    return list({(r["release_id"],r["date"]):r for r in out}.values())


def _setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS market_event_receipts(
        source TEXT NOT NULL,received_utc TEXT NOT NULL,sha256 TEXT NOT NULL,
        raw_text TEXT NOT NULL,events_json TEXT NOT NULL,
        PRIMARY KEY(source,received_utc)
    );
    CREATE INDEX IF NOT EXISTS market_events_by_receipt
      ON market_event_receipts(received_utc,source);
    CREATE TABLE IF NOT EXISTS market_news_observations(
        source TEXT NOT NULL,event_id TEXT NOT NULL,first_received_utc TEXT NOT NULL,
        published_utc TEXT NOT NULL,title TEXT NOT NULL,topic TEXT NOT NULL,link TEXT NOT NULL,
        PRIMARY KEY(source,event_id)
    );
    CREATE INDEX IF NOT EXISTS market_news_by_time
      ON market_news_observations(source,first_received_utc,published_utc);
    """)


def save(source,raw,received):
    if source in SOURCES:
        rows=parse_rss(raw,source,received)
    elif source==CALENDAR:
        rows=parse_calendar(raw,received)
    else:
        raise ValueError("Unsupported event source")
    stamp=m._iso(received);digest=sha256(raw).hexdigest()
    path=shared_market_data.database_path();path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=8)) as db:
        db.execute("PRAGMA busy_timeout=8000");_setup(db)
        with db:
            inserted=db.execute("INSERT OR IGNORE INTO market_event_receipts VALUES(?,?,?,?,?)",
                (source,stamp,digest,raw.decode("utf-8"),json.dumps(rows,sort_keys=True))).rowcount
            if inserted and source in SOURCES:
                db.executemany("INSERT OR IGNORE INTO market_news_observations VALUES(?,?,?,?,?,?,?)",
                    [(source,r["event_id"],stamp,r["published_utc"],r["title"],r["topic"],r["link"]) for r in rows])
    return len(rows)


def _latest(db,source,cutoff,max_age):
    r=replay_storage.fetchone(db,"""SELECT received_utc,sha256,raw_text,events_json FROM market_event_receipts
        WHERE source=? AND received_utc<=? ORDER BY received_utc DESC LIMIT 1""",(source,m._iso(cutoff)))
    if not r:
        return None
    stamp,digest,raw,payload=r
    try:
        if cutoff-m._stamp(stamp)>max_age or sha256(raw.encode()).hexdigest()!=digest:
            return None
        rows=json.loads(payload)
        if not isinstance(rows,list):
            return None
        return {"received_utc":stamp,"sha256":digest,"rows":rows}
    except (TypeError,ValueError,OverflowError):
        return None


def features_at(db,cutoff):
    if not m._exists(db,"market_event_receipts"):
        return None
    receipts={s:_latest(db,s,cutoff,timedelta(minutes=90)) for s in SOURCES}
    calendar=_latest(db,CALENDAR,cutoff,timedelta(hours=36))
    rbi=receipts["rbi_press"] is not None
    fed=receipts["fed_monetary"] is not None and receipts["fed_banking"] is not None
    if not (calendar or rbi or fed):
        return None
    news={}
    for source,receipt in receipts.items():
        if receipt is None:
            continue
        rows=replay_storage.fetchall(db,"""SELECT title,topic,published_utc,first_received_utc,link
          FROM market_news_observations WHERE source=? AND published_utc>=? AND published_utc<=?
          AND first_received_utc<=? ORDER BY published_utc DESC LIMIT 501""",
          (source,m._iso(cutoff-timedelta(hours=24)),m._iso(cutoff),m._iso(cutoff)))
        if len(rows)>500:
            return None
        news[source]=rows
    counts=Counter(x[1] for x in news.get("rbi_press",[]))
    today=cutoff.astimezone(ET_ZONE).date()
    days=[(date.fromisoformat(r["date"])-today).days for r in calendar["rows"]] if calendar else []
    vector=[float(counts["rates_liquidity"]),float(counts["banking"]),
            float(len(news.get("fed_monetary",[]))),float(len(news.get("fed_banking",[]))),
            float(days.count(0)),float(days.count(1)),float(sum(0<=d<=7 for d in days)),
            float(calendar is None),float(not rbi),float(not fed)]
    evidence={"receipts":{s:{k:v for k,v in rec.items() if k!="rows"} for s,rec in receipts.items() if rec},
              "calendar":{k:v for k,v in calendar.items() if k!="rows"} if calendar else None,
              "features":dict(zip(FEATURE_NAMES,vector)),"full_source_coverage":bool(calendar and rbi and fed)}
    # Require each enabled source family for the matched event ablation.
    # Dashboard still displays partial sources.
    return vector,evidence


def snapshot(now=None):
    now=now or m._now()
    out={"as_of_utc":m._iso(now),"sources":{},"headlines":[],"calendar":[],"features":None,
         "warning":"Calendar dates are not exact release times or surprise values. Headlines are official source receipts, not sentiment predictions. Missing source coverage is not evidence of no news."}
    if not shared_market_data.database_path().is_file():
        return out
    with closing(ao._read_database()) as db:
        if not m._exists(db,"market_event_receipts"):
            return out
        for source in (*SOURCES,CALENDAR):
            latest=_latest(db,source,now,timedelta(days=14))
            out["sources"][source]={"received_utc":latest["received_utc"],"sha256":latest["sha256"]} if latest else None
            if source==CALENDAR and latest:
                out["calendar"]=latest["rows"]
        rows=replay_storage.fetchall(db,"""SELECT source,title,topic,published_utc,first_received_utc,link
          FROM market_news_observations WHERE first_received_utc<=? ORDER BY published_utc DESC LIMIT 80""",(m._iso(now),))
        out["headlines"]=[dict(zip(("source","title","topic","published_utc","first_received_utc","link"),r)) for r in rows]
        f=features_at(db,now)
        if f:
            out["features"]=f[1]
    return out
