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
        "--allow-detached", "--table", str(out_md)
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
        "--allow-detached", "--table", str(tmp_path / "out.md")
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
        "--allow-detached", "--table", str(tmp_path / "out.md")
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
        "--allow-detached", "--table", str(tmp_path / "out.md")
    ]
    res = subprocess.run(cmd, capture_output=True)
    assert res.returncode == 3



def _decision(key, kind, locator, question, options=None, decider="attorney"):
    return {
        "key": key,
        "source": {"tool_id": "t1", "rule_id": "r1"},
        "target": {"kind": kind, "locator": locator},
        "question": question,
        "adopted_default": "采用保守默认",
        "options": options or ["备选甲"],
        "impact": ["grant_risk"],
        "decider": decider,
    }


def _run_collect(tmp_path, items, docx=None, table=None):
    report = tmp_path / "report-round.json"
    report.write_text(json.dumps({"tool_id": "t1", "pending_decisions": items}, ensure_ascii=False), encoding="utf-8")
    out_json = tmp_path / "pending-decisions.json"
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(report),
        "--output", str(out_json),
    ]
    if docx is not None:
        cmd.extend(["--docx", str(docx)])
    else:
        cmd.extend(["--allow-detached", "--table", str(table)])
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res, out_json


def test_pending_file_is_written_beside_docx(tmp_path):
    docx = tmp_path / "交付" / "申请文件.docx"
    docx.parent.mkdir()
    items = [_decision("scope.threshold", "claim", "权利要求2", "阈值是否改为5？", ["改为5", "保持3"])]
    res, _ = _run_collect(tmp_path, items, docx=docx)
    assert res.returncode == 0, res.stderr
    pending = docx.parent / "待决文件.md"
    assert pending.is_file()
    text = pending.read_text(encoding="utf-8")
    assert text.startswith("# 待决文件\n")
    assert "申请文件.docx" in text
    assert "<!-- item:D001 -->" in text
    assert "### 决定" in text


def test_docx_rejects_a_different_filename(tmp_path):
    docx = tmp_path / "申请文件.docx"
    wrong = tmp_path / "待决事项清单.md"
    res, out_json = _run_collect(tmp_path, [], docx=docx)
    # 先确认空清单可以写到同目录，再单独验证错误路径不会落盘。
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "待决文件.md").is_file()
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(tmp_path / "report-round.json"),
        "--output", str(out_json),
        "--docx", str(docx),
        "--table", str(wrong),
    ]
    rejected = subprocess.run(cmd, capture_output=True, text=True)
    assert rejected.returncode == 3
    assert not wrong.exists()


def test_without_docx_is_rejected(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"pending_decisions": []}), encoding="utf-8")
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/collect_pending_decisions.py",
        "--case-dir", str(tmp_path),
        "--report", str(report),
        "--output", str(tmp_path / "out.json"),
        "--table", str(tmp_path / "待决文件.md"),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 3
    assert not (tmp_path / "待决文件.md").exists()


def test_annotations_and_ids_survive_regeneration(tmp_path):
    docx = tmp_path / "申请文件.docx"
    first = [
        _decision("beta.keep", "claim", "权利要求1", "是否保留特征甲？"),
        _decision("gamma.drop", "process", "阶段门", "是否补检索？"),
    ]
    res, out_json = _run_collect(tmp_path, first, docx=docx)
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    text = pending.read_text(encoding="utf-8")
    start = text.index("<!-- item:D001 -->")
    end = text.index("<!-- /item:D001 -->")
    block = text[start:end].replace("未决", "采纳默认", 1)
    block = block.replace("（在此填写。留空表示这一条仍未决定。）", "权利要求1维持现稿。", 1)
    pending.write_text(text[:start] + block + text[end:], encoding="utf-8")
    second = [
        _decision("alpha.new", "abstract", "摘要", "摘要要不要改写法？"),
        _decision("beta.keep", "claim", "权利要求1", "是否保留特征甲？"),
    ]
    res, _ = _run_collect(tmp_path, second, docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    by_key = {item["key"]: item["id"] for item in payload["decisions"]}
    assert by_key["beta.keep"] == "D001"
    assert by_key["alpha.new"] == "D003"
    regenerated = pending.read_text(encoding="utf-8")
    assert "采纳默认" in regenerated
    assert "权利要求1维持现稿。" in regenerated
    assert "原 D002" in regenerated
    kept = regenerated.split("<!-- /item:D001 -->", 1)[0]
    assert "alpha.new" not in kept


def test_unparseable_annotation_is_not_overwritten(tmp_path):
    docx = tmp_path / "申请文件.docx"
    pending = tmp_path / "待决文件.md"
    pending.write_text("# 待决文件\n\n### 决定\n\n人工已经写了不能解析的内容\n", encoding="utf-8")
    res, out_json = _run_collect(tmp_path, [_decision("a.one", "claim", "权利要求1", "问题")], docx=docx)
    assert res.returncode == 3
    assert "不能解析" in pending.read_text(encoding="utf-8")
    assert not out_json.exists()


def test_read_pending_file_classifies_user_edits(tmp_path):
    docx = tmp_path / "申请文件.docx"
    items = [
        _decision("a.default", "claim", "权利要求1", "是否维持默认？"),
        _decision("b.choose", "claim", "权利要求2", "选哪个？", ["改为5", "保持3"]),
        _decision("c.instruct", "specification", "具体实施方式", "实施例要不要补参数？"),
        _decision("d.bad", "claim", "权利要求3", "选哪个？", ["改为5"]),
    ]
    res, _ = _run_collect(tmp_path, items, docx=docx)
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    text = pending.read_text(encoding="utf-8")
    replacements = {
        "D001": ("采纳默认", "（在此填写。留空表示这一条仍未决定。）"),
        "D002": ("选择：改为5", "（在此填写。留空表示这一条仍未决定。）"),
        "D003": ("请把实施例里的压力写成 0.2 MPa。", "只改这一处。"),
        "D004": ("选择：不存在的方案", "（在此填写。留空表示这一条仍未决定。）"),
    }
    for item_id, (decision, annotation) in replacements.items():
        start = text.index(f"<!-- item:{item_id} -->")
        end = text.index(f"<!-- /item:{item_id} -->")
        block = text[start:end]
        block = block.replace("未决", decision, 1)
        block = block.replace("（在此填写。留空表示这一条仍未决定。）", annotation, 1)
        text = text[:start] + block + text[end:]
    pending.write_text(text, encoding="utf-8")
    resolution = tmp_path / "待决决议.json"
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/read_pending_file.py",
        "--pending-file", str(pending),
        "--output", str(resolution),
    ]
    read = subprocess.run(cmd, capture_output=True, text=True)
    assert read.returncode == 0, read.stderr
    payload = json.loads(resolution.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["D001"]["resolution"] == "accept_default"
    assert by_id["D002"]["resolution"] == "choose"
    assert by_id["D002"]["selected_option"] == "改为5"
    assert by_id["D003"]["resolution"] == "instruct"
    assert "0.2 MPa" in by_id["D003"]["instruction"]
    assert by_id["D004"]["resolution"] == "instruct"
    assert by_id["D004"]["option_unmatched"] is True
    assert payload["legal_effect"] == "ADVISORY_ONLY"
    assert "INSTRUCT=2" in read.stdout
