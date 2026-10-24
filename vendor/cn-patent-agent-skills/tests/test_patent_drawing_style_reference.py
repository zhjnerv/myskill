from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/cn-patent-diagram-generator"
ANALYZER = SKILL / "scripts/analyze_drawing_reference.py"
VALIDATOR = SKILL / "scripts/validate_drawing_style_brief.py"
SANITIZER = SKILL / "scripts/sanitize_drawing_reference.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_drawio(path: Path, *, changed_ids: bool, absolute_edge: bool) -> None:
    a = "new-a" if changed_ids else "A"
    b = "new-b" if changed_ids else "B"
    source = f' source="{a}"' if not absolute_edge else f' source="{a}"'
    target = f' target="{b}"' if not absolute_edge else ""
    target_point = '<mxPoint x="350" y="420" as="targetPoint"/>' if absolute_edge else ""
    path.write_text(
        f'''<mxfile compressed="false"><diagram name="Page-1"><mxGraphModel pageWidth="827" pageHeight="1169" gridSize="10"><root>
        <mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="{a}" value="100 主模块" style="rounded=1;whiteSpace=wrap;html=1;fontSize={'24' if changed_ids else '16'};fontFamily=Times New Roman;fillColor=#EAF2F8;strokeColor=#405F73;" vertex="1" parent="1"><mxGeometry x="100" y="100" width="300" height="100" as="geometry"/></mxCell>
        <mxCell id="{b}" value="110 支撑模块" style="rounded=1;whiteSpace=wrap;html=1;fontSize={'24' if changed_ids else '16'};fontFamily=Times New Roman;fillColor=#EEF4EA;strokeColor=#52634E;" vertex="1" parent="1"><mxGeometry x="{'450' if changed_ids else '100'}" y="300" width="300" height="100" as="geometry"/></mxCell>
        <mxCell id="R1" value="传递" edge="1" parent="1"{source}{target} style="edgeStyle=orthogonalEdgeStyle;rounded=1;endArrow=block;strokeWidth=1.4;"><mxGeometry relative="1" as="geometry">{target_point}</mxGeometry></mxCell>
        </root></mxGraphModel></diagram></mxfile>''',
        encoding="utf-8",
    )


def run(script: Path, *args: str):
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)


def test_reference_analyzer_separates_visual_intent_and_absolute_endpoint(tmp_path):
    baseline = tmp_path / "baseline.drawio"
    reference = tmp_path / "reference.drawio"
    output = tmp_path / "style-brief.json"
    write_drawio(baseline, changed_ids=False, absolute_edge=False)
    write_drawio(reference, changed_ids=True, absolute_edge=True)
    result = run(
        ANALYZER,
        "--baseline", str(baseline), "--reference", str(reference),
        "--case-dir", str(tmp_path), "--case-id", "case", "--output", str(output),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["analysis_status"] == "REVIEW_REQUIRED"
    assert len(payload["matching"]["matched_nodes"]) == 2
    assert {item["method"] for item in payload["matching"]["matched_nodes"]} == {"reference_sign"}
    assert payload["reusable_style"]["typography"]["font_size"] == 24.0
    assert payload["reusable_style"]["compactness"]["preserve_font_size_before_compacting_nodes"] is True
    assert payload["sanitization_plan"]["strategy"] == "rebuild_from_baseline_apply_reference_geometry"
    assert payload["sanitization_plan"]["restore_baseline_relation_endpoints"] is True
    assert "STYLE-REFERENCE-ABSOLUTE-ENDPOINT" in {item["code"] for item in payload["structural_anomalies"]}
    assert payload["approval"]["status"] == "pending"

    approved = run(
        ANALYZER,
        "--baseline", str(baseline), "--reference", str(reference),
        "--case-dir", str(tmp_path), "--case-id", "case", "--output", str(output),
        "--approve-by", "用户",
    )
    assert approved.returncode == 0
    validation = run(VALIDATOR, "--style-brief", str(output), "--case-dir", str(tmp_path))
    assert validation.returncode == 0, validation.stdout + validation.stderr
    report = json.loads(validation.stdout)
    assert report["status"] == "PASS"
    assert report["style_brief_sha256"] == digest(output)


def test_style_brief_stale_reference_is_blocked(tmp_path):
    baseline = tmp_path / "baseline.drawio"
    reference = tmp_path / "reference.drawio"
    output = tmp_path / "style-brief.json"
    write_drawio(baseline, changed_ids=False, absolute_edge=False)
    write_drawio(reference, changed_ids=False, absolute_edge=False)
    assert run(
        ANALYZER, "--baseline", str(baseline), "--reference", str(reference),
        "--case-dir", str(tmp_path), "--case-id", "case", "--output", str(output), "--approve-by", "用户",
    ).returncode == 0
    reference.write_text(reference.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    validation = run(VALIDATOR, "--style-brief", str(output), "--case-dir", str(tmp_path))
    assert validation.returncode == 2
    assert "STYLE-BRIEF-STALE" in validation.stdout


def test_sanitizer_keeps_baseline_topology_and_drops_manual_artifacts(tmp_path):
    baseline = tmp_path / "baseline.drawio"
    reference = tmp_path / "reference.drawio"
    output = tmp_path / "sanitized.drawio"
    report = tmp_path / "sanitize-report.json"
    write_drawio(baseline, changed_ids=False, absolute_edge=False)
    write_drawio(reference, changed_ids=True, absolute_edge=True)
    text = reference.read_text(encoding="utf-8")
    text = text.replace('value="传递" edge="1"', 'value="" edge="1"')
    text = text.replace(
        '</root>',
        '<mxCell id="label-R1" value="传递" style="text;html=1;" vertex="1" parent="1"><mxGeometry x="320" y="220" width="50" height="30" as="geometry"/></mxCell>'
        '<mxCell id="extra-loop" value="" edge="1" source="new-b" target="new-b" style="edgeStyle=orthogonalEdgeStyle;" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>'
        '</root>',
    )
    reference.write_text(text, encoding="utf-8")

    analysis_path = tmp_path / "style-brief.json"
    assert run(
        ANALYZER, "--baseline", str(baseline), "--reference", str(reference),
        "--case-dir", str(tmp_path), "--case-id", "case", "--output", str(analysis_path),
        "--approve-by", "用户",
    ).returncode == 0
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    codes = {item["code"] for item in analysis["structural_anomalies"]}
    assert "STYLE-REFERENCE-ABSOLUTE-ENDPOINT" in codes
    assert "STYLE-REFERENCE-DETACHED-EDGE-LABEL" in codes
    assert "STYLE-REFERENCE-SELF-LOOP" in codes

    result = run(
        SANITIZER, "--baseline", str(baseline), "--reference", str(reference),
        "--output", str(output), "--report", str(report),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    sanitize_payload = json.loads(report.read_text(encoding="utf-8"))
    assert sanitize_payload["status"] == "STRUCTURE_SAFE_VISUAL_REVIEW_REQUIRED"
    assert sanitize_payload["visual_review_required"] is True
    sanitized = output.read_text(encoding="utf-8")
    assert 'id="A"' in sanitized and 'id="B"' in sanitized
    assert 'id="new-a"' not in sanitized and 'id="label-R1"' not in sanitized and 'id="extra-loop"' not in sanitized
    assert 'id="R1"' in sanitized and 'source="A"' in sanitized and 'target="B"' in sanitized
    assert 'value="传递"' in sanitized
    assert 'x="450"' in sanitized

    post = tmp_path / "post-analysis.json"
    assert run(
        ANALYZER, "--baseline", str(baseline), "--reference", str(output),
        "--case-dir", str(tmp_path), "--case-id", "case", "--output", str(post),
    ).returncode == 0
    payload = json.loads(post.read_text(encoding="utf-8"))
    assert payload["analysis_status"] == "CLEAN_VISUAL_ONLY"
    assert not any(payload["technical_diff"].values())
    assert payload["structural_anomalies"] == []


def test_style_schema_requires_safe_rebuild_contract():
    schema = json.loads((SKILL / "references/drawing-style-brief-schema.json").read_text(encoding="utf-8"))
    assert "sanitization_plan" in schema["required"]
    properties = schema["properties"]["sanitization_plan"]["properties"]
    assert properties["strategy"]["const"] == "rebuild_from_baseline_apply_reference_geometry"
    assert properties["restore_baseline_relation_endpoints"]["const"] is True
    assert properties["restore_native_edge_labels"]["const"] is True
    application = schema["properties"]["application_policy"]["properties"]
    assert application["rebuild_from_baseline"]["const"] is True
    assert application["drop_reference_only_edges"]["const"] is True


def test_style_validator_blocks_incomplete_sanitization_plan(tmp_path):
    baseline = tmp_path / "baseline.drawio"
    reference = tmp_path / "reference.drawio"
    output = tmp_path / "style-brief.json"
    write_drawio(baseline, changed_ids=False, absolute_edge=False)
    write_drawio(reference, changed_ids=True, absolute_edge=True)
    assert run(
        ANALYZER, "--baseline", str(baseline), "--reference", str(reference),
        "--case-dir", str(tmp_path), "--case-id", "case", "--output", str(output),
        "--approve-by", "用户",
    ).returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["sanitization_plan"]["restore_baseline_relation_endpoints"] = False
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation = run(VALIDATOR, "--style-brief", str(output), "--case-dir", str(tmp_path))
    assert validation.returncode == 2
    assert "STYLE-BRIEF-SANITIZATION" in validation.stdout
