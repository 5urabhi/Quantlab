"""Synthetic control-flow tests; never evidence of trading performance."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import sqlite3

from scripts import validate_trading_research as suite

NOW=datetime(2026,11,26,13,tzinfo=timezone.utc)
DAY="2026-11-26"
ID="a"*64


class TradingValidationTests(TestCase):
    def test_off_hours_and_bounded_settings(self):
        with self.assertRaises(ValueError):
            suite.run(now=datetime(2026,11,26,5,tzinfo=timezone.utc))
        for args in ({"sessions":4},{"horizon":10},{"max_loss":20000},
                     {"days":["2026-12-01"]},{"model_ids":["bad"]}):
            with self.assertRaises(ValueError):
                suite.run(now=NOW,**args)

    def test_no_source_evidence_never_becomes_certified(self):
        with TemporaryDirectory() as tmp, \
             patch.object(suite.trading_acceptance,"inspect_saved_books",return_value={"status":"not_recorded"}), \
             patch.object(suite,"completed_days",return_value=[]), \
             patch.object(suite.constituent_alpha,"readiness",return_value={"recorded_sessions":0,"required_sessions":60}), \
             patch.object(suite.forecast_depth_research,"run") as forecast, \
             patch.object(suite.dynamic_strategy_research,"run") as replay, \
             patch.object(suite.volatility_evidence,"iv_run",return_value={"state":"descriptive_only_insufficient_sessions"}), \
             patch.object(suite.alpha_model_registry,"list_candidates",return_value=[]), \
             patch.object(suite,"local_timing_evidence",return_value={"state":"no_paper_journal"}):
            path,result=suite.run(now=NOW,output=Path(tmp)/"report.json")
            self.assertEqual(json.loads(path.read_text()),result)
        forecast.assert_not_called()
        replay.assert_not_called()
        self.assertEqual(result["stages"]["forecast_depth_replay"]["state"],"not_run")
        self.assertEqual(result["stages"]["frozen_monitor"]["state"],"not_run")
        self.assertEqual(result["state"],"assessment_saved")
        self.assertFalse(result["prospective_profitability_certified"])
        self.assertFalse(result["actual_broker_latency_verified"])

    def test_all_selected_stages_and_pinned_inventory(self):
        with TemporaryDirectory() as tmp, \
             patch.object(suite.trading_acceptance,"inspect_saved_books",return_value={"status":"verified_sample"}), \
             patch.object(suite.dynamic_strategy_research,"run",return_value={"policies":[]}) as replay, \
             patch.object(suite.constituent_alpha,"readiness",return_value={"recorded_sessions":60,"required_sessions":60}), \
             patch.object(suite.alpha_model_registry,"list_candidates",return_value=[{"model_id":ID,"source":"prospective","horizon_minutes":15,"reference_holdout_dates":["2026-11-25"]}]), \
             patch.object(suite.forecast_depth_research,"run",return_value={"state":"conditional_depth_assessment_available"}) as forecast, \
             patch.object(suite.volatility_evidence,"iv_run",return_value={"state":"chronological_assessment_available"}), \
             patch.object(suite.alpha_model_registry,"monitor",return_value={"state":"insufficient_later_evidence"}) as monitor, \
             patch.object(suite,"local_timing_evidence",return_value={"state":"local_timing_available"}):
            path,result=suite.run(days=[DAY],now=NOW,output=Path(tmp)/"report.json")
        self.assertEqual(replay.call_args.kwargs["day"],DAY)
        self.assertTrue(replay.call_args.kwargs["include_spreads"])
        self.assertFalse(forecast.call_args.kwargs["include_credit"])
        self.assertEqual(monitor.call_args.kwargs["model_id"],ID)
        self.assertEqual(result["monitored_model_ids"],[ID])
        self.assertFalse(result["actual_broker_margin_verified"])

    def test_timing_uses_only_observed_fields_and_never_certifies_broker_latency(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"paper.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE decisions(id INTEGER PRIMARY KEY,state TEXT,body TEXT)")
                for state,body in [
                    ("no_trade",{"decision_processing_ms":10,"conditional_entry_receipt_delay_ms":1}),
                    ("complete",{"decision_processing_ms":30,"conditional_entry_receipt_delay_ms":400,"conditional_exit_receipt_delay_ms":500}),
                    ("complete",{"decision_processing_ms":-1}),
                    ("paper_open",{"conditional_entry_receipt_delay_ms":600}),
                    ("complete",{})]:
                    db.execute("INSERT INTO decisions(state,body) VALUES(?,?)",(state,json.dumps(body)))
            with patch.object(suite.auto_paper_engine,"_path",return_value=path):
                result=suite.local_timing_evidence()
        self.assertEqual(result["rows_examined"],5)
        self.assertEqual(result["metrics"]["decision_processing_ms"]["n"],2)
        self.assertEqual(result["metrics"]["decision_processing_ms"]["p50_ms"],20)
        self.assertEqual(result["metrics"]["conditional_entry_receipt_delay_ms"]["n"],2)
        self.assertEqual(result["metrics"]["conditional_entry_receipt_delay_ms"]["p50_ms"],500)
        self.assertFalse(result["actual_broker_latency_verified"])
