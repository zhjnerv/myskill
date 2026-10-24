"""F03/F04/F05/F07 附图技术语义安全回归。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/cn-patent-diagram-generator"
SANITIZER = SKILL / "scripts/sanitize_drawing_reference.py"
VALIDATOR = SKILL / "scripts/validate_drawing_brief.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def drawio(path: Path, *, reference: bool = False, reversed_arrow: bool = False) -> None:
    # 范例只改变布局、字号和颜色；技术方向及命名节点外框必须来自母版。
    font = "24" if reference else "16"
    fill = "#EAF2F8" if reference else "#FFFFFF"
    arrow = "startArrow=blockThin;endArrow=none;" if reversed_arrow else "endArrow=blockThin;"
    path.write_text(
        f'''<mxfile compressed="false"><diagram name="Page-1"><mxGraphModel><root>
        <mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="A" value="A 开始" style="ellipse;whiteSpace=wrap;html=1;fontSize={font};fillColor={fill};" vertex="1" parent="1"><mxGeometry x="0" y="0" width="100" height="50" as="geometry"/></mxCell>
        <mxCell id="B" value="B 判断" style="rhombus;whiteSpace=wrap;html=1;fontSize={font};fillColor={fill};" vertex="1" parent="1"><mxGeometry x="0" y="150" width="100" height="50" as="geometry"/></mxCell>
        <mxCell id="R" value="" edge="1" source="A" target="B" style="edgeStyle=orthogonalEdgeStyle;{arrow}" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>
        </root></mxGraphModel></diagram></mxfile>''', encoding="utf-8"
    )


def test_f03_rebuild_rejects_reverse_arrow_but_keeps_visual_style(tmp_path: Path):
    baseline, reference, output = (tmp_path / name for name in ("baseline.drawio", "reference.drawio", "out.drawio"))
    drawio(baseline)
    drawio(reference, reference=True, reversed_arrow=True)
    result = run(SANITIZER, "--baseline", str(baseline), "--reference", str(reference), "--output", str(output))
    assert result.returncode == 0, result.stdout + result.stderr
    text = output.read_text(encoding="utf-8")
    assert "startArrow=blockThin" not in text and "endArrow=none" not in text
    assert "endArrow=blockThin" in text
    assert "fontSize=24" in text and "#EAF2F8" in text


def test_f07_rebuild_is_idempotent_and_preserves_named_shapes(tmp_path: Path):
    baseline, reference, first, second = (tmp_path / name for name in ("baseline.drawio", "reference.drawio", "first.drawio", "second.drawio"))
    drawio(baseline)
    drawio(reference)
    assert run(SANITIZER, "--baseline", str(baseline), "--reference", str(reference), "--output", str(first)).returncode == 0
    assert run(SANITIZER, "--baseline", str(baseline), "--reference", str(first), "--output", str(second)).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    text = second.read_text(encoding="utf-8")
    assert 'style="ellipse;' in text and 'style="rhombus;' in text


def test_f05_complete_node_text_rejects_contradictory_suffix_and_allows_whitespace(tmp_path: Path):
    verifier = load_module(SKILL / "scripts/verify_patent_drawings.py", "drawing_verifier_semantic_safety")
    drawing = tmp_path / "drawing.drawio"
    drawio(drawing)
    figure = {
        "figure_number": 1,
        "elements": [
            {"id": "A", "label": "开始", "reference_sign": "A", "kind": "start_end"},
            {"id": "B", "label": "判断", "reference_sign": "B", "kind": "decision"},
        ],
        "relations": [{"id": "R", "source": "A", "target": "B", "preferred_direction": "vertical", "direct_connection_required": True}],
    }
    policy = {"mode": "monochrome", "grayscale_safe": True, "color_semantics_redundant": True, "max_nonwhite_fills": 1, "allowed_fill_colors": ["#FFFFFF"], "allowed_stroke_colors": ["#000000"]}
    report = verifier.verify_drawio(drawing, figure, policy, Path.home() / ".codex/skills/drawio-skill")
    assert "DRAWING-LABEL" not in {item["code"] for item in report["errors"]}
    drawing.write_text(drawing.read_text(encoding="utf-8").replace("B 判断", "B 判断（禁止执行）"), encoding="utf-8")
    report = verifier.verify_drawio(drawing, figure, policy, Path.home() / ".codex/skills/drawio-skill")
    assert "DRAWING-LABEL" in {item["code"] for item in report["errors"]}


def v4_brief(tmp_path: Path) -> Path:
    # 复用现有 v4 fixture，避免构造另一套来源合同。
    module = load_module(ROOT / "tests/test_patent_drawing_contract_v4.py", "drawing_contract_v4_fixture")
    brief, _ = module.fixture(tmp_path)
    return brief


def validate_brief(brief: Path) -> set[str]:
    output = brief.parent / "validation.json"
    result = run(VALIDATOR, "--brief", str(brief), "--case-dir", str(brief.parent), "--output", str(output))
    assert result.returncode == 2
    return {item["code"] for item in json.loads(output.read_text(encoding="utf-8"))["errors"]}


def test_f04_true_false_relation_label_swap_is_rejected(tmp_path: Path):
    brief = v4_brief(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    binding = payload["figures"][0]["decision_bindings"][0]
    binding["true_branch"]["label"], binding["false_branch"]["label"] = "否", "是"
    brief.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert "BRIEF-DECISION-LABEL" in validate_brief(brief)


def test_f04_true_false_target_swap_and_missing_branch_are_rejected(tmp_path: Path):
    brief = v4_brief(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    binding = payload["figures"][0]["decision_bindings"][0]
    binding["true_branch"]["target_step_id"] = "S1"
    brief.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert "BRIEF-DECISION-ROUTING" in validate_brief(brief)

    brief = v4_brief(tmp_path / "missing")
    payload = json.loads(brief.read_text(encoding="utf-8"))
    del payload["figures"][0]["decision_bindings"][0]["false_branch"]
    brief.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert "BRIEF-DECISION-BRANCH" in validate_brief(brief)


# 使用已通过严格 lint 的真实 XML 正例，避免负例只是被其它版式错误偶然拦下。
@pytest.fixture
def valid_drawing(tmp_path):
    helpers = load_module(ROOT / "tests/test_patent_diagram_generator_zh_v2.py", "semantic_safety_v2_helpers")
    verifier = load_module(SKILL / "scripts/verify_patent_drawings.py", "semantic_safety_verifier")
    path = tmp_path / "valid.drawio"
    helpers.create_valid_drawio(path)
    figure = helpers.basic_figure()
    for item, kind in zip(figure["elements"], ("start_end", "decision", "step")):
        item["kind"] = kind

    def check():
        return verifier.verify_drawio(path, figure, helpers.restrained_policy(), helpers.DRAWIO_SKILL)

    assert check()["passed"] is True
    return path, figure, check


def change_cell(path, cid, **attrs):
    tree = ET.parse(path)
    cell = tree.find(f".//mxCell[@id='{cid}']")
    assert cell is not None
    for name, value in attrs.items():
        cell.set(name, value)
    tree.write(path, encoding="utf-8")


@pytest.mark.parametrize("arrows", [
    "startArrow=blockThin;endArrow=none;",
    "startArrow=blockThin;endArrow=blockThin;",
    "startArrow=none;endArrow=none;",
    "startArrow=none;endArrow=oval;",
])
def test_f03_visible_reverse_missing_or_ambiguous_arrow_is_rejected(valid_drawing, arrows):
    path, _figure, check = valid_drawing
    change_cell(path, "R1", style="edgeStyle=orthogonalEdgeStyle;fontSize=10;" + arrows)
    report = check()
    assert not report["passed"]
    assert "DRAWING-ARROW-DIRECTION" in {e["code"] for e in report["errors"]}


@pytest.mark.parametrize("value", [
    "S100<br>开始处理（禁止执行）", "S100<br>开始处", "S100<br>结束处理",
    "S1000<br>开始处理", "S100<br>开始处理S100", "禁止S100<br>开始处理",
])
def test_f05_full_text_mutations_fail(valid_drawing, value):
    path, _figure, check = valid_drawing
    change_cell(path, "S100", value=value)
    report = check()
    assert not report["passed"]
    assert "DRAWING-LABEL" in {e["code"] for e in report["errors"]}


@pytest.mark.parametrize("label,mark,value", [
    ("开始处理", "S100", "S100<br/>开 始\n处理"),
    ("S100 开始处理", "S100", "S100<br>开始处理"),
    ("开始处理", "100", "100<br>开始处理"),
    ("开始处理", "100", "开始处理<br>100"),
    ("开始处理", "100", "开始处理<br>（100）"),
    ("开始处理", "100", "(100)<br>开始处理"),
    ("开始处理（100）", "100", "开始处理<br>（100）"),
    ("开始处理", "S100", "<div>S100</div><div>开始&nbsp;处理</div>"),
    ("PWM控制", "100", "100<br>PWM控制"),
    ("100 PWM控制", "100", "100<br>PWM控制"),
])
def test_f05_whitespace_wrap_and_registered_part_mark_pass(valid_drawing, label, mark, value):
    path, figure, check = valid_drawing
    figure["elements"][0].update(label=label, reference_sign=mark)
    change_cell(path, "S100", value=value)
    report = check()
    assert report["passed"], report["errors"]


@pytest.mark.parametrize("mutation,expected", [
    ("edge_labels", "BRIEF-DECISION-LABEL"),
    ("edge_targets", "BRIEF-DECISION-ROUTING"),
    ("relation_ids", "BRIEF-DECISION-ROUTING"),
    ("duplicate_relation", "BRIEF-DECISION-BRANCH"),
    ("missing_edge", "BRIEF-DECISION-BRANCH"),
    ("extra_edge", "BRIEF-DECISION-BRANCH"),
    ("coordinated_labels", "BRIEF-DECISION-LABEL"),
])
def test_f04_branch_edge_mutations_fail(tmp_path, mutation, expected):
    brief = v4_brief(tmp_path)
    payload = json.loads(brief.read_text(encoding="utf-8"))
    figure = payload["figures"][0]
    binding = figure["decision_bindings"][0]
    true, false = figure["relations"][2:4]
    if mutation == "edge_labels":
        true["label"], false["label"] = false["label"], true["label"]
    elif mutation == "edge_targets":
        true["target"], false["target"] = false["target"], true["target"]
    elif mutation == "relation_ids":
        binding["true_branch"]["relation_id"], binding["false_branch"]["relation_id"] = "R_FALSE", "R_TRUE"
    elif mutation == "duplicate_relation":
        binding["false_branch"]["relation_id"] = "R_TRUE"
    elif mutation == "missing_edge":
        figure["relations"].remove(false)
    elif mutation == "extra_edge":
        figure["relations"].append({**false, "id": "EXTRA", "route_channel": "EXTRA"})
    else:
        true["label"] = binding["true_branch"]["label"] = "否"
        false["label"] = binding["false_branch"]["label"] = "是"
    brief.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert expected in validate_brief(brief)


def test_f07_reference_cannot_replace_baseline_shape(valid_drawing, tmp_path):
    path, _figure, check = valid_drawing
    baseline = tmp_path / "shape-baseline.drawio"
    reference = tmp_path / "shape-reference.drawio"
    baseline.write_bytes(path.read_bytes())
    reference.write_bytes(path.read_bytes())
    change_cell(reference, "S100", style="shape=cylinder3;fontSize=15;fillColor=#EAF2F8;")
    change_cell(reference, "S110", style="shape=ellipse;fontSize=15;fillColor=#F8F2E6;")
    result = run(SANITIZER, "--baseline", str(baseline), "--reference", str(reference), "--output", str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert check()["passed"] is True
    assert 'style="ellipse;' in path.read_text(encoding="utf-8")
    assert 'style="rhombus;' in path.read_text(encoding="utf-8")


def test_f07_decision_shape_loss_is_rejected(valid_drawing):
    path, _figure, check = valid_drawing
    text = path.read_text(encoding="utf-8").replace("rhombus;", "")
    path.write_text(text, encoding="utf-8")
    report = check()
    assert not report["passed"]
    assert "DRAWING-SHAPE-SEMANTICS" in {e["code"] for e in report["errors"]}


def test_f02_existing_report_parts_bind_current_bytes(valid_drawing, tmp_path):
    path, _figure, check = valid_drawing
    helpers = load_module(ROOT / "tests/test_patent_diagram_generator_zh_v2.py", "semantic_safety_png_helpers")
    verifier = load_module(SKILL / "scripts/verify_patent_drawings.py", "semantic_safety_png_verifier")
    png = tmp_path / "synthetic.png"
    helpers.make_rgb_png(png, 50, 50, (10, 10, 40, 40))
    assert check()["path"] == str(path)
    assert check()["sha256"] == helpers.digest(path)
    assert verifier.png_info(png)["sha256"] == helpers.digest(png)
