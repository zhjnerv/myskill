#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页眉页脚模板注入器（letterhead）。

把模板 DOCX 的页眉/页脚（含首页 first / 后续页 default 两套差异）搬到目标
DOCX 上，只动页眉页脚相关的内容：

- word/header*.xml、word/footer*.xml 部件本体；
- 这些部件的 .rels 与引用到的媒体文件（图片等）；
- 被页眉页脚引用的样式定义（含 basedOn/link 闭包）；
- 目标 sectPr 里的 header/footer 距离与 titlePg（首页不同页眉页脚的开关）。

正文、正文字体、段落、标题、表格等一律保持目标文档原样——这是本模块与
md2word 的 --template（整份模板当基底）的关键区别。

用法：
    from letterhead import apply_letterhead
    apply_letterhead("out.docx", "斯可睿抬头.docx")
"""

from __future__ import annotations

import os
import posixpath
import re
import tempfile
import zipfile

# ---------------------------------------------------------------- 常量与正则

_HDR_FTR_REF_RE = re.compile(r"<w:(header|footer)Reference\b[^>]*/>")
_SECTPR_RE = re.compile(r"<w:sectPr\b.*?</w:sectPr>", re.S)
_REL_RE = re.compile(r"<Relationship\b[^>]*/>")
_TITLEPG_RE = re.compile(r"<w:titlePg\b[^>]*/>")
_PGMAR_RE = re.compile(r"<w:pgMar\b[^>]*/>")
_STYLE_REF_RE = re.compile(r"<w:(?:pStyle|rStyle|tblStyle)\s+w:val=\"([^\"]+)\"")
_STYLE_DEF_RE = re.compile(r"<w:style\b.*?</w:style>", re.S)
_STYLE_ID_RE = re.compile(r"w:styleId=\"([^\"]+)\"")
_STYLE_NAME_RE = re.compile(r"<w:name\s+w:val=\"([^\"]+)\"")
_BASED_ON_RE = re.compile(r"<w:basedOn\s+w:val=\"([^\"]+)\"\s*/>")
_LINK_RE = re.compile(r"<w:link\s+w:val=\"([^\"]+)\"\s*/>")
_RFONTS_RE = re.compile(r"<w:rFonts\b[^>]*/>")
_RPR_OPEN_RE = re.compile(r"<w:rPr>")

# pPr 子元素顺序（OOXML 序列，插入 spacing 时需要）
_P_PR_ORDER = [
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
    "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
    "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
    "w:sectPr", "w:pPrChange",
]

# 目标文档（python-docx 基底）的 docDefaults 通常带 after=200/line=276 的间距，
# 模板没有的话必须显式写回 Word 默认值，否则页眉页脚会被撑高。
_DEFAULT_SPACING = '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'

_IMAGE_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
    "svg": "image/svg+xml",
}


# ---------------------------------------------------------------- 基础工具

def _read_zip(path):
    """读取 docx，返回 (有序名列表, 名字->bytes 字典)。"""
    with zipfile.ZipFile(path) as zf:
        names = list(zf.namelist())
        data = {name: zf.read(name) for name in names}
    return names, data


def _text(data, name):
    return data[name].decode("utf-8")


def _resolve_part(base_part, target):
    """把 OPC 关系里的 Target 解析成包内绝对部件名（如 word/header1.xml）。"""
    if target.startswith("/"):
        return target.lstrip("/")
    base_dir = posixpath.dirname(base_part)
    return posixpath.normpath(posixpath.join(base_dir, target))


def _doc_rels(data):
    """解析 word/_rels/document.xml.rels -> {rId: 部件名或外部目标}。"""
    name = "word/_rels/document.xml.rels"
    rels = {}
    if name not in data:
        return rels
    xml = _text(data, name)
    for m in _REL_RE.finditer(xml):
        el = m.group(0)
        rid = re.search(r'Id="([^"]+)"', el)
        target = re.search(r'Target="([^"]+)"', el)
        mode = re.search(r'TargetMode="([^"]+)"', el)
        if not rid or not target:
            continue
        if mode and mode.group(1) == "External":
            rels[rid.group(1)] = target.group(1)
        else:
            rels[rid.group(1)] = _resolve_part("word/document.xml", target.group(1))
    return rels


def _body_sectpr(document_xml):
    """取文档级（body 末尾）sectPr；没有页眉页脚引用时回退到最后一个 sectPr。"""
    sectprs = _SECTPR_RE.findall(document_xml)
    if not sectprs:
        raise ValueError("模板 document.xml 里没有 sectPr")
    for sect in reversed(sectprs):
        if _HDR_FTR_REF_RE.search(sect):
            return sect
    return sectprs[-1]


def _sectpr_refs(sect_xml, rels):
    """解析 sectPr 中的页眉页脚引用 -> {'header:first': 'word/header2.xml', ...}。"""
    out = {}
    for m in _HDR_FTR_REF_RE.finditer(sect_xml):
        el = m.group(0)
        kind = m.group(1)
        typ = re.search(r'w:type="([^"]+)"', el)
        rid = re.search(r'r:id="([^"]+)"', el)
        if not rid:
            continue
        typ = typ.group(1) if typ else "default"
        part = rels.get(rid.group(1))
        if part and not part.startswith("http"):
            out[f"{kind}:{typ}"] = part
    return out


def _attr(el, attr):
    m = re.search(attr + r'="([^"]+)"', el)
    return m.group(1) if m else None


def _push_xml(xml, new_content, tag):
    """把 new_content 插到 </tag> 前（tag 含前缀，如 w:styles）。"""
    closing = f"</{tag}>"
    idx = xml.rfind(closing)
    if idx < 0:
        raise ValueError(f"XML 里找不到 {closing}")
    return xml[:idx] + new_content + xml[idx:]


# ---------------------------------------------------------------- 样式闭包

def _parse_styles(styles_xml):
    """解析 styles.xml -> {id: {'name', 'xml', 'basedOn', 'link'}}。"""
    out = {}
    for m in _STYLE_DEF_RE.finditer(styles_xml):
        el = m.group(0)
        sid_m = _STYLE_ID_RE.search(el)
        if not sid_m:
            continue
        type_m = re.search(r'w:type="([^"]+)"', el)
        name_m = _STYLE_NAME_RE.search(el)
        based_m = _BASED_ON_RE.search(el)
        link_m = _LINK_RE.search(el)
        out[sid_m.group(1)] = {
            "type": type_m.group(1) if type_m else None,
            "name": name_m.group(1) if name_m else None,
            "xml": el,
            "basedOn": based_m.group(1) if based_m else None,
            "link": link_m.group(1) if link_m else None,
        }
    return out


def _collect_style_closure(ref_ids, src_styles):
    """按 basedOn/link 闭包收集需要的样式 id（保持引用顺序）。"""
    ordered, seen = [], set()
    queue = list(ref_ids)
    while queue:
        sid = queue.pop(0)
        if sid in seen or sid not in src_styles:
            continue
        seen.add(sid)
        ordered.append(sid)
        for nxt in (src_styles[sid]["basedOn"], src_styles[sid]["link"]):
            if nxt and nxt not in seen:
                queue.append(nxt)
    return ordered


def _effective_rfonts(sid, src_styles, depth=0):
    """沿 basedOn 链找样式继承到的 rFonts 元素字符串。"""
    if not sid or sid not in src_styles or depth > 10:
        return None
    st = src_styles[sid]
    m = _RFONTS_RE.search(st["xml"])
    if m:
        return m.group(0)
    return _effective_rfonts(st["basedOn"], src_styles, depth + 1)


def _materialize_rfonts(style_xml, rfonts):
    """把继承来的 rFonts 写进样式自身 rPr，避免基底样式换成目标 Normal 后字体漂移。"""
    if not rfonts or _RFONTS_RE.search(style_xml):
        return style_xml
    if _RPR_OPEN_RE.search(style_xml):
        return _RPR_OPEN_RE.sub("<w:rPr>" + rfonts, style_xml, count=1)
    return style_xml.replace("</w:style>", "<w:rPr>" + rfonts + "</w:rPr></w:style>")


def _effective_spacing(sid, src_styles, depth=0):
    """沿 basedOn 链找模板样式链上的 spacing；模板没写就返回 None。"""
    if not sid or sid not in src_styles or depth > 10:
        return None
    st = src_styles[sid]
    m = re.search(r"<w:spacing\b[^>]*/>", st["xml"])
    if m:
        return m.group(0)
    return _effective_spacing(st["basedOn"], src_styles, depth + 1)


def _insert_into_pPr(p_pr_xml, element, tag):
    """按 OOXML 顺序把 element 插进 pPr（spacing 要排在 snapToGrid 之后、ind/jc 之前）。"""
    order = _P_PR_ORDER.index(tag)
    for other in _P_PR_ORDER[order + 1:]:
        m = re.search("<" + re.escape(other) + r"(?=[\s/>])", p_pr_xml)
        if m:
            return p_pr_xml[:m.start()] + element + p_pr_xml[m.start():]
    return p_pr_xml.replace("</w:pPr>", element + "</w:pPr>", 1)


def _materialize_spacing(style_xml, spacing):
    """把有效 spacing 写进样式自身，挡住目标 docDefaults 的段后距/行距。"""
    if re.search(r"<w:spacing\b", style_xml):
        return style_xml
    m = re.search(r"<w:pPr>.*?</w:pPr>", style_xml, re.S)
    if m:
        return style_xml.replace(m.group(0), _insert_into_pPr(m.group(0), spacing, "w:spacing"), 1)
    return style_xml.replace("</w:style>", "<w:pPr>" + spacing + "</w:pPr></w:style>")


def _remap_style_refs(style_xml, src_styles, dst_by_id, dst_by_name, copied_ids):
    """把 basedOn/link 引用改写到目标已存在（或本次一并复制）的样式 id。"""

    def fix(match, tag):
        ref = match.group(1)
        if ref in copied_ids or ref in dst_by_id:
            return match.group(0)
        name = src_styles.get(ref, {}).get("name")
        if name and name in dst_by_name:
            return f'<w:{tag} w:val="{dst_by_name[name]}"/>'
        return ""  # 目标里找不到同名样式：去掉引用，样式自身属性仍在

    style_xml = _BASED_ON_RE.sub(lambda m: fix(m, "basedOn"), style_xml)
    return _LINK_RE.sub(lambda m: fix(m, "link"), style_xml)


def _apply_styles(tgt_styles_xml, src_styles_xml, copied_parts):
    """把被页眉页脚引用的样式闭包并入目标 styles.xml，返回 (新 XML, 复制的 id 列表)。"""
    src_styles = _parse_styles(src_styles_xml)
    dst_styles = _parse_styles(tgt_styles_xml)
    dst_by_id = set(dst_styles)
    dst_by_name = {st["name"]: sid for sid, st in dst_styles.items() if st["name"]}

    ref_ids = []
    for xml in copied_parts:
        for m in _STYLE_REF_RE.finditer(xml):
            sid = m.group(1)
            if sid not in ref_ids:
                ref_ids.append(sid)

    closure = _collect_style_closure(ref_ids, src_styles)
    to_copy = []
    for sid in closure:
        if sid in dst_by_id:
            continue
        # 直接引用的样式必须带过来；只是被继承的基底样式如果目标已有同名实现，
        # 就用目标的（后面 _remap_style_refs 会把 basedOn/link 指过去）。
        if sid not in ref_ids:
            name = src_styles.get(sid, {}).get("name")
            if name and name in dst_by_name:
                continue
        to_copy.append(sid)
    copied_ids = set(to_copy) | dst_by_id

    additions = []
    for sid in to_copy:
        st = src_styles[sid]
        xml = _materialize_rfonts(st["xml"], _effective_rfonts(st["basedOn"], src_styles))
        if st.get("type") == "paragraph":
            spacing = _effective_spacing(st["basedOn"], src_styles) or _DEFAULT_SPACING
            xml = _materialize_spacing(xml, spacing)
        xml = _remap_style_refs(xml, src_styles, dst_by_id, dst_by_name, copied_ids)
        # 样式本体不携带默认标记，避免目标里出现第二个默认样式
        xml = xml.replace(' w:default="1"', "").replace(' w:default="true"', "")
        additions.append(xml)

    if not additions:
        return tgt_styles_xml, []
    return _push_xml(tgt_styles_xml, "".join(additions), "w:styles"), to_copy


# ---------------------------------------------------------------- 部件搬运

def _copy_part_relationships(src_part, tgt_part, src_data, tgt_data, added, media_cache, counter):
    """复制模板部件（src_part）的 .rels 与内部目标（媒体等）到目标部件（tgt_part）。

    注意两端部件名可能不同（例如模板 header2.xml 对应目标 header1.xml），
    源 rels 必须按模板部件名查找。

    返回 (新的 .rels 内容或 None, {旧 rId: 新 rId})；重编号映射由调用方
    回写到部件 XML 的 r:embed/r:link/r:id 引用上。
    """
    src_rels_name = f"word/_rels/{posixpath.basename(src_part)}.rels"
    tgt_rels_name = f"word/_rels/{posixpath.basename(tgt_part)}.rels"
    if src_rels_name not in src_data:
        return None, {}

    src_rels_xml = _text(src_data, src_rels_name)
    tgt_rels_xml = _text(tgt_data, tgt_rels_name) if tgt_rels_name in tgt_data else None
    used_ids = set(re.findall(r'Id="([^"]+)"', tgt_rels_xml or ""))

    new_rels, id_map = [], {}
    for m in _REL_RE.finditer(src_rels_xml):
        el = m.group(0)
        rid = _attr(el, "Id")
        target = _attr(el, "Target")
        mode = _attr(el, "TargetMode")
        if not rid or not target:
            continue
        if mode == "External":
            new_rels.append(el)
            continue
        media_part = _resolve_part(src_part, target)
        if media_part not in src_data:
            continue
        ext = posixpath.splitext(media_part)[1]
        if media_part in media_cache:
            new_target = media_cache[media_part]
        else:
            counter[0] += 1
            new_target = f"media/letterhead_{counter[0]}{ext}"
            added[f"word/{new_target}"] = src_data[media_part]
            media_cache[media_part] = new_target
        new_rid = rid
        if new_rid in used_ids:
            while True:
                counter[0] += 1
                candidate = f"rIdLetH{counter[0]}"
                if candidate not in used_ids:
                    new_rid = candidate
                    break
        if new_rid != rid:
            id_map[rid] = new_rid
            el = el.replace(f'Id="{rid}"', f'Id="{new_rid}"')
        el = el.replace(f'Target="{target}"', f'Target="{new_target}"')
        used_ids.add(new_rid)
        new_rels.append(el)

    if not new_rels:
        return None, id_map
    rels_body = "".join(new_rels)
    if tgt_rels_xml:
        return _push_xml(tgt_rels_xml, rels_body, "Relationships"), id_map
    header = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')
    return header + rels_body + "</Relationships>", id_map


def _rewrite_rel_refs(part_xml, id_map):
    """把部件 XML 里对重编号 rId 的引用改成新 id。"""
    for old, new in id_map.items():
        for attr in ("r:embed", "r:link", "r:id", "r:href"):
            part_xml = part_xml.replace(f'{attr}="{old}"', f'{attr}="{new}"')
    return part_xml


def _ensure_content_types(ct_xml, part_names, added):
    """补 [Content_Types].xml：页眉页脚 Override 与媒体 Default。"""
    overrides = (
        ("header", "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"),
        ("footer", "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"),
    )
    additions = []
    for part in part_names:
        base = posixpath.basename(part)
        for prefix, content_type in overrides:
            if base.startswith(prefix):
                if f'PartName="/{part}"' not in ct_xml:
                    additions.append(f'<Override PartName="/{part}" ContentType="{content_type}"/>')
                break
    exts = {posixpath.splitext(name)[1].lstrip(".").lower() for name in added}
    for ext in sorted(exts):
        if not ext:
            continue
        if f'Extension="{ext}"' not in ct_xml:
            ctype = _IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream")
            additions.append(f'<Default Extension="{ext}" ContentType="{ctype}"/>')
    if not additions:
        return ct_xml
    return _push_xml(ct_xml, "".join(additions), "Types")


def _patch_sectpr(sect_xml, dist_header, dist_footer, add_titlepg):
    """给 sectPr 补 titlePg，并对齐 header/footer 距离（只动这两处）。"""
    if add_titlepg and not _TITLEPG_RE.search(sect_xml):
        if "<w:docGrid" in sect_xml:
            sect_xml = sect_xml.replace("<w:docGrid", "<w:titlePg/><w:docGrid", 1)
        else:
            sect_xml = sect_xml.replace("</w:sectPr>", "<w:titlePg/></w:sectPr>", 1)

    m = _PGMAR_RE.search(sect_xml)
    if m:
        pgmar = m.group(0)
        new_pgmar = pgmar
        for attr, value in (("w:header", dist_header), ("w:footer", dist_footer)):
            if value is None:
                continue
            if f"{attr}=" in new_pgmar:
                new_pgmar = re.sub(attr + r'="[^"]*"', f'{attr}="{value}"', new_pgmar)
            else:
                new_pgmar = new_pgmar.replace("/>", f' {attr}="{value}"/>')
        if new_pgmar != pgmar:
            sect_xml = sect_xml.replace(pgmar, new_pgmar, 1)
    return sect_xml


def _replace_with_retry(src, dst, attempts=6, delay=0.25):
    """Windows 上新建的 docx 可能被安全软件短暂占用，替换时带退避重试。"""
    import time

    last = None
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:  # 被占用：等一会儿再试
            last = exc
            time.sleep(delay * (i + 1))
    raise last


# ---------------------------------------------------------------- 主入口

def apply_letterhead(docx_path, template_path):
    """把 template_path 的页眉/页脚套到 docx_path 上（原地更新）。

    返回摘要 dict：headers / footers / media / styles / title_pg。
    模板缺页眉页脚、或目标没有可替换部件时抛错，避免悄悄产出没有抬头的文书。
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"页眉页脚模板不存在: {template_path}")

    _, src = _read_zip(template_path)
    names, tgt = _read_zip(docx_path)

    src_sect = _body_sectpr(_text(src, "word/document.xml"))
    src_refs = _sectpr_refs(src_sect, _doc_rels(src))
    if not src_refs:
        raise ValueError(f"模板里没有页眉/页脚引用: {template_path}")

    tgt_rels = _doc_rels(tgt)
    tgt_doc_xml = _text(tgt, "word/document.xml")
    tgt_sects = _SECTPR_RE.findall(tgt_doc_xml)

    replaced = {}  # 目标部件名 -> 模板部件名
    for sect in tgt_sects:
        for key, part in _sectpr_refs(sect, tgt_rels).items():
            if key in src_refs:
                replaced[part] = src_refs[key]
    if not replaced:
        raise ValueError("目标文档没有可替换的页眉/页脚部件（部件未创建或 sectPr 无引用）")

    counter = [0]
    media_cache = {}
    added = {}
    style_sources = []
    made_parts = []

    for tgt_part, src_part in sorted(replaced.items()):
        part_xml = _text(src, src_part)
        style_sources.append(part_xml)
        rels_xml, id_map = _copy_part_relationships(
            src_part, tgt_part, src, tgt, added, media_cache, counter
        )
        if id_map:
            part_xml = _rewrite_rel_refs(part_xml, id_map)
        added[tgt_part] = part_xml.encode("utf-8")
        made_parts.append(tgt_part)
        if rels_xml:
            added[f"word/_rels/{posixpath.basename(tgt_part)}.rels"] = rels_xml.encode("utf-8")

    # 样式闭包：只并入被页眉页脚引用的样式，不碰目标原有定义
    new_styles_xml, copied_styles = _apply_styles(
        _text(tgt, "word/styles.xml"), _text(src, "word/styles.xml"), style_sources
    )
    tgt["word/styles.xml"] = new_styles_xml.encode("utf-8")

    # sectPr：titlePg + header/footer 距离
    dist_header = _attr(src_sect, "w:header")
    dist_footer = _attr(src_sect, "w:footer")
    add_titlepg = bool(_TITLEPG_RE.search(src_sect))
    new_doc_xml = tgt_doc_xml
    for sect in tgt_sects:
        new_doc_xml = new_doc_xml.replace(
            sect, _patch_sectpr(sect, dist_header, dist_footer, add_titlepg), 1
        )
    tgt["word/document.xml"] = new_doc_xml.encode("utf-8")

    # Content Types
    ct_name = "[Content_Types].xml"
    tgt[ct_name] = _ensure_content_types(_text(tgt, ct_name), made_parts, added).encode("utf-8")

    # 写回（临时文件 + 原子替换）
    order = names + [n for n in added if n not in names]
    dir_name = os.path.dirname(os.path.abspath(docx_path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".letterhead.tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in order:
                if name in added:
                    zout.writestr(name, added[name])
                else:
                    zout.writestr(name, tgt[name])
        _replace_with_retry(tmp_path, docx_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    parts_by_kind = {"header": [], "footer": []}
    for part in made_parts:
        kind = posixpath.basename(part).split(".")[0].rstrip("0123456789")
        parts_by_kind.setdefault(kind, []).append(part)

    return {
        "headers": parts_by_kind.get("header", []),
        "footers": parts_by_kind.get("footer", []),
        "media": [n for n in added if n.startswith("word/media/")],
        "styles": copied_styles,
        "title_pg": add_titlepg,
    }


