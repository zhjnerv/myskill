"""CN v2 规范一致性回归：生产检查器的真实输出必须逐条通过机读规范校验。

本文件是 Wave 2 集成的守卫。此前 claims 检查器曾输出自造 schema id、把 finding
状态写进 raw_check.status、用规范外的 gap 类别、把 evidence 写成对象而非数组，
并产生重复 gap_id——这些缺陷单靠人工评审全部漏过。规范是机读的，一致性就必须
由机器复算。
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cn_contract = load_module("cn_contract", "skills/cn-patent-reviewer/scripts/cn_contract.py")
claims_checker = load_module("cn_claims_conformance", "skills/cn-patent-claims-analyzer/scripts/check_claims_cn.py")
formalities_checker = load_module("cn_formalities_conformance", "skills/cn-patent-formalities-reviewer/scripts/check_formalities_cn.py")
specification_checker = load_module("cn_specification_conformance", "skills/cn-patent-specification-reviewer/scripts/build_support_matrix_cn.py")

sys.path.insert(0, str(ROOT / "tests"))
from test_cn_contract_v2 import tuple_errors  # noqa: E402  Wave 1 的参考实现，用于交叉验证


CLAIMS_INPUTS = {
    "single_independent": "1. 一种数据处理装置，其特征在于，包括控制器。",
    "dependent_chain": "1. 一种数据处理方法，其特征在于，包括步骤A。\n2. 根据权利要求1所述的方法，其特征在于，还包括所述步骤B。\n",
    "numbering_defects": "1. 一种装置。\n3. 一种方法。\n3. 另一方法。\n",
    "not_starting_at_one": "2. 一种装置，包括所述控制器。\n",
    "draft_residue": "1. 一种装置，包括【待填：参数】和 TODO。\n",
    "unparsable_reference": "1. 一种装置。\n2. 根据权利要求甲所述的装置。\n",
    "multi_term_same_claim": "1. 一种系统，其特征在于，所述处理器与所述存储器耦合，所述总线连接所述处理器。\n",
    "empty_document": "",
}


def formalities_manifests() -> dict[str, dict]:
    from test_cn_formalities_checker import complete_manifest

    cases: dict[str, dict] = {"complete": complete_manifest()}

    absent_specification = complete_manifest()
    absent_specification["documents"]["specification"] = {"status": "unknown"}
    cases["specification_unknown"] = absent_specification

    absent_abstract = complete_manifest()
    absent_abstract["documents"]["abstract"] = {"status": "confirmed_absent"}
    cases["abstract_absent"] = absent_abstract

    all_unknown = complete_manifest()
    for key in ("request", "specification", "claims", "abstract"):
        all_unknown["documents"][key] = {"status": "unknown"}
    cases["all_core_unknown"] = all_unknown

    with_drawings = complete_manifest()
    with_drawings["documents"]["drawings"] = {"status": "provided", "content": "图1 结构示意图"}
    with_drawings["documents"]["specification"]["content"] += "\n附图说明\n图1至图3为示意图。"
    cases["drawings_with_range"] = with_drawings

    missing_conditionals = complete_manifest()
    del missing_conditionals["sequence_listing"]
    del missing_conditionals["priority_documents"]
    cases["conditional_declarations_missing"] = missing_conditionals

    long_abstract = complete_manifest()
    long_abstract["documents"]["abstract"] = {"status": "provided", "content": "本发明世界领先，" + "技" * 320}
    cases["abstract_too_long"] = long_abstract

    return cases


SPECIFICATION_INPUTS = {
    "matched": ("[0001] 本装置包括控制器与存储器。\n[0002] 所述控制器执行调度算法。", [{"id": "F001", "text": "控制器"}]),
    "unmatched": ("[0001] 本装置包括控制器。", [{"id": "F001", "text": "散热风扇"}]),
    "empty_specification": ("", [{"id": "F001", "text": "控制器"}]),
    "no_features": ("[0001] 本装置包括控制器。", []),
    "empty_both": ("", []),
    "duplicate_paragraphs": ("[0001] 甲。\n[0001] 乙。", [{"id": "F001", "text": "甲"}]),
    "unnumbered": ("第一段。\n\n第二段包括控制器。", [{"id": "F001", "text": "控制器"}]),
}


def run_specification(specification: str, items: list) -> dict:
    return specification_checker.build_raw_report(specification, specification_checker.validate_features(items))


def run_formalities(manifest: dict) -> dict:
    from test_cn_formalities_checker import write_json

    with tempfile.TemporaryDirectory() as directory:
        manifest_path = Path(directory) / "manifest.json"
        report_path = Path(directory) / "report.json"
        write_json(manifest_path, manifest)
        formalities_checker.main(["--manifest", str(manifest_path), "--output", str(report_path)])
        return json.loads(report_path.read_text(encoding="utf-8"))


class ContractModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = cn_contract.load_contract()

    def test_shared_module_reproduces_wave1_locked_state_space(self):
        """生产模块必须复现 Wave 1 锁定的 61 个合法五轴组合，而不是测试里另写一份。"""

        self.assertEqual(len(self.contract.legal_state_combinations()), 61)

    def test_shared_module_agrees_with_wave1_reference_on_all_1440_combinations(self):
        enums = self.contract.data["enums"]
        combinations = list(itertools.product(
            enums["coverage"], enums["result_atomic"], enums["evidence_mode"],
            enums["evidence_sufficiency"], enums["severity"],
        ))
        self.assertEqual(len(combinations), 1440)
        for combo in combinations:
            reference_ok = not tuple_errors(*combo)
            module_ok = not self.contract.state_axis_errors(*combo)
            self.assertEqual(module_ok, reference_ok, f"组合 {combo} 的判定与 Wave 1 参考实现不一致")

    def test_contract_load_fails_closed_on_unimplemented_invariant(self):
        data = json.loads(json.dumps(self.contract.data))
        data["state_invariants"].append({"id": "unimplemented_future_rule", "rule": "x"})
        with self.assertRaises(cn_contract.ContractError):
            cn_contract.Contract(data)

    def test_contract_load_fails_closed_on_unimplemented_disposition(self):
        data = json.loads(json.dumps(self.contract.data))
        data["disposition"].append({"priority": 6, "when": "future_branch", "value": "NOT_ASSESSED"})
        with self.assertRaises(cn_contract.ContractError):
            cn_contract.Contract(data)

    def test_enum_bindings_cover_every_status_carrying_field(self):
        bindings = self.contract.data["enum_bindings"]
        for required in (
            "raw_check.status", "raw_finding.status", "raw_gap.category",
            "atomic_assessment.coverage", "atomic_assessment.result",
            "atomic_assessment.severity", "evidence.mode", "evidence.sufficiency",
        ):
            self.assertIn(required, bindings)
            self.assertIn(bindings[required], self.contract.data["enums"])

    def test_aggregate_and_disposition_come_from_the_contract(self):
        children = [
            {"assessment_id": "b", "coverage": "PARTIAL", "result": "ISSUE_FOUND", "severity": "HIGH", "finding_ids": ["F2"], "gap_ids": []},
            {"assessment_id": "a", "coverage": "FULL", "result": "INCONCLUSIVE", "severity": "NONE", "finding_ids": [], "gap_ids": ["G1"]},
        ]
        first = self.contract.aggregate(children)
        self.assertEqual(first, self.contract.aggregate(list(reversed(children))))
        self.assertEqual(first["result"], "MIXED")
        self.assertEqual(first["child_ids"], ["a", "b"])

        adequate = {"mode": "DETERMINISTIC", "sufficiency": "ADEQUATE_FOR_SCOPED_ASSESSMENT", "artifact_ids": [], "source_locations": []}
        clean = {"assessment_id": "a", "coverage": "FULL", "result": "NO_ISSUE_FOUND", "severity": "NONE", "evidence": adequate, "finding_ids": [], "gap_ids": []}
        blocker = {**clean, "assessment_id": "b", "result": "ISSUE_FOUND", "severity": "BLOCKER", "finding_ids": ["F1"]}
        self.assertEqual(self.contract.derive_disposition([clean]), "NO_BLOCKING_ISSUE_FOUND_IN_SCOPE")
        self.assertEqual(self.contract.derive_disposition([clean, blocker]), "BLOCKING_ISSUE_FOUND")
        self.assertIsNone(self.contract.derive_disposition([clean], ["CONTRACT_ERROR"]))


class RawReportConformanceTests(unittest.TestCase):
    """三个原始检查器的真实输出必须逐份通过规范校验。"""

    def setUp(self) -> None:
        self.contract = cn_contract.load_contract()

    def test_claims_raw_reports_conform_for_every_input_shape(self):
        for name, text in CLAIMS_INPUTS.items():
            with self.subTest(claims_input=name):
                report = claims_checker.analyze_claims(text)
                self.assertEqual(self.contract.validate_raw_report(report, name), [])
                self.assertEqual(report["review_type"], "claims")

    def test_formalities_raw_reports_conform_for_every_manifest_shape(self):
        for name, manifest in formalities_manifests().items():
            with self.subTest(manifest=name):
                report = run_formalities(manifest)
                self.assertEqual(self.contract.validate_raw_report(report, name), [])
                self.assertEqual(report["review_type"], "formalities")

    def test_specification_raw_reports_conform_for_every_input_shape(self):
        for name, (specification, items) in SPECIFICATION_INPUTS.items():
            with self.subTest(specification_input=name):
                report = run_specification(specification, items)
                self.assertEqual(self.contract.validate_raw_report(report, name), [])
                self.assertEqual(report["review_type"], "specification")

    def test_every_raw_checker_declares_the_contract_schema_ids(self):
        expected = self.contract.schema_ids["raw_report"]
        reports = [
            claims_checker.analyze_claims(CLAIMS_INPUTS["dependent_chain"]),
            run_formalities(formalities_manifests()["complete"]),
            run_specification(*SPECIFICATION_INPUTS["matched"]),
        ]
        self.assertEqual({report["review_type"] for report in reports}, set(self.contract.data["enums"]["review_type"]))
        for report in reports:
            self.assertEqual(report["schema_version"], expected)
            self.assertEqual(report["legal_effect"], "ADVISORY_ONLY")
            self.assertEqual(report["jurisdiction"], "CN")
            self.assertEqual(report["tool_identity"]["contract_schema_version"], self.contract.schema_ids["contract"])

    def test_the_three_required_review_types_are_all_covered(self):
        """规范要求 claims/specification/formalities 三份原始报告缺一不可。"""

        required = set(self.contract.data["finding_conservation"]["required_raw_reports"])
        produced = {
            claims_checker.analyze_claims(CLAIMS_INPUTS["single_independent"])["review_type"],
            run_formalities(formalities_manifests()["complete"])["review_type"],
            run_specification(*SPECIFICATION_INPUTS["matched"])["review_type"],
        }
        self.assertEqual(produced, required)

    def test_raw_ids_are_unique_and_stable_across_repeated_runs(self):
        for name, text in CLAIMS_INPUTS.items():
            with self.subTest(claims_input=name):
                first = claims_checker.analyze_claims(text)
                second = claims_checker.analyze_claims(text)
                self.assertEqual(
                    [item["finding_id"] for item in first["findings"]],
                    [item["finding_id"] for item in second["findings"]],
                )
                gap_ids = [item["gap_id"] for item in first["gaps"]]
                self.assertEqual(len(gap_ids), len(set(gap_ids)), "gap_id 必须在报告内唯一")
                finding_ids = [item["finding_id"] for item in first["findings"]]
                self.assertEqual(len(finding_ids), len(set(finding_ids)), "finding_id 必须在报告内唯一")


class ConformanceDetectionTests(unittest.TestCase):
    """校验器本身必须能抓出各类偏离；否则"全部通过"没有意义。"""

    def setUp(self) -> None:
        self.contract = cn_contract.load_contract()
        self.report = claims_checker.analyze_claims(CLAIMS_INPUTS["dependent_chain"])
        self.assertEqual(self.contract.validate_raw_report(self.report), [])

    def mutate(self, mutation) -> list[str]:
        copy = json.loads(json.dumps(self.report))
        mutation(copy)
        return self.contract.validate_raw_report(copy)

    def test_detects_foreign_schema_id(self):
        problems = self.mutate(lambda r: r.update(schema_version="cn-patent-claims-raw-report/v2"))
        self.assertTrue(any("schema_ids.raw_report" in item for item in problems))

    def test_detects_finding_status_used_as_check_status(self):
        problems = self.mutate(lambda r: r["checks_performed"][0].update(status="DETERMINISTIC_FAIL"))
        self.assertTrue(any("raw_check_status" in item for item in problems))

    def test_detects_gap_category_outside_contract_enum(self):
        problems = self.mutate(lambda r: r["gaps"][0].update(category="DEPENDENCY_CANDIDATE"))
        self.assertTrue(any("gap_category" in item for item in problems))

    def test_detects_evidence_object_instead_of_array(self):
        problems = self.mutate(lambda r: r["findings"][0].update(evidence={"artifact_id": "claims", "location": "x", "excerpt": "y"}))
        self.assertTrue(any("必须是数组" in item for item in problems))

    def test_detects_duplicate_and_dangling_ids(self):
        duplicate = self.mutate(lambda r: r["gaps"].append(json.loads(json.dumps(r["gaps"][0]))))
        self.assertTrue(any("gap_id 重复" in item for item in duplicate))
        dangling = self.mutate(lambda r: r["findings"][0].update(check_id="不存在的检查"))
        self.assertTrue(any("未命中任何 check" in item for item in dangling))

    def test_detects_check_that_hides_its_own_findings(self):
        def drop_link(report):
            for check in report["checks_performed"]:
                check["finding_ids"] = []
        problems = self.mutate(drop_link)
        self.assertTrue(any("不一致" in item for item in problems))

    def test_detects_evidence_pointing_at_undeclared_artifact(self):
        problems = self.mutate(lambda r: r["findings"][0]["evidence"][0].update(artifact_id="未声明来源"))
        self.assertTrue(any("未声明的 artifact_id" in item for item in problems))

    def test_detects_unknown_and_missing_top_level_fields(self):
        unknown = self.mutate(lambda r: r.update(overall_status="PASS"))
        self.assertTrue(any("规范未定义的字段" in item for item in unknown))
        self.assertTrue(any("禁止的生产者结论字段" in item for item in unknown))
        missing = self.mutate(lambda r: r.pop("evidence_binding"))
        self.assertTrue(any("缺少规范要求的字段" in item for item in missing))

    def test_detects_resource_usage_count_drift_and_limit_conflict(self):
        drift = self.mutate(lambda r: r["resource_usage"].update(finding_count=999))
        self.assertTrue(any("resource_usage.finding_count" in item for item in drift))
        conflict = self.mutate(lambda r: r["resource_limits"].update(max_findings=999999))
        self.assertTrue(any("与规范" in item for item in conflict))


if __name__ == "__main__":
    unittest.main()
