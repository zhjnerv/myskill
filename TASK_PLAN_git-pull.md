# TASK_PLAN：拉取 origin/main 到本地 main

## 目标与范围

把 `main` 前进到 `origin/main`（`fa0b409`），同时保住本地未提交的工作：

- 未跟踪：`TASK_PLAN_配置GitHub_Actions_token.md`、`docs/github-actions-token-setup.md`
- 本地独有改动：见下方“必须保留”一节
- 12 个已暂存的 `TASK_PLAN_*.md` 保留为未跟踪文件

不改动 `临时目录/` 下的图片，不提交、不推送。

## 重要约束

- 本次只做“拉取”，不替用户决定提交内容。
- 任何清理前先有可恢复快照。
- 远端 `origin/main` 已确认比 `HEAD` 新 26 个提交，且 `HEAD` 是其祖先（可快进）。

## 现状事实

- `HEAD` = `2bf5787`；`origin/main` = `fa0b409`；`git merge-base` 即 `HEAD`，无分叉。
- 索引里 599 条 rename 是旧残留在 `vendor/ip-practice-workbench-skills/skills/` → `skills/` 的暂存状态，不属于 `origin/main`。
- 工作区 45 个文件与 `origin/main` 不同，其中 42 个的 blob 已存在于上游历史（陈旧副本），3 个是真正的本地独有内容。

## 必须保留

| 文件 | 原因 |
| --- | --- |
| `.github/workflows/sync-ip-practice-skills-back.yml` | 本地改写了 `skills` 输入说明 |
| `docs/skills/ip-practice-workbench-skills.md` | 本地指向新的 Token 配置指南 |
| `TASK_PLAN_配置GitHub_Actions_token.md` | 本次任务的未跟踪计划 |
| `docs/github-actions-token-setup.md` | 本次任务的未跟踪文档 |
| `TASK_PLAN*.md`（其余 18 个） | 历史任务记录 |
| `临时目录/` | 与本任务无关的本地图片 |

## 步骤与验证

- [x] 只读检查分支、远端、差异范围、冲突预言。结果：可快进，无分叉；`git merge-tree` 预演无冲突。
- [x] 建立工作区全量快照分支 `backup/pre-pull-20261123`。结果：提交 `d1f5922`，`git diff HEAD d1f5922` 覆盖全部本地新增与改动。
- [x] 把本地独有改动导出为补丁备份到 `/tmp/local_unique.patch`、`/tmp/registry_local.patch`。结果：两个补丁共 85 行，可重放。
- [x] `git reset --mixed origin/main`，让 HEAD/索引指向 `fa0b409`，工作区不动。结果：reset 成功，未丢失任何工作区内容。
- [x] 用 `origin/main` 覆盖 41 个陈旧文件，恢复 `TASK_PLAN_知产技能触发词与双向同步.md`。结果：`git diff origin/main -- skills vendor` 为空；`registry.json` 与上游一致。
- [x] 把 3 个上游已迁址/废弃的未跟踪残留移到 `/tmp/pull-leftovers/`。结果：`vendor/cn-patent-agent-skills/docs/uyanip-command-search-sop.md`（上游已回到 `references/`）、`assets/claim-architecture.example.json`、`assets/stability/legacy-positive-final-verification-v2.json`（上游均无此路径）已移出，需要时可取回。
- [x] 验证。结果：`HEAD` == `origin/main` == `fa0b409`；`git status` 只剩 2 个本地改动、19 个未跟踪项（18 个 `TASK_PLAN*.md` + `docs/github-actions-token-setup.md` + `临时目录/`）。
- [x] 按用户指示删除与项目无关的 `临时目录/` 10 张图片。结果：目录已移出仓库到 `/tmp/myskill-deleted-20261123/`，快照分支 `backup/pre-pull-20261123` 仍保留可恢复副本。
- [x] 提交保留的本地内容。结果：见下方“提交记录”。

## 当前进度

拉取与本地合并均已完成。`main` 在 `fa0b409` 基础上新增本地提交，未推送远端。

## 提交记录

- `45cebe8 docs: 补充 IP 技能反向同步 Token 配置指南`：工作流输入说明、技能维护文档链接、新指南、对应任务计划（4 个文件）
- `docs: 归档历史任务计划`（本文件所在提交）：13 份 `TASK_PLAN_*.md`

两个提交合计 17 个文件、+769/−2；`skills/`、`vendor/`、`registry.json` 与上游零差异。

## 遗留与风险

- 索引里原先 599 条 `vendor/ip-practice-workbench-skills/skills/*` → `skills/*` 的 rename 残留已随 reset 清除；上游本来就只保留 12 个包根文件。
- `skills/qu-ai-wei/tests/{prepare-zhuque.py,zhuque-pilot.md,zhuque-smoke.md}` 的“删除”实为本地副本落后于上游：这三个文件上游自始存在，现已恢复。
- 3 个移出的残留文件内容与上游历史 blob 同源，只是路径被上游调整过；如需保留可自行取回。

## 下一步动作

推送 `main` 到 `origin/main` 需另行确认。恢复点：`backup/pre-pull-20261123`（`d1f5922`）。
