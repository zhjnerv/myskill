#!/usr/bin/env python3
"""独立复算 DOCX 组装报告的输入、输出哈希和证据新鲜度。"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import tempfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from typing import Any
from posixpath import normpath

SCHEMA_ID = "cn-patent-docx-assembly/v2"
RESULT_SCHEMA_ID = "cn-patent-docx-assembly-verification/v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("组装报告含 BOM")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("组装报告顶层必须是对象")
    return value




W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"


def _integer(raw: str | None, label: str, *, level: bool = False) -> int:
    if raw is None or not re.fullmatch(r"[0-9]+", raw):
        raise ValueError(f"{label} 不是非负整数：{raw!r}")
    value = int(raw)
    if level and value > 8:
        raise ValueError(f"{label} 超出编号层级 0—8：{value}")
    return value


def _numbering_style_targets(styles_bytes: bytes | None) -> tuple[dict[str, int], dict[str, int]]:
    """返回编号样式的 styleId / 名称到 numId 的映射。"""
    by_id: dict[str, int] = {}
    by_name: dict[str, int] = {}
    if not styles_bytes:
        return by_id, by_name
    root = ET.fromstring(styles_bytes)
    for style in root.findall(W + "style"):
        if style.get(W + "type") != "numbering":
            continue
        num = style.find(f"{W}pPr/{W}numPr/{W}numId")
        if num is None:
            continue
        nid = _integer(num.get(W + "val"), "编号样式 numId")
        style_id = style.get(W + "styleId")
        name = style.find(W + "name")
        if style_id:
            by_id[style_id] = nid
        if name is not None and name.get(W + "val"):
            by_name[name.get(W + "val")] = nid
    return by_id, by_name


def _parse_final_numbering(
    numbering_bytes: bytes, styles_bytes: bytes | None = None,
) -> dict[int, set[int]]:
    """只接受真实层级定义；startOverride 不能凭空增加层级。

    ``w:numStyleLink`` 本身没有 ``w:lvl``。按 OOXML，这种抽象编号的层级
    来自所链接编号样式的 ``numId``，本地 ``w:lvl`` 不参与解析。
    """
    root = ET.fromstring(numbering_bytes)
    if root.tag != W + "numbering":
        raise ValueError("word/numbering.xml 根节点必须为 w:numbering")
    direct_levels: dict[int, set[int]] = {}
    style_links: dict[int, str] = {}
    for abstract in root.findall(W + "abstractNum"):
        aid = _integer(abstract.get(W + "abstractNumId"), "abstractNumId")
        if aid in direct_levels:
            raise ValueError(f"重复 abstractNumId={aid}")
        link = abstract.find(W + "numStyleLink")
        if link is not None and link.get(W + "val"):
            style_links[aid] = link.get(W + "val")
            direct_levels[aid] = set()
            continue
        levels: set[int] = set()
        for item in abstract.findall(W + "lvl"):
            level = _integer(item.get(W + "ilvl"), "lvl.ilvl", level=True)
            if level in levels:
                raise ValueError(f"abstractNumId={aid} 重复 ilvl={level}")
            levels.add(level)
        direct_levels[aid] = levels
    num_to_abstract: dict[int, int] = {}
    overrides: dict[int, list[tuple[int, bool]]] = {}
    for num in root.findall(W + "num"):
        nid = _integer(num.get(W + "numId"), "numId")
        if nid == 0 or nid in num_to_abstract:
            raise ValueError(f"编号实例 numId 无效或重复：{nid}")
        ref = num.find(W + "abstractNumId")
        aid = _integer(None if ref is None else ref.get(W + "val"), "abstractNumId 引用")
        if aid not in direct_levels:
            raise ValueError(f"numId={nid} 引用了未定义 abstractNumId={aid}")
        seen: set[int] = set()
        parsed_overrides: list[tuple[int, bool]] = []
        for override in num.findall(W + "lvlOverride"):
            level = _integer(override.get(W + "ilvl"), "lvlOverride.ilvl", level=True)
            if level in seen:
                raise ValueError(f"numId={nid} 重复 lvlOverride={level}")
            seen.add(level)
            children = override.findall(W + "lvl")
            if len(children) > 1:
                raise ValueError("lvlOverride 只能包含一个 w:lvl")
            if children:
                child_level = _integer(children[0].get(W + "ilvl"), "lvl.ilvl", level=True)
                if child_level != level:
                    raise ValueError("lvlOverride 与其 w:lvl 的 ilvl 不一致")
            parsed_overrides.append((level, bool(children)))
        num_to_abstract[nid] = aid
        overrides[nid] = parsed_overrides

    by_id, by_name = _numbering_style_targets(styles_bytes)
    resolved: dict[int, set[int]] = {}

    def resolve(nid: int, stack: tuple[int, ...]) -> set[int]:
        if nid in resolved:
            return resolved[nid]
        if nid in stack:
            raise ValueError(f"编号样式链接循环：numId={nid}")
        aid = num_to_abstract[nid]
        link = style_links.get(aid)
        if link is None:
            levels = set(direct_levels[aid])
        else:
            if not styles_bytes:
                raise ValueError(f"abstractNumId={aid} 使用 numStyleLink={link!r}，但缺少 word/styles.xml")
            if link in by_id:
                target = by_id[link]
            elif link in by_name:
                target = by_name[link]
            else:
                raise ValueError(f"abstractNumId={aid} 的 numStyleLink={link!r} 没有对应编号样式")
            if target == 0:
                raise ValueError(f"编号样式 {link!r} 不能使用 numId=0")
            if target not in num_to_abstract:
                raise ValueError(f"编号样式 {link!r} 指向了未定义 numId={target}")
            levels = set(resolve(target, stack + (nid,)))
        for level, has_definition in overrides[nid]:
            if has_definition:
                levels.add(level)
            elif level not in levels:
                raise ValueError(f"numId={nid} 的 lvlOverride={level} 没有真实层级定义")
        resolved[nid] = levels
        return levels

    return {nid: resolve(nid, ()) for nid in num_to_abstract}


def _validate_numbering_references(document_bytes: bytes, numbering: dict[int, set[int]] | None) -> None:
    """检查显式编号引用；numId=0 表示取消继承编号，不引用编号实例。"""
    root = ET.fromstring(document_bytes)
    for numpr in root.findall(".//" + W + "numPr"):
        numid = numpr.find(W + "numId")
        if numid is None:
            # 单独 ilvl 可能继承段落样式；此检查不推断未显式给出的 numId。
            continue
        nid = _integer(numid.get(W + "val"), "段落 numId")
        if nid == 0:
            continue
        if numbering is None:
            raise ValueError("最终 DOCX 缺少或损坏 word/numbering.xml，但存在编号引用")
        levels = numbering.get(nid)
        if levels is None:
            raise ValueError(f"最终 DOCX 引用了未定义的 numId={nid}")
        ilvl = numpr.find(W + "ilvl")
        level = _integer("0" if ilvl is None else ilvl.get(W + "val"), "段落 ilvl", level=True)
        if level not in levels:
            raise ValueError(f"numId={nid} 引用了未定义层级 ilvl={level}")


def _validate_final_numbering(
    document_bytes: bytes,
    numbering_bytes: bytes | None,
    styles_bytes: bytes | None = None,
) -> None:
    numbering = None if numbering_bytes is None else _parse_final_numbering(numbering_bytes, styles_bytes)
    _validate_numbering_references(document_bytes, numbering)


def check_docx_package(path: Path, errors: list[dict[str, str]]) -> None:
    """检查 Word 会在打开阶段强制修复的最小 OOXML 结构问题。"""
    try:
        with ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                errors.append({"code": "DOCX-PACKAGE-CRC", "message": f"DOCX ZIP 成员 CRC 损坏：{bad_member}"})
                return
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/_rels/document.xml.rels"}
            missing = sorted(required - set(archive.namelist()))
            if missing:
                errors.append({"code": "DOCX-PACKAGE-MISSING", "message": f"DOCX 缺少必需成员：{missing}"})
                return
            names = set(archive.namelist())
            document_bytes = archive.read("word/document.xml")
            numbering_bytes = archive.read("word/numbering.xml") if "word/numbering.xml" in names else None
            styles_bytes = archive.read("word/styles.xml") if "word/styles.xml" in names else None
    except BadZipFile:
        errors.append({"code": "DOCX-PACKAGE-ZIP", "message": "输出文件不是有效 DOCX ZIP 包"})
        return
    try:
        document_text = document_bytes.decode("utf-8")
        ET.fromstring(document_bytes)
    except (UnicodeDecodeError, ET.ParseError, ValueError) as exc:
        errors.append({"code": "DOCX-PACKAGE-XML", "message": f"word/document.xml 不是有效 XML：{exc}"})
        return
    try:
        _validate_final_numbering(document_bytes, numbering_bytes, styles_bytes)
    except (ET.ParseError, ValueError) as exc:
        errors.append({"code": "DOCX-PACKAGE-NUMBERING", "message": str(exc)})
        return
    root_match = re.search(r"<w:document\b[^>]*>", document_text)
    if root_match is None:
        errors.append({"code": "DOCX-PACKAGE-ROOT", "message": "word/document.xml 缺少 w:document 根节点"})
        return
    root_tag = root_match.group(0)
    declared = set(re.findall(r"xmlns:([A-Za-z_][\w.-]*)=\"[^\"]+\"", root_tag))
    ignorable_match = re.search(r"mc:Ignorable=\"([^\"]*)\"", root_tag)
    ignored = set(ignorable_match.group(1).split()) if ignorable_match else set()
    missing_ignored = sorted(ignored - declared)
    if missing_ignored:
        errors.append({
            "code": "DOCX-PACKAGE-IGNORABLE-NS",
            "message": f"mc:Ignorable 引用了未声明的命名空间前缀：{missing_ignored}；Microsoft Word 会提示恢复文档",
        })

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "{" + A_NS + "}"
R_EMBED = "{" + R_NS + "}embed"
R_ID = "{" + R_NS + "}id"
ABSTRACT_FIGURE_RE = re.compile(r"摘要附图：图\s*(\d+)")
CAPTION_RE = re.compile(r"图\s*(\d+)\s*$")
PACKAGE_UNREADABLE = {"DOCX-PACKAGE-ZIP", "DOCX-PACKAGE-CRC", "DOCX-PACKAGE-MISSING"}


def package_is_unreadable(errors: list[dict[str, str]]) -> bool:
    """坏包之后不再依赖 ZIP 成员内容做后续检查。"""
    return any(item.get("code") in PACKAGE_UNREADABLE for item in errors)


def parse_abstract_figure_number(text: str) -> int | None:
    match = ABSTRACT_FIGURE_RE.search(text)
    if match is None:
        return None
    return int(match.group(1))


def _rels_map(rels_xml: bytes) -> dict[str, str]:
    root = ET.fromstring(rels_xml)
    found: dict[str, str] = {}
    for rel in root:
        rel_id = rel.get("Id")
        target = rel.get("Target")
        if rel_id and target:
            found[rel_id] = target
    return found


def _word_target(target: str) -> str:
    """把 document.xml.rels 的相对目标解析成 ZIP 内路径。"""
    raw = normpath(str(Path("word") / target)).replace("\\", "/")
    if raw == ".." or raw.startswith("../"):
        raise ValueError(f"DOCX 关系目标越出 word 目录：{target}")
    return raw


def _header_text(archive: ZipFile, rels: dict[str, str], sect: ET.Element) -> str:
    for ref in sect.findall(W + "headerReference"):
        if ref.get(W + "type") not in {None, "default"}:
            continue
        target = rels.get(ref.get(R_ID) or "")
        if not target:
            continue
        name = _word_target(target)
        if name not in set(archive.namelist()):
            continue
        return _document_plain_text(archive.read(name).decode("utf-8")).strip()
    return ""


def _section_blocks(body: ET.Element) -> list[tuple[ET.Element | None, list[ET.Element]]]:
    """按分节符切分正文。段落内 sectPr 结束当前节，body 直接子级 sectPr 结束最后一节。"""
    sections: list[tuple[ET.Element | None, list[ET.Element]]] = []
    current: list[ET.Element] = []
    for child in list(body):
        if child.tag == W + "sectPr":
            sections.append((child, current))
            current = []
            continue
        current.append(child)
        ppr = child.find(W + "pPr")
        sect = None if ppr is None else ppr.find(W + "sectPr")
        if sect is not None:
            sections.append((sect, current))
            current = []
    if current:
        sections.append((None, current))
    return sections


def _block_text(block: ET.Element) -> str:
    return "".join(part.text or "" for part in block.iter(W + "t")).strip()


def _block_embeds(block: ET.Element) -> list[str]:
    return [blip.get(R_EMBED) or "" for blip in block.iter(A + "blip")]


def check_embedded_figures(
    path: Path,
    figures: dict[int, str],
    abstract_figure: int | None,
    errors: list[dict[str, str]],
    *,
    code: str = "DOCX-EMBEDDED",
) -> None:
    """沿文档显示顺序读取实际媒体字节。同图允许复用，不能只比较媒体文件数。"""
    if not figures:
        return
    if abstract_figure is None:
        errors.append({"code": code, "message": "有附图时必须能确定摘要附图图号"})
        return
    if abstract_figure not in figures:
        errors.append({"code": code, "message": f"摘要附图图号不在附图集合中：图{abstract_figure}"})
        return
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names or "word/_rels/document.xml.rels" not in names:
                errors.append({"code": code, "message": "DOCX 缺少 document.xml 或文档关系，无法核对内嵌图片"})
                return
            document = ET.fromstring(archive.read("word/document.xml"))
            rels = _rels_map(archive.read("word/_rels/document.xml.rels"))
            body = document.find(W + "body")
            if body is None:
                errors.append({"code": code, "message": "word/document.xml 缺少 w:body"})
                return
            digests: dict[str, str | None] = {}

            def media_digest(rel_id: str) -> str | None:
                if rel_id in digests:
                    return digests[rel_id]
                target = rels.get(rel_id)
                if not rel_id or target is None:
                    errors.append({"code": code, "message": f"图片引用 {rel_id or '空'} 没有对应关系"})
                    digests[rel_id] = None
                    return None
                try:
                    member = _word_target(target)
                except ValueError as exc:
                    errors.append({"code": code, "message": str(exc)})
                    digests[rel_id] = None
                    return None
                if member not in names:
                    errors.append({"code": code, "message": f"图片关系指向缺失的媒体：{member}"})
                    digests[rel_id] = None
                    return None
                digests[rel_id] = hashlib.sha256(archive.read(member)).hexdigest()
                return digests[rel_id]

            parsed: list[tuple[str, list[tuple[str, list[str | None]]]]] = []
            for sect, blocks in _section_blocks(body):
                header = "" if sect is None else _header_text(archive, rels, sect)
                rendered: list[tuple[str, list[str | None]]] = []
                for block in blocks:
                    rendered.append((_block_text(block), [media_digest(rel_id) for rel_id in _block_embeds(block)]))
                parsed.append((header, rendered))
    except BadZipFile:
        errors.append({"code": "DOCX-PACKAGE-ZIP", "message": "输出文件不是有效 DOCX ZIP 包，已停止读取内嵌图片"})
        return
    except (OSError, UnicodeError, ET.ParseError, KeyError, ValueError) as exc:
        errors.append({"code": code, "message": f"无法读取 DOCX 内嵌图片：{type(exc).__name__}: {exc}"})
        return

    spec_sections = [blocks for header, blocks in parsed if header == "说明书附图"]
    abstract_sections = [blocks for header, blocks in parsed if header == "摘要附图"]
    if len(spec_sections) != 1 or len(abstract_sections) != 1:
        errors.append({"code": code, "message": "DOCX 的说明书附图与摘要附图分节必须且只能各有一个，不能遗漏或重复"})
        return
    spec_blocks = spec_sections[0]
    abstract_blocks = abstract_sections[0]
    for header, blocks in parsed:
        if header not in {"说明书附图", "摘要附图"} and any(embeds for _text, embeds in blocks):
            errors.append({"code": code, "message": f"{header or '未命名分节'} 出现了不应显示的内嵌图片"})

    pairs: list[tuple[int, str | None]] = []
    pending: list[str | None] = []
    for text, embeds in spec_blocks:
        caption = CAPTION_RE.fullmatch(text)
        if embeds:
            if pending:
                errors.append({"code": code, "message": "说明书附图中有图片缺少紧随的图号"})
                pending = []
            pending.extend(embeds)
            continue
        if caption:
            if len(pending) != 1:
                errors.append({"code": code, "message": f"图号“{text}”没有唯一对应的内嵌图片"})
            else:
                pairs.append((int(caption.group(1)), pending[0]))
            pending = []
            continue
        if text and pending:
            errors.append({"code": code, "message": f"图号之前出现了无法配对的文字：{text[:40]}"})
    if pending:
        errors.append({"code": code, "message": "说明书附图末尾的图片没有图号"})

    shown_numbers = [number for number, _digest in pairs]
    if shown_numbers != sorted(figures):
        errors.append({
            "code": code,
            "message": f"说明书附图的图号顺序与当前附图不一致：文档={shown_numbers}，当前={sorted(figures)}",
        })
    for number, digest in pairs:
        if digest is None or digest != figures.get(number):
            errors.append({"code": code, "message": f"图{number} 实际显示的图片不是当前最终 PNG"})

    abstract_digests = [digest for _text, embeds in abstract_blocks for digest in embeds if digest is not None]
    abstract_slots = [digest for _text, embeds in abstract_blocks for digest in embeds]
    if len(abstract_slots) != 1 or len(abstract_digests) != 1:
        errors.append({"code": code, "message": f"摘要附图应有且仅有一幅可显示图片，当前为 {len(abstract_slots)} 幅"})
    elif abstract_digests[0] != figures[abstract_figure]:
        errors.append({"code": code, "message": f"摘要附图实际字节不是图{abstract_figure} 的当前最终 PNG"})


def _document_plain_text(document_xml: str) -> str:
    parts = re.findall(r"<w:t\b[^>]*>(.*?)</w:t>", document_xml, flags=re.DOTALL)
    return "".join(html.unescape(part) for part in parts)


def check_pending_marks(path: Path, copy_kind: str, pending_marks: list | None, errors: list[dict[str, str]]) -> None:
    if pending_marks is None:
        pending_marks = []
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            document_text = archive.read("word/document.xml").decode("utf-8") if "word/document.xml" in names else ""
            core_text = archive.read("docProps/core.xml").decode("utf-8") if "docProps/core.xml" in names else ""
    except BadZipFile:
        if not any(item.get("code") == "DOCX-PACKAGE-ZIP" for item in errors):
            errors.append({"code": "DOCX-PACKAGE-ZIP", "message": "输出文件不是有效 DOCX ZIP 包，已停止检查待决标记"})
        return
    except (OSError, UnicodeError, KeyError):
        return

    document_plain = _document_plain_text(document_text)
    title_match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", core_text, re.DOTALL)
    core_title = html.unescape(title_match.group(1)) if title_match else ""
    if "【待决" in core_title:
        errors.append({"code": "DOCX-PENDING-MARKS", "message": "核心属性标题不得保留待决标记"})

    if copy_kind == "submission":
        if "【待决" in document_plain:
            errors.append({"code": "DOCX-PENDING-MARKS", "message": "提交副本存在残缺待决标记"})
        if re.search(r'<w:highlight[^>]*w:val="yellow"[^>]*>', document_text):
            errors.append({"code": "DOCX-PENDING-MARKS", "message": "提交副本存在黄色高亮"})
    elif copy_kind == "review":
        for pm in pending_marks:
            if not isinstance(pm, dict):
                continue
            question = pm.get("question")
            if isinstance(question, str) and question.strip():
                missing: list[str] = []
                if question not in document_plain:
                    missing.append("问题")
                adopted = pm.get("adopted_default")
                if not isinstance(adopted, str) or not adopted.strip() or adopted not in document_plain:
                    missing.append("当前稿做法")
                options = pm.get("options")
                if not isinstance(options, list) or not options:
                    missing.append("备选")
                else:
                    for option in options:
                        if not isinstance(option, str) or not option.strip() or option not in document_plain:
                            missing.append("备选")
                            break
                if "【/待决】" not in document_plain:
                    missing.append("结束标记")
                if missing:
                    label = pm.get("id") or "未编号"
                    errors.append({
                        "code": "DOCX-PENDING-MARKS",
                        "message": f"客户审稿版的待决说明不完整（{label}）：缺少{'、'.join(dict.fromkeys(missing))}",
                    })
                continue
            pm_id = pm.get("id")
            if pm_id and f"【待决-{pm_id}】" not in document_plain:
                errors.append({"code": "DOCX-PENDING-MARKS", "message": f"客户审稿版丢失待决标记 {pm_id}"})


def verify(report_path: Path) -> dict[str, Any]:
    report_path = report_path.resolve()
    report = load_json(report_path)
    base_dir = report_path.parent
    errors: list[dict[str, str]] = []

    def resolve_evidence_path(path_value: Any) -> Path | None:
        if not isinstance(path_value, str) or not path_value:
            return None
        raw = Path(path_value)
        return (raw if raw.is_absolute() else base_dir / raw).resolve()

    def check_file(path_value: Any, expected: Any, artifact_id: str) -> None:
        if not isinstance(path_value, str) or not path_value:
            errors.append({"code": "DOCX-EVIDENCE-PATH", "message": f"{artifact_id} 缺少路径"})
            return
        path = resolve_evidence_path(path_value)
        if path is None:
            errors.append({"code": "DOCX-EVIDENCE-PATH", "message": f"{artifact_id} 缺少路径"})
            return
        if not path.is_file():
            errors.append({"code": "DOCX-EVIDENCE-MISSING", "message": f"{artifact_id} 文件不存在：{path}"})
            return
        actual = sha256(path)
        if expected != actual:
            errors.append({"code": "DOCX-EVIDENCE-STALE", "message": f"{artifact_id} 哈希与当前文件不一致"})

    if report.get("schema") != SCHEMA_ID:
        errors.append({"code": "DOCX-EVIDENCE-SCHEMA", "message": f"schema 必须为 {SCHEMA_ID}"})
    if report.get("status") not in {"STRUCTURE_VERIFIED", "STRUCTURE_VERIFIED_VISUAL_REVIEW_PENDING"}:
        errors.append({"code": "DOCX-EVIDENCE-STATUS", "message": "组装报告状态无效"})
    check_file(report.get("output"), report.get("output_sha256"), "output_docx")
    output_value = report.get("output")
    output_path = resolve_evidence_path(output_value)
    output_readable = False
    if output_path is not None and output_path.is_file():
        check_docx_package(output_path, errors)
        output_readable = not package_is_unreadable(errors)
        copy_kind = report.get("copy_kind")
        if copy_kind in {"review", "submission"} and output_readable:
            check_pending_marks(output_path, copy_kind, report.get("pending_marks"), errors)
    inputs = report.get("inputs") or {}
    check_file(inputs.get("template"), inputs.get("template_sha256"), "template")
    artifacts = inputs.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append({"code": "DOCX-EVIDENCE-INPUTS", "message": "缺少逐文件 inputs.artifacts"})
        artifacts = []
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            errors.append({"code": "DOCX-EVIDENCE-INPUTS", "message": "inputs.artifacts 含非对象项"})
            continue
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen:
            errors.append({"code": "DOCX-EVIDENCE-INPUTS", "message": f"artifact_id 缺失或重复：{artifact_id}"})
            continue
        seen.add(artifact_id)
        check_file(item.get("path"), item.get("sha256"), artifact_id)
    for required in {"claims", "specification", "abstract", "figure_index"}:
        if required not in seen:
            errors.append({"code": "DOCX-EVIDENCE-INPUTS", "message": f"缺少必需输入：{required}"})

    figure_hashes: dict[int, str] = {}
    if output_readable and output_path is not None:
        for artifact_id in sorted(seen):
            match = re.fullmatch(r"figure_(\d+)", artifact_id)
            if match is None:
                continue
            item = next(entry for entry in artifacts if isinstance(entry, dict) and entry.get("artifact_id") == artifact_id)
            figure_path = resolve_evidence_path(item.get("path"))
            if figure_path is None or not figure_path.is_file():
                continue
            figure_hashes[int(match.group(1))] = sha256(figure_path)
        if figure_hashes:
            abstract_path = None
            abstract_item = next((entry for entry in artifacts if isinstance(entry, dict) and entry.get("artifact_id") == "abstract"), None)
            if abstract_item is not None:
                abstract_path = resolve_evidence_path(abstract_item.get("path"))
            abstract_number = None
            if abstract_path is not None and abstract_path.is_file():
                abstract_number = parse_abstract_figure_number(abstract_path.read_text(encoding="utf-8", errors="replace"))
            reported = report.get("abstract_figure")
            if isinstance(reported, int) and not isinstance(reported, bool):
                if abstract_number is not None and reported != abstract_number:
                    errors.append({"code": "DOCX-EMBEDDED", "message": f"组装报告摘要附图图{reported} 与摘要正文图{abstract_number} 不一致"})
                abstract_number = reported if abstract_number is None else abstract_number
            check_embedded_figures(output_path, figure_hashes, abstract_number, errors)

    return {
        "schema_id": RESULT_SCHEMA_ID,
        "report": str(report_path),
        "report_sha256": sha256(report_path),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "evidence_scope": {
            "proves": [] if errors else ["组装报告绑定的模板、源文件、图片和输出 DOCX 当前仍为同一字节版本", "有附图时，说明书附图图号顺序和摘要附图引用显示的是当前图片字节"],
            "does_not_prove": ["DOCX 法律内容正确", "未执行的视觉复核已经完成"],
        },
    }


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.report.resolve())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, BadZipFile, ET.ParseError) as exc:
        result = {
            "schema_id": RESULT_SCHEMA_ID,
            "status": "FAIL",
            "errors": [{"code": "DOCX-EVIDENCE-INPUT", "message": f"{type(exc).__name__}: {exc}"}],
            "evidence_scope": {
                "proves": [],
                "does_not_prove": ["损坏或不完整的输入没有通过组装复验"],
            },
        }
    payload = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    if args.output:
        write_atomic(args.output.resolve(), payload)
    else:
        print(payload.decode("utf-8"), end="")
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
