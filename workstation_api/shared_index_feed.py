"""Documented IDX_I ticker packets on the existing option Quote/OI socket.

No new WebSocket or option-capacity sacrifice. Code 1 remains unsupported.
An independent bounded queue prevents index SQLite writes from blocking the
option feed's receive loop. Only accepted source packets become minute bars.
"""
from datetime import datetime,timezone
from queue import Queue,Empty,Full
from threading import RLock
import sqlite3

from . import live_market

LOCK=RLock()
IDS={"25":"INDEX:BANKNIFTY","13":"INDEX:NIFTY50"}
CAPACITY=1024


class IndexCapture:
    def __init__(self):
        self.lock=RLock()
        self.write_lock=RLock()
        self.queue=Queue(maxsize=CAPACITY)
        self.session=None
        self.requested=[]
        self.connected=False
        self.quotes={}
        self.saved=0
        self.dropped=0
        self.unsupported=0
        self.rejected=0
        self.error=None
        self.state="not_subscribed"

    def begin(self,session,requested):
        with self.lock:
            self.session=session
            self.requested=list(requested)
            self.connected=bool(requested)
            self.quotes={}
            self.state="awaiting_documented_ticker" if requested else "no_spare_capacity_or_disabled"

    def end(self,session):
        with self.lock:
            if self.session==session:
                self.connected=False
                self.state="disconnected"

    def disconnect(self):
        with self.lock:
            self.connected=False
            self.state="disconnected"

    def submit(self,event,received,session):
        with self.lock:
            if not self.connected or self.session!=session or event["identity"] not in self.requested:
                return
            if event["kind"]=="index_unsupported":
                self.unsupported+=1
                if not self.quotes:
                    self.state="undocumented_index_packet"
                return
        try:
            self.queue.put_nowait((event,received,session))
        except Full:
            with self.lock:
                self.dropped+=1
                self.error="Index storage queue full; source coverage incomplete"

    def write_one(self,record):
        event,received,session=record
        try:
            ok=live_market.ingest_tick(event["identity"],event["packet"],received=received,session_id=session)
        except (ValueError,OSError,sqlite3.Error):
            with self.lock:
                self.dropped+=1
                self.error="Index source storage failed; no fabricated recovery"
            return
        with self.lock:
            if not ok:
                self.rejected+=1
                return
            self.saved+=1
            if self.session==session and self.connected:
                packet=event["packet"]
                self.quotes[event["identity"]]={"price":packet["price"],"exchange_utc":packet["exchange_utc"],
                    "received_utc":received.astimezone(timezone.utc).isoformat(),
                    "source":"Dhan documented ticker on shared option socket","session":session}
                self.state="observed_documented_ticker"

    def writer(self,stop):
        while not stop.is_set() or not self.queue.empty():
            try:
                item=self.queue.get(timeout=.3)
            except Empty:
                continue
            try:
                with self.write_lock:
                    self.write_one(item)
            finally:
                self.queue.task_done()

    def status(self,now=None):
        now=now or datetime.now(timezone.utc)
        with self.lock:
            quotes={}
            for ident,item in self.quotes.items():
                received=(now-datetime.fromisoformat(item["received_utc"])).total_seconds()
                exchange=(now-datetime.fromisoformat(item["exchange_utc"])).total_seconds()
                quotes[ident]={**{k:v for k,v in item.items() if k!="session"},"age_seconds":max(0,received),
                    "fresh":self.connected and 0<=received<=8 and -2<=exchange<=8 and item["session"]==self.session}
            return {"connected":self.connected,"state":self.state,"requested":list(self.requested),"quotes":quotes,
                    "saved_ticks":self.saved,"dropped_ticks":self.dropped,"unsupported_packets":self.unsupported,
                    "rejected_or_duplicate_ticks":self.rejected,"queue_depth":self.queue.qsize(),"error":self.error,
                    "source":"same Dhan option-quote WebSocket; no additional socket","read_only":True}


CAPTURE=IndexCapture()


def subscriptions(option_count):
    """Preserve every option subscription; fill only available spare slots."""
    if not isinstance(option_count,int) or not 0<=option_count<=5000:
        raise ValueError("Invalid option capacity")
    rows=list(IDS.items())[:max(0,min(2,5000-option_count))]
    if not rows:
        return None,[]
    return {"RequestCode":15,"InstrumentCount":len(rows),
            "InstrumentList":[{"ExchangeSegment":"IDX_I","SecurityId":sid} for sid,_ in rows]},[ident for _,ident in rows]


def decode_index_packet(raw,code,segment,sid):
    if segment!=0 or str(sid) not in IDS:
        return None
    ident=IDS[str(sid)]
    if code==1 or (code==2 and len(raw)!=16):
        return {"kind":"index_unsupported","identity":ident}
    if code!=2:
        return None
    records=live_market.decode_marketfeed(raw)
    if not records:
        return None
    return {"kind":"index_tick","identity":ident,"packet":records[0]}


def status():
    return CAPTURE.status()
