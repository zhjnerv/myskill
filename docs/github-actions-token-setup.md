# GitHub Actions 跨仓库 Token 配置

此凭据供 [知产实务技能反向同步工作流](../.github/workflows/sync-ip-practice-skills-back.yml) 使用：当三个技能在 `zhjnerv/myskill` 的 `main` 有变更时，工作流把技能目录推到源仓库专用分支并创建或更新 PR。它不会自动合并 PR。

## 1. 创建 Fine-Grained Token

在 GitHub 网页打开个人设置中的 **Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**，设置：

- Token name：`myskill-ip-practice-sync`
- Expiration：选择符合个人轮换策略的期限，并在到期前更新仓库 secret。
- Resource owner：`zhjnerv`
- Repository access：**Only select repositories**，只选 `ip-practice-workbench-skills`。
- Repository permissions：
  - **Contents: Read and write**，用于读取源仓库、推送自动同步分支。
  - **Pull requests: Read and write**，用于查询、创建和更新 PR。
  - 其他权限保持 **No access**。

创建后立即复制 token。GitHub 只显示新 token 一次；不要把 token 写进仓库文件、Issue、PR、终端命令行参数或聊天记录。

## 2. 配置 myskill Actions Secret

在 `zhjnerv/myskill` 仓库打开 **Settings → Secrets and variables → Actions → New repository secret**：

- Name：`IP_PRACTICE`
- Secret：粘贴刚创建的 token

也可在已登录 `gh` 的终端交互式设置；命令不带 token 参数，CLI 会从标准输入读取：

```bash
gh secret set IP_PRACTICE --repo zhjnerv/myskill
```

不要使用 `--body TOKEN`，避免 token 留在 shell 历史或进程参数中。Secret 保存后 GitHub 不会再次显示其值。

## 3. 验证

先确认 secret 名称已登记（此命令不显示 secret 值）：

```bash
gh secret list --repo zhjnerv/myskill
```

然后在仓库 **Actions → Sync IP practice skills back → Run workflow** 手动运行。首次验证可将三个技能名填入 `skills` 输入框，或留空同步全部技能。检查运行结果：

- 若对应技能与源仓库相同，日志显示 `[current]`，不创建 PR。
- 若有差异，日志显示 `[created PR]` 或 `[updated PR]`，并在 `ip-practice-workbench-skills` 创建/更新同步 PR。
- 工作流成功后，检查源仓库 PR 的 base、head、文件范围和三份 `SKILL.md` 内容；仍按正常 review 流程合并。

工作流会在缺少 secret 时明确失败。不要为规避失败而改用个人全权限 OAuth token，也不要把 token 值提交到任何仓库。

工作流在推送前有两道前置检查，失败都会在留下任何上游分支之前中止：

- 用 `gh api repos/zhjnerv/ip-practice-workbench-skills` 读 `permissions.push`，不为 `true` 就报错。这一步能发现 token 选错了仓库、权限只给了只读、或已过期。
- 脚本在提交前比对 `registry.json` 的 `lastSyncTree` 与上游 `origin/main` 的目录 tree。不等说明上游已经前进而 myskill 还没拉回，脚本会提示先运行 `scripts/skill-sync.ps1 -Name <技能名>`，不会用旧内容覆盖上游。

另有一道只提示不中止的检查：读源仓库 API 的响应头，带 `X-OAuth-Scopes` 说明是 classic token，会在日志里报 warning。fine-grained token 不返回这个头。

判断不了的是 fine-grained token 到底授权了哪些仓库——API 不提供这个信息，而 `zhjnerv/myskill` 是 public 仓库，任何 token 甚至未认证都能读它，所以「能读到 myskill」不能当作授权范围宽的证据。要核实授权范围，只能看 GitHub 上该 token 的 **Repository access** 设置。

## 后续维护

- 定期检查 token 到期时间；轮换时创建新 token、更新同名 Actions secret，成功验证后再撤销旧 token。
- 如需撤销，先删除 `zhjnerv/myskill` 的 `IP_PRACTICE` secret，再在 GitHub token 设置中撤销 token。
- 即使 token 失效，已有源仓库与 myskill 内容不受影响；只有未来的自动回推会失败。
