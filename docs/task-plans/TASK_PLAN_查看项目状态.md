# TASK_PLAN：查看项目状态

## 目标与范围
查看当前仓库的分支、远端同步、未提交改动、技能登记、自动检查和未完成任务；只更新本计划，不改业务文件。以下原记录的检查日期为 2026-11-02，当前 Git 状态与最新新增技能以文末的[简单状态检查](#简单状态检查-2026-11-06)为准；历史测试结果不代表本轮重跑。

## 重要约束
- 不覆盖已有的 [TASK_PLAN.md](TASK_PLAN.md)。
- 本计划在检查开始时已是未跟踪文件；状态汇报时如实说明。
- 不执行同步、部署、提交或清理；远端状态优先以只读查询核对，失败则明确标注。
- 依据 [README.md](../../README.md)、[registry.json](../../registry.json) 和 [状态脚本](../../scripts/skill-status.ps1) 盘点，历史计划的完成标记需与当前文件或 Git 证据核对。

## 步骤与验证
- [x] 确认根目录、既有计划及工作区初始状态。结果：分支 `main`，HEAD `5efa134`；已跟踪改动仅 [choice-oracle 计划](TASK_PLAN_choice-oracle.md)，另有未跟踪计划、需求文档和临时目录。
- [x] 核对远端分支、最近提交和 worktree 状态。结果：`git ls-remote origin refs/heads/main` 与 HEAD、origin/main 均为 `5efa134aec69c277a493d0b335ae663268270142`；最近业务提交为 `9d50817`（2026-10-30 新增 choice-oracle），随后 `5efa134` 合并远端同步提交。另有 `fix/subtree-rejoin-sync` worktree 和一个路径已失效、标为 prunable 的旧同步 worktree，均保留。
- [x] 核对技能登记、任务计划和验证入口。结果：离线状态检查通过，7 个登记条目覆盖 13 份 SKILL.md；6 个 vendored 条目的 HEAD tree 与 lastSyncTree 一致，1 个自研 choice-oracle。待办与异常见下方；发现 [CLAUDE.md](../../CLAUDE.md) 的“没有测试套件”已不符合现有 [同步回归测试](../../scripts/test_sync_upstream_skills.py)。
- [x] 完成适当的只读验证并汇总状态。结果：`python -B -X utf8 -m unittest scripts.test_sync_upstream_skills` 1 项通过（50.211 秒）；所有根 scripts 下 PowerShell 脚本 Parser 校验通过；`git diff --check`、暂存区差异检查、注册表/目录一致性与本计划 17 个内部链接检查通过。最终状态与初始清单一致，本轮仅更新本计划。

## 当前进度
状态检查已完成。以下清单为用户后续授权实施前的检查快照：当时本地与实时远端一致，暂存区为空，技能代码和脚本没有未提交改动；1 个已跟踪计划修改、19 个未跟踪文件。后续 qu-ai-wei 修改和旧 worktree 处置见下节，不能再把此快照作为当前未提交清单。

## 同日后续处理（2026-11-02）
- 用户授权后，[qu-ai-wei 平均片段长度](TASK_PLAN_qu-ai-wei-average-segment-length.md) 已实现、验证并同步现有 Codex/Claude 安装源；改动留在工作区，未提交/推送。
- [两个旧 worktree](TASK_PLAN_worktree-cleanup.md) 已退出活动登记：失效临时树登记已 prune，云盘旧树保留为可恢复归档，两个旧分支保留。最终工作树列表仅剩主目录 main。
- 原 md2word 标题样式、choice-oracle/legal-skill-alignment 部署待办不在本次后续实施范围。

## 已核对的待办与异常
- [choice-oracle](../../skills/choice-oracle/SKILL.md) 已随 `9d50817` 提交且在远端 main 中；本机 Codex、Claude 的对应 skill 入口均不存在，符合 [该任务收尾记录](TASK_PLAN_choice-oracle.md) 的可选部署待办。
- [legal-skill-alignment 已按要求删除](TASK_PLAN_remove-legal-skill-alignment.md)；删除前本机 Codex、Claude 的同名入口均不存在，与 [引入计划的复核](TASK_PLAN_引入legal-skill-alignment.md) 一致。
- [md2word 标题样式计划](../../TASK_PLAN_md2word-heading-styles.md) 仍处于 S1 未开始；[当前转换代码](../../skills/md2word/scripts/md2word.py) 的标题分支仍创建普通段落后直接格式化，未发现 Heading 样式设置和编号实现。[10 月 28 日更新检查](TASK_PLAN_check-skill-updates.md) 将“原生标题样式”列为已有定制的表述不准确。
- [qu-ai-wei 平均断句长度](../skills/qu-ai-wei-average-segment-length.md) 只有需求文档，尚未写入 [SKILL.md](../../skills/qu-ai-wei/SKILL.md)；[需求计划](TASK_PLAN_qu-ai-wei-average-segment-length.md) 已完成的是起草阶段。
- [旧上游检查记录](TASK_PLAN_check-skill-updates.md) 的 gzh-design 待同步结论已被当前 main 的 `3294abf` 同步提交取代；本轮未重新逐个查询全部上游是否又有更新。
- 一个旧同步 worktree 已被 Git 标为 `prunable`（路径失效）；`fix/subtree-rejoin-sync` worktree 仍登记，但运行其 `git status` 报 `.git` 读取失败。该候选与已发布 `a5032da` 的两个修复文件 diff 为 0；未清理或修复 worktree。
- GitHub Actions 只读 API 查询：最近一次运行 `40305750501`，2026-10-26 18:13:46 北京时间启动并成功；之前定时运行 `40268841719` 失败。当前 [workflow](../../.github/workflows/sync-upstream-skills.yml) 定时为每周一 08:00 北京时间。

## 下一步动作
本次状态检查无剩余步骤。可后续单独处理上列部署待办、md2word 实现、qu-ai-wei 需求落地及旧 worktree/记录整理；本轮未扩大为修复、部署或清理任务。

## 本轮检查 2026-11-04

### 目标、范围与约束
- 目标：全面核对当前仓库 Git 状态、分支及远端跟踪、工作树、注册表及技能目录、子树同步一致性、单元测试与历史计划现场。
- 约束：只读检查，仅更新本计划文件；不改动任何业务代码、不修改已提交历史、不触碰临时文件。

### 步骤与验证
- [x] 核对 Git 分支、HEAD、远端与工作树。结果：当前分支 `main`，HEAD 为 `eebf01a`（已提交迁移三个专利/商标技能）；通过 `git ls-remote origin refs/heads/main` 确认与远端完全同步（差异 0/0）；仅存在单个主工作树。
- [x] 核对工作区与未跟踪文件。结果：无已暂存或未暂存的代码改动；未跟踪项均为任务计划文件（11 个）及 1 个测试用素材目录（`临时目录/`）。
- [x] 核对 [registry.json](../../registry.json) 与 [skills/](../../skills) 结构。结果：登记 9 个技能（5 个 vendored，4 个 own），全部在目录中对应存在：
  - 5 个引入技能：`cn-patent-agent-skills`（位于 `vendor/`）、`gzh-design`、`md2word`、`patent-download`、`qu-ai-wei`。
  - 4 个自研技能：`choice-oracle`、`cn-patent-fast-track-screener`、`cn-office-action-prior-art-collector`、`cn-trademark-goods-services-recommender`。
- [x] 核对 subtree tree 哈希一致性。结果：
  - 4 个 vendored 技能当前 HEAD tree 与 `lastSyncTree` 完全吻合。
  - `qu-ai-wei` 当前 HEAD tree 为 `ed3b3a49`，与 `lastSyncTree`（`2d0e48d6`）存在差异，系已记录的本地定制化功能提交（`f48cede` 增加平均断句长度与统计工具），符合 [本地记账规则](../skills/qu-ai-wei.md)。
- [x] 执行离线自动化测试与验证。结果全部通过（共 74 项测试）：
  - 上游同步测试：`python3 -B -X utf8 -m unittest scripts.test_sync_upstream_skills`（1 项通过）。
  - 快速预审技能：`python3 -B -m unittest skills/cn-patent-fast-track-screener/tests/test_screener.py`（25 项通过）。
  - 对比文件收集技能：`python3 -B skills/cn-office-action-prior-art-collector/scripts/selftest.py`（23 项通过）。
  - 商标商品推荐技能：`python3 -B -m unittest skills/cn-trademark-goods-services-recommender/tests/test_recommender.py`（25 项通过）。

### 当前状态与结论
项目状态整体健康，代码库与远端完全同步，所有已提交自研与引入技能测试均正常通过，无待提交代码改动。工作区仅存历史任务记录文件。

## 简单状态检查 2026-11-06

- 目标与范围：查看当前 Git 状态，依据新增文件历史确认最新加入的三个 skill；不开展全面测试。
- 重要约束：仅更新本计划，保留其他文件；“最新加入”按 Git 新增提交判断，不以文件修改时间判断。
- [x] 读取既有计划与工作区状态。结果：当前为 `main`，HEAD `eebf01a`；已跟踪文件无改动，存在 11 个未跟踪计划和 `临时目录/`。
- [x] 核对新增提交、[注册表](../../registry.json)和三个技能说明，确认名称、用途与加入时间。结果：三个技能均在 `eebf01a` 中于 2026-11-04 11:09:37（北京时间）加入，注册为 `own`：
  - [cn-patent-fast-track-screener](../../skills/cn-patent-fast-track-screener/SKILL.md)：专利预审、优先审查及 IPC 分类范围初筛。
  - [cn-office-action-prior-art-collector](../../skills/cn-office-action-prior-art-collector/SKILL.md)：审查意见通知书解析、专利号规范化、对比文件收集。
  - [cn-trademark-goods-services-recommender](../../skills/cn-trademark-goods-services-recommender/SKILL.md)：商标类别、类似群与商品服务项目推荐，校验及导出申报表。
- [x] 只读核对远端 main，检查计划链接，记录验证结果并简短汇报。结果：`git ls-remote origin refs/heads/main` 与本地 HEAD 均为 `eebf01aed366e7e98b881ffd0b06da91cda709fd`；暂存区和已跟踪工作区差异均为空。三个技能文件与注册表存在，新增记录的内部文件链接有效。
- 当前进度：检查完成；仅更新本计划，未运行功能测试。
- 下一步动作：无待执行步骤，保留本记录供接力。

