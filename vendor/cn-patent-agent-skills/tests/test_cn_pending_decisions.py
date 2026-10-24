import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

def test_schema_is_valid_json():
    for name in (
        "pending-decisions-schema-v1.json",
        "pending-application-evidence-schema-v1.json",
        "pending-resolutions-schema-v1.json",
    ):
        schema_path = Path("skills/cn-patent-application-creator/references") / name
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


def _run_collect(tmp_path, items, docx=None, table=None, evidence=None):
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
    if evidence is not None:
        cmd.extend(["--application-evidence", str(evidence)])
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


def test_routine_publication_and_repeated_cnipa_prompts(tmp_path):
    claim_1 = _decision(
        "inventive.assessment_review_pending",
        "claim",
        "权利要求1",
        "脚本把仅含权利要求1的方案评为defensible，但CNIPA官方库还没有检索，新颖性和创造性都不能下结论。是否批准先按这个复算结果保留权利要求1？",
    )
    claim_1["adopted_default"] = "不改权利要求1；分级保持脚本复算的defensible，新颖性和创造性仍不下结论。"
    claim_10 = _decision(
        "inventive.assessment_review_pending",
        "claim",
        "权利要求10",
        "脚本把仅含权利要求10的冷镦机方案评为defensible，但CNIPA官方库还没有检索，新颖性和创造性都不能下结论。是否批准先按这个复算结果保留权利要求10？",
    )
    claim_10["adopted_default"] = "不改权利要求10；分级保持脚本复算的defensible，新颖性和创造性仍不下结论。"
    claim_2 = _decision(
        "inventive.assessment_review_pending",
        "claim",
        "权利要求2",
        "脚本把权利要求1加权利要求2评为defensible，但CNIPA官方库还没有检索，新颖性和创造性都不能下结论。是否批准先按这个复算结果保留这组权利要求？",
    )
    claim_2["adopted_default"] = "不改权利要求1和权利要求2；分级保持脚本复算的defensible，新颖性和创造性仍不下结论。"
    partial = _decision(
        "inventive.partial_disclosure_heavy",
        "claim",
        "权利要求1",
        "脚本没有把这种更具体算作对比文件已经公开。是补充区别特征，还是确认接受这个风险？",
    )
    publication = _decision(
        "case.publication_and_priority",
        "application",
        "publication-priority",
        "现有材料没有写明这项技术是否已经公开，也没有写明要主张优先权。是否按尚未公开、并且不主张优先权继续？",
    )
    stated = _decision(
        "case.priority_documents",
        "application",
        "publication-priority",
        "用户已说明要主张优先权，在先申请号为 CN202410000001.1。优先权文件是否已备齐？",
    )
    cnipa = _decision(
        "search.cnipa_manual_search_pending_authorization",
        "process",
        "cnipa_manual_search",
        "本案还没有完成CNIPA官方库的人工检索，所以新颖性和创造性都不能写成已经成立。是否授权在官方库没有查完时继续使用本稿？",
    )
    cnipa["adopted_default"] = "继续使用本稿，新颖性和创造性保持不能下结论。"
    docx = tmp_path / "申请文件.docx"
    res, out_json = _run_collect(
        tmp_path,
        [publication, claim_1, claim_10, claim_2, partial, cnipa, stated],
        docx=docx,
    )
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    by_locator = {(item["key"], item["target"]["locator"]): item for item in payload["decisions"]}
    assert ("case.publication_and_priority", "publication-priority") not in by_locator
    assert "CNIPA" not in by_locator[("inventive.assessment_review_pending", "权利要求1")]["question"]
    assert by_locator[("inventive.assessment_review_pending", "权利要求1")]["question"] == (
        "脚本把仅含权利要求1的方案评为defensible。是否批准先按这个复算结果保留权利要求1？"
    )
    assert by_locator[("inventive.assessment_review_pending", "权利要求1")]["adopted_default"] == (
        "不改权利要求1；分级保持脚本复算的defensible。"
    )
    assert "CNIPA" not in by_locator[("inventive.assessment_review_pending", "权利要求10")]["question"]
    assert "CNIPA" not in by_locator[("inventive.assessment_review_pending", "权利要求2")]["question"]
    assert "新颖性和创造性仍不下结论" not in by_locator[("inventive.assessment_review_pending", "权利要求2")]["adopted_default"]
    assert by_locator[("inventive.partial_disclosure_heavy", "权利要求1")]["question"] == partial["question"]
    assert by_locator[("search.cnipa_manual_search_pending_authorization", "cnipa_manual_search")]["question"] == cnipa["question"]
    assert by_locator[("case.priority_documents", "publication-priority")]["question"] == stated["question"]
    pending = (tmp_path / "待决文件.md").read_text(encoding="utf-8")
    assert "是否已经公开" not in pending
    assert pending.count("CNIPA官方库") == 1


def test_without_dedicated_cnipa_item_only_one_claim_keeps_the_gap(tmp_path):
    first = _decision(
        "inventive.assessment_review_pending",
        "claim",
        "权利要求1",
        "脚本把权利要求1评为defensible，但CNIPA官方库还没有检索。是否保留？",
    )
    second = _decision(
        "inventive.assessment_review_pending",
        "claim",
        "权利要求2",
        "脚本把权利要求2评为defensible，但CNIPA官方库还没有检索。是否保留？",
    )
    docx = tmp_path / "申请文件.docx"
    res, out_json = _run_collect(tmp_path, [first, second], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    by_locator = {item["target"]["locator"]: item["question"] for item in payload["decisions"]}
    assert "CNIPA" in by_locator["权利要求1"]
    assert "CNIPA" not in by_locator["权利要求2"]
    assert by_locator["权利要求2"] == "脚本把权利要求2评为defensible。是否保留？"


def _replace_decision(text: str, item_id: str, decision: str, annotation: str | None = None) -> str:
    start = text.index(f"<!-- item:{item_id} -->")
    end = text.index(f"<!-- /item:{item_id} -->")
    block = text[start:end]
    block = block.replace("未决", decision, 1)
    if annotation is not None:
        block = block.replace("（在此填写。留空表示这一条仍未决定。）", annotation, 1)
    return text[:start] + block + text[end:]


def test_closed_decisions_leave_the_active_list_until_content_changes(tmp_path):
    """采纳默认且内容未变才离开活动清单。不同于默认的选择只是已决定，暂缓仍保留。"""

    docx = tmp_path / "申请文件.docx"
    kept = _decision("a.default", "claim", "权利要求1", "是否维持默认？")
    chosen = _decision("b.choose", "claim", "权利要求2", "选哪个？", ["改为5", "保持3"])
    deferred = _decision("c.defer", "claim", "权利要求3", "要不要现在改？")
    res, out_json = _run_collect(tmp_path, [kept, chosen, deferred], docx=docx)
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    text = pending.read_text(encoding="utf-8")
    text = _replace_decision(text, "D001", "采纳默认")
    text = _replace_decision(text, "D002", "选择：改为5")
    text = _replace_decision(text, "D003", "暂缓")
    pending.write_text(text, encoding="utf-8")

    res, _ = _run_collect(tmp_path, [kept, chosen, deferred], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert {item["key"] for item in payload["decisions"]} == {"b.choose", "c.defer"}
    by_key = {item["key"]: item for item in payload["resolutions"]}
    assert by_key["a.default"]["resolution"] == "accept_default"
    assert by_key["a.default"]["resolved"] is True
    assert by_key["a.default"]["applied"] is True
    assert by_key["a.default"]["status"] == "applied"
    assert by_key["a.default"]["application_binding"] == "accept_default_current_draft"
    assert by_key["a.default"]["content_version"]
    assert by_key["b.choose"]["resolution"] == "choose"
    assert by_key["b.choose"]["selected_option"] == "改为5"
    assert by_key["b.choose"]["resolved"] is True
    assert by_key["b.choose"]["applied"] is False
    assert by_key["b.choose"]["status"] == "resolved"
    assert by_key["b.choose"]["application_binding"] == "decision_only"
    assert by_key["c.defer"]["resolution"] == "defer"
    assert by_key["c.defer"]["resolved"] is False
    assert by_key["c.defer"]["applied"] is False
    assert "a.default" not in {item["key"] for item in payload["decisions"]}
    assert "选择：改为5" in pending.read_text(encoding="utf-8")

    res, _ = _run_collect(tmp_path, [kept, chosen, deferred], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert {item["key"] for item in payload["decisions"]} == {"b.choose", "c.defer"}
    again = {item["key"]: item for item in payload["resolutions"]}
    assert again["b.choose"]["selected_option"] == "改为5"
    assert again["b.choose"]["applied"] is False

    changed = dict(kept)
    changed["question"] = "是否改为另一默认？"
    res, _ = _run_collect(tmp_path, [changed, chosen, deferred], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "a.default" in {item["key"] for item in payload["decisions"]}
    reopened = next(item for item in payload["resolutions"] if item["key"] == "a.default")
    assert reopened["status"] == "reopened"
    assert reopened["applied"] is False
    assert reopened["content_version"] != reopened["current_content_version"]
    markdown = pending.read_text(encoding="utf-8")
    assert "失效决定：采纳默认" in markdown
    assert {item["key"] for item in payload["decisions"] if item["key"] == "b.choose"} == {"b.choose"}
    kept_choice = next(item for item in payload["resolutions"] if item["key"] == "b.choose")
    assert kept_choice["selected_option"] == "改为5"
    assert kept_choice["applied"] is False
    assert "选择：改为5" in markdown


def test_damaged_pending_boundaries_are_not_rewritten(tmp_path):
    """部分边界损坏、对调结束标记、重复编号或尾部残缺时，不覆盖用户原文。"""

    docx = tmp_path / "申请文件.docx"
    res, out_json = _run_collect(
        tmp_path,
        [
            _decision("a.one", "claim", "权利要求1", "问题一"),
            _decision("b.two", "claim", "权利要求2", "问题二"),
        ],
        docx=docx,
    )
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    original = pending.read_text(encoding="utf-8")
    instruction = "删除权利要求2并保留说明书披露"

    def assert_preserved(mutated: str) -> None:
        pending.write_bytes(mutated.encode("utf-8"))
        before = pending.read_bytes()
        json_before = out_json.read_bytes()
        again = _run_collect(
            tmp_path,
            [
                _decision("a.one", "claim", "权利要求1", "问题一"),
                _decision("b.two", "claim", "权利要求2", "问题二"),
            ],
            docx=docx,
        )[0]
        assert again.returncode == 3, again.stderr
        assert pending.read_bytes() == before
        assert out_json.read_bytes() == json_before

    damaged = original
    pos = damaged.index("<!-- item:D002 -->")
    damaged = damaged[:pos] + damaged[pos:].replace("### 决定\n\n未决", "### 决定\n\n" + instruction, 1)
    damaged = damaged.replace("<!-- /item:D002 -->", "<!-- /item:D002-X -->", 1)
    assert_preserved(damaged)

    swapped = original.replace("<!-- /item:D001 -->", "<!-- /item:TEMP -->", 1)
    swapped = swapped.replace("<!-- /item:D002 -->", "<!-- /item:D001 -->", 1)
    swapped = swapped.replace("<!-- /item:TEMP -->", "<!-- /item:D002 -->", 1)
    assert_preserved(swapped)

    duplicate = original + original[original.index("<!-- item:D001 -->"):original.index("<!-- /item:D001 -->") + len("<!-- /item:D001 -->")]
    assert_preserved(duplicate)

    truncated = original.replace("<!-- /item:D002 -->", "<!-- /item:D002", 1)
    assert_preserved(truncated)

    legal = _replace_decision(original, "D001", "请维持当前写法", "只改权利要求1。")
    pending.write_text(legal, encoding="utf-8")
    res, _ = _run_collect(
        tmp_path,
        [
            _decision("a.one", "claim", "权利要求1", "问题一"),
            _decision("b.two", "claim", "权利要求2", "问题二"),
        ],
        docx=docx,
    )
    assert res.returncode == 0, res.stderr
    rewritten = pending.read_text(encoding="utf-8")
    assert "请维持当前写法" in rewritten
    assert "只改权利要求1。" in rewritten
    assert "问题二" in rewritten


def _run_read(pending, output):
    cmd = [
        sys.executable, "skills/cn-patent-application-creator/scripts/read_pending_file.py",
        "--pending-file", str(pending),
        "--output", str(output),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _content_version(text, item_id):
    start = text.index(f"<!-- item:{item_id} -->")
    end = text.index(f"<!-- /item:{item_id} -->")
    matched = re.search(r"- 内容版本：([0-9a-f]{64})", text[start:end])
    assert matched is not None
    return matched.group(1)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _keep_claim_two():
    item = _decision(
        "claim.two.keep",
        "claim",
        "权利要求2",
        "权利要求2要不要从当前稿删除？",
        ["删除权利要求2"],
    )
    item["adopted_default"] = "保留权利要求2"
    return item


def _prepare_delete_choice(tmp_path):
    source = tmp_path / "权利要求书.md"
    source.write_text("权利要求2予以保留。\n", encoding="utf-8")
    item = _keep_claim_two()
    docx = tmp_path / "申请文件.docx"
    res, out_json = _run_collect(tmp_path, [item], docx=docx)
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    pending.write_text(
        _replace_decision(pending.read_text(encoding="utf-8"), "D001", "选择：删除权利要求2"),
        encoding="utf-8",
    )
    return item, source, pending, out_json, docx


def _evidence(tmp_path, source, content_version, *, case_id=None, sha=None, key="claim.two.keep"):
    payload = {
        "schema_id": "cn-patent-pending-application-evidence/v1",
        "case_id": tmp_path.name if case_id is None else case_id,
        "binding_note": "只证明应用声明绑定当前源稿，不证明备选已经写入文书。",
        "items": [{
            "key": key,
            "target": {"kind": "claim", "locator": "权利要求2"},
            "resolution": "choose",
            "selected_option": "删除权利要求2",
            "decision_text": "选择：删除权利要求2",
            "annotation": "",
            "content_version": content_version,
            "sources": [{
                "path": source.name,
                "sha256": sha if sha is not None else _sha256(source),
            }],
        }],
    }
    path = tmp_path / "application-evidence.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_choose_delete_is_not_applied_when_source_is_unchanged(tmp_path):
    """当前稿保留、用户选删除，源稿未变：回读和汇总都不得 applied，也不得丢掉待落实事项。"""

    item, source, pending, out_json, docx = _prepare_delete_choice(tmp_path)
    original = source.read_bytes()
    resolution = tmp_path / "待决决议.json"
    read = _run_read(pending, resolution)
    assert read.returncode == 0, read.stderr
    chosen = json.loads(resolution.read_text(encoding="utf-8"))["items"][0]
    assert chosen["resolution"] == "choose"
    assert chosen["selected_option"] == "删除权利要求2"
    assert chosen["resolved"] is True
    assert chosen["applied"] is False
    assert chosen["status"] == "resolved"

    res, _ = _run_collect(tmp_path, [item], docx=docx)
    assert res.returncode == 0, res.stderr
    assert source.read_bytes() == original
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert {entry["key"] for entry in payload["decisions"]} == {"claim.two.keep"}
    record = payload["resolutions"][0]
    assert record["applied"] is False
    assert record["resolved"] is True
    assert record["status"] == "resolved"
    assert record["selected_option"] == "删除权利要求2"
    assert record["application_binding"] == "decision_only"
    markdown = pending.read_text(encoding="utf-8")
    assert "选择：删除权利要求2" in markdown
    assert "## 已落实的决定" not in markdown

    read_again = _run_read(pending, resolution)
    assert read_again.returncode == 0, read_again.stderr
    reread = json.loads(resolution.read_text(encoding="utf-8"))["items"][0]
    assert reread["applied"] is False
    assert reread["selected_option"] == "删除权利要求2"
    assert source.read_bytes() == original


def test_accept_default_with_unchanged_content_still_closes(tmp_path):
    """采纳默认且问题、默认做法和备选都没变时，仍然收掉。"""

    docx = tmp_path / "申请文件.docx"
    kept = _decision("a.default", "claim", "权利要求1", "是否维持默认？")
    res, out_json = _run_collect(tmp_path, [kept], docx=docx)
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    pending.write_text(
        _replace_decision(pending.read_text(encoding="utf-8"), "D001", "采纳默认"),
        encoding="utf-8",
    )
    res, _ = _run_collect(tmp_path, [kept], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["decisions"] == []
    record = payload["resolutions"][0]
    assert record["resolution"] == "accept_default"
    assert record["resolved"] is True
    assert record["applied"] is True
    assert record["status"] == "applied"
    assert record["application_binding"] == "accept_default_current_draft"
    assert record["application_sources"] == []
    res, _ = _run_collect(tmp_path, [kept], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["decisions"] == []
    assert payload["resolutions"][0]["applied"] is True


def test_explicit_source_binding_can_close_a_changed_draft(tmp_path):
    """空自报和错误哈希不能关闭；绑定改过的源稿后可以关闭，选择记录仍在。"""

    item, source, pending, out_json, docx = _prepare_delete_choice(tmp_path)
    original = source.read_bytes()
    pending_bytes = pending.read_bytes()
    json_bytes = out_json.read_bytes()
    version = _content_version(pending.read_text(encoding="utf-8"), "D001")

    bogus = tmp_path / "application-evidence.json"
    bogus.write_text(json.dumps({"applied": True}, ensure_ascii=False), encoding="utf-8")
    rejected = _run_collect(tmp_path, [item], docx=docx, evidence=bogus)[0]
    assert rejected.returncode == 3, rejected.stderr
    assert "落实证据" in rejected.stderr
    assert pending.read_bytes() == pending_bytes
    assert out_json.read_bytes() == json_bytes
    assert source.read_bytes() == original

    bad_hash = _evidence(tmp_path, source, version, sha="0" * 64)
    rejected = _run_collect(tmp_path, [item], docx=docx, evidence=bad_hash)[0]
    assert rejected.returncode == 3, rejected.stderr
    assert pending.read_bytes() == pending_bytes
    assert source.read_bytes() == original

    source.write_text("权利要求2已从当前稿删除。\n", encoding="utf-8")
    wrong_case = _evidence(tmp_path, source, version, case_id="另一案")
    rejected = _run_collect(tmp_path, [item], docx=docx, evidence=wrong_case)[0]
    assert rejected.returncode == 3, rejected.stderr
    assert pending.read_bytes() == pending_bytes
    payload = json.loads(json_bytes)
    assert payload["decisions"][0]["key"] == "claim.two.keep"

    bound = _evidence(tmp_path, source, version)
    res, _ = _run_collect(tmp_path, [item], docx=docx, evidence=bound)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["decisions"] == []
    record = payload["resolutions"][0]
    assert record["applied"] is True
    assert record["resolved"] is True
    assert record["status"] == "applied"
    assert record["selected_option"] == "删除权利要求2"
    assert record["application_binding"] == "source_hash_bound"
    assert "不证明" in record["application_binding_note"]
    assert record["application_sources"] == [{"path": source.name, "sha256": _sha256(source)}]
    assert "选择：删除权利要求2" in pending.read_text(encoding="utf-8")

    res, _ = _run_collect(tmp_path, [item], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["decisions"] == []
    assert payload["resolutions"][0]["applied"] is True
    assert payload["resolutions"][0]["selected_option"] == "删除权利要求2"

    source.write_text("权利要求2又被写回当前稿。\n", encoding="utf-8")
    res, _ = _run_collect(tmp_path, [item], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert {entry["key"] for entry in payload["decisions"]} == {"claim.two.keep"}
    record = payload["resolutions"][0]
    assert record["applied"] is False
    assert record["resolved"] is True
    assert record["selected_option"] == "删除权利要求2"
    assert "选择：删除权利要求2" in pending.read_text(encoding="utf-8")


def test_content_change_reopens_closed_decisions_without_losing_the_choice(tmp_path):
    """内容变化会重新打开已落实事项，选择原文留在决议和失效决定里。"""

    docx = tmp_path / "申请文件.docx"
    kept = _decision("a.default", "claim", "权利要求1", "是否维持默认？")
    chosen = _keep_claim_two()
    res, out_json = _run_collect(tmp_path, [kept, chosen], docx=docx)
    assert res.returncode == 0, res.stderr
    pending = tmp_path / "待决文件.md"
    text = pending.read_text(encoding="utf-8")
    text = _replace_decision(text, "D001", "采纳默认")
    text = _replace_decision(text, "D002", "选择：删除权利要求2")
    pending.write_text(text, encoding="utf-8")
    source = tmp_path / "权利要求书.md"
    source.write_text("权利要求2已从当前稿删除。\n", encoding="utf-8")
    version = _content_version(pending.read_text(encoding="utf-8"), "D002")
    evidence = _evidence(tmp_path, source, version)
    res, _ = _run_collect(tmp_path, [kept, chosen], docx=docx, evidence=evidence)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert {entry["key"] for entry in payload["decisions"]} == set()

    kept_changed = dict(kept)
    kept_changed["question"] = "是否改为另一默认？"
    chosen_changed = dict(chosen)
    chosen_changed["question"] = "删除之后是否还要保留说明书里的对应句子？"
    res, _ = _run_collect(tmp_path, [kept_changed, chosen_changed], docx=docx)
    assert res.returncode == 0, res.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert {entry["key"] for entry in payload["decisions"]} == {"a.default", "claim.two.keep"}
    by_key = {entry["key"]: entry for entry in payload["resolutions"]}
    assert by_key["a.default"]["status"] == "reopened"
    assert by_key["a.default"]["applied"] is False
    assert by_key["a.default"]["resolved"] is False
    assert by_key["a.default"]["content_version"] != by_key["a.default"]["current_content_version"]
    assert by_key["claim.two.keep"]["status"] == "reopened"
    assert by_key["claim.two.keep"]["applied"] is False
    assert by_key["claim.two.keep"]["selected_option"] == "删除权利要求2"
    assert by_key["claim.two.keep"]["decision_text"] == "选择：删除权利要求2"
    markdown = pending.read_text(encoding="utf-8")
    assert "失效决定：采纳默认" in markdown
    assert "失效决定：选择：删除权利要求2" in markdown


def test_choice_record_survives_regeneration_while_unapplied(tmp_path):
    """未落实时重复汇总不能把选择清成未决，也不能改掉源稿。"""

    item, source, pending, out_json, docx = _prepare_delete_choice(tmp_path)
    original = source.read_bytes()
    for _ in range(2):
        res, _ = _run_collect(tmp_path, [item], docx=docx)
        assert res.returncode == 0, res.stderr
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        assert {entry["key"] for entry in payload["decisions"]} == {"claim.two.keep"}
        record = next(entry for entry in payload["resolutions"] if entry["key"] == "claim.two.keep")
        assert record["selected_option"] == "删除权利要求2"
        assert record["decision_text"] == "选择：删除权利要求2"
        assert record["applied"] is False
        assert record["resolved"] is True
        markdown = pending.read_text(encoding="utf-8")
        assert "选择：删除权利要求2" in markdown
        assert "失效决定" not in markdown
        assert source.read_bytes() == original
