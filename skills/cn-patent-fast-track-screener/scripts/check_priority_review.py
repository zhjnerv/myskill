from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any

from normalize_ipc import (
    extract_ipc_codes_from_text,
    extract_subclass_from_full_ipc,
    normalize_ipc_codes,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_PRIORITY_PATH = DEFAULT_DATA_DIR / "priority_review.json.gz"
DISCLAIMER = "本结果仅用于专利加快程序分类范围初筛，不代表国家知识产权局一定受理，也不代表专利授权前景。"

# 《专利优先审查管理办法》（国家知识产权局令第76号）第二条法定情形
STATUTORY_CONDITIONS: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "国家重点发展产业",
        "description": "涉及节能环保、新一代信息技术、生物、高端装备制造、新能源、新材料、新能源汽车、智能制造等国家重点发展产业。",
        "evidence_required": "属于国家重点产业目录范围的技术方案说明或对应 IPC 产业分类匹配。",
    },
    {
        "id": 2,
        "name": "地方重点鼓励产业",
        "description": "涉及各省级和设区的市级人民政府重点鼓励的产业。",
        "evidence_required": "提供省级或市级政府发布的重点产业目录文件及方案落入该目录的说明材料。",
    },
    {
        "id": 3,
        "name": "更新速度快的技术领域",
        "description": "涉及互联网、大数据、云计算等技术且技术或者产品更新速度快。",
        "evidence_required": "涉及互联网/大数据/云计算相关架构及产品快速迭代生命周期的说明。",
    },
    {
        "id": 4,
        "name": "已做好实施准备或已实施",
        "description": "专利申请人或者复审请求人已经做好实施准备或者已经开始实施，或者有证据证明他人正在实施其发明创造。",
        "evidence_required": "产品投产、销售合同、设备采购发票、厂房建设、模具开发凭证或他人侵权实施证据。",
    },
    {
        "id": 5,
        "name": "就相同主题向境外提出首次申请",
        "description": "就相同主题首次在中国提出专利申请又向其他国家或者地区提出申请的该中国首次申请。",
        "evidence_required": "PCT 国际申请受理通知书、境外专利局受理通知书或优先权证明文件。",
    },
    {
        "id": 6,
        "name": "国家利益或公共利益重大意义",
        "description": "其他对国家利益或者公共利益具有重大意义需要优先审查。",
        "evidence_required": "国家重大工程、国家级科技专项立项批复或关乎重大公共安全/卫生的证明。",
    },
]


def load_priority_data(data_path: Path | None = None) -> dict[str, Any]:
    path = data_path or DEFAULT_PRIORITY_PATH
    if not path.exists():
        fallback_json = path.with_suffix("") if path.suffix == ".gz" else path.with_name(path.name + ".gz")
        if fallback_json.exists():
            path = fallback_json
        else:
            raise FileNotFoundError(f"未找到优审数据文件: {path}")

    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_full_ipc_for_rule(value: Any) -> str:
    """把完整 IPC 分类号归一为无空格形式，用于规则前缀与排除项比对。"""
    if not isinstance(value, str):
        return ""
    text = value.strip().upper().replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    match = re.match(r"^([A-H][0-9]{2}[A-Z])([0-9]+)/([0-9]+)$", text)
    if not match:
        return text.rstrip("*")
    subclass, main_group, subgroup = match.groups()
    return f"{subclass}{int(main_group)}/{subgroup}"


def format_full_ipc_display(value: Any) -> str:
    normalized = normalize_full_ipc_for_rule(value)
    match = re.match(r"^([A-H][0-9]{2}[A-Z])([0-9]+)/([0-9]+)$", normalized)
    if not match:
        return normalized
    subclass, main_group, subgroup = match.groups()
    return f"{subclass} {int(main_group)}/{subgroup}"


def ipc_rule_prefix_matches(symbol: Any, prefix: Any) -> bool:
    """按 IPC 层级边界判断完整号是否落入前缀（如 G06F11* 匹配 G06F 11/22 但不匹配 G06F 111/00）。"""
    normalized_symbol = normalize_full_ipc_for_rule(symbol)
    normalized_prefix = normalize_full_ipc_for_rule(prefix).rstrip("*")
    if not normalized_symbol or not normalized_prefix:
        return False
    if "/" in normalized_prefix:
        return normalized_symbol == normalized_prefix or normalized_symbol.startswith(normalized_prefix)
    if len(normalized_prefix) == 4:
        return normalized_symbol.startswith(normalized_prefix)
    return normalized_symbol.startswith(f"{normalized_prefix}/")


def rule_matches_full_ipc(rule: dict[str, Any], full_ipc: str) -> bool:
    code = normalize_full_ipc_for_rule(full_ipc)
    include_prefix = normalize_full_ipc_for_rule(str(rule.get("include_prefix") or ""))
    if not code or not include_prefix:
        return False

    match_mode = str(rule.get("match_mode") or "exact")
    if match_mode == "prefix":
        if not ipc_rule_prefix_matches(code, include_prefix):
            return False
    elif code != include_prefix:
        return False

    exclusions = [
        normalize_full_ipc_for_rule(str(item))
        for item in (rule.get("exclude_prefixes") or [])
        if isinstance(item, str) and item
    ]
    return not any(prefix and ipc_rule_prefix_matches(code, prefix) for prefix in exclusions)


def _table_info(table_id: str, tables_by_id: dict[str, dict[str, Any]], rule: dict[str, Any] | None = None) -> dict[str, Any]:
    t = tables_by_id.get(table_id) or {}
    r = rule or {}
    year = r.get("table_year") or t.get("year")
    title = r.get("table_name") or t.get("table_name") or t.get("title", "")
    publisher = r.get("table_source") or t.get("source") or t.get("publisher", "国家知识产权局")
    return {
        "table_id": table_id,
        "title": title,
        "publisher": publisher,
        "year": year if isinstance(year, int) else None,
    }


def check_priority_review(
    ipc_codes: list[str] | None = None,
    statutory_condition_ids: list[int] | None = None,
    data: dict[str, Any] | None = None,
    data_path: Path | None = None,
) -> dict[str, Any]:
    if data is None:
        data = load_priority_data(data_path)

    raw_codes = ipc_codes or []
    normalized_all = normalize_ipc_codes(raw_codes, allow_full=True)
    if not normalized_all:
        return {
            "checked": bool(statutory_condition_ids),
            "matched": bool(statutory_condition_ids),
            "query_type": "statutory_condition" if statutory_condition_ids else "none",
            "matched_groups": [],
            "matched_codes": [],
            "matched_sources": [],
            "statutory_conditions": [c for c in STATUTORY_CONDITIONS if statutory_condition_ids and c["id"] in statutory_condition_ids],
            "message": "已核对指定的优先审查法定情形。" if statutory_condition_ids else "未得到有效 IPC 分类号，未核对优先审查政策范围。",
            "disclaimer": DISCLAIMER,
        }

    full_codes = [code for code in normalized_all if "/" in code]
    subclass_codes = [code for code in normalized_all if "/" not in code]

    tables_by_id = {t.get("table_id"): t for t in data.get("table_summaries", []) if isinstance(t, dict) and t.get("table_id")}
    rules = data.get("rules") or []
    rules_by_id = {r.get("rule_id"): r for r in rules if isinstance(r, dict) and r.get("rule_id")}
    eligible_groups = set(data.get("eligible_ipc_groups") or [])
    expanded_groups = set(data.get("expanded_ipc_groups") or [])
    expanded_group_index = data.get("expanded_group_index") or {}

    # 4位小类集合，用于判断是否属于已展开的小类
    expanded_subclasses = {extract_subclass_from_full_ipc(c) for c in expanded_groups if extract_subclass_from_full_ipc(c)}

    matched_groups: list[str] = []
    matched_sources: list[dict[str, Any]] = []

    # 1. 匹配完整号
    for code in full_codes:
        code_matched = False
        source_files: list[dict[str, Any]] = []
        matching_rule_details: list[dict[str, Any]] = []

        # 优先查已展开完整集合
        if code in eligible_groups or code in expanded_groups:
            code_matched = True
            norm_no_space = code.replace(" ", "")
            idx_item = expanded_group_index.get(norm_no_space) or expanded_group_index.get(code)
            if isinstance(idx_item, dict):
                seen_tables: set[str] = set()
                for table_id in idx_item.get("tables", []):
                    if table_id not in seen_tables:
                        seen_tables.add(table_id)
                        source_files.append(_table_info(table_id, tables_by_id))
                for entry_id in idx_item.get("entry_ids", []):
                    rule = rules_by_id.get(entry_id)
                    if rule:
                        if not rule_matches_full_ipc(rule, code):
                            continue
                        tid = rule.get("table_id")
                        if tid and tid not in seen_tables:
                            seen_tables.add(tid)
                            source_files.append(_table_info(tid, tables_by_id, rule))
                        matching_rule_details.append(rule)

        # 若不在已展开集合中，且所属小类不在已展开小类库中，动态规则比对
        if not code_matched:
            sub = extract_subclass_from_full_ipc(code)
            if sub not in expanded_subclasses:
                dynamic_matched_rules = [r for r in rules if rule_matches_full_ipc(r, code)]
                if dynamic_matched_rules:
                    code_matched = True
                    seen_tables = set()
                    for r in dynamic_matched_rules:
                        tid = r.get("table_id")
                        if tid and tid not in seen_tables:
                            seen_tables.add(tid)
                            source_files.append(_table_info(tid, tables_by_id, r))
                        matching_rule_details.append(r)

        if code_matched:
            matched_groups.append(code)
            matched_sources.append(
                {
                    "matched_code": code,
                    "match_level": "group",
                    "source_files": source_files,
                    "technology_branches": list(
                        dict.fromkeys(
                            r.get("technology_branch_name")
                            for r in matching_rule_details
                            if r.get("technology_branch_name")
                        )
                    ),
                }
            )

    matched = bool(matched_groups)

    # 处理只有 4 位小类的情形
    if not full_codes and subclass_codes:
        # 查找该小类下是否存在相关优审规则
        related_rule_count = sum(1 for r in rules if (r.get("include_prefix") or "").startswith(subclass_codes[0]))
        msg = (
            f"输入的是 4 位 IPC 小类（{', '.join(subclass_codes)}），该小类在优审体系中存在相关规则，但优审必须精确命中完整 IPC 组/小组号才能确认适用。"
            if related_rule_count > 0
            else f"输入的是 4 位 IPC 小类（{', '.join(subclass_codes)}），无法直接确认优先审查适用，需提供完整分类号（如 G06F 30/27）。"
        )
        return {
            "checked": True,
            "matched": False,
            "query_type": "subclass",
            "requires_full_ipc": True,
            "input_codes": normalized_all,
            "matched_groups": [],
            "matched_codes": [],
            "matched_sources": [],
            "related_rules_exist": related_rule_count > 0,
            "statutory_conditions": [c for c in STATUTORY_CONDITIONS if statutory_condition_ids and c["id"] in statutory_condition_ids],
            "message": msg,
            "disclaimer": DISCLAIMER,
        }

    message = (
        f"优审政策范围完整分类号命中（{', '.join(matched_groups)}），可在进入实质审查后进一步评估优先审查。"
        if matched
        else "未发现优审政策范围完整分类号命中。如方案符合实施准备、双报或地方重点产业等情形，仍可按法定事实条件申请优审。"
    )

    checked_conditions = [c for c in STATUTORY_CONDITIONS if statutory_condition_ids and c["id"] in statutory_condition_ids]

    return {
        "checked": True,
        "matched": matched,
        "query_type": "full_ipc",
        "requires_full_ipc": False,
        "input_codes": normalized_all,
        "matched_groups": matched_groups,
        "matched_codes": matched_groups,
        "matched_sources": matched_sources,
        "statutory_conditions": checked_conditions,
        "message": message,
        "disclaimer": DISCLAIMER,
    }


def search_priority_rules(
    ipc_code: str,
    data: dict[str, Any] | None = None,
    data_path: Path | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """根据给定的 IPC 分类号检索四张优审体系表中命中的规则与技术分支。"""
    if data is None:
        data = load_priority_data(data_path)

    normalized = normalize_ipc_codes([ipc_code], allow_full=True)
    if not normalized:
        return {
            "query": ipc_code,
            "normalized_ipc": "",
            "matched": False,
            "matching_rules": [],
            "matching_rule_count": 0,
            "message": "未识别到有效的 IPC 分类号。",
        }

    target = normalized[0]
    rules = data.get("rules") or []
    tables_by_id = {t.get("table_id"): t for t in data.get("table_summaries", []) if isinstance(t, dict) and t.get("table_id")}

    if "/" in target:
        # 完整号精确匹配
        matched_rules = [r for r in rules if rule_matches_full_ipc(r, target)]
        is_matched = bool(matched_rules)
    else:
        # 小类前缀检索相关规则
        matched_rules = [r for r in rules if (r.get("include_prefix") or "").startswith(target)]
        is_matched = False  # 小类不能直接算命中优审

    formatted_rules: list[dict[str, Any]] = []
    for r in matched_rules[:limit]:
        tid = r.get("table_id", "")
        tinfo = _table_info(tid, tables_by_id, r)
        formatted_rules.append(
            {
                "rule_id": r.get("rule_id", ""),
                "table_id": tid,
                "table_name": tinfo["title"],
                "publisher": tinfo["publisher"],
                "year": tinfo["year"],
                "row_title": r.get("row_title", ""),
                "technology_branch_name": r.get("technology_branch_name", ""),
                "keyword_summary": r.get("keyword_summary", ""),
                "raw_expression": r.get("raw_expression", ""),
                "include_prefix": r.get("include_prefix", ""),
                "exclude_prefixes": r.get("exclude_prefixes", []),
                "match_mode": r.get("match_mode", "exact"),
            }
        )

    return {
        "query": ipc_code,
        "normalized_ipc": target,
        "query_type": "full_ipc" if "/" in target else "subclass",
        "matched": is_matched,
        "matching_rule_count": len(matched_rules),
        "matching_rules": formatted_rules,
        "message": (
            f"完整分类号 {target} 命中 {len(matched_rules)} 条优审体系规则。"
            if is_matched
            else (
                f"小类 {target} 关联 {len(matched_rules)} 条规则（优审需提供具体组/小组号确认是否命中）。"
                if matched_rules
                else f"未在四张优审分类表中检索到 {target}。"
            )
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="国家知识产权局专利优先审查（优审）政策分类范围与法定条件核对工具。"
    )
    parser.add_argument(
        "-i",
        "--ipc",
        action="append",
        dest="ipc_list",
        help="待核对的完整 IPC 分类号（如 -i 'E02D 17/20' 或 -i 'G06N 3/08'）",
    )
    parser.add_argument(
        "positional_ipcs",
        nargs="*",
        help="位置参数传入的 IPC 分类号",
    )
    parser.add_argument(
        "--condition",
        action="append",
        type=int,
        dest="condition_ids",
        choices=[1, 2, 3, 4, 5, 6],
        help="指定核对的《优先审查管理办法》法定情形编号（1-6）",
    )
    parser.add_argument(
        "--list-conditions",
        action="store_true",
        help="列出全部 6 种法定优先审查情形及所需证据指引",
    )
    parser.add_argument(
        "--search",
        type=str,
        help="以特定 IPC 号检索优审分类表中对应的技术分支规则及原表出处",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=DEFAULT_PRIORITY_PATH,
        help="优审数据文件路径（默认读取 data/priority_review.json.gz）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="输出 JSON 格式结果（默认启用）",
    )

    args = parser.parse_args(argv)

    if args.list_conditions:
        print(json.dumps(STATUTORY_CONDITIONS, ensure_ascii=False, indent=2))
        return 0

    if args.search:
        search_res = search_priority_rules(args.search, data_path=args.data_path)
        print(json.dumps(search_res, ensure_ascii=False, indent=2))
        return 0 if search_res.get("normalized_ipc") else 1

    all_ipcs: list[str] = []
    if args.ipc_list:
        all_ipcs.extend(args.ipc_list)
    if args.positional_ipcs:
        all_ipcs.extend(args.positional_ipcs)

    if not all_ipcs and not sys.stdin.isatty():
        content = sys.stdin.read().strip()
        if content:
            all_ipcs.extend(extract_ipc_codes_from_text(content, allow_full=True))

    if not all_ipcs and not args.condition_ids:
        parser.error("请提供待核对的完整 IPC 分类号（如 -i 'E02D 17/20'）或法定情形编号（--condition 1），或使用 --list-conditions 查看指南。")

    result = check_priority_review(
        ipc_codes=all_ipcs,
        statutory_condition_ids=args.condition_ids,
        data_path=args.data_path,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("checked") else 1


if __name__ == "__main__":
    raise SystemExit(main())
