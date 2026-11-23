# TASK_PLAN：排查 Codex Hook 3 秒超时

## 目标与范围
检查项目与用户级 Codex 配置，定位并修复提示 `Hook failed: hook timed out after 3s`：移除已停用 Pebrel 遗留的 Codex Hook，保留当前 tty7 Hook。用户已授权修改用户级配置。

## 重要约束
- 先确认项目根目录和现有计划，不覆盖无关计划。
- 配置文件可能包含凭据；汇报时只说明相关字段，不输出秘密值。
- 只处理 Codex 自身的 Hook 配置，不顺手修改仓库或顶层 `notify`。
- 修改前备份两个 Hook 文件；不绕过 Codex 的 Hook 信任确认机制。

## 步骤与验证
- [x] 读取现有计划并确认仓库现状。
- [x] 检查是否存在 Codex 项目级、用户级及全局配置和 Hook 定义。结果：项目无 `.codex` Hook；Codex 0.166.0 使用用户级 `hooks.json`，其中 tty7 与 Pebrel 被重复注册给同一批事件。
- [x] 核对 Hook 超时字段、触发事件和实际命令，判断为什么达到 3 秒。结果：Pebrel 的每个 `command` 和 `commandWindows` 都显式配置 `"timeout": 3`；tty7 同事件 Hook 未设置超时。`Interrupt` 与 `SessionEnd` 由 Codex 限制为最多 3 秒。
- [x] 必要时用最小、只读命令测量 Hook 本身的耗时。结果：Pebrel 单独调用各事件 10 次，中位数 34–178 ms，最大值 491 ms，均退出 0；tty7 `tool-complete` 调用约 769 ms、退出 0。静态调用不能完全复现并发运行时的超时。
- [x] 汇总根因、可调整项及验证结果，并更新本计划。结果：3 秒提示来自 Pebrel 的显式 `timeout: 3`；它被注册到 8 个生命周期事件，并同时存在于 `hooks.json` 与 `hooks.pebrel-managed.json`。当前只有 tty7 进程在运行，未发现 Pebrel 进程；顶层 `notify` 指向的可执行文件存在，不是本次 3 秒超时来源。
- [x] 按 `openai-docs` 流程复核官方 Hook 行为并确认 tty7 没有可直接关闭 Pebrel Hook 的配置开关。
- [x] 备份 `hooks.json` 与 `hooks.pebrel-managed.json`。备份为 `hooks.json.bak-20261101-013502` 和 `hooks.pebrel-managed.json.bak-20261101-013502`。
- [x] 从 `hooks.json` 移除全部 Pebrel Hook，并在 managed 文件中将 `enabled_feature` 设为 `false`。共移除 8 个 Pebrel matcher group。
- [x] 验证两份 JSON 可解析、无 Pebrel 注册项、tty7 Hook 仍存在。结果：活动配置剩 6 个事件、6 个 tty7 handler、0 个 Pebrel handler；managed 文件 `enabled_feature=false`；等待 3 秒后配置未被重写。`codex doctor --summary --no-color` 显示 `config loaded`，0 fail。

## 当前进度
修复完成。Pebrel Codex Hook 已从活动配置移除，tty7 Hook 保留，备份与配置校验均已完成。

## 下一步动作
无需继续修改。下次启动 Codex 时可能要求重新确认保留下来的 tty7 Hook；这是配置哈希变化后的正常安全流程。参考 [OpenAI Docs Hook 超时说明](https://developers.openai.com/codex/hooks)。
