from datetime import datetime,timedelta,timezone
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from workstation_api import forecast_depth_research as f, constituent_alpha as a
from workstation_api import auto_paper_selection as s

NOW=datetime(2026,11,25,5,0,tzinfo=timezone.utc)
def book(side,strike,identity):
    return {"option_type":side,"strike":strike,"identity":identity,"expiry":"2026-12-29",
            "lot_size":30,"spread_bps":10.,"greeks":{"delta":.5 if side=="CE" else -.5}}

class ForecastDepthTests(TestCase):
    def test_forecast_source_not_available_live(self):
        with self.assertRaises(ValueError):
            s._source(NOW,{},forecast_only=True)

    def test_only_verified_defined_risk_structure_order(self):
        books=[book("CE",63000.,"NSE_FNO:1"),book("CE",63100.,"NSE_FNO:2"),
               book("PE",63000.,"NSE_FNO:3"),book("PE",63100.,"NSE_FNO:4")]
        no_credit=list(f._structures(books,63050.,False))
        self.assertEqual(sum(name=="LONG_OPTION" for name,_ in no_credit),4)
        self.assertEqual(sum(name.endswith("debit") for name,_ in no_credit),2)
        self.assertFalse(any(name.endswith("credit") for name,_ in no_credit))
        for name,legs in f._structures(books,63050.,True):
            if name!="LONG_OPTION":
                f.replay.studio._validate_structure(name,legs)

    def test_target_exit_uses_declared_clock(self):
        candidate={"strategy":"LONG_OPTION"}
        target=NOW+timedelta(minutes=15)
        cfg={"hold_seconds":900}
        def enter(row,now,*,update,first_book):
            self.assertEqual(now,NOW+timedelta(seconds=6))
            update(row,"paper_open")
        def exit_(row,now,*,update,first_book):
            self.assertEqual(a._stamp(row["exit_decision_utc"]),target)
            self.assertEqual(now,target+timedelta(seconds=6))
            update(row,"complete",net_pnl_inr=42.)
        with patch.object(f.engine,"_entry",side_effect=enter),patch.object(f.engine,"_exit",side_effect=exit_):
            result=f._execute(candidate,NOW,target,cfg,4250.,lambda *args:None)
        self.assertEqual(result["net_pnl_inr"],42.)

    def test_missing_ledger_does_not_fit(self):
        status={"training_dates":[],"calibration_dates":[],"holdout_dates":[],"required_sessions":60}
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)),patch.object(a,"readiness",return_value=status),patch.object(a,"_fit") as fit:
            r=f.run()
            self.assertEqual(r["state"],"insufficient_matched_evidence")
            self.assertTrue(a.result_path(r["audit_id"],audit=True).is_file())
            self.assertFalse(r["live_model_promoted"])
            fit.assert_not_called()
