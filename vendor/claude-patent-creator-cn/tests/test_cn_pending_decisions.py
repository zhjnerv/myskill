import json
import subprocess
import sys
from pathlib import Path

def test_schema_is_valid_json():
    schema_path = Path("skills/cn-patent-application-creator/references/pending-decisions-schema-v1.json")
    assert schema_path.is_file()
    with open(schema_path, "r", encoding="utf-8") as f:
        json.load(f)

def test_collect_decisions(tmp_path):
    report1 = tmp_path / "report1.json"
    report2 = tmp_path / "report2.json"
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"

    # report1 has 3 items (1 duplicate)
    item1 = {
        "key": "test.decision1",
        "source": {"tool_id": "t1", "rule_id": "r1"},
        "target": {"kind": "process", "locator": "loc1"},
        "question": "q1",
        "adopted_default": "def1",
        "options": ["opt1"],
        "impact": ["grant_risk"],
        "decider": "attorney"
    }
    item2 = {
        "key": "test.decision2",
        "source": {"tool_id": "t1", "rule_id": "r2"},
        "target": {"kind": "claim", "locator": "loc2"},
        "question": "q2",
        "adopted_default": "def2",
        "options": ["opt2"],
        "impact": ["protection_scope"],
        "decider": "inventor"
    }
    # Duplicate of item1
    item3 = {
        "key": "test.decision1",
        "source": {"tool_id": "t2", "rule_id": "r1"},
        "target": {"kind": "process", "locator": "loc1"},
        "question": "q1",
        "adopted_default": "def1",
        "options": ["opt1"],
        "impact": ["grant_risk"],
        "decider": "attorney"
    }

    report1.write_text(json.dumps({"tool_id": "t1", "pending_decisions": [item1, item2, item3]}, ensure_ascii=False))

    # report2 has no pending_decisions
    report2.write_text(json.dumps({"tool_id": "t2", "other": "data"}))

    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(report1),
        "--report", str(report2),
        "--output", str(out_json),
        "--table", str(out_md)
    ]
    res = subprocess.run(cmd, capture_output=True)
    assert res.returncode == 0

    out_data = json.loads(out_json.read_text("utf-8"))
    assert len(out_data["decisions"]) == 2
    assert out_data["decisions"][0]["id"] == "D001"
    assert out_data["decisions"][1]["id"] == "D002"

    assert out_data["summary"]["decider"]["attorney"] == 1
    assert out_data["summary"]["decider"]["inventor"] == 1

    md_content = out_md.read_text("utf-8")
    assert "D001" in md_content
    assert "D002" in md_content

def test_missing_field_exit_3(tmp_path):
    report = tmp_path / "report.json"
    bad_item = {
        "key": "test.decision1",
        # missing source
        "target": {"kind": "process", "locator": "loc1"},
        "question": "q1",
        "adopted_default": "def1",
        "options": ["opt1"],
        "impact": ["grant_risk"],
        "decider": "attorney"
    }
    report.write_text(json.dumps({"pending_decisions": [bad_item]}, ensure_ascii=False))
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(report),
        "--output", str(tmp_path / "out.json"),
        "--table", str(tmp_path / "out.md")
    ]
    res = subprocess.run(cmd, capture_output=True)
    assert res.returncode == 3

def test_no_decisions(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"pending_decisions": []}, ensure_ascii=False))
    out_json = tmp_path / "out.json"
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(report),
        "--output", str(out_json),
        "--table", str(tmp_path / "out.md")
    ]
    res = subprocess.run(cmd, capture_output=True)
    assert res.returncode == 0
    out_data = json.loads(out_json.read_text("utf-8"))
    assert out_data["decisions"] == []

def test_guard_rejects(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"pending_decisions": []}, ensure_ascii=False))
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(report),
        "--output", str(report),
        "--table", str(tmp_path / "out.md")
    ]
    res = subprocess.run(cmd, capture_output=True)
    assert res.returncode == 3

