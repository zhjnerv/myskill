#!/usr/bin/env python3
"""中国直接发明申请的 CN v2 形式/程序原始检查器。

本模块只做可复算的输入、文书和交叉一致性检查。未知、条件不明和
未覆盖的语义事项都记录为结构化 gap，不把能力边界包装成法律结论。
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
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "cn-patent-review-raw-report/v2"
INPUT_SCHEMA_VERSION = "cn-patent-application-manifest/v2"
JURISDICTION = "CN"
REVIEW_TYPE = "formalities"
LEGAL_EFFECT = "ADVISORY_ONLY"
TOOL_ID = "cn-patent-formalities-reviewer"
TOOL_VERSION = "2.1.0"
CONTRACT_SCHEMA_VERSION = "cn-patent-review-contract/v2"

FORMALITY_RULES = (
    "form_core_documents_and_application_type",
    "form_request_fields_and_party_identity",
    "form_language_format_and_execution",
    "form_title_consistency_and_quality",
    "form_specification_structure_and_drafting",
    "form_claim_presentation_and_reference_form",
    "form_abstract_content_and_length",
    "form_abstract_figure_designation",
    "form_drawings_requiredness_and_presence",
    "form_drawing_numbering_reference_signs_and_graphic_form",
    "form_sequence_listing",
    "form_biological_material_deposit",
    "form_genetic_resource_statement",
    "form_priority_declaration_and_documents",
    "form_article_24_declaration_and_proof",
    "form_divisional_filing_procedure",
    "form_substantive_examination_request_procedure",
)

DOCUMENT_KEYS = (
    "request",
    "specification",
    "claims",
    "abstract",
    "drawings",
    "sequence_listing",
    "biological_material_deposit",
    "genetic_resource_statement",
    "priority_documents",
    "article_24_proof",
    "divisional_documents",
    "substantive_examination_request",
)
DOCUMENT_KEY_SET = set(DOCUMENT_KEYS)
REQUIRED_CORE_DOCUMENTS = {"request", "specification", "claims", "abstract"}
ALLOWED_DOCUMENT_STATES = {"provided", "confirmed_absent", "unknown", "not_applicable"}
ALLOWED_APPLICATION_TYPES = {"invention"}
ALLOWED_FILING_MEDIA = {"electronic", "paper", "unknown"}
ALLOWED_SCOPE = {"direct_cn_invention_application"}
MAX_TOTAL_DOCUMENT_BYTES = 25_165_824
MAX_MANIFEST_BYTES = 4_194_304
MAX_SINGLE_DOCUMENT_BYTES = 8_388_608
MAX_DOCUMENTS = 256
MAX_STRING_BYTES = 1_048_576
MAX_JSON_DEPTH = 64
MAX_FINDINGS = 5_000
MAX_GAPS = 5_000
MAX_CHECKS = 10_000
MAX_OUTPUT_BYTES = 16_777_216
FAILURE_EXIT_CODE = 4
INPUT_ERROR_EXIT_CODE = 3
FAILURE_STATUS_EXIT_CODE = 2
DEADLINE_SECONDS = 180
MAX_FIGURES = 100_000
MAX_SECTION_HEADINGS = 100_000

RESOURCE_LIMITS = {
    "claims_input_bytes": 4_194_304, "claims_max_count": 20_000, "claims_max_number": 1_000_000,
    "claims_max_reference_edges": 100_000, "claims_max_ancestor_depth": 2_048, "claims_max_single_text_bytes": 262_144,
    "specification_input_bytes": 8_388_608, "specification_features_input_bytes": 4_194_304,
    "specification_max_paragraphs": 100_000, "specification_max_feature_candidates": 20_000,
    "specification_max_variants_per_feature": 32, "specification_max_matches_per_feature": 1_000,
    "specification_max_total_matches": 100_000, "formalities_input_bytes_total": MAX_TOTAL_DOCUMENT_BYTES,
    "formalities_manifest_bytes": MAX_MANIFEST_BYTES, "formalities_max_documents": MAX_DOCUMENTS,
    "formalities_max_single_document_bytes": MAX_SINGLE_DOCUMENT_BYTES,
    "formalities_max_string_bytes": MAX_STRING_BYTES, "verifier_referenced_bytes": 134_217_728,
    "verifier_max_artifacts": 512, "verifier_max_rule_sources": 256, "verifier_max_raw_reports": 3,
    "verifier_max_subreports": 3, "verifier_max_single_artifact_bytes": 25_165_824,
    "json_max_depth": MAX_JSON_DEPTH, "max_findings": MAX_FINDINGS, "max_gaps": MAX_GAPS,
    "max_checks": MAX_CHECKS, "max_report_output_bytes": MAX_OUTPUT_BYTES,
    "max_summary_output_bytes": 8_388_608, "orchestration_deadline_seconds": DEADLINE_SECONDS,
    "failure_exit_code": FAILURE_EXIT_CODE,
    "failure_rule": "A resource failure is a tool error and must not create a legal finding.",
}

ALLOWED_MANIFEST_FIELDS = {
    "schema_version", "application_scope", "application_type", "filing_medium", "documents", "titles",
    "request_fields", "execution", "abstract_figure", "sequence_listing", "biological_material_deposit",
    "genetic_resource_statement", "priority_documents", "article_24_proof", "divisional_documents",
    "substantive_examination_request",
}

SECTION_NAMES = ("技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式")
SECTION_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(技术领域|背景技术|发明内容|附图说明|具体实施方式)\s*$", re.MULTILINE)
FIGURE_RE = re.compile(r"图\s*([0-9]+|[一二三四五六七八九十百]+)([A-Za-z]?)", re.IGNORECASE)
FIGURE_RANGE_RE = re.compile(r"图\s*([0-9]+|[一二三四五六七八九十百]+)([A-Za-z]?)\s*(?:至|[-—–~])\s*(?:图\s*)?([0-9]+|[一二三四五六七八九十百]+)([A-Za-z]?)(?![A-Za-z])", re.IGNORECASE)
ABSTRACT_HEADING_RE = re.compile(r"^(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?(?:说明书\s*)?摘\s*要\s*(?:(?:\*\*|__)\s*)?(?:#+\s*)?$")
TITLE_INLINE_RE = re.compile(r"^\s*(?:发明(?:或者)?名称|实用新型(?:名称)?|名称)\s*[：:]\s*(\S.*?)\s*$")
TITLE_HEADING_RE = re.compile(r"^\s*(?:发明(?:或者)?名称|实用新型(?:名称)?|名称)\s*$")
TITLE_SKIP_LINE_RE = re.compile(r"^\s*(?:说明书|请求书|摘要|权利要求书)\s*$")
MARKDOWN_HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s*")
TITLE_MAX_RECOMMENDED_CHARS = 25
TITLE_MAX_EXTRACT_CHARS = 60
STRONG_PLACEHOLDER_RE = re.compile(r"(?:【[^】]{0,200}(?:内部|待填|待补|占位|TODO|TBD)[^】]{0,200}】|<\s*(?:TODO|TBD|待填|待补|占位)(?:\s*[：:][^>]*)?\s*>|(?<![A-Za-z0-9])(?:TODO|TBD|XXX)(?![A-Za-z0-9]))", re.IGNORECASE)
WEAK_DRAFT_SIGNAL_RE = re.compile(r"(?:待补充|待完善|待确认)")
PROMOTIONAL_TERMS = ("世界领先", "国际领先", "国内领先", "最先进", "最佳", "完美", "革命性", "唯一", "绝对", "无与伦比")

# 附图标记清单的提交形态筛查。中国说明书按撰写惯例把附图标记写成"附图说明"章节末尾的
# 单段句式"图中：100-高稳定参考时钟源、110-频率基准单元。"；表格、项目符号和逐行清单
# 在 CPC 电子申请的纯文本正文里会被打散或丢失。形态本身不是法定禁止事项，因此只记 WARNING。
MD_TABLE_DIVIDER_RE = re.compile(r"^\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*$")
MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+•]\s+|\(?\d{1,3}\)?\s*[.、)．]\s*)\S")
# 逐行清单只统计"整行仅一个标记条目"的情况；含顿号或逗号的行按单段句式的折行处理，不计入。
REFERENCE_SIGN_LINE_RE = re.compile(r"^\s*\(?\d{1,4}\)?\s*[-—–－:：]\s*\S")
MAX_FIGURE_SECTION_LINES = 100_000


class ResourceLimitError(Exception):
    """工具资源越限；不得转换为法律 finding。"""


class InputContractError(ValueError):
    """manifest、路径或编码违反输入规范。"""


class DocumentUnavailableError(Exception):
    """路径型文书本轮不可读取，不代表申请包实际缺件。"""


class Collector:
    def __init__(self, deadline: float):
        self.findings: list[dict[str, Any]] = []
        self.gaps: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.deadline = deadline

    def guard(self) -> None:
        if time.monotonic() > self.deadline:
            raise ResourceLimitError("形式检查超过 180 秒编排时限")

    def check(self, rule_id: str, target_id: str, status: str, finding_ids: Iterable[str] = (), gap_ids: Iterable[str] = ()) -> str:
        self.guard()
        if len(self.checks) >= MAX_CHECKS:
            raise ResourceLimitError("checks 数量超过上限")
        check_id = f"CHK-{len(self.checks) + 1:04d}-{rule_id}"
        item = {"check_id": check_id, "rule_id": rule_id, "target_id": target_id, "status": status, "finding_ids": list(finding_ids), "gap_ids": list(gap_ids)}
        self.checks.append(item)
        return check_id

    def finding(self, rule_id: str, target_id: str, location: str, problem: str, remedy: str, status: str = "REVIEW_REQUIRED", evidence: list[dict[str, str]] | None = None) -> str:
        self.guard()
        if len(self.findings) >= MAX_FINDINGS:
            raise ResourceLimitError("finding 数量超过上限")
        finding_id = f"F-{len(self.findings) + 1:04d}-{rule_id}"
        self.findings.append({
            "finding_id": finding_id,
            "check_id": "",  # finalize_checks fills this after the check is known
            "rule_id": rule_id,
            "target_id": target_id,
            "location": location,
            "status": status,
            "evidence": evidence or [],
            "problem": problem,
            "remedy": remedy,
            "manual_review_required": status != "DETERMINISTIC_FAIL",
        })
        return finding_id

    def gap(self, rule_id: str, target_id: str, category: str, reason: str, blocks_assessment: bool = True, evidence: list[dict[str, str]] | None = None) -> str:
        self.guard()
        if len(self.gaps) >= MAX_GAPS:
            raise ResourceLimitError("gap 数量超过上限")
        gap_id = f"G-{len(self.gaps) + 1:04d}-{rule_id}"
        self.gaps.append({
            "gap_id": gap_id,
            "check_id": "",
            "rule_id": rule_id,
            "target_id": target_id,
            "category": category,
            "reason": reason,
            "evidence": evidence or [],
            "blocks_assessment": blocks_assessment,
        })
        return gap_id


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def collection_digest(items: list[dict[str, str]]) -> str:
    return sha256_bytes(canonical_json(sorted(items, key=lambda item: item["id"])))


def check_bom(raw: bytes, label: str) -> None:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise InputContractError(f"{label} 含 UTF-8 BOM；CN v2 只接受 UTF-8 无 BOM")


def ensure_json_depth(value: Any, max_depth: int = MAX_JSON_DEPTH) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            raise ResourceLimitError(f"JSON 嵌套深度超过 {max_depth}")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str) and len(current.encode("utf-8")) > MAX_STRING_BYTES:
            raise ResourceLimitError("JSON 字符串超过上限")


def resolve_under(base: Path, raw_path: str) -> Path:
    candidate = (base / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise InputContractError(f"文书路径越出 manifest 目录：{raw_path}") from exc
    return candidate


def normalize_document_entry(name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        if not value.strip():
            raise InputContractError(f"文书 {name} 的路径不能为空")
        return {"status": "provided", "path": value}
    if value is None:
        return {"status": "unknown"}
    if not isinstance(value, dict):
        raise InputContractError(f"文书 {name} 必须是对象或路径字符串")
    allowed = {"status", "path", "content"}
    if set(value) - allowed:
        raise InputContractError(f"文书 {name} 含未知字段")
    state = value.get("status", "unknown")
    if state not in ALLOWED_DOCUMENT_STATES:
        raise InputContractError(f"文书 {name} 的 status 无效：{state}")
    has_path, has_content = "path" in value, "content" in value
    if state == "provided":
        if has_path == has_content:
            raise InputContractError(f"文书 {name} 在 provided 状态下必须且只能提供 path 或 content")
        if has_path and (not isinstance(value["path"], str) or not value["path"].strip()):
            raise InputContractError(f"文书 {name} 的 path 必须是非空字符串")
        if has_content and not isinstance(value["content"], str):
            raise InputContractError(f"文书 {name} 的 content 必须是字符串")
    elif has_path or has_content:
        raise InputContractError(f"文书 {name} 在 {state} 状态下不得携带 path 或 content")
    return dict(value)


def read_limited(path: Path, limit: int, label: str) -> bytes:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise DocumentUnavailableError(f"无法读取 {label}：{exc}") from exc
    if len(raw) > limit:
        raise ResourceLimitError(f"{label} 超过 {limit} 字节上限")
    check_bom(raw, label)
    return raw


def canonical_figure_id(value: Any) -> str:
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).upper()
    match = re.fullmatch(r"([0-9]+|[一二三四五六七八九十百]+)([A-Z]?)", normalized)
    if not match:
        raise InputContractError(f"图号格式无效：{value}")
    number, suffix = match.groups()
    if not number.isdigit():
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if number == "十":
            number = "10"
        elif "十" in number:
            tens, ones = number.split("十", 1)
            number = str((digits.get(tens, 1) * 10) + digits.get(ones, 0))
        elif number == "百":
            number = "100"
        else:
            number = str(digits[number])
    return number + suffix


def figure_ids(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text)
    found: set[str] = set()
    for match in FIGURE_RANGE_RE.finditer(normalized):
        start, start_suffix, end, end_suffix = match.groups()
        if start_suffix or end_suffix:
            continue
        try:
            first, last = int(canonical_figure_id(start)), int(canonical_figure_id(end))
        except (InputContractError, ValueError):
            continue
        if last >= first and last - first <= 1000:
            found.update(str(number) for number in range(first, last + 1))
    for match in FIGURE_RE.finditer(normalized):
        found.add(canonical_figure_id(match.group(1) + match.group(2)))
        if len(found) > MAX_FIGURES:
            raise ResourceLimitError("图号数量超过上限")
    return found


def abstract_body(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if ABSTRACT_HEADING_RE.fullmatch(line.strip()):
            return "\n".join(lines[index + 1 :])
        break
    return text


def clean_title_line(line: str) -> str:
    """移除 Markdown 标题和成对强调标记，保留名称正文。"""

    stripped = MARKDOWN_HEADING_PREFIX_RE.sub("", line.strip()).strip()
    for marker in ("**", "__"):
        if stripped.startswith(marker) and stripped.endswith(marker) and len(stripped) > len(marker) * 2:
            stripped = stripped[len(marker) : -len(marker)].strip()
            break
    return stripped


def plausible_title_line(line: str, *, enforce_extract_limit: bool = True) -> bool:
    stripped = clean_title_line(line)
    normalized = unicoded_title(stripped)
    if not normalized:
        return False
    if enforce_extract_limit and len(normalized) > TITLE_MAX_EXTRACT_CHARS:
        return False
    if TITLE_SKIP_LINE_RE.fullmatch(stripped):
        return False
    if TITLE_HEADING_RE.fullmatch(stripped):
        return False
    if ABSTRACT_HEADING_RE.fullmatch(stripped):
        return False
    if SECTION_RE.fullmatch(stripped):
        return False
    if stripped.endswith(("。", "；", "！", "？", ";", "!", "?")):
        return False
    return True


def first_nonempty(lines: list[str], start: int, stop: int) -> tuple[int, str] | None:
    upper = min(stop, len(lines))
    for index in range(start, upper):
        if lines[index].strip():
            return index, lines[index].strip()
    return None


def extract_title_from_document(name: str, text: str) -> tuple[str | None, str]:
    """从真实文书中尽量保守地提取名称。

    只接受显式标签，或说明书/摘要开头极窄窗口内的短行候选，避免把正文首句误判成标题。
    """

    lines = text.splitlines()
    for index, line in enumerate(lines[:20]):
        match = TITLE_INLINE_RE.fullmatch(clean_title_line(line))
        if match:
            return clean_title_line(match.group(1)), f"title_line:{index + 1}"

    for index, line in enumerate(lines[:20]):
        if TITLE_HEADING_RE.fullmatch(clean_title_line(line)):
            candidate = first_nonempty(lines, index + 1, index + 4)
            if candidate and plausible_title_line(candidate[1], enforce_extract_limit=False):
                return clean_title_line(candidate[1]), f"title_line:{candidate[0] + 1}"

    nonempty = [(index, clean_title_line(line)) for index, line in enumerate(lines[:20]) if line.strip()]
    if name == "specification":
        title_window: list[tuple[int, str]] = []
        for index, line in nonempty:
            if SECTION_RE.fullmatch(line):
                break
            if TITLE_SKIP_LINE_RE.fullmatch(line) or TITLE_HEADING_RE.fullmatch(line):
                continue
            title_window.append((index, line))
        if len(title_window) == 1 and plausible_title_line(title_window[0][1]):
            return title_window[0][1], f"title_line:{title_window[0][0] + 1}"
    if name == "abstract":
        for index, line in nonempty[:3]:
            if ABSTRACT_HEADING_RE.fullmatch(line):
                candidate = first_nonempty(lines, index + 1, index + 4)
                if candidate and plausible_title_line(candidate[1], enforce_extract_limit=False):
                    next_line = first_nonempty(lines, candidate[0] + 1, candidate[0] + 3)
                    if next_line is not None:
                        return clean_title_line(candidate[1]), f"title_line:{candidate[0] + 1}"
    return None, ""


def split_sections(text: str) -> tuple[list[str], dict[str, str]]:
    matches = list(SECTION_RE.finditer(text))
    if len(matches) > MAX_SECTION_HEADINGS:
        raise ResourceLimitError("说明书章节标题数量超过上限")
    found = [match.group(1) for match in matches]
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end]
    return found, sections


def reference_sign_form_issues(section: str) -> list[tuple[str, str]]:
    """筛查"附图说明"章节里附图标记与各图说明的呈现形态。

    返回 [(形态标签, 首个命中行原文)]，每种形态最多一条。只判断排版形态，不判断标记
    指向、名称是否与正文一致或图面质量——那些需要视觉核验，仍由 CAPABILITY_LIMIT gap 承接。
    """
    lines = section.splitlines()
    if len(lines) > MAX_FIGURE_SECTION_LINES:
        raise ResourceLimitError("附图说明章节行数超过上限")
    hits: dict[str, str] = {}
    consecutive_rows = 0
    sign_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if MD_TABLE_ROW_RE.match(line):
            consecutive_rows += 1
            # 分隔行可单独定案；否则需连续两行表格行，避免正文里孤立的竖线误报。
            if (MD_TABLE_DIVIDER_RE.match(line) or consecutive_rows >= 2) and "表格" not in hits:
                hits["表格"] = stripped[:120]
        else:
            consecutive_rows = 0
        if LIST_MARKER_RE.match(line) and "列表" not in hits:
            hits["列表"] = stripped[:120]
        if REFERENCE_SIGN_LINE_RE.match(line) and not ("、" in stripped or "，" in stripped):
            sign_lines.append(stripped[:120])
    if len(sign_lines) >= 2:
        hits["逐行清单"] = sign_lines[0]
    return sorted(hits.items())


def make_artifact(artifact_id: str, path: str, raw: bytes, media_type: str = "text/plain") -> dict[str, Any]:
    return {"artifact_id": artifact_id, "path": path, "sha256": sha256_bytes(raw), "byte_length": len(raw), "media_type": media_type, "encoding": "utf-8"}


def load_documents(manifest: dict[str, Any], manifest_path: Path, collector: Collector) -> tuple[dict[str, str | None], dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    documents = manifest.get("documents")
    if not isinstance(documents, dict):
        raise InputContractError("documents 必须是对象")
    if len(documents) > MAX_DOCUMENTS:
        raise ResourceLimitError("文书数量超过上限")
    unknown = set(documents) - DOCUMENT_KEY_SET
    if unknown:
        raise InputContractError("documents 含未知文书角色：" + ", ".join(sorted(unknown)))
    base = manifest_path.parent.resolve()
    contents: dict[str, str | None] = {}
    metadata: dict[str, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []
    total = 0
    for name in DOCUMENT_KEYS:
        entry = normalize_document_entry(name, documents.get(name))
        state = entry.get("status", "unknown")
        metadata[name] = {"status": state}
        contents[name] = None
        if state != "provided":
            continue
        if "content" in entry:
            raw = entry["content"].encode("utf-8")
            check_bom(raw, f"文书 {name}")
            source_path = f"inline://{name}"
        else:
            path = resolve_under(base, entry["path"])
            try:
                raw = read_limited(path, MAX_SINGLE_DOCUMENT_BYTES, f"文书 {name}")
            except DocumentUnavailableError as exc:
                metadata[name]["path"] = str(entry["path"])
                gap_id = collector.gap(
                    "form_core_documents_and_application_type",
                    name,
                    "INPUT_UNAVAILABLE",
                    "manifest 声明文书已提供，但本轮无法读取其内容；不得推定实际缺件。",
                    evidence=evidence("application-manifest", f"documents.{name}", str(exc)),
                )
                continue
            source_path = str(path)
            metadata[name]["path"] = str(entry["path"])
        if len(raw) > MAX_SINGLE_DOCUMENT_BYTES:
            raise ResourceLimitError(f"文书 {name} 超过单文书字节上限")
        total += len(raw)
        if total > MAX_TOTAL_DOCUMENT_BYTES:
            raise ResourceLimitError("形式审查文书总字节数超过 24 MiB 上限")
        content = raw.decode("utf-8")
        contents[name] = content
        metadata[name].update({"sha256": sha256_bytes(raw), "byte_length": len(raw)})
        artifacts.append(make_artifact(name, source_path, raw))
        if not content.strip():
            collector.finding("form_core_documents_and_application_type", name, name, "已声明 provided 的文书内容为空。", "补齐真实文书内容后重新检查。", status="DETERMINISTIC_FAIL")
    return contents, metadata, artifacts, total


def evidence(artifact_id: str, location: str, excerpt: str = "") -> list[dict[str, str]]:
    return [{"artifact_id": artifact_id, "location": location, "excerpt": excerpt[:MAX_STRING_BYTES]}]


def document_evidence(available: set[str], document: str, location: str, excerpt: str = "") -> list[dict[str, str]]:
    """文书未被读入时把证据锚回 manifest 声明，避免指向未声明的 artifact。

    verifier 需要按 artifact_id 复算来源，指向不存在的 artifact 等于来源映射断裂。
    """

    if document in available:
        return evidence(document, location, excerpt)
    return evidence("application-manifest", f"documents.{document}:{location}", excerpt)


def title_evidence(available: set[str], document: str, extracted_location: str, excerpt: str = "") -> list[dict[str, str]]:
    location = extracted_location or "title"
    return document_evidence(available, document, location, excerpt)


def add_conditional_check(collector: Collector, manifest: dict[str, Any], key: str, rule_id: str, target: str, artifact_ids: set[str]) -> None:
    value = manifest.get(key)
    if value is None:
        gap = collector.gap(rule_id, target, "CONDITIONAL_APPLICABILITY_UNRESOLVED", f"未提供 {key} 的适用性和证明材料。", evidence=evidence("application-manifest", key))
        collector.check(rule_id, target, "NOT_VERIFIED", gap_ids=[gap])
        return
    if not isinstance(value, dict):
        raise InputContractError(f"{key} 必须是对象")
    allowed = {"applicability", "status", "evidence", "document_ids", "details"}
    if set(value) - allowed:
        raise InputContractError(f"{key} 含未知字段")
    applicability = value.get("applicability", "unknown")
    if applicability not in {"applicable", "not_applicable", "unknown"}:
        raise InputContractError(f"{key}.applicability 无效")
    item_evidence = value.get("evidence", "")
    if not isinstance(item_evidence, str) or len(item_evidence.encode("utf-8")) > MAX_STRING_BYTES:
        raise ResourceLimitError(f"{key}.evidence 超过字符串上限")
    if applicability == "not_applicable" and item_evidence.strip():
        collector.check(rule_id, target, "COMPLETED")
        return
    if applicability == "applicable" and value.get("status") == "confirmed_absent":
        finding = collector.finding(rule_id, target, key, f"已声明 {key} 适用但法定材料被确认缺失。", "补齐材料并重新检查。", status="DETERMINISTIC_FAIL", evidence=evidence("application-manifest", key, item_evidence))
        collector.check(rule_id, target, "COMPLETED", finding_ids=[finding])
        return
    if applicability == "applicable" and value.get("status") == "provided":
        refs = value.get("document_ids", [])
        if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
            raise InputContractError(f"{key}.document_ids 必须是字符串数组")
        unknown = set(refs) - artifact_ids
        if unknown:
            raise InputContractError(f"{key}.document_ids 引用未知文书：{sorted(unknown)}")
        gap = collector.gap(rule_id, target, "SEMANTIC_REVIEW_NOT_PERFORMED", f"{key} 的实体/程序条件仍需独立人工复核。", evidence=evidence("application-manifest", key, item_evidence))
        collector.check(rule_id, target, "PARTIAL", gap_ids=[gap])
        return
    gap = collector.gap(rule_id, target, "CONDITIONAL_APPLICABILITY_UNRESOLVED", f"{key} 的适用性、状态或证明材料不足。", evidence=evidence("application-manifest", key, item_evidence))
    collector.check(rule_id, target, "NOT_VERIFIED", gap_ids=[gap])


def analyse(manifest: dict[str, Any], manifest_path: Path, manifest_raw: bytes) -> tuple[dict[str, Any], bytes]:
    start = time.monotonic()
    collector = Collector(start + DEADLINE_SECONDS)
    unknown_manifest_fields = set(manifest) - ALLOWED_MANIFEST_FIELDS
    if unknown_manifest_fields:
        raise InputContractError("manifest 含未知字段：" + ", ".join(sorted(unknown_manifest_fields)))
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise InputContractError(f"manifest schema_version 必须为 {INPUT_SCHEMA_VERSION}")
    if manifest.get("application_scope") not in ALLOWED_SCOPE:
        raise InputContractError("本检查器只接受 direct_cn_invention_application；PCT 国家阶段必须拒绝或转后续条件模块")
    if manifest.get("application_type") not in ALLOWED_APPLICATION_TYPES:
        raise InputContractError("application_type 必须为 invention")
    filing_medium = manifest.get("filing_medium", "unknown")
    if filing_medium not in ALLOWED_FILING_MEDIA:
        raise InputContractError("filing_medium 无效")
    documents, metadata, artifacts, total_bytes = load_documents(manifest, manifest_path, collector)
    artifact_ids = {item["artifact_id"] for item in artifacts} | {"application-manifest"}
    artifacts.insert(0, make_artifact("application-manifest", str(manifest_path), manifest_raw, "application/json"))
    titles = manifest.get("titles", {})
    if not isinstance(titles, dict) or set(titles) - {"request", "specification", "abstract"} or any(not isinstance(k, str) or not isinstance(v, str) for k, v in titles.items()):
        raise InputContractError("titles 必须是 request/specification/abstract 字符串对象")
    specification = documents.get("specification") or ""
    abstract = documents.get("abstract") or ""
    claims = documents.get("claims") or ""
    found_sections, sections = split_sections(specification)
    findings_by_rule: dict[str, list[str]] = {}
    gaps_by_rule: dict[str, list[str]] = {}

    def register(rule: str, target: str, status: str, finding_ids: Iterable[str] = (), gap_ids: Iterable[str] = ()) -> None:
        complete_findings = list(dict.fromkeys([
            *finding_ids,
            *(item["finding_id"] for item in collector.findings if item["rule_id"] == rule),
        ]))
        complete_gaps = list(dict.fromkeys([
            *gap_ids,
            *(item["gap_id"] for item in collector.gaps if item["rule_id"] == rule),
        ]))
        findings_by_rule[rule] = complete_findings
        gaps_by_rule[rule] = complete_gaps
        collector.check(rule, target, status, complete_findings, complete_gaps)

    # 1. 核心文件和直接申请范围。
    core_findings: list[str] = []
    for name in sorted(REQUIRED_CORE_DOCUMENTS):
        state = metadata[name]["status"]
        if state == "confirmed_absent":
            core_findings.append(collector.finding("form_core_documents_and_application_type", name, name, "核心申请文件已被确认实际缺失。", "补齐文件后重新检查。", status="DETERMINISTIC_FAIL", evidence=evidence("application-manifest", f"documents.{name}")))
        elif state in {"unknown", "not_applicable"}:
            gap_id = collector.gap("form_core_documents_and_application_type", name, "INPUT_UNAVAILABLE", f"无法确认核心文书 {name} 是否存在。", evidence=evidence("application-manifest", f"documents.{name}"))
            gaps_by_rule.setdefault("form_core_documents_and_application_type", []).append(gap_id)
    has_core_gaps = any(item["rule_id"] == "form_core_documents_and_application_type" for item in collector.gaps)
    register("form_core_documents_and_application_type", "application", "COMPLETED" if not core_findings and not has_core_gaps else ("PARTIAL" if not core_findings else "COMPLETED"), core_findings, gaps_by_rule.get("form_core_documents_and_application_type", []))

    # 2. 请求书字段和主体身份：字段存在只能证明声明，不证明权属或真实性。
    request_fields = manifest.get("request_fields")
    required_fields = ("applicant", "inventor", "address")
    if not isinstance(request_fields, dict):
        gap = collector.gap("form_request_fields_and_party_identity", "request", "INPUT_UNAVAILABLE", "没有提供结构化请求书主体字段。", evidence=evidence("application-manifest", "request_fields"))
        register("form_request_fields_and_party_identity", "request", "NOT_VERIFIED", gap_ids=[gap])
    else:
        missing = [field for field in required_fields if not isinstance(request_fields.get(field), str) or not request_fields[field].strip()]
        if missing:
            finding = collector.finding("form_request_fields_and_party_identity", "request", "request_fields", "结构化请求书缺少主体字段：" + ", ".join(missing), "补齐字段并核对官方请求书。", status="DETERMINISTIC_FAIL", evidence=evidence("application-manifest", "request_fields"))
            register("form_request_fields_and_party_identity", "request", "COMPLETED", finding_ids=[finding])
        else:
            gap = collector.gap("form_request_fields_and_party_identity", "request", "SEMANTIC_REVIEW_NOT_PERFORMED", "字段存在，但主体身份、签章真实性和权属未独立核验。", evidence=evidence("application-manifest", "request_fields"))
            register("form_request_fields_and_party_identity", "request", "PARTIAL", gap_ids=[gap])

    # 3. 语言、格式和签章。
    execution = manifest.get("execution")
    execution_findings: list[str] = []
    for document_name, content in documents.items():
        if not content:
            continue
        for pattern, status, problem, remedy in (
            (STRONG_PLACEHOLDER_RE, "DETERMINISTIC_FAIL", "提交包文本中存在强结构草稿占位或内部评注。", "补齐或删除草稿残留后重新检查。"),
            (WEAK_DRAFT_SIGNAL_RE, "REVIEW_REQUIRED", "提交包文本中存在可能是草稿残留的弱信号。", "结合上下文人工核对。"),
        ):
            for match in pattern.finditer(content):
                execution_findings.append(
                    collector.finding(
                        "form_language_format_and_execution",
                        document_name,
                        document_name,
                        problem,
                        remedy,
                        status=status,
                        evidence=evidence(document_name, "draft_signal", match.group(0)),
                    )
                )
    if not isinstance(execution, dict):
        gap = collector.gap("form_language_format_and_execution", "application", "INPUT_UNAVAILABLE", "未提供语言、格式和签章声明。", evidence=evidence("application-manifest", "execution"))
        register("form_language_format_and_execution", "application", "NOT_VERIFIED", execution_findings, [gap])
    else:
        missing = [key for key in ("language", "signature_status") if not isinstance(execution.get(key), str) or not execution[key].strip()]
        if missing:
            finding = collector.finding("form_language_format_and_execution", "application", "execution", "提交格式声明缺少：" + ", ".join(missing), "补齐声明并核对原始提交材料。", status="DETERMINISTIC_FAIL", evidence=evidence("application-manifest", "execution"))
            register("form_language_format_and_execution", "application", "COMPLETED", [*execution_findings, finding])
        else:
            gap = collector.gap("form_language_format_and_execution", "application", "SEMANTIC_REVIEW_NOT_PERFORMED", "文本编码已由工具验证，但法定格式、签章和译文未独立核验。", evidence=evidence("application-manifest", "execution"))
            register("form_language_format_and_execution", "application", "PARTIAL", execution_findings, [gap])

    # 4. 名称优先从真实文书提取；manifest 仅作为人工声明回退。
    title_values = [titles.get(key, "").strip() for key in ("request", "specification", "abstract")]
    title_findings: list[str] = []
    if any(not value for value in title_values):
        title_findings.append(collector.finding("form_title_consistency_and_quality", "titles", "titles", "一个或多个文书标题声明为空。", "补齐标题并从真实文书独立核验。", status="DETERMINISTIC_FAIL", evidence=evidence("application-manifest", "titles")))
    elif len(set(unicoded_title(value) for value in title_values)) > 1:
        title_findings.append(collector.finding("form_title_consistency_and_quality", "titles", "titles", "请求书、说明书和摘要的 manifest 标题声明不一致。", "从三份真实文书独立提取标题后复核。", status="REVIEW_REQUIRED", evidence=evidence("application-manifest", "titles")))
    extracted_titles: dict[str, tuple[str, str]] = {}
    for document_name in ("request", "specification", "abstract"):
        content = documents.get(document_name)
        if not content:
            continue
        extracted_title, location = extract_title_from_document(document_name, content)
        if extracted_title:
            extracted_titles[document_name] = (extracted_title, location)
    normalized_extracted = {
        name: unicoded_title(value)
        for name, (value, _location) in extracted_titles.items()
    }
    for document_name, (value, location) in extracted_titles.items():
        declared_title = titles.get(document_name, "").strip()
        if declared_title and unicoded_title(value) != unicoded_title(declared_title):
            title_findings.append(
                collector.finding(
                    "form_title_consistency_and_quality",
                    document_name,
                    f"{document_name}.title",
                    f"从真实文书提取的名称“{value}”与 manifest 声明“{declared_title}”不一致。",
                    "以真实文书正式名称栏位为准，修正 manifest 声明或文书名称。",
                    status="REVIEW_REQUIRED",
                    evidence=[
                        *title_evidence(artifact_ids, document_name, location, value),
                        *evidence("application-manifest", f"titles.{document_name}", declared_title),
                    ],
                )
            )
    if len(set(normalized_extracted.values())) > 1:
        evidence_items: list[dict[str, str]] = []
        for document_name, (value, location) in extracted_titles.items():
            evidence_items.extend(title_evidence(artifact_ids, document_name, location, value))
        title_findings.append(
            collector.finding(
                "form_title_consistency_and_quality",
                "titles",
                "titles",
                "从真实文书提取的请求书、说明书或摘要名称不一致。",
                "以三份真实文书为准核对名称，并同步修正不一致处。",
                status="REVIEW_REQUIRED",
                evidence=evidence_items,
            )
        )
    for document_name, (value, location) in extracted_titles.items():
        normalized = unicoded_title(value)
        if len(normalized) > TITLE_MAX_RECOMMENDED_CHARS:
            title_findings.append(
                collector.finding(
                    "form_title_consistency_and_quality",
                    document_name,
                    f"{document_name}.title",
                    f"从真实文书提取的名称为“{value}”，超出常用的 25 字内简短写法。",
                    "压缩为更简短、准确的名称；确需保留较长名称时人工确认是否符合中国专利名称撰写要求。",
                    status="WARNING",
                    evidence=title_evidence(artifact_ids, document_name, location, value),
                )
            )
    if extracted_titles:
        title_gap = collector.gap(
            "form_title_consistency_and_quality",
            "titles",
            "CAPABILITY_LIMIT",
            "脚本已尝试从真实文书提取名称，但仍不能仅凭文本提取结果证明请求书正式栏位中的名称已经正确填写。",
            evidence=evidence("application-manifest", "titles"),
        )
    else:
        title_gap = collector.gap(
            "form_title_consistency_and_quality",
            "titles",
            "CAPABILITY_LIMIT",
            "manifest 标题声明和 SHA-256 不能证明实际文书标题已被正确提取。",
            evidence=evidence("application-manifest", "titles"),
        )
    register("form_title_consistency_and_quality", "titles", "PARTIAL", title_findings, [title_gap])

    # 5. 说明书结构。
    required_sections = ["技术领域", "背景技术", "发明内容", "具体实施方式"]
    if metadata["drawings"]["status"] == "provided" or "附图说明" in found_sections:
        required_sections.insert(3, "附图说明")
    missing_sections = [section for section in required_sections if section not in found_sections]
    section_findings = [collector.finding("form_specification_structure_and_drafting", "specification", "说明书", f"未识别到“{section}”章节。", "核对真实说明书结构和例外理由。", status="REVIEW_REQUIRED", evidence=document_evidence(artifact_ids, "specification", "sections", section)) for section in missing_sections]
    section_gap = collector.gap("form_specification_structure_and_drafting", "specification", "SEMANTIC_REVIEW_NOT_PERFORMED", "章节存在性可筛查，但撰写质量和公开充分性不在形式检查器范围。", evidence=document_evidence(artifact_ids, "specification", "sections"))
    register("form_specification_structure_and_drafting", "specification", "PARTIAL", section_findings, [section_gap])

    # 6. 权利要求编号和引用形式仅作结构筛查。
    claim_gap = collector.gap("form_claim_presentation_and_reference_form", "claims", "SEMANTIC_REVIEW_NOT_PERFORMED", "权利要求清楚、支持和必要技术特征由 claims checker 独立审查。", evidence=document_evidence(artifact_ids, "claims", "claims"))
    register("form_claim_presentation_and_reference_form", "claims", "PARTIAL", gap_ids=[claim_gap])

    # 7. 摘要字数和宣传用语。
    body = abstract_body(abstract)
    count = len(re.sub(r"\s+", "", body))
    abstract_findings: list[str] = []
    if metadata["abstract"]["status"] in {"unknown", "confirmed_absent", "not_applicable"}:
        abstract_findings.append(collector.finding("form_abstract_content_and_length", "abstract", "abstract", "摘要文书未提供或已确认缺失。", "补齐摘要并重新检查。", status="DETERMINISTIC_FAIL" if metadata["abstract"]["status"] != "unknown" else "REVIEW_REQUIRED", evidence=evidence("application-manifest", "documents.abstract")))
    elif count > 300:
        abstract_findings.append(collector.finding("form_abstract_content_and_length", "abstract", "abstract", f"摘要文字部分包括标点共 {count} 字，超过 300 字。", "压缩摘要至法定长度。", status="DETERMINISTIC_FAIL", evidence=document_evidence(artifact_ids, "abstract", "abstract", str(count))))
    for term in PROMOTIONAL_TERMS:
        if term in body:
            abstract_findings.append(collector.finding("form_abstract_content_and_length", "abstract", "abstract", "摘要中存在可能具有商业宣传性质的用语。", "结合上下文改为客观技术表述。", status="WARNING", evidence=document_evidence(artifact_ids, "abstract", "abstract", term)))
    abstract_gap = collector.gap("form_abstract_content_and_length", "abstract", "SEMANTIC_REVIEW_NOT_PERFORMED", "摘要内容是否完整准确仍需人工复核。", evidence=document_evidence(artifact_ids, "abstract", "abstract"))
    register("form_abstract_content_and_length", "abstract", "PARTIAL", abstract_findings, [abstract_gap])

    # 8-10. 摘要附图、附图存在性和图号/标记。
    drawing_state = metadata["drawings"]["status"]
    abstract_figure = manifest.get("abstract_figure")
    if abstract_figure is None:
        gap = collector.gap("form_abstract_figure_designation", "abstract", "CONDITIONAL_APPLICABILITY_UNRESOLVED", "未提供摘要附图指定及适用性声明。", evidence=evidence("application-manifest", "abstract_figure"))
        register("form_abstract_figure_designation", "abstract", "NOT_VERIFIED", gap_ids=[gap])
    elif not isinstance(abstract_figure, dict) or abstract_figure.get("applicability") not in {"applicable", "not_applicable", "unknown"}:
        raise InputContractError("abstract_figure 必须含有效 applicability")
    elif drawing_state == "provided" and abstract_figure.get("applicability") == "not_applicable":
        finding = collector.finding(
            "form_abstract_figure_designation",
            "abstract",
            "abstract_figure",
            "附图已提供，但摘要附图被声明为 not_applicable。",
            "将摘要附图改为 applicable 并补充指定信息，或纠正附图状态声明。",
            status="DETERMINISTIC_FAIL",
            evidence=evidence("application-manifest", "abstract_figure", str(abstract_figure.get("evidence", ""))),
        )
        register("form_abstract_figure_designation", "abstract", "COMPLETED", finding_ids=[finding])
    elif drawing_state == "provided" and abstract_figure.get("applicability") == "applicable" and str(abstract_figure.get("evidence", "")).strip():
        gap = collector.gap(
            "form_abstract_figure_designation",
            "abstract",
            "SEMANTIC_REVIEW_NOT_PERFORMED",
            "摘要附图已声明适用，但指定图号和请求书正式栏位仍需人工复核。",
            evidence=evidence("application-manifest", "abstract_figure", str(abstract_figure.get("evidence", ""))),
        )
        register("form_abstract_figure_designation", "abstract", "PARTIAL", gap_ids=[gap])
    elif drawing_state != "provided" and abstract_figure.get("applicability") == "not_applicable" and str(abstract_figure.get("evidence", "")).strip():
        register("form_abstract_figure_designation", "abstract", "COMPLETED")
    else:
        gap = collector.gap("form_abstract_figure_designation", "abstract", "CONDITIONAL_APPLICABILITY_UNRESOLVED", "摘要附图指定需要人工或图面证据复核。", evidence=evidence("application-manifest", "abstract_figure"))
        register("form_abstract_figure_designation", "abstract", "NOT_VERIFIED", gap_ids=[gap])

    figure_text = "\n".join(sections.get(key, "") for key in ("背景技术", "附图说明", "具体实施方式"))
    referenced_figures = figure_ids(figure_text)
    if manifest.get("application_type") == "invention" and drawing_state == "confirmed_absent" and referenced_figures:
        finding = collector.finding("form_drawings_requiredness_and_presence", "drawings", "drawings", "说明书引用本申请图号，但附图被确认实际缺失。", "补齐附图或纠正引用。", status="DETERMINISTIC_FAIL", evidence=document_evidence(artifact_ids, "specification", "figure_references", json.dumps(sorted(referenced_figures), ensure_ascii=False)))
        register("form_drawings_requiredness_and_presence", "drawings", "COMPLETED", finding_ids=[finding])
    elif drawing_state == "unknown":
        gap = collector.gap("form_drawings_requiredness_and_presence", "drawings", "INPUT_UNAVAILABLE", "无法确认附图是否存在；发明申请不因未提供附图而机械判定缺陷。", evidence=evidence("application-manifest", "documents.drawings"))
        register("form_drawings_requiredness_and_presence", "drawings", "NOT_VERIFIED", gap_ids=[gap])
    else:
        register("form_drawings_requiredness_and_presence", "drawings", "COMPLETED")

    # 附图标记与各图说明的排版形态可在文本内客观确认，但"表格不合规"没有直接法源，
    # 属提交格式与撰写惯例问题，因此固定为 WARNING，不进入 DETERMINISTIC_FAIL 与退出码 2。
    figure_findings: list[str] = []
    if metadata["specification"]["status"] == "provided":
        for shape, excerpt in reference_sign_form_issues(sections.get("附图说明", "")):
            figure_findings.append(collector.finding(
                "form_drawing_numbering_reference_signs_and_graphic_form",
                "drawings",
                "specification.附图说明",
                f"附图说明章节以{shape}承载附图标记或各图说明。",
                "改写为各图说明每幅一段，附图标记集中为章节末尾的单段句式"
                "「图中：100-高稳定参考时钟源、110-频率基准单元。」。",
                status="WARNING",
                evidence=document_evidence(artifact_ids, "specification", "附图说明", excerpt),
            ))
    figure_gap = collector.gap("form_drawing_numbering_reference_signs_and_graphic_form", "drawings", "CAPABILITY_LIMIT", "图号文本筛查不能证明真实图面、附图标记指向和图形质量；形态筛查也不能证明标记名称与正文一致。", evidence=document_evidence(artifact_ids, "specification", "figure_references"))
    register("form_drawing_numbering_reference_signs_and_graphic_form", "drawings", "PARTIAL", figure_findings, [figure_gap])

    # 11-17. 条件程序文书，统一生成结构化 applicability gap。
    add_conditional_check(collector, manifest, "sequence_listing", "form_sequence_listing", "sequence_listing", artifact_ids)
    add_conditional_check(collector, manifest, "biological_material_deposit", "form_biological_material_deposit", "biological_material_deposit", artifact_ids)
    add_conditional_check(collector, manifest, "genetic_resource_statement", "form_genetic_resource_statement", "genetic_resource_statement", artifact_ids)
    add_conditional_check(collector, manifest, "priority_documents", "form_priority_declaration_and_documents", "priority", artifact_ids)
    add_conditional_check(collector, manifest, "article_24_proof", "form_article_24_declaration_and_proof", "article_24", artifact_ids)
    add_conditional_check(collector, manifest, "divisional_documents", "form_divisional_filing_procedure", "divisional", artifact_ids)
    add_conditional_check(collector, manifest, "substantive_examination_request", "form_substantive_examination_request_procedure", "substantive_examination", artifact_ids)

    # 将 finding/gap 绑定到产生它们的唯一 check；所有 17 个规则必须恰好一个 check。
    by_rule = {item["rule_id"]: item for item in collector.checks}
    for item in collector.findings:
        item["check_id"] = by_rule[item["rule_id"]]["check_id"]
    for item in collector.gaps:
        item["check_id"] = by_rule[item["rule_id"]]["check_id"]
    tool_raw = Path(__file__).resolve().read_bytes()
    rule_path = Path(__file__).resolve().parents[1].joinpath("references", "formalities-rule-matrix.md")
    rule_bytes = rule_path.read_bytes()
    contract_path = Path(__file__).resolve().parents[2].joinpath("cn-patent-reviewer", "references", "cn-review-contract-v2.json")
    contract_raw = contract_path.read_bytes()
    # 规则来源记录可解析的绝对路径，独立 verifier 才能重新读取原字节复算哈希。
    rule_sources = [make_artifact("formalities-rules", str(rule_path), rule_bytes, "text/markdown"), make_artifact("review-contract", str(contract_path), contract_raw, "application/json")]
    tool_identity = {"tool_id": TOOL_ID, "tool_version": TOOL_VERSION, "tool_sha256": sha256_bytes(tool_raw), "contract_schema_version": CONTRACT_SCHEMA_VERSION}
    report = {
        "schema_version": SCHEMA_VERSION,
        "jurisdiction": JURISDICTION,
        "review_type": REVIEW_TYPE,
        "legal_effect": LEGAL_EFFECT,
        "report_id": f"formalities-{sha256_bytes(manifest_raw)[:16]}",
        "input_artifacts": artifacts,
        "rule_sources": rule_sources,
        "tool_identity": tool_identity,
        "evidence_binding": {
            "input_set_sha256": collection_digest([{"id": item["artifact_id"], "sha256": item["sha256"]} for item in artifacts]),
            "rule_set_sha256": collection_digest([{"id": item["artifact_id"], "sha256": item["sha256"]} for item in rule_sources]),
            "tool_set_sha256": collection_digest([{"id": TOOL_ID, "sha256": tool_identity["tool_sha256"]}]),
        },
        "resource_limits": RESOURCE_LIMITS,
        "resource_usage": {"input_bytes_total": total_bytes + len(manifest_raw), "output_bytes": 0, "finding_count": len(collector.findings), "gap_count": len(collector.gaps), "check_count": len(collector.checks), "elapsed_milliseconds": int((time.monotonic() - start) * 1000)},
        "checks_performed": collector.checks,
        "findings": collector.findings,
        "gaps": collector.gaps,
    }
    if len(collector.checks) != len(FORMALITY_RULES) or {item["rule_id"] for item in collector.checks} != set(FORMALITY_RULES):
        raise InputContractError("17 个形式维度未各自产生唯一 raw_check")
    payload = canonical_json(report)
    while report["resource_usage"]["output_bytes"] != len(payload):
        report["resource_usage"]["output_bytes"] = len(payload)
        payload = canonical_json(report)
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ResourceLimitError("raw report 输出超过上限")
    return report, payload


def unicoded_title(value: str) -> str:
    return re.sub(r"[\s\u3000]+", "", unicodedata.normalize("NFKC", value)).strip("。.")


def write_output(output: Path, report: dict[str, Any], payload: bytes, protected: list[Path]) -> None:
    output = output.resolve()
    for path in protected:
        if output == path.resolve() or (output.exists() and path.exists() and os.path.samefile(output, path)):
            raise InputContractError(f"输出路径与证据别名冲突：{path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, dir=output.parent, prefix=f".{output.name}.", suffix=".tmp") as handle:
            handle.write(payload + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        for path in protected:
            if output == path.resolve() or (output.exists() and path.exists() and os.path.samefile(output, path)):
                raise InputContractError(f"输出路径在替换前与证据别名冲突：{path}")
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查中国直接发明申请的形式和程序条件")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest_path = args.manifest.resolve()
        manifest_raw = read_limited(manifest_path, MAX_MANIFEST_BYTES, "manifest")
        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InputContractError(f"manifest 不是 UTF-8 无 BOM JSON：{exc}") from exc
        if not isinstance(manifest, dict):
            raise InputContractError("manifest 顶层必须是对象")
        ensure_json_depth(manifest)
        report, payload = analyse(manifest, manifest_path, manifest_raw)
        protected = [manifest_path]
        for entry in manifest.get("documents", {}).values() if isinstance(manifest.get("documents"), dict) else ():
            if isinstance(entry, dict) and entry.get("status") == "provided" and isinstance(entry.get("path"), str):
                protected.append(resolve_under(manifest_path.parent.resolve(), entry["path"]))
        if args.output is None:
            sys.stdout.buffer.write(payload + b"\n")
        else:
            write_output(args.output, report, payload, protected)
        return FAILURE_STATUS_EXIT_CODE if report["findings"] and any(item["status"] == "DETERMINISTIC_FAIL" for item in report["findings"]) else 0
    except ResourceLimitError as exc:
        print(f"形式检查资源错误：{exc}", file=sys.stderr)
        return FAILURE_EXIT_CODE
    except (OSError, DocumentUnavailableError, InputContractError, ValueError) as exc:
        print(f"形式检查输入/工具错误：{exc}", file=sys.stderr)
        return INPUT_ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
