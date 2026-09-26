"""CN v2 claims raw checker regression tests."""

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
SCRIPT = ROOT / "skills/cn-patent-claims-analyzer/scripts/check_claims_cn.py"


def load_script():
    spec = importlib.util.spec_from_file_location("cn_claims_checker_v2", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = load_script()


class ClaimsCheckerV2Tests(unittest.TestCase):
    def test_v2_raw_report_has_exact_top_level_fields_and_advisory_effect(self):
        report = checker.analyze_claims("1. 一种数据处理装置，包括控制器。")
        self.assertEqual(report["schema_version"], "cn-patent-review-raw-report/v2")
        self.assertEqual(report["legal_effect"], "ADVISORY_ONLY")
        self.assertEqual(
            set(report),
            {
                "schema_version", "jurisdiction", "review_type", "legal_effect", "report_id",
                "input_artifacts", "rule_sources", "tool_identity", "evidence_binding",
                "resource_limits", "resource_usage", "checks_performed", "findings", "gaps",
            },
        )
        self.assertEqual(report["resource_usage"]["finding_count"], len(report["findings"]))
        self.assertEqual(report["resource_usage"]["gap_count"], len(report["gaps"]))
        self.assertGreater(report["resource_usage"]["output_bytes"], 0)
        self.assertIn("claim-length-policy", {item["artifact_id"] for item in report["rule_sources"]})

    def test_findings_and_gaps_have_stable_exact_contract_fields(self):
        report = checker.analyze_claims("1. 一种装置，包括【待填：参数】。")
        finding = next(item for item in report["findings"] if item["rule_id"] == "CN-CLAIM-DRAFT-001")
        self.assertEqual(
            set(finding),
            {"finding_id", "check_id", "rule_id", "target_id", "location", "status", "evidence", "problem", "remedy", "manual_review_required"},
        )
        self.assertEqual([set(item) for item in finding["evidence"]], [{"artifact_id", "location", "excerpt"}])
        gap = report["gaps"][0]
        self.assertEqual(set(gap), {"gap_id", "check_id", "rule_id", "target_id", "category", "reason", "evidence", "blocks_assessment"})
        repeat = checker.analyze_claims("1. 一种装置，包括【待填：参数】。")
        self.assertEqual(report["findings"][0]["finding_id"], repeat["findings"][0]["finding_id"])

    def test_word_compatible_count_matches_boundary_and_formula_rules(self):
        self.assertEqual(checker.word_compatible_claim_count("甲" * 600), 600)
        self.assertEqual(checker.word_compatible_claim_count("data processing 123"), 3)
        self.assertEqual(checker.word_compatible_claim_count("data-processing 3.14"), 2)
        self.assertEqual(checker.word_compatible_claim_count("甲，乙；丙。"), 3)
        self.assertEqual(checker.word_compatible_claim_count("$Q_{CT}=C(P,a_i)$"), 1)
        self.assertEqual(checker.word_compatible_claim_count(r"\[Q_{CT}=C(P,a_i)\]"), 1)
        self.assertEqual(checker.word_compatible_claim_count("```math\nQ_{CT}=C(P,a_i)\n```"), 1)
        self.assertEqual(checker.word_compatible_claim_count("∑"), 1)

    def test_single_claim_word_count_limit_accepts_600_and_rejects_601(self):
        # 用权利要求3做600/601边界测试
        accepted = checker.analyze_claims("1. 一种装置。\n2. 根据权利要求1所述的装置。\n3. " + "甲" * 599 + "$Q_{CT}=C(P,a_i)$")
        self.assertFalse(any(item["rule_id"] == "CN-CLAIM-LENGTH-001" for item in accepted["findings"]))
        accepted_check = next(item for item in accepted["checks_performed"] if item["check_id"] == "claim-word-count")
        self.assertEqual(accepted_check["status"], "COMPLETED")
        self.assertEqual(accepted_check["finding_ids"], [])

        rejected = checker.analyze_claims("1. 一种装置。\n2. 根据权利要求1所述的装置。\n3. " + "甲" * 600 + "$Q_{CT}=C(P,a_i)$")
        finding = next(item for item in rejected["findings"] if item["rule_id"] == "CN-CLAIM-LENGTH-001")
        self.assertEqual(finding["status"], "DETERMINISTIC_FAIL")
        self.assertIn("Word 口径字数=601", finding["evidence"][0]["excerpt"])
        self.assertEqual(finding["target_id"], "claim-3")

    def test_claim_number_is_excluded_from_word_count(self):
        report = checker.analyze_claims("999999. " + "甲" * 600)
        self.assertFalse(any(item["rule_id"] == "CN-CLAIM-LENGTH-001" for item in report["findings"]))

    def test_reference_leads_only_create_candidate_or_unresolved_states(self):
        candidate = checker.analyze_claims("1. 一种装置。\n2. 根据权利要求1所述的装置。")
        candidate_finding = next(item for item in candidate["findings"] if item["rule_id"] == "CN-CLAIM-REF-PARSE-001")
        self.assertEqual(candidate_finding["status"], "REVIEW_REQUIRED")
        self.assertIn("PARSE_UNRESOLVED", {item["category"] for item in candidate["gaps"]})
        unresolved = checker.analyze_claims("1. 一种装置。\n2. 根据权利要求甲所述的装置。")
        self.assertIn("PARSE_UNRESOLVED", {item["category"] for item in unresolved["gaps"]})
        self.assertFalse(any(item["rule_id"] == "CN-CLAIM-REF-001" and item["status"] == "DETERMINISTIC_FAIL" for item in candidate["findings"]))

    def test_multiple_dependent_conjunctive_and_nested_multi_fail(self):
        report = checker.analyze_claims(
            "1. 一种装置。\n"
            "2. 一种方法。\n"
            "3. 根据权利要求1和2所述的装置。\n"
            "4. 根据权利要求1或3所述的装置，还包括传感器。\n"
        )
        multi = [item for item in report["findings"] if item["rule_id"] == "CN-CLAIM-MULTI-001"]
        self.assertTrue(any(item["status"] == "DETERMINISTIC_FAIL" and "并列" in item["problem"] for item in multi))
        self.assertTrue(any(item["status"] == "DETERMINISTIC_FAIL" and "另一项多项从属" in item["problem"] for item in multi))
        alternative = checker.analyze_claims(
            "1. 一种装置。\n"
            "2. 一种方法。\n"
            "3. 根据权利要求1或2所述的装置。\n"
        )
        self.assertFalse(
            any(
                item["rule_id"] == "CN-CLAIM-MULTI-001" and item["status"] == "DETERMINISTIC_FAIL"
                for item in alternative["findings"]
            )
        )

    def test_reference_target_self_forward_and_missing_are_deterministic(self):
        report = checker.analyze_claims(
            "1. 一种装置。\n"
            "2. 根据权利要求2所述的装置。\n"
            "3. 根据权利要求9所述的装置。\n"
            "4. 根据权利要求5所述的装置。\n"
            "5. 一种方法。\n"
        )
        ref_findings = [item for item in report["findings"] if item["rule_id"] == "CN-CLAIM-REF-001"]
        problems = "；".join(item["problem"] for item in ref_findings)
        self.assertIn("引用自身", problems)
        self.assertIn("向后引用", problems)
        self.assertIn("不存在", problems)
        ref_check = next(item for item in report["checks_performed"] if item["check_id"] == "claim-reference-graph")
        self.assertEqual(ref_check["status"], "PARTIAL")
        self.assertTrue(ref_check["finding_ids"])

    def test_function_and_dependent_semantic_rules_emit_fixed_gaps(self):
        report = checker.analyze_claims("1. 一种装置。")
        gap_rules = {item["rule_id"] for item in report["gaps"]}
        self.assertIn("CN-CLAIM-FUNCTION-001", gap_rules)
        self.assertIn("CN-CLAIM-DEPENDENT-001", gap_rules)
        for rule_id in ("CN-CLAIM-FUNCTION-001", "CN-CLAIM-DEPENDENT-001"):
            gap = next(item for item in report["gaps"] if item["rule_id"] == rule_id)
            self.assertEqual(gap["category"], "SEMANTIC_REVIEW_NOT_PERFORMED")

    def test_reference_ranges_expand_through_501_502_601_without_endpoint_truncation(self):
        for end in (501, 502, 601):
            lines = [f"{number}. 一种处理装置，其特征在于，包括处理器。" for number in range(1, end + 1)]
            lines[2] = "3. 根据权利要求1或2中任一项所述的处理装置，其特征在于，还包括存储器。"
            lines.append(f"{end + 1}. 根据权利要求1至{end}中任一项所述的处理装置，其特征在于，还包括传感器。")
            report = checker.analyze_claims("\n".join(lines))
            findings = [item for item in report["findings"] if item["rule_id"] == "CN-CLAIM-MULTI-001" and item["target_id"] == f"claim-{end + 1}"]
            self.assertTrue(any(item["status"] == "DETERMINISTIC_FAIL" and "引用了另一项多项从属" in item["problem"] for item in findings), end)

    def test_reference_range_over_resource_budget_is_rejected_not_truncated(self):
        with self.assertRaises(checker.ResourceLimitError):
            checker.analyze_claims("1. 根据权利要求1至100001中任一项所述的装置。")

    def test_large_number_is_rejected_without_range_allocation(self):
        with self.assertRaises(checker.ResourceLimitError):
            checker.analyze_claims("1000001. 一种装置。")
        report = checker.analyze_claims("1. 一种装置。\n3. 一种方法。")
        evidence = [entry["excerpt"] for item in report["findings"] if item["rule_id"] == "CN-CLAIM-NUM-001" for entry in item["evidence"]]
        self.assertIn("2-2", evidence)

    def test_iterative_cycle_algorithm_handles_deep_graph_without_recursion(self):
        graph = {number: (number - 1,) for number in range(2, 1500)}
        graph[1] = (1499,)
        cycles = checker.detect_cycles_iterative(graph, checker.Budget())
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0][0], 1)
        self.assertEqual(cycles[0][-1], 1)

    def test_cli_rejects_bom_and_resource_failures_with_exit_four_and_no_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "claims.txt"
            output_path = root / "report.json"
            input_path.write_bytes(b"\xef\xbb\xbf1. \xe4\xb8\x80\xe7\xa7\x8d\xe8\xa3\x85\xe7\xbd\xae\xe3\x80\x82\n")
            self.assertEqual(checker.main(["--input", str(input_path), "--output", str(output_path)]), 3)
            self.assertFalse(output_path.exists())
            input_path.write_bytes(b"1. " + b"x" * (checker.MAX_INPUT_BYTES + 1))
            self.assertEqual(checker.main(["--input", str(input_path), "--output", str(output_path)]), 4)
            self.assertFalse(output_path.exists())

    def test_cli_returns_two_when_claim_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "claims.txt"
            output_path = root / "report.json"
            # 权利要求3超过600
            input_path.write_text("1. 一种装置。\n2. 根据权利要求1所述的装置。\n3. " + "甲" * 601, encoding="utf-8")
            self.assertEqual(checker.main(["--input", str(input_path), "--output", str(output_path)]), 2)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(any(item["rule_id"] == "CN-CLAIM-LENGTH-001" for item in report["findings"]))

    def test_cli_writes_atomic_independent_raw_report_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "claims.txt"
            output_path = root / "report.json"
            original = "1. 一种装置。\n"
            input_path.write_text(original, encoding="utf-8")
            self.assertEqual(checker.main(["--input", str(input_path), "--output", str(output_path)]), 0)
            self.assertEqual(input_path.read_text(encoding="utf-8"), original)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], checker.SCHEMA_VERSION)
            self.assertEqual(list(root.glob(".*.tmp")), [])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(checker.main(["--input", str(input_path), "--output", str(root / "." / "claims.txt")]), 3)
            self.assertEqual(input_path.read_text(encoding="utf-8"), original)

    def test_atomic_replace_failure_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_path = root / "report.json"
            output_path.write_text("old", encoding="utf-8")
            report = checker.analyze_claims("1. 一种装置。")
            with mock.patch.object(checker.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    checker.write_result(report, output_path)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_claim_1_word_count_limit_accepts_400_and_rejects_401(self):
        # 权利要求1: 400字通过，401字失败 LENGTH-002
        accepted = checker.analyze_claims("1. " + "甲" * 399 + "中")
        self.assertFalse(any(item["rule_id"] == "CN-CLAIM-LENGTH-002" for item in accepted["findings"]))
        self.assertFalse(any(item["rule_id"] == "CN-CLAIM-LENGTH-001" for item in accepted["findings"]))

        rejected = checker.analyze_claims("1. " + "甲" * 400 + "中")
        finding = next(item for item in rejected["findings"] if item["rule_id"] == "CN-CLAIM-LENGTH-002")
        self.assertEqual(finding["status"], "DETERMINISTIC_FAIL")
        self.assertIn("Word 口径字数=401", finding["evidence"][0]["excerpt"])
        self.assertIn("400", finding["evidence"][0]["excerpt"])
        self.assertNotIn("CN-CLAIM-LENGTH-001", {item["rule_id"] for item in rejected["findings"]})

    def test_claim_2_word_count_limit_accepts_500_and_rejects_501(self):
        prefix = "根据权利要求1所述的装置，其特征在于，"
        prefix_count = checker.word_compatible_claim_count(prefix)
        accepted = checker.analyze_claims("1. 一种装置。\n2. " + prefix + "甲" * (500 - prefix_count))
        self.assertFalse(any(item["rule_id"] in {"CN-CLAIM-LENGTH-003", "CN-CLAIM-LENGTH-001"} for item in accepted["findings"]))
        accepted_check = next(item for item in accepted["checks_performed"] if item["check_id"] == "claim-2-word-count")
        self.assertEqual(accepted_check["status"], "COMPLETED")
        self.assertEqual(accepted_check["finding_ids"], [])

        rejected = checker.analyze_claims("1. 一种装置。\n2. " + prefix + "甲" * (501 - prefix_count))
        finding = next(item for item in rejected["findings"] if item["rule_id"] == "CN-CLAIM-LENGTH-003")
        self.assertEqual(finding["status"], "DETERMINISTIC_FAIL")
        self.assertEqual(finding["target_id"], "claim-2")
        self.assertIn("Word 口径字数=501", finding["evidence"][0]["excerpt"])
        self.assertIn("上限=500", finding["evidence"][0]["excerpt"])
        self.assertFalse(any(item["rule_id"] == "CN-CLAIM-LENGTH-001" for item in rejected["findings"]))

        # 权利要求 2 远超 600 时仍只报 LENGTH-003，不重复报 LENGTH-001
        oversized = checker.analyze_claims("1. 一种装置。\n2. " + prefix + "甲" * 650)
        rule_ids = [item["rule_id"] for item in oversized["findings"] if item["target_id"] == "claim-2"]
        self.assertIn("CN-CLAIM-LENGTH-003", rule_ids)
        self.assertNotIn("CN-CLAIM-LENGTH-001", rule_ids)

    def test_claim_2_must_reference_claim_1_only(self):
        # CN-CLAIM-CORE-001：权利要求2必须直接引用权利要求1
        # 独立的权利要求2失败
        independent_2 = checker.analyze_claims("1. 一种装置。\n2. 一种方法。")
        core_findings = [item for item in independent_2["findings"] if item["rule_id"] == "CN-CLAIM-CORE-001"]
        self.assertTrue(any(item["status"] == "DETERMINISTIC_FAIL" and "未引用" in item["problem"] for item in core_findings))

        # 直接引用1的权利要求2通过
        correct_2 = checker.analyze_claims("1. 一种装置。\n2. 根据权利要求1所述的装置。")
        core_check = next(item for item in correct_2["checks_performed"] if item["check_id"] == "claim-2-core-dependency")
        self.assertEqual(core_check["status"], "COMPLETED")
        self.assertEqual(core_check["finding_ids"], [])

        # 引用的不是权利要求1（引用3、或引用1或3）都失败
        for text in ("1. 一种装置。\n2. 根据权利要求3所述的装置。\n3. 根据权利要求1所述的装置。",
                     "1. 一种装置。\n2. 根据权利要求1或3所述的装置。\n3. 根据权利要求1所述的装置。"):
            report = checker.analyze_claims(text)
            wrong_ref = [item for item in report["findings"] if item["rule_id"] == "CN-CLAIM-CORE-001"]
            self.assertTrue(any(item["status"] == "DETERMINISTIC_FAIL" and "实际引用" in item["problem"] for item in wrong_ref), text)

    def test_claim_2_missing_gives_not_verified_and_gap(self):
        # 只有权利要求1时，claim-2-core-dependency check状态为NOT_VERIFIED
        single_claim = checker.analyze_claims("1. 一种装置。")
        core_check = next(item for item in single_claim["checks_performed"] if item["check_id"] == "claim-2-core-dependency")
        self.assertEqual(core_check["status"], "NOT_VERIFIED")
        self.assertTrue(len(core_check["gap_ids"]) > 0)

    def test_claim_1_and_2_word_count_checks_separated_from_001(self):
        # 验证权利要求1和2有自己的check，不与001混淆
        report = checker.analyze_claims(
            "1. " + "甲" * 350 +
            "\n2. 根据权利要求1所述的" + "甲" * 450 +
            "\n3. " + "甲" * 599
        )
        checks = {item["check_id"] for item in report["checks_performed"]}
        self.assertIn("claim-1-word-count", checks)
        self.assertIn("claim-2-word-count", checks)
        self.assertIn("claim-word-count", checks)

        # 分别有三个check处理三个规则
        length_001_check = next((item for item in report["checks_performed"] if item["rule_id"] == "CN-CLAIM-LENGTH-001"), None)
        length_002_check = next((item for item in report["checks_performed"] if item["rule_id"] == "CN-CLAIM-LENGTH-002"), None)
        length_003_check = next((item for item in report["checks_performed"] if item["rule_id"] == "CN-CLAIM-LENGTH-003"), None)

        self.assertIsNotNone(length_001_check)
        self.assertIsNotNone(length_002_check)
        self.assertIsNotNone(length_003_check)


if __name__ == "__main__":
    unittest.main()
