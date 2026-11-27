"""Offline acquisition-plan and generic index identity tests."""
from datetime import date,datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
from index_research.dhan_data import Instrument
from scripts import prepare_banknifty_data as m


class PreparationTests(TestCase):
    def test_chunks_half_open_and_bound(self):
        a=date(2026,1,1);b=date(2026,1,12)
        self.assertEqual(list(m.chunks(a,b,5)),[(a,date(2026,1,6)),(date(2026,1,6),date(2026,1,11)),(date(2026,1,11),b)])

    def test_index_plan_reuses_checked_windows_repairs_known_dates_only(self):
        a=date(2026,10,5);b=date(2026,10,12)
        audit={"checked_ranges":[["2026-10-05","2026-10-10"]],"complete_dates":["2026-10-05"]}
        result=m.index_plan(audit,{"2026-10-05","2026-10-07"},a,b)
        self.assertEqual(result,[(date(2026,10,7),date(2026,10,8))])
        audit["checked_ranges"]=[]
        self.assertEqual(m.index_plan(audit,{"2026-10-05","2026-10-07"},a,b),[(a,b)])

    def test_market_priority_guard(self):
        self.assertFalse(m.offhours(datetime(2026,10,5,9,15,tzinfo=m.h.IST)))
        self.assertTrue(m.offhours(datetime(2026,10,5,16,0,tzinfo=m.h.IST)))
        self.assertTrue(m.offhours(datetime(2026,10,10,9,15,tzinfo=m.h.IST)))

    def test_generic_original_index_receipt_requires_exact_identity(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"dhan"/"raw"/"download_0123456789ab"
            raw.mkdir(parents=True)
            csv=raw/"BANKNIFTY_INDEX_intraday_1m.csv"
            manifest=raw/"BANKNIFTY_INDEX_intraday_1m.manifest.json"
            csv.write_bytes(b"fixture")
            data={"source":"DhanHQ REST API v2","interval_minutes":1,
                  "instrument":{"label":"BANKNIFTY_INDEX","exchange_segment":"IDX_I","instrument":"INDEX","security_id":"25"},
                  "row_count":1,"sha256":sha256(csv.read_bytes()).hexdigest()}
            manifest.write_text(json.dumps(data))
            exact=Instrument("BANKNIFTY_INDEX","25","IDX_I","INDEX")
            with patch.object(m.service,"DATA",root),patch.object(m.index_spot,"resolve",return_value=exact):
                self.assertEqual(len(m.cs._candidates("INDEX:BANKNIFTY")),1)
                data["instrument"]["security_id"]="13";manifest.write_text(json.dumps(data))
                self.assertEqual(m.cs._candidates("INDEX:BANKNIFTY"),[])

    def test_live_priority_requests_existing_worker_only(self):
        health={"ok":True,"mode":"local","read_only_market_data":True,"broker_orders_enabled":False}
        status={"config":{"enabled":True,"index":True,"index_days":365},"worker_running":True}
        with patch.object(m,"api",side_effect=[health,status,{"next_due_reason":"manual_check_requested"}]) as api:
            result=m.live_priority_request()
            self.assertEqual(result["state"],"maintenance_check_requested")
            self.assertTrue(result["heavy_backfill_deferred"])
            self.assertEqual(api.call_args_list[-1].args,("/api/data-manager/maintenance/check",))
            self.assertEqual(api.call_count,3)

    def test_live_priority_does_not_override_disabled_active_or_pressure(self):
        health={"ok":True,"mode":"local","read_only_market_data":True,"broker_orders_enabled":False}
        base={"config":{"enabled":True},"worker_running":True}
        for extra,state in [
            ({"config":{"enabled":False}},"maintenance_not_enabled"),
            ({"worker_running":False},"maintenance_worker_unavailable"),
            ({"live_pressure":"recent_live_quote_storage_gap"},"recorder_pressure_yielded"),
            ({"job":{"status":"running"}},"maintenance_already_active"),
            ({"next_due_reason":"provider_rate_limit","next_due_utc":"2099-01-01T00:00:00+00:00"},"provider_cooldown_preserved"),
        ]:
            with patch.object(m,"api",side_effect=[health,{**base,**extra}]) as api:
                self.assertEqual(m.live_priority_request()["state"],state)
                self.assertEqual(api.call_count,2)

    def test_parallel_live_uses_actual_pressure_not_time_gate(self):
        with patch.object(m,"offhours",return_value=False):
            status={"config":{"enabled":True},"live_pressure":None}
            with patch.object(m,"api",return_value=status) as api:
                self.assertIsNone(m.priority_blocker(True))
                self.assertEqual(m.priority_blocker(False),"Market-priority window began")
                self.assertEqual(api.call_count,1)
            with patch.object(m,"api",return_value={**status,"live_pressure":"live_quote_queue_backlog"}):
                self.assertEqual(m.priority_blocker(True),"Recorder pressure: live_quote_queue_backlog")
            with patch.object(m,"api",return_value={**status,"config":{"enabled":False}}):
                self.assertIn("monitoring unavailable",m.priority_blocker(True))
            limited={**status,"next_due_reason":"provider_rate_limit","next_due_utc":"2099-01-01T00:00:00+00:00"}
            with patch.object(m,"api",return_value=limited):
                self.assertTrue(m.priority_blocker(True).startswith("Provider cooldown until"))
                self.assertIsNone(m.priority_blocker(True,dhan=False))

    def test_parallel_live_job_completes_during_market_hours(self):
        record={}
        with patch.object(m,"offhours",return_value=False),patch.object(m,"wait_idle") as idle, \
             patch.object(m,"priority_blocker",return_value=None),patch.object(m.time,"sleep"), \
             patch.object(m,"api",side_effect=[{"job_id":"job1"},{"status":"running"},{"status":"complete","result":{"rows":123}}]) as api:
            result=m.job("/api/dhan/download",{},record,lambda:None,parallel_live=True)
        idle.assert_called_once_with(True)
        self.assertEqual(result,{"rows":123})
        self.assertEqual(record["state"],"job_complete")
        self.assertEqual(api.call_count,3)

    def test_parallel_live_pressure_cancels_only_own_cancellable_job(self):
        record={}
        with patch.object(m,"wait_idle"),patch.object(m.time,"sleep"), \
             patch.object(m,"priority_blocker",return_value="Recorder pressure: backlog"), \
             patch.object(m,"api",side_effect=[{"job_id":"job1"},{"status":"running"},{},{"status":"cancelled"}]) as api:
            with self.assertRaises(m.Pause):
                m.job("/api/data-manager/options-history/start",{},record,lambda:None,
                      cancel_path="job",parallel_live=True)
        self.assertEqual(api.call_args_list[2].args,("/api/workspace/jobs/job1/cancel",))
        self.assertEqual(record["state"],"cancelled")

    def test_external_archives_require_default_offhours_or_explicit_guard(self):
        a=date(2025,1,1);b=date(2025,1,2)
        with patch.object(m.fred.alpha_retraining,"safe_window",return_value=False), \
             patch.dict(m.os.environ,{"FRED_API_KEY":""}),patch.object(m.alpaca,"credentials",return_value=None):
            with self.assertRaises(ValueError):m.fred.backfill(a,b,confirmed=True)
            with self.assertRaises(ValueError):m.alpaca.backfill(a,b,confirmed=True)
            calls=[]
            guard=lambda:calls.append(True)
            self.assertEqual(m.fred.backfill(a,b,confirmed=True,live_guard=guard)["state"],"fred_key_not_configured")
            self.assertEqual(m.alpaca.backfill(a,b,confirmed=True,live_guard=guard)["state"],"alpaca_credentials_not_configured")
            self.assertEqual(len(calls),2)
            def pressure():raise m.Pause("Recorder pressure")
            with self.assertRaises(m.Pause):m.fred.backfill(a,b,confirmed=True,live_guard=pressure)
            with self.assertRaises(m.Pause):m.alpaca.backfill(a,b,confirmed=True,live_guard=pressure)

    def test_transient_recorder_pressure_waits_then_clears(self):
        with patch.object(m,"priority_blocker",side_effect=["Recorder pressure: auto_depth",None]) as guard,patch.object(m.time,"sleep") as sleep:
            m.require_priority(True)
            self.assertEqual(guard.call_count,2)
            sleep.assert_called_once_with(5)
        with patch.object(m,"priority_blocker",return_value="Provider cooldown until tomorrow"),patch.object(m.time,"sleep") as sleep:
            with self.assertRaises(m.Pause):m.require_priority(True)
            sleep.assert_not_called()

    def test_completed_batch_does_not_replay_after_recorder_pressure(self):
        record={}
        replies=[{"job_id":"job1","batch":{"id":"batch_fixture"}},
                 {"status":"running"},{"status":"running","processed":15,"total":16},
                 {},{"status":"complete","result":{}},{"status":"completed","processed":16,"total":16}]
        with patch.object(m,"wait_idle"),patch.object(m.time,"sleep"), \
             patch.object(m,"priority_blocker",return_value="Recorder pressure: auto_depth"), \
             patch.object(m,"require_priority") as recover,patch.object(m,"api",side_effect=replies) as api:
            m.job("/api/dhan/batches",{},record,lambda:None,parallel_live=True)
            recover.assert_called_once_with(True)
            self.assertEqual(api.call_count,6)
            self.assertEqual(api.call_args_list[3].args,("/api/dhan/batches/batch_fixture/cancel",))
        self.assertEqual(record["state"],"job_complete")
        self.assertEqual(record["batch_progress"]["processed"],16)
        self.assertIn("auto_depth",record["pressure_yield"])

    def test_generic_complete_does_not_mask_paused_stock_batch(self):
        record={}
        replies=[{"job_id":"job1","batch":{"id":"batch_fixture"}},
                 {"status":"complete","result":{}},{"status":"paused","processed":5,"total":16}]
        with patch.object(m,"wait_idle"),patch.object(m,"api",side_effect=replies):
            with self.assertRaises(m.Pause):m.job("/api/dhan/batches",{},record,lambda:None,parallel_live=True)
        self.assertEqual(record["state"],"batch_incomplete")
        self.assertEqual(record["batch_progress"]["status"],"paused")

    def test_fred_stops_at_first_provider_rate_limit(self):
        with patch.dict(m.os.environ,{"FRED_API_KEY":"OFFLINE_TEST"}), \
             patch.object(m.fred,"_fetch_vintages",side_effect=ValueError("Provider HTTP 429")) as fetch:
            result=m.fred.backfill(date(2025,1,1),date(2025,1,5),confirmed=True,live_guard=lambda:None)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(result["state"],"provider_rate_limited")
        states=[v["state"] for v in result["factors"].values()]
        self.assertEqual(states.count("unavailable"),1)
        self.assertEqual(states.count("deferred_provider_rate_limit"),len(states)-1)

    def test_archive_windows_defers_remaining_fred_windows_after_rate_limit(self):
        with TemporaryDirectory() as tmp,patch.dict(m.os.environ,{"FRED_API_KEY":"OFFLINE_TEST"}), \
             patch.object(m.alpaca,"credentials",return_value=None), \
             patch.object(m,"require_priority"),patch.object(m.fred,"backfill",return_value={"state":"provider_rate_limited","factors":{"SP500_CLOSE":{"state":"unavailable","reason":"Provider HTTP 429"}}}) as fetch:
            report={"context":[]}
            m.archive_windows(date(2025,1,1),date(2025,12,31),Path(tmp),report,lambda:None,"iex",parallel_live=True)
            self.assertEqual(fetch.call_count,1)
            self.assertTrue(any(x.get("state")=="remaining_windows_deferred_provider_rate_limit" for x in report["context"]))
