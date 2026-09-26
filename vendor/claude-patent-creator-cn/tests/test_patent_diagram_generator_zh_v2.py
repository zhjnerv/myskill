"""cn-patent-diagram-generator v2 领域合同、官方导出和历史路由缺陷回归。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cn-patent-diagram-generator"
BRIEF_VALIDATOR = SKILL / "scripts" / "validate_drawing_brief.py"
EXPORTER = SKILL / "scripts" / "export_patent_drawio.py"
VERIFIER = SKILL / "scripts" / "verify_patent_drawings.py"
DRAWIO_SKILL = Path.home() / ".codex/skills/drawio-skill"
STABILITY_CHECKER = SKILL / "scripts" / "check_stability_evidence.py"
STABILITY_ASSETS = SKILL / "assets" / "stability"




def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", check=False,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_sources(case: Path) -> dict[str, Path]:
    claims = case / "02-申请文件/权利要求书.md"
    spec = case / "02-申请文件/说明书.md"
    ledger = case / "01-检索/feature-ledger.json"
    write(claims, "# 权利要求书\n\n1. 一种方法，包括开始处理、条件校验和执行处理。\n")
    write(spec, "# 示例\n\n## 具体实施方式\n\n开始处理后执行条件校验；条件满足时执行处理。\n")
    write(ledger, json.dumps({"schema_id": "cn-patent-feature-ledger/v1", "features": [
        {"feature_id": "F001", "name": "条件校验", "classification": "distinguishing"}
    ]}, ensure_ascii=False))
    return {"claims": claims, "specification": spec, "feature_ledger": ledger}


def restrained_policy() -> dict:
    return {
        "mode": "restrained_color",
        "grayscale_safe": True,
        "color_semantics_redundant": True,
        "max_nonwhite_fills": 3,
        "allowed_fill_colors": ["#FFFFFF", "#EAF2F8", "#F8F2E6", "#F4F4F4"],
        "allowed_stroke_colors": ["#202020", "#405F73", "#706347", "#4A4A4A"],
        "palette_asset": "assets/patent-restrained-color.json",
    }


def create_brief(case: Path, sources: dict[str, Path]) -> Path:
    work = case / "03-审查工作区/附图"
    brief = work / "drawing-brief.json"
    payload = {
        "schema_id": "cn-patent-drawing-brief/v2",
        "case_id": "case-1",
        "production_skill": "drawio-skill",
        "generated_at": "2026-08-28",
        "source_artifacts": [
            {"artifact_id": key, "path": str(path.relative_to(case)), "sha256": digest(path)}
            for key, path in sources.items()
        ],
        "output_root": "02-申请文件/说明书附图",
        "global_constraints": {
            "color_policy": restrained_policy(),
            "figure_number_on_canvas": False,
            "edge_labels_allowed": True,
            "annotation_nodes_may_be_edge_endpoints": False,
            "native_edge_labels_required": True,
            "separate_relation_label_nodes_allowed": False,
            "official_drawio_export_required": True,
            "visual_review_required": True,
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
        },
        "visual_review_path": "03-审查工作区/附图/visual-review.json",
        "figures": [{
            "figure_number": 1,
            "title": "条件处理流程图",
            "file_stem": "图1-条件处理流程图",
            "diagram_type": "method_flowchart",
            "orientation": "portrait",
            "style_profile": "patent_restrained_color",
            "purpose": "表示条件校验和处理分支",
            "claim_numbers": [1],
            "spec_anchors": ["条件校验"],
            "elements": [
                {"id": "S100", "label": "开始处理", "kind": "start_end", "reference_sign": "S100", "source_anchor": "开始处理"},
                {"id": "S110", "label": "条件校验", "kind": "decision", "reference_sign": "S110", "source_feature_ids": ["F001"], "source_anchor": "条件校验"},
                {"id": "S120", "label": "执行处理", "kind": "step", "reference_sign": "S120", "source_anchor": "执行处理"},
            ],
            "relations": [
                {"id": "R1", "source": "S100", "target": "S110", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "条件校验"},
                {"id": "R2", "source": "S110", "target": "S120", "label": "是", "kind": "control", "preferred_direction": "vertical", "direct_connection_required": True, "source_anchor": "条件满足时"},
            ],
            "outputs": {
                "drawio": "02-申请文件/说明书附图/图1-条件处理流程图.drawio",
                "preview_png": "03-审查工作区/附图/preview/图1-条件处理流程图.png",
                "final_png": "02-申请文件/说明书附图/图1-条件处理流程图.png",
                "export_report": "03-审查工作区/附图/export/图1-export.json",
            },
        }],
    }
    write(brief, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return brief


def create_valid_drawio(path: Path) -> None:
    write(path, """<mxfile compressed="false"><diagram name="条件处理流程图"><mxGraphModel pageWidth="827" pageHeight="1169"><root>
    <mxCell id="0"/><mxCell id="1" parent="0"/>
    <mxCell id="S100" value="S100&lt;br&gt;开始处理" style="ellipse;whiteSpace=wrap;html=1;fillColor=#EAF2F8;strokeColor=#405F73;fontColor=#111111;fontSize=15;" vertex="1" parent="1"><mxGeometry x="300" y="80" width="220" height="70" as="geometry"/></mxCell>
    <mxCell id="S110" value="S110&lt;br&gt;条件校验" style="rhombus;whiteSpace=wrap;html=1;fillColor=#F8F2E6;strokeColor=#706347;fontColor=#111111;fontSize=15;" vertex="1" parent="1"><mxGeometry x="300" y="200" width="220" height="70" as="geometry"/></mxCell>
    <mxCell id="S120" value="S120&lt;br&gt;执行处理" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#EAF2F8;strokeColor=#405F73;fontColor=#111111;fontSize=15;" vertex="1" parent="1"><mxGeometry x="300" y="324" width="220" height="70" as="geometry"/></mxCell>
    <mxCell id="R1" edge="1" source="S100" target="S110" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=blockThin;endFill=1;fontSize=10;" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>
    <mxCell id="R2" value="是" edge="1" source="S110" target="S120" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=blockThin;endFill=1;fontSize=10;" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>
    </root></mxGraphModel></diagram></mxfile>""")


def basic_figure() -> dict:
    return {
        "figure_number": 1,
        "orientation": "portrait",
        "elements": [
            {"id": "S100", "label": "开始处理", "reference_sign": "S100"},
            {"id": "S110", "label": "条件校验", "reference_sign": "S110"},
            {"id": "S120", "label": "执行处理", "reference_sign": "S120"},
        ],
        "relations": [
            {"id": "R1", "source": "S100", "target": "S110", "preferred_direction": "vertical", "direct_connection_required": True},
            {"id": "R2", "source": "S110", "target": "S120", "label": "是", "preferred_direction": "vertical", "direct_connection_required": True},
        ],
    }


def test_brief_validator_binds_sources_and_rejects_stale_hash(tmp_path):
    case = tmp_path / "case"
    sources = create_sources(case)
    brief = create_brief(case, sources)
    result = run(BRIEF_VALIDATOR, "--brief", str(brief), "--case-dir", str(case))
    assert result.returncode == 0, result.stdout
    write(sources["specification"], sources["specification"].read_text(encoding="utf-8") + "已编辑")
    result = run(BRIEF_VALIDATOR, "--brief", str(brief), "--case-dir", str(case))
    assert result.returncode == 2
    assert "BRIEF-SOURCE-STALE" in result.stdout


def test_brief_validator_requires_relation_source_anchor_and_direct_edge(tmp_path):
    case = tmp_path / "case"
    sources = create_sources(case)
    brief = create_brief(case, sources)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["relations"][0].pop("source_anchor")
    payload["figures"][0]["relations"][1]["direct_connection_required"] = False
    write(brief, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    result = run(BRIEF_VALIDATOR, "--brief", str(brief), "--case-dir", str(case))
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert any(item["code"] == "BRIEF-EVIDENCE" for item in report["errors"])
    assert any(item["code"] == "BRIEF-RELATION" for item in report["errors"])


def test_historical_source_label_target_route_is_rejected(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_historical")
    drawing = tmp_path / "bad.drawio"
    drawing.write_text("""<mxfile compressed="false"><diagram name="bad"><mxGraphModel pageWidth="827" pageHeight="1169"><root>
    <mxCell id="0"/><mxCell id="1" parent="0"/>
    <mxCell id="S100" value="S100 开始处理" style="rounded=0;fillColor=#EAF2F8;strokeColor=#405F73;" vertex="1" parent="1"><mxGeometry x="300" y="80" width="220" height="70" as="geometry"/></mxCell>
    <mxCell id="S110" value="S110 条件校验" style="rhombus;fillColor=#F8F2E6;strokeColor=#706347;" vertex="1" parent="1"><mxGeometry x="300" y="200" width="220" height="70" as="geometry"/></mxCell>
    <mxCell id="label-R1" value="是" style="text;html=1;fillColor=#FFFFFF;strokeColor=none;" vertex="1" parent="1"><mxGeometry x="350" y="180" width="45" height="28" as="geometry"/></mxCell>
    <mxCell id="R1" edge="1" source="S100" target="label-R1" style="edgeStyle=orthogonalEdgeStyle;" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>
    <mxCell id="R1b" edge="1" source="label-R1" target="S110" style="edgeStyle=orthogonalEdgeStyle;" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>
    </root></mxGraphModel></diagram></mxfile>""", encoding="utf-8")
    figure = {
        "figure_number": 1,
        "elements": [
            {"id": "S100", "label": "开始处理", "reference_sign": "S100"},
            {"id": "S110", "label": "条件校验", "reference_sign": "S110"},
        ],
        "relations": [{"id": "R1", "source": "S100", "target": "S110", "label": "是", "preferred_direction": "vertical", "direct_connection_required": True}],
    }
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    codes = {item["code"] for item in report["errors"]}
    assert "DRAWING-TEXT-WAYPOINT" in codes
    assert "DRAWING-RELATION" in codes



def test_absolute_endpoint_and_self_loop_are_rejected(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_endpoint_safety")
    drawing = tmp_path / "endpoint-safety.drawio"
    create_valid_drawio(drawing)
    text = drawing.read_text(encoding="utf-8")
    text = text.replace('id="R1" edge="1" source="S100" target="S110"', 'id="R1" edge="1" source="S100"')
    text = text.replace('id="R2" value="是" edge="1" source="S110" target="S120"', 'id="R2" value="是" edge="1" source="S110" target="S110"')
    drawing.write_text(text, encoding="utf-8")
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    codes = {item["code"] for item in report["errors"]}
    assert "DRAWING-ABSOLUTE-ENDPOINT" in codes
    assert "DRAWING-SELF-LOOP" in codes


def test_detached_relation_label_is_rejected(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_detached_label")
    drawing = tmp_path / "detached-label.drawio"
    create_valid_drawio(drawing)
    text = drawing.read_text(encoding="utf-8")
    text = text.replace('id="R2" value="是"', 'id="R2" value=""')
    text = text.replace(
        '</root>',
        '<mxCell id="label-R2" value="是" style="text;html=1;" vertex="1" parent="1">'
        '<mxGeometry x="540" y="360" width="40" height="30" as="geometry"/></mxCell></root>',
    )
    drawing.write_text(text, encoding="utf-8")
    figure = {
        "figure_number": 1,
        "elements": [
            {"id": "S100", "label": "开始处理", "reference_sign": "S100"},
            {"id": "S110", "label": "条件校验", "reference_sign": "S110"},
            {"id": "S120", "label": "执行处理", "reference_sign": "S120"},
        ],
        "relations": [
            {"id": "R1", "source": "S100", "target": "S110", "preferred_direction": "vertical", "direct_connection_required": True},
            {"id": "R2", "source": "S110", "target": "S120", "label": "是", "preferred_direction": "vertical", "direct_connection_required": True},
        ],
    }
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    codes = {item["code"] for item in report["errors"]}
    assert "DRAWING-NATIVE-EDGE-LABEL" in codes
    assert "DRAWING-DETACHED-EDGE-LABEL" in codes


def test_brief_rejects_obsolete_svg_output(tmp_path):
    case = tmp_path / "case"
    sources = create_sources(case)
    brief = create_brief(case, sources)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    payload["figures"][0]["outputs"]["svg"] = "02-申请文件/说明书附图/图1.svg"
    write(brief, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    result = run(BRIEF_VALIDATOR, "--brief", str(brief), "--case-dir", str(case))
    assert result.returncode == 2
    assert "BRIEF-OUTPUT-OBSOLETE" in result.stdout


def test_oversized_node_with_small_font_is_rejected(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_large_box")
    drawing = tmp_path / "large-box.drawio"
    create_valid_drawio(drawing)
    text = drawing.read_text(encoding="utf-8").replace(
        'x="300" y="324" width="220" height="70"',
        'x="120" y="280" width="600" height="120"',
    )
    drawing.write_text(text, encoding="utf-8")
    figure = {
        "figure_number": 1,
        "orientation": "portrait",
        "elements": [
            {"id": "S100", "label": "开始处理", "reference_sign": "S100"},
            {"id": "S110", "label": "条件校验", "reference_sign": "S110"},
            {"id": "S120", "label": "执行处理", "reference_sign": "S120"},
        ],
        "relations": [
            {"id": "R1", "source": "S100", "target": "S110", "preferred_direction": "vertical", "direct_connection_required": True},
            {"id": "R2", "source": "S110", "target": "S120", "label": "是", "preferred_direction": "vertical", "direct_connection_required": True},
        ],
    }
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-NODE-PROPORTION" for item in report["errors"])


def test_text_overflow_is_rejected(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_text_overflow")
    drawing = tmp_path / "text-overflow.drawio"
    create_valid_drawio(drawing)
    text = drawing.read_text(encoding="utf-8").replace(
        'value="S120&lt;br&gt;执行处理"',
        'value="S120&lt;br&gt;这是一个明显无法容纳在当前狭小方框中的超长技术动作文字"',
    ).replace(
        'x="300" y="324" width="220" height="70"',
        'x="360" y="280" width="100" height="45"',
    )
    drawing.write_text(text, encoding="utf-8")
    figure = {
        "figure_number": 1,
        "orientation": "portrait",
        "elements": [
            {"id": "S100", "label": "开始处理", "reference_sign": "S100"},
            {"id": "S110", "label": "条件校验", "reference_sign": "S110"},
            {"id": "S120", "label": "这是一个明显无法容纳在当前狭小方框中的超长技术动作文字", "reference_sign": "S120"},
        ],
        "relations": [
            {"id": "R1", "source": "S100", "target": "S110", "preferred_direction": "vertical", "direct_connection_required": True},
            {"id": "R2", "source": "S110", "target": "S120", "label": "是", "preferred_direction": "vertical", "direct_connection_required": True},
        ],
    }
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-TEXT-OVERFLOW" for item in report["errors"])


def test_frame_height_cannot_exceed_twice_text_height(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_frame_height")
    drawing = tmp_path / "frame-height.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="324" width="220" height="70"',
            'x="300" y="280" width="220" height="80"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-NODE-HEIGHT" for item in report["errors"])


def test_frame_height_equal_to_twice_text_height_is_allowed(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_frame_height_boundary")
    drawing = tmp_path / "frame-height-boundary.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="324" width="220" height="70"',
            'x="300" y="280" width="220" height="72"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert not any(item["code"] == "DRAWING-NODE-HEIGHT" for item in report["errors"])


def test_more_than_twelve_chinese_characters_require_explicit_wrap(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_chinese_wrap")
    drawing = tmp_path / "chinese-wrap.drawio"
    create_valid_drawio(drawing)
    label = "一二三四五六七八九十甲乙丙"
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'value="S120&lt;br&gt;执行处理"',
            f'value="S120&lt;br&gt;{label}"',
        ),
        encoding="utf-8",
    )
    figure = basic_figure()
    figure["elements"][2]["label"] = label
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-CHINESE-WRAP" for item in report["errors"])


def test_exactly_twelve_chinese_characters_can_remain_on_one_line(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_chinese_wrap_boundary")
    drawing = tmp_path / "chinese-wrap-boundary.drawio"
    create_valid_drawio(drawing)
    label = "一二三四五六七八九十甲乙"
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'value="S120&lt;br&gt;执行处理"',
            f'value="S120&lt;br&gt;{label}"',
        ),
        encoding="utf-8",
    )
    figure = basic_figure()
    figure["elements"][2]["label"] = label
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    assert not any(item["code"] == "DRAWING-CHINESE-WRAP" for item in report["errors"])


def test_explicit_wrap_keeps_source_label_match_and_passes_chinese_limit(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_explicit_chinese_wrap")
    drawing = tmp_path / "explicit-chinese-wrap.drawio"
    create_valid_drawio(drawing)
    label = "一二三四五六七八九十甲乙丙"
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'value="S120&lt;br&gt;执行处理"',
            'value="S120&lt;br&gt;一二三四五六七&lt;br&gt;八九十甲乙丙"',
        ),
        encoding="utf-8",
    )
    figure = basic_figure()
    figure["elements"][2]["label"] = label
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    codes = {item["code"] for item in report["errors"]}
    assert "DRAWING-LABEL" not in codes
    assert "DRAWING-CHINESE-WRAP" not in codes


def test_vertical_spacing_accepts_minimum_two_font_heights_after_arrowhead(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_spacing_min_boundary")
    drawing = tmp_path / "spacing-min-boundary.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="200" width="220" height="70"',
            'x="300" y="192" width="220" height="70"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert not any(item["code"].startswith("DRAWING-VERTICAL-SPACING") for item in report["errors"])


def test_vertical_spacing_accepts_maximum_three_font_heights_after_arrowhead(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_spacing_max_boundary")
    drawing = tmp_path / "spacing-max-boundary.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8")
        .replace(
            'x="300" y="200" width="220" height="70"',
            'x="300" y="210" width="220" height="70"',
        )
        .replace(
            'x="300" y="324" width="220" height="70"',
            'x="300" y="334" width="220" height="70"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert not any(item["code"].startswith("DRAWING-VERTICAL-SPACING") for item in report["errors"])


def test_vertical_spacing_subtracts_native_label_and_arrowhead(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_edge_label_spacing")
    drawing = tmp_path / "edge-label-spacing.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="324" width="220" height="70"',
            'x="300" y="342" width="220" height="70"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert not any(item["code"].startswith("DRAWING-VERTICAL-SPACING") for item in report["errors"])


def test_vertical_spacing_rejects_less_than_two_font_heights(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_too_tight_spacing")
    drawing = tmp_path / "too-tight-spacing.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="200" width="220" height="70"',
            'x="300" y="191" width="220" height="70"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-VERTICAL-SPACING-MIN" for item in report["errors"])


def test_vertical_spacing_rejects_more_than_three_font_heights(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_excessive_spacing")
    drawing = tmp_path / "excessive-spacing.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="200" width="220" height="70"',
            'x="300" y="211" width="220" height="70"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-VERTICAL-SPACING-MAX" for item in report["errors"])


def make_rgb_png(path: Path, width: int, height: int, black_box: tuple[int, int, int, int]) -> None:
    exporter = load_module(EXPORTER, "patent_png_writer")
    left, top, right, bottom = black_box
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            color = 0 if left <= x <= right and top <= y <= bottom else 255
            row.extend((color, color, color))
        rows.append(b"\x00" + bytes(row))
    ihdr = __import__("struct").pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        exporter.PNG_SIGNATURE
        + exporter.chunk(b"IHDR", ihdr)
        + exporter.chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + exporter.chunk(b"IEND", b"")
    )


def test_cylinder_requires_explicit_storage_semantics(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_cylinder_semantics")
    drawing = tmp_path / "cylinder-semantics.drawio"
    create_valid_drawio(drawing)
    text = drawing.read_text(encoding="utf-8").replace(
        'id="S120" value="S120&lt;br&gt;执行处理" style="rounded=0;',
        'id="S120" value="S120&lt;br&gt;执行处理" style="shape=cylinder3;boundedLbl=1;',
    )
    drawing.write_text(text, encoding="utf-8")
    figure = basic_figure()
    figure["elements"][2]["kind"] = "step"
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-CYLINDER-SEMANTICS" for item in report["errors"])


def test_relation_label_font_must_be_two_thirds_of_node_font(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_edge_label_font")
    drawing = tmp_path / "edge-label-font.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace('endFill=1;fontSize=10;', 'endFill=1;fontSize=9;'),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-EDGE-LABEL-FONT" for item in report["errors"])


def test_relation_label_requires_one_arrowhead_height_above_and_below(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_edge_label_clearance")
    drawing = tmp_path / "edge-label-clearance.drawio"
    create_valid_drawio(drawing)
    drawing.write_text(
        drawing.read_text(encoding="utf-8").replace(
            'x="300" y="324" width="220" height="70"',
            'x="300" y="270" width="220" height="70"',
        ),
        encoding="utf-8",
    )
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-EDGE-LABEL-CLEARANCE" for item in report["errors"])


def test_relation_label_exact_two_thirds_and_clearance_boundary_are_allowed(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_edge_label_boundary")
    drawing = tmp_path / "edge-label-boundary.drawio"
    create_valid_drawio(drawing)
    # 节点字号15、标签字号10，正好为2/3；30px净距扣除12px文字块后，上下各9px，大于6px箭头高度。
    report = verifier.verify_drawio(drawing, basic_figure(), restrained_policy(), DRAWIO_SKILL)
    codes = {item["code"] for item in report["errors"]}
    assert "DRAWING-EDGE-LABEL-FONT" not in codes
    assert "DRAWING-EDGE-LABEL-CLEARANCE" not in codes


def test_png_margin_inspector_detects_excessive_white_border(tmp_path):
    exporter = load_module(EXPORTER, "patent_png_margin_inspector")
    png = tmp_path / "padded.png"
    make_rgb_png(png, 100, 80, (30, 20, 69, 59))
    info = exporter.inspect_png(png, 245)
    assert info["margins"] == {"left": 30, "top": 20, "right": 30, "bottom": 20}
    assert info["maximum_margin"] == 30


def test_restrained_color_policy_rejects_unapproved_flashy_fill(tmp_path):
    verifier = load_module(VERIFIER, "patent_drawing_verifier_color")
    drawing = tmp_path / "color.drawio"
    create_valid_drawio(drawing)
    text = drawing.read_text(encoding="utf-8").replace("fillColor=#EAF2F8", "fillColor=#FF0000", 1)
    drawing.write_text(text, encoding="utf-8")
    figure = {
        "figure_number": 1,
        "elements": [
            {"id": "S100", "label": "开始处理", "reference_sign": "S100"},
            {"id": "S110", "label": "条件校验", "reference_sign": "S110"},
            {"id": "S120", "label": "执行处理", "reference_sign": "S120"},
        ],
        "relations": [
            {"id": "R1", "source": "S100", "target": "S110", "preferred_direction": "vertical", "direct_connection_required": True},
            {"id": "R2", "source": "S110", "target": "S120", "label": "是", "preferred_direction": "vertical", "direct_connection_required": True},
        ],
    }
    report = verifier.verify_drawio(drawing, figure, restrained_policy(), DRAWIO_SKILL)
    assert any(item["code"] == "DRAWING-COLOR" for item in report["errors"])

@pytest.mark.skipif(shutil.which("drawio") is None and shutil.which("draw.io") is None, reason="Draw.io Desktop CLI unavailable")
def test_official_cli_export_and_final_verifier_pass(tmp_path):
    case = tmp_path / "case"
    sources = create_sources(case)
    brief = create_brief(case, sources)
    drawing = case / "02-申请文件/说明书附图/图1-条件处理流程图.drawio"
    create_valid_drawio(drawing)
    preview = case / "03-审查工作区/附图/preview/图1-条件处理流程图.png"
    final_png = case / "02-申请文件/说明书附图/图1-条件处理流程图.png"
    report = case / "03-审查工作区/附图/export/图1-export.json"
    export_result = run(EXPORTER, "--input", str(drawing), "--png", str(final_png), "--dpi", "300", "--report", str(report))
    assert export_result.returncode == 0, export_result.stdout
    preview.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final_png, preview)
    export_payload = json.loads(report.read_text(encoding="utf-8"))
    assert export_payload["renderer"]["kind"] == "drawio_desktop_cli"
    assert export_payload["source"]["sha256"] == digest(drawing)
    assert export_payload["parameters"]["size"] == "diagram"
    assert "--size" in export_payload["commands"]["png"]
    assert export_payload["commands"]["png"][export_payload["commands"]["png"].index("--size") + 1] == "diagram"
    assert set(export_payload["outputs"]) == {"png"}
    visual = {
        "schema_id": "cn-patent-drawing-visual-review/v1",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "test-reviewer",
        "figures": [{
            "figure_number": 1,
            "png_path": str(final_png.relative_to(case)),
            "png_sha256": digest(final_png),
            "checks": {
                "text_legible": True, "no_text_overlap": True, "no_edge_crossing": True,
                "no_edge_through_node": True, "no_arrow_ambiguity": True,
                "labels_adjacent": True, "no_unnecessary_detours": True,
                "node_text_proportionate": True, "no_text_overflow": True,
                "no_excessive_canvas_margin": True,
                "consistent_typography": True, "balanced_spacing": True,
                "clear_visual_hierarchy": True, "formal_patent_style": True,
                "monochrome": False, "restrained_color": True,
                "grayscale_safe": True, "no_figure_number_on_canvas": True,
            },
            "approved": True,
            "notes": "official CLI fixture",
        }],
    }
    write(case / "03-审查工作区/附图/visual-review.json", json.dumps(visual, ensure_ascii=False, indent=2) + "\n")
    output = case / "03-审查工作区/附图/final-verification.json"
    result = run(VERIFIER, "--brief", str(brief), "--case-dir", str(case), "--drawio-skill-dir", str(DRAWIO_SKILL), "--output", str(output))
    assert result.returncode == 0, result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["figures"][0]["png"]["dpi"][0] == pytest.approx(300, abs=0.2)
    assert payload["figures"][0]["official_reexport"]["matched"] is True

    # Candidate binding: changing the final image invalidates both export and visual evidence.
    final_png.write_bytes(final_png.read_bytes() + b"stale")
    stale = run(VERIFIER, "--brief", str(brief), "--case-dir", str(case), "--drawio-skill-dir", str(DRAWIO_SKILL), "--output", str(output))
    assert stale.returncode == 2
    stale_payload = json.loads(output.read_text(encoding="utf-8"))
    stale_codes = {item["code"] for item in stale_payload["errors"]}
    assert "DRAWING-EXPORT-STALE" in stale_codes
    assert "DRAWING-VISUAL-STALE" in stale_codes
    assert "DRAWING-EXPORT-REPRODUCE" in stale_codes

    # Even if both JSON evidence files are forged to match the tampered PNG,
    # re-exporting the current Draw.io master must still expose the mismatch.
    export_payload["outputs"]["png"]["sha256"] = digest(final_png)
    write(report, json.dumps(export_payload, ensure_ascii=False, indent=2) + "\n")
    visual["figures"][0]["png_sha256"] = digest(final_png)
    write(case / "03-审查工作区/附图/visual-review.json", json.dumps(visual, ensure_ascii=False, indent=2) + "\n")
    forged = run(VERIFIER, "--brief", str(brief), "--case-dir", str(case), "--drawio-skill-dir", str(DRAWIO_SKILL), "--output", str(output))
    assert forged.returncode == 2
    forged_payload = json.loads(output.read_text(encoding="utf-8"))
    forged_codes = {item["code"] for item in forged_payload["errors"]}
    assert "DRAWING-EXPORT-STALE" not in forged_codes
    assert "DRAWING-VISUAL-STALE" not in forged_codes
    assert "DRAWING-EXPORT-REPRODUCE" in forged_codes


@pytest.mark.parametrize(
    ("constraint_id", "observable", "measurement", "negative_fixture"),
    [
        ("PATENT-DRAWING-SOURCE-BINDING", "source-binding-observable", "source-binding-pass", "stale-source.json"),
        ("PATENT-DRAWING-STYLE-REFERENCE", "style-reference-observable", "style-reference-pass", "stale-style-reference.json"),
        ("PATENT-DRAWING-TECH-COVERAGE", "tech-coverage-observable", "tech-coverage-pass", "missing-element.json"),
        ("PATENT-DRAWING-STEP-ISOMORPHISM", "step-isomorphism-observable", "step-isomorphism-pass", "step-isomorphism-mismatch.json"),
        ("PATENT-DRAWING-DIRECT-CONNECTOR", "direct-connector-observable", "direct-connector-pass", "detached-edge-label.json"),
        ("PATENT-DRAWING-NODE-SHAPE", "node-shape-observable", "node-shape-pass", "cylinder-semantics-mismatch.json"),
        ("PATENT-DRAWING-EDGE-LABEL-READABILITY", "edge-label-readability-observable", "edge-label-readability-pass", "edge-label-readability-mismatch.json"),
        ("PATENT-DRAWING-NODE-TEXT-FIT", "node-text-fit-observable", "node-text-fit-pass", "node-text-mismatch.json"),
        ("PATENT-DRAWING-VERTICAL-SPACING", "vertical-spacing-observable", "vertical-spacing-pass", "vertical-spacing-mismatch.json"),
        ("PATENT-DRAWING-PNG-MARGIN", "png-margin-observable", "png-margin-pass", "excessive-margin.json"),
        ("PATENT-DRAWING-COLOR", "color-observable", "color-pass", "flashy-color.json"),
        ("PATENT-DRAWING-OFFICIAL-EXPORT", "official-export-observable", "official-export-pass", "forged-export.json"),
        ("PATENT-DRAWING-VISUAL-BINDING", "visual-binding-observable", "visual-binding-pass", "unapproved-visual.json"),
    ],
)
def test_stability_checker_has_positive_and_negative_evidence(constraint_id, observable, measurement, negative_fixture):
    positive_fixture = "positive-step-isomorphism.json" if constraint_id == "PATENT-DRAWING-STEP-ISOMORPHISM" else "positive-final-verification-v4.json"
    positive = run(
        STABILITY_CHECKER,
        "--report", str(STABILITY_ASSETS / positive_fixture),
        "--constraint", constraint_id,
        "--observable", observable,
        "--measurement", measurement,
    )
    assert positive.returncode == 0, positive.stdout + positive.stderr
    positive_payload = json.loads(positive.stdout.splitlines()[-1])
    assert positive_payload["passed_constraint_ids"] == [constraint_id]
    assert positive_payload["measurements"][constraint_id][measurement] is True

    negative = run(
        STABILITY_CHECKER,
        "--report", str(STABILITY_ASSETS / negative_fixture),
        "--constraint", constraint_id,
        "--observable", observable,
        "--measurement", measurement,
    )
    assert negative.returncode == 3, negative.stdout + negative.stderr
    negative_payload = json.loads(negative.stdout.splitlines()[-1])
    assert negative_payload["failed_constraint_ids"] == [constraint_id]
    assert negative_payload["measurements"][constraint_id][measurement] is False


def test_stability_contract_covers_all_hard_constraints():
    contract = json.loads((SKILL / "config/instruction-stability-contract.json").read_text(encoding="utf-8"))
    constraint_ids = {item["id"] for item in contract["constraints"] if item["severity"] == "hard"}
    assert constraint_ids == {
        "PATENT-DRAWING-SOURCE-BINDING",
        "PATENT-DRAWING-STYLE-REFERENCE",
        "PATENT-DRAWING-TECH-COVERAGE",
        "PATENT-DRAWING-STEP-ISOMORPHISM",
        "PATENT-DRAWING-DIRECT-CONNECTOR",
        "PATENT-DRAWING-NODE-SHAPE",
        "PATENT-DRAWING-EDGE-LABEL-READABILITY",
        "PATENT-DRAWING-NODE-TEXT-FIT",
        "PATENT-DRAWING-VERTICAL-SPACING",
        "PATENT-DRAWING-PNG-MARGIN",
        "PATENT-DRAWING-COLOR",
        "PATENT-DRAWING-OFFICIAL-EXPORT",
        "PATENT-DRAWING-VISUAL-BINDING",
    }
    assert contract["stability"]["minimum_runs"] == 3

def test_skill_is_domain_adapter_for_drawio_skill():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for required in (
        'version: "4.7.0"', "drawio-skill", "cn-patent-drawing-brief/v4",
        "Draw.io Desktop CLI", "patent_restrained_color", "verify_patent_drawings.py",
    ):
        assert required in skill
    assert "不得改用 Pillow" in skill
    assert "from PIL" not in skill
