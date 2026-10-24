#!/usr/bin/env python3
"""按技术相关性、IPC 相似度与撰写主体质量选择中国专利撰写范本。

综合得分 = 技术相关性×w + IPC 相似度×w + 申请人质量×w + 代理机构质量×w。

设计判断：技术相关性与 IPC 决定"能不能借鉴"，申请人/代理机构决定"文本质量值不值得
学"。绝大多数候选都能同时满足前两项，真正把候选区分开的是后两项，因此申请人/代理机构
默认合计占一半权重。主体质量来自 references/notable-entities.txt 的 Tier 名单命中，
是名单判定，不是对具体机构法律质量或商业信誉的实质评价。

候选 IPC 的获取顺序固定为：EPO OPS → 分类缓存 → 候选输入。EPO 没有凭据、
未收录或暂时失败时允许降级，但必须在报告中保留尝试状态和来源；无法取得 IPC
的候选不得成为机器推荐或最终选择。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_ID = "cn-patent-template-selection/v2"
SEARCH_SCHEMA_ID = "cn-patent-template-search/v1"
CANDIDATE_SCHEMA_ID = "cn-patent-template-candidates/v1"
ENTITIES_PATH = Path(__file__).resolve().parents[1] / "references" / "notable-entities.txt"
DEFAULT_WEIGHTS = {
    "technical_relevance": 0.30,
    "ipc_similarity": 0.20,
    "applicant_quality": 0.25,
    "agency_quality": 0.25,
}
WEIGHT_FIELDS = tuple(DEFAULT_WEIGHTS)
APPLICANT_FIELDS = ("applicant", "assignee", "applicant_name")
AGENCY_FIELDS = ("agency", "patent_agency", "agency_name")
TIER_SCORES = {1: 1.0, 2: 0.7}
UNLISTED_ENTITY_SCORE = 0.3
MISSING_ENTITY_SCORE = 0.0
ENTITY_MATCH_RULE = "名称归一化后完全相等，或较短名称不少于 4 个字符时的包含匹配"
ENTITY_SUFFIX_RE = re.compile(r"(?:集团股份有限公司|股份有限公司|有限责任公司|集团有限公司|有限公司|集团|公司)$")
IPC_RE = re.compile(r"^[A-H][0-9]{2}[A-Z](?:[0-9]+(?:/[0-9]+)?)?$")
IPC_EXTRACT_RE = re.compile(r"([A-H][0-9]{2}[A-Z](?:\s*[0-9]+(?:\s*/\s*[0-9]+)?)?)", re.IGNORECASE)


class SelectionError(ValueError):
    """范本候选或 IPC 选择合同无效。"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise SelectionError(f"{label}不存在：{path}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SelectionError(f"{label}含 BOM，必须使用 UTF-8 无 BOM")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"{label}不是有效 UTF-8 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise SelectionError(f"{label}顶层必须是对象")
    return value


def normalize_ipc(code: str) -> str:
    if not isinstance(code, str):
        raise SelectionError("IPC 分类号必须是字符串")
    value = re.sub(r"\([^)]*\)", "", code.upper())
    match = IPC_EXTRACT_RE.search(value)
    if not match:
        raise SelectionError(f"无效 IPC 分类号：{code}")
    value = re.sub(r"\s+", "", match.group(1))
    if not IPC_RE.fullmatch(value):
        raise SelectionError(f"无效 IPC 分类号：{code}")
    return value


def normalize_ipc_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise SelectionError(f"{field}必须是数组")
    result: list[str] = []
    for item in value:
        code = normalize_ipc(item)
        if code not in result:
            result.append(code)
    return result


def ipc_parts(code: str) -> dict[str, str]:
    code = normalize_ipc(code)
    subclass = code[:4]
    remainder = code[4:]
    main_group = remainder.split("/", 1)[0] if remainder else ""
    return {
        "section": code[:1],
        "class": code[:3],
        "subclass": subclass,
        "main_group": f"{subclass}{main_group}" if main_group else subclass,
        "full": code,
    }


def compare_ipc(target: str, candidate: str) -> tuple[float, str]:
    left, right = ipc_parts(target), ipc_parts(candidate)
    if left["full"] == right["full"]:
        return 1.0, "exact"
    if left["main_group"] == right["main_group"] and left["main_group"] != left["subclass"]:
        return 0.85, "same_main_group"
    if left["subclass"] == right["subclass"]:
        return 0.65, "same_subclass"
    if left["class"] == right["class"]:
        return 0.45, "same_class"
    if left["section"] == right["section"]:
        return 0.20, "same_section"
    return 0.0, "none"


def best_ipc_match(target_codes: list[str], candidate_codes: list[str]) -> dict[str, Any]:
    best = {"score": 0.0, "level": "none", "target_ipc": None, "candidate_ipc": None}
    for target in target_codes:
        for candidate in candidate_codes:
            score, level = compare_ipc(target, candidate)
            if score > best["score"]:
                best = {
                    "score": score,
                    "level": level,
                    "target_ipc": target,
                    "candidate_ipc": candidate,
                }
    return best


def load_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = load_json(path, "分类缓存")
    records = payload.get("patents", payload)
    if not isinstance(records, dict):
        raise SelectionError("分类缓存必须是以公开号为键的对象，或包含 patents 对象")
    return records


def build_epo_resolver(command: str | None = None) -> Callable[[str], tuple[list[str], dict[str, Any]]]:
    """构造独立 EPO provider 调用器，避免反向依赖主项目。

    provider 通过 argv 最后一项接收公开号，并在 stdout 输出 JSON 对象：
    ``{"ipc_codes": ["G06F11/36"]}``。调用不经过 shell。
    """

    raw_command = (command or os.getenv("CN_PATENT_EPO_PROVIDER_COMMAND") or "").strip()

    def resolve(publication_number: str) -> tuple[list[str], dict[str, Any]]:
        attempt: dict[str, Any] = {"provider": "epo_ops", "status": "unavailable"}
        if not raw_command:
            attempt["reason"] = "未配置 CN_PATENT_EPO_PROVIDER_COMMAND"
            return [], attempt
        try:
            # Windows 下 shlex 默认 POSIX 模式会把反斜杠当转义符，
            # 导致 python.exe 这类带路径的命令被拆坏；POSIX 平台保持默认语义。
            argv = shlex.split(raw_command, posix=os.name != "nt")
        except ValueError as exc:
            attempt.update(status="error", reason=f"provider 命令解析失败：{exc}")
            return [], attempt
        if not argv:
            attempt["reason"] = "EPO provider 命令为空"
            return [], attempt
        try:
            completed = subprocess.run(
                [*argv, publication_number],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                attempt.update(
                    status="error",
                    reason=f"provider 退出码 {completed.returncode}: {completed.stderr.strip()[-500:]}",
                )
                return [], attempt
            payload = json.loads(completed.stdout)
            if not isinstance(payload, dict):
                raise ValueError("provider 输出顶层必须是 JSON 对象")
            if payload.get("error"):
                attempt.update(status="error", reason=str(payload["error"]))
                return [], attempt
            codes = normalize_ipc_list(payload.get("ipc_codes", []), "EPO provider ipc_codes")
            if not codes:
                attempt.update(status="not_found", reason="EPO provider 未返回 IPC")
                return [], attempt
            attempt.update(status="success", ipc_codes=codes)
            return codes, attempt
        except Exception as exc:  # 外部 provider 失败必须进入报告，不得伪装成无分类。
            attempt.update(status="error", reason=f"{type(exc).__name__}: {exc}")
            return [], attempt

    return resolve


def epo_resolver(publication_number: str) -> tuple[list[str], dict[str, Any]]:
    """使用环境变量配置的独立 provider，保留旧的可注入 resolver 接口。"""

    return build_epo_resolver()(publication_number)


def resolve_candidate_ipc(
    candidate: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    resolver: Callable[[str], tuple[list[str], dict[str, Any]]] = epo_resolver,
) -> tuple[list[str], str, list[dict[str, Any]]]:
    number = candidate["publication_number"]
    attempts: list[dict[str, Any]] = []
    codes, attempt = resolver(number)
    attempts.append(attempt)
    if codes:
        return codes, "epo_ops", attempts

    cached = cache.get(number)
    if isinstance(cached, dict) and cached.get("ipc_codes"):
        codes = normalize_ipc_list(cached["ipc_codes"], f"classification_cache.{number}.ipc_codes")
        source = str(cached.get("source") or "classification_cache")
        attempts.append({"provider": "classification_cache", "status": "success", "source": source})
        return codes, source, attempts

    if candidate.get("ipc_codes"):
        codes = normalize_ipc_list(candidate["ipc_codes"], f"{number}.ipc_codes")
        source = str(candidate.get("classification_source") or "candidate_input")
        attempts.append({"provider": "candidate_input", "status": "success", "source": source})
        return codes, source, attempts

    attempts.append({"provider": "candidate_input", "status": "not_found"})
    return [], "unresolved", attempts


def tier_score(tier: int) -> float:
    """Tier 1 = 1.00、Tier 2 = 0.70，更靠后的梯队按 0.30 递减并保底 0.40。"""

    return TIER_SCORES.get(tier, max(0.40, 1.0 - 0.3 * (tier - 1)))


def normalize_entity_name(value: str) -> str:
    """归一化机构名称用于名单匹配；不改变写入报告的名称。"""

    text = re.sub(r"[（(][^）)]*[）)]", "", value)
    text = re.sub(r"[\s·・,，、.。:：;；\-—_]+", "", text)
    for _ in range(3):
        stripped = ENTITY_SUFFIX_RE.sub("", text)
        if stripped == text or not stripped:
            break
        text = stripped
    return text


def load_notable_entities(path: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    """解析知名申请人与代理机构名单，按 Tier 建索引。

    名单是带 ``## 知名公司（Tier 1）`` 这类小标题的纯文本；``#`` 开头的行是注释。
    标题含"代理/事务所"归入 agency，含"公司/申请人"归入 company，未识别的标题被忽略。
    """

    source = Path(path) if path else ENTITIES_PATH
    try:
        raw = source.read_bytes()
    except FileNotFoundError as exc:
        raise SelectionError(f"知名实体名单不存在：{source}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SelectionError(f"知名实体名单含 BOM，必须使用 UTF-8 无 BOM：{source}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SelectionError(f"知名实体名单不是有效 UTF-8：{source}（{exc}）") from exc

    registry: dict[str, dict[str, dict[str, Any]]] = {"company": {}, "agency": {}}
    kind: str | None = None
    tier: int | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not line.startswith("##"):
                continue
            header = line.lstrip("#").strip()
            tier_match = re.search(r"[Tt]ier\s*(\d+)", header)
            tier = int(tier_match.group(1)) if tier_match else None
            if "代理" in header or "事务所" in header:
                kind = "agency"
            elif "公司" in header or "申请人" in header:
                kind = "company"
            else:
                kind = None
            continue
        if kind is None or tier is None:
            continue
        key = normalize_entity_name(line)
        if len(key) < 2:
            continue
        registry[kind][key] = {"name": line, "key": key, "tier": tier, "score": tier_score(tier)}

    if not registry["company"] and not registry["agency"]:
        raise SelectionError(f"知名实体名单未解析出任何机构：{source}")
    return registry


def match_entity(name: str, table: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """在单个名单表内匹配机构；同命中多个条目时取最长的归一化名称。"""

    key = normalize_entity_name(name)
    if not key:
        return None
    exact = table.get(key)
    if exact is not None:
        return {**exact, "match": "exact"}
    if len(key) < 4:
        return None
    matches = [
        entry for entry_key, entry in table.items()
        if len(entry_key) >= 4 and (entry_key in key or key in entry_key)
    ]
    if not matches:
        return None
    best = max(matches, key=lambda entry: len(entry["key"]))
    return {**best, "match": "contains"}


def entity_quality(
    name: Any,
    kind: str,
    registry: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """把申请人/代理机构名称折算成 0—1 的名单质量分。

    命中名单按 Tier 计分；有名称但不在名单计 0.30（中性偏保守，不视为低质）；
    名称为空计 0.00，并在报告中标记 missing，避免"没填"被当成"填了但没上榜"。
    """

    if not isinstance(name, str) or not name.strip():
        return {
            "name": "", "status": "missing", "tier": None,
            "score": MISSING_ENTITY_SCORE, "matched_entry": None, "match": None,
        }
    cleaned = name.strip()
    entry = match_entity(cleaned, registry[kind])
    if entry is None:
        return {
            "name": cleaned, "status": "unlisted", "tier": None,
            "score": UNLISTED_ENTITY_SCORE, "matched_entry": None, "match": None,
        }
    return {
        "name": cleaned, "status": "listed", "tier": entry["tier"],
        "score": entry["score"], "matched_entry": entry["name"], "match": entry["match"],
    }


def candidate_entity_name(candidate: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = candidate.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_weights(weights: dict[str, float] | None = None) -> dict[str, float]:
    """校验并归一化四项权重；技术相关性与 IPC 必须保持正权重。"""

    resolved = dict(DEFAULT_WEIGHTS if weights is None else weights)
    missing = [field for field in WEIGHT_FIELDS if field not in resolved]
    if missing:
        raise SelectionError("权重缺少字段：" + "、".join(missing))
    unknown = [field for field in resolved if field not in WEIGHT_FIELDS]
    if unknown:
        raise SelectionError("未知权重字段：" + "、".join(sorted(unknown)))
    values: dict[str, float] = {}
    for field in WEIGHT_FIELDS:
        value = resolved[field]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise SelectionError(f"{field} 必须是不小于 0 的数值")
        values[field] = round(float(value), 6)
    total = round(sum(values.values()), 6)
    if abs(total - 1.0) > 1e-6:
        raise SelectionError(f"四项权重之和必须为 1，当前为 {total}")
    if values["technical_relevance"] <= 0:
        raise SelectionError("技术相关性必须保持正权重")
    if values["ipc_similarity"] <= 0:
        raise SelectionError("IPC 相似度必须保持正权重，不得退化为只看标题、摘要或主体名单")
    return values


def candidate_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = payload.get("candidates", payload.get("shortlist"))
    if not isinstance(values, list) or not values:
        raise SelectionError("候选清单必须包含非空 candidates 数组")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            raise SelectionError(f"第 {index} 个候选不是对象")
        number = item.get("publication_number")
        title = item.get("title")
        score = item.get("technical_relevance_score")
        reason = item.get("technical_relevance_reason")
        if not isinstance(number, str) or not number.strip():
            raise SelectionError(f"第 {index} 个候选缺少 publication_number")
        number = number.replace(" ", "").upper()
        if number in seen:
            raise SelectionError(f"候选公开号重复：{number}")
        seen.add(number)
        if not isinstance(title, str) or not title.strip():
            raise SelectionError(f"{number} 缺少 title")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 1:
            raise SelectionError(f"{number} 的 technical_relevance_score 必须在 0—1")
        if not isinstance(reason, str) or not reason.strip():
            raise SelectionError(f"{number} 缺少 technical_relevance_reason")
        normalized = dict(item)
        normalized["publication_number"] = number
        normalized["title"] = title.strip()
        normalized["technical_relevance_score"] = round(float(score), 6)
        normalized["technical_relevance_reason"] = reason.strip()
        result.append(normalized)
    return result


def rank_templates(
    search_manifest: dict[str, Any],
    candidates_payload: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    cache: dict[str, dict[str, Any]] | None = None,
    resolver: Callable[[str], tuple[list[str], dict[str, Any]]] = epo_resolver,
    selected_number: str | None = None,
    selection_reason: str | None = None,
    registry: dict[str, dict[str, dict[str, Any]]] | None = None,
    entities_path: Path | None = None,
) -> dict[str, Any]:
    if search_manifest.get("schema_id") != SEARCH_SCHEMA_ID:
        raise SelectionError(f"search-query.json 的 schema_id 必须是 {SEARCH_SCHEMA_ID}")
    target = search_manifest.get("target_ipc")
    if not isinstance(target, dict) or target.get("status") != "determined":
        raise SelectionError("目标 IPC 尚未确定；先在 technical-features.json 明确 ipc_codes 并重新生成 search-query.json")
    target_codes = normalize_ipc_list(target.get("ipc_codes"), "target_ipc.ipc_codes")
    if not target_codes:
        raise SelectionError("目标 IPC 为空，禁止进入范本选择")
    resolved_weights = resolve_weights(weights)
    entity_registry = registry if registry is not None else load_notable_entities(entities_path)
    ranked: list[dict[str, Any]] = []
    for candidate in candidate_list(candidates_payload):
        codes, source, attempts = resolve_candidate_ipc(candidate, cache or {}, resolver)
        match = best_ipc_match(target_codes, codes) if codes else {
            "score": 0.0, "level": "unresolved", "target_ipc": None, "candidate_ipc": None
        }
        technical_score = candidate["technical_relevance_score"]
        entity = {
            "applicant": entity_quality(
                candidate_entity_name(candidate, APPLICANT_FIELDS), "company", entity_registry
            ),
            "agency": entity_quality(
                candidate_entity_name(candidate, AGENCY_FIELDS), "agency", entity_registry
            ),
        }
        weighted = (
            resolved_weights["technical_relevance"] * technical_score
            + resolved_weights["ipc_similarity"] * float(match["score"])
            + resolved_weights["applicant_quality"] * entity["applicant"]["score"]
            + resolved_weights["agency_quality"] * entity["agency"]["score"]
        )
        ranked.append({
            **candidate,
            "ipc_codes": codes,
            "ipc_status": "resolved" if codes else "unresolved",
            "classification_source": source,
            "classification_attempts": attempts,
            "ipc_similarity": match,
            "entity_quality": entity,
            "weighted_score": round(weighted, 6),
            "eligible": bool(codes),
        })
    ranked.sort(
        key=lambda item: (
            item["eligible"], item["weighted_score"], item["ipc_similarity"]["score"],
            item["entity_quality"]["applicant"]["score"] + item["entity_quality"]["agency"]["score"],
            item["technical_relevance_score"], item["publication_number"]
        ), reverse=True
    )
    eligible = [item for item in ranked if item["eligible"]]
    if not eligible:
        raise SelectionError("所有范本候选的 IPC 均未取得；不得在没有候选 IPC 的情况下选定范本")
    recommended = eligible[0]
    selected = recommended
    override = False
    if selected_number:
        number = selected_number.replace(" ", "").upper()
        selected = next((item for item in eligible if item["publication_number"] == number), None)
        if selected is None:
            raise SelectionError(f"指定范本 {number} 不存在或 IPC 未解析")
        override = number != recommended["publication_number"]
        if override and (not isinstance(selection_reason, str) or not selection_reason.strip()):
            raise SelectionError("人工选择未采用加权最高候选时，必须提供 --selection-reason")
    reason = (selection_reason or (
        "技术相关性、IPC 相似度、申请人质量与代理机构质量四项加权得分最高。"
    )).strip()
    entity_path = Path(entities_path) if entities_path else ENTITIES_PATH
    return {
        "schema_id": SCHEMA_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_ipc": {"status": "determined", "ipc_codes": target_codes, "source": target.get("source", "search-query.json")},
        "weights": resolved_weights,
        "entity_policy": {
            "source": str(entity_path),
            "tiers": {f"tier{key}": value for key, value in sorted(TIER_SCORES.items())},
            "unlisted_score": UNLISTED_ENTITY_SCORE,
            "missing_score": MISSING_ENTITY_SCORE,
            "match_rule": ENTITY_MATCH_RULE,
            "boundary": "名单命中只表示申请人/代理机构在知名实体清单内，不构成对具体机构撰写质量或法律结论的评价。",
        },
        "entity_evidence": {
            "total": len(ranked),
            "with_applicant": sum(
                1 for item in ranked if item["entity_quality"]["applicant"]["status"] != "missing"
            ),
            "with_agency": sum(
                1 for item in ranked if item["entity_quality"]["agency"]["status"] != "missing"
            ),
            "listed_applicant": sum(
                1 for item in ranked if item["entity_quality"]["applicant"]["status"] == "listed"
            ),
            "listed_agency": sum(
                1 for item in ranked if item["entity_quality"]["agency"]["status"] == "listed"
            ),
        },
        "classification_policy": {
            "preferred_provider": "epo_ops",
            "fallback_order": ["classification_cache", "candidate_input"],
            "boundary": "EPO OPS 未配置、未收录或失败时允许使用有来源记录的缓存/输入分类；未取得 IPC 的候选不得入选。",
        },
        "candidates": ranked,
        "recommended": {
            "publication_number": recommended["publication_number"],
            "weighted_score": recommended["weighted_score"],
        },
        "selected": {
            "publication_number": selected["publication_number"],
            "weighted_score": selected["weighted_score"],
            "technical_relevance_score": selected["technical_relevance_score"],
            "ipc_codes": selected["ipc_codes"],
            "ipc_similarity": selected["ipc_similarity"],
            "classification_source": selected["classification_source"],
            "entity_quality": selected["entity_quality"],
            "entity_evidence_complete": all(
                selected["entity_quality"][key]["status"] != "missing"
                for key in ("applicant", "agency")
            ),
            "override_recommended": override,
            "selection_reason": reason,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按技术相关性、IPC 相似度与撰写主体质量加权选择中国专利范本")
    parser.add_argument("--search-query", required=True, type=Path, help="generate_search_query.py 输出")
    parser.add_argument("--candidates", required=True, type=Path, help="cn-patent-template-candidates/v1 候选清单")
    parser.add_argument("--output", required=True, type=Path, help="template-selection.json")
    parser.add_argument(
        "--technical-weight", type=float, default=None,
        help=f"技术相关性权重，默认 {DEFAULT_WEIGHTS['technical_relevance']}；指定任一时四项必须同时给出",
    )
    parser.add_argument(
        "--ipc-weight", type=float, default=None,
        help=f"IPC 相似度权重，默认 {DEFAULT_WEIGHTS['ipc_similarity']}，必须大于 0",
    )
    parser.add_argument(
        "--applicant-weight", type=float, default=None,
        help=f"申请人质量权重，默认 {DEFAULT_WEIGHTS['applicant_quality']}",
    )
    parser.add_argument(
        "--agency-weight", type=float, default=None,
        help=f"代理机构质量权重，默认 {DEFAULT_WEIGHTS['agency_quality']}",
    )
    parser.add_argument(
        "--notable-entities", type=Path, default=None,
        help="知名申请人与代理机构名单，默认使用技能内置 references/notable-entities.txt",
    )
    parser.add_argument("--classification-cache", type=Path, help="可选的公开号→IPC 分类缓存")
    parser.add_argument(
        "--epo-provider-command",
        default=os.getenv("CN_PATENT_EPO_PROVIDER_COMMAND"),
        help="可选 EPO provider 命令；程序会把公开号作为最后一个 argv 传入并读取 JSON stdout",
    )
    parser.add_argument("--selected", help="人工最终选定的公开号；省略时采用加权最高候选")
    parser.add_argument("--selection-reason", help="人工偏离推荐候选时的理由")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        search_manifest = load_json(args.search_query, "search-query.json")
        candidates_payload = load_json(args.candidates, "范本候选清单")
        if candidates_payload.get("schema_id") not in {None, CANDIDATE_SCHEMA_ID}:
            raise SelectionError(f"候选清单 schema_id 必须是 {CANDIDATE_SCHEMA_ID}")
        weights = {
            "technical_relevance": args.technical_weight,
            "ipc_similarity": args.ipc_weight,
            "applicant_quality": args.applicant_weight,
            "agency_quality": args.agency_weight,
        }
        if any(value is not None for value in weights.values()) and any(
            value is None for value in weights.values()
        ):
            raise SelectionError(
                "四项权重必须同时指定：--technical-weight、--ipc-weight、"
                "--applicant-weight、--agency-weight；省略全部则使用默认值 "
                + json.dumps(DEFAULT_WEIGHTS, ensure_ascii=False)
            )
        payload = rank_templates(
            search_manifest,
            candidates_payload,
            weights=None if all(value is None for value in weights.values()) else weights,
            cache=load_cache(args.classification_cache),
            resolver=build_epo_resolver(args.epo_provider_command),
            selected_number=args.selected,
            selection_reason=args.selection_reason,
            entities_path=args.notable_entities,
        )
        payload["inputs"] = {
            "search_query_path": str(args.search_query.resolve()),
            "search_query_sha256": sha256(args.search_query),
            "candidate_manifest_path": str(args.candidates.resolve()),
            "candidate_manifest_sha256": sha256(args.candidates),
        }
    except SelectionError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected = payload["selected"]
    entity = selected.get("entity_quality") or {}
    applicant = entity.get("applicant") or {}
    agency = entity.get("agency") or {}
    print(f"[OK] 范本加权选择报告：{args.output}")
    print(
        f"[INFO] 选定 {selected['publication_number']}；"
        f"综合得分 {selected['weighted_score']:.3f}；"
        f"技术 {selected['technical_relevance_score']:.2f}；"
        f"IPC {selected['ipc_similarity']['score']:.2f}（{selected['classification_source']}）；"
        f"申请人 {applicant.get('score', 0):.2f}（{applicant.get('status')}）；"
        f"代理机构 {agency.get('score', 0):.2f}（{agency.get('status')}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
