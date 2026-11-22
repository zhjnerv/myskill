#!/usr/bin/env python3
"""商标选类推荐引擎单元测试套件

基于 Python 标准库 unittest，测试各个独立脚本的核心逻辑与全流程链路。
测试覆盖：
  - 数据校验与构建 (build_data)
  - 大类检索与过滤 (list_classes)
  - 类似群检索 (list_groups)
  - 商品明细与审查注 (list_items)
  - 跨类全局检索 (search_items)
  - 选类结果合法性校验与去重 (validate_selection)
  - 商标局申报模版生成 (export_selection: XLSX & CSV)
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# 定位 Skill 根目录与相关模块
SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
DATA_DIR = SKILL_ROOT / "data"

import sys
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_data
import export_selection
import list_classes
import list_groups
import list_items
import search_items
import validate_selection


class TestDataValidation(unittest.TestCase):
    """测试数据集完整性"""

    def test_data_integrity(self) -> None:
        passed, stats = build_data.validate_data_directory(DATA_DIR)
        self.assertTrue(passed, f"数据校验失败: {stats.errors}")
        self.assertEqual(stats.class_count, 45)
        self.assertEqual(stats.group_count, 498)
        self.assertEqual(stats.detail_count, 498)
        self.assertGreater(stats.total_items, 30000)
        self.assertGreater(stats.note_count, 1000)


class TestListClasses(unittest.TestCase):
    """测试第一轮大类查询与检索"""

    def setUp(self) -> None:
        self.classes = list_classes.load_classes(DATA_DIR)

    def test_load_all_classes(self) -> None:
        self.assertEqual(len(self.classes), 45)

    def test_filter_by_code(self) -> None:
        # 支持 "09" 与 "9"
        res1 = list_classes.filter_classes(self.classes, class_code="09")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0].class_code, "09")
        self.assertIn("科学仪器", res1[0].class_name)

        res2 = list_classes.filter_classes(self.classes, class_code="9")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0].class_code, "09")

    def test_filter_by_query(self) -> None:
        res = list_classes.filter_classes(self.classes, query="软件")
        codes = {c.class_code for c in res}
        self.assertIn("09", codes)  # 09类包含软件
        self.assertIn("42", codes)  # 42类包含软件设计


class TestListGroups(unittest.TestCase):
    """测试第二轮类似群查询"""

    def test_load_groups_for_single_class(self) -> None:
        groups_09 = list_groups.load_groups_for_classes(DATA_DIR, ["09"])
        self.assertGreater(len(groups_09), 10)
        group_codes = {g.group_code for g in groups_09}
        self.assertIn("0901", group_codes)
        self.assertIn("0908", group_codes)

    def test_load_groups_for_multi_classes(self) -> None:
        groups = list_groups.load_groups_for_classes(DATA_DIR, ["09", "21"])
        classes_found = {g.class_code for g in groups}
        self.assertEqual(classes_found, {"09", "21"})

    def test_filter_groups_by_query(self) -> None:
        groups_21 = list_groups.load_groups_for_classes(DATA_DIR, ["21"])
        filtered = list_groups.filter_groups(groups_21, query="动植物")
        self.assertTrue(any(g.group_code == "2114" for g in filtered))


class TestListItems(unittest.TestCase):
    """测试第三轮商品/服务项查询"""

    def test_load_group_detail(self) -> None:
        detail = list_items.load_group_detail(DATA_DIR, "0901")
        self.assertIsNotNone(detail)
        self.assertEqual(detail.get("groupCode"), "0901")
        self.assertGreater(len(detail.get("notes", [])), 0)

    def test_filter_items(self) -> None:
        detail = list_items.load_group_detail(DATA_DIR, "0901")
        items, notes = list_items.get_items_from_detail(detail, query="计算机")
        self.assertGreater(len(items), 0)
        names = {it.name for it in items}
        self.assertIn("计算机", names)

    def test_nonstandard_items(self) -> None:
        detail = list_items.load_group_detail(DATA_DIR, "2114")
        items, _ = list_items.get_items_from_detail(detail, query="喂食器")
        names = {it.name for it in items}
        self.assertIn("宠物自动喂食器", names)


class TestSearchItems(unittest.TestCase):
    """测试全局跨类别检索"""

    def setUp(self) -> None:
        self.entities = search_items.load_all_search_entities(DATA_DIR)

    def test_search_feeder(self) -> None:
        results = search_items.execute_search(self.entities, query="喂食器", limit=20)
        self.assertGreater(len(results), 0)
        names = {r.name for r in results}
        self.assertTrue(any("喂食器" in n for n in names))
        # 命中 21 类类似群 2114
        self.assertTrue(any(r.class_code == "21" and r.group_code == "2114" for r in results))

    def test_search_code_prefix(self) -> None:
        results = search_items.execute_search(self.entities, query="0901", limit=10)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0].code, "0901")
        self.assertEqual(results[0].type, "group")

    def test_search_any_mode(self) -> None:
        results = search_items.execute_search(
            self.entities,
            query=["加奶", "茶饮料"],
            class_filter=["30"],
            match_any=True,
            limit=10,
        )
        self.assertGreater(len(results), 0)
        names = {r.name for r in results}
        self.assertIn("加奶的茶饮料", names)


class TestValidateSelection(unittest.TestCase):
    """测试推荐结果校验与去重"""

    def setUp(self) -> None:
        self.db = validate_selection.ClassificationDatabase(DATA_DIR)

    def test_valid_selection_hydration(self) -> None:
        sample_input = {
            "classes": [
                {
                    "classCode": "21",
                    "recommendation": "强推荐",
                    "reason": "宠物喂食器具",
                    "protectionType": "核心推荐",
                    "groups": [
                        {
                            "groupCode": "2114",
                            "recommendation": "强推荐",
                            "reason": "喂食器",
                            "protectionType": "核心推荐",
                            "items": [
                                {"name": "宠物自动喂食器"},
                                {"name": "宠物自动喂食器"},  # 重复项
                                {"name": "小动物喂食器"},
                            ],
                        }
                    ],
                }
            ]
        }

        report = validate_selection.validate_selection_data(sample_input, self.db)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.total_classes, 1)
        self.assertEqual(report.total_groups, 1)
        # 重复项自动去重：2114 下应有 2 项
        self.assertEqual(len(report.classes[0].groups[0].items), 2)
        # 类似群申报码应标准化为两位 "14"
        self.assertEqual(report.classes[0].groups[0].normalized_group_code, "14")

    def test_star_item_fallback(self) -> None:
        sample = {
            "classes": [
                {
                    "classCode": "30",
                    "groups": [
                        {
                            "groupCode": "3002",
                            "items": [{"name": "茶"}],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample, self.db)
        self.assertTrue(report.is_valid)
        item = report.classes[0].groups[0].items[0]
        self.assertEqual(item.name, "茶*")
        self.assertEqual(item.code, "300037")

    def test_code_priority_and_name_mismatch_warning(self) -> None:
        sample = {
            "classes": [
                {
                    "classCode": "30",
                    "groups": [
                        {
                            "groupCode": "3002",
                            "items": [{"name": "特种花茶", "code": "300037"}],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample, self.db)
        self.assertTrue(report.is_valid)
        item = report.classes[0].groups[0].items[0]
        self.assertEqual(item.name, "茶*")
        self.assertEqual(item.code, "300037")
        self.assertTrue(any("不一致" in w for w in report.warnings))

    def test_two_digit_group_code_error(self) -> None:
        sample = {
            "classes": [
                {
                    "classCode": "21",
                    "groups": [
                        {
                            "groupCode": "14",
                            "items": [{"name": "小动物喂食器"}],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample, self.db)
        self.assertFalse(report.is_valid)
        self.assertTrue(any("请改用 4 位群号" in e for e in report.errors))

    def test_class_fee_warning_over_ten_items(self) -> None:
        real_items = [
            "茶*", "昆布茶", "红茶", "绿茶", "乌龙茶",
            "黄茶", "黑茶", "白茶", "茉莉花茶", "铁观音茶",
            "冰茶（茶饮料）", "茶饮料",
        ]
        sample = {
            "classes": [
                {
                    "classCode": "30",
                    "groups": [
                        {
                            "groupCode": "3002",
                            "items": [{"name": n} for n in real_items],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample, self.db)
        self.assertTrue(report.is_valid)
        self.assertTrue(any("超出基准 10 项限额 2 项" in w for w in report.warnings))
        self.assertTrue(any("建议精简为 1~10 项" in w for w in report.warnings))

    def test_invalid_item_detection(self) -> None:
        sample_input = {
            "classes": [
                {
                    "classCode": "09",
                    "groups": [
                        {
                            "groupCode": "0901",
                            "items": [
                                {"name": "计算机"},
                                {"name": "虚构的不存在的宇宙航天飞船001"},
                            ],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample_input, self.db)
        self.assertEqual(report.valid_item_count, 1)
        self.assertEqual(report.invalid_item_count, 1)
        self.assertEqual(len(report.classes[0].groups[0].invalid_items), 1)

    def test_multi_name_same_code_no_warning_and_both_retained(self) -> None:
        """4101 中 410017 对应教学/教育/培训，同时选择教育与培训应零警告通过且两项均保留"""
        sample_input = {
            "classes": [
                {
                    "classCode": "41",
                    "groups": [
                        {
                            "groupCode": "4101",
                            "items": [
                                {"name": "教育", "code": "410017"},
                                {"name": "培训", "code": "410017"},
                            ],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample_input, self.db)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.warnings, [])
        self.assertEqual(report.errors, [])
        items = report.classes[0].groups[0].items
        self.assertEqual(len(items), 2)
        item_pairs = [(it.name, it.code) for it in items]
        self.assertEqual(item_pairs, [("教育", "410017"), ("培训", "410017")])

    def test_same_code_same_name_deduplication(self) -> None:
        """同一编码完全相同的 (code, name) 重复项应被自动去重"""
        sample_input = {
            "classes": [
                {
                    "classCode": "41",
                    "groups": [
                        {
                            "groupCode": "4101",
                            "items": [
                                {"name": "教育", "code": "410017"},
                                {"name": "教育", "code": "410017"},
                            ],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample_input, self.db)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.warnings, [])
        items = report.classes[0].groups[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "教育")
        self.assertEqual(items[0].code, "410017")

    def test_same_code_exact_name_match_no_warning(self) -> None:
        """3501 中 350039 对应广告与广告宣传，选择非末项'广告'应零警告通过且保留'广告'"""
        sample_input = {
            "classes": [
                {
                    "classCode": "35",
                    "groups": [
                        {
                            "groupCode": "3501",
                            "items": [
                                {"name": "广告", "code": "350039"},
                            ],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample_input, self.db)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.warnings, [])
        items = report.classes[0].groups[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "广告")
        self.assertEqual(items[0].code, "350039")


    def test_same_code_invalid_name_triggers_warning_and_correction(self) -> None:
        """输入错误名称如 {"name": "随便写", "code": "350039"} 仍触发 warning 并修正为首条官方名称"""
        sample_input = {
            "classes": [
                {
                    "classCode": "35",
                    "groups": [
                        {
                            "groupCode": "3501",
                            "items": [
                                {"name": "随便写", "code": "350039"},
                            ],
                        }
                    ],
                }
            ]
        }
        report = validate_selection.validate_selection_data(sample_input, self.db)
        self.assertTrue(report.is_valid)
        self.assertTrue(any("不一致" in w and "随便写" in w for w in report.warnings))
        items = report.classes[0].groups[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "广告")
        self.assertEqual(items[0].code, "350039")



class TestExportSelection(unittest.TestCase):
    """测试申报表格导出 (XLSX 与 CSV)"""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.sample_data = {
            "classes": [
                {
                    "classCode": "09",
                    "groups": [
                        {
                            "groupCode": "0901",
                            "normalized_group_code": "01",
                            "items": [{"name": "计算机"}, {"name": "已录制的计算机程序"}],
                        }
                    ],
                },
                {
                    "classCode": "21",
                    "groups": [
                        {
                            "groupCode": "2114",
                            "normalized_group_code": "14",
                            "items": [{"name": "宠物自动喂食器"}],
                        }
                    ],
                },
            ]
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_export_csv(self) -> None:
        csv_path = Path(self.test_dir) / "test.csv"
        rows = export_selection.extract_rows_from_selection(self.sample_data)
        export_selection.export_to_csv(rows, output_path=csv_path)

        self.assertTrue(csv_path.is_file())
        raw_bytes = csv_path.read_bytes()
        # 验证 UTF-8 BOM 前缀
        self.assertTrue(raw_bytes.startswith(b"\xef\xbb\xbf"))

        content = raw_bytes.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        lines = list(reader)
        # 表头
        self.assertEqual(lines[0], export_selection.EXPORT_HEADERS)
        # 第 1 行: 09 类
        self.assertEqual(lines[1], ["1", "09", "01", "计算机"])
        self.assertEqual(lines[2], ["2", "09", "01", "已录制的计算机程序"])
        # 类间空行
        self.assertEqual(lines[3], [])
        # 第 21 类
        self.assertEqual(lines[4], ["3", "21", "14", "宠物自动喂食器"])

    def test_export_xlsx(self) -> None:
        xlsx_path = Path(self.test_dir) / "test.xlsx"
        rows = export_selection.extract_rows_from_selection(self.sample_data)
        export_selection.export_to_xlsx(rows, output_path=xlsx_path)

        self.assertTrue(xlsx_path.is_file())
        with zipfile.ZipFile(xlsx_path, "r") as zf:
            names = zf.namelist()
            self.assertIn("xl/worksheets/sheet1.xml", names)
            self.assertIn("xl/styles.xml", names)
            self.assertIn("xl/workbook.xml", names)

            # 校验 XML 合法性
            sheet_xml = zf.read("xl/worksheets/sheet1.xml")
            root = ET.fromstring(sheet_xml)
            self.assertIsNotNone(root)

            styles_xml = zf.read("xl/styles.xml")
            styles_root = ET.fromstring(styles_xml)
            self.assertIsNotNone(styles_root)


if __name__ == "__main__":
    unittest.main()
