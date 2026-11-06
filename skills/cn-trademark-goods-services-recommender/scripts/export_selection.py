#!/usr/bin/env python3
"""将商标分类推荐/选类结果导出为商标局网上申报系统 Excel 模版或 CSV 文件

完全使用 Python 3 标准库（内置 zipfile + XML 生成），不依赖 openpyxl 或任何第三方库。
格式规范：
  - 符合国家知识产权局商标局网上申请“导入商品信息”模版格式；
  - 表头包含：序号、商品类别、类似群、商品名称；
  - 类似群自动转换为商标局申报规范的两码（如 2114 -> 14，0901 -> 01）；
  - 不同大类之间插入空白分隔行；
  - Excel 导出支持按大类梯队着色标记（浅绿到浅暖色系过渡），便于辨识与核对；
  - CSV 导出带 UTF-8 BOM，确保 Excel 双击打开不乱码。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple

# 推荐顺位大类背景填充色（与线上系统一致）
CLASS_RANK_FILL_COLORS = [
    "C6E0B4",  # 强推荐 1：清新浅绿
    "D9EAD3",  # 强推荐 2：薄荷淡绿
    "E2F0D9",  # 推荐 1：茶淡绿
    "FFF2CC",  # 推荐 2：浅暖黄
    "FCE4D6",  # 推荐 3：浅橙粉
    "F8CBAD",  # 扩展 1：淡珊瑚橙
    "F4CCCC",  # 扩展 2：淡绯红
    "DDEBF7",  # 扩展 3：淡柔蓝
    "D9E1F2",  # 扩展 4：浅青紫
    "EADCF8",  # 扩展 5：浅紫罗兰
]

EXPORT_HEADERS = ["序号", "商品类别", "类似群", "商品名称"]


@dataclass
class ExportRow:
    sequence: int
    class_code: str
    group_code: str  # 两位规范群码
    item_name: str
    class_index: int


def normalize_class_code(code: Any) -> str:
    clean = str(code or "").strip()
    return clean.zfill(2) if clean.isdigit() else clean


def normalize_group_code_for_export(group_code: str, class_code: str) -> str:
    clean_group = str(group_code or "").strip()
    clean_class = str(class_code or "").strip()

    if clean_class and clean_group.startswith(clean_class):
        return clean_group[len(clean_class):].zfill(2)

    return clean_group[-2:].zfill(2) if len(clean_group) >= 2 else clean_group


def extract_rows_from_selection(data: Any) -> list[Optional[ExportRow]]:
    """从校验后或原始推荐 JSON 中提取导出行列表（类间以 None 分隔）"""
    classes_list: list[dict[str, Any]] = []

    if isinstance(data, dict):
        classes_list = data.get("classes", [])
    elif isinstance(data, list):
        classes_list = data

    result_rows: list[Optional[ExportRow]] = []
    seq = 1

    for class_idx, class_obj in enumerate(classes_list):
        c_code = normalize_class_code(class_obj.get("class_code") or class_obj.get("classCode"))
        groups_list = class_obj.get("groups", [])
        class_has_items = False

        for group_obj in groups_list:
            raw_g_code = str(group_obj.get("group_code") or group_obj.get("groupCode") or "").strip()
            norm_g_code = str(group_obj.get("normalized_group_code") or group_obj.get("normalizedGroupCode") or "").strip()
            if not norm_g_code:
                norm_g_code = normalize_group_code_for_export(raw_g_code, c_code)

            items_list = group_obj.get("items", [])
            for it in items_list:
                item_name = str(it.get("name") if isinstance(it, dict) else it).strip()
                if not item_name:
                    continue

                result_rows.append(
                    ExportRow(
                        sequence=seq,
                        class_code=c_code,
                        group_code=norm_g_code,
                        item_name=item_name,
                        class_index=class_idx,
                    )
                )
                seq += 1
                class_has_items = True

        if class_has_items and class_idx < len(classes_list) - 1:
            result_rows.append(None)  # 类间空白分隔行

    # 去除末尾空行
    while result_rows and result_rows[-1] is None:
        result_rows.pop()

    return result_rows


def export_to_csv(rows: list[Optional[ExportRow]], output_path: Optional[Path] = None) -> str:
    """导出为带 BOM 的 UTF-8 CSV 字符串或写入文件"""
    output = io.StringIO()
    # 写入 UTF-8 BOM
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(EXPORT_HEADERS)

    for row in rows:
        if row is None:
            writer.writerow([])
        else:
            writer.writerow([row.sequence, row.class_code, row.group_code, row.item_name])

    csv_text = output.getvalue()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(csv_text, encoding="utf-8")

    return csv_text


# 内置基础样式表与模板文件内容（当外部 assets 缺失时仍可独立运行）
BUILTIN_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

BUILTIN_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

BUILTIN_WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="导入商品信息" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

BUILTIN_WORKBOOK_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def build_styles_xml(num_classes: int) -> tuple[str, dict[int, int], int]:
    """构建支持类目高亮与居中对齐的 styles.xml"""
    used_colors = CLASS_RANK_FILL_COLORS[: max(1, min(num_classes, len(CLASS_RANK_FILL_COLORS)))]

    # 基础 fills (0: none, 1: gray125)
    fills_xml = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
    fill_start_idx = len(fills_xml)

    class_fill_ids: dict[int, int] = {}
    for idx, color in enumerate(used_colors):
        fills_xml.append(f'<fill><patternFill patternType="solid"><fgColor rgb="FF{color}"/><bgColor indexed="64"/></patternFill></fill>')
        class_fill_ids[idx] = fill_start_idx + idx

    # cellXfs (0: default)
    cell_xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
    # 1: 表头样式（居中加粗，轻微灰色或无底色）
    header_xf_idx = len(cell_xfs)
    cell_xfs.append(
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    )

    # 各大类对应的 cellXf (居中) 与左对齐 (名称)
    class_style_indexes: dict[int, int] = {}
    for idx in range(len(used_colors)):
        fill_id = class_fill_ids[idx]
        style_idx = len(cell_xfs)
        cell_xfs.append(
            f'<xf numFmtId="0" fontId="0" fillId="{fill_id}" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        )
        class_style_indexes[idx] = style_idx

    styles_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="10.5"/><name val="宋体"/><family val="2"/></font>
    <font><b/><sz val="11.0"/><name val="宋体"/><family val="2"/></font>
  </fonts>
  <fills count="{len(fills_xml)}">
    {''.join(fills_xml)}
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="{len(cell_xfs)}">
    {''.join(cell_xfs)}
  </cellXfs>
</styleSheet>"""

    return styles_xml, class_style_indexes, header_xf_idx


def escape_xml(text: str) -> str:
    """转义 XML 特殊字符"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_worksheet_xml(
    rows: list[Optional[ExportRow]],
    class_style_indexes: dict[int, int],
    header_style_idx: int,
) -> str:
    """生成 sheet1.xml 内容"""
    max_row = len(rows) + 1  # 包含表头
    dimension = f"A1:D{max_row}"

    cols_xml = """<cols>
    <col min="1" max="1" width="8.0" customWidth="1"/>
    <col min="2" max="2" width="12.0" customWidth="1"/>
    <col min="3" max="3" width="10.0" customWidth="1"/>
    <col min="4" max="4" width="28.0" customWidth="1"/>
  </cols>"""

    sheet_rows_xml: list[str] = []

    # 表头行 (r=1)
    sheet_rows_xml.append(
        f'<row r="1" ht="20.0" customHeight="1">'
        f'<c r="A1" s="{header_style_idx}" t="inlineStr"><is><t>序号</t></is></c>'
        f'<c r="B1" s="{header_style_idx}" t="inlineStr"><is><t>商品类别</t></is></c>'
        f'<c r="C1" s="{header_style_idx}" t="inlineStr"><is><t>类似群</t></is></c>'
        f'<c r="D1" s="{header_style_idx}" t="inlineStr"><is><t>商品名称</t></is></c>'
        f"</row>"
    )

    for idx, r in enumerate(rows, start=2):
        if r is None:
            # 空白分隔行
            sheet_rows_xml.append(f'<row r="{idx}" ht="12.0" customHeight="1"/>')
        else:
            style_idx = class_style_indexes.get(
                r.class_index % len(CLASS_RANK_FILL_COLORS), 0
            )
            seq_val = escape_xml(str(r.sequence))
            class_val = escape_xml(r.class_code)
            group_val = escape_xml(r.group_code)
            name_val = escape_xml(r.item_name)

            sheet_rows_xml.append(
                f'<row r="{idx}" ht="18.0" customHeight="1">'
                f'<c r="A{idx}" s="{style_idx}"><v>{seq_val}</v></c>'
                f'<c r="B{idx}" s="{style_idx}" t="inlineStr"><is><t>{class_val}</t></is></c>'
                f'<c r="C{idx}" s="{style_idx}" t="inlineStr"><is><t>{group_val}</t></is></c>'
                f'<c r="D{idx}" s="{style_idx}" t="inlineStr"><is><t>{name_val}</t></is></c>'
                f"</row>"
            )

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="{dimension}"/>
  <sheetViews>
    <sheetView tabSelected="1" workbookViewId="0"/>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="16.0"/>
  {cols_xml}
  <sheetData>
    {''.join(sheet_rows_xml)}
  </sheetData>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>"""


def export_to_xlsx(
    rows: list[Optional[ExportRow]],
    output_path: Path,
    template_path: Optional[Path] = None,
) -> None:
    """生成商标局 Excel 导入模版 (.xlsx)"""
    num_classes = max((r.class_index + 1 for r in rows if r is not None), default=1)
    styles_xml, class_style_indexes, header_style_idx = build_styles_xml(num_classes)
    worksheet_xml = build_worksheet_xml(rows, class_style_indexes, header_style_idx)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", BUILTIN_CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", BUILTIN_RELS_XML)
        zf.writestr("xl/workbook.xml", BUILTIN_WORKBOOK_XML)
        zf.writestr("xl/_rels/workbook.xml.rels", BUILTIN_WORKBOOK_RELS_XML)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", worksheet_xml)


def generate_default_filename(query: str, ext: str = "xlsx") -> str:
    clean_query = re.sub(r"[^\w\u4e00-\u9fa5]", "", query)[:10] or "商标申请"
    date_str = datetime.now().strftime("%Y%m%d")
    return f"商标局导入模版_{clean_query}_{date_str}.{ext}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将商标选类结果导出为商标局网上申报模版（Excel/CSV）"
    )
    default_template_path = Path(__file__).resolve().parent.parent / "assets" / "导入商品信息.xlsx"

    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="输入文件路径（JSON 格式），或留空/指定 '-' 从标准输入读取",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出文件路径（默认按业务名称和日期自动命名为 .xlsx 或 .csv）",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["xlsx", "csv"],
        default="xlsx",
        help="导出格式：xlsx (商标局导入模版 Excel，默认) 或 csv",
    )
    parser.add_argument(
        "--query-name",
        type=str,
        default="商标清单",
        help="用于自动命名文件的业务简短名称",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=default_template_path,
        help="可选的原始模版文件路径",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="若格式为 CSV，直接输出到标准输出",
    )

    args = parser.parse_args()

    # 1. 读取输入数据
    try:
        if args.input == "-":
            raw_content = sys.stdin.read()
        else:
            in_path = Path(args.input)
            if not in_path.is_file():
                print(f"错误: 输入文件不存在: {in_path}", file=sys.stderr)
                return 1
            raw_content = in_path.read_text(encoding="utf-8")

        raw_data = json.loads(raw_content)
    except Exception as e:
        print(f"错误: 读取或解析输入 JSON 失败: {e}", file=sys.stderr)
        return 1

    # 2. 提取导出行
    rows = extract_rows_from_selection(raw_data)
    if not rows:
        print("警告: 输入数据中未提取到任何有效的商品/服务项", file=sys.stderr)
        return 1

    # 3. 确定输出路径
    output_path = args.output
    if not output_path and not args.stdout:
        output_path = Path(generate_default_filename(args.query_name, ext=args.format))

    # 4. 执行导出
    try:
        if args.format == "csv":
            csv_str = export_to_csv(rows, output_path=output_path if not args.stdout else None)
            if args.stdout:
                sys.stdout.write(csv_str)
            else:
                print(f"✓ 成功导出 CSV 清单: {output_path.resolve()} (共 {sum(1 for r in rows if r is not None)} 项)")
        else:
            template_p = args.template if args.template and args.template.is_file() else None
            export_to_xlsx(rows, output_path, template_path=template_p)
            print(f"✓ 成功生成商标局申报 Excel: {output_path.resolve()} (共 {sum(1 for r in rows if r is not None)} 项)")
        return 0
    except Exception as e:
        print(f"导出失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
