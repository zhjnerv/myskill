#!/usr/bin/env python3
"""按 Word 模板组装中国发明专利申请文件，并生成原生 Word 公式。

输入目录约定包含：权利要求书.md、说明书.md、说明书摘要.md、说明书附图.md
以及说明书附图目录。输出沿用模板的样式、分节、页眉、页脚、行号和页码设置。

公式支持两种来源：
1. 推荐：Markdown 行内 ``$...$``、独立 ``$$...$$`` 或 ``math`` 代码块；
2. 兼容：独立成段且含等号的线性公式，例如 ``ED_CT=Q_CT×C_CT(P,a)``。

公式直接生成 Office Math Markup Language（OMML）结构，在 Linux、macOS 和
Windows 上均为可编辑的 Word 原生公式；禁止把普通字符排版冒充为公式。默认交付
只执行 DOCX 结构化校验；仅当用户明确要求视觉检查时，才在 Windows 使用 Word、
在 Linux/macOS 使用 LibreOffice 导出 PDF，并调用 pdftoppm 生成逐页 PNG。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt
except ImportError as exc:  # pragma: no cover - 环境错误路径
    raise SystemExit("缺少 python-docx；请在执行环境中安装 python-docx 后重试。") from exc

try:
    from lxml import etree
except ImportError as exc:  # pragma: no cover - 项目依赖缺失路径
    raise SystemExit("缺少 lxml；请先安装项目依赖。") from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - 项目依赖缺失路径
    raise SystemExit("缺少 Pillow；请先安装项目依赖。") from exc


EXPECTED_HEADERS = ["权利要求书", "说明书", "说明书附图", "说明书摘要", "摘要附图"]
REQUIRED_PARAGRAPH_STYLES = ["Normal (Web)", "Title", "Heading 1", "正文2", "附图图号"]
REQUIRED_CHARACTER_STYLE = "Strong"  # 中文 Word 界面显示为“要点”
REPORT_SCHEMA = "cn-patent-docx-assembly/v2"
PROJECT_TEMPLATE_NAME = "模版.docx"
REPO_ROOT = Path(__file__).resolve().parents[3]

CJK_RE = re.compile(r"[\u3400-\u9fff]")
DISPLAY_FORMULA_RE = re.compile(r"=")
INLINE_EXPLICIT_RE = re.compile(r"\$([^$\n]+)\$")
SPEC_PARAGRAPH_NUMBER_RE = re.compile(r"^\[\d{4}\]\s*")
CLAIM_STEP_RE = re.compile(r"(?=S\d{3}\s*[：:])")
FIGURE_DESCRIPTION_RE = re.compile(r"^图\s*(\d+)\s*(?:为|是).+图[。.]$")
FIGURE_CITATION_RE = re.compile(r"(?:如|参见|结合)图\s*(\d+)\s*(?:所示|可见)?|图\s*(\d+)\s*(?:所示|中)")
PENDING_MARK_RE = re.compile(r"【待决-D(\d{3})】")
INLINE_EQUATION_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[A-Za-z][A-Za-z0-9_]*(?:_(?:[A-Za-z0-9]+|\([A-Za-z0-9+\-]+\)))?"
    r"(?:\([^，。；\s]*\))?="
    r"[A-Za-z0-9_()+\-*/×^.,≈]+"
)
IDENTIFIER_RE = re.compile(r"[A-Za-z]+(?:_(?:[A-Za-z0-9]+|\([A-Za-z0-9+\-]+\)))*")


@dataclass(frozen=True)
class SpecItem:
    kind: str
    text: str


@dataclass(frozen=True)
class FigureSpec:
    number: int
    title: str
    path: Path


@dataclass(frozen=True)
class MathSpec:
    linear: str


class MathRegistry:
    def __init__(self) -> None:
        self.specs: list[MathSpec] = []

    def add(self, linear: str) -> str:
        value = normalize_formula(linear)
        if not value:
            raise ValueError("公式内容为空")
        self.specs.append(MathSpec(linear=value))
        return value


@dataclass(frozen=True)
class FormulaNode:
    kind: str
    value: str = ""
    children: tuple["FormulaNode", ...] = ()


FORMULA_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<number>\d+(?:\.\d+)?)|"
    r"(?P<identifier>[A-Za-zΑ-Ωα-ω]+)|"
    r"(?P<operator>[_=+\-×*/^≈<>≤≥(),\[\]{}])|"
    r"(?P<other>.)"
    r")",
    re.DOTALL,
)


class FormulaParser:
    """把本项目使用的线性公式子集解析为可结构化输出的语法树。"""

    RELATIONS = {"=", "≈", "<", ">", "≤", "≥"}
    ADDITIVE = {"+", "-"}
    MULTIPLICATIVE = {"×", "*"}
    OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}

    def __init__(self, source: str) -> None:
        self.tokens = [
            next(value for value in match.groupdict().values() if value is not None)
            for match in FORMULA_TOKEN_RE.finditer(source)
        ]
        self.index = 0

    def current(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> str:
        token = self.current()
        if token is None:
            raise ValueError("公式意外结束")
        self.index += 1
        return token

    def parse(self) -> FormulaNode:
        if not self.tokens:
            raise ValueError("公式内容为空")
        node = self.parse_relation(set())
        if self.current() is not None:
            raise ValueError(f"公式含无法解析的剩余内容：{''.join(self.tokens[self.index:])}")
        return node

    @staticmethod
    def sequence(items: list[FormulaNode]) -> FormulaNode:
        compact: list[FormulaNode] = []
        for item in items:
            if item.kind == "sequence":
                compact.extend(item.children)
            else:
                compact.append(item)
        if len(compact) == 1:
            return compact[0]
        return FormulaNode("sequence", children=tuple(compact))

    def parse_relation(self, stop: set[str]) -> FormulaNode:
        items = [self.parse_additive(stop | self.RELATIONS)]
        while self.current() in self.RELATIONS and self.current() not in stop:
            items.append(FormulaNode("text", self.take()))
            items.append(self.parse_additive(stop | self.RELATIONS))
        return self.sequence(items)

    def parse_additive(self, stop: set[str]) -> FormulaNode:
        items = [self.parse_multiplicative(stop | self.ADDITIVE)]
        while self.current() in self.ADDITIVE and self.current() not in stop:
            items.append(FormulaNode("text", self.take()))
            items.append(self.parse_multiplicative(stop | self.ADDITIVE))
        return self.sequence(items)

    def parse_multiplicative(self, stop: set[str]) -> FormulaNode:
        items = [self.parse_scripted(stop | self.MULTIPLICATIVE | {"/"})]
        while self.current() is not None and self.current() not in stop:
            token = self.current()
            if token in self.MULTIPLICATIVE:
                items.append(FormulaNode("text", self.take()))
                items.append(self.parse_scripted(stop | self.MULTIPLICATIVE | {"/"}))
            elif token == "/":
                self.take()
                numerator = self.sequence(items)
                denominator = self.parse_scripted(stop | self.MULTIPLICATIVE | {"/"})
                items = [FormulaNode("fraction", children=(numerator, denominator))]
            elif token in self.RELATIONS or token in self.ADDITIVE or token in {')', ']', '}'}:
                break
            else:
                # 函数调用、相邻括号和省略乘号均按相邻数学对象保留。
                items.append(self.parse_scripted(stop | self.MULTIPLICATIVE | {"/"}))
        return self.sequence(items)

    def parse_scripted(self, stop: set[str]) -> FormulaNode:
        base = self.parse_primary(stop | {"_", "^"})
        subscript: FormulaNode | None = None
        superscript: FormulaNode | None = None
        while self.current() in {"_", "^"}:
            operator = self.take()
            script = self.parse_script_argument(stop)
            if operator == "_":
                if subscript is not None:
                    raise ValueError("同一公式对象出现重复下标")
                subscript = script
            else:
                if superscript is not None:
                    raise ValueError("同一公式对象出现重复上标")
                superscript = script
        if subscript is not None and superscript is not None:
            return FormulaNode("subsup", children=(base, subscript, superscript))
        if subscript is not None:
            return FormulaNode("subscript", children=(base, subscript))
        if superscript is not None:
            return FormulaNode("superscript", children=(base, superscript))
        return base

    def parse_script_argument(self, stop: set[str]) -> FormulaNode:
        token = self.current()
        if token in self.OPEN_TO_CLOSE:
            opening = self.take()
            closing = self.OPEN_TO_CLOSE[opening]
            value = self.parse_relation({closing})
            if self.current() != closing:
                raise ValueError(f"公式下标/上标缺少闭合符号 {closing}")
            self.take()
            return value
        return self.parse_primary(stop)

    def parse_primary(self, stop: set[str]) -> FormulaNode:
        token = self.current()
        if token is None or token in stop:
            raise ValueError(f"公式在 {token!r} 前缺少操作数")
        if token in self.OPEN_TO_CLOSE:
            opening = self.take()
            closing = self.OPEN_TO_CLOSE[opening]
            value = self.parse_relation({closing})
            if self.current() != closing:
                raise ValueError(f"公式缺少闭合符号 {closing}")
            self.take()
            return FormulaNode("delimiter", value=opening + closing, children=(value,))
        if token in {')', ']', '}'}:
            raise ValueError(f"公式出现多余闭合符号 {token}")
        return FormulaNode("text", self.take())


def _math_element(name: str):
    return OxmlElement(f"m:{name}")


def _math_container(name: str, node: FormulaNode):
    container = _math_element(name)
    for child in render_formula_node(node):
        container.append(child)
    return container


def _math_run(text: str):
    run = _math_element("r")
    value = _math_element("t")
    value.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    value.text = text
    run.append(value)
    return run


def render_formula_node(node: FormulaNode) -> list:
    if node.kind == "text":
        return [_math_run(node.value)]
    if node.kind == "sequence":
        result: list = []
        for child in node.children:
            result.extend(render_formula_node(child))
        return result
    if node.kind == "fraction":
        fraction = _math_element("f")
        fraction.append(_math_container("num", node.children[0]))
        fraction.append(_math_container("den", node.children[1]))
        return [fraction]
    if node.kind == "subscript":
        scripted = _math_element("sSub")
        scripted.append(_math_container("e", node.children[0]))
        scripted.append(_math_container("sub", node.children[1]))
        return [scripted]
    if node.kind == "superscript":
        scripted = _math_element("sSup")
        scripted.append(_math_container("e", node.children[0]))
        scripted.append(_math_container("sup", node.children[1]))
        return [scripted]
    if node.kind == "subsup":
        scripted = _math_element("sSubSup")
        scripted.append(_math_container("e", node.children[0]))
        scripted.append(_math_container("sub", node.children[1]))
        scripted.append(_math_container("sup", node.children[2]))
        return [scripted]
    if node.kind == "delimiter":
        delimiter = _math_element("d")
        properties = _math_element("dPr")
        begin = _math_element("begChr")
        begin.set(qn("m:val"), node.value[0])
        end = _math_element("endChr")
        end.set(qn("m:val"), node.value[1])
        properties.extend((begin, end))
        delimiter.append(properties)
        delimiter.append(_math_container("e", node.children[0]))
        return [delimiter]
    raise ValueError(f"未知公式节点：{node.kind}")


def build_omath(linear: str):
    """生成可由 Word/LibreOffice 编辑的原生 OMML 公式对象。"""

    root = _math_element("oMath")
    node = FormulaParser(normalize_formula(linear)).parse()
    for child in render_formula_node(node):
        root.append(child)
    return root


def append_omath(paragraph, registry: MathRegistry, linear: str) -> None:
    value = registry.add(linear)
    paragraph._p.append(build_omath(value))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def markdown_blocks(path: Path) -> list[str]:
    text = read_text(path).strip()
    return [
        re.sub(r"\s*\n\s*", " ", block.strip())
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]


def parse_claims(path: Path) -> list[str]:
    lines = read_text(path).splitlines()
    if not lines or lines[0].strip() != "# 权利要求书":
        raise ValueError("权利要求书缺少预期标题“# 权利要求书”")
    # 权利要求之间允许用一个换行或空行分隔；以行首编号作为唯一边界，
    # 避免把连续编号列表误合并成一项，同时保留多行权利要求正文。
    claim_parts: list[list[str]] = []
    numbers: list[int] = []
    current: list[str] | None = None
    for line in lines[1:]:
        match = re.match(r"^\s*(\d+)\.\s*(.*)$", line)
        if match:
            if current is not None:
                claim_parts.append(current)
            numbers.append(int(match.group(1)))
            current = [match.group(2).strip()]
        elif line.strip():
            if current is None:
                raise ValueError(f"首项权利要求之前出现无法识别的正文：{line[:80]}")
            current.append(line.strip())
    if current is not None:
        claim_parts.append(current)
    claims = [" ".join(part).strip() for part in claim_parts]
    if not claims:
        raise ValueError("权利要求书中没有可识别的编号权利要求")
    if numbers != list(range(1, len(claims) + 1)):
        raise ValueError(f"权利要求编号不连续：{numbers}")
    return claims



def split_claim_paragraphs(text: str) -> list[str]:
    """将包含连续步骤标记的方法权利要求拆为模板中的多级段落。"""
    matches = list(re.finditer(r"S\d{3}\s*[：:]", text))
    if len(matches) < 2:
        return [text]
    prefix = text[:matches[0].start()].strip()
    steps = [part.strip() for part in CLAIM_STEP_RE.split(text[matches[0].start():]) if part.strip()]
    return ([prefix] if prefix else []) + steps


# 生产与独立验证共用编号约束，但分别读取各自当前的 DOCX 字节。
_numbering_spec = importlib.util.spec_from_file_location(
    "cn_docx_numbering_contract", Path(__file__).with_name("verify_docx_assembly.py")
)
if _numbering_spec is None or _numbering_spec.loader is None:
    raise RuntimeError("无法加载 DOCX 编号约束")
_numbering = importlib.util.module_from_spec(_numbering_spec)
_numbering_spec.loader.exec_module(_numbering)


def _parse_numbering_bytes(
    numbering_bytes: bytes, styles_bytes: bytes | None = None,
) -> dict[int, set[int]]:
    return _numbering._parse_final_numbering(numbering_bytes, styles_bytes)


def parse_template_numbering(template_path: Path) -> dict[int, set[int]] | None:
    """缺少编号部件返回 None；损坏或非法编号定义明确失败。"""
    with ZipFile(template_path) as archive:
        names = set(archive.namelist())
        if "word/numbering.xml" not in names:
            return None
        styles_bytes = archive.read("word/styles.xml") if "word/styles.xml" in names else None
        try:
            return _parse_numbering_bytes(archive.read("word/numbering.xml"), styles_bytes)
        except (_numbering.ET.ParseError, ValueError) as exc:
            raise ValueError(f"模板 numbering.xml 无效：{exc}") from exc


def project_application_template() -> Path:
    """仓库根目录的最终专利申请文件模板。"""
    return REPO_ROOT / PROJECT_TEMPLATE_NAME


def resolve_application_template(explicit: Path | None) -> Path:
    """默认使用项目模板。案件目录中的 ``输出模版.docx`` 不参与选择。"""
    if explicit is not None:
        return explicit.expanduser().resolve()
    template = project_application_template()
    if not template.is_file():
        raise FileNotFoundError(
            f"未找到项目专利申请模板：{template}。"
            "不要改用案件目录中的输出模版.docx；如需替换，请显式传入 --template。"
        )
    return template.resolve()


def select_step_ilvl(available_levels: set[int]) -> int:
    """为步骤段落选择模板已定义的层级：优先 ``>0`` 的最小层级，否则退回 ``0``。

    单级模板只定义 ``ilvl=0`` 时，步骤段落也使用 ``ilvl=0``（避免引用未定义层级）。
    项目模板若在正文中示范了另一个步骤层级，由 ``template_step_ilvl`` 优先采用示范值。
    """

    if not available_levels:
        raise ValueError("模板未提供任何 numId/ilvl 定义，无法生成步骤段落")
    ordered = sorted(available_levels)
    for level in ordered:
        if level > 0:
            return level
    return ordered[0]


def template_step_ilvl(doc: Document, claim_num_id: int, available_levels: set[int]) -> int:
    """模板正文已经示范步骤层级时采用该层级，否则退回最小可用子层。"""
    observed: list[int] = []
    for paragraph in doc.paragraphs:
        ppr = paragraph._p.pPr
        if ppr is None or ppr.numPr is None:
            continue
        numid = ppr.numPr.find(qn("w:numId"))
        if numid is None or numid.get(qn("w:val")) != str(claim_num_id):
            continue
        ilvl = ppr.numPr.find(qn("w:ilvl"))
        raw = "0" if ilvl is None or ilvl.get(qn("w:val")) is None else ilvl.get(qn("w:val"))
        if not raw.isdigit():
            continue
        level = int(raw)
        if level > 0 and level in available_levels and level not in observed:
            observed.append(level)
    if len(observed) > 1:
        raise ValueError(
            f"模板权利要求 numId={claim_num_id} 示范了多个步骤层级 {observed}，无法确定应使用哪一层"
        )
    if len(observed) == 1:
        return observed[0]
    return select_step_ilvl(available_levels)


def claim_step_properties(claim_ppr, available_levels: set[int], step_ilvl: int | None = None):
    """复制模板权利要求属性，并把 ilvl 切到模板已定义的步骤层级。"""

    result = deepcopy(claim_ppr)
    numpr = result.find(qn("w:numPr"))
    if numpr is None:
        raise ValueError("模板权利要求缺少 numPr，无法生成步骤段落")
    numid = numpr.find(qn("w:numId"))
    if numid is None or numid.get(qn("w:val")) is None:
        raise ValueError("模板权利要求 numPr 缺少 numId，无法生成步骤段落")
    level = select_step_ilvl(available_levels) if step_ilvl is None else step_ilvl
    if level not in available_levels:
        raise ValueError(f"步骤层级 ilvl={level} 不在模板编号定义中")
    ilvl = numpr.find(qn("w:ilvl"))
    if ilvl is None:
        ilvl = OxmlElement("w:ilvl")
        numpr.insert(0, ilvl)
    ilvl.set(qn("w:val"), str(level))
    ind = result.find(qn("w:ind"))
    if ind is not None:
        result.remove(ind)
    return result


def validate_numbering_references(
    document_xml: bytes, numbering: dict[int, set[int]] | None,
) -> None:
    """根据最终 DOCX 的真实定义检查显式编号引用，而非旧模板映射。"""
    _numbering._validate_numbering_references(document_xml, numbering)


def validate_specification_structure(items: list[SpecItem], figures: list[FigureSpec]) -> None:
    """校验附图说明和具体实施方式的模板化组织。"""
    headings = [(index, item.text) for index, item in enumerate(items) if item.kind == "heading"]
    by_name = {text: index for index, text in headings}
    if "附图说明" not in by_name or "具体实施方式" not in by_name:
        raise ValueError("说明书缺少附图说明或具体实施方式")
    drawing_start = by_name["附图说明"] + 1
    implementation_start = by_name["具体实施方式"]
    drawing_items = items[drawing_start:implementation_start]
    descriptions: list[tuple[int, str]] = []
    reference_sign_lines = []
    for item in drawing_items:
        if item.kind != "body":
            raise ValueError("附图说明中只允许图名句和一段附图标记说明")
        if item.text.startswith("图中："):
            reference_sign_lines.append(item.text)
            continue
        match = FIGURE_DESCRIPTION_RE.fullmatch(item.text)
        if match is None or "；" in item.text or len(item.text) > 80:
            raise ValueError(f"附图说明必须一图一句且不得展开解释：{item.text[:80]}")
        descriptions.append((int(match.group(1)), item.text))
    expected_numbers = [figure.number for figure in figures]
    if [number for number, _ in descriptions] != expected_numbers:
        raise ValueError(f"附图说明图号必须与说明书附图一致：{[number for number, _ in descriptions]} != {expected_numbers}")
    if len(reference_sign_lines) != 1:
        raise ValueError("附图说明必须且只能包含一段以“图中：”开头的附图标记说明")

    implementation_items = items[implementation_start + 1:]
    if len(implementation_items) < 3:
        raise ValueError("具体实施方式缺少引导段、实施例1标题或实施例正文")
    intro = implementation_items[0]
    example_heading = implementation_items[1]
    if intro.kind != "body" or "实施例" not in intro.text or "附图" not in intro.text:
        raise ValueError("具体实施方式标题后必须先有说明结合附图描述具体实施例的引导段")
    if example_heading.kind != "heading" or not re.fullmatch(r"实施例\s*1[。.]?", example_heading.text):
        raise ValueError("具体实施方式引导段后必须有明显的“实施例1。”标题")
    embodiment_text = "\n".join(item.text for item in implementation_items[2:] if item.kind == "body")
    cited = {
        int(first or second)
        for first, second in FIGURE_CITATION_RE.findall(embodiment_text)
        if first or second
    }
    missing = sorted(set(expected_numbers) - cited)
    if missing:
        raise ValueError(f"实施例正文必须结合附图逐图说明，缺少引用：{missing}")

LATEX_SYMBOL_MACROS: dict[str, str] = {
    # 希腊字母
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # 大型运算符（注意 \sum 用 U+2211 ∑，不用希腊 Σ）
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮", "bigcup": "⋃", "bigcap": "⋂",
    # 二元运算符
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "ast": "*", "star": "★",
    "circ": "∘", "bullet": "•", "oplus": "⊕", "otimes": "⊗", "cap": "∩", "cup": "∪",
    "land": "∧", "wedge": "∧", "lor": "∨", "vee": "∨", "lnot": "¬", "neg": "¬", "setminus": "∖",
    # 关系符
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "equiv": "≡",
    "approx": "≈", "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝", "ll": "≪", "gg": "≫",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "supseteq": "⊇", "perp": "⊥", "parallel": "∥", "mid": "|",
    # 逻辑与集合
    "forall": "∀", "exists": "∃", "nexists": "∄", "emptyset": "∅", "varnothing": "∅",
    "infty": "∞", "partial": "∂", "nabla": "∇",
    # 箭头
    "leftarrow": "←", "gets": "←", "rightarrow": "→", "to": "→", "uparrow": "↑", "downarrow": "↓",
    "leftrightarrow": "↔", "Leftarrow": "⇐", "Rightarrow": "⇒", "Uparrow": "⇑", "Downarrow": "⇓",
    "Leftrightarrow": "⇔", "mapsto": "↦",
    # 定界与省略
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    # 尺寸与间距提示：\left \right 无输出，\quad \qquad 为单空格
    "left": "", "right": "", "quad": " ", "qquad": " ",
}
# 函数名宏：去掉反斜杠后保留为普通标识符（\max_{w} -> max_{w}）
LATEX_OPERATOR_NAME_MACROS = frozenset({
    "max", "min", "arg", "argmax", "argmin", "log", "ln", "lg", "exp", "sin", "cos", "tan",
    "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "lim", "sup",
    "inf", "det", "dim", "gcd", "deg", "Pr", "mod", "bmod",
})
# 非字母转义：\{ \} \| 是可见字面字符；\, \; \: 为细空格；\! 为负空格。注意：\_ 故意不在表中。
LATEX_LITERAL_ESCAPES = {"\\{": "{", "\\}": "}", "\\|": "|", "\\,": " ", "\\;": " ", "\\:": " ", "\\!": ""}
LATEX_MACRO_RE = re.compile(r"\\([A-Za-z]+)")
LATEX_RESIDUAL_RE = re.compile(r"\\(?:[A-Za-z]+|.)?", re.DOTALL)


def _replace_latex_macro(match: re.Match[str]) -> str:
    name = match.group(1)
    if name in LATEX_SYMBOL_MACROS:
        return LATEX_SYMBOL_MACROS[name]
    if name in LATEX_OPERATOR_NAME_MACROS:
        return name
    return match.group(0)  # 未知宏原样保留，由残留检查报错


def normalize_formula(value: str) -> str:
    text = value.strip()
    if text.startswith("$$") and text.endswith("$$"):
        text = text[2:-2].strip()
    if text.startswith("```math") and text.endswith("```"):
        text = text[len("```math") : -3].strip()
    text = LATEX_MACRO_RE.sub(_replace_latex_macro, text)
    for escape, literal in LATEX_LITERAL_ESCAPES.items():
        text = text.replace(escape, literal)
    if "\\" in text:
        unsupported = sorted(set(LATEX_RESIDUAL_RE.findall(text)))
        raise ValueError(
            "公式包含组装器不支持的 LaTeX 宏或转义：" + "、".join(unsupported)
            + "；请改写为 a/b、x_{i}、x^{2}、Unicode 符号或直接去掉反斜杠后重试。"
        )
    return text.removesuffix("。").strip()


def looks_like_display_formula(value: str) -> bool:
    text = normalize_formula(value)
    if not DISPLAY_FORMULA_RE.search(text):
        return False
    if len(text) > 500 or CJK_RE.search(text):
        return False
    return bool(re.search(r"[_^×*/()]", text))


def classify_spec_block(value: str) -> SpecItem:
    text = SPEC_PARAGRAPH_NUMBER_RE.sub("", value.strip())
    if text.startswith("$$") and text.endswith("$$"):
        return SpecItem("formula", normalize_formula(text))
    if text.startswith("```math") and text.endswith("```"):
        return SpecItem("formula", normalize_formula(text))
    if looks_like_display_formula(text):
        return SpecItem("formula", normalize_formula(text))
    return SpecItem("body", text)


def parse_specification(path: Path) -> list[SpecItem]:
    items: list[SpecItem] = []
    pending: list[str] = []
    math_fence: list[str] | None = None

    def flush() -> None:
        if pending:
            items.append(classify_spec_block(" ".join(line.strip() for line in pending)))
            pending.clear()

    for raw in read_text(path).splitlines():
        line = raw.strip()
        if math_fence is not None:
            if line == "```":
                items.append(SpecItem("formula", normalize_formula(" ".join(math_fence))))
                math_fence = None
            else:
                math_fence.append(line)
            continue
        if line == "```math":
            flush()
            math_fence = []
            continue
        if not line:
            flush()
            continue
        if line.startswith("# "):
            flush()
            items.append(SpecItem("title", line[2:].strip()))
        elif line.startswith("## "):
            flush()
            items.append(SpecItem("heading", line[3:].strip()))
        elif line.startswith("### "):
            flush()
            items.append(SpecItem("heading", line[4:].strip()))
        else:
            pending.append(line)
    if math_fence is not None:
        raise ValueError("说明书存在未闭合的 ```math 代码块")
    flush()
    if not items or items[0].kind != "title":
        raise ValueError("说明书缺少一级标题形式的发明名称")
    return items


def parse_abstract(path: Path) -> tuple[str, int]:
    blocks = markdown_blocks(path)
    if not blocks or not blocks[0].startswith("# "):
        raise ValueError("说明书摘要缺少一级标题")
    figure_number: int | None = None
    body: list[str] = []
    for block in blocks[1:]:
        match = re.fullmatch(r"摘要附图：图(\d+)[。.]?", block)
        if match:
            figure_number = int(match.group(1))
        else:
            body.append(block)
    if len(body) != 1:
        raise ValueError(f"预期一个摘要正文段落，实际为 {len(body)} 个")
    if figure_number is None:
        raise ValueError("说明书摘要未指定“摘要附图：图N。”")
    return body[0], figure_number


def resolve_figure_path(index_path: Path, raw_target: str) -> Path:
    target = Path(raw_target)
    candidate = (index_path.parent / target).resolve()
    if candidate.suffix.lower() == ".svg":
        png = candidate.with_suffix(".png")
        if png.is_file():
            candidate = png
    if not candidate.is_file():
        raise FileNotFoundError(f"附图文件不存在：{candidate}")
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError(f"Word 组装仅接受 PNG/JPEG 发布图：{candidate}")
    return candidate


def parse_figures(path: Path) -> list[FigureSpec]:
    heading_re = re.compile(r"^##\s+图(\d+)\s+(.+)$")
    image_re = re.compile(r"^!\[[^]]*]\(([^)]+)\)$")
    current: tuple[int, str] | None = None
    figures: list[FigureSpec] = []
    for raw in read_text(path).splitlines():
        line = raw.strip()
        heading = heading_re.match(line)
        if heading:
            current = (int(heading.group(1)), heading.group(2).strip())
            continue
        image = image_re.match(line)
        if image and current is not None:
            figures.append(
                FigureSpec(
                    number=current[0],
                    title=current[1],
                    path=resolve_figure_path(path, image.group(1)),
                )
            )
            current = None
    numbers = [figure.number for figure in figures]
    if not figures or numbers != list(range(1, len(figures) + 1)):
        raise ValueError(f"说明书附图编号不连续：{numbers}")
    return figures


def extract_function_calls(formula: str) -> set[str]:
    calls: set[str] = set()
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_]*\(", formula):
        start = match.start()
        depth = 0
        for index in range(match.end() - 1, len(formula)):
            char = formula[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    calls.add(formula[start : index + 1])
                    break
    return calls


def collect_math_symbols(items: Iterable[SpecItem]) -> tuple[str, ...]:
    symbols: set[str] = set()
    for item in items:
        if item.kind != "formula":
            continue
        symbols.update(IDENTIFIER_RE.findall(item.text))
        symbols.update(extract_function_calls(item.text))
    # 常量和函数名也可作为公式对象；数字与运算符不单独提取。
    return tuple(sorted((value for value in symbols if value), key=len, reverse=True))


def tokenize_inline_math(text: str, symbols: tuple[str, ...]) -> list[tuple[bool, str]]:
    """把正文拆成普通文字与需要转为 OMath 的线性表达式。"""
    explicit: list[tuple[int, int, str]] = [
        (match.start(), match.end(), match.group(1)) for match in INLINE_EXPLICIT_RE.finditer(text)
    ]
    symbol_pattern = None
    if symbols:
        symbol_pattern = re.compile(
            r"(?<![A-Za-z0-9_])(?:"
            + "|".join(re.escape(value) for value in symbols)
            + r")(?![A-Za-z0-9_])"
        )

    spans: list[tuple[int, int, str]] = list(explicit)
    protected = [(start, end) for start, end, _ in explicit]

    def overlaps(start: int, end: int) -> bool:
        return any(start < other_end and end > other_start for other_start, other_end in protected)

    for match in INLINE_EQUATION_RE.finditer(text):
        if not overlaps(match.start(), match.end()):
            spans.append((match.start(), match.end(), match.group(0)))
            protected.append((match.start(), match.end()))
    if symbol_pattern is not None:
        for match in symbol_pattern.finditer(text):
            if not overlaps(match.start(), match.end()):
                spans.append((match.start(), match.end(), match.group(0)))
                protected.append((match.start(), match.end()))

    spans.sort(key=lambda item: item[0])
    result: list[tuple[bool, str]] = []
    cursor = 0
    for start, end, formula in spans:
        if start < cursor:
            continue
        if start > cursor:
            result.append((False, text[cursor:start]))
        result.append((True, formula))
        cursor = end
    if cursor < len(text):
        result.append((False, text[cursor:]))
    return result or [(False, text)]


def validate_template(doc: Document) -> list:
    if len(doc.sections) != 5:
        raise ValueError(f"输出模板必须包含5个分节，实际为 {len(doc.sections)}")
    missing = [name for name in REQUIRED_PARAGRAPH_STYLES if name not in doc.styles]
    if missing:
        raise ValueError(f"输出模板缺少段落样式：{missing}")
    if REQUIRED_CHARACTER_STYLE not in doc.styles:
        raise ValueError("输出模板缺少“要点”字符样式（OOXML/英文名 Strong）")
    headers = [
        section.header.paragraphs[0].text.strip() if section.header.paragraphs else ""
        for section in doc.sections
    ]
    if headers != EXPECTED_HEADERS:
        raise ValueError(f"输出模板页眉顺序错误：{headers}")
    first = doc.paragraphs[0]._p.pPr if doc.paragraphs else None
    if first is None or first.numPr is None:
        raise ValueError("输出模板首段必须提供权利要求自动编号格式")
    return [deepcopy(section._sectPr) for section in doc.sections]


def clear_body_keep_final_sectpr(doc: Document, final_sectpr) -> None:
    body = doc._body._element
    for child in list(body):
        body.remove(child)
    body.append(deepcopy(final_sectpr))


def copy_paragraph_properties(paragraph, source_ppr) -> None:
    existing = paragraph._p.pPr
    if existing is not None:
        paragraph._p.remove(existing)
    paragraph._p.insert(0, deepcopy(source_ppr))


def copy_run_properties(run, source_rpr) -> None:
    if source_rpr is None:
        return
    existing = run._r.rPr
    if existing is not None:
        run._r.remove(existing)
    run._r.insert(0, deepcopy(source_rpr))


def set_east_asia_font(run, font_name: str) -> None:
    run.font.name = font_name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = rpr._add_rFonts()
    rfonts.set(qn("w:eastAsia"), font_name)
    rfonts.set(qn("w:ascii"), font_name)
    rfonts.set(qn("w:hAnsi"), font_name)


def end_section(paragraph, sectpr) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    existing = ppr.sectPr
    if existing is not None:
        ppr.remove(existing)
    ppr.append(deepcopy(sectpr))


def apply_highlight(run) -> None:
    rPr = run._r.get_or_add_rPr()
    hl = OxmlElement("w:highlight")
    hl.set(qn("w:val"), "yellow")
    rPr.append(hl)


def process_pending_marks(text: str, copy_kind: str, location: str, pending_marks: list) -> tuple[str, bool]:
    marks = PENDING_MARK_RE.findall(text)
    if not marks:
        if copy_kind == "submission" and "【待决" in text:
            raise ValueError("提交副本存在残缺待决标记")
        return text, False
    for mark in marks:
        pending_marks.append({"id": f"D{mark}", "location": location})
    if copy_kind == "submission":
        text = PENDING_MARK_RE.sub("", text)
        if "【待决" in text:
            raise ValueError("提交副本存在残缺待决标记")
        return text, False
    return text, True


def add_claim(
    doc: Document,
    text: str,
    claim_ppr,
    claim_rpr,
    registry: MathRegistry,
    symbols: tuple[str, ...],
    highlight: bool = False,
):
    paragraph = doc.add_paragraph()
    copy_paragraph_properties(paragraph, claim_ppr)
    for is_math, value in tokenize_inline_math(text, symbols):
        if is_math:
            append_omath(paragraph, registry, value)
        elif value:
            run = paragraph.add_run(value)
            copy_run_properties(run, claim_rpr)
            if highlight:
                apply_highlight(run)
    return paragraph


def add_plain_run(paragraph, text: str, highlight: bool = False) -> None:
    if not text:
        return
    run = paragraph.add_run(text)
    set_east_asia_font(run, "宋体")
    run.font.size = Pt(12)
    if highlight:
        apply_highlight(run)


def add_spec_item(
    doc: Document,
    item: SpecItem,
    registry: MathRegistry,
    symbols: tuple[str, ...],
    processed_text: str = None,
    highlight: bool = False,
):
    text = processed_text if processed_text is not None else item.text
    if item.kind == "title":
        paragraph = doc.add_paragraph(style="Title")
        run = paragraph.add_run(text)
        if highlight: apply_highlight(run)
        return paragraph
    if item.kind == "heading":
        paragraph = doc.add_paragraph(style="Heading 1")
        run = paragraph.add_run(text)
        run.style = doc.styles[REQUIRED_CHARACTER_STYLE]
        if highlight: apply_highlight(run)
        return paragraph
    if item.kind == "formula":
        paragraph = doc.add_paragraph(style="正文2")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Pt(0)
        append_omath(paragraph, registry, text)
        punctuation = paragraph.add_run("。")
        set_east_asia_font(punctuation, "宋体")
        punctuation.font.size = Pt(12)
        return paragraph

    paragraph = doc.add_paragraph(style="正文2")
    for is_math, value in tokenize_inline_math(text, symbols):
        if is_math:
            append_omath(paragraph, registry, value)
        else:
            add_plain_run(paragraph, value, highlight)
    return paragraph


def image_size(path: Path, max_width_in: float, max_height_in: float) -> tuple[float, float]:
    with Image.open(path) as image:
        width_px, height_px = image.size
    scale = min(max_width_in / width_px, max_height_in / height_px)
    return width_px * scale, height_px * scale


def add_figure(doc: Document, figure: FigureSpec, page_break_before: bool):
    width, height = image_size(figure.path, max_width_in=6.25, max_height_in=8.75)
    image_p = doc.add_paragraph(style="附图图号")
    image_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    image_p.paragraph_format.space_before = Pt(0)
    image_p.paragraph_format.space_after = Pt(0)
    image_p.paragraph_format.keep_with_next = True
    image_p.paragraph_format.page_break_before = page_break_before
    image_p.add_run().add_picture(str(figure.path), width=Inches(width), height=Inches(height))

    caption_p = doc.add_paragraph(style="附图图号")
    caption_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_p.paragraph_format.space_before = Pt(0)
    caption_p.paragraph_format.space_after = Pt(0)
    caption_p.paragraph_format.keep_together = True
    caption_run = caption_p.add_run(f"图{figure.number}")
    set_east_asia_font(caption_run, "宋体")
    caption_run.font.size = Pt(12)
    return caption_p


def add_abstract_figure(doc: Document, figure: FigureSpec):
    width, height = image_size(figure.path, max_width_in=6.10, max_height_in=8.85)
    paragraph = doc.add_paragraph(style="附图图号")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.add_run().add_picture(str(figure.path), width=Inches(width), height=Inches(height))
    return paragraph


def require_word_automation():
    if sys.platform != "win32":
        raise RuntimeError("Microsoft Word 自动化仅在 Windows 可用")
    try:
        import win32com.client as win32
    except ImportError as exc:
        raise RuntimeError("缺少 pywin32，无法调用 Microsoft Word") from exc
    return win32


def export_pdf_with_libreoffice(path: Path, pdf_path: Path) -> None:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None:
        raise RuntimeError("未找到 LibreOffice，无法在非 Windows 环境导出视觉检查 PDF")
    with tempfile.TemporaryDirectory(prefix="cn_patent_lo_export_") as temporary:
        out_dir = Path(temporary)
        completed = subprocess.run(
            [
                executable,
                "--headless",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(out_dir),
                str(path.resolve()),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        generated = out_dir / f"{path.stem}.pdf"
        if completed.returncode != 0 or not generated.is_file():
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"LibreOffice 导出 PDF 失败：{detail}")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated, pdf_path)


def count_pdf_pages(pdf_path: Path) -> int:
    executable = shutil.which("pdfinfo")
    if executable is None:
        raise RuntimeError("未找到 pdfinfo，无法核对视觉检查页数")
    completed = subprocess.run(
        [executable, str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    match = re.search(r"^Pages:\s*(\d+)\s*$", completed.stdout, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("pdfinfo 输出中未找到页数")
    return int(match.group(1))


def process_with_word(path: Path, registry: MathRegistry, pdf_path: Path | None) -> int | None:
    """刷新文档并按需导出 PDF；公式已在保存前直接写成 OMML。"""

    if pdf_path is None:
        return None
    if sys.platform != "win32":
        export_pdf_with_libreoffice(path, pdf_path)
        return count_pdf_pages(pdf_path)

    win32 = require_word_automation()
    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    document = None
    try:
        document = word.Documents.Open(str(path.resolve()), False, False)
        for story in document.StoryRanges:
            with suppress(Exception):
                story.Fields.Update()
        document.Repaginate()
        page_count = int(document.ComputeStatistics(2))
        document.Save()
        if pdf_path is not None:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            document.ExportAsFixedFormat(str(pdf_path.resolve()), 17)
        document.Close(False)
        document = None
        return page_count
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()


def render_pdf_to_png(pdf_path: Path, render_dir: Path) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("未找到 pdftoppm，无法把 Word 导出的 PDF 渲染为逐页 PNG")
    # Windows 版 Poppler 对包含中文的路径兼容性不稳定。使用系统临时目录中的
    # ASCII 文件名完成栅格化，再复制回案件工作区，避免路径编码导致假失败。
    with tempfile.TemporaryDirectory(prefix="cn_patent_docx_render_") as staging_raw:
        staging = Path(staging_raw)
        staged_pdf = staging / "input.pdf"
        shutil.copy2(pdf_path, staged_pdf)
        prefix = staging / "page"
        subprocess.run(
            [executable, "-png", "-r", "120", str(staged_pdf), str(prefix)],
            check=True,
        )
        staged_pages = sorted(staging.glob("page-*.png"))
        if not staged_pages:
            raise RuntimeError("pdftoppm 未生成逐页 PNG")
        pages: list[Path] = []
        for source in staged_pages:
            target = render_dir / source.name
            shutil.copy2(source, target)
            pages.append(target)
        return pages


def inspect_package(
    path: Path,
    expected_math_count: int,
    heading_style_id: str,
    strong_style_id: str,
    template_numbering: dict[int, set[int]] | None = None,
) -> dict:
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        document_bytes = archive.read("word/document.xml")
        numbering_bytes = archive.read("word/numbering.xml") if "word/numbering.xml" in names else None
        styles_bytes = archive.read("word/styles.xml") if "word/styles.xml" in names else None
        root = etree.fromstring(document_bytes)
    final_numbering = (
        None if numbering_bytes is None else _parse_numbering_bytes(numbering_bytes, styles_bytes)
    )
    namespaces = {
        "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
    math_count = len(root.xpath(".//m:oMath", namespaces=namespaces))
    strong_count = len(
        root.xpath(
            './/w:p[w:pPr/w:pStyle[@w:val=$heading]]/w:r/w:rPr/w:rStyle[@w:val=$strong]',
            namespaces=namespaces,
            heading=heading_style_id,
            strong=strong_style_id,
        )
    )
    markers = root.xpath('.//w:t[contains(text(), "[[EQ")]/text()', namespaces=namespaces)
    if markers:
        raise RuntimeError(f"仍有公式占位符未转换：{markers}")
    if math_count != expected_math_count:
        raise RuntimeError(f"公式对象数量错误：期望 {expected_math_count}，实际 {math_count}")
    # 这里必须消费最终 DOCX 内的编号定义，而不是组装前模板的旧映射。
    validate_numbering_references(document_bytes, final_numbering)
    return {"math_count": math_count, "strong_heading_run_count": strong_count}


def build_document(
    source_dir: Path,
    template_path: Path,
    output_path: Path,
    render_dir: Path | None,
    copy_kind: str = "review",
) -> dict:
    claims_path = source_dir / "权利要求书.md"
    spec_path = source_dir / "说明书.md"
    abstract_path = source_dir / "说明书摘要.md"
    figure_index_path = source_dir / "说明书附图.md"
    for path in [template_path, claims_path, spec_path, abstract_path, figure_index_path]:
        if not path.is_file():
            raise FileNotFoundError(path)

    claims = parse_claims(claims_path)
    specification = parse_specification(spec_path)
    abstract, abstract_figure_number = parse_abstract(abstract_path)
    figures = parse_figures(figure_index_path)
    validate_specification_structure(specification, figures)
    by_number = {figure.number: figure for figure in figures}
    if abstract_figure_number not in by_number:
        raise ValueError(f"摘要附图图号不存在：图{abstract_figure_number}")
    symbols = collect_math_symbols(specification)
    registry = MathRegistry()

    pending_marks = []
    doc = Document(template_path)
    section_props = validate_template(doc)
    heading_style_id = doc.styles["Heading 1"].style_id
    strong_style_id = doc.styles[REQUIRED_CHARACTER_STYLE].style_id
    claim_ppr = deepcopy(doc.paragraphs[0]._p.pPr)
    claim_rpr = next(
        (deepcopy(run._r.rPr) for run in doc.paragraphs[0].runs if run.text),
        None,
    )
    template_numbering = parse_template_numbering(template_path)
    claim_numpr = claim_ppr.find(qn("w:numPr"))
    claim_numid_elem = claim_numpr.find(qn("w:numId")) if claim_numpr is not None else None
    claim_num_id_value: int | None = None
    if claim_numid_elem is not None and claim_numid_elem.get(qn("w:val")) is not None:
        try:
            claim_num_id_value = int(claim_numid_elem.get(qn("w:val")))
        except ValueError:
            claim_num_id_value = None
    if claim_num_id_value not in (None, 0):
        if template_numbering is None:
            raise ValueError("模板缺少或损坏 word/numbering.xml，但权利要求模板存在编号引用")
        available_levels = template_numbering.get(claim_num_id_value, set())
        if not available_levels:
            raise ValueError(
                f"权利要求模板引用了未定义或无真实层级的 numId={claim_num_id_value}"
            )
        step_ilvl = template_step_ilvl(doc, claim_num_id_value, available_levels)
    else:
        # numId=0 是取消编号；不为取消编号的段落伪造编号实例。
        available_levels = {0}
        step_ilvl = 0
    clear_body_keep_final_sectpr(doc, section_props[-1])

    last = None
    step_ppr = claim_step_properties(claim_ppr, available_levels, step_ilvl)
    claim_idx = 1
    for claim in claims:
        parts = split_claim_paragraphs(claim)
        loc = f"权利要求{claim_idx}"
        claim_idx += 1
        for index, part in enumerate(parts):
            processed_text, highlight = process_pending_marks(part, copy_kind, loc, pending_marks)
            last = add_claim(
                doc,
                processed_text,
                claim_ppr if index == 0 else step_ppr,
                claim_rpr,
                registry,
                symbols,
                highlight,
            )
    if last is None:
        raise ValueError("权利要求为空")
    end_section(last, section_props[0])

    for item in specification:
        loc = f"说明书:{item.text[:20]}"
        processed_text, highlight = process_pending_marks(item.text, copy_kind, loc, pending_marks)
        last = add_spec_item(doc, item, registry, symbols, processed_text, highlight)
    end_section(last, section_props[1])

    for index, figure in enumerate(figures):
        last = add_figure(doc, figure, page_break_before=index > 0)
    end_section(last, section_props[2])

    abstract_text, highlight = process_pending_marks(abstract, copy_kind, "摘要", pending_marks)
    abstract_p = doc.add_paragraph(style="正文2")
    abstract_run = abstract_p.add_run(abstract_text)
    set_east_asia_font(abstract_run, "宋体")
    abstract_run.font.size = Pt(12)
    if highlight:
        apply_highlight(abstract_run)
    end_section(abstract_p, section_props[3])
    add_abstract_figure(doc, by_number[abstract_figure_number])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    title = next(item.text for item in specification if item.kind == "title")
    doc.core_properties.title = title
    doc.core_properties.subject = "中国发明专利申请文件"
    doc.save(output_path)

    pdf_path = None
    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = render_dir / f"{output_path.stem}.pdf"
    page_count = process_with_word(output_path, registry, pdf_path)
    package = inspect_package(
        output_path,
        len(registry.specs),
        heading_style_id,
        strong_style_id,
        template_numbering=template_numbering or None,
    )

    check = Document(output_path)
    headers = [
        section.header.paragraphs[0].text.strip() if section.header.paragraphs else ""
        for section in check.sections
    ]
    heading_texts = [p.text for p in check.paragraphs if p.style.name == "Heading 1"]
    if headers != EXPECTED_HEADERS:
        raise RuntimeError(f"输出页眉错误：{headers}")
    if package["strong_heading_run_count"] != len(heading_texts):
        raise RuntimeError(
            "说明书小标题未全部应用“要点”样式："
            f"标题 {len(heading_texts)}，要点样式 {package['strong_heading_run_count']}"
        )
    if len(check.inline_shapes) != len(figures) + 1:
        raise RuntimeError("说明书附图或摘要附图数量错误")

    rendered_pages: list[Path] = []
    if pdf_path is not None:
        rendered_pages = render_pdf_to_png(pdf_path, render_dir)
        if page_count is None or len(rendered_pages) != page_count:
            raise RuntimeError(
                f"PDF 页数与 PNG 页数不一致：PDF {page_count}，PNG {len(rendered_pages)}"
            )

    return {
        "schema": REPORT_SCHEMA,
        "status": (
            "STRUCTURE_VERIFIED_VISUAL_REVIEW_PENDING"
            if render_dir is not None
            else "STRUCTURE_VERIFIED"
        ),
        "output": str(output_path.resolve()),
        "output_sha256": file_sha256(output_path),
        "inputs": {
            "template": str(template_path.resolve()),
            "template_sha256": file_sha256(template_path),
            "source_dir": str(source_dir.resolve()),
            "artifacts": [
                {"artifact_id": "claims", "path": str(claims_path.resolve()), "sha256": file_sha256(claims_path)},
                {"artifact_id": "specification", "path": str(spec_path.resolve()), "sha256": file_sha256(spec_path)},
                {"artifact_id": "abstract", "path": str(abstract_path.resolve()), "sha256": file_sha256(abstract_path)},
                {"artifact_id": "figure_index", "path": str(figure_index_path.resolve()), "sha256": file_sha256(figure_index_path)},
            ] + [
                {"artifact_id": f"figure_{figure.number}", "path": str(figure.path.resolve()), "sha256": file_sha256(figure.path)}
                for figure in figures
            ],
        },
        "evidence_scope": {
            "proves": [
                "DOCX ZIP/XML、分节、页眉、样式、原生公式对象和嵌入图片数量满足本脚本合同",
                "输出 DOCX 绑定当前模板、四文书源文件和每幅嵌入图片的 SHA-256",
            ],
            "does_not_prove": [
                "申请文件的法律实体条件已经满足",
                "未请求视觉检查时的逐页视觉效果",
                "附图本身不存在视觉缺陷",
            ],
        },
        "math_generation": {
            "engine": "direct_omml",
            "platform": sys.platform,
            "word_automation_required": False,
        },
        "counts": {
            "claims": len(claims),
            "specification_items": len(specification),
            "headings_with_strong_style": package["strong_heading_run_count"],
            "native_word_math_objects": package["math_count"],
            "figures": len(figures),
            "inline_images": len(check.inline_shapes),
            "sections": len(check.sections),
            "pages": page_count,
        },
        "headers": headers,
        "abstract_figure": abstract_figure_number,
        "copy_kind": copy_kind,
        "pending_marks": pending_marks,
        "render": {
            "requested": render_dir is not None,
            "engine": (
                "microsoft_word" if render_dir is not None and sys.platform == "win32"
                else "libreoffice" if render_dir is not None
                else None
            ),
            "pdf": str(pdf_path.resolve()) if pdf_path else None,
            "png_pages": [str(path.resolve()) for path in rendered_pages],
            "visual_review_completed": False if render_dir is not None else None,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path, help="案件根目录")
    parser.add_argument("--template", type=Path, help="输出模板；默认仓库根目录模版.docx，不读取案件目录")
    parser.add_argument("--source-dir", type=Path, help="申请文件目录，默认 <case-dir>/02-申请文件")
    parser.add_argument("--output", type=Path, help="输出 DOCX 路径")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="报告目录；仅在视觉检查时同时保存 PDF/PNG",
    )
    parser.add_argument(
        "--visual-review",
        action="store_true",
        help="仅在用户明确要求视觉检查时使用：导出 PDF 并生成逐页 PNG",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help=argparse.SUPPRESS,  # 向后兼容；默认已不渲染
    )
    parser.add_argument(
        "--copy",
        choices=["review", "submission"],
        default="review",
        help="生成副本类型",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.resolve()
    template = resolve_application_template(args.template)
    source_dir = (args.source_dir or case_dir / "02-申请文件").resolve()
    title_items = parse_specification(source_dir / "说明书.md")
    title = next(item.text for item in title_items if item.kind == "title")
    safe_title = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", title).strip("_")
    output = (args.output or case_dir / f"{safe_title}-专利申请文件.docx").resolve()
    work_dir = (
        args.work_dir
        or case_dir / "03-审查工作区" / f"docx组装-{datetime.now():%Y%m%d-%H%M%S}"
    ).resolve()
    if args.visual_review and args.no_render:
        raise ValueError("--visual-review 与兼容参数 --no-render 不能同时使用")
    render_dir = work_dir / "render" if args.visual_review else None

    report = build_document(source_dir, template, output, render_dir, args.copy)
    work_dir.mkdir(parents=True, exist_ok=True)
    report_path = work_dir / "docx-assembly-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "output": str(output),
        "report": str(report_path),
        "status": report["status"],
        "visual_review_requested": report["render"]["requested"],
        **report["counts"],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
