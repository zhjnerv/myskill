# 任务计划归档

本目录收存已完成任务的 `TASK_PLAN_*.md`。它们是执行过程与交接记录，不是当前待办清单。

仍在进行或等待授权的计划留在仓库根目录：

- [TASK_PLAN_md2word-heading-styles.md](../../TASK_PLAN_md2word-heading-styles.md)：md2word 输出 Word 原生标题样式，S1–S5 尚未开工。
- [TASK_PLAN_双向同步启用.md](../../TASK_PLAN_双向同步启用.md)：IP 技能双向同步，仅余「制造真实差异验证开 PR」待授权。

## 归档清单

| 计划 | 时间 | 结果 |
| --- | --- | --- |
| [落地 skill 改动记账](TASK_PLAN.md) | 2026-10-04 | 规则落在 [docs/skills/README.md](../skills/README.md)，`skill-new.ps1` 生成自研三份账 |
| [盘点仓库内 Skill 更新](TASK_PLAN_check-skill-updates.md) | 2026-10-08～11-04 | 多轮只读复查，含 gzh-design 跟进同步；各上游无待同步更新 |
| [choice-oracle](TASK_PLAN_choice-oracle.md) | 2026-10-30 | 新建自研 skill 并改名，提交 `9d50817` |
| [排查 Codex Hook 超时](TASK_PLAN_codex-hook-timeout.md) | 2026-11-01 | 移出活动配置，保留 tty7 Hook 与备份 |
| [修复 cn-patent-agent-skills 上游同步](TASK_PLAN_fix_subtree_sync.md) | 2026-10-26 | 修复 `a5032da`，Actions `40305750501` 验证通过 |
| [拉取 origin/main](TASK_PLAN_git-pull.md) | 2026-11-23 | 快进 26 个提交并合并本地改动，恢复点 `backup/pre-pull-20261123` |
| [qu-ai-wei 平均断句长度](TASK_PLAN_qu-ai-wei-average-segment-length.md) | 2026-11-02 | 提交 `f48cede` 已推送 |
| [重连 cn-patent-agent-skills](TASK_PLAN_reconnect_cn_patent_agent_skills.md) | 2026-10-25 | 包名迁移与七个 Skill 入口重建，合并提交 `f529685` |
| [删除 legal-skill-alignment](TASK_PLAN_remove-legal-skill-alignment.md) | 2026-11-03 | 目录与 registry 条目删除，本地齐平 `c3e3fb7` |
| [本地 main 齐平远端](TASK_PLAN_sync-main-legal-removal.md) | 2026-11-04 | 未提交未推送，仅对齐远端 |
| [处理旧 worktree 遗留](TASK_PLAN_worktree-cleanup.md) | 2026-11-02 | 云盘旧树按 RETAINED_WITH_REASON 归档，备份在本机 LocalAppData |
| [引入 legal-skill-alignment](TASK_PLAN_引入legal-skill-alignment.md) | 2026-11-03 | 已引入，随后于 11-03 删除 |
| [知产工作台接回 myskill](TASK_PLAN_拆分三个skill.md) | 2026-11-06 | 整包 vendored 登记，main 与 origin/main 同为 `2bf5787` |
| [查看项目状态](TASK_PLAN_查看项目状态.md) | 2026-11-02～11-06 | 多轮只读状态快照，含待办清单 |
| [清理 subtree 临时工作区](TASK_PLAN_清理subtree临时工作区.md) | 2026-11-01 | worktree 登记、分支与临时目录清理完毕 |
| [知产技能触发词与双向同步](TASK_PLAN_知产技能触发词与双向同步.md) | 2026-11-22 | 两端描述一致，PR #1/#2 合入，自动回推后续在根目录计划收尾 |
| [配置 GitHub Actions token](TASK_PLAN_配置GitHub_Actions_token.md) | 2026-11-23 | 配置指南落 [docs/github-actions-token-setup.md](../github-actions-token-setup.md)，secret 名定为 `IP_PRACTICE` |

## 相关规则

- 计划的写法与交接要求见仓库根目录 `AGENTS.md`。
- 引入 skill 的本地改动账写在 [docs/skills/](../skills/README.md)，与任务计划分开。
