"""Offline acceptance for original Dhan all-option Quote/OI and depth promotion.

No live brokerage credentials, market requests, invented prices or orders.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from queue import Queue
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from fastapi.testclient import TestClient
import json
import os
import sqlite3
import stat
import struct
import tempfile

from workstation_api import auto_option_depth as auto, full_option_feed as feed
from workstation_api import live_market, service, wide_option_depth
from workstation_api.app import app


def quote_packet(sid: int, price: float, volume: int, when: datetime,
                 *, segment: int = 2) -> bytes:
    body = struct.pack("<fHIfIIIffff",price,30,int(when.timestamp()),
                       price,volume,100,120,price,0.0,price,price)
    assert len(body)==42
    return struct.pack("<BHBI",4,50,segment,sid)+body


def oi_packet(sid: int, oi: int) -> bytes:
    return struct.pack("<BHBII",5,12,2,sid,oi)


def master(n: int = 874) -> tuple[dict,list[str]]:
    expiry=(date.today()+timedelta(days=12)).isoformat()
    nxt=(date.today()+timedelta(days=19)).isoformat()
    rows={}
    for index in range(n):
        secid=str(61000+index)
        expiry_date=expiry if index%2==0 else nxt
        rows[secid]={
            "identity":"NSE_FNO:"+secid,"security_id":secid,
            "expiry":expiry_date,"strike":60000.0+(index//2)*100.0,
            "option_type":"CE" if index%2==0 else "PE",
            "lot_size":30,
        }
    return {"available":True,"fresh":True,"by_id":rows},[expiry,nxt]


def chain_rows(n: int = 420) -> dict:
    expiry=(date.today()+timedelta(days=12)).isoformat()
    rows=[]
    for index in range(n):
        strike=60000.0+(index//2)*100.
        side="CE" if index%2==0 else "PE"
        rows.append({
            "identity":"NSE_FNO:"+str(80000+index),
            "strike":strike,"expiry":expiry,"option_type":side,
            "contract_master_verified":True,"lot_size":30,
            "ltp":100.,"bid":99.,"ask":101.,"volume":100,
        })
    return {"underlying_spot":64000.,"expiry":expiry,
            "received_utc":datetime.now(timezone.utc).isoformat(),
            "contracts":rows}


class DhanFullUniverseTests(TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_full_options_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        env=patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"","DHAN_CLIENT_ID":""})
        env.start();self.addCleanup(env.stop)
        source=patch.object(service,"DATA",self.root/"data")
        source.start();self.addCleanup(source.stop)
        # Restore in-memory objects; offline fixtures must never start sockets.
        original={key:getattr(feed,key) for key in (
            "CATALOG","LATEST","HISTORY","WRITES","STATUS","STORAGE_INITIALIZED")}
        feed.CATALOG={};feed.LATEST={};feed.HISTORY={}
        feed.WRITES=Queue(maxsize=feed.MAX_QUEUE)
        feed.STATUS=dict(feed.STATUS);feed.STORAGE_INITIALIZED=False
        def cleanup():
            for key,value in original.items():
                setattr(feed,key,value)
        self.addCleanup(cleanup)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_decode_real_quote_oi_concatenation_and_missing_modes(self):
        now=datetime.now(timezone.utc)
        a=quote_packet(62539,99.,100,now)
        b=oi_packet(62539,15000)
        control=struct.pack("<BHBI",7,8,0,0)
        decoded=feed.decode_quote_frames(a+b+control)
        self.assertEqual(len(decoded),2)
        self.assertEqual(decoded[0]["security_id"],"62539")
        self.assertEqual(decoded[0]["kind"],"quote")
        self.assertEqual(decoded[0]["price"],99.)
        self.assertEqual(decoded[0]["volume"],100)
        self.assertEqual(decoded[0]["packet_sha256"],sha256(a).hexdigest())
        self.assertEqual(decoded[1]["kind"],"oi")
        self.assertEqual(decoded[1]["oi"],15000)
        self.assertEqual(feed.decode_quote_frames(
            quote_packet(100,99,1,now,segment=1)),[])
        with self.assertRaisesRegex(ValueError,"length"):
            feed.decode_quote_frames(b"\x04\x40\x00\x02\x59\x00\x00\x00")
        with self.assertRaisesRegex(ValueError,"header"):
            feed.decode_quote_frames(b"\x04")

    def test_all_874_current_master_ids_not_only_atm_and_batches_100(self):
        original,expiry=master(874)
        rows=feed._safe_master_contracts(
            original,expiry,today=date.today(),spot=64000.)
        self.assertEqual(len(rows),874)
        self.assertEqual(len({x["identity"] for x in rows}),874)
        requests=feed._subscribe_batches(rows)
        self.assertEqual(len(requests),9)
        self.assertEqual([req["InstrumentCount"] for req in requests],
                         [100]*8+[74])
        self.assertTrue(all(req["RequestCode"]==17 for req in requests))
        self.assertEqual(requests[0]["InstrumentList"][0]["ExchangeSegment"],"NSE_FNO")
        with self.assertRaisesRegex(ValueError,"maximum"):
            feed._subscribe_batches(rows*6)

    def test_missing_duplicates_and_expired_source_ids_are_not_subscribed(self):
        original,expiries=master(10)
        first=next(iter(original["by_id"].values()))
        original["by_id"]["99999"]={
            **first,"identity":"NSE_FNO:99999","security_id":"99999"}
        original["by_id"]["invalid"]={
            **first,"identity":"NSE_FNO:invalid"}
        original["by_id"]["expired"]={
            **first,"identity":"NSE_FNO:98888",
            "expiry":(date.today()-timedelta(days=4)).isoformat()}
        found=feed._safe_master_contracts(original,expiries,today=date.today())
        self.assertEqual(len(found),9)
        self.assertNotIn(first["identity"],{x["identity"] for x in found})
        self.assertFalse(any(x["expiry"]<date.today().isoformat() for x in found))
        with self.assertRaisesRegex(ValueError,"Fresh"):
            feed._safe_master_contracts({**original,"fresh":False},expiries,
                                        today=date.today())

    def test_99_to_500_original_quotes_generate_live_opportunity_and_oi(self):
        original,exps=master(2)
        selected=original["by_id"]["61000"]
        feed.CATALOG[selected["identity"]]=selected
        now=datetime.now(timezone.utc)
        series=[(now-timedelta(seconds=14),99.,100),
                (now-timedelta(seconds=8),125.,175),
                (now-timedelta(seconds=2),500.,1000)]
        with patch.object(feed,"_armed",return_value=True):
            for index,(stamp,price,volume) in enumerate(series):
                raw=quote_packet(61000,price,volume,stamp)
                feed._ingest(feed.decode_quote_frames(raw)[0],stamp,"test_session")
            oi=feed.decode_quote_frames(oi_packet(61000,2000))[0]
            feed._ingest(oi,now,"test_session")
            # The unchanged packet hash must not create another stored price update.
            feed._ingest(feed.decode_quote_frames(
                quote_packet(61000,500.,1000,series[-1][0]))[0],now,"test_session")
        rank=feed.ranked_opportunities(limit=10)
        self.assertEqual(rank[0]["identity"],selected["identity"])
        self.assertEqual(rank[0]["price"],500.)
        self.assertGreater(rank[0]["move_5m_pct"],300.)
        self.assertEqual(rank[0]["open_interest"],2000)
        self.assertGreaterEqual(rank[0]["score"],70)
        self.assertEqual(feed.WRITES.qsize(),4)
        self.assertEqual(feed.STATUS["unchanged_quote_packets"],1)
        self.assertEqual(feed.LATEST[selected["identity"]]["volume"],1000)

    def test_stale_trade_does_not_trigger_false_momentum(self):
        original,_=master(2)
        item=original["by_id"]["61000"]
        feed.CATALOG[item["identity"]]=item
        now=datetime.now(timezone.utc)
        packet=quote_packet(61000,150.,200,now-timedelta(hours=6))
        with patch.object(feed,"_armed",return_value=True):
            feed._ingest(feed.decode_quote_frames(packet)[0],now,"test_session")
        self.assertEqual(feed.ranked_opportunities(),[])
        self.assertEqual(feed.STATUS["ignored_stale_trades"],1)
        self.assertEqual(feed.WRITES.qsize(),0)

    def test_real_source_tick_persists_and_history_is_not_interpolated(self):
        original,_=master(2)
        item=original["by_id"]["61000"]
        feed.CATALOG[item["identity"]]=item
        now=datetime.now(timezone.utc)
        with patch.object(feed,"_armed",return_value=True):
            for idx,price in enumerate((99.,150.,500.)):
                stamp=now-timedelta(seconds=12-idx*5)
                event=feed.decode_quote_frames(quote_packet(
                    61000,price,100+idx*10,stamp))[0]
                feed._ingest(event,stamp,"fixture_option_feed")
        close=Event();close.set()
        feed._write_batches(close)
        saved=feed.saved_history(item["identity"])
        prices=[x["price"] for x in saved["events"] if x["kind"]=="quote"]
        self.assertEqual(prices,[99.,150.,500.])
        self.assertEqual(len(saved["events"]),3)
        self.assertEqual(feed.STATUS["stored_events"],3)
        self.assertTrue(all(x["exchange_trade_utc"] for x in saved["events"]))

    def test_independent_opt_in_permissions_and_safe_loopback_endpoint(self):
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"fixture-not-a-real-dhan-token"}), \
             patch.object(auto,"_config",return_value={**auto.DEFAULTS,"enabled":True}), \
             patch.object(feed,"resume_if_armed"):
            denied=self.client.post("/api/trading-cockpit/option-feed/enable",
                                    json={"confirm_live_quote_stream":False})
            self.assertEqual(denied.status_code,400)
            self.assertFalse(feed._consented())
            permitted=self.client.post("/api/trading-cockpit/option-feed/enable",
                                       json={"confirm_live_quote_stream":True})
            self.assertEqual(permitted.status_code,200,permitted.text)
            self.assertTrue(permitted.json()["full_universe_consent"])
            saved_file=feed._consent_path()
            self.assertEqual(stat.S_IMODE(saved_file.stat().st_mode),0o600)
            self.assertNotIn("fixture-not-a-real-dhan-token",permitted.text)
            self.assertEqual(self.client.get(
                "/api/trading-cockpit/option-feed/contracts").status_code,200)
            invalid=self.client.get(
                "/api/trading-cockpit/option-feed/history",
                params={"identity":"../../other", "limit":20})
            self.assertEqual(invalid.status_code,400)
            disabled=self.client.post("/api/trading-cockpit/option-feed/disable",
                                      json={})
            self.assertEqual(disabled.status_code,200)
            self.assertFalse(feed._consented())

    def test_promoted_original_price_movers_take_priority_depth_slots(self):
        chain=chain_rows(600)
        distant=[chain["contracts"][-i]["identity"] for i in range(1,61)]
        selected=wide_option_depth.select_full_chain_rotation(
            chain,auto.DEFAULTS,rotation_step=1,priority_ids=distant)
        self.assertEqual(len(selected),200)
        roles=[x["coverage_role"] for x in selected]
        self.assertEqual(roles.count("core"),120)
        self.assertEqual(roles.count("opportunity"),40)
        self.assertEqual(roles.count("rotating"),40)
        self.assertEqual(len({x["identity"] for x in selected}),200)
        self.assertTrue(set(distant[:40])<=
                        {x["identity"] for x in selected
                         if x["coverage_role"]=="opportunity"})
        self.assertEqual([len(g) for g in wide_option_depth.socket_groups(selected)],
                         [50,50,50,50])
        no_priority=wide_option_depth.select_full_chain_rotation(
            chain,auto.DEFAULTS,rotation_step=1)
        self.assertEqual(sum(x["coverage_role"]=="rotating" for x in no_priority),80)
