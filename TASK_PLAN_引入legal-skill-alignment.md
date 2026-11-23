# TASK_PLAN：引入 legal-skill-alignment

## 目标与范围
把 `cat-xierluo/legal-skills` 的 `skills/legal-skill-alignment` 通过已有 fork `zhjnerv/legal-skills` 引入本仓库 `skills/legal-skill-alignment/`，并写入 registry.json。

## 重要约束
- 使用已有 fork，不新建 fork。
- 本计划文件不纳入提交。
- 引入成功后推到 origin/main，并部署到本机 Claude / Codex。

## 步骤与验证
- [x] 确认工作区干净。结果：引入前 `main` 仅比 origin 超前既有的 `4521d24`。
- [x] 引入 skill。完成标准：目录、registry、提交身份。结果：`skills/legal-skill-alignment/SKILL.md` 为 v1.0.7；registry 提交 `7a53c9f`，作者 `zhjnerv <zhjwork@gmail.com>`。镜像工作区先对齐到 `origin/main` 后，subtree split 得到 `aad4ccd`，再 squash 引入。
- [x] safe-push 并部署。结果：`SAFE_PUSH_OK`，`HEAD` 与 `origin/main` 均为 `7a53c9f`。当时记录已 junction 到 `.claude\skills` 与 `.codex\skills`。

## 当前进度
仓库引入已完成。2026-10-04 复核：本机没有这个 skill 的入口。`~/.claude/skills` 和 `~/.codex/skills` 里相关目录都是指向 `~/.cc-switch/skills` 的符号链接，不是 myskill junction；cc-switch 中也没有 `legal-skill-alignment`。

## 下一步动作
该 skill 已于 2026-11-03 按要求删除，原引入流程结束，见 [TASK_PLAN_remove-legal-skill-alignment.md](TASK_PLAN_remove-legal-skill-alignment.md)。若以后重新引入，应另开任务并重新核对本机部署状态。
