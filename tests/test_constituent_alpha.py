"""Synthetic fixtures exercise the protocol; never market performance evidence."""
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import csv
import json
import sqlite3

import numpy as np
from workstation_api import constituent_alpha as a
from workstation_api import constituent_prospective as p

START=datetime(2026,10,1,3,45,tzinfo=timezone.utc)
DIGEST="a"*64
MEMBERSHIP="b"*64


def row(i,horizon=5):
    slot=START+timedelta(minutes=i)
    cutoff=slot+timedelta(seconds=10)
    decided=cutoff+timedelta(seconds=1)
    target=decided+timedelta(minutes=horizon)
    price=63000.+i
    def quote(t,price):
        return {"identity":"NSE_EQ:1","received_utc":p._iso(t-timedelta(seconds=1)),
                "exchange_trade_utc":p._iso(t-timedelta(seconds=2)),
                "packet_sha256":DIGEST,"membership_sha256":MEMBERSHIP,
                "price":price,"atp":100.,"buy_quantity":1000,"sell_quantity":500}
    e={"reference":{"price":price,"exchange_utc":p._iso(cutoff-timedelta(seconds=2)),
                     "received_utc":p._iso(cutoff-timedelta(seconds=1)),"sha256":DIGEST},
       "ema":{"quote_mode":"RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE","contiguous_session_bars":35,
              "last_observed_utc":p._iso(slot-timedelta(minutes=1)),"ema9":price,
              "ema21":price-2,"rsi14":60.},
       "expected_members":1,"members":1,"observed_weight_pct":100.,"membership_sha256":MEMBERSHIP,
       "weights_sha256":DIGEST,"weights_recorded_utc":p._iso(START),
       "constituent_receipts":[{"symbol":"BANK","weight_pct":100.,
             "current":quote(cutoff,101.),"anchor":quote(cutoff-timedelta(minutes=5),100.),
             "relative_volume":1.2,"baseline_sessions":5}]}
    return {"slot_utc":p._iso(slot),"session_ist":"2026-10-01","cutoff_utc":p._iso(cutoff),
            "decided_utc":p._iso(decided),"target_utc":p._iso(target),"horizon_minutes":horizon,
            "reference_price":price,"reference_sha256":DIGEST,"pressure":"UP","volume_pressure":"UP","ema_rsi":"UP",
            "evidence_json":json.dumps(e),"outcome":"UP","observed_price":price*1.001,
            "observed_exchange_utc":p._iso(target+timedelta(seconds=1)),
            "observed_received_utc":p._iso(target+timedelta(seconds=2)),"observed_sha256":DIGEST}


class AlphaEvidenceTests(TestCase):
    def test_missing_label_reserves_window_and_future_feature_rejected(self):
        rows=[row(i) for i in range(43)]
        rows[30]["outcome"]="UNVERIFIABLE"
        rows[30]["observed_price"]=None
        e=json.loads(rows[36]["evidence_json"])
        e["constituent_receipts"][0]["current"]["received_utc"]=p._iso(a._stamp(rows[36]["cutoff_utc"])+timedelta(seconds=1))
        rows[36]["evidence_json"]=json.dumps(e)
        samples,counts=a.sample_day(rows)
        self.assertEqual(counts["missing_label"],1)
        self.assertEqual(counts["missing_constituent_features"],1)
        self.assertEqual(counts["overlap_skipped"],10)
        self.assertEqual([a._stamp(r["decision_utc"]).minute for r in samples],[22])
        self.assertEqual(counts["reserved_nonoverlap"],2)
        self.assertAlmostEqual(samples[0]["return_bps"],10.)
        self.assertEqual(samples[0]["class"],1)
        self.assertAlmostEqual(samples[0]["full"][len(a.INDEX_FEATURES)],100.)

    def test_features_invariant_to_future_label_change(self):
        rows=[row(i) for i in range(31)]
        original,_=a.sample_day(rows)
        rows[-1]["observed_price"]=rows[-1]["reference_price"]*.999
        rows[-1]["outcome"]="DOWN"
        modified,_=a.sample_day(rows)
        self.assertEqual(original[0]["full"],modified[0]["full"])
        self.assertEqual(modified[0]["class"],-1)

    def test_missing_rvol_is_explicit_not_a_fake_observation(self):
        e=json.loads(row(30)["evidence_json"])
        e["constituent_receipts"][0]["relative_volume"]=None
        values=a._bank_features(e,a._stamp(row(30)["cutoff_utc"]))
        self.assertEqual(values[3:5],[0.,1.])
        e["weights_recorded_utc"]=p._iso(START+timedelta(days=1))
        with self.assertRaisesRegex(ValueError,"dated"):
            a._bank_features(e,a._stamp(row(30)["cutoff_utc"]))

    def test_partial_ledger_does_not_train(self):
        empty={"version":a.VERSION,"policy_sha256":a.POLICY_HASH,"horizon_minutes":5,
               "training_dates":["2026-10-01"],"calibration_dates":[],"holdout_dates":[]}
        with TemporaryDirectory() as tmp, \
             patch.object(a,"_root",return_value=Path(tmp)), \
             patch.object(a,"readiness",return_value=empty), \
             patch.object(a,"_read",side_effect=lambda:sqlite3.connect(":memory:")), \
             patch.object(a,"_rows",return_value=[row(i) for i in range(43)]), \
             patch.object(a,"_fit") as fit:
            out=a.run(horizon=5)
            with a.result_path(out["audit_id"],audit=True).open() as f:
                self.assertEqual(len(list(csv.DictReader(f))),2)
        fit.assert_not_called()
        self.assertEqual(out["state"],"awaiting_recorded_sessions")
        self.assertGreater(out["evidence_counts"]["scored"],0)
        self.assertIsNone(out["run_id"])

    def test_original_ledger_date_window(self):
        with sqlite3.connect(":memory:") as db:
            p._setup(db)
            r=row(30)
            fields=list(r)+["identity","protocol_hash"]
            db.execute("INSERT INTO banknifty_paired_signals("+",".join(fields)+") VALUES("+",".join("?" for _ in fields)+")",
                       (*r.values(),"INDEX:BANKNIFTY",p.PROTOCOL_HASH))
            self.assertEqual(a._days(db,5,"2026-10-02"),["2026-10-01"])
            self.assertEqual(a._days(db,5,"2026-10-01"),[])
            self.assertEqual(a._rows(db,"2026-10-01",5),[r])


def fixture_samples(days):
    rows=[]
    for d,day in enumerate(days):
        for i in range(9):
            cls=(i+d)%3-1
            t=datetime.fromisoformat(day+"T05:00:00+00:00")+timedelta(minutes=i*10)
            index=[float(i),float(d%3),float(i-4),4.,0.,50.,90.]
            full=index+[float(cls*10),float(cls*50),1.,0.,1.,0.,1.,0.,1.]
            rows.append({"session":day,"decision_utc":p._iso(t),"target_utc":p._iso(t+timedelta(minutes=5)),
                         "reference_price":63000.,"return_bps":float(cls*20),"class":cls,
                         "index":index,"full":full,"regime":"range",
                         "pressure":"UP" if cls==1 else "DOWN" if cls==-1 else "ABSTAIN",
                         "volume_pressure":"UNAVAILABLE","ema_rsi":"ABSTAIN"})
    return rows


class AlphaModelTests(TestCase):
    def test_model_outputs_and_matched_comparison(self):
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(60)]
        train,cal,test=[fixture_samples(d) for d in (dates[:30],dates[30:40],dates[40:])]
        methods,regimes,q,records=a._compare(train,cal,test)
        self.assertEqual(methods["no_trade"]["sum_net_index_proxy_bps"],0.)
        self.assertEqual(methods["volume_pressure"]["unavailable"],len(test))
        for model in a.MODELS:
            self.assertEqual(methods[model]["eligible_samples"],len(test))
            self.assertIsNotNone(methods[model]["brier"])
        self.assertEqual(regimes["range"]["samples"],len(test))
        self.assertEqual(len(q["pinball_loss_bps"]),3)
        self.assertEqual(len(records),(len(methods)+1)*len(test))
        self.assertTrue(all(r["session"] in dates[40:] for r in records))
        for r in records:
            if r["p_up"] is not None:
                self.assertAlmostEqual(r["p_up"]+r["p_flat"]+r["p_down"],1.)
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)):
            run_id=a._save(records)
            with a.result_path(run_id).open() as f:
                self.assertEqual(len(list(csv.DictReader(f))),len(records))

    def test_run_isolates_chronological_splits(self):
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(60)]
        status={"training_dates":dates[:30],"calibration_dates":dates[30:40],"holdout_dates":dates[40:]}
        def per_day(db,day,horizon):
            return fixture_samples([day])
        def compare(train,cal,test,progress):
            self.assertEqual({r["session"] for r in train},set(dates[:30]))
            self.assertEqual({r["session"] for r in cal},set(dates[30:40]))
            self.assertEqual({r["session"] for r in test},set(dates[40:]))
            return {},{},None,[{"session":test[0]["session"]}]
        with TemporaryDirectory() as tmp, \
             patch.object(a,"readiness",return_value=status), \
             patch.object(a,"_read",side_effect=lambda:sqlite3.connect(":memory:")), \
             patch.object(a,"_rows",side_effect=per_day), \
             patch.object(a,"sample_day",side_effect=lambda rows:(rows,{"scored":len(rows)})), \
             patch.object(a,"_walk_forward",return_value=[]),patch.object(a,"_compare",side_effect=compare), \
             patch.object(a,"_root",return_value=Path(tmp)):
            result=a.run()
        self.assertEqual(result["state"],"holdout_assessment_available")
        self.assertFalse(result["live_model_promoted"])
        self.assertFalse(result["broker_orders_enabled"])
