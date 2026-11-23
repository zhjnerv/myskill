# TASK_PLAN：删除 legal-skill-alignment

## 目标与范围

从本仓库删除 `legal-skill-alignment`，包括 `skills/legal-skill-alignment/` 的 44 个已跟踪文件和 [registry.json](registry.json) 中的对应登记项；同步修复受影响计划中的内部链接。不删除上游 fork，不执行同步、提交、推送或部署。

## 重要约束

- 保留当前工作区其他未提交改动，不触碰无关 skill、脚本或临时目录。
- 本机未发现该 skill 的 Codex/Claude 部署入口，因此没有部署链接需要清理。
- 删除后 registry 必须保持合法 JSON，且自动同步不会再枚举该 skill。
- 历史任务计划保留，但失效的本地 skill 链接需要改为删除记录或普通文本。

## 步骤与验证

- [x] 核对工作区、登记项、文件数量、部署入口和全部引用。结果：skill 目录有 44 个已跟踪文件，registry 有 1 个对应条目，本机无同名部署入口。
- [x] 删除 skill 目录并移除 registry 条目。完成标准：目录不存在，registry 可解析且不再包含该名称。结果：目录已删除，registry 合法且从 7 项降为 6 项。
- [x] 修复受影响计划中的内部链接。完成标准：保留历史结论，相关计划指向本删除计划或使用不失效的文本。结果：4 份相关计划已更新，历史结论保留。
- [x] 执行最终核验。完成标准：无失效链接或 registry 残留、JSON 合法、Git 状态只包含预期删除和既有改动；计划内部链接有效。结果：registry 剩 6 项，44 个跟踪文件删除，无暂存内容，修改计划内部链接和空白检查通过。

## 当前进度

全部步骤已完成。删除结果保持为未暂存改动，未提交、未推送。

## 下一步动作

本轮无剩余步骤。后续如需固化删除结果，可单独提交 `registry.json` 与 `skills/legal-skill-alignment/` 的删除改动。

## 提交与推送（2026-11-03）

### 目标与约束

- 将删除结果提交并推送到 `origin/main`；远端基准为实时 `dddf92f`。
- 只纳入 `registry.json` 和 `skills/legal-skill-alignment/` 的删除，不提交现有未跟踪计划、其他计划修改或 `临时目录/`。
- 按 Git Workflow 要求在独立检出中提交，不改共享主目录；提交身份使用仓库最近一次提交的 `zhjnerv <zhjwork@gmail.com>`，通过单次环境变量绑定。
- Release Skills 检查未发现根级版本文件、变更日志或 tag，因此不执行版本 bump、changelog 或 tag，只做普通提交与推送。

### 步骤与验证

- [x] 固定提交范围、远端基准、身份和发布配置。结果：范围 45 个路径（registry 1 个、skill 删除 44 个），远端 `dddf92f`，身份 `zhjnerv <zhjwork@gmail.com>`。
- [x] 从最新远端创建独立检出并重放删除。完成标准：仅目标路径变化，registry 合法且不再包含该 skill。结果：独立克隆 HEAD 为 `dddf92f`，共 45 个路径变化（44 个删除、1 个 registry 修改），无其他改动。
- [x] 精确暂存并完成提交前检查。完成标准：隐私预检、diff 范围和空白检查通过，提交身份正确。结果：45 个候选路径全部在允许范围内；删除内容中的示例身份证/手机号经核对为无效/文档测试值，已登记精确本地例外；隐私、diff 和空白检查通过。
- [x] 创建提交并通过 `safe-push.sh` 推送 `origin/main`。完成标准：推送返回 `SAFE_PUSH_OK`，远端 main 指向新提交。结果：提交为 `c3e3fb78252dbd59a642a6562baf4879ad927c3b`，推送 `dddf92f..c3e3fb7`，身份与隐私门禁通过。
- [x] 核验远端内容与本地任务记录。完成标准：远端提交范围正确、registry 已移除该 skill、计划记录实际 OID。结果：远端 `origin/main` 为 `c3e3fb7`，提交恰含 45 个允许路径；registry 剩 6 项，远端 skill 路径不存在。

### 当前进度

全部步骤已完成。云端 main 已更新，本地共享主目录随后已 fast-forward 到 `c3e3fb7`，与 `origin/main` 齐平。

### 下一步动作

本轮无剩余操作。本地同步记录见 [TASK_PLAN_sync-main-legal-removal.md](TASK_PLAN_sync-main-legal-removal.md)。
