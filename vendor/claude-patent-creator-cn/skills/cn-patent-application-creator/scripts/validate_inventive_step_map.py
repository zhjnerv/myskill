#!/usr/bin/env python3
"""校验中国专利创造性防御地图 `cn-patent-inventive-step-map/v1`。

把三步法的"需要几篇对比文件才能凑齐全部区别特征、作用是否一致、是否存在说明书可定位的耦合"
变成机器状态位。产物有效性问题（来源过期、格子缺失、锚点定位失败、集合不匹配、手改分级）
以退出码 2 阻断；判断题（分级不够、复核未批准、公知常识 medium、partial 过多、核心特征集非最小）
按保守默认继续并写入 pending_decisions。

退出码：0 通过（含待决）；2 存在阻断错误；3 输入、路径、编码或 JSON 无效。
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cn_drafting_io import DraftingOutputGuard  # noqa: E402
from validate_claim_architecture import (  # noqa: E402
    claim_references,
    load_json,
    parse_claims,
    read_utf8,
    resolve_under,
    sha256,
)

SCHEMA_ID = "cn-patent-inventive-step-map/v1"
REPORT_SCHEMA_ID = "cn-patent-inventive-step-map-validation/v1"
TOOL_ID = "validate_inventive_step_map"
COMMON_KNOWLEDGE = "COMMON_KNOWLEDGE"
REQUIRED_SOURCES = {"claims", "specification", "feature_ledger", "claim_architecture"}
FEATURE_ID_RE = re.compile(r"^F[0-9]{3}$")
MAX_FEATURES = 15
MAX_REFERENCES = 12
GRADE_ORDER = {"novelty_risk": 0, "weak": 1, "defensible": 2}


class InventiveStepMapError(ValueError):
    """输入不符合合同形状时抛出，退出码 3。"""


def _pending(
    key: str, rule_id: str, kind: str, locator: str, question: str,
    adopted_default: str, options: list[str], impact: list[str], decider: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "source": {"tool_id": TOOL_ID, "rule_id": rule_id},
        "target": {"kind": kind, "locator": locator},
        "question": question,
        "adopted_default": adopted_default,
        "options": options,
        "impact": impact,
        "decider": decider,
    }


def validate_map(
    map_path: Path, case_dir: Path, claims_path: Path, specification_path: Path,
    *, output_guard: DraftingOutputGuard | None = None,
) -> dict[str, Any]:
    contract = load_json(map_path, "创造性防御地图")
    if contract.get("schema_id") != SCHEMA_ID:
        raise InventiveStepMapError(f"schema_id 必须为 {SCHEMA_ID}")
    for field in ("source_artifacts", "references", "cells", "couplings", "claim_assessments"):
        if not isinstance(contract.get(field), list):
            raise InventiveStepMapError(f"{field} 必须是数组")

    errors: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    pending: list[dict[str, Any]] = []

    def error(code: str, target: str, message: str) -> None:
        errors.append({"code": code, "target": target, "message": message})

    def review(code: str, target: str, message: str) -> None:
        reviews.append({"code": code, "target": target, "message": message})

    def add_pending(decision: dict[str, Any]) -> None:
        for item in pending:
            if item["key"] == decision["key"] and item["target"] == decision["target"]:
                return
        pending.append(decision)

    claims_text = read_utf8(claims_path, "权利要求书")
    specification_text = read_utf8(specification_path, "说明书")
    claims = parse_claims(claims_text)
    if not claims:
        raise InventiveStepMapError("权利要求书中没有解析到编号权利要求")

    # ---- 来源绑定 --------------------------------------------------------
    source_paths: dict[str, Path] = {}
    bound_sources: list[dict[str, str]] = []
    for index, item in enumerate(contract["source_artifacts"], start=1):
        if not isinstance(item, dict):
            error("ISM-SOURCE-SHAPE", f"source[{index}]", "来源必须是对象")
            continue
        artifact_id = item.get("artifact_id")
        raw_path = item.get("path")
        if artifact_id not in REQUIRED_SOURCES or artifact_id in source_paths:
            error("ISM-SOURCE-SHAPE", f"source[{index}]", "artifact_id 非法或重复")
            continue
        if not isinstance(raw_path, str) or not raw_path:
            error("ISM-SOURCE-SHAPE", str(artifact_id), "path 必须是非空字符串")
            continue
        path = resolve_under(case_dir, raw_path, f"来源{artifact_id}")
        if output_guard is not None:
            output_guard.protect_inputs([path])
        if not path.is_file():
            error("ISM-SOURCE-MISSING", str(artifact_id), f"来源不存在：{raw_path}")
            continue
        actual = sha256(path)
        if item.get("sha256") != actual:
            error("ISM-SOURCE-STALE", str(artifact_id), f"来源 {artifact_id} 的 SHA-256 与当前文件不一致，地图失效")
        source_paths[str(artifact_id)] = path
        bound_sources.append({"artifact_id": str(artifact_id), "path": str(path), "sha256": actual})
    if set(source_paths) != REQUIRED_SOURCES:
        error("ISM-SOURCE-SET", "source_artifacts", f"必须且只能绑定 {sorted(REQUIRED_SOURCES)}")
    if source_paths.get("claims") and source_paths["claims"] != claims_path.resolve():
        error("ISM-SOURCE-MISMATCH", "claims", "合同绑定的 claims 与命令行输入不是同一文件")
    if source_paths.get("specification") and source_paths["specification"] != specification_path.resolve():
        error("ISM-SOURCE-MISMATCH", "specification", "合同绑定的 specification 与命令行输入不是同一文件")

    ledger = load_json(source_paths["feature_ledger"], "特征台账") if source_paths.get("feature_ledger") else {}
    architecture = load_json(source_paths["claim_architecture"], "架构合同") if source_paths.get("claim_architecture") else {}
    ledger_features: dict[str, dict[str, Any]] = {}
    for feature in ledger.get("features") or []:
        if isinstance(feature, dict) and isinstance(feature.get("feature_id"), str):
            ledger_features[feature["feature_id"]] = feature

    def feature_sites(fid: str) -> set[int]:
        sites = ledger_features.get(fid, {}).get("claim_sites") or []
        return {site.get("claim_number") for site in sites if isinstance(site, dict) and isinstance(site.get("claim_number"), int)}

    # ---- 对比文件 --------------------------------------------------------
    ref_ids: list[str] = []
    ck_role_ok = False
    for index, item in enumerate(contract["references"], start=1):
        if not isinstance(item, dict) or not isinstance(item.get("ref_id"), str) or not item["ref_id"]:
            error("ISM-REF-SHAPE", f"reference[{index}]", "ref_id 必须是非空字符串")
            continue
        if item["ref_id"] in ref_ids:
            error("ISM-REF-SHAPE", item["ref_id"], "ref_id 重复")
            continue
        ref_ids.append(item["ref_id"])
        if item["ref_id"] == COMMON_KNOWLEDGE:
            ck_role_ok = item.get("role") == "common_knowledge"
    if COMMON_KNOWLEDGE not in ref_ids:
        error("ISM-REF-001", "references", f"必须固定登记 {COMMON_KNOWLEDGE} 虚拟条目")
    elif not ck_role_ok:
        error("ISM-REF-001", COMMON_KNOWLEDGE, "COMMON_KNOWLEDGE 的 role 必须是 common_knowledge")
    if len(ref_ids) > MAX_REFERENCES:
        error("ISM-COVER-002", "references", f"对比文件数 {len(ref_ids)} 超过上限 {MAX_REFERENCES}")

    # ---- 格子 ------------------------------------------------------------
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for index, cell in enumerate(contract["cells"], start=1):
        if not isinstance(cell, dict):
            error("ISM-CELL-SHAPE", f"cell[{index}]", "格子必须是对象")
            continue
        fid, rid = cell.get("feature_id"), cell.get("ref_id")
        if not isinstance(fid, str) or not FEATURE_ID_RE.match(fid) or rid not in ref_ids:
            error("ISM-CELL-SHAPE", f"cell[{index}]", "feature_id 必须匹配 ^F[0-9]{3}$ 且 ref_id 必须已登记")
            continue
        if (fid, rid) in cells:
            error("ISM-CELL-SHAPE", f"{fid}×{rid}", "格子重复")
            continue
        cells[(fid, rid)] = cell
    map_features = sorted({fid for fid, _ in cells})
    if len(map_features) > MAX_FEATURES:
        error("ISM-COVER-001", "cells", f"区别特征数 {len(map_features)} 超过上限 {MAX_FEATURES}，拒绝枚举")
        map_features = []

    for fid in map_features:
        feature = ledger_features.get(fid)
        if feature is None:
            error("ISM-CELL-002", fid, f"特征 {fid} 不在台账中")
            continue
        if feature.get("classification") != "distinguishing":
            error("ISM-CELL-002", fid, f"特征 {fid} 在台账中不是 distinguishing，不得进入地图")
        verdict = (feature.get("prior_art_status") or {}).get("verdict")
        if verdict in (None, "not_searched"):
            add_pending(_pending(
                "inventive.feature_not_searched", "ISM-CELL-004", "ledger", fid,
                f"特征 {fid} 尚无检索判定，地图按最坏情况处理",
                "该特征视同被公知常识覆盖参与分级",
                ["补做检索并回填台账", "确认按最坏情况评估"], ["grant_risk"], "attorney",
            ))
        for rid in ref_ids:
            cell = cells.get((fid, rid))
            if cell is None:
                error("ISM-CELL-001", f"{fid}×{rid}", "缺少该特征与该对比文件的格子")
                continue
            if rid == COMMON_KNOWLEDGE:
                risk = cell.get("common_knowledge_risk")
                if risk not in {"high", "medium", "low"} or not str(cell.get("evidence_type", "")).strip():
                    error("ISM-CELL-001", f"{fid}×{rid}", "COMMON_KNOWLEDGE 格子必须提供 common_knowledge_risk 与 evidence_type")
                elif risk == "medium":
                    add_pending(_pending(
                        "inventive.common_knowledge_medium", "ISM-CK-MEDIUM", "ledger", fid,
                        f"特征 {fid} 的公知常识风险被判为 medium，需要人工改判",
                        "按 high 参与分级（视同被公知常识覆盖）",
                        ["改判 high", "改判 low"], ["grant_risk"], "attorney",
                    ))
                continue
            disclosed = cell.get("disclosed")
            if disclosed not in {"yes", "partial", "no"}:
                error("ISM-CELL-001", f"{fid}×{rid}", "非公知常识格子必须提供 disclosed ∈ {yes, partial, no}")
            elif disclosed in {"yes", "partial"}:
                if not str(cell.get("locator", "")).strip():
                    error("ISM-CELL-001", f"{fid}×{rid}", f"disclosed={disclosed} 时必须提供 locator（段落或图号）")
                if disclosed == "yes" and cell.get("function_match") not in {"same", "different"}:
                    error("ISM-CELL-001", f"{fid}×{rid}", "disclosed=yes 时必须提供 function_match ∈ {same, different}")
            elif not str(cell.get("searched_scope", "")).strip():
                error("ISM-CELL-001", f"{fid}×{rid}", "disclosed=no 时必须提供 searched_scope")

    def covers(fid: str, rid: str) -> bool:
        cell = cells.get((fid, rid), {})
        if rid == COMMON_KNOWLEDGE:
            verdict = (ledger_features.get(fid, {}).get("prior_art_status") or {}).get("verdict")
            if verdict in (None, "not_searched"):
                return True
            return cell.get("common_knowledge_risk") in {"high", "medium"}
        return cell.get("disclosed") == "yes"

    def function_different(fid: str, rid: str) -> bool:
        # 公知常识覆盖即按相同作用对待：D1+公知常识是审查员最常用的组合，不能借"作用不同"逃逸。
        return rid != COMMON_KNOWLEDGE and cells.get((fid, rid), {}).get("function_match") == "different"

    # ---- 耦合 ------------------------------------------------------------
    couplings: list[tuple[str, str]] = []
    for index, item in enumerate(contract["couplings"], start=1):
        if not isinstance(item, dict):
            error("ISM-COUPLING-SHAPE", f"coupling[{index}]", "耦合记录必须是对象")
            continue
        fa, fb, anchor = item.get("feature_a"), item.get("feature_b"), item.get("statement_anchor")
        if fa not in map_features or fb not in map_features or fa == fb:
            error("ISM-COUPLING-001", f"coupling[{index}]", "耦合两端必须是地图中不同的区别特征")
            continue
        if not isinstance(anchor, str) or not anchor.strip() or anchor.strip() not in specification_text:
            error("ISM-COUPLING-001", f"coupling[{index}]", f"耦合 {fa}↔{fb} 的 statement_anchor 未在说明书中逐字定位，不计入耦合证据")
            continue
        if any(covers(fa, rid) and covers(fb, rid) for rid in ref_ids):
            review("ISM-COUPLING-002", f"{fa}↔{fb}", "已有单篇对比文件或公知常识同时覆盖耦合两端，该耦合不计入耦合证据")
            continue
        couplings.append((fa, fb))

    # ---- 分级 ------------------------------------------------------------
    def grade_feature_set(fset: frozenset[str]) -> dict[str, Any]:
        if not fset:
            return {"grade": "novelty_risk", "min_refs_to_cover": 0, "same_function_cover": True, "coupling_evidence": False, "uncovered": []}
        uncovered = sorted(f for f in fset if not any(covers(f, r) for r in ref_ids))
        coupling_evidence = any(a in fset and b in fset for a, b in couplings)
        if uncovered:
            return {"grade": "defensible", "min_refs_to_cover": None, "same_function_cover": False, "coupling_evidence": coupling_evidence, "uncovered": uncovered}
        min_size: int | None = None
        min_covers: list[tuple[str, ...]] = []
        for size in range(1, len(ref_ids) + 1):
            for subset in itertools.combinations(ref_ids, size):
                if all(any(covers(f, r) for r in subset) for f in fset):
                    min_covers.append(subset)
            if min_covers:
                min_size = size
                break
        assert min_size is not None
        same_function_cover = min_size <= 2 and any(
            all(any(covers(f, r) and not function_different(f, r) for r in subset) for f in fset)
            for subset in min_covers
        )
        all_different = min_size == 2 and any(
            all(any(covers(f, r) and function_different(f, r) for r in subset) for f in fset)
            for subset in min_covers
        )
        if min_size == 1:
            grade = "novelty_risk"
        elif min_size >= 3 or coupling_evidence or all_different:
            grade = "defensible"
        else:
            grade = "weak"
        return {"grade": grade, "min_refs_to_cover": min_size, "same_function_cover": same_function_cover, "coupling_evidence": coupling_evidence, "uncovered": []}

    # ---- claim_set 推导 ----------------------------------------------------
    derived_sets: list[tuple[int, ...]] = []
    independent_numbers = sorted(number for number, text in claims.items() if not claim_references(text))
    for k in independent_numbers:
        derived_sets.append((k,))
        follower = k + 1
        if follower in claims and claim_references(claims[follower]) == [k]:
            derived_sets.append((k, follower))
        else:
            add_pending(_pending(
                "inventive.core_dependent_missing", "ISM-DEPENDENT", "claim", f"权利要求{k}",
                f"独立权利要求 {k} 之后没有直接且仅引用它的核心从属项，无法形成保底组",
                "仅评估独立权利要求本身",
                ["补写直接从属于该独权的核心从属项", "确认不设保底组"], ["grant_risk", "protection_scope"], "attorney",
            ))
    declared: dict[tuple[int, ...], dict[str, Any]] = {}
    for index, item in enumerate(contract["claim_assessments"], start=1):
        if not isinstance(item, dict) or not isinstance(item.get("claim_set"), list) or not all(isinstance(n, int) and not isinstance(n, bool) for n in item["claim_set"]):
            error("ISM-CLAIMSET-SHAPE", f"assessment[{index}]", "claim_set 必须是整数数组")
            continue
        declared[tuple(sorted(item["claim_set"]))] = item
    if set(declared) != set(derived_sets):
        error("ISM-CLAIMSET-001", "claim_assessments", f"合同 claim_set {sorted(declared)} 与权利要求推导集合 {sorted(derived_sets)} 不一致")

    core_point = architecture.get("core_protection_point") if isinstance(architecture, dict) else None
    assessments: list[dict[str, Any]] = []
    minimal_sets: dict[str, list[list[str]]] = {}
    searched_scope: dict[str, list[str]] = {}
    for claim_set in derived_sets:
        label = ",".join(map(str, claim_set))
        fset = frozenset(f for f in map_features if feature_sites(f) & set(claim_set))
        partial_features = sorted(
            f for f in fset
            if any(cells.get((f, r), {}).get("disclosed") == "partial" for r in ref_ids) and not any(covers(f, r) for r in ref_ids)
        )
        if fset and len(partial_features) * 2 >= len(fset):
            review("ISM-PARTIAL-001", f"claim_set=[{label}]", f"仅被部分公开的特征 {partial_features} 占区别特征一半以上，易被“部分公开 + 公知常识”补齐")
            add_pending(_pending(
                "inventive.partial_disclosure_heavy", "ISM-PARTIAL-001", "claim", f"权利要求{claim_set[-1]}",
                f"权利要求组 [{label}] 半数以上区别特征仅比对比文件更具体一点",
                "partial 不计入覆盖，按当前分级交付",
                ["补充耦合/条件型区别特征", "确认接受该风险"], ["grant_risk"], "attorney",
            ))
        result = grade_feature_set(fset)
        for f in result["uncovered"]:
            searched_scope[f] = [
                str(cells.get((f, r), {}).get("searched_scope", "")).strip()
                for r in ref_ids if r != COMMON_KNOWLEDGE and cells.get((f, r), {}).get("disclosed") == "no"
            ]
        item = declared.get(claim_set, {})
        review_block = item.get("review") if isinstance(item.get("review"), dict) else {}
        if item.get("grade") not in (None, result["grade"]):
            error("ISM-GRADE-001", f"claim_set=[{label}]", f"声明 grade={item.get('grade')} 与复算 {result['grade']} 不一致；grade 只能由脚本复算写回")
        if result["grade"] != "defensible":
            add_pending(_pending(
                "inventive.core_set_not_defensible", "ISM-GRADE", "claim", f"权利要求{claim_set[-1]}",
                f"权利要求组 [{label}] 复算分级为 {result['grade']}",
                f"按当前权利要求交付，创造性风险等级={result['grade']}，需在说明书补机理链或换特征",
                ["补充说明书机理链与效果证据", "更换或增加耦合/条件型特征", "接受该风险等级"], ["grant_risk"], "both",
            ))
        if review_block.get("status") != "approved":
            add_pending(_pending(
                "inventive.assessment_review_pending", "ISM-REVIEW", "claim", f"权利要求{claim_set[-1]}",
                f"权利要求组 [{label}] 的创造性评估尚未经代理师复核",
                "按脚本复算结果继续",
                ["批准", "要求修改后重评"], ["grant_risk"], "attorney",
            ))
        assessments.append({
            "claim_set": list(claim_set),
            "features": sorted(fset),
            "min_refs_to_cover": result["min_refs_to_cover"],
            "same_function_cover": result["same_function_cover"],
            "coupling_evidence": result["coupling_evidence"],
            "uncovered_features": result["uncovered"],
            "grade": result["grade"],
            "review": review_block,
        })
        if fset:
            defensible_subsets = [
                frozenset(sub)
                for size in range(1, len(fset) + 1)
                for sub in itertools.combinations(sorted(fset), size)
                if grade_feature_set(frozenset(sub))["grade"] == "defensible"
            ]
            minimal = [s for s in defensible_subsets if not any(o < s for o in defensible_subsets)]
            minimal_sets[label] = sorted(sorted(s) for s in minimal)
            if len(claim_set) == 2 and claim_set[0] == 1 and isinstance(core_point, dict):
                registered = set(core_point.get("feature_ids") or [])
                if registered and not any(registered == set(s) for s in minimal):
                    add_pending(_pending(
                        "inventive.core_point_not_minimal", "ISM-CORE", "claim", "权利要求2",
                        f"架构合同登记的核心特征集 {sorted(registered)} 不是使 [1,2] 达到 defensible 的最小特征集之一；复算最小集合：{minimal_sets[label]}",
                        "沿用架构合同登记的核心特征集",
                        ["按复算最小集合更新 core_protection_point", "确认保留当前登记"], ["grant_risk", "protection_scope"], "attorney",
                    ))

    return {
        "schema_id": REPORT_SCHEMA_ID,
        "legal_effect": "ADVISORY_ONLY",
        "status": "PASS" if not errors else "FAIL",
        "map": {"path": str(map_path), "sha256": sha256(map_path)},
        "bound_sources": bound_sources,
        "errors": errors,
        "review_required": reviews,
        "pending_decisions": pending,
        "claim_assessments": assessments,
        "minimal_defensible_sets": minimal_sets,
        "searched_scope": searched_scope,
        "boundary": "分级只证明在已登记对比文件与公知常识判断下凑齐区别特征的难度，不证明创造性成立；partial 不计覆盖，公知常识 medium 与未检索特征按最坏情况处理。",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验中国专利创造性防御地图")
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--specification", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        output_guard = DraftingOutputGuard([args.map, args.claims, args.specification], [args.output] if args.output else [])
        report = validate_map(
            args.map.resolve(), args.case_dir.resolve(), args.claims.resolve(), args.specification.resolve(),
            output_guard=output_guard,
        )
        exit_code = 0 if report["status"] == "PASS" else 2
        if args.output:
            output_guard.write_texts([json.dumps(report, ensure_ascii=False, indent=2) + "\n"])
    except (OSError, UnicodeError, ValueError) as exc:
        report = {"schema_id": REPORT_SCHEMA_ID, "status": "FAIL", "errors": [{"code": "ISM-INPUT", "target": "input", "message": str(exc)}], "review_required": [], "pending_decisions": []}
        exit_code = 3
    print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
