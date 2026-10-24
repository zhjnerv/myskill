#!/usr/bin/env python3
"""从结构化技术特征生成度衍命令检索方案（首选）、CNIPA 人工检索清单和 BigQuery 查询。

该脚本不调用翻译服务，也不声称完成 CNIPA 官方库检索。英文关键词来自：
1. 输入中显式提供的 ``keywords_en``；
2. 本文件维护的确定性中英术语表。
无法映射的中文词会写入 ``untranslated_cn_terms``，要求人工补充而不是静默丢弃。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote
from typing import Any

SCHEMA_ID = "cn-patent-template-search/v1"
PUBLICATIONS_TABLE = "patents-public-data.patents.publications"
UYANIP_COMMAND_URL = "https://www.uyanip.com/search/command"
UYANIP_RESULT_TEMPLATE = "https://www.uyanip.com/result?fromMode=5&exp=%s&country=%s"
UYANIP_DETAIL_TEMPLATE = "https://www.uyanip.com/detail?aid=%s"
UYANIP_DEFAULT_COUNTRY = "AND GJ:(CN)"
UYANIP_FIELD_CODES = {
    "所有字段": "KEYWORD",
    "专利名称": "ZLMC",
    "摘要": "ZY",
    "权利要求": "QLYQ",
    "名称或摘要": "ZLMC_ZY",
    "IPC分类号": "IPC",
    "公开号": "GKH",
    "申请号": "SQH",
    "申请人": "SQREN",
    "发明人": "FMR",
    "法律状态": "FLZTA",
    "公开日": "GKR",
    "申请日": "SQR",
}

# 只覆盖高频基础术语；未命中的词必须显式留给人工处理。
TERM_GLOSSARY = {
    "人工智能": ["artificial intelligence"],
    "机器学习": ["machine learning"],
    "深度学习": ["deep learning"],
    "神经网络": ["neural network"],
    "大语言模型": ["large language model"],
    "图像处理": ["image processing"],
    "计算机视觉": ["computer vision"],
    "数据处理": ["data processing"],
    "数据库": ["database"],
    "分布式": ["distributed"],
    "一致性": ["consistency"],
    "共识": ["consensus"],
    "锁": ["lock"],
    "租约": ["lease"],
    "版本戳": ["version stamp"],
    "故障恢复": ["fault recovery"],
    "网络": ["network"],
    "通信": ["communication"],
    "无线": ["wireless"],
    "加密": ["encryption"],
    "认证": ["authentication"],
    "区块链": ["blockchain"],
    "存储": ["storage"],
    "缓存": ["cache"],
    "调度": ["scheduling"],
    "控制": ["control"],
    "传感器": ["sensor"],
    "机器人": ["robot"],
    "芯片": ["chip"],
    "半导体": ["semiconductor"],
    "电路": ["circuit"],
}

FIELD_CLASSIFICATIONS = {
    "网络": {"cpc": ["H04L"], "ipc": ["H04L"]},
    "数据处理": {"cpc": ["G06F"], "ipc": ["G06F"]},
    "人工智能": {"cpc": ["G06N"], "ipc": ["G06N"]},
    "机器学习": {"cpc": ["G06N20"], "ipc": ["G06N20"]},
    "图像处理": {"cpc": ["G06T"], "ipc": ["G06T"]},
    "通信": {"cpc": ["H04L", "H04W"], "ipc": ["H04L", "H04W"]},
    "存储": {"cpc": ["G06F3/06"], "ipc": ["G06F3/06"]},
    "控制": {"cpc": ["G05B"], "ipc": ["G05B"]},
    "医疗": {"cpc": ["A61B"], "ipc": ["A61B"]},
    "机器人": {"cpc": ["B25J"], "ipc": ["B25J"]},
}

SPLIT_RE = re.compile(r"[、，。；：;,:\n\r\t]+")
SPACE_RE = re.compile(r"\s+")
CLASSIFICATION_RE = re.compile(r"^[A-HY][0-9]{2}[A-Z](?:[0-9]+(?:/[0-9]+)?)?$", re.IGNORECASE)


class InputContractError(ValueError):
    """技术特征输入不满足检索生成合同。"""


def _normalize_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InputContractError(f"{field} 必须是字符串数组")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise InputContractError(f"{field}[{index}] 必须是非空字符串")
        result.append(_normalize_text(item))
    return result


def _text_field(data: dict[str, Any], field: str) -> str:
    value = data.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InputContractError(f"{field} 必须是字符串")
    return _normalize_text(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _derive_phrases(text: str) -> list[str]:
    """保守提取检索短语；不伪装成通用中文分词。"""

    phrases: list[str] = []
    for segment in SPLIT_RE.split(text):
        segment = _normalize_text(segment)
        if 2 <= len(segment) <= 40:
            phrases.append(segment)
        for term in TERM_GLOSSARY:
            if term in segment:
                phrases.append(term)
    return phrases


def extract_keywords(technical_features: dict[str, Any]) -> dict[str, list[str]]:
    """提取显式关键词、结构化部件词和可确定映射的英文词。"""

    explicit_cn = _string_list(technical_features.get("keywords_cn"), "keywords_cn")
    explicit_en = _string_list(technical_features.get("keywords_en"), "keywords_en")
    components = _string_list(technical_features.get("key_components"), "key_components")
    algorithms = _string_list(technical_features.get("algorithms"), "algorithms")

    texts = [
        _text_field(technical_features, "technical_problem"),
        _text_field(technical_features, "technical_solution"),
        _text_field(technical_features, "field"),
    ]
    keywords_cn = explicit_cn + components + algorithms
    for text in texts:
        keywords_cn.extend(_derive_phrases(text))
    keywords_cn = _unique(keywords_cn)

    mapped_en: list[str] = []
    mapped_cn: set[str] = set()
    for cn_term in keywords_cn:
        for source_term, english_terms in TERM_GLOSSARY.items():
            if source_term in cn_term:
                mapped_en.extend(english_terms)
                mapped_cn.add(cn_term)

    keywords_en = _unique([term.lower() for term in explicit_en + mapped_en])
    untranslated = [term for term in keywords_cn if term not in mapped_cn]
    return {
        "keywords_cn": keywords_cn,
        "keywords_en": keywords_en,
        "untranslated_cn_terms": untranslated,
    }


def _classification_list(value: Any, field: str) -> list[str]:
    codes = _string_list(value, field)
    normalized: list[str] = []
    for code in codes:
        compact = code.replace(" ", "").upper()
        if not CLASSIFICATION_RE.fullmatch(compact):
            raise InputContractError(f"{field} 中存在无效分类号：{code}")
        normalized.append(compact)
    return normalized


def map_to_cpc_ipc(features: dict[str, Any]) -> dict[str, list[str]]:
    """合并人工提供的分类号与保守的技术领域前缀建议。"""

    cpc_codes = _classification_list(features.get("cpc_codes"), "cpc_codes")
    ipc_codes = _classification_list(features.get("ipc_codes"), "ipc_codes")
    searchable_text = " ".join(
        [
            _text_field(features, "field"),
            _text_field(features, "technical_problem"),
            _text_field(features, "technical_solution"),
        ]
        + _string_list(features.get("key_components"), "key_components")
        + _string_list(features.get("algorithms"), "algorithms")
    )
    for keyword, codes in FIELD_CLASSIFICATIONS.items():
        if keyword in searchable_text:
            cpc_codes.extend(codes["cpc"])
            ipc_codes.extend(codes["ipc"])
    return {"cpc_codes": _unique(cpc_codes), "ipc_codes": _unique(ipc_codes)}


def assess_target_ipc(features: dict[str, Any], classifications: dict[str, list[str]]) -> dict[str, Any]:
    """记录目标技术方案 IPC 的判定状态与来源。

    自动领域映射只能生成检索建议，不能替代对技术方案主发明构思的 IPC 判断。
    只有 technical-features.json 显式提供了 ipc_codes，状态才是 determined，
    后续范本 IPC 加权选择脚本会拒绝 suggested/unresolved 状态。
    """

    explicit = _classification_list(features.get("ipc_codes"), "ipc_codes")
    codes = classifications["ipc_codes"]
    if explicit:
        return {
            "status": "determined",
            "ipc_codes": explicit,
            "explicit_ipc_codes": explicit,
            "suggested_ipc_codes": [code for code in codes if code not in explicit],
            "source": "technical_features_explicit",
            "basis": "由起草者基于技术问题、技术手段和主发明构思明确填写；领域映射结果仅作为旁路建议，不参与范本 IPC 相似度的最高匹配。",
        }
    if codes:
        return {
            "status": "suggested",
            "ipc_codes": codes,
            "explicit_ipc_codes": [],
            "source": "deterministic_field_mapping",
            "basis": "仅由技术领域关键词映射产生，必须人工判断后写回 technical-features.json 的 ipc_codes。",
        }
    return {
        "status": "unresolved",
        "ipc_codes": [],
        "explicit_ipc_codes": [],
        "source": "none",
        "basis": "未取得可用 IPC；不得进入范本选择。",
    }


def _bigquery_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def generate_bigquery_query(keywords: list[str], cpc_codes: list[str], limit: int = 100) -> str:
    """生成与项目现有 Google Patents Public Datasets schema 一致的查询。"""

    if not keywords and not cpc_codes:
        raise InputContractError("至少需要一个检索关键词或 CPC 分类号，禁止生成全表 1=1 查询")
    keyword_array = ", ".join(_bigquery_string(value) for value in keywords[:20])
    cpc_array = ", ".join(_bigquery_string(value) for value in cpc_codes[:20])
    return f"""DECLARE search_terms ARRAY<STRING> DEFAULT [{keyword_array}];
DECLARE cpc_prefixes ARRAY<STRING> DEFAULT [{cpc_array}];

SELECT
  publication_number,
  title_localized[SAFE_OFFSET(0)].text AS title,
  abstract_localized[SAFE_OFFSET(0)].text AS abstract,
  CAST(filing_date AS STRING) AS filing_date,
  CAST(grant_date AS STRING) AS grant_date,
  CAST(publication_date AS STRING) AS publication_date,
  application_number,
  family_id,
  country_code,
  cpc
FROM `{PUBLICATIONS_TABLE}`
WHERE country_code = 'CN'
  AND (
    ARRAY_LENGTH(search_terms) = 0
    OR EXISTS (
      SELECT 1
      FROM UNNEST(search_terms) AS term
      WHERE EXISTS (
        SELECT 1
        FROM UNNEST(title_localized) AS localized_title
        WHERE STRPOS(LOWER(localized_title.text), LOWER(term)) > 0
      )
      OR EXISTS (
        SELECT 1
        FROM UNNEST(abstract_localized) AS localized_abstract
        WHERE STRPOS(LOWER(localized_abstract.text), LOWER(term)) > 0
      )
    )
  )
  AND (
    ARRAY_LENGTH(cpc_prefixes) = 0
    OR EXISTS (
      SELECT 1
      FROM UNNEST(cpc) AS cpc_entry
      JOIN UNNEST(cpc_prefixes) AS prefix
        ON STARTS_WITH(cpc_entry.code, prefix)
    )
  )
ORDER BY publication_date DESC, publication_number DESC
LIMIT {limit};"""


def generate_cnipa_guide(
    keywords_cn: list[str],
    keywords_en: list[str],
    cpc_codes: list[str],
    ipc_codes: list[str],
    untranslated: list[str],
) -> str:
    """生成可留档的 CNIPA 人工检索步骤和能力边界。"""

    lines = [
        "CNIPA 专利检索及分析系统人工检索清单",
        "=" * 48,
        "1. 在发明名称、摘要、权利要求中分别执行关键词组合检索。",
        f"   中文关键词：{'；'.join(keywords_cn) if keywords_cn else '未提供'}",
        f"   英文关键词：{'；'.join(keywords_en) if keywords_en else '未提供'}",
        f"2. 叠加 IPC/CPC 前缀：{'；'.join(ipc_codes + cpc_codes) if ipc_codes or cpc_codes else '待人工确认'}",
        "3. 分别记录宽检索、技术特征组合检索、申请人/代理机构筛选的检索式和命中数。",
        "4. 从结果中同时选择对抗性文献和 1—3 篇优质撰写范本。",
        "5. 留档检索日期、数据库、检索式、命中数量、选中文献及筛选理由。",
    ]
    if untranslated:
        lines.extend(
            [
                "",
                "必须人工补充英文对应词（系统未确定映射）：",
                *[f"- {term}" for term in untranslated],
            ]
        )
    lines.extend(
        [
            "",
            "能力边界：本文件只生成检索建议，不证明已完成 CNIPA 官方库检索，也不支持“未发现即不存在现有技术”的结论。",
        ]
    )
    return "\n".join(lines)


def _uyanip_term_expr(values: list[str], field: str) -> str:
    return "%s:(%s)" % (field, " OR ".join(values))


def _uyanip_result_url(expr: str, country: str) -> str:
    return UYANIP_RESULT_TEMPLATE % (quote(expr, safe=""), quote(country, safe=""))


def generate_uyanip_plan(
    keywords_cn: list[str],
    determined_ipc: list[str],
    suggested_codes: list[str],
    untranslated: list[str],
) -> dict[str, Any]:
    """生成度衍（uyanip.com）命令检索方案，作为首选检索渠道。

    只生成检索式与可直开的结果页 URL，不执行检索、不代替人工留档。
    人工确定的 IPC 进入主检索式；仅由关键词映射得到的宽分类只作扩展建议，
    与范本相似度计算保持同一边界。
    """

    terms = [t for t in keywords_cn if t][:8]
    determined = [c for c in determined_ipc if c][:3]
    suggested = [c for c in suggested_codes if c and c not in determined][:3]
    expressions: list[dict[str, str]] = []
    if terms:
        wide = _uyanip_term_expr(terms, "KEYWORD")
        expressions.append({
            "name": "wide_keyword",
            "expr": wide,
            "purpose": "keyword_discovery",
            "result_url": _uyanip_result_url(wide, UYANIP_DEFAULT_COUNTRY),
        })
        if len(terms) >= 2:
            narrow = "%s AND %s" % (
                _uyanip_term_expr(terms[:1], "ZLMC_ZY"),
                _uyanip_term_expr(terms[1:2], "ZLMC_ZY"),
            )
            expressions.append({
                "name": "name_abstract_narrow",
                "expr": narrow,
                "purpose": "keyword_narrow",
                "result_url": _uyanip_result_url(narrow, UYANIP_DEFAULT_COUNTRY),
            })
    for code in determined:
        scoped = "IPC:(%s)" % code if not terms else "IPC:(%s) AND %s" % (code, _uyanip_term_expr(terms, "KEYWORD"))
        slug = re.sub(r"[^0-9A-Za-z]+", "", code) or "code"
        expressions.append({
            "name": "ipc_scoped_" + slug,
            "expr": scoped,
            "purpose": "determined_ipc",
            "result_url": _uyanip_result_url(scoped, UYANIP_DEFAULT_COUNTRY),
        })
    for code in suggested:
        broad = "IPC:(%s)" % code if not terms else "IPC:(%s) AND %s" % (code, _uyanip_term_expr(terms, "KEYWORD"))
        slug = re.sub(r"[^0-9A-Za-z]+", "", code) or "code"
        expressions.append({
            "name": "ipc_broad_" + slug,
            "expr": broad,
            "purpose": "broad_expansion",
            "result_url": _uyanip_result_url(broad, UYANIP_DEFAULT_COUNTRY),
        })
    return {
        "priority": 1,
        "channel": "uyanip_command_search",
        "channel_name": "度衍命令检索（首选）",
        "command_url": UYANIP_COMMAND_URL,
        "result_url_template": UYANIP_RESULT_TEMPLATE,
        "detail_url_template": UYANIP_DETAIL_TEMPLATE,
        "country_filter": UYANIP_DEFAULT_COUNTRY,
        "country_note": "默认检索中国；其他国家用 AND GJ:(US)、AND GJ:(WO) 等，代码取专利国别码。",
        "boolean_operators": ["AND", "OR", "NOT"],
        "boolean_note": "AND 收窄、OR 扩大、NOT 排除，支持括号分组与嵌套；关键词支持前缀通配符 *。",
        "field_codes": UYANIP_FIELD_CODES,
        "expression_policy": "purpose=determined_ipc 为人工确定分类的主检索式；purpose=broad_expansion 仅用于扩展，不得据宽分类判定范本相似度。",
        "expressions": expressions,
        "detail_text_note": "详情页 /detail?aid=<申请号> 可直接读取权利要求与说明书正文；附图取 img[src*=picnew.duyandb.com]，PDF 下载按钮为 #pdf-download。",
        "automation_note": "所有 window.open 类操作要求标签页在前台（先 bringToFront），否则静默失败；否则改用结果页 URL 直开。",
        "untranslated_cn_terms": untranslated,
        "not_executed_notice": "本方案只生成检索式与 URL，不证明已完成度衍检索；命中数、日期与筛选理由须人工留档。",
    }


def build_search_manifest(features: dict[str, Any], *, limit: int = 100) -> dict[str, Any]:
    if not isinstance(features, dict):
        raise InputContractError("技术特征输入必须是 JSON 对象")
    keywords = extract_keywords(features)
    classifications = map_to_cpc_ipc(features)
    target_ipc = assess_target_ipc(features, classifications)
    all_search_terms = _unique(keywords["keywords_cn"] + keywords["keywords_en"])
    bigquery_query = generate_bigquery_query(
        all_search_terms,
        classifications["cpc_codes"],
        limit=limit,
    )
    uyanip_plan = generate_uyanip_plan(
        keywords["keywords_cn"],
        [c for c in (target_ipc.get("ipc_codes") or []) if c],
        [c for c in (target_ipc.get("suggested_ipc_codes") or []) if c],
        keywords["untranslated_cn_terms"],
    )
    guide = generate_cnipa_guide(
        keywords["keywords_cn"],
        keywords["keywords_en"],
        classifications["cpc_codes"],
        classifications["ipc_codes"],
        keywords["untranslated_cn_terms"],
    )
    return {
        "schema_id": SCHEMA_ID,
        "schema": "search-query/v1",
        "keywords": keywords,
        "classifications": classifications,
        "target_ipc": target_ipc,
        "uyanip_plan": uyanip_plan,
        "cnipa_guide": guide,
        "bigquery_table": PUBLICATIONS_TABLE,
        "bigquery_query": bigquery_query,
        "manual_actions_required": [
            "先用度衍命令检索（uyanip_plan，首选渠道）执行并留档命中数与筛选理由",
            "补充 untranslated_cn_terms 的英文同义词",
            "在 CNIPA 官方系统执行并留档检索",
            (
                "目标 IPC 已显式判定；在范本选择报告中核对候选 IPC 相似度"
                if target_ipc["status"] == "determined"
                else "先判断目标技术方案 IPC，并写回 technical-features.json 的 ipc_codes"
            ),
            "候选范本 IPC 优先通过 EPO OPS 获取，并保留降级来源",
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中国专利范本检索式生成器")
    parser.add_argument("--features", required=True, help="技术特征 JSON 文件")
    parser.add_argument("--output", required=True, help="检索清单 JSON 输出路径")
    parser.add_argument("--limit", type=int, default=100, help="BigQuery 最大返回条数（1—1000）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not 1 <= args.limit <= 1000:
        print("错误：--limit 必须在 1—1000 之间", file=sys.stderr)
        return 2

    input_path = Path(args.features)
    try:
        features = json.loads(input_path.read_text(encoding="utf-8"))
        manifest = build_search_manifest(features, limit=args.limit)
    except FileNotFoundError:
        print(f"错误：技术特征文件不存在：{input_path}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"错误：技术特征文件不是有效 UTF-8：{input_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"错误：技术特征 JSON 解析失败：{exc}", file=sys.stderr)
        return 2
    except InputContractError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] 检索清单已生成：{output_path}")
    print(
        "[INFO] CNIPA 官方库检索仍需人工执行；未映射中文词："
        f"{len(manifest['keywords']['untranslated_cn_terms'])} 项"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
