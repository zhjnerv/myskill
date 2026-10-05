#!/usr/bin/env python3
"""汇总各阶段 pending_decisions，并写出可人工回读的待决文件。"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cn_drafting_io import DraftingOutputGuard
from pending_file import (
    PENDING_FILENAME,
    PendingFileError,
    load_existing,
    render_pending_file,
    stable_key,
)

SCHEMA_ID = "cn-patent-pending-decisions/v1"
EXIT_SUCCESS = 0
EXIT_INPUT_ERROR = 3


def read_json_report(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"读取报告失败 {path}: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"含 BOM，必须使用 UTF-8 无 BOM：{path}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"读取报告失败 {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()



CNIPA_PENDING_KEY = "search.cnipa_manual_search_pending_authorization"
CNIPA_LOCATOR = "cnipa_manual_search"
_CNIPA_GAP = ("CNIPA", "官方库")
_SEARCH_GAP = ("检索", "未检索", "没有检索", "还没有检索")
_GAP_CLAUSE = re.compile(
    r"(?:^|[，,；;])\s*(?:但|并且|所以)?"
    r"(?:本案)?(?:还没有完成|尚未完成|未完成)?\s*(?:CNIPA|官方库)[^。；]*"
    r"|(?:^|[，,；;])\s*新颖性和创造性(?:都|仍)?不能(?:下结论|写成已经成立)"
    r"|(?:^|[，,；;])\s*新颖性和创造性仍不下结论"
    r"|(?:^|[，,；;])\s*新颖性/创造性维度保持\s*INCONCLUSIVE"
    r"|(?:^|[，,；;])\s*按官方库穷举未完成继续"
)


def _mentions_search_gap(value: str) -> bool:
    return any(token in value for token in _CNIPA_GAP) and any(token in value for token in _SEARCH_GAP)


def _user_stated_publication_or_priority(question: str) -> bool:
    stated = (
        "用户已说明",
        "用户说明",
        "用户写明",
        "在先申请号",
        "优先权日",
        "公开日为",
    )
    return any(token in question for token in stated)


def _is_unsolicited_publication_priority(decision: dict[str, Any]) -> bool:
    """材料没写公开或优先权时，不向审稿人主动提这个问题。"""
    target = decision.get("target") if isinstance(decision.get("target"), dict) else {}
    locator = str(target.get("locator") or "")
    key = str(decision.get("key") or "")
    question = str(decision.get("question") or "")
    if _user_stated_publication_or_priority(question):
        return False
    if locator in {"publication-priority", "publication_priority", "priority"}:
        return True
    if "publication" in key and "priority" in key:
        return True
    silent = any(
        token in question
        for token in ("没有写明", "未写明", "是否已经公开", "是否按尚未公开", "不主张优先权")
    )
    return silent and "优先权" in question and "公开" in question


def _strip_repeated_search_gap(value: str) -> str:
    if not isinstance(value, str) or not value:
        return value
    if not (_mentions_search_gap(value) or "新颖性和创造性" in value or "INCONCLUSIVE" in value):
        return value
    cleaned = _GAP_CLAUSE.sub("", value)
    cleaned = re.sub(r"[，,；;]{2,}", "，", cleaned)
    cleaned = re.sub(r"^[，,；;。？！\s]+", "", cleaned)
    cleaned = re.sub(r"[，,；;]+([。？！])", r"\1", cleaned)
    cleaned = re.sub(r"。{2,}", "。", cleaned).strip()
    if cleaned and cleaned[-1] not in "。？！":
        cleaned += "。"
    return cleaned


def _is_dedicated_cnipa(decision: dict[str, Any]) -> bool:
    target = decision.get("target") if isinstance(decision.get("target"), dict) else {}
    if decision.get("key") == CNIPA_PENDING_KEY or target.get("locator") == CNIPA_LOCATOR:
        return True
    return target.get("kind") == "process" and _mentions_search_gap(str(decision.get("question") or ""))


def suppress_routine_prompts(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """公开/优先权不主动问；CNIPA 人工检索未完成只保留一条。"""
    kept = [item for item in decisions if not _is_unsolicited_publication_priority(item)]
    keeper_index = next((index for index, item in enumerate(kept) if _is_dedicated_cnipa(item)), None)
    if keeper_index is None:
        keeper_index = next(
            (
                index for index, item in enumerate(kept)
                if _mentions_search_gap(
                    str(item.get("question") or "") + str(item.get("adopted_default") or "")
                )
            ),
            None,
        )
    if keeper_index is None:
        return kept
    result: list[dict[str, Any]] = []
    for index, item in enumerate(kept):
        if index == keeper_index:
            result.append(item)
            continue
        question_raw = str(item.get("question") or "")
        default_raw = str(item.get("adopted_default") or "")
        if not _mentions_search_gap(question_raw + default_raw):
            result.append(item)
            continue
        question = _strip_repeated_search_gap(question_raw)
        if not question:
            continue
        updated = dict(item)
        updated["question"] = question
        updated["adopted_default"] = _strip_repeated_search_gap(default_raw)
        result.append(updated)
    return result


def validate_decision(decision: dict, report_path: Path) -> None:
    required = [
        "key", "source", "target", "question",
        "adopted_default", "options", "impact", "decider",
    ]
    for field in required:
        if field not in decision:
            raise ValueError(f"[{report_path}] 缺少必填字段: {field}")
    source = decision.get("source")
    if not isinstance(source, dict) or "tool_id" not in source or "rule_id" not in source:
        raise ValueError(f"[{report_path}] source 缺少必填字段")
    target = decision.get("target")
    if not isinstance(target, dict) or "kind" not in target or "locator" not in target:
        raise ValueError(f"[{report_path}] target 缺少必填字段")


def resolve_table_path(args: argparse.Namespace) -> tuple[Path, str]:
    if args.docx and args.allow_detached:
        raise PendingFileError("--docx 与 --allow-detached 不能同时使用")
    if args.docx:
        docx = Path(args.docx)
        if docx.suffix.lower() != ".docx":
            raise PendingFileError("--docx 必须指向 .docx 申请文件")
        expected = docx.parent / PENDING_FILENAME
        if args.table and Path(args.table).resolve() != expected.resolve():
            raise PendingFileError(
                f"待决文件必须是最终申请文件同目录下的 {PENDING_FILENAME}"
            )
        return expected, docx.name
    if not args.allow_detached:
        raise PendingFileError("待决文件必须与最终申请文件放在同一目录，请传入 --docx")
    if not args.table:
        raise PendingFileError("--allow-detached 时必须传入 --table")
    return Path(args.table), "（未绑定最终申请文件）"


def read_existing(path: Path) -> tuple[bytes | None, dict[str, list]]:
    if not path.exists():
        return None, {"items": [], "retired": []}
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PendingFileError(f"含 BOM，必须使用 UTF-8 无 BOM：{path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PendingFileError(f"待决文件不是 UTF-8：{path}") from exc
    return raw, load_existing(text)


def assign_ids(
    decisions: list[dict[str, Any]], existing: dict[str, list]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], list[dict[str, Any]]]:
    active = {
        stable_key(item["key"], item["kind"], item["locator"]): item
        for item in existing["items"]
    }
    retired_map = {
        stable_key(item["key"], item["kind"], item["locator"]): item
        for item in existing["retired"]
    }
    notes: dict[str, dict[str, str]] = {}
    used = {item["id"] for item in [*active.values(), *retired_map.values()]}
    ordered = sorted(
        decisions,
        key=lambda item: (item["key"], item["target"]["kind"], item["target"]["locator"]),
    )
    for decision in ordered:
        key = stable_key(decision["key"], decision["target"]["kind"], decision["target"]["locator"])
        previous = active.pop(key, None) or retired_map.pop(key, None)
        if previous:
            decision["id"] = previous["id"]
            notes[key] = {
                "decision": previous.get("decision", ""),
                "annotation": previous.get("annotation", ""),
            }
        else:
            decision["id"] = ""
    counter = 1
    for decision in ordered:
        if decision["id"]:
            continue
        while f"D{counter:03d}" in used:
            counter += 1
        decision["id"] = f"D{counter:03d}"
        used.add(decision["id"])
        counter += 1
    ordered.sort(key=lambda item: item["id"])
    retired = [*retired_map.values(), *active.values()]
    retired.sort(key=lambda item: item["id"])
    return ordered, notes, retired


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总待决事项并生成可回读的待决文件")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--docx", help="最终申请文件路径。待决文件固定写到同目录的 待决文件.md")
    parser.add_argument("--table", help="仅在 --allow-detached 时指定脱离交付目录的路径")
    parser.add_argument("--allow-detached", action="store_true", help="仅测试可把待决文件写到非交付目录")
    args = parser.parse_args()

    try:
        table_path, application_name = resolve_table_path(args)
        snapshot, existing = read_existing(table_path)
    except (PendingFileError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    input_paths = [Path(item) for item in args.report]
    output_paths = [Path(args.output), table_path]
    try:
        guard = DraftingOutputGuard(input_paths, output_paths)
    except Exception as exc:
        print(f"路径冲突: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    sources = []
    collected: dict[str, dict[str, Any]] = {}
    try:
        for report_path in input_paths:
            data = read_json_report(report_path)
            pending = data.get("pending_decisions")
            if pending is None:
                sources.append({
                    "tool_id": data.get("tool_id", "unknown"),
                    "report_path": str(report_path),
                    "sha256": sha256_file(report_path),
                    "count": 0,
                })
                continue
            if not isinstance(pending, list):
                raise ValueError(f"[{report_path}] pending_decisions 必须是数组")
            count = 0
            for decision in pending:
                validate_decision(decision, report_path)
                dedupe_key = f"{decision['key']}::{decision['target']['locator']}"
                if dedupe_key not in collected:
                    copied = dict(decision)
                    copied["duplicates_of"] = []
                    collected[dedupe_key] = copied
                    count += 1
                else:
                    collected[dedupe_key]["duplicates_of"].append({
                        "tool_id": decision["source"]["tool_id"],
                        "rule_id": decision["source"]["rule_id"],
                    })
            sources.append({
                "tool_id": data.get("tool_id", "unknown"),
                "report_path": str(report_path),
                "sha256": sha256_file(report_path),
                "count": count,
            })
        decisions, notes, retired = assign_ids(
            suppress_routine_prompts(list(collected.values())), existing,
        )
    except PendingFileError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"处理失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    summary = {
        "decider": {"inventor": 0, "attorney": 0, "both": 0},
        "impact": {
            "protection_scope": 0,
            "grant_risk": 0,
            "formality": 0,
            "delivery": 0,
            "evidence": 0,
        },
    }
    for decision in decisions:
        if not decision.get("duplicates_of"):
            decision.pop("duplicates_of", None)
        decider = decision["decider"]
        summary["decider"][decider] = summary["decider"].get(decider, 0) + 1
        for impact in decision["impact"]:
            summary["impact"][impact] = summary["impact"].get(impact, 0) + 1

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_id": SCHEMA_ID,
        "case_id": Path(args.case_dir).name,
        "generated_at": generated_at,
        "legal_effect": "ADVISORY_ONLY",
        "sources": sources,
        "decisions": decisions,
        "summary": summary,
    }
    try:
        if snapshot is not None and table_path.read_bytes() != snapshot:
            raise PendingFileError("待决文件在汇总期间被修改，已停止覆盖")
        markdown = render_pending_file(
            case_id=payload["case_id"],
            generated_at=generated_at,
            application_name=application_name,
            decisions=decisions,
            notes=notes,
            retired=retired,
        )
        guard.write_texts((
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            markdown,
        ))
    except (PendingFileError, OSError, ValueError) as exc:
        print(f"写入失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
