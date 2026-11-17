"""Offline validation for 1-minute Parquet and genuine market-depth evidence."""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import csv
import io
import json
import struct
import tempfile
import unittest

from fastapi.testclient import TestClient

from workstation_api import dhan_workspace,intraday_parquet,market_depth,service
from workstation_api.app import app


class OriginalMicrostructureTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="quantlab_depth_intraday_")
        self.addCleanup(tmp.cleanup)
        for key,directory in (("DATA","data"),("RESULTS","results")):
            patcher=patch.object(service,key,Path(tmp.name)/directory)
            patcher.start();self.addCleanup(patcher.stop)
        self.identity="NSE_EQ:1333"
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def _minute_source(self):
        raw=dhan_workspace._history_file(
            {"exchange_segment":"NSE_EQ","security_id":"1333"},1)
        raw.parent.mkdir(parents=True,exist_ok=True)
        rows=[
            "datetime,open,high,low,close,volume",
            "2026-09-01T09:15:00+0530,100,101,99,100.5,120",
            "2026-09-01T09:16:00+0530,100.5,101,100,100.8,90",
            "2026-09-01T09:17:00+0530,100.8,102,100.6,101.5,99",
            "2026-09-02T09:15:00+0530,101.5,102,101,101.8,80",
        ]
        raw.write_text("\n".join(rows)+"\n",encoding="utf-8")
        sidecar={
            "instrument_id":self.identity,"interval_minutes":1,
            "coverage":[["2026-09-01","2026-09-03"]],
            "rows":4,"sha256":sha256(raw.read_bytes()).hexdigest(),
        }
        raw.with_suffix(".json").write_text(json.dumps(sidecar))
        return raw

    def test_minute_cache_partitions_query_and_stale_protection(self):
        raw=self._minute_source()
        cat=self.client.get("/api/data-manager/intraday/catalog")
        self.assertEqual(cat.status_code,200,cat.text)
        self.assertEqual(cat.json()["instruments"][0]["identity"],self.identity)
        built=intraday_parquet.build(self.identity)
        self.assertTrue(built["ready"],built)
        self.assertEqual(built["observations"],4)
        result=self.client.get("/api/data-manager/intraday/series",params={
            "identity":self.identity,"limit":2})
        self.assertEqual(result.status_code,200,result.text)
        rows=result.json()["rows"]
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]["close"],101.8)
        self.assertTrue(result.json()["has_more"])
        raw.write_text(raw.read_text()+"2026-09-03T09:15:00+0530,102,103,101,102.7,70\n")
        self.assertEqual(intraday_parquet.status(self.identity)["state"],"stale")
        refused=self.client.get("/api/data-manager/intraday/series",
                                params={"identity":self.identity})
        self.assertEqual(refused.status_code,400)
        with self.assertRaisesRegex(ValueError,"checksum"):
            intraday_parquet.build(self.identity)

    def test_minute_history_requires_explicit_timezone_and_real_ohlcv(self):
        raw=self._minute_source()
        original=raw.read_text()
        raw.write_text(original.replace("+0530",""))
        side=raw.with_suffix(".json")
        manifest=json.loads(side.read_text())
        manifest["sha256"]=sha256(raw.read_bytes()).hexdigest()
        side.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,"Naive"):
            intraday_parquet.build(self.identity)

    def _packet(self, code:int, prices:list[float],size:int=20)->bytes:
        side=[]
        for price in prices:
            side.append(struct.pack("<dII",price,100,3))
        hdr=struct.pack("<HBBII",12+size*16,code,1,1333,7)
        return hdr+b"".join(side)

    def test_dhan_20_level_binary_decoder_and_microstructure_math(self):
        bid=[100-i*.05 for i in range(20)]
        ask=[100.1+i*.05 for i in range(20)]
        packets=market_depth.packet_stream(
            self._packet(41,bid)+self._packet(51,ask),20)
        self.assertEqual(len(packets),2)
        self.assertEqual(packets[0]["side"],"bid")
        self.assertEqual(len(packets[0]["levels"]),20)
        snap=market_depth._snapshot(packets[0],packets[1],self.identity,
                                    datetime.now(timezone.utc),20)
        self.assertTrue(snap["full_depth"])
        session=market_depth._id()
        receipt=market_depth._save(
            session,[snap],method="dhan_live_websocket",provider="dhan_live",
            instrument=self.identity,depth=20,original_digest=sha256(b"test").hexdigest())
        self.assertEqual(receipt["full_depth_snapshots"],1)
        report=market_depth.analyze(session)
        self.assertAlmostEqual(report["metrics"][0]["spread_bps"],10000*.1/100.05)
        self.assertEqual(report["summary"]["average_imbalance"],0)

    def test_historical_orderbook_csv_import_never_invents_levels(self):
        stamp="2026-09-01T09:15:00+05:30"
        csv_rows=["timestamp_utc,side,level,price,quantity,orders"]
        for level in range(1,21):
            csv_rows.append(f"{stamp},bid,{level},{100-level*.05},100,3")
            csv_rows.append(f"{stamp},ask,{level},{100+level*.05},100,3")
        result=market_depth.import_csv(
            ("\n".join(csv_rows)+"\n").encode(),self.identity,
            "authorized_vendor",20,confirm_authorized=True)
        self.assertEqual(result["snapshots"],1)
        self.assertEqual(result["method"],"licensed_historical_csv")
        catalog=self.client.get("/api/data-manager/depth/catalog")
        self.assertEqual(catalog.status_code,200,catalog.text)
        self.assertEqual(catalog.json()["captures"][0]["id"],result["id"])
        analytics=self.client.get("/api/data-manager/depth/analyze",
                                  params={"session_id":result["id"]})
        self.assertEqual(analytics.status_code,200,analytics.text)
        self.assertIn("mid_price",analytics.json()["metrics"][0])

    def test_orderbook_rejects_crossed_and_gap_levels(self):
        rows=[
            "timestamp_utc,side,level,price,quantity,orders",
            "2026-09-01T09:15:00+05:30,bid,1,105,10,2",
            "2026-09-01T09:15:00+05:30,ask,1,100,10,2",
        ]
        with self.assertRaisesRegex(ValueError,"best bid"):
            market_depth.import_csv(("\n".join(rows)+"\n").encode(),
                self.identity,"licensed_vendor",20,confirm_authorized=True)
        self.assertEqual(market_depth.catalog()["captures"],[])
        with self.assertRaisesRegex(ValueError,"Confirm"):
            market_depth.import_csv(b"irrelevant",self.identity,
                "licensed_vendor",20,confirm_authorized=False)

    def test_live_capture_requires_local_token_but_never_makes_orders(self):
        with patch.dict("os.environ",{"DHAN_ACCESS_TOKEN":"","DHAN_CLIENT_ID":""}):
            r=self.client.post("/api/data-manager/depth/start",json={
                "identity":self.identity,"depth":20,
                "duration_seconds":30,"confirm_live_data":True})
        self.assertEqual(r.status_code,400)
        self.assertIn("ignored .env",r.text)
        self.assertEqual(market_depth.stop_live(market_depth._id())["state"],
                         "not_recording")


if __name__=="__main__":
    unittest.main()
