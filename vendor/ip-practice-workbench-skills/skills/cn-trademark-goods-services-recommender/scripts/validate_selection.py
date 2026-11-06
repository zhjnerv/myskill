#!/usr/bin/env python3
"""校验并去重商标选类结果（大类、类似群、商品/服务项）

用于在完成三轮推断后，对拟申报的类别、类似群与商品项进行严格一致性校验：
  1. 验证大类（01-45）与类似群对应关系；
  2. 验证商品/服务项是否真实存在于《类似商品和服务区分表》对应群组中；
  3. 自动补齐官方 6 位商品编码、项目类型（规范/非规范/带※项）及所属段落；
  4. 同群组内项目去重，标准化群组申报代码（两位的群组代码）；
  5. 输出格式化校验报告及合规的 JSON 数据结构，供后续导出模版使用。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class ValidatedItem:
    name: str
    code: str
    type: str  # "standard", "marked", "nonstandard"
    section: str = ""
    is_valid: bool = True
    error_message: str = ""


@dataclass
class ValidatedGroup:
    group_code: str
    group_name: str
    class_code: str
    normalized_group_code: str  # 两位群号（用于商标局网报，如 2114 -> 14）
    recommendation: str = "推荐"
    reason: str = ""
    protection_type: str = "核心推荐"
    items: list[ValidatedItem] = field(default_factory=list)
    invalid_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ValidatedClass:
    class_code: str
    class_name: str
    recommendation: str = "推荐"
    reason: str = ""
    protection_type: str = "核心推荐"
    groups: list[ValidatedGroup] = field(default_factory=list)


@dataclass
class ValidationReport:
    is_valid: bool
    total_classes: int
    total_groups: int
    valid_item_count: int
    invalid_item_count: int
    classes: list[ValidatedClass]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_class_code(code: Any) -> str:
    """标准化大类编号为两位字符串（如 '9' -> '09'）"""
    clean = str(code or "").strip()
    return clean.zfill(2) if clean.isdigit() else clean


def normalize_group_code_for_export(group_code: str, class_code: str) -> str:
    """计算商标局网报所需的类似群编号（通常为截去大类后的后两位）"""
    clean_group = str(group_code or "").strip()
    clean_class = str(class_code or "").strip()

    if clean_class and clean_group.startswith(clean_class):
        return clean_group[len(clean_class):].zfill(2)

    return clean_group[-2:].zfill(2) if len(clean_group) >= 2 else clean_group


class ClassificationDatabase:
    """轻量内存缓存数据库"""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.classes: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}  # group_code -> group info
        self.details: dict[str, dict[str, Any]] = {}  # group_code -> detail
        self._load_classes()

    def _load_classes(self) -> None:
        classes_file = self.data_dir / "classes.json"
        if not classes_file.is_file():
            raise FileNotFoundError(f"缺少 classes.json: {classes_file}")
        with classes_file.open("r", encoding="utf-8") as f:
            for item in json.load(f):
                code = normalize_class_code(item.get("classCode"))
                self.classes[code] = item

    def get_class(self, class_code: str) -> Optional[dict[str, Any]]:
        return self.classes.get(normalize_class_code(class_code))

    def get_group(self, group_code: str) -> Optional[dict[str, Any]]:
        g_code = str(group_code).strip()
        if g_code in self.groups:
            return self.groups[g_code]

        # 尝试推导大类并从对应 groups 文件中读取
        c_code = g_code[:2] if len(g_code) >= 2 else ""
        groups_file = self.data_dir / "groups" / f"{c_code}.json"
        if groups_file.is_file():
            with groups_file.open("r", encoding="utf-8") as f:
                for g in json.load(f):
                    self.groups[str(g.get("groupCode")).strip()] = g

        return self.groups.get(g_code)

    def get_group_detail(self, group_code: str) -> Optional[dict[str, Any]]:
        g_code = str(group_code).strip()
        if g_code in self.details:
            return self.details[g_code]

        detail_file = self.data_dir / "details" / f"{g_code}.json"
        if detail_file.is_file():
            with detail_file.open("r", encoding="utf-8") as f:
                self.details[g_code] = json.load(f)
                return self.details[g_code]
        return None


def validate_selection_data(
    raw_data: Any,
    db: ClassificationDatabase,
) -> ValidationReport:
    report = ValidationReport(
        is_valid=True,
        total_classes=0,
        total_groups=0,
        valid_item_count=0,
        invalid_item_count=0,
        classes=[],
        errors=[],
        warnings=[],
    )

    # 兼容两种输入格式：
    # 格式 A: {"classes": [...]} 或 直接为列表 [{"classCode": ...}]
    # 格式 B: 扁平列表 [{"classCode": "21", "groupCode": "2114", "name": "..."}]
    class_inputs: list[dict[str, Any]] = []

    if isinstance(raw_data, dict):
        class_inputs = raw_data.get("classes", [])
    elif isinstance(raw_data, list):
        if raw_data and "items" not in raw_data[0] and "groups" not in raw_data[0] and "name" in raw_data[0]:
            # 扁平列表转树状结构
            tree: dict[str, dict[str, list[dict[str, Any]]]] = {}
            for row in raw_data:
                c = normalize_class_code(row.get("classCode"))
                g = str(row.get("groupCode", "")).strip()
                tree.setdefault(c, {}).setdefault(g, []).append(row)

            for c, groups_dict in tree.items():
                c_obj: dict[str, Any] = {"classCode": c, "groups": []}
                for g, items in groups_dict.items():
                    c_obj["groups"].append({"groupCode": g, "items": items})
                class_inputs.append(c_obj)
        else:
            class_inputs = raw_data

    if not class_inputs:
        report.errors.append("未提供任何待校验的类别或商品数据")
        report.is_valid = False
        return report

    for c_raw in class_inputs:
        c_code = normalize_class_code(c_raw.get("classCode"))
        c_meta = db.get_class(c_code)
        if not c_meta:
            report.errors.append(f"大类编号非法或不存在于区分表中: '{c_code}'")
            report.is_valid = False
            continue

        c_name = c_meta.get("className", f"第{c_code}类")
        validated_class = ValidatedClass(
            class_code=c_code,
            class_name=c_name,
            recommendation=c_raw.get("recommendation", "推荐"),
            reason=c_raw.get("reason", ""),
            protection_type=c_raw.get("protectionType", "核心推荐"),
        )

        raw_groups = c_raw.get("groups", [])
        for g_raw in raw_groups:
            g_code = str(g_raw.get("groupCode", "")).strip()
            if len(g_code) <= 2:
                suggested_4digit = f"{c_code}{g_code.zfill(2)}"
                report.errors.append(
                    f"类似群编号 '{g_code}' 格式错误（在大类 {c_code} 下）：groupCode 必须使用 4 位完整类似群编号（如 '{suggested_4digit}'），请改用 4 位群号"
                )
                report.is_valid = False
                continue

            g_meta = db.get_group(g_code)
            if not g_meta:
                report.errors.append(f"类似群编号不存在: '{g_code}'（在大类 {c_code} 下），请改用 4 位群号")
                report.is_valid = False
                continue

            # 校验类似群是否属于该大类
            meta_class_code = normalize_class_code(g_meta.get("classCode"))
            if meta_class_code != c_code:
                report.errors.append(f"类似群 {g_code} 实际属于第 {meta_class_code} 类，不能归入第 {c_code} 类")
                report.is_valid = False
                continue

            g_name = g_meta.get("groupName", g_code)
            norm_g_code = normalize_group_code_for_export(g_code, c_code)

            validated_group = ValidatedGroup(
                group_code=g_code,
                group_name=g_name,
                class_code=c_code,
                normalized_group_code=norm_g_code,
                recommendation=g_raw.get("recommendation", "推荐"),
                reason=g_raw.get("reason", ""),
                protection_type=g_raw.get("protectionType", "核心推荐"),
            )

            # 读取群组详情中的所有合法项目
            detail_data = db.get_group_detail(g_code)
            items_by_name: dict[str, dict[str, Any]] = {}
            items_by_code: dict[str, list[dict[str, Any]]] = {}
            items_by_stripped_name: dict[str, dict[str, Any]] = {}

            if detail_data:
                for sec in detail_data.get("sections", []):
                    sec_label = str(sec.get("label", "")).strip()
                    for it in sec.get("items", []):
                        it_copy = dict(it)
                        it_copy["section"] = sec_label or it_copy.get("section", "")
                        raw_it_name = str(it.get("name", "")).strip()
                        name_key = raw_it_name.lower()
                        code_key = str(it.get("code", "")).strip()
                        if name_key:
                            items_by_name[name_key] = it_copy
                        if code_key:
                            items_by_code.setdefault(code_key, []).append(it_copy)
                        stripped_key = raw_it_name.rstrip("*＊").strip().lower()
                        if stripped_key and stripped_key not in items_by_stripped_name:
                            items_by_stripped_name[stripped_key] = it_copy

                for it in detail_data.get("nonstandardItems", []):
                    it_copy = dict(it)
                    it_copy["section"] = "非规范项目"
                    raw_it_name = str(it.get("name", "")).strip()
                    name_key = raw_it_name.lower()
                    code_key = str(it.get("code", "")).strip()
                    if name_key:
                        items_by_name[name_key] = it_copy
                    if code_key:
                        items_by_code.setdefault(code_key, []).append(it_copy)
                    stripped_key = raw_it_name.rstrip("*＊").strip().lower()
                    if stripped_key and stripped_key not in items_by_stripped_name:
                        items_by_stripped_name[stripped_key] = it_copy

            # 校验项目并去重
            seen_items: Set[Tuple[str, str]] = set()
            raw_items = g_raw.get("items", [])

            for it_raw in raw_items:
                raw_name = str(it_raw.get("name", "")).strip() if isinstance(it_raw, dict) else str(it_raw).strip()
                raw_code = str(it_raw.get("code", "")).strip() if isinstance(it_raw, dict) else ""

                if not raw_name and not raw_code:
                    continue

                matched_item: Optional[dict[str, Any]] = None

                # 1. 有 code 时以 code 为准查项目
                if raw_code and raw_code in items_by_code:
                    candidates = items_by_code[raw_code]
                    if raw_name:
                        clean_raw = raw_name.rstrip("*＊").strip().lower()
                        # 先在候选列表中查找精确匹配项
                        for cand in candidates:
                            cand_name = str(cand.get("name", "")).strip()
                            if cand_name.lower() == raw_name.lower():
                                matched_item = cand
                                break
                        # 若未精确匹配，尝试去星号匹配
                        if not matched_item:
                            for cand in candidates:
                                cand_name = str(cand.get("name", "")).strip()
                                if cand_name.rstrip("*＊").strip().lower() == clean_raw:
                                    matched_item = cand
                                    break
                        # 仅当 name 不属于该 code 下的任何官方名称时，才采用首条官方名称并发出 warning
                        if not matched_item:
                            matched_item = candidates[0]
                            official_name = matched_item.get("name", "")
                            report.warnings.append(
                                f"类似群 {g_code} 项目编码 {raw_code} 对应的官方名称为 '{official_name}'，与填写的名称 '{raw_name}' 不一致，已自动采用官方名称"
                            )
                    else:
                        # 仅提供 code 未提供 name，采用首条官方名称
                        matched_item = candidates[0]
                # 2. 无 code 或 code 未匹配上时，按名称精确匹配
                elif raw_name and raw_name.lower() in items_by_name:
                    matched_item = items_by_name[raw_name.lower()]
                # 3. 名称回退：支持去掉末尾 * 或 ＊ 后相等（如输入“茶”匹配“茶* 300037”、“奶粉”匹配“奶粉* 290192”）
                elif raw_name:
                    clean_raw = raw_name.rstrip("*＊").strip().lower()
                    if clean_raw in items_by_stripped_name:
                        matched_item = items_by_stripped_name[clean_raw]

                if matched_item:
                    matched_name = matched_item.get("name", raw_name)
                    matched_code = matched_item.get("code", raw_code)
                    final_type = matched_item.get("type", "standard")
                    final_sec = matched_item.get("section", "")

                    item_key = (matched_code, matched_name)
                    if item_key in seen_items:
                        # 重复项自动过滤
                        continue
                    seen_items.add(item_key)

                    validated_group.items.append(
                        ValidatedItem(
                            name=matched_name,
                            code=matched_code,
                            type=final_type,
                            section=final_sec,
                            is_valid=True,
                        )
                    )
                    report.valid_item_count += 1
                else:
                    validated_group.invalid_items.append(
                        {
                            "name": raw_name,
                            "code": raw_code,
                            "error": f"在类似群 {g_code} 中未找到该商品/服务项",
                        }
                    )
                    report.invalid_item_count += 1
                    report.warnings.append(
                        f"类似群 {g_code} 中的项目 '{raw_name}' ({raw_code}) 未在官方区分表中匹配成功"
                    )

            if len(validated_group.items) > 10:
                report.warnings.append(
                    f"类似群 {g_code} 选取的项目为 {len(validated_group.items)} 项，建议精简为 1~10 项核心代表项以聚焦保护范围"
                )

            validated_class.groups.append(validated_group)
            report.total_groups += 1

        # 大类累计申报项数超过 10 项时发出官费加收提醒
        class_total_items = sum(len(g.items) for g in validated_class.groups)
        if class_total_items > 10:
            excess = class_total_items - 10
            report.warnings.append(
                f"第 {c_code} 类申报项目累计为 {class_total_items} 项，超出基准 10 项限额 {excess} 项，商标局将逐项加收超项规费"
            )

        report.classes.append(validated_class)
        report.total_classes += 1

    if report.total_classes > 10:
        report.warnings.append(f"推荐大类总数为 {report.total_classes}，超过常规建议上限（10 个大类）")

    return report


def format_report_text(report: ValidationReport) -> str:
    lines: list[str] = [
        "========================================",
        "商标分类推荐校验结果",
        "========================================",
        f"校验状态: {'✓ 通过' if report.is_valid else '✗ 存在严重错误'}",
        f"大类总数: {report.total_classes} 类",
        f"类似群数: {report.total_groups} 个",
        f"合规项目: {report.valid_item_count} 项",
        f"未匹配项: {report.invalid_item_count} 项",
        "----------------------------------------",
    ]

    for c in report.classes:
        lines.append(f"【第 {c.class_code} 类】{c.class_name} [{c.recommendation} - {c.protection_type}]")
        if c.reason:
            lines.append(f"  理由: {c.reason}")
        for g in c.groups:
            lines.append(f"  └─ 类似群 {g.group_code}（申报码: {g.normalized_group_code}）{g.group_name}")
            for it in g.items:
                code_str = f"({it.code})" if it.code else ""
                lines.append(f"       • {it.name} {code_str} [{it.type}]")
            for inv in g.invalid_items:
                lines.append(f"       ⚠ 无法匹配: {inv.get('name')} {inv.get('code')}")

    if report.warnings:
        lines.append("\n[警告提醒]")
        for w in report.warnings:
            lines.append(f"  ⚠ {w}")

    if report.errors:
        lines.append("\n[错误详情]")
        for e in report.errors:
            lines.append(f"  ✗ {e}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="校验并去重商标选类结果（大类、类似群、商品/服务项）"
    )
    default_data_dir = Path(__file__).resolve().parent.parent / "data"

    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="输入文件路径（JSON 格式），或留空/指定 '-' 从标准输入读取",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出校验规范化后的 JSON 文件路径",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="区分表数据目录路径（默认指向 Skill 内部 data/）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出校验报告",
    )

    args = parser.parse_args()

    # 读取输入
    try:
        if args.input == "-":
            raw_content = sys.stdin.read()
        else:
            in_path = Path(args.input)
            if not in_path.is_file():
                print(f"错误: 输入文件不存在: {in_path}", file=sys.stderr)
                return 1
            raw_content = in_path.read_text(encoding="utf-8")

        raw_data = json.loads(raw_content)
    except Exception as e:
        print(f"错误: 读取或解析输入 JSON 失败: {e}", file=sys.stderr)
        return 1

    try:
        db = ClassificationDatabase(args.data_dir.resolve())
        report = validate_selection_data(raw_data, db)

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as f:
                json.dump(asdict(report), f, ensure_ascii=False, indent=2)

        if args.json:
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            print(format_report_text(report))

        return 0 if report.is_valid else 1
    except Exception as e:
        print(f"校验执行异常: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
