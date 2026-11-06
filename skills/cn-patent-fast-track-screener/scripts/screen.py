from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from check_priority_review import check_priority_review
from match_preexam import match_preexam
from normalize_ipc import (
    extract_ipc_codes_from_text,
    extract_subclass_from_full_ipc,
    load_subclass_definitions,
    normalize_ipc_codes,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DISCLAIMER = "本结果仅用于专利加快程序分类范围初筛，不代表保护中心一定受理，也不代表专利授权前景。"
MAX_IPC_CODES = 3


def screen_fast_track(
    province: str,
    city: str | None = None,
    special_area: str | None = None,
    primary_ipc: str | None = None,
    secondary_ipcs: list[str] | None = None,
    ipc_codes: list[str] | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    base_dir = data_dir or DEFAULT_DATA_DIR
    preexam_path = base_dir / "preexam_ready.json.gz"
    priority_path = base_dir / "priority_review.json.gz"

    # 整合所有 IPC
    raw_primary = [primary_ipc] if primary_ipc else []
    raw_secondary = secondary_ipcs or []
    other_ipcs = ipc_codes or []

    combined_input = [*raw_primary, *raw_secondary, *other_ipcs]
    normalized_all = normalize_ipc_codes(combined_input, allow_full=True)[:MAX_IPC_CODES]

    if not normalized_all:
        return {
            "status": "unknown",
            "province": province,
            "city": city,
            "special_area": special_area,
            "ipc_classification": {
                "primary_ipc": "",
                "secondary_ipc": [],
                "all_ipc": [],
                "primary_subclass": "",
                "secondary_subclasses": [],
                "all_subclasses": [],
            },
            "ipc_codes": [],
            "candidate_centers": [],
            "matched_center_count": 0,
            "message": "未得到有效的 IPC 分类号，无法判断预审和优审分类范围。",
            "warnings": ["未提供有效 IPC 分类号（例如 G06F 30/27 或 G06N）。"],
            "preexam": {
                "checked": False,
                "matched": False,
                "message": "未得到有效 IPC，无法判断预审分类范围。",
                "candidate_centers": [],
                "matched_center_count": 0,
            },
            "priority_review": {
                "checked": False,
                "matched": False,
                "matched_groups": [],
                "matched_codes": [],
                "matched_sources": [],
                "message": "未得到有效 IPC，未检查优先审查分类号。",
            },
            "accelerated_paths": [],
            "disclaimer": DISCLAIMER,
            "ipc_definitions": {},
        }

    # 确定主要分类号与次要分类号
    if raw_primary:
        prim = normalize_ipc_codes(raw_primary, allow_full=True)
        primary_code = prim[0] if prim else normalized_all[0]
        secondary_codes = [c for c in normalized_all if c != primary_code][: MAX_IPC_CODES - 1]
    else:
        primary_code = normalized_all[0]
        secondary_codes = normalized_all[1:MAX_IPC_CODES]

    primary_sub = extract_subclass_from_full_ipc(primary_code)
    secondary_subs = [extract_subclass_from_full_ipc(c) for c in secondary_codes]
    secondary_subs = [s for s in secondary_subs if s and s != primary_sub]
    all_subclasses = [primary_sub, *secondary_subs] if primary_sub else []

    ipc_classification = {
        "primary_ipc": primary_code,
        "secondary_ipc": secondary_codes,
        "all_ipc": normalized_all,
        "primary_subclass": primary_sub,
        "secondary_subclasses": secondary_subs,
        "all_subclasses": all_subclasses,
    }

    # 读取官方定义（带 600 字长度上限保护）
    defs_all = load_subclass_definitions(base_dir)
    ipc_defs = {s: defs_all[s] for s in all_subclasses if s in defs_all}

    # 执行预审匹配（按小类及地域筛选候选保护中心，并标注 primary / secondary 触发源）
    preexam_res = match_preexam(
        province=province,
        city=city,
        special_area=special_area,
        primary_ipc=primary_code,
        secondary_ipcs=secondary_codes,
        data_path=preexam_path,
    )

    # 执行优审匹配（按完整 IPC 组/小组号精确匹配）
    priority_res = check_priority_review(
        ipc_codes=normalized_all,
        data_path=priority_path,
    )

    accelerated_paths: list[str] = []
    if preexam_res.get("matched"):
        accelerated_paths.append("preexam")
    if priority_res.get("matched"):
        accelerated_paths.append("priority_review")

    status = "accelerated_matched" if accelerated_paths else "not_matched"

    pre_matched = bool(preexam_res.get("matched"))
    prio_matched = bool(priority_res.get("matched"))
    if pre_matched and prio_matched:
        summary_msg = "预审分类范围命中，可考虑申请预审；同时命中优审政策范围完整分类号。"
    elif pre_matched:
        summary_msg = "预审分类范围命中，可考虑申请预审。"
    elif prio_matched:
        summary_msg = "未命中预审分类范围；优审政策范围完整分类号命中，可在进入实质审查后进一步评估优先审查。"
    else:
        summary_msg = "未命中当前预审分类范围，也未发现优审政策范围完整分类号命中。"

    return {
        "status": status,
        "province": preexam_res.get("province", province),
        "city": preexam_res.get("city", city),
        "special_area": preexam_res.get("special_area", special_area),
        "ipc_classification": ipc_classification,
        "ipc_codes": normalized_all,
        "candidate_centers": preexam_res.get("candidate_centers", []),
        "matched_center_count": preexam_res.get("matched_center_count", 0),
        "message": summary_msg,
        "warnings": preexam_res.get("warnings", []),
        "preexam": {
            "checked": preexam_res.get("checked", True),
            "matched": pre_matched,
            "message": preexam_res.get("message", ""),
            "candidate_centers": preexam_res.get("candidate_centers", []),
            "matched_center_count": preexam_res.get("matched_center_count", 0),
            "warnings": preexam_res.get("warnings", []),
        },
        "priority_review": {
            "checked": priority_res.get("checked", True),
            "matched": prio_matched,
            "matched_groups": priority_res.get("matched_groups", []),
            "matched_codes": priority_res.get("matched_codes", []),
            "matched_sources": priority_res.get("matched_sources", []),
            "message": priority_res.get("message", ""),
        },
        "accelerated_paths": accelerated_paths,
        "disclaimer": DISCLAIMER,
        "ipc_definitions": ipc_defs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="中国发明专利快速审查通道一键初筛工具（预审 + 优审 + IPC 标准化）。"
    )
    parser.add_argument(
        "-p",
        "--province",
        required=True,
        help="申请主体所在省/自治区/直辖市（如 '浙江省' 或 '广东'）",
    )
    parser.add_argument(
        "-c",
        "--city",
        default=None,
        help="申请主体所在城市（如 '杭州市' 或 '深圳'）",
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
        help="次要 IPC 分类号（可重复传入多个，每次传入一个，如 --secondary-ipc G06V10/40 --secondary-ipc B60W30/00）",
    )
    parser.add_argument(
        "-i",
        "--ipc",
        action="append",
        dest="ipc_list",
        help="常规 IPC 分类号（若未明确区分主次，可通过此参数传入）",
    )
    parser.add_argument(
        "positional_ipcs",
        nargs="*",
        help="位置参数传入的 IPC 分类号",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="数据目录（默认读取 Skill 内 data/）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="输出 JSON 格式（默认启用）",
    )

    args = parser.parse_args(argv)

    general_ipcs: list[str] = []
    if args.ipc_list:
        general_ipcs.extend(args.ipc_list)
    if args.positional_ipcs:
        general_ipcs.extend(args.positional_ipcs)

    if not args.primary_ipc and not general_ipcs and not sys.stdin.isatty():
        content = sys.stdin.read().strip()
        if content:
            general_ipcs.extend(extract_ipc_codes_from_text(content, allow_full=True))

    result = screen_fast_track(
        province=args.province,
        city=args.city,
        special_area=args.special_area,
        primary_ipc=args.primary_ipc,
        secondary_ipcs=args.secondary_ipcs,
        ipc_codes=general_ipcs,
        data_dir=args.data_dir,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "accelerated_matched" else (0 if result["status"] == "not_matched" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
