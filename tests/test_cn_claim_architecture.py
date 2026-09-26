"""权利要求架构合同：载体分工、继承拓扑和方法步骤回归。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/cn-patent-application-creator/scripts/validate_claim_architecture.py"
SCHEMA = ROOT / "skills/cn-patent-application-creator/references/claim-architecture-schema-v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value: object) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    claims = tmp_path / "权利要求书.md"
    specification = tmp_path / "说明书.md"
    ledger = tmp_path / "feature-ledger.json"
    contract = tmp_path / "claim-architecture.json"
    write(
        claims,
        "1. 一种时钟系统，包括时钟源和前级模块，所述时钟源用于向所述前级模块提供参考时钟。\n"
        "2. 根据权利要求1所述的时钟系统，其特征在于，还包括设置于所述时钟源与所述前级模块之间的附加模块。\n"
        "8. 一种控制方法，其特征在于，包括以下步骤：\n"
        "S1，获取输入数据；\n"
        "$$a=b$$\n"
        "S2，处理所述输入数据；\n"
        "$$c=d$$\n"
        "S3，输出结果。\n"
        "$$e=f$$\n",
    )
    write(
        specification,
        "步骤S1：获取输入数据。\n"
        "步骤S2：处理所述输入数据。\n"
        "步骤S3：输出结果。\n",
    )
    write_json(ledger, {
        "schema_id": "cn-patent-feature-ledger/v2",
        "features": [
            {
                "feature_id": "F001",
                "name": "附加模块",
                "statement": "插入在时钟源与前级模块之间的中间模块结构",
                "classification": "distinguishing",
                "claim_sites": [
                    {"claim_number": 2, "part": "characterizing", "claim_type": "system", "execution_role": "module", "actor": "附加模块"}
                ],
            }
        ],
    })
    payload = {
        "schema_id": "cn-patent-claim-architecture/v1",
        "case_id": "case",
        "generated_at": "2026-09-03",
        "legal_effect": "ADVISORY_ONLY",
        "source_artifacts": [
            {"artifact_id": "claims", "path": claims.name, "sha256": digest(claims)},
            {"artifact_id": "specification", "path": specification.name, "sha256": digest(specification)},
            {"artifact_id": "feature_ledger", "path": ledger.name, "sha256": digest(ledger)},
        ],
        "independent_claims": [
            {
                "claim_number": 1,
                "claim_type": "system",
                "complexity_metrics": {"formula_block_count": 0, "symbol_definition_count": 0, "execution_phases": []},
                "carrier_allocations": [],
                "conciseness_review": {"status": "approved", "statement": "系统独权仅保留必要结构关系。", "reviewed_at": "2026-09-03"},
            },
            {
                "claim_number": 8,
                "claim_type": "method",
                "complexity_metrics": {
                    "formula_block_count": 3,
                    "symbol_definition_count": 0,
                    "execution_phases": ["runtime_input", "runtime_processing", "runtime_output"],
                },
                "carrier_allocations": [
                    {"content_id": "formula-a", "kind": "formula", "placement": "dependent_claim", "rationale": "独权只保留计算动作。", "source_feature_ids": []},
                    {"content_id": "formula-b", "kind": "formula", "placement": "dependent_claim", "rationale": "具体公式由从权限定。", "source_feature_ids": []},
                    {"content_id": "formula-c", "kind": "formula", "placement": "specification", "rationale": "结果公式在说明书展开。", "source_feature_ids": []},
                ],
                "conciseness_review": {"status": "approved", "statement": "已确认公式载体分工，独权保持必要动作。", "reviewed_at": "2026-09-03"},
            },
        ],
        "topology_nodes": [
            {"node_id": "CLOCK", "label": "时钟源"},
            {"node_id": "EXTRA", "label": "附加模块"},
            {"node_id": "FRONT", "label": "前级模块"},
        ],
        "claim_topologies": [
            {
                "claim_number": 1,
                "parent_claim_numbers": [],
                "declared_relations": [
                    {
                        "relation_id": "R1",
                        "source_node_id": "CLOCK",
                        "target_node_id": "FRONT",
                        "relation_type": "provides",
                        "target_port": "reference_clock",
                        "exclusive_target_port": False,
                        "source_anchor": "时钟源用于向前级模块提供参考时钟",
                    }
                ],
            },
            {
                "claim_number": 2,
                "parent_claim_numbers": [1],
                "declared_relations": [
                    {
                        "relation_id": "R2",
                        "source_node_id": "CLOCK",
                        "target_node_id": "EXTRA",
                        "relation_type": "connects",
                        "target_port": "reference_clock",
                        "exclusive_target_port": True,
                        "source_anchor": "时钟源与附加模块连接",
                    },
                    {
                        "relation_id": "R3",
                        "source_node_id": "EXTRA",
                        "target_node_id": "FRONT",
                        "relation_type": "connects",
                        "target_port": "reference_clock",
                        "exclusive_target_port": True,
                        "source_anchor": "附加模块与前级模块连接",
                    },
                ],
            },
            {"claim_number": 8, "parent_claim_numbers": [], "declared_relations": []},
        ],
        "method_claims": [
            {
                "claim_number": 8,
                "steps": [
                    {"step_id": "S1", "order": 1, "action": "获取输入数据", "specification_anchor": "步骤S1：获取输入数据"},
                    {"step_id": "S2", "order": 2, "action": "处理所述输入数据", "specification_anchor": "步骤S2：处理所述输入数据"},
                    {"step_id": "S3", "order": 3, "action": "输出结果", "specification_anchor": "步骤S3：输出结果"},
                ],
                "decisions": [],
                "loops": [{"from_step_id": "S3", "to_step_id": "S2", "condition": "未完成处理"}],
            }
        ],
        "core_protection_point": {
            "claim_number": 2,
            "parent_claim_number": 1,
            "feature_ids": ["F001"],
            "statement": "特征 F001（附加模块）是本案最核心的区别特征，通过在时钟源与前级模块之间插入附加模块形成新的信号处理架构。",
            "review": {"status": "approved", "statement": "已对标检索结论，确认 F001 不存在于现有技术。", "reviewed_at": "2026-09-03"},
        },
    }
    write_json(contract, payload)
    return contract, claims, specification, tmp_path / "report.json"


def run(contract: Path, claims: Path, specification: Path, output: Path):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--contract", str(contract), "--case-dir", str(contract.parent), "--claims", str(claims), "--specification", str(specification), "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )


def codes(output: Path) -> set[str]:
    return {item["code"] for item in json.loads(output.read_text(encoding="utf-8"))["errors"]}


def test_contract_schema_is_utf8_json():
    raw = SCHEMA.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["$id"] == "cn-patent-claim-architecture/v1"


def test_architecture_contract_passes_and_requires_complexity_review(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    result = run(contract, claims, specification, output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert any(item["code"] == "ARCH-CARRIER-COMPLEXITY" for item in report["review_required"])


def test_pending_conciseness_review_does_not_block(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["independent_claims"][1]["conciseness_review"]["status"] = "pending"
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    keys = [item["key"] for item in report.get("pending_decisions", [])]
    assert "architecture.conciseness_review_pending" in keys


def test_observed_formula_count_cannot_be_understated(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["independent_claims"][1]["complexity_metrics"]["formula_block_count"] = 0
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-CARRIER-METRIC" in codes(output)


def test_inherited_exclusive_port_conflict_is_blocked(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["claim_topologies"][0]["declared_relations"][0]["exclusive_target_port"] = True
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-TOPOLOGY-CONFLICT" in codes(output)


def test_method_step_set_must_match_claim(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["method_claims"][0]["steps"].pop()
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-METHOD-ISOMORPHISM" in codes(output)


def test_loop_must_target_existing_step(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["method_claims"][0]["loops"][0]["to_step_id"] = "S9"
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-METHOD-LOOP" in codes(output)


def test_contract_source_must_match_cli_input(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    other = tmp_path / "other-claims.md"
    write(other, claims.read_text(encoding="utf-8"))
    result = run(contract, other, specification, output)
    assert result.returncode == 2
    assert "ARCH-SOURCE-MISMATCH" in codes(output)

def test_all_independent_claims_must_be_registered(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["independent_claims"].pop()
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-CARRIER-COVERAGE" in codes(output)


def test_every_claim_needs_topology_record(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["claim_topologies"].pop()
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-TOPOLOGY-COVERAGE" in codes(output)


def test_every_claim_with_steps_needs_method_contract(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["method_claims"] = []
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 2
    assert "ARCH-METHOD-COVERAGE" in codes(output)


def test_missing_core_protection_point_fails_shape_check(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    del payload["core_protection_point"]
    write_json(contract, payload)
    assert run(contract, claims, specification, output).returncode == 3


def test_core_protection_point_claim_number_must_be_2(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["core_protection_point"]["claim_number"] = 3
    write_json(contract, payload)
    assert run(contract, claims, specification, output).returncode == 2
    assert "ARCH-CORE-SHAPE" in codes(output)


def test_core_protection_point_claim_2_must_reference_only_claim_1(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    text = claims.read_text(encoding="utf-8").replace(
        "2. 根据权利要求1所述的时钟系统，其特征在于，还包括设置于所述时钟源与所述前级模块之间的附加模块。",
        "2. 另一种时钟系统，包括新的结构。",
    )
    write(claims, text)
    payload["source_artifacts"][0]["sha256"] = digest(claims)
    payload["claim_topologies"][1]["parent_claim_numbers"] = []
    write_json(contract, payload)
    assert run(contract, claims, specification, output).returncode == 2
    assert "ARCH-CORE-CLAIM" in codes(output)


def test_core_protection_point_topology_parent_must_be_claim_1(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["claim_topologies"][1]["parent_claim_numbers"] = [8]
    write_json(contract, payload)
    assert run(contract, claims, specification, output).returncode == 2
    assert "ARCH-CORE-CLAIM" in codes(output)


def test_core_protection_point_feature_must_exist_in_ledger(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["core_protection_point"]["feature_ids"] = ["F999"]
    write_json(contract, payload)
    assert run(contract, claims, specification, output).returncode == 2
    assert "ARCH-CORE-FEATURE" in codes(output)


def _rewrite_ledger(contract: Path, mutate) -> None:
    ledger_path = contract.parent / "feature-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    mutate(ledger)
    write_json(ledger_path, ledger)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["source_artifacts"][2]["sha256"] = digest(ledger_path)
    write_json(contract, payload)


def test_core_protection_point_feature_must_be_distinguishing(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    _rewrite_ledger(contract, lambda ledger: ledger["features"][0].__setitem__("classification", "preamble"))
    assert run(contract, claims, specification, output).returncode == 2
    assert "ARCH-CORE-FEATURE" in codes(output)


def test_core_protection_point_feature_must_be_in_claim_2(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    _rewrite_ledger(contract, lambda ledger: ledger["features"][0]["claim_sites"][0].__setitem__("claim_number", 3))
    assert run(contract, claims, specification, output).returncode == 2
    assert "ARCH-CORE-FEATURE" in codes(output)


def test_core_protection_point_review_does_not_block_when_pending(tmp_path):
    contract, claims, specification, output = fixture(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["core_protection_point"]["review"]["status"] = "pending"
    write_json(contract, payload)
    result = run(contract, claims, specification, output)
    assert result.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    keys = [item["key"] for item in report.get("pending_decisions", [])]
    assert "architecture.core_point_review_pending" in keys
