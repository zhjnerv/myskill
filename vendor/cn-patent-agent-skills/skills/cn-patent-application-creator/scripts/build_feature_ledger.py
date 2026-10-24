#!/usr/bin/env python3
"""区别特征表：技术特征在权利要求、说明书与附图之间的四向对账。

问题背景：权利要求、说明书和附图各自持有一份技术事实副本，彼此只靠散文
连接。范本学习、检索边界和起草三段各自记一套特征编号，谁也对不上谁。本
脚本把全案技术特征收敛为唯一台账（v1 兼容、v2 为新案件默认），并做四向
对账：

  台账 -> 权利要求   登记的落点在权利要求原文中确实存在
  权利要求 -> 台账   权利要求实际出现的项号都被登记过
  台账 -> 说明书     每个特征在说明书有可检索到的落点
  台账 -> 附图       component 标记进附图标记清单、step 标记不进；
                     附图标记清单与台账互为全集

脚本只做可复算的文本定位与集合运算。命中不等于得到支持，未命中也不等于
缺乏支持——法律判断由 REVIEW_REQUIRED 承载，不由本脚本给出。

退出码：0 工具成功执行；2 存在 DETERMINISTIC_FAIL；3 输入/路径/编码/JSON 无效。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from cn_drafting_io import DraftingOutputGuard

SCHEMA_ID = "cn-patent-feature-ledger/v1"
SCHEMA_ID_V2 = "cn-patent-feature-ledger/v2"
SUPPORTED_SCHEMA_IDS = {SCHEMA_ID, SCHEMA_ID_V2}
REPORT_SCHEMA_ID = "cn-patent-feature-ledger-report/v2"
LEGAL_EFFECT = "ADVISORY_ONLY"

EXIT_OK = 0
EXIT_DETERMINISTIC_FAIL = 2
EXIT_INPUT_ERROR = 3

FEATURE_ID_RE = re.compile(r"^F\d{3}$")
CLAIM_HEAD_RE = re.compile(r"^\s*(\d+)\s*[.、．]\s*(.+)$")
REFERENCE_LIST_RE = re.compile(r"图\s*中\s*[：:](.+?)。", re.S)
REFERENCE_ITEM_RE = re.compile(r"(\d+)\s*[-−–]\s*([^、。]+)")
SECTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(技术领域|背景技术|发明内容|附图说明|具体实施方式)\s*$",
    re.MULTILINE,
)

CLASSIFICATION_LABEL = {
    "preamble": "前序（共有）",
    "distinguishing": "区别特征",
    "fallback_only": "仅说明书（33条弹药）",
}
PRIOR_ART_LABEL = {
    "disclosed": "已被公开",
    "partially_disclosed": "部分公开",
    "not_found_in_searched_outlets": "已检索出口未发现",
    "not_searched": "未检索",
}

# CN-LEDGER-ABSTRACT-001 —— 限定成分标记（仅句法结构性词汇，禁止任何具体技术领域的机制名词）
QUALIFIER_MARKERS: list[str] = [
    # 条件／时序（不收录“当/若/在/与/由/随”这类单字，几乎任何中文句子都会命中）
    "仅当", "仅在", "之后", "之前", "时才", "情况下", "条件下",
    "满足", "触发", "响应于", "直到",
    # 关系／位置
    "位于", "设置于", "连接于", "固定于", "之间", "对应", "绑定",
    "依赖", "基于", "根据", "决定", "变化",
    # 数值用词（正则单独处理，见下方 _NUMERIC_RE）
    "范围", "区间", "不超过", "不小于", "不大于", "不低于",
    "大于", "小于", "等于", "介于",
]

# 数值区间正则：数字后跟单位或区间词
_NUMERIC_RE = re.compile(
    r"\d+(\.\d+)?\s*(%|℃|°|mm|cm|m|s|ms|Hz|kHz|MHz|V|A|W|Pa|MPa|kPa|mol|g|kg|L|mL"
    r"|倍|次|个|项|级|以上|以下|以内|之间|至|到|~|—|-)"
)

# 多量绑定正则：同句中两个及以上"所述 X"由连接词串联
_MULTI_SUOSHU_RE = re.compile(r"所述\S+.*?(?:与|及|和|并|且).*?所述\S+")


class LedgerError(ValueError):
    """输入不符合 v1 台账合同时抛出。"""


def normalize(text: str) -> str:
    """NFKC 归一并压掉全部空白，避免全半角与换行造成的假阴性。"""

    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def read_text(path: Path, label: str) -> str:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise LedgerError(f"{label}文件不存在：{path}") from exc
    except OSError as exc:
        raise LedgerError(f"{label}文件不可读：{path}（{exc}）") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise LedgerError(f"{label}含 BOM，必须使用 UTF-8 无 BOM：{path}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerError(f"{label}不是有效 UTF-8：{path}") from exc


def load_ledger(path: Path) -> dict[str, Any]:
    text = read_text(path, "区别特征表")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"区别特征表 JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise LedgerError("区别特征表必须是对象")
    if data.get("schema_id") not in SUPPORTED_SCHEMA_IDS:
        raise LedgerError(f"schema_id 必须是 {SCHEMA_ID} 或 {SCHEMA_ID_V2}")
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise LedgerError("features 必须是非空数组")

    seen: set[str] = set()
    for index, feature in enumerate(features, start=1):
        if not isinstance(feature, dict):
            raise LedgerError(f"第 {index} 个特征必须是对象")
        fid = feature.get("feature_id")
        if not isinstance(fid, str) or not FEATURE_ID_RE.match(fid):
            raise LedgerError(f"第 {index} 个特征的 feature_id 必须形如 F001")
        if fid in seen:
            raise LedgerError(f"特征编号重复：{fid}")
        seen.add(fid)
        for field in ("name", "statement", "classification"):
            if not isinstance(feature.get(field), str) or not feature[field].strip():
                raise LedgerError(f"特征 {fid} 的 {field} 必须是非空字符串")
        if feature["classification"] not in CLASSIFICATION_LABEL:
            raise LedgerError(f"特征 {fid} 的 classification 非法：{feature['classification']}")
        if not isinstance(feature.get("evidence"), list) or not feature["evidence"]:
            raise LedgerError(f"特征 {fid} 必须提供至少一条实现证据 evidence")
        if not isinstance(feature.get("spec_sites"), list) or not feature["spec_sites"]:
            raise LedgerError(f"特征 {fid} 必须提供至少一个说明书落点 spec_sites")
        for key in ("claim_sites", "drawing_sites"):
            if key in feature and not isinstance(feature[key], list):
                raise LedgerError(f"特征 {fid} 的 {key} 必须是数组")

    if data["schema_id"] == SCHEMA_ID_V2:
        _validate_v2_shape(data)
    return data


def _require_string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "非空数组" if not allow_empty else "数组"
        raise LedgerError(f"{label} 必须是{qualifier}")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise LedgerError(f"{label} 的每一项必须是非空字符串")
    if len(set(value)) != len(value):
        raise LedgerError(f"{label} 不得包含重复项")
    return value


def _validate_v2_shape(data: dict[str, Any]) -> None:
    """校验 v2 的结构字段；跨对象引用由后续可报告检查处理。"""

    phases = {"preconfigured", "runtime_input", "runtime_processing", "runtime_output", "postprocessing"}
    for feature in data["features"]:
        fid = feature["feature_id"]
        flow = feature.get("flow")
        if not isinstance(flow, dict):
            raise LedgerError(f"特征 {fid} 缺少 flow 对象")
        if flow.get("action_phase") not in phases:
            raise LedgerError(f"特征 {fid} 的 flow.action_phase 非法")
        for field in ("input_objects", "output_objects", "downstream_feature_ids", "exception_path_ids"):
            _require_string_list(flow.get(field), f"特征 {fid} 的 flow.{field}")
        for field in ("processing_actor", "action"):
            if not isinstance(flow.get(field), str) or not flow[field].strip():
                raise LedgerError(f"特征 {fid} 的 flow.{field} 必须是非空字符串")
        for site in feature.get("claim_sites") or []:
            if site.get("claim_type") not in {"method", "system", "device", "medium", "other"}:
                raise LedgerError(f"特征 {fid} 的 claim_sites.claim_type 非法")
            if site.get("execution_role") not in {"precondition", "runtime_step", "module", "result", "storage", "limitation"}:
                raise LedgerError(f"特征 {fid} 的 claim_sites.execution_role 非法")
            if site.get("execution_role") == "module" and not str(site.get("actor", "")).strip():
                raise LedgerError(f"特征 {fid} 的系统模块落点必须填写 actor")

    flows = data.get("claim_data_flows")
    if not isinstance(flows, list) or not flows:
        raise LedgerError("v2 claim_data_flows 必须是非空数组")
    for index, flow in enumerate(flows, start=1):
        if not isinstance(flow, dict):
            raise LedgerError(f"第 {index} 个 claim_data_flow 必须是对象")
        if not isinstance(flow.get("claim_number"), int) or isinstance(flow.get("claim_number"), bool):
            raise LedgerError(f"第 {index} 个 claim_data_flow.claim_number 必须是整数")
        if flow.get("claim_type") not in {"method", "system", "device", "medium", "other"}:
            raise LedgerError(f"第 {index} 个 claim_data_flow.claim_type 非法")
        for field in ("entry_feature_ids", "ordered_feature_ids", "normal_exit_feature_ids"):
            _require_string_list(flow.get(field), f"claim{flow.get('claim_number')} 的 {field}", allow_empty=False)
        for field in ("merge_feature_ids", "exception_path_ids", "storage_feature_ids"):
            _require_string_list(flow.get(field), f"claim{flow.get('claim_number')} 的 {field}")

    pairs = data.get("method_system_pairs")
    if not isinstance(pairs, list):
        raise LedgerError("v2 method_system_pairs 必须是数组")
    for index, pair in enumerate(pairs, start=1):
        if not isinstance(pair, dict):
            raise LedgerError(f"第 {index} 个 method_system_pair 必须是对象")
        for field in ("method_claim_number", "system_claim_number"):
            if not isinstance(pair.get(field), int) or isinstance(pair.get(field), bool):
                raise LedgerError(f"第 {index} 个 method_system_pair.{field} 必须是整数")
        _require_string_list(pair.get("required_feature_ids"), f"第 {index} 个 method_system_pair.required_feature_ids", allow_empty=False)

    paths = data.get("exception_paths")
    if not isinstance(paths, list):
        raise LedgerError("v2 exception_paths 必须是数组")
    seen_paths: set[str] = set()
    for index, path in enumerate(paths, start=1):
        if not isinstance(path, dict):
            raise LedgerError(f"第 {index} 个 exception_path 必须是对象")
        path_id = path.get("path_id")
        if not isinstance(path_id, str) or not re.fullmatch(r"E\d{3}", path_id) or path_id in seen_paths:
            raise LedgerError(f"第 {index} 个 exception_path.path_id 必须形如 E001 且唯一")
        seen_paths.add(path_id)
        for field in ("trigger", "terminal_state", "reason_code"):
            if not isinstance(path.get(field), str) or not path[field].strip():
                raise LedgerError(f"异常路径 {path_id} 的 {field} 必须是非空字符串")
        _require_string_list(path.get("action_feature_ids"), f"异常路径 {path_id} 的 action_feature_ids", allow_empty=False)
        _require_string_list(path.get("stored_fields"), f"异常路径 {path_id} 的 stored_fields", allow_empty=False)
        _require_string_list(path.get("drawing_relation_ids"), f"异常路径 {path_id} 的 drawing_relation_ids")
        if not isinstance(path.get("produces_value"), bool):
            raise LedgerError(f"异常路径 {path_id} 的 produces_value 必须是布尔值")
        if path.get("confidence") not in {"not_applicable", "high", "medium", "low", "unknown"}:
            raise LedgerError(f"异常路径 {path_id} 的 confidence 非法")
        if not isinstance(path.get("claim_sites"), list) or not path["claim_sites"]:
            raise LedgerError(f"异常路径 {path_id} 必须登记 claim_sites")
        if not isinstance(path.get("spec_sites"), list) or not path["spec_sites"]:
            raise LedgerError(f"异常路径 {path_id} 必须登记 spec_sites")


def parse_claims(text: str) -> dict[int, str]:
    """把权利要求书切成 {项号: 正文}。跨行的权利要求归入其编号行。"""

    claims: dict[int, str] = {}
    current: int | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = CLAIM_HEAD_RE.match(line)
        if match:
            if current is not None:
                claims[current] = "\n".join(buffer).strip()
            current = int(match.group(1))
            if current in claims:
                raise LedgerError(f"权利要求书出现重复项号：{current}")
            buffer = [match.group(2)]
        elif current is not None and line.strip():
            buffer.append(line)
    if current is not None:
        claims[current] = "\n".join(buffer).strip()
    return claims


def split_sections(text: str) -> dict[str, str]:
    """按五个法定章节切分说明书。缺章节由形式检查器负责，此处只取存在的。"""

    marks = [(m.group(1), m.start(), m.end()) for m in SECTION_RE.finditer(text)]
    sections: dict[str, str] = {}
    for index, (name, _start, end) in enumerate(marks):
        stop = marks[index + 1][1] if index + 1 < len(marks) else len(text)
        sections[name] = text[end:stop]
    return sections


def parse_reference_list(spec_text: str) -> dict[str, str]:
    """解析"图中：100-xxx、110-yyy。"单段附图标记清单。"""

    match = REFERENCE_LIST_RE.search(spec_text)
    if not match:
        return {}
    return {
        num: name.strip()
        for num, name in REFERENCE_ITEM_RE.findall(match.group(1))
    }


class Report:
    """收集 finding 并保持 ID 稳定。"""

    def __init__(self) -> None:
        self.findings: list[dict[str, Any]] = []
        self.pending_decisions: list[dict[str, Any]] = []

    def add(
        self,
        rule_id: str,
        target: str,
        status: str,
        problem: str,
        remedy: str,
    ) -> None:
        self.findings.append(
            {
                "finding_id": f"FL{len(self.findings) + 1:04d}",
                "rule_id": rule_id,
                "target_id": target,
                "status": status,
                "problem": problem,
                "remedy": remedy,
            }
        )

    def pending(self, decision: dict[str, Any]) -> None:
        self.pending_decisions.append(decision)

    def fail(self, rule_id: str, target: str, problem: str, remedy: str) -> None:
        self.add(rule_id, target, "DETERMINISTIC_FAIL", problem, remedy)

    def review(self, rule_id: str, target: str, problem: str, remedy: str) -> None:
        self.add(rule_id, target, "REVIEW_REQUIRED", problem, remedy)


def _has_qualifier(statement: str) -> bool:
    """判断 statement 是否含有限定成分标记（句法结构启发式）。

    规则：命中 QUALIFIER_MARKERS 中任意词、_NUMERIC_RE 数值区间、或
    _MULTI_SUOSHU_RE 多量绑定即视为有限定成分，返回 True；否则返回 False。

    设计约束：
    - 判句法结构，不判词表；不得为特定领域加机制名词。
    - 这是启发式，误报走 REVIEW_REQUIRED 由人工判断。
    """
    if any(marker in statement for marker in QUALIFIER_MARKERS):
        return True
    if _NUMERIC_RE.search(statement):
        return True
    if _MULTI_SUOSHU_RE.search(statement):
        return True
    return False


def check_classification(ledger: dict[str, Any], report: Report) -> None:
    """分类与落点必须自洽，且必须存在至少一个区别特征。"""

    distinguishing = 0
    for feature in ledger["features"]:
        fid = feature["feature_id"]
        classification = feature["classification"]
        sites = feature.get("claim_sites") or []
        if classification == "fallback_only" and sites:
            report.fail(
                "CN-LEDGER-CLASS-001",
                fid,
                f"特征 {fid} 标为 fallback_only 却登记了权利要求落点",
                "改为 preamble 或 distinguishing，或清空 claim_sites",
            )
        if classification in {"preamble", "distinguishing"} and not sites:
            report.fail(
                "CN-LEDGER-CLASS-001",
                fid,
                f"特征 {fid} 标为 {classification} 却没有任何权利要求落点",
                "补登 claim_sites，或降级为 fallback_only",
            )
        for site in sites:
            part = site.get("part")
            if classification == "preamble" and part != "preamble":
                report.fail(
                    "CN-LEDGER-CLASS-002",
                    f"{fid}@claim{site.get('claim_number')}",
                    f"特征 {fid} 是前序特征，却被登记在权利要求特征部分",
                    "把该特征移入前序部分，或重新判定其分类",
                )
            if classification == "distinguishing" and part == "preamble":
                report.fail(
                    "CN-LEDGER-CLASS-002",
                    f"{fid}@claim{site.get('claim_number')}",
                    f"特征 {fid} 是区别特征，却被登记在权利要求前序部分",
                    "把该特征移入特征部分，或重新判定其分类",
                )
        if classification == "distinguishing":
            distinguishing += 1
            if not str(feature.get("technical_effect", "")).strip():
                report.review(
                    "CN-LEDGER-EFFECT-001",
                    fid,
                    f"区别特征 {fid} 未记载技术效果",
                    "补写该区别特征实际带来的技术效果；三步法第二步据此重述实际解决的技术问题",
                )
                report.pending({
                    "key": "ledger.technical_effect_missing",
                    "source": {"tool_id": "build_feature_ledger", "rule_id": "CN-LEDGER-EFFECT-001"},
                    "target": {"kind": "ledger", "locator": fid},
                    "question": f"区别特征 {fid} 缺少技术效果，是否需补充？",
                    "adopted_default": "留空继续",
                    "options": ["补充技术效果", "确认留空"],
                    "impact": ["grant_risk"],
                    "decider": "inventor"
                })
            verdict = (feature.get("prior_art_status") or {}).get("verdict")
            if verdict == "disclosed":
                report.fail(
                    "CN-LEDGER-PRIOR-001",
                    fid,
                    f"特征 {fid} 被判定为已被现有技术公开，却仍作为区别特征",
                    "将该特征改判为 preamble，或将其限定到一个未被公开的子区间/更具体的实现",
                )
            if verdict in (None, "not_searched"):
                report.review(
                    "CN-LEDGER-PRIOR-002",
                    fid,
                    f"区别特征 {fid} 没有检索判定，可能无法支撑创造性论证",
                    "补充 prior_art_status.verdict；目前暂视为未检索继续对账",
                )
                report.pending({
                    "key": "ledger.prior_art_verdict_missing",
                    "source": {"tool_id": "build_feature_ledger", "rule_id": "CN-LEDGER-PRIOR-002"},
                    "target": {"kind": "ledger", "locator": fid},
                    "question": f"区别特征 {fid} 没有检索判定，是否补充？",
                    "adopted_default": "按 distinguishing 参与对账，prior_art_status.effective_verdict='not_searched'",
                    "options": ["补充判定", "视为未检索保留"],
                    "impact": ["grant_risk"],
                    "decider": "attorney"
                })
            statement = str(feature.get("statement", "")).strip()
            if not _has_qualifier(statement):
                report.review(
                    "CN-LEDGER-ABSTRACT-001",
                    fid,
                    f"区别特征 {fid} 的表述只是部件/步骤/组分/机制的名称，缺少条件、位置关系、参数区间、绑定或时序限定",
                    "改写为“条件 + 动作”“绑定集合”或“位置关系 + 作用”形式，或改判 preamble；"
                    "参见 references/distinguishing-feature-patterns.md",
                )
                report.pending({
                    "key": "ledger.statement_too_abstract",
                    "source": {"tool_id": "build_feature_ledger", "rule_id": "CN-LEDGER-ABSTRACT-001"},
                    "target": {"kind": "ledger", "locator": fid},
                    "question": f"区别特征 {fid} 的表述可能过于宽泛/抽象，是否修改？",
                    "adopted_default": "原样保留继续对账",
                    "options": ["修改表述", "确认保留"],
                    "impact": ["grant_risk"],
                    "decider": "both"
                })
    if distinguishing == 0:
        report.fail(
            "CN-LEDGER-CLASS-003",
            "ledger",
            "台账中没有任何 distinguishing 特征",
            "至少标注一个区别特征；全部特征均与最接近现有技术共有意味着不存在保护边界",
        )


def check_claims(ledger: dict[str, Any], claims: dict[int, str], report: Report) -> None:
    """台账与权利要求双向对账。"""

    normalized = {num: normalize(text) for num, text in claims.items()}
    covered: set[int] = set()

    for feature in ledger["features"]:
        fid = feature["feature_id"]
        for site in feature.get("claim_sites") or []:
            number = site.get("claim_number")
            if not isinstance(number, int):
                report.fail(
                    "CN-LEDGER-CLAIM-001",
                    fid,
                    f"特征 {fid} 的 claim_number 不是整数",
                    "修正为权利要求项号",
                )
                continue
            if number not in claims:
                report.fail(
                    "CN-LEDGER-CLAIM-001",
                    f"{fid}@claim{number}",
                    f"特征 {fid} 登记在权利要求 {number}，但权利要求书没有该项",
                    "修正项号，或补写该项权利要求",
                )
                continue
            covered.add(number)
            verbatim = site.get("verbatim")
            if verbatim and normalize(verbatim) not in normalized[number]:
                report.fail(
                    "CN-LEDGER-CLAIM-002",
                    f"{fid}@claim{number}",
                    f"特征 {fid} 登记的权利要求 {number} 原文片段在该项中找不到",
                    "按权利要求书实际用词更新 verbatim，或修正权利要求",
                )
            elif not verbatim:
                report.review(
                    "CN-LEDGER-CLAIM-003",
                    f"{fid}@claim{number}",
                    f"特征 {fid} 在权利要求 {number} 没有登记原文片段，无法逐字核对术语一致性",
                    "补写 verbatim",
                )

    for number in sorted(set(claims) - covered):
        report.fail(
            "CN-LEDGER-CLAIM-004",
            f"claim{number}",
            f"权利要求 {number} 没有任何台账特征落点",
            "为该项登记对应特征；权利要求中的每一个限定都必须在台账中有来源",
        )


def check_specification(ledger: dict[str, Any], spec_text: str, report: Report) -> None:
    """台账登记的说明书落点必须能在对应章节里检索到。"""

    sections = split_sections(spec_text)
    normalized_sections = {name: normalize(body) for name, body in sections.items()}
    normalized_all = normalize(spec_text)

    for feature in ledger["features"]:
        fid = feature["feature_id"]
        if normalize(feature["name"]) not in normalized_all:
            report.fail(
                "CN-LEDGER-SPEC-001",
                fid,
                f"特征 {fid} 的规范名称“{feature['name']}”在说明书全文中找不到",
                "在说明书中使用该规范名称，或按说明书实际用词更新台账；权利要求与说明书必须使用完全相同的名词",
            )
        for index, site in enumerate(feature.get("spec_sites") or [], start=1):
            section = site.get("section")
            anchor = site.get("anchor", "")
            if section not in normalized_sections:
                report.fail(
                    "CN-LEDGER-SPEC-002",
                    f"{fid}#{index}",
                    f"特征 {fid} 登记的章节“{section}”在说明书中不存在",
                    "修正章节名，或补写该章节",
                )
                continue
            if normalize(anchor) not in normalized_sections[section]:
                report.fail(
                    "CN-LEDGER-SPEC-003",
                    f"{fid}#{index}",
                    f"特征 {fid} 在“{section}”中的定位串找不到：{anchor}",
                    "按说明书实际文字更新 anchor，或把该特征写入说明书",
                )

        if feature["classification"] == "fallback_only":
            in_implementation = any(
                site.get("section") == "具体实施方式"
                for site in feature.get("spec_sites") or []
            )
            if not in_implementation:
                report.review(
                    "CN-LEDGER-SPEC-004",
                    fid,
                    f"特征 {fid} 仅作为第三十三条弹药保留，却未落在具体实施方式",
                    "把被砍出权利要求的方案完整写入具体实施方式；答复审查意见时只能从原始记载中取弹药",
                )


def check_drawings(ledger: dict[str, Any], spec_text: str, report: Report) -> None:
    """附图标记清单与台账互为全集；步骤号不得混入附图标记清单。"""

    listed = parse_reference_list(spec_text)
    ledger_components: dict[str, tuple[str, str]] = {}
    ledger_steps: set[str] = set()

    for feature in ledger["features"]:
        fid = feature["feature_id"]
        for site in feature.get("drawing_sites") or []:
            kind = site.get("mark_kind")
            mark = str(site.get("mark", "")).strip()
            if kind == "component":
                label = site.get("label") or feature["name"]
                previous = ledger_components.get(mark)
                if previous and previous[1] != label:
                    report.fail(
                        "CN-LEDGER-FIG-001",
                        f"mark{mark}",
                        f"附图标记 {mark} 被登记了两个名称：“{previous[1]}”与“{label}”",
                        "同一标记只能对应一个技术对象",
                    )
                ledger_components[mark] = (fid, label)
            elif kind == "step":
                ledger_steps.add(mark)

    for mark, (fid, label) in sorted(ledger_components.items()):
        if mark not in listed:
            report.fail(
                "CN-LEDGER-FIG-002",
                f"mark{mark}",
                f"特征 {fid} 的附图标记 {mark} 未出现在“图中：…”附图标记清单中",
                "把该标记补入附图标记清单",
            )
        elif normalize(listed[mark]) != normalize(label):
            report.fail(
                "CN-LEDGER-FIG-003",
                f"mark{mark}",
                f"附图标记 {mark} 的清单名称“{listed[mark]}”与台账名称“{label}”不一致",
                "使清单名称与说明书正文首次出现处逐字一致",
            )

    for mark in sorted(set(listed) - set(ledger_components)):
        if mark in ledger_steps:
            report.fail(
                "CN-LEDGER-FIG-004",
                f"mark{mark}",
                f"{mark} 在台账中是方法步骤号，却被写进了附图标记清单",
                "步骤号不进附图标记清单；清单只登记部件标记",
            )
        else:
            report.fail(
                "CN-LEDGER-FIG-005",
                f"mark{mark}",
                f"附图标记清单中的 {mark}-{listed[mark]} 在台账中没有对应特征",
                "为该标记登记特征，或从清单中删除",
            )

    for mark in sorted(ledger_steps & set(listed)):
        # 已在上一循环覆盖；此处仅保证步骤号与部件标记不冲突。
        if mark in ledger_components:
            report.fail(
                "CN-LEDGER-FIG-006",
                f"mark{mark}",
                f"{mark} 同时被登记为部件标记和方法步骤号",
                "部件标记与步骤号必须使用互不重叠的编号空间",
            )

    # 步骤号与部件标记落在同一百位区间时，任何按数字做的自动核对都会误报。
    # 这不是法律缺陷，但它让"图上标记与正文是否一致"无法被机器验证。
    component_blocks = {
        int(mark) // 100 for mark in ledger_components if mark.isdigit()
    }
    for step in sorted(ledger_steps):
        digits = re.sub(r"\D", "", step)
        if not digits:
            continue
        block = int(digits) // 100
        if block in component_blocks:
            report.review(
                "CN-LEDGER-FIG-007",
                f"step{step}",
                f"步骤号 {step} 的数字落在部件标记的 {block}00 区间内，"
                "按数字做的图文自动核对会把两者混为一谈",
                f"把步骤号移出 {block}00 区间，或为部件标记与步骤号约定互不重叠的编号空间",
            )



def check_v2_relations(
    ledger: dict[str, Any],
    claims: dict[int, str],
    spec_text: str,
    report: Report,
    drawing_brief: dict[str, Any] | None = None,
) -> None:
    """复算 v2 台账中的数据流、方法—系统映射和异常终态。"""

    if ledger.get("schema_id") != SCHEMA_ID_V2:
        report.review(
            "CN-LEDGER-V2-000",
            "ledger",
            "当前为 v1 台账，未执行数据流、动作阶段、方法—系统和异常闭合复算",
            "新案件升级为 cn-patent-feature-ledger/v2；v1 仅用于旧案件回放",
        )
        return

    feature_by_id = {item["feature_id"]: item for item in ledger["features"]}
    phase_order = {
        "preconfigured": 0,
        "runtime_input": 1,
        "runtime_processing": 2,
        "runtime_output": 3,
        "postprocessing": 4,
    }
    path_by_id = {item["path_id"]: item for item in ledger["exception_paths"]}
    normalized_claims = {number: normalize(text) for number, text in claims.items()}
    sections = {name: normalize(body) for name, body in split_sections(spec_text).items()}

    for fid, feature in feature_by_id.items():
        flow = feature["flow"]
        for target in flow["downstream_feature_ids"]:
            if target not in feature_by_id:
                report.fail(
                    "CN-LEDGER-FLOW-001", fid,
                    f"特征 {fid} 的下游特征 {target} 未登记",
                    "补登下游特征或删除无效引用",
                )
            elif target == fid:
                report.fail(
                    "CN-LEDGER-FLOW-002", fid,
                    f"特征 {fid} 把自身登记为下游，数据流形成无意义自环",
                    "登记实际下游特征；循环算法应通过状态或迭代条件单独描述",
                )
        for path_id in flow["exception_path_ids"]:
            if path_id not in path_by_id:
                report.fail(
                    "CN-LEDGER-EXCEPTION-001", fid,
                    f"特征 {fid} 引用的异常路径 {path_id} 未登记",
                    "在 exception_paths 中补齐该路径",
                )
        for site in feature.get("claim_sites") or []:
            role = site.get("execution_role")
            phase = flow["action_phase"]
            if phase == "preconfigured" and role == "runtime_step":
                report.fail(
                    "CN-LEDGER-PHASE-001", f"{fid}@claim{site.get('claim_number')}",
                    f"预配置特征 {fid} 被登记为运行时步骤",
                    "将权利要求表述改为预先配置/预先建立，或修正真实动作阶段",
                )
            if phase != "preconfigured" and role == "precondition":
                report.fail(
                    "CN-LEDGER-PHASE-002", f"{fid}@claim{site.get('claim_number')}",
                    f"运行阶段特征 {fid} 被登记为预置条件",
                    "按真实执行时序区分预配置行为与运行时处理行为",
                )

    flow_by_claim: dict[int, dict[str, Any]] = {}
    linked_exception_ids: set[str] = set()
    for flow in ledger["claim_data_flows"]:
        number = flow["claim_number"]
        if number in flow_by_claim:
            report.fail(
                "CN-LEDGER-FLOW-003", f"claim{number}",
                f"权利要求 {number} 重复登记 claim_data_flow",
                "每项独立权利要求只保留一条数据流登记",
            )
        flow_by_claim[number] = flow
        if number not in claims:
            report.fail(
                "CN-LEDGER-FLOW-004", f"claim{number}",
                f"claim_data_flow 指向不存在的权利要求 {number}",
                "修正项号或补写对应独立权利要求",
            )
        ordered = flow["ordered_feature_ids"]
        for field in ("entry_feature_ids", "ordered_feature_ids", "merge_feature_ids", "normal_exit_feature_ids", "storage_feature_ids"):
            for fid in flow[field]:
                if fid not in feature_by_id:
                    report.fail(
                        "CN-LEDGER-FLOW-005", f"claim{number}",
                        f"{field} 引用未登记特征 {fid}",
                        "补登特征或修正数据流引用",
                    )
                elif not any(site.get("claim_number") == number for site in feature_by_id[fid].get("claim_sites") or []):
                    report.fail(
                        "CN-LEDGER-FLOW-006", f"{fid}@claim{number}",
                        f"数据流包含特征 {fid}，但该特征没有权利要求 {number} 落点",
                        "补登 claim_sites 并填写可逐字核对的 verbatim",
                    )
        for fid in flow["entry_feature_ids"] + flow["normal_exit_feature_ids"] + flow["merge_feature_ids"] + flow["storage_feature_ids"]:
            if fid not in ordered:
                report.fail(
                    "CN-LEDGER-FLOW-007", f"{fid}@claim{number}",
                    f"特征 {fid} 被登记为入口/汇合/出口/存储点，但不在 ordered_feature_ids 中",
                    "把该特征纳入独立权利要求的数据流顺序链",
                )
        phases = [phase_order[feature_by_id[fid]["flow"]["action_phase"]] for fid in ordered if fid in feature_by_id]
        if any(current > following for current, following in zip(phases, phases[1:])):
            report.fail(
                "CN-LEDGER-PHASE-003", f"claim{number}",
                "独立权利要求的数据流动作阶段发生倒退",
                "按预配置→运行时输入→运行时处理→运行时输出→后处理重新排列",
            )
        position = {fid: index for index, fid in enumerate(ordered)}
        for fid in ordered:
            if fid not in feature_by_id:
                continue
            for target in feature_by_id[fid]["flow"]["downstream_feature_ids"]:
                if target in position and position[target] <= position[fid]:
                    report.fail(
                        "CN-LEDGER-FLOW-008", f"{fid}->{target}@claim{number}",
                        "台账下游关系与独立权利要求数据流顺序冲突",
                        "修正 downstream_feature_ids 或 ordered_feature_ids",
                    )
        for path_id in flow["exception_path_ids"]:
            linked_exception_ids.add(path_id)
            if path_id not in path_by_id:
                report.fail(
                    "CN-LEDGER-EXCEPTION-002", f"claim{number}",
                    f"独立权利要求引用未登记异常路径 {path_id}",
                    "补齐 exception_paths",
                )

    for pair in ledger["method_system_pairs"]:
        method_number = pair["method_claim_number"]
        system_number = pair["system_claim_number"]
        method_flow = flow_by_claim.get(method_number)
        system_flow = flow_by_claim.get(system_number)
        if not method_flow or method_flow.get("claim_type") != "method":
            report.fail(
                "CN-LEDGER-PAIR-001", f"claim{method_number}",
                "方法—系统对照缺少方法独权数据流",
                "为方法独权登记 claim_type=method 的 claim_data_flow",
            )
        if not system_flow or system_flow.get("claim_type") not in {"system", "device"}:
            report.fail(
                "CN-LEDGER-PAIR-002", f"claim{system_number}",
                "方法—系统对照缺少系统/装置独权数据流",
                "为系统独权登记 claim_type=system/device 的 claim_data_flow",
            )
        for fid in pair["required_feature_ids"]:
            feature = feature_by_id.get(fid)
            if feature is None:
                report.fail(
                    "CN-LEDGER-PAIR-003", fid,
                    f"方法—系统必要特征 {fid} 未登记",
                    "补登该技术特征",
                )
                continue
            method_sites = [s for s in feature.get("claim_sites") or [] if s.get("claim_number") == method_number]
            system_sites = [s for s in feature.get("claim_sites") or [] if s.get("claim_number") == system_number]
            if not method_sites:
                report.fail(
                    "CN-LEDGER-PAIR-004", f"{fid}@claim{method_number}",
                    f"必要特征 {fid} 未落入方法独权 {method_number}",
                    "补入方法步骤或从 required_feature_ids 移除并说明理由",
                )
            if not system_sites:
                report.fail(
                    "CN-LEDGER-PAIR-005", f"{fid}@claim{system_number}",
                    f"必要特征 {fid} 未落入系统独权 {system_number}",
                    "补入对应处理模块，不能只做名称平行转换",
                )
            elif not any(str(site.get("actor", "")).strip() for site in system_sites):
                report.fail(
                    "CN-LEDGER-PAIR-006", f"{fid}@claim{system_number}",
                    f"系统独权中的必要特征 {fid} 未登记具体处理主体",
                    "填写实施该功能的子模块/模块 actor",
                )

    for path_id, path in path_by_id.items():
        for fid in path["action_feature_ids"]:
            if fid not in feature_by_id:
                report.fail(
                    "CN-LEDGER-EXCEPTION-003", path_id,
                    f"异常路径 {path_id} 引用未登记动作特征 {fid}",
                    "补登特征或修正 action_feature_ids",
                )
        if path["produces_value"] and path["confidence"] not in {"high", "medium", "low"}:
            report.fail(
                "CN-LEDGER-EXCEPTION-004", path_id,
                f"异常路径 {path_id} 生成结果值却未给出确定置信度等级",
                "明确 high/medium/low 之一；低置信度退守不得只写待复核标识",
            )
        if not path["produces_value"] and path["confidence"] != "not_applicable":
            report.fail(
                "CN-LEDGER-EXCEPTION-005", path_id,
                f"异常路径 {path_id} 不生成结果值，confidence 应为 not_applicable",
                "修正 produces_value 或 confidence",
            )
        for site in path["claim_sites"]:
            number, anchor = site.get("claim_number"), site.get("anchor", "")
            if number not in normalized_claims or normalize(anchor) not in normalized_claims[number]:
                report.fail(
                    "CN-LEDGER-EXCEPTION-006", f"{path_id}@claim{number}",
                    f"异常路径 {path_id} 的权利要求锚点无法定位",
                    "按权利要求实际文字更新 anchor，确保终态和原因码相关限定可核对",
                )
        for index, site in enumerate(path["spec_sites"], start=1):
            section, anchor = site.get("section"), site.get("anchor", "")
            if section not in sections or normalize(anchor) not in sections[section]:
                report.fail(
                    "CN-LEDGER-EXCEPTION-007", f"{path_id}#{index}",
                    f"异常路径 {path_id} 的说明书锚点无法定位",
                    "在说明书中完整写明触发、动作、结果、置信度、终态、原因码和存储字段",
                )
        if path_id not in linked_exception_ids:
            report.fail(
                "CN-LEDGER-EXCEPTION-008", path_id,
                f"异常路径 {path_id} 未被任何独立权利要求数据流引用",
                "把该路径关联到对应 claim_data_flow，或删除无效登记",
            )

    if drawing_brief is not None:
        element_ids: set[str] = set()
        relation_ids: set[str] = set()
        for figure in drawing_brief.get("figures") or []:
            element_ids.update(item.get("id") for item in figure.get("elements") or [] if isinstance(item.get("id"), str))
            relation_ids.update(item.get("id") for item in figure.get("relations") or [] if isinstance(item.get("id"), str))
        for fid, feature in feature_by_id.items():
            for site in feature.get("drawing_sites") or []:
                element_id = site.get("element_id")
                if element_id and element_id not in element_ids:
                    report.fail(
                        "CN-LEDGER-DRAWING-001", f"{fid}:{element_id}",
                        f"台账声明的附图元素 {element_id} 不在当前绘图合同中",
                        "同步 drawing brief 或修正 drawing_sites.element_id",
                    )
                for relation_id in site.get("relation_ids") or []:
                    if relation_id not in relation_ids:
                        report.fail(
                            "CN-LEDGER-DRAWING-002", f"{fid}:{relation_id}",
                            f"台账声明的附图关系 {relation_id} 不在当前绘图合同中",
                            "同步 drawing brief 或修正 drawing_sites.relation_ids",
                        )
        for path_id, path in path_by_id.items():
            for relation_id in path["drawing_relation_ids"]:
                if relation_id not in relation_ids:
                    report.fail(
                        "CN-LEDGER-DRAWING-003", f"{path_id}:{relation_id}",
                        f"异常路径 {path_id} 的附图关系 {relation_id} 不在当前绘图合同中",
                        "在对应附图中闭合该异常分支，或修正关系 ID",
                    )

def render_table(ledger: dict[str, Any]) -> str:
    """渲染人类可读的区别特征表。"""

    lines: list[str] = []
    lines.append("# 区别特征表")
    lines.append("")
    lines.append(f"案件：{ledger['case_id']}　生成时间：{ledger['generated_at']}")
    lines.append("")
    lines.append(
        "本表是全案技术特征的唯一台账。权利要求书、说明书和说明书附图由本表派生，"
        "三者的一致性以本表为裁决标准。本表不构成新颖性、创造性或授权前景判断。"
    )
    lines.append("")

    search = ledger.get("search_status") or {}
    if search:
        lines.append("## 检索状态")
        lines.append("")
        lines.append(f"- CNIPA 人工检索：{search.get('cnipa_manual_search', '未声明')}")
        lines.append(f"- 声明：{search.get('statement', '')}")
        if search.get("as_of_date"):
            lines.append(f"- 截止日期：{search['as_of_date']}")
        lines.append("")

    prior_art = ledger.get("closest_prior_art") or []
    lines.append("## 最接近的现有技术")
    lines.append("")
    if prior_art:
        lines.append("| 文献号 | 名称 | 角色 | 备注 |")
        lines.append("|---|---|---|---|")
        for doc in prior_art:
            lines.append(
                f"| {doc['doc_id']} | {doc['title']} | {doc['role']} | {doc.get('note', '')} |"
            )
    else:
        lines.append("未登记最接近现有技术。空列表不等于不存在现有技术，须结合检索状态阅读。")
    lines.append("")

    lines.append("## 特征对照")
    lines.append("")
    lines.append("| 编号 | 特征名称 | 分类 | 检索判定 | 权利要求落点 | 说明书落点 | 附图落点 |")
    lines.append("|---|---|---|---|---|---|---|")
    for feature in ledger["features"]:
        claim_sites = feature.get("claim_sites") or []
        claim_text = "、".join(
            f"权{site['claim_number']}"
            + ("（前序）" if site.get("part") == "preamble" else "（特征部分）")
            for site in claim_sites
        ) or "—"
        spec_text = "、".join(
            f"{site['section']}：{site['anchor']}"
            for site in (feature.get("spec_sites") or [])
        ) or "—"
        drawing_text = "、".join(
            f"图{site['figure']}"
            + (f" {site['mark']}" if site.get("mark_kind") != "none" else "")
            for site in (feature.get("drawing_sites") or [])
        ) or "—"
        verdict = (feature.get("prior_art_status") or {}).get("verdict")
        lines.append(
            "| {fid} | {name} | {cls} | {verdict} | {claims} | {spec} | {fig} |".format(
                fid=feature["feature_id"],
                name=feature["name"],
                cls=CLASSIFICATION_LABEL[feature["classification"]],
                verdict=PRIOR_ART_LABEL.get(verdict, "未声明"),
                claims=claim_text,
                spec=spec_text,
                fig=drawing_text,
            )
        )
    lines.append("")

    lines.append("## 区别特征与技术效果")
    lines.append("")
    distinguishing = [f for f in ledger["features"] if f["classification"] == "distinguishing"]
    if distinguishing:
        lines.append("| 编号 | 区别特征 | 技术效果 | 对比文件 |")
        lines.append("|---|---|---|---|")
        for feature in distinguishing:
            status = feature.get("prior_art_status") or {}
            docs = "、".join(status.get("cited_docs") or []) or "—"
            lines.append(
                "| {fid} | {stmt} | {effect} | {docs} |".format(
                    fid=feature["feature_id"],
                    stmt=feature["statement"],
                    effect=feature.get("technical_effect", "（未记载）"),
                    docs=docs,
                )
            )
    else:
        lines.append("未登记区别特征。")
    lines.append("")

    fallback = [f for f in ledger["features"] if f["classification"] == "fallback_only"]
    lines.append("## 仅写入说明书的退守方案（专利法第三十三条弹药）")
    lines.append("")
    if fallback:
        lines.append("| 编号 | 方案 | 说明书落点 |")
        lines.append("|---|---|---|")
        for feature in fallback:
            spec_text = "、".join(
                f"{site['section']}：{site['anchor']}"
                for site in (feature.get("spec_sites") or [])
            )
            lines.append(f"| {feature['feature_id']} | {feature['statement']} | {spec_text} |")
    else:
        lines.append("未登记仅写入说明书的退守方案。答复审查意见时可用的收窄落点将非常有限。")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="区别特征表四向对账")
    parser.add_argument("--ledger", required=True, help="feature-ledger.json 路径")
    parser.add_argument("--claims", required=True, help="权利要求书 UTF-8 文本路径")
    parser.add_argument("--specification", required=True, help="说明书 UTF-8 文本路径")
    parser.add_argument("--output", required=True, help="对账报告 JSON 输出路径")
    parser.add_argument("--table", help="区别特征表 Markdown 输出路径")
    parser.add_argument("--drawing-brief", help="可选：drawing-brief.json，用于核对元素和关系 ID")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = [Path(args.ledger), Path(args.claims), Path(args.specification)]
        if args.drawing_brief:
            inputs.append(Path(args.drawing_brief))
        outputs = [Path(args.output)] + ([Path(args.table)] if args.table else [])
        output_guard = DraftingOutputGuard(inputs, outputs)
        ledger = load_ledger(Path(args.ledger))
        claims_text = read_text(Path(args.claims), "权利要求书")
        spec_text = read_text(Path(args.specification), "说明书")
        claims = parse_claims(claims_text)
        drawing_brief = None
        if args.drawing_brief:
            drawing_brief_text = read_text(Path(args.drawing_brief), "绘图合同")
            drawing_brief = json.loads(drawing_brief_text)
            if not isinstance(drawing_brief, dict):
                raise LedgerError("绘图合同顶层必须是对象")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    if not claims:
        print("错误：权利要求书中没有解析到任何编号权利要求", file=sys.stderr)
        return EXIT_INPUT_ERROR

    report = Report()
    check_classification(ledger, report)
    check_claims(ledger, claims, report)
    check_specification(ledger, spec_text, report)
    check_drawings(ledger, spec_text, report)
    check_v2_relations(ledger, claims, spec_text, report, drawing_brief)

    fails = [f for f in report.findings if f["status"] == "DETERMINISTIC_FAIL"]
    reviews = [f for f in report.findings if f["status"] == "REVIEW_REQUIRED"]
    payload = {
        "schema_id": REPORT_SCHEMA_ID,
        "legal_effect": LEGAL_EFFECT,
        "case_id": ledger["case_id"],
        "input_artifacts": [
            {"artifact_id": "feature_ledger", "path": str(Path(args.ledger).resolve()), "sha256": hashlib.sha256(Path(args.ledger).read_bytes()).hexdigest()},
            {"artifact_id": "claims", "path": str(Path(args.claims).resolve()), "sha256": hashlib.sha256(Path(args.claims).read_bytes()).hexdigest()},
            {"artifact_id": "specification", "path": str(Path(args.specification).resolve()), "sha256": hashlib.sha256(Path(args.specification).read_bytes()).hexdigest()},
        ] + ([{"artifact_id": "drawing_brief", "path": str(Path(args.drawing_brief).resolve()), "sha256": hashlib.sha256(Path(args.drawing_brief).read_bytes()).hexdigest()}] if args.drawing_brief else []),
        "evidence_scope": {
            "proves": [
                "台账字段和跨对象引用满足确定性合同",
                "登记的权利要求与说明书锚点可在当前输入中定位",
                "v2 数据流、动作阶段、方法—系统覆盖和异常出口通过结构复算",
                "提供绘图合同时，台账登记的图元素和关系 ID 存在",
            ],
            "does_not_prove": [
                "权利要求必然清楚或得到说明书支持",
                "某项特征必然属于必要技术特征",
                "申请具备新颖性、创造性或授权前景",
                "附图视觉质量已经通过人工复核",
            ],
        },
        "counts": {
            "features": len(ledger["features"]),
            "claims": len(claims),
            "deterministic_fail": len(fails),
            "review_required": len(reviews),
        },
        "boundary": (
            "文本命中不等于得到支持，未命中也不等于缺乏支持。零 DETERMINISTIC_FAIL "
            "只表示登记、数据流和引用关系在当前输入范围内可对账，不代表清楚、支持、必要技术特征或创造性成立。"
        ),
        "findings": report.findings,
        "pending_decisions": report.pending_decisions,
    }

    try:
        texts = [json.dumps(payload, ensure_ascii=False, indent=2) + "\n"]
        if args.table:
            texts.append(render_table(ledger))
        output_guard.write_texts(texts)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(f"[OK] 对账报告：{args.output}")
    if args.table:
        print(f"[OK] 区别特征表：{args.table}")

    print(
        "[INFO] 特征 {} 项，权利要求 {} 项，DETERMINISTIC_FAIL {} 条，REVIEW_REQUIRED {} 条".format(
            len(ledger["features"]), len(claims), len(fails), len(reviews)
        )
    )
    for finding in fails:
        print(f"[FAIL] {finding['rule_id']} {finding['target_id']}：{finding['problem']}")
    for finding in reviews:
        print(f"[REVIEW] {finding['rule_id']} {finding['target_id']}：{finding['problem']}")

    return EXIT_DETERMINISTIC_FAIL if fails else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
