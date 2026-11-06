#!/usr/bin/env python3
"""列出或检索指定类似群下的具体商品与服务项（第三轮商品推荐）

用于第三轮商品/服务项选择：输入类似群编号（如 0901），输出该群组下的规范商品项（带 6 位编码）、
非规范项目、分段及官方审查注释（含跨类交叉检索提醒）。
支持关键词匹配、类型过滤（规范/非规范）、数量限制及 JSON 格式输出。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class ItemEntry:
    name: str
    code: str
    type: str  # standard, marked, nonstandard
    section: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_section: str = "") -> ItemEntry:
        return cls(
            name=str(data.get("name", "")).strip(),
            code=str(data.get("code", "")).strip(),
            type=str(data.get("type", "standard")).strip(),
            section=str(data.get("section", default_section)).strip(),
        )


@dataclass
class GroupDetailResult:
    group_code: str
    group_name: str
    class_code: str
    notes: list[str]
    total_count: int
    items: list[ItemEntry]


def load_group_detail(data_dir: Path, group_code: str) -> Optional[dict[str, Any]]:
    normalized_code = group_code.strip()
    # 如果用户输入了如 "901"，尝试 pad 为 "0901"
    if len(normalized_code) == 3:
        normalized_code = "0" + normalized_code

    detail_file = data_dir / "details" / f"{normalized_code}.json"
    if not detail_file.is_file():
        return None

    with detail_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_items_from_detail(
    detail_data: dict[str, Any],
    item_type: str = "all",
    query: Optional[str] = None,
    limit: Optional[int] = None,
) -> tuple[list[ItemEntry], list[str]]:
    notes: list[str] = [str(n).strip() for n in detail_data.get("notes", [])]
    all_items: list[ItemEntry] = []

    # 1. 规范项 (sections)
    if item_type in ("all", "standard", "marked"):
        for section in detail_data.get("sections", []):
            sec_label = str(section.get("label", "")).strip()
            for it in section.get("items", []):
                entry = ItemEntry.from_dict(it, default_section=sec_label)
                if item_type == "marked" and entry.type != "marked":
                    continue
                all_items.append(entry)

    # 2. 非规范项 (nonstandardItems)
    if item_type in ("all", "nonstandard"):
        for it in detail_data.get("nonstandardItems", []):
            entry = ItemEntry.from_dict(it, default_section="非规范项目")
            all_items.append(entry)

    # 关键词过滤
    if query:
        q = query.strip().lower()
        all_items = [
            it
            for it in all_items
            if q in it.name.lower() or (it.code and q in it.code.lower())
        ]

    total_matched = len(all_items)
    if limit and limit > 0:
        all_items = all_items[:limit]

    return all_items, notes


def format_text(
    group_code: str,
    group_name: str,
    class_code: str,
    notes: list[str],
    items: list[ItemEntry],
    show_notes: bool = True,
) -> str:
    lines: list[str] = [
        f"【类似群 {group_code} {group_name}（第 {class_code} 类）】",
    ]

    if show_notes and notes:
        lines.append("\n[审查注释与交叉检索]")
        for n in notes:
            lines.append(f"  • {n}")

    lines.append(f"\n[商品/服务候选项目] (共 {len(items)} 项):")
    if not items:
        lines.append("  (无匹配项目)")
    else:
        for it in items:
            type_tag = " [※]" if it.type == "marked" else (" [非规范]" if it.type == "nonstandard" else "")
            code_tag = f"({it.code})" if it.code else ""
            sec_tag = f"<{it.section}> " if it.section and it.section != "非规范项目" else ""
            lines.append(f"  {it.name} {code_tag}{type_tag} {sec_tag}".strip())

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="列出或检索指定类似群下的具体商品与服务项（第三轮商品推荐）"
    )
    default_data_dir = Path(__file__).resolve().parent.parent / "data"

    parser.add_argument(
        "group_code",
        type=str,
        help="类似群编号（如 0901 或 3501）",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="关键词过滤商品名称或商品编码",
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=["all", "standard", "marked", "nonstandard"],
        default="all",
        help="过滤项目类型：all(全部), standard(官方规范项), marked(带星号项), nonstandard(非规范可接受项)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="返回项目最大条数（默认不限）",
    )
    parser.add_argument(
        "--no-notes",
        action="store_true",
        help="不显示官方审查注释",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="数据目录路径（默认指向 Skill 内部 data/）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出结果",
    )

    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    detail_data = load_group_detail(data_dir, args.group_code)

    if not detail_data:
        print(f"错误: 未找到类似群 {args.group_code} 的详情数据文件", file=sys.stderr)
        return 1

    group_code = str(detail_data.get("groupCode", args.group_code)).strip()
    group_name = str(detail_data.get("groupName", "")).strip()
    class_code = str(detail_data.get("classCode", "")).strip()

    items, notes = get_items_from_detail(
        detail_data,
        item_type=args.type,
        query=args.query,
        limit=args.limit,
    )

    if args.json:
        result = GroupDetailResult(
            group_code=group_code,
            group_name=group_name,
            class_code=class_code,
            notes=notes if not args.no_notes else [],
            total_count=len(items),
            items=items,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(
            format_text(
                group_code=group_code,
                group_name=group_name,
                class_code=class_code,
                notes=notes,
                items=items,
                show_notes=not args.no_notes,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
