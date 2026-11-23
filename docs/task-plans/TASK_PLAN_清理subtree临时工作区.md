# TASK_PLAN：清理 subtree 临时工作区

## 目标与范围
删除 2026-10-26 修复 `cn-patent-agent-skills` subtree 同步时留下的一次性资源：
`../myskill-fix-subtree-sync`、`../myskill-publish-subtree-sync`、失效的
`myskill-fix-subtree-sync` worktree 登记，以及本地分支
`fix/subtree-rejoin-sync`。不改主目录源码、registry、现有未提交任务材料或其他分支。

## 重要约束
- 保留 [TASK_PLAN_fix_subtree_sync.md](TASK_PLAN_fix_subtree_sync.md) 作为交付记录。
- 删除授权仅覆盖上述两个目录、对应失效 worktree 登记和精确本地分支。
- 不删除 `main`、`feat/md2word-vendor`、`codex/sync-claude-patent-creator-cn-20261009`
  或其他 worktree。
- 删除分支前复核 `b5a79c0` 的补丁已由 `a5032da` 等价发布，且 `a5032da`
  已进入当前 `origin/main`。
- 不使用无条件 `git branch -D`；本地 ref 使用 expected-tip 条件删除。
- 不执行 fetch、push、merge、commit 或历史重写。

## 步骤与验证
- [x] 复核两个目录无进程占用、无独有未提交材料，并核固定提交关系。
  完成标准：`b5a79c0` 与 `a5032da` 的目标文件差异为空，`a5032da` 为当前
  `origin/main` 祖先。结果：两个目录均无进程 cwd 占用，提交内容哈希全部匹配；
  忽略的 `__pycache__` 可重新生成，其余额外文件与主目录现有文件一致，
  `b5a79c0^{tree}` 与 `a5032da^{tree}` 相同，`a5032da` 已进入 `origin/main`，
  远端不存在同名分支。
- [x] 清理失效 worktree 登记并删除两个临时目录。
  完成标准：两个目录不存在，`git worktree list` 不再显示 `myskill-fix-subtree-sync`。
  结果：先修复临时 worktree 的迁移后路径，再以普通 `git worktree remove`
  删除；发布克隆使用非强制递归删除。两个目录均确认不存在，worktree 列表中
  `myskill-fix-subtree-sync` 已消失。
- [x] 以 expected tip 条件删除本地分支 `fix/subtree-rejoin-sync`。
  完成标准：`git show-ref --verify refs/heads/fix/subtree-rejoin-sync` 返回不存在。
  结果：已以 expected tip `b5a79c0c8d93adcdced2a3c8dfd4d190e81d76b1`
  执行条件删除；本地 ref 已不存在，远端同名分支查询结果为 0 条。
- [x] 复核主仓库现场和剩余分支。
  完成标准：主目录原本的 modified/untracked 内容仍存在，目标资源均已移除。
  结果：主目录仍在 `main`，HEAD 保持为
  `5efa134aec69c277a493d0b335ae663268270142`；原有 modified/untracked
  现场未受影响，两个临时目录、失效 worktree 登记和本地分支均已移除。

## 当前进度
全部完成。清理后的目录、worktree 登记、本地分支和主仓库现场均已复核。

## 下一步动作
无。
