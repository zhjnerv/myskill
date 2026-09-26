#!/usr/bin/env python3
"""阶段门：阶段 2 到阶段 3 之间的机器状态位。

问题背景：上一轮起草中，CNIPA 人工检索状态写在散文里（"本轮尚未完成"），
范本确认也只是散文描述。文档说"不得静默继续"，但"写了未完成再继续"字面
合规，于是权利要求和说明书在检索未完成、范本未确认的情况下就产出了，事后
才补范本学习并返工三轮。

约束写成文档口号就等于没有约束。本脚本把三件事变成机器可判定的状态位：

  1. CNIPA 人工检索是否完成，未完成时是否有用户的显式授权继续；
  2. 范本是否已由用户确认，或用户是否显式选择不使用范本；
  3. style-brief.json 是否存在、是否绑定到已确认的范本风格指南。

未过门时退出码为 2，起草阶段不得开始。跳过必须携带用户原话，不接受
agent 自行判断"用户应该同意"。

退出码：0 放行；2 未过门；3 输入/路径/编码/JSON 无效。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_ID = "cn-patent-stage2-gate/v1"
SCHEMA_ID_V2 = "cn-patent-stage2-gate/v2"
SUPPORTED_SCHEMA_IDS = {SCHEMA_ID, SCHEMA_ID_V2}
TEMPLATE_SELECTION_SCHEMA_ID = "cn-patent-template-selection/v2"
TEMPLATE_CANDIDATES_SCHEMA_ID = "cn-patent-template-candidates/v1"
SEARCH_SCHEMA_ID = "cn-patent-template-search/v1"
REPORT_SCHEMA_ID = "cn-patent-stage2-gate-report/v1"
STYLE_BRIEF_SCHEMA_ID = "cn-patent-style-brief/v1"

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_INPUT_ERROR = 3

SEARCH_STATES = {"completed", "partial", "not_completed"}
TEMPLATE_STATES = {"confirmed", "declined", "pending"}


class GateError(ValueError):
    """阶段门输入不合法时抛出。"""


def read_bytes(path: Path, label: str) -> bytes:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise GateError(f"{label}文件不存在：{path}") from exc
    except OSError as exc:
        raise GateError(f"{label}文件不可读：{path}（{exc}）") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise GateError(f"{label}含 BOM，必须使用 UTF-8 无 BOM：{path}")
    return raw


def load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = read_bytes(path, label)
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise GateError(f"{label}不是有效 UTF-8：{path}") from exc
    except json.JSONDecodeError as exc:
        raise GateError(f"{label} JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise GateError(f"{label}必须是对象：{path}")
    return data, raw


def require_authorization(block: Any, label: str) -> str | None:
    """提取用户原话，如果不存在则返回 None。"""
    if not isinstance(block, dict):
        return None
    quote = block.get("user_quote")
    if not isinstance(quote, str) or not quote.strip():
        return None
    granted_at = block.get("granted_at")
    if not isinstance(granted_at, str) or not granted_at.strip():
        return None
    return quote.strip()


class Gate:
    def __init__(self) -> None:
        self.blocks: list[dict[str, str]] = []
        self.notes: list[dict[str, str]] = []
        self.pending_decisions: list[dict[str, Any]] = []

    def block(self, gate_id: str, reason: str, remedy: str) -> None:
        self.blocks.append({"gate_id": gate_id, "reason": reason, "remedy": remedy})

    def note(self, gate_id: str, message: str) -> None:
        self.notes.append({"gate_id": gate_id, "message": message})

    def pending(self, decision: dict[str, Any]) -> None:
        self.pending_decisions.append(decision)


def check_search(state: dict[str, Any], gate: Gate) -> None:
    search = state.get("cnipa_manual_search")
    if not isinstance(search, dict):
        raise GateError("必须提供 cnipa_manual_search 对象")
    status = search.get("status")
    if status not in SEARCH_STATES:
        raise GateError(
            "cnipa_manual_search.status 必须是以下值之一：" + "、".join(sorted(SEARCH_STATES))
        )

    if status == "completed":
        records = search.get("records")
        if not isinstance(records, list) or not records:
            gate.block(
                "GATE-SEARCH-001",
                "CNIPA 人工检索声明为 completed，却没有任何检索记录",
                "逐条登记检索日期、检索式、命中数和筛选理由；无记录的完成声明不可核对",
            )
        else:
            for index, record in enumerate(records, start=1):
                if not isinstance(record, dict):
                    gate.block(
                        "GATE-SEARCH-002",
                        f"第 {index} 条检索记录不是对象",
                        "按 date/query/hits/screening 结构登记",
                    )
                    continue
                for field in ("date", "query", "hits"):
                    if field not in record:
                        gate.block(
                            "GATE-SEARCH-002",
                            f"第 {index} 条检索记录缺少 {field}",
                            "补齐检索日期、检索式与命中数",
                        )
        gate.note("GATE-SEARCH-001", "CNIPA 官方库人工检索已登记完成")
        return

    # 未完成或部分完成时，必须有用户显式授权才允许进入起草。
    quote = require_authorization(
        search.get("user_authorization"),
        f"CNIPA 人工检索状态为 {status} 时",
    )
    if quote:
        gate.note(
            "GATE-SEARCH-003",
            f"CNIPA 人工检索为 {status}，凭用户授权继续：“{quote}”。"
            "文件包必须写明未完成官方库穷举检索，新颖性与创造性维度保持 INCONCLUSIVE。",
        )
    else:
        gate.pending({
            "key": "search.cnipa_manual_search_pending_authorization",
            "source": {"tool_id": "check_stage_gate", "rule_id": "GATE-SEARCH-003"},
            "target": {"kind": "process", "locator": "cnipa_manual_search"},
            "question": f"CNIPA 人工检索状态为 {status}，是否授权继续？",
            "adopted_default": "按官方库穷举未完成继续；新颖性/创造性维度保持 INCONCLUSIVE",
            "options": ["授权继续", "补充检索记录"],
            "impact": ["grant_risk"],
            "decider": "attorney"
        })
        gate.note("GATE-SEARCH-003", f"CNIPA 人工检索未提供用户授权，产生待决项，按官方库穷举未完成继续。")


def check_template(state: dict[str, Any], gate: Gate, workspace: Path) -> list[Path]:
    template = state.get("template_selection")
    if not isinstance(template, dict):
        raise GateError("必须提供 template_selection 对象")
    status = template.get("status")
    if status not in TEMPLATE_STATES:
        raise GateError(
            "template_selection.status 必须是以下值之一：" + "、".join(sorted(TEMPLATE_STATES))
        )

    if status == "pending":
        gate.pending({
            "key": "template.selection_pending",
            "source": {"tool_id": "check_stage_gate", "rule_id": "GATE-TEMPLATE-001"},
            "target": {"kind": "process", "locator": "template_selection"},
            "question": "是否确认使用范本？",
            "adopted_default": "不加载范本，用默认起草策略",
            "options": ["确认范本", "不使用范本"],
            "impact": ["formality"],
            "decider": "attorney"
        })
        return []

    if status == "declined":
        quote = require_authorization(
            template.get("user_authorization"),
            "范本状态为 declined 时",
        )
        if quote:
            gate.note("GATE-TEMPLATE-002", f"用户明确不使用范本：“{quote}”，按默认起草策略执行")
        else:
            gate.pending({
                "key": "template.declined_authorization_missing",
                "source": {"tool_id": "check_stage_gate", "rule_id": "GATE-TEMPLATE-002"},
                "target": {"kind": "process", "locator": "template_selection"},
                "question": "是否确认不使用范本？",
                "adopted_default": "按 declined 继续",
                "options": ["确认不使用范本", "补充确认用户原话"],
                "impact": ["formality"],
                "decider": "attorney"
            })
        return []

    guides = template.get("style_guides")
    if not isinstance(guides, list) or not guides:
        gate.block(
            "GATE-TEMPLATE-003",
            "范本状态为 confirmed，却没有列出任何 template-style-guide.json",
            "对每篇确认的范本运行 analyze_template_style.py 并在此登记其路径",
        )
        return []

    quote = require_authorization(
        template.get("user_authorization"),
        "范本状态为 confirmed 时",
    )
    if quote:
        gate.note("GATE-TEMPLATE-004", f"范本已由用户确认：“{quote}”")
    else:
        gate.note("GATE-TEMPLATE-004", "范本状态为 confirmed，但未提供用户原话；按已确认范本继续")

    resolved: list[Path] = []
    for index, item in enumerate(guides, start=1):
        if not isinstance(item, str) or not item.strip():
            gate.block(
                "GATE-TEMPLATE-005",
                f"第 {index} 个风格指南路径不是字符串",
                "登记为相对于工作目录的路径",
            )
            continue
        path = (workspace / item).resolve()
        if not path.is_file():
            gate.block(
                "GATE-TEMPLATE-005",
                f"风格指南文件不存在：{item}",
                "先生成 template-style-guide.json 再过门",
            )
            continue
        resolved.append(path)
    return resolved


def check_template_ipc_selection(
    state: dict[str, Any], gate: Gate, workspace: Path, guides: list[Path]
) -> None:
    """v2 阶段门：核验目标 IPC 与候选 IPC 加权选择证据。"""

    if state.get("schema_id") != SCHEMA_ID_V2:
        gate.note(
            "GATE-IPC-000",
            "旧版 v1 阶段门不含 IPC 加权范本选择；新案件必须升级为 cn-patent-stage2-gate/v2。",
        )
        return
    template = state.get("template_selection") or {}
    if template.get("status") != "confirmed":
        return

    required_paths = {
        "search_query_path": "search-query.json",
        "candidate_manifest_path": "范本候选清单",
        "selection_report_path": "IPC 加权范本选择报告",
    }
    resolved: dict[str, Path] = {}
    for field, label in required_paths.items():
        raw = template.get(field)
        if not isinstance(raw, str) or not raw.strip():
            gate.block(
                "GATE-IPC-001",
                f"v2 范本选择缺少 {field}",
                "先确定目标 IPC、建立候选清单并运行 rank_template_candidates.py。",
            )
            continue
        path = (workspace / raw).resolve()
        if not path.is_file():
            gate.block("GATE-IPC-001", f"{label}不存在：{raw}", "补齐文件后重新运行阶段门。")
            continue
        resolved[field] = path
    if len(resolved) != len(required_paths):
        return

    try:
        selection, _ = load_json(resolved["selection_report_path"], "template-selection.json")
    except GateError as exc:
        gate.block("GATE-IPC-002", str(exc), "重新运行 rank_template_candidates.py。")
        return
    if selection.get("schema_id") != TEMPLATE_SELECTION_SCHEMA_ID:
        gate.block(
            "GATE-IPC-002",
            f"范本选择报告 schema_id 不是 {TEMPLATE_SELECTION_SCHEMA_ID}",
            "使用当前 rank_template_candidates.py 重新生成。",
        )
        return

    inputs = selection.get("inputs") or {}
    for field, hash_field in (
        ("search_query_path", "search_query_sha256"),
        ("candidate_manifest_path", "candidate_manifest_sha256"),
    ):
        expected = inputs.get(hash_field)
        actual = hashlib.sha256(resolved[field].read_bytes()).hexdigest()
        if expected != actual:
            gate.block(
                "GATE-IPC-003",
                f"范本选择报告绑定的 {field} 哈希与当前文件不一致",
                "候选、目标 IPC 或检索清单变化后必须重跑 rank_template_candidates.py。",
            )

    try:
        search_query, _ = load_json(resolved["search_query_path"], "search-query.json")
        candidate_manifest, _ = load_json(resolved["candidate_manifest_path"], "template-candidates.json")
    except GateError as exc:
        gate.block("GATE-IPC-003", str(exc), "修正输入文件并重跑范本选择。")
        return

    if search_query.get("schema_id") != SEARCH_SCHEMA_ID:
        gate.block(
            "GATE-IPC-003",
            f"search-query.json 的 schema_id 不是 {SEARCH_SCHEMA_ID}",
            "使用当前 generate_search_query.py 重新生成。",
        )
    if candidate_manifest.get("schema_id") != TEMPLATE_CANDIDATES_SCHEMA_ID:
        gate.block(
            "GATE-IPC-003",
            f"范本候选清单 schema_id 不是 {TEMPLATE_CANDIDATES_SCHEMA_ID}",
            "按 v1 候选合同重建 template-candidates.json。",
        )

    target = selection.get("target_ipc") or {}
    target_codes = target.get("ipc_codes")
    search_target = search_query.get("target_ipc") or {}
    if target.get("status") != "determined" or not isinstance(target_codes, list) or not target_codes:
        recommended = []
        if search_target.get("ipc_codes"):
            recommended.extend(search_target.get("ipc_codes"))
        for cand in candidate_manifest.get("candidates", candidate_manifest.get("shortlist", [])) or []:
            if isinstance(cand, dict) and cand.get("ipc_codes"):
                recommended.extend(cand.get("ipc_codes"))

        if recommended:
            adopted = f"采用推荐 IPC {recommended[0]} 作为 provisional"
        else:
            adopted = "记录无 IPC，继续"

        gate.pending({
            "key": "ipc.target_pending_determination",
            "source": {"tool_id": "check_stage_gate", "rule_id": "GATE-IPC-004"},
            "target": {"kind": "process", "locator": "template_selection"},
            "question": "目标 IPC 未处于 determined 状态，需确认 IPC",
            "adopted_default": adopted,
            "options": ["确认 provisional IPC", "补充人工指定"],
            "impact": ["grant_risk"],
            "decider": "attorney"
        })
        gate.note("GATE-IPC-004", f"目标技术方案 IPC 未处于 determined 状态，产生待决项，{adopted}。")
    elif search_target.get("status") != "determined" or search_target.get("ipc_codes") != target_codes:
        gate.block(
            "GATE-IPC-004",
            "范本选择报告中的目标 IPC 与当前 search-query.json 不一致",
            "不得手改选择报告；应从当前 search-query.json 重新运行排名脚本。",
        )

    weights = selection.get("weights") or {}
    weight_fields = (
        "technical_relevance",
        "ipc_similarity",
        "applicant_quality",
        "agency_quality",
    )
    raw_weights = {field: weights.get(field) for field in weight_fields}
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
        for value in raw_weights.values()
    ):
        gate.block(
            "GATE-IPC-005",
            "范本综合评分的四项权重缺失或不是非负数值",
            "重新运行 rank_template_candidates.py 生成 v2 选择报告。",
        )
    elif (
        raw_weights["technical_relevance"] <= 0
        or raw_weights["ipc_similarity"] <= 0
        or abs(sum(float(value) for value in raw_weights.values()) - 1.0) > 1e-6
    ):
        gate.block(
            "GATE-IPC-005",
            "IPC 相似度或技术相关性未以正权重进入范本综合评分，或四项权重之和不为 1",
            "重新运行 rank_template_candidates.py，并保留技术相关性与 ipc_similarity 正权重。",
        )
    ipc_weight = raw_weights["ipc_similarity"]
    technical_weight = raw_weights["technical_relevance"]
    applicant_weight = raw_weights["applicant_quality"]
    agency_weight = raw_weights["agency_quality"]

    policy = selection.get("classification_policy") or {}
    if policy.get("preferred_provider") != "epo_ops":
        gate.block(
            "GATE-IPC-006",
            "候选 IPC 获取策略未把 EPO OPS 列为首选来源",
            "将 preferred_provider 设置为 epo_ops；失败时再降级并记录原因。",
        )

    candidates = selection.get("candidates")
    selected = selection.get("selected")
    if not isinstance(candidates, list) or not isinstance(selected, dict):
        gate.block("GATE-IPC-007", "范本选择报告缺少候选或最终选择", "重新生成选择报告。")
        return

    manifest_candidates = candidate_manifest.get("candidates", candidate_manifest.get("shortlist"))
    manifest_numbers = {
        item.get("publication_number")
        for item in manifest_candidates or []
        if isinstance(item, dict) and isinstance(item.get("publication_number"), str)
    }
    manifest_by_number = {
        item.get("publication_number"): item
        for item in manifest_candidates or []
        if isinstance(item, dict) and isinstance(item.get("publication_number"), str)
    }
    report_numbers = {
        item.get("publication_number")
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("publication_number"), str)
    }
    if not manifest_numbers or manifest_numbers != report_numbers:
        gate.block(
            "GATE-IPC-007",
            "范本选择报告的候选公开号集合与当前候选清单不一致",
            "从当前候选清单重新运行 rank_template_candidates.py。",
        )

    def entity_score(item: dict[str, Any], key: str) -> Any:
        entity = item.get("entity_quality") or {}
        entry = entity.get(key) or {}
        return entry.get("score") if isinstance(entry, dict) else None

    recomputed: list[tuple[float, str]] = []
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            gate.block("GATE-IPC-009", f"第 {index} 个候选不是对象", "重新生成选择报告。")
            continue
        number = item.get("publication_number")
        technical_score = item.get("technical_relevance_score")
        similarity = (item.get("ipc_similarity") or {}).get("score")
        weighted_score = item.get("weighted_score")
        applicant_score = entity_score(item, "applicant")
        agency_score = entity_score(item, "agency")
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in (
                technical_score, similarity, weighted_score, applicant_score, agency_score,
            )
        ):
            gate.block(
                "GATE-IPC-009",
                f"第 {index} 个候选缺少可复算的评分字段（含申请人/代理机构质量分）",
                "重新运行 rank_template_candidates.py 生成含 entity_quality 的报告。",
            )
            continue
        expected_score = (
            float(technical_weight) * float(technical_score)
            + float(ipc_weight) * float(similarity)
            + float(applicant_weight) * float(applicant_score)
            + float(agency_weight) * float(agency_score)
        )
        if abs(expected_score - float(weighted_score)) > 1e-6:
            gate.block(
                "GATE-IPC-009",
                f"候选 {number} 的加权得分不可复算（技术/IPC/申请人/代理机构四项）",
                "不得手改得分；重新运行 rank_template_candidates.py。",
            )
        manifest_item = manifest_by_number.get(number)
        if isinstance(manifest_item, dict):
            manifest_applicant = manifest_item.get("applicant")
            manifest_fields = ("applicant", "agency")
            if not (isinstance(manifest_applicant, str) and manifest_applicant.strip()):
                manifest_fields = ("assignee", "agency")
            for field in manifest_fields:
                expected_name = manifest_item.get(field)
                if not isinstance(expected_name, str) or not expected_name.strip():
                    continue
                reported_name = (item.get("entity_quality") or {}).get(
                    "agency" if field == "agency" else "applicant"
                ) or {}
                actual_name = reported_name.get("name") if isinstance(reported_name, dict) else None
                if actual_name != expected_name.strip():
                    gate.block(
                        "GATE-IPC-014",
                        f"候选 {number} 的{('申请人' if field != 'agency' else '代理机构')}"
                        f"著录与当前候选清单不一致（报告：{actual_name}；清单：{expected_name.strip()}）",
                        "不得手改主体名称；从当前候选清单重新运行 rank_template_candidates.py。",
                    )
        if item.get("eligible") is not False and item.get("ipc_status") == "resolved":
            recomputed.append((expected_score, str(item.get("publication_number"))))
        attempts = item.get("classification_attempts")
        first_attempt = attempts[0] if isinstance(attempts, list) and attempts else {}
        if first_attempt.get("provider") != "epo_ops":
            gate.block(
                "GATE-IPC-010",
                f"候选 {item.get('publication_number')} 没有首先尝试 EPO OPS",
                "逐篇候选必须先尝试 EPO OPS，再记录降级来源。",
            )

    recommended = selection.get("recommended") or {}
    if recomputed:
        expected_recommended = max(recomputed, key=lambda pair: (pair[0], pair[1]))[1]
        if recommended.get("publication_number") != expected_recommended:
            gate.block(
                "GATE-IPC-009",
                "recommended 不是按当前权重复算得到的最高候选",
                "重新运行 rank_template_candidates.py。",
            )

    number = selected.get("publication_number")
    chosen = next(
        (item for item in candidates if isinstance(item, dict) and item.get("publication_number") == number),
        None,
    )
    if not isinstance(number, str) or chosen is None:
        gate.block("GATE-IPC-007", "最终选择未绑定候选清单中的公开号", "重新生成选择报告。")
        return
    if chosen.get("ipc_status") != "resolved" or not chosen.get("ipc_codes"):
        gate.block(
            "GATE-IPC-008",
            f"选定范本 {number} 没有可核对的逐篇 IPC 分类号",
            "优先调用 EPO OPS；失败后使用有来源记录的分类缓存或候选输入。",
        )
    match = chosen.get("ipc_similarity") or {}
    if not isinstance(match.get("score"), (int, float)) or match.get("score") < 0:
        gate.block("GATE-IPC-009", f"选定范本 {number} 缺少 IPC 相似度评分", "重新生成选择报告。")

    attempts = chosen.get("classification_attempts")
    first = attempts[0] if isinstance(attempts, list) and attempts else {}
    if first.get("provider") != "epo_ops":
        gate.block(
            "GATE-IPC-010",
            f"选定范本 {number} 没有留下 EPO OPS 优先尝试记录",
            "候选 IPC 必须先尝试 EPO OPS，再记录降级来源。",
        )
    elif chosen.get("classification_source") != "epo_ops":
        gate.note(
            "GATE-IPC-010",
            f"选定范本 {number} 的 EPO OPS 尝试状态为 {first.get('status')}，"
            f"已降级到 {chosen.get('classification_source')}。",
        )

    if chosen is not None:
        if selected.get("weighted_score") != chosen.get("weighted_score"):
            gate.block(
                "GATE-IPC-009",
                f"最终选择 {number} 的得分与候选记录不一致",
                "重新运行 rank_template_candidates.py。",
            )
        if selected.get("ipc_codes") != chosen.get("ipc_codes"):
            gate.block(
                "GATE-IPC-009",
                f"最终选择 {number} 的 IPC 与候选记录不一致",
                "不得手改选定结果；重新运行排名脚本。",
            )

    chosen_entity = chosen.get("entity_quality") or {}
    missing_entities = [
        label for key, label in (("applicant", "申请人"), ("agency", "代理机构"))
        if ((chosen_entity.get(key) or {}).get("status") == "missing")
        or not isinstance(chosen_entity.get(key), dict)
    ]
    if missing_entities:
        gate.pending({
            "key": "template.entity_evidence_missing",
            "source": {"tool_id": "check_stage_gate", "rule_id": "GATE-IPC-015"},
            "target": {"kind": "process", "locator": "template_selection"},
            "question": f"选定范本 {number} 缺少{'、'.join(missing_entities)}著录，主体质量分为 0",
            "adopted_default": "按现有主体信息继续",
            "options": ["补齐申请人/代理机构后重跑排序", "确认无法获取并继续"],
            "impact": ["grant_risk"],
            "decider": "attorney"
        })
        gate.note(
            "GATE-IPC-015",
            f"选定范本 {number} 缺少{'、'.join(missing_entities)}著录，"
            "申请人/代理机构质量分为 0，排序已退化为技术相关性 + IPC，产生待决项并继续。",
        )

    if selected.get("override_recommended") and not str(selected.get("selection_reason", "")).strip():
        gate.pending({
            "key": "template.override_reason_pending",
            "source": {"tool_id": "check_stage_gate", "rule_id": "GATE-IPC-011"},
            "target": {"kind": "process", "locator": "template_selection"},
            "question": "人工偏离 IPC 推荐结果，是否补充理由？",
            "adopted_default": "沿用人工选定继续",
            "options": ["沿用人工选定", "补充选择理由"],
            "impact": ["grant_risk"],
            "decider": "attorney"
        })
        gate.note("GATE-IPC-011", "人工偏离 IPC 加权推荐结果却没有选择理由，产生待决项，沿用人工选定继续。")

    guide_patents: set[str] = set()
    for path in guides:
        try:
            guide, _ = load_json(path, "template-style-guide.json")
        except GateError as exc:
            gate.block("GATE-IPC-012", str(exc), "重新生成范本风格指南。")
            continue
        patent = guide.get("template_patent")
        if isinstance(patent, str):
            guide_patents.update(part.strip() for part in patent.split("+") if part.strip())
    if number not in guide_patents:
        gate.block(
            "GATE-IPC-012",
            f"IPC 加权选择的范本 {number} 未出现在已确认的风格指南中",
            "使用选定范本生成 template-style-guide.json，或重做最终选择。",
        )
    else:
        applicant_info = chosen_entity.get("applicant") or {}
        agency_info = chosen_entity.get("agency") or {}
        gate.note(
            "GATE-IPC-013",
            f"目标 IPC {target_codes}；选定范本 {number} IPC {chosen.get('ipc_codes')}；"
            f"相似度 {match.get('score')}（{match.get('level')}）；"
            f"申请人 {applicant_info.get('name') or '未记录'}（{applicant_info.get('status')}，"
            f"{applicant_info.get('score')}）；代理机构 {agency_info.get('name') or '未记录'}"
            f"（{agency_info.get('status')}，{agency_info.get('score')}）；"
            f"权重 技术 {technical_weight}／IPC {ipc_weight}／申请人 {applicant_weight}／"
            f"代理机构 {agency_weight}。",
        )


def check_style_brief(state: dict[str, Any], gate: Gate, workspace: Path, guides: list[Path]) -> None:
    brief_path_raw = state.get("style_brief_path")
    if not isinstance(brief_path_raw, str) or not brief_path_raw.strip():
        gate.block(
            "GATE-BRIEF-001",
            "未登记 style_brief_path",
            "运行 style_applicator.py 生成 style-brief.json 并在此登记路径",
        )
        return

    brief_path = (workspace / brief_path_raw).resolve()
    if not brief_path.is_file():
        gate.block(
            "GATE-BRIEF-001",
            f"style-brief.json 不存在：{brief_path_raw}",
            "运行 style_applicator.py 生成起草风格简报",
        )
        return

    try:
        brief, _ = load_json(brief_path, "style-brief.json")
    except GateError as exc:
        gate.block("GATE-BRIEF-002", str(exc), "重新生成 style-brief.json")
        return

    if brief.get("schema_id") != STYLE_BRIEF_SCHEMA_ID:
        gate.block(
            "GATE-BRIEF-002",
            f"style-brief.json 的 schema_id 不是 {STYLE_BRIEF_SCHEMA_ID}",
            "用当前版本的 style_applicator.py 重新生成",
        )
        return

    source_mode = (brief.get("source") or {}).get("mode")
    if guides and source_mode != "template":
        gate.block(
            "GATE-BRIEF-003",
            "已确认范本，但 style-brief.json 的来源模式是默认策略",
            "用确认的 template-style-guide.json 重新生成简报；确认过范本却按默认策略起草，"
            "等于范本学习结果没有进入起草",
        )
    if not guides and source_mode == "template":
        gate.block(
            "GATE-BRIEF-003",
            "未确认范本，style-brief.json 却声明来源于范本",
            "核对范本确认状态与简报来源；两者必须一致",
        )

    embodiments = (brief.get("specification") or {}).get("embodiments") or {}
    if "organization" not in embodiments:
        gate.block(
            "GATE-BRIEF-004",
            "style-brief.json 缺少实施例组织方式 organization",
            "用当前版本的 style_applicator.py 重新生成；只有实施例数量而没有组织方式，"
            "会把单一实施方式的范本误拆成多个平行实施例",
        )
    for warning in brief.get("warnings") or []:
        gate.note("GATE-BRIEF-005", f"风格简报警告：{warning}")


def check_ledger(state: dict[str, Any], gate: Gate, workspace: Path) -> None:
    ledger_raw = state.get("feature_ledger_path")
    if not isinstance(ledger_raw, str) or not ledger_raw.strip():
        gate.block(
            "GATE-LEDGER-001",
            "未登记 feature_ledger_path",
            "先建立区别特征表 feature-ledger.json；权利要求、说明书和附图必须由它派生",
        )
        return
    ledger_path = (workspace / ledger_raw).resolve()
    if not ledger_path.is_file():
        gate.block(
            "GATE-LEDGER-001",
            f"区别特征表不存在：{ledger_raw}",
            "先建立 feature-ledger.json 再进入起草",
        )
        return
    try:
        ledger, _ = load_json(ledger_path, "feature-ledger.json")
    except GateError as exc:
        gate.block("GATE-LEDGER-002", str(exc), "修正区别特征表")
        return
    expected_ledger_schema = (
        "cn-patent-feature-ledger/v2"
        if state.get("schema_id") == SCHEMA_ID_V2
        else "cn-patent-feature-ledger/v1"
    )
    if ledger.get("schema_id") != expected_ledger_schema:
        gate.block(
            "GATE-LEDGER-002",
            f"feature-ledger.json 的 schema_id 不是 {expected_ledger_schema}",
            "新案件按 v2 关系台账重建；v1 仅用于旧案件回放",
        )
        return
    features = ledger.get("features")
    if not isinstance(features, list) or not features:
        gate.block("GATE-LEDGER-003", "区别特征表没有任何特征", "登记全案技术特征后再进入起草")
        return
    distinguishing = [
        f for f in features
        if isinstance(f, dict) and f.get("classification") == "distinguishing"
    ]
    if not distinguishing:
        gate.block(
            "GATE-LEDGER-004",
            "区别特征表中没有任何区别特征",
            "标注区别特征；全部特征均与最接近现有技术共有意味着不存在保护边界",
        )
    else:
        gate.note(
            "GATE-LEDGER-004",
            f"区别特征表登记 {len(features)} 项特征，其中区别特征 {len(distinguishing)} 项",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="阶段 2 到阶段 3 的阶段门校验")
    parser.add_argument("--state", required=True, help="stage2-gate.json 路径")
    parser.add_argument("--workspace", help="相对路径的解析基准目录；默认取 state 文件所在目录")
    parser.add_argument("--output", required=True, help="阶段门报告 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_path = Path(args.state)
    try:
        state, raw = load_json(state_path, "阶段门状态")
    except GateError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    if state.get("schema_id") not in SUPPORTED_SCHEMA_IDS:
        print(
            "错误：schema_id 必须是 " + " 或 ".join(sorted(SUPPORTED_SCHEMA_IDS)),
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR

    workspace = Path(args.workspace).resolve() if args.workspace else state_path.resolve().parent

    gate = Gate()
    try:
        check_search(state, gate)
        guides = check_template(state, gate, workspace)
        check_template_ipc_selection(state, gate, workspace, guides)
        check_style_brief(state, gate, workspace, guides)
        check_ledger(state, gate, workspace)
    except GateError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    decision = "BLOCKED" if gate.blocks else ("CLEARED_WITH_PENDING" if gate.pending_decisions else "CLEARED")
    payload = {
        "schema_id": REPORT_SCHEMA_ID,
        "legal_effect": "ADVISORY_ONLY",
        "decision": decision,
        "state_sha256": hashlib.sha256(raw).hexdigest(),
        "boundary": (
            "阶段门只校验流程状态位是否齐备与自洽，不判断检索质量、范本适配度或申请文件内容。"
            "CLEARED 只表示允许进入阶段 3，不代表检索充分或范本选择正确。"
        ),
        "blocks": gate.blocks,
        "notes": gate.notes,
        "pending_decisions": gate.pending_decisions,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    status_str = 'BLOCKED' if gate.blocks else ('PENDING' if gate.pending_decisions else 'OK')
    print(f"[{status_str}] 阶段门报告：{output_path}")
    for pending in gate.pending_decisions:
        print(f"[PENDING] {pending['key']}：{pending['question']}")
    for note in gate.notes:
        print(f"[INFO] {note['gate_id']}：{note['message']}")
    for block in gate.blocks:
        print(f"[BLOCK] {block['gate_id']}：{block['reason']}")
        print(f"        补救：{block['remedy']}")

    if gate.blocks:
        print("[BLOCKED] 阶段门未通过，不得开始撰写权利要求与说明书。", file=sys.stderr)
        return EXIT_BLOCKED
    print(f"[{'PENDING' if gate.pending_decisions else 'OK'}] 阶段门通过，可进入阶段 3。")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
