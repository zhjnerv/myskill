from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from normalize_ipc import (
    extract_ipc_codes_from_text,
    extract_subclass_from_full_ipc,
    normalize_ipc_code,
    normalize_ipc_codes,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_PREEXAM_PATH = DEFAULT_DATA_DIR / "preexam_ready.json.gz"
DISCLAIMER = "本结果仅用于专利加快程序分类范围初筛，不代表保护中心一定受理，也不代表专利授权前景。"

SPECIAL_AREA_SUPERIORS: dict[tuple[str, str], str] = {
    ("北京市", "中关村"): "北京市",
    ("天津市", "滨海新区"): "天津市",
}


@dataclass(frozen=True)
class ResolvedRegion:
    province: str
    city: str | None
    special_area: str | None
    candidate_center_ids: list[str]
    warnings: list[str]


def load_preexam_data(data_path: Path | None = None) -> dict[str, Any]:
    path = data_path or DEFAULT_PREEXAM_PATH
    if not path.exists():
        fallback_json = path.with_suffix("") if path.suffix == ".gz" else path.with_name(path.name + ".gz")
        if fallback_json.exists():
            path = fallback_json
        else:
            raise FileNotFoundError(f"未找到预审数据文件: {path}")

    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_simple_alias(value: Any, aliases: dict[str, Any]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip()
    aliased = aliases.get(key)
    return aliased if isinstance(aliased, str) else key


def _normalize_city_alias(value: Any, aliases: dict[str, Any], province: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip()
    aliased = aliases.get(key)
    if isinstance(aliased, str):
        return aliased
    if isinstance(aliased, list):
        for item in aliased:
            if isinstance(item, dict) and item.get("province") == province:
                city = item.get("city")
                if isinstance(city, str) and city:
                    return city
        for item in aliased:
            if isinstance(item, dict):
                city = item.get("city")
                if isinstance(city, str) and city:
                    return city
    return key


def _normalize_area_alias(value: Any, aliases: dict[str, Any], province: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip()
    aliased = aliases.get(key)
    if isinstance(aliased, str):
        return aliased
    if isinstance(aliased, list):
        for item in aliased:
            if isinstance(item, dict) and item.get("province") == province:
                area = item.get("area")
                if isinstance(area, str) and area:
                    return area
        for item in aliased:
            if isinstance(item, dict):
                area = item.get("area")
                if isinstance(area, str) and area:
                    return area
    return key


def _append_center_ids(target: list[str], centers: list[dict[str, Any]]) -> None:
    for center in centers:
        cid = center.get("center_id")
        if isinstance(cid, str) and cid and cid not in target:
            target.append(cid)


def _superior_city_for_area(province: str | None, special_area: str | None) -> str | None:
    if not province or not special_area:
        return None
    return SPECIAL_AREA_SUPERIORS.get((province, special_area))


def resolve_region(
    data: dict[str, Any],
    province: Any,
    city: Any = None,
    special_area: Any = None,
) -> ResolvedRegion:
    aliases = data.get("region_alias_index") or {}
    region_index = data.get("region_index") or {}

    normalized_province = _normalize_simple_alias(province, aliases.get("province_aliases") or {})
    normalized_city = _normalize_city_alias(city, aliases.get("city_aliases") or {}, normalized_province)
    normalized_area = _normalize_area_alias(special_area, aliases.get("special_area_aliases") or {}, normalized_province)
    warnings: list[str] = []

    if not normalized_province:
        return ResolvedRegion("", normalized_city, normalized_area, [], ["缺少省级所在地。"])

    region = region_index.get(normalized_province)
    if not region:
        return ResolvedRegion(
            normalized_province,
            normalized_city,
            normalized_area,
            [],
            [f"当前数据中未收录 {normalized_province} 的保护中心预审分类号。"],
        )

    candidate_ids: list[str] = []
    _append_center_ids(candidate_ids, region.get("province_level_centers") or [])

    effective_city = _superior_city_for_area(normalized_province, normalized_area) or normalized_city
    city_centers = (region.get("city_level_centers") or {}).get(effective_city or "", [])
    if effective_city:
        _append_center_ids(candidate_ids, city_centers)
        if normalized_area and normalized_city and normalized_city != effective_city:
            warnings.append(f"已按 {normalized_area} 所属地区检查对应保护中心。")
        elif not city_centers and not normalized_area:
            warnings.append(f"未找到 {effective_city} 对应的市级保护中心，已仅检查省级中心。")
    elif not normalized_area:
        warnings.append("未提供市级所在地，已仅检查省级中心。")

    if normalized_area:
        area_centers = (region.get("special_area_centers") or {}).get(normalized_area, [])
        _append_center_ids(candidate_ids, area_centers)
        if not area_centers:
            warnings.append(f"未找到 {normalized_area} 对应的特殊区域保护中心。")

    return ResolvedRegion(
        province=normalized_province,
        city=effective_city,
        special_area=normalized_area,
        candidate_center_ids=candidate_ids,
        warnings=warnings,
    )


def match_preexam(
    province: str,
    city: str | None = None,
    special_area: str | None = None,
    ipc_codes: list[str] | None = None,
    primary_ipc: str | None = None,
    secondary_ipcs: list[str] | None = None,
    data: dict[str, Any] | None = None,
    data_path: Path | None = None,
) -> dict[str, Any]:
    if data is None:
        data = load_preexam_data(data_path)

    # 确定主要分类号与次要分类号
    raw_primary = [primary_ipc] if primary_ipc else []
    raw_secondary = secondary_ipcs or []
    other_ipcs = ipc_codes or []

    combined_input = [*raw_primary, *raw_secondary, *other_ipcs]
    normalized_all = normalize_ipc_codes(combined_input, allow_full=True)

    if not normalized_all:
        return {
            "checked": False,
            "matched": False,
            "province": province,
            "city": city,
            "special_area": special_area,
            "ipc_codes": [],
            "subclasses": [],
            "candidate_centers": [],
            "matched_center_count": 0,
            "message": "未得到有效的 IPC 分类号，无法进行预审分类范围匹配。",
            "warnings": ["请输入有效的 IPC 小类或完整分类号（如 G06F 30/27 或 G06N）。"],
            "disclaimer": DISCLAIMER,
        }

    if raw_primary:
        prim = normalize_ipc_codes(raw_primary, allow_full=True)
        primary_code = prim[0] if prim else normalized_all[0]
        secondary_codes = [c for c in normalized_all if c != primary_code]
    else:
        primary_code = normalized_all[0]
        secondary_codes = normalized_all[1:]

    primary_subclass = extract_subclass_from_full_ipc(primary_code)
    secondary_subclasses = [extract_subclass_from_full_ipc(c) for c in secondary_codes]
    secondary_subclasses = [s for s in secondary_subclasses if s and s != primary_subclass]
    all_subclasses = [primary_subclass, *secondary_subclasses] if primary_subclass else []

    resolved = resolve_region(data, province, city, special_area)
    center_index = data.get("center_index") or {}

    candidate_results: list[dict[str, Any]] = []
    primary_matched = False
    secondary_matched = False

    for cid in resolved.candidate_center_ids:
        center = center_index.get(cid)
        if not center:
            continue
        accepted = set(center.get("accepted_ipc") or [])
        matched = [code for code in all_subclasses if code in accepted]

        center_primary_matched = bool(primary_subclass and primary_subclass in accepted)
        center_secondary_matched = any(sub in accepted for sub in secondary_subclasses)
        if center_primary_matched:
            primary_matched = True
        if center_secondary_matched:
            secondary_matched = True

        # 标注触发来源（primary / secondary 及具体分类号）
        matched_details: list[dict[str, Any]] = []
        for code in matched:
            sources: list[str] = []
            inputs: list[str] = []
            if code == primary_subclass:
                sources.append("primary")
                inputs.append(primary_code)
            if code in secondary_subclasses:
                sources.append("secondary")
                inputs.extend([c for c in secondary_codes if extract_subclass_from_full_ipc(c) == code])

            matched_details.append(
                {
                    "subclass": code,
                    "source": "/".join(sources),
                    "input_ipcs": inputs,
                }
            )

        center_name = center.get("center_name", "")
        center_dict: dict[str, Any] = {
            "center_id": cid,
            "center_name": center_name,
            "province": center.get("province", ""),
            "city": center.get("city"),
            "level": center.get("level", "city"),
            "matched_ipc": matched,
            "matched_ipc_details": matched_details,
            "prequalification_possible": bool(matched),
            "primary_matched": center_primary_matched,
            "secondary_matched": center_secondary_matched,
        }
        if bool(matched) and not center_primary_matched:
            center_dict["warning"] = f"{center_name}仅命中次要 IPC 小类，未命中主要 IPC 小类；实务中保护中心通常以第一主分类号为准，存在退案风险。"

        candidate_results.append(center_dict)

    candidate_results.sort(
        key=lambda item: (
            not item["prequalification_possible"],
            not item["primary_matched"],
            -len(item["matched_ipc"]),
            item["level"] or "",
            item["center_name"] or "",
        )
    )

    matched_count = sum(1 for item in candidate_results if item["prequalification_possible"])
    matched = bool(matched_count)
    warnings = list(resolved.warnings)

    # 针对某中心仅命中次要 IPC 的情形，在顶层 warnings 中增加专门提示（不被其他命中主 IPC 的候选中心掩盖）
    for item in candidate_results:
        w = item.get("warning")
        if w and w not in warnings:
            warnings.append(w)

    # 全局：所有命中中心均仅次要 IPC 命中、主要 IPC 均未命中时增加统揽警告
    if matched and secondary_matched and not primary_matched:
        generic_warn = (
            "主要 IPC 小类未落入候选保护中心预审范围，仅次要 IPC 命中；保护中心是否接受以其分类审核为准，建议复核主要分类号是否准确。"
        )
        if generic_warn not in warnings:
            warnings.append(generic_warn)

    if not resolved.candidate_center_ids:
        msg = "当前所在地没有可用于程序匹配的保护中心预审分类号数据。"
    elif matched:
        msg = f"预审分类范围命中（{matched_count} 家保护中心可受理），可考虑申请预审。"
    else:
        msg = "未命中申请主体所在地可申请保护中心的当前预审 IPC 分类范围。"

    return {
        "checked": True,
        "matched": matched,
        "province": resolved.province,
        "city": resolved.city,
        "special_area": resolved.special_area,
        "ipc_codes": normalized_all,
        "primary_ipc": primary_code,
        "secondary_ipcs": secondary_codes,
        "subclasses": all_subclasses,
        "candidate_centers": candidate_results,
        "matched_center_count": matched_count,
        "message": msg,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="知识产权保护中心专利预审范围匹配工具。根据申请人所在地与 IPC 分类号，初筛可申请的保护中心。"
    )
    parser.add_argument(
        "-p",
        "--province",
        required=True,
        help="申请主体所在省/自治区/直辖市（如 '浙江省' 或 '浙江'）",
    )
    parser.add_argument(
        "-c",
        "--city",
        default=None,
        help="申请主体所在城市（如 '杭州市' 或 '杭州'）",
    )
    parser.add_argument(
        "-s",
        "--special-area",
        default=None,
        help="特殊保护区域（如 '中关村'、'滨海新区'）",
    )
    parser.add_argument(
        "--primary-ipc",
        type=str,
        help="主要 IPC 分类号（如 'G06N 3/08'）",
    )
    parser.add_argument(
        "--secondary-ipc",
        action="append",
        dest="secondary_ipcs",
        help="次要 IPC 分类号（可重复传入多个，每次一个）",
    )
    parser.add_argument(
        "-i",
        "--ipc",
        action="append",
        dest="ipc_list",
        help="常规 IPC 分类号，可重复传入多个（如 -i G06F30/27 -i G06N）",
    )
    parser.add_argument(
        "positional_ipcs",
        nargs="*",
        help="位置参数传入的 IPC 分类号",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=DEFAULT_PREEXAM_PATH,
        help="预审数据文件路径（默认读取 data/preexam_ready.json.gz）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="输出 JSON 格式结果（默认启用）",
    )

    args = parser.parse_args(argv)

    all_ipcs: list[str] = []
    if args.ipc_list:
        all_ipcs.extend(args.ipc_list)
    if args.positional_ipcs:
        all_ipcs.extend(args.positional_ipcs)

    if not args.primary_ipc and not all_ipcs and not sys.stdin.isatty():
        content = sys.stdin.read().strip()
        if content:
            all_ipcs.extend(extract_ipc_codes_from_text(content))

    result = match_preexam(
        province=args.province,
        city=args.city,
        special_area=args.special_area,
        ipc_codes=all_ipcs,
        primary_ipc=args.primary_ipc,
        secondary_ipcs=args.secondary_ipcs,
        data_path=args.data_path,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["matched"] else (0 if result["checked"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
