"""Isolated prospective research tests: no real quotes or provider actions."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from workstation_api import constituent_prospective as p, banknifty_constituents as bank, live_market, service, shared_market_data

HASH="a"*64
class ProspectiveTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher=patch.object(service,"DATA",Path(tmp.name)/"data")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cut=datetime(2026,11,23,4,10,5,tzinfo=timezone.utc)
        self.path=shared_market_data.database_path()
        self.path.parent.mkdir(parents=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE live_ticks(identity TEXT,exchange_utc TEXT,received_utc TEXT,price REAL,packet_sha256 TEXT,session_id TEXT)""")
            db.execute("CREATE INDEX live_ticks_test ON live_ticks(identity,exchange_utc)")
            p._setup(db)

    def tick(self,event,receipt,price,digest=HASH):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO live_ticks VALUES(?,?,?,?,?,?)",("INDEX:BANKNIFTY",p._iso(event),p._iso(receipt),price,digest,"synthetic_unit_fixture"))

    def test_frozen_pressure_and_volume(self):
        receipt={"packet_sha256":HASH,"membership_sha256":HASH}
        report={"complete_weighted_coverage":True,"weighted_return_pct":.1,"weighted_breadth_pct":20,
                "membership":{"source_sha256":HASH},
                "weight_snapshot":{"source_csv_sha256":HASH,"membership_sha256":HASH},
                "rows":[{"weight_pct":60.,"return_pct":.2,"relative_volume":2.,"baseline_sessions":5,"current":receipt,"anchor":receipt},
                        {"weight_pct":40.,"return_pct":-.05,"relative_volume":1.,"baseline_sessions":5,"current":receipt,"anchor":receipt}]}
        rules=p.pressure_rules(report)
        self.assertEqual(rules["pressure"],"UP")
        self.assertEqual(rules["volume_pressure"],"UP")
        self.assertAlmostEqual(rules["signed_rvol"],.8)
        report["rows"][1]["relative_volume"]=None
        self.assertEqual(p.pressure_rules(report)["volume_pressure"],"UNAVAILABLE")
        report["weighted_breadth_pct"]=0
        self.assertEqual(p.pressure_rules(report)["pressure"],"ABSTAIN")
        report["complete_weighted_coverage"]=False
        self.assertEqual(p.pressure_rules(report)["pressure"],"UNAVAILABLE")

    def test_prospective_only_deduplicates_and_resolves_same_target(self):
        cutoff=self.cut
        self.tick(cutoff-timedelta(seconds=1),cutoff-timedelta(seconds=1),60000)
        ref={"price":60000.,"sha256":HASH,"received_utc":p._iso(cutoff),"exchange_utc":p._iso(cutoff)}
        inputs=(ref,"UP","UP","DOWN",{"test":"synthetic"})
        with patch.object(p,"_inputs",return_value=inputs),patch.object(p,"enabled",return_value=True),patch.object(bank,"enabled",return_value=True),patch.object(p,"_now",return_value=cutoff),patch.object(p.recorder_storage,"allow",return_value=True),patch.object(p.recorder_storage,"saved"):
            self.assertEqual(p._record(cutoff),7)
            self.assertEqual(p._record(cutoff),0)
            self.assertEqual(p._record(cutoff-timedelta(minutes=1)),0)
        target=cutoff+timedelta(minutes=1)
        self.tick(target-timedelta(seconds=1),target+timedelta(seconds=1),70000)
        self.tick(target+timedelta(seconds=1),target+timedelta(seconds=1),60050)
        self.tick(target+timedelta(seconds=2),target+timedelta(seconds=2),59000)
        with patch.object(p,"enabled",return_value=True),patch.object(p.recorder_storage,"allow",return_value=True):
            self.assertEqual(p._resolve(target+timedelta(seconds=89)),0)
            self.assertEqual(p._resolve(target+timedelta(seconds=90)),1)
            self.assertEqual(p._resolve(target+timedelta(seconds=100)),0)
        r=p.report(1)
        self.assertEqual(r["summary"]["attempts"],1)
        self.assertEqual(r["latest"][0]["observed_price"],60050)
        self.assertEqual(r["summary"]["methods"]["pressure"]["accuracy"],1)
        self.assertEqual(r["summary"]["paired_vs_ema"]["pressure"]["difference"],1)
        self.assertIsNone(r["summary"]["paired_vs_ema"]["pressure"]["session_bootstrap_95"])
        self.assertEqual(p.report(5)["summary"]["pending"],1)
        self.assertEqual(p.report(15)["summary"]["pending"],1)
        self.assertEqual(p.report(0)["summary"]["pending"],1)
        self.assertEqual(p.report(0)["latest"][0]["target_utc"],p._iso(p.target_for(cutoff,0)))
        self.assertNotEqual(p.report(15)["protocol_sha256"],p.report(5)["protocol_sha256"])

    def test_ema_original_cutoff_and_missing_labels(self):
        # 35 completed consecutive bars from 09:15 IST; the current
        # incomplete bar and later receipt must not enter the EMA input.
        start=self.cut.replace(hour=3,minute=45,second=0)
        for i in range(25):
            event=start+timedelta(minutes=i,seconds=55)
            self.tick(event,event,60000+i)
        self.tick(self.cut-timedelta(seconds=10),self.cut+timedelta(seconds=1),99999)
        with p._read() as db:
            direction,features=p._ema(db,self.cut)
        self.assertEqual(direction,"UNAVAILABLE")
        self.assertEqual(features["contiguous_session_bars"],25)
        self.assertIn("completed_bars_sha256",features)
        # A missing reference is recorded as unavailable, not a fabricated label.
        with patch.object(p,"_inputs",return_value=(None,"UP","UP","UP",{})),patch.object(p,"enabled",return_value=True),patch.object(bank,"enabled",return_value=True),patch.object(p,"_now",return_value=self.cut),patch.object(p.recorder_storage,"allow",return_value=True),patch.object(p.recorder_storage,"saved"):
            self.assertEqual(p._record(self.cut),7)
        out=p.report(5)
        self.assertEqual(out["summary"]["unverifiable"],1)
        self.assertEqual(out["summary"]["methods"]["pressure"]["unavailable"],1)
        self.assertIsNone(out["summary"]["methods"]["pressure"]["accuracy"])

    def test_paired_denominators_and_abstentions(self):
        rows=[{"session_ist":"2026-11-23","outcome":"UP","pressure":"UP","volume_pressure":"ABSTAIN","ema_rsi":"DOWN"},
              {"session_ist":"2026-11-23","outcome":"DOWN","pressure":"ABSTAIN","volume_pressure":"DOWN","ema_rsi":"DOWN"},
              {"session_ist":"2026-11-24","outcome":"FLAT","pressure":"UP","volume_pressure":"UP","ema_rsi":"UP"},
              {"session_ist":"2026-11-24","outcome":"UNVERIFIABLE","pressure":"UNAVAILABLE","volume_pressure":"UNAVAILABLE","ema_rsi":"UNAVAILABLE"}]
        s=p._summary(rows)
        self.assertEqual(s["directional_outcomes"],2)
        self.assertEqual(s["methods"]["pressure"]["scored_coverage"],.5)
        self.assertEqual(s["methods"]["ema_rsi"]["accuracy"],.5)
        self.assertEqual(s["paired_vs_ema"]["pressure"]["joint_scored"],1)
        self.assertEqual(s["paired_vs_ema"]["pressure"]["ema_accuracy"],0)
