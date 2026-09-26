#!/usr/bin/env python3
"""
范本风格分析器 - 从范本专利提取写作风格特征

输入：
  - 权利要求书文本文件
  - 说明书文本文件
  - 可选：摘要文本文件

输出：
  - template-style-guide.json（符合 schema）
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from template_style_contract import StyleGuideValidationError, validate_style_guide

# 中文序数与阿拉伯数字两种写法。范本实际使用"第一实施例""第二实施方式"，
# 早期只匹配"实施例N"的正则在这两份范本上命中为 0，导致实施例数被误报。
_ORDINAL = r"[一二三四五六七八九十百]+|\d+"

# 与中文序数连写会构成其他词的字符（"实施方式一致"里的"致"）。
# 只用于内联提及，标题形态由行锚定判别，不受此列表影响。
_FALSE_COMPOUND_TAIL = "致样般体同起旦直定些者"

# 分节标题形态：独占一行，允许 Markdown 井号前缀和结尾标点。
EMBODIMENT_HEADING_RE = re.compile(
    rf"^[ \t]*(?:#{{1,6}}[ \t]*)?"
    rf"(?:第[ \t]*(?P<pre>{_ORDINAL})[ \t]*(?:实施例|实施方式)"
    rf"|(?:实施例|实施方式)[ \t]*(?P<post>{_ORDINAL}))"
    rf"[ \t]*[:：、.．]?[ \t]*$",
    re.MULTILINE,
)

# 内联提及形态：出现在句子中间的实施例编号。
EMBODIMENT_INLINE_RE = re.compile(
    rf"(?:第[ \t]*(?P<pre>{_ORDINAL})[ \t]*(?:实施例|实施方式)"
    rf"|(?:实施例|实施方式)[ \t]*(?P<post>{_ORDINAL})(?![{_FALSE_COMPOUND_TAIL}]))"
)

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def normalize_ordinal(text: str) -> str:
    """把"一""十二""3"归一为可比较的序数键；无法解析时原样返回。"""

    token = text.strip()
    if token.isdigit():
        return str(int(token))
    if not token:
        return ""
    # 仅覆盖专利文本实际会出现的一至九十九，超出范围保留原文避免错误合并。
    if token in _CN_DIGITS:
        return str(_CN_DIGITS[token])
    if token == "十":
        return "10"
    if token.startswith("十") and token[1:] in _CN_DIGITS:
        return str(10 + _CN_DIGITS[token[1:]])
    if token.endswith("十") and token[:-1] in _CN_DIGITS:
        return str(_CN_DIGITS[token[:-1]] * 10)
    if len(token) == 3 and token[1] == "十" and token[0] in _CN_DIGITS and token[2] in _CN_DIGITS:
        return str(_CN_DIGITS[token[0]] * 10 + _CN_DIGITS[token[2]])
    return token


def _collect_ordinals(pattern: re.Pattern[str], text: str) -> list[str]:
    """按出现顺序返回去重后的实施例序数键。"""

    seen: list[str] = []
    for match in pattern.finditer(text):
        raw = match.group("pre") or match.group("post") or ""
        key = normalize_ordinal(raw)
        if key and key not in seen:
            seen.append(key)
    return seen


class ClaimsAnalyzer:
    """权利要求结构分析器"""

    def analyze(self, claims_text: str) -> dict:
        """
        分析权利要求结构

        返回：
        {
            "independent_claims_count": int,
            "dependent_claims_count": int,
            "total_claims": int,
            "dependency_pattern": "tree|linear|mixed",
            "avg_independent_claim_chars": int,
            "avg_dependent_claim_chars": int,
            "max_independent_claim_chars": int,
            "min_independent_claim_chars": int,
            "claim_preamble_style": [...],
            "feature_introduction_pattern": str,
            "claim_structure_notes": str
        }
        """
        claims = self._parse_claims(claims_text)

        if not claims:
            return {
                "independent_claims_count": 0,
                "dependent_claims_count": 0,
                "total_claims": 0,
                "dependency_pattern": "unknown",
                "avg_independent_claim_chars": 0,
                "avg_dependent_claim_chars": 0,
                "max_independent_claim_chars": 0,
                "min_independent_claim_chars": 0,
                "claim_preamble_style": [],
                "feature_introduction_pattern": "",
                "claim_structure_notes": "未能解析权利要求"
            }

        independent = [c for c in claims if c["is_independent"]]
        dependent = [c for c in claims if not c["is_independent"]]

        independent_chars = [len(c["text"]) for c in independent]
        dependent_chars = [len(c["text"]) for c in dependent]

        # 分析特征部分引入方式
        feature_patterns = []
        for claim in claims:
            if "其特征在于" in claim["text"]:
                feature_patterns.append("其特征在于")
            elif "其改进之处在于" in claim["text"]:
                feature_patterns.append("其改进之处在于")
            elif "包括" in claim["text"] and "特征" not in claim["text"]:
                feature_patterns.append("包括")

        feature_intro = Counter(feature_patterns).most_common(1)
        feature_intro_pattern = feature_intro[0][0] if feature_intro else "其特征在于"

        # 分析前序部分风格
        preamble_patterns = self._extract_preamble_patterns(independent)

        # 检测依赖模式
        dependency_pattern = self._detect_dependency_pattern(claims)

        return {
            "independent_claims_count": len(independent),
            "dependent_claims_count": len(dependent),
            "total_claims": len(claims),
            "dependency_pattern": dependency_pattern,
            "avg_independent_claim_chars": round(sum(independent_chars) / len(independent_chars), 1) if independent_chars else 0,
            "avg_dependent_claim_chars": round(sum(dependent_chars) / len(dependent_chars), 1) if dependent_chars else 0,
            "max_independent_claim_chars": max(independent_chars) if independent_chars else 0,
            "min_independent_claim_chars": min(independent_chars) if independent_chars else 0,
            "claim_preamble_style": preamble_patterns,
            "feature_introduction_pattern": feature_intro_pattern,
            "claim_structure_notes": f"共{len(claims)}项权利要求，其中独立权利要求{len(independent)}项，从属权利要求{len(dependent)}项。依赖结构为{dependency_pattern}模式。"
        }

    def _parse_claims(self, text: str) -> list[dict]:
        """解析权利要求项

        返回 [{"num": 1, "is_independent": True, "text": "...", "refs": []}, ...]
        """
        claims = []

        # 按行分割并处理
        lines = text.split('\n')
        current_claim = None
        current_text = []

        for line in lines:
            # 检测权利要求编号：1. 或 1、 或 1. （各种格式）
            match = re.match(r'^\s*(\d+)\s*[.、]\s*(.*)', line)
            if match:
                # 保存前一个权利要求
                if current_claim is not None:
                    current_claim["text"] = '\n'.join(current_text).strip()
                    claims.append(current_claim)

                # 开始新权利要求
                claim_num = int(match.group(1))
                rest = match.group(2)

                # 检测是否为从属权利要求
                is_independent = not self._is_dependent_claim(rest)

                # 提取引用关系
                refs = self._extract_references(rest)

                current_claim = {
                    "num": claim_num,
                    "is_independent": is_independent,
                    "refs": refs,
                    "text": ""
                }
                current_text = [rest]
            elif current_claim is not None:
                # 继续当前权利要求的文本
                if line.strip():
                    current_text.append(line)

        # 保存最后一个权利要求
        if current_claim is not None:
            current_claim["text"] = '\n'.join(current_text).strip()
            claims.append(current_claim)

        return claims

    _DEPENDENCY_RE = re.compile(
        r"^\s*(?:根据|按照|如)\s*权利要求\s*"
        r"(?P<refs>[0-9０-９、,，或和至到\-—~～]+?)"
        r"(?:中的)?(?:任一项)?\s*所述"
    )

    def _is_dependent_claim(self, text: str) -> bool:
        """判断是否为从属权利要求。

        中国申请文件中常见“根据权利要求…”“如权利要求…”和
        “按照权利要求…”三种起始句式。只在权利要求开头识别，避免把独立
        装置权利要求中“包括权利要求1-3任一项所述组件”误判为从属项。
        """

        return bool(self._DEPENDENCY_RE.search(text))

    def _extract_references(self, text: str) -> list[int]:
        """提取从属权利要求引用号，并展开“1-3”“1至3”范围。"""

        match = self._DEPENDENCY_RE.search(text)
        if not match:
            return []
        trans = str.maketrans("０１２３４５６７８９", "0123456789")
        clause = match.group("refs").translate(trans)
        refs: set[int] = set()
        for start, end in re.findall(r"(\d+)\s*(?:-|—|~|～|至|到)\s*(\d+)", clause):
            left, right = int(start), int(end)
            refs.update(range(min(left, right), max(left, right) + 1))
        clause_without_ranges = re.sub(
            r"\d+\s*(?:-|—|~|～|至|到)\s*\d+", "", clause
        )
        refs.update(int(value) for value in re.findall(r"\d+", clause_without_ranges))
        return sorted(refs)

    def _detect_dependency_pattern(self, claims: list[dict]) -> str:
        """检测引用模式

        tree: 从属权利要求引用多个不同的独权
        linear: 从属权利要求形成长链（A->B->C->D）
        mixed: 两种模式混合
        """
        dependent_claims = [c for c in claims if not c["is_independent"]]

        if not dependent_claims:
            return "linear"  # 只有独权

        # 检查是否存在线性链
        has_linear_chain = False
        for claim in dependent_claims:
            if len(claim["refs"]) == 1 and not claims[claim["refs"][0] - 1]["is_independent"]:
                has_linear_chain = True
                break

        # 检查是否存在树形结构（多个从属引用同一个独权）
        has_tree_structure = False
        for claim in dependent_claims:
            if len(claim["refs"]) > 1:
                has_tree_structure = True
                break

        # 检查多个从属引用同一个权利要求的情况
        ref_counts = Counter()
        for claim in dependent_claims:
            for ref in claim["refs"]:
                ref_counts[ref] += 1

        if any(count > 1 for count in ref_counts.values()):
            has_tree_structure = True

        if has_tree_structure and has_linear_chain:
            return "mixed"
        elif has_tree_structure:
            return "tree"
        else:
            return "linear"

    def _extract_preamble_patterns(self, independent_claims: list[dict]) -> list[str]:
        """提取独权前序部分的常见表述"""
        patterns = []

        for claim in independent_claims[:5]:  # 取前5个样本
            text = claim["text"]
            # 提取第一句话作为前序
            first_sentence = text.split('。')[0] if '。' in text else text[:100]
            if first_sentence not in patterns and len(first_sentence) > 10:
                patterns.append(first_sentence)

        return patterns[:3]  # 返回前3个模式


class SpecificationAnalyzer:
    """说明书布局分析器"""

    def analyze(self, spec_text: str) -> dict:
        """
        分析说明书布局和语言风格

        返回结构见 schema
        """
        chapters = self._extract_chapters(spec_text)
        paragraphs = self._extract_paragraphs(spec_text)
        embodiments = self._analyze_embodiments(spec_text, chapters.get("具体实施方式", ""))

        paragraph_chars = [len(p) for p in paragraphs if p.strip()]

        description_mode = self._detect_description_mode(chapters.get("具体实施方式", ""))
        terminology = self._extract_terminology(spec_text)
        sentence_patterns = self._extract_sentence_patterns(spec_text)

        implementation_text = chapters.get("具体实施方式", "")

        return {
            "embodiments_count": embodiments["count"],
            "embodiment_organization": embodiments["organization"],
            "embodiment_detection_notes": embodiments["notes"],
            "avg_paragraph_chars": round(sum(paragraph_chars) / len(paragraph_chars), 1) if paragraph_chars else 0,
            "max_paragraph_chars": max(paragraph_chars) if paragraph_chars else 0,
            "min_paragraph_chars": min(paragraph_chars) if paragraph_chars else 0,
            "technical_field_chars": len(chapters.get("技术领域", "")),
            "background_chars": len(chapters.get("背景技术", "")),
            "invention_content_chars": len(chapters.get("发明内容", "")),
            "implementation_chars": len(implementation_text),
            "drawings_description_chars": len(chapters.get("附图说明", "")),
            "description_mode": description_mode,
            "embodiment_description_pattern": "如图N所示" if "如图" in implementation_text else "叙述式",
            "terminology_samples": terminology[:20],
            "sentence_patterns": sentence_patterns[:5],
            "paragraph_structure_notes": f"共{len(paragraphs)}个段落，平均长度{round(sum(paragraph_chars) / len(paragraph_chars), 0) if paragraph_chars else 0}字符。"
        }

    def _extract_chapters(self, text: str) -> dict:
        """提取五个法定章节"""
        chapters = {}

        chapter_names = ["技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式"]

        for chapter in chapter_names:
            # 匹配章节标题（支持不同的标记方式）
            pattern = rf'(?:#+\s*)?{chapter}(?:\n|$)'
            match = re.search(pattern, text)

            if match:
                start = match.end()

                # 找到下一个章节的开始
                remaining_text = text[start:]
                next_chapter_match = None
                for other_chapter in chapter_names:
                    if other_chapter != chapter:
                        m = re.search(rf'(?:#+\s*)?{other_chapter}(?:\n|$)', remaining_text)
                        if m and (next_chapter_match is None or m.start() < next_chapter_match.start()):
                            next_chapter_match = m

                end = (
                    start + next_chapter_match.start()
                    if next_chapter_match
                    else len(text)
                )

                chapters[chapter] = text[start:end].strip()

        return chapters

    def _extract_paragraphs(self, text: str) -> list[str]:
        """提取段落"""
        # 以双换行符分割
        paragraphs = text.split('\n\n')
        return paragraphs

    def _analyze_embodiments(self, text: str, implementation_text: str) -> dict:
        """识别实施例数量与组织方式。

        实施例数量只回答"有几个编号"，回答不了"说明书长什么形态"——这正是
        早期只输出一个整数时的缺口：范本用单一实施方式贯穿全文，起草端却按
        实施例数拆成多节。因此这里同时给出 organization 枚举：

        - ``sectioned``：实施例以独立标题分节，各节平行展开；
        - ``single_flow``：只有一条实施方式脉络，编号仅在行文中提及；
        - ``none``：全文没有实施例编号。

        判据是"是否存在实施例标题行"，不是"是否出现实施例三个字"。
        """

        scope = implementation_text or text
        headings = _collect_ordinals(EMBODIMENT_HEADING_RE, scope)
        inline = _collect_ordinals(EMBODIMENT_INLINE_RE, scope)

        if headings:
            merged = list(headings)
            merged.extend(key for key in inline if key not in merged)
            return {
                "count": len(merged),
                "organization": "sectioned",
                "notes": (
                    f"识别到 {len(headings)} 个实施例标题行"
                    f"（序数 {'、'.join(headings)}）"
                    f"，另有 {len(merged) - len(headings)} 个仅在正文提及的编号。"
                ),
            }
        if inline:
            return {
                "count": len(inline),
                "organization": "single_flow",
                "notes": (
                    f"未识别到实施例标题行；正文提及 {len(inline)} 个实施例编号"
                    f"（序数 {'、'.join(inline)}），按单一实施方式贯穿处理。"
                ),
            }
        return {
            "count": 0,
            "organization": "none",
            "notes": "未识别到任何实施例编号，具体实施方式为不编号的连续叙述。",
        }

    def _detect_description_mode(self, implementation_text: str) -> str:
        """检测技术描述模式

        process_oriented: 偏流程式（"首先...然后...最后..."）
        structure_oriented: 偏结构式（"包括...其中..."）
        mixed: 混合
        """
        process_keywords = ["首先", "其次", "然后", "接着", "最后", "步骤", "过程"]
        structure_keywords = ["包括", "包含", "由...组成", "其中", "构成", "组成"]

        process_count = sum(implementation_text.count(kw) for kw in process_keywords)
        structure_count = sum(implementation_text.count(kw) for kw in structure_keywords)

        if process_count > structure_count * 1.5:
            return "process_oriented"
        elif structure_count > process_count * 1.5:
            return "structure_oriented"
        else:
            return "mixed"

    def _extract_terminology(self, text: str) -> list[str]:
        """提取高频术语"""
        # 简单的方法：提取2-8字的高频词组
        # 这里使用正则表达式提取名词和名词短语

        # 分割成词
        words = re.findall(r'[一-龥]{2,8}', text)

        # 停用词列表
        stopwords = {
            "的", "和", "是", "了", "在", "不", "有", "一", "这", "为",
            "以", "及", "其", "所", "被", "来", "到", "对", "中", "于",
            "而", "与", "等", "也", "由", "或", "个", "两", "没", "没有",
            "下", "上", "就", "只", "又", "很", "过", "都", "但", "则",
            "更", "还", "已", "可", "其他", "同时", "另外", "因此"
        }

        # 统计词频
        word_freq = Counter(words)

        # 过滤停用词，返回前20个高频词
        result = [word for word, count in word_freq.most_common(40) if word not in stopwords and len(word) >= 2]

        return result[:20]

    def _extract_sentence_patterns(self, text: str) -> list[str]:
        """提取句式模式"""
        sentences = text.split('。')
        patterns = []

        pattern_templates = [
            r'如图\d+所示',
            r'根据.*所述',
            r'其中.*为',
            r'(\w+)是',
            r'(\w+)包括',
        ]

        for sentence in sentences[:100]:  # 取前100个句子
            sentence = sentence.strip()
            if (
                20 < len(sentence) < 200
                and any(re.search(pattern, sentence) for pattern in pattern_templates)
                and sentence not in patterns
            ):
                patterns.append(sentence)
                if len(patterns) >= 5:
                    break

        return patterns


class DrawingAnalyzer:
    """附图风格分析器"""

    def analyze(self, spec_text: str) -> dict:
        """
        从"附图说明"章节提取附图风格
        """
        drawing_section = self._extract_drawing_section(spec_text)
        total_drawings = self._count_drawings(drawing_section)
        drawing_types = self._extract_drawing_types(drawing_section)
        reference_sign_pattern = self._extract_reference_sign_pattern(drawing_section)
        reference_signs = self._extract_reference_signs(drawing_section)

        # 统计标记分布
        distribution = {
            "100_series": sum(1 for s in reference_signs if 100 <= s < 200),
            "200_series": sum(1 for s in reference_signs if 200 <= s < 300),
            "other": sum(1 for s in reference_signs if s < 100 or s >= 300)
        }

        return {
            "total_drawings": total_drawings,
            "drawing_types": drawing_types,
            "reference_sign_pattern": reference_sign_pattern,
            "reference_sign_count": len(reference_signs),
            "reference_sign_distribution": distribution,
            "drawing_notes": f"共{total_drawings}幅附图，包含{len(drawing_types)}种类型，使用附图标记{len(reference_signs)}个。"
        }

    def _extract_drawing_section(self, text: str) -> str:
        """提取附图说明章节"""
        pattern = r'(?:#+\s*)?附图说明(?:\n|$)(.*?)(?:(?:#+\s*)?具体实施方式|$)'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else ""

    def _count_drawings(self, drawing_section: str) -> int:
        """计算图号数量"""
        # 匹配 "图1", "图 1", "图1是" 等
        pattern = r'图\s*(\d+)'
        matches = re.findall(pattern, drawing_section)
        return len(set(matches))  # 去重

    def _extract_drawing_types(self, drawing_section: str) -> list[str]:
        """识别附图类型"""
        types = set()

        type_keywords = [
            "示意图", "流程图", "时序图", "结构图", "框图",
            "电路图", "系统图", "原理图", "分解图", "详图"
        ]

        for keyword in type_keywords:
            if keyword in drawing_section:
                types.add(keyword)

        return list(types)

    def _extract_reference_sign_pattern(self, drawing_section: str) -> str:
        """识别附图标记编号模式"""
        # 查找形如 "100-", "200-", "10-", "20-" 等的模式
        pattern = r'(\d+)\s*[-−]\s*[^\s、。，]'
        matches = re.findall(pattern, drawing_section)

        if not matches:
            return "unknown"

        # 提取首位数字
        first_digits = [int(m[0]) // 100 for m in matches]
        counter = Counter(first_digits)

        if counter[1] > counter[2] > 0:  # 既有100系又有200系
            return "100系列层级：主体组件及其子组件"
        elif counter[1] > 0:  # 主要是100系
            return "100系列单层或多层：100为主体，110/120为子组件"
        else:
            return "mixed_series"

    def _extract_reference_signs(self, drawing_section: str) -> list[int]:
        """提取所有附图标记号"""
        pattern = r'(\d{2,3})\s*[-−]\s*[^\s、。，]'
        matches = re.findall(pattern, drawing_section)
        signs = [int(m) for m in matches]
        return sorted(set(signs))


class AbstractAnalyzer:
    """摘要风格分析器"""

    def analyze(self, abstract_text: str) -> dict:
        """
        分析摘要风格
        """
        if not abstract_text or not abstract_text.strip():
            return {
                "chars_count": 0,
                "structure_pattern": "unknown",
                "opening_phrase": "",
                "abstract_notes": "无摘要文本"
            }

        chars_count = len(abstract_text)

        # 使用稳定枚举描述结构，不把自由文本写进合同字段。
        has_problem = any(term in abstract_text for term in ("技术问题", "问题在于", "解决"))
        has_solution = any(term in abstract_text for term in ("技术方案", "方案是", "包括", "提供"))
        has_effect = any(term in abstract_text for term in ("技术效果", "效果", "提高", "降低"))
        has_field = any(term in abstract_text for term in ("技术领域", "涉及"))
        structure_pattern = "unknown"
        if has_problem and has_solution and has_effect:
            structure_pattern = "technical_problem+technical_solution+technical_effect"
        elif has_field and has_solution and has_effect:
            structure_pattern = "technical_field+technical_solution+technical_effect"
        elif has_solution and has_effect:
            structure_pattern = "technical_solution+technical_effect"

        # 提取开头短语
        opening_phrase = ""
        sentences = abstract_text.split('。')
        if sentences:
            first_sentence = sentences[0][:30]
            opening_phrase = first_sentence

        return {
            "chars_count": chars_count,
            "structure_pattern": structure_pattern,
            "opening_phrase": opening_phrase,
            "abstract_notes": f"摘要长度{chars_count}字符，结构模式为{structure_pattern}。"
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="范本专利风格分析器")
    parser.add_argument("--patent-number", required=True, help="范本专利号")
    parser.add_argument("--claims", required=True, help="权利要求书文本文件路径")
    parser.add_argument("--specification", required=True, help="说明书文本文件路径")
    parser.add_argument("--abstract", help="摘要文本文件路径（可选）")
    parser.add_argument("--output", required=True, help="输出风格指南JSON路径")

    args = parser.parse_args()

    # 读取输入文件
    try:
        claims_text = Path(args.claims).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"错误：权利要求书文件不存在：{args.claims}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"错误：权利要求书不是有效 UTF-8：{args.claims}", file=sys.stderr)
        return 2

    try:
        spec_text = Path(args.specification).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"错误：说明书文件不存在：{args.specification}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"错误：说明书不是有效 UTF-8：{args.specification}", file=sys.stderr)
        return 2

    abstract_text = ""
    if args.abstract:
        try:
            abstract_text = Path(args.abstract).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"错误：摘要文件不存在：{args.abstract}", file=sys.stderr)
            return 2
        except UnicodeDecodeError:
            print(f"错误：摘要不是有效 UTF-8：{args.abstract}", file=sys.stderr)
            return 2

    # 执行分析
    claims_analyzer = ClaimsAnalyzer()
    spec_analyzer = SpecificationAnalyzer()
    drawing_analyzer = DrawingAnalyzer()
    abstract_analyzer = AbstractAnalyzer()

    claims_style = claims_analyzer.analyze(claims_text)
    spec_style = spec_analyzer.analyze(spec_text)
    drawing_style = drawing_analyzer.analyze(spec_text)
    abstract_style = abstract_analyzer.analyze(abstract_text) if abstract_text else {}

    # 组装风格指南
    style_guide = {
        "schema_id": "cn-patent-template-style/v1",
        "template_patent": args.patent_number,
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "claims_style": claims_style,
        "specification_style": spec_style,
        "drawing_style": drawing_style,
        "abstract_style": abstract_style,
        "special_formatting": {
            "formula_count": spec_text.count("∑") + spec_text.count("∏") + spec_text.count("∫"),
            "table_in_spec": "表格" in spec_text or "Table" in spec_text,
            "list_usage": "- " in spec_text or "• " in spec_text,
            "equation_format": "独立成段"
        },
        "terminology_consistency": {
            "key_terms": [],
            "term_variations": ""
        },
        "quality_indicators": {
            "patent_status": "unknown",
            "citation_count": -1,
            "examiner_remarks": ""
        },
        "extraction_methodology": {
            "tools_used": "Python正则表达式与统计分析",
            "confidence_level": "medium",
            "limitations": "基于句法和结构层面的特征提取，不进行语义理解。范本学习用于模仿写作方式和布局，但技术内容必须来自本申请的实际发明。"
        },
        "usage_notes": {
            "applicable_scope": "中国发明专利申请，相同或相近的技术领域",
            "mimicry_boundary": "本指南用于学习撰写方式、权利要求结构、说明书布局和用语风格。技术内容、权利要求限定和技术特征必须来自本申请的实际发明和现有技术检索结果，不得凭范本臆造未实现的技术特征。",
            "disclaimer": "本分析是句法与结构层面的特征提取，不代表对范本专利授权前景、技术价值或法律有效性的任何判断。"
        }
    }

    try:
        validate_style_guide(style_guide)
    except StyleGuideValidationError as exc:
        print(f"错误：风格分析结果不符合 v1 合同：{exc}", file=sys.stderr)
        return 1

    # 原子写入不属于本脚本职责，但必须先创建目标目录并输出稳定 UTF-8 文本。
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(style_guide, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[OK] Style analysis completed: {args.output}")
    print("   - Independent claims: {} items".format(claims_style['independent_claims_count']))
    print("   - Dependent claims: {} items".format(claims_style['dependent_claims_count']))
    print("   - Dependency pattern: {}".format(claims_style['dependency_pattern']))
    print("   - Embodiments: {} ({})".format(
        spec_style['embodiments_count'], spec_style['embodiment_organization']
    ))
    print("   - Embodiment notes: {}".format(spec_style['embodiment_detection_notes']))
    print("   - Description mode: {}".format(spec_style['description_mode']))
    print("   - Drawings: {} figures".format(drawing_style['total_drawings']))
    print("   - Reference signs: {} marks".format(drawing_style['reference_sign_count']))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
