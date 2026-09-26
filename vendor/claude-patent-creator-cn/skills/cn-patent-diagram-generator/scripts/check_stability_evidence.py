#!/usr/bin/env python3
"""为 Skill Lint 复核最终验证报告中的单项专利附图约束。"""
from __future__ import annotations

import argparse
import hashlib
import json
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


def main() -> int:
    parser = argparse.ArgumentParser(description="检查最终附图验证报告中的单项稳定性约束")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--constraint", required=True, choices=sorted(SUPPORTED))
    parser.add_argument("--observable", required=True)
    parser.add_argument("--measurement", required=True)
    args = parser.parse_args()

    artifact_hash = {"verification-report": sha256(args.report)}
    try:
        report = load_report(args.report)
        passed, observable = check_constraint(report, args.constraint)
    except Exception as exc:  # 输入损坏也必须形成可审计失败结果。
        passed, observable = False, [f"{type(exc).__name__}:{exc}"]

    measurements = {args.constraint: {args.measurement: passed}}
    if passed:
        payload = {
            "passed_constraint_ids": [args.constraint],
            "artifact_sha256": artifact_hash,
            "measurements": measurements,
            "observables": {args.observable: observable},
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    payload = {
        "failed_constraint_ids": [args.constraint],
        "artifact_sha256": artifact_hash,
        "measurements": measurements,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
