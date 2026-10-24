# TASK_PLAN：重连 cn-patent-agent-skills

## 目标与范围
把原 `claude-patent-creator-cn` 整包连接迁移为 `cn-patent-agent-skills`：更新 [registry.json](registry.json) 的包名、远端地址和本地前缀，把 [vendor/claude-patent-creator-cn](vendor/claude-patent-creator-cn) 迁到新包名并同步远端改名后的内容，同时把本机 Codex/Claude 的七个 `cn-patent-*` Skill 入口接到本仓库新包。

## 重要约束
- 新仓库地址已核验为 `https://github.com/zhjnerv/cn-patent-agent-skills`；七个 Skill 名称不变。
- 用户已明确授权本次提交并推送；保留现有未跟踪任务计划，不把无关未跟踪文件混入提交。
- 只替换指向旧源的 Skill 链接，不删除或改动 `~\.cc-switch\skills` 下的源目录。
- 修改写集限于 `registry.json`、[docs/usage.md](docs/usage.md)、`vendor/claude-patent-creator-cn -> vendor/cn-patent-agent-skills` 及本计划。

## 步骤与验证
- [x] 核验旧仓库重命名和新远端。结果：GitHub API 返回 `zhjnerv/cn-patent-agent-skills`，远端 `main` 为 `c396b89a`。
- [x] 比较本地旧包与远端新版。结果：18 个文件、88 行新增、73 行删除，主要是包名、运行根变量和默认安装目录更新。
- [x] 将远端新版应用到本地包，并把本地目录改名为 `vendor/cn-patent-agent-skills`。结果：18 个内容差异已同步，整包目录已改名。
- [x] 更新 `registry.json` 与 `docs/usage.md` 的包名、地址、路径示例，并刷新 `lastSync`/`lastSyncTree`。结果：`lastSyncTree` 为 `7ac38cee95dea6056d4a94e52ce605a1175e53b1`。
- [x] 验证 JSON、包完整性、关键安装标识和聚焦测试；不默认跑无关全量测试。结果：`git diff --check` 与注册表解析通过；`verify_package.py` PASS；相关 2 个测试文件共 4 项在短 Temp 路径下全部通过。默认 Temp 路径会触发 Windows 长路径复制失败，非包内容缺陷。
- [x] 重建本机 Codex/Claude 的七个 Skill 链接，并创建 `~\.codex\vendor\cn-patent-agent-skills` 包根链接。结果：14 个 Skill 入口均指向本仓库 `vendor/cn-patent-agent-skills/skills/`；Codex vendor 包根也指向新包；旧 `~\.cc-switch\skills` 源目录未删除。
- [x] 复查链接目标、Git 状态和剩余差异。结果：Codex/Claude 各 7 个入口和 Codex vendor 包根均指向本仓库新包；旧 `.cc-switch` 源仍在；`git diff --cached --check` 通过；暂存包 tree 与远端 `7ac38cee...` 一致；未暂存改动为 0。
- [x] 复核分支、HEAD、身份来源、暂存范围和主目录 main 门禁。结果：`main`，`HEAD` 与 `origin/main` 同为 `82dd1bd4`；生效身份 `zhjnerv <zhjwork@gmail.com>` 来自全局配置，无仓库/工作树覆盖，`identity-audit.sh whoami` 为 `IDENTITY_AUDIT_OK`；staged 245 路径，`git diff --cached --check` 通过；未安装 main-guard、无 `index.lock`。
- [x] 运行本地隐私预检。结果：首次命中 `vendor/cn-patent-agent-skills/模版.docx` 的 `binary-content`；已按 docx 结构检查正文、页眉页脚、脚注、批注、嵌入对象、核心/应用元数据与内嵌图片，确认是虚构示例模板，且字节与已发表旧路径 `vendor/claude-patent-creator-cn/模版.docx`（blob `f61e682`）完全一致，本次仅改名；审查产物 `.git/privacy-review-artifacts/模版.docx.review.json`（sha256 `5330427c...`），登记 `.git/privacy-reviewed.json` 例外后复跑 `PRIVACY_OK`。
- [x] 提交暂存范围，提交后再用安全推送门禁推送 `main` 到 `origin/main`。结果：提交 `5f9faac`（245 路径）；首次推送时远端已前进到 `3b2d157`，门禁按预期拒绝非祖先 base；并入远端后生成合并提交 `f529685`，`registry.json` 自动合并保留双方更新；`safe-push.sh` 输出 `IDENTITY_GATE_OK`（2 commits）与 `PRIVACY_OK`，推送 `3b2d157..f529685` 成功，`SAFE_PUSH_OK`。
- [x] 复核本地 HEAD、远端跟踪分支、工作区剩余现场，并记录提交/推送结果。结果：推送后本地 `HEAD` 与 `origin/main` 一致；工作区仅剩 7 个既有未跟踪文件与本次任务无关，保留未动。

## 当前进度
迁移、门禁、提交、远端合并与推送均完成；远端 `main` 已包含 `f529685`。本计划文件的结果更新作为收尾记录提交。另有 7 个既有未跟踪文件与本次任务无关，保留未动。

## 下一步动作
无。
