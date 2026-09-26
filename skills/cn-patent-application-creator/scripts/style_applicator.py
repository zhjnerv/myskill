#!/usr/bin/env python3
"""把范本风格指南转换为起草阶段可消费的结构化风格简报。

风格简报只约束布局、篇幅和句法偏好，不能添加本申请没有的技术特征，
也不能覆盖中国专利法、检索结果或 -CN 审查链的硬约束。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from template_style_contract import StyleGuideValidationError, validate_style_guide

BRIEF_SCHEMA_ID = "cn-patent-style-brief/v1"


class StyleGuide:
    """经合同校验的风格指南；路径为空时代表使用默认起草策略。"""

    def __init__(self, guide_path: str | Path | None = None):
        self.guide_data: dict[str, Any] | None = None
        if guide_path is None:
            return
        path = Path(guide_path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StyleGuideValidationError(f"风格指南文件不存在：{path}") from exc
        except UnicodeDecodeError as exc:
            raise StyleGuideValidationError(f"风格指南不是有效 UTF-8：{path}") from exc
        except json.JSONDecodeError as exc:
            raise StyleGuideValidationError(f"风格指南 JSON 解析失败：{exc}") from exc
        self.guide_data = validate_style_guide(raw)

    def is_available(self) -> bool:
        return self.guide_data is not None

    def get_template_patent(self) -> str | None:
        return self.guide_data["template_patent"] if self.guide_data else None

    def get_claims_style(self) -> dict[str, Any]:
        return self.guide_data["claims_style"] if self.guide_data else {}

    def get_specification_style(self) -> dict[str, Any]:
        return self.guide_data["specification_style"] if self.guide_data else {}

    def get_drawing_style(self) -> dict[str, Any]:
        return self.guide_data["drawing_style"] if self.guide_data else {}

    def get_abstract_style(self) -> dict[str, Any]:
        if not self.guide_data:
            return {}
        return self.guide_data.get("abstract_style") or {}

    def get_provenance_mode(self) -> str | None:
        """返回风格指南的来源模式；未声明 provenance 时视为 analyzer。"""

        if not self.guide_data:
            return None
        provenance = self.guide_data.get("provenance") or {}
        return str(provenance.get("mode", "analyzer"))

    def count_manual_overrides(self) -> int:
        if not self.guide_data:
            return 0
        provenance = self.guide_data.get("provenance") or {}
        return len(provenance.get("manual_overrides") or [])


class ClaimsStyleApplicator:
    """把权利要求统计特征转换为起草建议。"""

    def __init__(self, style_guide: StyleGuide):
        self.guide = style_guide

    def suggest_claims_count(self, available_features: int) -> dict[str, Any]:
        if available_features < 1:
            raise ValueError("available_features 必须大于等于 1")

        if not self.guide.is_available():
            independent = min(2, max(1, available_features // 5))
            dependent = min(10 - independent, max(0, available_features - independent))
            return {
                "independent": independent,
                "dependent": dependent,
                "total": independent + dependent,
                "reasoning": "默认策略（未提供范本）",
            }

        style = self.guide.get_claims_style()
        template_independent = style["independent_claims_count"]
        template_dependent = style["dependent_claims_count"]
        ratio = template_dependent / template_independent
        independent = min(template_independent, max(1, available_features // 5))
        dependent = min(
            round(independent * ratio),
            max(0, available_features - independent),
            max(0, 10 - independent),
        )
        return {
            "independent": independent,
            "dependent": dependent,
            "total": independent + dependent,
            "reasoning": (
                f"参考范本 {self.guide.get_template_patent()}"
                f"（独权 {template_independent} 项，从权 {template_dependent} 项）"
            ),
        }

    def suggest_dependency_pattern(self) -> str:
        if not self.guide.is_available():
            return "mixed"
        return str(self.guide.get_claims_style()["dependency_pattern"])

    def suggest_claim_length(self, is_independent: bool) -> dict[str, Any]:
        if not self.guide.is_available():
            if is_independent:
                return {
                    "target_chars": 160,
                    "min_chars": 120,
                    "max_chars": 200,
                    "reasoning": "默认策略",
                }
            return {
                "target_chars": 90,
                "min_chars": 60,
                "max_chars": 120,
                "reasoning": "默认策略",
            }

        style = self.guide.get_claims_style()
        field = "avg_independent_claim_chars" if is_independent else "avg_dependent_claim_chars"
        average = max(1, round(float(style[field])))
        return {
            "target_chars": average,
            "min_chars": max(1, round(average * 0.75)),
            "max_chars": max(1, round(average * 1.25)),
            "reasoning": f"参考范本{'独权' if is_independent else '从权'}平均 {average} 字符",
        }

    def get_preamble_examples(self) -> list[str]:
        if not self.guide.is_available():
            return []
        return list(self.guide.get_claims_style()["claim_preamble_style"])

    def get_feature_introduction_pattern(self) -> str:
        if not self.guide.is_available():
            return "其特征在于"
        return str(self.guide.get_claims_style()["feature_introduction_pattern"])


class SpecificationStyleApplicator:
    """把说明书统计特征转换为起草建议。"""

    def __init__(self, style_guide: StyleGuide):
        self.guide = style_guide

    def suggest_embodiments_count(self, available_variations: int) -> dict[str, Any]:
        if available_variations < 1:
            raise ValueError("available_variations 必须大于等于 1")
        if not self.guide.is_available():
            return {
                "count": min(3, available_variations),
                "organization": "sectioned",
                "reasoning": "默认策略（未提供范本）",
                "warnings": [],
            }

        style = self.guide.get_specification_style()
        template_count = int(style["embodiments_count"])
        organization = str(style["embodiment_organization"])
        warnings: list[str] = []

        # single_flow / none 的范本靠一条实施方式脉络贯穿全文。按数量机械拆节
        # 会把范本没有的平行实施例结构强加给本申请——这正是上一轮把说明书
        # 拆成 6 个平行实施例的直接原因。
        if organization in {"single_flow", "none"}:
            count = 1
            reasoning = (
                f"参考范本 {self.guide.get_template_patent()}"
                f"（组织方式 {organization}：单一实施方式贯穿，实施例编号 {template_count} 个）；"
                "按范本形态收敛为一个实施方式，变体作为可选路径写在同一脉络内"
            )
        else:
            count = min(max(1, template_count), available_variations)
            reasoning = (
                f"参考范本 {self.guide.get_template_patent()}"
                f"（组织方式 sectioned，{template_count} 个实施例）"
            )

        drawing_total = int(self.guide.get_drawing_style()["total_drawings"])
        if template_count and template_count == drawing_total:
            warnings.append(
                f"范本实施例数（{template_count}）与附图数（{drawing_total}）相同，"
                "存在把附图数误填为实施例数的可能，起草前须人工复核范本原文"
            )
        if organization in {"single_flow", "none"} and available_variations > 1:
            warnings.append(
                f"本申请有 {available_variations} 个变体，但范本采用单一实施方式形态；"
                "变体应作为替代路径写入同一实施方式，不得拆成平行实施例"
            )
        return {
            "count": count,
            "organization": organization,
            "reasoning": reasoning,
            "warnings": warnings,
        }

    def suggest_paragraph_length(self) -> dict[str, Any]:
        if not self.guide.is_available():
            return {
                "target_chars": 150,
                "min_chars": 80,
                "max_chars": 250,
                "reasoning": "默认策略",
            }
        average = max(1, round(float(self.guide.get_specification_style()["avg_paragraph_chars"])))
        return {
            "target_chars": average,
            "min_chars": max(1, round(average * 0.5)),
            "max_chars": max(1, round(average * 1.5)),
            "reasoning": f"参考范本段落平均 {average} 字符",
        }

    def get_description_mode(self) -> str:
        if not self.guide.is_available():
            return "mixed"
        return str(self.guide.get_specification_style()["description_mode"])

    def get_preferred_terminology(self) -> list[str]:
        if not self.guide.is_available():
            return []
        return list(self.guide.get_specification_style()["terminology_samples"])

    def get_sentence_patterns(self) -> list[str]:
        if not self.guide.is_available():
            return []
        return list(self.guide.get_specification_style()["sentence_patterns"])


class DrawingStyleApplicator:
    """把附图统计特征转换为起草建议。"""

    def __init__(self, style_guide: StyleGuide):
        self.guide = style_guide

    def suggest_reference_sign_start(self) -> int:
        if not self.guide.is_available():
            return 100
        pattern = str(self.guide.get_drawing_style()["reference_sign_pattern"])
        if "100" in pattern:
            return 100
        if "10" in pattern:
            return 10
        return 1

    def suggest_drawing_count(self, available_components: int) -> dict[str, Any]:
        if available_components < 1:
            raise ValueError("available_components 必须大于等于 1")
        if not self.guide.is_available():
            return {
                "count": min(5, max(1, available_components)),
                "reasoning": "默认策略（未提供范本）",
            }
        template_count = int(self.guide.get_drawing_style()["total_drawings"])
        target = max(1, template_count)
        return {
            "count": min(target, available_components),
            "reasoning": (
                f"参考范本 {self.guide.get_template_patent()}（{template_count} 幅附图）"
            ),
        }

    def get_preferred_drawing_types(self) -> list[str]:
        if not self.guide.is_available():
            return []
        return list(self.guide.get_drawing_style()["drawing_types"])


class AbstractStyleApplicator:
    """把摘要统计特征转换为起草建议。"""

    def __init__(self, style_guide: StyleGuide):
        self.guide = style_guide

    def suggest_abstract_length(self) -> dict[str, Any]:
        if not self.guide.is_available() or not self.guide.get_abstract_style():
            return {"target_chars": 250, "max_chars": 300, "reasoning": "默认策略"}
        template_chars = int(self.guide.get_abstract_style()["chars_count"])
        target = min(max(1, template_chars), 280)
        return {
            "target_chars": target,
            "max_chars": 300,
            "reasoning": (
                f"参考范本 {self.guide.get_template_patent()}（{template_chars} 字符）"
            ),
        }


def load_style_guide(guide_path: str | Path | None) -> StyleGuide:
    return StyleGuide(guide_path)


def create_applicators(style_guide: StyleGuide) -> dict[str, Any]:
    return {
        "claims": ClaimsStyleApplicator(style_guide),
        "specification": SpecificationStyleApplicator(style_guide),
        "drawing": DrawingStyleApplicator(style_guide),
        "abstract": AbstractStyleApplicator(style_guide),
    }


def build_style_brief(
    style_guide: StyleGuide,
    *,
    available_features: int,
    available_variations: int,
    available_components: int,
) -> dict[str, Any]:
    """生成起草阶段的唯一结构化交接文件。"""

    applicators = create_applicators(style_guide)
    claims = applicators["claims"]
    specification = applicators["specification"]
    drawing = applicators["drawing"]
    abstract = applicators["abstract"]
    embodiments = specification.suggest_embodiments_count(available_variations)
    return {
        "schema_id": BRIEF_SCHEMA_ID,
        "source": {
            "mode": "template" if style_guide.is_available() else "default",
            "template_patent": style_guide.get_template_patent(),
            "provenance_mode": style_guide.get_provenance_mode(),
            "manual_override_count": style_guide.count_manual_overrides(),
        },
        "claims": {
            "count": claims.suggest_claims_count(available_features),
            "dependency_pattern": claims.suggest_dependency_pattern(),
            "independent_claim_length": claims.suggest_claim_length(True),
            "dependent_claim_length": claims.suggest_claim_length(False),
            "preamble_examples": claims.get_preamble_examples(),
            "feature_introduction_pattern": claims.get_feature_introduction_pattern(),
        },
        "specification": {
            "embodiments": embodiments,
            "paragraph_length": specification.suggest_paragraph_length(),
            "description_mode": specification.get_description_mode(),
            "preferred_terminology": specification.get_preferred_terminology(),
            "sentence_patterns": specification.get_sentence_patterns(),
        },
        "drawings": {
            "count": drawing.suggest_drawing_count(available_components),
            "reference_sign_start": drawing.suggest_reference_sign_start(),
            "preferred_types": drawing.get_preferred_drawing_types(),
        },
        "abstract": abstract.suggest_abstract_length(),
        "warnings": list(embodiments.get("warnings", [])),
        "priority_order": [
            "本申请已披露的技术事实",
            "中国专利法律与形式要求",
            "现有技术检索后的权利要求边界",
            "范本风格简报",
        ],
        "usage_boundary": (
            "本简报只提供结构、篇幅和句法偏好。不得据此新增技术特征、删除必要技术特征、"
            "复制范本技术内容或绕过 -CN 审查链。实施例数量必须与 organization 一并消费："
            "single_flow 与 none 形态不得按数量拆成平行实施例。"
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成中国专利起草风格简报")
    parser.add_argument("--style-guide", help="template-style-guide.json；省略时使用默认策略")
    parser.add_argument("--available-features", type=int, required=True, help="可用于权利要求布局的技术特征数")
    parser.add_argument("--available-variations", type=int, default=1, help="已披露的技术方案变体数")
    parser.add_argument("--available-components", type=int, default=1, help="可视化的组件或流程数")
    parser.add_argument("--output", required=True, help="style-brief.json 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        guide = load_style_guide(args.style_guide)
        brief = build_style_brief(
            guide,
            available_features=args.available_features,
            available_variations=args.available_variations,
            available_components=args.available_components,
        )
    except (StyleGuideValidationError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] 起草风格简报已生成：{output_path}")
    print(f"[INFO] 风格来源：{brief['source']['mode']}")
    print(
        "[INFO] 实施例：{} 个，组织方式 {}".format(
            brief["specification"]["embodiments"]["count"],
            brief["specification"]["embodiments"]["organization"],
        )
    )
    for warning in brief["warnings"]:
        print(f"[WARNING] {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
