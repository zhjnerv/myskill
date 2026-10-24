#!/usr/bin/env python3
"""校验红队报告是否绑定四文书字节，且待决项可被收集器读取。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from collect_pending_decisions import validate_decision


SCHEMA_ID = "cn-patent-red-team-report/v1"
RESULT_SCHEMA_ID = "cn-patent-red-team-validation/v1"
ROLES = ("claims", "specification", "abstract", "drawings")
RESULTS = {"攻击奏效", "攻击未奏效", "证据不足"}
TEAMS = {"claims", "package"}
DISPOSITIONS = {"RETURN_TO_DRAFTING", "NO_RETURN"}
TARGET_KINDS = {"process", "ledger", "claim", "specification", "abstract", "drawing", "review"}
IMPACTS = {"protection_scope", "grant_risk", "formality", "delivery", "evidence"}
DECIDERS = {"inventor", "attorney", "both"}
PENDING_KEYS = {
    "key", "source", "target", "question", "adopted_default", "options", "impact", "decider",
}
EXIT_OK = 0
EXIT_FAIL = 2
EXIT_INPUT = 3
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ATTACK_ID_RE = re.compile(r"^A\d{3}$")


def read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"含 BOM，必须使用 UTF-8 无 BOM：{path}")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("红队报告顶层必须是对象")
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_in_case(case_dir: Path, raw: str) -> Path:
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (case_dir / path).resolve()
    resolved.relative_to(case_dir.resolve())
    return resolved


def add(errors: list[dict[str, str]], code: str, message: str) -> None:
    errors.append({"code": code, "message": message})


def check_pending(item: Any, index: int, report_path: Path, errors: list[dict[str, str]]) -> None:
    label = f"pending_decisions[{index}]"
    if not isinstance(item, dict):
        add(errors, "RED-PENDING-SHAPE", f"{label} 必须是对象")
        return
    extra = sorted(set(item) - PENDING_KEYS)
    if extra:
        add(errors, "RED-PENDING-SHAPE", f"{label} 含收集器不读取的字段：{extra}")
    if "id" in item:
        add(errors, "RED-PENDING-SHAPE", f"{label} 不得预写编号，由 collect_pending_decisions.py 分配")
    try:
        validate_decision(item, report_path)
    except ValueError as exc:
        add(errors, "RED-PENDING-SHAPE", str(exc))
        return
    source = item["source"]
    target = item["target"]
    if set(source) != {"tool_id", "rule_id"} or not all(isinstance(source[key], str) and source[key].strip() for key in source):
        add(errors, "RED-PENDING-SHAPE", f"{label}.source 只能包含非空 tool_id 与 rule_id")
    if set(target) != {"kind", "locator"}:
        add(errors, "RED-PENDING-SHAPE", f"{label}.target 只能包含 kind 与 locator")
    elif target.get("kind") not in TARGET_KINDS or not isinstance(target.get("locator"), str) or not target["locator"].strip():
        add(errors, "RED-PENDING-SHAPE", f"{label}.target 的 kind 或 locator 无效")
    if item.get("decider") not in DECIDERS:
        add(errors, "RED-PENDING-SHAPE", f"{label}.decider 无效")
    options = item.get("options")
    if not isinstance(options, list) or any(not isinstance(option, str) or not option.strip() for option in options):
        add(errors, "RED-PENDING-SHAPE", f"{label}.options 必须是非空字符串数组")
    impact = item.get("impact")
    if not isinstance(impact, list) or any(value not in IMPACTS for value in impact):
        add(errors, "RED-PENDING-SHAPE", f"{label}.impact 含未登记影响")
    for field in ("key", "question", "adopted_default"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            add(errors, "RED-PENDING-SHAPE", f"{label}.{field} 必须是非空字符串")


def validate(report: dict[str, Any], report_path: Path, case_dir: Path) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    allowed = {
        "schema_id", "case_id", "team", "legal_effect",
        "bound_artifacts", "attacks", "disposition", "pending_decisions",
    }
    extra = sorted(set(report) - allowed)
    missing = sorted(allowed - set(report))
    if extra or missing:
        add(errors, "RED-SCHEMA", f"顶层字段不一致：多出 {extra} / 缺少 {missing}")
        return errors
    if report.get("schema_id") != SCHEMA_ID:
        add(errors, "RED-SCHEMA", f"schema_id 必须是 {SCHEMA_ID}")
    if not isinstance(report.get("case_id"), str) or not report["case_id"].strip():
        add(errors, "RED-SCHEMA", "case_id 必须是非空字符串")
    if report.get("team") not in TEAMS:
        add(errors, "RED-SCHEMA", "team 只能是 claims 或 package")
    if report.get("legal_effect") != "ADVISORY_ONLY":
        add(errors, "RED-SCHEMA", "legal_effect 必须是 ADVISORY_ONLY")

    artifacts = report.get("bound_artifacts")
    if not isinstance(artifacts, list):
        add(errors, "RED-BINDING", "bound_artifacts 必须是数组")
        artifacts = []
    roles: list[str] = []
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict) or set(item) != {"role", "path", "sha256"}:
            add(errors, "RED-BINDING", f"bound_artifacts[{index}] 只能包含 role、path、sha256")
            continue
        role = item["role"]
        roles.append(role)
        if role not in ROLES:
            add(errors, "RED-BINDING", f"未知文书角色：{role}")
            continue
        if not isinstance(item["path"], str) or not item["path"].strip():
            add(errors, "RED-BINDING", f"{role} 路径为空")
            continue
        if not isinstance(item["sha256"], str) or SHA256_RE.fullmatch(item["sha256"]) is None:
            add(errors, "RED-BINDING", f"{role} 的 sha256 必须是 64 位小写十六进制")
            continue
        try:
            path = resolve_in_case(case_dir, item["path"])
        except ValueError:
            add(errors, "RED-BINDING", f"{role} 路径越出案件目录：{item['path']}")
            continue
        if not path.is_file():
            add(errors, "RED-BINDING", f"{role} 文件不存在：{item['path']}")
            continue
        actual = sha256_file(path)
        if actual != item["sha256"]:
            add(errors, "RED-BINDING", f"{role} SHA-256 与当前文件不一致")
    if sorted(roles) != sorted(ROLES) or len(roles) != len(ROLES):
        add(errors, "RED-BINDING", "必须且只能绑定权利要求书、说明书、摘要、附图各一次")

    attacks = report.get("attacks")
    if not isinstance(attacks, list) or not attacks:
        add(errors, "RED-ATTACK", "attacks 必须是非空数组")
        attacks = []
    seen: set[str] = set()
    succeeded = False
    for index, attack in enumerate(attacks):
        if not isinstance(attack, dict) or set(attack) != {"attack_id", "checklist_item", "result", "evidence"}:
            add(errors, "RED-ATTACK", f"attacks[{index}] 字段不符合合同")
            continue
        attack_id = attack["attack_id"]
        if not isinstance(attack_id, str) or ATTACK_ID_RE.fullmatch(attack_id) is None:
            add(errors, "RED-ATTACK", f"attacks[{index}].attack_id 必须形如 A001")
        elif attack_id in seen:
            add(errors, "RED-ATTACK", f"attack_id 重复：{attack_id}")
        else:
            seen.add(attack_id)
        if not isinstance(attack["checklist_item"], str) or not attack["checklist_item"].strip():
            add(errors, "RED-ATTACK", f"{attack_id} 缺少攻击项")
        if attack["result"] not in RESULTS:
            add(errors, "RED-ATTACK", f"{attack_id} 的结果只能是攻击奏效、攻击未奏效或证据不足")
        elif attack["result"] == "攻击奏效":
            succeeded = True
        if not isinstance(attack["evidence"], str) or not attack["evidence"].strip():
            add(errors, "RED-ATTACK", f"{attack_id} 缺少证据")
    expected = "RETURN_TO_DRAFTING" if succeeded else "NO_RETURN"
    if report.get("disposition") not in DISPOSITIONS:
        add(errors, "RED-DISPOSITION", "disposition 只能是 RETURN_TO_DRAFTING 或 NO_RETURN")
    elif report["disposition"] != expected:
        add(errors, "RED-DISPOSITION", f"当前攻击结果对应的 disposition 必须是 {expected}")

    pending = report.get("pending_decisions")
    if not isinstance(pending, list):
        add(errors, "RED-PENDING-SHAPE", "pending_decisions 必须是数组")
    else:
        for index, item in enumerate(pending):
            check_pending(item, index, report_path, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        case_dir = args.case_dir.resolve()
        report_path = args.report.resolve()
        if not case_dir.is_dir():
            raise ValueError(f"案件目录不存在：{case_dir}")
        report = read_json(report_path)
        errors = validate(report, report_path, case_dir)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT
    payload = {
        "schema_id": RESULT_SCHEMA_ID,
        "legal_effect": "ADVISORY_ONLY",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "error_count": len(errors)}, ensure_ascii=False))
    return EXIT_OK if not errors else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
