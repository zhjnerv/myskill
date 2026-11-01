# TASK_PLAN：处理旧 worktree 遗留问题

## 目标与范围
2026-11-02 用户授权处理状态检查发现的两个旧 worktree：临时同步树 `myskill-sync-claude-patent-creator-cn` 路径失效；`myskill-fix-subtree-sync` 的 `.git` 因 Google Drive 云操作失败无法读取。以 Git 登记、分支 tip、交付提交 `a5032da`，以及 [同步实现](scripts/sync_upstream_skills.py) 和 [回归测试](scripts/test_sync_upstream_skills.py) 核对交付与保留材料。

## 约束
- 主工作区保持 main；不删除未知未提交、未跟踪或 ignored 内容，不使用强制清理。
- 用户已授权解决这两个具名遗留问题；不扩大为全机/全部分支清理，不删除远端分支。后续 commit and push 授权仅发布本次技能改动及处理记录。
- 删除或移动前解析绝对路径并核对目标；先备份关联 Git 元数据，确认只涉及具名对象。
- 云文件无法读取时优先修复可重建的 Git 连接；无法验证目录内容时保留实体目录和分支，明确原因。

## 步骤与验证
- [x] 核对登记、路径、锁、分支 tip、交付提交及云文件状态。结果：失效临时目录确实不存在、无 locked；修复树 tip 为 `b5a79c0c8d93adcdced2a3c8dfd4d190e81d76b1`，交付 `a5032da` 是 main 祖先且两个修复文件与候选一致。绕过 `.git` 查询后发现 9 个 tracked 文件因云读取失败显示修改，另有 2 个未跟踪 pyc；无法确认目录干净。
- [x] 处理失效临时树登记。结果：dry-run 仅列具名过期登记，随后 `git worktree prune --verbose` 成功；临时树分支及原 tip 保留。
- [x] 恢复或安全处置云盘旧树。结果：按保留方案完成归档，原 `.git` 以 `.snapshot` 名称留在原目录，管理目录整体移入本机备份，目录新增归档说明；原文件和分支均保留。该目录已不在活动 worktree 列表。云文件读取故障未修复，未来核验内容须先恢复云盘访问。
- [x] 复核 worktree 列表、主工作区改动和备份可恢复性，更新本计划。结果：最终 `git worktree list --porcelain` 仅有主工作区 main，prune dry-run 无输出；两个旧分支 tip 均未变，云占位 `.snapshot` 仍存在（隐藏文件需 `-Force` 查看），原 `.git` 已不存在；备份内保留原管理目录/索引/日志并写入恢复说明。本轮 qu-ai-wei 临时工作树及临时分支也已移除。

## 当前进度
已完成，云盘旧树状态为 RETAINED_WITH_REASON：原文件读取失败，保留目录、分支与可恢复 Git 元数据；失效临时树登记已清理。备份位于本机 LocalAppData 的 `myskill-backups/20261102-qu-ai-wei-worktrees`，初始管理目录逐文件 SHA-256 核验通过，恢复说明为该目录的 `RESTORE.md`。原实体目录内有 `WORKTREE_ARCHIVED.md`。没有递归删除原目录，也没有删除旧分支。Google Drive 文件可读性仍是归档内容复核的前提，不属于本次已修复结果。

## 下一步
本次旧 worktree 登记问题无剩余步骤。如以后需要恢复或最终删除保留归档，先恢复云盘读取并核对其中的未提交/未跟踪内容，按备份说明恢复或另行处置。

## 发布记录
2026-11-02 用户授权提交并推送本次技能改动及处理记录。记录已随 `f48cedee341a8899be00416917b2391bb785cc6f` 发布至 origin/main，身份、隐私与安全推送门禁均通过；详见 [qu-ai-wei 提交与推送计划](TASK_PLAN_qu-ai-wei-average-segment-length.md)。归档内容和本地备份不进入仓库。
