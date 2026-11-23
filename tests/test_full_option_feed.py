"""Offline acceptance for original Dhan all-option Quote/OI and depth promotion.

No live brokerage credentials, market requests, invented prices or orders.
"""
from __future__ import annotations

from collections import deque
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
        # There have been only twelve seconds of original trade history.
        # Do NOT advertise that as a five-minute or 60-second return.
        self.assertGreater(rank[0]["observed_change_pct"],300.)
        self.assertIsNone(rank[0]["move_60s_pct"])
        self.assertIsNone(rank[0]["move_5m_pct"])
        self.assertEqual(rank[0]["observed_span_seconds"],12)
        self.assertTrue(rank[0]["eligible_for_depth"])
        self.assertEqual(rank[0]["open_interest"],2000)
        self.assertGreaterEqual(rank[0]["score"],70)
        self.assertEqual(feed.WRITES.qsize(),4)
        self.assertEqual(feed.STATUS["unchanged_quote_packets"],1)
        self.assertEqual(feed.LATEST[selected["identity"]]["volume"],1000)

    def test_observed_span_and_true_horizon_returns_are_not_conflated(self):
        source_time=1_900_000_000
        short=deque([
            (source_time, source_time, 99., 100),
            (source_time+6, source_time+6, 125., 300),
            (source_time+12, source_time+12, 500., 1000),
        ])
        result=feed._opportunity(short)
        self.assertGreater(result["observed_change_pct"], 400)
        self.assertEqual(result["observed_span_seconds"], 12)
        self.assertIsNone(result["move_60s_pct"])
        self.assertIsNone(result["move_5m_pct"])
        self.assertGreaterEqual(result["score"], 70)

        full=deque([
            (source_time+0, source_time+0, 100., 100),
            (source_time+4, source_time+4, 102., 140),
            (source_time+242, source_time+242, 170., 540),
            (source_time+302, source_time+302, 180., 1000),
        ])
        expanded=feed._opportunity(full)
        self.assertAlmostEqual(expanded["move_60s_pct"],5.88,places=2)
        self.assertEqual(expanded["move_5m_pct"],80.0)
        self.assertEqual(expanded["observed_span_seconds"],302)

        # Multiple quote packets with an unchanged Dhan last-trade time
        # must not be advertised as a market price impulse.
        duplicate_time=feed._opportunity(deque([
            (source_time, source_time, 99., 100),
            (source_time+4, source_time, 500., 500),
        ]))
        self.assertEqual(duplicate_time["score"],0)
        self.assertIsNone(duplicate_time["observed_change_pct"])

    def test_all_observed_penny_movers_are_preserved_but_not_promoted(self):
        now=datetime.now(timezone.utc).isoformat()
        original,_=master(4)
        ids=list(original["by_id"].values())
        for item in ids[:2]:
            feed.CATALOG[item["identity"]]=item
        feed.LATEST[ids[0]["identity"]]={
            "identity":ids[0]["identity"],"expiry":ids[0]["expiry"],
            "price":0.95,"score":100.0,"observed_span_seconds":20,
            "observed_change_pct":-55,"volume_increase":100000,
            "quote_received_utc":now}
        feed.LATEST[ids[1]["identity"]]={
            "identity":ids[1]["identity"],"expiry":ids[1]["expiry"],
            "price":120.0,"score":25.0,"observed_span_seconds":20,
            "observed_change_pct":10.0,"volume_increase":900,
            "quote_received_utc":now}
        all_movers=feed.ranked_opportunities(10)
        depth=feed.ranked_depth_candidates(10)
        self.assertEqual(len(all_movers),2)
        self.assertEqual(all_movers[0]["identity"],ids[1]["identity"])
        self.assertFalse(all_movers[1]["eligible_for_depth"])
        self.assertEqual([x["identity"] for x in depth],[ids[1]["identity"]])
        # Source catalog stays intact; these are research-ranking screens,
        # not a market-data capture restriction.
        self.assertEqual(len(feed.CATALOG),2)

    def test_expiry_coverage_distinguishes_requested_quote_and_oi_packets(self):
        original,expiry=master(4)
        rows=list(original["by_id"].values())
        feed.CATALOG={item["identity"]:item for item in rows}
        now=datetime.now(timezone.utc).isoformat()
        feed.LATEST[rows[0]["identity"]]={
            "quote_received_utc":now,"last_quote_packet_received_utc":now,
            "price":100.,"score":0}
        feed.LATEST[rows[1]["identity"]]={
            "oi_received_utc":now,"open_interest":1000,"score":0}
        feed.LATEST[rows[2]["identity"]]={
            "last_quote_packet_received_utc":now,"score":0}
        status=feed.status()
        self.assertEqual(status["observed_contracts"],1)
        self.assertEqual(status["recent_price_contracts"],1)
        self.assertEqual(status["source_quote_delivered_contracts"],2)
        self.assertEqual(status["recent_source_quote_contracts"],2)
        self.assertEqual(status["stale_source_quote_only_contracts"],1)
        self.assertEqual(status["never_received_source_quote_ids"],2)
        self.assertEqual(status["observed_oi_contracts"],1)
        self.assertEqual(status["requested_not_yet_quoted"],3)
        self.assertEqual(sum(e["subscribed"] for e in
                             status["coverage_by_expiry"]),4)
        self.assertEqual(sum(e["never_quoted"] for e in
                             status["coverage_by_expiry"]),3)
        self.assertEqual(sum(e["oi_only"] for e in
                             status["coverage_by_expiry"]),1)
        self.assertEqual(sum(e["stale_quote_packet_only"] for e in
                             status["coverage_by_expiry"]),1)

    def test_stable_recent_original_ce_and_pe_can_get_active_depth(self):
        original,_=master(6)
        now=datetime.now(timezone.utc).isoformat()
        rows=list(original["by_id"].values())
        feed.CATALOG={row["identity"]:row for row in rows}
        for index,row in enumerate(rows):
            feed.LATEST[row["identity"]]={
                "identity":row["identity"],"expiry":row["expiry"],
                "strike":row["strike"],"option_type":row["option_type"],
                "price":100.0 if index<4 else 1.0,
                "volume":1000+index*100,
                "quote_received_utc":now,
                "last_trade_quantity":30,
                "volume_increase":0,"score":0,
            }
        ranked=feed.ranked_active_depth(10)
        self.assertEqual(len(ranked),4)
        self.assertEqual(
            [x["option_type"] for x in ranked],["CE","PE","CE","PE"])
        self.assertTrue(all(x["source"]=="observed_original_Dhan_trade"
                            for x in ranked))
        self.assertEqual(feed.ranked_depth_candidates(),[])
        self.assertEqual(len(feed.CATALOG),6)

    def test_readonly_dhan_quote_receipt_audit_reports_gaps_as_uncertain(self):
        feed._init_storage()
        day="2026-11-23"
        base=datetime(2026,11,23,5,0,tzinfo=timezone.utc)
        identity="NSE_FNO:62539"
        events=[
            (base, "quote", 100.),
            (base+timedelta(seconds=70), "quote", 101.),
            (base+timedelta(seconds=420), "quote", 99.),
            (base+timedelta(seconds=440), "oi", None),
        ]
        with live_market._database() as db:
            db.executemany(
                """INSERT INTO dhan_option_live_events(
                identity,received_utc,exchange_trade_utc,kind,price,
                volume,open_interest,last_trade_quantity,packet_sha256,session_id)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [(identity,stamp.isoformat(),stamp.isoformat()
                    if kind=="quote" else None,kind,price,
                    100 if kind=="quote" else None,
                    500 if kind=="oi" else None,
                    30 if kind=="quote" else None,
                    "fixture"+str(i),"source_fixture")
                 for i,(stamp,kind,price) in enumerate(events)])
        audit=feed.audit_saved_quote_history(identity,day)
        self.assertEqual(audit["saved_quote_receipts"],3)
        self.assertEqual(audit["saved_oi_events"],1)
        self.assertEqual(audit["inter_receipt_gaps_over_60s"],2)
        self.assertEqual(audit["inter_receipt_gaps_over_300s"],1)
        self.assertEqual(audit["largest_inter_receipt_gap_seconds"],350.)
        self.assertEqual(audit["minutes_with_saved_quotes"],3)
        self.assertTrue(audit["scan_complete"])
        self.assertIn("cannot prove loss",audit["note"])
        endpoint=self.client.get(
            "/api/trading-cockpit/option-feed/quality",
            params={"identity":identity,"day":day})
        self.assertEqual(endpoint.status_code,200,endpoint.text)
        self.assertEqual(endpoint.json()["saved_quote_receipts"],3)
        invalid=self.client.get(
            "/api/trading-cockpit/option-feed/quality",
            params={"identity":"../../secrets","day":day})
        self.assertEqual(invalid.status_code,400)

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
        # A stale Dhan LTT still proves that the broker sent a Quote packet;
        # it is NOT a new trade and must not be saved as a current trade.
        self.assertIn("last_quote_packet_received_utc",
                      feed.LATEST[item["identity"]])
        self.assertEqual(feed.status()["source_quote_delivered_contracts"],1)
        self.assertEqual(feed.status()["observed_contracts"],0)
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

    def test_option_feed_continues_past_legacy_daily_event_cap(self):
        """A preexisting daily event count must not block new source packets.

        Uses a tiny fixture and a deliberately tiny legacy constant, not
        two million DB rows; no real market data or broker socket needed.
        """
        self.assertEqual(feed.MAX_DAILY_EVENTS, 0)
        original, _ = master(2)
        contract = original["by_id"]["61000"]
        feed.CATALOG[contract["identity"]] = contract
        now = datetime.now(timezone.utc).replace(microsecond=0)
        feed._init_storage()
        with live_market._database() as db:
            for index in range(2):
                previous = now - timedelta(seconds=30-index)
                db.execute("""
                    INSERT INTO dhan_option_live_events(
                      identity,received_utc,exchange_trade_utc,kind,price,
                      volume,open_interest,last_trade_quantity,packet_sha256,session_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                    contract["identity"], previous.isoformat(),
                    previous.isoformat(), "quote", 99.0, 1+index,
                    None, 30, "existing"+str(index), "prior_source_run"))
        for index in range(3):
            received = now - timedelta(seconds=5-index)
            event = feed.decode_quote_frames(
                quote_packet(61000, 100.+index, 10+index, received))[0]
            feed._ingest(event, received, "new_source_run")
        stopped = Event()
        stopped.set()
        with patch.object(feed, "_storage_disk_capacity",
                          return_value=(True, 50*1024**3, 2*1024**3)), \
             patch.object(feed, "MAX_DAILY_EVENTS", 2):
            feed._write_batches(stopped)
        self.assertEqual(feed.STATUS["stored_events"], 3)
        self.assertEqual(feed.STATUS["storage_daily_events"], 5)
        self.assertEqual(feed.STATUS["storage_state"], "recording")
        self.assertIsNone(feed.STATUS["storage_daily_limit"])
        self.assertEqual(feed.STATUS["dropped_events"], 0)
        self.assertEqual(len(feed.saved_history(contract["identity"])["events"]), 5)

    def test_full_option_writer_disk_guard_reports_durable_gap(self):
        original, _ = master(2)
        contract = original["by_id"]["61000"]
        feed.CATALOG[contract["identity"]] = contract
        now = datetime.now(timezone.utc).replace(microsecond=0)
        event = feed.decode_quote_frames(
            quote_packet(61000, 120., 300, now))[0]
        feed._ingest(event, now, "insufficient_disk_fixture")
        stopped = Event()
        stopped.set()
        with patch.object(feed, "_storage_disk_capacity",
                          return_value=(False, 50, 1000)):
            feed._write_batches(stopped)
        self.assertEqual(feed.STATUS["storage_state"],
                         "insufficient_free_disk_space")
        self.assertEqual(feed.STATUS["dropped_events"], 1)
        self.assertTrue(feed.STATUS["storage_gap_detected"])
        log = auto._root()/"option_feed_storage_gaps.jsonl"
        self.assertTrue(log.is_file())
        entries = [json.loads(row) for row in log.read_text().splitlines()]
        self.assertEqual(entries[-1]["dropped_events"], 1)
        self.assertEqual(entries[-1]["reason"], "insufficient_free_disk_space")
        self.assertTrue(entries[-1]["not_recoverable_from_source_snapshot"])
        # The network thread can report streaming, but cannot overwrite
        # independent writer error state or its durable incident.
        feed._set(state="streaming_original_quotes")
        self.assertEqual(feed.STATUS["storage_state"],
                         "insufficient_free_disk_space")

    def test_option_feed_capacity_floor_reserves_disk(self):
        with patch.object(feed.shutil, "disk_usage") as usage:
            usage.return_value.total = 250 * 1024**3
            usage.return_value.free = 120 * 1024**3
            healthy, free, reserve = feed._storage_disk_capacity()
            self.assertTrue(healthy)
            self.assertEqual(free, 120*1024**3)
            self.assertEqual(reserve, 7.5*1024**3)
            usage.return_value.free = 100 * 1024**2
            healthy, _, _ = feed._storage_disk_capacity()
            self.assertFalse(healthy)

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

        active_only=wide_option_depth.select_full_chain_rotation(
            chain,auto.DEFAULTS,rotation_step=1,
            activity_ids=distant[:70])
        self.assertEqual(sum(x["coverage_role"]=="core" for x in active_only),120)
        self.assertEqual(sum(x["coverage_role"]=="active" for x in active_only),60)
        self.assertEqual(sum(x["coverage_role"]=="rotating" for x in active_only),20)

        joint=wide_option_depth.select_full_chain_rotation(
            chain,auto.DEFAULTS,rotation_step=1,
            priority_ids=distant[:40],activity_ids=distant[40:70])
        self.assertEqual(sum(x["coverage_role"]=="opportunity" for x in joint),40)
        self.assertEqual(sum(x["coverage_role"]=="active" for x in joint),20)
        self.assertEqual(sum(x["coverage_role"]=="rotating" for x in joint),20)
        self.assertEqual(len({x["identity"] for x in joint}),200)
