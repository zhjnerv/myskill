# TASK_PLAN：qu-ai-wei 平均断句长度需求

## 目标与范围
2026-11-02 用户授权落地既有需求：在 [skills/qu-ai-wei/SKILL.md](skills/qu-ai-wei/SKILL.md) 中要求普通正文平均片段字数 >=10，提供轻量统计方法，并保护事实、语体和有意节奏。旧 worktree 问题另见 [清理计划](TASK_PLAN_worktree-cleanup.md)。

## 重要约束
- 只修改 qu-ai-wei 技能及 [本地需求账](docs/skills/qu-ai-wei-average-segment-length.md)，按 [记账规则](docs/skills/README.md) 补标准账本；不修改上游账或 registry 同步基线。2026-11-02 用户追加授权 commit and push，仅发布本次任务范围。
- 片段指断句标点之间的文字，不计标点和空白。
- 保留现有“自然变化、拆长句、合并碎句”的节奏原则，避免写成所有片段必须等长。

## 步骤与验证（原需求起草阶段）
- [x] 检查 skill 现有节奏规则位置。
- [x] 起草独立需求文档，写清指标定义、计算口径、适用范围和验收方式。结果：见 [docs/skills/qu-ai-wei-average-segment-length.md](docs/skills/qu-ai-wei-average-segment-length.md)。
- [x] 检查文档链接可访问、无草稿残留，并确认 skill 本体未改动。结果：`git status` 显示仅新增计划与需求文档，`skills/qu-ai-wei/SKILL.md` 未修改。

## 当前进度
实施、安装及发布均已完成。功能提交 `f48cedee341a8899be00416917b2391bb785cc6f` 已推送至 origin/main，并经实时远端核对。此前由本轮 Codex 从基准 `5efa134aec69c277a493d0b335ae663268270142` 精确采用 7 个文件，采用前快照创建及复验均 PASS，所有候选文件另有 SHA-256 清单和仓外副本。Codex/Claude 共用的安装源已同步本次 4 个技能文件；两个入口的 SKILL.md 与仓库哈希一致。本轮临时工作树和分支已普通移除。

## 实施步骤与验证（2026-11-02）
- [x] 核对 fork/上游内容、现有节奏与输出规则，冻结最小改动范围。结果：两远端 commit 同为 `1d32e803f091ec90808a69683ebf49e8a970a5e7`，tree 与本地同为 `2d0e48d6d3df0c805943e58ced4fd94fbd79e0d6`；无需先同步。事实/保护优先级与内嵌模式不变。
- [x] 在仓库外新建稀疏隔离工作树，仅检出 `skills/qu-ai-wei` 与 `docs/skills`。结果：基准、目录与初始干净状态核对通过，规则及统计辅助已实现；[本地账](docs/skills/qu-ai-wei.md) 和原需求已更新，未改上游版本或 registry。
- [x] 执行计数正反例、skill 静态检查和差异审阅。结果：8 项计数/CLI 测试通过；quick_validate 通过；现有触发/排除检查 10 项通过；中文样例 23 字/2 片段=11.5 通过，9 字/3 片段=3.0 正确失败。安全扫描无 high/critical，11 项 medium 均经上下文审阅为测试标记/固定参数调用；规则要求人工筛选受保护片段，脚本不假称能识别。多轮模型遵循稳定性为 NOT_VERIFIED；未执行含 npx 下载步骤的全量发布检查。
- [x] 将验证过的精确文件应用至主工作区并同步已有安装源。结果：7 个采用文件逐一核对候选/仓库/备份哈希，4 个技能文件同步至现有 cc-switch 安装源，Codex/Claude 链接保持原样且实际文件一致；临时树中本轮产物完整归档后恢复干净并普通移除，无强制删除。32 个相关内部链接检查及 `git diff --check` 通过，未提交/推送。

## 下一步动作
本次实施与用户追加授权的提交、推送均完成。后续真实改写按新口径复核；本轮不宣称模型多轮输出质量已经验证。旧 worktree 结果见 [清理计划](TASK_PLAN_worktree-cleanup.md)。

## 提交与推送（2026-11-02）
- [x] 核验远端 main、身份来源、精确文件范围和提交内容。结果：远端与本地同为 `5efa134aec69c277a493d0b335ae663268270142`；身份审计为 IDENTITY_AUDIT_OK，无 repo/worktree 覆盖。7 个实施文件与此前验证候选哈希一致，所有发布文档链接目标已在 HEAD 或本次范围内。提交范围为本技能 SKILL.md、统计脚本、计数测试、测试 README，docs/skills 的索引/本地账/需求，以及本计划和 worktree 清理计划，共 9 个文件；其他任务现场保留。
- [x] 经快照、身份及隐私检查后提交上述范围，再通过 safe-push 发布 origin/main。结果：提交 `f48cedee341a8899be00416917b2391bb785cc6f`，9 文件；IDENTITY_GATE_OK、PRIVACY_OK、SAFE_PUSH_OK 均通过。实时远端 main 与本地提交一致。
- [x] 补记已核验的提交/推送结果，检查暂存区、剩余工作区与 worktree。结果：功能提交发布后暂存区为空，工作树仅 main；其他任务计划、choice-oracle 收尾改动和临时图片均保留。两份本次任务计划形成完成记录，随本次发布收尾一并保留。

提交 `f48cedee341a8899be00416917b2391bb785cc6f` 已生成，精确包含上述 9 文件，staged 与提交说明隐私检查均为 PRIVACY_OK。首次 safe-push 身份门禁通过，随后因 Git Bash 的 `python3` 指向 WindowsApps 占位入口而退出；实时远端仍为 `5efa134`。下一步仅在本次 shell 中把 `python3` 绑定到现有 Python 3.12，继续执行原 safe-push，不改全局 PATH、不跳过检查。

修正解释器后的首次重试在 fetch 阶段遇到 GitHub `Connection was reset`，未进入 push；下一步先只读复核远端，再作一次有界重试。

后续只读诊断确认：GitHub API/HTTP 可达，Git 提示当前仅支持 schannel，而系统配置仍指定 openssl。本机中间 DNS 地址的 TLS 连接仍不稳定；改用公开 DNS 本次解析结果，在单次 safe-push 进程中绑定 schannel、HTTP/1.1 和目标地址后，成功推送 `5efa134..f48cede`。未修改全局 Git、DNS 或代理配置，也未跳过证书、身份或隐私检查。
