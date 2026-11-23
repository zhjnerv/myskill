# TASK_PLAN：本地 main 齐平远端

## 目标与范围

把本地 `main` 从 `d58eec4` 快进到远端 `origin/main` 的 `c3e3fb7`。保留无关的 [choice-oracle 计划](TASK_PLAN_choice-oracle.md)修改、全部未跟踪任务计划和 `临时目录/`。不提交、不推送，也不改写历史。

## 重要约束

- 用户已明确要求直接拉齐；只使用 `git pull --ff-only`，不做普通 merge。
- 拉取前在仓库外保存并复验 dirty/index 快照。
- 本地 `registry.json` 和 44 个删除路径必须与 `origin/main` 对应内容一致，避免把真实本地成果当成重复内容。
- 若 Git 因 dirty 工作区拒绝，保留现场并停止；不使用 stash、reset、checkout 或强制合并。

## 步骤与验证

- [x] 核对本地 HEAD、远端 HEAD、dirty/index 和提交内容。结果：本地 `d58eec4`，远端 `c3e3fb7`；重复内容与远端提交一致，另有 1 个无关已跟踪修改和未跟踪文件。
- [x] 创建并复验仓外快照。完成标准：快照和账本均返回 PASS，覆盖工作区与 index。结果：快照 `20261103T144055Z-pre-ff-sync-legal-removal-4fbcae67` 创建和复验均为 PASS，覆盖 66 个工作区路径。
- [x] 执行 `git pull --ff-only origin main`。完成标准：命令成功，本地 HEAD 与远端一致；失败时工作区保持可恢复状态。结果：首次因重复 registry 修改被拒；精确撤销后重新快照并复验，第二次 fast-forward 成功。
- [x] 核验最终状态。完成标准：HEAD 齐平，重复删除/registry 改动消失，无关修改与未跟踪文件保留。结果：HEAD 与 `origin/main` 均为 `c3e3fb7`，双方独有提交均为 0；仅保留 `TASK_PLAN_choice-oracle.md` 修改和未跟踪任务材料。

## 当前进度

全部步骤已完成。本地已齐平远端，未提交、未推送、未改写历史。

## 下一步动作

本轮无剩余步骤。仓外恢复快照保留在 `/tmp/myskill-main-safety.sHdtDu/myskill/`。
