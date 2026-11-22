# 知产实务工作台技能包

## 来源和维护边界

独立仓库 `zhjnerv/ip-practice-workbench-skills` 是开发与公开发布源；myskill 在 [registry.json](../../registry.json) 为三个技能分别登记源子路径，并将技能本体放在标准 `skills/<name>/` 目录。包根的许可证、资料说明、统一验证入口仍保留在 `vendor/ip-practice-workbench-skills`。三个技能保留原技术 ID。

各技能目录按自身上游子路径同步，包根许可证、数据说明和统一验证入口则在 `vendor/ip-practice-workbench-skills` 保留快照。技能本体是 vendored 来源，不作为 myskill 自研副本；本文件记录集成方式，上游变更记录随技能目录保留。

同步方向是双向的：上游更新由现有定时/手动同步工作流带入 myskill；myskill 的三个技能目录进入 `main` 后，由 [反向同步工作流](../../.github/workflows/sync-ip-practice-skills-back.yml) 为各自源子目录创建或更新 PR，不会自动合并。要启用反向工作流，需先在 `zhjnerv/myskill` 仓库配置 Actions secret `IP_PRACTICE_WORKBENCH_TOKEN`，值为仅对 `zhjnerv/ip-practice-workbench-skills` 有 Contents（读写）和 Pull requests（读写）权限的 fine-grained token。当前 GitHub Actions secrets 尚未配置该 secret；配置前工作流会明确失败，不会静默丢弃修改。

## 日常操作

在独立仓库修改、验证并发布后，在干净的 myskill 工作区按技能名同步：

```powershell
.\scripts\skill-sync.ps1 -Name cn-patent-fast-track-screener
.\scripts\skill-status.ps1 -Name cn-patent-fast-track-screener
```

`fork` 与 `upstream` 都指向本人的公开仓库，不需要另建 fork。同步单位是单个技能目录；可对 `cn-office-action-prior-art-collector` 和 `cn-trademark-goods-services-recommender` 使用相同命令。三个技能都保留原始目录结构及其运行资源。

按单个技能安装到 Agent：

```powershell
.\scripts\skill-deploy.ps1 -Name cn-patent-fast-track-screener
.\scripts\skill-deploy.ps1 -Name cn-office-action-prior-art-collector -TargetRoot "$env:USERPROFILE\.codex\skills"
.\scripts\skill-deploy.ps1 -Name cn-trademark-goods-services-recommender
```

三个技能位于标准 `skills/<name>/` 目录，可由常规技能安装器直接发现，也可按技能名部署。源仓库 PR 合并后，现有上游同步工作流会把更新带回 myskill；myskill 的本地提交推到 `main` 后则自动创建源仓库 PR。完整源包还保留统一验证脚本，可从 myskill 根目录运行 `python -B -S -X utf8 vendor/ip-practice-workbench-skills/scripts/verify.py`。

## 保留的经验

- 展示名称可随品牌调整，技术 ID 保持稳定；审查意见技能只处理材料准备。
- 从 Git 受控快照引入，不复制个人计划、缓存或整个业务工作区。
- 跨平台路径测试使用 Path 比较；不把分隔符差异误判成业务错误。
- 数据实际来源和再分发依据与原创代码的 MIT 分别记录。原迁入记录曾提到移除来源字段；这不能代替来源核实，后续以包内 DATA_SOURCES、NOTICE 的待核事项为准。
- vendored 登记需要真实 subtree 基线与对应 tree 哈希；只改 `origin` 字段不能建立可持续同步关系。

## 本次接回

版本为 `1e1042385522145b167ba8931f1a5a4bd591b532`，包 tree 为 `c6600b396b542a3726c2d9ec607d0f4406771291`。采用整个仓库以保留根许可、品牌说明和统一验证入口；不再逐技能维护重复来源。

隔离验收：73 项技能测试、551 份 JSON 解析及商标数据校验通过；5 项 Windows 实际部署回归、1 项 subtree 连续同步回归通过。包内文件与独立仓库 tree 一致。部署按技能名查找及 `-DryRun` 不写安装目录的行为已覆盖；实际联网文献下载和 Agent 运行未在本次测试。
