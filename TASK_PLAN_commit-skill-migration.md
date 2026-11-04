# TASK_PLAN：commit and push

## 目标与范围
提交当前工作区中与三个自研专利技能迁移相关的改动并推送 `origin/main`。

## 重要约束
- `临时目录/`（XIUREN 图片）不提交。
- 历史 TASK_PLAN 文件与本次改动无关时单独处理，不混入技能提交。

## 步骤与验证
- [x] 检查三个技能 README 的许可/数据来源说明，确认无阻塞发布的风险点。
- [x] 精确暂存：skills/cn-*（3 个目录）、registry.json、README.md、TASK_PLAN_choice-oracle.md；校验 `git diff --cached --stat` 与 JSON 语法。
- [x] 提交并推送 origin/main；确认 HEAD 与 origin/main 一致。

## 当前进度
重写为单一干净提交：移除第三方数据来源说明（含数据 JSON 的 source/sourceUrl 字段），DECISIONS 以老周手改版本为准（官方渠道口径）；grep 全目录及全部新提交零命中，数据校验与 25 个测试通过后推送。

## 下一步动作
老周确认后执行 git push；若暂缓则按其决定处理。
