#!/usr/bin/env python3
"""列出或检索商标 45 个大类（尼斯分类）基础信息

用于第一轮大类初筛：提供 45 个大类的编号、名称、官方标题描述及类别注释。
支持按类号精确查询、关键词过滤及 JSON 格式输出。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class ClassEntry:
    class_code: str
    class_name: str
    description: str
    notes: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClassEntry:
        return cls(
            class_code=str(data.get("classCode", "")).strip(),
            class_name=str(data.get("className", "")).strip(),
            description=str(data.get("description", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
        )


def load_classes(data_dir: Path) -> list[ClassEntry]:
    classes_file = data_dir / "classes.json"
    if not classes_file.is_file():
        raise FileNotFoundError(f"未找到大类数据文件: {classes_file}")

    with classes_file.open("r", encoding="utf-8") as f:
        raw_list = json.load(f)

    return [ClassEntry.from_dict(item) for item in raw_list]


def filter_classes(
    classes: list[ClassEntry],
    class_code: Optional[str] = None,
    query: Optional[str] = None,
) -> list[ClassEntry]:
    results = classes

    if class_code:
        normalized_code = class_code.strip().zfill(2)
        results = [c for c in results if c.class_code == normalized_code]

    if query:
        q = query.strip().lower()
        results = [
            c
            for c in results
            if q in c.class_code.lower()
            or q in c.class_name.lower()
            or q in c.description.lower()
            or q in c.notes.lower()
        ]

    return results


def format_text(classes: list[ClassEntry], verbose: bool = False) -> str:
    if not classes:
        return "未找到匹配的大类。"

    lines: list[str] = []
    for c in classes:
        lines.append(f"【第 {c.class_code} 类】{c.class_name}")
        lines.append(f"  范围描述: {c.description}")
        if verbose and c.notes:
            lines.append(f"  官方注释: {c.notes}")
        lines.append("")
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="列出或检索商标 45 个大类（第一轮大类筛选）"
    )
    default_data_dir = Path(__file__).resolve().parent.parent / "data"

    parser.add_argument(
        "class_code",
        nargs="?",
        default=None,
        help="可选：指定大类编号（如 09 或 9）",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="关键词搜索（在大类名称、范围描述和注释中检索）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="数据目录路径（默认指向 Skill 内部 data/）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="显示详细官方注释信息",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出结果",
    )

    args = parser.parse_args()

    try:
        all_classes = load_classes(args.data_dir.resolve())
        filtered = filter_classes(
            all_classes,
            class_code=args.class_code,
            query=args.query,
        )

        if args.json:
            json_data = [asdict(c) for c in filtered]
            print(json.dumps(json_data, ensure_ascii=False, indent=2))
        else:
            print(format_text(filtered, verbose=args.verbose))
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
