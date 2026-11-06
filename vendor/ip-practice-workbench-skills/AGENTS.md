# 知产实务工作台 · 实务技能

先阅读 [README](README.md) 和 [品牌约定](docs/brand.md)。本仓库维护三个独立技能，不包含线上服务运行环境。

- 保持目录名与 `SKILL.md` 的 `name` 一致；场景展示名称与品牌约定同步。
- 每个技能应可单独复制使用；脚本和运行时资源使用技能目录内相对路径，不依赖个人工作区。
- 不把“审查意见答复 · 材料准备”扩写成完整策略或文稿生成，不引入复审场景的未实现能力。
- 修改数据时核对实际来源、版本与条目数量，更新 [数据说明](DATA_SOURCES.md) 及技能 NOTICE；不要通过改写来源口径代替来源证据。
- 改动前先写本地 TASK_PLAN，完成后保留验证结果；计划和临时证据不进入公开提交。
- 用 `python -B -S -X utf8 scripts/verify.py` 运行离线验收；实际网络下载或 Agent 评测单独记录。
- 发布前按 [公开发布准备](docs/release.md) 检查确切文件清单，区分原创 MIT 内容与第三方资料。
- 维护每个技能的 TASKS、DECISIONS、CHANGELOG；仓库级变更记入 [CHANGELOG](CHANGELOG.md)。
