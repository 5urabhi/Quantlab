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
