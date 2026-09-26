"""feature ledger v2 的数据流、方法—系统和异常路径回归。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/cn-patent-application-creator/scripts/build_feature_ledger.py"


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    claims = tmp_path / "权利要求书.md"
    specification = tmp_path / "说明书.md"
    ledger = tmp_path / "feature-ledger.json"
    output = tmp_path / "feature-ledger-report.json"
    claims.write_text(
        "# 权利要求书\n\n"
        "1. 一种处理方法，包括预先配置规则，读取输入数据，输出结果并设置低置信度完成状态及原因码。\n\n"
        "9. 一种处理系统，包括规则配置模块、数据处理模块和结果存储模块，所述结果存储模块设置低置信度完成状态及原因码。\n",
        encoding="utf-8",
    )
    specification.write_text(
        "# 示例\n\n## 技术领域\n\n数据处理。\n\n## 背景技术\n\n现有技术。\n\n"
        "## 发明内容\n\n预先配置规则，读取输入数据，输出结果。\n\n## 附图说明\n\n无。\n\n"
        "## 具体实施方式\n\n预先配置规则后读取输入数据，输出结果并设置低置信度完成状态及原因码，存储结果值、置信度、状态和原因码。\n",
        encoding="utf-8",
    )
    features = [
        {
            "feature_id": "F001", "name": "预先配置规则", "statement": "预先配置规则", "classification": "distinguishing",
            "prior_art_status": {"verdict": "not_found_in_searched_outlets"}, "technical_effect": "使规则与运行处理分离",
            "evidence": [{"source": "交底书", "locator": "1"}],
            "claim_sites": [
                {"claim_number": 1, "part": "characterizing", "claim_type": "method", "execution_role": "precondition", "verbatim": "预先配置规则"},
                {"claim_number": 9, "part": "characterizing", "claim_type": "system", "execution_role": "module", "actor": "规则配置模块", "verbatim": "规则配置模块"},
            ],
            "spec_sites": [{"section": "发明内容", "anchor": "预先配置规则"}], "drawing_sites": [],
            "flow": {"action_phase": "preconfigured", "input_objects": ["规则参数"], "processing_actor": "规则配置模块", "action": "配置", "output_objects": ["规则"], "downstream_feature_ids": ["F002"], "exception_path_ids": []},
        },
        {
            "feature_id": "F002", "name": "读取输入数据", "statement": "读取输入数据", "classification": "distinguishing",
            "prior_art_status": {"verdict": "not_found_in_searched_outlets"}, "technical_effect": "取得待处理数据",
            "evidence": [{"source": "交底书", "locator": "2"}],
            "claim_sites": [
                {"claim_number": 1, "part": "characterizing", "claim_type": "method", "execution_role": "runtime_step", "verbatim": "读取输入数据"},
                {"claim_number": 9, "part": "characterizing", "claim_type": "system", "execution_role": "module", "actor": "数据处理模块", "verbatim": "数据处理模块"},
            ],
            "spec_sites": [{"section": "发明内容", "anchor": "读取输入数据"}], "drawing_sites": [],
            "flow": {"action_phase": "runtime_input", "input_objects": ["输入源"], "processing_actor": "数据处理模块", "action": "读取", "output_objects": ["输入数据"], "downstream_feature_ids": ["F003"], "exception_path_ids": ["E001"]},
        },
        {
            "feature_id": "F003", "name": "输出结果", "statement": "输出结果", "classification": "distinguishing",
            "prior_art_status": {"verdict": "not_found_in_searched_outlets"}, "technical_effect": "形成可追溯结果",
            "evidence": [{"source": "交底书", "locator": "3"}],
            "claim_sites": [
                {"claim_number": 1, "part": "characterizing", "claim_type": "method", "execution_role": "result", "verbatim": "输出结果"},
                {"claim_number": 9, "part": "characterizing", "claim_type": "system", "execution_role": "storage", "actor": "结果存储模块", "verbatim": "结果存储模块"},
            ],
            "spec_sites": [{"section": "发明内容", "anchor": "输出结果"}], "drawing_sites": [],
            "flow": {"action_phase": "runtime_output", "input_objects": ["输入数据"], "processing_actor": "结果存储模块", "action": "输出并存储", "output_objects": ["结果"], "downstream_feature_ids": [], "exception_path_ids": []},
        },
    ]
    write_json(ledger, {
        "schema_id": "cn-patent-feature-ledger/v2", "case_id": "case", "generated_at": "2026-09-01", "legal_effect": "ADVISORY_ONLY",
        "closest_prior_art": [], "search_status": {"cnipa_manual_search": "completed", "statement": "已完成"}, "features": features,
        "claim_data_flows": [
            {"claim_number": 1, "claim_type": "method", "entry_feature_ids": ["F001"], "ordered_feature_ids": ["F001", "F002", "F003"], "merge_feature_ids": [], "normal_exit_feature_ids": ["F003"], "exception_path_ids": ["E001"], "storage_feature_ids": ["F003"]},
            {"claim_number": 9, "claim_type": "system", "entry_feature_ids": ["F001"], "ordered_feature_ids": ["F001", "F002", "F003"], "merge_feature_ids": [], "normal_exit_feature_ids": ["F003"], "exception_path_ids": ["E001"], "storage_feature_ids": ["F003"]},
        ],
        "method_system_pairs": [{"method_claim_number": 1, "system_claim_number": 9, "required_feature_ids": ["F001", "F002", "F003"]}],
        "exception_paths": [{"path_id": "E001", "trigger": "输入数据不完整", "action_feature_ids": ["F003"], "produces_value": True, "confidence": "low", "terminal_state": "低置信度完成", "reason_code": "INPUT_INCOMPLETE", "stored_fields": ["结果值", "置信度", "状态", "原因码"], "claim_sites": [{"claim_number": 1, "anchor": "低置信度完成状态及原因码"}, {"claim_number": 9, "anchor": "低置信度完成状态及原因码"}], "spec_sites": [{"section": "具体实施方式", "anchor": "低置信度完成状态及原因码"}], "drawing_relation_ids": []}],
    })
    return ledger, claims, specification, output


def run(ledger: Path, claims: Path, specification: Path, output: Path):
    return subprocess.run([sys.executable, str(SCRIPT), "--ledger", str(ledger), "--claims", str(claims), "--specification", str(specification), "--output", str(output)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)


def test_v2_data_flow_and_exception_closure_pass(tmp_path):
    ledger, claims, specification, output = fixture(tmp_path)
    result = run(ledger, claims, specification, output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_id"] == "cn-patent-feature-ledger-report/v2"
    assert report["counts"]["deterministic_fail"] == 0
    assert report["input_artifacts"]


def test_v2_missing_system_feature_is_blocked(tmp_path):
    ledger, claims, specification, output = fixture(tmp_path)
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["features"][1]["claim_sites"] = [payload["features"][1]["claim_sites"][0]]
    write_json(ledger, payload)
    result = run(ledger, claims, specification, output)
    assert result.returncode == 2
    codes = {item["rule_id"] for item in json.loads(output.read_text(encoding="utf-8"))["findings"]}
    assert "CN-LEDGER-PAIR-005" in codes


def test_v2_value_producing_exception_requires_confidence(tmp_path):
    ledger, claims, specification, output = fixture(tmp_path)
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["exception_paths"][0]["confidence"] = "unknown"
    write_json(ledger, payload)
    result = run(ledger, claims, specification, output)
    assert result.returncode == 2
    codes = {item["rule_id"] for item in json.loads(output.read_text(encoding="utf-8"))["findings"]}
    assert "CN-LEDGER-EXCEPTION-004" in codes


# ---------------------------------------------------------------------------
# 辅助：最小 v1 台账 fixture，只传入 features 列表即可，绕开 v2 relations 检查
# ---------------------------------------------------------------------------

def _make_minimal_ledger(tmp_path: Path, features: list[dict]) -> tuple[Path, Path, Path, Path]:
    """构造包含 features 的最小 v1 台账，权利要求和说明书与 features 匹配。"""
    claims_path = tmp_path / "权利要求书.md"
    spec_path = tmp_path / "说明书.md"
    ledger_path = tmp_path / "feature-ledger.json"
    output_path = tmp_path / "feature-ledger-report.json"

    # 从 features 中收集所有出现在权利要求里的 verbatim 和 name，拼成权利要求正文
    claim1_parts = []
    spec_anchors = []
    for feat in features:
        for site in feat.get("claim_sites") or []:
            if site.get("claim_number") == 1 and site.get("verbatim"):
                claim1_parts.append(site["verbatim"])
        spec_anchors.append(feat["name"])
        for ss in feat.get("spec_sites") or []:
            if ss.get("anchor"):
                spec_anchors.append(ss["anchor"])

    claim1_body = "，".join(claim1_parts) if claim1_parts else "通用处理步骤"
    spec_body = "，".join(spec_anchors)

    claims_path.write_text(
        f"# 权利要求书\n\n1. 一种方法，其特征在于：{claim1_body}。\n",
        encoding="utf-8",
    )
    spec_path.write_text(
        f"# 示例\n\n## 技术领域\n\n{spec_body}。\n\n## 背景技术\n\n现有技术。\n\n"
        f"## 发明内容\n\n{spec_body}。\n\n## 附图说明\n\n无。\n\n"
        f"## 具体实施方式\n\n{spec_body}。\n",
        encoding="utf-8",
    )
    write_json(ledger_path, {
        "schema_id": "cn-patent-feature-ledger/v1",
        "case_id": "test",
        "generated_at": "2026-09-01",
        "legal_effect": "ADVISORY_ONLY",
        "closest_prior_art": [],
        "search_status": {"cnipa_manual_search": "completed", "statement": "已完成"},
        "features": features,
    })
    return ledger_path, claims_path, spec_path, output_path


def _feat(fid: str, name: str, statement: str, classification: str = "distinguishing",
          verdict: str | None = "not_found_in_searched_outlets") -> dict:
    """构造一个最小特征条目，claim_sites verbatim 与 name 相同。"""
    prior = {"verdict": verdict} if verdict is not None else {}
    return {
        "feature_id": fid,
        "name": name,
        "statement": statement,
        "classification": classification,
        "prior_art_status": prior,
        "technical_effect": "测试技术效果",
        "evidence": [{"source": "测试", "locator": "1"}],
        "claim_sites": (
            []
            if classification == "fallback_only"
            else [{"claim_number": 1,
                   "part": "preamble" if classification == "preamble" else "characterizing",
                   "claim_type": "method",
                   "execution_role": "runtime_step", "verbatim": name}]
        ),
        "spec_sites": [{"section": "发明内容", "anchor": name}],
        "drawing_sites": [],
    }


# ---------------------------------------------------------------------------
# 任务 1：PRIOR-002 升级为 fail 的断言
# ---------------------------------------------------------------------------

def test_prior_002_no_verdict_is_review_and_pending(tmp_path):
    """distinguishing 特征 prior_art_status 缺 verdict → PRIOR-002 REVIEW_REQUIRED + pending。"""
    feat = _feat("F001", "无verdict特征", "无verdict特征", verdict=None)
    ledger, claims, spec, output = _make_minimal_ledger(tmp_path, [feat])
    result = run(ledger, claims, spec, output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    findings = report["findings"]
    matched = [f for f in findings if f["rule_id"] == "CN-LEDGER-PRIOR-002"]
    assert matched, "应有 CN-LEDGER-PRIOR-002 finding"
    assert matched[0]["status"] == "REVIEW_REQUIRED"

    pending = report.get("pending_decisions", [])
    assert any(p["key"] == "ledger.prior_art_verdict_missing" for p in pending)


def test_prior_002_not_searched_is_review_and_pending(tmp_path):
    """verdict=not_searched → PRIOR-002 REVIEW_REQUIRED + pending。"""
    feat = _feat("F001", "未检索特征", "未检索特征", verdict="not_searched")
    ledger, claims, spec, output = _make_minimal_ledger(tmp_path, [feat])
    result = run(ledger, claims, spec, output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    findings = report["findings"]
    codes = {f["rule_id"]: f["status"] for f in findings}
    assert codes.get("CN-LEDGER-PRIOR-002") == "REVIEW_REQUIRED"

    pending = report.get("pending_decisions", [])
    assert any(p["key"] == "ledger.prior_art_verdict_missing" for p in pending)


# ---------------------------------------------------------------------------
# 任务 2：CN-LEDGER-ABSTRACT-001 触发与豁免
# ---------------------------------------------------------------------------

def test_abstract_001_bare_name_triggers_review(tmp_path):
    """只含名称（"缓存模块""回流阀""状态机"）的 distinguishing 特征 → 各触发 ABSTRACT-001 review。"""
    feats = [
        _feat("F001", "缓存模块", "缓存模块"),
        _feat("F002", "回流阀", "回流阀"),
        _feat("F003", "状态机", "状态机"),
    ]
    ledger, claims, spec, output = _make_minimal_ledger(tmp_path, feats)
    result = run(ledger, claims, spec, output)
    findings = json.loads(output.read_text(encoding="utf-8"))["findings"]
    abstract_targets = {f["target_id"] for f in findings if f["rule_id"] == "CN-LEDGER-ABSTRACT-001"}
    assert "F001" in abstract_targets
    assert "F002" in abstract_targets
    assert "F003" in abstract_targets


def test_abstract_001_qualified_statements_no_trigger(tmp_path):
    """含限定成分的 statement → 不触发 ABSTRACT-001。"""
    qualified = [
        "仅在冷却液温度回落至阈值以下后才开启回流阀",
        "弹簧预紧量由相邻凸轮的最大升程决定",
        "组分A与B的质量比处于1:2至1:3",
        "所述请求标识与所述会话标识和所述设备标识绑定",
    ]
    feats = [_feat(f"F{i+1:03d}", stmt[:4], stmt) for i, stmt in enumerate(qualified)]
    ledger, claims, spec, output = _make_minimal_ledger(tmp_path, feats)
    result = run(ledger, claims, spec, output)
    findings = json.loads(output.read_text(encoding="utf-8"))["findings"]
    abstract_fids = {f["target_id"] for f in findings if f["rule_id"] == "CN-LEDGER-ABSTRACT-001"}
    assert not abstract_fids, f"含限定成分的特征不应触发 ABSTRACT-001，实际触发：{abstract_fids}"


def test_abstract_001_preamble_and_fallback_not_triggered(tmp_path):
    """preamble 和 fallback_only 特征即使只有名称也不触发 ABSTRACT-001。"""
    feats = [
        _feat("F001", "缓存模块", "缓存模块", classification="preamble"),
        _feat("F002", "状态机", "状态机", classification="fallback_only"),
        # 至少需要一个 distinguishing 特征以通过 CN-LEDGER-CLASS-003
        _feat("F003", "处理步骤", "处理步骤"),
    ]
    ledger, claims, spec, output = _make_minimal_ledger(tmp_path, feats)
    result = run(ledger, claims, spec, output)
    findings = json.loads(output.read_text(encoding="utf-8"))["findings"]
    abstract_targets = {f["target_id"] for f in findings if f["rule_id"] == "CN-LEDGER-ABSTRACT-001"}
    assert "F001" not in abstract_targets, "preamble 特征不应触发 ABSTRACT-001"
    assert "F002" not in abstract_targets, "fallback_only 特征不应触发 ABSTRACT-001"
