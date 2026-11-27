"""Regression tests for date-aware continuous cash and derivative cutoffs."""
from datetime import date,time,datetime,timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import numpy as np
import pandas as pd

from workstation_api import nse_session_policy as s, verified_equity_context as ve
from workstation_api import service, banknifty_forecast_features as f, dhan_option_chain
from scripts.audit_banknifty_stock_clock import clock_summary


class SessionPolicyTests(TestCase):
    def test_all_sixteen_audited_bank_identities_and_date_boundaries(self):
        self.assertEqual(len(s.BANK_CAS_IDENTITIES),16)
        for identity,symbol in s.BANK_CAS_IDENTITIES.items():
            self.assertEqual(s.cash_bank_minutes("2026-07-31",identity,symbol),375)
            self.assertEqual(s.cash_bank_minutes("2026-08-03",identity,symbol),360)
            self.assertEqual(s.cash_bank_minutes("2026-12-06",identity),360)
            self.assertEqual(s.cash_bank_minutes("2026-12-07",identity,symbol),375)
        self.assertEqual(s.cash_bank_minutes("2026-08-03","NSE_EQ:999","HDFCBANK"),375)
        self.assertEqual(s.cash_bank_minutes("2026-08-03","NSE_EQ:1333","OTHER"),375)
        self.assertEqual(s.cash_bank_minutes("2026-08-03","NSE_FNO:1333","HDFCBANK"),375)

    def test_expiring_index_contract_close_differs_from_segment_maximum(self):
        self.assertEqual(s.index_expiry_close("2026-07-28"),time(15,30))
        self.assertEqual(s.index_expiry_close("2026-08-25"),time(15,40))
        self.assertEqual(s.index_expiry_close("2026-12-29"),time(15,30))
        self.assertEqual(s.index_contract_close("2026-12-29","2027-01-26"),time(15,45))
        self.assertIsNone(s.index_contract_close("2026-12-29",None))
        self.assertEqual(s.derivatives_close("2026-12-29"),time(15,45))
        self.assertEqual(dhan_option_chain._pick_expiry(["2026-08-25","2026-09-29"],
            datetime.fromisoformat("2026-08-25T15:35:00+05:30")),"2026-08-25")
        self.assertEqual(dhan_option_chain._pick_expiry(["2026-12-29","2027-01-26"],
            datetime.fromisoformat("2026-12-29T15:35:00+05:30")),"2027-01-26")

    def test_cash_audit_accepts_360_and_excludes_auction_but_rejects_missing_cts(self):
        days=["2026-07-31","2026-08-03","2026-08-04","2026-12-07"]
        clocks=[]
        for day,n in zip(days,[375,360,359,375]):
            clocks.extend(pd.date_range(day+" 09:15",periods=n,freq="min",tz="Asia/Kolkata"))
        clocks.append(pd.Timestamp("2026-08-03 15:32",tz="Asia/Kolkata"))
        payload=pd.DataFrame({"datetime":clocks}).to_csv(index=False).encode()
        result=clock_summary(payload,set(days),len(clocks),"NSE_EQ:1333","HDFCBANK")
        self.assertEqual(result["complete_regular_sessions"],3)
        self.assertEqual(result["expected_minute_slots"],1470)
        self.assertEqual(result["observed_minute_slots"],1469)
        self.assertEqual(result["outside_regular_hours_rows"],1)
        self.assertEqual(result["most_frequent_missing_minutes_partial_sessions"],[["15:14",1]])

    def test_original_equity_coverage_and_native_daily_close_not_conflated(self):
        identity="NSE_EQ:1333"
        with TemporaryDirectory() as tmp,patch.object(service,"DATA",Path(tmp)):
            folder=Path(tmp)/"dhan/history/NSE_EQ/1333"
            folder.mkdir(parents=True)
            clocks=pd.date_range("2026-08-03 09:15",periods=360,freq="min",tz="Asia/Kolkata")
            def save(stem,interval,frame):
                path=folder/(stem+".csv")
                frame.to_csv(path,index=False)
                path.with_suffix(".json").write_text(json.dumps({"instrument_id":identity,
                    "interval_minutes":interval,"rows":len(frame),"coverage":[],
                    "sha256":sha256(path.read_bytes()).hexdigest()}))
                return path.with_suffix(".json")
            path=save("1m",1,pd.DataFrame({"datetime":clocks,"close":100.}))
            series,info=ve._original_daily(path,identity,1,"2026-08-05",[ve.MAX_TOTAL_BYTES])
            self.assertEqual(series["2026-08-03"],100)
            self.assertEqual(info["scheduled_session_minute_counts"],{"360":1})
            panel,meta=ve.original_panel("2026-08-05")
            self.assertNotIn("NSE_EQ_1333",panel.columns)
            self.assertEqual(meta["cas_daily_missing_sessions"],1)
            save("daily",None,pd.DataFrame({"datetime":["2026-08-03T00:00:00+05:30"],"close":[103.]}))
            panel,meta=ve.original_panel("2026-08-05")
            self.assertEqual(panel.loc["2026-08-03","NSE_EQ_1333"],103)
            self.assertEqual(meta["cas_native_daily_preferred_sessions"],1)
            self.assertEqual(meta["conflicting_daily_closes"],0)

    def test_forecast_cash_auction_mask_and_scheduled_coverage(self):
        ids=["NSE_EQ:1333","NSE_EQ:4963","NSE_EQ:5900"]
        day="2026-08-03"
        c=100.+np.arange(375)*.01
        arr=np.column_stack((c,c+.1,c-.1,c,np.full(375,10.)))
        stocks={identity:{day:arr} for identity in ids}
        names,values,ok=f.banks_at(day,np.array([358,359,360,369]),ids,stocks,set(ids),None,[],arr[:,3])
        self.assertEqual(ok.tolist(),[True,True,False,False])
        self.assertEqual(values[:,names.index("bank_scheduled_open_count")].tolist(),[3.,3.,0.,0.])
        self.assertEqual(values[:,names.index(ids[0]+"_scheduled_open")].tolist(),[1.,1.,0.,0.])
        self.assertTrue(np.isnan(f.continuous_stock(day,ids[0],arr)[360:]).all())
        self.assertTrue(np.isfinite(arr).all())
        self.assertTrue(np.isfinite(f.continuous_stock("2026-12-07",ids[0],arr)).all())
