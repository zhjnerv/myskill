"""中国专利说明书 CN v2 原始检查器回归测试。

覆盖三层：文本定位的确定性语义（命中/未命中/规范化边界）、v2 原始报告的合同一致性、
以及资源上限与输出保护。文本命中只是证据，任何"已支持"结论都必须留给独立语义审查。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/cn-patent-specification-reviewer/scripts/build_support_matrix_cn.py"
CONTRACT_SCRIPT = ROOT / "skills/cn-patent-reviewer/scripts/cn_contract.py"


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load_script("cn_support_matrix", SCRIPT)
cn_contract = load_script("cn_contract_for_spec", CONTRACT_SCRIPT)


def features(*items) -> list:
    return builder.validate_features(list(items))


def report_for(specification: str, *items) -> dict:
    return builder.build_raw_report(specification, features(*items))


def gaps_of(report: dict, rule_id: str) -> list[dict]:
    return [item for item in report["gaps"] if item["rule_id"] == rule_id]


def findings_of(report: dict, rule_id: str) -> list[dict]:
    return [item for item in report["findings"] if item["rule_id"] == rule_id]


class TextLocationTests(unittest.TestCase):
    """定位语义：命中固定为证据，未命中只能触发人工复核。"""

    def test_exact_match_is_recorded_as_evidence_without_declaring_legal_support(self):
        report = report_for("[0001] 本装置包括控制器。", {"id": "F001", "text": "控制器"})
        gap = next(item for item in gaps_of(report, builder.MATCH_RULE_ID) if item["target_id"] == "feature-F001")
        self.assertEqual(gap["category"], "SEMANTIC_REVIEW_NOT_PERFORMED")
        self.assertTrue(gap["blocks_assessment"])
        self.assertIn("仍未作法律判断", gap["reason"])
        self.assertEqual(len(gap["evidence"]), 1)
        self.assertIn("feature_text", gap["evidence"][0]["location"])
        self.assertEqual(findings_of(report, builder.MATCH_RULE_ID), [])

    def test_explicit_variant_matches_and_is_labelled_as_variant(self):
        report = report_for("[0001] 本装置包括处理器。", {"id": "F001", "text": "控制器", "variants": ["处理器"]})
        gap = next(item for item in gaps_of(report, builder.MATCH_RULE_ID) if item["target_id"] == "feature-F001")
        self.assertTrue(any("explicit_variant" in entry["location"] for entry in gap["evidence"]))

    def test_unmatched_feature_requires_review_instead_of_declaring_no_support(self):
        report = report_for("[0001] 本装置包括控制器。", {"id": "F001", "text": "散热风扇"})
        finding = next(item for item in findings_of(report, builder.MATCH_RULE_ID) if item["target_id"] == "feature-F001")
        self.assertEqual(finding["status"], "REVIEW_REQUIRED")
        self.assertTrue(finding["manual_review_required"])
        self.assertIn("不得仅凭未命中认定缺乏支持", finding["remedy"])

    def test_match_evidence_carries_paragraph_key_offsets_and_centered_context(self):
        body = "无关内容。" * 60 + "目标特征出现在此处。" + "补充内容。" * 60
        report = report_for(f"[0007] {body}", {"id": "F001", "text": "目标特征"})
        gap = next(item for item in gaps_of(report, builder.MATCH_RULE_ID) if item["target_id"] == "feature-F001")
        entry = gap["evidence"][0]
        self.assertTrue(entry["location"].startswith("0007#1["))
        self.assertIn("目标特征", entry["excerpt"])
        self.assertTrue(entry["excerpt"].startswith("…"))

    def test_unnumbered_specification_is_split_on_blank_lines(self):
        report = report_for("第一段落。\n\n第二段落包括控制器。", {"id": "F001", "text": "控制器"})
        gap = next(item for item in gaps_of(report, builder.MATCH_RULE_ID) if item["target_id"] == "feature-F001")
        self.assertTrue(gap["evidence"][0]["location"].startswith("P0002#1["))

    def test_latin_and_numeric_spaces_are_kept_but_cjk_line_break_is_tolerated(self):
        latin = report_for("该标识为 AB，数值为 10。", {"id": "F001", "text": "A B"}, {"id": "F002", "text": "1 0"})
        self.assertEqual(len(findings_of(latin, builder.MATCH_RULE_ID)), 2)
        cjk = report_for("本实施方式包括目标\n特征。", {"id": "F001", "text": "目标特征"})
        self.assertEqual(findings_of(cjk, builder.MATCH_RULE_ID), [])


class ParagraphNumberingTests(unittest.TestCase):
    def test_duplicate_paragraph_ids_are_deterministic_failures(self):
        report = report_for("[0001] 甲。\n[0001] 乙。", {"id": "F001", "text": "甲"})
        finding = next(iter(findings_of(report, builder.PARAGRAPH_RULE_ID)))
        self.assertEqual(finding["status"], "DETERMINISTIC_FAIL")
        self.assertFalse(finding["manual_review_required"])

    def test_fullwidth_and_ascii_ids_collide_after_normalization(self):
        report = report_for("[0001] 甲。\n【０００１】乙。", {"id": "F001", "text": "甲"})
        self.assertEqual(len(findings_of(report, builder.PARAGRAPH_RULE_ID)), 1)

    def test_distinct_ids_and_fullwidth_only_input_stay_clean(self):
        distinct = report_for("[0001] 甲。\n[0002] 乙。", {"id": "F001", "text": "甲"})
        self.assertEqual(findings_of(distinct, builder.PARAGRAPH_RULE_ID), [])
        fullwidth = report_for("【０００１】目标特征。", {"id": "F001", "text": "目标特征"})
        self.assertEqual(findings_of(fullwidth, builder.PARAGRAPH_RULE_ID), [])
        gap = next(item for item in gaps_of(fullwidth, builder.MATCH_RULE_ID) if item["target_id"] == "feature-F001")
        self.assertTrue(gap["evidence"][0]["location"].startswith("0001#1["))

    def test_inline_marker_does_not_split_a_paragraph(self):
        report = report_for("[0001] 前文提到 [0002] 并非新段落。", {"id": "F001", "text": "前文"})
        self.assertEqual(findings_of(report, builder.PARAGRAPH_RULE_ID), [])


class FeatureInputTests(unittest.TestCase):
    def test_feature_schema_rejects_non_strings_empty_values_and_duplicate_ids(self):
        for payload in (
            [{"id": "F001", "text": None}],
            [{"id": "F001", "text": "  "}],
            [{"id": "", "text": "控制器"}],
            [{"id": 1, "text": "控制器"}],
            [{"id": "F001", "text": "甲"}, {"id": "f001", "text": "乙"}],
            [{"id": "F001", "text": "甲", "variants": "不是数组"}],
            [{"id": "F001", "feature_id": "F002", "text": "甲"}],
            [123],
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    builder.validate_features(payload)

    def test_variants_drop_empty_and_normalized_duplicates(self):
        parsed = features({"id": "F001", "text": "控制器", "variants": ["", "  ", "控制器", "控 制 器", "处理器", "处理器"]})
        self.assertEqual(parsed[0].variants, ("处理器",))

    def test_features_file_must_be_utf8_without_bom(self):
        with self.assertRaises(UnicodeError):
            builder.parse_features_bytes(b"\xef\xbb\xbf" + b'["a"]')


class RawReportContractTests(unittest.TestCase):
    """v2 原始报告必须逐份通过机读合同校验，并保持维度不静默消失。"""

    def setUp(self) -> None:
        self.contract = cn_contract.load_contract()

    def test_report_conforms_to_contract_for_every_input_shape(self):
        cases = {
            "matched": ("[0001] 控制器与存储器。", [{"id": "F001", "text": "控制器"}]),
            "unmatched": ("[0001] 控制器。", [{"id": "F001", "text": "散热风扇"}]),
            "empty_specification": ("", [{"id": "F001", "text": "控制器"}]),
            "no_features": ("[0001] 控制器。", []),
            "empty_both": ("", []),
            "duplicate_paragraphs": ("[0001] 甲。\n[0001] 乙。", [{"id": "F001", "text": "甲"}]),
        }
        for name, (specification, items) in cases.items():
            with self.subTest(case=name):
                report = builder.build_raw_report(specification, builder.validate_features(items))
                self.assertEqual(self.contract.validate_raw_report(report, name), [])
                self.assertEqual(report["review_type"], "specification")
                self.assertEqual(report["schema_version"], self.contract.schema_ids["raw_report"])

    def test_every_semantic_rule_becomes_a_structured_gap(self):
        report = report_for("[0001] 控制器。", {"id": "F001", "text": "控制器"})
        semantic_rules = {rule_id for rule_id, _, _ in builder.SEMANTIC_RULE_IDS}
        gap_rules = {item["rule_id"] for item in report["gaps"] if item["category"] == "SEMANTIC_REVIEW_NOT_PERFORMED"}
        self.assertTrue(semantic_rules.issubset(gap_rules))
        for rule_id in semantic_rules:
            check = next(item for item in report["checks_performed"] if item["rule_id"] == rule_id)
            self.assertEqual(check["status"], "NOT_VERIFIED")

    def test_empty_specification_does_not_fabricate_per_feature_misses(self):
        report = report_for("", {"id": "F001", "text": "控制器"})
        self.assertEqual(findings_of(report, builder.MATCH_RULE_ID), [])
        check = next(item for item in report["checks_performed"] if item["rule_id"] == builder.MATCH_RULE_ID)
        self.assertEqual(check["status"], "SKIPPED")
        self.assertTrue(any(item["category"] == "INPUT_UNAVAILABLE" for item in gaps_of(report, builder.INPUT_RULE_ID)))

    def test_report_is_byte_stable_across_repeated_runs(self):
        first = report_for("[0001] 控制器。", {"id": "F001", "text": "控制器"})
        second = report_for("[0001] 控制器。", {"id": "F001", "text": "控制器"})
        self.assertEqual(first["report_id"], second["report_id"])
        self.assertEqual([item["gap_id"] for item in first["gaps"]], [item["gap_id"] for item in second["gaps"]])
        self.assertEqual(first["evidence_binding"], second["evidence_binding"])


class ResourceLimitTests(unittest.TestCase):
    def test_oversized_inputs_and_match_explosions_raise_resource_errors(self):
        with mock.patch.object(builder, "MAX_SPECIFICATION_BYTES", 8):
            with self.assertRaises(builder.ResourceLimitError):
                builder.build_raw_report("超过上限的说明书文本", [])
        with mock.patch.object(builder, "MAX_PARAGRAPHS", 2):
            with self.assertRaises(builder.ResourceLimitError):
                report_for("[0001] 甲。\n[0002] 乙。\n[0003] 丙。", {"id": "F001", "text": "甲"})
        with mock.patch.object(builder, "MAX_FEATURE_CANDIDATES", 1):
            with self.assertRaises(builder.ResourceLimitError):
                builder.validate_features([{"id": "F001", "text": "甲"}, {"id": "F002", "text": "乙"}])
        with mock.patch.object(builder, "MAX_VARIANTS_PER_FEATURE", 1):
            with self.assertRaises(builder.ResourceLimitError):
                builder.validate_features([{"id": "F001", "text": "甲", "variants": ["乙", "丙"]}])
        with mock.patch.object(builder, "MAX_MATCHES_PER_FEATURE", 1):
            with self.assertRaises(builder.ResourceLimitError):
                report_for("[0001] 甲甲甲。", {"id": "F001", "text": "甲"})

    def test_declared_limits_match_the_contract(self):
        contract = cn_contract.load_contract()
        report = report_for("[0001] 控制器。", {"id": "F001", "text": "控制器"})
        for key, value in report["resource_limits"].items():
            self.assertEqual(contract.limits[key], value, f"{key} 与合同不一致")


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.specification = self.root / "specification.txt"
        self.features = self.root / "features.json"
        self.output = self.root / "raw-report.json"
        self.specification.write_bytes("[0001] 目标特征。\n".encode("utf-8"))
        self.features.write_bytes(json.dumps(["目标特征"], ensure_ascii=False).encode("utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, output: Path | None = None) -> tuple[int, str]:
        stderr = io.StringIO()
        arguments = ["--specification", str(self.specification), "--features", str(self.features)]
        if output is not None:
            arguments += ["--output", str(output)]
        with contextlib.redirect_stderr(stderr):
            code = builder.main(arguments)
        return code, stderr.getvalue()

    def test_successful_run_writes_conformant_report(self):
        code, _ = self.run_cli(self.output)
        self.assertEqual(code, 0)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(cn_contract.load_contract().validate_raw_report(report), [])

    def test_duplicate_paragraph_ids_return_exit_two(self):
        self.specification.write_bytes("[0001] 甲。\n[0001] 乙。\n".encode("utf-8"))
        code, _ = self.run_cli(self.output)
        self.assertEqual(code, 2)

    def test_output_aliasing_is_rejected_and_inputs_are_preserved(self):
        original = self.specification.read_bytes()
        for target in (self.specification, self.features):
            with self.subTest(target=target.name):
                code, stderr = self.run_cli(target)
                self.assertEqual(code, 3)
                self.assertIn(builder.OUTPUT_RULE_ID, stderr)
        self.assertEqual(self.specification.read_bytes(), original)

        hard_link = self.root / "specification-hardlink.txt"
        try:
            os.link(self.specification, hard_link)
        except OSError as exc:
            self.skipTest(f"当前文件系统不支持硬链接：{exc}")
        code, _ = self.run_cli(hard_link)
        self.assertEqual(code, 3)
        self.assertEqual(self.specification.read_bytes(), original)

    def test_bom_inputs_and_schema_errors_return_exit_three(self):
        self.specification.write_bytes(b"\xef\xbb\xbf" + "[0001] 甲。".encode("utf-8"))
        self.assertEqual(self.run_cli(self.output)[0], 3)
        self.specification.write_bytes("[0001] 甲。".encode("utf-8"))
        self.features.write_bytes(b'{"features": {"not": "a list"}}')
        self.assertEqual(self.run_cli(self.output)[0], 3)
        self.assertFalse(self.output.exists())

    def test_resource_failure_returns_exit_four_without_report(self):
        with mock.patch.object(builder, "MAX_SPECIFICATION_BYTES", 4):
            code, stderr = self.run_cli(self.output)
        self.assertEqual(code, builder.FAILURE_EXIT_CODE)
        self.assertIn(builder.RESOURCE_RULE_ID, stderr)
        self.assertFalse(self.output.exists())

    def test_atomic_write_failure_preserves_the_existing_report(self):
        self.output.write_text("旧报告", encoding="utf-8")
        report = report_for("[0001] 目标特征。", {"id": "F001", "text": "目标特征"})
        with mock.patch.object(builder.os, "replace", side_effect=OSError("模拟替换失败")):
            with self.assertRaises(OSError):
                builder.write_report(report, self.output, protected_inputs=[self.specification, self.features])
        self.assertEqual(self.output.read_text(encoding="utf-8"), "旧报告")
        self.assertEqual(list(self.root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
