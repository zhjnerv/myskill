"""CN v2 形式/程序原始检查器回归测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/cn-patent-formalities-reviewer/scripts/check_formalities_cn.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("cn_formalities_v2", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = load_checker()


def complete_manifest() -> dict:
    return {
        "schema_version": "cn-patent-application-manifest/v2",
        "application_scope": "direct_cn_invention_application",
        "application_type": "invention",
        "filing_medium": "electronic",
        "documents": {
            "request": {"status": "provided", "content": "请求书"},
            "specification": {"status": "provided", "content": "技术领域\n本发明涉及数据处理。\n背景技术\n现有技术存在延迟。\n发明内容\n提供处理装置。\n具体实施方式\n装置包括控制器。"},
            "claims": {"status": "provided", "content": "1. 一种数据处理装置。"},
            "abstract": {"status": "provided", "content": "一种数据处理装置及其用途。"},
            "drawings": {"status": "confirmed_absent"},
        },
        "titles": {"request": "一种数据处理装置", "specification": "一种数据处理装置", "abstract": "一种数据处理装置"},
        "request_fields": {"applicant": "甲公司", "inventor": "张三", "address": "北京市"},
        "execution": {"language": "zh-CN", "signature_status": "unknown"},
        "abstract_figure": {"applicability": "not_applicable", "evidence": "未提供附图"},
        "sequence_listing": {"applicability": "not_applicable", "evidence": "未涉及核苷酸或氨基酸序列"},
        "biological_material_deposit": {"applicability": "not_applicable", "evidence": "无保藏生物材料"},
        "genetic_resource_statement": {"applicability": "not_applicable", "evidence": "未依赖遗传资源"},
        "priority_documents": {"applicability": "not_applicable", "evidence": "未主张优先权"},
        "article_24_proof": {"applicability": "not_applicable", "evidence": "未主张第二十四条公开例外"},
        "divisional_documents": {"applicability": "not_applicable", "evidence": "不是分案申请"},
        "substantive_examination_request": {"applicability": "applicable", "status": "provided", "evidence": "已提供实审请求", "document_ids": []},
    }


def write_json(path: Path, payload: dict, bom: bool = False) -> None:
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class FormalitiesCheckerV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_checker(self, manifest: dict, bom: bool = False) -> tuple[int, Path]:
        manifest_path = self.path / "manifest.json"
        report_path = self.path / "report.json"
        write_json(manifest_path, manifest, bom)
        return checker.main(["--manifest", str(manifest_path), "--output", str(report_path)]), report_path

    def test_real_utf8_input_produces_exact_v2_raw_report_and_17_checks(self):
        exit_code, report_path = self.run_checker(complete_manifest())
        self.assertEqual(exit_code, 0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], checker.SCHEMA_VERSION)
        self.assertEqual(report["legal_effect"], "ADVISORY_ONLY")
        self.assertEqual(set(report), {"schema_version", "jurisdiction", "review_type", "legal_effect", "report_id", "input_artifacts", "rule_sources", "tool_identity", "evidence_binding", "resource_limits", "resource_usage", "checks_performed", "findings", "gaps"})
        self.assertEqual(len(report["checks_performed"]), 17)
        self.assertEqual({item["rule_id"] for item in report["checks_performed"]}, set(checker.FORMALITY_RULES))
        self.assertEqual(len({item["check_id"] for item in report["checks_performed"]}), 17)
        self.assertEqual(report["resource_limits"]["failure_exit_code"], 4)
        self.assertEqual(report["tool_identity"]["contract_schema_version"], "cn-patent-review-contract/v2")

    def test_all_findings_and_gaps_have_unique_existing_check_ids_and_exact_fields(self):
        manifest = complete_manifest()
        manifest["documents"]["request"] = {"status": "confirmed_absent"}
        del manifest["sequence_listing"]
        exit_code, report_path = self.run_checker(manifest)
        self.assertEqual(exit_code, 2)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        check_ids = {item["check_id"] for item in report["checks_performed"]}
        self.assertTrue(report["findings"])
        self.assertTrue(report["gaps"])
        for finding in report["findings"]:
            self.assertEqual(set(finding), {"finding_id", "check_id", "rule_id", "target_id", "location", "status", "evidence", "problem", "remedy", "manual_review_required"})
            self.assertIn(finding["check_id"], check_ids)
        for gap in report["gaps"]:
            self.assertEqual(set(gap), {"gap_id", "check_id", "rule_id", "target_id", "category", "reason", "evidence", "blocks_assessment"})
            self.assertIn(gap["check_id"], check_ids)

    def test_unknown_core_document_becomes_gap_but_confirmed_absence_is_finding(self):
        unknown = complete_manifest()
        unknown["documents"]["request"] = {"status": "unknown"}
        code, path = self.run_checker(unknown)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(any(item["status"] == "DETERMINISTIC_FAIL" for item in report["findings"]))
        self.assertTrue(any(item["rule_id"] == "form_core_documents_and_application_type" for item in report["gaps"]))

        absent = complete_manifest()
        absent["documents"]["request"] = {"status": "confirmed_absent"}
        code, path = self.run_checker(absent)
        self.assertEqual(code, 2)
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(any(item["status"] == "DETERMINISTIC_FAIL" and item["rule_id"] == "form_core_documents_and_application_type" for item in report["findings"]))

    def test_unreadable_path_is_a_structured_gap_not_a_missing_document_finding(self):
        manifest = complete_manifest()
        manifest["documents"]["request"] = {"status": "provided", "path": "missing-request.txt"}
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(any(item["rule_id"] == "form_core_documents_and_application_type" and item["category"] == "INPUT_UNAVAILABLE" for item in report["gaps"]))
        self.assertFalse(any(item["rule_id"] == "form_core_documents_and_application_type" and item["status"] == "DETERMINISTIC_FAIL" for item in report["findings"]))

    def test_bom_and_persistent_input_contract_errors_return_three_without_report(self):
        code, path = self.run_checker(complete_manifest(), bom=True)
        self.assertEqual(code, 3)
        self.assertFalse(path.exists())

        manifest = complete_manifest()
        manifest["application_scope"] = "pct_national_phase"
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 3)
        self.assertFalse(path.exists())

    def test_document_and_manifest_resource_limits_return_four_without_report(self):
        original_manifest_limit = checker.MAX_MANIFEST_BYTES
        original_document_limit = checker.MAX_SINGLE_DOCUMENT_BYTES
        try:
            checker.MAX_MANIFEST_BYTES = 64
            code, path = self.run_checker(complete_manifest())
            self.assertEqual(code, 4)
            self.assertFalse(path.exists())

            checker.MAX_MANIFEST_BYTES = original_manifest_limit
            checker.MAX_SINGLE_DOCUMENT_BYTES = 8
            code, path = self.run_checker(complete_manifest())
            self.assertEqual(code, 4)
            self.assertFalse(path.exists())
        finally:
            checker.MAX_MANIFEST_BYTES = original_manifest_limit
            checker.MAX_SINGLE_DOCUMENT_BYTES = original_document_limit

    def test_json_depth_unknown_document_role_and_output_alias_are_rejected(self):
        manifest = complete_manifest()
        nested: object = {"leaf": "value"}
        for _ in range(65):
            nested = {"x": nested}
        manifest["request_fields"]["nested"] = nested
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 4)
        self.assertFalse(path.exists())

        manifest = complete_manifest()
        manifest["documents"]["unknown_document"] = {"status": "unknown"}
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 3)
        self.assertFalse(path.exists())

        manifest_path = self.path / "manifest.json"
        write_json(manifest_path, complete_manifest())
        self.assertEqual(checker.main(["--manifest", str(manifest_path), "--output", str(manifest_path)]), 3)

    def test_summary_abstract_and_conditional_procedure_states_are_preserved(self):
        manifest = complete_manifest()
        manifest["documents"]["abstract"] = {"status": "provided", "content": "摘要\n" + "技" * 301}
        manifest["documents"]["specification"] = {"status": "provided", "content": manifest["documents"]["specification"]["content"] + "\n附图说明\n图1为示意图。"}
        manifest["documents"]["drawings"] = {"status": "confirmed_absent"}
        del manifest["biological_material_deposit"]
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 2)
        report = json.loads(path.read_text(encoding="utf-8"))
        rules = {item["rule_id"] for item in report["findings"]}
        self.assertIn("form_abstract_content_and_length", rules)
        self.assertIn("form_drawings_requiredness_and_presence", rules)
        self.assertTrue(any(item["rule_id"] == "form_biological_material_deposit" and item["category"] == "CONDITIONAL_APPLICABILITY_UNRESOLVED" for item in report["gaps"]))

    def test_real_document_titles_detect_mismatch_and_overlength_even_when_manifest_titles_match(self):
        manifest = complete_manifest()
        manifest["titles"] = {
            "request": "统一标题",
            "specification": "统一标题",
            "abstract": "统一标题",
        }
        manifest["documents"]["request"] = {
            "status": "provided",
            "content": "请求书\n发明名称：标题甲",
        }
        manifest["documents"]["specification"] = {
            "status": "provided",
            "content": "发明名称\n一种明显超过中国专利常用名称长度阈值的数据处理装置与方法\n技术领域\n本发明涉及数据处理。\n背景技术\n现有技术存在延迟。\n发明内容\n提供处理装置。\n具体实施方式\n装置包括控制器。",
        }
        manifest["documents"]["abstract"] = {
            "status": "provided",
            "content": "摘要\n标题丙\n一种数据处理装置。",
        }
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        title_findings = [item for item in report["findings"] if item["rule_id"] == "form_title_consistency_and_quality"]
        self.assertTrue(any(item["status"] == "REVIEW_REQUIRED" and "真实文书提取" in item["problem"] for item in title_findings))
        self.assertTrue(any(item["status"] == "WARNING" and "25 字内" in item["problem"] for item in title_findings))

    def test_extracted_title_is_compared_with_corresponding_manifest_declaration(self):
        manifest = complete_manifest()
        manifest["titles"] = {
            "request": "申报标题",
            "specification": "申报标题",
            "abstract": "申报标题",
        }
        manifest["documents"]["request"] = {
            "status": "provided",
            "content": "请求书\n发明名称：真实标题",
        }
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        title_findings = [item for item in report["findings"] if item["rule_id"] == "form_title_consistency_and_quality"]
        self.assertTrue(any(item["status"] == "REVIEW_REQUIRED" and "manifest 声明" in item["problem"] for item in title_findings))

    def test_explicit_title_over_extract_limit_still_produces_length_warning(self):
        manifest = complete_manifest()
        long_title = "一种" + "超长名称" * 20
        manifest["titles"] = {
            "request": long_title,
            "specification": long_title,
            "abstract": long_title,
        }
        manifest["documents"]["specification"] = {
            "status": "provided",
            "content": f"发明名称\n{long_title}\n技术领域\n本发明涉及数据处理。\n背景技术\n现有技术存在延迟。\n发明内容\n提供处理装置。\n具体实施方式\n装置包括控制器。",
        }
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        title_findings = [item for item in report["findings"] if item["rule_id"] == "form_title_consistency_and_quality"]
        self.assertTrue(any(item["status"] == "WARNING" and long_title in item["problem"] for item in title_findings))

    def test_markdown_title_heading_is_normalized_before_comparison(self):
        manifest = complete_manifest()
        manifest["documents"]["request"] = {
            "status": "provided",
            "content": "请求书\n发明名称：一种数据处理装置",
        }
        manifest["documents"]["specification"] = {
            "status": "provided",
            "content": "# 一种数据处理装置\n# 技术领域\n本发明涉及数据处理。\n# 背景技术\n现有技术存在延迟。\n# 发明内容\n提供处理装置。\n# 具体实施方式\n装置包括控制器。",
        }
        manifest["documents"]["abstract"] = {
            "status": "provided",
            "content": "# 摘要\n## 一种数据处理装置\n一种数据处理装置及其用途。",
        }
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        title_findings = [item for item in report["findings"] if item["rule_id"] == "form_title_consistency_and_quality"]
        self.assertFalse(any(item["status"] == "REVIEW_REQUIRED" for item in title_findings))

    def test_drawings_provided_but_abstract_figure_marked_not_applicable_is_deterministic_fail(self):
        manifest = complete_manifest()
        manifest["documents"]["drawings"] = {"status": "provided", "content": "图1"}
        manifest["documents"]["specification"] = {
            "status": "provided",
            "content": "技术领域\n本发明涉及数据处理。\n背景技术\n现有技术存在延迟。\n发明内容\n提供处理装置。\n附图说明\n图1为示意图。\n具体实施方式\n如图1所示，装置包括控制器。",
        }
        manifest["abstract_figure"] = {"applicability": "not_applicable", "evidence": "未指定摘要附图"}
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 2)
        report = json.loads(path.read_text(encoding="utf-8"))
        finding = next(item for item in report["findings"] if item["rule_id"] == "form_abstract_figure_designation")
        self.assertEqual(finding["status"], "DETERMINISTIC_FAIL")
        self.assertIn("not_applicable", finding["problem"])

    def test_strong_draft_placeholder_is_conserved_as_execution_finding(self):
        manifest = complete_manifest()
        manifest["documents"]["specification"]["content"] += "\n【内部待填：实施例参数】"
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 2)
        report = json.loads(path.read_text(encoding="utf-8"))
        finding = next(item for item in report["findings"] if item["rule_id"] == "form_language_format_and_execution")
        self.assertEqual(finding["status"], "DETERMINISTIC_FAIL")
        execution_check = next(item for item in report["checks_performed"] if item["rule_id"] == "form_language_format_and_execution")
        self.assertIn(finding["finding_id"], execution_check["finding_ids"])

    def figure_section_manifest(self, figure_section: str) -> dict:
        manifest = complete_manifest()
        # 说明书引用图号而附图被确认缺失会触发 form_drawings_requiredness_and_presence 的
        # 确定性失败，与形态筛查无关；这里让附图状态未知，把退出码留给形态筛查本身。
        manifest["documents"]["drawings"] = {"status": "unknown"}
        manifest["documents"]["specification"] = {
            "status": "provided",
            "content": "技术领域\n本发明涉及数据处理。\n背景技术\n现有技术存在延迟。\n发明内容\n提供处理装置。\n"
            + figure_section
            + "\n具体实施方式\n如图1所示，装置包括控制器100和存储器110。",
        }
        return manifest

    def figure_form_findings(self, figure_section: str) -> list[dict]:
        code, path = self.run_checker(self.figure_section_manifest(figure_section))
        # 形态问题是 WARNING，不得把退出码抬到 2。
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in report["findings"] if item["location"] == "specification.附图说明"]

    def test_canonical_single_paragraph_reference_sign_list_produces_no_form_finding(self):
        section = "附图说明\n图1是本发明装置的结构示意图。\n\n图中：100-控制器、110-存储器。"
        self.assertEqual(self.figure_form_findings(section), [])

    def test_wrapped_single_paragraph_reference_sign_list_is_not_a_false_positive(self):
        # 单段句式折行后续行可能以数字开头，含顿号即视为折行，不得误报逐行清单。
        section = "附图说明\n图1是本发明装置的结构示意图。\n\n图中：100-控制器、\n110-存储器、120-总线、\n130-接口。"
        self.assertEqual(self.figure_form_findings(section), [])

    def test_markdown_table_carrying_reference_signs_is_a_warning_bound_to_the_figure_rule(self):
        section = "附图说明\n图1是本发明装置的结构示意图。\n\n| 标记 | 名称 |\n|---|---|\n| 100 | 控制器 |\n| 110 | 存储器 |"
        findings = self.figure_form_findings(section)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["status"], "WARNING")
        self.assertEqual(finding["rule_id"], "form_drawing_numbering_reference_signs_and_graphic_form")
        self.assertTrue(finding["manual_review_required"])
        self.assertIn("表格", finding["problem"])

    def test_per_line_reference_sign_list_and_bulleted_figure_captions_are_both_flagged(self):
        section = "附图说明\n- 图1是本发明装置的结构示意图。\n\n100-控制器\n110-存储器\n120-总线"
        shapes = {item["problem"] for item in self.figure_form_findings(section)}
        self.assertEqual(len(shapes), 2)
        self.assertTrue(any("列表" in item for item in shapes))
        self.assertTrue(any("逐行清单" in item for item in shapes))

    def test_figure_form_screening_is_skipped_when_specification_is_not_provided(self):
        manifest = complete_manifest()
        manifest["documents"]["specification"] = {"status": "unknown"}
        code, path = self.run_checker(manifest)
        self.assertEqual(code, 0)
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([item for item in report["findings"] if item["location"] == "specification.附图说明"], [])


if __name__ == "__main__":
    unittest.main()
