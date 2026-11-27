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
        self.assertTrue(m._due(cfg,{},datetime(2026,11,26,5,tzinfo=timezone.utc)))
        m.configure({**cfg,"enabled":False},False)
        self.assertFalse(m.enabled())

    def test_scope_and_request_bounds(self):
        for invalid in ({**m.DEFAULT,"index_days":366},{**m.DEFAULT,"wings":11},
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

    def test_disabled_or_recording_pressure_never_calls_provider(self):
        live=datetime(2026,11,26,5,tzinfo=timezone.utc)
        with patch.object(m.dhan_auth,"check_profile") as provider:
            self.assertEqual(m.run(now=self.now)["state"],"paused")
            m.configure({**m.DEFAULT,"enabled":True},True)
            with patch.object(m,"_now",return_value=live),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m,"live_pressure",return_value="live_quote_queue_backlog"):
                result=m.run(now=live)
            self.assertEqual(result["state"],"paused")
            self.assertEqual(result["pause_reason"],"live_quote_queue_backlog")
            self.assertEqual(m._state()["next_due_reason"],"live_recording_priority")
            self.assertEqual(m._state()["next_due_utc"],(live+m.PRESSURE_RETRY).isoformat())
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


    def test_productive_retry_and_backoff(self):
        option={"state":"partial","new_receipts":112,"unattempted_requests":4324,
                "rejected_windows":0,"unreadable_receipts_encountered":0}
        report={"state":"partial","sources":{"options":option}}
        self.assertEqual(m._next_schedule(report),(m.PRODUCTIVE_RETRY,"more_option_requests"))
        for changes in ({"new_receipts":0},{"unattempted_requests":0},
                        {"rejected_windows":1},{"unreadable_receipts_encountered":1},{"state":"blocked"}):
            self.assertEqual(m._next_schedule({"state":"partial","sources":{"options":{**option,**changes}}})[0],m.RETRY)
        self.assertEqual(m._next_schedule({"state":"checked"})[0],m.CHECKED_RETRY)
        self.assertEqual(m._next_schedule({"state":"paused"})[0],m.RETRY)
        panel={"state":"partial","repair_dates_attempted":10,"retryable_member_session_gaps":395,
               "batch_status":"completed","batch_errors":False}
        self.assertEqual(m._next_schedule({"state":"partial","sources":{"bank_panel":panel}})[0],m.PRODUCTIVE_RETRY)
        self.assertEqual(m._next_schedule({"state":"partial","sources":{"bank_panel":{**panel,"retryable_member_session_gaps":0}}})[0],m.RETRY)
        self.assertEqual(m._next_schedule({"state":"partial","sources":{"bank_panel":{**panel,"batch_errors":True},"options":option}})[0],m.RETRY)
        self.assertEqual(m._next_schedule({"state":"partial","sources":{"index":{"INDEX:BANKNIFTY":{"state":"partial","downloaded_windows":5,"uncovered_request_windows":10}}}})[0],m.PRODUCTIVE_RETRY)

    def test_productive_legacy_checkpoint_resumes_and_respects_consent(self):
        cfg={**m.DEFAULT,"enabled":True}
        state={"target":m._target(self.now),"next_due_utc":(self.now+timedelta(hours=3)).isoformat(),
               "last_run":{"state":"partial","finished_utc":(self.now-timedelta(minutes=3)).isoformat(),
                           "sources":{"options":{"state":"partial","new_receipts":112,"unattempted_requests":4324}}}}
        self.assertTrue(m._due(cfg,state,self.now))
        self.assertFalse(m._due({**cfg,"enabled":False},state,datetime(2026,11,26,5,tzinfo=timezone.utc)))
        state["next_due_reason"]="source_error_backoff"
        self.assertFalse(m._due(cfg,state,self.now))

    def test_productive_pass_persists_finished_time_schedule(self):
        cfg={**m.DEFAULT,"enabled":True,"index":False,"constituents":False}
        m.configure(cfg,True)
        finish=self.now+timedelta(minutes=4)
        lane={"state":"partial_requests","existing_verified_receipts":3208,"new_receipts":112,
              "planned_missing_requests":4436,"unattempted_requests":4324,"empty_processed_receipts":0,
              "usable_rows_in_processed_receipts":68995,"unreadable_receipts_encountered":0,
              "excluded_active_calendar_days":2,"continuous_coverage_certified":False,
              "empty_verified_receipts":486,"observed_rolling_minute_slots":1679528,
              "observed_offset_session_pairs":4498,"observed_session_dates":245,"rejected_requests":[]}
        with patch.object(m,"_now",return_value=finish),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":True}),patch.object(m.options,"run",return_value=lane) as provider,patch.object(m.mp,"_history",return_value={"days":{}}):
            result=m.run(now=self.now)
        self.assertEqual(result["state"],"partial")
        self.assertEqual(provider.call_args.kwargs["request_limit"],m.MAX_OPTION_REQUESTS)
        saved=m._state()
        self.assertEqual(saved["next_due_utc"],(finish+m.PRODUCTIVE_RETRY).isoformat())
        self.assertEqual(saved["next_due_reason"],"more_option_requests")


    def test_live_backfill_uses_small_batches_and_closed_dates(self):
        live=datetime(2026,11,26,5,tzinfo=timezone.utc)
        cfg={**m.DEFAULT,"enabled":True,"index":False,"constituents":False}
        m.configure(cfg,True)
        lane={"state":"partial_requests","existing_verified_receipts":3208,"new_receipts":32,
              "planned_missing_requests":4436,"unattempted_requests":4404,"empty_processed_receipts":0,
              "usable_rows_in_processed_receipts":10,"unreadable_receipts_encountered":0,
              "excluded_active_calendar_days":2,"continuous_coverage_certified":False,
              "empty_verified_receipts":486,"observed_rolling_minute_slots":10,
              "observed_offset_session_pairs":1,"observed_session_dates":1,"rejected_requests":[]}
        with patch.object(m,"_now",return_value=live),patch.object(m,"live_pressure",return_value=None),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":True}),patch.object(m.options,"run",return_value=lane) as provider,patch.object(m.mp,"_history",return_value={"days":{}}):
            result=m.run(now=live)
        self.assertEqual(result["state"],"partial")
        self.assertEqual(result["backfill_mode"],"live_priority")
        self.assertEqual(provider.call_args.kwargs["request_limit"],m.LIVE_OPTION_REQUESTS)
        self.assertEqual(provider.call_args.kwargs["end_date"],"2026-11-25")
        self.assertEqual(m._state()["next_due_reason"],"more_option_requests")

    def test_recorder_pressure_has_recent_drop_cooldown(self):
        from workstation_api import full_option_feed as feed
        live=datetime(2026,11,26,5,tzinfo=timezone.utc)
        with patch.object(feed.WRITES,"qsize",return_value=feed.MAX_QUEUE),patch.object(m.recorder_storage,"status",return_value={}):
            self.assertEqual(m.live_pressure(live),"live_quote_queue_backlog")
            self.assertIsNone(m.live_pressure(self.now))
        with patch.object(feed.WRITES,"qsize",return_value=0),patch.dict(feed.STATUS,{"storage_last_drop_utc":None,"storage_gap_started_utc":None}),patch.object(m.recorder_storage,"status",return_value={"last_drop_utc":(live-timedelta(seconds=30)).isoformat()}):
            self.assertTrue(m.live_pressure(live).startswith("recent_live_recorder_storage_gap"))
        with patch.object(feed.WRITES,"qsize",return_value=0),patch.dict(feed.STATUS,{"storage_last_drop_utc":None,"storage_gap_started_utc":None}),patch.object(m.recorder_storage,"status",return_value={"last_drop_utc":(live-timedelta(minutes=3)).isoformat()}):
            self.assertIsNone(m.live_pressure(live))

    def test_unattempted_equity_repairs_remain_eligible(self):
        state={}
        callback,attempted=m._repair_request_callback(state,{"NSE_EQ:1333":["2026-11-23","2026-11-24"]})
        with patch.object(m,"_now",return_value=self.now):
            callback("NSE_EQ:1333",date(2026,11,23),date(2026,11,24))
        self.assertEqual(attempted,{"NSE_EQ:1333|2026-11-23"})
        self.assertFalse(m._attempt_allowed(state["repairs"],"NSE_EQ:1333|2026-11-23",self.now))
        self.assertTrue(m._attempt_allowed(state["repairs"],"NSE_EQ:1333|2026-11-24",self.now))


    def test_option_progress_available_before_pass_finishes(self):
        cfg={**m.DEFAULT,"enabled":True,"index":False,"constituents":False}
        m.configure(cfg,True)
        counts={"eligible_offset_date_pairs":100,"checked_offset_date_pairs":60,
                "remaining_planned_requests":20,"batch_attempted":2,"batch_limit":20}
        old={"state":"partial","members":{}}
        state=m._state()
        state.update(coverage_config=cfg,coverage_sources={"bank_panel":old})
        m._save_state(state)
        lane={"state":"partial_requests","existing_verified_receipts":30,"new_receipts":2,
              "planned_missing_requests":22,"unattempted_requests":20,"empty_processed_receipts":0,
              "usable_rows_in_processed_receipts":2,"unreadable_receipts_encountered":0,
              "excluded_active_calendar_days":1,"continuous_coverage_certified":False,
              "empty_verified_receipts":0,"observed_rolling_minute_slots":2,
              "observed_offset_session_pairs":1,"observed_session_dates":1,"rejected_requests":[],**counts}
        def provider(**kwargs):
            kwargs["on_counts"](counts)
            live=m.status()
            self.assertEqual(live["option_progress"],counts)
            self.assertEqual(live["coverage_sources"]["bank_panel"],old)
            return lane
        with patch.object(m,"_now",return_value=self.now),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":True}),patch.object(m.options,"run",side_effect=provider),patch.object(m.mp,"_history",return_value={"days":{}}):
            result=m.run(now=self.now)
            self.assertIsNone(m.status()["option_progress"])
            self.assertEqual(m.status()["coverage_sources"]["options"]["checked_offset_date_pairs"],60)
        self.assertEqual(result["state"],"partial")


    def test_connection_retry_is_bounded_and_legacy_block_is_released(self):
        base={"state":"partial","transient_connection_failure":True,
              "sources":{"options":{"state":"blocked"}}}
        for failures,minutes in ((1,2),(2,4),(3,8),(4,16),(5,30),(99,30)):
            self.assertEqual(m._next_schedule({**base,"connection_failure_count":failures}),
                             (timedelta(minutes=minutes),"connection_retry"))
        self.assertEqual(m._next_schedule({"state":"partial","sources":{"options":{"state":"blocked","reason":"HTTP 429"}}})[0],m.RETRY)
        self.assertEqual(m._next_schedule({**base,"sources":{**base["sources"],"bank_panel":{"state":"partial","batch_errors":True}}})[0],m.RETRY)
        cfg={**m.DEFAULT,"enabled":True}
        state={"target":m._target(self.now),"next_due_utc":(self.now+timedelta(hours=3)).isoformat(),
               "next_due_reason":"source_blocked_or_paused",
               "last_run":{"state":"partial","finished_utc":(self.now-timedelta(minutes=5)).isoformat(),
                           "sources":{"options":{"state":"blocked","reason":"Dhan expired-options data connection unavailable; check local network"}}}}
        self.assertTrue(m._due(cfg,state,self.now))
        state["last_run"]["sources"]["options"]["reason"]="HTTP 429"
        self.assertFalse(m._due(cfg,state,self.now))

    def test_transient_disconnect_retains_counts_and_retries(self):
        cfg={**m.DEFAULT,"enabled":True,"index":False,"constituents":False}
        m.configure(cfg,True)
        counts={"eligible_offset_date_pairs":100,"checked_offset_date_pairs":60,
                "remaining_planned_requests":20,"batch_attempted":1,"new_receipts":0}
        def provider(**kwargs):
            kwargs["on_counts"](counts)
            raise opt.exp.RollingConnectionError("connection unavailable")
        with patch.object(m,"_now",return_value=self.now),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":True}),patch.object(m.options,"run",side_effect=provider),patch.object(m.mp,"_history",return_value={"days":{}}):
            first=m.run(now=self.now)
            self.assertEqual(first["connection_failure_count"],1)
            self.assertEqual(m.status()["coverage_sources"]["options"]["checked_offset_date_pairs"],60)
            self.assertEqual(m._state()["next_due_utc"],(self.now+timedelta(minutes=2)).isoformat())
            second=m.run(now=self.now)
            self.assertEqual(second["connection_failure_count"],2)
            self.assertEqual(m._state()["next_due_utc"],(self.now+timedelta(minutes=4)).isoformat())

    def test_profile_connectivity_retry_does_not_treat_auth_as_network_failure(self):
        m.configure({**m.DEFAULT,"enabled":True},True)
        with patch.object(m,"_now",return_value=self.now),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":False,"code":"profile_unreachable"}):
            result=m.run(now=self.now)
            self.assertTrue(result["transient_connection_failure"])
            self.assertEqual(m._state()["next_due_reason"],"connection_retry")
        with patch.object(m,"_now",return_value=self.now),patch.object(m.recorder_storage,"allow",return_value=True),patch.object(m.dhan_auth,"check_profile",return_value={"ok":False,"code":"auth_rejected"}):
            result=m.run(now=self.now)
            self.assertNotIn("transient_connection_failure",result)
            self.assertEqual(m._state()["next_due_reason"],"normal_backoff")
