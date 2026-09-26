#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from cn_drafting_io import DraftingOutputGuard

SCHEMA_ID = "cn-patent-pending-decisions/v1"
EXIT_SUCCESS = 0
EXIT_INPUT_ERROR = 3

def read_json_report(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            raw = f.read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raise ValueError(f"含 BOM，必须使用 UTF-8 无 BOM：{path}")
            return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise
    except Exception as exc:
        raise ValueError(f"读取报告失败 {path}: {exc}") from exc

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def validate_decision(d: dict, report_path: Path) -> None:
    required = [
        "key", "source", "target", "question",
        "adopted_default", "options", "impact", "decider"
    ]
    for r in required:
        if r not in d:
            raise ValueError(f"[{report_path}] 缺少必填字段: {r}")
    if not isinstance(d.get("source"), dict) or "tool_id" not in d["source"] or "rule_id" not in d["source"]:
        raise ValueError(f"[{report_path}] source 缺少必填字段")
    if not isinstance(d.get("target"), dict) or "kind" not in d["target"] or "locator" not in d["target"]:
        raise ValueError(f"[{report_path}] target 缺少必填字段")

def main() -> int:
    parser = argparse.ArgumentParser(description="Collect pending decisions")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--table", required=True)
    args = parser.parse_args()

    input_paths = [Path(p) for p in args.report]
    output_paths = [Path(args.output), Path(args.table)]

    try:
        guard = DraftingOutputGuard(input_paths, output_paths)
    except Exception as exc:
        print(f"路径冲突: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    sources = []
    collected_decisions_map = {}

    try:
        for rp in input_paths:
            data = read_json_report(rp)
            pds = data.get("pending_decisions")
            if pds is None:
                sources.append({
                    "tool_id": data.get("tool_id", "unknown"),
                    "report_path": str(rp),
                    "sha256": sha256_file(rp),
                    "count": 0
                })
                continue

            if not isinstance(pds, list):
                raise ValueError(f"[{rp}] pending_decisions 必须是数组")

            count = 0
            for d in pds:
                validate_decision(d, rp)
                k = f"{d['key']}::{d['target']['locator']}"
                if k not in collected_decisions_map:
                    d_copy = dict(d)
                    d_copy["duplicates_of"] = []
                    collected_decisions_map[k] = d_copy
                    count += 1
                else:
                    collected_decisions_map[k]["duplicates_of"].append({
                        "tool_id": d["source"]["tool_id"],
                        "rule_id": d["source"]["rule_id"]
                    })
            sources.append({
                "tool_id": data.get("tool_id", "unknown"),
                "report_path": str(rp),
                "sha256": sha256_file(rp),
                "count": count
            })
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"处理失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    # 排序并分配 ID
    # 按 key+target.locator 排序
    sorted_keys = sorted(collected_decisions_map.keys())
    decisions = []

    summary = {
        "decider": {"inventor": 0, "attorney": 0, "both": 0},
        "impact": {"protection_scope": 0, "grant_risk": 0, "formality": 0, "delivery": 0, "evidence": 0}
    }

    for idx, k in enumerate(sorted_keys):
        d = collected_decisions_map[k]
        d["id"] = f"D{idx + 1:03d}"
        if not d["duplicates_of"]:
            del d["duplicates_of"]
        decisions.append(d)

        decider = d["decider"]
        if decider not in summary["decider"]:
            summary["decider"][decider] = 0
        summary["decider"][decider] += 1

        for imp in d["impact"]:
            if imp not in summary["impact"]:
                summary["impact"][imp] = 0
            summary["impact"][imp] += 1

    case_id = Path(args.case_dir).name
    now_str = datetime.now(timezone.utc).isoformat()

    out_json = {
        "schema_id": SCHEMA_ID,
        "case_id": case_id,
        "generated_at": now_str,
        "legal_effect": "ADVISORY_ONLY",
        "sources": sources,
        "decisions": decisions,
        "summary": summary
    }

    # Write JSON
    try:
        guard.check()
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out_json, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as exc:
        print(f"写入 JSON 失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    # Write Markdown
    # 表：编号 / 位置 / 问题 / 已采用默认 / 备选 / 影响 / 决策人；按 decider 分组，both 排最前
    md_lines = ["# 待决事项清单\n"]
    if not decisions:
        md_lines.append("当前无待决事项。\n")
    else:
        decider_groups = {"both": [], "inventor": [], "attorney": []}
        for d in decisions:
            decider_groups.setdefault(d["decider"], []).append(d)

        for group in ["both", "inventor", "attorney"]:
            group_decisions = decider_groups.get(group, [])
            if not group_decisions:
                continue

            md_lines.append(f"## 决策人: {group}\n")
            md_lines.append("| 编号 | 位置 | 问题 | 已采用默认 | 备选 | 影响 | 决策人 |")
            md_lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for d in group_decisions:
                loc = f"{d['target']['kind']}:{d['target']['locator']}"
                opts = "<br>".join(d["options"])
                imps = ", ".join(d["impact"])
                md_lines.append(f"| {d['id']} | {loc} | {d['question']} | {d['adopted_default']} | {opts} | {imps} | {d['decider']} |")
            md_lines.append("")

    try:
        Path(args.table).parent.mkdir(parents=True, exist_ok=True)
        with open(args.table, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
    except Exception as exc:
        print(f"写入 Markdown 失败: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    return EXIT_SUCCESS

if __name__ == "__main__":
    sys.exit(main())
