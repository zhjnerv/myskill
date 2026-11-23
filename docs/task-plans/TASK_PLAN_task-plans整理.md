# TASK_PLAN：整理本地 TASK_PLAN 文件

## 目标与范围

仓库根目录堆了 20 份 `TASK_PLAN_*.md`，合计 140K（2026-11-23 一次性「归档历史任务计划」时全部落在根目录）。本次整理只做文件组织与状态校正：

- 删掉 1 份内容重复且状态过时的副本。
- 把已完成的任务计划移入 `docs/task-plans/`，根目录只留仍有未完成动作的计划。
- 修正所有移动后的相对链接，确保没有断链。
- 校正几处已经与现实不符的状态描述（例如仍在说 secret 未配置）。

不改任何 skill 内容、`registry.json`、脚本和 workflow。

## 重要约束

- `docs/task-plans/` 是仓库既有约定的归档位置（AGENTS：「待用户确认执行结果后……归档计划文件」）。
- 归档目录内的计划需自身可读，链接按所在目录重算（多两级 `../`）。
- 计划里引用 `registry.json`、`skills/`、`scripts/` 的链接必须仍能点到实际文件。
- 只做本次列明的文件移动与文字修正，不重写计划的历史记录内容。

## 现状核查（2026-11-24）

| 文件 | 未完成项 | 判断 |
| --- | --- | --- |
| `TASK_PLAN.md` | 0 | 记账规则，已完成，规则正文已落在 [docs/skills/README.md](../skills/README.md) |
| `TASK_PLAN_check-skill-updates.md` | 5（陈旧） | 5 项在文末「跟进轮结果（2026-10-16）」已全部完成，只是中途清单没回填 |
| `TASK_PLAN_choice-oracle.md` | 0 | 已完成 |
| `TASK_PLAN_codex-hook-timeout.md` | 0 | 已完成 |
| `TASK_PLAN_fix_subtree_sync.md` | 0 | 已完成 |
| `TASK_PLAN_git-pull.md` | 0 | 已完成 |
| `TASK_PLAN_md2word-heading-styles.md` | 9 | **真实未开工**（S1–S5 未开始），保留根目录 |
| `TASK_PLAN_qu-ai-wei-average-segment-length.md` | 0 | 已完成 |
| `TASK_PLAN_reconnect_cn_patent_agent_skills.md` | 0 | 已完成 |
| `TASK_PLAN_remove-legal-skill-alignment.md` | 0 | 已完成 |
| `TASK_PLAN_sync-main-legal-removal.md` | 0 | 已完成 |
| `TASK_PLAN_worktree-cleanup.md` | 0 | 已完成 |
| `TASK_PLAN_双向同步启用.md` | 1 | 余下「制造真实差异验证开 PR」待用户授权，保留根目录 |
| `TASK_PLAN_引入legal-skill-alignment.md` | 0 | 已完成 |
| `TASK_PLAN_拆分三个skill.md` | 0 | 已完成 |
| `TASK_PLAN_查看项目状态.md` | 0 | 已完成（多轮快照） |
| `TASK_PLAN_核对知产技能包引入.md` | 3 | **重复文件**：标题与正文同 `TASK_PLAN_知产技能触发词与双向同步.md` 一致，仅状态未回填，删除 |
| `TASK_PLAN_清理subtree临时工作区.md` | 0 | 已完成 |
| `TASK_PLAN_知产技能触发词与双向同步.md` | 0 | 已完成 |
| `TASK_PLAN_配置GitHub_Actions_token.md` | 0 | 已完成，但正文仍称 secret 未配置，需校正 |

## 步骤与验证

- [x] 1. 删除重复计划 `TASK_PLAN_核对知产技能包引入.md`。结果：`git rm` 保留历史；该文件标题与正文实为 `TASK_PLAN_知产技能触发词与双向同步.md` 的未回填副本。
- [x] 2. 新建 `docs/task-plans/`，把 17 份已完成计划移入。结果：根目录仅剩 `TASK_PLAN_md2word-heading-styles.md`、`TASK_PLAN_双向同步启用.md` 和本计划。
- [x] 3. 按新位置重写移动文件的相对链接。结果：脚本改写 86 条，同目录计划和根目录计划各自保持正确相对路径。
- [x] 4. 修正互链。结果：`双向同步启用` 原有的 `../.github/` 前缀本来就错（它在根目录），已去掉；归档计划指向根目录计划的链接补 `../../`。
- [x] 5. 更新 `docs/skills/` 下的计划引用。结果：`qu-ai-wei-average-segment-length.md` 指向新归档位置；`md2word.md` 链接本来失效（上游已无 `TASKS.md`/`DECISIONS.md`），改为说明性文字。
- [x] 6. 新增 `docs/task-plans/README.md` 索引。结果：17 条计划含时间与结果摘要，并标出根目录仍活跃的两份。
- [x] 7. 校正 3 处过时状态。结果：`配置GitHub_Actions_token` 与 `知产技能触发词与双向同步` 改为已配置 `IP_PRACTICE` 并实跑成功；`check-skill-updates` 的 5 项陈旧清单回填为已完成并注明见后续结果节。归档计划已无 `[ ]` 未完成项。
- [x] 8. 全量复验。结果：22 个 Markdown 文件的相对链接全部可达（断链 0）、`git diff --check` 干净、`registry.json` 与 workflow 解析通过、9 项脚本测试通过。

## 当前进度

8 个步骤全部完成并推送（`4ccd429`）。根目录从 20 份计划降到 3 份，另有 `docs/task-plans/` 归档 17 份加索引。

## 下一步动作

无。本计划随本次整理一并归档到 `docs/task-plans/`。

## 已知风险

- 移动文件会让 126 个相对链接全部失效，必须逐条重算并验证，不能只做 `git mv`。
- `TASK_PLAN_知产技能触发词与双向同步.md` 被源仓库 PR 记录引用，归档后路径变化需同步查引用。
