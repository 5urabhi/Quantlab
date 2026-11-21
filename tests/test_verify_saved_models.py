"""Offline verification tests; synthetic rows only, never broker/live source data."""
from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import verify_saved_models as mod
from workstation_api import model_registry, service


def fake_report(*, blocked_heston=False, failure=None):
    math = [s for s in model_registry.MODELS
            if s["mode"] in {"synthetic", "theoretical"}]
    observed = [s for s in model_registry.MODELS
                if s["mode"] not in {"synthetic", "theoretical"}]
    rows = []
    for spec in observed:
        status = ("blocked_input" if blocked_heston and spec["id"]=="heston_proxy"
                  else "software_fail" if spec["id"] == failure
                  else "observed_input_pass")
        rows.append({
            "dataset_id":"dhan_shared", "model_id":spec["id"],
            "mode":spec["mode"], "status":status,
            "reason":"Not enough original returns" if status=="blocked_input" else "",
            "next_action":"Complete original history" if status=="blocked_input" else "",
            "selected_ticker":"FEDERALBNK" if status=="blocked_input" else "",
            "observed_returns":"224" if status=="blocked_input" else "303",
            "minimum_returns":"252" if spec["id"]=="heston_proxy" else "30",
            "preferred_returns":"303" if spec["id"]=="heston_proxy" else "36",
            "missing_minimum":"28" if status=="blocked_input" else "0",
            "missing_to_target":"79" if status=="blocked_input" else "0",
        })
    return {
        "registered_models":len(model_registry.MODELS),
        "mathematics":[{"model_id":s["id"],"status":"math_pass"} for s in math],
        "math_pass":len(math), "math_fail":0,
        "datasets":[{"dataset_id":"dhan_shared","source_changed":False}],
        "observed_input_pass":sum(r["status"]=="observed_input_pass" for r in rows),
        "blocked_input":sum(r["status"]=="blocked_input" for r in rows),
        "software_fail":sum(r["status"]=="software_fail" for r in rows),
        "source_changed":0,
    },rows


class SavedModelVerificationTests(unittest.TestCase):
    def test_default_filters_synthetic_and_empty_legacy_but_not_real_incomplete(self):
        data=[
            {"id":"synthetic","kind":"synthetic"},
            {"id":"dhan_monthly","kind":"dhan","has_prices":False},
            {"id":"dhan_shared","kind":"dhan","has_daily_prices":True},
            {"id":"upload_daily","kind":"uploaded","has_daily_prices":True},
            {"id":"upload_incomplete","kind":"uploaded","has_prices":False},
        ]
        with patch.object(service,"datasets",return_value=data):
            self.assertEqual(mod.selected_dataset_ids(None),[
                "dhan_shared","upload_daily","upload_incomplete"])
            self.assertEqual(mod.selected_dataset_ids(["dhan_shared","dhan_shared"]),
                             ["dhan_shared"])
            with self.assertRaisesRegex(ValueError,"Unavailable"):
                mod.selected_dataset_ids(["not_saved"])

    def test_existing_eligible_chain_is_linked_once_from_saved_local_evidence(self):
        inventory={"recommended_snapshot_sha256":"a"*64}
        result={"id":"oq_saved","contracts":200,"reused_existing":False}
        with patch.object(mod.option_quotes,"list_for",return_value=[]), \
             patch.object(mod.recorded_chain_model_quotes,"available",
                          return_value=inventory) as available, \
             patch.object(mod.recorded_chain_model_quotes,"use_saved",
                          return_value=result) as linked:
            receipt=mod.link_existing_chain(["dhan_shared"],enabled=True)
        self.assertEqual(receipt["model_quote_id"],"oq_saved")
        self.assertEqual(receipt["provider_calls"],0)
        self.assertEqual(receipt["orders"],0)
        available.assert_called_once()
        linked.assert_called_once_with("dhan_shared","a"*64,confirm_reuse=True)

    def test_previously_saved_quote_skips_new_derived_catalog_file(self):
        with patch.object(mod.option_quotes,"list_for",
                          return_value=[{"contracts":[{"row_index":0}]}]), \
             patch.object(mod.recorded_chain_model_quotes,"use_saved") as write:
            receipt=mod.link_existing_chain(["dhan_shared"],enabled=True)
        self.assertEqual(receipt["status"],"already_saved_quotes_available")
        write.assert_not_called()

    def test_missing_chain_is_blocked_not_fabricated(self):
        with patch.object(mod.option_quotes,"list_for",return_value=[]), \
             patch.object(mod.recorded_chain_model_quotes,"available",
                          return_value={"recommended_snapshot_sha256":None}), \
             patch.object(mod.recorded_chain_model_quotes,"use_saved") as write:
            receipt=mod.link_existing_chain(["dhan_shared"],enabled=True)
        self.assertEqual(receipt["status"],"no_eligible_saved_chain")
        write.assert_not_called()

    def test_heston_shortfall_remains_explicitly_incomplete(self):
        report,rows=fake_report(blocked_heston=True)
        summary=mod.verification_summary(report,rows,{"status":"quoted"})
        self.assertEqual(summary["verdict"],"SOURCE_DATA_INCOMPLETE")
        self.assertEqual(summary["math_pass"],9)
        self.assertEqual(summary["datasets"][0]["verified_calculations"],25)
        self.assertEqual(summary["datasets"][0]["missing_original_inputs"],1)
        blocked=summary["issues"][0]
        self.assertEqual(blocked["model"],"heston_proxy")
        self.assertEqual(blocked["selected_ticker"],"FEDERALBNK")
        self.assertEqual(blocked["missing_minimum"],28)
        self.assertEqual(blocked["missing_to_target"],79)
        with TemporaryDirectory() as root:
            folder=Path(root)
            mod.write_digest(folder,summary)
            self.assertIn("SOURCE_DATA_INCOMPLETE",
                          (folder/"FULL_SAVED_VERIFICATION.md").read_text())

    def test_genuinely_complete_matrix_is_claimed_as_numerical_only(self):
        report,rows=fake_report()
        summary=mod.verification_summary(report,rows,{"status":"quoted"})
        self.assertEqual(summary["verdict"],"ALL_REGISTERED_MODELS_EXECUTED")
        self.assertFalse(summary["real_market_source_certified"])
        self.assertFalse(summary["backtesting_quality_certified"])

    def test_software_failure_is_never_mislabeled_missing_data(self):
        report,rows=fake_report(failure="garch")
        summary=mod.verification_summary(report,rows,{"status":"quoted"})
        self.assertEqual(summary["verdict"],"SOFTWARE_OR_SOURCE_CHANGED")
        self.assertEqual(summary["software_fail"],1)
        self.assertEqual(summary["issues"][0]["status"],"software_fail")

    def test_missing_model_in_audit_matrix_fails_closed(self):
        report,rows=fake_report()
        rows=[row for row in rows if row["model_id"]!="garch"]
        with self.assertRaisesRegex(ValueError,"missing registered models"):
            mod.verification_summary(report,rows,{"status":"quoted"})

    def test_full_audit_writes_exact_report_and_never_calls_broker(self):
        report,rows=fake_report(blocked_heston=True)
        def local_audit(*,datasets,execute,output):
            self.assertEqual(datasets,["dhan_shared"])
            self.assertTrue(execute)
            output.mkdir(parents=True)
            with (output/"ALL_MODEL_RESULTS.csv").open("w",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]))
                writer.writeheader();writer.writerows(rows)
            return report
        sample_trading = {
            "read_only": True, "external_api_requests": 0, "orders_placed": 0,
            "market_regular_hours_ist": False, "recorder_armed": True,
            "saved_books": {"total_automatic_books": 9},
            "checks": [
                {"code": "banknifty_history", "title": "BANKNIFTY history",
                 "status": "pass", "detail": "Original minute candles saved",
                 "next_action": "Review spot research", "screen": "backtest"},
                {"code": "live_depth", "title": "Live 20-level depth",
                 "status": "waiting", "detail": "Outside regular market hours",
                 "next_action": "Inspect during NSE session", "screen": "live"},
            ],
        }
        with TemporaryDirectory() as root, \
             patch.object(mod,"selected_dataset_ids",
                          return_value=["dhan_shared"]), \
             patch.object(mod,"link_existing_chain",
                          return_value={"status":"quoted"}) as linked, \
             patch.object(mod.trading_acceptance, "report",
                          return_value=sample_trading) as trading, \
             patch.object(mod.audit_all_models,"audit",
                          side_effect=local_audit) as audit:
            folder=Path(root)/"verification"
            result=mod.verify(dataset_ids=["dhan_shared"],output=folder)
            self.assertEqual(result["verdict"],"SOURCE_DATA_INCOMPLETE")
            self.assertTrue((folder/"FULL_SAVED_VERIFICATION.json").exists())
            self.assertTrue((folder/"FULL_TRADING_READINESS.json").exists())
            self.assertEqual(result["trading_readiness"]["status"], "available")
            self.assertEqual(result["trading_readiness"]["saved_books_total"], 9)
            self.assertEqual(result["trading_readiness"]["checks"][1]["status"],
                             "waiting")
            self.assertIn("BANKNIFTY trading-source readiness",
                          (folder/"FULL_SAVED_VERIFICATION.md").read_text())
            trading.assert_called_once()
            linked.assert_called_once()
            audit.assert_called_once()
            with self.assertRaisesRegex(ValueError,"exists"):
                mod.verify(dataset_ids=["dhan_shared"],output=folder)


    def test_unavailable_trading_report_never_invalidates_unrelated_models(self):
        report, rows = fake_report()
        def local_audit(*, datasets, execute, output):
            output.mkdir(parents=True)
            with (output / "ALL_MODEL_RESULTS.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            return report
        with TemporaryDirectory() as root, \
             patch.object(mod, "selected_dataset_ids", return_value=["dhan_shared"]), \
             patch.object(mod, "link_existing_chain",
                          return_value={"status": "already_saved_quotes_available"}), \
             patch.object(mod.audit_all_models, "audit",
                          side_effect=local_audit), \
             patch.object(mod.trading_acceptance, "report",
                          side_effect=OSError("Market source database locked")):
            output = Path(root) / "verification"
            result = mod.verify(dataset_ids=["dhan_shared"], output=output)
            self.assertEqual(result["verdict"], "ALL_REGISTERED_MODELS_EXECUTED")
            self.assertEqual(result["trading_readiness"]["status"], "unavailable")
            self.assertIn("locked", result["trading_readiness"]["reason"])
            self.assertFalse((output / "FULL_TRADING_READINESS.json").exists())
            self.assertIn("could not be examined",
                          (output / "FULL_SAVED_VERIFICATION.md").read_text())

    def test_source_check_without_read_only_provenance_is_rejected(self):
        report, rows = fake_report()
        def local_audit(*, datasets, execute, output):
            output.mkdir(parents=True)
            with (output / "ALL_MODEL_RESULTS.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            return report
        with TemporaryDirectory() as root, \
             patch.object(mod, "selected_dataset_ids", return_value=["dhan_shared"]), \
             patch.object(mod, "link_existing_chain",
                          return_value={"status": "already_saved_quotes_available"}), \
             patch.object(mod.audit_all_models, "audit",
                          side_effect=local_audit), \
             patch.object(mod.trading_acceptance, "report",
                          return_value={"read_only": False, "external_api_requests": 1}):
            output = Path(root) / "verification"
            result = mod.verify(dataset_ids=["dhan_shared"], output=output)
            self.assertEqual(result["trading_readiness"]["status"], "unavailable")
            self.assertIn("read-only", result["trading_readiness"]["reason"])
            self.assertFalse((output / "FULL_TRADING_READINESS.json").exists())


if __name__=="__main__":
    unittest.main()
