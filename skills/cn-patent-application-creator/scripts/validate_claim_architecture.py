#!/usr/bin/env python3
"""校验独权载体分工、父从权继承拓扑和方法步骤边界。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from cn_drafting_io import DraftingOutputGuard

SCHEMA_ID = "cn-patent-claim-architecture/v1"
REPORT_SCHEMA_ID = "cn-patent-claim-architecture-validation/v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
STEP_RE = re.compile(r"^S[0-9]+$")
CLAIM_RE = re.compile(r"^\s*([0-9０-９]+)\s*[.．、:：]\s*(.*)$")
REFERENCE_CLAUSE_RE = re.compile(r"(?:根据|按照|如)\s*权利要求(?P<clause>.+?)所述")
STEP_IN_CLAIM_RE = re.compile(r"(?<![A-Za-z0-9])S([0-9]+)(?=\s*[，,:：])")


class ArchitectureError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_utf8(path: Path, label: str) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ArchitectureError(f"{label}含 BOM，必须使用 UTF-8 无 BOM")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchitectureError(f"{label}不是有效 UTF-8：{path}") from exc


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(read_utf8(path, label))
    if not isinstance(value, dict):
        raise ArchitectureError(f"{label}顶层必须是对象")
    return value


def resolve_under(case_dir: Path, raw: str, label: str) -> Path:
    candidate = Path(raw)
    candidate = candidate.resolve() if candidate.is_absolute() else (case_dir / candidate).resolve()
    try:
        candidate.relative_to(case_dir)
    except ValueError as exc:
        raise ArchitectureError(f"{label}必须位于案件目录内：{raw}") from exc
    return candidate


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value)


def parse_claims(text: str) -> dict[int, str]:
    claims: dict[int, list[str]] = {}
    current: int | None = None
    for line in text.splitlines():
        match = CLAIM_RE.match(line)
        if match:
            current = int(match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
            if current in claims:
                raise ArchitectureError(f"权利要求编号重复：{current}")
            claims[current] = [match.group(2).strip()]
        elif current is not None and line.strip():
            claims[current].append(line.strip())
    return {number: "\n".join(lines) for number, lines in claims.items()}


def claim_references(text: str) -> list[int]:
    match = REFERENCE_CLAUSE_RE.search(text)
    if not match:
        return []
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    return sorted({int(value.translate(table)) for value in re.findall(r"[0-9０-９]+", match.group("clause"))})


def observed_formula_blocks(claim_text: str) -> int:
    """保守计算Markdown/纯文本中可明确识别的独立公式块。"""
    fenced = len(re.findall(r"```(?:math|latex)\s*.*?```", claim_text, flags=re.S | re.I))
    without_fenced = re.sub(r"```(?:math|latex)\s*.*?```", "", claim_text, flags=re.S | re.I)
    display = len(re.findall(r"\$\$.*?\$\$", without_fenced, flags=re.S))
    return fenced + display


def observed_symbol_definitions(claim_text: str) -> int:
    """只统计“其中”之后可明确识别的分号分隔“X为……”定义，作为下限。"""
    if "其中" not in claim_text:
        return 0
    tail = claim_text.split("其中", 1)[1]
    clauses = re.split(r"[；;。]", tail)
    return sum(1 for clause in clauses if "为" in clause and clause.strip())


def validate_shape(contract: dict[str, Any]) -> None:
    required = {
        "schema_id", "case_id", "generated_at", "legal_effect", "source_artifacts",
        "independent_claims", "topology_nodes", "claim_topologies", "method_claims",
        "core_protection_point",
    }
    missing = required - set(contract)
    if missing:
        raise ArchitectureError(f"合同缺少字段：{sorted(missing)}")
    if contract.get("schema_id") != SCHEMA_ID:
        raise ArchitectureError(f"schema_id 必须为 {SCHEMA_ID}")
    if contract.get("legal_effect") != "ADVISORY_ONLY":
        raise ArchitectureError("legal_effect 必须为 ADVISORY_ONLY")
    for field in ("case_id", "generated_at"):
        if not isinstance(contract.get(field), str) or not contract[field].strip():
            raise ArchitectureError(f"{field} 必须为非空字符串")
    for field in ("source_artifacts", "independent_claims", "topology_nodes", "claim_topologies", "method_claims"):
        if not isinstance(contract.get(field), list):
            raise ArchitectureError(f"{field} 必须是数组")
    if not isinstance(contract.get("core_protection_point"), dict):
        raise ArchitectureError("core_protection_point 必须是对象")


def validate_contract(
    contract_path: Path, case_dir: Path, claims_path: Path, specification_path: Path,
    *, output_guard: DraftingOutputGuard | None = None,
) -> dict[str, Any]:
    contract = load_json(contract_path, "权利要求架构合同")
    validate_shape(contract)
    if output_guard is not None:
        # 合同是发现间接输入的唯一入口；读取其来源正文/哈希之前先纳入输出隔离。
        for item in contract["source_artifacts"]:
            if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"]:
                output_guard.protect_inputs([resolve_under(case_dir, item["path"], "来源")])
    errors: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    pending_decisions: list[dict[str, Any]] = []

    def error(code: str, target: str, message: str) -> None:
        errors.append({"code": code, "target": target, "message": message})

    def review(code: str, target: str, message: str) -> None:
        reviews.append({"code": code, "target": target, "message": message})

    def pending(decision: dict[str, Any]) -> None:
        pending_decisions.append(decision)

    claims_text = read_utf8(claims_path, "权利要求书")
    specification_text = read_utf8(specification_path, "说明书")
    claims = parse_claims(claims_text)
    if not claims:
        raise ArchitectureError("权利要求书中没有解析到编号权利要求")

    source_ids: set[str] = set()
    source_paths: dict[str, Path] = {}
    bound_sources: list[dict[str, str]] = []
    for index, item in enumerate(contract["source_artifacts"], start=1):
        if not isinstance(item, dict):
            error("ARCH-SOURCE-SHAPE", f"source[{index}]", "来源必须是对象")
            continue
        artifact_id = item.get("artifact_id")
        raw_path = item.get("path")
        digest = item.get("sha256")
        if artifact_id not in {"claims", "specification", "feature_ledger"} or artifact_id in source_ids:
            error("ARCH-SOURCE-SHAPE", f"source[{index}]", "artifact_id非法或重复")
            continue
        source_ids.add(artifact_id)
        if not isinstance(raw_path, str) or not raw_path:
            error("ARCH-SOURCE-SHAPE", str(artifact_id), "path必须是非空字符串")
            continue
        path = resolve_under(case_dir, raw_path, f"来源{artifact_id}")
        if not path.is_file():
            error("ARCH-SOURCE-MISSING", str(artifact_id), f"来源不存在：{raw_path}")
            continue
        actual = sha256(path)
        if not isinstance(digest, str) or not SHA_RE.fullmatch(digest) or digest != actual:
            error("ARCH-SOURCE-STALE", str(artifact_id), "来源SHA-256与当前文件不一致")
        source_paths[str(artifact_id)] = path
        bound_sources.append({"artifact_id": str(artifact_id), "path": str(path), "sha256": actual})
    if source_ids != {"claims", "specification", "feature_ledger"}:
        error("ARCH-SOURCE-SET", "source_artifacts", "必须且只能绑定claims、specification和feature_ledger")
    if source_paths.get("claims") and source_paths["claims"] != claims_path.resolve():
        error("ARCH-SOURCE-MISMATCH", "claims", "合同绑定的claims与命令行输入不是同一文件")
    if source_paths.get("specification") and source_paths["specification"] != specification_path.resolve():
        error("ARCH-SOURCE-MISMATCH", "specification", "合同绑定的specification与命令行输入不是同一文件")

    independent_numbers: set[int] = set()
    for index, item in enumerate(contract["independent_claims"], start=1):
        target = f"independent_claim[{index}]"
        if not isinstance(item, dict):
            error("ARCH-CARRIER-SHAPE", target, "独权记录必须是对象")
            continue
        number = item.get("claim_number")
        if not isinstance(number, int) or isinstance(number, bool) or number in independent_numbers:
            error("ARCH-CARRIER-SHAPE", target, "claim_number必须为唯一正整数")
            continue
        independent_numbers.add(number)
        if number not in claims:
            error("ARCH-CLAIM-MISSING", f"claim{number}", "合同中的独立权利要求不存在")
            continue
        if claim_references(claims[number]):
            error("ARCH-CARRIER-INDEPENDENCE", f"claim{number}", "登记为独权，但权利要求文本包含引用关系")
        metrics = item.get("complexity_metrics")
        if not isinstance(metrics, dict):
            error("ARCH-CARRIER-SHAPE", f"claim{number}", "缺少complexity_metrics")
            continue
        formula_count = metrics.get("formula_block_count")
        symbol_count = metrics.get("symbol_definition_count")
        phases = metrics.get("execution_phases")
        if not isinstance(formula_count, int) or isinstance(formula_count, bool) or formula_count < 0:
            error("ARCH-CARRIER-SHAPE", f"claim{number}", "formula_block_count必须是非负整数")
            formula_count = 0
        if not isinstance(symbol_count, int) or isinstance(symbol_count, bool) or symbol_count < 0:
            error("ARCH-CARRIER-SHAPE", f"claim{number}", "symbol_definition_count必须是非负整数")
            symbol_count = 0
        valid_phases = {"preconfigured", "runtime_input", "runtime_processing", "runtime_output", "postprocessing"}
        if not isinstance(phases, list) or len(set(phases)) != len(phases) or any(phase not in valid_phases for phase in phases):
            error("ARCH-CARRIER-SHAPE", f"claim{number}", "execution_phases必须是合法且不重复的数组")
            phases = []
        observed_formulas = observed_formula_blocks(claims[number])
        observed_symbols = observed_symbol_definitions(claims[number])
        if formula_count < observed_formulas:
            error("ARCH-CARRIER-METRIC", f"claim{number}", f"合同公式块数量{formula_count}小于文本可确认数量{observed_formulas}")
        if symbol_count < observed_symbols:
            error("ARCH-CARRIER-METRIC", f"claim{number}", f"合同符号定义数量{symbol_count}小于文本可确认数量{observed_symbols}")
        allocations = item.get("carrier_allocations")
        if not isinstance(allocations, list):
            error("ARCH-CARRIER-SHAPE", f"claim{number}", "carrier_allocations必须是数组")
            allocations = []
        allocation_ids: set[str] = set()
        allocation_kind_counts = {"formula": 0, "symbol_definition": 0}
        for allocation in allocations:
            if not isinstance(allocation, dict):
                error("ARCH-CARRIER-SHAPE", f"claim{number}", "carrier_allocation必须是对象")
                continue
            content_id = allocation.get("content_id")
            if not isinstance(content_id, str) or not ID_RE.fullmatch(content_id) or content_id in allocation_ids:
                error("ARCH-CARRIER-SHAPE", f"claim{number}", "content_id必须合法且唯一")
            else:
                allocation_ids.add(content_id)
            kind = allocation.get("kind")
            if kind not in {"core_action", "formula", "symbol_definition", "implementation_detail", "control_sequence"}:
                error("ARCH-CARRIER-SHAPE", f"claim{number}", "carrier_allocation.kind非法")
            elif kind in allocation_kind_counts:
                allocation_kind_counts[kind] += 1
            if allocation.get("placement") not in {"independent_claim", "dependent_claim", "specification"}:
                error("ARCH-CARRIER-SHAPE", f"claim{number}", "carrier_allocation.placement非法")
            if not str(allocation.get("rationale", "")).strip():
                error("ARCH-CARRIER-SHAPE", f"claim{number}", "carrier_allocation.rationale不能为空")
            duplicate_claims = allocation.get("duplicate_claim_numbers", [])
            if not isinstance(duplicate_claims, list) or any(not isinstance(value, int) or isinstance(value, bool) or value not in claims for value in duplicate_claims):
                error("ARCH-CARRIER-SHAPE", f"claim{number}", "duplicate_claim_numbers必须引用现有权利要求")
            elif duplicate_claims and allocation.get("placement") == "independent_claim":
                review("ARCH-CARRIER-DUPLICATION", f"claim{number}.{content_id}", f"独权内容同时在权利要求{sorted(duplicate_claims)}重复，需确认是否应下沉")
        if allocation_kind_counts["formula"] < formula_count:
            error("ARCH-CARRIER-ALLOCATION", f"claim{number}", "每个已登记公式块都必须有载体分配记录")
        if allocation_kind_counts["symbol_definition"] < symbol_count:
            error("ARCH-CARRIER-ALLOCATION", f"claim{number}", "每项已登记符号定义都必须有载体分配记录")
        decision = item.get("conciseness_review")
        if not isinstance(decision, dict) or decision.get("status") not in {"pending", "approved", "revise"}:
            error("ARCH-CARRIER-REVIEW", f"claim{number}", "必须提供pending、approved或revise的简要性复核状态")
            continue
        if not str(decision.get("statement", "")).strip() or not str(decision.get("reviewed_at", "")).strip() or decision.get("status") != "approved":
            review("ARCH-CARRIER-REVIEW", f"claim{number}", "简要性复核未批准或缺说明/日期")
            pending({
                "key": "architecture.conciseness_review_pending",
                "source": {"tool_id": "validate_claim_architecture", "rule_id": "ARCH-CARRIER-REVIEW"},
                "target": {"kind": "claim", "locator": f"权利要求{number}"},
                "question": "简要性复核尚未批准或信息不全",
                "adopted_default": "按当前载体分工继续，独权保持现状",
                "options": ["批准当前分工", "调整后重新复核"],
                "impact": ["protection_scope"],
                "decider": "attorney"
            })
        overloaded = formula_count >= 3 or symbol_count >= 5 or len(phases) >= 3
        if overloaded:
            review("ARCH-CARRIER-COMPLEXITY", f"claim{number}", "独权含较多公式、符号定义或执行阶段；已要求人工确认载体分工，不以数量直接认定法律缺陷")
            if not allocations:
                error("ARCH-CARRIER-ALLOCATION", f"claim{number}", "高复杂度独权必须登记公式、符号定义或实施细节的载体分配")

    actual_independent_numbers = {number for number, text in claims.items() if not claim_references(text)}
    if independent_numbers != actual_independent_numbers:
        error("ARCH-CARRIER-COVERAGE", "independent_claims", f"合同独权集合{sorted(independent_numbers)}与文本独权集合{sorted(actual_independent_numbers)}不一致")

    nodes: set[str] = set()
    for index, node in enumerate(contract["topology_nodes"], start=1):
        if not isinstance(node, dict) or not isinstance(node.get("node_id"), str) or not ID_RE.fullmatch(node["node_id"]) or node["node_id"] in nodes:
            error("ARCH-TOPOLOGY-NODE", f"node[{index}]", "node_id必须合法且唯一")
            continue
        nodes.add(node["node_id"])
        if not str(node.get("label", "")).strip():
            error("ARCH-TOPOLOGY-NODE", node["node_id"], "节点label不能为空")

    topologies: dict[int, dict[str, Any]] = {}
    relation_ids: set[str] = set()
    for index, topo in enumerate(contract["claim_topologies"], start=1):
        if not isinstance(topo, dict):
            error("ARCH-TOPOLOGY-SHAPE", f"topology[{index}]", "拓扑记录必须是对象")
            continue
        number = topo.get("claim_number")
        if not isinstance(number, int) or isinstance(number, bool) or number in topologies:
            error("ARCH-TOPOLOGY-SHAPE", f"topology[{index}]", "claim_number必须为唯一正整数")
            continue
        topologies[number] = topo
        if number not in claims:
            error("ARCH-CLAIM-MISSING", f"claim{number}", "拓扑记录对应权利要求不存在")
        parents = topo.get("parent_claim_numbers")
        if not isinstance(parents, list) or any(not isinstance(value, int) or isinstance(value, bool) for value in parents) or len(set(parents)) != len(parents):
            error("ARCH-TOPOLOGY-SHAPE", f"claim{number}", "parent_claim_numbers必须是不重复的整数数组")
            parents = []
        elif number in claims and sorted(parents) != claim_references(claims[number]):
            error("ARCH-TOPOLOGY-PARENT", f"claim{number}", f"合同父项{sorted(parents)}与权利要求文本引用{claim_references(claims[number])}不一致")
        relations = topo.get("declared_relations")
        if not isinstance(relations, list):
            error("ARCH-TOPOLOGY-SHAPE", f"claim{number}", "declared_relations必须是数组")
            relations = []
        for relation in relations:
            if not isinstance(relation, dict):
                error("ARCH-TOPOLOGY-SHAPE", f"claim{number}", "关系必须是对象")
                continue
            rid = relation.get("relation_id")
            if not isinstance(rid, str) or not ID_RE.fullmatch(rid) or rid in relation_ids:
                error("ARCH-TOPOLOGY-RELATION", f"claim{number}", "relation_id必须合法且全局唯一")
            else:
                relation_ids.add(rid)
            for field in ("source_node_id", "target_node_id"):
                if relation.get(field) not in nodes:
                    error("ARCH-TOPOLOGY-RELATION", f"claim{number}", f"{field}引用未知节点：{relation.get(field)}")
            if relation.get("relation_type") not in {"connects", "provides", "controls", "contains", "data_flow", "other"}:
                error("ARCH-TOPOLOGY-RELATION", f"claim{number}", "relation_type非法")
            if not str(relation.get("target_port", "")).strip() or not isinstance(relation.get("exclusive_target_port"), bool):
                error("ARCH-TOPOLOGY-RELATION", f"claim{number}", "target_port和exclusive_target_port必须明确")

    if set(topologies) != set(claims):
        error("ARCH-TOPOLOGY-COVERAGE", "claim_topologies", f"拓扑登记项号{sorted(topologies)}与权利要求项号{sorted(claims)}不一致")

    # 核心保护点校验（在拓扑校验完成之后）
    cpp = contract.get("core_protection_point")
    if isinstance(cpp, dict):
        cpp_claim_number = cpp.get("claim_number")
        cpp_parent_claim_number = cpp.get("parent_claim_number")
        cpp_feature_ids = cpp.get("feature_ids")
        cpp_statement = cpp.get("statement")
        cpp_review = cpp.get("review")

        shape_errors = []
        if not isinstance(cpp_claim_number, int) or isinstance(cpp_claim_number, bool) or cpp_claim_number != 2:
            shape_errors.append("claim_number 必须为整数 2")
        if not isinstance(cpp_parent_claim_number, int) or isinstance(cpp_parent_claim_number, bool) or cpp_parent_claim_number != 1:
            shape_errors.append("parent_claim_number 必须为 1")
        if not isinstance(cpp_feature_ids, list) or not cpp_feature_ids or len(set(cpp_feature_ids)) != len(cpp_feature_ids):
            shape_errors.append("feature_ids 必须是非空、无重复的数组")
        elif any(not isinstance(fid, str) or not re.match(r"^F[0-9]{3}$", fid) for fid in cpp_feature_ids):
            shape_errors.append("feature_ids 中每项必须匹配 ^F[0-9]{3}$")
        if not isinstance(cpp_statement, str) or not cpp_statement.strip():
            shape_errors.append("statement 必须是非空字符串")

        if shape_errors:
            for msg in shape_errors:
                error("ARCH-CORE-SHAPE", "core_protection_point", msg)
        else:
            # ARCH-CORE-CLAIM：权利要求 2 的存在与引用关系
            if 2 not in claims:
                error("ARCH-CORE-CLAIM", "claim2", "权利要求 2 必须存在")
            elif claim_references(claims[2]) != [1]:
                error("ARCH-CORE-CLAIM", "claim2", f"权利要求 2 必须仅引用权利要求 1，实际为{claim_references(claims[2])}")
            if 2 not in topologies:
                error("ARCH-CORE-CLAIM", "topology[2]", "拓扑中必须有权利要求 2 的记录")
            elif sorted(topologies[2].get("parent_claim_numbers", [])) != [1]:
                error("ARCH-CORE-CLAIM", "topology[2]", f"权利要求 2 的拓扑 parent_claim_numbers 必须为 [1]，实际为{sorted(topologies[2].get('parent_claim_numbers', []))}")

            # ARCH-CORE-FEATURE：特征台账校验
            ledger_path = source_paths.get("feature_ledger")
            if ledger_path:
                try:
                    ledger_text = read_utf8(ledger_path, "特征台账")
                    ledger = json.loads(ledger_text)
                    features_list = ledger.get("features") if isinstance(ledger, dict) else None
                    if not isinstance(features_list, list):
                        error("ARCH-CORE-FEATURE", "feature_ledger", "特征台账中 features 必须是数组")
                    else:
                        features_by_id = {f.get("feature_id"): f for f in features_list if isinstance(f, dict)}
                        for fid in cpp_feature_ids:
                            feature = features_by_id.get(fid)
                            if feature is None:
                                error("ARCH-CORE-FEATURE", fid, f"特征 {fid} 在台账中未找到")
                            else:
                                if feature.get("classification") != "distinguishing":
                                    error("ARCH-CORE-FEATURE", fid, f"特征 {fid} 的 classification 必须为 'distinguishing'，实际为 '{feature.get('classification')}'")
                                claim_sites = feature.get("claim_sites")
                                has_claim_2 = isinstance(claim_sites, list) and any(
                                    isinstance(site, dict) and site.get("claim_number") == 2
                                    for site in claim_sites
                                )
                                if not has_claim_2:
                                    error("ARCH-CORE-FEATURE", fid, f"特征 {fid} 的 claim_sites 中必须至少有一条 claim_number=2 的记录")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    error("ARCH-CORE-FEATURE", "feature_ledger", "特征台账不可解析或没有 features 数组")

            # ARCH-CORE-REVIEW：复核状态检查
            if isinstance(cpp_review, dict):
                review_status = cpp_review.get("status")
                review_statement = cpp_review.get("statement")
                review_reviewed_at = cpp_review.get("reviewed_at")

                if review_status not in {"pending", "approved", "revise"}:
                    error("ARCH-CORE-REVIEW", "core_protection_point.review", f"review.status 必须为 pending/approved/revise，实际为 '{review_status}'")
                if not isinstance(review_statement, str) or not review_statement.strip():
                    error("ARCH-CORE-REVIEW", "core_protection_point.review", "review.statement 必须是非空字符串")
                if not isinstance(review_reviewed_at, str) or not review_reviewed_at.strip():
                    error("ARCH-CORE-REVIEW", "core_protection_point.review", "review.reviewed_at 必须是非空字符串")
                if review_status != "approved":
                    review("ARCH-CORE-REVIEW", "core_protection_point", "核心保护点复核未批准")
                    pending({
                        "key": "architecture.core_point_review_pending",
                        "source": {"tool_id": "validate_claim_architecture", "rule_id": "ARCH-CORE-REVIEW"},
                        "target": {"kind": "claim", "locator": "权利要求2"},
                        "question": "核心保护点复核尚未批准",
                        "adopted_default": "按当前载体分工继续，独权保持现状",
                        "options": ["批准当前核心点", "调整核心点"],
                        "impact": ["grant_risk", "protection_scope"],
                        "decider": "both"
                    })
            else:
                error("ARCH-CORE-REVIEW", "core_protection_point", "review 必须是对象")

    visiting: set[int] = set()
    accumulated_cache: dict[int, list[dict[str, Any]]] = {}

    def accumulated(number: int) -> list[dict[str, Any]]:
        if number in accumulated_cache:
            return accumulated_cache[number]
        if number in visiting:
            error("ARCH-TOPOLOGY-CYCLE", f"claim{number}", "父从权继承关系形成循环")
            return []
        visiting.add(number)
        topo = topologies.get(number)
        if topo is None:
            visiting.remove(number)
            error("ARCH-TOPOLOGY-PARENT", f"claim{number}", "缺少父项或本项的拓扑记录")
            return []
        merged: list[dict[str, Any]] = []
        for parent in topo.get("parent_claim_numbers") or []:
            if parent not in topologies:
                error("ARCH-TOPOLOGY-PARENT", f"claim{number}", f"缺少父权利要求{parent}的拓扑记录")
                continue
            merged.extend(accumulated(parent))
        merged.extend([item for item in topo.get("declared_relations") or [] if isinstance(item, dict)])
        visiting.remove(number)
        unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for relation in merged:
            signature = (
                str(relation.get("source_node_id")), str(relation.get("target_node_id")),
                str(relation.get("target_port")), str(relation.get("relation_type")),
            )
            unique[signature] = relation
        accumulated_cache[number] = list(unique.values())
        return accumulated_cache[number]

    for number in sorted(topologies):
        relations = accumulated(number)
        by_port: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for relation in relations:
            if relation.get("exclusive_target_port") is True:
                by_port.setdefault((str(relation.get("target_node_id")), str(relation.get("target_port"))), []).append(relation)
        for (target, port), items in by_port.items():
            source_nodes = {str(item.get("source_node_id")) for item in items}
            if len(source_nodes) > 1:
                error("ARCH-TOPOLOGY-CONFLICT", f"claim{number}", f"继承后排他端口{target}.{port}出现不兼容来源：{sorted(source_nodes)}")

    method_numbers: set[int] = set()
    for index, method in enumerate(contract["method_claims"], start=1):
        if not isinstance(method, dict):
            error("ARCH-METHOD-SHAPE", f"method[{index}]", "方法记录必须是对象")
            continue
        number = method.get("claim_number")
        if not isinstance(number, int) or isinstance(number, bool) or number not in claims or number in method_numbers:
            error("ARCH-METHOD-CLAIM", f"method[{index}]", "claim_number必须唯一并对应现有权利要求")
            continue
        method_numbers.add(number)
        steps = method.get("steps")
        if not isinstance(steps, list) or not steps:
            error("ARCH-METHOD-STEPS", f"claim{number}", "steps必须是非空数组")
            continue
        step_ids: list[str] = []
        orders: list[int] = []
        for step in steps:
            if not isinstance(step, dict):
                error("ARCH-METHOD-STEPS", f"claim{number}", "步骤必须是对象")
                continue
            step_id = step.get("step_id")
            order = step.get("order")
            action = step.get("action")
            anchor = step.get("specification_anchor")
            if not isinstance(step_id, str) or not STEP_RE.fullmatch(step_id) or step_id in step_ids:
                error("ARCH-METHOD-STEPS", f"claim{number}", "step_id必须形如S1且唯一")
                continue
            step_ids.append(step_id)
            if not isinstance(order, int) or isinstance(order, bool):
                error("ARCH-METHOD-STEPS", f"claim{number}.{step_id}", "order必须是整数")
            else:
                orders.append(order)
            if not isinstance(action, str) or not action.strip() or normalize(action) not in normalize(claims[number]):
                error("ARCH-METHOD-ACTION", f"claim{number}.{step_id}", "action必须能在对应方法权利要求中逐字定位")
            if not isinstance(anchor, str) or not anchor.strip() or normalize(anchor) not in normalize(specification_text):
                error("ARCH-METHOD-SPEC", f"claim{number}.{step_id}", "specification_anchor必须能在说明书中定位")
        if orders != list(range(1, len(orders) + 1)):
            error("ARCH-METHOD-ORDER", f"claim{number}", f"步骤order必须从1连续排列，实际为{orders}")
        actual_steps = [f"S{value}" for value in STEP_IN_CLAIM_RE.findall(claims[number])]
        if actual_steps != step_ids:
            error("ARCH-METHOD-ISOMORPHISM", f"claim{number}", f"合同步骤{step_ids}与权利要求步骤{actual_steps}不一致")
        step_set = set(step_ids)
        decision_ids: set[str] = set()
        for decision in method.get("decisions") or []:
            if not isinstance(decision, dict):
                error("ARCH-METHOD-DECISION", f"claim{number}", "decision必须是对象")
                continue
            did = decision.get("decision_id")
            if not isinstance(did, str) or not ID_RE.fullmatch(did) or did in decision_ids:
                error("ARCH-METHOD-DECISION", f"claim{number}", "decision_id必须合法且唯一")
            else:
                decision_ids.add(did)
            for field in ("after_step_id", "true_target_step_id", "false_target_step_id"):
                if decision.get(field) not in step_set:
                    error("ARCH-METHOD-DECISION", f"claim{number}.{did}", f"{field}引用未知步骤")
            if not str(decision.get("condition", "")).strip():
                error("ARCH-METHOD-DECISION", f"claim{number}.{did}", "condition不能为空")
        for loop in method.get("loops") or []:
            if not isinstance(loop, dict):
                error("ARCH-METHOD-LOOP", f"claim{number}", "loop必须是对象")
                continue
            for field in ("from_step_id", "to_step_id"):
                if loop.get(field) not in step_set:
                    error("ARCH-METHOD-LOOP", f"claim{number}", f"{field}引用未知步骤")
            if not str(loop.get("condition", "")).strip():
                error("ARCH-METHOD-LOOP", f"claim{number}", "condition不能为空")

    claims_with_steps = {number for number, text in claims.items() if STEP_IN_CLAIM_RE.search(text)}
    if method_numbers != claims_with_steps:
        error("ARCH-METHOD-COVERAGE", "method_claims", f"方法步骤合同项号{sorted(method_numbers)}与含步骤号权利要求{sorted(claims_with_steps)}不一致")

    return {
        "schema_id": REPORT_SCHEMA_ID,
        "case_id": contract["case_id"],
        "contract": str(contract_path),
        "contract_sha256": sha256(contract_path),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "review_required": reviews,
        "pending_decisions": pending_decisions,
        "sources": bound_sources,
        "evidence_scope": {
            "proves": [
                "高复杂度独权已留下人工载体分工决定",
                "父从权继承后的登记拓扑不存在确定性的排他端口冲突",
                "方法权利要求步骤编号、顺序及动作与合同一致",
            ],
            "does_not_prove": [
                "权利要求必然清楚、简要或得到说明书支持",
                "未登记为排他端口的技术关系必然能够共存",
                "申请具备新颖性、创造性或授权前景",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验中国专利权利要求架构合同")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--specification", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        output_guard = DraftingOutputGuard(
            [args.contract, args.claims, args.specification],
            [args.output] if args.output else [],
        )
        report = validate_contract(
            args.contract.resolve(), args.case_dir.resolve(),
            args.claims.resolve(), args.specification.resolve(), output_guard=output_guard,
        )
        exit_code = 0 if report["status"] == "PASS" else 2
        if args.output:
            output_guard.write_texts([json.dumps(report, ensure_ascii=False, indent=2) + "\n"])
    except (OSError, UnicodeError, ValueError) as exc:
        report = {"schema_id": REPORT_SCHEMA_ID, "status": "FAIL", "errors": [{"code": "ARCH-INPUT", "target": "input", "message": str(exc)}], "review_required": []}
        exit_code = 3
    print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
