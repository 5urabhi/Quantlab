"""Offline regression tests for wider source repair and exact live identities."""
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from workstation_api import (cpr_option_repair as repair, options_history_sync as sync,
    expired_options_backtest as exp, cpr_hybrid_research as r, full_option_feed as feed,
    live_market, cpr_live_evidence, service, data_maintenance as dm)


class SourceRepairTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=patch.object(service,"DATA",Path(tmp.name))
        root.start();self.addCleanup(root.stop)
        for mod,name in ((feed,"STORAGE_INITIALIZED"),(live_market,"DB_INITIALIZED")):
            p=patch.object(mod,name,False)
            p.start();self.addCleanup(p.stop)

    def test_incremental_probe_never_assumes_unsupported_width(self):
        day="2026-10-06"
        stamp=datetime.fromisoformat(r._stamp(day,34)).timestamp()
        calls=[]
        def fetch(body):
            calls.append(body)
            if body["strike"]=="ATM+8":
                raise exp.RollingInputError("DH-905")
            field="ce" if body["drvOptionType"]=="CALL" else "pe"
            return {"data":{field:{"timestamp":[stamp],"open":[100.],"high":[101.],
                "low":[99.],"close":[100.],"strike":[60000.],"volume":[100.]}}}
        report=repair.probe_wings(day,date(2026,11,26),fetcher=fetch)
        self.assertEqual(report["verified_wings"],7)
        self.assertEqual(report["state"],"probe_limited")
        self.assertEqual(len(calls),9)
        self.assertTrue(all(exp._get_cached(b) is not None for b in calls[:-1]))
        self.assertIsNone(exp._get_cached(calls[-1]))
        calls.clear()
        report=repair.probe_wings(day,date(2026,11,26),fetcher=fetch)
        self.assertEqual(len(calls),1)
        self.assertEqual(report["verified_wings"],7)

    def test_empty_response_not_verified_wider_observation(self):
        report=repair.probe_wings("2026-10-06",date(2026,11,26),fetcher=lambda _:{"data":{}})
        self.assertEqual(report["verified_wings"],5)
        self.assertEqual(len(report["checks"]),4)
        self.assertTrue(all(x["state"]=="no_positive_observation" for x in report["checks"]))

    def test_documented_bound_and_core_request_priority(self):
        self.assertEqual(sync.preview("2026-10-01","2026-10-06",10,date(2026,11,26))["wings"],10)
        self.assertEqual(dm.validate({**dm.DEFAULT,"wings":10})["wings"],10)
        with self.assertRaises(ValueError):
            sync.preview("2026-10-01","2026-10-06",11,date(2026,11,26))
        older=exp._request_body(date(2026,10,5),date(2026,10,6),"MONTH",0,"ATM-5","CALL")
        newer=exp._request_body(date(2026,10,7),date(2026,10,8),"MONTH",0,"ATM+6","CALL")
        rank={x:i for i,x in enumerate(exp._offsets(10))}
        self.assertEqual(sync._prioritize([newer,older],rank,["2026-10-06","2026-10-08"]),[older,newer])
        with sync.acquisition_lock():
            with self.assertRaises(ValueError):
                with sync.acquisition_lock():
                    self.fail("Concurrent acquisition must be blocked")
        with sync.acquisition_lock():
            pass

    def test_exact_contract_terms_survive_master_changes_and_order(self):
        a={"identity":"NSE_FNO:100","expiry":"2026-11-24","strike":60000.,
           "option_type":"CE","lot_size":30}
        b={**a,"identity":"NSE_FNO:101","option_type":"PE"}
        self.assertEqual(feed._contract_signature([a,b]),feed._contract_signature([b,a]))
        feed._persist_session_contracts("session1",[a,b])
        feed._persist_session_contracts("session1",[b,a])
        with self.assertRaises(ValueError):
            feed._persist_session_contracts("session1",[{**a,"strike":60100.},b])
        feed._persist_session_contracts("session2",[{**a,"expiry":"2026-12-29","strike":60100.}])
        with live_market._database() as db:
            rows=db.execute("SELECT session_id,strike FROM dhan_option_contract_sessions WHERE identity=? ORDER BY session_id",(a["identity"],)).fetchall()
        self.assertEqual(rows,[("session1",60000.),("session2",60100.)])

    def test_live_audit_does_not_backfill_unmapped_receipts(self):
        a={"identity":"NSE_FNO:100","expiry":"2026-11-24","strike":60000.,
           "option_type":"CE","lot_size":30}
        feed._persist_session_contracts("session1",[a])
        now=datetime(2026,10,6,5,tzinfo=timezone.utc)
        snapshot={"rest_request_elapsed_ms":23.,"contracts":[{**a,"bid":100.,"ask":102.,"contract_master_verified":True}]}
        payload=json.dumps(snapshot,sort_keys=True,separators=(",",":"))
        with live_market._database() as db:
            for session in ("session1","legacy"):
                db.execute("INSERT INTO dhan_option_live_events VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (a["identity"],(now+timedelta(seconds=1 if session=="legacy" else 0)).isoformat(),
                    (now-timedelta(seconds=3)).isoformat(),"quote",100.,100,None,30,"a"*64,session))
            db.execute("CREATE TABLE option_chain_observations(snapshot_sha256 TEXT,normalized_json TEXT,captured_utc TEXT)")
            db.execute("INSERT INTO option_chain_observations VALUES(?,?,?)",
                (sha256(payload.encode()).hexdigest(),payload,now.isoformat()))
        report=cpr_live_evidence.audit()
        self.assertEqual(report["quote_sample"]["exact_mapped_pairs"],1)
        self.assertEqual(report["quote_sample"]["unmapped_legacy_pairs"],1)
        self.assertEqual(report["chain_sample"]["spread_inr_per_lot"]["median"],60.)
        self.assertEqual(report["chain_sample"]["rest_round_trip_ms"]["median"],23.)
