#!/usr/bin/env python3
"""独立验证中国专利 Draw.io 附图、官方导出和视觉复核证据。"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import re
import subprocess
import sys
import unicodedata
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BRIEF_VALIDATOR = SCRIPT_DIR / "validate_drawing_brief.py"

DEFAULT_NODE_TEXT_POLICY = {
    "reference_page_width": 827.0,
    "reference_page_height": 1169.0,
    "minimum_font_size": 14.0,
    "maximum_width_to_font_size_ratio": 18.0,
    "maximum_frame_to_text_height_ratio": 2.0,
    "maximum_chinese_characters_per_line": 12,
    "horizontal_padding": 8.0,
    "vertical_padding": 4.0,
    "line_height_factor": 1.2,
    "maximum_wrapped_lines": 4,
    "wrap_required": True,
    "font_autoshrink_allowed": False,
}

DEFAULT_VERTICAL_SPACING_POLICY = {
    "minimum_effective_blank_to_font_height_ratio": 2.0,
    "maximum_effective_blank_to_font_height_ratio": 3.0,
    "subtract_native_edge_label_text_height": True,
    "subtract_arrowhead_height": True,
    "default_edge_label_font_size": 12.0,
    "default_arrowhead_height": 6.0,
}

DEFAULT_NODE_SHAPE_POLICY = {
    "cylinder_requires_data_store_kind": True,
    "cylinder_label_pattern": "存储|记录|数据库|数据表|缓存|仓库",
}

DEFAULT_RELATION_LABEL_POLICY = {
    "minimum_font_to_node_font_ratio": 2.0 / 3.0,
    "minimum_vertical_clearance_in_arrowhead_heights": 1.0,
    "default_arrowhead_height": 6.0,
    "centered_vertical_label_required": True,
    "vertical_label_center_tolerance": 0.1,
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


brief_validator = load_module(BRIEF_VALIDATOR, "patent_drawing_brief_validator")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label}含 BOM")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label}顶层必须是对象")
    return value


def resolve_under(case_dir: Path, raw: str, label: str) -> Path:
    candidate = Path(raw)
    candidate = candidate.resolve() if candidate.is_absolute() else (case_dir / candidate).resolve()
    try:
        candidate.relative_to(case_dir)
    except ValueError as exc:
        raise ValueError(f"{label}必须位于案件目录内：{raw}") from exc
    return candidate


def parse_style(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in (value or "").split(";"):
        if "=" in part:
            key, item = part.split("=", 1)
            result[key] = item
    return result


def visible_text_lines(value: str) -> list[str]:
    """按 Draw.io 可见换行切分文本，保留显式换行所表达的版式。"""
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:div|p|li)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return lines or [""]


def plain_text(value: str) -> str:
    return "\n".join(visible_text_lines(value)).strip()


def chinese_character_count(text: str) -> int:
    """统计汉字，不把数字、拉丁字母或中文标点计入12字上限。"""
    ranges = (
        (0x3400, 0x4DBF),
        (0x4E00, 0x9FFF),
        (0xF900, 0xFAFF),
        (0x20000, 0x2EBEF),
    )
    return sum(any(start <= ord(char) <= end for start, end in ranges) for char in text)


def compact_label(value: str) -> str:
    return re.sub(r"\s+", "", plain_text(value))


def frozen_node_labels(element: dict[str, Any]) -> set[str]:
    """仅允许完整合同文字及单独登记的部件标记，不开放任意前后缀。"""
    label = compact_label(element["label"])
    mark = compact_label(element.get("reference_sign", ""))
    if not mark or has_reference_sign(plain_text(element["label"]), mark):
        return {label}
    # 兼容标记前置、后置及中英文括号；已在label中冻结的标记不得重复追加。
    marks = (mark, f"({mark})", f"（{mark}）")
    return {text for token in marks for text in (token + label, label + token)}


def has_reference_sign(text: str, mark: str) -> bool:
    """不将S100中的S10、100中的10误认作独立部件标记。"""
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(mark) + r"(?![A-Za-z0-9])", text))


def rect(cell: ET.Element) -> tuple[float, float, float, float] | None:
    geometry = cell.find("mxGeometry")
    if geometry is None:
        return None
    try:
        return (
            float(geometry.get("x", "0")), float(geometry.get("y", "0")),
            float(geometry.get("width", "0")), float(geometry.get("height", "0")),
        )
    except ValueError:
        return None


def explicit_points(edge: ET.Element) -> list[tuple[float, float]]:
    geometry = edge.find("mxGeometry")
    if geometry is None:
        return []
    array = geometry.find("Array[@as='points']")
    if array is None:
        return []
    result = []
    for point in array.findall("mxPoint"):
        try:
            result.append((float(point.get("x", "0")), float(point.get("y", "0"))))
        except ValueError:
            pass
    return result


def style_number(style: dict[str, str], key: str) -> float | None:
    value = style.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def display_units(text: str) -> float:
    """按中英文显示宽度估算一行文本所需空间。"""
    units = 0.0
    for char in text:
        if char == "\n":
            continue
        units += 1.0 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 0.55
    return units


def estimated_line_count(text: str, width: float, font_size: float, padding: float) -> int:
    available = max(font_size, width - 2 * padding)
    capacity = max(1.0, available / font_size)
    lines = 0
    for raw_line in text.splitlines() or [""]:
        lines += max(1, math.ceil(display_units(raw_line) / capacity))
    return lines


def reference_scale(model: ET.Element, figure: dict[str, Any], policy: dict[str, Any]) -> float:
    """返回当前画布到统一 A4 基准坐标的缩放系数。"""
    page_width = float(model.get("pageWidth", "0"))
    page_height = float(model.get("pageHeight", "0"))
    if page_width <= 0 or page_height <= 0:
        raise ValueError("Draw.io 画布宽高必须大于0")
    ref_width = float(policy["reference_page_width"])
    ref_height = float(policy["reference_page_height"])
    if figure.get("orientation") == "landscape":
        ref_width, ref_height = ref_height, ref_width
    return min(ref_width / page_width, ref_height / page_height)


def verify_node_text_layout(
    model: ET.Element,
    vertices: dict[str, ET.Element],
    figure: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, str]]:
    """在统一 A4 基准坐标中检查技术节点的框字比例、显式换行和文字容量。"""
    errors: list[dict[str, str]] = []
    try:
        scale = reference_scale(model, figure, policy)
    except (KeyError, TypeError, ValueError):
        return [{"code": "DRAWING-NODE-TEXT-POLICY", "message": "无法读取画布或节点文字策略尺寸"}]
    minimum_font = float(policy["minimum_font_size"])
    max_width_ratio = float(policy["maximum_width_to_font_size_ratio"])
    max_frame_text_ratio = float(policy["maximum_frame_to_text_height_ratio"])
    max_chinese_per_line = int(policy["maximum_chinese_characters_per_line"])
    padding_x = float(policy["horizontal_padding"])
    padding_y = float(policy["vertical_padding"])
    line_height_factor = float(policy["line_height_factor"])
    max_lines = int(policy["maximum_wrapped_lines"])

    for item in figure["elements"]:
        if item.get("kind") == "annotation":
            continue
        cell = vertices.get(item["id"])
        box = rect(cell) if cell is not None else None
        if cell is None or box is None:
            continue
        style = parse_style(cell.get("style", ""))
        font_size = style_number(style, "fontSize")
        if font_size is None or font_size <= 0:
            errors.append({"code": "DRAWING-FONT-SIZE", "message": f"节点 {item['id']} 必须显式设置有效 fontSize"})
            continue
        width = box[2] * scale
        height = box[3] * scale
        normalized_font = font_size * scale
        if normalized_font + 0.01 < minimum_font:
            errors.append({
                "code": "DRAWING-FONT-SIZE",
                "message": f"节点 {item['id']} 归一化字号 {normalized_font:.2f} 小于 {minimum_font:g}",
            })
        if policy.get("wrap_required") is True and style.get("whiteSpace") != "wrap":
            errors.append({"code": "DRAWING-TEXT-WRAP", "message": f"节点 {item['id']} 必须启用 whiteSpace=wrap"})
        if normalized_font > 0 and width / normalized_font > max_width_ratio:
            errors.append({
                "code": "DRAWING-NODE-PROPORTION",
                "message": f"节点 {item['id']} 框字比例失衡：宽/字号={width / normalized_font:.2f}",
            })

        value = cell.get("value", "")
        explicit_lines = visible_text_lines(value)
        overlong_lines = [
            (index, chinese_character_count(line))
            for index, line in enumerate(explicit_lines, start=1)
            if chinese_character_count(line) > max_chinese_per_line
        ]
        if overlong_lines:
            details = "、".join(f"第{index}行{count}个" for index, count in overlong_lines)
            errors.append({
                "code": "DRAWING-CHINESE-WRAP",
                "message": (
                    f"节点 {item['id']} 存在超过 {max_chinese_per_line} 个汉字的可见行（{details}），"
                    "必须使用 <br> 或换行符显式换行"
                ),
            })

        text = "\n".join(explicit_lines).strip()
        lines = estimated_line_count(text, width, max(normalized_font, 0.1), padding_x)
        text_height = max(normalized_font * line_height_factor, lines * normalized_font * line_height_factor)
        if height > text_height * max_frame_text_ratio + 0.01:
            errors.append({
                "code": "DRAWING-NODE-HEIGHT",
                "message": (
                    f"节点 {item['id']} 外框高度 {height:.1f}px 超过文字块高度 {text_height:.1f}px 的 "
                    f"{max_frame_text_ratio:g} 倍"
                ),
            })
        required_height = text_height + 2 * padding_y
        if lines > max_lines or required_height > height + 1:
            errors.append({
                "code": "DRAWING-TEXT-OVERFLOW",
                "message": (
                    f"节点 {item['id']} 预计需要 {lines} 行、{required_height:.1f}px 高，"
                    f"当前归一化高度仅 {height:.1f}px"
                ),
            })
    return errors


def verify_vertical_spacing(
    model: ET.Element,
    vertices: dict[str, ET.Element],
    edges: dict[str, ET.Element],
    figure: dict[str, Any],
    node_text_policy: dict[str, Any],
    spacing_policy: dict[str, Any],
) -> list[dict[str, str]]:
    """检查纵向直连节点扣除关系标签和箭头头部后的有效空白是否为2—3倍字体行高。"""
    errors: list[dict[str, str]] = []
    try:
        scale = reference_scale(model, figure, node_text_policy)
        min_ratio = float(spacing_policy["minimum_effective_blank_to_font_height_ratio"])
        max_ratio = float(spacing_policy["maximum_effective_blank_to_font_height_ratio"])
        subtract_label = spacing_policy["subtract_native_edge_label_text_height"] is True
        subtract_arrowhead = spacing_policy["subtract_arrowhead_height"] is True
        default_edge_font = float(spacing_policy["default_edge_label_font_size"])
        default_arrow_height = float(spacing_policy["default_arrowhead_height"])
        line_height_factor = float(node_text_policy["line_height_factor"])
    except (KeyError, TypeError, ValueError):
        return [{"code": "DRAWING-VERTICAL-SPACING-POLICY", "message": "无法读取纵向节点间距策略"}]

    for relation in figure["relations"]:
        if relation.get("preferred_direction") != "vertical" or relation.get("direct_connection_required") is not True:
            continue
        edge = edges.get(relation["id"])
        source = vertices.get(relation["source"])
        target = vertices.get(relation["target"])
        source_box = rect(source if source is not None else ET.Element("x"))
        target_box = rect(target if target is not None else ET.Element("x"))
        if edge is None or source is None or target is None or source_box is None or target_box is None:
            continue
        _, sy, _, sh = source_box
        _, ty, _, th = target_box
        if sy + sh <= ty:
            raw_gap = ty - (sy + sh)
        elif ty + th <= sy:
            raw_gap = sy - (ty + th)
        else:
            continue

        edge_style = parse_style(edge.get("style", ""))
        label_height = 0.0
        edge_value = edge.get("value", "")
        if subtract_label and plain_text(edge_value):
            edge_font = style_number(edge_style, "fontSize") or default_edge_font
            label_lines = max(1, sum(1 for line in visible_text_lines(edge_value) if line))
            label_height = label_lines * edge_font * line_height_factor

        arrowhead_height = 0.0
        if subtract_arrowhead:
            arrowhead_height = style_number(edge_style, "endSize") or default_arrow_height

        source_font = style_number(parse_style(source.get("style", "")), "fontSize")
        target_font = style_number(parse_style(target.get("style", "")), "fontSize")
        adjacent_fonts = [value for value in (source_font, target_font) if value is not None and value > 0]
        if not adjacent_fonts:
            errors.append({
                "code": "DRAWING-VERTICAL-SPACING-POLICY",
                "message": f"关系 {relation['id']} 的相邻节点缺少有效字号，无法计算纵向间距",
            })
            continue

        normalized_gap = raw_gap * scale
        normalized_label_height = label_height * scale
        normalized_arrowhead_height = arrowhead_height * scale
        effective_blank = max(0.0, normalized_gap - normalized_label_height - normalized_arrowhead_height)
        font_line_height = min(adjacent_fonts) * line_height_factor * scale
        minimum_blank = font_line_height * min_ratio
        maximum_blank = font_line_height * max_ratio
        details = (
            f"关系 {relation['id']} 两节点净距 {normalized_gap:.1f}px，扣除关系标签 "
            f"{normalized_label_height:.1f}px 和箭头头部 {normalized_arrowhead_height:.1f}px 后，"
            f"有效空白 {effective_blank:.1f}px；相邻节点较小字体行高 {font_line_height:.1f}px"
        )
        if effective_blank + 0.01 < minimum_blank:
            errors.append({
                "code": "DRAWING-VERTICAL-SPACING-MIN",
                "message": f"{details}，小于2倍字体行高下限 {minimum_blank:.1f}px",
            })
        if effective_blank > maximum_blank + 0.01:
            errors.append({
                "code": "DRAWING-VERTICAL-SPACING-MAX",
                "message": f"{details}，超过3倍字体行高上限 {maximum_blank:.1f}px",
            })
    return errors


def verify_node_shapes(
    vertices: dict[str, ET.Element],
    figure: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, str]]:
    """校验命名及显式外框的判断、起止、存储语义，不把形状当装饰。"""
    errors: list[dict[str, str]] = []
    element_by_id = {item["id"]: item for item in figure["elements"]}
    label_pattern = re.compile(str(policy["cylinder_label_pattern"]))
    for node_id, cell in vertices.items():
        named_shapes = {"ellipse", "rhombus", "cylinder", "cylinder3", "rectangle"}
        shape = "rectangle"
        for part in cell.get("style", "").split(";"):
            if part in named_shapes:
                shape = part
            elif part.startswith("shape="):
                shape = part.split("=", 1)[1]
        element = element_by_id.get(node_id) or {}
        kind = element.get("kind")
        if kind == "decision" and shape != "rhombus":
            errors.append({"code": "DRAWING-SHAPE-SEMANTICS", "message": f"判断节点 {node_id} 必须保留菱形节点外框"})
        if kind and kind != "decision" and shape == "rhombus":
            errors.append({"code": "DRAWING-SHAPE-SEMANTICS", "message": f"非判断节点 {node_id} 不得使用菱形节点外框"})
        if kind == "start_end" and shape not in {"ellipse", "rectangle"}:
            errors.append({"code": "DRAWING-SHAPE-SEMANTICS", "message": f"开始／结束节点 {node_id} 的节点外框与合同语义不一致"})
        if shape not in {"cylinder", "cylinder3"}:
            continue
        element = element_by_id.get(node_id) or {}
        label = plain_text(cell.get("value", ""))
        if policy.get("cylinder_requires_data_store_kind") is True and element.get("kind") != "data_store":
            errors.append({
                "code": "DRAWING-CYLINDER-SEMANTICS",
                "message": f"节点 {node_id} 使用圆柱形，但drawing brief中的kind不是data_store",
            })
        if not label_pattern.search(label):
            errors.append({
                "code": "DRAWING-CYLINDER-SEMANTICS",
                "message": f"节点 {node_id} 使用圆柱形，但节点文字未明确表达存储或记录语义：{label}",
            })
    return errors


def verify_relation_labels(
    model: ET.Element,
    vertices: dict[str, ET.Element],
    edges: dict[str, ET.Element],
    figure: dict[str, Any],
    node_text_policy: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, str]]:
    """检查原生关系标签字号和纵向关系中的上下净空。"""
    errors: list[dict[str, str]] = []
    try:
        scale = reference_scale(model, figure, node_text_policy)
        minimum_ratio = float(policy["minimum_font_to_node_font_ratio"])
        clearance_multiple = float(policy["minimum_vertical_clearance_in_arrowhead_heights"])
        default_arrow_height = float(policy["default_arrowhead_height"])
        center_tolerance = float(policy["vertical_label_center_tolerance"])
        line_height_factor = float(node_text_policy["line_height_factor"])
    except (KeyError, TypeError, ValueError):
        return [{"code": "DRAWING-RELATION-LABEL-POLICY", "message": "无法读取原生关系标签策略"}]

    for relation in figure["relations"]:
        label = str(relation.get("label") or "").strip()
        if not label:
            continue
        edge = edges.get(relation["id"])
        source = vertices.get(relation["source"])
        target = vertices.get(relation["target"])
        if edge is None or source is None or target is None:
            continue
        edge_style = parse_style(edge.get("style", ""))
        edge_font = style_number(edge_style, "fontSize")
        source_font = style_number(parse_style(source.get("style", "")), "fontSize")
        target_font = style_number(parse_style(target.get("style", "")), "fontSize")
        if edge_font is None or edge_font <= 0:
            errors.append({"code": "DRAWING-EDGE-LABEL-FONT", "message": f"关系 {relation['id']} 必须显式设置原生关系标签字号"})
            continue
        adjacent_fonts = [value for value in (source_font, target_font) if value is not None and value > 0]
        if adjacent_fonts:
            minimum_font = min(adjacent_fonts) * minimum_ratio
            if edge_font + 0.01 < minimum_font:
                errors.append({
                    "code": "DRAWING-EDGE-LABEL-FONT",
                    "message": (
                        f"关系 {relation['id']} 标签字号 {edge_font:g} 小于相邻节点字号的 "
                        f"{minimum_ratio:.3f} 倍下限 {minimum_font:.2f}"
                    ),
                })

        source_box, target_box = rect(source), rect(target)
        if source_box is None or target_box is None:
            continue
        sx, sy, sw, sh = source_box
        tx, ty, tw, th = target_box
        horizontal_overlap = min(sx + sw, tx + tw) - max(sx, tx)
        if horizontal_overlap <= 0:
            continue
        if sy + sh <= ty:
            raw_gap = ty - (sy + sh)
        elif ty + th <= sy:
            raw_gap = sy - (ty + th)
        else:
            continue
        geometry = edge.find("mxGeometry")
        relative_position = 0.0
        if geometry is not None and geometry.get("x") not in {None, ""}:
            try:
                relative_position = float(geometry.get("x", "0"))
            except ValueError:
                relative_position = 0.0
        if policy.get("centered_vertical_label_required") is True and abs(relative_position) > center_tolerance:
            errors.append({
                "code": "DRAWING-EDGE-LABEL-CLEARANCE",
                "message": f"关系 {relation['id']} 的原生关系标签未位于上下节点间距中央：relative x={relative_position:g}",
            })
        label_lines = max(1, sum(1 for line in visible_text_lines(edge.get("value", "")) if line))
        label_height = label_lines * edge_font * line_height_factor * scale
        arrow_height = (style_number(edge_style, "endSize") or default_arrow_height) * scale
        clearance = (raw_gap * scale - label_height) / 2
        required_clearance = arrow_height * clearance_multiple
        if clearance + 0.01 < required_clearance:
            errors.append({
                "code": "DRAWING-EDGE-LABEL-CLEARANCE",
                "message": (
                    f"关系 {relation['id']} 标签上下净空各约 {clearance:.1f}px，小于一个箭头头部高度 "
                    f"{required_clearance:.1f}px"
                ),
            })
    return errors


def normalize_color(value: str | None) -> str | None:
    if not value or value.lower() in {"none", "transparent", "default"}:
        return None
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value.upper()
    return value.upper()


def find_drawio_skill(raw: Path | None) -> Path:
    candidates = [
        raw,
        Path.home() / ".codex/skills/drawio-skill",
        Path.home() / ".claude/skills/drawio-skill",
        Path.home() / ".cc-switch/skills/drawio-skill",
    ]
    for candidate in candidates:
        if candidate and (candidate / "scripts/validate.py").is_file():
            return candidate.resolve()
    raise FileNotFoundError("未找到 drawio-skill/scripts/validate.py")


def run_drawio_lint(drawio_skill: Path, drawing: Path) -> dict[str, Any]:
    command = [sys.executable, str(drawio_skill / "scripts/validate.py"), str(drawing), "--strict", "--json"]
    # Draw.io 在 Windows 下可能仍向 stderr 输出系统代码页字节；使用替换策略
    # 保留 lint 退出码和 JSON 标准输出，避免解码异常掩盖真正的结构检查结果。
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"errors": 1, "warnings": 0, "findings": [{"code": "LINT-OUTPUT", "message": result.stdout + result.stderr}]}
    return {"command": command, "exit_code": result.returncode, "report": payload}


def png_info(path: Path, white_threshold: int = 245) -> dict[str, Any]:
    exporter = load_module(SCRIPT_DIR / "export_patent_drawio.py", "patent_drawio_export_inspector")
    return exporter.inspect_png(path, white_threshold)


def verify_drawio(
    path: Path,
    figure: dict[str, Any],
    color_policy: dict[str, Any],
    drawio_skill: Path,
    node_text_policy: dict[str, Any] | None = None,
    vertical_spacing_policy: dict[str, Any] | None = None,
    node_shape_policy: dict[str, Any] | None = None,
    relation_label_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []

    def error(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    root = ET.parse(path).getroot()
    if root.tag != "mxfile" or root.get("compressed") != "false":
        error("DRAWING-XML", "必须是 mxfile compressed=false")
    diagrams = root.findall("diagram")
    if len(diagrams) != 1:
        error("DRAWING-PAGE", "每个专利附图母版必须恰好一页")
        model = None
    else:
        model = diagrams[0].find("mxGraphModel")
    if model is None or model.find("root") is None:
        error("DRAWING-XML", "缺少 mxGraphModel/root")
        return {"path": str(path), "sha256": sha256(path), "errors": errors, "passed": False}

    cells = model.findall("./root/mxCell")
    by_id = {cell.get("id", ""): cell for cell in cells}
    vertices = {key: cell for key, cell in by_id.items() if cell.get("vertex") == "1"}
    edges = {key: cell for key, cell in by_id.items() if cell.get("edge") == "1"}
    element_ids = {item["id"] for item in figure["elements"]}
    relation_ids = {item["id"] for item in figure["relations"]}

    for eid in element_ids:
        if eid not in vertices:
            error("DRAWING-ELEMENT", f"合同元素未出现在 drawio：{eid}")
    allowed_vertex_ids = element_ids
    for vid, cell in vertices.items():
        if vid in {"0", "1"}:
            continue
        if vid not in allowed_vertex_ids and not vid.startswith(("container-", "frame-", "decor-")):
            error("DRAWING-EXTRA", f"图中存在合同外的可见/技术节点：{vid}")

    for item in figure["elements"]:
        cell = vertices.get(item["id"])
        if cell is None:
            continue
        text = plain_text(cell.get("value", ""))
        matches_frozen_text = compact_label(text) in frozen_node_labels(item)
        if not matches_frozen_text:
            error("DRAWING-LABEL", f"元素 {item['id']} 的完整节点文字与合同不一致：{text!r}，合同标签：{item['label']!r}")
        mark = compact_label(item.get("reference_sign", ""))
        if mark and not matches_frozen_text and not has_reference_sign(text, mark):
            error("DRAWING-MARK", f"元素 {item['id']} 缺少标记：{mark}")

    visible_text_ids = {
        vid for vid, cell in vertices.items()
        if "text;" in cell.get("style", "") and plain_text(cell.get("value", ""))
    }
    for edge_id, edge in edges.items():
        source, target = edge.get("source"), edge.get("target")
        if not source or not target:
            error("DRAWING-ABSOLUTE-ENDPOINT", f"边 {edge_id} 缺少 source 或 target，不得以绝对端点代替真实连接")
        if source and source == target:
            error("DRAWING-SELF-LOOP", f"边 {edge_id} 出现未登记自连接")
        if source in visible_text_ids or target in visible_text_ids:
            error("DRAWING-TEXT-WAYPOINT", f"边 {edge_id} 使用可见文字节点作为端点")
        if edge_id not in relation_ids:
            error("DRAWING-EXTRA", f"图中存在合同外技术关系：{edge_id}")
        if "edgeStyle=orthogonalEdgeStyle" not in edge.get("style", ""):
            error("DRAWING-ROUTE", f"边 {edge_id} 不是正交连接")

    for relation in figure["relations"]:
        edge = edges.get(relation["id"])
        if edge is None:
            error("DRAWING-RELATION", f"合同关系未出现在 drawio：{relation['id']}")
            continue
        if edge.get("source") != relation["source"] or edge.get("target") != relation["target"]:
            error("DRAWING-RELATION", f"关系 {relation['id']} 的 source/target 与合同不一致")
        style = parse_style(edge.get("style", ""))
        # Draw.io默认在target端使用classic箭头；source端箭头会改变或混淆有向关系。
        directional_arrows = {"classic", "classicThin", "block", "blockThin", "open", "openThin", "async"}
        if style.get("startArrow", "none") != "none" or style.get("endArrow", "classic") not in directional_arrows:
            error("DRAWING-ARROW-DIRECTION", f"关系 {relation['id']} 的箭头必须仅指向合同target，不能反向、双向或无方向")
        label = relation.get("label", "").strip()
        edge_label = compact_label(edge.get("value", ""))
        if label and edge_label != compact_label(label):
            error("DRAWING-NATIVE-EDGE-LABEL", f"关系 {relation['id']} 的原生线条文字与合同不一致：{edge_label!r}")
        if not label and edge_label:
            error("DRAWING-NATIVE-EDGE-LABEL", f"无标签关系 {relation['id']} 出现多余原生线条文字：{edge_label!r}")
        detached_label_ids = [
            vid for vid, cell in vertices.items()
            if vid not in element_ids and plain_text(cell.get("value", "")) == label and label
        ]
        if detached_label_ids:
            error(
                "DRAWING-DETACHED-EDGE-LABEL",
                f"关系 {relation['id']} 不得使用独立文本框模拟线条文字：{sorted(detached_label_ids)}",
            )
        source_rect, target_rect = rect(vertices.get(relation["source"], ET.Element("x"))), rect(vertices.get(relation["target"], ET.Element("x")))
        points = explicit_points(edge)
        direction = relation.get("preferred_direction")
        if relation.get("direct_connection_required") and direction in {"vertical", "horizontal"} and source_rect and target_rect:
            sx, sy, sw, sh = source_rect; tx, ty, tw, th = target_rect
            if direction == "vertical" and abs((sx + sw / 2) - (tx + tw / 2)) > 1:
                error("DRAWING-DIRECT", f"关系 {relation['id']} 应竖直直连但节点中心未对齐")
            if direction == "horizontal" and abs((sy + sh / 2) - (ty + th / 2)) > 1:
                error("DRAWING-DIRECT", f"关系 {relation['id']} 应水平直连但节点中心未对齐")
            if points:
                error("DRAWING-DIRECT", f"关系 {relation['id']} 本应直连却设置了显式路由点")

    canvas_text = "\n".join(plain_text(cell.get("value", "")) for cell in vertices.values())
    if re.search(rf"图\s*{figure['figure_number']}(?![0-9])", canvas_text):
        error("DRAWING-FIGURE-NUMBER", "图号不得写入画布")

    allowed_fills = {normalize_color(value) for value in color_policy["allowed_fill_colors"]}
    allowed_strokes = {normalize_color(value) for value in color_policy["allowed_stroke_colors"]}
    nonwhite_fills: set[str] = set()
    for vid, cell in vertices.items():
        style = parse_style(cell.get("style", ""))
        fill = normalize_color(style.get("fillColor"))
        stroke = normalize_color(style.get("strokeColor"))
        if fill and fill not in allowed_fills:
            error("DRAWING-COLOR", f"节点 {vid} 使用未授权填充色：{fill}")
        if stroke and stroke not in allowed_strokes:
            error("DRAWING-COLOR", f"节点 {vid} 使用未授权边框色：{stroke}")
        if fill and fill not in {"#FFFFFF", "#F4F4F4", "#F5F5F5"}:
            nonwhite_fills.add(fill)
        if style.get("gradientColor") not in {None, "none"}:
            error("DRAWING-COLOR", f"节点 {vid} 使用渐变")
        if style.get("shadow") == "1" or style.get("sketch") == "1":
            error("DRAWING-COLOR", f"节点 {vid} 使用阴影或手绘效果")
    if len(nonwhite_fills) > color_policy["max_nonwhite_fills"]:
        error("DRAWING-COLOR", f"非白填充色超过上限：{sorted(nonwhite_fills)}")

    resolved_node_text_policy = node_text_policy or DEFAULT_NODE_TEXT_POLICY
    errors.extend(verify_node_text_layout(model, vertices, figure, resolved_node_text_policy))
    errors.extend(verify_vertical_spacing(
        model,
        vertices,
        edges,
        figure,
        resolved_node_text_policy,
        vertical_spacing_policy or DEFAULT_VERTICAL_SPACING_POLICY,
    ))
    errors.extend(verify_node_shapes(vertices, figure, node_shape_policy or DEFAULT_NODE_SHAPE_POLICY))
    errors.extend(verify_relation_labels(
        model,
        vertices,
        edges,
        figure,
        resolved_node_text_policy,
        relation_label_policy or DEFAULT_RELATION_LABEL_POLICY,
    ))

    lint = run_drawio_lint(drawio_skill, path)
    if lint["exit_code"] != 0 or lint["report"].get("errors") or lint["report"].get("warnings"):
        error("DRAWING-LINT", "drawio-skill validate.py --strict 未通过")

    return {
        "path": str(path),
        "sha256": sha256(path),
        "page_name": diagrams[0].get("name") if diagrams else None,
        "vertices": len(vertices),
        "edges": len(edges),
        "nonwhite_fill_colors": sorted(nonwhite_fills),
        "drawio_skill_lint": lint,
        "errors": errors,
        "passed": not errors,
    }


def reproduce_official_export(drawio_path: Path, final_png: Path, export: dict[str, Any]) -> dict[str, Any]:
    """Re-run the official exporter and require byte-identical PNG output."""

    parameters = export.get("parameters") or {}
    width = parameters.get("width")
    dpi = parameters.get("dpi", 300)
    border = parameters.get("border", 10)
    white_threshold = parameters.get("white_threshold", 245)
    maximum_margin = parameters.get("maximum_margin_pixels", 20)
    with tempfile.TemporaryDirectory(prefix="patent_drawing_verify_") as raw:
        temp = Path(raw)
        reproduced = temp / "reproduced.png"
        report = temp / "reproduced-report.json"
        command = [
            sys.executable, str(SCRIPT_DIR / "export_patent_drawio.py"),
            "--input", str(drawio_path), "--png", str(reproduced),
            "--dpi", str(dpi), "--border", str(border),
            "--white-threshold", str(white_threshold), "--max-margin", str(maximum_margin),
            "--report", str(report),
        ]
        if isinstance(width, int) and not isinstance(width, bool) and width > 0:
            command.extend(["--width", str(width)])
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180, check=False,
        )
        payload = load_json(report, "复算导出报告") if report.is_file() else {}
        return {
            "command": command,
            "exit_code": completed.returncode,
            "report": payload,
            "reproduced_sha256": sha256(reproduced) if reproduced.is_file() else None,
            "expected_sha256": sha256(final_png),
            "matched": reproduced.is_file() and sha256(reproduced) == sha256(final_png),
            "stderr_tail": completed.stderr[-1000:],
        }


def verify(brief_path: Path, case_dir: Path, drawio_skill_dir: Path | None) -> dict[str, Any]:
    brief_report = brief_validator.validate_brief(brief_path, case_dir)
    errors = list(brief_report.get("errors", []))
    brief = load_json(brief_path, "drawing-brief.json")
    brief_schema = brief.get("schema_id")
    output_schema = ({"cn-patent-drawing-brief/v4": "cn-patent-drawing-verification/v4", "cn-patent-drawing-brief/v3": "cn-patent-drawing-verification/v3"}.get(brief_schema, "cn-patent-drawing-verification/v2"))
    if errors:
        return {"schema_id": output_schema, "status": "FAIL", "errors": errors, "brief_validation": brief_report}
    drawio_skill = find_drawio_skill(drawio_skill_dir)
    visual_path = resolve_under(case_dir, brief["visual_review_path"], "visual_review_path")
    visual = load_json(visual_path, "visual-review.json")
    visual_schema = visual.get("schema_id")
    if brief_schema in {"cn-patent-drawing-brief/v3", "cn-patent-drawing-brief/v4"}:
        if visual_schema != "cn-patent-drawing-visual-review/v2":
            errors.append({"code": "DRAWING-VISUAL", "message": "v3/v4绘图合同必须使用 cn-patent-drawing-visual-review/v2"})
        if visual.get("brief_sha256") != sha256(brief_path):
            errors.append({"code": "DRAWING-VISUAL-STALE", "message": "视觉复核绑定的绘图合同已陈旧"})
        if not isinstance(visual.get("review_method"), str) or not visual["review_method"].strip():
            errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json 缺少实际查看方式 review_method"})
    elif visual_schema not in {"cn-patent-drawing-visual-review/v1", "cn-patent-drawing-visual-review/v2"}:
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json schema_id 无效"})
    if not isinstance(visual.get("reviewer"), str) or not visual["reviewer"].strip():
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json 缺少复核者"})
    if not isinstance(visual.get("reviewed_at"), str) or not visual["reviewed_at"].strip():
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json 缺少复核时间"})
    visual_items = visual.get("figures")
    if not isinstance(visual_items, list):
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json figures 必须是数组"})
        visual_items = []
    valid_visual_items = [item for item in visual_items if isinstance(item, dict) and isinstance(item.get("figure_number"), int)]
    if len(valid_visual_items) != len(visual_items):
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json 含无效图项或图号"})
    visual_by_number = {item["figure_number"]: item for item in valid_visual_items}
    if len(visual_by_number) != len(valid_visual_items):
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json 含重复图号"})
    pending_decisions = []
    figures = []
    for figure in brief["figures"]:
        machine_error_start = len(errors)
        number = figure["figure_number"]
        paths = {key: resolve_under(case_dir, raw, f"图{number} {key}") for key, raw in figure["outputs"].items() if raw}
        for required in ("drawio", "preview_png", "final_png", "export_report"):
            if required not in paths or not paths[required].is_file():
                errors.append({"code": "DRAWING-ARTIFACT", "message": f"图{number} 缺少 {required}"})
        if any(required not in paths or not paths[required].is_file() for required in ("drawio", "preview_png", "final_png", "export_report")):
            continue
        drawio_report = verify_drawio(
            paths["drawio"],
            figure,
            brief["global_constraints"]["color_policy"],
            drawio_skill,
            brief["global_constraints"]["node_text_policy"],
            brief["global_constraints"]["vertical_spacing_policy"],
            brief["global_constraints"]["node_shape_policy"],
            brief["global_constraints"]["relation_label_policy"],
        )
        errors.extend(drawio_report["errors"])
        export = load_json(paths["export_report"], f"图{number} export-report")
        if export.get("schema_id") != "cn-patent-drawio-export/v1":
            errors.append({"code": "DRAWING-EXPORT", "message": f"图{number} 导出报告 schema_id 无效"})
        if export.get("status") != "PASS" or (export.get("renderer") or {}).get("kind") != "drawio_desktop_cli":
            errors.append({"code": "DRAWING-EXPORT", "message": f"图{number} 未由 Draw.io Desktop CLI 正式导出"})
        export_parameters = export.get("parameters") or {}
        if export_parameters.get("size") != "diagram":
            errors.append({"code": "DRAWING-EXPORT-MODE", "message": f"图{number} 必须按 diagram 边界导出，禁止整页白边"})
        if (export.get("source") or {}).get("sha256") != sha256(paths["drawio"]):
            errors.append({"code": "DRAWING-EXPORT-STALE", "message": f"图{number} 导出报告绑定的 drawio 已陈旧"})
        margin_policy = brief["global_constraints"]["png_margin_policy"]
        png = png_info(paths["final_png"], margin_policy["white_threshold"])
        export_outputs = export.get("outputs") or {}
        export_png = export_outputs.get("png") or {}
        if export_png.get("sha256") != sha256(paths["final_png"]):
            errors.append({"code": "DRAWING-EXPORT-STALE", "message": f"图{number} 最终 PNG 与导出报告不一致"})
        reproduced = reproduce_official_export(paths["drawio"], paths["final_png"], export)
        if reproduced["exit_code"] != 0 or not reproduced["matched"]:
            errors.append({"code": "DRAWING-EXPORT-REPRODUCE", "message": f"图{number} 无法由当前母版复算出字节一致的官方 CLI PNG"})
        minimum_dpi = brief["global_constraints"].get("minimum_png_dpi", 300)
        if not png.get("dpi") or min(png["dpi"]) + 0.2 < minimum_dpi:
            errors.append({"code": "DRAWING-DPI", "message": f"图{number} PNG DPI 不足：{png.get('dpi')}"})
        if png.get("maximum_margin") is None or png["maximum_margin"] > margin_policy["maximum_margin_pixels"]:
            errors.append({
                "code": "DRAWING-EXCESSIVE-MARGIN",
                "message": f"图{number} PNG白边超过上限：{png.get('margins')}，maximum={margin_policy['maximum_margin_pixels']}",
            })
        machine_error_count = len(errors) - machine_error_start
        review = visual_by_number.get(number)
        figure_visual_errors = []
        if not isinstance(review, dict) or review.get("approved") is not True:
            figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 缺少批准的视觉复核"})
        else:
            try:
                reviewed_png = resolve_under(case_dir, review.get("png_path", ""), f"图{number} visual png_path")
            except ValueError as exc:
                figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": str(exc)})
            else:
                if reviewed_png != paths["final_png"]:
                    figure_visual_errors.append({"code": "DRAWING-VISUAL-STALE", "message": f"图{number} 视觉复核指向的不是当前最终 PNG"})
            if review.get("png_sha256") != sha256(paths["final_png"]):
                figure_visual_errors.append({"code": "DRAWING-VISUAL-STALE", "message": f"图{number} 视觉复核绑定的 PNG 已陈旧"})
            if brief_schema in {"cn-patent-drawing-brief/v3", "cn-patent-drawing-brief/v4"}:
                try:
                    reviewed_export = resolve_under(case_dir, review.get("export_report_path", ""), f"图{number} visual export_report_path")
                except ValueError as exc:
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": str(exc)})
                else:
                    if reviewed_export != paths["export_report"]:
                        figure_visual_errors.append({"code": "DRAWING-VISUAL-STALE", "message": f"图{number} 视觉复核指向的不是当前导出报告"})
                if review.get("export_report_sha256") != sha256(paths["export_report"]):
                    figure_visual_errors.append({"code": "DRAWING-VISUAL-STALE", "message": f"图{number} 视觉复核绑定的导出报告已陈旧"})
                inspection = review.get("inspection")
                if not isinstance(inspection, dict):
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 缺少 inspection 观察记录"})
                    inspection = {}
                full_scale = inspection.get("full_scale_percent")
                reduced_scale = inspection.get("reduced_scale_percent")
                if not isinstance(full_scale, int) or isinstance(full_scale, bool) or full_scale < 100:
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 未记录至少 100% 比例检查"})
                if not isinstance(reduced_scale, int) or isinstance(reduced_scale, bool) or not 20 <= reduced_scale <= 80:
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 未记录 20%—80% 缩小检查"})
                if not isinstance(inspection.get("viewed_at"), str) or not inspection["viewed_at"].strip():
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 缺少实际查看时间"})
            required_checks = [
                "text_legible", "no_text_overlap", "no_edge_crossing", "no_edge_through_node",
                "no_arrow_ambiguity", "labels_adjacent", "no_unnecessary_detours",
                "consistent_typography", "balanced_spacing", "clear_visual_hierarchy",
                "formal_patent_style", "grayscale_safe", "no_figure_number_on_canvas",
                "node_text_proportionate", "no_text_overflow", "no_excessive_canvas_margin",
            ]
            mode_check = "monochrome" if brief["global_constraints"]["color_policy"]["mode"] == "monochrome" else "restrained_color"
            required_checks.append(mode_check)
            checks = review.get("checks") or {}
            for check in required_checks:
                if checks.get(check) is not True:
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 视觉检查未通过：{check}"})
            if brief_schema in {"cn-patent-drawing-brief/v3", "cn-patent-drawing-brief/v4"}:
                observations = (review.get("inspection") or {}).get("observations")
                if not isinstance(observations, dict):
                    figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 缺少逐项 observations"})
                    observations = {}
                for check in required_checks:
                    if not isinstance(observations.get(check), str) or not observations[check].strip():
                        figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 缺少视觉检查观察记录：{check}"})
            if bool(checks.get("monochrome")) == bool(checks.get("restrained_color")):
                figure_visual_errors.append({"code": "DRAWING-VISUAL", "message": f"图{number} 黑白/克制彩色模式必须且只能确认一种"})

        visual_stales = [e for e in figure_visual_errors if e["code"] == "DRAWING-VISUAL-STALE"]
        visual_missings = [e for e in figure_visual_errors if e["code"] == "DRAWING-VISUAL"]
        errors.extend(visual_stales)
        final_visual_status = review
        if visual_missings:
            if machine_error_count == 0 and not visual_stales:
                pending_decisions.append({
                    "key": "drawing.visual_review_pending",
                    "source": {"tool_id": "verify_patent_drawings", "rule_id": "DRAWING-VISUAL"},
                    "target": {"kind": "drawing", "locator": f"图{number}"},
                    "question": "视觉复核未批准或有未通过项",
                    "adopted_default": "机器指标达标，按当前 PNG 交付，视觉复核待人工",
                    "options": ["批准", "不批准"],
                    "impact": ["delivery"],
                    "decider": "attorney"
                })
                final_visual_status = "pending"
            else:
                errors.extend(visual_missings)
        figures.append({"figure_number": number, "drawio": drawio_report, "png": {"path": str(paths["final_png"]), **png}, "export_report": str(paths["export_report"]), "official_reexport": reproduced, "visual_review": final_visual_status})
    expected_numbers = [item["figure_number"] for item in brief["figures"]]
    if sorted(visual_by_number) != expected_numbers:
        errors.append({"code": "DRAWING-VISUAL", "message": "visual-review.json 图号集合与绘图合同不一致"})
    return {
        "schema_id": output_schema,
        "brief": str(brief_path),
        "brief_sha256": sha256(brief_path),
        "drawio_skill": str(drawio_skill),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "pending_decisions": pending_decisions,
        "evidence_scope": {
            "proves": ["绘图合同和来源哈希有效", "当前 Draw.io 母版可复算得到当前最终 PNG", "技术节点字号、框字比例、显式中文换行、节点形状、关系标签字号与净空、估算文本容量和纵向空白间距满足合同", "视觉复核记录绑定当前合同、导出报告和最终 PNG", "逐项视觉检查均有观察记录"],
            "does_not_prove": ["图示技术方案具备新颖性或创造性", "说明书和权利要求的法律支持关系已经成立", "未由复核者实际观察到的视觉事实"],
        },
        "brief_validation": brief_report,
        "figures": figures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证中国专利 Draw.io 附图交付包")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--drawio-skill-dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify(args.brief.resolve(), args.case_dir.resolve(), args.drawio_skill_dir)
    except Exception as exc:
        report = {"schema_id": "cn-patent-drawing-verification/v2", "status": "FAIL", "errors": [{"code": "DRAWING-VERIFY-CRASH", "message": f"{type(exc).__name__}: {exc}"}], "figures": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
