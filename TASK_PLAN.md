# TASK_PLAN：落地 skill 改动记账

## 目标与范围
把「引入的 skill 本地账写在 docs/skills/，自研 skill 在目录内写 TASKS/DECISIONS/CHANGELOG」写成仓库规则，并让 skill-new.ps1 生成自研三份账。不改任何上游 skill 的 CHANGELOG、TASKS、DECISIONS。

## 重要约束
- 自动同步冲突时整份保留本仓库文件。本地需求不能再写进上游那三份文件。
- md2word 已有的 1.3.9-skr 记录留在原 CHANGELOG，只在新账里指向它。
- 不提交，除非用户另说。

## 步骤与验证
- [x] 写 docs/skills/README.md，并补上 md2word、gzh-design 已有本地改动。结果：三份文件已在 docs/skills/。
- [x] CLAUDE.md、docs/usage.md、docs/fork-workflow.md、README.md 指向这条规则。结果：四处都有链接或对应段落。
- [x] skill-new.ps1 创建 TASKS.md、DECISIONS.md、CHANGELOG.md。结果：Parser 解析通过，未实际新建 skill。

## 提交与推送
- [x] 复核工作区、分支、远端、身份和差异范围。结果：当前为 `main`，本地领先 `origin/main` 4 个提交；提交范围固定为 5 个修改文件和 `docs/skills/` 下 3 份账本，其他任务现场保留。
- [x] 运行 `git diff --check`、`skill-new.ps1` Parser 解析和账本内部链接检查。结果：全部通过。
- [x] 精确提交上述 8 个路径，不用整索引提交。结果：提交 `d4242c0`，已保留当时暂存的 `斯可睿抬头.docx`。
- [x] 按用户补充授权，单独提交已暂存的 `skills/md2word/assets/letterhead/斯可睿抬头.docx`。结果：提交 `6b5abb8`。
- [x] 处理远端并发：`safe-push.sh` fetch 后显示 `origin/main` 已前进到 `4f0b0a0`，且新增提交只改 `registry.json`；将远端提交并入本地 `main`，仅在必要时解决 `registry.json` 冲突。结果：合并提交 `82dd1bd`，`registry.json` 保留本地较新 gzh/legal 记录并采纳远端 claude 同步时间，JSON 校验通过。
- [x] 合并后重新运行完整身份、隐私和推送门禁。结果：身份门禁 `IDENTITY_GATE_OK`；隐私门禁 `PRIVACY_REVIEW_REQUIRED`，未推送。
- [x] 定位隐私命中并记录用户放行决定。结果：文本命中来自法律对齐技能的示例和测试占位路径；二进制命中包括二维码、演示 GIF、Word 模板及其历史版本。用户明确授权放行并推送。`.git/privacy-reviewed.json` 的现有类型不支持记录“用户授权公开”，未伪造审查类别。
- [x] 按用户授权将已核对的本地 `main` 提交范围推送至 `origin/main`。结果：推送成功，远端从 `4f0b0a0` 更新到 `82dd1bd`；推送前隐私扫描发现待核对项，用户明确授权后按该授权发布。
- [x] 复核本地 HEAD、远端跟踪分支和工作区剩余现场。结果：`HEAD` 与 `origin/main` 均为 `82dd1bd4d701614a9a993be679bf49976b8b3933`；未跟踪的任务计划及 qu-ai-wei 需求文档仍保留。

## 当前进度
提交与推送已完成。身份门禁通过；隐私扫描曾发现待核对项，用户明确授权后完成推送。工作区其他未跟踪文件保留。

## 下一步动作
无。
