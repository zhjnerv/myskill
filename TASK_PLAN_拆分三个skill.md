# 知产实务工作台：接回 myskill

## 目标与结果

独立仓库负责开发和开源；myskill 通过 [整包登记](registry.json) 同步到 [vendor 包](vendor/ip-practice-workbench-skills/README.md)，统一部署三个技能。管理方式和可复用经验只维护在 [包说明](docs/skills/ip-practice-workbench-skills.md)。

## 已完成（2026-11-06）

- [x] 精简两个现役计划，删除旧迁入计划和旧提交计划；保留品牌/技术 ID、数据来源、跨平台路径及受控文件迁移经验。
- [x] 引入上游 `1e1042385522145b167ba8931f1a5a4bd591b532`，tree `c6600b396b542a3726c2d9ec607d0f4406771291`；移除三个顶层副本及 own 登记。
- [x] 修复包内按名称部署，验证 73 项技能测试、5 项部署回归、1 项 subtree 连续同步回归；同版 pull 无变化，文档文件/锚点链接通过。
- [x] 本地采用 `200eadc` 与 subtree 提交 `2bf5787`；主目录 tree 与隔离候选 `73b127c` 一致。Codex/Claude 六个 junction 均指向本仓库 vendor 包中的技能；25 份其他计划/材料哈希保持。

## 当前状态与后续

本地接回、安装及远端推送完成；已跟踪工作区干净，main 与 origin/main 均为 `2bf5787ce0be42ff0e4959a152529f29e34b641e`，差异 0/0。本轮不改独立公开仓库的已跟踪文件、技能业务实现或线上页面。

本轮无待推送提交；公开仓库资料来源的待核事项仍在包内 DATA_SOURCES/NOTICE 中。后续维护命令见 [包说明](docs/skills/ip-practice-workbench-skills.md)。

已验证隔离候选与远端 tree 相同并移除本轮临时 worktree/分支，仓外回退与格式审查证据保留；没有遗留未验证的本机安装步骤。新会话从本记录与 [使用手册](docs/usage.md) 接手，无需重跑已通过的业务测试。

实际联网同步预览已通过：`skill-sync.ps1 -Name ip-practice-workbench-skills -DryRun` 获取到上游 `1e10423`，同步配置可用。

## 提交与推送结果

- [x] 复核已有 3 个提交，已跟踪工作区与暂存区无改动，无需重复提交。
- [x] 身份检查通过，二进制格式审查完成，完整范围隐私复验返回 PRIVACY_OK。
- [x] safe-push 成功，远端从 eebf01a 更新至 2bf5787；实时 ls-remote、HEAD 与 origin/main 一致，差异 0/0。
- [x] 本轮临时工作树和分支在完整 tree 对照后清理；未跟踪计划与临时素材未推送。

当前状态：本次任务完成。按 [技能包说明](docs/skills/ip-practice-workbench-skills.md) 进行后续开发和同步。
