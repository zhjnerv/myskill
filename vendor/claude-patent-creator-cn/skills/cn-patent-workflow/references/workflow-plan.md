# 可续跑的流程计划

完整申请或单阶段任务，在读取子 Skill 正文和运行阶段命令之前，先把本次要做的全部步骤写进案件目录。没有 `流程计划.json` 就还没开始。

## 文件

- `<案件目录>/流程计划.json`：`cn-patent-workflow-plan/v1`，续跑时只信它。
- `<案件目录>/流程计划.md`：给人看的同一份计划，每次状态变化都重写。

`init` 发现计划已在时不会覆盖。除非用户明确要求作废，否则不要加 `--force`。

## 命令

```bash
python3 "$ROOT/scripts/run_python.py" \
  "$ROOT/skills/cn-patent-workflow/scripts/workflow_plan.py" init \
  --case-dir "<案件目录>" --profile full-application --objective "<这次要完成的事>"
```

单阶段不用完整档案。用重复的 `--step id|标题|技能|required` 把本次步骤一次列全。可选步骤第四段写 `optional`；只有可选步骤可以第五段写 `waiting`。

```bash
workflow_plan.py start  --case-dir "<案件目录>" --step <id>
workflow_plan.py complete --case-dir "<案件目录>" --step <id> --note "<做了什么>" --output "<产物>"
workflow_plan.py skip   --case-dir "<案件目录>" --step <id> --note "<为何不做>"
workflow_plan.py block  --case-dir "<案件目录>" --step <id> --note "<硬阻断原因>"
workflow_plan.py reopen --case-dir "<案件目录>" --step <id> --cascade --note "<为何打回>"
workflow_plan.py next   --case-dir "<案件目录>"
```

## 状态

- `pending`：未开始。
- `running`：已经开始。进程中断后它仍是 `running`，`next` 给出 `redo`。必须重做，不能直接记成完成。
- `done`：这一步结束时立刻 `complete`。没有备注不能完成。
- `skipped`：只允许可选步骤，而且要写明原因。不能跳过还没轮到的步骤。
- `waiting`：等人。完整档案里只有最后的 `pending-round` 初始是这个状态。
- `blocked`：产物无效或不安全。判断题不能用这个状态。

`next` 遇到第一个未结束步骤就停下。`running` 要重做，`blocked` 不能绕过，`pending` 才能开始，`waiting` 表示先读人改过的 `待决文件.md`。全部是 `done` 或 `skipped` 时才是 `done`。

不适用的可选步骤，走到它时 `skip`，不要假装做完。用户没有要求第二轮时，才可以 `skip pending-round`，备注里留下用户原话。

源稿因待决决议改动后，对受影响且已完成的步骤执行 `reopen --cascade`。被跳过的可选步骤保持跳过。
