#!/usr/bin/env python3
"""范本风格指南 v1 的轻量合同校验器。

只使用标准库，供风格分析器和风格应用器共同调用。它检查起草流程实际
依赖的字段、类型、枚举和数值边界；不把描述性 schema 当作已验证证据。
"""

from __future__ import annotations

from typing import Any

SCHEMA_ID = "cn-patent-template-style/v1"
DEPENDENCY_PATTERNS = {"tree", "linear", "mixed"}
DESCRIPTION_MODES = {"process_oriented", "structure_oriented", "mixed"}
EMBODIMENT_ORGANIZATIONS = {"sectioned", "single_flow", "none"}
PROVENANCE_MODES = {"analyzer", "composite", "manual_revision"}
ABSTRACT_PATTERNS = {
    "technical_problem+technical_solution+technical_effect",
    "technical_field+technical_solution+technical_effect",
    "technical_solution+technical_effect",
    "unknown",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
_SHA256_CHARS = set("0123456789abcdef")


class StyleGuideValidationError(ValueError):
    """风格指南不符合 v1 合同时抛出。"""


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StyleGuideValidationError(f"{path} 必须是对象")
    return value


def _require_string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise StyleGuideValidationError(f"{path} 必须是字符串")
    if not allow_empty and not value.strip():
        raise StyleGuideValidationError(f"{path} 不得为空")
    return value


def _require_number(value: Any, path: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StyleGuideValidationError(f"{path} 必须是数字")
    if value < minimum:
        raise StyleGuideValidationError(f"{path} 不得小于 {minimum:g}")
    return float(value)


def _require_integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StyleGuideValidationError(f"{path} 必须是整数")
    if value < minimum:
        raise StyleGuideValidationError(f"{path} 不得小于 {minimum}")
    return value


def _require_string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        raise StyleGuideValidationError(f"{path} 必须是字符串数组")
    for index, item in enumerate(value):
        _require_string(item, f"{path}[{index}]")
    return value


def _require_enum(value: Any, path: str, allowed: set[str]) -> str:
    text = _require_string(value, path)
    if text not in allowed:
        choices = "、".join(sorted(allowed))
        raise StyleGuideValidationError(f"{path} 必须是以下值之一：{choices}")
    return text


def _validate_provenance(root: dict[str, Any]) -> None:
    """校验合成来源与人工覆盖审计。

    机器分析出的指南可以不带 provenance；一旦声明为 composite 或 manual_revision，
    每一处偏离机器值的修改都必须逐条登记。手改数字而不留审计，正是"实施例数被
    填成附图数"这类错误能一路走到起草端的通道。
    """

    provenance = root.get("provenance")
    if provenance is None:
        return
    provenance = _require_mapping(provenance, "provenance")
    mode = _require_enum(provenance.get("mode"), "provenance.mode", PROVENANCE_MODES)

    sources = provenance.get("source_guides", [])
    if not isinstance(sources, list):
        raise StyleGuideValidationError("provenance.source_guides 必须是数组")
    for index, item in enumerate(sources):
        entry = _require_mapping(item, f"provenance.source_guides[{index}]")
        _require_string(entry.get("template_patent"), f"provenance.source_guides[{index}].template_patent")
        _require_string(entry.get("path"), f"provenance.source_guides[{index}].path")
        digest = _require_string(entry.get("sha256"), f"provenance.source_guides[{index}].sha256")
        if len(digest) != 64 or not set(digest).issubset(_SHA256_CHARS):
            raise StyleGuideValidationError(
                f"provenance.source_guides[{index}].sha256 必须是 64 位小写十六进制摘要"
            )
    if mode == "composite" and not sources:
        raise StyleGuideValidationError("provenance.mode 为 composite 时必须列出 source_guides")

    overrides = provenance.get("manual_overrides", [])
    if not isinstance(overrides, list):
        raise StyleGuideValidationError("provenance.manual_overrides 必须是数组")
    for index, item in enumerate(overrides):
        entry = _require_mapping(item, f"provenance.manual_overrides[{index}]")
        _require_string(entry.get("field_path"), f"provenance.manual_overrides[{index}].field_path")
        for field in ("machine_value", "manual_value"):
            if field not in entry:
                raise StyleGuideValidationError(
                    f"provenance.manual_overrides[{index}].{field} 必须存在，用于对照机器值与人工值"
                )
        if entry["machine_value"] == entry["manual_value"]:
            raise StyleGuideValidationError(
                f"provenance.manual_overrides[{index}] 的机器值与人工值相同，不构成覆盖"
            )
        _require_string(entry.get("justification"), f"provenance.manual_overrides[{index}].justification")
        _require_string(entry.get("evidence"), f"provenance.manual_overrides[{index}].evidence")
    if mode == "manual_revision" and not overrides:
        raise StyleGuideValidationError("provenance.mode 为 manual_revision 时必须列出 manual_overrides")


def validate_style_guide(data: Any) -> dict[str, Any]:
    """校验并返回风格指南。

    校验范围绑定风格应用器真正消费的字段。分析器可输出额外的说明字段，
    但这些字段不能代替必需字段。
    """

    root = _require_mapping(data, "风格指南")
    _require_enum(root.get("schema_id"), "schema_id", {SCHEMA_ID})
    _require_string(root.get("template_patent"), "template_patent")
    _require_string(root.get("extraction_timestamp"), "extraction_timestamp")

    claims = _require_mapping(root.get("claims_style"), "claims_style")
    independent = _require_integer(
        claims.get("independent_claims_count"),
        "claims_style.independent_claims_count",
        minimum=1,
    )
    dependent = _require_integer(
        claims.get("dependent_claims_count"),
        "claims_style.dependent_claims_count",
    )
    total = _require_integer(claims.get("total_claims"), "claims_style.total_claims", minimum=1)
    if independent + dependent != total:
        raise StyleGuideValidationError(
            "claims_style.total_claims 必须等于独立权利要求数与从属权利要求数之和"
        )
    _require_enum(
        claims.get("dependency_pattern"),
        "claims_style.dependency_pattern",
        DEPENDENCY_PATTERNS,
    )
    for field in (
        "avg_independent_claim_chars",
        "avg_dependent_claim_chars",
        "max_independent_claim_chars",
        "min_independent_claim_chars",
    ):
        _require_number(claims.get(field), f"claims_style.{field}")
    _require_string_list(claims.get("claim_preamble_style"), "claims_style.claim_preamble_style")
    _require_string(
        claims.get("feature_introduction_pattern"),
        "claims_style.feature_introduction_pattern",
        allow_empty=True,
    )

    specification = _require_mapping(root.get("specification_style"), "specification_style")
    embodiments_count = _require_integer(
        specification.get("embodiments_count"),
        "specification_style.embodiments_count",
    )
    organization = _require_enum(
        specification.get("embodiment_organization"),
        "specification_style.embodiment_organization",
        EMBODIMENT_ORGANIZATIONS,
    )
    # 数量与组织方式必须自洽。none 表示范本没有任何实施例编号，此时给出正数
    # 计数会让起草端凭空拆出平行实施例——这正是上一轮说明书被拆成 6 节的形态。
    if organization == "none" and embodiments_count != 0:
        raise StyleGuideValidationError(
            "specification_style.embodiment_organization 为 none 时 embodiments_count 必须为 0"
        )
    if organization in {"sectioned", "single_flow"} and embodiments_count < 1:
        raise StyleGuideValidationError(
            f"specification_style.embodiment_organization 为 {organization} 时 "
            "embodiments_count 必须大于等于 1"
        )
    for field in (
        "avg_paragraph_chars",
        "max_paragraph_chars",
        "min_paragraph_chars",
        "technical_field_chars",
        "background_chars",
        "invention_content_chars",
        "implementation_chars",
        "drawings_description_chars",
    ):
        _require_number(specification.get(field), f"specification_style.{field}")
    _require_enum(
        specification.get("description_mode"),
        "specification_style.description_mode",
        DESCRIPTION_MODES,
    )
    _require_string_list(
        specification.get("terminology_samples"),
        "specification_style.terminology_samples",
    )
    _require_string_list(
        specification.get("sentence_patterns"),
        "specification_style.sentence_patterns",
    )

    drawing = _require_mapping(root.get("drawing_style"), "drawing_style")
    _require_integer(drawing.get("total_drawings"), "drawing_style.total_drawings")
    _require_integer(drawing.get("reference_sign_count"), "drawing_style.reference_sign_count")
    _require_string_list(drawing.get("drawing_types"), "drawing_style.drawing_types")
    _require_string(
        drawing.get("reference_sign_pattern"),
        "drawing_style.reference_sign_pattern",
        allow_empty=True,
    )

    abstract = root.get("abstract_style")
    if abstract:
        abstract = _require_mapping(abstract, "abstract_style")
        _require_integer(abstract.get("chars_count"), "abstract_style.chars_count")
        _require_enum(
            abstract.get("structure_pattern"),
            "abstract_style.structure_pattern",
            ABSTRACT_PATTERNS,
        )

    methodology = _require_mapping(root.get("extraction_methodology"), "extraction_methodology")
    _require_enum(
        methodology.get("confidence_level"),
        "extraction_methodology.confidence_level",
        CONFIDENCE_LEVELS,
    )

    usage_notes = _require_mapping(root.get("usage_notes"), "usage_notes")
    _require_string(usage_notes.get("mimicry_boundary"), "usage_notes.mimicry_boundary")
    _require_string(usage_notes.get("disclaimer"), "usage_notes.disclaimer")
    _validate_provenance(root)
    return root
