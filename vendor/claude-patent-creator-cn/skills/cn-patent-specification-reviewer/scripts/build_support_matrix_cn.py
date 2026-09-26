#!/usr/bin/env python3
"""中国发明专利说明书的 CN v2 原始检查器。

脚本只做可复算的文本定位：把人工选定的候选技术特征在说明书中的精确命中位置
固定为结构化证据，并把全部法律语义判断显式记录为 gap。文本命中不等于得到支持，
未命中也不等于缺乏支持——这条边界由 gap 而不是由结论字段承载。

段落规范化结果只计算一次并缓存，避免"每个特征重复规范化整份说明书"的二次复杂度。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "cn-patent-review-raw-report/v2"
CONTRACT_SCHEMA_VERSION = "cn-patent-review-contract/v2"
JURISDICTION = "CN"
REVIEW_TYPE = "specification"
LEGAL_EFFECT = "ADVISORY_ONLY"
TOOL_ID = "cn-patent-specification-reviewer"
TOOL_VERSION = "2.0.0"

INPUT_RULE_ID = "CN-SPEC-INPUT-001"
FEATURE_RULE_ID = "CN-SPEC-FEATURE-001"
OUTPUT_RULE_ID = "CN-SPEC-OUTPUT-001"
PARAGRAPH_RULE_ID = "CN-SPEC-PARAGRAPH-001"
MATCH_RULE_ID = "CN-SPEC-MATCH-001"
RESOURCE_RULE_ID = "CN-SPEC-RESOURCE-001"

# 脚本不做法律语义判断的维度，逐条形成结构化缺口而不是静默消失。
SEMANTIC_RULE_IDS = (
    ("CN-SPEC-DISCLOSURE-001", "specification", "清楚、完整、能够实现的充分公开判断"),
    ("CN-SPEC-STRUCTURE-001", "specification", "说明书撰写结构及其例外理由的判断"),
    ("CN-SPEC-DRAWING-001", "drawings", "附图必要性、图号与附图标记一致性的判断"),
    ("CN-SPEC-SUPPORT-001", "claims", "权利要求能否从说明书得到或合理概括的判断"),
    ("CN-SPEC-FUNCTION-001", "claims", "功能性限定的可验证性和概括范围判断"),
    ("CN-SPEC-RANGE-001", "claims", "数值范围和上位概括的实施方式充分性判断"),
    ("CN-SPEC-EFFECT-001", "specification", "技术效果与技术手段、技术问题对应关系的判断"),
    ("CN-SPEC-AI-001", "specification", "算法与人工智能两条并列技术路径的充分公开判断"),
    ("CN-SPEC-AMEND-001", "amendment", "修改是否可从原始记载直接、毫无疑义确定的判断"),
)

MAX_SPECIFICATION_BYTES = 8 * 1024 * 1024
MAX_FEATURES_BYTES = 4 * 1024 * 1024
MAX_PARAGRAPHS = 100_000
MAX_FEATURE_CANDIDATES = 20_000
MAX_VARIANTS_PER_FEATURE = 32
MAX_MATCHES_PER_FEATURE = 1_000
MAX_TOTAL_MATCHES = 100_000
MAX_FINDINGS = 5_000
MAX_GAPS = 5_000
MAX_CHECKS = 10_000
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
DEADLINE_SECONDS = 180
FAILURE_EXIT_CODE = 4

RESOURCE_LIMITS = {
    "specification_input_bytes": MAX_SPECIFICATION_BYTES,
    "specification_features_input_bytes": MAX_FEATURES_BYTES,
    "specification_max_paragraphs": MAX_PARAGRAPHS,
    "specification_max_feature_candidates": MAX_FEATURE_CANDIDATES,
    "specification_max_variants_per_feature": MAX_VARIANTS_PER_FEATURE,
    "specification_max_matches_per_feature": MAX_MATCHES_PER_FEATURE,
    "specification_max_total_matches": MAX_TOTAL_MATCHES,
    "max_findings": MAX_FINDINGS,
    "max_gaps": MAX_GAPS,
    "max_checks": MAX_CHECKS,
    "max_report_output_bytes": MAX_OUTPUT_BYTES,
    "orchestration_deadline_seconds": DEADLINE_SECONDS,
    "failure_exit_code": FAILURE_EXIT_CODE,
}

GAP_CATEGORIES = {
    "INPUT_UNAVAILABLE",
    "PARSE_UNRESOLVED",
    "CAPABILITY_LIMIT",
    "SEARCH_EVIDENCE_MISSING",
    "CONDITIONAL_APPLICABILITY_UNRESOLVED",
    "SEMANTIC_REVIEW_NOT_PERFORMED",
}
RAW_STATUSES = {"DETERMINISTIC_FAIL", "REVIEW_REQUIRED", "WARNING", "NOT_VERIFIED"}
CHECK_STATUSES = {"COMPLETED", "PARTIAL", "SKIPPED", "NOT_VERIFIED"}

RULE_MATRIX_PATH = Path(__file__).resolve().parents[1] / "references" / "specification-rule-matrix.md"
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "cn-patent-reviewer" / "references" / "cn-review-contract-v2.json"
PARAGRAPH_MARK_RE = re.compile(r"^[ \t　]*[\[【](\d{4})[\]】][ \t　]*", re.MULTILINE)
MAX_EXCERPT_CHARS = 240


class ResourceLimitError(Exception):
    """资源越限属于工具错误，统一退出码 4，不得转换为法律 finding。"""


@dataclass(frozen=True)
class Feature:
    feature_id: str
    text: str
    variants: tuple[str, ...]


@dataclass(frozen=True)
class Paragraph:
    """段落及其一次性计算的规范化结果与字符位置映射。"""

    paragraph_id: str
    occurrence: int
    text: str
    normalized: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    @property
    def key(self) -> str:
        return f"{self.paragraph_id}#{self.occurrence}"


class Budget:
    def __init__(self) -> None:
        self.started = time.monotonic()

    def guard(self) -> None:
        if time.monotonic() - self.started > DEADLINE_SECONDS:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 说明书检查超过 {DEADLINE_SECONDS} 秒编排时限")

    def elapsed_milliseconds(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


# --------------------------------------------------------------------------
# 文本规范化与定位
# --------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def is_cjk(character: str) -> bool:
    return bool(character) and ("㐀" <= character <= "䶿" or "一" <= character <= "鿿")


def normalize_with_positions(value: str) -> tuple[str, list[int], list[int]]:
    """Unicode 规范化并保留字符位置；仅忽略汉字之间的排版空白。"""

    units: list[tuple[str, int, int]] = []
    whitespace_open = False
    for original_index, original_character in enumerate(value):
        normalized_piece = unicodedata.normalize("NFKC", original_character).casefold()
        for character in normalized_piece:
            if character.isspace():
                if units and not whitespace_open:
                    units.append((" ", original_index, original_index + 1))
                    whitespace_open = True
                continue
            units.append((character, original_index, original_index + 1))
            whitespace_open = False

    while units and units[0][0] == " ":
        units.pop(0)
    while units and units[-1][0] == " ":
        units.pop()

    filtered: list[tuple[str, int, int]] = []
    for index, unit in enumerate(units):
        character = unit[0]
        if character == " ":
            previous = units[index - 1][0] if index > 0 else ""
            following = units[index + 1][0] if index + 1 < len(units) else ""
            if is_cjk(previous) and is_cjk(following):
                continue
        filtered.append(unit)

    return (
        "".join(unit[0] for unit in filtered),
        [unit[1] for unit in filtered],
        [unit[2] for unit in filtered],
    )


def normalize(value: str) -> str:
    return normalize_with_positions(value)[0]


def normalize_paragraph_id(value: str) -> str:
    """统一段落号的 Unicode 表示，避免等值数字绕过重复编号检查。"""

    normalized = unicodedata.normalize("NFKC", value)
    digits: list[str] = []
    for character in normalized:
        decimal_value = unicodedata.decimal(character, None)
        if decimal_value is None:
            raise ValueError(f"{PARAGRAPH_RULE_ID}: 段落号包含非十进制数字字符：{value}")
        digits.append(str(decimal_value))
    return "".join(digits)


def build_paragraph(paragraph_id: str, occurrence: int, text: str) -> Paragraph:
    normalized, starts, ends = normalize_with_positions(text)
    return Paragraph(paragraph_id, occurrence, text, normalized, tuple(starts), tuple(ends))


def parse_paragraphs(text: str, budget: Budget) -> list[Paragraph]:
    """解析段落并一次性完成规范化；段落数受规范上限约束。"""

    matches = list(PARAGRAPH_MARK_RE.finditer(text))
    paragraphs: list[Paragraph] = []
    if matches:
        if len(matches) + 1 > MAX_PARAGRAPHS:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 说明书段落数超过上限 {MAX_PARAGRAPHS}")
        preamble = text[: matches[0].start()].strip()
        if preamble:
            paragraphs.append(build_paragraph("PREAMBLE", 1, preamble))
        occurrences: dict[str, int] = {}
        for index, match in enumerate(matches):
            budget.guard()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            paragraph_id = normalize_paragraph_id(match.group(1))
            occurrences[paragraph_id] = occurrences.get(paragraph_id, 0) + 1
            paragraphs.append(build_paragraph(paragraph_id, occurrences[paragraph_id], body))
        return paragraphs

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks and text.strip():
        blocks = [text.strip()]
    if len(blocks) > MAX_PARAGRAPHS:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 说明书段落数超过上限 {MAX_PARAGRAPHS}")
    for index, block in enumerate(blocks, start=1):
        budget.guard()
        paragraphs.append(build_paragraph(f"P{index:04d}", 1, block))
    return paragraphs


def context_excerpt(text: str, start: int, end: int, limit: int = MAX_EXCERPT_CHARS) -> str:
    """以命中位置为中心生成上下文，而不是固定截取段落开头。"""

    if len(text) <= limit:
        return re.sub(r"\s+", " ", text).strip()
    match_length = max(1, end - start)
    surrounding = max(0, limit - min(match_length, limit))
    excerpt_start = max(0, start - surrounding // 2)
    excerpt_end = min(len(text), excerpt_start + limit)
    excerpt_start = max(0, excerpt_end - limit)
    excerpt = re.sub(r"\s+", " ", text[excerpt_start:excerpt_end]).strip()
    return ("…" if excerpt_start > 0 else "") + excerpt + ("…" if excerpt_end < len(text) else "")


def locate(paragraph: Paragraph, normalized_term: str) -> list[tuple[int, int]]:
    """在已缓存的规范化段落中定位术语，返回原文半开区间。"""

    if not normalized_term:
        return []
    spans: list[tuple[int, int]] = []
    search_start = 0
    while True:
        position = paragraph.normalized.find(normalized_term, search_start)
        if position < 0:
            return spans
        last = position + len(normalized_term) - 1
        spans.append((paragraph.starts[position], paragraph.ends[last]))
        search_start = position + max(1, len(normalized_term))


# --------------------------------------------------------------------------
# 候选特征输入
# --------------------------------------------------------------------------

def validate_features(raw_features: list[Any]) -> list[Feature]:
    """校验并规范化候选特征，拒绝隐式类型转换、空值和重复 ID。"""

    if len(raw_features) > MAX_FEATURE_CANDIDATES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 候选特征数超过上限 {MAX_FEATURE_CANDIDATES}")
    features: list[Feature] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_features, start=1):
        if isinstance(item, str):
            text, feature_id, raw_variants = item, f"F{index:03d}", []
        elif isinstance(item, dict):
            text = item.get("text")
            if not isinstance(text, str):
                raise ValueError(f"{FEATURE_RULE_ID}: 第 {index} 个候选特征的 text 必须是字符串。")
            has_id, has_feature_id = "id" in item, "feature_id" in item
            if has_id and has_feature_id and item["id"] != item["feature_id"]:
                raise ValueError(f"{FEATURE_RULE_ID}: 第 {index} 个候选特征的 id 与 feature_id 不一致。")
            raw_id = item["id"] if has_id else item.get("feature_id", f"F{index:03d}")
            if not isinstance(raw_id, str):
                raise ValueError(f"{FEATURE_RULE_ID}: 第 {index} 个候选特征的 ID 必须是字符串。")
            feature_id = raw_id
            raw_variants = item.get("variants", [])
            if not isinstance(raw_variants, list):
                raise ValueError(f"{FEATURE_RULE_ID}: 特征 {feature_id} 的 variants 必须是数组。")
        else:
            raise ValueError(f"{FEATURE_RULE_ID}: 第 {index} 个候选特征必须是字符串或对象。")

        feature_id = unicodedata.normalize("NFKC", feature_id).strip()
        if not feature_id:
            raise ValueError(f"{FEATURE_RULE_ID}: 第 {index} 个候选特征的 ID 不能为空。")
        id_key = feature_id.casefold()
        if id_key in seen_ids:
            raise ValueError(f"{FEATURE_RULE_ID}: 候选特征 ID 必须唯一，重复 ID：{feature_id}")
        seen_ids.add(id_key)

        feature_text = text.strip()
        if not feature_text:
            raise ValueError(f"{FEATURE_RULE_ID}: 特征 {feature_id} 的 text 不能为空。")
        if len(raw_variants) > MAX_VARIANTS_PER_FEATURE:
            raise ResourceLimitError(
                f"{RESOURCE_RULE_ID}: 特征 {feature_id} 的 variant 数超过上限 {MAX_VARIANTS_PER_FEATURE}"
            )

        variants: list[str] = []
        seen_variants = {normalize(feature_text)}
        for variant_index, raw_variant in enumerate(raw_variants, start=1):
            if not isinstance(raw_variant, str):
                raise ValueError(
                    f"{FEATURE_RULE_ID}: 特征 {feature_id} 的第 {variant_index} 个 variant 必须是字符串。"
                )
            variant = raw_variant.strip()
            if not variant:
                continue
            variant_key = normalize(variant)
            if not variant_key or variant_key in seen_variants:
                continue
            seen_variants.add(variant_key)
            variants.append(variant)
        features.append(Feature(feature_id, feature_text, tuple(variants)))
    return features


def parse_features_bytes(raw: bytes) -> list[Feature]:
    """从原始字节解析候选特征；只接受 UTF-8 无 BOM。"""

    if raw.startswith(b"\xef\xbb\xbf"):
        raise UnicodeError(f"{FEATURE_RULE_ID}: 候选特征文件必须是 UTF-8 无 BOM")
    data = json.loads(raw.decode("utf-8"))
    raw_features = data.get("features") if isinstance(data, dict) else data
    if not isinstance(raw_features, list):
        raise ValueError(f"{FEATURE_RULE_ID}: 候选特征 JSON 必须是数组，或包含 features 数组。")
    return validate_features(raw_features)


# --------------------------------------------------------------------------
# v2 原始报告构造
# --------------------------------------------------------------------------

class Collector:
    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.checks: list[dict[str, Any]] = []
        self.findings: list[dict[str, Any]] = []
        self.gaps: list[dict[str, Any]] = []

    def finding(
        self, check_id: str, rule_id: str, target_id: str, location: str, status: str,
        problem: str, remedy: str, evidence: list[dict[str, str]],
    ) -> str:
        self.budget.guard()
        if status not in RAW_STATUSES:
            raise ValueError(f"不支持的原始 finding 状态：{status}")
        if len(self.findings) >= MAX_FINDINGS:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: finding 数量超过上限 {MAX_FINDINGS}")
        finding_id = stable_id("F", check_id, rule_id, target_id, location, status, problem)
        self.findings.append({
            "finding_id": finding_id,
            "check_id": check_id,
            "rule_id": rule_id,
            "target_id": target_id,
            "location": location,
            "status": status,
            "evidence": evidence,
            "problem": problem,
            "remedy": remedy,
            "manual_review_required": status != "DETERMINISTIC_FAIL",
        })
        return finding_id

    def gap(
        self, check_id: str, rule_id: str, target_id: str, category: str, reason: str,
        evidence: list[dict[str, str]], blocks_assessment: bool = True,
    ) -> str:
        self.budget.guard()
        if category not in GAP_CATEGORIES:
            raise ValueError(f"不支持的原始 gap 类别：{category}")
        if len(self.gaps) >= MAX_GAPS:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: gap 数量超过上限 {MAX_GAPS}")
        gap_id = stable_id("G", check_id, rule_id, target_id, category, reason)
        self.gaps.append({
            "gap_id": gap_id,
            "check_id": check_id,
            "rule_id": rule_id,
            "target_id": target_id,
            "category": category,
            "reason": reason,
            "evidence": evidence,
            "blocks_assessment": blocks_assessment,
        })
        return gap_id

    def check(self, check_id: str, rule_id: str, target_id: str, status: str,
              finding_ids: list[str], gap_ids: list[str]) -> None:
        if status not in CHECK_STATUSES:
            raise ValueError(f"不支持的 raw_check 状态：{status}")
        if len(self.checks) >= MAX_CHECKS:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 检查数量超过上限 {MAX_CHECKS}")
        self.checks.append({
            "check_id": check_id,
            "rule_id": rule_id,
            "target_id": target_id,
            "status": status,
            "finding_ids": sorted(set(finding_ids)),
            "gap_ids": sorted(set(gap_ids)),
        })


def make_artifact(artifact_id: str, path: str, raw: bytes, media_type: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "path": path,
        "sha256": sha256_bytes(raw),
        "byte_length": len(raw),
        "media_type": media_type,
        "encoding": "utf-8",
    }


def collection_digest(items: list[dict[str, Any]]) -> str:
    material = sorted((item["artifact_id"], item["sha256"]) for item in items)
    return sha256_bytes(canonical_json(material))


def evidence_entry(artifact_id: str, location: str, excerpt: str = "") -> dict[str, str]:
    return {"artifact_id": artifact_id, "location": location, "excerpt": excerpt[:MAX_EXCERPT_CHARS]}


def build_raw_report(
    specification: str,
    features: list[Feature],
    *,
    specification_bytes: bytes | None = None,
    features_bytes: bytes | None = None,
    specification_name: str = "<memory>",
    features_name: str = "<memory>",
) -> dict[str, Any]:
    """生成符合 CN v2 规范的说明书原始检查报告。"""

    budget = Budget()
    collector = Collector(budget)
    specification_raw = specification_bytes if specification_bytes is not None else specification.encode("utf-8")
    if len(specification_raw) > MAX_SPECIFICATION_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 说明书输入超过 {MAX_SPECIFICATION_BYTES} 字节上限")
    if features_bytes is not None and len(features_bytes) > MAX_FEATURES_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 候选特征输入超过 {MAX_FEATURES_BYTES} 字节上限")

    specification_available = bool(specification.strip())
    paragraphs = parse_paragraphs(specification, budget) if specification_available else []

    # 1. 说明书输入可用性。
    if specification_available:
        collector.check("spec-input", INPUT_RULE_ID, "specification", "COMPLETED", [], [])
    else:
        finding_id = collector.finding(
            "spec-input", INPUT_RULE_ID, "specification", "说明书", "NOT_VERIFIED",
            "说明书文本为空，未执行任何文本定位。", "提供可读取的说明书全文后重新运行。",
            [evidence_entry("specification", "specification")],
        )
        gap_id = collector.gap(
            "spec-input", INPUT_RULE_ID, "specification", "INPUT_UNAVAILABLE",
            "说明书文本为空，段落解析和候选特征定位均未执行。",
            [evidence_entry("specification", "specification")],
        )
        collector.check("spec-input", INPUT_RULE_ID, "specification", "NOT_VERIFIED", [finding_id], [gap_id])

    # 2. 候选特征输入可用性。
    if features:
        collector.check("spec-features", FEATURE_RULE_ID, "features", "COMPLETED", [], [])
    else:
        finding_id = collector.finding(
            "spec-features", FEATURE_RULE_ID, "features", "候选技术特征", "NOT_VERIFIED",
            "未提供由人工或 Skill 逐项权利要求提取的候选技术特征。",
            "先完成候选技术特征提取，再运行本检查器。",
            [evidence_entry("features", "features")],
        )
        gap_id = collector.gap(
            "spec-features", FEATURE_RULE_ID, "features", "INPUT_UNAVAILABLE",
            "缺少候选技术特征，逐特征文本定位未执行。",
            [evidence_entry("features", "features")],
        )
        collector.check("spec-features", FEATURE_RULE_ID, "features", "NOT_VERIFIED", [finding_id], [gap_id])

    # 3. 段落编号唯一性：重复编号使命中位置无法唯一定位，属确定性缺陷。
    paragraph_findings: list[str] = []
    counts: dict[str, int] = {}
    for paragraph in paragraphs:
        counts[paragraph.paragraph_id] = counts.get(paragraph.paragraph_id, 0) + 1
    for paragraph_id in sorted(value for value, count in counts.items() if count > 1):
        paragraph_findings.append(collector.finding(
            "spec-paragraph", PARAGRAPH_RULE_ID, f"paragraph-{paragraph_id}",
            f"说明书段落 {paragraph_id}", "DETERMINISTIC_FAIL",
            f"段落编号 {paragraph_id} 重复出现 {counts[paragraph_id]} 次，命中位置无法仅凭段落号唯一定位。",
            "核对原稿或文本转换结果，修正重复编号后重新生成证据。",
            [evidence_entry("specification", f"paragraph:{paragraph_id}", str(counts[paragraph_id]))],
        ))
    collector.check(
        "spec-paragraph", PARAGRAPH_RULE_ID, "specification",
        "COMPLETED" if specification_available else "SKIPPED", paragraph_findings, [],
    )

    # 4. 逐特征文本定位：命中作为结构化证据固定下来，法律结论仍未作出。
    match_findings: list[str] = []
    match_gaps: list[str] = []
    total_matches = 0
    if specification_available and features:
        for feature in features:
            budget.guard()
            candidates = [(feature.text, "feature_text")]
            candidates.extend((variant, "explicit_variant") for variant in feature.variants)
            normalized_candidates = [(term, mode, normalize(term)) for term, mode in candidates]
            evidence: list[dict[str, str]] = []
            for paragraph in paragraphs:
                for term, mode, normalized_term in normalized_candidates:
                    for start, end in locate(paragraph, normalized_term):
                        if len(evidence) >= MAX_MATCHES_PER_FEATURE:
                            raise ResourceLimitError(
                                f"{RESOURCE_RULE_ID}: 特征 {feature.feature_id} 的命中数超过上限 {MAX_MATCHES_PER_FEATURE}"
                            )
                        total_matches += 1
                        if total_matches > MAX_TOTAL_MATCHES:
                            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 总命中数超过上限 {MAX_TOTAL_MATCHES}")
                        evidence.append(evidence_entry(
                            "specification",
                            f"{paragraph.key}[{start}:{end}]:{mode}",
                            context_excerpt(paragraph.text, start, end),
                        ))
            if evidence:
                match_gaps.append(collector.gap(
                    "spec-match", MATCH_RULE_ID, f"feature-{feature.feature_id}",
                    "SEMANTIC_REVIEW_NOT_PERFORMED",
                    "已定位精确文本或显式变体命中，但能否得到说明书支持仍未作法律判断。",
                    evidence,
                ))
            else:
                match_findings.append(collector.finding(
                    "spec-match", MATCH_RULE_ID, f"feature-{feature.feature_id}",
                    feature.feature_id, "REVIEW_REQUIRED",
                    "未找到该候选特征的精确短语或显式变体。",
                    "人工核对同义表达、父概念、隐含公开和实施方式；不得仅凭未命中认定缺乏支持。",
                    [evidence_entry("features", f"feature:{feature.feature_id}", feature.text)],
                ))
                match_gaps.append(collector.gap(
                    "spec-match", MATCH_RULE_ID, f"feature-{feature.feature_id}",
                    "SEMANTIC_REVIEW_NOT_PERFORMED",
                    "未命中精确文本，同义表达和隐含公开必须由独立审阅者判断。",
                    [evidence_entry("features", f"feature:{feature.feature_id}", feature.text)],
                ))
        match_status = "PARTIAL"
    else:
        match_status = "SKIPPED"
    collector.check("spec-match", MATCH_RULE_ID, "features", match_status, match_findings, match_gaps)

    # 5. 语义边界：脚本能力之外的判断逐条形成结构化缺口，不允许静默消失。
    for rule_id, target_id, description in SEMANTIC_RULE_IDS:
        check_id = f"semantic-{rule_id.lower()}"
        gap_id = collector.gap(
            check_id, rule_id, target_id, "SEMANTIC_REVIEW_NOT_PERFORMED",
            f"确定性文本脚本不执行{description}。",
            [evidence_entry("specification-rules", rule_id)],
        )
        collector.check(check_id, rule_id, target_id, "NOT_VERIFIED", [], [gap_id])

    rule_bytes = RULE_MATRIX_PATH.read_bytes()
    contract_bytes = CONTRACT_PATH.read_bytes()
    tool_bytes = Path(__file__).resolve().read_bytes()
    features_payload = features_bytes if features_bytes is not None else canonical_json(
        [{"feature_id": item.feature_id, "text": item.text, "variants": list(item.variants)} for item in features]
    )
    input_artifacts = [
        make_artifact("specification", specification_name, specification_raw, "text/plain"),
        make_artifact("features", features_name, features_payload, "application/json"),
    ]
    rule_sources = [
        make_artifact("specification-rules", str(RULE_MATRIX_PATH), rule_bytes, "text/markdown"),
        make_artifact("review-contract", str(CONTRACT_PATH), contract_bytes, "application/json"),
    ]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "jurisdiction": JURISDICTION,
        "review_type": REVIEW_TYPE,
        "legal_effect": LEGAL_EFFECT,
        "report_id": stable_id("R", sha256_bytes(specification_raw), sha256_bytes(features_payload), sha256_bytes(tool_bytes)),
        "input_artifacts": input_artifacts,
        "rule_sources": rule_sources,
        "tool_identity": {
            "tool_id": TOOL_ID,
            "tool_version": TOOL_VERSION,
            "tool_sha256": sha256_bytes(tool_bytes),
            "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        },
        "evidence_binding": {
            "input_set_sha256": collection_digest(input_artifacts),
            "rule_set_sha256": collection_digest(rule_sources),
            "tool_set_sha256": sha256_bytes(tool_bytes),
        },
        "resource_limits": dict(RESOURCE_LIMITS),
        "resource_usage": {
            "input_bytes_total": len(specification_raw) + len(features_payload),
            "output_bytes": 0,
            "finding_count": len(collector.findings),
            "gap_count": len(collector.gaps),
            "check_count": len(collector.checks),
            "elapsed_milliseconds": budget.elapsed_milliseconds(),
        },
        "checks_performed": collector.checks,
        "findings": collector.findings,
        "gaps": collector.gaps,
    }
    serialize_report(report)
    return report


def serialize_report(report: dict[str, Any]) -> bytes:
    """输出字节长度写回 usage，迭代到固定点后再检查输出上限。"""

    payload = b""
    for _ in range(4):
        payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        if len(payload) > MAX_OUTPUT_BYTES:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 原始报告输出超过上限 {MAX_OUTPUT_BYTES}")
        if report["resource_usage"]["output_bytes"] == len(payload):
            return payload
        report["resource_usage"]["output_bytes"] = len(payload)
    return payload


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def paths_alias(first: Path, second: Path) -> bool:
    """比较规范化路径，并在文件已存在时识别符号链接或硬链接别名。"""

    first_key = os.path.normcase(os.path.abspath(os.fspath(first.resolve(strict=False))))
    second_key = os.path.normcase(os.path.abspath(os.fspath(second.resolve(strict=False))))
    if first_key == second_key:
        return True
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def ensure_output_is_distinct(output: Path | None, protected_inputs: list[Path]) -> None:
    if output is None:
        return
    for input_path in protected_inputs:
        if paths_alias(output, input_path):
            raise ValueError(f"{OUTPUT_RULE_ID}: 输出路径不得与输入文件相同或互为别名：{input_path}")


def write_report(report: dict[str, Any], output: Path | None, *, protected_inputs: list[Path] | None = None) -> None:
    payload = serialize_report(report)
    if output is None:
        sys.stdout.buffer.write(payload)
        return
    inputs = protected_inputs or []
    ensure_output_is_distinct(output, inputs)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        ensure_output_is_distinct(output, inputs)
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def read_specification(path: Path) -> tuple[bytes, str]:
    size = path.stat().st_size
    if size > MAX_SPECIFICATION_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 说明书输入超过 {MAX_SPECIFICATION_BYTES} 字节上限")
    raw = path.read_bytes()
    if len(raw) > MAX_SPECIFICATION_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 说明书输入超过 {MAX_SPECIFICATION_BYTES} 字节上限")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise UnicodeError(f"{INPUT_RULE_ID}: 说明书必须是 UTF-8 无 BOM")
    return raw, raw.decode("utf-8")


def read_features(path: Path) -> tuple[bytes, list[Feature]]:
    size = path.stat().st_size
    if size > MAX_FEATURES_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 候选特征输入超过 {MAX_FEATURES_BYTES} 字节上限")
    raw = path.read_bytes()
    if len(raw) > MAX_FEATURES_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 候选特征输入超过 {MAX_FEATURES_BYTES} 字节上限")
    return raw, parse_features_bytes(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成中国发明专利说明书的 CN v2 原始检查报告")
    parser.add_argument("--specification", required=True, type=Path, help="UTF-8 无 BOM 说明书文本")
    parser.add_argument("--features", required=True, type=Path, help="UTF-8 无 BOM 候选技术特征 JSON")
    parser.add_argument("--output", type=Path, help="独立 JSON 原始报告路径；省略时输出到 stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protected_inputs = [args.specification, args.features]
    try:
        ensure_output_is_distinct(args.output, protected_inputs)
        specification_raw, specification = read_specification(args.specification)
        features_raw, features = read_features(args.features)
        report = build_raw_report(
            specification,
            features,
            specification_bytes=specification_raw,
            features_bytes=features_raw,
            specification_name=str(args.specification),
            features_name=str(args.features),
        )
        write_report(report, args.output, protected_inputs=protected_inputs)
        return 2 if any(item["status"] == "DETERMINISTIC_FAIL" for item in report["findings"]) else 0
    except ResourceLimitError as exc:
        print(f"说明书检查资源失败：{exc}", file=sys.stderr)
        return FAILURE_EXIT_CODE
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"说明书检查失败：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
