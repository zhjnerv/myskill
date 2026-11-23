# TASK_PLAN：启用 IP 技能双向同步

## 目标与范围

让 `myskill` 与 `ip-practice-workbench-skills` 之间的两个方向都能自动跑通：

- 上游 → myskill：由 [sync-upstream-skills.yml](../.github/workflows/sync-upstream-skills.yml) 每周一 00:00 UTC 拉取
- myskill → 上游：由 [sync-ip-practice-skills-back.yml](../.github/workflows/sync-ip-practice-skills-back.yml) 在三个技能目录被推送后开 PR

本次只解决第二个方向缺失凭据的问题，并修掉一个已知的误覆盖风险。不改技能内容。

## 现状核查（2026-11-23）

| 项 | 结论 |
| --- | --- |
| 上游 → myskill | 正常。最近 4 次 schedule 全部 success |
| myskill → 上游 | 从未成功。仅 1 次运行 `45061007823`，报 `Missing repository secret IP_PRACTICE_WORKBENCH_TOKEN` |
| 仓库级 Actions secret | `total_count=0`，确认为空 |
| 三份技能目录 vs 上游 main | 逐字节一致（`diff -rq` 无输出） |
| `registry.json` 的 `lastSyncTree` | 三个技能均与当前目录 tree 一致 |
| 分支保护 / rulesets | 两个仓库的 `main` 均无保护规则 |

## 重要约束

- Token 必须是最小权限 fine-grained token，只授权 `zhjnerv/ip-practice-workbench-skills`。
- 不复用本机 `gh` 的 OAuth token：其 scope 为 `repo`，可写全部仓库，超出最小权限。
- 凭据只进仓库 secret，不落仓库文件、不写进 shell 历史、不出现在对话记录里。
- 创建 token 与写 secret 属于账号级操作，由用户本人完成。

## 步骤与验证

- [x] 核查双向同步现状、secret 状态、目录一致性、分支保护。结果：见上表。
- [x] 确认 secret。结果：仓库级 secret 实际名为 `IP_PRACTICE`（`updated_at=2026-11-23T15:30:22Z`），与代码期望的 `IP_PRACTICE_WORKBENCH_TOKEN` 不一致。
- [x] 按实际 secret 名统一代码与文档。结果：workflow 两处 `secrets.*`、错误提示、脚本报错、两份文档共 8 处引用改为 `IP_PRACTICE`，全仓库无残留。
- [x] 修 back-sync 缺少“上游是否领先”检查导致的误覆盖风险。结果：`sync_one()` 在提交前比对 `origin/{branch}:{subpath}` tree 与 `registry.json` 的 `lastSyncTree`，不等即抛错并提示先 `skill-sync.ps1`。
- [x] 给守卫补回归测试。结果：新增 `scripts/test_sync_ip_practice_skills_to_upstream.py`，3 个用例（上游前进、基线缺失、内容一致）全部通过；移除守卫后其中 2 个失败，确认测试有效。
- [x] 补 token 权限前置检查。结果：workflow 在 `gh auth setup-git` 之后读取 `repos/zhjnerv/ip-practice-workbench-skills` 的 `permissions.push`，读不到或不为 `true` 就中止；这样 token 选错仓库、只给只读或已过期时不会先在上游留下分支。
- [x] 手动运行 back-sync workflow 验证。结果：`45209965462`（提交 `c72f01b`）与 `45210477755`（`15ad029`）均 success，日志三个 `[current]`，上游未新增分支或 PR。
- [x] 补 token 权限范围检查。结果：workflow 读 `gh api -i repos/zhjnerv/myskill` 响应头区分 classic / fine-grained；`45211364887` 报 `IP_PRACTICE 是 fine-grained token，但也可访问 zhjnerv/myskill，授权仓库多于最小权限`。
- [ ] 制造一次真实差异验证开 PR 路径。完成标准：上游出现 `myskill-sync/<name>` 分支与对应 PR，内容只含该技能目录。

## 当前进度

代码侧改动已推送（`c72f01b`、`15ad029`、`5d5fef3`），workflow 手动运行三次全部 success，`[current]` 路径已验证。

## 下一步动作

真实差异路径（`myskill-sync/<name>` 分支 + PR）尚未验证，需要在上游建分支，待用户授权后执行。

## 已知风险

`sync_ip_practice_skills_to_upstream.py` 的 `sync_one()` 直接克隆上游默认分支、用 myskill 目录整体覆盖、无差异即 `[current]`。
它**不检查 myskill 是否落后于上游**。若上游已在别处更新而 myskill 尚未拉回，该脚本会提交一份把上游新内容删掉的 PR。
已在 `sync_one()` 中补上前置比对；当前三份目录与上游一致，`lastSyncTree` 均等于上游 tree。

## 凭据待确认

已确认 `IP_PRACTICE` 是 fine-grained token（响应头无 `X-OAuth-Scopes`），但它能读 `zhjnerv/myskill`，说明授权仓库不止 `ip-practice-workbench-skills`。
这不算凭据泄露风险，但违反最小权限：一旦 token 泄漏，攻击面比只授权一个仓库更大。建议在 GitHub 上把该 token 的 Repository access 收紧到仅 `ip-practice-workbench-skills`。
