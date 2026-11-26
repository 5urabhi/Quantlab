"""Synthetic market context fixtures; no empirical alpha or provider claim."""
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from hashlib import sha256
from contextlib import closing
import csv
import json
import sqlite3
from workstation_api import market_context as m,context_alpha as c,constituent_alpha as a

NOW=datetime(2026,11,25,6,0,tzinfo=timezone.utc)
def iso(t):return m._iso(t)

def source_csv(factor="SP500_CLOSE"):
    return "factor,event_utc,available_utc,value\n"+ "\n".join(
        ",".join((factor,iso(NOW-timedelta(days=d,hours=1)),iso(NOW-timedelta(days=d)),str(v)))
        for d,v in ((2,100),(1,101)))

def chain(t,iv=20,oi_increment=0,volume_increment=0):
    rows=[]
    for i,k in enumerate((980,990,1000,1010,1020)):
        for side in ("CE","PE"):
            rows.append({"strike":k,"expiry":"2026-11-25","option_type":side,
                "contract_master_verified":True,"quote_valid":True,
                "identity":"NSE_FNO:"+str(2*i+(1 if side=="CE" else 2)),
                "lot_size":30,"oi":100+(oi_increment if side=="PE" else 0),
                "volume":100+(volume_increment if side=="PE" else 0),"iv":iv+(1 if side=="PE" else 0)})
    v={"underlying":"BANKNIFTY","underlying_spot":1000,"expiry":"2026-11-25",
       "received_utc":iso(t),"read_only":True,"contracts":rows}
    raw=json.dumps(v,sort_keys=True,separators=(",",":"))
    return v,sha256(raw.encode()).hexdigest(),raw


class ContextEvidenceTests(TestCase):
    def test_receipt_cannot_backdate_and_archive_requires_availability(self):
        with TemporaryDirectory() as tmp,patch.object(m.shared_market_data,"database_path",return_value=Path(tmp)/"shared.db"):
            receipt=m.ingest(source_csv(),"fixture vendor A","receipt",True,now=NOW)
            self.assertTrue(receipt["inserted"])
            self.assertFalse(m.ingest(source_csv(),"fixture vendor A","receipt",True,now=NOW)["inserted"])
            with self.assertRaises(ValueError):
                m.ingest(source_csv(),"other vendor","receipt",True,now=NOW)
            with closing(sqlite3.connect(Path(tmp)/"shared.db")) as db:
                timelines,_=m.load_timelines(db,NOW-timedelta(days=3),NOW,"receipt")
                _,before,_=m.factor_at(timelines,NOW-timedelta(seconds=1))
                self.assertEqual(before["SP500_CLOSE"]["state"],"unavailable")
                _,after,_=m.factor_at(timelines,NOW)
                self.assertAlmostEqual(after["SP500_CLOSE"]["change_feature"],100.)
                self.assertEqual(after["SP500_CLOSE"]["known_utc"],iso(NOW))
            m.ingest(source_csv("NIKKEI_CLOSE"),"fixture vendor A","archive",True,now=NOW)
            with closing(sqlite3.connect(Path(tmp)/"shared.db")) as db:
                t,_=m.load_timelines(db,NOW-timedelta(days=3),NOW,"archive")
                self.assertEqual(m.factor_at(t,NOW-timedelta(days=1,seconds=1))[1]["NIKKEI_CLOSE"]["state"],"stale_or_missing_anchor")
                self.assertEqual(m.factor_at(t,NOW-timedelta(days=1))[1]["NIKKEI_CLOSE"]["state"],"available")
                t,_=m.load_timelines(db,NOW-timedelta(days=3),NOW,"receipt")
                self.assertNotIn("NIKKEI_CLOSE",t)
    def test_invalid_input_and_future_availability(self):
        with self.assertRaises(ValueError):
            m.parse_csv("factor,event_utc,available_utc,value\nNIKKEI_CLOSE,2026-11-24T06:00:00,2026-11-24T07:00:00+00:00,100",NOW)
        with self.assertRaises(ValueError):
            m.parse_csv("factor,event_utc,available_utc,value\nNIKKEI_CLOSE,"+iso(NOW)+","+iso(NOW+timedelta(seconds=1))+",100",NOW)
    def test_timeline_preserves_event_order_and_revisions(self):
        a1=NOW-timedelta(days=2);a2=NOW-timedelta(days=1)
        t=m.Timeline([(a1,a1,100.,"x","a"),(a2,a2,101.,"x","b"),
            (NOW,a1,99.,"x","c")])
        self.assertEqual(t.at(a2)[0][2],101.)
        self.assertEqual(t.at(a2)[1][2],100.)
        self.assertEqual(t.at(NOW)[0][2],101.)
        self.assertEqual(t.at(NOW)[1][2],99.)
    def test_nse_participants_reconcile_and_preserve_original(self):
        report="Original NSE fixture\nClient Type,Future Index Long,Future Index Short,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short\n"
        report+="Client,20,10,30,10,20,30\nDII,10,20,10,30,20,10\nFII,20,10,30,10,20,30\nPro,10,20,10,30,20,10\nTOTAL,60,60,80,80,80,80\n"
        with TemporaryDirectory() as tmp,patch.object(m.shared_market_data,"database_path",return_value=Path(tmp)/"shared.db"):
            r=m.ingest_participant(report,"2026-11-24",iso(NOW-timedelta(hours=8)),"oi","archive",True,now=NOW)
            self.assertEqual(r["rows"],12)
            with closing(sqlite3.connect(Path(tmp)/"shared.db")) as db:
                self.assertEqual(db.execute("SELECT value FROM market_context_observations WHERE factor='CLIENT_INDEX_FUT_NET'").fetchone()[0],10.)
                self.assertEqual(db.execute("SELECT original_sha256 FROM market_context_raw_reports").fetchone()[0],sha256(report.encode()).hexdigest())
            with self.assertRaises(ValueError):
                m.ingest_participant(report.replace("TOTAL,60","TOTAL,61"),"2026-11-24",iso(NOW-timedelta(hours=8)),"oi","archive",True,now=NOW)
    def test_original_option_chain_and_no_future_receipts(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE option_chain_observations(underlying TEXT,expiry TEXT,captured_utc TEXT,normalized_json TEXT,snapshot_sha256 TEXT)")
            for ts,iv,oi,vol in ((NOW-timedelta(minutes=15,seconds=1),18,0,0),(NOW-timedelta(seconds=1),20,10,10),(NOW+timedelta(seconds=1),99,99,99)):
                v,h,raw=chain(ts,iv,oi,vol)
                db.execute("INSERT INTO option_chain_observations VALUES(?,?,?,?,?)",("BANKNIFTY",v["expiry"],v["received_utc"],raw,h))
            vector,detail=m.options_at(db,NOW)
            self.assertEqual(detail["matched_prior_strikes"],5)
            self.assertAlmostEqual(detail["put_call_oi_ratio"],1.1)
            self.assertEqual(detail["features"]["same_atm_iv_change_pct_points"],2.)
            self.assertEqual(detail["features"]["atm_iv_pct"],20.5)
            self.assertEqual(detail["features"]["volume_increment_imbalance"],1.)
            self.assertEqual(len(vector),len(m.OPTION_NAMES))
            db.execute("UPDATE option_chain_observations SET snapshot_sha256='bad' WHERE captured_utc=?", (iso(NOW-timedelta(seconds=1)),))
            self.assertIsNone(m.options_at(db,NOW))
    def test_nifty_uses_receipt_and_exchange_cutoffs(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE live_ticks(identity TEXT,price REAL,exchange_utc TEXT,received_utc TEXT,packet_sha256 TEXT)")
            for t,v,lag in ((NOW-timedelta(minutes=30,seconds=2),100.,1),(NOW-timedelta(seconds=2),101.,1),(NOW-timedelta(seconds=1),300.,2)):
                db.execute("INSERT INTO live_ticks VALUES(?,?,?,?,?)",("INDEX:NIFTY50",v,iso(t),iso(t+timedelta(seconds=lag)),"a"*64))
            vector,detail=m.domestic_at(db,NOW,120.)
            self.assertAlmostEqual(vector[0],100.)
            self.assertAlmostEqual(vector[1],20.)
            self.assertEqual(vector[2],0.)
            self.assertEqual(detail["current"]["price"],101.)

class ContextStudyTests(TestCase):
    def test_matching_excludes_missing_context_without_replacement(self):
        rows=[{"cutoff_utc":iso(NOW+timedelta(minutes=i)),"index":[0.,0.,0.],"full":[0.]} for i in range(3)]
        good=([0.]*len(m.OPTION_NAMES),{"sha256":"a"*64})
        with patch.object(m,"options_at",side_effect=[good,None,good]):
            kept,counts,coverage=c._attach(None,rows,{},"options")
        self.assertEqual([x["cutoff_utc"] for x in kept],[rows[0]["cutoff_utc"],rows[2]["cutoff_utc"]])
        self.assertEqual(counts,{"base_scored":3,"options_available":2,"context_matched":2,"missing_options_context":1})
        self.assertEqual(coverage,{})
        self.assertEqual(len(c._view(kept,("options",))[0]["full"]),1+len(m.OPTION_NAMES))
    def test_blocked_context_still_exports_audit(self):
        dates=["2026-11-24"]
        status={"training_dates":dates,"calibration_dates":[],"holdout_dates":[]}
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)), \
             patch.object(a,"readiness",return_value=status), \
             patch.object(a,"_read",side_effect=lambda:sqlite3.connect(":memory:")), \
             patch.object(a,"_rows",return_value=[]),patch.object(a,"_fit") as fit:
            result=c.run(scope="combined")
            with a.result_path(result["audit_id"],audit=True).open() as f:
                self.assertEqual(len(list(csv.DictReader(f))),2)
        fit.assert_not_called()
        self.assertEqual(result["state"],"awaiting_recorded_sessions")
        self.assertIsNone(result["run_id"])
        self.assertFalse(result["live_model_promoted"])
    def test_enriched_models_compare_identical_holdout(self):
        def samples(days):
            out=[]
            for day in days:
                for i in range(6):
                    cls=i%3-1;t=datetime.fromisoformat(day+"T05:00:00+00:00")+timedelta(minutes=10*i)
                    out.append({"session":day,"cutoff_utc":iso(t),"decision_utc":iso(t),
                        "target_utc":iso(t+timedelta(minutes=5)),"regime":"range",
                        "return_bps":float(cls*20),"class":cls,
                        "index":[float(i),0.],"full":[float(i),0.,float(cls)],
                        "context":{"options":[float(cls*2),0.]},"context_evidence":{"options":{"sha256":"a"*64}}})
            return out
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(60)]
        train,cal,test=[samples(x) for x in (dates[:30],dates[30:40],dates[40:])]
        methods,_,quantiles,records=c._assess(train,cal,test,"options")
        self.assertEqual(methods["no_trade"]["sum_net_index_proxy_bps"],0.)
        self.assertIn("constituent_options_logistic",methods)
        self.assertIn("constituent_options_boosting",methods)
        self.assertTrue(all(x["eligible_samples"]==len(test) for x in methods.values()))
        self.assertEqual(len(records),len(test)*(len(methods)+1))
        self.assertEqual(len(quantiles["pinball_loss_bps"]),3)
        self.assertEqual(sum(bool(r["context_evidence_json"]) for r in records),len(test))
