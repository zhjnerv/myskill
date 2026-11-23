# TASK_PLAN：配置 GitHub Actions token

## 目标与范围
把为 myskill 反向同步工作流创建并配置 Actions token 的步骤写入项目。secret 名最终按仓库实际情况定为 `IP_PRACTICE`。

## 重要约束
- 项目只保存操作说明，不保存 token、临时文件或凭据。
- 保留现有工作区暂存状态；不执行 GitHub secret 写入。
- 指南只授权目标源仓库和必要权限。

## 步骤与验证
- [x] 新增 token 与 Actions secret 配置指南。结果：文档说明 fine-grained token 仅授权 `ip-practice-workbench-skills`，只授予 Contents 与 Pull requests 读写权限，并记录 secret 配置、首次验证和轮换/撤销步骤；没有保存 token。
- [x] 在技能包维护说明中加入可达链接。结果：维护说明链接至新指南；目标文件存在，`git diff --check` 通过。

## 当前进度
项目内配置指南已完成。后续用户在 `zhjnerv/myskill` 配置了名为 `IP_PRACTICE` 的 secret（非本计划的 `IP_PRACTICE_WORKBENCH_TOKEN`），代码与文档已统一改用实际名称，回推工作流已实跑成功。详见[双向同步启用计划](../../TASK_PLAN_双向同步启用.md)。

## 下一步动作
无剩余动作。配置与验证结果记在[双向同步启用计划](../../TASK_PLAN_双向同步启用.md)；配置步骤见 [Token 配置指南](../github-actions-token-setup.md)。
