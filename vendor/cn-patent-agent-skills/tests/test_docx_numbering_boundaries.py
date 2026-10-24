"""独立验收 F02/F08：最终编号定义、禁用编号和报告相对路径边界。

复用真实组装夹具；只变异 ZIP/XML，不执行法律判断或 DOCX 视觉导出。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from lxml import etree as ET

from test_docx_delivery_current_bytes import (
    DELIVERY_PATH,
    _build_realistic_docx_evidence,
    _run_delivery,
    _sha,
    _verify_assembly,
    _write_json,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
NUM_ID = "91001"
ABSTRACT_ID = "91000"


@pytest.fixture
def evidence(tmp_path):
    return _build_realistic_docx_evidence(tmp_path)


def _xml(root) -> bytes:
    # lxml 保留正文原有命名空间声明，避免引入与编号无关的 mc:Ignorable 变异。
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _element(name: str, **attributes):
    return ET.Element(f"{{{W}}}{name}", {f"{{{W}}}{key}": str(value) for key, value in attributes.items()})


def _numbering(*, override: str | None = None, parent_level: int = 2, child_level: int = 2) -> bytes:
    root = ET.Element(f"{{{W}}}numbering", nsmap=NS)
    abstract = _element("abstractNum", abstractNumId=ABSTRACT_ID)
    level = _element("lvl", ilvl=0)
    level.extend([
        _element("start", val=1), _element("numFmt", val="decimal"),
        _element("lvlText", val="%1."), _element("lvlJc", val="left"),
    ])
    abstract.append(level)
    num = _element("num", numId=NUM_ID)
    num.append(_element("abstractNumId", val=ABSTRACT_ID))
    if override:
        replacement = _element("lvlOverride", ilvl=parent_level)
        replacement.append(_element("startOverride", val=1))
        if override == "level":
            new_level = _element("lvl", ilvl=child_level)
            new_level.extend([
                _element("start", val=1), _element("numFmt", val="decimal"),
                _element("lvlText", val=f"%{child_level + 1}."), _element("lvlJc", val="left"),
            ])
            replacement.append(new_level)
        num.append(replacement)
    root.extend([abstract, num])
    return _xml(root)


def _mutate_numbering(evidence, numbering: bytes | None, *, num_id: str = NUM_ID, level: int = 2):
    path = evidence["docx"]
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(members["word/document.xml"])
    refs = document.xpath(".//w:numPr", namespaces=NS)
    assert refs, "真实组装夹具必须有段落编号引用，防止负例未触发"
    for ref in refs:
        for child in list(ref):
            ref.remove(child)
        ref.extend([_element("ilvl", val=level), _element("numId", val=num_id)])
    members["word/document.xml"] = _xml(document)
    if numbering is None:
        members.pop("word/numbering.xml", None)
        # 去除悬空部件关系，确保 numId=0 正例不是依赖损坏 ZIP 的侥幸放行。
        relationships = ET.fromstring(members["word/_rels/document.xml.rels"])
        for rel in list(relationships):
            if (rel.get("Type") or "").endswith("/numbering"):
                relationships.remove(rel)
        members["word/_rels/document.xml.rels"] = _xml(relationships)
        content_types = ET.fromstring(members["[Content_Types].xml"])
        for item in list(content_types):
            if item.get("PartName") == "/word/numbering.xml":
                content_types.remove(item)
        members["[Content_Types].xml"] = _xml(content_types)
    else:
        members["word/numbering.xml"] = numbering
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    report = json.loads(evidence["docx_report"].read_text(encoding="utf-8"))
    report["output_sha256"] = _sha(path)
    _write_json(evidence["docx_report"], report)
    assert report["output_sha256"] == _sha(path)


def _assembly_result(evidence):
    result = _verify_assembly(evidence["docx_report"])
    assert result["stdout"].strip(), result
    payload = json.loads(result["stdout"])
    _write_json(evidence["case_dir"] / "independent-assembly-result.json", {**result, "payload": payload})
    return result, payload


def _assert_numbering_rejected(evidence):
    result, payload = _assembly_result(evidence)
    assert result["returncode"] == 2, result
    assert payload["status"] == "FAIL", payload
    codes = {error["code"] for error in payload["errors"]}
    assert "DOCX-PACKAGE-NUMBERING" in codes, payload
    assert "DOCX-EVIDENCE-STALE" not in codes, "已同步 output_sha256，不应靠哈希过期拒绝"


def _assert_assembly_passes(evidence):
    result, payload = _assembly_result(evidence)
    assert result["returncode"] == 0, result
    assert payload["status"] == "PASS" and not payload["errors"], payload
    return payload


@pytest.mark.parametrize("part", ["missing", "malformed"])
def test_positive_numid_requires_readable_numbering_part(evidence, part):
    numbering = None if part == "missing" else b'<w:numbering xmlns:w="' + W.encode() + b'">'
    _mutate_numbering(evidence, numbering, level=0)
    _assert_numbering_rejected(evidence)


def test_undefined_level_two_is_rejected_after_hash_refresh(evidence):
    _mutate_numbering(evidence, _numbering())
    _assert_numbering_rejected(evidence)


def test_start_override_alone_cannot_define_level_two(evidence):
    _mutate_numbering(evidence, _numbering(override="start"))
    _assert_numbering_rejected(evidence)


@pytest.mark.parametrize("parent_level,child_level", [(1, 2), (2, 1)])
def test_override_parent_and_child_levels_must_agree(evidence, parent_level, child_level):
    _mutate_numbering(
        evidence, _numbering(override="level", parent_level=parent_level, child_level=child_level),
        level=child_level,
    )
    _assert_numbering_rejected(evidence)


def test_real_level_override_defines_previously_absent_level(evidence):
    _mutate_numbering(evidence, _numbering(override="level"))
    _assert_assembly_passes(evidence)


def test_start_override_can_restart_existing_level(evidence):
    _mutate_numbering(evidence, _numbering(override="start", parent_level=0), level=0)
    _assert_assembly_passes(evidence)


@pytest.mark.parametrize("has_numbering_part", [False, True])
def test_numid_zero_disables_numbering_without_requiring_definition(evidence, has_numbering_part):
    # numId=0 是合法禁用值；即使标注 ilvl=2，也不要求任何相应编号定义。
    _mutate_numbering(evidence, _numbering() if has_numbering_part else None, num_id="0")
    _assert_assembly_passes(evidence)


def _relocate_report(evidence, subdirectory: str) -> None:
    old_path = evidence["docx_report"]
    new_path = evidence["case_dir"] / subdirectory / old_path.name
    report = json.loads(old_path.read_text(encoding="utf-8"))

    def relative(raw):
        path = Path(raw)
        actual = path if path.is_absolute() else old_path.parent / path
        value = os.path.relpath(actual.resolve(), new_path.parent)
        assert not Path(value).is_absolute()
        if subdirectory:
            assert value.startswith("../"), value
        return value

    report["output"] = relative(report["output"])
    inputs = report["inputs"]
    inputs["template"] = relative(inputs["template"])
    inputs["source_dir"] = relative(inputs["source_dir"])
    for item in inputs["artifacts"]:
        item["path"] = relative(item["path"])
    _write_json(new_path, report)
    evidence["docx_report"] = new_path


@pytest.mark.parametrize("subdirectory", ["", "reports"])
def test_all_assembly_report_paths_can_be_relative(evidence, subdirectory):
    _relocate_report(evidence, subdirectory)
    _assert_assembly_passes(evidence)


@pytest.mark.parametrize("missing", ["file", "brief_path", "drawing_binding"])
def test_delivery_rejects_missing_drawio(evidence, missing):
    if missing == "file":
        evidence["drawio"].unlink()
    elif missing == "brief_path":
        brief = json.loads(evidence["brief"].read_text(encoding="utf-8"))
        brief["figures"][0]["outputs"].pop("drawio")
        _write_json(evidence["brief"], brief)
        drawing = json.loads(evidence["drawing"].read_text(encoding="utf-8"))
        drawing["brief_sha256"] = _sha(evidence["brief"])
        _write_json(evidence["drawing"], drawing)
    else:
        drawing = json.loads(evidence["drawing"].read_text(encoding="utf-8"))
        drawing["figures"][0].pop("drawio")
        _write_json(evidence["drawing"], drawing)
    result, payload = _run_delivery(
        evidence["case_dir"], evidence["brief"], evidence["drawing"],
        evidence["docx_report"], evidence["docx_verification"],
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert payload["status"] == "FAIL", payload
    assert payload["docx_assembly_reverified_status"] == "PASS", payload
    codes = {error["code"] for error in payload["errors"]}
    expected = "DELIVERY-DRAWING-EVIDENCE" if missing == "file" else "DELIVERY-DRAWING-BINDING"
    assert expected in codes and "DELIVERY-DRAWING-STALE" not in codes, payload


def test_delivery_rejects_stale_drawio_hash(evidence):
    evidence["drawio"].write_bytes(b"<mxfile>changed-after-verification</mxfile>")
    result, payload = _run_delivery(
        evidence["case_dir"], evidence["brief"], evidence["drawing"],
        evidence["docx_report"], evidence["docx_verification"],
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert payload["status"] == "FAIL", payload
    assert payload["docx_assembly_reverified_status"] == "PASS", payload
    assert any(error["code"] == "DELIVERY-DRAWING-EVIDENCE-STALE" for error in payload["errors"]), payload


def test_delivery_accepts_relative_cli_reports_and_parent_relative_artifacts(evidence):
    _relocate_report(evidence, "reports")
    freshness = _assert_assembly_passes(evidence)
    freshness["report"] = os.path.relpath(evidence["docx_report"], evidence["docx_verification"].parent)
    _write_json(evidence["docx_verification"], freshness)
    drawing = json.loads(evidence["drawing"].read_text(encoding="utf-8"))
    for item in drawing["figures"]:
        for kind in ("png", "drawio"):
            item[kind]["path"] = os.path.relpath(item[kind]["path"], evidence["case_dir"])
    _write_json(evidence["drawing"], drawing)
    command = [sys.executable, str(DELIVERY_PATH), "--case-dir", "."]
    for option, key in (
        ("--brief", "brief"), ("--drawing-verification", "drawing"),
        ("--docx-report", "docx_report"), ("--docx-verification", "docx_verification"),
    ):
        command.extend([option, os.path.relpath(evidence[key], evidence["case_dir"])])
    command.extend(["--output", "relative-delivery.json"])
    result = subprocess.run(command, cwd=evidence["case_dir"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads((evidence["case_dir"] / "relative-delivery.json").read_text(encoding="utf-8"))
    assert payload["status"] == "PASS" and not payload["errors"], payload
    assert payload["docx_assembly_reverified_status"] == "PASS", payload
