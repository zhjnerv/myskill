# TASK_PLAN：盘点仓库内 Skill 更新

## 目标与范围

盘点本仓库所有含 `SKILL.md` 的技能，并把自有整包 `claude-patent-creator-cn` 从 `zhjnerv/claude-patent-creator-cn` 拉取到本地。范围含 [registry.json](../../registry.json) 中该整包及其 `vendor/claude-patent-creator-cn/` 目录。

## 重要约束

- 只同步 `claude-patent-creator-cn`，不动其他 Skill。
- 工作区已有未提交改动，必须保留；使用临时 worktree 执行项目 subtree 同步流程。
- 保留整包内本地定制；出现无法安全解决的冲突时停在可恢复状态并记录。

## 步骤与验证

- [x] 读取仓库状态、注册表与本地版本信息。结果：registry 登记 6 项、共覆盖 13 份 `SKILL.md`；工作区已有未提交文档/脚本改动。
- [x] 查询远程版本和内容树。结果：项目自带 [skill-status.ps1](../../scripts/skill-status.ps1) 因本机缺少 `gh` 回退到耗时的 subtree split，在 md2word 处停止后改用 GitHub 只读 API；远端目录树和关键 `SKILL.md` / `CHANGELOG.md` 已复核。
- [x] 汇总更新盘点并检查内部链接。结果：自有专利整包与 `gzh-design` 存在上游更新；其余项目状态见下表。计划中的本地文件链接已检查存在。
- [x] 在隔离 worktree 执行 `skill-sync.ps1 -Name claude-patent-creator-cn`。结果：dry-run 指向 fork 提交 `3723846de2`；同步产生 subtree merge 与 registry 基线提交，整包 tree 为 `8264ac29caa7b7bb723f1f472d72a3f5de90e8ea`。候选范围仅含该整包和 registry。
- [x] 将已核候选窄采用到当前 main 并验证。结果：以具名主目录门禁提交 `c1562ff66a9c3cd8683b4cf7c3d43be6a3b5c714`，仅含 registry 与 `vendor/claude-patent-creator-cn/` 的 89 个路径；提交包 tree 与候选一致，原有无关 dirty 文件保留。未 push；整包测试未运行。

## 检查结果（2026-10-08）

| registry 项 | 判断 | 证据 |
|---|---|---|
| `claude-patent-creator-cn` | **有更新，建议审阅后同步。** 上游与 fork 当前均为提交 `3723846de2d002cb5180d94c028bf1bbbf1ec262`（2026-10-05），本地上次同步为 2026-09-28。7 个子 Skill 中 6 个 `SKILL.md` 与上游存在差异：起草、权利要求分析、附图、形式审查、综合审查、工作流；说明书审查 Skill 相同。整包还有参考资料、脚本、配置与测试资产的上游差异。 | [registry 基线](../../registry.json)；[上游 2026-10-05 提交](https://github.com/zhjnerv/claude-patent-creator-cn/commit/3723846de2d002cb5180d94c028bf1bbbf1ec262) |
| `gzh-design` | **有更新。** 原作者上游最新提交 `339840b1343c86b0159d97a06a0e9eba7c09f9ba`（2026-10-03）；`zhjnerv` fork 落后 4 个提交。上游相对本地修改了 `SKILL.md`、`assets/preview-template.html`、`scripts/extract_docx.py`。本地另有二维码指引与二维码资源/脚本，合并时应保留这些本地定制。 | [registry 基线](../../registry.json)；[原作者上游提交](https://github.com/isjiamu/gzh-design-skill/commit/339840b1343c86b0159d97a06a0e9eba7c09f9ba)；[本地 SKILL](../../skills/gzh-design/SKILL.md) |
| `md2word` | **未发现新上游版本。** 本地与上游版本均为 `1.3.8`，上游 CHANGELOG 最新版本日期为 2026-09-23。文件差异来自本地触发词 `2word`、页眉页脚模板功能等定制，未发现上游新增的技能目录文件；不要整目录覆盖。 | [本地 SKILL](../../skills/md2word/SKILL.md)；[上游更新日志](https://github.com/cat-xierluo/legal-skills/blob/main/skills/md2word/CHANGELOG.md) |
| `patent-download` | **当前。** registry 对应子目录的本地、fork、原作者上游树完全一致；本地版本 `2.7.1` 与上游一致。 | [本地 SKILL](../../skills/patent-download/SKILL.md)；[上游 SKILL](https://github.com/cat-xierluo/legal-skills/blob/main/skills/patent-download/SKILL.md) |
| `qu-ai-wei` | **当前。** 本地、fork、原作者上游的技能树完全一致。 | [本地 SKILL](../../skills/qu-ai-wei/SKILL.md)；[上游仓库](https://github.com/LifelongLazyLearner/qu-ai-wei) |
| `legal-skill-alignment` | **当时为当前版本。** 本地与 fork、原作者上游对应子目录树完全一致；本地和上游版本均为 `1.0.7`。该 skill 已于 2026-11-03 删除。 | 本地 SKILL；[上游 SKILL](https://github.com/cat-xierluo/legal-skills/blob/main/skills/legal-skill-alignment/SKILL.md) |

### 检查限制

仓库自带的远程脚本依赖 `gh`；环境中未找到该命令，导致其完整 subtree 回退耗时停滞，本轮已中止该回退。之后通过 GitHub 公共只读 API 和 raw 内容核对远程目录树、版本及关键文件，没有修改 Skill 或 registry。上游代码差异尚未逐项做安全/兼容审查，因此“有更新”表示存在上游内容变化，不等于可无冲突直接覆盖。

## 当前进度

隔离 worktree 的 subtree 同步已完成，冲突为 0。候选为 `a3d51fa0d5b66b1df6e174c5e9c7d0217f550a00`，上游 split 为 `3723846de2d002cb5180d94c028bf1bbbf1ec262`，包 tree 为 `8264ac29caa7b7bb723f1f472d72a3f5de90e8ea`。候选 registry 提交重排了 entries；采用时只更新该包的同步字段，保留原数组顺序。具名集成者：zhjnerv；采用前预期 main HEAD：`7a53c9f917f7aaea7a04e222d6915779ca4f00d7`。包内 ignored runtime 不纳入同步。最终提交为 `c1562ff66a9c3cd8683b4cf7c3d43be6a3b5c714`，提交路径共 89 项，仅含该包与 registry；HEAD 中包 tree 与候选一致。原先无关的 `CLAUDE.md`、`README.md`、`docs/fork-workflow.md`、`docs/usage.md`、`scripts/skill-new.ps1`、`TASK_PLAN.md`、其他任务计划与 `docs/skills/` 均保持未提交状态。

## 收口与验证

已用 Python 3.12 + `PYTHONUTF8=1`，并将真实 Git 路径缩写为 Windows 8.3 路径以适配门禁转发，完成只检查和精确暂存。实际 Git index 核验结果：暂存共 89 条，唯一根级文件为 `registry.json`，其余均位于 `vendor/claude-patent-creator-cn/`；index 中包 tree 与候选同为 `8264ac29caa7b7bb723f1f472d72a3f5de90e8ea`，`git diff --cached --check` 通过。此前未成功的调用没有改动 index。

提交前核验：分支 `main`，HEAD 为 `7a53c9f917f7aaea7a04e222d6915779ca4f00d7`；提交身份审计通过，身份为 `zhjnerv <zhjwork@gmail.com>`，来源为用户全局 Git 配置且无 repo/worktree 覆盖；暂存路径 89 项全部落在允许范围，包 tree 与候选一致，cached diff check 通过。

首次直接把中文提交说明作为命令参数传给 Windows 门禁时，Git 收到乱码参数并报 pathspec 错误；虽门禁返回 0，但核对 HEAD 未变后没有误判为成功，也没有绕开门禁。改用临时 UTF-8 message file、门禁参数保持 ASCII，经 check-only 与同一具名门禁完成提交。提交后验证：HEAD 为 `c1562ff66a9c3cd8683b4cf7c3d43be6a3b5c714`；说明和正文编码正确；提交恰含 89 个允许路径；包 tree `8264ac29caa7b7bb723f1f472d72a3f5de90e8ea` 与候选完全一致；工作区剩余 dirty 仅为本任务之外的既有文件。未运行专利整包测试，未 push。



## 复查（2026-10-16）

用 `git ls-remote` + GitHub compare API 对 4 个上游仓库做了只读复查（未修改任何 skill / registry）。

| 上游仓库 | 判断 | 证据 |
|---|---|---|
| `zhjnerv/claude-patent-creator-cn` | 无新更新。main 仍为 `3723846de2`（2026-10-05），与 10-08 基线一致。 | ls-remote |
| `isjiamu/gzh-design-skill` | **有新更新。** main 到 `fa4b78fb94`（2026-10-09），新增 2 个提交：修复渐变背景问题 #21（默认纯色文字背景+渐变风险提示）。变更 8 个文件：SKILL.md、5 个主题参考、2 个校验脚本。本地 lastSync 仍为 2026-09-26。 | [compare 339840b...main](https://github.com/isjiamu/gzh-design-skill/compare/339840b1343c86b0159d97a06a0e9eba7c09f9ba...main) |
| `cat-xierluo/legal-skills` | 上游有 31 个新提交（2026-10-15/16，涉及 skill-manager、github-star-manager、multi-agent-orca、video-screenshot 等），但**均不涉及**本仓库引入的 `skills/md2word`、`skills/patent-download`、`skills/legal-skill-alignment` 三个子路径。对本仓库无实际影响。 | [compare 1db5492...main](https://github.com/cat-xierluo/legal-skills/compare/1db549245b...main) |
| `LifelongLazyLearner/qu-ai-wei` | 无新更新。main 仍为 `1d32e803f0`（2026-09-10）。 | API commits/main |

## 当前进度（复查轮）

已完成的只读复查如上表。唯一建议跟进项：`gzh-design` 可在用户确认后执行 `skill-sync.ps1 -Name gzh-design`；合并时需保留本地二维码指引与二维码资源/脚本定制。

## 下一步动作（复查轮）

等用户决定是否同步 `gzh-design`。

## 跟进轮（2026-10-16）：同步 gzh-design

用户确认跟进。按仓库 fork-workflow 执行 `skill-sync.ps1 -Name gzh-design -FromUpstream`。

以下清单当初未回填，实际结果见本节之后的「跟进轮结果（2026-10-16）」，五项均已完成：

- [x] 检查环境（gh 可用性、工作区状态）。
- [x] 在隔离 worktree 从 main 跑同步，fork 先追平 isjiamu 上游（fa4b78fb94）。
- [x] 核对候选提交范围仅含 skills/gzh-design/ 与 registry.json。
- [x] 窄采用候选到当前 main，保留本地二维码定制；冲突时整份保留本仓库文件并记录。
- [x] 验证：git diff 范围、registry lastSync 刷新、本地定制仍在。

## 跟进轮结果（2026-10-16）

- [x] 环境检查：gh 已安装但未登录，脚本回退本地 push 首次失败为瞬时网络错误，手动重推成功。
- [x] fork `zhjnerv/gzh-design-skill` main 已追平原作者 `fa4b78fb94`（ba1f417..fa4b78f 快进）。
- [x] 隔离 worktree 执行 `skill-sync.ps1 -Name gzh-design`，冲突 0；候选 3 个提交（7a39b2a squash、346fd38 subtree merge、bab1b6a registry）仅涉及 [skills/gzh-design/](../../skills/gzh-design/SKILL.md) 与 registry.json。
- [x] 以 `git merge --ff-only` 窄采用到 main（bab1b6a），原有未提交改动全部保留。main 领先 origin 4 个提交，未 push。
- [x] 验证：
  - registry lastSyncTree `ba6f805318a27ab4c7c13c33dab9069b4cce4d19` 与 `git rev-parse sync/...:skills/gzh-design` 一致。
  - 本地二维码定制完整保留（[SKILL.md](../../skills/gzh-design/SKILL.md) 第 112 行二维码指引、assets/account-qr.jpg、scripts/account_qr_block.py）。
  - 上游渐变修复已生效（SKILL.md 第 86、129 行；高亮/荧光笔改纯色，移除 linear-gradient 默认可用项）。
  - 随包新增测试 `test_validate_gzh_html.py`：Windows 默认控制台编码下 2 个用例因子进程 GBK 输出按 UTF-8 解码失败，属环境问题；`PYTHONIOENCODING=utf-8` 后 3 个测试全部通过。

## 当前状态

同步完成。main @ bab1b6a，未 push（等用户指示）。遗留小项：上游测试脚本在 Windows 非 UTF-8 控制台有编码兼容问题，可后续向上游反馈。

## 复查轮（2026-10-28）：检查上游是否有更新

### 目标与范围

对 [registry.json](../../registry.json) 登记的全部 6 个 skill 做只读上游复查；只判断是否有对应更新，不执行同步、提交或推送。沿用 fork 基线流程：外部 skill 以 `zhjnerv` fork 为本仓库基线，fork 再相对原作者 upstream 判断。

### 约束与验证

- 不修改 `skills/`、`vendor/` 和 registry 的同步基线。
- 先检查工作区状态，避免误动既有任务现场。
- 用仓库自带状态脚本或等价的 `git ls-remote` / GitHub 只读 API 复核；结论需给出上游 HEAD、变更范围或“无更新”依据。
- 将结果写回本计划，并核对计划内内部链接仍然存在。

### 步骤

- [x] 记录当前工作区与 registry 基线。结果：本地 HEAD `4832c88ec2fce7a3ed0dd4dcd43e2c6e17fe321d`；已跟踪 skill 目录无未提交改动，未跟踪文件均为既有任务计划/文档。
- [x] 运行只读远程状态检查。结果：本机 `gh` 已安装但未登录，改用 GitHub 公共只读 API 对本地、fork、upstream 的 Git tree 做内容寻址比较；未调用会修改内容的同步脚本。
- [x] 对有变化的 skill 复核提交与变更文件范围。结果见下表；`gzh-design` 用 commits API 按上次同步时间过滤，`md2word` 用 `path=skills/md2word` 过滤确认为 0 个新提交。
- [x] 更新检查结论、当前进度和下一步动作。结果：只读复查完成；未修改任何 skill、[registry.json](../../registry.json) 基线或工作区代码。

### 检查结果（2026-10-28）

| registry 项 | 判断 | 证据 |
|---|---|---|
| `cn-patent-agent-skills` | 当前。fork 与 upstream 同仓库，HEAD 均为 `c396b89a9e73`，整包 tree 均为 `7ac38cee95de`，与本地/registry 一致。 | [registry 基线](../../registry.json)；上游仓库 https://github.com/zhjnerv/cn-patent-agent-skills |
| `gzh-design` | **有新上游更新，建议后续同步。** 上游 HEAD `750a50dffdc4`（2026-10-21），本地/registry tree `ba6f805318a2`；fork HEAD 仍是上次同步的 `fa4b78fb9471`。新增 2 个提交，只改 `README.md`、`README.en.md`，公告 AtomGit 镜像。本地二维码定制为 `assets/account-qr.jpg`、`scripts/account_qr_block.py` 和 [SKILL.md](../../skills/gzh-design/SKILL.md) 中的指引；上游未碰这些文件。 | [gzh-design 本地账](../skills/gzh-design.md)；上游提交 5634700b4adc（2026-10-20）与 750a50dffdc4（2026-10-21） |
| `legal-skill-alignment` | 当时当前。upstream 子路径 tree `04e08d8f5614`，与 fork、本地、registry 完全一致。该 skill 已于 2026-11-03 删除。 | 本地 SKILL；[registry 基线](../../registry.json) |
| `md2word` | 无 10-19 后的新上游更新。按 `skills/md2word` 过滤上游 commits API 返回 0 个提交。本地与 upstream 有 12 个内容差异，对应页眉页脚/斯可睿抬头/GBK 控制台/原生标题样式等本地定制；fork 相对 upstream 只多 fork 侧 `DECISIONS.md` 和 `TASKS.md`。不要把这些定制差异误判为待同步更新。 | [md2word 本地账](../skills/md2word.md)；[registry 基线](../../registry.json) |
| `patent-download` | 当前。upstream 子路径 tree `b353d07dbf2f`，与 fork、本地、registry 完全一致。 | [本地 SKILL](../../skills/patent-download/SKILL.md)；[registry 基线](../../registry.json) |
| `qu-ai-wei` | 当前。fork 与 upstream HEAD 均为 `1d32e803f091`，tree `2d0e48d6d3df` 与本地/registry 一致。 | [本地 SKILL](../../skills/qu-ai-wei/SKILL.md)；[registry 基线](../../registry.json) |

### 检查限制

`skill-status.ps1 -Remote` 本轮未直接运行：`gh` 未登录会让脚本回退到慢速 subtree split。已改用等价的 GitHub Git Trees / Commits 公共只读 API。tree SHA 比较可确认内容是否一致；commits API 补充了提交时间与文件范围。本轮没有逐文件做安全审查，“有更新”只表示存在上游内容变化。

### 当前进度

只读复查已完成。唯一建议跟进项是同步 `gzh-design`：先让 `zhjnerv/gzh-design-skill` 追平 `isjiamu/gzh-design-skill` 到 `750a50dffdc4`，再执行本仓库的 fork-to-local subtree sync；合并时保留本地二维码定制。

### 下一步动作

等用户决定是否同步 `gzh-design`。执行前应确认 fork 追平和本地合并都保留二维码定制；本轮不主动同步。

## 复查轮（2026-11-03）：项目状态与全部 Skill 上游

### 目标与范围

只读检查当前仓库状态，并逐一判断 [registry.json](../../registry.json) 中 7 个登记项、共 13 份 `SKILL.md` 是否有对应上游更新；不执行同步、提交、推送、部署或清理。

### 重要约束

- 保留工作区现有未提交改动，不修改 `skills/`、`vendor/`、registry 或业务脚本。
- 外部 skill 继续沿用“原作者 upstream → zhjnerv fork → 本仓库”的基线关系；自研 `choice-oracle` 与自有整包需单独说明。
- 远程判断优先使用只读 Git/GitHub API；必须给出远端 HEAD/tree 或限定路径的提交证据。
- 结论写回本计划，并检查内部链接对应的文件存在。

### 步骤与验证

- [x] 记录当前工作区、本地 HEAD、实时远端和工作树状态；完成标准：区分已跟踪改动、未跟踪文件及分支同步关系。结果：本地 `main`/HEAD 为 `d58eec4`，实时远端 `origin/main` 为 `dddf92f`；远端向前 3 个自动同步提交，本地尚未拉取。当前有 1 个已跟踪计划修改、9 个未跟踪条目，均非 skill 内容修改；仅有主 worktree。
- [x] 核对 registry 登记项与本地 skill 目录/tree；完成标准：确认 7 个登记项、13 份 `SKILL.md` 的覆盖关系。结果：7 个登记项覆盖 6 个 `skills/` 条目和自有整包中的 7 个 `SKILL.md`；`choice-oracle` 为自研。
- [x] 查询各上游与 fork 的远程 HEAD、目标子路径 tree/提交；完成标准：每个登记项均有“有更新/无更新/不适用”及证据。结果见下表。
- [x] 汇总检查结果、限制和下一步；完成标准：更新本计划并验证新增内部链接存在。结果：本计划全部内部链接存在，CRLF/LF 已统一为 LF，空白检查通过。

### 当前进度

本轮只读检查已完成。未修改任何 skill、vendor 内容或 registry，也未拉取、同步、提交或推送。

### 检查结果（2026-11-03）

| registry 项 | 判断 | 证据 |
|---|---|---|
| [cn-patent-agent-skills](../../vendor/cn-patent-agent-skills/skills/cn-patent-workflow/SKILL.md) | **无新增内容更新。** 7 个子 skill 随整包一致。 | 上游与 fork HEAD 均为 `c396b89`，远端根 tree 与本地 tree 均为 `7ac38cee`；上游没有 2026-10-25 后的新提交。远端 myskill 的自动同步提交也未改变该 tree。 |
| [gzh-design](../../skills/gzh-design/SKILL.md) | **本地无新增更新；fork 尚未追平。** | 原作者 HEAD 仍为 `750a50d`，本地已通过 `89f3c5d` 纳入该版本；fork `fa4b78f` 落后原作者 2 个 README 提交，但这 2 个提交已经在本地。本地二维码定制见 [gzh-design 本地账](../skills/gzh-design.md)。 |
| `legal-skill-alignment` | **无更新；随后已删除。** | 原作者 `f5dafa4`、fork `6203418` 与本地在 `skills/legal-skill-alignment` 的 tree 均为 `04e08d8f`；删除记录见 [TASK_PLAN_remove-legal-skill-alignment.md](TASK_PLAN_remove-legal-skill-alignment.md)。 |
| [md2word](../../skills/md2word/SKILL.md) | **无新增更新。** | 上游该路径最后一次提交为 `b7f5bc9`（2026-10-18），本地已在 `d06c075`（2026-10-19）同步；之后无该路径提交。上游 tree `db274f11` 与本地 `bbf11bbe` 的差异来自既有本地定制，见 [md2word 本地账](../skills/md2word.md)。 |
| [patent-download](../../skills/patent-download/SKILL.md) | **无更新。** | 原作者、fork 与本地 tree 均为 `b353d07d`。 |
| [qu-ai-wei](../../skills/qu-ai-wei/SKILL.md) | **无新增更新。** | 上游与 fork HEAD 均为 `1d32e803`，tree 均为 `2d0e48d6`；本地 tree `ed3b3a49` 来自 [qu-ai-wei 本地账](../skills/qu-ai-wei.md)记录的平均断句长度定制。 |
| [choice-oracle](../../skills/choice-oracle/SKILL.md) | **不适用。** | registry 标记为 `origin: own`，没有上游。 |

### 项目状态（2026-11-03）

- 本地 `main` 与 HEAD 为 `d58eec4`；实时远端 `origin/main` 为 `dddf92f`，GitHub compare 显示远端向前 3 个提交、本地落后 0 个本地独有提交，可以快进。
- 远端 3 个提交来自 2026-11-02 成功运行的 [上游同步 workflow](../../.github/workflows/sync-upstream-skills.yml)；内容变化只有 [registry.json](../../registry.json) 中 `cn-patent-agent-skills` 的 `lastSync` 时间，skill 内容 tree 未变。
- 当前无暂存改动；1 个已跟踪修改为 [choice-oracle 计划](TASK_PLAN_choice-oracle.md)，另有 9 个未跟踪条目（既有任务计划与 `临时目录/`）。没有未提交的 skill 内容改动。
- 当前只有主 worktree；最新 GitHub Actions 定时同步运行 `41395354396` 成功。

### 检查限制

- tree 对比只能确认内容是否相同，未对上游逐文件做安全和兼容性审查。
- `gzh-design` fork 仍落后原作者 2 个提交；`legal-skills` fork 与原作者历史已明显分叉。本次判断以本地实际内容和三个导入子路径的 tree 为准。

## 复查轮（2026-11-04）：检查上游更新

### 目标与范围
对 [registry.json](../../registry.json) 登记的 5 个 vendored skill（`cn-patent-agent-skills`、`gzh-design`、`md2word`、`patent-download`、`qu-ai-wei`）做只读上游更新复查，自研 4 个 skill 标注为不适用。判断 upstream 与 fork 相对本仓库本地及 `lastSyncTree` 是否有新增更新；只读检查，不执行同步、拉取、合并或修改业务代码。

### 重要约束
- 保持工作区干净，不改动任何 skill 或 registry 同步基线。
- 采用 `gh api` / `git ls-remote` 只读查询远程仓库状态。
- 子路径 skill（`md2word`、`patent-download`）核对限定在子路径的 tree 及提交，避免合集仓库其他不相关目录更新造成误判。
- 逐项记录判定依据，完成后更新本计划。

### 步骤与验证
- [x] 1. 查询各上游与 fork 的远程最新 HEAD、提交时间与对应 tree。结果：通过 `gh api` 查询到所有上游与 fork 的最新提交及根 tree SHA。
- [x] 2. 针对子路径 skill 获取对应 subpath 的 Git tree SHA 及最近 commits。结果：`cat-xierluo/legal-skills` 中 `skills/md2word` 最近提交为 2026-10-18 `b7f5bc9`，`skills/patent-download` 最近提交为 2026-08-05 `5fce235`，均无新增上游提交。
- [x] 3. 比对本地 HEAD tree / registry `lastSyncTree`，判定是否存在待同步更新。结果：5 个引入 skill 的上游目前均无任何新增代码或文档提交；`gzh-design` fork 仍停留在 10-09，但原作者 10-21 的 2 个提交已于 10-26 通过自动 workflow 汇入本地。
- [x] 4. 汇总判定结论并更新本计划。结果：下表已列出完整检查证据与判定。

### 检查结果（2026-11-04）

| registry 项 | 判断 | 证据与详情 |
|---|---|---|
| [cn-patent-agent-skills](../../vendor/cn-patent-agent-skills) | **当前（无新更新）** | 上游与 fork 均为 `zhjnerv/cn-patent-agent-skills` main 分支，HEAD 仍为 `c396b89`（2026-10-20），根 tree 为 `7ac38cee`，与本地 HEAD tree 及 [registry 基线](../../registry.json) 完全一致。 |
| [gzh-design](../../skills/gzh-design/SKILL.md) | **当前（无新更新）** | 原作者 `isjiamu/gzh-design-skill` 最新提交仍为 `750a50d`（2026-10-21），自此无任何新提交。该提交已于 2026-10-26 随 `3294abf` 纳入本地。fork 仍留在 `fa4b78f`（未追平 2 个 README 提交，但不影响本地）。本地二维码定制见 [gzh-design 本地账](../skills/gzh-design.md)。 |
| [md2word](../../skills/md2word/SKILL.md) | **当前（无新更新）** | 原作者 `cat-xierluo/legal-skills` 虽有其他目录提交，但针对 `skills/md2word` 路径最后一次提交为 `b7f5bc9`（2026-10-18），之后无任何触碰该路径的提交。本地已于 2026-10-19 纳入该上游基线，本地定制见 [md2word 本地账](../skills/md2word.md)。 |
| [patent-download](../../skills/patent-download/SKILL.md) | **当前（无新更新）** | 原作者 `cat-xierluo/legal-skills` 针对 `skills/patent-download` 路径自 2026-08-05（`5fce235`，v2.7.1）以来无任何新提交。本地 tree `b353d07d` 与上游完全一致。 |
| [qu-ai-wei](../../skills/qu-ai-wei/SKILL.md) | **当前（无新更新）** | 原作者 `LifelongLazyLearner/qu-ai-wei` 最新提交仍为 `1d32e803`（2026-09-10），自此无任何新提交。fork 亦为 `1d32e803`，上游 tree 为 `2d0e48d6`。本地 tree `ed3b3a49` 系已记录的本地特性定制（`f48cede` 断句长度要求），见 [qu-ai-wei 本地账](../skills/qu-ai-wei.md)。 |
| [choice-oracle](../../skills/choice-oracle/SKILL.md) 等 4 个自研技能 | **不适用** | `choice-oracle`、`cn-patent-fast-track-screener`、`cn-office-action-prior-art-collector`、`cn-trademark-goods-services-recommender` 均为自研技能（`origin: own`），无外部上游。 |

### 当前进度
本轮 5 个引入 skill 的上游更新核查已全部完成。经 `gh api` 逐一比对，各外部上游目前均无新版本或新提交需要同步。未修改任何业务代码或注册表基线。

### 下一步动作
无需执行任何同步或合并操作。保留本计划记录供后续核查。

