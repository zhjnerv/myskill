#!/usr/bin/env python3
"""跨类别全局检索大类、类似群及商品/服务项

支持在全量 45 个大类、498 个类似群以及 31,000+ 商品服务项中进行全局检索。
匹配优先级规则：
  1. 编码精确匹配 (Exact Code)
  2. 编码前缀匹配 (Prefix Code)
  3. 名称精确/前缀匹配 (Prefix Name)
  4. 名称包含匹配 (Contains Name)
同等级匹配按【大类 > 类似群 > 商品项】排序。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class SearchResultItem:
    type: str  # "class", "group", "item"
    code: str
    name: str
    class_code: str
    class_name: str
    group_code: str = ""
    group_name: str = ""
    item_type: str = ""  # "standard", "marked", "nonstandard"
    score_tier: int = 4  # 0: exact_code/name, 1: code_prefix, 2: name_prefix, 3: name_contains


def load_all_search_entities(data_dir: Path) -> list[SearchResultItem]:
    """构建全量内存搜索实体索引"""
    entities: list[SearchResultItem] = []

    classes_file = data_dir / "classes.json"
    if not classes_file.is_file():
        raise FileNotFoundError(f"缺少 classes.json: {classes_file}")

    with classes_file.open("r", encoding="utf-8") as f:
        classes_data = json.load(f)

    class_dict: dict[str, str] = {}
    for c in classes_data:
        c_code = str(c.get("classCode", "")).strip().zfill(2)
        c_name = str(c.get("className", "")).strip()
        class_dict[c_code] = c_name
        entities.append(
            SearchResultItem(
                type="class",
                code=c_code,
                name=c_name,
                class_code=c_code,
                class_name=c_name,
            )
        )

    groups_dir = data_dir / "groups"
    details_dir = data_dir / "details"

    for c_code, c_name in class_dict.items():
        g_file = groups_dir / f"{c_code}.json"
        if not g_file.is_file():
            continue

        with g_file.open("r", encoding="utf-8") as f:
            groups_data = json.load(f)

        for g in groups_data:
            g_code = str(g.get("groupCode", "")).strip()
            g_name = str(g.get("groupName", "")).strip()

            entities.append(
                SearchResultItem(
                    type="group",
                    code=g_code,
                    name=g_name,
                    class_code=c_code,
                    class_name=c_name,
                    group_code=g_code,
                    group_name=g_name,
                )
            )

            # 读取该类似群下的商品项
            d_file = details_dir / f"{g_code}.json"
            if not d_file.is_file():
                continue

            with d_file.open("r", encoding="utf-8") as f:
                d_data = json.load(f)

            for sec in d_data.get("sections", []):
                for it in sec.get("items", []):
                    i_name = str(it.get("name", "")).strip()
                    i_code = str(it.get("code", "")).strip()
                    i_type = str(it.get("type", "standard")).strip()
                    entities.append(
                        SearchResultItem(
                            type="item",
                            code=i_code,
                            name=i_name,
                            class_code=c_code,
                            class_name=c_name,
                            group_code=g_code,
                            group_name=g_name,
                            item_type=i_type,
                        )
                    )

            for it in d_data.get("nonstandardItems", []):
                i_name = str(it.get("name", "")).strip()
                entities.append(
                    SearchResultItem(
                        type="item",
                        code="",
                        name=i_name,
                        class_code=c_code,
                        class_name=c_name,
                        group_code=g_code,
                        group_name=g_name,
                        item_type="nonstandard",
                    )
                )

    return entities


def execute_search(
    entities: list[SearchResultItem],
    query: list[str] | str,
    target_type: str = "all",
    class_filter: Optional[list[str]] = None,
    match_any: bool = False,
    limit: int = 50,
) -> list[SearchResultItem]:
    terms: list[str] = []
    query_list = query if isinstance(query, list) else [query]
    for q_item in query_list:
        for t in q_item.split():
            clean = t.strip().lower()
            if clean and clean not in terms:
                terms.append(clean)

    if not terms:
        return []

    norm_classes = {c.strip().zfill(2) for c in class_filter} if class_filter else None
    type_order = {"class": 0, "group": 1, "item": 2}

    if match_any:
        # 多关键词 OR 检索模式
        matched_items: list[tuple[int, int, int, int, SearchResultItem]] = []
        for item in entities:
            if target_type != "all" and item.type != target_type:
                continue
            if norm_classes and item.class_code not in norm_classes:
                continue

            item_code_lower = item.code.lower()
            item_name_lower = item.name.lower()

            hit_count = 0
            best_tier = 4

            for t in terms:
                if (item_code_lower and item_code_lower == t) or (item_name_lower == t):
                    tier = 0
                elif item_code_lower and item_code_lower.startswith(t):
                    tier = 1
                elif item_name_lower.startswith(t):
                    tier = 2
                elif t in item_name_lower:
                    tier = 3
                else:
                    tier = None

                if tier is not None:
                    hit_count += 1
                    if tier < best_tier:
                        best_tier = tier

            if hit_count > 0:
                item.score_tier = best_tier
                matched_items.append((best_tier, -hit_count, type_order.get(item.type, 9), len(item.name), item))

        matched_items.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        return [x[4] for x in matched_items[:limit]]
    else:
        # 默认模式：单关键词或多关键词 AND
        if len(terms) == 1:
            q = terms[0]
            tier0: list[SearchResultItem] = []
            tier1: list[SearchResultItem] = []
            tier2: list[SearchResultItem] = []
            tier3: list[SearchResultItem] = []

            for item in entities:
                if target_type != "all" and item.type != target_type:
                    continue
                if norm_classes and item.class_code not in norm_classes:
                    continue

                item_code_lower = item.code.lower()
                item_name_lower = item.name.lower()

                if (item_code_lower and item_code_lower == q) or (item_name_lower == q):
                    item.score_tier = 0
                    tier0.append(item)
                elif item_code_lower and item_code_lower.startswith(q):
                    item.score_tier = 1
                    tier1.append(item)
                elif item_name_lower.startswith(q):
                    item.score_tier = 2
                    tier2.append(item)
                elif q in item_name_lower:
                    item.score_tier = 3
                    tier3.append(item)

            for bucket in (tier0, tier1, tier2, tier3):
                bucket.sort(key=lambda x: (type_order.get(x.type, 9), len(x.name)))

            combined = tier0 + tier1 + tier2 + tier3
            return combined[:limit]
        else:
            and_matched: list[tuple[int, int, SearchResultItem]] = []
            for item in entities:
                if target_type != "all" and item.type != target_type:
                    continue
                if norm_classes and item.class_code not in norm_classes:
                    continue

                item_code_lower = item.code.lower()
                item_name_lower = item.name.lower()

                if all((t in item_name_lower or (item_code_lower and t in item_code_lower)) for t in terms):
                    and_matched.append((type_order.get(item.type, 9), len(item.name), item))

            and_matched.sort(key=lambda x: (x[0], x[1]))
            return [x[2] for x in and_matched[:limit]]


def format_text(results: list[SearchResultItem], query_display: str) -> str:
    if not results:
        return f"检索 '{query_display}' 未命中任何结果。"

    type_cn = {"class": "【大类】", "group": "【类似群】", "item": "【商品项】"}
    lines: list[str] = [f"检索 '{query_display}' 命中 {len(results)} 条记录:"]
    lines.append(f"{'类型':<8} {'代码':<10} {'名称':<28} {'所属类别/类似群'}")
    lines.append("-" * 75)

    for r in results:
        t_label = type_cn.get(r.type, r.type)
        c_label = r.code if r.code else "-"
        loc = f"第{r.class_code}类"
        if r.group_code:
            loc += f" / {r.group_code} {r.group_name}"
        lines.append(f"{t_label:<8} {c_label:<10} {r.name:<28} {loc}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="跨类别全局检索大类、类似群及商品/服务项"
    )
    default_data_dir = Path(__file__).resolve().parent.parent / "data"

    parser.add_argument(
        "query",
        nargs="+",
        type=str,
        help="检索关键词或编号（如 '喂食器'、'0901'、'软件'，支持传入多个关键词）",
    )
    parser.add_argument(
        "--any",
        action="store_true",
        help="多关键词 OR 检索模式（任一关键词命中即返回候选，默认需全部匹配）",
    )
    parser.add_argument(
        "-c",
        "--classes",
        nargs="+",
        default=None,
        help="限制在大类范围内检索（如 -c 09 21 30）",
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=["all", "class", "group", "item"],
        default="all",
        help="搜索对象类型：all(全部), class(大类), group(类似群), item(商品服务项)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=50,
        help="最多返回条数（默认 50 条）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="数据目录路径（默认指向 Skill 内部 data/）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出检索结果",
    )

    args = parser.parse_args()

    try:
        entities = load_all_search_entities(args.data_dir.resolve())
        results = execute_search(
            entities,
            query=args.query,
            target_type=args.type,
            class_filter=args.classes,
            match_any=args.any,
            limit=args.limit,
        )

        query_display = " | ".join(args.query) if args.any else " ".join(args.query)
        if args.json:
            json_data = [asdict(r) for r in results]
            print(json.dumps(json_data, ensure_ascii=False, indent=2))
        else:
            print(format_text(results, query_display))

        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
