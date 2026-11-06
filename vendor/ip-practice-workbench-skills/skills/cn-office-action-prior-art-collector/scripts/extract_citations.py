#!/usr/bin/env python3
"""从中国专利审查意见通知书或资料文档中抽取对比文件与著录项信息。

支持输入文件格式：
- 纯文本 / Markdown (.txt, .md)
- Word 文档 (.docx) —— 基于标准库 zipfile + xml 解析
- PDF 文档 (.pdf) —— 优先可选 fitz (PyMuPDF)，自动降级至内置流与 CMap 解析器

解析模式：
- auto: 自动识别是否为正式审查意见通知书（OA）或自由文献清单
- oa: 正式审查意见通知书模式，抽取封面著录项、第 5 栏对比文件及正文审查意见
- free: 自由文献清单模式，采用防误报收紧正则从全文本提取对比文件号

无需强制外部依赖，纯 Python 标准库即可运行。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

# 允许从当前脚本同级目录导入 normalize_patent_number
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from normalize_patent_number import (  # noqa: E402
    format_application_number,
    infer_patent_type_from_number,
    normalize_patent_number,
    validate_cn_check_digit,
)

# 可选第三方依赖：PyMuPDF
try:
    import fitz  # type: ignore[import-not-found]
except ImportError:
    fitz = None

# ---------------------------------------------------------------------------
# 正则表达式与模式常量
# ---------------------------------------------------------------------------

PATENT_ID_RE = re.compile(
    r"\b(?:"
    r"(?:CN|ZL)\s?(?:(?:\d{8,}(?:\.[\dXx])?|\d{7})\s*[A-Za-z]\d?|\d{8,}(?:\.[\dXx])?)"
    r"|US\s?(?:(?:\d{1,3}(?:,\d{3})+|\d{4}\s?\d{7}|\d{7,8})\s*(?:[A-Za-z]\d?)?|\d{1,7}\s*[A-Za-z]\d)"
    r"|WO\s?(?:(?:\d{4}/\d{5,7}|\d{2}/\d{5,6}|\d{6,})\s*(?:[A-Za-z]\d?)?)"
    r"|(?:EP|JP|KR)\s?\d{6,}(?:\s*[A-Za-z]\d?)?"
    r")",
    re.IGNORECASE,
)
NOTICE_TITLE_RE = re.compile(r"(第[一二三四五六七八九十百0-9]+次审查意见通知书)")
CLAIM_RE = re.compile(r"权利要求\s*([0-9、,，\-至和及 ]+)")
LEGAL_BASIS_RE = re.compile(r"专利法第[一二三四五六七八九十百0-9]+条(?:第[一二三四五六七八九十百0-9]+款)?")
BODY_START_MARKERS = (
    "本申请涉及",
    "经审查，现提出以下审查意见",
    "经审查，提出以下审查意见",
    "现提出以下审查意见",
    "现提出审查意见如下",
    "审查意见：",
    "审查意见:",
    "具体意见如下",
    "一、审查意见",
)
ATTACHMENT_MARKERS = ("检索报告",)

_PATENT_PREFIXED_RE = PATENT_ID_RE
_CN_BARE_APPLICATION_RE = re.compile(r"(?<![\dA-Za-z])(\d{12,13}(?:\.[\dXx])?)(?![\dA-Za-z])")
_CN_APP_WITH_DOT_RE = re.compile(r"(?:(?:CN|ZL)\s*)?(\d{8}|\d{12})\.([\dXx])(?!\d)", re.IGNORECASE)

DEFAULT_MAX_CITATIONS = 30


# ---------------------------------------------------------------------------
# 自包含文件文本抽取器 (纯标准库 + 可选 PyMuPDF)
# ---------------------------------------------------------------------------

def normalize_extracted_text(text: str) -> str:
    """清理换行与连续空白。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\u3000]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def extract_text_from_plain_bytes(payload: bytes) -> str:
    """UTF-8 (自动去 BOM) -> GBK -> UTF-8 ignore 降级解析。"""
    if payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = payload.decode("gbk")
        except UnicodeDecodeError:
            text = payload.decode("utf-8", errors="ignore")
    return normalize_extracted_text(text)


def extract_text_from_docx_bytes(payload: bytes) -> str:
    """无需 python-docx，直接使用标准库 zipfile + xml 解析 document.xml。"""
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        try:
            xml_bytes = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("DOCX 文件缺少 word/document.xml") from exc
    root = ElementTree.fromstring(xml_bytes)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        fragments = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(fragments).strip()
        if text:
            paragraphs.append(text)
    return normalize_extracted_text("\n".join(paragraphs))


def _iter_pdf_streams(payload: bytes) -> Iterable[tuple[bool, bytes]]:
    for match in re.finditer(rb"<<(?P<dict>.*?)>>\s*stream\r?\n(?P<data>.*?)\r?\nendstream", payload, re.S):
        dictionary = match.group("dict")
        data = match.group("data")
        yield b"/FlateDecode" in dictionary, data


def _decode_pdf_literal(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            result.append(char)
            index += 1
            continue
        index += 1
        if index >= len(value):
            break
        marker = value[index]
        escape_map = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}
        if marker in escape_map:
            result.append(escape_map[marker])
            index += 1
            continue
        if marker.isdigit():
            octal = marker
            for _ in range(2):
                if index + 1 < len(value) and value[index + 1].isdigit():
                    index += 1
                    octal += value[index]
                else:
                    break
            result.append(chr(int(octal, 8)))
            index += 1
            continue
        result.append(marker)
        index += 1
    return "".join(result)


def _decode_pdf_hex_target(value: str) -> str:
    if len(value) % 4 != 0:
        return ""
    chars: list[str] = []
    for index in range(0, len(value), 4):
        chunk = value[index : index + 4]
        try:
            chars.append(chr(int(chunk, 16)))
        except ValueError:
            return ""
    return "".join(chars)


def _parse_bfchar_mappings(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for section in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for source, target in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", section):
            decoded = _decode_pdf_hex_target(target)
            if decoded:
                mapping[source.upper()] = decoded
    return mapping


def _parse_bfrange_mappings(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    pattern = re.compile(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]+\]|<[^>]+>)")
    for section in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for start_hex, end_hex, target in pattern.findall(section):
            start = int(start_hex, 16)
            end = int(end_hex, 16)
            width = len(start_hex)
            if target.startswith("["):
                values = re.findall(r"<([0-9A-Fa-f]+)>", target)
                for offset, value in enumerate(values):
                    key = f"{start + offset:0{width}X}"
                    decoded = _decode_pdf_hex_target(value)
                    if decoded:
                        mapping[key] = decoded
                continue
            base = int(target.strip("<>"), 16)
            for offset, codepoint in enumerate(range(base, base + (end - start + 1))):
                key = f"{start + offset:0{width}X}"
                try:
                    mapping[key] = chr(codepoint)
                except ValueError:
                    continue
    return mapping


def _extract_pdf_cmap(payload: bytes) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for compressed, stream in _iter_pdf_streams(payload):
        raw = stream
        if compressed:
            try:
                raw = zlib.decompress(stream)
            except zlib.error:
                continue
        if b"beginbfchar" not in raw and b"beginbfrange" not in raw:
            continue
        text = raw.decode("latin-1", errors="ignore")
        mapping.update(_parse_bfchar_mappings(text))
        mapping.update(_parse_bfrange_mappings(text))
    return mapping


def _decode_pdf_hex_string(value: str, cmap: dict[str, str]) -> str:
    normalized = re.sub(r"\s+", "", value).upper()
    if not normalized or len(normalized) % 2 != 0:
        return ""
    if not cmap:
        try:
            return bytes.fromhex(normalized).decode("latin-1", errors="ignore")
        except ValueError:
            return ""
    key_lengths = sorted({len(key) for key in cmap.keys()}, reverse=True)
    result: list[str] = []
    index = 0
    while index < len(normalized):
        matched = False
        for key_length in key_lengths:
            chunk = normalized[index : index + key_length]
            if len(chunk) != key_length:
                continue
            decoded = cmap.get(chunk)
            if decoded is None:
                continue
            result.append(decoded)
            index += key_length
            matched = True
            break
        if matched:
            continue
        try:
            result.append(bytes.fromhex(normalized[index : index + 2]).decode("latin-1", errors="ignore"))
        except ValueError:
            break
        index += 2
    return "".join(result)


def _extract_text_from_pdf_streams(payload: bytes) -> str:
    texts: list[str] = []
    cmap = _extract_pdf_cmap(payload)
    for compressed, stream in _iter_pdf_streams(payload):
        raw = stream
        if compressed:
            try:
                raw = zlib.decompress(stream)
            except zlib.error:
                continue
        stream_text = raw.decode("latin-1", errors="ignore")
        for block in re.findall(r"BT(.*?)ET", stream_text, re.S):
            for literal in re.findall(r"\((.*?)\)\s*T[Jj]", block, re.S):
                texts.append(_decode_pdf_literal(literal))
            for hex_value in re.findall(r"<([0-9A-Fa-f]+)>\s*T[Jj]", block, re.S):
                decoded = _decode_pdf_hex_string(hex_value, cmap)
                if decoded.strip():
                    texts.append(decoded)
            for array in re.findall(r"\[(.*?)\]\s*TJ", block, re.S):
                for literal in re.findall(r"\((.*?)\)", array, re.S):
                    texts.append(_decode_pdf_literal(literal))
                for hex_value in re.findall(r"<([0-9A-Fa-f]+)>", array):
                    decoded = _decode_pdf_hex_string(hex_value, cmap)
                    if decoded.strip():
                        texts.append(decoded)
    return normalize_extracted_text("\n".join(item.strip() for item in texts if item.strip()))


def extract_text_from_pdf_bytes(payload: bytes) -> str:
    """PDF 文本提取：优先 PyMuPDF，降级内置流与 CMap 解析器。"""
    if fitz is not None:
        try:
            with fitz.open(stream=payload, filetype="pdf") as doc:
                pages: list[str] = []
                for page in doc:
                    page_text = page.get_text("text", sort=True).strip()
                    if page_text:
                        pages.append(page_text)
                if pages:
                    return normalize_extracted_text("\n\n".join(pages))
        except Exception:
            pass

    # 内置轻量解析器
    stream_text = _extract_text_from_pdf_streams(payload)
    if any(marker in stream_text for marker in ("申请号", "发明名称", "审查员", "权利要求")):
        return stream_text

    # 兜底可见字符
    decoded = payload.decode("utf-8", errors="ignore")
    lines = [line.strip() for line in decoded.splitlines() if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", line.strip())]
    visible_text = normalize_extracted_text("\n".join(lines))
    return stream_text or visible_text


def extract_text_from_file(file_path: Path) -> str:
    """按扩展名自动提取文件纯文本。"""
    suffix = file_path.suffix.lower()
    payload = file_path.read_bytes()
    if suffix in (".txt", ".md"):
        return extract_text_from_plain_bytes(payload)
    if suffix == ".docx":
        return extract_text_from_docx_bytes(payload)
    if suffix == ".pdf":
        return extract_text_from_pdf_bytes(payload)
    # 其它类型默认按普通文本尝试
    return extract_text_from_plain_bytes(payload)


# ---------------------------------------------------------------------------
# 自由文本模式抽取逻辑
# ---------------------------------------------------------------------------

def build_citation_context(text: str, document_id: str, span: int = 40) -> str:
    compact = re.sub(r"\s+", " ", text)
    index = compact.find(document_id)
    match_len = len(document_id)
    if index == -1:
        # 兼容带逗号、斜杠、空格的原始形态（如 US 10,123,456 B2 或 WO 2020/123456 A1）
        char_pat = r"[/,\s]*".join(re.escape(c) for c in document_id)
        m = re.search(char_pat, compact, re.IGNORECASE)
        if m:
            index = m.start()
            match_len = m.end() - m.start()
    if index == -1:
        digits_core = re.sub(r"[^0-9]", "", document_id)
        if len(digits_core) >= 7:
            index = compact.find(digits_core)
            match_len = len(digits_core)
    if index == -1:
        return document_id
    start = max(0, index - span)
    end = min(len(compact), index + match_len + span)
    return compact[start:end].strip()


def extract_patent_ids_free_text(text: str, exclude_application_numbers: bool = True) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    excluded_norms: set[str] = set()
    if exclude_application_numbers:
        for app_match in _CN_APP_WITH_DOT_RE.finditer(text):
            main_digits = app_match.group(1)
            excluded_norms.add(f"CN{main_digits}".upper())
            excluded_norms.add(main_digits)

    for match in _PATENT_PREFIXED_RE.finditer(text):
        raw = match.group(0).rstrip(".,;:?!)'\"”’").strip()
        norm = normalize_patent_number(raw).strip().upper()
        if not norm:
            continue
        if exclude_application_numbers:
            if norm in excluded_norms or norm.replace(".", "") in excluded_norms:
                continue
            if _CN_APP_WITH_DOT_RE.search(raw):
                continue
        if norm not in seen:
            seen.add(norm)
            ordered.append(norm)

    for match in _CN_BARE_APPLICATION_RE.finditer(text):
        raw = match.group(1).rstrip(".,;:?!)'\"”’").strip()
        if exclude_application_numbers:
            if _CN_APP_WITH_DOT_RE.search(raw):
                continue
        norm = normalize_patent_number(raw).strip().upper()
        if not norm:
            continue
        if exclude_application_numbers and (norm in excluded_norms or norm.replace(".", "") in excluded_norms):
            continue
        if norm not in seen:
            seen.add(norm)
            ordered.append(norm)

    return ordered


# ---------------------------------------------------------------------------
# 审查意见通知书 (OA) 结构化抽取逻辑
# ---------------------------------------------------------------------------

def _clean_extracted_value(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", cleaned)
    return cleaned


def _extract_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return _clean_extracted_value(match.group(1))
    return None


def _extract_mailing_date(front_text: str) -> str | None:
    # 1. 优先带明确发文日前缀的匹配
    direct = _extract_first(
        front_text,
        [
            r"(?:发文日期|发文日|通知书发文日)[:：]\s*([0-9]{4}\s*年\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日)",
            r"(?:发文日期|发文日|通知书发文日)[:：]\s*([0-9]{4}[./-][0-9]{1,2}[./-][0-9]{1,2})",
        ],
    )
    if direct:
        return direct

    # 2. 回退无前缀扫描：必须严格排除第 5 栏区域及含"公开日/公布日/对比文件/申请日/优先权日/检索"的行
    clean_lines: list[str] = []
    for line in front_text.splitlines():
        line_str = line.strip()
        if re.search(r"^\s*5\.", line_str) or "对比文件" in line_str or "检索报告" in line_str:
            break
        if any(bad in line_str for bad in ("公开日", "公布日", "申请日", "优先权日", "公告日", "授权日", "对比文件", "检索")):
            continue
        clean_lines.append(line_str)

    clean_text = "\n".join(clean_lines)
    dates = re.findall(r"(?:^|[^\d])([0-9]{4}\s*年\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日)", clean_text)
    if dates:
        return _clean_extracted_value(dates[0])
    plain = re.findall(r"(?:^|[^\d])([0-9]{4}[./-][0-9]{1,2}[./-][0-9]{1,2})(?:$|[^\d])", clean_text)
    if plain:
        return _clean_extracted_value(plain[0])
    return None


def _find_first_marker(text: str, markers: tuple[str, ...]) -> int:
    positions = [text.find(m) for m in markers if m in text]
    positions = [p for p in positions if p != -1]
    return min(positions) if positions else -1


def _extract_claim_numbers(text: str) -> list[int]:
    match = CLAIM_RE.search(text)
    if not match:
        return []
    raw = match.group(1).replace("至", "-").replace("和", ",").replace("及", ",").replace("，", ",")
    values: list[int] = []
    for part in [item.strip() for item in raw.split(",") if item.strip()]:
        if "-" in part:
            parts = [item.strip() for item in part.split("-", 1)]
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                start, end = int(parts[0]), int(parts[1])
                if start <= end:
                    values.extend(range(start, end + 1))
                continue
        if part.isdigit():
            values.append(int(part))
    result: list[int] = []
    for val in values:
        if val not in result:
            result.append(val)
    return result


def _infer_patent_type(text: str, application_number: str | None = None) -> str | None:
    from_num = infer_patent_type_from_number(application_number)
    if from_num:
        return from_num
    if re.search(r"发明(?:创造|专利)?名称[:：]", text):
        return "发明专利"
    if re.search(r"实用新型名称[:：]", text):
        return "实用新型专利"
    if re.search(r"外观设计名称[:：]|外观设计专利", text):
        return "外观设计专利"
    if re.search(r"专利法第22条|新颖性|创造性", text):
        return "发明专利"
    return None


def _split_body_paragraphs(body_text: str) -> list[str]:
    """正文切分：兼容双换行分段及单换行+序号（1. / 1、 / (1) / （1） / 一、）排版。"""
    pattern = re.compile(
        r"(?:^|\n)\s*(?=(?:[0-9]{1,2}[、.．]|\([0-9]{1,2}\)|（[0-9]{1,2}）|[一二三四五六七八九十]{1,2}[、.．]))"
    )
    numbered_chunks = [p.strip() for p in pattern.split(body_text) if p.strip()]
    if len(numbered_chunks) > 1:
        return numbered_chunks

    return [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]


def parse_office_action_structure(text: str) -> dict[str, Any]:
    """完整解析 OA 通知书结构。"""
    normalized = normalize_extracted_text(text)

    # 去掉附带的检索报告
    main_text = normalized
    trimmed_ignored = None
    for marker in ATTACHMENT_MARKERS:
        pos = normalized.find(marker)
        if pos != -1:
            trimmed_ignored = marker
            main_text = normalized[:pos].strip()
            break

    # 切分封面：确保封面严格截断在第 5 栏之前
    front_text = main_text
    sec_five = re.search(r"(?:^|\n)\s*5\.", main_text)
    sec_six = re.search(r"(?:^|\n)\s*6\.", main_text)
    if sec_five:
        front_text = main_text[:sec_five.start()].strip()
    elif sec_six:
        front_text = main_text[:sec_six.start()].strip()
    else:
        b_pos = _find_first_marker(main_text, BODY_START_MARKERS)
        if b_pos != -1:
            front_text = main_text[:b_pos].strip()

    # 提取著录项目
    notice_title = _extract_first(main_text, [NOTICE_TITLE_RE.pattern])
    raw_app = _extract_first(main_text, [r"申请号[:：]\s*([A-Z0-9./-]+)", r"申请编号[:：]\s*([A-Z0-9./-]+)"])
    app_num = format_application_number(raw_app)

    # 直接给出申请号校验位有效性
    check_digit_valid: bool | None = None
    if app_num:
        clean_digits = re.sub(r"[^0-9X]", "", app_num.upper())
        clean_digits = re.sub(r"^(CN|ZL)", "", clean_digits)
        if len(clean_digits) in {9, 13}:
            main_d = clean_digits[:-1]
            chk_d = clean_digits[-1]
            check_digit_valid = validate_cn_check_digit(main_d, chk_d)

    applicant = _extract_first(main_text, [r"(?:申请人|专利申请人)[:：]\s*(.+)"])
    title = _extract_first(main_text, [r"(?:发明创造名称|发明名称|实用新型名称|名称)[:：]\s*(.+)"])
    mailing_date = _extract_mailing_date(front_text)
    patent_type = _infer_patent_type(main_text, app_num)

    bibliographic = {
        "application_number": app_num,
        "check_digit_valid": check_digit_valid,
        "applicant": applicant,
        "title": title,
        "notice_title": notice_title,
        "mailing_date": mailing_date,
        "patent_type": patent_type,
    }

    # 提取第 5 栏对比文件
    sec_five_text = ""
    s5_match = re.search(r"(?:^|\n)\s*5\.", main_text)
    if s5_match:
        tail = main_text[s5_match.start():]
        s6_match = re.search(r"(?:^|\n)\s*6\.", tail)
        sec_five_text = tail[:s6_match.start()].strip() if s6_match else tail.strip()

    cited_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    norm_app = (app_num or "").replace(" ", "").upper()
    for match in PATENT_ID_RE.finditer(sec_five_text):
        raw = match.group(0).rstrip(".,;:?!)'\"”’").strip()
        doc_id = normalize_patent_number(raw).strip().upper()
        if not doc_id:
            continue
        if norm_app and (doc_id == norm_app or doc_id.replace(".", "") == norm_app.replace(".", "")):
            continue
        if doc_id in seen:
            continue
        seen.add(doc_id)
        cited_docs.append({
            "label": f"对比文件{len(cited_docs) + 1}",
            "document_id": doc_id,
            "role": "prior_art",
            "raw_context": sec_five_text[:240],
        })

    # 提取正文审查意见段落
    body_text = main_text
    search_scope_start = sec_six.end() if sec_six else 0
    b_start = -1
    if search_scope_start > 0:
        pos_list = [
            main_text.find(m, search_scope_start)
            for m in BODY_START_MARKERS
            if main_text.find(m, search_scope_start) != -1
        ]
        b_start = min(pos_list) if pos_list else search_scope_start
    else:
        b_pos = _find_first_marker(main_text, BODY_START_MARKERS)
        if b_pos != -1:
            b_start = b_pos

    if b_start != -1:
        end_positions = [
            main_text.find(m, b_start)
            for m in ("审查员姓名", "审查员：", "审查员:")
            if main_text.find(m, b_start) != -1
        ]
        b_end = min(end_positions) if end_positions else len(main_text)
        body_text = main_text[b_start:b_end].strip()

    paragraphs = _split_body_paragraphs(body_text)
    objections: list[dict[str, Any]] = []
    keywords = ("不具备", "不符合", "缺乏", "不清楚", "未充分公开", "新颖性", "创造性", "单一性", "含糊不清")
    for p in paragraphs:
        if not any(k in p for k in keywords):
            continue
        leg_match = LEGAL_BASIS_RE.search(p)
        c_nums = _extract_claim_numbers(p)
        obj_title = "审查意见"
        if "创造性" in p:
            obj_title = "创造性意见"
        elif "新颖性" in p:
            obj_title = "新颖性意见"
        elif "不清楚" in p or "含糊不清" in p:
            obj_title = "清楚性意见"
        elif "26 条第3 款" in p or "第二十六条第三款" in p:
            obj_title = "公开充分意见"
        elif "26 条第4 款" in p or "第二十六条第四款" in p or "第26条第4款" in p:
            obj_title = "权项支持/清楚性意见"
        objections.append({
            "objection_id": f"OBJ-{len(objections) + 1}",
            "title": obj_title,
            "claim_numbers": c_nums,
            "legal_basis": leg_match.group(0) if leg_match else None,
            "raw_text": p,
        })

    summary = (
        f"已从《{title or '该申请'}》的{notice_title or '审查意见通知书'}中提取基础案件信息，"
        f"识别到 {len(objections)} 条正文审查意见，并在第5栏识别到 {len(cited_docs)} 篇对比文件。"
    )

    source_trace: dict[str, Any] = {
        "mode": "office_action",
        "attachment_ignored": trimmed_ignored,
    }

    return {
        "mode": "office_action",
        "bibliographic_items": bibliographic,
        "objections": objections,
        "cited_documents": cited_docs,
        "summary": summary,
        "source_trace": source_trace,
    }


def parse_free_document_structure(filename: str, text: str, max_limit: int = DEFAULT_MAX_CITATIONS) -> dict[str, Any]:
    """自由文档/文献清单抽取模式。"""
    normalized = normalize_extracted_text(text)

    # 1. 识别并提取带小数点校验位的中国申请号（归入著录项，严禁混入对比文件）
    bibliographic: dict[str, Any] = {}
    app_matches = list(_CN_APP_WITH_DOT_RE.finditer(normalized))
    if app_matches:
        first_app = app_matches[0]
        main_digits = first_app.group(1)
        check_char = first_app.group(2).upper()
        app_num_str = f"{main_digits}.{check_char}"
        is_valid = validate_cn_check_digit(main_digits, check_char)
        bibliographic["application_number"] = app_num_str
        bibliographic["check_digit_valid"] = is_valid

    # 2. 提取对比文件（已自动排除上述申请号）
    raw_ids = extract_patent_ids_free_text(normalized, exclude_application_numbers=True)
    truncated = len(raw_ids) > max_limit
    if truncated:
        raw_ids = raw_ids[:max_limit]

    cited_docs: list[dict[str, Any]] = []
    for idx, pid in enumerate(raw_ids, start=1):
        cited_docs.append({
            "label": f"对比文件{idx}",
            "document_id": pid,
            "role": "prior_art",
            "raw_context": build_citation_context(normalized, pid),
        })

    if bibliographic.get("application_number"):
        summary = (
            f"已从《{filename}》识别到客户申请号 {bibliographic['application_number']} "
            f"及 {len(cited_docs)} 篇对比文件文献号。"
        )
    else:
        summary = f"已从《{filename}》识别到 {len(cited_docs)} 篇专利文献号。"

    if truncated:
        summary += f" 超出上限已截取前 {max_limit} 篇。"

    return {
        "mode": "free_text",
        "bibliographic_items": bibliographic,
        "objections": [],
        "cited_documents": cited_docs,
        "summary": summary,
        "source_trace": {
            "mode": "free_text",
            "truncated": truncated,
        },
    }


def is_likely_office_action(text: str) -> bool:
    """启发式判断文本是否为正式中国专利审查意见通知书。"""
    oa_markers = (
        "审查意见通知书",
        "本通知书是在进行了检索的情况下作出的",
        "本通知书引用下列对比文件",
        "审查的结论性意见",
        "国家知识产权局",
    )
    score = sum(1 for m in oa_markers if m in text)
    return score >= 2 or NOTICE_TITLE_RE.search(text) is not None


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="专利审查意见通知书与资料文档对比文件提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_file", nargs="?", help="待解析的文件路径 (.txt, .md, .docx, .pdf)")
    parser.add_argument("--raw-text", help="直接传入文本字符串（用于测试或管道输入）")
    parser.add_argument("-m", "--mode", choices=["auto", "oa", "free"], default="auto", help="解析模式 (默认: auto)")
    parser.add_argument("--max-citations", type=int, default=DEFAULT_MAX_CITATIONS, help="自由文本模式最大提取数量 (默认: 30)")
    parser.add_argument("-o", "--output", help="输出 JSON 结果文件路径")
    parser.add_argument("--compact", action="store_true", help="紧凑 JSON 输出")

    args = parser.parse_args()

    filename = "input_text"
    if args.input_file:
        file_path = Path(args.input_file)
        if not file_path.exists():
            print(f"错误: 文件未找到: {args.input_file}", file=sys.stderr)
            return 1
        filename = file_path.name
        text = extract_text_from_file(file_path)
    elif args.raw_text:
        text = args.raw_text
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.print_help()
        return 0

    if not text.strip():
        print("错误: 提取到的文本内容为空", file=sys.stderr)
        return 1

    mode = args.mode
    if mode == "auto":
        mode = "oa" if is_likely_office_action(text) else "free"

    if mode == "oa":
        result = parse_office_action_structure(text)
    else:
        result = parse_free_document_structure(filename, text, max_limit=args.max_citations)

    result["file_name"] = filename
    indent = None if args.compact else 2
    output_str = json.dumps(result, ensure_ascii=False, indent=indent)

    if args.output:
        Path(args.output).write_text(output_str, encoding="utf-8")
    else:
        print(output_str)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
