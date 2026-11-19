"""Offline Dhan ticker, 20-level depth, live replay and permission regressions.

No sockets, tokens, internet requests, exchange orders or made-up broker history.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from fastapi.testclient import TestClient
import json
import os
import struct
import tempfile

from workstation_api import live_market, market_depth, service
from workstation_api.app import app


START = datetime(2026, 11, 19, 3, 45, tzinfo=timezone.utc)


def tick_packet(price: float, when: datetime, *, segment: int = 0,
                security_id: int = 25) -> bytes:
    return struct.pack("<BHBIfI", 2, 16, segment, security_id, price, int(when.timestamp()))


class LiveCopilotOfflineTests(TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_live_copilot_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        patcher=patch.object(service, "DATA", self.root / "data")
        patcher.start()
        self.addCleanup(patcher.stop)
        live_market._reset_for_tests()
        self.addCleanup(live_market._reset_for_tests)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_binary_ticker_exact_identity_and_no_control_as_price(self):
        one=tick_packet(63021.5,START)
        second=tick_packet(63026.5,START+timedelta(seconds=3))
        parsed=live_market.decode_marketfeed(one+second)
        self.assertEqual(len(parsed),2)
        self.assertEqual(parsed[0]["exchange_segment"],"IDX_I")
        self.assertEqual(parsed[0]["security_id"],"25")
        self.assertAlmostEqual(parsed[0]["price"],63021.5)
        self.assertEqual(parsed[0]["packet_sha256"],sha256(one).hexdigest())
        ctrl=struct.pack("<BHBI",6,8,0,25)
        self.assertEqual(live_market.decode_marketfeed(ctrl),[])
        with self.assertRaisesRegex(ValueError,"length"):
            live_market.decode_marketfeed(b"\x02\x10\x00\x00\x19\x00\x00\x00")

    def test_tick_minutes_are_source_backed_not_interpolated(self):
        packet1=live_market.decode_marketfeed(tick_packet(63000,START))[0]
        packet2=live_market.decode_marketfeed(tick_packet(
            63005,START+timedelta(seconds=10)))[0]
        packet3=live_market.decode_marketfeed(tick_packet(
            63020,START+timedelta(minutes=2)))[0]
        self.assertTrue(live_market.ingest_tick("INDEX:BANKNIFTY",packet1,received=START))
        self.assertTrue(live_market.ingest_tick("INDEX:BANKNIFTY",packet2,
                                                received=START+timedelta(seconds=10)))
        self.assertFalse(live_market.ingest_tick("INDEX:BANKNIFTY",packet2,
                                                 received=START+timedelta(seconds=10)))
        self.assertTrue(live_market.ingest_tick("INDEX:BANKNIFTY",packet3,
                                                received=START+timedelta(minutes=2)))
        result=live_market.minute_series("INDEX:BANKNIFTY")
        self.assertEqual(len(result["rows"]),2)
        self.assertEqual([x["close"] for x in result["rows"]],[63005,63020])
        self.assertEqual([x["observed_tick_count"] for x in result["rows"]],[2,1])
        self.assertEqual(result["rows"][0]["volume"],0)
        self.assertIn("no authenticated traded volume",result["source_warning"])
        self.assertEqual(result["basis"],"Dhan_live_ticker_observed_LTP_minute_aggregate")
        self.assertEqual(result["rows"][0]["session_ist"],"2026-11-19")
        self.assertFalse(any(x["timestamp_utc"].startswith("2026-11-19T03:46")
                             for x in result["rows"]))
        with patch.object(live_market,"_database", wraps=live_market._database):
            status=live_market.status()
        self.assertTrue(status["read_only"])
        self.assertEqual(status["shared_library"],"dhan_shared")
        catalog=self.client.get("/api/trading-cockpit/live/capture-catalog")
        self.assertEqual(catalog.status_code,200,catalog.text)
        minutes=catalog.json()["minute_sources"]
        self.assertEqual(len(minutes),1)
        self.assertEqual(minutes[0]["identity"],"INDEX:BANKNIFTY")
        self.assertEqual(minutes[0]["observations"],2)
        self.assertEqual(catalog.json()["shared_library"],"dhan_shared")

    def test_original_full_depth_is_sampled_and_remains_reviewable(self):
        bids=[{"price":100-i*0.05,"quantity":10+i,"orders":2} for i in range(20)]
        asks=[{"price":100.10+i*0.05,"quantity":15+i,"orders":3} for i in range(20)]
        snap=market_depth._validate_snapshot({
            "identity":"NSE_FNO:333",
            "received_utc":START.isoformat(),
            "timestamp_kind":"local_receive","bid":bids,"ask":asks,
            "bid_packet_sha256":"a"*64,"ask_packet_sha256":"b"*64,
        },20)
        with live_market.CHANGED:
            live_market.ACTIVE.update(active=True,session_id="live_test_fixture",
                                      depth_connection="connected",revision=1)
        live_market._receive_depth(snap)
        history=live_market.latest_depth_history("NSE_FNO:333")
        self.assertEqual(len(history["snapshots"]),1)
        self.assertEqual(history["snapshots"][0]["bid_levels"],20)
        self.assertEqual(history["snapshots"][0]["ask_levels"],20)
        self.assertTrue(history["snapshots"][0]["full_depth"])
        self.assertGreater(history["snapshots"][0]["spread_bps"],0)
        self.assertEqual(live_market.status()["saved_books"],1)
        self.assertFalse(history["historical_download_supported"])
        saved=self.client.get("/api/trading-cockpit/live/capture-catalog")
        self.assertEqual(saved.status_code,200,saved.text)
        depth=saved.json()["depth_sources"]
        self.assertEqual(depth[0]["identity"],"NSE_FNO:333")
        self.assertEqual(depth[0]["observations"],1)
        self.assertNotIn("access_token",json.dumps(live_market.status()))

    def test_read_only_start_guard_rejects_missing_consent_and_index_depth(self):
        denied=self.client.post("/api/trading-cockpit/live/start",json={
            "index_identity":"INDEX:BANKNIFTY","confirm_live_data":False})
        self.assertEqual(denied.status_code,400)
        self.assertIn("Approve",denied.text)
        bad=self.client.post("/api/trading-cockpit/live/start",json={
            "index_identity":"INDEX:BANKNIFTY","depth_identity":"INDEX:BANKNIFTY",
            "confirm_live_data":True})
        self.assertEqual(bad.status_code,400)
        self.assertIn("NSE_EQ/NSE_FNO",bad.text)
        with patch.dict(os.environ,{"DHAN_CLIENT_ID":"","DHAN_ACCESS_TOKEN":""}):
            no_token=self.client.post("/api/trading-cockpit/live/start",json={
                "index_identity":"INDEX:BANKNIFTY","confirm_live_data":True})
        self.assertEqual(no_token.status_code,400)
        self.assertEqual(self.client.get("/api/trading-cockpit/live/status").status_code,200)
        self.assertEqual(self.client.post("/api/trading-cockpit/live/stop").status_code,200)

    def test_live_signal_cannot_fake_missing_recent_candles(self):
        output=self.client.get("/api/trading-cockpit/live/signal")
        self.assertEqual(output.status_code,200,output.text)
        self.assertFalse(output.json()["ready"])
        self.assertEqual(output.json()["quote_mode"],"NO_LIVE_OBSERVATIONS")
        rejected=self.client.post("/api/trading-cockpit/live/predictions",
            json={"identity":"INDEX:BANKNIFTY","horizon_minutes":3})
        self.assertEqual(rejected.status_code,400)
        response=self.client.get("/api/trading-cockpit/live/depth-history",
            params={"identity":"INDEX:BANKNIFTY"})
        self.assertEqual(response.status_code,400)

    def test_local_contract_search_returns_exact_derivative_security_ids(self):
        source=self.root / "data" / "dhan" / "instrument_master.csv"
        source.parent.mkdir(parents=True)
        source.write_text(
            "EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,TRADING_SYMBOL,SYMBOL_NAME,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE\n"
            "NSE,D,58742,OPTIDX,BANKNIFTY27NOV63000CE,BANKNIFTY 63000 CE,2026-11-27,63000,CE\n"
            "NSE,D,58743,OPTIDX,BANKNIFTY27NOV63000PE,BANKNIFTY 63000 PE,2026-11-27,63000,PE\n"
            "NSE,E,1333,EQUITY,HDFCBANK,HDFC BANK,,,\n"
        )
        found=self.client.get("/api/trading-cockpit/live/contracts",params={"query":"BANKNIFTY"})
        self.assertEqual(found.status_code,200,found.text)
        identities=[x["identity"] for x in found.json()["contracts"]]
        self.assertEqual(identities,["NSE_FNO:58742","NSE_FNO:58743"])
        self.assertNotIn("NSE_EQ:1333",identities)

    def test_historical_session_replay_uses_only_original_minute_observations(self):
        observations=[
            {"timestamp_utc":(START+timedelta(minutes=m)).isoformat(),
             "session_ist":"2026-11-19","open":63000+m,"high":63004+m,
             "low":62996+m,"close":63002+m,"volume":0}
            for m in (0,1,3)]
        with patch("workstation_api.app.cockpit_sources.series",
                   return_value={"rows":observations,"basis":"original_Dhan_IDX_I",
                                 "warning":"Historical only","has_more":True}) as original:
            response=self.client.get("/api/trading-cockpit/historical/series",
                                     params={"identity":"INDEX:BANKNIFTY","limit":5000})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(data["rows"],observations)
        self.assertEqual(len(data["sessions"]),1)
        self.assertEqual(data["sessions"][0]["observed_bars"],3)
        self.assertEqual(data["kind"],"historical_not_streaming")
        self.assertTrue(data["has_more"])
        self.assertIn("never synthesized",data["note"])
        original.assert_called_once_with("INDEX:BANKNIFTY",limit=5000)
        invalid=self.client.get("/api/trading-cockpit/historical/series",
                                params={"identity":"INDEX:BANKNIFTY","limit":5001})
        self.assertEqual(invalid.status_code,400)

    def test_shared_minute_rows_are_not_labeled_original_vendor_history(self):
        snapshot=self.client.get("/api/trading-cockpit/live/minutes",
            params={"identity":"INDEX:BANKNIFTY"})
        self.assertEqual(snapshot.status_code,200,snapshot.text)
        self.assertEqual(snapshot.json()["basis"],"Dhan_live_ticker_observed_LTP_minute_aggregate")
        self.assertEqual(snapshot.json()["rows"],[])


if __name__=="__main__":
    import unittest
    unittest.main()
