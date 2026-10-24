"""绘图合同 v3 的阅读语法、复杂度和图文范围回归。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/cn-patent-diagram-generator/scripts/validate_drawing_brief.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(tmp_path: Path) -> tuple[Path, Path]:
    claims = tmp_path / "权利要求书.md"
    spec = tmp_path / "说明书.md"
    ledger = tmp_path / "feature-ledger.json"
    write(claims, "1. 对输入数据进行条件判断，正常时输出结果，异常时输出错误状态。\n")
    write(spec, "具体实施方式：如图1所示，输入数据经条件判断后分别进入正常输出关系和异常输出关系。\n")
    write(ledger, '{"schema_id":"cn-patent-feature-ledger/v2","features":[{"feature_id":"F001"}]}\n')
    brief = tmp_path / "drawing-brief.json"
    payload = {
        "schema_id": "cn-patent-drawing-brief/v3", "case_id": "case", "production_skill": "drawio-skill",
        "source_artifacts": [
            {"artifact_id": "claims", "path": claims.name, "sha256": digest(claims)},
            {"artifact_id": "specification", "path": spec.name, "sha256": digest(spec)},
            {"artifact_id": "feature_ledger", "path": ledger.name, "sha256": digest(ledger)},
        ],
        "output_root": "drawings", "visual_review_path": "review/visual-review.json",
        "global_constraints": {
            "figure_number_on_canvas": False, "edge_labels_allowed": True,
            "annotation_nodes_may_be_edge_endpoints": False,
            "native_edge_labels_required": True,
            "separate_relation_label_nodes_allowed": False, "official_drawio_export_required": True,
            "visual_review_required": True, "single_primary_question_required": True,
            "independent_route_channels_required": True, "final_png_visual_review_required": True,
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
        "figures": [{
            "figure_number": 1, "title": "判断流程图", "file_stem": "图1-判断流程图", "diagram_type": "method_flowchart",
            "orientation": "portrait", "style_profile": "patent_monochrome", "purpose": "表示条件判断分支",
            "primary_question": "输入数据如何根据条件进入正常或异常出口？", "reading_direction": "top_to_bottom",
            "layers": [{"id": "L1", "title": "输入", "order": 1}, {"id": "L2", "title": "判断", "order": 2}, {"id": "L3", "title": "输出", "order": 3}],
            "complexity_budget": {"max_technical_elements": 4, "max_relations": 3, "max_decisions": 1},
            "claim_numbers": [1], "spec_anchors": ["如图1所示"],
            "elements": [
                {"id": "START", "label": "输入", "kind": "start_end", "source_anchor": "输入数据", "layer_id": "L1"},
                {"id": "DECIDE", "label": "条件判断", "kind": "decision", "source_anchor": "条件判断", "layer_id": "L2", "source_feature_ids": ["F001"]},
                {"id": "NORMAL", "label": "正常输出", "kind": "start_end", "source_anchor": "正常输出", "layer_id": "L3"},
                {"id": "ERROR", "label": "错误状态", "kind": "start_end", "source_anchor": "错误状态", "layer_id": "L3"},
            ],
            "relations": [
                {"id": "R1", "source": "START", "target": "DECIDE", "kind": "data", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "输入数据经条件判断", "route_channel": "C1", "source_feature_ids": ["F001"]},
                {"id": "R2", "source": "DECIDE", "target": "NORMAL", "label": "是", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "正常输出关系", "route_channel": "C2", "source_feature_ids": ["F001"]},
                {"id": "R3", "source": "DECIDE", "target": "ERROR", "label": "否", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "异常输出关系", "route_channel": "C3", "source_feature_ids": ["F001"]},
            ],
            "normal_exit_ids": ["NORMAL"], "exception_exit_ids": ["ERROR"],
            "spec_assertions": [{"anchor": "输入数据经条件判断后分别进入正常输出关系和异常输出关系", "element_ids": ["DECIDE", "NORMAL", "ERROR"], "relation_ids": ["R1", "R2", "R3"]}],
            "outputs": {"drawio": "drawings/图1-判断流程图.drawio", "preview_png": "review/图1-preview.png", "final_png": "drawings/图1-判断流程图.png", "export_report": "review/图1-export.json"},
        }],
    }
    brief.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return brief, tmp_path / "report.json"


def run(brief: Path, output: Path):
    return subprocess.run([sys.executable, str(VALIDATOR), "--brief", str(brief), "--case-dir", str(brief.parent), "--output", str(output)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)


def test_v3_contract_passes(tmp_path):
    brief, output = fixture(tmp_path)
    result = run(brief, output)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"


def test_v3_contract_blocks_overloaded_figure(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["complexity_budget"]["max_relations"] = 2
    brief.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = run(brief, output)
    assert result.returncode == 2
    assert any(item["code"] == "BRIEF-COMPLEXITY" for item in json.loads(output.read_text(encoding="utf-8"))["errors"])


def test_v3_contract_blocks_figure_text_scope_mismatch(tmp_path):
    brief, output = fixture(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["spec_assertions"][0]["relation_ids"].append("R404")
    brief.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = run(brief, output)
    assert result.returncode == 2
    assert any(item["code"] == "BRIEF-SPEC-ASSERTION" for item in json.loads(output.read_text(encoding="utf-8"))["errors"])
