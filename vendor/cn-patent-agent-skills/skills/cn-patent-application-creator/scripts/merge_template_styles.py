#!/usr/bin/env python3
"""把多份范本风格指南合成为一份，并强制人工覆盖留下审计。

问题背景：上一轮的 composite-template-style-guide.json 是手写文件，不在任何
脚本的输出路径上。机器分析出的实施例数是 0，手写文件把它填成 6——与附图数
相同——起草端据此把说明书拆成 6 个平行实施例。手改数字而不留审计，就是
这类错误能一路走到起草端的通道。

本脚本承担两件事：

1. 合成：多份指南的数值取中位数、枚举取多数、列表按出现顺序去重合并；
   组织方式取最保守值（none < single_flow < sectioned），因为把单脉络范本
   误判成分节范本的代价远大于反向。
2. 审计：任何偏离合成结果的人工值必须经 --override 显式提供，并逐条写入
   provenance.manual_overrides，携带机器值、人工值、理由和依据。

退出码：0 成功；2 输入或覆盖不合法；3 路径/编码/JSON 无效。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from template_style_contract import StyleGuideValidationError, validate_style_guide

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_INPUT_ERROR = 3

# 组织方式的保守序：把单脉络范本误判为分节范本会直接导致说明书被拆成
# 范本没有的平行实施例，因此合成时取最保守（最小）的那个。
ORGANIZATION_ORDER = {"none": 0, "single_flow": 1, "sectioned": 2}

NUMERIC_CLAIM_FIELDS = (
    "avg_independent_claim_chars",
    "avg_dependent_claim_chars",
    "max_independent_claim_chars",
    "min_independent_claim_chars",
)
NUMERIC_SPEC_FIELDS = (
    "avg_paragraph_chars",
    "max_paragraph_chars",
    "min_paragraph_chars",
    "technical_field_chars",
    "background_chars",
    "invention_content_chars",
    "implementation_chars",
    "drawings_description_chars",
)


class MergeError(ValueError):
    """合成输入不合法时抛出。"""


def load_guide(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise MergeError(f"风格指南不存在：{path}") from exc
    except OSError as exc:
        raise MergeError(f"风格指南不可读：{path}（{exc}）") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise MergeError(f"风格指南含 BOM，必须使用 UTF-8 无 BOM：{path}")
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise MergeError(f"风格指南不是有效 UTF-8：{path}") from exc
    except json.JSONDecodeError as exc:
        raise MergeError(f"风格指南 JSON 解析失败：{path}（{exc}）") from exc
    try:
        validate_style_guide(data)
    except StyleGuideValidationError as exc:
        raise MergeError(f"风格指南不符合 v1 合同：{path}（{exc}）") from exc
    return data, hashlib.sha256(raw).hexdigest()


def median_int(values: list[float]) -> int:
    return int(round(statistics.median(values)))


def majority(values: list[str], fallback: str) -> str:
    return Counter(values).most_common(1)[0][0] if values else fallback


def merge_unique(lists: list[list[str]]) -> list[str]:
    merged: list[str] = []
    for items in lists:
        for item in items:
            if item not in merged:
                merged.append(item)
    return merged


def merge_guides(guides: list[dict[str, Any]], digests: list[str], paths: list[Path]) -> dict[str, Any]:
    claims = [g["claims_style"] for g in guides]
    specs = [g["specification_style"] for g in guides]
    drawings = [g["drawing_style"] for g in guides]
    abstracts = [g.get("abstract_style") or {} for g in guides]

    independent = median_int([float(c["independent_claims_count"]) for c in claims])
    dependent = median_int([float(c["dependent_claims_count"]) for c in claims])

    organization = min(
        (s["embodiment_organization"] for s in specs),
        key=lambda value: ORGANIZATION_ORDER[value],
    )
    # 组织方式收敛到最保守值后，实施例数必须与之自洽：单脉络与无编号形态
    # 不存在多个平行实施例，否则合成结果自身就会自相矛盾。
    if organization == "none":
        embodiments = 0
    elif organization == "single_flow":
        embodiments = median_int([float(s["embodiments_count"]) for s in specs])
    else:
        embodiments = median_int([float(s["embodiments_count"]) for s in specs])

    merged: dict[str, Any] = {
        "schema_id": "cn-patent-template-style/v1",
        "template_patent": " + ".join(g["template_patent"] for g in guides),
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "claims_style": {
            "independent_claims_count": max(1, independent),
            "dependent_claims_count": dependent,
            "total_claims": max(1, independent) + dependent,
            "dependency_pattern": majority([c["dependency_pattern"] for c in claims], "mixed"),
            **{field: median_int([float(c[field]) for c in claims]) for field in NUMERIC_CLAIM_FIELDS},
            "claim_preamble_style": merge_unique([list(c["claim_preamble_style"]) for c in claims])[:3],
            "feature_introduction_pattern": majority(
                [c["feature_introduction_pattern"] for c in claims], "其特征在于"
            ),
            "claim_structure_notes": "由 {} 份范本合成；数值取中位数，枚举取多数。".format(len(guides)),
        },
        "specification_style": {
            "embodiments_count": embodiments,
            "embodiment_organization": organization,
            "embodiment_detection_notes": "组织方式取各范本最保守值（none < single_flow < sectioned）：{}。".format(
                "、".join(f"{g['template_patent']}={s['embodiment_organization']}" for g, s in zip(guides, specs))
            ),
            **{field: median_int([float(s[field]) for s in specs]) for field in NUMERIC_SPEC_FIELDS},
            "description_mode": majority([s["description_mode"] for s in specs], "mixed"),
            "terminology_samples": merge_unique([list(s["terminology_samples"]) for s in specs])[:20],
            "sentence_patterns": merge_unique([list(s["sentence_patterns"]) for s in specs])[:5],
            "paragraph_structure_notes": "由 {} 份范本合成。".format(len(guides)),
        },
        "drawing_style": {
            "total_drawings": median_int([float(d["total_drawings"]) for d in drawings]),
            "drawing_types": merge_unique([list(d["drawing_types"]) for d in drawings]),
            "reference_sign_pattern": majority(
                [d["reference_sign_pattern"] for d in drawings if d["reference_sign_pattern"]],
                "unknown",
            ),
            "reference_sign_count": median_int([float(d["reference_sign_count"]) for d in drawings]),
            "drawing_notes": "由 {} 份范本合成。".format(len(guides)),
        },
        "extraction_methodology": {
            "tools_used": "analyze_template_style.py 分析结果的确定性合成",
            "confidence_level": min(
                (g["extraction_methodology"]["confidence_level"] for g in guides),
                key=lambda level: {"low": 0, "medium": 1, "high": 2}[level],
            ),
            "limitations": (
                "合成只做数值中位数、枚举多数和列表去重合并，不做语义理解。"
                "任何偏离合成结果的人工值必须写入 provenance.manual_overrides。"
            ),
        },
        "usage_notes": {
            "applicable_scope": merge_unique(
                [[g["usage_notes"]["applicable_scope"]] for g in guides]
            )[0],
            "mimicry_boundary": (
                "仅学习权利要求主题布局、段落功能、图文对应、实施方式展开顺序与句式偏好；"
                "不得复制范本技术内容，也不得据范本新增本申请未披露的技术特征。"
            ),
            "disclaimer": (
                "本指南是撰写风格和结构分析，不构成对范本或本申请的新颖性、创造性、"
                "授权前景及法律有效性的判断。"
            ),
        },
        "provenance": {
            "mode": "composite",
            "source_guides": [
                {
                    "template_patent": guide["template_patent"],
                    "path": str(path),
                    "sha256": digest,
                }
                for guide, path, digest in zip(guides, paths, digests)
            ],
            "manual_overrides": [],
        },
    }

    non_empty_abstracts = [a for a in abstracts if a]
    if non_empty_abstracts:
        merged["abstract_style"] = {
            "chars_count": median_int([float(a["chars_count"]) for a in non_empty_abstracts]),
            "structure_pattern": majority(
                [a["structure_pattern"] for a in non_empty_abstracts], "unknown"
            ),
            "opening_phrase": non_empty_abstracts[0].get("opening_phrase", ""),
            "abstract_notes": "由 {} 份范本合成。".format(len(non_empty_abstracts)),
        }
    else:
        merged["abstract_style"] = {}
    return merged


def resolve_path(document: dict[str, Any], field_path: str) -> tuple[dict[str, Any], str]:
    """把 a.b.c 解析为 (父对象, 末级键)。"""

    parts = field_path.split(".")
    node: Any = document
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise MergeError(f"覆盖路径不存在：{field_path}")
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise MergeError(f"覆盖路径不存在：{field_path}")
    return node, parts[-1]


def apply_overrides(merged: dict[str, Any], overrides: list[str]) -> None:
    """逐条应用人工覆盖并写入审计。

    覆盖值以 JSON 字面量解析；解析失败时按字符串处理，便于直接传中文枚举。
    """

    for raw in overrides:
        parts = raw.split("=", 3)
        if len(parts) != 4:
            raise MergeError(
                "覆盖格式必须是 字段路径=新值=理由=依据，实际收到：" + raw
            )
        field_path, new_raw, justification, evidence = (item.strip() for item in parts)
        if not justification or not evidence:
            raise MergeError(f"覆盖 {field_path} 必须同时提供理由与依据")
        parent, key = resolve_path(merged, field_path)
        machine_value = parent[key]
        try:
            new_value: Any = json.loads(new_raw)
        except json.JSONDecodeError:
            new_value = new_raw
        if new_value == machine_value:
            raise MergeError(f"覆盖 {field_path} 的人工值与机器值相同，不构成覆盖")
        parent[key] = new_value
        merged["provenance"]["manual_overrides"].append(
            {
                "field_path": field_path,
                "machine_value": machine_value,
                "manual_value": new_value,
                "justification": justification,
                "evidence": evidence,
            }
        )
    if merged["provenance"]["manual_overrides"]:
        merged["provenance"]["mode"] = "manual_revision"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="合成多份范本风格指南")
    parser.add_argument(
        "--guide", action="append", required=True, dest="guides",
        help="template-style-guide.json 路径，可重复",
    )
    parser.add_argument(
        "--override", action="append", default=[], dest="overrides",
        help="人工覆盖，格式：字段路径=新值=理由=依据。可重复。",
    )
    parser.add_argument("--output", required=True, help="合成风格指南输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = [Path(item) for item in args.guides]
    try:
        loaded = [load_guide(path) for path in paths]
    except MergeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    guides = [item[0] for item in loaded]
    digests = [item[1] for item in loaded]

    try:
        merged = merge_guides(guides, digests, paths)
        apply_overrides(merged, args.overrides)
        validate_style_guide(merged)
    except (MergeError, StyleGuideValidationError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_INVALID

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[OK] 合成风格指南：{output_path}")
    print(f"[INFO] 来源范本 {len(guides)} 份，来源模式 {merged['provenance']['mode']}")
    print(
        "[INFO] 实施例：{} 个，组织方式 {}".format(
            merged["specification_style"]["embodiments_count"],
            merged["specification_style"]["embodiment_organization"],
        )
    )
    for item in merged["provenance"]["manual_overrides"]:
        print(
            "[OVERRIDE] {}：机器值 {} → 人工值 {}（{}）".format(
                item["field_path"],
                json.dumps(item["machine_value"], ensure_ascii=False),
                json.dumps(item["manual_value"], ensure_ascii=False),
                item["justification"],
            )
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
