#!/usr/bin/env python3
"""从用户修改范例提取安全布局，基于原始母版重建无拓扑副作用的 Draw.io。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ANALYZER_PATH = SCRIPT_DIR / "analyze_drawing_reference.py"
spec = importlib.util.spec_from_file_location("drawing_reference_analyzer_for_sanitizer", ANALYZER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(ANALYZER_PATH)
analyzer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = analyzer
spec.loader.exec_module(analyzer)

NODE_STYLE_KEYS = {
    "rounded", "arcSize", "whiteSpace", "html", "fontSize", "fontFamily",
    "fontColor", "fillColor", "strokeColor", "strokeWidth", "dashed", "align",
    "verticalAlign", "spacing", "spacingTop", "spacingBottom", "spacingLeft", "spacingRight",
}
EDGE_STYLE_KEYS = {
    "edgeStyle", "rounded", "orthogonalLoop", "jettySize", "html",
    "strokeWidth", "strokeColor", "fontSize", "fontFamily",
    "fontColor", "labelBackgroundColor", "labelBorderColor", "exitX", "exitY", "exitDx",
    "exitDy", "exitPerimeter", "entryX", "entryY", "entryDx", "entryDy", "entryPerimeter",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_style(value: str) -> dict[str, str | None]:
    """命名样式没有等号，不能在白名单合并时丢弃其形状语义。"""
    result: dict[str, str | None] = {}
    for part in (value or "").split(";"):
        if not part:
            continue
        key, separator, item = part.partition("=")
        result[key] = item if separator else None
    return result


def serialize_style(style: dict[str, str | None]) -> str:
    return ";".join(key if value is None else f"{key}={value}" for key, value in style.items()) + (";" if style else "")


def apply_style(base: ET.Element, reference_style: dict[str, str], allowed: set[str]) -> None:
    # 外框形状、命名样式及箭头所在端属于母版技术语义，绝不从范例复制。
    style = parse_style(base.get("style", ""))
    for key, value in reference_style.items():
        if key in allowed:
            style[key] = value
    base.set("style", serialize_style(style))


def cell_map(root: ET.Element) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    model = root.find("diagram/mxGraphModel") if root.tag == "mxfile" else root
    if model is None or model.find("root") is None:
        raise ValueError("缺少 mxGraphModel/root")
    root_node = model.find("root")
    if root_node is None:
        raise ValueError("缺少 mxGraphModel/root")
    for child in root_node:
        cell = child if child.tag == "mxCell" else child.find("mxCell")
        if cell is None:
            continue
        cid = (child.get("id") if child.tag != "mxCell" else None) or cell.get("id")
        if cid:
            result[cid] = cell
    return result


def copy_geometry(target: ET.Element, source: ET.Element, *, edge: bool) -> None:
    source_geometry = source.find("mxGeometry")
    if source_geometry is None:
        return
    copied = deepcopy(source_geometry)
    if edge:
        copied.set("relative", "1")
        copied.set("as", "geometry")
        for point in list(copied.findall("mxPoint")):
            if point.get("as") in {"sourcePoint", "targetPoint"}:
                copied.remove(point)
    old = target.find("mxGeometry")
    if old is not None:
        target.remove(old)
    target.append(copied)


def safe_edge_matches(
    baseline_cells: list[dict[str, Any]],
    reference_cells: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """按映射后的端点匹配参考边；标签脱离时仍允许复用其线路几何。"""
    reference_to_baseline = {item["reference"]["id"]: item["baseline"]["id"] for item in matches}
    baseline_edges = [item for item in baseline_cells if item["edge"]]
    reference_edges = [item for item in reference_cells if item["edge"]]
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in reference_edges:
        source = reference_to_baseline.get(item.get("source"))
        target = reference_to_baseline.get(item.get("target"))
        if source and target and source != target:
            candidates.setdefault((source, target), []).append(item)
    result: dict[str, dict[str, Any]] = {}
    for edge in baseline_edges:
        items = candidates.get((edge.get("source"), edge.get("target")), [])
        if len(items) == 1:
            result[edge["id"]] = items[0]
    return result


def sanitize(baseline: Path, reference: Path, output: Path, report_path: Path | None) -> dict[str, Any]:
    baseline_root = ET.parse(baseline).getroot()
    reference_root = ET.parse(reference).getroot()
    baseline_model, baseline_cells = analyzer.normalized_cells(baseline)
    reference_model, reference_cells = analyzer.normalized_cells(reference)
    matches, old_unmatched, new_unmatched = analyzer.match_nodes(baseline_cells, reference_cells)
    base_map = cell_map(baseline_root)
    reference_map = cell_map(reference_root)

    applied_nodes = []
    for match in matches:
        baseline_id = match["baseline"]["id"]
        reference_id = match["reference"]["id"]
        base_cell = base_map.get(baseline_id)
        reference_cell = reference_map.get(reference_id)
        if base_cell is None or reference_cell is None or base_cell.get("vertex") != "1":
            continue
        copy_geometry(base_cell, reference_cell, edge=False)
        apply_style(base_cell, match["reference"]["style"], NODE_STYLE_KEYS)
        applied_nodes.append({"baseline_id": baseline_id, "reference_id": reference_id, "label": match["reference"]["text"]})

    edge_matches = safe_edge_matches(baseline_cells, reference_cells, matches)
    copied_edge_geometry = []
    reset_edge_geometry = []
    baseline_edge_ids = {item["id"] for item in baseline_cells if item["edge"]}
    for baseline_edge in [item for item in baseline_cells if item["edge"]]:
        cell = base_map[baseline_edge["id"]]
        reference_edge = edge_matches.get(baseline_edge["id"])
        if reference_edge is not None:
            apply_style(cell, reference_edge["style"], EDGE_STYLE_KEYS)
        # 参考边只提供样式，不复制人工 waypoint、sourcePoint 或 targetPoint；
        # 所有线路从真实 source/target 重新交给 Draw.io 正交路由。
        old = cell.find("mxGeometry")
        if old is not None:
            cell.remove(old)
        cell.append(ET.Element("mxGeometry", {"relative": "1", "as": "geometry"}))
        reset_edge_geometry.append(baseline_edge["id"])
        # 技术关系始终以基准母版为准，禁止传播手工断连、自连接和旁置标签。
        original = next(item for item in baseline_cells if item["id"] == baseline_edge["id"])
        for key in ("source", "target"):
            value = original.get(key)
            if value:
                cell.set(key, value)
            else:
                cell.attrib.pop(key, None)
        cell.set("value", original.get("value", ""))

    # 只更新安全的页面视觉属性，不复制参考页中的额外节点或额外边。
    output_model = baseline_root.find("diagram/mxGraphModel") if baseline_root.tag == "mxfile" else baseline_root
    for key in ("pageWidth", "pageHeight", "gridSize", "grid", "page", "pageScale"):
        value = reference_model.get(key)
        if output_model is not None and value is not None:
            output_model.set(key, value)

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(baseline_root).write(output, encoding="utf-8", xml_declaration=False)
    report = {
        "schema_id": "cn-patent-drawing-reference-sanitization/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "STRUCTURE_SAFE_VISUAL_REVIEW_REQUIRED",
        "baseline": {"path": str(baseline.resolve()), "sha256": sha256(baseline)},
        "reference": {"path": str(reference.resolve()), "sha256": sha256(reference)},
        "output": {"path": str(output.resolve()), "sha256": sha256(output)},
        "strategy": "rebuild_from_baseline_apply_reference_geometry",
        "applied_node_count": len(applied_nodes),
        "applied_nodes": applied_nodes,
        "copied_edge_geometry_ids": sorted(copied_edge_geometry),
        "reset_edge_geometry_ids": sorted(reset_edge_geometry),
        "retained_baseline_relation_ids": sorted(baseline_edge_ids),
        "dropped_reference_only_node_ids": sorted(item["id"] for item in new_unmatched),
        "retained_unmatched_baseline_node_ids": sorted(item["id"] for item in old_unmatched),
        "visual_review_required": True,
        "postconditions": {
            "baseline_ids_preserved": True,
            "baseline_relation_endpoints_preserved": True,
            "baseline_relation_labels_preserved": True,
            "reference_only_nodes_not_copied": True,
            "reference_only_edges_not_copied": True,
            "absolute_endpoints_not_propagated": True,
            "self_loops_not_propagated": True,
        },
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = sanitize(args.baseline.resolve(), args.reference.resolve(), args.output.resolve(), args.report.resolve() if args.report else None)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"schema_id": "cn-patent-drawing-reference-sanitization/v1", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
