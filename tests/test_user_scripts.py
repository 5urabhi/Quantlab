"""Offline UI V3 tests using the repository's existing unittest runner."""
import json
import unittest
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from workstation_api import user_scripts as scripts
from workstation_api import script_monitor as monitor
from workstation_api import python_strategy_sandbox as sandbox


class UserScriptTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp=Path(self.stack.enter_context(TemporaryDirectory()))
        self.stack.enter_context(patch.object(scripts,"_db_path",lambda:self.tmp/"scripts.sqlite3"))

    def test_versions_preserve_code_and_detect_stale_writes(self):
        one=scripts.save_script(name="My chart",kind="chart",code="x = 1")
        two=scripts.save_script(name="My chart",kind="chart",code="x = 2",
                                script_id=one["script_id"],expected_revision=1)
        self.assertEqual(two["revision"],2)
        self.assertEqual(scripts.read_script(one["script_id"],1)["code"],"x = 1")
        self.assertEqual(scripts.list_scripts()[0]["revision"],2)
        with self.assertRaisesRegex(ValueError,"updated elsewhere"):
            scripts.save_script(name="Stale",kind="chart",code="x = 3",
                                script_id=one["script_id"],expected_revision=1)
        with self.assertRaisesRegex(ValueError,"syntax"):
            scripts.save_script(name="Invalid",kind="chart",code="def :")
        with self.assertRaises(ValueError):
            scripts.read_script("../../.env")

    def test_snapshot_validation_and_aligned_numeric_output(self):
        data={"columns":["time","price"],"rows":[["t1",1],["t2",None]]}
        self.assertEqual(json.loads(scripts.snapshot_json(data))["rows"],data["rows"])
        for bad in ({"columns":["x","x"],"rows":[[1,2]]},
                    {"columns":["x"],"rows":[[float("nan")]]},
                    {"columns":["x"],"rows":[[1,2]]}):
            with self.assertRaises(ValueError):
                scripts.snapshot_json(bad)
        output={"title":"Custom","x_label":"Time (IST)","y_label":"Price (points)",
                "traces":[{"name":"Series","y":[1,None]}]}
        self.assertEqual(scripts.validate_output(output,2)["traces"][0]["y"],[1,None])
        with self.assertRaises(ValueError):
            scripts.validate_output(output,3)
        output["traces"][0]["y"]=[True,float("inf")]
        with self.assertRaises(ValueError):
            scripts.validate_output(output,2)

    def test_sandbox_unavailable_fails_closed(self):
        with patch.object(sandbox,"_command",side_effect=ValueError("isolated runner unavailable")):
            with self.assertRaisesRegex(ValueError,"unavailable"):
                scripts.run_chart(code="raise RuntimeError('must not execute')",
                                  snapshot={"columns":["x"],"rows":[[1]]})

    def test_saved_custom_runs_reopen(self):
        result=scripts._save_chart_run({"plot":{"title":"Local chart"},"input_rows":2,
                                       "snapshot_sha256":"example"})
        self.assertEqual(scripts.read_chart_run(result["run_id"]),result)
        self.assertEqual(scripts.list_chart_runs()[0]["title"],"Local chart")

    def test_scientific_profile_uses_fixed_system_packages(self):
        with patch.object(sandbox,"availability",return_value={"available":True}), \
             patch.object(sandbox.shutil,"which",side_effect=lambda name:"/usr/bin/"+name):
            cmd=sandbox._command(Path("/tmp/test_snapshot"),"scientific")
            self.assertIn("--unshare-all",cmd)
            self.assertIn("--clearenv",cmd)
            self.assertIn("/usr/lib/python3/dist-packages",cmd[-1])
            self.assertIn("-S",cmd)
            self.assertIn("--as=1073741824",cmd)
            self.assertEqual(cmd.count("--bind"),1)
            self.assertFalse(any("DHAN_ACCESS_TOKEN" in arg for arg in cmd))
            with self.assertRaisesRegex(ValueError,"profile"):
                sandbox._command(Path("/tmp/test_snapshot"),"/home/user/custom_venv")

    def test_monitors_pin_revision_deduplicate_and_pause(self):
        with patch.object(sandbox,"availability",return_value={"available":True}), \
             patch.object(monitor,"STOP",Event()):
            item=scripts.save_script(name="Indicator",kind="indicator",code="def analyze(data): return {}")
            row=monitor.register(script_id=item["script_id"],revision=1,source="index_minutes",profile="stdlib")
            scripts.save_script(name="Indicator",kind="indicator",code="def analyze(data): return None",
                                script_id=item["script_id"],expected_revision=1)
            calls=[]
            def evaluate(saved,snap,bars):
                calls.append(saved["revision"])
                return {"result":"test"}
            with patch.object(monitor,"source_snapshot",return_value=("receipt-a","2026-11-25T04:00:00+00:00",{},[])), \
                 patch.object(monitor,"_evaluate",side_effect=evaluate):
                monitor.cycle()
                monitor.cycle()
                self.assertEqual(calls,[1])
                self.assertEqual(monitor.list_monitors()[0]["output"],{"result":"test"})
                monitor.set_enabled(row["id"],False)
                monitor.cycle()
                self.assertEqual(calls,[1])
                monitor.remove(row["id"])
                self.assertEqual(monitor.list_monitors(),[])

    def test_monitor_source_freshness_and_market_window(self):
        now=datetime(2026,11,25,4,30,tzinfo=timezone.utc)
        self.assertTrue(monitor._regular(now))
        self.assertTrue(monitor._fresh("2026-11-25T04:29:00+00:00",now,60,150))
        self.assertFalse(monitor._fresh("2026-11-25T04:30:00+00:00",now,60,150))
        self.assertFalse(monitor._fresh("2026-11-24T04:29:00+00:00",now,60,150))
