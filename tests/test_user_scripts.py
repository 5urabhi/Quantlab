"""UI V3 script persistence and output contract regression tests."""
import json
import pytest
from workstation_api import user_scripts as scripts


def test_versions_preserve_code_and_detect_stale_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts, "_db_path", lambda: tmp_path / "scripts.sqlite3")
    one = scripts.save_script(name="My chart", kind="chart", code="x = 1")
    two = scripts.save_script(name="My chart", kind="chart", code="x = 2",
                              script_id=one["script_id"], expected_revision=1)
    assert two["revision"] == 2
    assert scripts.read_script(one["script_id"], 1)["code"] == "x = 1"
    assert scripts.list_scripts()[0]["revision"] == 2
    with pytest.raises(ValueError, match="updated elsewhere"):
        scripts.save_script(name="Stale", kind="chart", code="x = 3",
                            script_id=one["script_id"], expected_revision=1)
    with pytest.raises(ValueError, match="syntax"):
        scripts.save_script(name="Invalid", kind="chart", code="def :")
    with pytest.raises(ValueError):
        scripts.read_script("../../.env")


def test_snapshot_validation_and_aligned_numeric_output():
    data = {"columns": ["time", "price"], "rows": [["t1", 1], ["t2", None]]}
    assert json.loads(scripts.snapshot_json(data))["rows"] == data["rows"]
    for bad in ({"columns": ["x", "x"], "rows": [[1,2]]},
                {"columns": ["x"], "rows": [[float("nan")]]},
                {"columns": ["x"], "rows": [[1,2]]}):
        with pytest.raises(ValueError):
            scripts.snapshot_json(bad)
    output = {"title":"Custom", "x_label":"Time (IST)", "y_label":"Price (points)",
              "traces":[{"name":"Series", "y":[1,None]}]}
    assert scripts.validate_output(output, 2)["traces"][0]["y"] == [1,None]
    with pytest.raises(ValueError):
        scripts.validate_output(output, 3)
    output["traces"][0]["y"] = [True, float("inf")]
    with pytest.raises(ValueError):
        scripts.validate_output(output, 2)


def test_sandbox_unavailable_fails_closed(monkeypatch):
    def denied(_):
        raise ValueError("isolated runner unavailable")
    monkeypatch.setattr(scripts.python_strategy_sandbox, "_command", denied)
    with pytest.raises(ValueError, match="unavailable"):
        scripts.run_chart(code="raise RuntimeError('must not execute')",
                          snapshot={"columns":["x"],"rows":[[1]]})


def test_saved_custom_runs_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts, "_db_path", lambda: tmp_path / "scripts.sqlite3")
    result = scripts._save_chart_run({"plot":{"title":"Local chart"}, "input_rows":2,
                                      "snapshot_sha256":"example"})
    assert scripts.read_chart_run(result["run_id"]) == result
    assert scripts.list_chart_runs()[0]["title"] == "Local chart"


def test_scientific_profile_uses_only_fixed_readonly_system_packages(monkeypatch):
    from pathlib import Path
    from workstation_api import python_strategy_sandbox as sandbox
    monkeypatch.setattr(sandbox, "availability", lambda: {"available":True})
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/" + name)
    cmd = sandbox._command(Path("/tmp/test_snapshot"), "scientific")
    assert "--unshare-all" in cmd and "--clearenv" in cmd
    assert "/usr/lib/python3/dist-packages" in cmd[-1]
    assert "-S" in cmd and "--as=1073741824" in cmd
    assert cmd.count("--bind") == 1
    assert not any("DHAN_ACCESS_TOKEN" in arg for arg in cmd)
    with pytest.raises(ValueError, match="profile"):
        sandbox._command(Path("/tmp/test_snapshot"), "/home/user/custom_venv")


def test_monitors_pin_revision_deduplicate_and_pause(tmp_path,monkeypatch):
    from workstation_api import script_monitor as monitor
    monkeypatch.setattr(scripts,"_db_path",lambda:tmp_path/"scripts.sqlite3")
    monkeypatch.setattr(monitor.sandbox,"availability",lambda:{"available":True})
    monkeypatch.setattr(monitor,"STOP",__import__("threading").Event())
    item=scripts.save_script(name="Indicator",kind="indicator",code="def analyze(data): return {}")
    row=monitor.register(script_id=item["script_id"],revision=1,source="index_minutes",profile="stdlib")
    scripts.save_script(name="Indicator",kind="indicator",code="def analyze(data): return None",
                        script_id=item["script_id"],expected_revision=1)
    monkeypatch.setattr(monitor,"source_snapshot",lambda source:("receipt-a","2026-11-25T04:00:00+00:00",{},[]))
    calls=[]
    def evaluate(saved,snap,bars):
        calls.append(saved["revision"])
        return {"result":"test"}
    monkeypatch.setattr(monitor,"_evaluate",evaluate)
    monitor.cycle()
    monitor.cycle()
    assert calls == [1]
    assert monitor.list_monitors()[0]["output"] == {"result":"test"}
    monitor.set_enabled(row["id"],False)
    monitor.cycle()
    assert calls == [1]
    monitor.remove(row["id"])
    assert monitor.list_monitors() == []


def test_monitor_source_freshness_and_market_window():
    from datetime import datetime,timezone
    from workstation_api import script_monitor as monitor
    now=datetime(2026,11,25,4,30,tzinfo=timezone.utc)
    assert monitor._regular(now)
    assert monitor._fresh("2026-11-25T04:29:00+00:00",now,60,150)
    assert not monitor._fresh("2026-11-25T04:30:00+00:00",now,60,150)
    assert not monitor._fresh("2026-11-24T04:29:00+00:00",now,60,150)
