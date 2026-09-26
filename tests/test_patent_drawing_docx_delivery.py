from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/cn-patent-diagram-generator/scripts/verify_drawing_docx_delivery.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_minimal_docx(path: Path) -> None:
    """Write a minimal but OOXML-valid DOCX (so verify_docx_assembly accepts it)."""
    from docx import Document

    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_paragraph("hello")
    document.save(path)


def fixture(tmp_path: Path):
    """Construct a fully-bound fixture that the hardened delivery verifier accepts."""
    png = tmp_path / "drawings/图1.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"current-png")
    drawio = tmp_path / "drawings/图1.drawio"
    drawio.write_bytes(b"<mxfile>current</mxfile>")
    brief = tmp_path / "drawing-brief.json"
    write_json(brief, {
        "figures": [{
            "figure_number": 1,
            "outputs": {
                "final_png": "drawings/图1.png",
                "drawio": "drawings/图1.drawio",
            },
        }],
    })
    drawing = tmp_path / "drawing-verification.json"
    write_json(drawing, {
        "status": "PASS",
        "errors": [],
        "brief_sha256": digest(brief),
        "figures": [{
            "figure_number": 1,
            "png": {"path": str(png), "sha256": digest(png)},
            "drawio": {"path": str(drawio), "sha256": digest(drawio)},
        }],
    })
    docx = tmp_path / "output.docx"
    _build_minimal_docx(docx)
    template = tmp_path / "template.docx"
    _build_minimal_docx(template)
    artifact_inputs = []
    for aid in ("claims", "specification", "abstract", "figure_index"):
        artifact_path = tmp_path / f"{aid}.md"
        artifact_path.write_text(f"# {aid}\n", encoding="utf-8")
        artifact_inputs.append({
            "artifact_id": aid,
            "path": str(artifact_path),
            "sha256": digest(artifact_path),
        })
    artifact_inputs.append({
        "artifact_id": "figure_1",
        "path": str(png),
        "sha256": digest(png),
    })
    report = tmp_path / "docx-report.json"
    write_json(report, {
        "schema": "cn-patent-docx-assembly/v2",
        "status": "STRUCTURE_VERIFIED",
        "output": str(docx),
        "output_sha256": digest(docx),
        "inputs": {
            "template": str(template),
            "template_sha256": digest(template),
            "artifacts": artifact_inputs,
        },
        "render": {"requested": False},
    })
    verification = tmp_path / "docx-verification.json"
    write_json(verification, {"status": "PASS", "errors": []})
    return brief, drawing, report, verification, png, drawio, docx


def run(tmp_path: Path, brief: Path, drawing: Path, report: Path, verification: Path,
        visual: Path | None = None):
    output = tmp_path / "delivery.json"
    cmd = [
        sys.executable, str(SCRIPT), "--case-dir", str(tmp_path), "--brief", str(brief),
        "--drawing-verification", str(drawing), "--docx-report", str(report),
        "--docx-verification", str(verification), "--output", str(output),
    ]
    if visual is not None:
        cmd.extend(["--docx-visual-review", str(visual)])
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    return result, json.loads(output.read_text(encoding="utf-8"))


def test_drawing_docx_delivery_passes_for_current_png(tmp_path):
    brief, drawing, report, verification, _png, _drawio, _docx = fixture(tmp_path)
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["status"] == "PASS"
    assert payload["figure_count"] == 1


def test_drawing_docx_delivery_blocks_stale_embedded_png(tmp_path):
    brief, drawing, report, verification, png, _drawio, _docx = fixture(tmp_path)
    png.write_bytes(b"changed")
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2
    assert "DELIVERY-DOCX-FIGURE-STALE" in {item["code"] for item in payload["errors"]}


def test_visual_review_pending_status_accepts_visual_review_and_ignores_figure_index(tmp_path):
    brief, drawing, report, verification, png, drawio, docx = fixture(tmp_path)
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    report_payload["status"] = "STRUCTURE_VERIFIED_VISUAL_REVIEW_PENDING"
    # Replace the auto-built ``figure_index`` artifact with a real caller file
    # whose ``artifact_id`` is ``figure_index`` (not matching ``figure_\d+``).
    # The DOCX report filter must exclude it from the figure-N set so it
    # doesn't have to round-trip with the current PNG.
    figure_index_path = tmp_path / "说明书附图.md"
    figure_index_path.write_text("# 说明书附图\n", encoding="utf-8")
    for index, item in enumerate(report_payload["inputs"]["artifacts"]):
        if item.get("artifact_id") == "figure_index":
            report_payload["inputs"]["artifacts"][index] = {
                "artifact_id": "figure_index",
                "path": str(figure_index_path),
                "sha256": digest(figure_index_path),
            }
    write_json(report, report_payload)
    visual = tmp_path / "docx-visual-review.json"
    write_json(visual, {
        "schema_id": "cn-patent-docx-visual-review/v1",
        "reviewed_at": "2026-09-09T00:00:00+08:00",
        "reviewer": "tester",
        "docx_path": str(docx),
        "docx_sha256": digest(docx),
        "page_count": 1,
        "checks": {
            "all_figures_present": True, "figures_legible": True,
            "figure_captions_same_page": True, "no_clipping": True,
            "no_abnormal_blank_pages": True, "abstract_figure_correct": True,
        },
        "approved": True,
    })
    result, payload = run(tmp_path, brief, drawing, report, verification, visual=visual)
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["status"] == "PASS"


# -----------------------------------------------------------------------------
# F02: 机器交付分支必须独立复算当前 DOCX，不得信任旧 freshness。
# -----------------------------------------------------------------------------

def test_docx_modified_after_assembly_is_rejected(tmp_path):
    """真实组装后修改 DOCX 内嵌图片，机器交付必须 FAIL（不再信任旧 freshness）。"""
    brief, drawing, report, verification, _png, _drawio, docx = fixture(tmp_path)
    docx.write_bytes(b"docx-tampered")
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in payload["errors"]}
    assert "DELIVERY-DOCX-OUTPUT-STALE" in codes or "DELIVERY-DOCX-STALE" in codes


def test_docx_replaced_by_other_file_is_rejected(tmp_path):
    brief, drawing, report, verification, _png, _drawio, docx = fixture(tmp_path)
    # Replace DOCX contents with arbitrary bytes without updating report's
    # output_sha256.  Independently recomputed freshness must surface a stale
    # hash regardless of which code the underlying verifier picks.
    docx.write_bytes(b"totally-different-content")
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in payload["errors"]}
    assert codes & {"DELIVERY-DOCX-OUTPUT-STALE", "DELIVERY-DOCX-STALE"}


def test_docx_deleted_is_rejected(tmp_path):
    brief, drawing, report, verification, _png, _drawio, docx = fixture(tmp_path)
    docx.unlink()
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in payload["errors"]}
    assert codes & {"DELIVERY-DOCX-OUTPUT-STALE", "DELIVERY-DOCX-STALE"}


def test_drawing_verification_without_figures_array_is_rejected(tmp_path):
    """旧 fixture 只校验 brief_sha256，没有 per-figure PNG/Draw.io 绑定，必须 FAIL。"""
    brief, _drawing_full, report, verification, png, drawio, _docx = fixture(tmp_path)
    stale_drawing = tmp_path / "drawing-verification.json"
    write_json(stale_drawing, {
        "status": "PASS",
        "errors": [],
        "brief_sha256": digest(brief),
    })
    result, payload = run(tmp_path, brief, stale_drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in payload["errors"]}
    assert "DELIVERY-DRAWING-BINDING" in codes


def test_drawing_png_sha_stale_is_rejected(tmp_path):
    brief, drawing, report, verification, png, _drawio, _docx = fixture(tmp_path)
    png.write_bytes(b"changed-after-drawing")
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in payload["errors"]}
    assert "DELIVERY-DRAWING-EVIDENCE-STALE" in codes


def test_drawing_drawio_sha_stale_is_rejected(tmp_path):
    brief, drawing, report, verification, _png, drawio, _docx = fixture(tmp_path)
    drawio.write_bytes(b"<mxfile>changed</mxfile>")
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in payload["errors"]}
    assert "DELIVERY-DRAWING-EVIDENCE-STALE" in codes


def test_drawing_png_path_mismatch_is_rejected(tmp_path):
    brief, drawing, report, verification, _png, _drawio, _docx = fixture(tmp_path)
    payload = json.loads(drawing.read_text(encoding="utf-8"))
    payload["figures"][0]["png"]["path"] = str(tmp_path / "drawings/其它.png")
    write_json(drawing, payload)
    result, output = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    codes = {item["code"] for item in output["errors"]}
    assert "DELIVERY-DRAWING-BINDING" in codes


def test_old_freshness_report_with_replaced_docx_is_rejected(tmp_path):
    """仅替换 DOCX 文件，保留旧 docx-verification.json 为 PASS，仍必须被拒。"""
    brief, drawing, report, verification, _png, _drawio, docx = fixture(tmp_path)
    docx.write_bytes(b"replacement-bytes")
    result, payload = run(tmp_path, brief, drawing, report, verification)
    assert result.returncode == 2, result.stdout + result.stderr
    # 旧 freshness 必须被视为历史证据，不再阻断；当前复算失败即拒绝。
    assert payload["docx_assembly_reverified_status"] == "FAIL"
