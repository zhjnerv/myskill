#!/usr/bin/env python3
"""中国发明专利权利要求的有界确定性原始检查器。"""

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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "cn-patent-review-raw-report/v2"
CONTRACT_SCHEMA_VERSION = "cn-patent-review-contract/v2"
TOOL_ID = "cn-patent-claims-analyzer"
TOOL_VERSION = "2.1.0"
LEGAL_EFFECT = "ADVISORY_ONLY"
OUTPUT_RULE_ID = "CN-CLAIM-OUTPUT-001"
RESOURCE_RULE_ID = "CN-CLAIM-RESOURCE-001"
INPUT_RULE_ID = "CN-CLAIM-INPUT-001"

MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_CLAIMS = 20_000
MAX_CLAIM_NUMBER = 1_000_000
MAX_REFERENCE_EDGES = 100_000
MAX_ANCESTOR_DEPTH = 2_048
MAX_SINGLE_CLAIM_BYTES = 256 * 1024
MAX_CLAIM_WORD_COUNT = 600
CLAIM_WORD_COUNT_LIMITS: dict[int, int] = {1: 400, 2: 500}
CLAIM_WORD_COUNT_RULES: dict[int, str] = {1: "CN-CLAIM-LENGTH-002", 2: "CN-CLAIM-LENGTH-003"}
CORE_DEPENDENT_RULE_ID = "CN-CLAIM-CORE-001"
MAX_FINDINGS = 5_000
MAX_GAPS = 5_000
MAX_CHECKS = 10_000
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
DEADLINE_SECONDS = 180

RAW_STATUSES = {"DETERMINISTIC_FAIL", "REVIEW_REQUIRED", "WARNING", "NOT_VERIFIED"}
CHECK_STATUSES = {"COMPLETED", "PARTIAL", "SKIPPED", "NOT_VERIFIED"}
GAP_CATEGORIES = {
    "INPUT_UNAVAILABLE",
    "PARSE_UNRESOLVED",
    "CAPABILITY_LIMIT",
    "SEARCH_EVIDENCE_MISSING",
    "CONDITIONAL_APPLICABILITY_UNRESOLVED",
    "SEMANTIC_REVIEW_NOT_PERFORMED",
}
CLAIM_START_RE = re.compile(r"^\s*([0-9０-９]+)\s*[\.．、:：]\s*(.*)$")
REFERENCE_LEAD_RE = re.compile(r"(?:根据|按照|如)\s*权利要求")
REFERENCE_CLAUSE_RE = re.compile(r"(?:根据|按照|如)\s*(?P<clause>权利要求.+?)\s*所述")
RANGE_RE = re.compile(r"(\d+)\s*(?:-|—|~|～|至|到)\s*(\d+)")
PLACEHOLDER_RE = re.compile(r"【[^】]*(?:待填|待补|占位|内部备注|TODO|TBD)[^】]*】|<[^>\r\n]*(?:待填|待补|占位|TODO|TBD)[^>\r\n]*>", re.IGNORECASE)
WEAK_DRAFT_RE = re.compile(r"(?<![A-Za-z0-9_])(?:TODO|TBD|XXX)(?![A-Za-z0-9_])|待补充|待完善|待填写|待填", re.IGNORECASE)
TERM_RE = re.compile(r"所述(?:的)?(?P<term>[\u4e00-\u9fffA-Za-z0-9_（）()\-]{1,40}?)(?=\s*(?:[，,；;。:：]|的|用于|用以|被配置|配置为|连接|包括|包含|具有|接收|输出|生成|执行|$))")
FORMULA_TOKEN = "\ue000"
WORD_INTERNAL_PUNCTUATION = frozenset("'’-.·/‐‑‒–—")
FORMULA_PATTERNS = (
    re.compile(r"```(?:math|latex)\s*.*?```", re.IGNORECASE | re.DOTALL),
    re.compile(r"\$\$.*?\$\$", re.DOTALL),
    re.compile(r"\\\[.*?\\\]", re.DOTALL),
    re.compile(r"\\\(.*?\\\)", re.DOTALL),
    re.compile(r"(?<!\\)\$(?!\$)(?:\\.|[^$\r\n])+?(?<!\\)\$"),
)


class ResourceLimitError(ValueError):
    """资源限制失败；CLI 将其映射为退出码 4 且不输出法律 finding。"""


@dataclass(frozen=True)
class Claim:
    number: int
    text: str
    references: tuple[int, ...]
    kind: str
    reference_parse_status: str
    reference_mode: str


class Budget:
    def __init__(self) -> None:
        self.started = time.monotonic()

    def check_deadline(self) -> None:
        if time.monotonic() - self.started > DEADLINE_SECONDS:
            raise ResourceLimitError("CN-CLAIM-RESOURCE-001: 编排时间超过 180 秒")

    def elapsed_milliseconds(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", unicodedata.normalize("NFKC", value)).strip()


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _is_cjk_counted_character(char: str) -> bool:
    """判断 Word 中文字数口径下按单字计数的东亚文字。"""

    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x323AF
        or 0x3040 <= codepoint <= 0x30FF
        or 0x31F0 <= codepoint <= 0x31FF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _is_word_component(char: str) -> bool:
    category = unicodedata.category(char)
    return category[0] in {"L", "N", "M"} or category == "Pc"


def collapse_formula_tokens(text: str) -> str:
    """把明确标记的完整公式或公式变量折算为一个计数占位符。"""

    collapsed = text
    for pattern in FORMULA_PATTERNS:
        collapsed = pattern.sub(FORMULA_TOKEN, collapsed)
    return collapsed


def word_compatible_claim_count(text: str) -> int:
    """按项目定义的 Word 中文字数口径计算单项权利要求，不含编号。"""

    normalized = unicodedata.normalize("NFKC", collapse_formula_tokens(text))
    count = 0
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char == FORMULA_TOKEN or _is_cjk_counted_character(char):
            count += 1
            index += 1
            continue
        if _is_word_component(char):
            count += 1
            index += 1
            while index < len(normalized):
                next_char = normalized[index]
                if _is_word_component(next_char) and not _is_cjk_counted_character(next_char):
                    index += 1
                    continue
                if (
                    next_char in WORD_INTERNAL_PUNCTUATION
                    and index + 1 < len(normalized)
                    and _is_word_component(normalized[index + 1])
                    and not _is_cjk_counted_character(normalized[index + 1])
                ):
                    index += 1
                    continue
                break
            continue
        # Word 会把单独的数学/技术符号作为一个计数单元；普通标点和空白不计。
        if unicodedata.category(char).startswith("S"):
            count += 1
        index += 1
    return count


def artifact(path: str, payload: bytes, artifact_id: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "path": path,
        "sha256": sha256_bytes(payload),
        "byte_length": len(payload),
        "media_type": "text/plain",
        "encoding": "UTF-8",
    }


def canonical_set_sha256(items: list[dict[str, Any]]) -> str:
    material = sorted((item["artifact_id"], item["sha256"]) for item in items)
    return sha256_bytes(json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def ensure_count(name: str, count: int, maximum: int) -> None:
    if count > maximum:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: {name} 超过上限 {maximum}")


def parse_reference_numbers(clause: str, budget: Budget) -> tuple[int, ...]:
    """有界解析引用编号；区间永不按极大编号展开。"""

    numbers: set[int] = set()
    normalized = normalize_text(clause)
    consumed: list[tuple[int, int]] = []
    for match in RANGE_RE.finditer(normalized):
        budget.check_deadline()
        start, end = int(match.group(1)), int(match.group(2))
        if max(start, end) > MAX_CLAIM_NUMBER:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 引用编号超过上限 {MAX_CLAIM_NUMBER}")
        if start <= end:
            range_size = end - start + 1
            # 现有资源合同允许最多 100,000 条引用边；超过预算必须明确失败，
            # 不能退化为只保留端点，否则会漏掉区间内的多项从属违规。
            ensure_count("引用区间展开", range_size, MAX_REFERENCE_EDGES)
            numbers.update(range(start, end + 1))
        else:
            numbers.update((start, end))
        consumed.append(match.span())
        ensure_count("单项引用候选", len(numbers), MAX_REFERENCE_EDGES)
    remaining = list(normalized)
    for start, end in consumed:
        remaining[start:end] = " " * (end - start)
    for value in re.findall(r"\d+", "".join(remaining)):
        budget.check_deadline()
        number = int(value)
        if number > MAX_CLAIM_NUMBER:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 引用编号超过上限 {MAX_CLAIM_NUMBER}")
        numbers.add(number)
        ensure_count("单项引用候选", len(numbers), MAX_REFERENCE_EDGES)
    return tuple(sorted(numbers))


def parse_reference_clause(clause: str, budget: Budget) -> tuple[tuple[int, ...], str | None]:
    normalized = normalize_text(clause)
    numbers = parse_reference_numbers(normalized, budget)
    residue = re.sub(r"权利要求\s*", "", normalized)
    residue = RANGE_RE.sub("", residue)
    residue = re.sub(r"\d+", "", residue)
    residue = re.sub(r"(?:中(?:的)?)?(?:任意一项|任一项|任一|之一)", "", residue)
    residue = re.sub(r"(?:或者|或|以及|和|与|及|、|,|，|/)", "", residue)
    residue = re.sub(r"\s+", "", residue)
    if not numbers:
        return (), "引用子句中未识别到权利要求编号"
    return numbers, f"引用子句包含无法识别的文本：{residue}" if residue else None


def classify_reference_mode(expression: str, references: tuple[int, ...]) -> str:
    if len(references) <= 1:
        return "not_applicable"
    normalized = normalize_text(expression)
    if re.search(r"(?:和|及)\s*/\s*或", normalized):
        return "review_required"
    alternative = bool(re.search(r"(?:或者|或|任意一项|任一项|任一|之一)", normalized))
    conjunctive = bool(re.search(r"(?:以及|和|与|及)", normalized))
    if alternative and conjunctive:
        return "review_required"
    if conjunctive:
        return "conjunctive"
    return "alternative" if alternative else "missing_alternative"


def split_claims(text: str, budget: Budget) -> tuple[list[Claim], list[tuple[str, str, str]]]:
    """解析文本；引用引导语只能形成 candidate 或 unresolved，不确认从属关系。"""

    raw: list[tuple[int, str]] = []
    current_number: int | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        budget.check_deadline()
        match = CLAIM_START_RE.match(line)
        if match:
            if current_number is not None:
                raw.append((current_number, "\n".join(current_lines)))
            digits = unicodedata.normalize("NFKC", match.group(1))
            if len(digits) > 7:
                raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 权利要求编号超过上限 {MAX_CLAIM_NUMBER}")
            current_number = int(digits)
            if current_number > MAX_CLAIM_NUMBER:
                raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 权利要求编号超过上限 {MAX_CLAIM_NUMBER}")
            current_lines = [match.group(2)]
            ensure_count("权利要求数量", len(raw) + 1, MAX_CLAIMS)
        elif current_number is not None:
            current_lines.append(line.strip())
    if current_number is not None:
        raw.append((current_number, "\n".join(current_lines)))

    parser_notes: list[tuple[str, str, str]] = []
    claims: list[Claim] = []
    for number, raw_text in raw:
        budget.check_deadline()
        if len(raw_text.encode("utf-8")) > MAX_SINGLE_CLAIM_BYTES:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 单项权利要求文本超过上限")
        claim_text = normalize_text(raw_text)
        leads = list(REFERENCE_LEAD_RE.finditer(claim_text))
        clauses = list(REFERENCE_CLAUSE_RE.finditer(claim_text))
        references: set[int] = set()
        errors: list[str] = []
        for clause in clauses:
            parsed, error = parse_reference_clause(clause.group("clause"), budget)
            references.update(parsed)
            if error:
                errors.append(error)
        ensure_count("引用边", len(references), MAX_REFERENCE_EDGES)
        if leads and not clauses:
            errors.append("检测到引用引导语，但未识别到以“所述”结束的完整引用子句")
        expression = claim_text[clauses[0].start():clauses[-1].end()] if clauses else ""
        if not leads:
            kind, parse_status = "independent_candidate", "not_applicable"
        elif errors:
            kind, parse_status = "dependent_unresolved", "unresolved"
        else:
            kind, parse_status = "dependent_candidate", "candidate"
            errors.append("引用引导语仅形成从属候选，尚未确认该项不是独立权利要求")
        if errors:
            parser_notes.append((f"claim-{number}", "；".join(sorted(set(errors))), kind))
        claims.append(Claim(number, claim_text, tuple(sorted(references)), kind, parse_status, classify_reference_mode(expression, tuple(sorted(references)))))
    return claims, parser_notes


def detect_cycles_iterative(graph: dict[int, tuple[int, ...]], budget: Budget) -> list[tuple[int, ...]]:
    """有界、非递归 DFS；只处理已确认的引用边。"""

    color: dict[int, int] = {}
    cycles: set[tuple[int, ...]] = set()
    for root in sorted(graph):
        if color.get(root, 0):
            continue
        stack: list[tuple[int, int]] = [(root, 0)]
        path: list[int] = []
        position: dict[int, int] = {}
        while stack:
            budget.check_deadline()
            node, edge_index = stack[-1]
            if color.get(node, 0) == 0:
                color[node] = 1
                position[node] = len(path)
                path.append(node)
                ensure_count("祖先深度", len(path), MAX_ANCESTOR_DEPTH)
            parents = graph.get(node, ())
            if edge_index >= len(parents):
                color[node] = 2
                position.pop(node, None)
                path.pop()
                stack.pop()
                continue
            parent = parents[edge_index]
            stack[-1] = (node, edge_index + 1)
            if parent not in graph:
                continue
            if color.get(parent, 0) == 0:
                stack.append((parent, 0))
            elif color.get(parent) == 1:
                cycle = tuple(path[position[parent]:] + [parent])
                body = cycle[:-1]
                minimum = min(range(len(body)), key=lambda index: body[index])
                canonical = body[minimum:] + body[:minimum]
                cycles.add(canonical + (canonical[0],))
    return sorted(cycles)


def new_finding(check_id: str, rule_id: str, target_id: str, location: str, status: str, evidence: str, problem: str, remedy: str) -> dict[str, Any]:
    """构造 v2 raw_finding；ID 纳入 rule_id 以避免同一 check 下的 ID 碰撞。"""

    if status not in RAW_STATUSES:
        raise ValueError(f"不支持的原始 finding 状态：{status}")
    return {
        "finding_id": stable_id("F", check_id, rule_id, target_id, status, evidence, problem),
        "check_id": check_id,
        "rule_id": rule_id,
        "target_id": target_id,
        "location": location,
        "status": status,
        "evidence": [{"artifact_id": "claims", "location": location, "excerpt": evidence[:4096]}],
        "problem": problem,
        "remedy": remedy,
        "manual_review_required": status in {"REVIEW_REQUIRED", "NOT_VERIFIED"},
    }


def new_gap(check_id: str, rule_id: str, target_id: str, category: str, reason: str, evidence: str, blocks: bool = True) -> dict[str, Any]:
    """构造 v2 raw_gap；category 只能取规范枚举值。"""

    if category not in GAP_CATEGORIES:
        raise ValueError(f"不支持的原始 gap 类别：{category}")
    return {
        "gap_id": stable_id("G", check_id, rule_id, target_id, category, reason, evidence),
        "check_id": check_id,
        "rule_id": rule_id,
        "target_id": target_id,
        "category": category,
        "reason": reason,
        "evidence": [{"artifact_id": "claims", "location": target_id, "excerpt": evidence[:4096]}],
        "blocks_assessment": blocks,
    }


def add_limited(items: list[dict[str, Any]], item: dict[str, Any], maximum: int, label: str) -> None:
    if len(items) >= maximum:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: {label} 超过上限 {maximum}")
    items.append(item)


def analyze_claims(text: str, source_name: str = "<memory>", source_bytes: bytes | None = None) -> dict[str, Any]:
    """生成严格的 v2 raw report；调用方负责在 CLI 前完成输入字节预算。"""

    budget = Budget()
    raw = source_bytes if source_bytes is not None else text.encode("utf-8")
    if len(raw) > MAX_INPUT_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 权利要求输入超过 4 MiB")
    claims, parser_notes = split_claims(text, budget)
    findings: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def finding(*args: str) -> None:
        add_limited(findings, new_finding(*args), MAX_FINDINGS, "finding 数量")

    def gap(*args: str, blocks: bool = True) -> None:
        add_limited(gaps, new_gap(*args, blocks=blocks), MAX_GAPS, "gap 数量")

    def check(check_id: str, rule_id: str, target_id: str, status: str, finding_ids: list[str], gap_ids: list[str]) -> None:
        if status not in CHECK_STATUSES:
            raise ValueError(f"不支持的 raw_check 状态：{status}")
        if len(checks) >= MAX_CHECKS:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 检查数量超过上限")
        checks.append({"check_id": check_id, "rule_id": rule_id, "target_id": target_id, "status": status, "finding_ids": sorted(finding_ids), "gap_ids": sorted(gap_ids)})

    if not claims:
        item = new_finding("claims-identification", INPUT_RULE_ID, "claims-document", "权利要求书", "NOT_VERIFIED", "未识别到行首阿拉伯数字编号。", "未识别到可解析的权利要求。", "确认输入为纯文本权利要求书且编号位于行首。")
        add_limited(findings, item, MAX_FINDINGS, "finding 数量")
        missing = new_gap("claims-identification", INPUT_RULE_ID, "claims-document", "INPUT_UNAVAILABLE", "未识别到权利要求，后续结构检查未执行。", "未识别到行首编号")
        add_limited(gaps, missing, MAX_GAPS, "gap 数量")
        check("claims-identification", INPUT_RULE_ID, "claims-document", "NOT_VERIFIED", [item["finding_id"]], [missing["gap_id"]])
    else:
        numbers = [claim.number for claim in claims]
        counts = Counter(numbers)
        number_findings: list[str] = []
        if numbers[0] != 1:
            item = new_finding("claim-numbering", "CN-CLAIM-NUM-001", "claims-document", "权利要求编号", "DETERMINISTIC_FAIL", str(numbers[0]), "权利要求编号未从 1 开始。", "从 1 开始连续编号并同步修改引用。")
            add_limited(findings, item, MAX_FINDINGS, "finding 数量"); number_findings.append(item["finding_id"])
        for number, count_value in sorted(counts.items()):
            budget.check_deadline()
            if count_value > 1:
                item = new_finding("claim-numbering", "CN-CLAIM-NUM-001", f"claim-{number}", f"权利要求{number}", "DETERMINISTIC_FAIL", str(number), f"编号 {number} 重复出现 {count_value} 次。", "合并或重新编号，并同步检查引用。")
                add_limited(findings, item, MAX_FINDINGS, "finding 数量"); number_findings.append(item["finding_id"])
        unique_sorted = sorted(set(number for number in numbers if number > 0))
        for previous, current in zip(unique_sorted, unique_sorted[1:]):
            if current != previous + 1:
                excerpt = f"{previous + 1}-{current - 1}"
                item = new_finding("claim-numbering", "CN-CLAIM-NUM-001", "claims-document", "权利要求编号", "DETERMINISTIC_FAIL", excerpt, f"编号不连续，缺少区间 {excerpt}。", "重新编号并同步修改引用关系。")
                add_limited(findings, item, MAX_FINDINGS, "finding 数量"); number_findings.append(item["finding_id"])
        check("claim-numbering", "CN-CLAIM-NUM-001", "claims-document", "COMPLETED", number_findings, [])

        length_findings: list[str] = []
        length_002_findings: list[str] = []
        length_003_findings: list[str] = []
        for claim in claims:
            budget.check_deadline()
            word_count = word_compatible_claim_count(claim.text)
            limit = CLAIM_WORD_COUNT_LIMITS.get(claim.number, MAX_CLAIM_WORD_COUNT)
            rule_id = CLAIM_WORD_COUNT_RULES.get(claim.number, "CN-CLAIM-LENGTH-001")
            if word_count > limit:
                if rule_id == "CN-CLAIM-LENGTH-002":
                    problem = f"权利要求1按 Word 口径计 {word_count} 字，超过 400 字上限；权利要求1应只保留解决技术问题的必要技术特征，避免明显堆砌或非必要限缩保护范围。"
                elif rule_id == "CN-CLAIM-LENGTH-003":
                    problem = f"权利要求2按 Word 口径计 {word_count} 字，超过 500 字上限；权利要求2承载最核心的保护点，应精简表述并把次要限定下沉到后续从属项。"
                else:
                    problem = f"该项权利要求按 Word 口径计 {word_count} 字，超过 {limit} 字上限。"
                item = new_finding(
                    f"claim-{claim.number}-word-count" if claim.number in (1, 2) else "claim-word-count",
                    rule_id,
                    f"claim-{claim.number}",
                    f"权利要求{claim.number}",
                    "DETERMINISTIC_FAIL",
                    f"Word 口径字数={word_count}；上限={limit}",
                    problem,
                    "在不遗漏必要技术特征且不改变保护主题的前提下拆分或精简；完整公式和特殊公式变量应使用明确公式标记。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                if rule_id == "CN-CLAIM-LENGTH-002":
                    length_002_findings.append(item["finding_id"])
                elif rule_id == "CN-CLAIM-LENGTH-003":
                    length_003_findings.append(item["finding_id"])
                else:
                    length_findings.append(item["finding_id"])
        check("claim-word-count", "CN-CLAIM-LENGTH-001", "claims-document", "COMPLETED", length_findings, [])

        # 权利要求1字数检查
        claim_1 = next((c for c in claims if c.number == 1), None)
        if claim_1:
            check("claim-1-word-count", "CN-CLAIM-LENGTH-002", "claim-1", "COMPLETED", length_002_findings, [])
        else:
            check("claim-1-word-count", "CN-CLAIM-LENGTH-002", "claim-1", "SKIPPED", [], [])

        # 权利要求2字数检查
        claim_2 = next((c for c in claims if c.number == 2), None)
        if claim_2:
            check("claim-2-word-count", "CN-CLAIM-LENGTH-003", "claim-2", "COMPLETED", length_003_findings, [])
        else:
            check("claim-2-word-count", "CN-CLAIM-LENGTH-003", "claim-2", "SKIPPED", [], [])

        parse_findings: list[str] = []
        parse_gaps: list[str] = []
        for target, reason, kind in parser_notes:
            item = new_finding("claim-reference-candidate", "CN-CLAIM-REF-PARSE-001", target, target.replace("claim-", "权利要求"), "REVIEW_REQUIRED", reason, "引用引导语未被确认可作为直接从属关系。", "人工确认该项的独立/从属属性及引用原文。")
            add_limited(findings, item, MAX_FINDINGS, "finding 数量"); parse_findings.append(item["finding_id"])
            missing = new_gap("claim-reference-candidate", "CN-CLAIM-REF-PARSE-001", target, "PARSE_UNRESOLVED", reason, reason)
            add_limited(gaps, missing, MAX_GAPS, "gap 数量"); parse_gaps.append(missing["gap_id"])
        check("claim-reference-candidate", "CN-CLAIM-REF-PARSE-001", "claims-document", "PARTIAL" if parse_findings else "COMPLETED", parse_findings, parse_gaps)

        # 编号集合级引用目标检查：自引用、向后引用、不存在目标不依赖“已确认从属边”。
        # 环检测仍只消费经独立确认的边；当前解析仅产出 candidate/unresolved，故不把候选边当确定性环证据。
        existing_numbers = set(numbers)
        graph_findings: list[str] = []
        graph_gaps: list[str] = []
        for claim in claims:
            budget.check_deadline()
            if not claim.references:
                continue
            location = f"权利要求{claim.number}"
            target = f"claim-{claim.number}"
            for ref in claim.references:
                if ref not in existing_numbers:
                    item = new_finding(
                        "claim-reference-graph",
                        "CN-CLAIM-REF-001",
                        target,
                        location,
                        "DETERMINISTIC_FAIL",
                        str(ref),
                        f"权利要求{claim.number} 引用的权利要求{ref} 不存在。",
                        "更正引用编号，使其指向本申请中在前的权利要求。",
                    )
                    add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                    graph_findings.append(item["finding_id"])
                elif ref == claim.number:
                    item = new_finding(
                        "claim-reference-graph",
                        "CN-CLAIM-REF-001",
                        target,
                        location,
                        "DETERMINISTIC_FAIL",
                        str(ref),
                        f"权利要求{claim.number} 引用自身。",
                        "删除自引用或改为引用在前的其他权利要求。",
                    )
                    add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                    graph_findings.append(item["finding_id"])
                elif ref > claim.number:
                    item = new_finding(
                        "claim-reference-graph",
                        "CN-CLAIM-REF-001",
                        target,
                        location,
                        "DETERMINISTIC_FAIL",
                        str(ref),
                        f"权利要求{claim.number} 向后引用权利要求{ref}。",
                        "从属权利要求只能引用在前的权利要求。",
                    )
                    add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                    graph_findings.append(item["finding_id"])
        confirmed_graph: dict[int, tuple[int, ...]] = {}
        for cycle in detect_cycles_iterative(confirmed_graph, budget):
            item = new_finding(
                "claim-reference-graph",
                "CN-CLAIM-REF-001",
                "claims-document",
                "权利要求引用图",
                "DETERMINISTIC_FAIL",
                " -> ".join(map(str, cycle)),
                "检测到循环引用。",
                "重构引用链。",
            )
            add_limited(findings, item, MAX_FINDINGS, "finding 数量")
            graph_findings.append(item["finding_id"])
        graph_gap = new_gap(
            "claim-reference-graph",
            "CN-CLAIM-REF-001",
            "claims-document",
            "PARSE_UNRESOLVED",
            "直接从属边尚未独立确认，循环引用的图算法未对候选边执行。",
            "引用引导语保持 candidate/unresolved；集合级目标检查已执行。",
        )
        add_limited(gaps, graph_gap, MAX_GAPS, "gap 数量")
        graph_gaps.append(graph_gap["gap_id"])
        check(
            "claim-reference-graph",
            "CN-CLAIM-REF-001",
            "claims-document",
            "PARTIAL",
            graph_findings,
            graph_gaps,
        )

        # 多项从属：择一方式与“多项不得作为另一多项基础”可在编号集合上机判。
        multi_numbers = {claim.number for claim in claims if len(claim.references) > 1}
        multi_findings: list[str] = []
        for claim in claims:
            budget.check_deadline()
            if len(claim.references) <= 1:
                continue
            location = f"权利要求{claim.number}"
            target = f"claim-{claim.number}"
            ref_text = "、".join(map(str, claim.references))
            if claim.reference_mode == "conjunctive":
                item = new_finding(
                    "claim-multiple-dependent",
                    "CN-CLAIM-MULTI-001",
                    target,
                    location,
                    "DETERMINISTIC_FAIL",
                    ref_text,
                    f"多项从属权利要求{claim.number} 以并列方式引用在前权利要求。",
                    "改为择一引用（如“或”“或者”“任一项”），并同步检查是否被其他多项从属引用。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                multi_findings.append(item["finding_id"])
            elif claim.reference_mode in {"review_required", "missing_alternative"}:
                item = new_finding(
                    "claim-multiple-dependent",
                    "CN-CLAIM-MULTI-001",
                    target,
                    location,
                    "REVIEW_REQUIRED",
                    ref_text,
                    f"多项从属权利要求{claim.number} 的择一引用方式不明确或含混合连接词。",
                    "人工确认引用连接词，并改为明确的择一表达。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                multi_findings.append(item["finding_id"])
            bad_bases = [ref for ref in claim.references if ref in multi_numbers]
            if bad_bases:
                item = new_finding(
                    "claim-multiple-dependent",
                    "CN-CLAIM-MULTI-001",
                    target,
                    location,
                    "DETERMINISTIC_FAIL",
                    "、".join(map(str, bad_bases)),
                    f"多项从属权利要求{claim.number} 引用了另一项多项从属权利要求作为基础。",
                    "多项从属不得作为另一项多项从属的基础；改为引用非多项从属的在前权利要求。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                multi_findings.append(item["finding_id"])
        check(
            "claim-multiple-dependent",
            "CN-CLAIM-MULTI-001",
            "claims-document",
            "COMPLETED",
            multi_findings,
            [],
        )

        # CN-CLAIM-CORE-001：权利要求2必须直接引用权利要求1
        core_findings: list[str] = []
        core_gaps: list[str] = []
        claim_2 = next((c for c in claims if c.number == 2), None)
        if claim_2:
            if claim_2.kind == "independent_candidate":
                item = new_finding(
                    "claim-2-core-dependency",
                    CORE_DEPENDENT_RULE_ID,
                    "claim-2",
                    "权利要求2",
                    "DETERMINISTIC_FAIL",
                    claim_2.text[:200],
                    "权利要求2未引用权利要求1，不是承载核心保护点的直接从属项。",
                    "将最核心的区别特征写入直接从属于权利要求1的权利要求2；其他独立权利要求后移。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                core_findings.append(item["finding_id"])
            elif claim_2.kind == "dependent_candidate" and claim_2.references == (1,):
                # 权利要求2直接引用权利要求1，无issue
                pass
            elif claim_2.kind == "dependent_candidate":
                # 引用不是(1,)
                item = new_finding(
                    "claim-2-core-dependency",
                    CORE_DEPENDENT_RULE_ID,
                    "claim-2",
                    "权利要求2",
                    "DETERMINISTIC_FAIL",
                    f"引用：{claim_2.references}",
                    f"权利要求2应仅直接引用权利要求1，实际引用 {claim_2.references}。",
                    "将最核心的区别特征写入直接且仅引用权利要求1的权利要求2；引用其他权利要求的从属项后移。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                core_findings.append(item["finding_id"])
            elif claim_2.kind == "dependent_unresolved":
                item = new_finding(
                    "claim-2-core-dependency",
                    CORE_DEPENDENT_RULE_ID,
                    "claim-2",
                    "权利要求2",
                    "REVIEW_REQUIRED",
                    claim_2.text[:200],
                    "权利要求2的引用子句无法完整解析，无法确认是否直接引用权利要求1。",
                    "人工确认权利要求2的引用关系；必须直接引用权利要求1作为唯一引用基础。",
                )
                add_limited(findings, item, MAX_FINDINGS, "finding 数量")
                core_findings.append(item["finding_id"])
                missing = new_gap(
                    "claim-2-core-dependency",
                    CORE_DEPENDENT_RULE_ID,
                    "claim-2",
                    "PARSE_UNRESOLVED",
                    claim_2.reference_parse_status,
                    claim_2.text[:200],
                )
                add_limited(gaps, missing, MAX_GAPS, "gap 数量")
                core_gaps.append(missing["gap_id"])
            check(
                "claim-2-core-dependency",
                CORE_DEPENDENT_RULE_ID,
                "claim-2",
                "PARTIAL" if core_gaps else "COMPLETED",
                core_findings,
                core_gaps,
            )
        else:
            # 权利要求2不存在
            item = new_finding(
                "claim-2-core-dependency",
                CORE_DEPENDENT_RULE_ID,
                "claims-document",
                "权利要求结构",
                "REVIEW_REQUIRED",
                f"仅有 {len(claims)} 项权利要求",
                "未识别到权利要求2，无法确认核心保护点落位。",
                "至少添加权利要求2作为直接从属于权利要求1的从属项，承载最核心的区别特征。",
            )
            add_limited(findings, item, MAX_FINDINGS, "finding 数量")
            core_findings.append(item["finding_id"])
            missing = new_gap(
                "claim-2-core-dependency",
                CORE_DEPENDENT_RULE_ID,
                "claims-document",
                "CONDITIONAL_APPLICABILITY_UNRESOLVED",
                "权利要求2不存在",
                f"仅有 {len(claims)} 项权利要求",
                blocks=False,
            )
            add_limited(gaps, missing, MAX_GAPS, "gap 数量")
            core_gaps.append(missing["gap_id"])
            check(
                "claim-2-core-dependency",
                CORE_DEPENDENT_RULE_ID,
                "claims-document",
                "NOT_VERIFIED",
                core_findings,
                core_gaps,
            )

        draft_findings: list[str] = []
        for claim in claims:
            for match in PLACEHOLDER_RE.finditer(claim.text):
                item = new_finding("claim-draft-signal", "CN-CLAIM-DRAFT-001", f"claim-{claim.number}", f"权利要求{claim.number}", "DETERMINISTIC_FAIL", match.group(0), "检测到结构化编辑占位或内部备注。", "在形成审查稿前补齐或删除该占位。")
                add_limited(findings, item, MAX_FINDINGS, "finding 数量"); draft_findings.append(item["finding_id"])
            for match in WEAK_DRAFT_RE.finditer(claim.text):
                if match.group(0) not in {"待确认"}:
                    item = new_finding("claim-draft-signal", "CN-CLAIM-DRAFT-001", f"claim-{claim.number}", f"权利要求{claim.number}", "REVIEW_REQUIRED", match.group(0), "弱草稿信号可能是编辑提示。", "人工确认其是否属于正常技术或业务状态。")
                    add_limited(findings, item, MAX_FINDINGS, "finding 数量"); draft_findings.append(item["finding_id"])
        check("claim-draft-signal", "CN-CLAIM-DRAFT-001", "claims-document", "COMPLETED", draft_findings, [])

        term_findings: list[str] = []
        term_gaps: list[str] = []
        for claim in claims:
            seen: set[str] = set()
            prefix = ""
            for match in TERM_RE.finditer(claim.text):
                budget.check_deadline()
                term = normalize_text(match.group("term"))
                prefix += claim.text[len(prefix):match.start()]
                if term and term not in seen and term not in prefix:
                    seen.add(term)
                    item = new_finding("claim-term-candidate", "CN-CLAIM-TERM-001", f"claim-{claim.number}", f"权利要求{claim.number}", "REVIEW_REQUIRED", f"所述{term}", "未找到完全一致的显式引入文本。", "人工核对上下文、同义表达和可能的父项。")
                    add_limited(findings, item, MAX_FINDINGS, "finding 数量"); term_findings.append(item["finding_id"])
                    missing = new_gap("claim-term-candidate", "CN-CLAIM-TERM-001", f"claim-{claim.number}", "CAPABILITY_LIMIT", "术语引入检查为启发式，且父链尚未确认。", f"所述{term}", False)
                    add_limited(gaps, missing, MAX_GAPS, "gap 数量"); term_gaps.append(missing["gap_id"])
        check("claim-term-candidate", "CN-CLAIM-TERM-001", "claims-document", "PARTIAL" if term_findings else "COMPLETED", term_findings, term_gaps)

    for rule_id, target in (
        ("CN-CLAIM-CLEAR-001", "claims-document"),
        ("CN-CLAIM-SUPPORT-001", "claims-document"),
        ("CN-CLAIM-FUNCTION-001", "claims-document"),
        ("CN-CLAIM-ESSENTIAL-001", "independent-claims"),
        ("CN-CLAIM-DEPENDENT-001", "dependent-claims"),
        ("CN-CLAIM-UNITY-001", "claims-document"),
        ("CN-CLAIM-AMEND-001", "claims-document"),
    ):
        semantic_check_id = f"semantic-{rule_id.lower()}"
        missing = new_gap(semantic_check_id, rule_id, target, "SEMANTIC_REVIEW_NOT_PERFORMED", "确定性结构脚本不执行该法律语义判断。", rule_id)
        add_limited(gaps, missing, MAX_GAPS, "gap 数量")
        check(semantic_check_id, rule_id, target, "NOT_VERIFIED", [], [missing["gap_id"]])

    script_path = Path(__file__).resolve()
    matrix_path = script_path.parents[1] / "references" / "claims-rule-matrix.md"
    length_policy_path = script_path.parents[1] / "references" / "claim-length-policy.md"
    contract_path = script_path.parents[2] / "cn-patent-reviewer" / "references" / "cn-review-contract-v2.json"
    # 规则来源记录可解析的绝对路径，独立 verifier 才能重新读取原字节复算哈希。
    rules = [
        artifact(str(matrix_path), matrix_path.read_bytes(), "claims-rules"),
        artifact(str(length_policy_path), length_policy_path.read_bytes(), "claim-length-policy"),
        artifact(str(contract_path), contract_path.read_bytes(), "review-contract"),
    ]
    source = artifact(source_name, raw, "claims")
    tool_bytes = script_path.read_bytes()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "jurisdiction": "CN",
        "review_type": "claims",
        "legal_effect": LEGAL_EFFECT,
        "report_id": stable_id("R", source["sha256"], sha256_bytes(tool_bytes)),
        "input_artifacts": [source],
        "rule_sources": rules,
        "tool_identity": {"tool_id": TOOL_ID, "tool_version": TOOL_VERSION, "tool_sha256": sha256_bytes(tool_bytes), "contract_schema_version": CONTRACT_SCHEMA_VERSION},
        "evidence_binding": {"input_set_sha256": canonical_set_sha256([source]), "rule_set_sha256": canonical_set_sha256(rules), "tool_set_sha256": sha256_bytes(tool_bytes)},
        "resource_limits": {"claims_input_bytes": MAX_INPUT_BYTES, "claims_max_count": MAX_CLAIMS, "claims_max_number": MAX_CLAIM_NUMBER, "claims_max_reference_edges": MAX_REFERENCE_EDGES, "claims_max_ancestor_depth": MAX_ANCESTOR_DEPTH, "max_findings": MAX_FINDINGS, "max_gaps": MAX_GAPS, "max_report_output_bytes": MAX_OUTPUT_BYTES, "failure_exit_code": 4},
        "resource_usage": {"input_bytes_total": len(raw), "output_bytes": 0, "finding_count": len(findings), "gap_count": len(gaps), "check_count": len(checks), "elapsed_milliseconds": budget.elapsed_milliseconds()},
        "checks_performed": checks,
        "findings": findings,
        "gaps": gaps,
    }
    payload = serialize_result(result)
    result["resource_usage"]["output_bytes"] = len(payload)
    return result


def serialize_result(result: dict[str, Any]) -> bytes:
    """输出字节长度进入 usage 字段，迭代到固定长度后再执行上限检查。"""

    for _ in range(4):
        payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > MAX_OUTPUT_BYTES:
            raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 原始报告输出超过上限")
        if result["resource_usage"]["output_bytes"] == len(payload):
            return payload
        result["resource_usage"]["output_bytes"] = len(payload)
    return payload


def paths_alias(first: Path, second: Path) -> bool:
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


def write_result(result: dict[str, Any], output: Path | None, *, protected_inputs: list[Path] | None = None) -> None:
    payload = serialize_result(result)
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


def read_input(path: Path) -> tuple[bytes, str]:
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 权利要求输入超过 4 MiB")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ResourceLimitError(f"{RESOURCE_RULE_ID}: 权利要求输入超过 4 MiB")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise UnicodeError("权利要求输入必须是 UTF-8 无 BOM")
    return raw, raw.decode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查中国发明专利权利要求的有界确定性结构问题")
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 无 BOM 权利要求书文本")
    parser.add_argument("--output", type=Path, help="独立 JSON 原始报告路径；省略时输出到 stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ensure_output_is_distinct(args.output, [args.input])
        raw, text = read_input(args.input)
        result = analyze_claims(text, str(args.input), raw)
        write_result(result, args.output, protected_inputs=[args.input])
        return 2 if any(item["status"] == "DETERMINISTIC_FAIL" for item in result["findings"]) else 0
    except ResourceLimitError as exc:
        print(f"检查资源失败：{exc}", file=sys.stderr)
        return 4
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"检查失败：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
