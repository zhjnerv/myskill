#!/usr/bin/env python3
"""复核单项专利附图约束。

几何、配色、白边、导出绑定和视觉绑定会按领域清单重读整组来源，以及每一幅
附图各自的母版、PNG 或导出/视觉记录，再调用领域验证函数或核对当前哈希。
只解释最终报告字段的检查仍属于 schema，不冒充几何测量。
清单指向的文件缺失时直接失败，不补造 PNG 或 Draw.io。
领域夹具里的附图输入是 `.drawio.txt` 文本测试模板，不是正式交付附图，
也不使用分发后缀清单之外的 `.xml`。
本适配器不重新启动 Draw.io 或 Word 做视觉导出；官方 CLI 复算仍由
``verify_patent_drawings.py`` 在正式附图验证中执行。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SUPPORTED = {
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
VISUAL_CHECKS = {
    "text_legible",
    "no_text_overlap",
    "no_edge_crossing",
    "no_edge_through_node",
    "no_arrow_ambiguity",
    "labels_adjacent",
    "node_text_proportionate",
    "no_text_overflow",
    "no_excessive_canvas_margin",
    "no_unnecessary_detours",
    "consistent_typography",
    "balanced_spacing",
    "clear_visual_hierarchy",
    "formal_patent_style",
    "grayscale_safe",
    "no_figure_number_on_canvas",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("最终验证报告顶层必须是对象")
    return value


def error_codes(report: dict[str, Any]) -> set[str]:
    return {
        item.get("code", "")
        for item in report.get("errors", [])
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    }


def check_constraint(report: dict[str, Any], constraint: str) -> tuple[bool, list[str]]:
    codes = error_codes(report)
    figures = [item for item in report.get("figures", []) if isinstance(item, dict)]

    if constraint == "PATENT-DRAWING-SOURCE-BINDING":
        brief = report.get("brief_validation") or {}
        relevant = sorted(code for code in codes if code.startswith("BRIEF-"))
        ok = brief.get("status") == "PASS" and not relevant
        return ok, ["brief-pass"] if ok else relevant or ["brief-fail"]

    if constraint == "PATENT-DRAWING-STYLE-REFERENCE":
        brief = report.get("brief_validation") or {}
        relevant = sorted(code for code in codes if code.startswith("BRIEF-STYLE"))
        ok = brief.get("status") == "PASS" and not relevant
        return ok, ["style-reference-pass"] if ok else relevant or ["style-reference-fail"]

    if constraint == "PATENT-DRAWING-TECH-COVERAGE":
        prefixes = ("DRAWING-ELEMENT", "DRAWING-LABEL", "DRAWING-MARK", "DRAWING-RELATION", "DRAWING-EXTRA")
        relevant = sorted(code for code in codes if code.startswith(prefixes))
        ok = bool(figures) and all((item.get("drawio") or {}).get("passed") is True for item in figures) and not relevant
        return ok, [f"figures:{len(figures)}"] if ok else relevant or ["drawio-coverage-fail"]

    if constraint == "PATENT-DRAWING-STEP-ISOMORPHISM":
        brief = report.get("brief_validation") or {}
        relevant = sorted(
            code for code in codes
            if code.startswith(("BRIEF-STEP", "BRIEF-DECISION", "BRIEF-LOOP", "BRIEF-ARCHITECTURE"))
        )
        v4 = report.get("schema_id") == "cn-patent-drawing-verification/v4"
        figures_bound = bool(brief.get("figures")) and all(
            isinstance(item.get("method_claim_number"), int) and bool(item.get("bound_step_ids"))
            for item in brief.get("figures", []) if isinstance(item, dict)
        )
        ok = v4 and brief.get("status") == "PASS" and figures_bound and not relevant
        return ok, ["method-step-isomorphism-pass"] if ok else relevant or ["method-step-isomorphism-fail"]

    if constraint == "PATENT-DRAWING-DIRECT-CONNECTOR":
        prefixes = (
            "DRAWING-DIRECT", "DRAWING-NATIVE-EDGE-LABEL", "DRAWING-DETACHED-EDGE-LABEL",
            "DRAWING-TEXT-WAYPOINT", "DRAWING-ABSOLUTE-ENDPOINT", "DRAWING-SELF-LOOP",
            "DRAWING-ROUTE", "DRAWING-LINT",
        )
        relevant = sorted(code for code in codes if code.startswith(prefixes))
        lint_ok = bool(figures) and all(
            ((item.get("drawio") or {}).get("drawio_skill_lint") or {}).get("exit_code") == 0
            for item in figures
        )
        ok = lint_ok and not relevant
        return ok, ["direct-connectors-pass"] if ok else relevant or ["connector-lint-fail"]

    if constraint == "PATENT-DRAWING-NODE-SHAPE":
        relevant = sorted(code for code in codes if code == "DRAWING-CYLINDER-SEMANTICS")
        has_drawio_evidence = bool(figures) and all(isinstance(item.get("drawio"), dict) for item in figures)
        ok = has_drawio_evidence and not relevant
        return ok, ["node-shape-pass"] if ok else relevant or ["node-shape-fail"]

    if constraint == "PATENT-DRAWING-EDGE-LABEL-READABILITY":
        relevant = sorted(code for code in codes if code.startswith(("DRAWING-EDGE-LABEL-FONT", "DRAWING-EDGE-LABEL-CLEARANCE", "DRAWING-RELATION-LABEL-POLICY")))
        has_drawio_evidence = bool(figures) and all(isinstance(item.get("drawio"), dict) for item in figures)
        ok = has_drawio_evidence and not relevant
        return ok, ["edge-label-readability-pass"] if ok else relevant or ["edge-label-readability-fail"]

    if constraint == "PATENT-DRAWING-NODE-TEXT-FIT":
        prefixes = (
            "DRAWING-NODE-TEXT-POLICY", "DRAWING-FONT-SIZE", "DRAWING-TEXT-WRAP",
            "DRAWING-NODE-PROPORTION", "DRAWING-NODE-HEIGHT", "DRAWING-CHINESE-WRAP",
            "DRAWING-TEXT-OVERFLOW",
        )
        relevant = sorted(code for code in codes if code.startswith(prefixes))
        has_drawio_evidence = bool(figures) and all(isinstance(item.get("drawio"), dict) for item in figures)
        ok = has_drawio_evidence and not relevant
        return ok, ["node-text-fit-pass"] if ok else relevant or ["node-text-fit-fail"]

    if constraint == "PATENT-DRAWING-VERTICAL-SPACING":
        relevant = sorted(code for code in codes if code.startswith("DRAWING-VERTICAL-SPACING"))
        has_drawio_evidence = bool(figures) and all(isinstance(item.get("drawio"), dict) for item in figures)
        ok = has_drawio_evidence and not relevant
        return ok, ["vertical-spacing-pass"] if ok else relevant or ["vertical-spacing-fail"]

    if constraint == "PATENT-DRAWING-PNG-MARGIN":
        relevant = sorted(code for code in codes if code.startswith(("DRAWING-EXCESSIVE-MARGIN", "DRAWING-EXPORT-MODE")))
        ok = bool(figures) and all(
            ((item.get("png") or {}).get("maximum_margin") is not None)
            for item in figures
        ) and not relevant
        return ok, ["png-margin-pass"] if ok else relevant or ["png-margin-fail"]

    if constraint == "PATENT-DRAWING-COLOR":
        relevant = sorted(code for code in codes if code == "DRAWING-COLOR")
        ok = bool(figures) and not relevant
        return ok, ["color-policy-pass"] if ok else relevant or ["color-policy-fail"]

    if constraint == "PATENT-DRAWING-OFFICIAL-EXPORT":
        prefixes = ("DRAWING-EXPORT", "DRAWING-DPI", "DRAWING-ARTIFACT")
        relevant = sorted(code for code in codes if code.startswith(prefixes))
        ok = bool(figures) and all((item.get("official_reexport") or {}).get("matched") is True for item in figures) and not relevant
        return ok, ["official-reexport-match"] if ok else relevant or ["official-reexport-fail"]

    if constraint == "PATENT-DRAWING-VISUAL-BINDING":
        relevant = sorted(code for code in codes if code.startswith("DRAWING-VISUAL"))
        reviews = [item.get("visual_review") or {} for item in figures]
        ok = bool(reviews) and not relevant
        for review in reviews:
            checks = review.get("checks") or {}
            ok = ok and review.get("approved") is True and all(checks.get(name) is True for name in VISUAL_CHECKS)
            ok = ok and (checks.get("monochrome") is True or checks.get("restrained_color") is True)
        return ok, ["visual-review-bound"] if ok else relevant or ["visual-review-fail"]

    raise ValueError(f"未知约束：{constraint}")



DRAWIO_CONSTRAINTS = {
    "PATENT-DRAWING-DIRECT-CONNECTOR": (
        "DRAWING-DIRECT", "DRAWING-NATIVE-EDGE-LABEL", "DRAWING-DETACHED-EDGE-LABEL",
        "DRAWING-TEXT-WAYPOINT", "DRAWING-ABSOLUTE-ENDPOINT", "DRAWING-SELF-LOOP",
        "DRAWING-ROUTE", "DRAWING-LINT",
    ),
    "PATENT-DRAWING-NODE-SHAPE": ("DRAWING-CYLINDER-SEMANTICS",),
    "PATENT-DRAWING-EDGE-LABEL-READABILITY": (
        "DRAWING-EDGE-LABEL-FONT", "DRAWING-EDGE-LABEL-CLEARANCE", "DRAWING-RELATION-LABEL-POLICY",
    ),
    "PATENT-DRAWING-NODE-TEXT-FIT": (
        "DRAWING-NODE-TEXT-POLICY", "DRAWING-FONT-SIZE", "DRAWING-TEXT-WRAP",
        "DRAWING-NODE-PROPORTION", "DRAWING-NODE-HEIGHT", "DRAWING-CHINESE-WRAP",
        "DRAWING-TEXT-OVERFLOW",
    ),
    "PATENT-DRAWING-VERTICAL-SPACING": ("DRAWING-VERTICAL-SPACING",),
    "PATENT-DRAWING-COLOR": ("DRAWING-COLOR",),
}

DOMAIN_FIELDS = {
    **{name: ("drawio",) for name in DRAWIO_CONSTRAINTS},
    "PATENT-DRAWING-PNG-MARGIN": ("png",),
    "PATENT-DRAWING-OFFICIAL-EXPORT": ("drawio", "png", "export_report"),
    "PATENT-DRAWING-VISUAL-BINDING": ("png",),
}
BRIEF_OUTPUT_KEYS = {"drawio": "drawio", "png": "final_png", "export_report": "export_report"}
MANIFEST_SCHEMA = "cn-patent-drawing-domain-manifest/v1"
_VERIFIER = None


def load_verifier():
    """加载正式附图验证器，供适配器重跑领域测量。"""
    global _VERIFIER
    if _VERIFIER is None:
        script = Path(__file__).resolve().parent / "verify_patent_drawings.py"
        spec = importlib.util.spec_from_file_location("patent_drawing_domain_verifier", script)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载领域验证器：{script}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _VERIFIER = module
    return _VERIFIER


def _load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} 顶层必须是对象")
    return value


def _resolve_output(base: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} 缺少路径")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (base.parent / path).resolve()


def _report_figures(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in report.get("figures", []) if isinstance(item, dict)]


def _index_figures(items: list[Any]) -> dict[int, dict[str, Any]] | None:
    indexed: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        number = item.get("figure_number")
        if type(number) is not int or number in indexed:
            return None
        indexed[number] = item
    return indexed


def _load_manifest(path: Path) -> dict[str, Any]:
    data = _load_json(path, "领域清单")
    if data.get("schema_id") != MANIFEST_SCHEMA:
        raise ValueError("领域清单 schema 不正确")
    sources = data.get("sources")
    figures = data.get("figures")
    if not isinstance(sources, list) or not isinstance(figures, list) or not figures:
        raise ValueError("领域清单缺少来源或附图")
    resolved_sources = []
    seen_sources: set[str] = set()
    for index, item in enumerate(sources, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"领域清单来源第 {index} 项无效")
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen_sources:
            raise ValueError(f"领域清单来源第 {index} 项标识无效或重复")
        seen_sources.add(artifact_id)
        resolved_sources.append({
            "artifact_id": artifact_id,
            "path": _resolve_output(path, item.get("path"), f"来源 {artifact_id}"),
        })
    resolved_figures: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(figures, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"领域清单附图第 {index} 项无效")
        number = item.get("figure_number")
        if type(number) is not int or number in resolved_figures:
            raise ValueError(f"领域清单附图第 {index} 项图号无效或重复")
        entry: dict[str, Any] = {"figure_number": number}
        for key in ("drawio", "png", "export_report"):
            if key in item:
                entry[key] = _resolve_output(path, item.get(key), f"图{number} {key}")
        resolved_figures[number] = entry
    return {"sources": resolved_sources, "figures": resolved_figures}


def _missing_declared(manifest: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """只检查清单已经声明的路径。缺失即失败，不创建文件。"""
    missing = []
    for number, entry in sorted(manifest["figures"].items()):
        keys = list(required)
        for key in ("drawio", "png", "export_report"):
            if key in entry and key not in keys:
                keys.append(key)
        for key in keys:
            file_path = entry.get(key)
            if not isinstance(file_path, Path) or not file_path.is_file():
                missing.append(f"figure-{number}:{key}")
    for source in manifest["sources"]:
        if not source["path"].is_file():
            missing.append(f"source:{source['artifact_id']}")
    return missing


def _bind_sources(brief: dict[str, Any], manifest: dict[str, Any], brief_path: Path) -> tuple[bool, list[str]]:
    artifacts = brief.get("source_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False, ["source-set-missing"]
    brief_ids = []
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("artifact_id"), str) or not item["artifact_id"]:
            return False, ["source-set-invalid"]
        brief_ids.append(item["artifact_id"])
    if len(set(brief_ids)) != len(brief_ids):
        return False, ["source-set-invalid"]
    manifest_ids = [item["artifact_id"] for item in manifest["sources"]]
    if set(brief_ids) != set(manifest_ids):
        return False, ["source-set-coverage"]
    by_id = {item["artifact_id"]: item for item in manifest["sources"]}
    for item in artifacts:
        artifact_id = item["artifact_id"]
        bound = by_id[artifact_id]
        if item.get("sha256") != sha256(bound["path"]):
            return False, [f"source-hash-mismatch:{artifact_id}"]
        raw_path = item.get("path")
        if isinstance(raw_path, str) and raw_path:
            if _resolve_output(brief_path, raw_path, f"来源 {artifact_id}") != bound["path"]:
                return False, [f"source-path-mismatch:{artifact_id}"]
    return True, ["source-set-bound"]


def _align_figures(brief: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[int, dict[str, Any]] | None, list[str]]:
    figures = brief.get("figures")
    if not isinstance(figures, list) or not figures:
        return None, ["brief-figures-missing"]
    indexed = _index_figures(figures)
    if indexed is None or set(indexed) != set(manifest["figures"]):
        return None, ["figure-coverage"]
    return indexed, []


def _outputs_match(
    brief_path: Path,
    figures: dict[int, dict[str, Any]],
    manifest: dict[str, Any],
    required: tuple[str, ...],
) -> tuple[bool, list[str]]:
    for number, figure in figures.items():
        outputs = figure.get("outputs") if isinstance(figure.get("outputs"), dict) else {}
        entry = manifest["figures"][number]
        for key in required:
            expected = _resolve_output(brief_path, outputs.get(BRIEF_OUTPUT_KEYS[key]), BRIEF_OUTPUT_KEYS[key])
            if expected != entry[key]:
                return False, [f"{key}-artifact-mismatch", f"figure-{number}"]
    return True, []


def _measure_drawio(
    constraint: str,
    figures: dict[int, dict[str, Any]],
    manifest: dict[str, Any],
    brief: dict[str, Any],
) -> tuple[bool, list[str]]:
    verifier = load_verifier()
    policies = brief.get("global_constraints") or {}
    skill = verifier.find_drawio_skill(None)
    prefixes = DRAWIO_CONSTRAINTS[constraint]
    observed: list[str] = []
    digests: list[str] = []
    for number, figure in sorted(figures.items()):
        target = manifest["figures"][number]["drawio"]
        report = verifier.verify_drawio(
            target,
            figure,
            policies.get("color_policy") or {},
            skill,
            policies.get("node_text_policy"),
            policies.get("vertical_spacing_policy"),
            policies.get("node_shape_policy"),
            policies.get("relation_label_policy"),
        )
        relevant = sorted(item["code"] for item in report["errors"] if item["code"].startswith(prefixes))
        observed.extend(f"figure-{number}:{code}" for code in relevant)
        digests.append(f"figure-{number}:drawio-sha256:{sha256(target)[:12]}")
    return not observed, observed or [*digests, "measured-errors:0"]


def _bind_report_digests(
    report: dict[str, Any],
    manifest: dict[str, Any],
    field: str,
    manifest_key: str,
) -> tuple[bool, list[str]]:
    report_figures = _index_figures(_report_figures(report))
    if report_figures is None or set(report_figures) != set(manifest["figures"]):
        return False, ["figure-coverage"]
    notes = []
    for number, entry in sorted(manifest["figures"].items()):
        digest = sha256(entry[manifest_key])
        reported = (report_figures[number].get(field) or {}).get("sha256")
        if reported != digest:
            return False, [f"report-{field}-sha-mismatch", f"figure-{number}"]
        notes.append(f"figure-{number}:{field}-sha256:{digest[:12]}")
    return True, notes


def _measure_png(brief: dict[str, Any], manifest: dict[str, Any], report: dict[str, Any]) -> tuple[bool, list[str]]:
    verifier = load_verifier()
    policy = (brief.get("global_constraints") or {}).get("png_margin_policy") or {}
    threshold = int(policy.get("white_threshold", 245))
    limit = policy.get("maximum_margin_pixels")
    if not isinstance(limit, int) or isinstance(limit, bool):
        return False, ["png-margin-policy-missing"]
    report_figures = _index_figures(_report_figures(report))
    if report_figures is None or set(report_figures) != set(manifest["figures"]):
        return False, ["figure-coverage"]
    notes = []
    for number, entry in sorted(manifest["figures"].items()):
        target = entry["png"]
        info = verifier.png_info(target, threshold)
        margin = info.get("maximum_margin")
        if margin is None or margin > limit:
            return False, [f"figure-{number}:measured-maximum-margin:{margin}", f"limit:{limit}"]
        reported = report_figures[number].get("png") or {}
        if reported.get("sha256") != sha256(target) or reported.get("maximum_margin") != margin:
            return False, ["report-png-measurement-mismatch", f"figure-{number}", f"measured-maximum-margin:{margin}"]
        if isinstance(reported.get("margins"), dict) and reported.get("margins") != info.get("margins"):
            return False, ["report-png-margins-mismatch", f"figure-{number}"]
        notes.append(f"figure-{number}:margin:{margin}")
    return True, notes


def _measure_export(manifest: dict[str, Any], report: dict[str, Any]) -> tuple[bool, list[str]]:
    report_figures = _index_figures(_report_figures(report))
    if report_figures is None or set(report_figures) != set(manifest["figures"]):
        return False, ["figure-coverage"]
    notes = []
    for number, entry in sorted(manifest["figures"].items()):
        export = _load_json(entry["export_report"], f"图{number}导出记录")
        source_sha = (export.get("source") or {}).get("sha256")
        output_sha = ((export.get("outputs") or {}).get("png") or {}).get("sha256")
        drawio_sha = sha256(entry["drawio"])
        png_sha = sha256(entry["png"])
        if source_sha != drawio_sha or output_sha != png_sha:
            return False, ["export-record-byte-mismatch", f"figure-{number}"]
        item = report_figures[number]
        drawio_info = item.get("drawio") or {}
        png_info = item.get("png") or {}
        matched = (item.get("official_reexport") or {}).get("matched")
        if drawio_info.get("sha256") != drawio_sha or png_info.get("sha256") != png_sha or matched is not True:
            return False, ["report-export-binding-mismatch", f"figure-{number}"]
        notes.append(f"figure-{number}:export-bytes-match")
    return True, notes


def _checks_match(left: Any, right: Any) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and left == right


def _measure_visual(manifest: dict[str, Any], visual_path: Path, report: dict[str, Any]) -> tuple[bool, list[str]]:
    visual = _load_json(visual_path, "视觉记录")
    items = visual.get("figures")
    indexed = _index_figures(items) if isinstance(items, list) else None
    if indexed is None or set(indexed) != set(manifest["figures"]):
        return False, ["figure-coverage"]
    report_figures = _index_figures(_report_figures(report))
    if report_figures is None or set(report_figures) != set(indexed):
        return False, ["figure-coverage"]
    for number, item in sorted(indexed.items()):
        png = manifest["figures"][number].get("png")
        if not isinstance(png, Path) or not png.is_file():
            return False, [f"missing-domain-artifact:figure-{number}:png"]
        checks = item.get("checks") or {}
        if item.get("approved") is not True or item.get("png_sha256") != sha256(png):
            return False, ["visual-record-not-bound", f"figure-{number}"]
        if any(checks.get(name) is not True for name in VISUAL_CHECKS):
            return False, ["visual-record-failed-check", f"figure-{number}"]
        if (checks.get("monochrome") is True) == (checks.get("restrained_color") is True):
            return False, ["visual-record-color-mode", f"figure-{number}"]
        reported = report_figures[number].get("visual_review") or {}
        if reported.get("approved") is not True or not _checks_match(reported.get("checks"), checks):
            return False, ["report-visual-mismatch", f"figure-{number}"]
    return True, ["visual-record-bound"]


def _hash_manifest_files(manifest_path: Path, artifact_hash: dict[str, str]) -> None:
    try:
        manifest = _load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    for source in manifest["sources"]:
        if source["path"].is_file():
            artifact_hash[f"source:{source['artifact_id']}"] = sha256(source["path"])
    for number, entry in sorted(manifest["figures"].items()):
        for key in ("drawio", "png", "export_report"):
            file_path = entry.get(key)
            if isinstance(file_path, Path) and file_path.is_file():
                artifact_hash[f"figure-{number}:{key}"] = sha256(file_path)


def evaluate_domain(
    constraint: str,
    report: dict[str, Any],
    brief_path: Path | None,
    manifest_path: Path | None,
    visual_path: Path | None,
) -> tuple[bool, list[str]] | None:
    """重读清单中的当前文件。返回 None 表示该约束只做报告 schema 解释。"""
    if constraint not in DOMAIN_FIELDS:
        return None
    if manifest_path is None or not manifest_path.is_file():
        return False, ["missing-domain-artifact:manifest"]
    try:
        manifest = _load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, [f"manifest-invalid:{exc}"]
    missing = _missing_declared(manifest, DOMAIN_FIELDS[constraint])
    if missing:
        return False, ["missing-domain-artifact:" + ",".join(missing)]
    report_ok, report_observable = check_constraint(report, constraint)
    if constraint == "PATENT-DRAWING-VISUAL-BINDING":
        if visual_path is None or not visual_path.is_file():
            return False, ["missing-domain-artifact:visual-review"]
        measured_ok, measured = _measure_visual(manifest, visual_path, report)
        notes = ["visual-reread", *measured]
        if not report_ok:
            notes.extend(report_observable)
        return measured_ok and report_ok, notes
    if brief_path is None or not brief_path.is_file():
        return False, ["missing-domain-artifact:brief"]
    brief = _load_json(brief_path, "绘图简报")
    source_ok, source_notes = _bind_sources(brief, manifest, brief_path)
    if not source_ok:
        return False, source_notes
    figures, figure_notes = _align_figures(brief, manifest)
    if figures is None:
        return False, figure_notes
    matched, match_notes = _outputs_match(brief_path, figures, manifest, DOMAIN_FIELDS[constraint])
    if not matched:
        return False, match_notes
    if constraint in DRAWIO_CONSTRAINTS:
        measured_ok, measured = _measure_drawio(constraint, figures, manifest, brief)
        bound, bound_notes = _bind_report_digests(report, manifest, "drawio", "drawio")
        notes = ["domain-remeasured", *source_notes, *measured]
        if not bound:
            notes.extend(bound_notes)
        if not report_ok:
            notes.extend(report_observable)
        return measured_ok and report_ok and bound, notes
    if constraint == "PATENT-DRAWING-PNG-MARGIN":
        measured_ok, measured = _measure_png(brief, manifest, report)
        notes = ["png-remeasured", *source_notes, *measured]
        if not report_ok:
            notes.extend(report_observable)
        return measured_ok and report_ok, notes
    measured_ok, measured = _measure_export(manifest, report)
    notes = ["export-rebind", *source_notes, *measured]
    if not report_ok:
        notes.extend(report_observable)
    return measured_ok and report_ok, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="检查最终附图验证报告中的单项稳定性约束")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--visual-review", type=Path)
    parser.add_argument("--constraint", required=True, choices=sorted(SUPPORTED))
    parser.add_argument("--observable", required=True)
    parser.add_argument("--measurement", required=True)
    args = parser.parse_args()

    artifact_hash: dict[str, str] = {}
    if args.report.is_file():
        artifact_hash["verification-report"] = sha256(args.report)
    if args.brief is not None and args.brief.is_file():
        artifact_hash["brief"] = sha256(args.brief)
    if args.manifest is not None and args.manifest.is_file():
        artifact_hash["manifest"] = sha256(args.manifest)
        _hash_manifest_files(args.manifest, artifact_hash)
    if args.visual_review is not None and args.visual_review.is_file():
        artifact_hash["visual-review"] = sha256(args.visual_review)
    try:
        if not args.report.is_file():
            raise FileNotFoundError(f"验证报告不存在：{args.report}")
        report = load_report(args.report)
        domain = evaluate_domain(args.constraint, report, args.brief, args.manifest, args.visual_review)
        if domain is None:
            passed, observable = check_constraint(report, args.constraint)
        else:
            passed, observable = domain
    except Exception as exc:  # 输入损坏也必须形成可审计失败结果。
        passed, observable = False, [f"{type(exc).__name__}:{exc}"]

    measurements = {args.constraint: {args.measurement: passed}}
    payload: dict[str, Any] = {
        "artifact_sha256": artifact_hash,
        "measurements": measurements,
        "observables": {args.observable: observable},
    }
    if passed:
        payload["passed_constraint_ids"] = [args.constraint]
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    payload["failed_constraint_ids"] = [args.constraint]
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
