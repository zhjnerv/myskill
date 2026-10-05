#!/usr/bin/env python3
"""案件目录里的可续跑流程计划。动手前生成全部步骤，每步结束后立即回写。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_ID = "cn-patent-workflow-plan/v1"
PLAN_JSON = "流程计划.json"
PLAN_MD = "流程计划.md"
EXIT_SUCCESS = 0
EXIT_INPUT_ERROR = 3
STEP_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STATUSES = {"pending", "running", "done", "skipped", "waiting", "blocked"}
STATUS_LABEL = {
    "pending": "未开始",
    "running": "进行中",
    "done": "已完成",
    "skipped": "已跳过",
    "waiting": "等待人工",
    "blocked": "已阻断",
}

# 完整申请的步骤一次列全。可选步骤不自动消失，不适用时必须显式 skip。
FULL_APPLICATION: tuple[tuple[str, str, str, bool, str], ...] = (
    ("intake", "受理", "cn-patent-application-creator", False, "pending"),
    ("mining", "发明挖掘", "cn-patent-application-creator", False, "pending"),
    ("history-mining", "历史挖掘", "cn-patent-application-creator", True, "pending"),
    ("search-template", "检索与范本", "cn-patent-application-creator", False, "pending"),
    ("ledger-gate", "区别特征表与阶段门", "cn-patent-application-creator", False, "pending"),
    ("drafting", "权利要求与说明书", "cn-patent-application-creator", False, "pending"),
    ("integrity", "数据流、架构门与创造性地图", "cn-patent-application-creator", False, "pending"),
    ("drawing-brief", "附图绘制简报", "cn-patent-diagram-generator", True, "pending"),
    ("style-brief", "用户范例与样式简报", "cn-patent-diagram-generator", True, "pending"),
    ("drawing-rebuild", "同图修改稿安全重建", "cn-patent-diagram-generator", True, "pending"),
    ("drawings", "说明书附图", "cn-patent-diagram-generator", True, "pending"),
    ("review", "综合审查", "cn-patent-reviewer", False, "pending"),
    ("red-team", "两支红队", "cn-patent-application-creator", False, "pending"),
    ("pending-file", "汇总待决文件", "cn-patent-application-creator", False, "pending"),
    ("docx", "组装审稿版与提交版", "cn-patent-application-creator", True, "pending"),
    ("docx-verify", "DOCX 与附图交付复验", "cn-patent-application-creator", True, "pending"),
    ("pending-round", "读取待决文件并修订申请文件", "cn-patent-application-creator", True, "waiting"),
)


class PlanError(ValueError):
    """计划文件缺失、损坏或状态转移不合法。"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plan_paths(case_dir: Path) -> tuple[Path, Path]:
    return case_dir / PLAN_JSON, case_dir / PLAN_MD


def blank_step(step_id: str, title: str, skill: str, optional: bool, status: str) -> dict[str, Any]:
    if not STEP_ID_RE.fullmatch(step_id):
        raise PlanError(f"步骤编号不合法：{step_id}")
    if status not in {"pending", "waiting"}:
        raise PlanError("新步骤只能是 pending 或 waiting")
    if status == "waiting" and not optional:
        raise PlanError("等待人工只允许用于可选步骤")
    if not title.strip() or not skill.strip():
        raise PlanError("步骤标题和技能不能为空")
    return {
        "id": step_id,
        "title": title.strip(),
        "skill": skill.strip(),
        "optional": optional,
        "status": status,
        "note": "",
        "outputs": [],
        "started_at": None,
        "finished_at": None,
    }


def full_steps() -> list[dict[str, Any]]:
    return [blank_step(*item) for item in FULL_APPLICATION]


def parse_step_arg(raw: str) -> dict[str, Any]:
    parts = raw.split("|")
    if len(parts) not in {4, 5}:
        raise PlanError("自定义步骤格式：id|标题|技能|optional或required|pending或waiting")
    status = parts[4] if len(parts) == 5 else "pending"
    if parts[3] not in {"optional", "required"}:
        raise PlanError("步骤第四段只能是 optional 或 required")
    return blank_step(parts[0], parts[1], parts[2], parts[3] == "optional", status)


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema_id") != SCHEMA_ID:
        raise PlanError("流程计划 schema 不匹配")
    if not str(plan.get("objective") or "").strip():
        raise PlanError("流程计划缺少目标")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlanError("流程计划没有步骤")
    seen: set[str] = set()
    running = 0
    for step in steps:
        if not isinstance(step, dict) or step.get("id") in seen:
            raise PlanError("流程计划有缺失或重复的步骤")
        seen.add(step["id"])
        if step.get("status") not in STATUSES or not isinstance(step.get("optional"), bool):
            raise PlanError(f"步骤状态损坏：{step.get('id')}")
        if not isinstance(step.get("outputs"), list):
            raise PlanError(f"步骤输出损坏：{step.get('id')}")
        if step["status"] == "running":
            running += 1
    if running > 1:
        raise PlanError("流程计划里有多个进行中的步骤")


def load_plan(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PlanError(f"无法读取流程计划：{exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PlanError("流程计划含 BOM")
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"流程计划不是合法 JSON：{exc}") from exc
    validate_plan(plan)
    return plan


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def render_markdown(plan: dict[str, Any], nxt: dict[str, str]) -> str:
    lines = [
        "# 流程计划",
        "",
        "中断后不要从头开始。先运行 `workflow_plan.py next`，只做它给出的那一步。",
        "状态是进行中的步骤视为没做完，必须重做，不能改记为已完成。",
        "",
        f"- 目标：{plan['objective']}",
        f"- 档案：{plan['profile']}",
        f"- 更新时间：{plan['updated_at']}",
        (
            f"- 下一步：{nxt['NEXT_ACTION']} {nxt.get('NEXT_STEP', '')} "
            f"{nxt.get('NEXT_TITLE', '')}"
        ).rstrip(),
        "",
        "## 步骤",
        "",
    ]
    for step in plan["steps"]:
        mark = "x" if step["status"] in {"done", "skipped"} else " "
        lines.append(f"- [{mark}] `{step['id']}` {step['title']}")
        lines.append(f"  - 状态：{STATUS_LABEL[step['status']]}")
        lines.append(f"  - 技能：{step['skill']}")
        lines.append(f"  - 可选：{'是' if step['optional'] else '否'}")
        if step["note"]:
            lines.append(f"  - 备注：{step['note']}")
        if step["outputs"]:
            lines.append("  - 输出：" + "；".join(step["outputs"]))
    lines.append("")
    return "\n".join(lines)


def decide_next(plan: dict[str, Any]) -> dict[str, str]:
    for step in plan["steps"]:
        status = step["status"]
        if status == "running":
            action = "redo"
        elif status == "blocked":
            action = "blocked"
        elif status == "pending":
            action = "start"
        elif status == "waiting":
            action = "wait-human"
        else:
            continue
        return {
            "NEXT_ACTION": action,
            "NEXT_STEP": step["id"],
            "NEXT_TITLE": step["title"],
            "NEXT_SKILL": step["skill"],
            "NEXT_OPTIONAL": "yes" if step["optional"] else "no",
        }
    return {"NEXT_ACTION": "done"}


def print_next(plan: dict[str, Any]) -> dict[str, str]:
    nxt = decide_next(plan)
    for key, value in nxt.items():
        print(f"{key}={value}")
    return nxt


def save_plan(case_dir: Path, plan: dict[str, Any]) -> None:
    validate_plan(plan)
    plan["updated_at"] = now()
    nxt = decide_next(plan)
    json_path, md_path = plan_paths(case_dir)
    atomic_write(json_path, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    atomic_write(md_path, render_markdown(plan, nxt))
    print_next(plan)


def require_case(path: Path) -> Path:
    case_dir = path.resolve()
    if not case_dir.is_dir():
        raise PlanError(f"案件目录不存在：{case_dir}")
    return case_dir


def find_step(plan: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in plan["steps"]:
        if step["id"] == step_id:
            return step
    raise PlanError(f"计划中没有步骤：{step_id}")


def assert_previous_settled(plan: dict[str, Any], step_id: str) -> None:
    for step in plan["steps"]:
        if step["id"] == step_id:
            return
        if step["status"] not in {"done", "skipped"}:
            raise PlanError(f"前序步骤 {step['id']} 仍是 {step['status']}，不能越过")


def cmd_init(args: argparse.Namespace) -> int:
    case_dir = require_case(Path(args.case_dir))
    json_path, _ = plan_paths(case_dir)
    if json_path.exists() and not args.force:
        plan = load_plan(json_path)
        print("PLAN_EXISTS")
        print_next(plan)
        return EXIT_SUCCESS
    if bool(args.profile) == bool(args.step):
        raise PlanError("init 必须且只能二选一：--profile full-application，或重复 --step")
    objective = args.objective.strip()
    if not objective:
        raise PlanError("目标不能为空")
    steps = full_steps() if args.profile else [parse_step_arg(item) for item in args.step]
    if len({item["id"] for item in steps}) != len(steps):
        raise PlanError("步骤编号重复")
    created = now()
    plan = {
        "schema_id": SCHEMA_ID,
        "case_id": case_dir.name,
        "objective": objective,
        "profile": args.profile or "custom",
        "created_at": created,
        "updated_at": created,
        "steps": steps,
    }
    save_plan(case_dir, plan)
    print("PLAN_CREATED")
    return EXIT_SUCCESS


def with_plan(args: argparse.Namespace, mutate: Callable[[dict[str, Any]], None]) -> int:
    case_dir = require_case(Path(args.case_dir))
    json_path, _ = plan_paths(case_dir)
    if not json_path.exists():
        raise PlanError("还没有流程计划。先 init，再执行步骤")
    plan = load_plan(json_path)
    mutate(plan)
    save_plan(case_dir, plan)
    return EXIT_SUCCESS


def cmd_start(args: argparse.Namespace) -> int:
    def mutate(plan: dict[str, Any]) -> None:
        if any(step["status"] == "running" for step in plan["steps"]):
            raise PlanError("已有进行中的步骤。它没做完，先重做并 complete、skip 或 block")
        step = find_step(plan, args.step)
        assert_previous_settled(plan, step["id"])
        if step["status"] not in {"pending", "waiting"}:
            raise PlanError(f"{step['id']} 当前是 {step['status']}，不能开始")
        step["status"] = "running"
        step["started_at"] = now()
        step["finished_at"] = None
    return with_plan(args, mutate)


def cmd_complete(args: argparse.Namespace) -> int:
    note = args.note.strip()
    if not note:
        raise PlanError("完成步骤时必须写备注")

    def mutate(plan: dict[str, Any]) -> None:
        step = find_step(plan, args.step)
        if step["status"] != "running":
            raise PlanError("只有进行中的步骤可以记成完成")
        step["status"] = "done"
        step["note"] = note
        step["outputs"] = list(args.output)
        step["finished_at"] = now()
    return with_plan(args, mutate)


def cmd_skip(args: argparse.Namespace) -> int:
    note = args.note.strip()
    if not note:
        raise PlanError("跳过步骤时必须写明原因")

    def mutate(plan: dict[str, Any]) -> None:
        step = find_step(plan, args.step)
        if not step["optional"]:
            raise PlanError("必做步骤不能跳过")
        if step["status"] not in {"pending", "waiting"}:
            raise PlanError("只有未开始或等待人工的可选步骤可以跳过")
        assert_previous_settled(plan, step["id"])
        step["status"] = "skipped"
        step["note"] = note
        step["finished_at"] = now()
    return with_plan(args, mutate)


def cmd_block(args: argparse.Namespace) -> int:
    note = args.note.strip()
    if not note:
        raise PlanError("阻断步骤时必须写明原因")

    def mutate(plan: dict[str, Any]) -> None:
        step = find_step(plan, args.step)
        if step["status"] not in {"pending", "running", "waiting"}:
            raise PlanError("当前状态不能改为阻断")
        step["status"] = "blocked"
        step["note"] = note
        step["finished_at"] = now()
    return with_plan(args, mutate)


def reopen_step(step: dict[str, Any], note: str) -> None:
    if step["status"] == "running":
        raise PlanError(f"{step['id']} 正在进行，不能直接重开")
    if step["status"] == "pending":
        raise PlanError(f"{step['id']} 还没开始，不必重开")
    step["status"] = "pending"
    step["note"] = note
    step["outputs"] = []
    step["started_at"] = None
    step["finished_at"] = None


def cmd_reopen(args: argparse.Namespace) -> int:
    note = args.note.strip()
    if not note:
        raise PlanError("重开步骤时必须写明原因")

    def mutate(plan: dict[str, Any]) -> None:
        find_step(plan, args.step)
        found = False
        for step in plan["steps"]:
            if step["id"] == args.step:
                reopen_step(step, note)
                found = True
                if not args.cascade:
                    break
                continue
            if found and args.cascade and step["status"] == "done":
                reopen_step(step, note)
    return with_plan(args, mutate)


def cmd_next(args: argparse.Namespace) -> int:
    case_dir = require_case(Path(args.case_dir))
    json_path, _ = plan_paths(case_dir)
    if not json_path.exists():
        raise PlanError("还没有流程计划。先 init")
    print_next(load_plan(json_path))
    return EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="维护可中断续跑的中国专利申请流程计划")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--case-dir", required=True)
    init.add_argument("--objective", required=True)
    init.add_argument("--profile", choices=["full-application"])
    init.add_argument("--step", action="append", default=[])
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    for name, func in (
        ("start", cmd_start), ("complete", cmd_complete), ("skip", cmd_skip),
        ("block", cmd_block), ("reopen", cmd_reopen), ("next", cmd_next),
    ):
        command = sub.add_parser(name)
        command.add_argument("--case-dir", required=True)
        command.set_defaults(func=func)
        if name != "next":
            command.add_argument("--step", required=True)
        if name in {"complete", "skip", "block", "reopen"}:
            command.add_argument("--note", required=True)
        if name == "complete":
            command.add_argument("--output", action="append", default=[])
        if name == "reopen":
            command.add_argument("--cascade", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except PlanError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":
    sys.exit(main())
