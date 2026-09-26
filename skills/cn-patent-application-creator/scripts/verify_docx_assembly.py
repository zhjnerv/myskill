#!/usr/bin/env python3
"""独立复算 DOCX 组装报告的输入、输出哈希和证据新鲜度。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from typing import Any

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

def check_pending_marks(path: Path, copy_kind: str, pending_marks: list | None, errors: list[dict[str, str]]) -> None:
    if pending_marks is None:
        pending_marks = []
    try:
        with ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                return
            document_text = archive.read("word/document.xml").decode("utf-8")
    except Exception:
        return

    if copy_kind == "submission":
        if "【待决" in document_text:
            errors.append({"code": "DOCX-PENDING-MARKS", "message": "提交副本存在残缺待决标记"})
        if re.search(r'<w:highlight[^>]*w:val="yellow"[^>]*>', document_text):
            errors.append({"code": "DOCX-PENDING-MARKS", "message": "提交副本存在黄色高亮"})
    elif copy_kind == "review":
        for pm in pending_marks:
            pm_id = pm.get("id")
            if pm_id and f"【待决-{pm_id}】" not in document_text:
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
    if output_path is not None and output_path.is_file():
        check_docx_package(output_path, errors)
        copy_kind = report.get("copy_kind")
        if copy_kind in {"review", "submission"}:
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

    return {
        "schema_id": RESULT_SCHEMA_ID,
        "report": str(report_path),
        "report_sha256": sha256(report_path),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "evidence_scope": {
            "proves": ["组装报告绑定的模板、源文件、图片和输出 DOCX 当前仍为同一字节版本"],
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
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result = {"schema_id": RESULT_SCHEMA_ID, "status": "FAIL", "errors": [{"code": "DOCX-EVIDENCE-INPUT", "message": str(exc)}]}
    payload = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    if args.output:
        write_atomic(args.output.resolve(), payload)
    else:
        print(payload.decode("utf-8"), end="")
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
