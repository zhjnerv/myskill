#!/usr/bin/env python3
"""列出或检索指定大类下的类似群（第二轮类似群筛选）

用于第二轮类似群筛选：输入第一轮选中的一个或多个大类，输出其包含的所有类似群编号与名称。
支持多大类批量查询、群组名称关键词过滤及 JSON 格式输出。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class GroupEntry:
    group_code: str
    group_name: str
    class_code: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupEntry:
        return cls(
            group_code=str(data.get("groupCode", "")).strip(),
            group_name=str(data.get("groupName", "")).strip(),
            class_code=str(data.get("classCode", "")).strip(),
        )


def load_groups_for_classes(
    data_dir: Path,
    class_codes: list[str],
) -> list[GroupEntry]:
    groups_dir = data_dir / "groups"
    if not groups_dir.is_dir():
        raise FileNotFoundError(f"未找到类似群目录: {groups_dir}")

    results: list[GroupEntry] = []
    for raw_code in class_codes:
        normalized_code = raw_code.strip().zfill(2)
        group_file = groups_dir / f"{normalized_code}.json"
        if not group_file.is_file():
            continue

        with group_file.open("r", encoding="utf-8") as f:
            raw_list = json.load(f)

        for item in raw_list:
            results.append(GroupEntry.from_dict(item))

    return results


def filter_groups(
    groups: list[GroupEntry],
    query: Optional[str] = None,
) -> list[GroupEntry]:
    if not query:
        return groups

    q = query.strip().lower()
    return [
        g
        for g in groups
        if q in g.group_code.lower() or q in g.group_name.lower()
    ]


def format_text(groups: list[GroupEntry]) -> str:
    if not groups:
        return "未找到匹配的类似群。"

    lines: list[str] = []
    current_class = ""
    for g in groups:
        if g.class_code != current_class:
            current_class = g.class_code
            if lines:
                lines.append("")
            lines.append(f"--- 第 {current_class} 类 ---")
        lines.append(f"  {g.group_code} {g.group_name}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="列出或检索指定大类下的类似群（第二轮类似群筛选）"
    )
    default_data_dir = Path(__file__).resolve().parent.parent / "data"

    parser.add_argument(
        "class_codes",
        nargs="*",
        default=[],
        help="大类编号列表（如 09 35 42）",
    )
    parser.add_argument(
        "-c",
        "--classes",
        nargs="+",
        dest="flag_classes",
        default=[],
        help="大类编号列表（如 -c 09 35）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="列出全部 45 个大类的所有类似群",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="关键词过滤（在类似群编号和群名中匹配）",
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

    classes_to_query = list(args.class_codes) + list(args.flag_classes)

    if args.all:
        classes_to_query = [str(i).zfill(2) for i in range(1, 46)]
    elif not classes_to_query:
        # 如果未提供大类，提示用法
        parser.print_help(sys.stderr)
        print("\n提示: 请提供至少一个大类编号（如 '09'），或指定 --all 参数", file=sys.stderr)
        return 1

    try:
        groups = load_groups_for_classes(args.data_dir.resolve(), classes_to_query)
        filtered = filter_groups(groups, query=args.query)

        if args.json:
            json_data = [asdict(g) for g in filtered]
            print(json.dumps(json_data, ensure_ascii=False, indent=2))
        else:
            print(format_text(filtered))
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
