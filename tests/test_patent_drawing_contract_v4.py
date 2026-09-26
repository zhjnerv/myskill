"""绘图合同 v4 的方法步骤、判断和循环同构回归。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/cn-patent-diagram-generator/scripts/validate_drawing_brief.py"
SCHEMA = ROOT / "skills/cn-patent-diagram-generator/references/patent-drawing-brief-schema-v4.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value: object) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fixture(tmp_path: Path) -> tuple[Path, Path]:
    claims = tmp_path / "权利要求书.md"
    spec = tmp_path / "说明书.md"
    ledger = tmp_path / "feature-ledger.json"
    architecture = tmp_path / "claim-architecture.json"
    write(
        claims,
        "1. 一种控制方法，其特征在于，包括以下步骤：\n"
        "S1，获取输入数据；\n"
        "S2，判断是否满足输出条件；\n"
        "S3，输出结果。\n",
    )
    write(
        spec,
        "步骤S1：获取输入数据。\n"
        "步骤S2：判断是否满足输出条件。\n"
        "若满足输出条件则输出结果；若未满足输出条件则返回获取输入数据。\n"
        "步骤S3：输出结果。\n",
    )
    write_json(ledger, {"schema_id": "cn-patent-feature-ledger/v2", "features": [{"feature_id": "F001"}]})
    write_json(
        architecture,
        {
            "schema_id": "cn-patent-claim-architecture/v1",
            "method_claims": [
                {
                    "claim_number": 1,
                    "steps": [
                        {"step_id": "S1", "order": 1, "action": "获取输入数据", "specification_anchor": "步骤S1：获取输入数据"},
                        {"step_id": "S2", "order": 2, "action": "判断是否满足输出条件", "specification_anchor": "步骤S2：判断是否满足输出条件"},
                        {"step_id": "S3", "order": 3, "action": "输出结果", "specification_anchor": "步骤S3：输出结果"},
                    ],
                    "decisions": [
                        {"decision_id": "D1", "after_step_id": "S2", "condition": "是否满足输出条件", "true_target_step_id": "S3", "false_target_step_id": "S1"}
                    ],
                    "loops": [{"from_step_id": "S2", "to_step_id": "S1", "condition": "未满足输出条件"}],
                }
            ],
        },
    )
    brief = tmp_path / "drawing-brief.json"
    payload = {
        "schema_id": "cn-patent-drawing-brief/v4",
        "case_id": "case",
        "production_skill": "drawio-skill",
        "source_artifacts": [
            {"artifact_id": "claims", "path": claims.name, "sha256": digest(claims)},
            {"artifact_id": "specification", "path": spec.name, "sha256": digest(spec)},
            {"artifact_id": "feature_ledger", "path": ledger.name, "sha256": digest(ledger)},
            {"artifact_id": "claim_architecture", "path": architecture.name, "sha256": digest(architecture)},
        ],
        "output_root": "drawings",
        "visual_review_path": "review/visual-review.json",
        "global_constraints": {
            "figure_number_on_canvas": False,
            "edge_labels_allowed": True,
            "annotation_nodes_may_be_edge_endpoints": False,
            "native_edge_labels_required": True,
            "separate_relation_label_nodes_allowed": False,
            "official_drawio_export_required": True,
            "visual_review_required": True,
            "single_primary_question_required": True,
            "independent_route_channels_required": True,
            "final_png_visual_review_required": True,
            "method_step_isomorphism_required": True,
            "source_text_binding_required": True,
            "minimum_png_dpi": 300,
            "png_margin_policy": {"crop_to_diagram_required": True, "target_border_pixels": 10, "maximum_margin_pixels": 20, "white_threshold": 245},
            "node_text_policy": {
                "reference_page_width": 827,
                "reference_page_height": 1169,
                "minimum_font_size": 14,
                "maximum_width_to_font_size_ratio": 18,
                "maximum_frame_to_text_height_ratio": 2,
                "maximum_chinese_characters_per_line": 12,
                "horizontal_padding": 8,
                "vertical_padding": 4,
                "line_height_factor": 1.2,
                "maximum_wrapped_lines": 4,
                "wrap_required": True,
                "font_autoshrink_allowed": False,
            },
            "vertical_spacing_policy": {
                "minimum_effective_blank_to_font_height_ratio": 2,
                "maximum_effective_blank_to_font_height_ratio": 3,
                "subtract_native_edge_label_text_height": True,
                "subtract_arrowhead_height": True,
                "default_edge_label_font_size": 12,
                "default_arrowhead_height": 6,
            },
            "node_shape_policy": {
                "cylinder_requires_data_store_kind": True,
                "cylinder_label_pattern": "存储|记录|数据库|数据表|缓存|仓库",
            },
            "relation_label_policy": {
                "minimum_font_to_node_font_ratio": 0.6666666666666666,
                "minimum_vertical_clearance_in_arrowhead_heights": 1,
                "default_arrowhead_height": 6,
                "centered_vertical_label_required": True,
                "vertical_label_center_tolerance": 0.1,
            },
            "color_policy": {"mode": "monochrome", "grayscale_safe": True, "color_semantics_redundant": True, "max_nonwhite_fills": 1, "allowed_fill_colors": ["#FFFFFF"], "allowed_stroke_colors": ["#000000"]},
        },
        "figures": [
            {
                "figure_number": 1,
                "title": "控制方法流程图",
                "file_stem": "图1-控制方法流程图",
                "diagram_type": "method_flowchart",
                "orientation": "portrait",
                "style_profile": "patent_monochrome",
                "purpose": "表示控制方法的步骤、判断与循环",
                "primary_question": "输入数据如何经判断后输出结果？",
                "reading_direction": "top_to_bottom",
                "layers": [
                    {"id": "L1", "title": "输入", "order": 1},
                    {"id": "L2", "title": "判断", "order": 2},
                    {"id": "L3", "title": "输出", "order": 3},
                ],
                "complexity_budget": {"max_technical_elements": 4, "max_relations": 4, "max_decisions": 1},
                "claim_numbers": [1],
                "spec_anchors": ["步骤S1：获取输入数据"],
                "elements": [
                    {"id": "STEP1", "label": "S1 获取输入数据", "kind": "step", "reference_sign": "S1", "source_anchor": "获取输入数据", "layer_id": "L1", "source_feature_ids": ["F001"]},
                    {"id": "STEP2", "label": "S2 判断是否满足输出条件", "kind": "step", "reference_sign": "S2", "source_anchor": "判断是否满足输出条件", "layer_id": "L2", "source_feature_ids": ["F001"]},
                    {"id": "DECIDE", "label": "是否满足输出条件", "kind": "decision", "source_anchor": "是否满足输出条件", "layer_id": "L2", "source_feature_ids": ["F001"]},
                    {"id": "STEP3", "label": "S3 输出结果", "kind": "step", "reference_sign": "S3", "source_anchor": "输出结果", "layer_id": "L3", "source_feature_ids": ["F001"]},
                ],
                "relations": [
                    {"id": "R12", "source": "STEP1", "target": "STEP2", "kind": "data", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "获取输入数据", "route_channel": "C1", "source_feature_ids": ["F001"]},
                    {"id": "R2D", "source": "STEP2", "target": "DECIDE", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "判断是否满足输出条件", "route_channel": "C2", "source_feature_ids": ["F001"]},
                    {"id": "R_TRUE", "source": "DECIDE", "target": "STEP3", "label": "是", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "满足输出条件则输出结果", "route_channel": "C3", "source_feature_ids": ["F001"]},
                    {"id": "R_FALSE", "source": "DECIDE", "target": "STEP1", "label": "否", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "未满足输出条件则返回获取输入数据", "route_channel": "C4", "source_feature_ids": ["F001"]},
                ],
                "normal_exit_ids": ["STEP3"],
                "exception_exit_ids": [],
                "spec_assertions": [
                    {"anchor": "若满足输出条件则输出结果；若未满足输出条件则返回获取输入数据", "element_ids": ["STEP1", "STEP2", "DECIDE", "STEP3"], "relation_ids": ["R12", "R2D", "R_TRUE", "R_FALSE"]}
                ],
                "method_claim_number": 1,
                "step_bindings": [
                    {"step_id": "S1", "element_id": "STEP1", "claim_action": "获取输入数据", "specification_anchor": "步骤S1：获取输入数据"},
                    {"step_id": "S2", "element_id": "STEP2", "claim_action": "判断是否满足输出条件", "specification_anchor": "步骤S2：判断是否满足输出条件"},
                    {"step_id": "S3", "element_id": "STEP3", "claim_action": "输出结果", "specification_anchor": "步骤S3：输出结果"},
                ],
                "decision_bindings": [{
                    "decision_id": "D1", "element_id": "DECIDE", "condition": "是否满足输出条件",
                    "true_branch": {"relation_id": "R_TRUE", "target_step_id": "S3", "label": "是"},
                    "false_branch": {"relation_id": "R_FALSE", "target_step_id": "S1", "label": "否"},
                }],
                "loop_bindings": [{"relation_id": "R_FALSE", "from_step_id": "S2", "to_step_id": "S1", "condition": "未满足输出条件"}],
                "outputs": {"drawio": "drawings/图1-控制方法流程图.drawio", "preview_png": "review/图1-preview.png", "final_png": "drawings/图1-控制方法流程图.png", "export_report": "review/图1-export.json"},
            }
        ],
    }
    write_json(brief, payload)
    return brief, tmp_path / "report.json"


def run(brief: Path, output: Path):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--brief", str(brief), "--case-dir", str(brief.parent), "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )


def codes(output: Path) -> set[str]:
    return {item["code"] for item in json.loads(output.read_text(encoding="utf-8"))["errors"]}


def test_v4_schema_is_utf8_json():
    raw = SCHEMA.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    schema = json.loads(raw.decode("utf-8"))
    assert schema["$id"] == "cn-patent-drawing-brief/v4"
    constraints = schema["properties"]["global_constraints"]["properties"]
    assert constraints["edge_labels_allowed"]["const"] is True
    assert constraints["native_edge_labels_required"]["const"] is True
    assert constraints["separate_relation_label_nodes_allowed"]["const"] is False
    assert "node_text_policy" in constraints
    node_text_policy = constraints["node_text_policy"]
    assert node_text_policy["properties"]["maximum_frame_to_text_height_ratio"]["maximum"] == 2
    assert node_text_policy["properties"]["maximum_chinese_characters_per_line"]["maximum"] == 12
    assert "maximum_height_to_font_size_ratio" not in node_text_policy["properties"]
    spacing_policy = constraints["vertical_spacing_policy"]
    assert spacing_policy["properties"]["minimum_effective_blank_to_font_height_ratio"]["const"] == 2
    assert spacing_policy["properties"]["maximum_effective_blank_to_font_height_ratio"]["const"] == 3
    assert spacing_policy["properties"]["subtract_native_edge_label_text_height"]["const"] is True
    assert spacing_policy["properties"]["subtract_arrowhead_height"]["const"] is True
    assert spacing_policy["properties"]["default_arrowhead_height"]["const"] == 6
    shape_policy = constraints["node_shape_policy"]
    assert shape_policy["properties"]["cylinder_requires_data_store_kind"]["const"] is True
    label_policy = constraints["relation_label_policy"]
    assert label_policy["properties"]["minimum_font_to_node_font_ratio"]["minimum"] == 2 / 3
    assert label_policy["properties"]["minimum_vertical_clearance_in_arrowhead_heights"]["minimum"] == 1
    outputs = schema["properties"]["figures"]["items"]["properties"]["outputs"]["properties"]
    assert "svg" not in outputs


def test_v4_rejects_weakened_node_and_spacing_limits(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    policy = payload["global_constraints"]["node_text_policy"]
    policy["maximum_frame_to_text_height_ratio"] = 2.1
    policy["maximum_chinese_characters_per_line"] = 13
    payload["global_constraints"]["vertical_spacing_policy"]["minimum_effective_blank_to_font_height_ratio"] = 1.5
    payload["global_constraints"]["relation_label_policy"]["minimum_font_to_node_font_ratio"] = 0.5
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    found = codes(output)
    assert "BRIEF-NODE-TEXT-POLICY" in found
    assert "BRIEF-VERTICAL-SPACING-POLICY" in found
    assert "BRIEF-RELATION-LABEL-POLICY" in found


def test_v4_method_flowchart_passes(tmp_path):
    brief, output = fixture(tmp_path)
    result = run(brief, output)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"


def test_v4_missing_claim_step_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["step_bindings"].pop()
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-STEP-ISOMORPHISM" in codes(output)


def test_v4_summary_label_instead_of_claim_text_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["elements"][1]["label"] = "S2 处理数据"
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-STEP-TEXT" in codes(output)


def test_v4_merged_claim_steps_are_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["step_bindings"][1]["claim_action"] = "判断是否满足输出条件并输出结果"
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-STEP-TEXT" in codes(output)


def test_v4_wrong_loop_target_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["loop_bindings"][0]["to_step_id"] = "S3"
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-LOOP-ISOMORPHISM" in codes(output)


def test_v4_stale_claim_architecture_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    architecture = tmp_path / "claim-architecture.json"
    architecture.write_text(architecture.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-SOURCE-STALE" in codes(output)

def test_v4_extra_unbound_step_element_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["elements"].append(
        {"id": "STEP4", "label": "S4 额外动作", "kind": "step", "reference_sign": "S4", "source_anchor": "输出结果", "layer_id": "L3", "source_feature_ids": ["F001"]}
    )
    payload["figures"][0]["complexity_budget"]["max_technical_elements"] = 5
    payload["figures"][0]["spec_assertions"][0]["element_ids"].append("STEP4")
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-STEP-ISOMORPHISM" in codes(output)


def test_v4_extra_unbound_decision_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["elements"].append(
        {"id": "DECIDE2", "label": "是否重试", "kind": "decision", "source_anchor": "未满足输出条件", "layer_id": "L2", "source_feature_ids": ["F001"]}
    )
    payload["figures"][0]["complexity_budget"]["max_technical_elements"] = 5
    payload["figures"][0]["complexity_budget"]["max_decisions"] = 2
    payload["figures"][0]["spec_assertions"][0]["element_ids"].append("DECIDE2")
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-DECISION-ISOMORPHISM" in codes(output)


def test_v4_approved_style_brief_is_bound_and_stale_hash_is_blocked(tmp_path):
    brief, output = fixture(tmp_path)
    baseline = tmp_path / "baseline.drawio"
    reference = tmp_path / "reference.drawio"
    baseline.write_text('<mxfile compressed="false"><diagram><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>', encoding="utf-8")
    reference.write_text(baseline.read_text(encoding="utf-8"), encoding="utf-8")
    style = tmp_path / "style-brief.json"
    style_payload = {
        "schema_id": "cn-patent-drawing-style-brief/v1",
        "case_id": "case",
        "generated_at": "2026-09-09",
        "baseline_drawio": {"path": baseline.name, "sha256": digest(baseline)},
        "reference_drawio": {"path": reference.name, "sha256": digest(reference)},
        "analysis_status": "CLEAN_VISUAL_ONLY",
        "matching": {"strategy": "stable_id_then_reference_sign_then_visible_label", "matched_nodes": [], "unmatched_baseline_nodes": [], "unmatched_reference_nodes": []},
        "technical_diff": {"added_nodes": [], "removed_nodes": [], "renamed_nodes": [], "added_relations": [], "removed_relations": [], "endpoint_changes": []},
        "visual_diff": {},
        "structural_anomalies": [],
        "reusable_style": {"page": {}, "grid_size": 10, "layout": {}, "typography": {}, "node_geometry": {}, "palette": {}, "edge_style": {}},
        "sanitization_plan": {
            "required": False,
            "strategy": "rebuild_from_baseline_apply_reference_geometry",
            "baseline_topology_authority": True,
            "copy_matched_node_geometry": True,
            "copy_only_whitelisted_styles": True,
            "reference_edges_are_style_only": True,
            "restore_baseline_relation_ids": True,
            "restore_baseline_relation_endpoints": True,
            "restore_native_edge_labels": True,
            "drop_reference_only_nodes": True,
            "drop_reference_only_edges": True,
            "reject_self_loops_not_in_baseline": True,
            "repair_anomaly_codes": [],
            "excluded_reference_node_ids": [],
            "expected_postconditions": ["technical_diff_empty", "all_edges_have_source_and_target", "no_unregistered_self_loops", "no_detached_edge_labels", "baseline_relation_labels_restored"],
        },
        "application_policy": {"visual_only": True, "preserve_stable_ids": True, "preserve_element_labels": True, "preserve_relation_ids": True, "preserve_relation_endpoints": True, "preserve_method_topology": True, "rebuild_from_baseline": True, "drop_reference_only_nodes": True, "drop_reference_only_edges": True, "restore_native_edge_labels": True},
        "approval": {"status": "approved", "approved_visual_only": True, "approved_by": "用户", "approved_at": "2026-09-09", "acknowledged_anomaly_codes": []},
    }
    write_json(style, style_payload)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["style_brief_path"] = style.name
    payload["style_brief_sha256"] = digest(style)
    write_json(brief, payload)
    result = run(brief, output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["style_brief_validation"]["status"] == "PASS"

    style.write_text(style.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = run(brief, output)
    assert result.returncode == 2
    assert "BRIEF-STYLE-STALE" in codes(output)
