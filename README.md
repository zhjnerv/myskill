# 知产实务工作台 · 实务技能

**IP Practice Workbench Skills** — 面向专利代理人、商标代理人、代理机构案件处理人员和企业知产人员的独立技能集合。

把知产实务中的分类检索、加快路径初筛和审查材料整理，做成可以交给 Agent 调用、也可以直接运行的工具。每个技能自带脚本、参考资料、测试及所需资源，核心脚本使用 Python 标准库。

本仓库沿用“知产实务工作台”的名称和场景术语，是三个实务场景的技能实现。技能与线上服务各自维护；完整的审查意见答复流程和复审策略分析不在本仓库范围内。

## 三个实务场景

| 场景 | Skill | 处理内容 |
| --- | --- | --- |
| 商标分类检索 | [cn-trademark-goods-services-recommender](skills/cn-trademark-goods-services-recommender/README.md) | 从业务描述定位大类、类似群与商品服务项，校验选择并导出申报表 |
| 加快程序初筛 | [cn-patent-fast-track-screener](skills/cn-patent-fast-track-screener/README.md) | 根据技术方案、申请主体所在地和 IPC 分类，提供预审或优先审查路径线索 |
| 审查意见答复 · 材料准备 | [cn-office-action-prior-art-collector](skills/cn-office-action-prior-art-collector/README.md) | 解析通知书、整理文献号，收集公开文本与对比文件；不生成答复策略或意见陈述书 |

场景顺序与门户一致。英文目录名和 `SKILL.md` 的 `name` 保持稳定，供安装和工具调用使用；[品牌与能力映射](docs/brand.md) 记录展示名称及能力边界。

## 快速使用

准备 Python 3.12（本次实际验证版本），下载或克隆本仓库后，在仓库根目录运行：

```bash
# 商标分类检索：按关键词检索商品、服务项目
python skills/cn-trademark-goods-services-recommender/scripts/search_items.py "宠物自动喂食器"

# 加快程序初筛：根据所在地与候选 IPC 生成路径线索
python skills/cn-patent-fast-track-screener/scripts/screen.py --province "浙江省" --city "杭州市" --primary-ipc "G06N 3/08"

# 审查材料准备：生成取材候选链接，本例不下载文件
python skills/cn-office-action-prior-art-collector/scripts/fetch_patent_documents.py --dry-run "CN114528944A"
```

各技能 README 包含更完整的调用示例。通知书解析可选使用 PyMuPDF 增强复杂 PDF 的文本提取；未安装时使用内置解析器。在线文献取材需要网络，扫描件可能需要 Agent 进一步读取。

## 安装到 Agent

把所需的 `skills/<技能名>/` **整个目录**放进 Agent 的技能目录，保留 `SKILL.md`、脚本、资源、`LICENSE` 和 `NOTICE.md`。三个技能可以分别安装；不要只复制入口文档。目标 Agent 的具体加载和启用方式以其自身说明为准。

Windows 下也可把技能目录作为目录联接的源，让安装入口随本仓库更新。例如，在确认目标位置尚不存在后：

```powershell
$skillSource = (Resolve-Path '.\skills\cn-patent-fast-track-screener').Path
$agentSkills = '请替换为你的 Agent 技能目录'
New-Item -ItemType Junction -Path (Join-Path $agentSkills 'cn-patent-fast-track-screener') -Target $skillSource
```

## 验证与维护

```bash
python -B -S -X utf8 scripts/verify.py
```

该命令在各技能目录运行现有测试，校验商标数据、JSON、评测附件、文档内部链接及三个技能的入口名称。它不调用付费服务，不执行实际联网下载。

- [贡献说明](CONTRIBUTING.md)：修改、验证和提交流程。
- [数据来源与许可范围](DATA_SOURCES.md)：随包资料的来源记录及待核事项。
- [迁移与验收记录](docs/migration.md)：独立仓库建立过程和验证边界。
- [公开发布准备](docs/release.md)：当前本地候选与后续发布步骤。
- [更新记录](CHANGELOG.md)：仓库级变更。

## 线上工作台

下列地址来自配套产品门户的配置，线上服务的能力、版本和访问规则以各入口说明为准：

- [知产实务工作台](https://patent.zhjwork.online/)
- [商标分类检索](https://tm.zhjwork.online/)
- [加快程序初筛](https://ysys.zhjwork.online/)
- [审查意见答复](https://scyj.zhjwork.online/)

## 使用边界与许可证

本项目辅助材料整理、分类检索和前置判断。涉及法律适用、创造性、商标显著性及程序风险的判断，仍需专业人员结合具体案件完成；工具不承诺授权、加快、复审或商标注册结果。

原创代码和文档采用 [MIT License](LICENSE)。随包数据、模板和第三方内容的来源及权利范围单列于 [DATA_SOURCES.md](DATA_SOURCES.md) 和各技能的 `NOTICE.md`，不能仅由本仓库的 MIT 声明推定其再分发许可。
