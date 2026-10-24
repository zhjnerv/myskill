"""中国发明专利范本学习闭环测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "cn-patent-application-creator" / "scripts"
REFERENCES = ROOT / "skills" / "cn-patent-application-creator" / "references"
SEARCH_SCRIPT = SCRIPTS / "generate_search_query.py"
ANALYZER_SCRIPT = SCRIPTS / "analyze_template_style.py"
APPLICATOR_SCRIPT = SCRIPTS / "style_applicator.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_search_generator_produces_project_schema_query_and_gap_disclosure(tmp_path):
    features = {
        "technical_problem": "提高分布式锁在网络抖动场景下的一致性",
        "technical_solution": "通过租约续期和仲裁节点切换实现故障恢复",
        "key_components": ["租约管理器", "仲裁节点"],
        "algorithms": ["版本戳校验算法"],
        "field": "分布式数据处理与网络通信",
        "keywords_en": ["lease renewal", "controller's state"],
        "ipc_codes": ["G06F11/30"],
    }
    source = tmp_path / "features.json"
    output = tmp_path / "search-query.json"
    source.write_text(json.dumps(features, ensure_ascii=False), encoding="utf-8")

    result = _run(SEARCH_SCRIPT, "--features", str(source), "--output", str(output))

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["schema_id"] == "cn-patent-template-search/v1"
    assert manifest["bigquery_table"] == "patents-public-data.patents.publications"
    assert "patents_2024" not in manifest["bigquery_query"]
    assert "title_localized" in manifest["bigquery_query"]
    assert "UNNEST(cpc)" in manifest["bigquery_query"]
    assert "lease renewal" in manifest["keywords"]["keywords_en"]
    assert "controller\\'s state" in manifest["bigquery_query"]
    assert "仲裁节点" in manifest["keywords"]["untranslated_cn_terms"]
    assert manifest["target_ipc"]["status"] == "determined"
    assert manifest["target_ipc"]["ipc_codes"] == ["G06F11/30"]
    assert manifest["target_ipc"]["suggested_ipc_codes"] == ["H04L", "G06F", "H04W"]
    assert "CNIPA 官方库检索仍需人工执行" in result.stdout
    assert "不证明已完成 CNIPA 官方库检索" in manifest["cnipa_guide"]
    uyanip = manifest["uyanip_plan"]
    assert uyanip["priority"] == 1
    assert "uyanip.com" in uyanip["command_url"]
    assert uyanip["country_filter"] == "AND GJ:(CN)"
    assert uyanip["expressions"], "至少生成一个度衍检索式"
    assert all(
        e["result_url"].startswith("https://www.uyanip.com/result?fromMode=5")
        for e in uyanip["expressions"]
    )
    assert any(e["purpose"] == "determined_ipc" for e in uyanip["expressions"])
    assert any(e["purpose"] == "broad_expansion" for e in uyanip["expressions"])
    assert uyanip["field_codes"]["专利名称"] == "ZLMC"



def test_search_generator_marks_keyword_only_ipc_as_suggested(tmp_path):
    source = tmp_path / "features.json"
    output = tmp_path / "search-query.json"
    source.write_text(
        json.dumps({
            "technical_problem": "移动应用测试故障难以归因",
            "technical_solution": "基于数据处理和故障恢复进行分层判断",
            "field": "数据处理",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    result = _run(SEARCH_SCRIPT, "--features", str(source), "--output", str(output))
    assert result.returncode == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["target_ipc"]["status"] == "suggested"
    assert manifest["target_ipc"]["ipc_codes"] == ["G06F"]
    assert any(
        "先判断目标技术方案 IPC" in item
        for item in manifest["manual_actions_required"]
    )

def test_search_generator_rejects_unbounded_empty_query(tmp_path):
    source = tmp_path / "features.json"
    output = tmp_path / "search-query.json"
    source.write_text("{}", encoding="utf-8")

    result = _run(SEARCH_SCRIPT, "--features", str(source), "--output", str(output))

    assert result.returncode == 2
    assert "禁止生成全表" in result.stderr
    assert not output.exists()


def test_analyzer_and_applicator_form_a_valid_handoff(tmp_path):
    claims = tmp_path / "claims.txt"
    specification = tmp_path / "specification.txt"
    abstract = tmp_path / "abstract.txt"
    guide = tmp_path / "nested" / "template-style-guide.json"
    brief = tmp_path / "nested" / "style-brief.json"

    claims.write_text(
        "1. 一种分布式锁管理系统，其特征在于，包括租约管理器和仲裁节点。\n"
        "2. 根据权利要求1所述的系统，其特征在于，所述租约管理器执行续期。\n"
        "3. 根据权利要求1所述的系统，其特征在于，所述仲裁节点校验版本戳。\n",
        encoding="utf-8",
    )
    specification.write_text(
        "技术领域\n本发明涉及分布式数据处理技术。\n\n"
        "背景技术\n现有系统在网络抖动时可能失去一致性。\n\n"
        "发明内容\n本发明提供一种分布式锁管理系统。\n\n"
        "附图说明\n图1为系统结构示意图。\n图2为续期流程图。\n\n"
        "具体实施方式\n实施例1\n如图1所示，系统包括租约管理器100和仲裁节点200。\n"
        "实施例2\n如图2所示，首先校验版本戳，然后执行租约续期。\n"
        "图中：100-租约管理器、200-仲裁节点。\n",
        encoding="utf-8",
    )
    abstract.write_text(
        "本发明涉及分布式数据处理技术，提供一种锁管理系统，用于解决网络抖动导致的一致性问题，能够提高故障恢复效率。",
        encoding="utf-8",
    )

    analysis = _run(
        ANALYZER_SCRIPT,
        "--patent-number",
        "CN202610000001.0",
        "--claims",
        str(claims),
        "--specification",
        str(specification),
        "--abstract",
        str(abstract),
        "--output",
        str(guide),
    )
    assert analysis.returncode == 0, analysis.stderr

    application = _run(
        APPLICATOR_SCRIPT,
        "--style-guide",
        str(guide),
        "--available-features",
        "8",
        "--available-variations",
        "2",
        "--available-components",
        "3",
        "--output",
        str(brief),
    )
    assert application.returncode == 0, application.stderr
    payload = json.loads(brief.read_text(encoding="utf-8"))
    assert payload["schema_id"] == "cn-patent-style-brief/v1"
    assert payload["source"] == {
        "mode": "template",
        "template_patent": "CN202610000001.0",
        "provenance_mode": "analyzer",
        "manual_override_count": 0,
    }
    assert payload["claims"]["count"]["dependent"] >= 0
    assert payload["claims"]["count"]["total"] <= 10
    assert payload["abstract"]["max_chars"] == 300
    assert "不得据此新增技术特征" in payload["usage_boundary"]


def test_applicator_rejects_invalid_guide_and_zero_features(tmp_path):
    invalid_guide = tmp_path / "invalid-guide.json"
    invalid_guide.write_text(
        json.dumps(
            {
                "schema_id": "cn-patent-template-style/v1",
                "template_patent": "CN1",
                "extraction_timestamp": "2026-08-12T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    invalid_result = _run(
        APPLICATOR_SCRIPT,
        "--style-guide",
        str(invalid_guide),
        "--available-features",
        "3",
        "--output",
        str(tmp_path / "invalid-brief.json"),
    )
    assert invalid_result.returncode == 2
    assert "claims_style 必须是对象" in invalid_result.stderr

    zero_result = _run(
        APPLICATOR_SCRIPT,
        "--available-features",
        "0",
        "--output",
        str(tmp_path / "zero-brief.json"),
    )
    assert zero_result.returncode == 2
    assert "available_features 必须大于等于 1" in zero_result.stderr


def test_template_style_schema_is_machine_readable_utf8_json():
    schema_path = REFERENCES / "template-style-schema.json"
    raw = schema_path.read_bytes()
    assert raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    schema = json.loads(raw.decode("utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["$id"] == "cn-patent-template-style/v1"
    assert "claims_style" in schema["required"]


def test_skill_and_orchestrator_bind_template_learning_handoff():
    skill = (ROOT / "skills" / "cn-patent-application-creator" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / "skills" / "cn-patent-workflow" / "SKILL.md").read_text(encoding="utf-8")
    stage_map = (
        ROOT / "skills" / "cn-patent-workflow" / "references" / "stage-map.md"
    ).read_text(encoding="utf-8")
    for required in (
        "generate_search_query.py",
        "analyze_template_style.py",
        "style_applicator.py",
        "rank_template_candidates.py",
        "cn-patent-template-search/v1",
        "cn-patent-template-candidates/v1",
        "cn-patent-template-selection/v2",
        "cn-patent-stage2-gate/v2",
        "cn-patent-template-style/v1",
        "cn-patent-style-brief/v1",
    ):
        assert required in skill
    assert "检索与范本" in workflow
    assert "cn-patent-application-creator" in workflow
    for artifact in (
        "search-query.json",
        "template-selection.json",
        "cn-patent-feature-ledger/v2",
        "cn-patent-stage2-gate/v2",
    ):
        assert artifact in stage_map


def test_cn_creator_delivery_scope_is_four_technical_documents_only():
    skill = (ROOT / "skills" / "cn-patent-application-creator" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / "skills" / "cn-patent-workflow" / "SKILL.md").read_text(encoding="utf-8")

    for required in ("权利要求书", "说明书", "说明书摘要", "说明书附图"):
        assert required in skill

    assert "申请人、发明人、联系电话、地址、联系人、代理机构" in skill
    assert "不属于本技能交付范围" in skill
    assert "DOCX" in workflow
    assert "Slash Command" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_analyzer_recognizes_ru_and_range_dependency_phrases(tmp_path):
    claims = tmp_path / "claims.txt"
    specification = tmp_path / "specification.txt"
    guide = tmp_path / "guide.json"
    claims.write_text(
        "1. 一种冷镦机顶出机构，包括凸轮和摇臂。\n"
        "2. 如权利要求1所述的冷镦机顶出机构，其特征在于，包括调节盘。\n"
        "3. 按照权利要求1或2所述的冷镦机顶出机构，其特征在于，包括挡销。\n"
        "4. 根据权利要求1-3任一项所述的冷镦机顶出机构，其特征在于，包括弹簧。\n",
        encoding="utf-8",
    )
    specification.write_text(
        "技术领域\n冷镦设备。\n背景技术\n现有机构。\n发明内容\n提供顶出机构。\n"
        "附图说明\n图1为结构图。\n具体实施方式\n凸轮驱动摇臂。\n",
        encoding="utf-8",
    )
    result = _run(
        ANALYZER_SCRIPT,
        "--patent-number", "CNTEST",
        "--claims", str(claims),
        "--specification", str(specification),
        "--output", str(guide),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(guide.read_text(encoding="utf-8"))
    assert payload["claims_style"]["independent_claims_count"] == 1
    assert payload["claims_style"]["dependent_claims_count"] == 3
    assert payload["claims_style"]["total_claims"] == 4
