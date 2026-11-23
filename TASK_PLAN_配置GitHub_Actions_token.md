# TASK_PLAN：配置 GitHub Actions token

## 目标与范围
把为 myskill 反向同步工作流创建并配置 `IP_PRACTICE_WORKBENCH_TOKEN` 的步骤写入项目，供后续继续完成。

## 重要约束
- 项目只保存操作说明，不保存 token、临时文件或凭据。
- 保留现有工作区暂存状态；不执行 GitHub secret 写入。
- 指南只授权目标源仓库和必要权限。

## 步骤与验证
- [x] 新增 token 与 Actions secret 配置指南。结果：文档说明 fine-grained token 仅授权 `ip-practice-workbench-skills`，只授予 Contents 与 Pull requests 读写权限，并记录 secret 配置、首次验证和轮换/撤销步骤；没有保存 token。
- [x] 在技能包维护说明中加入可达链接。结果：维护说明链接至新指南；目标文件存在，`git diff --check` 通过。

## 当前进度
项目内配置指南已完成。GitHub Actions 当前没有 `IP_PRACTICE_WORKBENCH_TOKEN` secret；本机 OAuth token 权限过宽，不复用，也未尝试写入 secret。

## 下一步动作
下次按 [配置指南](docs/github-actions-token-setup.md) 创建最小权限 token 并将其保存为 `zhjnerv/myskill` 的 Actions secret；再手动运行回推 workflow 验证。
