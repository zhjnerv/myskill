from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from check_priority_review import ipc_rule_prefix_matches, normalize_full_ipc_for_rule
except ImportError:
    from .check_priority_review import ipc_rule_prefix_matches, normalize_full_ipc_for_rule



def _clean_preexam_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    """精简预审数据：只保留匹配与展示必需的核心字段，剔除内部审计、哈希与原始文件列表。"""
    raw_centers = raw_data.get("center_index") or {}
    clean_centers: dict[str, dict[str, Any]] = {}

    for center_id, center in raw_centers.items():
        if not isinstance(center, dict):
            continue
        clean_centers[center_id] = {
            "center_id": center.get("center_id", center_id),
            "center_name": center.get("center_name", ""),
            "province": center.get("province", ""),
            "city": center.get("city"),
            "level": center.get("level", "city"),
            "accepted_ipc": center.get("accepted_ipc", []),
        }

    return {
        "metadata": raw_data.get("metadata", {}),
        "summary": raw_data.get("summary", {}),
        "center_index": clean_centers,
        "region_index": raw_data.get("region_index", {}),
        "region_alias_index": raw_data.get("region_alias_index", {}),
    }


def _clean_priority_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    """精简优审数据：去重冗余条目，为每条规则分配全局唯一 rule_id，重建展开索引映射。"""
    raw_rules = raw_data.get("rules") or raw_data.get("entries") or []
    clean_rules: list[dict[str, Any]] = []
    rules_by_orig_id: dict[str, list[tuple[str, dict[str, Any], str, str, list[str]]]] = {}

    for idx, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            continue
        orig_id = item.get("rule_id") or item.get("entry_id", "")
        unique_rule_id = f"{orig_id}:{idx}"
        rule_dict = {
            "rule_id": unique_rule_id,
            "table_id": item.get("table_id", ""),
            "table_name": item.get("table_name") or item.get("document_title", ""),
            "table_source": item.get("table_source") or item.get("publisher", ""),
            "table_year": item.get("table_year") or item.get("document_year"),
            "row_title": item.get("row_title", ""),
            "technology_branch_code": item.get("technology_branch_code") or item.get("row_title", ""),
            "technology_branch_name": item.get("technology_branch_name", ""),
            "keyword_summary": item.get("keyword_summary", ""),
            "raw_expression": item.get("raw_expression", ""),
            "include_prefix": item.get("include_prefix", ""),
            "exclude_prefixes": item.get("exclude_prefixes") or [],
            "match_mode": item.get("match_mode", "exact"),
            "has_star": bool(item.get("has_star")),
            "code_level": item.get("code_level", "group_or_subgroup"),
            "normalized_code": item.get("normalized_code", ""),
        }
        clean_rules.append(rule_dict)

        inc = normalize_full_ipc_for_rule(str(item.get("include_prefix") or ""))
        mode = str(item.get("match_mode") or "exact")
        excs = [normalize_full_ipc_for_rule(str(x)) for x in (item.get("exclude_prefixes") or []) if x]
        rule_tuple = (unique_rule_id, rule_dict, inc, mode, excs)
        if orig_id not in rules_by_orig_id:
            rules_by_orig_id[orig_id] = []
        rules_by_orig_id[orig_id].append(rule_tuple)

    def fast_matches(code_norm: str, rule_tuple: tuple[str, dict[str, Any], str, str, list[str]]) -> bool:
        _, _, inc, mode, excs = rule_tuple
        if not inc:
            return False
        if mode == "prefix":
            if not ipc_rule_prefix_matches(code_norm, inc):
                return False
        elif code_norm != inc:
            return False
        return not any(ex and ipc_rule_prefix_matches(code_norm, ex) for ex in excs)

    raw_idx = raw_data.get("expanded_group_index", {})
    cleaned_idx: dict[str, dict[str, Any]] = {}
    for code, entry in raw_idx.items():
        code_norm = normalize_full_ipc_for_rule(code)
        orig_entry_ids = entry.get("entry_ids", [])
        item_tables = set(entry.get("tables", []))
        matched_uids: list[str] = []
        seen: set[str] = set()
        for orig_eid in orig_entry_ids:
            for r_tuple in rules_by_orig_id.get(orig_eid, []):
                uid = r_tuple[0]
                if uid not in seen and fast_matches(code_norm, r_tuple):
                    seen.add(uid)
                    matched_uids.append(uid)
        if not matched_uids:
            for orig_eid in orig_entry_ids:
                for r_tuple in rules_by_orig_id.get(orig_eid, []):
                    uid = r_tuple[0]
                    if uid not in seen and (not item_tables or r_tuple[1].get("table_id") in item_tables):
                        seen.add(uid)
                        matched_uids.append(uid)
        cleaned_idx[code] = {
            "entry_ids": matched_uids,
            "tables": entry.get("tables", []),
        }

    return {
        "version": raw_data.get("version", "1.0"),
        "table_summaries": raw_data.get("table_summaries", []),
        "rules": clean_rules,
        "eligible_ipc_groups": raw_data.get("eligible_ipc_groups", []),
        "expanded_ipc_groups": raw_data.get("expanded_ipc_groups", []),
        "expanded_group_index": cleaned_idx,
    }


def _clean_definition_text(text: str) -> tuple[str, bool]:
    """清洗官方定义中的连续重复分句或残缺尾部拼接（如 C01G 的连续数百次碳酸盐重复）。"""
    if not isinstance(text, str) or not text.strip():
        return text, False
    original = text
    # 清洗连续重复的分句（分号结尾，长度>=6且连续重复，或较短短语连续重复3次以上）
    cleaned = re.sub(r"((?:[^;；\n]{6,}[;；]))(?:\s*\1)+", r"\1", text)
    cleaned = re.sub(r"((?:[^;；\n]+[;；]))(?:\s*\1){2,}", r"\1", cleaned)

    # 检查尾部是否存在由于截断导致的残缺前缀重复
    m = re.search(r"([^;；\n]+)[;；]([^;；\n]+)$", cleaned)
    if m:
        prev, tail = m.group(1).strip(), m.group(2).strip()
        if len(tail) >= 4 and (prev.startswith(tail) or tail in prev):
            cleaned = cleaned[:-len(tail)].rstrip(";；")
            if "（" in cleaned and "）" not in cleaned:
                cleaned += "）"

    return cleaned, cleaned != original


def _clean_definitions_data(raw_data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    clean_defs: dict[str, Any] = {}
    affected_count = 0
    for code, item in raw_data.items():
        if not isinstance(item, dict):
            continue
        zh_text = item.get("zh", "")
        en_text = item.get("en", "")
        clean_zh, changed_zh = _clean_definition_text(zh_text)
        clean_en, changed_en = _clean_definition_text(en_text)
        if changed_zh or changed_en:
            affected_count += 1
        clean_defs[code] = {
            "zh": clean_zh,
            "en": clean_en,
        }
    return clean_defs, affected_count


def _write_json_or_gz(data: Any, target_path: Path, use_gzip: bool) -> int:
    serialized = json.dumps(data, ensure_ascii=False, indent=None if use_gzip else 2)
    encoded = serialized.encode("utf-8")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if use_gzip:
        out_path = target_path.with_name(target_path.name + ".gz") if not target_path.name.endswith(".gz") else target_path
        compressed = gzip.compress(encoded, compresslevel=9)
        out_path.write_bytes(compressed)
        return len(compressed)
    else:
        out_path = target_path.with_name(target_path.name[:-3]) if target_path.name.endswith(".gz") else target_path
        out_path.write_text(serialized, encoding="utf-8")
        return len(encoded)


def build_data(
    preexam_input: Path | None,
    priority_input: Path | None,
    definitions_input: Path | None,
    output_dir: Path,
    use_gzip: bool = True,
) -> dict[str, Any]:
    stats: dict[str, Any] = {}

    if preexam_input and preexam_input.exists():
        raw_preexam = json.loads(preexam_input.read_text(encoding="utf-8"))
        cleaned_preexam = _clean_preexam_data(raw_preexam)
        target_name = "preexam_ready.json.gz" if use_gzip else "preexam_ready.json"
        bytes_written = _write_json_or_gz(cleaned_preexam, output_dir / target_name, use_gzip)
        stats["preexam"] = {
            "centers": len(cleaned_preexam["center_index"]),
            "provinces": len(cleaned_preexam["region_index"]),
            "size_bytes": bytes_written,
        }

    if priority_input and priority_input.exists():
        raw_priority = json.loads(priority_input.read_text(encoding="utf-8"))
        cleaned_priority = _clean_priority_data(raw_priority)
        target_name = "priority_review.json.gz" if use_gzip else "priority_review.json"
        bytes_written = _write_json_or_gz(cleaned_priority, output_dir / target_name, use_gzip)
        stats["priority"] = {
            "rules": len(cleaned_priority["rules"]),
            "expanded_groups": len(cleaned_priority["expanded_ipc_groups"]),
            "size_bytes": bytes_written,
        }

    if definitions_input and definitions_input.exists():
        raw_defs = json.loads(definitions_input.read_text(encoding="utf-8"))
        cleaned_defs, affected_count = _clean_definitions_data(raw_defs)
        target_name = "ipc_subclass_definitions.json.gz" if use_gzip else "ipc_subclass_definitions.json"
        bytes_written = _write_json_or_gz(cleaned_defs, output_dir / target_name, use_gzip)
        stats["definitions"] = {
            "count": len(cleaned_defs),
            "cleaned_subclasses_count": affected_count,
            "size_bytes": bytes_written,
        }

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从原始专利预审与优审数据构建 Skill 运行时所需的精简数据包。"
    )
    parser.add_argument(
        "--preexam-input",
        type=Path,
        help="原始 preexam_ready_all.json 文件路径",
    )
    parser.add_argument(
        "--priority-input",
        type=Path,
        help="原始 priority_review_ipc.json 文件路径",
    )
    parser.add_argument(
        "--definitions-input",
        type=Path,
        help="可选的 ipc_subclass_definitions.json 文件路径",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
        help="数据输出目录（默认写入当前 Skill 的 data/ 目录）",
    )
    parser.add_argument(
        "--no-gzip",
        action="store_true",
        help="输出纯 JSON 文件而非 .json.gz 压缩包",
    )

    args = parser.parse_args(argv)

    if not args.preexam_input and not args.priority_input and not args.definitions_input:
        parser.error("至少需要指定 --preexam-input、--priority-input 或 --definitions-input 之一。")

    stats = build_data(
        preexam_input=args.preexam_input,
        priority_input=args.priority_input,
        definitions_input=args.definitions_input,
        output_dir=args.output_dir,
        use_gzip=not args.no_gzip,
    )

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
