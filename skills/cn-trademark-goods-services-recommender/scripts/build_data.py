#!/usr/bin/env python3
"""商标分类区分表数据构建与校验工具

用于从原始数据目录构建、验证并标准化商标分类数据包（包含 45 个大类、498 个类似群及明细项目）。
不依赖任何外部第三方库，仅使用 Python 3 标准库。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Set


@dataclass
class ValidationStats:
    class_count: int = 0
    group_count: int = 0
    detail_count: int = 0
    standard_item_count: int = 0
    nonstandard_item_count: int = 0
    total_items: int = 0
    note_count: int = 0
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []


def read_json_file(file_path: Path) -> Any:
    """读取并解析 JSON 文件"""
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_file(file_path: Path, data: Any) -> None:
    """以统一格式写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def validate_data_directory(source_dir: Path) -> tuple[bool, ValidationStats]:
    """完整校验数据目录结构的正确性与引用完整性"""
    stats = ValidationStats()
    classes_file = source_dir / "classes.json"
    groups_dir = source_dir / "groups"
    details_dir = source_dir / "details"

    if not classes_file.is_file():
        stats.errors.append(f"缺少主分类文件: {classes_file}")
        return False, stats

    if not groups_dir.is_dir():
        stats.errors.append(f"缺少类似群目录: {groups_dir}")
        return False, stats

    if not details_dir.is_dir():
        stats.errors.append(f"缺少详情目录: {details_dir}")
        return False, stats

    # 1. 校验 classes.json
    try:
        classes_data = read_json_file(classes_file)
    except Exception as e:
        stats.errors.append(f"解析 classes.json 失败: {e}")
        return False, stats

    if not isinstance(classes_data, list):
        stats.errors.append("classes.json 必须是数组结构")
        return False, stats

    stats.class_count = len(classes_data)
    if stats.class_count != 45:
        stats.warnings.append(f"大类总数不是 45，当前为 {stats.class_count}")

    class_codes: Set[str] = set()
    for item in classes_data:
        code = str(item.get("classCode", "")).strip()
        name = str(item.get("className", "")).strip()
        if not code or not name:
            stats.errors.append(f"大类缺少 classCode 或 className: {item}")
        class_codes.add(code)

    # 2. 校验 groups/
    all_group_codes: Set[str] = set()
    for class_code in sorted(class_codes):
        group_file = groups_dir / f"{class_code}.json"
        if not group_file.is_file():
            stats.errors.append(f"大类 {class_code} 缺少对应的群组文件 {group_file.name}")
            continue

        try:
            groups_data = read_json_file(group_file)
        except Exception as e:
            stats.errors.append(f"解析 {group_file.name} 失败: {e}")
            continue

        if not isinstance(groups_data, list):
            stats.errors.append(f"{group_file.name} 必须是数组结构")
            continue

        for group in groups_data:
            g_code = str(group.get("groupCode", "")).strip()
            g_name = str(group.get("groupName", "")).strip()
            g_class = str(group.get("classCode", "")).strip()

            if not g_code or not g_name:
                stats.errors.append(f"群组条目缺少 groupCode 或 groupName: {group}")
            if g_class != class_code:
                stats.warnings.append(f"群组 {g_code} 的 classCode ({g_class}) 与文件名不一致 ({class_code})")

            all_group_codes.add(g_code)

    stats.group_count = len(all_group_codes)

    # 3. 校验 details/
    detail_files = list(details_dir.glob("*.json"))
    stats.detail_count = len(detail_files)

    for detail_file in detail_files:
        g_code = detail_file.stem
        if g_code not in all_group_codes:
            stats.warnings.append(f"详情文件 {detail_file.name} 在群组列表中无对应条目")

        try:
            detail_data = read_json_file(detail_file)
        except Exception as e:
            stats.errors.append(f"解析 {detail_file.name} 失败: {e}")
            continue

        if not isinstance(detail_data, dict):
            stats.errors.append(f"{detail_file.name} 顶层必须是字典结构")
            continue

        notes = detail_data.get("notes", [])
        if isinstance(notes, list):
            stats.note_count += len(notes)

        # 统计规范商品/服务项
        sections = detail_data.get("sections", [])
        if isinstance(sections, list):
            for sec in sections:
                items = sec.get("items", [])
                if isinstance(items, list):
                    stats.standard_item_count += len(items)

        # 统计非规范商品/服务项
        nonstandards = detail_data.get("nonstandardItems", [])
        if isinstance(nonstandards, list):
            stats.nonstandard_item_count += len(nonstandards)

    stats.total_items = stats.standard_item_count + stats.nonstandard_item_count

    # 检查是否有群组未生成详情文件
    missing_details = all_group_codes - {f.stem for f in detail_files}
    if missing_details:
        stats.errors.append(f"以下群组缺少对应的详情文件: {sorted(missing_details)}")

    passed = len(stats.errors) == 0
    return passed, stats


def build_data(source_dir: Path, output_dir: Path) -> tuple[bool, ValidationStats]:
    """从源目录复制并规范化数据到目标目录"""
    passed, stats = validate_data_directory(source_dir)
    if not passed:
        return False, stats

    if source_dir.resolve() == output_dir.resolve():
        return True, stats

    output_dir.mkdir(parents=True, exist_ok=True)

    # 复制 manifest.json（如果存在）
    manifest_src = source_dir / "manifest.json"
    if manifest_src.is_file():
        shutil.copy2(manifest_src, output_dir / "manifest.json")

    # 复制 classes.json
    shutil.copy2(source_dir / "classes.json", output_dir / "classes.json")

    # 复制 groups/
    out_groups = output_dir / "groups"
    out_groups.mkdir(parents=True, exist_ok=True)
    for g_file in (source_dir / "groups").glob("*.json"):
        shutil.copy2(g_file, out_groups / g_file.name)

    # 复制 details/
    out_details = output_dir / "details"
    out_details.mkdir(parents=True, exist_ok=True)
    for d_file in (source_dir / "details").glob("*.json"):
        shutil.copy2(d_file, out_details / d_file.name)

    return True, stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="构建与校验商标分类数据集（尼斯分类/《类似商品和服务区分表》）"
    )
    default_data_dir = Path(__file__).resolve().parent.parent / "data"
    parser.add_argument(
        "--source",
        type=Path,
        default=default_data_dir,
        help="数据源目录路径（默认读取 Skill 目录下的 data/）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_data_dir,
        help="目标输出目录路径（默认写入/校验 Skill 目录下的 data/）",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="仅执行数据完整性校验，不执行文件复制",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出校验统计结果",
    )

    args = parser.parse_args()

    source_dir = args.source.resolve()
    output_dir = args.output.resolve()

    if args.validate_only:
        passed, stats = validate_data_directory(source_dir)
    else:
        passed, stats = build_data(source_dir, output_dir)

    if args.json:
        result = {
            "passed": passed,
            "source": str(source_dir),
            "output": str(output_dir) if not args.validate_only else None,
            "stats": asdict(stats),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status_text = "✓ 校验通过" if passed else "✗ 校验失败"
        print(f"数据校验状态: {status_text}")
        print(f"源目录: {source_dir}")
        if not args.validate_only and source_dir != output_dir:
            print(f"输出目录: {output_dir}")
        print("-" * 40)
        print(f"大类总数 (Classes):   {stats.class_count}")
        print(f"类似群总数 (Groups):  {stats.group_count}")
        print(f"详情文件数 (Details): {stats.detail_count}")
        print(f"规范商品项 (Standard): {stats.standard_item_count}")
        print(f"非规范项 (Nonstandard): {stats.nonstandard_item_count}")
        print(f"商品/服务项总数:      {stats.total_items}")
        print(f"审查注释条数:         {stats.note_count}")

        if stats.warnings:
            print(f"\n警告信息 ({len(stats.warnings)}条):")
            for w in stats.warnings[:10]:
                print(f"  [警告] {w}")
            if len(stats.warnings) > 10:
                print(f"  ... 另有 {len(stats.warnings) - 10} 条警告省略")

        if stats.errors:
            print(f"\n错误信息 ({len(stats.errors)}条):")
            for e in stats.errors:
                print(f"  [错误] {e}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
