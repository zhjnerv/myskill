from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_priority_review import (
    check_priority_review,
    load_priority_data,
    search_priority_rules,
)
from match_preexam import load_preexam_data, match_preexam, resolve_region
from normalize_ipc import (
    extract_ipc_codes_from_text,
    extract_subclass_from_full_ipc,
    load_subclass_definitions,
    normalize_ipc_code,
    normalize_ipc_codes,
)
from screen import screen_fast_track


class TestIpcNormalizer(unittest.TestCase):
    def test_normalize_subclass_and_full(self) -> None:
        self.assertEqual(normalize_ipc_code("g06v"), "G06V")
        self.assertEqual(normalize_ipc_code("G06F 16/00", allow_full=False), "G06F")
        self.assertEqual(normalize_ipc_code("G06F30/27", allow_full=True), "G06F 30/27")
        self.assertEqual(normalize_ipc_code("H01M10/0525", allow_full=True), "H01M 10/0525")
        self.assertIsNone(normalize_ipc_code("G06"))
        self.assertIsNone(normalize_ipc_code("invalid_text"))

    def test_extract_subclass_from_full(self) -> None:
        self.assertEqual(extract_subclass_from_full_ipc("G06F 30/27"), "G06F")
        self.assertEqual(extract_subclass_from_full_ipc("H01M 10/0525"), "H01M")
        self.assertEqual(extract_subclass_from_full_ipc("A01B"), "A01B")

    def test_extract_from_text(self) -> None:
        text = "本技术方案涉及 G06F 30/27 与 H01M 10/0525，也可参考 g06n。"
        extracted = extract_ipc_codes_from_text(text, allow_full=True)
        self.assertIn("G06F 30/27", extracted)
        self.assertIn("H01M 10/0525", extracted)
        self.assertIn("G06N", extracted)

    def test_load_definitions(self) -> None:
        defs = load_subclass_definitions()
        self.assertIn("G06F", defs)
        self.assertIn("zh", defs["G06F"])
        self.assertIn("en", defs["G06F"])

    def test_c01g_cleaned_and_length_bounded(self) -> None:
        defs = load_subclass_definitions()
        self.assertIn("C01G", defs)
        zh = defs["C01G"]["zh"]
        # 验证 C01G 的中文定义已被成功清洗，不再存在数百次重复拼接
        self.assertLess(len(zh), 600)
        self.assertFalse("碳的含氧酸盐入C01B25/16;碳的含氧酸盐入C01B25/16" in zh)


class TestMatchPreexam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preexam_data = load_preexam_data()

    def test_region_resolver_hangzhou(self) -> None:
        resolved = resolve_region(self.preexam_data, "浙江省", "杭州市")
        self.assertEqual(resolved.province, "浙江省")
        self.assertEqual(resolved.city, "杭州市")
        self.assertIn("hangzhou", resolved.candidate_center_ids)
        self.assertIn("zhejiang", resolved.candidate_center_ids)

    def test_region_alias_resolution(self) -> None:
        resolved = resolve_region(self.preexam_data, "浙江", "杭州")
        self.assertEqual(resolved.province, "浙江省")
        self.assertEqual(resolved.city, "杭州市")

    def test_special_area_zhongguancun(self) -> None:
        resolved = resolve_region(self.preexam_data, "北京市", None, special_area="中关村")
        self.assertEqual(resolved.province, "北京市")
        self.assertEqual(resolved.special_area, "中关村")
        self.assertIn("zhongguancun", resolved.candidate_center_ids)
        self.assertIn("beijing", resolved.candidate_center_ids)

    def test_match_preexam_hangzhou_g06n(self) -> None:
        result = match_preexam("浙江省", "杭州市", ipc_codes=["G06N"], data=self.preexam_data)
        self.assertTrue(result["checked"])
        self.assertTrue(result["matched"])
        self.assertGreaterEqual(result["matched_center_count"], 1)

    def test_match_preexam_unmatched(self) -> None:
        result = match_preexam("浙江省", "金华市", ipc_codes=["A63F"], data=self.preexam_data)
        self.assertTrue(result["checked"])
        self.assertFalse(result["matched"])
        self.assertEqual(result["matched_center_count"], 0)

    def test_matched_ipc_details_and_source_annotation(self) -> None:
        result = match_preexam(
            "浙江省",
            "杭州市",
            primary_ipc="G06N 3/08",
            secondary_ipcs=["G06V 10/40"],
            data=self.preexam_data,
        )
        self.assertTrue(result["matched"])
        # 验证返回候选中心包含 matched_ipc_details 并且标注了 source
        centers = result["candidate_centers"]
        hz_center = next(c for c in centers if c["center_id"] == "hangzhou")
        self.assertTrue(hz_center["prequalification_possible"])
        details = hz_center["matched_ipc_details"]
        sources = {item["subclass"]: item["source"] for item in details}
        self.assertIn("G06N", sources)
        self.assertEqual(sources["G06N"], "primary")

    def test_secondary_only_match_warning(self) -> None:
        # A01B 不在杭州中心或浙江中心受理范围，而 G06N 在受理范围
        result = match_preexam(
            "浙江省",
            "杭州市",
            primary_ipc="A01B 1/00",
            secondary_ipcs=["G06N 3/08"],
            data=self.preexam_data,
        )
        self.assertTrue(result["matched"])
        # 必须触发"仅次要 IPC 命中"的警示 warning
        warnings_str = " ".join(result["warnings"])
        self.assertIn("仅次要 IPC 命中", warnings_str)
        self.assertIn("主要 IPC 小类未落入候选保护中心预审范围", warnings_str)

    def test_multi_center_secondary_only_warning_not_masked(self) -> None:
        # 浙江省+杭州市，主 IPC 为 G16H 30/20（浙江中心受理，杭州中心不受理），次 IPC 为 G06T 7/11（两中心均受理）
        result = match_preexam(
            "浙江省",
            "杭州市",
            primary_ipc="G16H 30/20",
            secondary_ipcs=["G06T 7/11"],
            data=self.preexam_data,
        )
        self.assertTrue(result["matched"])
        centers = result["candidate_centers"]
        hz = next(c for c in centers if c["center_id"] == "hangzhou")
        zj = next(c for c in centers if c["center_id"] == "zhejiang")

        # 省级中心命中主 IPC
        self.assertTrue(zj["primary_matched"])
        self.assertNotIn("warning", zj)

        # 市级中心仅命中次要 IPC，必须具有 primary_matched=False、secondary_matched=True 及中心级 warning
        self.assertFalse(hz["primary_matched"])
        self.assertTrue(hz["secondary_matched"])
        self.assertIn("warning", hz)
        self.assertIn("杭州市知识产权保护中心仅命中次要 IPC 小类", hz["warning"])
        self.assertIn("存在退案风险", hz["warning"])

        # 顶层 warnings 必须包含该市级中心的专门提示，且不被省级中心命中主 IPC 掩盖
        warnings_str = " ".join(result["warnings"])
        self.assertIn("杭州市知识产权保护中心仅命中次要 IPC 小类", warnings_str)

    def test_guangdong_foshan_secondary_only_warning(self) -> None:
        # 广东省+佛山市，主 IPC 为 H01M 10/6556（广东中心受理，佛山中心不受理），次 IPC 为 F28F 3/08（佛山中心受理，广东中心不受理）
        result = match_preexam(
            "广东省",
            "佛山市",
            primary_ipc="H01M 10/6556",
            secondary_ipcs=["F28F 3/08"],
            data=self.preexam_data,
        )
        self.assertTrue(result["matched"])
        centers = result["candidate_centers"]
        fs = next(c for c in centers if c["center_id"] == "foshan")
        gd = next(c for c in centers if c["center_id"] == "guangdong")

        self.assertTrue(gd["primary_matched"])
        self.assertFalse(fs["primary_matched"])
        self.assertTrue(fs["secondary_matched"])
        self.assertIn("warning", fs)
        self.assertIn("佛山知识产权保护中心仅命中次要 IPC 小类", fs["warning"])
        self.assertIn("佛山知识产权保护中心仅命中次要 IPC 小类", " ".join(result["warnings"]))


class TestCheckPriorityReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.priority_data = load_priority_data()

    def test_exact_full_ipc_match(self) -> None:
        result = check_priority_review(["E02D 17/20"], data=self.priority_data)
        self.assertTrue(result["checked"])
        self.assertTrue(result["matched"])
        self.assertIn("E02D 17/20", result["matched_groups"])
        self.assertGreater(len(result["matched_sources"]), 0)

    def test_g06n_machine_learning_match(self) -> None:
        result = check_priority_review(["G06N 3/08"], data=self.priority_data)
        self.assertTrue(result["checked"])
        self.assertTrue(result["matched"])
        self.assertIn("G06N 3/08", result["matched_groups"])

    def test_subclass_requires_full_ipc(self) -> None:
        result = check_priority_review(["G06F"], data=self.priority_data)
        self.assertTrue(result["checked"])
        self.assertFalse(result["matched"])
        self.assertTrue(result["requires_full_ipc"])
        self.assertEqual(result["query_type"], "subclass")

    def test_search_rules(self) -> None:
        search_res = search_priority_rules("E02D 17/20", data=self.priority_data)
        self.assertTrue(search_res["matched"])
        self.assertGreaterEqual(search_res["matching_rule_count"], 1)
        self.assertTrue(any("保水开采技术" in r["technology_branch_name"] for r in search_res["matching_rules"]))

    def test_g06t_branches_accurate_no_irrelevant_quantum_or_lcd(self) -> None:
        result = check_priority_review(["G06T 7/11"], data=self.priority_data)
        self.assertTrue(result["checked"])
        self.assertTrue(result["matched"])
        self.assertGreater(len(result["matched_sources"]), 0)
        branches = result["matched_sources"][0]["technology_branches"]
        # 确保包含合法的相关分支
        self.assertTrue(any("计算机视觉" in b or "图像识别" in b or "智能芯片" in b for b in branches))
        # 确保不含由于 ID 冲突误绑的无关分支（量子模拟、Fast-LCD 显示、同态加密、差分隐私等）
        unwanted = ["量子模拟", "Fast-LCD 显示", "差分隐私", "同态加密", "超导量子处理器", "零信任网络"]
        for u in unwanted:
            self.assertFalse(any(u in b for b in branches), f"不应包含无关分支: {u}")

    def test_search_and_check_unmatched_exit_code_zero(self) -> None:
        import subprocess

        cli_script = SCRIPTS_DIR / "check_priority_review.py"
        # 1. --search 未命中时退出码为 0
        p_search = subprocess.run(
            [sys.executable, str(cli_script), "--search", "A63F 9/00"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p_search.returncode, 0)
        self.assertIn('"matched": false', p_search.stdout)

        # 2. -i 正常查询但未命中时退出码为 0
        p_check = subprocess.run(
            [sys.executable, str(cli_script), "-i", "A63F 9/00"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p_check.returncode, 0)
        self.assertIn('"matched": false', p_check.stdout)

        # 3. 参数无效（无有效 IPC）时退出码为 1
        p_invalid = subprocess.run(
            [sys.executable, str(cli_script), "--search", "invalid_ipc"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p_invalid.returncode, 1)


class TestScreenFastTrack(unittest.TestCase):
    def test_screen_both_matched(self) -> None:
        result = screen_fast_track("浙江省", "杭州市", primary_ipc="G06N 3/08")
        self.assertEqual(result["status"], "accelerated_matched")
        self.assertIn("preexam", result["accelerated_paths"])
        self.assertIn("priority_review", result["accelerated_paths"])
        self.assertTrue(result["preexam"]["matched"])
        self.assertTrue(result["priority_review"]["matched"])
        self.assertIn("G06N", result["ipc_definitions"])

    def test_screen_neither_matched(self) -> None:
        result = screen_fast_track("浙江省", "金华市", primary_ipc="A63F")
        self.assertEqual(result["status"], "not_matched")
        self.assertEqual(result["accelerated_paths"], [])
        self.assertFalse(result["preexam"]["matched"])
        self.assertFalse(result["priority_review"]["matched"])

    def test_screen_no_valid_ipc(self) -> None:
        result = screen_fast_track("浙江省", "杭州市", ipc_codes=["invalid_code"])
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["preexam"]["checked"])
        self.assertFalse(result["priority_review"]["checked"])

    def test_screen_multiple_secondary_ipcs_and_warning(self) -> None:
        result = screen_fast_track(
            province="浙江省",
            city="杭州市",
            primary_ipc="A01B 1/00",
            secondary_ipcs=["G06N 3/08", "G06V 10/40"],
        )
        self.assertEqual(result["status"], "accelerated_matched")
        self.assertTrue(result["preexam"]["matched"])
        warnings_text = " ".join(result["warnings"])
        self.assertIn("仅次要 IPC 命中", warnings_text)
        self.assertIn("主要 IPC 小类未落入候选保护中心预审范围", warnings_text)

    def test_screen_multi_center_secondary_warning(self) -> None:
        result = screen_fast_track(
            province="浙江省",
            city="杭州市",
            primary_ipc="G16H 30/20",
            secondary_ipcs=["G06T 7/11"],
        )
        self.assertEqual(result["status"], "accelerated_matched")
        self.assertIn("杭州市知识产权保护中心仅命中次要 IPC 小类", " ".join(result["warnings"]))
        hz = next(c for c in result["candidate_centers"] if c["center_id"] == "hangzhou")
        self.assertFalse(hz["primary_matched"])
        self.assertTrue(hz["secondary_matched"])
        self.assertIn("warning", hz)


if __name__ == "__main__":
    unittest.main()
