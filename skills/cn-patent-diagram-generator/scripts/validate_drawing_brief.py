#!/usr/bin/env python3
"""校验中国专利绘图合同及其来源证据绑定。"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_ID = "cn-patent-drawing-brief/v2"
SCHEMA_ID_V3 = "cn-patent-drawing-brief/v3"
SCHEMA_ID_V4 = "cn-patent-drawing-brief/v4"
SUPPORTED_SCHEMA_IDS = {SCHEMA_ID, SCHEMA_ID_V3, SCHEMA_ID_V4}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
COMPONENT_RE = re.compile(r"^[0-9]+$")
STEP_RE = re.compile(r"^S[0-9]+$")
STYLE_ANALYZER = Path(__file__).resolve().parent / "analyze_drawing_reference.py"


def load_style_analyzer():
    spec = importlib.util.spec_from_file_location("drawing_style_analyzer_for_brief", STYLE_ANALYZER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载样式合同验证器：{STYLE_ANALYZER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("绘图合同含 BOM，必须使用 UTF-8 无 BOM")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("绘图合同顶层必须是对象")
    return value


def resolve_under(case_dir: Path, raw: str, label: str) -> Path:
    candidate = Path(raw)
    candidate = candidate.resolve() if candidate.is_absolute() else (case_dir / candidate).resolve()
    try:
        candidate.relative_to(case_dir)
    except ValueError as exc:
        raise ValueError(f"{label}必须位于案件目录内：{raw}") from exc
    return candidate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[\s，,；;。:：]", "", text)


def validate_brief(brief_path: Path, case_dir: Path) -> dict[str, Any]:
    brief = load_json(brief_path)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def error(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    def warning(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    schema_id = brief.get("schema_id")
    if schema_id not in SUPPORTED_SCHEMA_IDS:
        error("BRIEF-SCHEMA", f"schema_id 必须为 {SCHEMA_ID}、{SCHEMA_ID_V3} 或 {SCHEMA_ID_V4}")
    elif schema_id == SCHEMA_ID:
        warning("BRIEF-LEGACY", "v2 未冻结阅读层级、复杂度预算、正文图示声明和独立线路通道；仅用于历史案件回放")
    elif schema_id == SCHEMA_ID_V3:
        warning("BRIEF-LEGACY", "v3 未绑定权利要求架构合同和方法步骤同构；新案件必须使用 v4")
    if brief.get("production_skill") != "drawio-skill":
        error("BRIEF-PRODUCER", "production_skill 必须为 drawio-skill")

    constraints = brief.get("global_constraints")
    expected_constraints = {
        "figure_number_on_canvas": False,
        "edge_labels_allowed": True,
        "annotation_nodes_may_be_edge_endpoints": False,
        "native_edge_labels_required": True,
        "separate_relation_label_nodes_allowed": False,
        "official_drawio_export_required": True,
        "visual_review_required": True,
    }
    if schema_id in {SCHEMA_ID_V3, SCHEMA_ID_V4}:
        expected_constraints.update({
            "single_primary_question_required": True,
            "independent_route_channels_required": True,
            "final_png_visual_review_required": True,
        })
    if schema_id == SCHEMA_ID_V4:
        expected_constraints.update({
            "method_step_isomorphism_required": True,
            "source_text_binding_required": True,
        })
    if not isinstance(constraints, dict):
        error("BRIEF-CONSTRAINTS", "缺少 global_constraints 对象")
        constraints = {}
    for key, expected in expected_constraints.items():
        if constraints.get(key) != expected:
            error("BRIEF-CONSTRAINTS", f"{key} 必须为 {expected!r}")
    color_policy = constraints.get("color_policy")
    if not isinstance(color_policy, dict):
        error("BRIEF-COLOR", "缺少 color_policy 对象")
        color_policy = {}
    mode = color_policy.get("mode")
    if mode not in {"monochrome", "restrained_color"}:
        error("BRIEF-COLOR", "color_policy.mode 必须为 monochrome 或 restrained_color")
    if color_policy.get("grayscale_safe") is not True or color_policy.get("color_semantics_redundant") is not True:
        error("BRIEF-COLOR", "颜色必须灰度安全，且不得作为唯一语义载体")
    max_fills = color_policy.get("max_nonwhite_fills")
    if not isinstance(max_fills, int) or isinstance(max_fills, bool) or not 0 <= max_fills <= 3:
        error("BRIEF-COLOR", "max_nonwhite_fills 必须为0—3的整数")
    for field in ("allowed_fill_colors", "allowed_stroke_colors"):
        values = color_policy.get(field)
        if not isinstance(values, list) or not values or any(not isinstance(item, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", item) for item in values):
            error("BRIEF-COLOR", f"{field} 必须是非空的 #RRGGBB 数组")
    dpi = constraints.get("minimum_png_dpi", 300)
    if not isinstance(dpi, (int, float)) or isinstance(dpi, bool) or dpi < 150:
        error("BRIEF-DPI", "minimum_png_dpi 必须不小于 150")

    png_margin_policy = constraints.get("png_margin_policy")
    if not isinstance(png_margin_policy, dict):
        error("BRIEF-PNG-MARGIN-POLICY", "缺少 png_margin_policy 对象")
        png_margin_policy = {}
    if png_margin_policy.get("crop_to_diagram_required") is not True:
        error("BRIEF-PNG-MARGIN-POLICY", "png_margin_policy.crop_to_diagram_required 必须为 true")
    margin_rules = {
        "target_border_pixels": (0, 30),
        "maximum_margin_pixels": (1, 60),
        "white_threshold": (220, 255),
    }
    for key, (minimum, maximum) in margin_rules.items():
        value = png_margin_policy.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            error("BRIEF-PNG-MARGIN-POLICY", f"png_margin_policy.{key} 必须为 {minimum}—{maximum} 的整数")
    if isinstance(png_margin_policy.get("target_border_pixels"), int) and isinstance(png_margin_policy.get("maximum_margin_pixels"), int):
        if png_margin_policy["target_border_pixels"] > png_margin_policy["maximum_margin_pixels"]:
            error("BRIEF-PNG-MARGIN-POLICY", "target_border_pixels 不得大于 maximum_margin_pixels")

    node_text_policy = constraints.get("node_text_policy")
    if not isinstance(node_text_policy, dict):
        error("BRIEF-NODE-TEXT-POLICY", "缺少 node_text_policy 对象")
        node_text_policy = {}
    expected_node_text_flags = {
        "wrap_required": True,
        "font_autoshrink_allowed": False,
    }
    for key, expected in expected_node_text_flags.items():
        if node_text_policy.get(key) != expected:
            error("BRIEF-NODE-TEXT-POLICY", f"node_text_policy.{key} 必须为 {expected!r}")
    numeric_rules = {
        "reference_page_width": (1, None),
        "reference_page_height": (1, None),
        "minimum_font_size": (12, None),
        "maximum_width_to_font_size_ratio": (8, 30),
        "maximum_frame_to_text_height_ratio": (1, 2),
        "maximum_chinese_characters_per_line": (1, 12),
        "horizontal_padding": (0, None),
        "vertical_padding": (0, None),
        "line_height_factor": (1, 1.2),
        "maximum_wrapped_lines": (1, 6),
    }
    for key, (minimum, maximum) in numeric_rules.items():
        value = node_text_policy.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            error("BRIEF-NODE-TEXT-POLICY", f"node_text_policy.{key} 必须是数字")
            continue
        if value < minimum or (maximum is not None and value > maximum):
            suffix = f"且不大于 {maximum}" if maximum is not None else ""
            error("BRIEF-NODE-TEXT-POLICY", f"node_text_policy.{key} 必须不小于 {minimum}{suffix}")
    for key in ("maximum_wrapped_lines", "maximum_chinese_characters_per_line"):
        if not isinstance(node_text_policy.get(key), int) or isinstance(node_text_policy.get(key), bool):
            error("BRIEF-NODE-TEXT-POLICY", f"node_text_policy.{key} 必须是整数")

    vertical_spacing_policy = constraints.get("vertical_spacing_policy")
    if not isinstance(vertical_spacing_policy, dict):
        error("BRIEF-VERTICAL-SPACING-POLICY", "缺少 vertical_spacing_policy 对象")
        vertical_spacing_policy = {}
    required_true_fields = (
        "subtract_native_edge_label_text_height",
        "subtract_arrowhead_height",
    )
    for key in required_true_fields:
        if vertical_spacing_policy.get(key) is not True:
            error(
                "BRIEF-VERTICAL-SPACING-POLICY",
                f"vertical_spacing_policy.{key} 必须为 True",
            )
    exact_numeric_fields = {
        "minimum_effective_blank_to_font_height_ratio": 2,
        "maximum_effective_blank_to_font_height_ratio": 3,
        "default_edge_label_font_size": 12,
        "default_arrowhead_height": 6,
    }
    for key, expected in exact_numeric_fields.items():
        if vertical_spacing_policy.get(key) != expected:
            error(
                "BRIEF-VERTICAL-SPACING-POLICY",
                f"vertical_spacing_policy.{key} 必须为 {expected}",
            )

    node_shape_policy = constraints.get("node_shape_policy")
    if not isinstance(node_shape_policy, dict):
        error("BRIEF-NODE-SHAPE-POLICY", "缺少 node_shape_policy 对象")
        node_shape_policy = {}
    if node_shape_policy.get("cylinder_requires_data_store_kind") is not True:
        error("BRIEF-NODE-SHAPE-POLICY", "node_shape_policy.cylinder_requires_data_store_kind 必须为 True")
    if node_shape_policy.get("cylinder_label_pattern") != "存储|记录|数据库|数据表|缓存|仓库":
        error("BRIEF-NODE-SHAPE-POLICY", "node_shape_policy.cylinder_label_pattern 必须为 '存储|记录|数据库|数据表|缓存|仓库'")

    relation_label_policy = constraints.get("relation_label_policy")
    if not isinstance(relation_label_policy, dict):
        error("BRIEF-RELATION-LABEL-POLICY", "缺少 relation_label_policy 对象")
        relation_label_policy = {}
    if relation_label_policy.get("centered_vertical_label_required") is not True:
        error("BRIEF-RELATION-LABEL-POLICY", "relation_label_policy.centered_vertical_label_required 必须为 True")
    relation_numeric_rules = {
        "minimum_font_to_node_font_ratio": (2 / 3, 1),
        "minimum_vertical_clearance_in_arrowhead_heights": (1, 3),
        "default_arrowhead_height": (6, 24),
        "vertical_label_center_tolerance": (0, 0.1),
    }
    for key, (minimum, maximum) in relation_numeric_rules.items():
        value = relation_label_policy.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            error("BRIEF-RELATION-LABEL-POLICY", f"relation_label_policy.{key} 必须是数字")
            continue
        if value < minimum or value > maximum:
            error(
                "BRIEF-RELATION-LABEL-POLICY",
                f"relation_label_policy.{key} 必须不小于 {minimum:g} 且不大于 {maximum:g}",
            )

    source_artifacts = brief.get("source_artifacts")
    if not isinstance(source_artifacts, list):
        error("BRIEF-SOURCES", "source_artifacts 必须是数组")
        source_artifacts = []
    source_ids: set[str] = set()
    source_texts: list[str] = []
    source_text_by_id: dict[str, str] = {}
    bound_sources: list[dict[str, Any]] = []
    for index, item in enumerate(source_artifacts, start=1):
        if not isinstance(item, dict):
            error("BRIEF-SOURCES", f"第 {index} 个来源不是对象")
            continue
        artifact_id, raw_path, digest = item.get("artifact_id"), item.get("path"), item.get("sha256")
        if not isinstance(artifact_id, str) or artifact_id in source_ids:
            error("BRIEF-SOURCES", f"第 {index} 个来源 artifact_id 缺失或重复")
            continue
        source_ids.add(artifact_id)
        if not isinstance(raw_path, str) or not raw_path:
            error("BRIEF-SOURCES", f"来源 {artifact_id} 缺少 path")
            continue
        try:
            path = resolve_under(case_dir, raw_path, f"来源 {artifact_id}")
        except ValueError as exc:
            error("BRIEF-SOURCES", str(exc))
            continue
        if not path.is_file():
            error("BRIEF-SOURCE-MISSING", f"来源不存在：{raw_path}")
            continue
        actual = sha256(path)
        if not isinstance(digest, str) or not SHA_RE.fullmatch(digest) or digest != actual:
            error("BRIEF-SOURCE-STALE", f"来源 {artifact_id} 的 SHA-256 与当前文件不一致")
        try:
            source_text = path.read_text(encoding="utf-8")
            source_texts.append(source_text)
            source_text_by_id[artifact_id] = source_text
        except UnicodeDecodeError:
            warning("BRIEF-SOURCE-BINARY", f"来源 {artifact_id} 不是 UTF-8 文本，未执行 anchor 文本核对")
        bound_sources.append({"artifact_id": artifact_id, "path": str(path), "sha256": actual})
    for required in ("claims", "specification", "feature_ledger"):
        if required not in source_ids:
            error("BRIEF-SOURCES", f"缺少必需来源：{required}")
    architecture_methods: dict[int, dict[str, Any]] = {}
    if schema_id == SCHEMA_ID_V4:
        if "claim_architecture" not in source_ids:
            error("BRIEF-SOURCES", "v4缺少必需来源：claim_architecture")
        else:
            try:
                architecture = json.loads(source_text_by_id.get("claim_architecture", ""))
                if not isinstance(architecture, dict) or architecture.get("schema_id") != "cn-patent-claim-architecture/v1":
                    error("BRIEF-ARCHITECTURE", "claim_architecture必须使用cn-patent-claim-architecture/v1")
                else:
                    for method in architecture.get("method_claims") or []:
                        if isinstance(method, dict) and isinstance(method.get("claim_number"), int):
                            architecture_methods[method["claim_number"]] = method
            except json.JSONDecodeError:
                error("BRIEF-ARCHITECTURE", "claim_architecture不是有效JSON")
    source_corpus = "\n".join(source_texts)

    output_root_raw = brief.get("output_root")
    output_root: Path | None = None
    if not isinstance(output_root_raw, str) or not output_root_raw:
        error("BRIEF-OUTPUT", "缺少 output_root")
    else:
        try:
            output_root = resolve_under(case_dir, output_root_raw, "output_root")
        except ValueError as exc:
            error("BRIEF-OUTPUT", str(exc))

    style_brief_report = None
    style_path_raw = brief.get("style_brief_path")
    style_sha = brief.get("style_brief_sha256")
    if style_path_raw is not None or style_sha is not None:
        if schema_id != SCHEMA_ID_V4:
            error("BRIEF-STYLE", "用户范例样式合同仅支持 drawing brief v4")
        if not isinstance(style_path_raw, str) or not style_path_raw:
            error("BRIEF-STYLE", "style_brief_path 必须是非空字符串")
        elif not isinstance(style_sha, str) or not SHA_RE.fullmatch(style_sha):
            error("BRIEF-STYLE", "style_brief_sha256 必须为64位SHA-256")
        else:
            try:
                style_path = resolve_under(case_dir, style_path_raw, "style_brief_path")
                if not style_path.is_file():
                    error("BRIEF-STYLE-MISSING", f"样式合同不存在：{style_path_raw}")
                elif sha256(style_path) != style_sha:
                    error("BRIEF-STYLE-STALE", "style brief SHA-256 与当前文件不一致")
                else:
                    style_brief_report = load_style_analyzer().validate_style_brief(style_path, case_dir, True)
                    for item in style_brief_report.get("errors", []):
                        error("BRIEF-STYLE-" + item.get("code", "INVALID"), item.get("message", "样式合同无效"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                error("BRIEF-STYLE", str(exc))

    figures = brief.get("figures")
    if not isinstance(figures, list) or not figures:
        error("BRIEF-FIGURES", "figures 必须是非空数组")
        figures = []
    numbers: list[int] = []
    stems: set[str] = set()
    figure_reports: list[dict[str, Any]] = []
    for index, figure in enumerate(figures, start=1):
        if not isinstance(figure, dict):
            error("BRIEF-FIGURE", f"第 {index} 幅图不是对象")
            continue
        number = figure.get("figure_number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            error("BRIEF-FIGURE", f"第 {index} 幅图的 figure_number 无效")
            continue
        numbers.append(number)
        stem = figure.get("file_stem")
        if not isinstance(stem, str) or not stem.strip() or stem in stems:
            error("BRIEF-FIGURE", f"图{number} file_stem 缺失或重复")
        else:
            stems.add(stem)
            if not stem.startswith(f"图{number}-"):
                warning("BRIEF-FILENAME", f"图{number} file_stem 建议以“图{number}-”开头")
        if figure.get("diagram_type") not in {
            "system_block", "method_flowchart", "interaction_sequence", "state_machine",
            "data_flow", "internal_structure", "cross_functional_flow",
            "network_topology", "data_structure"
        }:
            error("BRIEF-DIAGRAM-TYPE", f"图{number} diagram_type 不在专利适配图型中")
        expected_profile = "patent_monochrome" if mode == "monochrome" else "patent_restrained_color"
        if figure.get("style_profile") != expected_profile:
            error("BRIEF-COLOR", f"图{number} style_profile 必须为 {expected_profile}")

        layer_ids: set[str] = set()
        if schema_id in {SCHEMA_ID_V3, SCHEMA_ID_V4}:
            primary_question = figure.get("primary_question")
            if not isinstance(primary_question, str) or not primary_question.strip():
                error("BRIEF-PRIMARY-QUESTION", f"图{number} 缺少唯一 primary_question")
            elif any(separator in primary_question for separator in ("；", ";", "以及", "同时")):
                warning("BRIEF-PRIMARY-QUESTION", f"图{number} primary_question 可能包含多个并列任务，应复核是否拆图")
            if figure.get("reading_direction") not in {"left_to_right", "top_to_bottom"}:
                error("BRIEF-READING-DIRECTION", f"图{number} reading_direction 无效")
            layers = figure.get("layers")
            if not isinstance(layers, list) or not layers:
                error("BRIEF-LAYERS", f"图{number} layers 必须是非空数组")
                layers = []
            orders: set[int] = set()
            for layer in layers:
                if not isinstance(layer, dict):
                    error("BRIEF-LAYERS", f"图{number} 存在非对象层级")
                    continue
                layer_id, order = layer.get("id"), layer.get("order")
                if not isinstance(layer_id, str) or not ID_RE.fullmatch(layer_id) or layer_id in layer_ids:
                    error("BRIEF-LAYERS", f"图{number} 层级 ID 缺失、非法或重复：{layer_id}")
                else:
                    layer_ids.add(layer_id)
                if not isinstance(order, int) or isinstance(order, bool) or order < 1 or order in orders:
                    error("BRIEF-LAYERS", f"图{number} 层级 order 必须为不重复正整数：{order}")
                else:
                    orders.add(order)
            if orders and orders != set(range(1, len(orders) + 1)):
                error("BRIEF-LAYERS", f"图{number} 层级 order 必须从1连续编号")

        elements = figure.get("elements")
        if not isinstance(elements, list) or not elements:
            error("BRIEF-ELEMENTS", f"图{number} elements 必须是非空数组")
            elements = []
        element_ids: set[str] = set()
        element_by_id: dict[str, dict[str, Any]] = {}
        component_marks: set[str] = set()
        step_marks: set[str] = set()
        for item in elements:
            if not isinstance(item, dict):
                error("BRIEF-ELEMENTS", f"图{number} 存在非对象元素")
                continue
            eid, label, kind = item.get("id"), item.get("label"), item.get("kind")
            if not isinstance(eid, str) or not ID_RE.fullmatch(eid) or eid in element_ids:
                error("BRIEF-ELEMENTS", f"图{number} 元素 ID 缺失、非法或重复：{eid}")
                continue
            element_ids.add(eid)
            element_by_id[eid] = item
            if schema_id in {SCHEMA_ID_V3, SCHEMA_ID_V4} and item.get("layer_id") not in layer_ids:
                error("BRIEF-LAYERS", f"图{number} 元素 {eid} 引用了未知 layer_id：{item.get('layer_id')}")
            if not isinstance(label, str) or not label.strip():
                error("BRIEF-ELEMENTS", f"图{number} 元素 {eid} 缺少 label")
            anchor = item.get("source_anchor")
            if not isinstance(anchor, str) or not anchor.strip():
                error("BRIEF-EVIDENCE", f"图{number} 元素 {eid} 缺少 source_anchor")
            elif source_corpus and anchor not in source_corpus:
                error("BRIEF-EVIDENCE", f"图{number} 元素 {eid} 的 source_anchor 在冻结来源中找不到：{anchor}")
            mark = item.get("reference_sign")
            if kind == "component":
                if not isinstance(mark, str) or not COMPONENT_RE.fullmatch(mark) or mark in component_marks:
                    error("BRIEF-MARK", f"图{number} 部件 {eid} 的数字标记无效或重复：{mark}")
                else:
                    component_marks.add(mark)
            elif kind == "step":
                if not isinstance(mark, str) or not STEP_RE.fullmatch(mark) or mark in step_marks:
                    error("BRIEF-MARK", f"图{number} 步骤 {eid} 的 Sxxx 标记无效或重复：{mark}")
                else:
                    step_marks.add(mark)
        if component_marks & step_marks:
            error("BRIEF-MARK", f"图{number} 部件标记与步骤号发生冲突")

        relation_ids: set[str] = set()
        relation_by_id: dict[str, dict[str, Any]] = {}
        route_channels: set[str] = set()
        relations = figure.get("relations") or []
        for relation in relations:
            if not isinstance(relation, dict):
                error("BRIEF-RELATION", f"图{number} 存在非对象关系")
                continue
            rid = relation.get("id")
            if not isinstance(rid, str) or not ID_RE.fullmatch(rid) or rid in relation_ids:
                error("BRIEF-RELATION", f"图{number} 关系 ID 缺失、非法或重复：{rid}")
                continue
            relation_ids.add(rid)
            relation_by_id[rid] = relation
            if schema_id in {SCHEMA_ID_V3, SCHEMA_ID_V4}:
                channel = relation.get("route_channel")
                if not isinstance(channel, str) or not ID_RE.fullmatch(channel) or channel in route_channels:
                    error("BRIEF-ROUTE-CHANNEL", f"图{number} 关系 {rid} 缺少独立 route_channel 或通道重复：{channel}")
                else:
                    route_channels.add(channel)
                feature_ids = relation.get("source_feature_ids")
                if not isinstance(feature_ids, list) or not feature_ids or any(not isinstance(fid, str) or not re.fullmatch(r"F\d{3}", fid) for fid in feature_ids):
                    error("BRIEF-EVIDENCE", f"图{number} 关系 {rid} 必须登记 source_feature_ids")
            source, target = relation.get("source"), relation.get("target")
            if source not in element_ids or target not in element_ids:
                error("BRIEF-RELATION", f"图{number} 关系 {rid} 引用了未知元素：{source}→{target}")
            if source == target:
                error("BRIEF-RELATION", f"图{number} 关系 {rid} 不得自环")
            if relation.get("preferred_direction") not in {"vertical", "horizontal", "auto"}:
                error("BRIEF-RELATION", f"图{number} 关系 {rid} preferred_direction 无效")
            if relation.get("direct_connection_required") is not True:
                error("BRIEF-RELATION", f"图{number} 关系 {rid} 的 direct_connection_required 必须为 true")
            anchor = relation.get("source_anchor")
            if not isinstance(anchor, str) or not anchor.strip():
                error("BRIEF-EVIDENCE", f"图{number} 关系 {rid} 缺少 source_anchor")
            elif source_corpus and anchor not in source_corpus:
                error("BRIEF-EVIDENCE", f"图{number} 关系 {rid} 的 source_anchor 在冻结来源中找不到：{anchor}")

        if schema_id in {SCHEMA_ID_V3, SCHEMA_ID_V4}:
            budget = figure.get("complexity_budget")
            if not isinstance(budget, dict):
                error("BRIEF-COMPLEXITY", f"图{number} 缺少 complexity_budget")
                budget = {}
            decisions = sum(1 for item in elements if isinstance(item, dict) and item.get("kind") == "decision")
            for field, actual in (
                ("max_technical_elements", len(elements)),
                ("max_relations", len(relations)),
                ("max_decisions", decisions),
            ):
                limit = budget.get(field)
                if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                    error("BRIEF-COMPLEXITY", f"图{number} {field} 必须是非负整数")
                elif actual > limit:
                    error("BRIEF-COMPLEXITY", f"图{number} {field} 预算 {limit}，实际 {actual}；应拆图而非继续堆叠")

            normal_exits = figure.get("normal_exit_ids")
            exception_exits = figure.get("exception_exit_ids")
            if not isinstance(normal_exits, list) or not normal_exits:
                error("BRIEF-EXIT", f"图{number} 必须登记至少一个正常出口")
                normal_exits = []
            if not isinstance(exception_exits, list):
                error("BRIEF-EXIT", f"图{number} exception_exit_ids 必须是数组")
                exception_exits = []
            for exit_id in normal_exits + exception_exits:
                if exit_id not in element_ids:
                    error("BRIEF-EXIT", f"图{number} 出口 {exit_id} 不是已登记元素")
            if set(normal_exits) & set(exception_exits):
                error("BRIEF-EXIT", f"图{number} 正常出口与异常出口不得重叠")

            assertions = figure.get("spec_assertions")
            if not isinstance(assertions, list) or not assertions:
                error("BRIEF-SPEC-ASSERTION", f"图{number} 缺少 spec_assertions")
                assertions = []
            covered_elements: set[str] = set()
            covered_relations: set[str] = set()
            specification_text = source_text_by_id.get("specification", "")
            for assertion_index, assertion in enumerate(assertions, start=1):
                if not isinstance(assertion, dict):
                    error("BRIEF-SPEC-ASSERTION", f"图{number} 第 {assertion_index} 条正文声明不是对象")
                    continue
                anchor = assertion.get("anchor")
                if not isinstance(anchor, str) or not anchor.strip() or anchor not in specification_text:
                    error("BRIEF-SPEC-ASSERTION", f"图{number} 第 {assertion_index} 条正文声明锚点无法在说明书中定位：{anchor}")
                assertion_elements = assertion.get("element_ids")
                assertion_relations = assertion.get("relation_ids")
                if not isinstance(assertion_elements, list) or not isinstance(assertion_relations, list):
                    error("BRIEF-SPEC-ASSERTION", f"图{number} 第 {assertion_index} 条正文声明必须提供 element_ids 和 relation_ids 数组")
                    continue
                unknown_elements = set(assertion_elements) - element_ids
                unknown_relations = set(assertion_relations) - relation_ids
                if unknown_elements:
                    error("BRIEF-SPEC-ASSERTION", f"图{number} 正文声明引用未知元素：{sorted(unknown_elements)}")
                if unknown_relations:
                    error("BRIEF-SPEC-ASSERTION", f"图{number} 正文声明引用未知关系：{sorted(unknown_relations)}")
                covered_elements.update(assertion_elements)
                covered_relations.update(assertion_relations)
            technical_elements = {
                item["id"] for item in elements
                if isinstance(item, dict) and item.get("kind") not in {"annotation", "start_end"} and isinstance(item.get("id"), str)
            }
            if technical_elements - covered_elements:
                error("BRIEF-SPEC-ASSERTION", f"图{number} 有技术元素未被说明书图示声明覆盖：{sorted(technical_elements - covered_elements)}")
            if relation_ids - covered_relations:
                error("BRIEF-SPEC-ASSERTION", f"图{number} 有技术关系未被说明书图示声明覆盖：{sorted(relation_ids - covered_relations)}")

        if schema_id == SCHEMA_ID_V4 and figure.get("diagram_type") == "method_flowchart":
            claim_number = figure.get("method_claim_number")
            architecture_method = architecture_methods.get(claim_number) if isinstance(claim_number, int) else None
            if architecture_method is None:
                error("BRIEF-STEP-CLAIM", f"图{number} method_claim_number未指向架构合同中的方法权利要求")
                architecture_method = {"steps": [], "decisions": [], "loops": []}
            architecture_steps = architecture_method.get("steps") or []
            architecture_step_by_id = {item.get("step_id"): item for item in architecture_steps if isinstance(item, dict)}
            expected_step_ids = [item.get("step_id") for item in architecture_steps if isinstance(item, dict)]
            bindings = figure.get("step_bindings")
            if not isinstance(bindings, list) or not bindings:
                error("BRIEF-STEP-BINDING", f"图{number} 缺少step_bindings")
                bindings = []
            bound_step_ids: list[str] = []
            step_to_element: dict[str, str] = {}
            for binding_index, binding in enumerate(bindings, start=1):
                if not isinstance(binding, dict):
                    error("BRIEF-STEP-BINDING", f"图{number} 第{binding_index}个步骤绑定不是对象")
                    continue
                step_id = binding.get("step_id")
                element_id = binding.get("element_id")
                if not isinstance(step_id, str) or not STEP_RE.fullmatch(step_id) or step_id in bound_step_ids:
                    error("BRIEF-STEP-BINDING", f"图{number} step_id缺失、非法或重复：{step_id}")
                    continue
                bound_step_ids.append(step_id)
                if not isinstance(element_id, str) or element_id not in element_by_id:
                    error("BRIEF-STEP-BINDING", f"图{number} {step_id}引用未知元素：{element_id}")
                    continue
                step_to_element[step_id] = element_id
                element = element_by_id[element_id]
                if element.get("kind") != "step" or element.get("reference_sign") != step_id:
                    error("BRIEF-STEP-BINDING", f"图{number} {step_id}必须绑定kind=step且reference_sign相同的元素")
                source = architecture_step_by_id.get(step_id)
                if source is None:
                    error("BRIEF-STEP-ISOMORPHISM", f"图{number} {step_id}不在权利要求架构合同中")
                    continue
                claim_action = binding.get("claim_action")
                spec_anchor = binding.get("specification_anchor")
                if claim_action != source.get("action"):
                    error("BRIEF-STEP-TEXT", f"图{number} {step_id}的claim_action未逐字绑定架构合同")
                if spec_anchor != source.get("specification_anchor"):
                    error("BRIEF-STEP-TEXT", f"图{number} {step_id}的说明书锚点未逐字绑定架构合同")
                if compact_text(element.get("label", "")) != compact_text(step_id + str(claim_action or "")):
                    error("BRIEF-STEP-TEXT", f"图{number} {step_id}图框文字必须等于步骤号加权利要求动作，不得自行概括")
            if bound_step_ids != expected_step_ids:
                error("BRIEF-STEP-ISOMORPHISM", f"图{number} 步骤{bound_step_ids}与架构合同{expected_step_ids}不一致")
            if step_marks != set(expected_step_ids):
                error("BRIEF-STEP-ISOMORPHISM", f"图{number} 图面步骤标记{sorted(step_marks)}与架构合同{expected_step_ids}不一致")

            architecture_decisions = {item.get("decision_id"): item for item in architecture_method.get("decisions") or [] if isinstance(item, dict)}
            decision_bindings = figure.get("decision_bindings")
            if not isinstance(decision_bindings, list):
                error("BRIEF-DECISION-BINDING", f"图{number} decision_bindings必须是数组")
                decision_bindings = []
            bound_decisions: dict[str, str] = {}
            for binding in decision_bindings:
                if not isinstance(binding, dict):
                    error("BRIEF-DECISION-BINDING", f"图{number} decision_binding必须是对象")
                    continue
                decision_id = binding.get("decision_id")
                element_id = binding.get("element_id")
                if decision_id not in architecture_decisions or decision_id in bound_decisions:
                    error("BRIEF-DECISION-BINDING", f"图{number} decision_id未知或重复：{decision_id}")
                    continue
                if element_id not in element_by_id or element_by_id[element_id].get("kind") != "decision":
                    error("BRIEF-DECISION-BINDING", f"图{number} 判断{decision_id}必须绑定kind=decision的元素")
                    continue
                bound_decisions[str(decision_id)] = str(element_id)
                source = architecture_decisions[decision_id]
                if binding.get("condition") != source.get("condition") or compact_text(element_by_id[element_id].get("label", "")) != compact_text(str(source.get("condition", ""))):
                    error("BRIEF-DECISION-TEXT", f"图{number} 判断{decision_id}文字未逐字绑定架构合同")
                branch_relation_ids: set[str] = set()
                for role, allowed_labels in (("true", {"是", "真", "true", "yes"}), ("false", {"否", "假", "false", "no"})):
                    branch = binding.get(f"{role}_branch")
                    if not isinstance(branch, dict):
                        error("BRIEF-DECISION-BRANCH", f"图{number} 判断{decision_id}缺少{role}_branch的关系ID、目标步骤和原生关系标签绑定")
                        continue
                    rid = branch.get("relation_id")
                    if not isinstance(rid, str) or rid not in relation_by_id or rid in branch_relation_ids:
                        error("BRIEF-DECISION-BRANCH", f"图{number} 判断{decision_id}的{role}关系ID未知或重复：{rid}")
                        continue
                    branch_relation_ids.add(rid)
                    relation = relation_by_id[rid]
                    target_step = source.get(f"{role}_target_step_id")
                    expected_target = step_to_element.get(target_step)
                    if (branch.get("target_step_id") != target_step or expected_target is None
                            or relation.get("source") != element_id or relation.get("target") != expected_target):
                        error("BRIEF-DECISION-ROUTING", f"图{number} 判断{decision_id}的{role}关系{rid}未绑定架构合同规定的目标步骤{target_step}")
                    label = branch.get("label")
                    relation_label = relation.get("label")
                    if (not isinstance(label, str) or label not in allowed_labels
                            or not isinstance(relation_label, str) or re.sub(r"\s+", "", relation_label) != label):
                        error("BRIEF-DECISION-LABEL", f"图{number} 判断{decision_id}的{role}关系{rid}原生关系标签与真假角色不一致")
                outgoing_ids = {rid for rid, relation in relation_by_id.items() if relation.get("source") == element_id}
                if len(branch_relation_ids) != 2 or outgoing_ids != branch_relation_ids:
                    error("BRIEF-DECISION-BRANCH", f"图{number} 判断{decision_id}必须恰好绑定真、假两条出关系边，不得缺支或额外出支")
            if set(bound_decisions) != set(architecture_decisions):
                error("BRIEF-DECISION-ISOMORPHISM", f"图{number} 判断集合与架构合同不一致")
            diagram_decision_ids = {eid for eid, item in element_by_id.items() if item.get("kind") == "decision"}
            if set(bound_decisions.values()) != diagram_decision_ids:
                error("BRIEF-DECISION-ISOMORPHISM", f"图{number} 图面判断节点与decision_bindings不一致")

            architecture_loops = {(item.get("from_step_id"), item.get("to_step_id"), item.get("condition")) for item in architecture_method.get("loops") or [] if isinstance(item, dict)}
            loop_bindings = figure.get("loop_bindings")
            if not isinstance(loop_bindings, list):
                error("BRIEF-LOOP-BINDING", f"图{number} loop_bindings必须是数组")
                loop_bindings = []
            bound_loops: set[tuple[Any, Any, Any]] = set()
            for binding in loop_bindings:
                if not isinstance(binding, dict):
                    error("BRIEF-LOOP-BINDING", f"图{number} loop_binding必须是对象")
                    continue
                signature = (binding.get("from_step_id"), binding.get("to_step_id"), binding.get("condition"))
                bound_loops.add(signature)
                if signature not in architecture_loops:
                    error("BRIEF-LOOP-ISOMORPHISM", f"图{number} 循环{signature}不在架构合同中")
                relation = relation_by_id.get(binding.get("relation_id"))
                if relation is None:
                    error("BRIEF-LOOP-BINDING", f"图{number} 循环引用未知关系：{binding.get('relation_id')}")
                    continue
                expected_target = step_to_element.get(binding.get("to_step_id"))
                possible_sources = {step_to_element.get(binding.get("from_step_id"))}
                possible_sources.update(
                    bound_decisions.get(did) for did, decision in architecture_decisions.items()
                    if decision.get("after_step_id") == binding.get("from_step_id")
                )
                possible_sources.discard(None)
                if relation.get("target") != expected_target or relation.get("source") not in possible_sources:
                    error("BRIEF-LOOP-ROUTING", f"图{number} 循环关系未指向架构合同规定的返回步骤")
            if bound_loops != architecture_loops:
                error("BRIEF-LOOP-ISOMORPHISM", f"图{number} 循环集合与架构合同不一致")

        outputs = figure.get("outputs")
        resolved_outputs: dict[str, str] = {}
        if not isinstance(outputs, dict):
            error("BRIEF-OUTPUT", f"图{number} 缺少 outputs")
            outputs = {}
        if "svg" in outputs:
            error("BRIEF-OUTPUT-OBSOLETE", f"图{number} 不再生成或登记 SVG 输出")
        for key in ("drawio", "preview_png", "final_png", "export_report"):
            raw = outputs.get(key)
            if not isinstance(raw, str) or not raw:
                error("BRIEF-OUTPUT", f"图{number} 缺少 outputs.{key}")
                continue
            try:
                path = resolve_under(case_dir, raw, f"图{number} outputs.{key}")
                resolved_outputs[key] = str(path)
                if key in {"drawio", "final_png"} and output_root is not None:
                    try:
                        path.relative_to(output_root)
                    except ValueError:
                        error("BRIEF-OUTPUT", f"图{number} {key} 必须位于 output_root 内")
            except ValueError as exc:
                error("BRIEF-OUTPUT", str(exc))
        figure_reports.append({
            "figure_number": number,
            "elements": len(elements),
            "relations": len(figure.get("relations") or []),
            "component_marks": sorted(component_marks),
            "step_marks": sorted(step_marks),
            "method_claim_number": figure.get("method_claim_number") if schema_id == SCHEMA_ID_V4 and figure.get("diagram_type") == "method_flowchart" else None,
            "bound_step_ids": [item.get("step_id") for item in figure.get("step_bindings") or [] if isinstance(item, dict)] if schema_id == SCHEMA_ID_V4 else [],
            "outputs": resolved_outputs,
        })
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        error("BRIEF-NUMBERING", f"图号必须从1连续排列，实际为 {numbers}")

    return {
        "schema_id": "cn-patent-drawing-brief-validation/v3" if schema_id == SCHEMA_ID_V4 else "cn-patent-drawing-brief-validation/v2",
        "brief": str(brief_path.resolve()),
        "brief_sha256": sha256(brief_path),
        "case_dir": str(case_dir),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "evidence_scope": {
            "proves": ["绘图合同字段、来源哈希、元素关系引用和输出路径可复算", "v3/v4的阅读层级、复杂度预算、出口和正文图示声明满足结构合同", "节点文字适配策略字段有效", "v4方法流程图与权利要求架构合同的步骤、判断和循环同构"],
            "does_not_prove": ["最终 PNG 不存在视觉缺陷", "图示技术关系具有法律支持或创造性"],
        },
        "sources": bound_sources,
        "style_brief_validation": style_brief_report,
        "figures": figure_reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验中国专利附图交接合同")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_brief(args.brief.resolve(), args.case_dir.resolve())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = {"schema_id": "cn-patent-drawing-brief-validation/v2", "status": "FAIL", "errors": [{"code": "BRIEF-INPUT", "message": str(exc)}], "warnings": []}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
