# Claude Patent Creator CN

面向中国发明专利申请的 Codex Skill 工作流。项目以 `cn-patent-workflow` 为唯一总入口，按阶段加载六个专业子 Skill、本地中国法源和确定性校验脚本，完成检索准备、起草、附图、审查及 DOCX 交付。

本仓库不包含美国 MPEP RAG、向量索引、Embedding、PyTorch 或主 MCP Server，也不把脚本输出冒充专利代理师的实体法律判断。

## 一键安装到 Codex

从仓库根目录执行：

```bash
python3 scripts/install_codex_skill.py
```

安装器会：

1. 将完整运行时复制到 `${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn`；
2. 在运行时创建 `.venv`，安装 DOCX 所需依赖并执行包边界检查；
3. 将七个 Skill 链接或复制到 `${CODEX_HOME:-$HOME/.codex}/skills/`；
4. 写入 `codex-install.json`，记录运行根目录、入口 Skill 和依赖状态。

已有安装需要更新时：

```bash
python3 scripts/install_codex_skill.py --force
```

需要同时安装测试依赖：

```bash
python3 scripts/install_codex_skill.py --force --with-dev
```

安装完成后重新启动 Codex，在新会话中调用：

```text
$cn-patent-workflow
```

例如：

```text
$cn-patent-workflow 根据当前代码仓库起草一套中国发明专利申请文件，并完成附图、综合审查和 DOCX 交付。
```

`cn-patent-workflow` 只负责阶段判断和交接。它确定当前阶段后读取对应子 Skill 的 `SKILL.md`，完成后再回到总入口判断下一阶段；不会一次性把全部法源和全部规则塞入上下文。

## Skill 组成与职责

| Skill | 作用 | 主要输入 | 主要输出 |
|---|---|---|---|
| `cn-patent-workflow` | 唯一总入口，负责阶段路由、根目录解析、失效传播和子 Skill 交接 | 用户任务、当前案件目录 | 当前阶段决策、子 Skill 调用链 |
| `cn-patent-application-creator` | 发明挖掘、检索式、范本选择、区别特征台账、权利要求架构、四文书起草和 DOCX 组装 | 技术交底、代码、检索与范本材料 | 权利要求书、说明书、摘要、附图索引及过程合同 |
| `cn-patent-claims-analyzer` | 权利要求编号、引用、多项从属、分项字数上限（权利要求 1≤400、权利要求 2≤500、其余≤600）、权利要求 2 核心从属落位、草稿残留和有限术语线索检查 | 权利要求文本 | `cn-patent-review-raw-report/v2` |
| `cn-patent-specification-reviewer` | 定位说明书对权利要求特征的文本证据，并组织充分公开、支持和功能性限定的人工语义复核 | 说明书、权利要求特征 | 支持矩阵、说明书专项报告 |
| `cn-patent-formalities-reviewer` | 文件组成、标题、摘要字数、章节、图号、附图标记及条件性程序事项检查 | 申请文件 manifest | 形式专项报告 |
| `cn-patent-reviewer` | 编排三类原始检查器和独立语义审查，冻结输入、规则及前置流程证据 | 四文书、manifest、provenance 工件 | review bundle、整改顺序、独立验证报告 |
| `cn-patent-diagram-generator` | 分析用户修改范例，提取紧凑布局并从原始母版安全重建，再把 drawing brief v4 转成可编辑 Draw.io 附图，完成图文一致性、白边及DOCX交付绑定验收 | drawing brief、说明书、台账、架构合同；可选原图与用户范例 | style brief、安全重建报告、`.drawio`、PNG、视觉复核、附图验证及DOCX交付验证 |

各 Skill 的名称均使用 Codex 要求的全小写 hyphen-case，`SKILL.md` frontmatter 已通过 Codex Skill 校验器。

## 完整执行流程

```text
技术材料或代码
      │
      ▼
[1] 发明挖掘与技术特征结构化
      │ technical-features.json
      ▼
[2] 检索式、目标 IPC、候选范本与用户确认
      │ search-query / template-selection / stage2-gate
      ▼
[3] 区别特征台账与权利要求优先起草
      │ feature-ledger v2
      ▼
[4] 数据流、方法—系统覆盖、异常出口复算
      │
      ▼
[5] 权利要求架构门
      │ 载体分工 / 父从权继承拓扑 / 方法步骤边界
      ▼
[6] 说明书、摘要与附图说明起草
      │
      ▼
[7] 可选用户范例差异分析 → style brief v1 → 原始母版安全重建 → drawing brief v4 → Draw.io 附图 → 视觉与图文一致性验收
      │
      ▼
[8] 权利要求 / 说明书 / 形式原始检查
      │
      ▼
[9] 独立语义审查 → review bundle → verifier
      │
      ▼
[10] 可选 DOCX 组装 → 原生 OMML 公式 → 哈希新鲜度复验 → 附图—DOCX交付绑定验证
```

阶段之间只通过版本化 JSON、申请文件和哈希报告交接。权利要求、说明书、台账或图片发生变化时，下游架构、附图、综合审查和 DOCX 证据按 `skills/cn-patent-workflow/references/stage-map.md` 失效并重跑。

## Linux 下的 Word 原生公式

DOCX 公式不再依赖 Windows COM，也不再要求先用 Microsoft Word 执行 `OMaths.Add/BuildUp`。

组装器现在直接生成 Office Math Markup Language：

```xml
<m:oMath>
  <m:f>...</m:f>
  <m:sSub>...</m:sSub>
  <m:sSup>...</m:sSup>
</m:oMath>
```

因此在 Linux、macOS 和 Windows 上均可生成可编辑的 Word 原生公式，支持当前申请文件使用的：

- 行内和独立公式；
- 上标、下标及上下标组合；
- 分式；
- 圆括号、方括号和花括号；
- 函数调用、等式和常用运算符。

默认 DOCX 交付只执行 ZIP/XML、分节、页眉、样式、`m:oMath` 对象和图片数量检查，不导出 PDF/PNG。

用户明确要求视觉检查时：

- Windows：使用 Microsoft Word 导出 PDF；
- Linux/macOS：使用 LibreOffice headless 导出 PDF；
- 两个平台均使用 `pdftoppm` 渲染逐页 PNG，并使用 `pdfinfo` 核对页数。

Microsoft Word 只影响 Windows 下的分页和 PDF 渲染，不再是生成原生公式的必要条件。

## DOCX 输入模板

DOCX 组装默认使用仓库根目录的 `模版.docx`。该模板包含五个分节及相应页眉，并提供权利要求自动编号、`Normal (Web)`、`Title`、`Heading 1`、`正文2`、`附图图号` 和 `Strong` 样式。案件目录里的 `输出模版.docx` 不会自动接管；只有显式传入 `--template` 才替换项目模板。

具体合同见：

```text
skills/cn-patent-application-creator/references/docx-assembly.md
```

## 运行依赖

基础起草与审查脚本只使用 Python 标准库。安装器默认增加：

- `python-docx`；
- `lxml`；
- `Pillow`；
- Windows 平台上的 `pywin32`。

按需外部能力：

- Draw.io Desktop CLI 和 `drawio-skill`：生成及导出附图；
- LibreOffice：Linux/macOS 视觉复核 PDF；
- Poppler 的 `pdftoppm`、`pdfinfo`：逐页渲染及页数核对；
- EPO OPS provider：自动补全候选专利 IPC；缺失时只能使用有来源的缓存或候选输入。

## 开发环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,docx]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_package.py
```

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,docx]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_package.py
```

## 其他安装形态

仓库同时保留 `.codex-plugin/plugin.json`，可作为 skills-only Codex Plugin 加入本地 Marketplace。默认推荐文件系统 Skill 模式，因为它允许 `$cn-patent-workflow` 作为单一入口逐阶段调用全部子 Skill。

本项目不提供业务型 Slash Command。自然语言请求由 Skill description 或显式 `$cn-patent-workflow` 触发，确定性步骤由各 Skill 自带脚本执行。

## 附图术语约定

项目对附图中的节点、外框、文字、关系边、原生关系标签、端口、路由点和间距使用统一称呼。完整术语表见：

```text
skills/cn-patent-diagram-generator/references/drawing-terminology.md
```

讨论“方框中的文字”时，整体称为“节点”，内部文字称为“节点文字”；讨论“箭头线上的文字”时，称为“原生关系标签”。“独立文本节点”专指脱离关系边的浮动文字对象，不得用于模拟关系标签。

## 质量边界

- 中国法规则绑定 `references/cn-legal-sources/` 中的本地法源；
- 客观约束由脚本和 JSON 合同判定，语义判断不伪装成确定性结论；
- 形式或结构检查通过不等于申请具备新颖性、创造性或可授权性；
- DOCX 结构检查通过不等于已经完成逐页视觉复核；
- 权利要求分项字数上限：权利要求 1 不超过 400 字、权利要求 2 不超过 500 字、其余各项不超过 600 字（Word 中文字数口径，公式整体计 1）；三者均为上限而非目标。最核心的保护点放在直接且仅引用权利要求 1 的权利要求 2，并在 `cn-patent-claim-architecture/v1` 的 `core_protection_point` 登记并复核。
- 附图节点必须通过 A4 归一化字号、每行最多12个汉字的显式换行、外框不超过文字块高度2倍和文本容量检查；直接上下相连节点扣除原生关系标签和一个箭头头部后的有效空白必须处于相邻节点较小字体行高的2倍至3倍之间。
- 圆柱型节点只用于明确的存储/记录对象；原生关系标签字号不小于相邻节点字号的三分之二，纵向标签上下各至少保留一个箭头头部高度。
- 用户修改的 Draw.io 范例只传递紧凑布局和视觉规则；正式图须从原始母版安全重建，恢复真实关系端点和原生线条文字，禁止传播手工断连、自连接或独立标签。
- 新案件使用 `cn-patent-feature-ledger/v2`、`cn-patent-claim-architecture/v1`、`cn-patent-drawing-brief/v4` 和 `cn-patent-drawing-visual-review/v2`；存在用户范例时增加已批准的 `cn-patent-drawing-style-brief/v1`。
- 区别特征按六种形态（耦合/时序条件/绑定/参数配比/反默认/失败驱动）发现并通过抽象层级测试；权 1 攻防按换特征→重述问题→降层级→加特征顺序，不得直接加字。
- 进入撰写后流程不因判断题停止：检索/范本/IPC/复核/公知常识等待决事项按保守默认继续并写入 `cn-patent-pending-decisions/v1` 与《待决事项清单.md》，审稿版 DOCX 以 `【待决-Dnnn】` 黄色高亮标出，提交副本机械剥离；只有产物无效或不安全的门保留硬阻断。
- 创造性防御地图 `cn-patent-inventive-step-map/v1`：区别特征 × 对比文件（含公知常识虚拟条目）矩阵，复算凑齐全部区别特征所需最少对比文件数、作用一致性与说明书可定位的耦合证据，按 novelty_risk / weak / defensible 分级；权 1 允许 weak，权 1+2 须 defensible，核心保护点须为最小 defensible 特征集。
