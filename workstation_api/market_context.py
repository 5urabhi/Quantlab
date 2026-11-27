"""Underlying-first market context on the canonical shared market store.

Imported values are user-reviewed normalized evidence, not independently
verified feed data. Archive mode trusts documented availability timestamps
for retrospective research; receipt mode additionally enforces actual import
time. Neither path makes an order or contacts a provider.
"""
from bisect import bisect_right, insort
from collections import defaultdict, Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
from hashlib import sha256
import csv
import io
import json
import math
import sqlite3

from . import advanced_options as ao, constituent_prospective as p
from . import replay_storage, shared_market_data

VERSION="market_context_v3"
MAX_IMPORT_BYTES=5_000_000
MAX_IMPORT_ROWS=50000
MAX_READ_ROWS=350000
MAX_CHAIN_AGE=90
OPTION_BAND=.03
# kind: daily level return in bps, daily yield change in bps, intraday
# return in bps, or signed daily report level (fixed scale, not inferred).
FACTORS={
    "SP500_CLOSE":("daily_return","global_equity","S&P 500 previous available close"),
    "NASDAQ_CLOSE":("daily_return","global_equity","Nasdaq Composite previous available close"),
    "US_BANKS_CLOSE":("daily_return","global_equity","US banking index / ETF close (consistent series)"),
    "NIKKEI_CLOSE":("daily_return","asia","Nikkei 225 close"),
    "HANGSENG_CLOSE":("daily_return","asia","Hang Seng close"),
    "SHANGHAI_CLOSE":("daily_return","asia","Shanghai Composite close"),
    "EUROPE_BANKS_CLOSE":("daily_return","global_equity","European bank index close"),
    "US_VIX_CLOSE":("daily_return","macro","US VIX close"),
    "USDINR_CLOSE":("daily_return","macro","USD/INR close (INR per USD)"),
    "BRENT_CLOSE":("daily_return","macro","Brent benchmark close"),
    "US10Y":("daily_yield","macro","US 10-year yield, percentage points"),
    "INDIA10Y":("daily_yield","macro","India 10-year government yield, percentage points"),
    "GIFT_NIFTY":("intraday_return","asia","GIFT NIFTY continuous consistent price series"),
    "NIKKEI":("intraday_return","asia","Nikkei 225 intraday"),
    "HANGSENG":("intraday_return","asia","Hang Seng intraday"),
    "SHANGHAI":("intraday_return","asia","Shanghai Composite intraday"),
    "EUROPE_BANKS":("intraday_return","global_equity","European bank index intraday"),
    "SP500_FUT":("intraday_return","global_equity","S&P 500 futures consistent series"),
    "NASDAQ_FUT":("intraday_return","global_equity","Nasdaq futures consistent series"),
    "USDINR":("intraday_return","macro","USD/INR intraday (INR per USD)"),
    "BRENT":("intraday_return","macro","Brent intraday consistent series"),
    "INDIA_VIX":("intraday_return","domestic","India VIX intraday level"),
    "FII_CASH_NET_CR":("daily_flow","participants","FII/FPI cash net buy, INR crore"),
    "DII_CASH_NET_CR":("daily_flow","participants","DII cash net buy, INR crore"),
}
# US-listed ETFs are explicit proxy series, not the index/futures levels
# and not live Asian exchange prices. Keep their identities independent.
ALPACA_PROXIES={
    "US_SPY_ETF_CLOSE":("SPY","global_equity","US large-cap ETF price"),
    "US_QQQ_ETF_CLOSE":("QQQ","global_equity","Nasdaq-100 ETF price"),
    "US_KBE_ETF_CLOSE":("KBE","global_equity","US bank ETF price"),
    "JAPAN_EWJ_ETF_CLOSE":("EWJ","asia","US-listed Japan equity ETF price proxy"),
    "CHINA_FXI_ETF_CLOSE":("FXI","asia","US-listed China equity ETF price proxy"),
    "US_TLT_ETF_CLOSE":("TLT","macro","US long Treasury ETF price proxy"),
    "GOLD_GLD_ETF_CLOSE":("GLD","macro","Gold ETF price proxy"),
}
for key,(_,group,description) in ALPACA_PROXIES.items():
    FACTORS[key]=("daily_return",group,description)
# US ETF five-minute bars are opportunistic prospective evidence; they
# are neither futures nor a substitute for Asian exchange/GIFT data.
ALPACA_INTRADAY_PROXIES={
    "US_SPY_ETF_5M":("SPY","global_equity","US large-cap ETF five-minute price"),
    "US_QQQ_ETF_5M":("QQQ","global_equity","Nasdaq-100 ETF five-minute price"),
    "US_KBE_ETF_5M":("KBE","global_equity","US bank ETF five-minute price"),
}
for key,(_,group,description) in ALPACA_INTRADAY_PROXIES.items():
    FACTORS[key]=("intraday_return",group,description)
for category in ("FII","DII","CLIENT","PRO"):
    for position in ("INDEX_FUT_NET","INDEX_CALL_NET","INDEX_PUT_NET"):
        FACTORS[category+"_"+position]=("daily_position","participants",
            category+" aggregate index derivatives net long minus short contracts: "+position)
        FACTORS[category+"_"+position+"_VOL"]=("daily_position","participants",
            category+" aggregate index derivatives long-side minus short-side traded contracts: "+position)

GLOBAL_GROUPS=("global_equity","asia","macro")
FEATURE_NAMES=tuple(v for key in FACTORS for v in
                    (key.lower()+"_value",key.lower()+"_change",key.lower()+"_age_hours",key.lower()+"_missing"))
DOMESTIC_NAMES=("nifty50_30m_bps","bank_minus_nifty50_30m_bps","nifty50_missing")
OPTION_NAMES=("oi_imbalance","volume_imbalance","oi_change_put_minus_call",
              "volume_increment_imbalance","atm_iv_pct","otm_put_minus_call_iv",
              "call_oi_concentration","put_oi_concentration","days_to_expiry",
              "paired_strikes","oi_change_missing","volume_increment_missing","iv_skew_missing",
              "same_atm_iv_change_pct_points","atm_iv_change_missing")
HEADER=("factor","event_utc","available_utc","value")


def _now():
    return datetime.now(timezone.utc)


def _stamp(s):
    if not isinstance(s,str):
        raise ValueError("Timestamp must be a timezone-aware ISO value")
    t=datetime.fromisoformat(s.replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("Timezone offset is required")
    return t.astimezone(timezone.utc)


def _iso(t):
    return p._iso(t)


def _finite(v):
    if type(v) not in (int,float) or not math.isfinite(v):
        raise ValueError("Invalid numeric evidence")
    return float(v)


def _setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS market_context_imports(
      receipt_sha256 TEXT PRIMARY KEY, source TEXT NOT NULL, mode TEXT NOT NULL,
      imported_utc TEXT NOT NULL, normalized_csv TEXT NOT NULL, row_count INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS market_context_observations(
      factor TEXT NOT NULL, event_utc TEXT NOT NULL, available_utc TEXT NOT NULL,
      value REAL NOT NULL, receipt_sha256 TEXT NOT NULL REFERENCES market_context_imports(receipt_sha256),
      PRIMARY KEY(factor,event_utc,available_utc,receipt_sha256)
    );
    CREATE INDEX IF NOT EXISTS context_available
      ON market_context_observations(available_utc,factor,event_utc);
    CREATE INDEX IF NOT EXISTS context_factor_receipt
      ON market_context_observations(factor,receipt_sha256);
    CREATE TABLE IF NOT EXISTS market_context_raw_reports(
      receipt_sha256 TEXT PRIMARY KEY REFERENCES market_context_imports(receipt_sha256),
      original_sha256 TEXT NOT NULL, original_csv TEXT NOT NULL
    );
    """)


def catalog():
    return [{"factor":key,"kind":kind,"group":group,"description":desc}
            for key,(kind,group,desc) in FACTORS.items()]


def parse_csv(text,now):
    if not isinstance(text,str) or not 0<len(text.encode())<=MAX_IMPORT_BYTES:
        raise ValueError("Provide a normalized CSV up to 5 MB")
    reader=csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if tuple(reader.fieldnames or [])!=HEADER:
        raise ValueError("CSV header must be factor,event_utc,available_utc,value")
    rows=[];seen=set()
    for r in reader:
        if len(rows)>=MAX_IMPORT_ROWS or None in r:
            raise ValueError("Import row limit or malformed columns")
        factor=r["factor"]
        if factor not in FACTORS:
            raise ValueError("Unsupported factor: "+str(factor)[:80])
        event,available=_stamp(r["event_utc"]),_stamp(r["available_utc"])
        if not event<=available<=now:
            raise ValueError("Require event <= actual source availability <= import time")
        kind=FACTORS[factor][0]
        try:
            value=float(r["value"])
        except (TypeError,ValueError) as exc:
            raise ValueError("Missing or invalid factor value") from exc
        if not math.isfinite(value) or abs(value)>1e12 or (kind in ("daily_return","intraday_return") and value<=0):
            raise ValueError("Invalid factor level")
        key=(factor,_iso(event),_iso(available))
        if key in seen:
            raise ValueError("Duplicate factor/event/availability in import")
        seen.add(key)
        rows.append((*key,value))
    if not rows:
        raise ValueError("CSV contains no observations")
    return rows


def ingest(csv_text,source,mode,confirm_reviewed,*,now=None,original_report=None):
    if confirm_reviewed is not True or mode not in ("receipt","archive") or not isinstance(source,str) or not 3<=len(source.strip())<=300:
        raise ValueError("Review the authorized source, actual availability and chosen import mode")
    now=now or _now()
    rows=parse_csv(csv_text,now)
    source=source.strip()
    digest=sha256(json.dumps([source,mode,csv_text,original_report],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    path=shared_market_data.database_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=8)) as db:
        db.execute("PRAGMA busy_timeout=8000")
        db.execute("PRAGMA foreign_keys=ON")
        _setup(db)
        with db:
            db.execute("BEGIN IMMEDIATE")
            # One consistent instrument/provider series per factor.
            for factor in sorted({r[0] for r in rows}):
                previous=db.execute("""SELECT DISTINCT i.source FROM market_context_observations o
                  JOIN market_context_imports i USING(receipt_sha256) WHERE o.factor=?""",(factor,)).fetchall()
                if any(r[0]!=source for r in previous):
                    raise ValueError("Source differs from existing series for "+factor)
            inserted=db.execute("INSERT OR IGNORE INTO market_context_imports VALUES(?,?,?,?,?,?)",
                (digest,source,mode,_iso(now),csv_text,len(rows))).rowcount
            if inserted:
                db.executemany("INSERT INTO market_context_observations VALUES(?,?,?,?,?)",
                    [(*r,digest) for r in rows])
                if original_report is not None:
                    db.execute("INSERT INTO market_context_raw_reports VALUES(?,?,?)",(digest,
                        sha256(original_report.encode()).hexdigest(),original_report))
    return {"receipt_sha256":digest,"rows":len(rows),"inserted":bool(inserted),"mode":mode,
            "source":source,"factor_counts":dict(Counter(r[0] for r in rows)),
            "independently_verified":False,
            "note":"Archive availability is reviewed but not independently verified. Receipt mode cannot backdate the import."}


def ingest_participant(csv_text,report_day,available_utc,report_type,mode,confirm_reviewed,*,now=None,source_identity='NSE'):
    """Normalize reviewed NSE report long/short sides, preserving raw CSV."""
    from . import nse_session_policy as sessions
    if not isinstance(csv_text,str) or not 0<len(csv_text.encode())<=64_000:
        raise ValueError("Provide an original participant CSV up to 64 KB")
    if report_type not in ("oi","volume"):
        raise ValueError("Choose open interest or trading volume")
    day=date.fromisoformat(report_day)
    event=datetime.combine(day,sessions.derivatives_close(day),p.live_market.IST).astimezone(timezone.utc)
    known=_stamp(available_utc)
    now=now or _now()
    if day.weekday()>=5 or not event<=known<=now:
        raise ValueError("Review session date and report availability after market close")
    raw=list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
    required=("client type","future index long","future index short",
              "option index call long","option index call short","option index put long","option index put short")
    header_idx=None
    for i,r in enumerate(raw[:5]):
        cols=[" ".join(x.strip().lower().split()) for x in r]
        if all(k in cols for k in required):
            if any(cols.count(k)!=1 for k in required):
                raise ValueError("Ambiguous participant columns")
            header_idx=i;positions={k:cols.index(k) for k in required};break
    if header_idx is None:
        raise ValueError("Missing official NSE participant report headers")
    data={}
    for row in raw[header_idx+1:]:
        if not row or not any(x.strip() for x in row):
            continue
        if len(row)<=max(positions.values()):
            raise ValueError("Truncated participant row")
        category=row[positions["client type"]].strip().upper()
        if category not in ("FII","DII","CLIENT","PRO","TOTAL") or category in data:
            raise ValueError("Unexpected or duplicate participant category")
        nums=[]
        for k in required[1:]:
            token=row[positions[k]].strip().replace(",","")
            if not token.isdigit():
                raise ValueError("Expected nonnegative integer contract counts")
            nums.append(int(token))
        data[category]=nums
    if set(data)!={"FII","DII","CLIENT","PRO","TOTAL"}:
        raise ValueError("Require all four categories and TOTAL row")
    if any(sum(data[c][i] for c in ("FII","DII","CLIENT","PRO"))!=data["TOTAL"][i] for i in range(6)):
        raise ValueError("Participant counts do not reconcile to TOTAL")
    out=io.StringIO();writer=csv.writer(out,lineterminator="\n")
    writer.writerow(HEADER)
    suffix="_VOL" if report_type=="volume" else ""
    for c in ("FII","DII","CLIENT","PRO"):
        for i,name in enumerate(("INDEX_FUT_NET","INDEX_CALL_NET","INDEX_PUT_NET")):
            writer.writerow((c+"_"+name+suffix,_iso(event),_iso(known),data[c][2*i]-data[c][2*i+1]))
    if not isinstance(source_identity,str) or not 3<=len(source_identity.strip())<=200:
        raise ValueError("Invalid reviewed participant source identity")
    return ingest(out.getvalue(),source_identity.strip()+" participant-wise "+report_type,mode,confirm_reviewed,
                  now=now,original_report=csv_text)


def _exists(db,table):
    return bool(replay_storage.fetchone(db,"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)))


class Timeline:
    """As-of two latest distinct event times; revisions never backdate.

    Every step captures the latest and preceding event available at that
    information time. Older late reports cannot replace a newer event.
    """
    def __init__(self,rows):
        self.times=[];self.snapshots=[]
        known={};events=[]
        for available,event,value,source,digest in sorted(rows,key=lambda r:(r[0],r[1],r[3],r[4])):
            if event not in known:
                insort(events,event)
            old=known.get(event)
            # An ambiguous simultaneous conflicting revision is unavailable.
            if old and old[0]==available and old[1]!=value:
                known[event]=(available,None,source,digest)
            else:
                known[event]=(available,value,source,digest)
            self.times.append(available)
            self.snapshots.append(tuple((e,*known[e]) for e in reversed(events[-2:])))

    def at(self,cutoff):
        pos=bisect_right(self.times,cutoff)-1
        return self.snapshots[pos] if pos>=0 else ()


def load_timelines(db,start,stop,mode):
    if mode not in ("receipt","archive"):
        raise ValueError("Unknown source availability mode")
    if not _exists(db,"market_context_observations"):
        return {},{"rows":0,"ambiguous_factors":[]}
    mode_filter=" AND i.mode='receipt' AND i.imported_utc<=?" if mode=="receipt" else ""
    args=[_iso(stop),_iso(start-timedelta(days=10)),_iso(stop)]
    if mode=="receipt":
        args.append(_iso(stop))
    args.append(MAX_READ_ROWS+1)
    rows=replay_storage.fetchall(db,"""SELECT o.factor,o.event_utc,o.available_utc,o.value,
         i.source,i.receipt_sha256,i.imported_utc,i.mode
         FROM market_context_observations o JOIN market_context_imports i USING(receipt_sha256)
         WHERE o.available_utc<=? AND o.event_utc>=? AND o.event_utc<=?"""+mode_filter+
         " ORDER BY o.factor,o.available_utc,o.event_utc LIMIT ?",tuple(args))
    if len(rows)>MAX_READ_ROWS:
        raise ValueError("Market context evidence exceeds bounded study read; reduce archive frequency")
    factors=defaultdict(list);sources=defaultdict(set)
    for key,event,available,value,source,digest,imported,import_mode in rows:
        if key not in FACTORS or import_mode not in ("receipt","archive"):
            continue
        if mode=="receipt" and import_mode!="receipt":
            continue
        try:
            event,available,imported=map(_stamp,(event,available,imported))
            value=_finite(value)
            if not event<=available<=imported:
                continue
            known=max(available,imported) if import_mode=="receipt" else available
            if known>stop:
                continue
            factors[key].append((known,event,value,source,digest))
            sources[key].add(source)
        except (TypeError,ValueError,OverflowError):
            continue
    ambiguous=sorted(k for k,s in sources.items() if len(s)>1)
    return {k:Timeline(v) for k,v in factors.items() if k not in ambiguous},{"rows":sum(map(len,factors.values())),"ambiguous_factors":ambiguous}


def factor_at(timelines,cutoff):
    vector=[];details={};groups=set()
    for key,(kind,group,_) in FACTORS.items():
        t=timelines.get(key)
        rows=t.at(cutoff) if t else ()
        values=None
        if rows:
            event,known,level,source,digest=rows[0]
            age=(cutoff-event).total_seconds()/3600
            max_age=10/60 if kind=="intraday_return" else 24*7
            if 0<=age<=max_age and level is not None:
                prev=(t.at(cutoff-timedelta(minutes=30)) if kind=="intraday_return" else rows[1:])
                if prev:
                    pe,pk,pv,prior_source,prior_digest=prev[0]
                    gap=(event-pe).total_seconds()/3600
                    anchor_age=(cutoff-timedelta(minutes=30)-pe).total_seconds()/3600
                    if pv is not None and 0<gap<=24*7 and (kind!="intraday_return" or 0<=anchor_age<=10/60):
                        if kind.endswith("return") and min(pv,level)>0:
                            change=10000*(level/pv-1)
                            # Keep level only for volatility measures; price
                            # levels across indices are nonstationary scales.
                            stable_level=level if key in ("US_VIX_CLOSE","INDIA_VIX") else 0.
                            values=(stable_level,change,age,0.)
                        elif kind=="daily_yield":
                            values=(level,100*(level-pv),age,0.)
                        elif kind in ("daily_flow","daily_position"):
                            scale=1000. if kind=="daily_flow" else 100000.
                            values=(level/scale,(level-pv)/scale,age,0.)
            if values is not None and all(math.isfinite(x) for x in values):
                details[key]={"state":"available","level":level,"change_feature":values[1],
                    "event_utc":_iso(event),"known_utc":_iso(known),"age_hours":age,
                    "source":source,"receipt_sha256":digest,"group":group,
                    "prior_event_utc":_iso(pe),"prior_known_utc":_iso(pk),
                    "prior_source":prior_source,"prior_receipt_sha256":prior_digest}
                groups.add(group)
            else:
                values=None
                details[key]={"state":"stale_or_missing_anchor","event_utc":_iso(event),"age_hours":age}
        if values is None:
            values=(0.,0.,0.,1.)
            details.setdefault(key,{"state":"unavailable"})
        vector.extend(values)
    # Require evidence from three distinct economic groups rather than
    # counting several highly correlated US equity series as diversification.
    return vector,details,all(g in groups for g in GLOBAL_GROUPS)


def _chain(db,cutoff,expiry=None):
    if not _exists(db,"option_chain_observations"):
        return None
    session=p._session(cutoff).date().isoformat()
    args=[session,(cutoff-timedelta(seconds=MAX_CHAIN_AGE)).isoformat(),cutoff.isoformat()]
    # Current writer uses UTC isoformat; query exact expiry only for the
    # earlier observation. No roll across different expiry series.
    extra=""
    if expiry is not None:
        extra=" AND expiry=?"
        args.append(expiry)
    r=replay_storage.fetchone(db,"""SELECT expiry,captured_utc,normalized_json,snapshot_sha256
        FROM option_chain_observations WHERE underlying='BANKNIFTY' AND expiry>=?
        AND captured_utc>=? AND captured_utc<=?"""+extra+" ORDER BY expiry,captured_utc DESC LIMIT 1",tuple(args))
    if not r:
        return None
    expiry,stamp,raw,digest=r
    try:
        captured=_stamp(stamp)
        if not isinstance(raw,str) or sha256(raw.encode()).hexdigest()!=digest or not cutoff-timedelta(seconds=MAX_CHAIN_AGE)<=captured<=cutoff:
            return None
        chain=json.loads(raw)
        if chain["underlying"]!="BANKNIFTY" or chain["expiry"]!=expiry or chain["received_utc"]!=stamp or chain["read_only"] is not True:
            return None
        if p._session(captured).date()!=p._session(cutoff).date():
            return None
        return chain,digest
    except (KeyError,ValueError,TypeError,OverflowError):
        return None


def _pairs(chain,spot):
    pairs=defaultdict(dict);duplicates=set()
    for c in chain["contracts"]:
        try:
            strike=_finite(c["strike"])
            side=c["option_type"]
            if abs(strike/spot-1)>OPTION_BAND or side not in ("CE","PE") or c["expiry"]!=chain["expiry"]:
                continue
            if c["contract_master_verified"] is not True or c["quote_valid"] is not True or not c["identity"]:
                continue
            if not isinstance(c["identity"],str) or not c["identity"].startswith("NSE_FNO:"):
                continue
            for field in ("oi","volume"):
                if type(c[field]) is not int or c[field]<0:
                    raise ValueError("Invalid OI or volume")
            if type(c["lot_size"]) is not int or c["lot_size"]<=0:
                continue
            if side in pairs[strike]:
                duplicates.add(strike)
            pairs[strike][side]=c
        except (ValueError,KeyError,TypeError,OverflowError):
            continue
    identity_counts=Counter(c["identity"] for v in pairs.values() for c in v.values())
    return {k:v for k,v in pairs.items() if k not in duplicates and set(v)=={"CE","PE"}
            and v["CE"]["lot_size"]==v["PE"]["lot_size"]
            and all(identity_counts[v[s]["identity"]]==1 for s in ("CE","PE"))}


def _imb(put,call):
    total=put+call
    return (put-call)/total if total>0 else None


def option_features(current,prior=None):
    """Paired near-spot OI and IV are crowding proxies, not dealer direction."""
    try:
        chain,digest=current
        spot=_finite(chain["underlying_spot"])
        if spot<=0:
            return None
        pairs=_pairs(chain,spot)
        if len(pairs)<5:
            return None
        sums=lambda field,side:sum(v[side][field] for v in pairs.values())
        co,po,cv,pv=sums("oi","CE"),sums("oi","PE"),sums("volume","CE"),sums("volume","PE")
        oi,vol=_imb(po,co),_imb(pv,cv)
        if oi is None or vol is None or co<=0 or po<=0:
            return None
        atm=min(pairs,key=lambda k:(abs(k-spot),k))
        def iv(c):
            v=c.get("iv")
            return float(v) if type(v) in (int,float) and math.isfinite(v) and 0<v<=500 else None
        atm_values=[iv(pairs[atm][s]) for s in ("CE","PE")]
        if any(v is None for v in atm_values):
            return None
        below=[k for k in pairs if k<spot]
        above=[k for k in pairs if k>spot]
        skew=None
        if below and above:
            pi=iv(pairs[min(below,key=lambda k:abs(k-.99*spot))]["PE"])
            ci=iv(pairs[min(above,key=lambda k:abs(k-1.01*spot))]["CE"])
            if pi is not None and ci is not None:
                skew=pi-ci
        oi_change=volume_change=atm_change=None;matched=0
        if prior is not None and prior[0]["expiry"]==chain["expiry"]:
            old=_pairs(prior[0],spot)
            common=[k for k,v in pairs.items() if k in old and all(v[s]["identity"]==old[k][s]["identity"] and
                        v[s]["lot_size"]==old[k][s]["lot_size"] for s in ("CE","PE"))]
            matched=len(common)
            if atm in common:
                old_iv=[iv(old[atm][side]) for side in ("CE","PE")]
                if all(v is not None for v in old_iv):
                    atm_change=(sum(atm_values)-sum(old_iv))/2
            if matched>=5 and matched>=.8*len(pairs):
                previous_oi=sum(old[k][s]["oi"] for k in common for s in ("CE","PE"))
                if previous_oi>0:
                    oi_change=(sum(pairs[k]["PE"]["oi"]-old[k]["PE"]["oi"] for k in common)-
                               sum(pairs[k]["CE"]["oi"]-old[k]["CE"]["oi"] for k in common))/previous_oi
                increments={s:[pairs[k][s]["volume"]-old[k][s]["volume"] for k in common] for s in ("CE","PE")}
                if all(v>=0 for values in increments.values() for v in values):
                    volume_change=_imb(sum(increments["PE"]),sum(increments["CE"]))
        ce_strike=max(pairs,key=lambda k:(pairs[k]["CE"]["oi"],-abs(k-spot)))
        pe_strike=max(pairs,key=lambda k:(pairs[k]["PE"]["oi"],-abs(k-spot)))
        day=p._session(_stamp(chain["received_utc"])).date()
        dte=(date.fromisoformat(chain["expiry"])-day).days
        if dte<0:
            return None
        vector=[oi,vol,oi_change if oi_change is not None else 0.,volume_change if volume_change is not None else 0.,
                sum(atm_values)/2,skew if skew is not None else 0.,pairs[ce_strike]["CE"]["oi"]/co,
                pairs[pe_strike]["PE"]["oi"]/po,float(dte),float(len(pairs)),
                float(oi_change is None),float(volume_change is None),float(skew is None),
                atm_change if atm_change is not None else 0.,float(atm_change is None)]
        if not all(math.isfinite(v) for v in vector):
            return None
        return vector,{"expiry":chain["expiry"],"received_utc":chain["received_utc"],"sha256":digest,
                "prior_received_utc":prior[0]["received_utc"] if prior else None,
                "prior_sha256":prior[1] if prior else None,"spot":spot,"paired_strikes":len(pairs),"matched_prior_strikes":matched,
                "put_call_oi_ratio":po/co,"put_call_volume_ratio":pv/cv if cv>0 else None,
                "call_oi":co,"put_oi":po,"call_volume":cv,"put_volume":pv,
                "largest_call_oi_strike":ce_strike,"largest_put_oi_strike":pe_strike,
                "features":dict(zip(OPTION_NAMES,vector))}
    except (KeyError,ValueError,TypeError,OverflowError,ZeroDivisionError):
        return None


def options_at(db,cutoff):
    current=_chain(db,cutoff)
    if not current:
        return None
    prior=_chain(db,cutoff-timedelta(minutes=15),expiry=current[0]["expiry"])
    return option_features(current,prior)


def _nifty_tick(db,cutoff):
    lower=cutoff-timedelta(seconds=30)
    rows=replay_storage.fetchall(db,"""SELECT price,exchange_utc,received_utc,packet_sha256 FROM live_ticks
       WHERE identity='INDEX:NIFTY50' AND exchange_utc>=? AND exchange_utc<=?
       AND received_utc>=? AND received_utc<=?
       ORDER BY exchange_utc DESC,received_utc DESC,packet_sha256 DESC LIMIT 20""",
       (_iso(lower),_iso(cutoff),_iso(lower),_iso(cutoff)))
    for price,event,receipt,digest in rows:
        try:
            et,rt=_stamp(event),_stamp(receipt)
            if not lower<=et<=cutoff or not lower<=rt<=cutoff or not -2<=(rt-et).total_seconds()<=15:
                continue
            if not p._valid_hash(digest) or _finite(price)<=0:
                continue
            return {"price":price,"exchange_utc":event,"received_utc":receipt,"sha256":digest}
        except (ValueError,TypeError,OverflowError):
            continue
    return None


def domestic_at(db,cutoff,bank_return_bps=None):
    if not _exists(db,"live_ticks") or p._session(cutoff).date()!=p._session(cutoff-timedelta(minutes=30)).date():
        return [0.,0.,1.],None
    c,a=_nifty_tick(db,cutoff),_nifty_tick(db,cutoff-timedelta(minutes=30))
    if c is None or a is None:
        return [0.,0.,1.],None
    ret=10000*(c["price"]/a["price"]-1)
    relative=bank_return_bps-ret if bank_return_bps is not None else None
    return [ret,relative if relative is not None else 0.,0.],{"return_30m_bps":ret,"bank_minus_nifty_bps":relative,"current":c,"anchor":a}


def snapshot(*,mode="receipt",now=None):
    now=now or _now()
    result={"version":VERSION,"as_of_utc":_iso(now),"mode":mode,"catalog":catalog(),
            "factors":{},"global_group_coverage":False,"options":None,"domestic":None,"imported_rows":0,"ambiguous_factors":[],
            "warning":"External inputs are reviewed imports, not independently verified live feeds. Chain OI/volume are aggregate two-sided exposures, not signed retail flow or net dealer gamma. Participant categories cover aggregate index derivatives, not BANKNIFTY-only positions."}
    if not shared_market_data.database_path().is_file():
        return result
    with closing(ao._read_database()) as db:
        timelines,meta=load_timelines(db,now-timedelta(hours=1),now,mode)
        _,details,ok=factor_at(timelines,now)
        opt=options_at(db,now)
        _,domestic=domestic_at(db,now)
    result.update(factors=details,global_group_coverage=ok,options=opt[1] if opt else None,domestic=domestic,
                  imported_rows=meta["rows"],ambiguous_factors=meta["ambiguous_factors"])
    return result
