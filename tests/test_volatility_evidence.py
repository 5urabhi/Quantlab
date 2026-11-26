from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import numpy as np
from workstation_api import volatility_evidence as v, constituent_alpha as a

NOW=datetime(2026,11,25,5,0,tzinfo=timezone.utc)
DAY="2026-11-25"

def chain(stamp,iv=20,shift=0):
    contracts=[]
    for i,strike in enumerate((980,990,1000,1010,1020)):
        for side in ("CE","PE"):
            contracts.append({"strike":strike,"expiry":"2026-12-29","option_type":side,
                "contract_master_verified":True,"quote_valid":True,"identity":"NSE_FNO:"+str(2*i+(1 if side=="CE" else 2)+shift),
                "lot_size":30,"oi":100,"volume":100,"iv":iv+(1 if side=="PE" else 0)})
    return {"expiry":"2026-12-29","received_utc":v.m._iso(stamp),"underlying_spot":1000,
            "contracts":contracts},"a"*64

def bars():
    return {i:(100.,101.,99.,100.+.001*i,100) for i in range(375)}

class VolatilityTests(TestCase):
    def test_same_entry_atm_contract_and_expiry(self):
        before=chain(NOW)
        after=chain(NOW+timedelta(minutes=15),22)
        after[0]["underlying_spot"]=1020
        row=v._matched_iv(before,after)
        self.assertEqual(row["strike"],1000)
        self.assertEqual(row["ce_iv_change_pp"],2.)
        self.assertEqual(row["pe_iv_change_pp"],2.)
        self.assertIsNone(v._matched_iv(before,chain(NOW+timedelta(minutes=15),22,shift=100)))
        self.assertIsNone(v._matched_iv(after,before))

    def test_iv_small_sample_never_claims_calibrated_interval(self):
        row=v._matched_iv(chain(NOW),chain(NOW+timedelta(minutes=15),21))
        r=v._iv_report([{**row,"session":DAY}],[DAY])
        self.assertEqual(r["state"],"descriptive_only_insufficient_sessions")
        self.assertIsNone(r["metrics"]["ce_iv_change_pp"]["holdout_90pct_interval_coverage"])

    def test_realized_features_invariant_to_future_and_no_gap_return(self):
        data=bars()
        rows,counts=v._rv_rows([DAY],{DAY:data},15)
        self.assertEqual(counts["scored"],len(rows))
        old=rows[0]
        data[45]=(100.,102.,99.,101.,100)
        newer,_=v._rv_rows([DAY],{DAY:data},15)
        np.testing.assert_array_equal(old["features"],newer[0]["features"])
        self.assertEqual(old["ewma"],newer[0]["ewma"])
        self.assertNotEqual(old["actual"],newer[0]["actual"])
        del data[45]
        returns=v._returns(data)
        self.assertNotIn(45,returns)
        self.assertNotIn(46,returns)
        _,c=v._rv_rows([DAY],{DAY:data},15)
        self.assertGreater(c["missing_adjacent_returns"],0)

    def test_garch_prediction_positive_and_insufficient_audit(self):
        fit={"omega":.1,"alpha":.1,"beta":.8,"training_variance":1.}
        self.assertGreater(v._garch_predict(np.asarray([1.,-1.,2.]),fit,15),0.)
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)), \
             patch.object(v,"_index_only",return_value=({DAY:bars()},"b"*64)),patch.object(v,"_fit_garch") as fit_mock:
            report=v.rv_run(batch_id="batch_"+"a"*16)
            self.assertEqual(report["state"],"insufficient_evidence")
            fit_mock.assert_not_called()
            self.assertTrue(a.result_path(report["audit_id"],audit=True).is_file())
