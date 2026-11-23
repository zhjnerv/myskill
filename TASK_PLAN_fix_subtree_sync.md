# TASK_PLAN：修复 cn-patent-agent-skills 上游同步

## 目标与范围
修复 GitHub Actions 的 `subtree pull` 失败：`vendor/cn-patent-agent-skills` 在改名迁移后没有该新前缀的 subtree squash 记录，导致 [scripts/sync_upstream_skills.py](scripts/sync_upstream_skills.py) 无法继续拉取 [registry.json](registry.json) 中的 `cn-patent-agent-skills`。让同步脚本能在遇到“前缀从未添加”时保内容补记 subtree 关系，并覆盖后续上游更新。

## 重要约束
- 不删除或重建 `vendor/cn-patent-agent-skills`，不覆盖本地内容。
- 不使用 force push、历史重写或破坏性清理；主目录现有未跟踪任务文件保持不动。
- 代码修改在独立 worktree 分支完成；未获用户确认前不推送 GitHub。
- 修复必须兼容既有 `--squash` 约定，且不能影响正常已初始化 vendored skill 的同步。

## 步骤与验证
- [x] 刷新远端基准并创建独立 worktree。完成标准：分支基于已核 `origin/main`，工作区干净。结果：`fix/subtree-rejoin-sync` 与 `origin/main` 同为 `4832c88ec2fce7a3ed0dd4dcd43e2c6e17fe321d`，工作区干净。
- [x] 在临时 Git 仓库复现“普通目录存在但未 `subtree add --squash`”的失败，并验证 `git subtree split --rejoin` 能补记元数据且目录内容不变。结果：复现 `can't squash-merge: 'vendor/pkg' was never added.`；rejoin 前后仓库 tree 同为 `8f92cde...`，随后上游更新可正常 squash 合入。
- [x] 修改 [scripts/sync_upstream_skills.py](scripts/sync_upstream_skills.py)：识别 `can't squash-merge ... was never added` 后执行 rejoin，再重试原拉取；失败时保留首个错误并中止。结果：仅新增精确错误识别、rejoin 调用和一次原拉取重试。
- [x] 增加针对该回归场景的自动化测试，至少覆盖首次补记和第二次上游更新。结果：[scripts/test_sync_upstream_skills.py](scripts/test_sync_upstream_skills.py) 使用两个本地临时 Git 仓库离线复现普通目录迁移状态，验证首次 rejoin、元数据存在和第二次上游更新。
- [x] 运行回归测试、Python 编译/静态检查和 `git diff --check`。完成标准：相关测试通过，工作分支无格式错误。结果：`python -m unittest scripts.test_sync_upstream_skills` 1 项通过；`py_compile` 与 `git diff --check` 通过。首轮测试曾因 Windows 本地反斜杠路径夹具触发镜像目录推导差异，改用 `file:///` URI 后通过；生产 workflow 使用 HTTPS，不受该夹具问题影响。
- [x] 审阅完整差异并记录候选状态。结果：候选提交 `b5a79c0c8d93adcdced2a3c8dfd4d190e81d76b1`，仅修改 [scripts/sync_upstream_skills.py](scripts/sync_upstream_skills.py) 并新增 [scripts/test_sync_upstream_skills.py](scripts/test_sync_upstream_skills.py)，共 144 行；staged 隐私预检 `PRIVACY_OK`，`origin/main..HEAD` 的 `git diff --check` 通过，worktree 干净且领先 `origin/main` 1 个提交。
- [x] 经用户确认推送后，在独立发布检出中窄采用候选提交，并发布到 `origin/main`。完成标准：安全推送通过，远端 `main` 包含修复。结果：在 `..\myskill-publish-subtree-sync` 中 cherry-pick 候选提交，发布提交为 `a5032dad19d74ac3e2ab803ae98c770268056e2e`；两个目标文件与候选提交逐字节一致，测试与检查通过；`safe-push` 输出 `IDENTITY_GATE_OK`、`PRIVACY_OK`、`SAFE_PUSH_OK`，远端 `main` 从 `4832c88` 前进到 `a5032da`。
- [x] 手动触发并观察 `Sync upstream skills` GitHub Actions。结果：定时运行 `40268841719` 在修复提交进入远端前仍因 `vendor/cn-patent-agent-skills was never added` 失败；修复提交 `a5032da` 进入 `main` 后，手动运行 `40305750501` 成功，日志出现 `[rejoin]`、`[updated] cn-patent-agent-skills`，并成功推送提交 `05fbb4b`。

## 当前进度
已完成只读定位、worktree 创建、最小复现、脚本修复、离线回归验证、隐私预检、本地候选提交、窄采用发布和安全推送。修复提交 `a5032dad19d74ac3e2ab803ae98c770268056e2e` 已进入远端；随后手动触发的 Actions 运行 `40305750501` 全部成功，并将同步提交 `05fbb4b46bc39f260e150c4bd9364c5c51b38944` 推送到 `main`。

## 下一步动作
无。后续按周一 00:00 UTC 的定时任务继续观察即可。
