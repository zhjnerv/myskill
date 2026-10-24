import json
import subprocess
import sys


PLAN = "skills/cn-patent-workflow/scripts/workflow_plan.py"
FULL_IDS = [
    "intake", "mining", "history-mining", "search-template", "ledger-gate", "drafting",
    "integrity", "drawing-brief", "style-brief", "drawing-rebuild", "drawings", "review",
    "red-team", "pending-file", "docx", "docx-verify", "pending-round",
]


def run_plan(tmp_path, *args):
    cmd = [sys.executable, PLAN, *args, "--case-dir", str(tmp_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_full_plan_is_created_before_work_and_survives_reinit(tmp_path):
    created = run_plan(tmp_path, "init", "--profile", "full-application", "--objective", "完成申请文件")
    assert created.returncode == 0, created.stderr
    assert "PLAN_CREATED" in created.stdout
    assert "NEXT_ACTION=start" in created.stdout
    assert "NEXT_STEP=intake" in created.stdout
    plan_json = tmp_path / "流程计划.json"
    plan_md = tmp_path / "流程计划.md"
    assert plan_json.is_file()
    assert plan_md.is_file()
    payload = json.loads(plan_json.read_text(encoding="utf-8"))
    assert [step["id"] for step in payload["steps"]] == FULL_IDS
    assert payload["steps"][-1]["status"] == "waiting"
    assert "中断后不要从头开始" in plan_md.read_text(encoding="utf-8")

    again = run_plan(tmp_path, "init", "--profile", "full-application", "--objective", "别的目标")
    assert again.returncode == 0, again.stderr
    assert "PLAN_EXISTS" in again.stdout
    assert json.loads(plan_json.read_text(encoding="utf-8"))["objective"] == "完成申请文件"


def test_steps_update_in_order_and_running_step_is_redone(tmp_path):
    init = run_plan(
        tmp_path, "init", "--objective", "只走两步",
        "--step", "intake|受理|cn-patent-application-creator|required",
        "--step", "drafting|撰写|cn-patent-application-creator|required",
        "--step", "drawings|附图|cn-patent-diagram-generator|optional",
        "--step", "pending-round|回读待决文件|cn-patent-application-creator|optional|waiting",
    )
    assert init.returncode == 0, init.stderr
    skipped = run_plan(tmp_path, "skip", "--step", "drawings", "--note", "还没到")
    assert skipped.returncode == 3

    started = run_plan(tmp_path, "start", "--step", "intake")
    assert started.returncode == 0, started.stderr
    assert "NEXT_ACTION=redo" in started.stdout
    jumped = run_plan(tmp_path, "start", "--step", "drafting")
    assert jumped.returncode == 3
    bare_complete = run_plan(tmp_path, "complete", "--step", "drafting", "--note", "没开始就完成")
    assert bare_complete.returncode == 3

    done = run_plan(tmp_path, "complete", "--step", "intake", "--note", "日期已核对", "--output", "受理记录.md")
    assert done.returncode == 0, done.stderr
    assert "NEXT_STEP=drafting" in done.stdout
    payload = json.loads((tmp_path / "流程计划.json").read_text(encoding="utf-8"))
    intake = payload["steps"][0]
    assert intake["status"] == "done"
    assert intake["outputs"] == ["受理记录.md"]

    required_skip = run_plan(tmp_path, "skip", "--step", "drafting", "--note", "想跳过")
    assert required_skip.returncode == 3
    run_plan(tmp_path, "start", "--step", "drafting")
    run_plan(tmp_path, "complete", "--step", "drafting", "--note", "四文书已落盘")
    skip_drawings = run_plan(tmp_path, "skip", "--step", "drawings", "--note", "用户不要附图")
    assert skip_drawings.returncode == 0, skip_drawings.stderr
    waiting = run_plan(tmp_path, "next")
    assert "NEXT_ACTION=wait-human" in waiting.stdout
    assert "NEXT_STEP=pending-round" in waiting.stdout


def test_reopen_cascades_only_completed_later_steps(tmp_path):
    run_plan(
        tmp_path, "init", "--objective", "重开",
        "--step", "review|审查|cn-patent-reviewer|required",
        "--step", "docx|组装|cn-patent-application-creator|optional",
        "--step", "drawings|附图|cn-patent-diagram-generator|optional",
    )
    run_plan(tmp_path, "start", "--step", "review")
    run_plan(tmp_path, "complete", "--step", "review", "--note", "审查完成")
    run_plan(tmp_path, "start", "--step", "docx")
    run_plan(tmp_path, "complete", "--step", "docx", "--note", "已组装")
    run_plan(tmp_path, "skip", "--step", "drawings", "--note", "无附图")
    reopened = run_plan(tmp_path, "reopen", "--step", "review", "--cascade", "--note", "待决决议改了权利要求")
    assert reopened.returncode == 0, reopened.stderr
    payload = json.loads((tmp_path / "流程计划.json").read_text(encoding="utf-8"))
    by_id = {step["id"]: step for step in payload["steps"]}
    assert by_id["review"]["status"] == "pending"
    assert by_id["docx"]["status"] == "pending"
    assert by_id["drawings"]["status"] == "skipped"
    nxt = run_plan(tmp_path, "next")
    assert "NEXT_STEP=review" in nxt.stdout


def _plan(tmp_path):
    return json.loads((tmp_path / "流程计划.json").read_text(encoding="utf-8"))


def test_reopen_upstream_while_later_step_is_running(tmp_path):
    """回读进行中时重开上游，next 推荐的步骤必须能够 start，并留下完成记录。"""

    init = run_plan(
        tmp_path, "init", "--objective", "重开进行中的下游",
        "--step", "drafting|撰写|cn-patent-application-creator|required",
        "--step", "pending-round|待决回读|cn-patent-application-creator|optional|waiting",
    )
    assert init.returncode == 0, init.stderr
    assert run_plan(tmp_path, "start", "--step", "drafting").returncode == 0
    done = run_plan(
        tmp_path, "complete", "--step", "drafting", "--note", "已验证", "--output", "权利要求书.md",
    )
    assert done.returncode == 0, done.stderr
    assert run_plan(tmp_path, "start", "--step", "pending-round").returncode == 0
    reopened = run_plan(tmp_path, "reopen", "--step", "drafting", "--cascade", "--note", "人工决定修改源稿")
    assert reopened.returncode == 0, reopened.stderr
    payload = _plan(tmp_path)
    by_id = {step["id"]: step for step in payload["steps"]}
    assert by_id["drafting"]["status"] == "pending"
    assert by_id["pending-round"]["status"] == "pending"
    assert by_id["drafting"]["history"][0]["status"] == "done"
    assert by_id["drafting"]["history"][0]["note"] == "已验证"
    assert by_id["drafting"]["history"][0]["outputs"] == ["权利要求书.md"]
    assert by_id["pending-round"]["history"][0]["status"] == "running"
    nxt = run_plan(tmp_path, "next")
    assert "NEXT_ACTION=start" in nxt.stdout
    assert "NEXT_STEP=drafting" in nxt.stdout
    started = run_plan(tmp_path, "start", "--step", "drafting")
    assert started.returncode == 0, started.stderr


def test_reopen_without_running_and_multiple_done_steps_keep_history(tmp_path):
    init = run_plan(
        tmp_path, "init", "--objective", "多个下游",
        "--step", "review|审查|cn-patent-reviewer|required",
        "--step", "docx|组装|cn-patent-application-creator|required",
        "--step", "drawings|附图|cn-patent-diagram-generator|optional",
    )
    assert init.returncode == 0, init.stderr
    for step_id, note in (("review", "审查完成"), ("docx", "已组装"), ("drawings", "附图完成")):
        assert run_plan(tmp_path, "start", "--step", step_id).returncode == 0
        assert run_plan(tmp_path, "complete", "--step", step_id, "--note", note).returncode == 0
    reopened = run_plan(tmp_path, "reopen", "--step", "review", "--note", "只重开审查")
    assert reopened.returncode == 0, reopened.stderr
    by_id = {step["id"]: step for step in _plan(tmp_path)["steps"]}
    assert by_id["review"]["status"] == "pending"
    assert by_id["review"]["history"][0]["status"] == "done"
    assert by_id["review"]["history"][0]["note"] == "审查完成"
    assert by_id["docx"]["status"] == "done"
    assert "history" not in by_id["docx"]
    cascaded = run_plan(tmp_path, "reopen", "--step", "review", "--cascade", "--note", "下游也要重做")
    assert cascaded.returncode == 3
    # review 已经是 pending，先把它做完再级联，覆盖多个已完成下游。
    assert run_plan(tmp_path, "start", "--step", "review").returncode == 0
    assert run_plan(tmp_path, "complete", "--step", "review", "--note", "再次审查").returncode == 0
    cascaded = run_plan(tmp_path, "reopen", "--step", "review", "--cascade", "--note", "下游也要重做")
    assert cascaded.returncode == 0, cascaded.stderr
    by_id = {step["id"]: step for step in _plan(tmp_path)["steps"]}
    assert [by_id[item]["status"] for item in ("review", "docx", "drawings")] == ["pending", "pending", "pending"]
    assert by_id["docx"]["history"][-1]["status"] == "done"
    assert by_id["docx"]["history"][-1]["note"] == "已组装"
    assert by_id["drawings"]["history"][-1]["note"] == "附图完成"
    started = run_plan(tmp_path, "start", "--step", "review")
    assert started.returncode == 0, started.stderr
