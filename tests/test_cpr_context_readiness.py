"""Synthetic tests for scoped membership and conservative vintage availability."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from unittest import TestCase
from unittest.mock import patch

from workstation_api import historical_alpha as h, cpr_context_features as cx
from workstation_api import cpr_context_archive as arc, market_context as m


class ContextReadinessTests(TestCase):
    def test_long_manifest_is_scoped_without_disabling_original_guard(self):
        intervals=[{"symbol":"HDFCBANK","valid_from":"2020-01-01","valid_to":""},
                   {"symbol":"OLD","valid_from":"2020-01-01","valid_to":"2022-01-01"}]
        manifest={"selection":"banknifty_pit","interval":1,
                  "from_date":"2020-01-01","to_date":"2025-01-01",
                  "historical_index":{"intervals":intervals,
                      "intervals_sha256":sha256(json.dumps(intervals,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
                      "covered_through":"2024-12-31"},
                  "items":[{"pit_symbol":"HDFCBANK","id":"NSE_EQ:1333"},
                           {"pit_symbol":"OLD","id":"NSE_EQ:2"}]}
        with patch.object(h.dw,"_load_batch",return_value=manifest):
            with self.assertRaisesRegex(ValueError,"240 calendar days"):
                h._batch("batch_test")
            _,start,stop,_,mapped=h._batch("batch_test",study_start=date(2024,1,1),study_stop=date(2024,3,1))
            self.assertEqual(mapped,{"HDFCBANK":"NSE_EQ:1333"})
            self.assertEqual((start,stop),(date(2024,1,1),date(2024,3,1)))
            manifest["historical_index"]["intervals_sha256"]="bad"
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                h._batch("batch_test",study_start=date(2024,1,1),study_stop=date(2024,3,1))

    def test_invalid_auto_batch_falls_back_and_explains_reason(self):
        start,stop=date(2024,1,1),date(2024,3,1)
        raw={"historical_index":{"intervals_sha256":"digest","covered_through":"2024-03-01"}}
        with patch.object(cx,"_batch_candidates",return_value=["bad","good"]), \
             patch.object(h,"_batch",side_effect=[ValueError("Pinned historical membership missing or hash mismatch"),
                                                  (raw,start,stop,[],{"HDFCBANK":"NSE_EQ:1333"})]), \
             patch.object(h.pq,"_source_signature",return_value={}):
            _,_,_,_,meta=cx._load_banks(start,stop,"auto")
        self.assertEqual(meta["batch_id"],"good")
        self.assertIn("hash mismatch",meta["rejected_batches"]["bad"])
        self.assertEqual(meta["failures"]["HDFCBANK"],"missing original receipt")

    def test_vintage_rows_preserve_revision_dates_and_never_backdate(self):
        rows=[{"date":"2024-01-02","realtime_start":"2024-01-03","value":"100"},
              {"date":"2024-01-02","realtime_start":"2024-01-05","value":"101"},
              {"date":"2024-01-02","realtime_start":"2024-01-01","value":"999"}]
        raw=json.dumps({"observations":rows,"count":3,"offset":0}).encode()
        now=datetime(2024,1,10,tzinfo=timezone.utc)
        csv_text,n,bad=arc.normalize("SP500_CLOSE",raw,date(2024,1,1),date(2024,1,9),now)
        parsed=m.parse_csv(csv_text,now)
        self.assertEqual((n,bad),(2,1))
        self.assertEqual(m._stamp(parsed[0][2]),datetime(2024,1,4,12,tzinfo=timezone.utc))
        self.assertEqual(m._stamp(parsed[1][2]),datetime(2024,1,6,12,tzinfo=timezone.utc))
        self.assertEqual([x[3] for x in parsed],[100.,101.])
        timeline=m.Timeline([(m._stamp(x[2]),m._stamp(x[1]),x[3],"FRED:SP500","receipt") for x in parsed])
        self.assertEqual(timeline.at(datetime(2024,1,5,tzinfo=timezone.utc))[0][2],100.)
        self.assertEqual(timeline.at(datetime(2024,1,7,tzinfo=timezone.utc))[0][2],101.)

    def test_truncated_vintage_response_rejected(self):
        raw=json.dumps({"observations":[],"count":5001,"offset":0}).encode()
        with self.assertRaisesRegex(ValueError,"Incomplete bounded"):
            arc.normalize("SP500_CLOSE",raw,date(2024,1,1),date(2024,1,9),
                          datetime(2024,1,10,tzinfo=timezone.utc))

    def test_network_requires_authorization(self):
        with patch.object(arc.feeds,"_http") as http:
            with self.assertRaisesRegex(ValueError,"Explicit authorization"):
                arc.backfill(date(2024,1,1),date(2024,1,9))
            http.assert_not_called()


    def test_fred_retry_preserves_archive_formats(self):
        with patch.object(arc.alpha_retraining,"safe_window",return_value=True), \
             patch.object(arc.feeds,"_http",side_effect=[ValueError("Provider HTTP 400 [vintage_parameters_rejected]"),
                       ValueError("Provider HTTP 400 [vintage_parameters_rejected]"),b"archive"]) as http:
            raw,mode,attempts=arc._fetch_vintages("local-key","SP500",date(2024,1,1),date(2024,1,9))
        self.assertEqual((raw,mode),(b"archive","initial_release_only"))
        self.assertEqual(len(attempts),3)
        params=[x.args[1] for x in http.call_args_list]
        self.assertEqual([x["output_type"] for x in params],[1,1,4])
        self.assertEqual(params[1]["realtime_start"],"2024-01-01")

    def test_alpaca_proxy_availability_after_new_york_day(self):
        from workstation_api import cpr_alpaca_archive as alpaca
        rows=[{"t":"2024-07-01T04:00:00Z","o":100,"h":102,"l":99,"c":101,"v":1000},
              {"t":"2024-07-02T04:00:00Z","o":101,"h":103,"l":100,"c":102,"v":1000}]
        now=datetime(2024,7,2,6,tzinfo=timezone.utc)
        text,n=alpaca.normalize("US_SPY_ETF_CLOSE",rows,date(2024,7,1),date(2024,7,3),now)
        self.assertEqual(n,1)
        parsed=m.parse_csv(text,now)
        self.assertEqual(m._stamp(parsed[0][2]),datetime(2024,7,2,4,15,tzinfo=timezone.utc))
        self.assertEqual(m.FACTORS["JAPAN_EWJ_ETF_CLOSE"][1],"asia")
        self.assertNotEqual("JAPAN_EWJ_ETF_CLOSE","NIKKEI_CLOSE")

    def test_alpaca_network_requires_authorization(self):
        from workstation_api import cpr_alpaca_archive as alpaca
        with patch.object(alpaca,"_http") as http:
            with self.assertRaisesRegex(ValueError,"Review Alpaca"):
                alpaca.backfill(date(2024,7,1),date(2024,7,3))
            http.assert_not_called()
