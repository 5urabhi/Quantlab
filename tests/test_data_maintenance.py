from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import hashlib
import json

from workstation_api import data_maintenance as m, historical_alpha as h
from workstation_api import options_history_sync as opt, expired_options_backtest as exp


class MaintenanceTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p=patch.object(m.service,"DATA",Path(self.tmp.name))
        self.p.start();self.addCleanup(self.p.stop)
        self.legacy=patch.object(m.mp,"configure_sync")
        self.legacy.start();self.addCleanup(self.legacy.stop)
        self.stop_was_set=m.STOP.is_set()
        m.STOP.clear()
        self.addCleanup(m.STOP.set if self.stop_was_set else m.STOP.clear)
        self.now=datetime(2026,11,26,11,tzinfo=timezone.utc) # 16:30 IST

    def test_persisted_consent_and_quiet_window(self):
        cfg={**m.DEFAULT,"enabled":True}
        with self.assertRaises(ValueError):
            m.configure(cfg,False)
        self.assertFalse(m.enabled())
        m.configure(cfg,True)
        self.assertEqual(m.config(),cfg)
        self.assertTrue(m.safe_window(self.now))
        self.assertFalse(m.safe_window(datetime(2026,11,26,5,tzinfo=timezone.utc)))
        self.assertEqual(m.target_dates(self.now),(date(2026,11,27),date(2026,11,25)))
        self.assertEqual(m.target_dates(datetime(2026,11,30,1,tzinfo=timezone.utc))[0],date(2026,11,28))
        self.assertTrue(m._due(cfg,{},self.now))
        self.assertFalse(m._due(cfg,{},datetime(2026,11,26,5,tzinfo=timezone.utc)))
        m.configure({**cfg,"enabled":False},False)
        self.assertFalse(m.enabled())

    def test_scope_and_request_bounds(self):
        for invalid in ({**m.DEFAULT,"index_days":366},{**m.DEFAULT,"wings":6},
                        {**m.DEFAULT,"enabled":True,"index":False,"constituents":True}):
            with self.assertRaises(ValueError):
                m.validate(invalid)
        source={"coverage":[(date(2026,11,20),date(2026,11,27))],
                "days":{"2026-11-23":{0:(1,1,1,1)},"2026-11-24":{i:None for i in range(375)}}}
        other={"complete":{"2026-11-25":{}}}
        plan,missing=m._index_plan(source,other,date(2026,11,20),date(2026,11,27),
                                  "INDEX:BANKNIFTY",{},self.now)
        self.assertEqual(missing,["2026-11-23","2026-11-25"])
        self.assertEqual([x[0].isoformat() for x in plan],missing)
        state={"repairs":{"INDEX:BANKNIFTY|2026-11-23":self.now.isoformat()}}
        plan,_=m._index_plan(source,other,date(2026,11,20),date(2026,11,27),
                             "INDEX:BANKNIFTY",state,self.now)
        self.assertEqual([x[0].isoformat() for x in plan],["2026-11-25"])

    def test_disabled_or_market_open_never_calls_provider(self):
        with patch.object(m.dhan_auth,"check_profile") as provider:
            self.assertEqual(m.run(now=self.now)["state"],"paused")
            m.configure({**m.DEFAULT,"enabled":True},True)
            self.assertEqual(m.run(now=datetime(2026,11,26,5,tzinfo=timezone.utc))["state"],"paused")
            provider.assert_not_called()

    def test_missing_credentials_report_blocker(self):
        m.configure({**m.DEFAULT,"enabled":True},True)
        with patch.object(m,"_now",return_value=self.now),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":False}):
            report=m.run(now=self.now)
        self.assertEqual(report["state"],"blocked")
        self.assertEqual(m._state()["last_run"]["state"],"blocked")

    def test_shared_index_receipts_reused_and_newest_valid_minute_wins(self):
        root=Path(self.tmp.name)
        def receipt(name,when,rows):
            folder=root/name;folder.mkdir()
            p=folder/"original.csv";p.write_text("fixture")
            return p,folder/"manifest.json",{"from_inclusive":"2026-11-23","to_exclusive":"2026-11-26",
                         "retrieved_utc":when,"sha256":name,"row_count":len(rows)},rows
        newer=receipt("batch_"+"a"*16,"2026-11-26T11:00:00+00:00",{"2026-11-24":{0:(2,2,2,2,0)}})
        older=receipt("batch_"+"b"*16,"2026-11-25T11:00:00+00:00",{"2026-11-24":{0:(1,1,1,1,0),1:(3,3,3,3,0)}})
        with patch.object(h.cockpit_sources,"_candidates",return_value=[x[:3] for x in (older,newer)]),patch.object(h,"_read_file",side_effect=lambda path,*args: next(x[3] for x in (newer,older) if x[0]==path)):
            data,hashes,failures=h.shared_index_sources(date(2026,11,23),date(2026,11,26),[1000])
        self.assertEqual(data["2026-11-24"][0][3],2)
        self.assertEqual(data["2026-11-24"][1][3],3)
        self.assertEqual(len(hashes),2)
        self.assertEqual(failures,{})

    def test_bounded_option_pass_resumes_and_counts_observed_reused_rows(self):
        def fetch(body):
            # The two-date endpoint is inclusive. A valid empty response
            # is request evidence, not evidence of minute completeness.
            side="ce" if body["drvOptionType"]=="CALL" else "pe"
            d=date.fromisoformat(body["fromDate"])
            t=datetime(d.year,d.month,d.day,4,0,tzinfo=timezone.utc).timestamp()
            return {"data":{side:{"timestamp":[t],"open":[10],"high":[10],"low":[10],"close":[10],"strike":[60000],"volume":[1]}}}
        args=dict(start_date="2026-10-01",end_date="2026-10-04",wings=0,today=date(2026,11,26),fetcher=fetch)
        first=opt.run(**args,request_limit=1)
        self.assertEqual(first["new_receipts"],1)
        self.assertEqual(first["state"],"partial_requests")
        self.assertGreater(first["unattempted_requests"],0)
        self.assertEqual(first["observed_rolling_minute_slots"],1)
        second=opt.run(**args)
        self.assertEqual(second["existing_verified_receipts"],1)
        self.assertEqual(second["state"],"request_windows_checked")
        third=opt.run(**args)
        self.assertEqual(third["new_receipts"],0)
        self.assertEqual(third["observed_rolling_minute_slots"],second["observed_rolling_minute_slots"])
        self.assertFalse(third["continuous_coverage_certified"])
