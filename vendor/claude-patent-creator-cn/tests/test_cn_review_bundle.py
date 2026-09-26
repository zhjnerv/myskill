"""CN v2 审查链的真实 E2E 与故障注入回归。

三个层次：

1. **真实闭环**：从真实 UTF-8 申请文件跑通 prepare -> 三个检查器 -> 语义输入
   -> finalize -> 独立 verifier -> 机械摘要。
2. **故障注入**：原始 finding 的遗漏、重复、降级和来源篡改；请求书、规则、原始
   报告或工具身份变化导致的证据陈旧；合同缺陷与申请文件缺陷的分离。
3. **边界**：搜索证据边界、资源上限、UTF-8 无 BOM、无网络/模型/新依赖、
   禁止总体通过与授权预测措辞。

故障注入的意义在于证明验证器确实会拒绝——"全部通过"若不能被任何篡改打破，
就不构成证据。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))
import cn_fixtures as fx  # noqa: E402


contract_module = fx.load_module("contract", "cn_bundle_contract")
CONTRACT = contract_module.load_contract()

# CN 审查链只允许标准库；出现下列任何模块即意味着引入了网络、模型或新依赖。
FORBIDDEN_IMPORTS = (
    "requests", "urllib.request", "urllib3", "httpx", "socket", "aiohttp",
    "torch", "faiss", "sentence_transformers", "transformers", "numpy",
    "sklearn", "openai", "anthropic", "google.cloud", "pip",
)

CN_SCRIPT_PATHS = (
    "skills/cn-patent-claims-analyzer/scripts/check_claims_cn.py",
    "skills/cn-patent-specification-reviewer/scripts/build_support_matrix_cn.py",
    "skills/cn-patent-formalities-reviewer/scripts/check_formalities_cn.py",
    "skills/cn-patent-reviewer/scripts/cn_contract.py",
    "skills/cn-patent-reviewer/scripts/build_review_bundle.py",
    "skills/cn-patent-reviewer/scripts/verify_review_bundle.py",
)

# 生产链禁止出现的结论性措辞：总体通过、可申报、授权预测和专业确认。
FORBIDDEN_PHRASES = (
    "总体通过", "整体通过", "审查通过", "可以申报", "可申报", "建议申报",
    "满足授权条件", "予以授权", "授权概率", "合规分", "专业复核已完成",
    "专业审核已完成", "已通过专业复核", "保证授权",
)


class ChainTestCase(unittest.TestCase):
    """每个用例独享临时工作区，避免相互污染。"""

    application: dict = {}

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.chain = fx.Chain(Path(self.temporary.name), **self.application)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_quiet(self, callable_object, *args, **kwargs) -> tuple[int, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = callable_object(*args, **kwargs)
        return code, stderr.getvalue()


class RealEndToEndTests(ChainTestCase):
    def test_full_chain_runs_on_real_utf8_files_and_renders_summary(self):
        self.assertEqual(self.run_quiet(self.chain.prepare)[0], 0)
        for review_type in ("claims", "specification", "formalities"):
            report = fx.read_json(self.chain.raw_path(review_type))
            self.assertEqual(CONTRACT.validate_raw_report(report, review_type), [])
            self.assertEqual(report["review_type"], review_type)

        self.assertEqual(self.run_quiet(self.chain.finalize)[0], 0)
        bundle = fx.read_json(self.chain.bundle_path)
        self.assertEqual(CONTRACT.validate_bundle(bundle), [])
        self.assertEqual(len(bundle["assessments"]), 41)
        self.assertEqual(len(bundle["subreports"]), 3)

        self.assertEqual(self.run_quiet(self.chain.verify)[0], 0)
        verification = self.chain.verification()
        self.assertEqual(verification["errors"], [])
        self.assertEqual(verification["disposition"], "NOT_ASSESSED")
        self.assertTrue(self.chain.summary_path.is_file())

    def test_unfilled_semantic_review_cannot_clear_the_application(self):
        """模板默认全部失败关闭；未做语义审查不得产生"无阻断问题"。"""

        self.run_quiet(self.chain.run)
        verification = self.chain.verification()
        self.assertEqual(verification["disposition"], "NOT_ASSESSED")
        self.assertEqual(len(verification["coverage_summary"]["not_assessed_dimension_ids"]), 41)

    def test_every_raw_finding_and_gap_survives_into_the_bundle(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        bundle = fx.read_json(self.chain.bundle_path)
        for review_type in ("claims", "specification", "formalities"):
            raw = fx.read_json(self.chain.raw_path(review_type))
            subreport = next(item for item in bundle["subreports"] if item["review_type"] == review_type)
            self.assertEqual(
                {item["finding_id"] for item in raw["findings"]},
                {item["origin"]["origin_raw_finding_id"] for item in subreport["findings"]},
            )
            self.assertEqual(
                {item["gap_id"] for item in raw["gaps"]},
                {item["origin"]["origin_raw_gap_id"] for item in subreport["gaps"]},
            )

    def test_summary_never_claims_overall_pass_or_predicts_grant(self):
        self.run_quiet(self.chain.run)
        summary = self.chain.summary_path.read_text(encoding="utf-8")
        for phrase in FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, summary, f"摘要不得出现结论性措辞：{phrase}")
        self.assertIn("ADVISORY_ONLY", summary)
        self.assertIn("不代表官方审查结论", summary)

    def test_rerunning_the_chain_on_unchanged_inputs_reproduces_the_same_evidence(self):
        """同一份输入重跑，除耗时遥测外全部内容必须逐字段一致。

        `resource_usage` 含 elapsed_milliseconds 和随之变动的 output_bytes，天然不可复现；
        真正需要确定性的是证据内容、ID 与证据绑定。
        """

        def evidence_of(report: dict) -> dict:
            return {key: value for key, value in report.items() if key != "resource_usage"}

        self.run_quiet(self.chain.run)
        first_raw = {value: fx.read_json(self.chain.raw_path(value)) for value in
                     ("claims", "specification", "formalities")}
        first_bundle = fx.read_json(self.chain.bundle_path)

        self.run_quiet(self.chain.prepare)
        for review_type, report in first_raw.items():
            with self.subTest(review_type=review_type):
                repeated = fx.read_json(self.chain.raw_path(review_type))
                self.assertEqual(evidence_of(repeated), evidence_of(report))
                self.assertEqual(repeated["report_id"], report["report_id"])
                self.assertEqual(repeated["evidence_binding"], report["evidence_binding"])
        self.run_quiet(self.chain.finalize)
        self.assertEqual(evidence_of(fx.read_json(self.chain.bundle_path)), evidence_of(first_bundle))


class FindingConservationFaultTests(ChainTestCase):
    """原始 finding 的遗漏、重复、降级和来源篡改必须全部被验证器拒绝。"""

    def setUp(self) -> None:
        super().setUp()
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 0)

    def corrupt_bundle(self, mutate) -> dict:
        self.chain.rewrite_json(self.chain.bundle_path, mutate)
        code, _ = self.run_quiet(self.chain.verify)
        self.assertEqual(code, 3, "篡改后的 bundle 必须验证失败")
        return self.chain.verification()

    @staticmethod
    def first_subreport_with_findings(bundle: dict) -> dict:
        return next(item for item in bundle["subreports"] if item["findings"])

    def test_dropped_finding_is_detected(self):
        verification = self.corrupt_bundle(
            lambda bundle: self.first_subreport_with_findings(bundle)["findings"].pop()
        )
        self.assertTrue(any("在下游丢失" in item["message"] for item in verification["errors"]))
        self.assertIsNone(verification["disposition"])

    def test_duplicated_finding_is_detected(self):
        def mutate(bundle):
            findings = self.first_subreport_with_findings(bundle)["findings"]
            clone = json.loads(json.dumps(findings[0]))
            clone["finding_id"] = clone["finding_id"] + "-copy"
            findings.append(clone)
        verification = self.corrupt_bundle(mutate)
        self.assertTrue(any("必须恰好一次" in item["message"] for item in verification["errors"]))

    def test_downgraded_finding_status_is_detected(self):
        def mutate(bundle):
            for subreport in bundle["subreports"]:
                for item in subreport["findings"]:
                    if item["status"] != "WARNING":
                        item["status"] = "WARNING"
                        return
        verification = self.corrupt_bundle(mutate)
        self.assertTrue(any("的 status 被改写" in item["message"] for item in verification["errors"]))

    def test_tampered_problem_and_remedy_are_detected(self):
        for field, value in (("problem", "已核实无问题"), ("remedy", "无需处理")):
            with self.subTest(field=field):
                verification = self.corrupt_bundle(
                    lambda bundle, field=field, value=value:
                    self.first_subreport_with_findings(bundle)["findings"][0].update({field: value})
                )
                self.assertTrue(any(f"的 {field} 被改写" in item["message"] for item in verification["errors"]))
                self.run_quiet(self.chain.finalize)

    def test_tampered_evidence_source_is_detected(self):
        def mutate(bundle):
            self.first_subreport_with_findings(bundle)["findings"][0]["evidence"] = [
                {"artifact_id": "claims", "location": "伪造位置", "excerpt": "伪造摘录"}
            ]
        verification = self.corrupt_bundle(mutate)
        self.assertTrue(any("证据来源被改写" in item["message"] for item in verification["errors"]))

    def test_fabricated_origin_reference_is_detected(self):
        def mutate(bundle):
            self.first_subreport_with_findings(bundle)["findings"][0]["origin"]["origin_raw_finding_id"] = "F-不存在"
        verification = self.corrupt_bundle(mutate)
        self.assertTrue(any("不存在的原始 ID" in item["message"] for item in verification["errors"]))

    def test_double_or_null_origin_is_detected(self):
        for mutation in (
            lambda bundle: bundle["subreports"][0]["gaps"][0]["origin"].update(origin_raw_finding_id="F-x"),
            lambda bundle: bundle["subreports"][0]["gaps"][0]["origin"].update(origin_raw_gap_id=None),
        ):
            with self.subTest(mutation=str(mutation)):
                verification = self.corrupt_bundle(mutation)
                self.assertTrue(any(
                    "必须恰好一个非空引用" in item["message"] for item in verification["errors"]
                ))
                self.run_quiet(self.chain.finalize)

    def test_missing_subreport_is_detected(self):
        def mutate(bundle):
            bundle["subreports"] = [item for item in bundle["subreports"] if item["review_type"] != "specification"]
        verification = self.corrupt_bundle(mutate)
        self.assertTrue(any("subreports" in item["message"] for item in verification["errors"]))


class StaleEvidenceTests(ChainTestCase):
    """请求书、规则、原始报告或工具身份变化都必须使旧证据失效。"""

    def setUp(self) -> None:
        super().setUp()
        self.run_quiet(self.chain.prepare)

    def test_changed_application_file_invalidates_finalize(self):
        target = self.chain.application_directory / "claims.txt"
        target.write_bytes((fx.CLAIMS_TEXT + "3. 新增权利要求。\n").encode("utf-8"))
        code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 3)
        self.assertIn("冻结证据失效", stderr)
        self.assertFalse(self.chain.bundle_path.exists())

    def test_changed_formalities_manifest_invalidates_finalize(self):
        manifest = fx.formalities_manifest()
        manifest["titles"]["abstract"] = "另一个名称"
        fx.write_json(self.chain.application_directory / "formalities-manifest.json", manifest)
        code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 3)
        self.assertIn("冻结证据失效", stderr)

    def test_changed_raw_report_invalidates_finalize(self):
        self.chain.rewrite_json(self.chain.raw_path("claims"), lambda report: report["findings"].clear())
        code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 3)
        self.assertIn("冻结证据失效", stderr)

    def test_changed_rule_matrix_invalidates_finalize(self):
        manifest = fx.read_json(self.chain.workspace / "prepare-manifest.json")
        rule_path = Path(manifest["rule_sources"][0]["path"])
        original = rule_path.read_bytes()
        try:
            rule_path.write_bytes(original + "\n<!-- 规则已变更 -->\n".encode("utf-8"))
            code, stderr = self.run_quiet(self.chain.finalize)
            self.assertEqual(code, 3)
            self.assertIn("冻结证据失效", stderr)
        finally:
            rule_path.write_bytes(original)

    def test_semantic_input_bound_to_another_prepare_is_rejected(self):
        template = fx.read_json(self.chain.template_path)
        template["prepare_id"] = "P-另一次准备"
        stale = self.chain.workspace / "stale-review.json"
        fx.write_json(stale, template)
        code, stderr = self.run_quiet(self.chain.finalize, review_input=stale)
        self.assertEqual(code, 3)
        self.assertIn("prepare_id", stderr)

    def test_semantic_input_with_stale_binding_is_rejected(self):
        template = fx.read_json(self.chain.template_path)
        template["evidence_binding"]["input_set_sha256"] = "0" * 64
        stale = self.chain.workspace / "stale-binding.json"
        fx.write_json(stale, template)
        code, stderr = self.run_quiet(self.chain.finalize, review_input=stale)
        self.assertEqual(code, 3)
        self.assertIn("陈旧", stderr)

    def test_verifier_rejects_bundle_bound_to_another_prepare(self):
        self.run_quiet(self.chain.finalize)
        self.chain.rewrite_json(self.chain.bundle_path, lambda bundle: bundle.update(prepare_id="P-伪造"))
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        self.assertTrue(any("prepare_id" in item["message"] for item in self.chain.verification()["errors"]))

    def test_verifier_recomputes_binding_instead_of_trusting_the_bundle(self):
        self.run_quiet(self.chain.finalize)
        self.chain.rewrite_json(
            self.chain.bundle_path,
            lambda bundle: bundle["evidence_binding"].update(input_set_sha256="f" * 64),
        )
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        self.assertTrue(any("独立复算" in item["message"] for item in self.chain.verification()["errors"]))

    def test_changed_provenance_artifact_invalidates_finalize(self):
        target = self.chain.application_directory / "search-query.json"
        target.write_bytes((target.read_bytes() + b"\n").decode("utf-8").encode("utf-8"))
        code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 3)
        self.assertIn("冻结证据失效", stderr)
        self.assertFalse(self.chain.bundle_path.exists())

    def test_semantic_input_with_extra_top_level_key_is_rejected(self):
        self.assertEqual(self.run_quiet(self.chain.prepare)[0], 0)
        def mutate(payload):
            payload["overall_verdict"] = "PASS"
        self.chain.rewrite_json(self.chain.template_path, mutate)
        code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 3)
        self.assertFalse(self.chain.bundle_path.exists())

    def test_semantic_input_with_missing_top_level_key_is_rejected(self):
        self.assertEqual(self.run_quiet(self.chain.prepare)[0], 0)
        def mutate(payload):
            if "semantic_gaps" in payload:
                del payload["semantic_gaps"]
        self.chain.rewrite_json(self.chain.template_path, mutate)
        code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 3)
        self.assertFalse(self.chain.bundle_path.exists())


class ProvenanceArtifactTests(ChainTestCase):
    """前置检索、范本、阶段门、台账和架构证据必须进入可复算绑定链。"""

    def test_provenance_artifacts_are_bound_in_manifest_bundle_and_prepare_id(self):
        self.assertEqual(self.run_quiet(self.chain.prepare)[0], 0)
        manifest = fx.read_json(self.chain.workspace / "prepare-manifest.json")
        self.assertEqual(
            {item["artifact_id"] for item in manifest["provenance_artifacts"]},
            set(fx.PROVENANCE_FILES),
        )
        self.assertIn("provenance_set_sha256", manifest["evidence_binding"])
        template = fx.read_json(self.chain.template_path)
        self.assertEqual(template["evidence_binding"], manifest["evidence_binding"])
        self.assertEqual(template["provenance_artifacts"], manifest["provenance_artifacts"])

        self.assertEqual(self.run_quiet(self.chain.finalize)[0], 0)
        bundle = fx.read_json(self.chain.bundle_path)
        self.assertEqual(bundle["provenance_artifacts"], manifest["provenance_artifacts"])
        self.assertEqual(bundle["evidence_binding"], manifest["evidence_binding"])
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 0)
        self.assertEqual(self.chain.verification()["errors"], [])

    def test_provenance_declaration_mapping_is_normalized(self):
        chain = fx.Chain(
            Path(self.temporary.name) / "mapping",
            provenance_artifacts=fx.PROVENANCE_FILES,
        )
        self.assertEqual(self.run_quiet(chain.prepare)[0], 0)
        manifest = fx.read_json(chain.workspace / "prepare-manifest.json")
        self.assertEqual(len(manifest["provenance_artifacts"]), len(fx.PROVENANCE_FILES))

    def test_provenance_path_escape_is_rejected_before_reports(self):
        chain = fx.Chain(
            Path(self.temporary.name) / "escape",
            provenance_artifacts=[{"artifact_id": "outside", "path": "../outside.json"}],
        )
        code, stderr = self.run_quiet(chain.prepare)
        self.assertEqual(code, 3)
        self.assertIn("越出输入目录", stderr)
        self.assertFalse((chain.workspace / "raw").exists())

    def test_duplicate_provenance_id_is_rejected(self):
        chain = fx.Chain(
            Path(self.temporary.name) / "duplicate",
            provenance_artifacts=[
                {"artifact_id": "same", "path": "search-query.json"},
                {"artifact_id": "same", "path": "template-candidates.json"},
            ],
        )
        code, stderr = self.run_quiet(chain.prepare)
        self.assertEqual(code, 3)
        self.assertIn("重复 artifact_id", stderr)

    def test_verifier_rejects_bundle_provenance_different_from_manifest(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        self.chain.rewrite_json(
            self.chain.bundle_path,
            lambda bundle: bundle["provenance_artifacts"].pop(),
        )
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        self.assertTrue(any("provenance_artifacts" in item["message"] for item in self.chain.verification()["errors"]))

    def test_verifier_rejects_provenance_binding_tamper(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        self.chain.rewrite_json(
            self.chain.bundle_path,
            lambda bundle: bundle["evidence_binding"].update(provenance_set_sha256="0" * 64),
        )
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        self.assertTrue(any("provenance_set_sha256" in item["message"] for item in self.chain.verification()["errors"]))

    def test_semantic_input_provenance_must_match_prepare_manifest(self):
        self.run_quiet(self.chain.prepare)
        template = fx.read_json(self.chain.template_path)
        template["provenance_artifacts"].pop()
        stale = self.chain.root / "stale-semantic-input.json"
        stale.write_bytes(json.dumps(template, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
        code, stderr = self.run_quiet(self.chain.finalize, review_input=stale)
        self.assertEqual(code, 3)
        self.assertIn("provenance_artifacts", stderr)

    def test_verifier_malformed_provenance_id_returns_structured_error(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        self.chain.rewrite_json(
            self.chain.bundle_path,
            lambda bundle: bundle["provenance_artifacts"][0].update(artifact_id=[]),
        )
        code, _ = self.run_quiet(self.chain.verify)
        self.assertEqual(code, 3)
        errors = self.chain.verification()["errors"]
        self.assertTrue(any("artifact_id" in item["message"] for item in errors))


class ContractVersusApplicationDefectTests(ChainTestCase):
    """合同缺陷与申请文件缺陷必须分离：工具故障不得写成中国专利法结论。"""

    def test_contract_defect_produces_verifier_rule_ids_only(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        # 证据仍为 NONE/MISSING 却给出 NO_ISSUE_FOUND，是明确非法的状态组合。
        self.chain.rewrite_json(
            self.chain.bundle_path,
            lambda bundle: bundle["assessments"][0].update(result="NO_ISSUE_FOUND", coverage="FULL"),
        )
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        verification = self.chain.verification()
        self.assertIsNone(verification["disposition"])
        citations = {item["citation"] for item in CONTRACT.data["dimensions"]}
        for error in verification["errors"]:
            self.assertTrue(error["rule_id"].startswith("CN-VERIFY-"))
            for citation in citations:
                self.assertNotIn(citation, error["message"], "工具错误不得伪造中国专利法引用")

    def test_application_defect_stays_a_legal_finding_with_a_legal_rule_id(self):
        chain = fx.Chain(
            Path(self.temporary.name) / "defective",
            claims="1. 一种装置，包括控制器，TODO 待补充。\n",
        )
        self.assertEqual(self.run_quiet(chain.prepare)[0], 2)
        self.run_quiet(chain.finalize)
        self.assertEqual(self.run_quiet(chain.verify)[0], 0)
        bundle = fx.read_json(chain.bundle_path)
        deterministic = [
            item for subreport in bundle["subreports"] for item in subreport["findings"]
            if item["status"] == "DETERMINISTIC_FAIL"
        ]
        self.assertTrue(deterministic, "申请文件缺陷必须保留为确定性 finding")
        for item in deterministic:
            self.assertIn(item["dimension_id"], CONTRACT.dimension_ids)
            self.assertFalse(item["rule_id"].startswith("CN-VERIFY-"))

    def test_producer_cannot_inject_overall_conclusions_at_any_depth(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        for mutation in (
            lambda bundle: bundle.update(overall_status="PASS"),
            lambda bundle: bundle["subreports"][0].update(verdict="通过"),
            lambda bundle: bundle["assessments"][0].update(ready_to_file=True),
        ):
            with self.subTest(mutation=str(mutation)):
                self.chain.rewrite_json(self.chain.bundle_path, mutation)
                self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
                self.assertTrue(any(
                    "禁止的生产者结论字段" in item["message"] or "合同未定义的字段" in item["message"]
                    for item in self.chain.verification()["errors"]
                ))
                self.run_quiet(self.chain.finalize)


class SearchEvidenceBoundaryTests(ChainTestCase):
    """搜索清单只作只读消费；不得据此宣称新颖性或创造性成立。"""

    def setUp(self) -> None:
        super().setUp()
        self.run_quiet(self.chain.prepare)

    def cleared_assessment(self, dimension_id: str, mode: str, artifact_ids: list[str]) -> Path:
        template = fx.read_json(self.chain.template_path)
        for assessment in template["assessments"]:
            if assessment["rule_id"] == dimension_id:
                assessment.update({
                    "coverage": "FULL", "result": "NO_ISSUE_FOUND", "severity": "NONE",
                    "evidence": {
                        "mode": mode, "sufficiency": "ADEQUATE_FOR_SCOPED_ASSESSMENT",
                        "artifact_ids": artifact_ids, "source_locations": [],
                    },
                    "finding_ids": [], "gap_ids": [],
                })
        template["semantic_gaps"] = [
            item for item in template["semantic_gaps"] if item["dimension_id"] != dimension_id
        ]
        path = self.chain.workspace / f"review-{dimension_id}-{mode}-{len(artifact_ids)}.json"
        fx.write_json(path, template)
        return path

    def test_novelty_or_inventiveness_cleared_without_prior_art_comparison_is_rejected(self):
        for dimension_id in ("novelty", "inventiveness"):
            with self.subTest(dimension=dimension_id):
                review = self.cleared_assessment(dimension_id, "DOCUMENTARY_SEMANTIC", [])
                self.assertEqual(self.run_quiet(self.chain.finalize, review_input=review)[0], 0)
                self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
                messages = " ".join(item["message"] for item in self.chain.verification()["errors"])
                self.assertIn("搜索清单的结构有效性不证明该维度成立", messages)

    def test_prior_art_comparison_must_bind_declared_artifacts(self):
        review = self.cleared_assessment("novelty", "PRIOR_ART_COMPARISON", [])
        self.run_quiet(self.chain.finalize, review_input=review)
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        self.assertTrue(any("未绑定任何证据工件" in item["message"] for item in self.chain.verification()["errors"]))

        review = self.cleared_assessment("novelty", "PRIOR_ART_COMPARISON", ["不存在的对比文件"])
        self.run_quiet(self.chain.finalize, review_input=review)
        self.assertEqual(self.run_quiet(self.chain.verify)[0], 3)
        self.assertTrue(any("未声明的工件" in item["message"] for item in self.chain.verification()["errors"]))

    def test_contract_records_that_search_manifest_establishes_nothing(self):
        compatibility = CONTRACT.data["search_manifest_compatibility"]
        self.assertEqual(compatibility["mode"], "READ_ONLY_CONSUMER")
        self.assertEqual(compatibility["accepted_schema"], "cn-patent-search-manifest/v1")
        for value in ("novelty", "inventiveness", "single_reference_completeness",
                      "conflicting_application_status", "claim_effective_date", "search_completeness"):
            self.assertIn(value, compatibility["does_not_establish"])


class StateAndDispositionTests(unittest.TestCase):
    """状态组合、聚合顺序无关性和处置优先级由合同驱动。"""

    def test_illegal_state_combinations_are_all_rejected(self):
        enums = CONTRACT.data["enums"]
        legal = set(CONTRACT.legal_state_combinations())
        checked = 0
        for coverage in enums["coverage"]:
            for result in enums["result_atomic"]:
                for mode in enums["evidence_mode"]:
                    for sufficiency in enums["evidence_sufficiency"]:
                        for severity in enums["severity"]:
                            combination = (coverage, result, mode, sufficiency, severity)
                            errors = CONTRACT.state_axis_errors(*combination)
                            self.assertEqual(bool(errors), combination not in legal)
                            checked += 1
        self.assertEqual(checked, 1440)
        self.assertEqual(len(legal), 61)

    def test_aggregation_is_independent_of_producer_order(self):
        children = [
            {"assessment_id": f"A-{index}", "coverage": coverage, "result": result,
             "severity": severity, "finding_ids": [f"F{index}"], "gap_ids": [f"G{index}"]}
            for index, (coverage, result, severity) in enumerate([
                ("FULL", "NO_ISSUE_FOUND", "NONE"),
                ("PARTIAL", "ISSUE_FOUND", "HIGH"),
                ("NONE", "INCONCLUSIVE", "NONE"),
                ("NOT_APPLICABLE", "NOT_APPLICABLE", "NONE"),
            ])
        ]
        reference = CONTRACT.aggregate(children)
        for rotation in range(len(children)):
            rotated = children[rotation:] + children[:rotation]
            self.assertEqual(CONTRACT.aggregate(rotated), reference)
        self.assertEqual(reference["result"], "MIXED")
        self.assertEqual(reference["coverage"], "NONE")
        self.assertEqual(reference["severity"], "HIGH")

    def test_disposition_priority_matches_the_contract_order(self):
        adequate = {"mode": "DETERMINISTIC", "sufficiency": "ADEQUATE_FOR_SCOPED_ASSESSMENT",
                    "artifact_ids": [], "source_locations": []}
        missing = {"mode": "NONE", "sufficiency": "MISSING", "artifact_ids": [], "source_locations": []}
        clean = {"assessment_id": "A", "coverage": "FULL", "result": "NO_ISSUE_FOUND",
                 "severity": "NONE", "evidence": adequate, "finding_ids": [], "gap_ids": []}
        unassessed = {**clean, "assessment_id": "B", "coverage": "NONE", "result": "INCONCLUSIVE",
                      "evidence": missing, "gap_ids": ["G1"]}
        blocker = {**clean, "assessment_id": "C", "result": "ISSUE_FOUND", "severity": "BLOCKER",
                   "finding_ids": ["F1"]}
        remediation = {**blocker, "assessment_id": "D", "severity": "MEDIUM"}

        self.assertEqual(CONTRACT.derive_disposition([unassessed]), "NOT_ASSESSED")
        self.assertEqual(CONTRACT.derive_disposition([clean, blocker]), "BLOCKING_ISSUE_FOUND")
        self.assertEqual(CONTRACT.derive_disposition([clean, unassessed]), "REVIEW_INCOMPLETE")
        self.assertEqual(CONTRACT.derive_disposition([clean, remediation]), "REMEDIATION_REQUIRED")
        self.assertEqual(CONTRACT.derive_disposition([clean]), "NO_BLOCKING_ISSUE_FOUND_IN_SCOPE")
        self.assertIsNone(CONTRACT.derive_disposition([clean], ["CONTRACT_ERROR"]))

    def test_conditional_dimensions_cannot_silently_disappear(self):
        conditional = CONTRACT.dimensions_in_group("conditional_special_domain")
        self.assertEqual(len(conditional), 3)
        for dimension_id in conditional:
            self.assertIn(dimension_id, CONTRACT.dimension_ids)

    def test_priority_and_grace_period_dimensions_are_present(self):
        group = CONTRACT.dimensions_in_group("priority_and_grace")
        self.assertEqual(len(group), 4)
        for dimension_id in ("priority_entitlement_effective_date", "claim_level_priority",
                             "partial_multiple_priority", "article_24_grace_period"):
            self.assertIn(dimension_id, group)


class ResourceLimitAndEncodingTests(ChainTestCase):
    def test_bom_input_is_rejected_before_any_report_is_produced(self):
        target = self.chain.application_directory / "claims.txt"
        target.write_bytes(b"\xef\xbb\xbf" + fx.CLAIMS_TEXT.encode("utf-8"))
        code, stderr = self.run_quiet(self.chain.prepare)
        self.assertEqual(code, 3)
        self.assertIn("BOM", stderr)
        self.assertFalse((self.chain.workspace / "raw").exists())

    def test_oversized_input_is_a_tool_error_not_a_legal_finding(self):
        claims_module = fx.load_module("claims", "cn_claims_checker")
        with mock.patch.object(claims_module, "MAX_INPUT_BYTES", 8):
            code, stderr = self.run_quiet(self.chain.prepare)
        self.assertEqual(code, 4)
        self.assertIn("资源", stderr)
        self.assertFalse(self.chain.bundle_path.exists())

    def test_extreme_claim_number_is_rejected_without_allocating_memory(self):
        target = self.chain.application_directory / "claims.txt"
        target.write_bytes("999999999. 一种装置。\n".encode("utf-8"))
        code, _ = self.run_quiet(self.chain.prepare)
        self.assertEqual(code, 4)

    def test_orchestration_deadline_is_enforced(self):
        """超时是工具错误：退出码 4，且不产出 bundle。"""

        self.run_quiet(self.chain.prepare)
        orchestrator = self.chain.orchestrator
        readings = iter([0.0])

        def slow_clock():
            return next(readings, float(CONTRACT.limits["orchestration_deadline_seconds"] + 1))

        with mock.patch.object(orchestrator.time, "monotonic", slow_clock):
            code, stderr = self.run_quiet(self.chain.finalize)
        self.assertEqual(code, 4)
        self.assertIn("时限", stderr)
        self.assertFalse(self.chain.bundle_path.exists())

    def test_declared_limits_never_contradict_the_contract(self):
        self.run_quiet(self.chain.prepare)
        for review_type in ("claims", "specification", "formalities"):
            report = fx.read_json(self.chain.raw_path(review_type))
            for key, value in report["resource_limits"].items():
                self.assertEqual(CONTRACT.limits[key], value, f"{review_type}.{key}")


class OutputProtectionTests(ChainTestCase):
    def test_outputs_cannot_overwrite_evidence_or_its_aliases(self):
        self.run_quiet(self.chain.prepare)
        evidence = self.chain.application_directory / "claims.txt"
        original = evidence.read_bytes()
        code, stderr = self.run_quiet(self.chain.finalize, output=evidence)
        self.assertEqual(code, 3)
        self.assertIn("冲突", stderr)
        self.assertEqual(evidence.read_bytes(), original)

        alias = self.chain.application_directory / "claims-hardlink.txt"
        try:
            os.link(evidence, alias)
        except OSError as exc:
            self.skipTest(f"当前文件系统不支持硬链接：{exc}")
        code, _ = self.run_quiet(self.chain.finalize, output=alias)
        self.assertEqual(code, 3)
        self.assertEqual(evidence.read_bytes(), original)

    def test_verifier_output_cannot_overwrite_the_bundle(self):
        self.run_quiet(self.chain.prepare)
        self.run_quiet(self.chain.finalize)
        original = self.chain.bundle_path.read_bytes()
        code, _ = self.run_quiet(
            self.chain.verifier.main,
            ["--workspace", str(self.chain.workspace), "--bundle", str(self.chain.bundle_path),
             "--output", str(self.chain.bundle_path)],
        )
        self.assertEqual(code, 3)
        self.assertEqual(self.chain.bundle_path.read_bytes(), original)


class IsolationTests(unittest.TestCase):
    """无网络、无模型、无索引、无新依赖，且检索树保持冻结。"""

    def test_cn_scripts_import_standard_library_only(self):
        for relative in CN_SCRIPT_PATHS:
            with self.subTest(script=relative):
                source = (fx.ROOT / relative).read_text(encoding="utf-8")
                for forbidden in FORBIDDEN_IMPORTS:
                    self.assertNotIn(f"import {forbidden}", source, f"{relative} 不得引入 {forbidden}")
                    self.assertNotIn(f"from {forbidden}", source, f"{relative} 不得引入 {forbidden}")

    def test_cn_scripts_never_reference_network_or_model_downloads(self):
        for relative in CN_SCRIPT_PATHS:
            with self.subTest(script=relative):
                source = (fx.ROOT / relative).read_text(encoding="utf-8")
                for marker in ("urlopen", "pip install", "from_pretrained", "hf_hub", "IndexFlat"):
                    self.assertNotIn(marker, source, f"{relative} 不得出现 {marker}")

    def test_generic_search_and_rag_trees_are_not_bundled(self):
        forbidden = (
            "mcp_server",
            "skills/bigquery-patent-search",
            "skills/patent-search",
            "skills/prior-art-search",
            "skills/mpep-search",
            "skills/epc-search",
            "skills/epo-patent-search",
            "skills/index-manager",
        )
        for path in forbidden:
            with self.subTest(path=path):
                self.assertFalse((fx.ROOT / path).exists(), f"独立 CN Skill 包不得包含 {path}")


class ProhibitedConclusionTests(ChainTestCase):
    def test_no_artifact_in_the_chain_claims_overall_pass(self):
        self.run_quiet(self.chain.run)
        artifacts = [
            self.chain.bundle_path, self.chain.verification_path, self.chain.summary_path,
            self.chain.workspace / "prepare-manifest.json", self.chain.template_path,
            *(self.chain.raw_path(value) for value in ("claims", "specification", "formalities")),
        ]
        for path in artifacts:
            with self.subTest(artifact=path.name):
                text = path.read_text(encoding="utf-8")
                for phrase in FORBIDDEN_PHRASES:
                    self.assertNotIn(phrase, text, f"{path.name} 不得出现结论性措辞：{phrase}")

    def test_every_artifact_declares_advisory_only(self):
        self.run_quiet(self.chain.run)
        for path in (
            self.chain.bundle_path, self.chain.verification_path,
            *(self.chain.raw_path(value) for value in ("claims", "specification", "formalities")),
        ):
            with self.subTest(artifact=path.name):
                self.assertEqual(fx.read_json(path)["legal_effect"], "ADVISORY_ONLY")

    def test_no_artifact_is_written_with_a_bom(self):
        self.run_quiet(self.chain.run)
        for path in sorted(self.chain.workspace.rglob("*")):
            if path.is_file():
                with self.subTest(artifact=path.name):
                    self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"), f"{path.name} 含 BOM")

if __name__ == "__main__":
    unittest.main()
