"""CN v2 review contract regression tests."""

from __future__ import annotations

import itertools
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "skills/cn-patent-reviewer/references/cn-review-contract-v2.json"

EXPECTED_DIMENSIONS = {
    "article_5", "article_25", "technical_solution", "utility", "disclosure",
    "novelty", "inventiveness", "claim_clarity", "claim_support", "essential_features",
    "unity", "amendment_scope", "divisional_scope", "same_invention",
    "foreign_filing_confidentiality", "genetic_resource_disclosure", "good_faith",
    "priority_entitlement_effective_date", "claim_level_priority",
    "partial_multiple_priority", "article_24_grace_period",
    "form_core_documents_and_application_type", "form_request_fields_and_party_identity",
    "form_language_format_and_execution", "form_title_consistency_and_quality",
    "form_specification_structure_and_drafting", "form_claim_presentation_and_reference_form",
    "form_abstract_content_and_length", "form_abstract_figure_designation",
    "form_drawings_requiredness_and_presence",
    "form_drawing_numbering_reference_signs_and_graphic_form", "form_sequence_listing",
    "form_biological_material_deposit", "form_genetic_resource_statement",
    "form_priority_declaration_and_documents", "form_article_24_declaration_and_proof",
    "form_divisional_filing_procedure", "form_substantive_examination_request_procedure",
    "computer_and_ai", "chemical_and_biotech", "traditional_chinese_medicine",
}


def load_contract() -> dict:
    with CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def tuple_errors(coverage: str, result: str, mode: str, sufficiency: str, severity: str) -> list[str]:
    """Mirror the v2 core state invariants for all 1,440 enum combinations."""

    errors: list[str] = []
    if (coverage == "NOT_APPLICABLE") != (result == "NOT_APPLICABLE"):
        errors.append("not_applicable_pair")
    if coverage == "NONE" and (result, mode, sufficiency) != ("INCONCLUSIVE", "NONE", "MISSING"):
        errors.append("none_requires_missing")
    if coverage == "PARTIAL" and result not in {"ISSUE_FOUND", "INCONCLUSIVE"}:
        errors.append("partial_cannot_clear")
    if (mode == "NONE") != (sufficiency == "MISSING"):
        errors.append("none_mode_iff_missing")
    if mode == "HEURISTIC" and (sufficiency, result) != ("LIMITED", "INCONCLUSIVE"):
        errors.append("heuristic_inconclusive")
    if sufficiency in {"LIMITED", "MISSING"} and result != "INCONCLUSIVE":
        errors.append("limited_missing_inconclusive")
    if result == "NO_ISSUE_FOUND" and not (
        coverage == "FULL"
        and sufficiency == "ADEQUATE_FOR_SCOPED_ASSESSMENT"
        and mode not in {"HEURISTIC", "NONE"}
        and severity == "NONE"
    ):
        errors.append("no_issue_requirements")
    if result == "ISSUE_FOUND" and not (
        coverage in {"FULL", "PARTIAL"}
        and sufficiency == "ADEQUATE_FOR_SCOPED_ASSESSMENT"
        and mode not in {"HEURISTIC", "NONE"}
        and severity != "NONE"
    ):
        errors.append("issue_requirements")
    if result == "INCONCLUSIVE" and severity != "NONE":
        errors.append("inconclusive_severity")
    if result == "NOT_APPLICABLE" and severity != "NONE":
        errors.append("not_applicable_severity")
    return errors


def aggregate(assessments: list[dict]) -> dict:
    """Reference aggregation: sorting makes results independent of producer order."""

    children = sorted(assessments, key=lambda item: item["assessment_id"])
    present_results = sorted({item["result"] for item in children})
    coverage = "NOT_APPLICABLE"
    for candidate in ("NONE", "PARTIAL", "FULL"):
        if any(item["coverage"] == candidate for item in children):
            coverage = candidate
            break
    severity = next(
        candidate
        for candidate in ("BLOCKER", "HIGH", "MEDIUM", "LOW", "NONE")
        if any(item["severity"] == candidate for item in children)
    )
    return {
        "child_ids": [item["assessment_id"] for item in children],
        "present_results": present_results,
        "result": present_results[0] if len(present_results) == 1 else "MIXED",
        "coverage": coverage,
        "severity": severity,
        "finding_ids": sorted({value for item in children for value in item["finding_ids"]}),
        "gap_ids": sorted({value for item in children for value in item["gap_ids"]}),
    }


def derive_disposition(assessments: list[dict], verifier_errors: list[str] | None = None) -> str | None:
    """Reference the fixed verifier-only disposition priority."""

    if verifier_errors:
        return None
    if all(item["coverage"] == "NONE" for item in assessments):
        return "NOT_ASSESSED"
    if any(item["result"] == "ISSUE_FOUND" and item["severity"] == "BLOCKER" for item in assessments):
        return "BLOCKING_ISSUE_FOUND"
    if any(
        item["result"] == "INCONCLUSIVE"
        or item["gap_ids"]
        or item["sufficiency"] in {"LIMITED", "MISSING"}
        for item in assessments
    ):
        return "REVIEW_INCOMPLETE"
    if any(item["result"] == "ISSUE_FOUND" for item in assessments):
        return "REMEDIATION_REQUIRED"
    return "NO_BLOCKING_ISSUE_FOUND_IN_SCOPE"


class ContractV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract()

    def test_exact_contract_identity_scope_and_raw_fields(self):
        contract = self.contract
        self.assertEqual(contract["schema_version"], "cn-patent-review-contract/v2")
        self.assertEqual(contract["jurisdiction"], "CN")
        self.assertEqual(contract["legal_effect"], "ADVISORY_ONLY")
        self.assertEqual(
            contract["schema_ids"],
            {
                "contract": "cn-patent-review-contract/v2",
                "raw_report": "cn-patent-review-raw-report/v2",
                "subreport": "cn-patent-review-subreport/v2",
                "bundle": "cn-patent-review-bundle/v2",
                "verifier_output": "cn-patent-review-verification/v2",
            },
        )
        self.assertEqual(contract["scope"]["included"], ["direct_cn_invention_application"])
        self.assertEqual(contract["scope"]["excluded"], ["pct_national_phase"])
        self.assertEqual(
            contract["exact_fields"]["atomic_assessment"],
            ["assessment_id", "rule_id", "target_id", "coverage", "result", "evidence", "severity", "finding_ids", "gap_ids"],
        )
        self.assertEqual(
            contract["exact_fields"]["dimension"],
            ["id", "group", "citation", "applicability", "required_evidence", "non_inference_boundary"],
        )
        self.assertEqual(
            contract["exact_fields"]["raw_check"],
            ["check_id", "rule_id", "target_id", "status", "finding_ids", "gap_ids"],
        )
        self.assertEqual(contract["enums"]["review_type"], ["claims", "specification", "formalities"])
        self.assertEqual(contract["enums"]["raw_check_status"], ["COMPLETED", "PARTIAL", "SKIPPED", "NOT_VERIFIED"])
        self.assertEqual(
            contract["enums"]["gap_category"],
            ["INPUT_UNAVAILABLE", "PARSE_UNRESOLVED", "CAPABILITY_LIMIT", "SEARCH_EVIDENCE_MISSING", "CONDITIONAL_APPLICABILITY_UNRESOLVED", "SEMANTIC_REVIEW_NOT_PERFORMED"],
        )
        self.assertEqual(
            contract["exact_fields"]["raw_evidence_binding"],
            ["input_set_sha256", "rule_set_sha256", "tool_set_sha256"],
        )
        self.assertEqual(
            contract["exact_fields"]["bundle_evidence_binding"],
            ["input_set_sha256", "provenance_set_sha256", "rule_set_sha256", "tool_set_sha256", "raw_report_set_sha256"],
        )
        self.assertEqual(contract["optional_fields"]["bundle"], ["provenance_artifacts"])
        self.assertEqual(contract["optional_fields"]["bundle_evidence_binding"], ["provenance_set_sha256"])
        self.assertIn("finding_id", contract["exact_fields"]["raw_finding"])
        self.assertIn("gap_id", contract["exact_fields"]["raw_gap"])
        self.assertEqual(contract["exact_fields"]["raw_evidence"], ["artifact_id", "location", "excerpt"])
        self.assertEqual(
            contract["exact_fields"]["resource_usage"],
            ["input_bytes_total", "output_bytes", "finding_count", "gap_count", "check_count", "elapsed_milliseconds"],
        )
        self.assertEqual(
            contract["field_relationships"]["raw_report.schema_version"],
            "schema_ids.raw_report",
        )
        self.assertEqual(
            contract["field_relationships"]["raw_finding.evidence[]"],
            "exact_fields.raw_evidence",
        )
        self.assertEqual(
            contract["exact_field_policy"],
            {
                "required_fields_equal_allowed_fields": True,
                "reject_unknown_fields": True,
                "reject_missing_fields": True,
            },
        )
        self.assertEqual(contract["resource_limits"]["failure_exit_code"], 4)

    def test_exact_41_dimension_set_and_group_counts(self):
        dimensions = self.contract["dimensions"]
        self.assertEqual({item["id"] for item in dimensions}, EXPECTED_DIMENSIONS)
        self.assertEqual(len(dimensions), 41)
        self.assertEqual(sum(item["group"] == "substantive_core" for item in dimensions), 17)
        self.assertEqual(sum(item["group"] == "priority_and_grace" for item in dimensions), 4)
        self.assertEqual(sum(item["group"] == "formalities" for item in dimensions), 17)
        conditional = [item for item in dimensions if item["group"] == "conditional_special_domain"]
        self.assertEqual(len(conditional), 3)
        expected_fields = set(self.contract["exact_fields"]["dimension"])
        for dimension in dimensions:
            self.assertEqual(set(dimension), expected_fields)
            self.assertTrue(all(isinstance(dimension[key], str) and dimension[key].strip() for key in expected_fields))
        self.assertNotIn("priority_formalities", EXPECTED_DIMENSIONS)

    def test_rule_dimension_map_covers_claim_structure_and_tool_only_rules(self):
        mapping = self.contract["rule_dimension_map"]
        self.assertEqual(mapping["CN-CLAIM-MULTI-001"], "form_claim_presentation_and_reference_form")
        self.assertEqual(mapping["CN-CLAIM-LENGTH-001"], "form_claim_presentation_and_reference_form")
        self.assertEqual(mapping["CN-CLAIM-LENGTH-002"], "form_claim_presentation_and_reference_form")
        self.assertEqual(mapping["CN-CLAIM-LENGTH-003"], "form_claim_presentation_and_reference_form")
        self.assertEqual(mapping["CN-CLAIM-CORE-001"], "form_claim_presentation_and_reference_form")
        self.assertEqual(mapping["CN-CLAIM-REF-001"], "form_claim_presentation_and_reference_form")
        self.assertEqual(mapping["CN-CLAIM-FUNCTION-001"], "claim_support")
        self.assertEqual(mapping["CN-CLAIM-DEPENDENT-001"], "claim_clarity")
        self.assertTrue(set(mapping.values()).issubset(EXPECTED_DIMENSIONS))
        tool_only = set(self.contract["tool_only_rules"])
        self.assertIn("CN-CLAIM-OUTPUT-001", tool_only)
        self.assertIn("CN-CLAIM-RESOURCE-001", tool_only)
        self.assertTrue(tool_only.isdisjoint(mapping))
        good_faith = next(item for item in self.contract["dimensions"] if item["id"] == "good_faith")
        self.assertIn("实施细则第十一条", good_faith["citation"])
        claim_form = next(item for item in self.contract["dimensions"] if item["id"] == "form_claim_presentation_and_reference_form")
        self.assertIn("第二十二条至第二十五条", claim_form["citation"])
        drawings = next(item for item in self.contract["dimensions"] if item["id"] == "form_drawings_requiredness_and_presence")
        self.assertIn("第四十六条", drawings["citation"])
        self.assertNotIn("第四十三条至第四十六条", drawings["citation"])

    def test_all_1440_atomic_state_combinations_apply_invariants(self):
        enums = self.contract["enums"]
        combinations = list(itertools.product(
            enums["coverage"], enums["result_atomic"], enums["evidence_mode"],
            enums["evidence_sufficiency"], enums["severity"],
        ))
        self.assertEqual(len(combinations), 4 * 4 * 6 * 3 * 5)
        results = {combo: tuple_errors(*combo) for combo in combinations}
        self.assertEqual(sum(not errors for errors in results.values()), 61)
        self.assertEqual(results[("FULL", "NO_ISSUE_FOUND", "DETERMINISTIC", "ADEQUATE_FOR_SCOPED_ASSESSMENT", "NONE")], [])
        self.assertEqual(results[("PARTIAL", "ISSUE_FOUND", "DOCUMENTARY_SEMANTIC", "ADEQUATE_FOR_SCOPED_ASSESSMENT", "HIGH")], [])
        self.assertEqual(results[("NONE", "INCONCLUSIVE", "NONE", "MISSING", "NONE")], [])
        self.assertEqual(results[("NOT_APPLICABLE", "NOT_APPLICABLE", "DOCUMENTARY_SEMANTIC", "ADEQUATE_FOR_SCOPED_ASSESSMENT", "NONE")], [])
        self.assertTrue(results[("PARTIAL", "NO_ISSUE_FOUND", "DETERMINISTIC", "ADEQUATE_FOR_SCOPED_ASSESSMENT", "NONE")])
        self.assertTrue(results[("FULL", "ISSUE_FOUND", "HEURISTIC", "LIMITED", "HIGH")])
        self.assertTrue(results[("FULL", "NO_ISSUE_FOUND", "NONE", "MISSING", "NONE")])
        self.assertTrue(results[("NOT_APPLICABLE", "INCONCLUSIVE", "NONE", "MISSING", "NONE")])

    def test_aggregate_is_order_independent_and_mixed_is_aggregate_only(self):
        children = [
            {"assessment_id": "b", "coverage": "PARTIAL", "result": "ISSUE_FOUND", "severity": "HIGH", "finding_ids": ["F2"], "gap_ids": []},
            {"assessment_id": "a", "coverage": "FULL", "result": "INCONCLUSIVE", "severity": "NONE", "finding_ids": [], "gap_ids": ["G1"]},
        ]
        first = aggregate(children)
        second = aggregate(list(reversed(children)))
        self.assertEqual(first, second)
        self.assertEqual(first["result"], "MIXED")
        self.assertEqual(first["child_ids"], ["a", "b"])
        self.assertNotIn("MIXED", self.contract["enums"]["result_atomic"])

    def test_disposition_and_search_boundaries_are_locked(self):
        values = [item["value"] for item in self.contract["disposition"]]
        self.assertEqual(values, ["NOT_ASSESSED", "BLOCKING_ISSUE_FOUND", "REVIEW_INCOMPLETE", "REMEDIATION_REQUIRED", "NO_BLOCKING_ISSUE_FOUND_IN_SCOPE"])
        search = self.contract["search_manifest_compatibility"]
        self.assertEqual(search["accepted_schema"], "cn-patent-search-manifest/v1")
        self.assertEqual(search["mode"], "READ_ONLY_CONSUMER")
        self.assertIn("novelty", search["does_not_establish"])
        self.assertIn("inventiveness", search["does_not_establish"])

    def test_resource_limits_cover_each_amplification_axis(self):
        limits = self.contract["resource_limits"]
        required = {
            "claims_input_bytes", "claims_max_count", "claims_max_number",
            "claims_max_reference_edges", "claims_max_ancestor_depth", "claims_max_single_text_bytes",
            "specification_input_bytes", "specification_features_input_bytes", "specification_max_paragraphs",
            "specification_max_feature_candidates", "specification_max_variants_per_feature",
            "specification_max_matches_per_feature", "specification_max_total_matches",
            "formalities_input_bytes_total", "formalities_manifest_bytes",
            "formalities_max_documents", "formalities_max_single_document_bytes", "formalities_max_string_bytes",
            "verifier_referenced_bytes", "verifier_max_artifacts",
            "verifier_max_rule_sources", "verifier_max_raw_reports",
            "verifier_max_subreports", "verifier_max_single_artifact_bytes",
            "json_max_depth", "max_findings", "max_gaps", "max_checks",
            "max_report_output_bytes", "max_summary_output_bytes",
            "orchestration_deadline_seconds", "failure_exit_code", "failure_rule",
        }
        self.assertTrue(required.issubset(limits))
        self.assertEqual(limits["claims_input_bytes"], 4 * 1024 * 1024)
        self.assertEqual(limits["specification_input_bytes"], 8 * 1024 * 1024)
        self.assertEqual(limits["formalities_input_bytes_total"], 24 * 1024 * 1024)
        self.assertEqual(limits["verifier_referenced_bytes"], 128 * 1024 * 1024)
        self.assertEqual(limits["json_max_depth"], 64)
        self.assertEqual(limits["max_findings"], 5000)
        self.assertEqual(limits["failure_exit_code"], 4)
        self.assertEqual(limits["verifier_max_raw_reports"], 3)
        self.assertEqual(limits["verifier_max_subreports"], 3)

    def test_disposition_priority_is_not_a_producer_conclusion(self):
        base = {"coverage": "FULL", "result": "NO_ISSUE_FOUND", "severity": "NONE", "gap_ids": [], "sufficiency": "ADEQUATE_FOR_SCOPED_ASSESSMENT"}
        self.assertEqual(derive_disposition([{**base, "coverage": "NONE", "result": "INCONCLUSIVE", "sufficiency": "MISSING"}]), "NOT_ASSESSED")
        self.assertEqual(derive_disposition([{**base, "result": "ISSUE_FOUND", "severity": "BLOCKER"}, {**base, "result": "INCONCLUSIVE", "gap_ids": ["G1"]}]), "BLOCKING_ISSUE_FOUND")
        self.assertEqual(derive_disposition([{**base, "result": "ISSUE_FOUND", "severity": "HIGH"}, {**base, "result": "INCONCLUSIVE", "gap_ids": ["G1"]}]), "REVIEW_INCOMPLETE")
        self.assertEqual(derive_disposition([{**base, "result": "ISSUE_FOUND", "severity": "HIGH"}]), "REMEDIATION_REQUIRED")
        self.assertEqual(derive_disposition([base]), "NO_BLOCKING_ISSUE_FOUND_IN_SCOPE")
        self.assertIsNone(derive_disposition([base], ["CONTRACT_ERROR"]))
        error_handling = self.contract["verifier_error_handling"]
        self.assertIsNone(error_handling["application_disposition"])
        self.assertFalse(error_handling["legal_finding_allowed"])
        self.assertFalse(error_handling["legal_citation_allowed"])

    def test_contract_records_conservation_and_forbidden_producer_conclusions(self):
        conservation = self.contract["finding_conservation"]
        self.assertEqual(conservation["required_raw_reports"], ["claims", "specification", "formalities"])
        joined = " ".join(conservation["requirements"])
        self.assertIn("exactly once", joined)
        self.assertIn("cannot be omitted", joined)
        integrity = self.contract["id_integrity"]
        self.assertEqual(integrity["unique_within_raw_report"], ["check_id", "finding_id", "gap_id"])
        self.assertTrue(any("Dangling" in rule for rule in integrity["requirements"]))
        self.assertEqual(
            self.contract["prohibited_producer_fields"],
            ["overall_status", "overallResult", "decision", "verdict", "score", "complianceScore", "ready_to_file", "filingReadiness"],
        )


if __name__ == "__main__":
    unittest.main()
