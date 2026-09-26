#!/usr/bin/env python3
"""中国发明专利综合审查 bundle 的 CN v2 独立验证器。

验证器不信任 bundle 自报的任何值：哈希、规范一致性、状态组合、41 维覆盖、
finding 守恒、搜索证据边界和资源上限全部从磁盘原字节独立复算。

三条硬边界：

1. 处置状态只能由验证器派生；生产者自报的总体结论一律拒绝。
2. 存在规范、工具或资源错误时不存在申请处置，也不得把工具故障写成中国专利法结论。
3. `review-summary.md` 只能从通过结构验证的验证结果机械渲染，不接受自由撰写。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
TOOL_ID = "cn-patent-reviewer-verifier"
TOOL_VERSION = "2.0.0"
PREPARE_MANIFEST_SCHEMA = "cn-patent-review-prepare-manifest/v2"
REVIEW_TYPES = ("claims", "specification", "formalities")

EXIT_OK = 0
EXIT_BLOCKING = 2
EXIT_VERIFICATION_FAILED = 3
EXIT_RESOURCE_ERROR = 4

CONTRACT_ERROR = "CONTRACT_ERROR"
TOOL_ERROR = "TOOL_ERROR"
RESOURCE_ERROR = "RESOURCE_ERROR"

# 验证器自身的规则 ID。工具与规范故障使用这些 ID，绝不伪造中国专利法条款引用。
VERIFIER_RULES = {
    "binding": "CN-VERIFY-BINDING-001",
    "contract": "CN-VERIFY-CONTRACT-001",
    "conservation": "CN-VERIFY-CONSERVATION-001",
    "coverage": "CN-VERIFY-COVERAGE-001",
    "search": "CN-VERIFY-SEARCH-001",
    "resource": "CN-VERIFY-RESOURCE-001",
    "input": "CN-VERIFY-INPUT-001",
}

DISPOSITION_TEXT = {
    "NOT_ASSESSED": "全部维度均未评估。",
    "BLOCKING_ISSUE_FOUND": "存在阻断级问题。",
    "REVIEW_INCOMPLETE": "审查未完成：存在未决结论、证据缺口或证据不足。",
    "REMEDIATION_REQUIRED": "存在需整改的非阻断问题。",
    "NO_BLOCKING_ISSUE_FOUND_IN_SCOPE": "在本轮已界定范围内未发现阻断问题。",
}


class ResourceLimitError(Exception):
    """资源越限；统一退出码 4，不得转换为法律 finding。"""


class VerificationInputError(Exception):
    """验证器无法读取或解析必需工件；属于工具错误。"""


def load_module(name: str, path: Path):
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise VerificationInputError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cn_contract = load_module("cn_contract", SCRIPT_DIR / "cn_contract.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def collection_digest(items: list[dict[str, Any]]) -> str:
    if not isinstance(items, list):
        raise VerificationInputError("工件集合必须是数组")
    material: list[tuple[str, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise VerificationInputError(f"工件集合[{index}] 必须是对象")
        artifact_id = item.get("artifact_id")
        digest = item.get("sha256")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise VerificationInputError(
                f"工件集合[{index}].artifact_id 必须是非空字符串"
            )
        if not isinstance(digest, str) or not digest:
            raise VerificationInputError(
                f"工件集合[{index}].sha256 必须是非空字符串"
            )
        material.append((artifact_id, digest))
    material.sort()
    return sha256_bytes(canonical_json(material))


def evidence_digest(report: dict[str, Any]) -> str:
    """与编排器一致：证据绑定只覆盖证据内容，排除运行遥测。"""

    return sha256_bytes(canonical_json({
        key: value for key, value in report.items() if key != "resource_usage"
    }))


class Verifier:
    """一次验证运行的状态；错误按种类累积，不在中途抛出法律结论。"""

    def __init__(self, contract) -> None:
        self.contract = contract
        self.errors: list[dict[str, str]] = []
        self.referenced_bytes = 0
        self.started = time.monotonic()

    def error(self, kind: str, rule_key: str, message: str) -> None:
        if kind not in self.contract.data["enums"]["verification_error_kind"]:
            raise VerificationInputError(f"未知的验证错误种类：{kind}")
        self.errors.append({"kind": kind, "rule_id": VERIFIER_RULES[rule_key], "message": message})

    def read_bytes(self, path: Path, label: str) -> bytes:
        """有界读取被引用工件，并累计验证器引用的总字节数。"""

        limits = self.contract.limits
        if not path.is_file():
            raise VerificationInputError(f"{label} 不存在：{path}")
        size = path.stat().st_size
        if size > limits["verifier_max_single_artifact_bytes"]:
            raise ResourceLimitError(f"{label} 超过单工件字节上限")
        self.referenced_bytes += size
        if self.referenced_bytes > limits["verifier_referenced_bytes"]:
            raise ResourceLimitError("验证器引用的总字节数超过上限")
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise VerificationInputError(f"{label} 必须是 UTF-8 无 BOM")
        return raw

    def read_json(self, path: Path, label: str) -> Any:
        raw = self.read_bytes(path, label)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationInputError(f"{label} 不是合法 UTF-8 JSON：{exc}") from exc

    def guard_deadline(self) -> None:
        if time.monotonic() - self.started > self.contract.limits["orchestration_deadline_seconds"]:
            raise ResourceLimitError("验证超过编排时限")


def recompute_binding(
    verifier: Verifier, bundle: dict[str, Any], checker_identities: list[dict[str, Any]],
    raw_reports: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """从磁盘原字节独立复算证据绑定，而不是采信 bundle 自报的哈希。"""

    limits = verifier.contract.limits
    input_artifacts = bundle["input_artifacts"]
    provenance_artifacts = bundle.get("provenance_artifacts", [])
    rule_sources = bundle["rule_sources"]
    if not isinstance(input_artifacts, list):
        raise VerificationInputError("input_artifacts 必须是数组")
    if not isinstance(rule_sources, list):
        raise VerificationInputError("rule_sources 必须是数组")
    if len(input_artifacts) > limits["verifier_max_artifacts"]:
        raise ResourceLimitError("输入 artifact 数超过验证器上限")
    if not isinstance(provenance_artifacts, list):
        raise VerificationInputError("provenance_artifacts 必须是数组")
    if len(provenance_artifacts) > limits.get("provenance_max_artifacts", limits["verifier_max_artifacts"]):
        raise ResourceLimitError("provenance artifact 数超过验证器上限")
    if len(input_artifacts) + len(provenance_artifacts) > limits["verifier_max_artifacts"]:
        raise ResourceLimitError("输入与 provenance artifact 总数超过验证器上限")
    if len(rule_sources) > limits["verifier_max_rule_sources"]:
        raise ResourceLimitError("规则来源数超过验证器上限")

    # provenance 工件必须位于 prepare-input 所在目录之下，防止通过篡改 manifest
    # 把审查链绑定到工作区之外的任意文件。
    prepare_input = next(
        (item for item in input_artifacts if isinstance(item, dict) and item.get("artifact_id") == "prepare-input"),
        None,
    )
    provenance_base: Path | None = None
    if provenance_artifacts:
        if not isinstance(prepare_input, dict) or not isinstance(prepare_input.get("path"), str):
            raise VerificationInputError("provenance_artifacts 存在时必须有 prepare-input 工件")
        provenance_base = Path(prepare_input["path"]).resolve().parent

    for label, artifacts in (("输入", input_artifacts), ("provenance", provenance_artifacts), ("规则", rule_sources)):
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                raise VerificationInputError(f"{label}工件[{index}] 必须是对象")
            artifact_id = artifact.get("artifact_id")
            path_value = artifact.get("path")
            expected_sha = artifact.get("sha256")
            expected_length = artifact.get("byte_length")
            if not isinstance(artifact_id, str) or not artifact_id:
                raise VerificationInputError(f"{label}工件[{index}] 缺少有效 artifact_id")
            if not isinstance(path_value, str) or not path_value:
                raise VerificationInputError(f"{label}工件 {artifact_id} 缺少有效 path")
            if not isinstance(expected_sha, str) or not expected_sha:
                raise VerificationInputError(f"{label}工件 {artifact_id} 缺少有效 sha256")
            if not isinstance(expected_length, int) or expected_length < 0:
                raise VerificationInputError(f"{label}工件 {artifact_id} 缺少有效 byte_length")
            path = Path(path_value)
            if label == "provenance" and provenance_base is not None:
                try:
                    path.resolve().relative_to(provenance_base)
                except ValueError:
                    verifier.error(
                        CONTRACT_ERROR, "binding",
                        f"provenance 工件 {artifact_id} 越出 prepare 输入目录",
                    )
                    continue
            try:
                raw = verifier.read_bytes(path, f"{label}工件 {artifact_id}")
            except VerificationInputError as exc:
                verifier.error(TOOL_ERROR, "binding", str(exc))
                continue
            if sha256_bytes(raw) != expected_sha:
                verifier.error(
                    CONTRACT_ERROR, "binding",
                    f"{label}工件 {artifact_id} 的实际字节哈希与声明不一致，证据已陈旧",
                )
            elif len(raw) != expected_length:
                verifier.error(
                    CONTRACT_ERROR, "binding",
                    f"{label}工件 {artifact_id} 的字节长度与声明不一致",
                )

    if not isinstance(checker_identities, list):
        raise VerificationInputError("checker_identities 必须是数组")
    tool_set: list[tuple[str, str]] = []
    for index, item in enumerate(checker_identities):
        if not isinstance(item, dict) or not isinstance(item.get("tool_id"), str) \
                or not isinstance(item.get("tool_sha256"), str):
            raise VerificationInputError(f"checker_identities[{index}] 缺少有效 tool_id/tool_sha256")
        tool_set.append((item["tool_id"], item["tool_sha256"]))
    bundle_tool = bundle.get("tool_identity")
    if not isinstance(bundle_tool, dict) or not isinstance(bundle_tool.get("tool_id"), str) \
            or not isinstance(bundle_tool.get("tool_sha256"), str):
        raise VerificationInputError("bundle.tool_identity 缺少有效 tool_id/tool_sha256")
    tool_set.append((bundle_tool["tool_id"], bundle_tool["tool_sha256"]))
    tool_set.sort()
    return {
        "input_set_sha256": collection_digest(input_artifacts),
        **({"provenance_set_sha256": collection_digest(provenance_artifacts)}
           if "provenance_artifacts" in bundle else {}),
        "rule_set_sha256": collection_digest(rule_sources),
        "tool_set_sha256": sha256_bytes(canonical_json(tool_set)),
        "raw_report_set_sha256": collection_digest([
            {"artifact_id": f"raw-{review_type}", "sha256": evidence_digest(report)}
            for review_type, report in sorted(raw_reports.items())
        ]),
    }


def check_search_evidence_boundary(verifier: Verifier, bundle: dict[str, Any]) -> None:
    """搜索清单只是只读消费品，不能把新颖性、创造性升级为已成立。"""

    compatibility = verifier.contract.data["search_manifest_compatibility"]
    declared_artifacts = {
        item["artifact_id"]
        for collection in (
            bundle.get("input_artifacts", []),
            bundle.get("provenance_artifacts", []),
        )
        for item in collection
        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
    }
    for dimension_id in compatibility["required_incomplete_results"]:
        assessment = next((item for item in bundle["assessments"] if item["rule_id"] == dimension_id), None)
        if assessment is None:
            verifier.error(CONTRACT_ERROR, "search", f"缺少维度 {dimension_id} 的评估")
            continue
        mode = assessment["evidence"]["mode"]
        if assessment["result"] != "INCONCLUSIVE" and mode != "PRIOR_ART_COMPARISON":
            verifier.error(
                CONTRACT_ERROR, "search",
                f"维度 {dimension_id} 未使用逐项现有技术比对证据却给出了 {assessment['result']}；"
                f"搜索清单的结构有效性不证明该维度成立",
            )
        if mode == "PRIOR_ART_COMPARISON":
            artifact_ids = assessment["evidence"]["artifact_ids"]
            if not artifact_ids:
                verifier.error(
                    CONTRACT_ERROR, "search",
                    f"维度 {dimension_id} 声称已完成现有技术比对，但未绑定任何证据工件",
                )
            for artifact_id in artifact_ids:
                if artifact_id not in declared_artifacts:
                    verifier.error(
                        CONTRACT_ERROR, "search",
                        f"维度 {dimension_id} 的比对证据指向未声明的工件 {artifact_id}",
                    )


def build_coverage_summary(contract, bundle: dict[str, Any]) -> dict[str, Any]:
    assessments = {item["rule_id"]: item for item in bundle["assessments"]}
    not_assessed = sorted(key for key, item in assessments.items() if item["coverage"] == "NONE")
    blocking = sorted(
        key for key, item in assessments.items()
        if item["result"] == "ISSUE_FOUND" and item["severity"] == "BLOCKER"
    )
    return {
        "dimension_count": len(contract.dimension_ids),
        "assessed_dimension_count": len(assessments) - len(not_assessed),
        "not_assessed_dimension_ids": not_assessed,
        "conditional_dimension_ids": sorted(contract.dimensions_in_group("conditional_special_domain")),
        "blocking_dimension_ids": blocking,
    }


def verify(verifier: Verifier, workspace: Path, bundle_path: Path) -> dict[str, Any]:
    contract = verifier.contract
    limits = contract.limits

    manifest = verifier.read_json(workspace / "prepare-manifest.json", "prepare 清单")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != PREPARE_MANIFEST_SCHEMA:
        raise VerificationInputError(f"prepare 清单 schema_version 必须为 {PREPARE_MANIFEST_SCHEMA}")
    bundle = verifier.read_json(bundle_path, "bundle")
    if not isinstance(bundle, dict):
        raise VerificationInputError("bundle 顶层必须是对象")

    # provenance 声明必须从 prepare manifest 原样传递到 bundle；只改 bundle 自报
    # 的列表或只改 manifest 都应被独立验证器捕获。
    manifest_has_provenance = "provenance_artifacts" in manifest
    bundle_has_provenance = "provenance_artifacts" in bundle
    if manifest_has_provenance != bundle_has_provenance:
        verifier.error(
            CONTRACT_ERROR, "binding",
            "prepare 清单与 bundle 的 provenance_artifacts 出现状态不一致",
        )
    elif manifest_has_provenance and manifest.get("provenance_artifacts") != bundle.get("provenance_artifacts"):
        verifier.error(
            CONTRACT_ERROR, "binding",
            "bundle 的 provenance_artifacts 与 prepare 清单不一致",
        )
    manifest_binding = manifest.get("evidence_binding", {})
    bundle_binding = bundle.get("evidence_binding", {})
    if not isinstance(manifest_binding, dict):
        verifier.error(CONTRACT_ERROR, "binding", "prepare 清单的 evidence_binding 必须是对象")
        manifest_binding = {}
    if not isinstance(bundle_binding, dict):
        verifier.error(CONTRACT_ERROR, "binding", "bundle 的 evidence_binding 必须是对象")
        bundle_binding = {}
    if isinstance(manifest_binding, dict) and isinstance(bundle_binding, dict):
        if ("provenance_set_sha256" in manifest_binding) != ("provenance_set_sha256" in bundle_binding):
            verifier.error(
                CONTRACT_ERROR, "binding",
                "prepare 清单与 bundle 的 provenance_set_sha256 出现状态不一致",
            )
        elif manifest_binding.get("provenance_set_sha256") != bundle_binding.get("provenance_set_sha256") \
                and ("provenance_set_sha256" in manifest_binding or "provenance_set_sha256" in bundle_binding):
            verifier.error(
                CONTRACT_ERROR, "binding",
                "bundle 的 provenance_set_sha256 与 prepare 清单不一致",
            )

    declared = manifest.get("raw_reports", {})
    if not isinstance(declared, dict) or sorted(declared) != sorted(REVIEW_TYPES):
        raise VerificationInputError(f"prepare 清单必须声明 {sorted(REVIEW_TYPES)} 三份原始报告")
    if len(declared) > limits["verifier_max_raw_reports"]:
        raise ResourceLimitError("原始报告数超过验证器上限")

    raw_payloads: dict[str, bytes] = {}
    raw_reports: dict[str, dict[str, Any]] = {}
    for review_type, entry in sorted(declared.items()):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            verifier.error(TOOL_ERROR, "input", f"{review_type} 原始报告条目缺少有效 path")
            continue
        path = (workspace / entry["path"]).resolve()
        payload = verifier.read_bytes(path, f"{review_type} 原始报告")
        raw_payloads[review_type] = payload
        if sha256_bytes(payload) != entry["sha256"]:
            verifier.error(
                CONTRACT_ERROR, "binding",
                f"{review_type} 原始报告字节与 prepare 冻结值不一致，下游证据已陈旧",
            )
        try:
            report = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            verifier.error(TOOL_ERROR, "input", f"{review_type} 原始报告无法解析：{exc}")
            continue
        raw_reports[review_type] = report
        for problem in contract.validate_raw_report(report, f"raw:{review_type}"):
            verifier.error(CONTRACT_ERROR, "contract", problem)
        verifier.guard_deadline()

    try:
        bundle_problems = contract.validate_bundle(bundle)
    except (KeyError, TypeError, ValueError) as exc:
        bundle_problems = [f"bundle 结构无法校验：{exc}"]
    for problem in bundle_problems:
        verifier.error(CONTRACT_ERROR, "contract", problem)

    structurally_valid = not verifier.errors
    # 守恒检查始终执行：结构问题不应掩盖"原始 finding 在下游丢失"这类独立缺陷。
    try:
        conservation_problems = contract.check_finding_conservation(raw_reports, bundle)
    except (KeyError, TypeError, ValueError) as exc:
        conservation_problems = [f"守恒检查无法执行：{exc}"]
    for problem in conservation_problems:
        verifier.error(CONTRACT_ERROR, "conservation", problem)
    if isinstance(bundle.get("assessments"), list) and isinstance(bundle.get("input_artifacts"), list):
        try:
            check_search_evidence_boundary(verifier, bundle)
        except (KeyError, TypeError, ValueError) as exc:
            verifier.error(CONTRACT_ERROR, "search", f"搜索证据边界无法检查：{exc}")

    recomputed: dict[str, str] = {
        "input_set_sha256": "", "rule_set_sha256": "", "tool_set_sha256": "", "raw_report_set_sha256": "",
    }
    if isinstance(bundle.get("input_artifacts"), list) and isinstance(bundle.get("rule_sources"), list) \
            and isinstance(bundle.get("tool_identity"), dict):
        try:
            recomputed = recompute_binding(
                verifier, bundle, manifest.get("checker_identities", []), raw_reports
            )
        except ResourceLimitError:
            raise
        except (VerificationInputError, KeyError, TypeError, ValueError) as exc:
            verifier.error(CONTRACT_ERROR, "binding", f"证据绑定无法独立复算：{exc}")
        else:
            for key, value in sorted(recomputed.items()):
                if bundle_binding.get(key) != value:
                    verifier.error(
                        CONTRACT_ERROR, "binding",
                        f"证据绑定 {key} 独立复算为 {value}，"
                        f"与 bundle 声明的 {bundle_binding.get(key)} 不一致",
                    )
    if bundle.get("prepare_id") != manifest.get("prepare_id"):
        verifier.error(CONTRACT_ERROR, "binding", "bundle 绑定的 prepare_id 与冻结清单不一致")

    coverage = (
        build_coverage_summary(contract, bundle)
        if structurally_valid
        else {
            "dimension_count": len(contract.dimension_ids),
            "assessed_dimension_count": 0,
            "not_assessed_dimension_ids": sorted(contract.dimension_ids),
            "conditional_dimension_ids": sorted(contract.dimensions_in_group("conditional_special_domain")),
            "blocking_dimension_ids": [],
        }
    )
    conservation = {
        "raw_finding_count": sum(len(item.get("findings", [])) for item in raw_reports.values()),
        "raw_gap_count": sum(len(item.get("gaps", [])) for item in raw_reports.values()),
        "downstream_finding_count": sum(len(item.get("findings", [])) for item in bundle.get("subreports", [])),
        "downstream_gap_count": sum(len(item.get("gaps", [])) for item in bundle.get("subreports", [])),
        "semantic_gap_count": len(bundle.get("semantic_gaps", [])),
    }

    aggregate: dict[str, Any] = {
        "child_ids": [], "present_results": [], "result": "INCONCLUSIVE",
        "coverage": "NONE", "severity": "NONE", "finding_ids": [], "gap_ids": [],
    }
    disposition = None
    if not verifier.errors:
        aggregate = contract.aggregate(bundle["assessments"])
        disposition = contract.derive_disposition(bundle["assessments"], verifier.errors)

    verification = {
        "schema_version": contract.schema_ids["verifier_output"],
        "jurisdiction": contract.data["jurisdiction"],
        "legal_effect": contract.data["legal_effect"],
        "verification_id": f"V-{sha256_bytes(canonical_json([bundle.get('bundle_id'), verifier.errors]))[:20]}",
        "bundle_id": bundle.get("bundle_id", ""),
        "prepare_id": manifest.get("prepare_id", ""),
        "recomputed_binding": recomputed,
        "errors": verifier.errors,
        "coverage_summary": coverage,
        "conservation_summary": conservation,
        "aggregate": aggregate,
        "disposition": disposition,
        "resource_usage": {
            "input_bytes_total": verifier.referenced_bytes,
            "output_bytes": 0,
            "finding_count": conservation["downstream_finding_count"],
            "gap_count": conservation["downstream_gap_count"] + conservation["semantic_gap_count"],
            "check_count": sum(len(item.get("checks_performed", [])) for item in raw_reports.values()),
            "elapsed_milliseconds": int((time.monotonic() - verifier.started) * 1000),
        },
    }
    problems = contract.validate_verification(verification)
    if problems:
        raise VerificationInputError("验证输出自身不符合规范：" + "；".join(problems[:5]))
    return verification


# --------------------------------------------------------------------------
# 机械渲染
# --------------------------------------------------------------------------

def render_summary(verification: dict[str, Any]) -> str:
    """只从已通过结构验证的验证结果机械渲染；不接受任何自由撰写的结论。"""

    lines: list[str] = [
        "# 中国发明专利审查结果摘要",
        "",
        "> 本摘要由验证器从结构化验证结果机械渲染，不含人工撰写结论。",
        f"> 法律效力：{verification['legal_effect']}（仅供参考，不构成专业法律意见，也不代表官方审查结论）",
        "",
        "## 标识",
        "",
        f"- 验证 ID：`{verification['verification_id']}`",
        f"- bundle ID：`{verification['bundle_id']}`",
        f"- prepare ID：`{verification['prepare_id']}`",
        "",
    ]

    errors = verification["errors"]
    if errors:
        lines += [
            "## 验证未通过",
            "",
            "存在规范、工具或资源错误，本轮不存在申请处置状态。以下条目使用验证器规则 ID，不是中国专利法结论。",
            "",
            "| 种类 | 规则 ID | 说明 |",
            "|---|---|---|",
        ]
        for item in errors[:200]:
            message = item["message"].replace("|", "\\|")
            lines.append(f"| {item['kind']} | `{item['rule_id']}` | {message} |")
        if len(errors) > 200:
            lines.append(f"| — | — | 另有 {len(errors) - 200} 条错误未展开 |")
        lines += ["", f"错误总数：{len(errors)}", ""]
        return "\n".join(lines) + "\n"

    disposition = verification["disposition"]
    coverage = verification["coverage_summary"]
    conservation = verification["conservation_summary"]
    aggregate = verification["aggregate"]
    lines += [
        "## 处置状态",
        "",
        f"- 处置：`{disposition}`",
        f"- 含义：{DISPOSITION_TEXT.get(disposition, '未定义处置状态。')}",
        f"- 聚合结论：`{aggregate['result']}`；聚合覆盖度：`{aggregate['coverage']}`；"
        f"聚合严重度：`{aggregate['severity']}`",
        "",
        "## 维度覆盖",
        "",
        f"- 规范维度总数：{coverage['dimension_count']}",
        f"- 已评估维度数：{coverage['assessed_dimension_count']}",
        f"- 未评估维度数：{len(coverage['not_assessed_dimension_ids'])}",
        f"- 阻断维度数：{len(coverage['blocking_dimension_ids'])}",
        "",
    ]
    if coverage["blocking_dimension_ids"]:
        lines += ["阻断维度：", ""]
        lines += [f"- `{value}`" for value in coverage["blocking_dimension_ids"]]
        lines.append("")
    if coverage["not_assessed_dimension_ids"]:
        lines += ["未评估维度（覆盖度为 NONE，必须由独立语义审查补齐）：", ""]
        lines += [f"- `{value}`" for value in coverage["not_assessed_dimension_ids"]]
        lines.append("")
    lines += ["条件适用维度（必须完成评估、以充分证据确认不适用，或明确记录审查未完成）：", ""]
    lines += [f"- `{value}`" for value in coverage["conditional_dimension_ids"]]
    lines += [
        "",
        "## 证据守恒",
        "",
        "| 项目 | 原始 | 下游 |",
        "|---|---|---|",
        f"| finding | {conservation['raw_finding_count']} | {conservation['downstream_finding_count']} |",
        f"| gap | {conservation['raw_gap_count']} | {conservation['downstream_gap_count']} |",
        f"| 语义缺口 | — | {conservation['semantic_gap_count']} |",
        "",
        "验证器已逐条比较原始报告与专项报告；原始 finding 和 gap 未被丢弃、合并或降级。",
        "",
        "## 边界声明",
        "",
        "- 本结果不代表官方审查结论，也不预测审查结果。",
        "- 未评估维度和证据缺口必须由具备资质的人员独立完成，不得据本摘要替代。",
        "- 搜索清单只作只读消费，其结构有效性不证明新颖性或创造性成立。",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, payload: bytes, protected: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    for candidate in protected:
        if resolved == candidate.resolve() or (
            resolved.exists() and candidate.exists() and os.path.samefile(resolved, candidate)
        ):
            raise VerificationInputError(f"输出路径与证据工件冲突：{candidate}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立验证中国发明专利综合审查 bundle")
    parser.add_argument("--workspace", required=True, type=Path, help="prepare 使用过的工作目录")
    parser.add_argument("--bundle", required=True, type=Path, help="finalize 产出的 bundle")
    parser.add_argument("--output", type=Path, help="验证结果 JSON 输出路径")
    parser.add_argument("--summary", type=Path, help="机械渲染的 review-summary.md 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        contract = cn_contract.load_contract()
        verifier = Verifier(contract)
        verification = verify(verifier, args.workspace.resolve(), args.bundle.resolve())

        payload = json.dumps(verification, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        verification["resource_usage"]["output_bytes"] = len(payload)
        payload = json.dumps(verification, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        if len(payload) > contract.limits["max_report_output_bytes"]:
            raise ResourceLimitError("验证结果输出超过上限")

        protected = [args.bundle.resolve()]
        if args.output is not None:
            write_atomic(args.output.resolve(), payload, protected)
        else:
            sys.stdout.buffer.write(payload)
        if args.summary is not None:
            summary = render_summary(verification).encode("utf-8")
            if len(summary) > contract.limits["max_summary_output_bytes"]:
                raise ResourceLimitError("摘要输出超过上限")
            write_atomic(args.summary.resolve(), summary, protected)

        if verification["errors"]:
            return EXIT_VERIFICATION_FAILED
        return EXIT_BLOCKING if verification["disposition"] == "BLOCKING_ISSUE_FOUND" else EXIT_OK
    except ResourceLimitError as exc:
        print(f"验证资源失败：{exc}", file=sys.stderr)
        return EXIT_RESOURCE_ERROR
    except cn_contract.ContractError as exc:
        print(f"规范错误：{exc}", file=sys.stderr)
        return EXIT_VERIFICATION_FAILED
    except (VerificationInputError, OSError, UnicodeError, json.JSONDecodeError,
            KeyError, TypeError, ValueError, AttributeError) as exc:
        print(f"验证失败：{exc}", file=sys.stderr)
        return EXIT_VERIFICATION_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
