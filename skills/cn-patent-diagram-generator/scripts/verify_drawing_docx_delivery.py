#!/usr/bin/env python3
"""验证最终附图已通过门禁，并确实作为当前图片嵌入最终 DOCX。

机器交付分支必须独立复算当前 DOCX/组装报告，不得信任旧的 freshness：
  * 重新调用 ``verify_docx_assembly.verify`` 对当前 ``docx-report`` 执行
    freshness 校验；任何陈旧 output/output_sha256/inputs.artifacts 哈希都会
    触发失败。
  * ``docx-report.output_sha256`` 必须等于当前 DOCX 文件 SHA-256。
  * ``drawing-verification`` 必须以 ``figures[]`` 数组逐图给出
    ``png.path``/``png.sha256``/``drawio.path``/``drawio.sha256``，并且
    这些路径与 SHA-256 必须与当前 brief 的对应产物字节一致；缺少字段
    或只校验 brief_sha256 的旧 fixture 会被拒绝。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
VERIFY_DOCX_ASSEMBLY_PATH = (
    SCRIPT_DIR.parent.parent
    / "cn-patent-application-creator"
    / "scripts"
    / "verify_docx_assembly.py"
)
_docx_spec = importlib.util.spec_from_file_location(
    "verify_docx_assembly_for_delivery", VERIFY_DOCX_ASSEMBLY_PATH
)
if _docx_spec is None or _docx_spec.loader is None:
    raise RuntimeError(f"无法加载 verify_docx_assembly: {VERIFY_DOCX_ASSEMBLY_PATH}")
_docx_assembly = importlib.util.module_from_spec(_docx_spec)
sys.modules[_docx_spec.name] = _docx_assembly
_docx_spec.loader.exec_module(_docx_assembly)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label}顶层必须为对象")
    return value


def resolve(base_dir: Path, raw: str) -> Path:
    """按所属证据文件/案件目录解析路径，并禁止越出案件目录。"""
    path = Path(raw)
    path = path.resolve() if path.is_absolute() else (base_dir / path).resolve()
    path.relative_to(base_dir.resolve())
    return path


def _verify_current_docx_assembly(docx_report_path: Path) -> dict[str, Any]:
    """独立复算当前 DOCX 组装报告的新鲜度与字节绑定。

    直接调用 ``verify_docx_assembly.verify``，避免信任任何旧 freshness 报告。
    """
    try:
        return _docx_assembly.verify(docx_report_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema_id": _docx_assembly.RESULT_SCHEMA_ID,
            "status": "FAIL",
            "errors": [
                {
                    "code": "DELIVERY-DOCX-CRASH",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }


def _check_docx_output_sha(docx_report: dict[str, Any], docx_report_dir: Path, errors: list[dict[str, str]]) -> None:
    """独立比较 ``docx-report.output_sha256`` 与当前 DOCX 字节。"""
    output_value = docx_report.get("output")
    output_sha = docx_report.get("output_sha256")
    if not isinstance(output_value, str) or not output_value:
        errors.append({"code": "DELIVERY-DOCX-OUTPUT", "message": "docx_report 缺少 output 路径"})
        return
    try:
        raw_output = Path(output_value)
        output_path = (raw_output if raw_output.is_absolute() else docx_report_dir / raw_output).resolve()
    except (TypeError, ValueError):
        errors.append({"code": "DELIVERY-DOCX-OUTPUT", "message": f"DOCX output 路径无法解析：{output_value!r}"})
        return
    if not output_path.is_file():
        errors.append({"code": "DELIVERY-DOCX-OUTPUT", "message": f"DOCX不存在：{output_path}"})
        return
    if not isinstance(output_sha, str) or len(output_sha) != 64:
        errors.append({"code": "DELIVERY-DOCX-OUTPUT-SHA", "message": "docx_report.output_sha256 缺失或格式错误"})
        return
    current = sha256(output_path)
    if current != output_sha:
        errors.append(
            {
                "code": "DELIVERY-DOCX-OUTPUT-STALE",
                "message": (
                    f"docx_report.output_sha256 与当前DOCX不一致："
                    f"report={output_sha[:12]}… current={current[:12]}…"
                ),
            }
        )


def _collect_drawing_bindings(
    drawing: dict[str, Any], errors: list[dict[str, str]]
) -> dict[int, dict[str, Any]]:
    """从 drawing verification 中读取 ``figures[]`` 数组并校验字段完整性。"""
    figures = drawing.get("figures")
    if not isinstance(figures, list) or not figures:
        errors.append(
            {
                "code": "DELIVERY-DRAWING-BINDING",
                "message": "drawing verification 缺少 figures[] 数组；不得仅依赖 brief_sha256 信任旧证据",
            }
        )
        return {}
    seen: set[int] = set()
    out: dict[int, dict[str, Any]] = {}
    for item in figures:
        if not isinstance(item, dict):
            errors.append({"code": "DELIVERY-DRAWING-BINDING", "message": "drawing figures[] 含非对象项"})
            continue
        number = item.get("figure_number")
        if type(number) is not int or number <= 0:
            errors.append({"code": "DELIVERY-DRAWING-BINDING", "message": "drawing figure 缺少整数 figure_number"})
            continue
        if number in seen:
            errors.append({"code": "DELIVERY-DRAWING-BINDING", "message": f"drawing figure_number 重复：{number}"})
            continue
        seen.add(number)
        out[number] = item
    return out


def _verify_figure_binding(
    figure_number: int,
    brief_outputs: dict[str, Any],
    drawing_figure: dict[str, Any],
    case_dir: Path,
    errors: list[dict[str, str]],
) -> None:
    """逐图核对 PNG/Draw.io 路径与 SHA-256 与当前文件一致。"""
    png_info = drawing_figure.get("png") or {}
    png_path_value = png_info.get("path")
    png_sha = png_info.get("sha256")
    brief_png_value = brief_outputs.get("final_png")
    if not isinstance(brief_png_value, str) or not brief_png_value:
        errors.append(
            {
                "code": "DELIVERY-DRAWING-BINDING",
                "message": f"figure {figure_number} brief 缺少 outputs.final_png",
            }
        )
    elif not isinstance(png_path_value, str) or not png_path_value:
        errors.append(
            {
                "code": "DELIVERY-DRAWING-BINDING",
                "message": f"figure {figure_number} drawing png.path 缺失",
            }
        )
    elif not isinstance(png_sha, str) or len(png_sha) != 64:
        errors.append(
            {
                "code": "DELIVERY-DRAWING-BINDING",
                "message": f"figure {figure_number} drawing png.sha256 缺失或格式错误",
            }
        )
    else:
        try:
            expected_png = resolve(case_dir, brief_png_value)
            actual_png = resolve(case_dir, png_path_value)
        except (TypeError, ValueError) as exc:
            errors.append(
                {
                    "code": "DELIVERY-DRAWING-BINDING",
                    "message": f"figure {figure_number} PNG 路径无法解析：{exc}",
                }
            )
        else:
            if actual_png != expected_png:
                errors.append(
                    {
                        "code": "DELIVERY-DRAWING-BINDING",
                        "message": (
                            f"figure {figure_number} drawing png.path 与 brief 不一致："
                            f"brief={expected_png} drawing={actual_png}"
                        ),
                    }
                )
            elif not expected_png.is_file():
                errors.append(
                    {
                        "code": "DELIVERY-DRAWING-EVIDENCE",
                        "message": f"figure {figure_number} 当前 PNG 不存在：{expected_png}",
                    }
                )
            else:
                current_png_sha = sha256(expected_png)
                if current_png_sha != png_sha:
                    errors.append(
                        {
                            "code": "DELIVERY-DRAWING-EVIDENCE-STALE",
                            "message": (
                                f"figure {figure_number} PNG SHA-256 与当前文件不一致："
                                f"drawing={png_sha[:12]}… current={current_png_sha[:12]}…"
                            ),
                        }
                    )

    drawio_info = drawing_figure.get("drawio") or {}
    brief_drawio_value = brief_outputs.get("drawio")
    if not isinstance(brief_drawio_value, str) or not brief_drawio_value:
        errors.append({
            "code": "DELIVERY-DRAWING-BINDING",
            "message": f"figure {figure_number} brief 缺少必需 outputs.drawio",
        })
    else:
        drawio_path_value = drawio_info.get("path")
        drawio_sha = drawio_info.get("sha256")
        if not isinstance(drawio_path_value, str) or not drawio_path_value:
            errors.append(
                {
                    "code": "DELIVERY-DRAWING-BINDING",
                    "message": f"figure {figure_number} drawing drawio.path 缺失",
                }
            )
        elif not isinstance(drawio_sha, str) or len(drawio_sha) != 64:
            errors.append(
                {
                    "code": "DELIVERY-DRAWING-BINDING",
                    "message": f"figure {figure_number} drawing drawio.sha256 缺失或格式错误",
                }
            )
        else:
            try:
                expected_drawio = resolve(case_dir, brief_drawio_value)
                actual_drawio = resolve(case_dir, drawio_path_value)
            except (TypeError, ValueError) as exc:
                errors.append(
                    {
                        "code": "DELIVERY-DRAWING-BINDING",
                        "message": f"figure {figure_number} Draw.io 路径无法解析：{exc}",
                    }
                )
            else:
                if actual_drawio != expected_drawio:
                    errors.append(
                        {
                            "code": "DELIVERY-DRAWING-BINDING",
                            "message": (
                                f"figure {figure_number} drawing drawio.path 与 brief 不一致："
                                f"brief={expected_drawio} drawing={actual_drawio}"
                            ),
                        }
                    )
                elif not expected_drawio.is_file():
                    errors.append(
                        {
                            "code": "DELIVERY-DRAWING-EVIDENCE",
                            "message": f"figure {figure_number} 当前 Draw.io 不存在：{expected_drawio}",
                        }
                    )
                else:
                    current_drawio_sha = sha256(expected_drawio)
                    if current_drawio_sha != drawio_sha:
                        errors.append(
                            {
                                "code": "DELIVERY-DRAWING-EVIDENCE-STALE",
                                "message": (
                                    f"figure {figure_number} Draw.io SHA-256 与当前文件不一致："
                                    f"drawing={drawio_sha[:12]}… current={current_drawio_sha[:12]}…"
                                ),
                            }
                        )


def verify(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = args.case_dir.resolve()
    brief_path = args.brief.resolve()
    brief = load(brief_path, "drawing brief")
    drawing = load(args.drawing_verification.resolve(), "drawing verification")
    docx_report = load(args.docx_report.resolve(), "DOCX report")
    docx_verification = load(args.docx_verification.resolve(), "DOCX verification")
    errors: list[dict[str, str]] = []

    # 1. 附图门禁本身必须处于 PASS，且 brief_sha256 与当前 brief 一致。
    if drawing.get("status") != "PASS" or drawing.get("errors"):
        errors.append({"code": "DELIVERY-DRAWING", "message": "最终附图验证未通过"})
    if drawing.get("brief_sha256") != sha256(brief_path):
        errors.append({"code": "DELIVERY-DRAWING-STALE", "message": "最终附图验证未绑定当前 drawing brief"})

    # 2. 独立复算当前 DOCX/组装报告（不再信任旧 freshness）。
    fresh = _verify_current_docx_assembly(args.docx_report.resolve())
    if fresh.get("status") != "PASS":
        for err in fresh.get("errors") or [
            {"code": "DELIVERY-DOCX-STALE", "message": "组装重新核验未通过"}
        ]:
            errors.append(
                {
                    "code": "DELIVERY-DOCX-STALE",
                    "message": f"当前组装重新核验失败：{err.get('message', '')}".rstrip("："),
                }
            )
    else:
        _check_docx_output_sha(docx_report, args.docx_report.resolve().parent, errors)

    # 3. 旧 docx-verification.json 仍要求曾处于 PASS，但已不再是新鲜度证据。
    if docx_verification.get("status") != "PASS" or docx_verification.get("errors"):
        errors.append(
            {"code": "DELIVERY-DOCX-VERIFICATION", "message": "历史 DOCX freshness 报告未通过"}
        )

    # 4. DOCX 报告状态门禁（仅作为最终结构/视觉状态的额外信号）。
    allowed_docx_statuses = {"STRUCTURE_VERIFIED"}
    if args.docx_visual_review:
        allowed_docx_statuses.add("STRUCTURE_VERIFIED_VISUAL_REVIEW_PENDING")
    if docx_report.get("status") not in allowed_docx_statuses:
        errors.append({"code": "DELIVERY-DOCX", "message": "DOCX组装报告未通过结构验证"})

    # 5. 附图验证必须以 figures[] 数组逐图绑定 PNG/Draw.io 当前字节。
    drawing_figures = _collect_drawing_bindings(drawing, errors)
    artifacts = {
        item.get("artifact_id"): item
        for item in ((docx_report.get("inputs") or {}).get("artifacts") or [])
        if isinstance(item, dict)
    }
    expected: dict[str, dict[str, Any]] = {}
    brief_figure_numbers: set[int] = set()
    brief_by_number: dict[int, dict[str, Any]] = {}
    brief_figures = brief.get("figures")
    if not isinstance(brief_figures, list) or not brief_figures:
        errors.append({"code": "DELIVERY-BRIEF", "message": "drawing brief 缺少非空 figures[]"})
        brief_figures = []
    for figure in brief_figures:
        if not isinstance(figure, dict) or (type(figure.get("figure_number")) is not int or figure["figure_number"] <= 0):
            errors.append({"code": "DELIVERY-BRIEF", "message": "drawing brief figure 缺少整数 figure_number"})
            continue
        number = figure["figure_number"]
        if number in brief_by_number:
            errors.append({"code": "DELIVERY-BRIEF", "message": f"drawing brief figure_number 重复：{number}"})
            continue
        outputs = figure.get("outputs")
        if not isinstance(outputs, dict):
            errors.append({"code": "DELIVERY-DRAWING-BINDING", "message": f"figure {number} 缺少 outputs 对象"})
            continue
        brief_figure_numbers.add(number)
        brief_by_number[number] = figure
        for output_key in ("final_png", "drawio"):
            raw_output = outputs.get(output_key)
            if not isinstance(raw_output, str) or not raw_output:
                errors.append({"code": "DELIVERY-DRAWING-BINDING", "message": f"figure {number} brief 缺少 outputs.{output_key}"})
        try:
            png = resolve(case_dir, outputs["final_png"])
            drawio = resolve(case_dir, outputs["drawio"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"code": "DELIVERY-DRAWING-BINDING", "message": f"figure {number} 产物路径无法解析：{exc}"})
            continue
        if not png.is_file():
            errors.append({"code": "DELIVERY-DRAWING-EVIDENCE", "message": f"figure {number} 当前 PNG 不存在：{png}"})
        else:
            expected[f"figure_{number}"] = {"path": str(png), "sha256": sha256(png)}
        if not drawio.is_file():
            errors.append({"code": "DELIVERY-DRAWING-EVIDENCE", "message": f"figure {number} 当前 Draw.io 不存在：{drawio}"})
    for artifact_id, item in expected.items():
        actual = artifacts.get(artifact_id)
        if actual is None:
            errors.append({"code": "DELIVERY-DOCX-FIGURE", "message": f"DOCX报告缺少 {artifact_id}"})
            continue
        raw_artifact = Path(actual.get("path", ""))
        artifact_path = (raw_artifact if raw_artifact.is_absolute() else args.docx_report.resolve().parent / raw_artifact).resolve()
        if artifact_path != Path(item["path"]).resolve():
            errors.append({"code": "DELIVERY-DOCX-FIGURE", "message": f"{artifact_id} 路径不是当前最终PNG"})
        if actual.get("sha256") != item["sha256"]:
            errors.append({"code": "DELIVERY-DOCX-FIGURE-STALE", "message": f"{artifact_id} 哈希已陈旧"})
    actual_figure_ids = {key for key in artifacts if isinstance(key, str) and re.fullmatch(r"figure_\d+", key)}
    if actual_figure_ids != set(expected):
        errors.append({"code": "DELIVERY-DOCX-FIGURE-SET", "message": f"DOCX附图集合不一致：{sorted(actual_figure_ids)} != {sorted(expected)}"})

    if drawing_figures:
        drawing_numbers = set(drawing_figures)
        if drawing_numbers != brief_figure_numbers:
            errors.append(
                {
                    "code": "DELIVERY-DRAWING-BINDING",
                    "message": (
                        f"drawing figures[] 与 brief 不匹配：drawing={sorted(drawing_numbers)} "
                        f"brief={sorted(brief_figure_numbers)}"
                    ),
                }
            )
        else:
            for number, figure in brief_by_number.items():
                _verify_figure_binding(
                    number,
                    figure.get("outputs") or {},
                    drawing_figures.get(number, {}),
                    case_dir,
                    errors,
                )

    render = docx_report.get("render") or {}
    docx_visual = None
    if args.docx_visual_review:
        docx_visual = load(args.docx_visual_review.resolve(), "DOCX visual review")
        raw_output = Path(docx_report.get("output", ""))
        output_path = (raw_output if raw_output.is_absolute() else args.docx_report.resolve().parent / raw_output).resolve()
        output_path = resolve(case_dir, str(output_path))
        if docx_visual.get("schema_id") != "cn-patent-docx-visual-review/v1":
            errors.append({"code": "DELIVERY-DOCX-VISUAL", "message": "DOCX视觉复核schema无效"})
        if docx_visual.get("approved") is not True:
            errors.append({"code": "DELIVERY-DOCX-VISUAL", "message": "DOCX视觉复核未批准"})
        try:
            reviewed_docx = resolve(case_dir, docx_visual.get("docx_path", ""))
        except (TypeError, ValueError):
            reviewed_docx = None
        if reviewed_docx != output_path or docx_visual.get("docx_sha256") != sha256(output_path):
            errors.append({"code": "DELIVERY-DOCX-VISUAL-STALE", "message": "DOCX视觉复核未绑定当前DOCX"})
        checks = docx_visual.get("checks") or {}
        for key in ("all_figures_present", "figures_legible", "figure_captions_same_page", "no_clipping", "no_abnormal_blank_pages", "abstract_figure_correct"):
            if checks.get(key) is not True:
                errors.append({"code": "DELIVERY-DOCX-VISUAL", "message": f"DOCX视觉检查未通过：{key}"})
    elif render.get("requested") is True:
        errors.append({"code": "DELIVERY-DOCX-VISUAL", "message": "已请求DOCX视觉检查，但未提供批准的视觉复核记录"})

    return {
        "schema_id": "cn-patent-drawing-docx-delivery-verification/v1",
        "status": "PASS" if not errors else "FAIL",
        "case_dir": str(case_dir),
        "brief_sha256": sha256(brief_path),
        "drawing_verification_sha256": sha256(args.drawing_verification.resolve()),
        "docx_report_sha256": sha256(args.docx_report.resolve()),
        "docx_verification_sha256": sha256(args.docx_verification.resolve()),
        "docx_assembly_reverified_status": fresh.get("status"),
        "docx_assembly_reverified_errors": [
            err.get("message") for err in (fresh.get("errors") or [])
        ],
        "figure_count": len(expected),
        "docx_visual_review": str(args.docx_visual_review.resolve()) if args.docx_visual_review else None,
        "errors": errors,
        "evidence_scope": {
            "proves": [
                "当前附图验证已通过",
                "drawing verification 通过 figures[] 数组绑定当前 PNG/Draw.io 路径与 SHA-256",
                "DOCX 组装报告与所有 inputs.artifacts 重新核验通过",
                "DOCX 实际字节与 docx-report.output_sha256 一致",
                "DOCX 嵌入图片路径与 SHA-256 与当前最终 PNG 一致",
            ],
            "does_not_prove": [
                "未明确请求时的 DOCX 逐页视觉效果",
                "申请文件法律实体条件",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--drawing-verification", required=True, type=Path)
    parser.add_argument("--docx-report", required=True, type=Path)
    parser.add_argument("--docx-verification", required=True, type=Path)
    parser.add_argument("--docx-visual-review", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = verify(args)
    except Exception as exc:
        report = {"schema_id": "cn-patent-drawing-docx-delivery-verification/v1", "status": "FAIL", "errors": [{"code": "DELIVERY-CRASH", "message": f"{type(exc).__name__}: {exc}"}]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
