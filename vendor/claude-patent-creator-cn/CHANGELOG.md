# Changelog

## Unreleased

- 最终专利申请 DOCX 默认使用仓库根目录 `模版.docx`。组装器解析该模板的编号样式链接，方法步骤采用模板正文示范的第 2 层；案件目录中的 `输出模版.docx` 不再自动接管，只有显式 `--template` 才替换。
- 建档范本主体名单：`references/notable-entities.txt` 代理机构部分补实，Tier 1 共 18 条（含同一机构的不同著录写法）、Tier 2 共 27 条，依据 2025 年发明授权量百强榜、润桐 RainPat 申请量/授权率榜、IPRDB 综合榜、Chambers 中国 IP、北京市专利代理师协会 5A 等级评定、IPRdaily×incoPat 百人以上代理机构榜等公开榜单；文件内登记来源、建档日期与偏差说明。
- 范本选取改为四因子加权：技术相关性 0.30 + IPC 相似度 0.20 + 申请人质量 0.25 + 代理机构质量 0.25（`cn-patent-template-selection/v2`）。主体质量按 `references/notable-entities.txt` 名单分层（Tier 1 = 1.00、Tier 2 = 0.70、未上榜 = 0.30、未著录 = 0.00 并标 `missing`）。候选清单新增 `applicant`/`agency`；四项权重须同时给出且和为 1，技术相关性与 IPC 保持正权重；阶段门复算四项加权、校验主体著录与候选清单一一致（`GATE-IPC-014`），选定范本缺主体著录时产生待决项（`GATE-IPC-015`）；v1 选择合同移入 `references/legacy/`。

## [0.3.0] - 2026-09-23

- skill-lint 正式验收整改：分发树与复盘文档移除真实案件示例并改为虚构中性示例；附图 Skill 对 `drawio-skill` 的引用加外部前缀；起草 SKILL.md 阶段 2-A 范本 pending 措辞与待决语义对齐；claims-analyzer 文档输出 schema 名改为 `cn-patent-review-raw-report/v2`，description 补齐触发/不触发边界；formalities 退出码句补法律免责。
- 起草 SKILL.md 收敛：运行根目录改为一次定义的 `$ROOT`；说明书输出格式下沉到 `references/specification-output-format.md`，DOCX 组装门禁并入 `references/docx-assembly.md`；v1 历史 schema 移至 `references/legacy/` 与 `legacy-*` 文件名；开发用脚本移入 `tests/`。
- 综合审查器 `finalize` 对语义审查输入顶层字段执行 `exact_fields.review_input` 白名单，多出或缺少字段退出码 3。
- 附图稳定性合同正向夹具升级为 `cn-patent-drawing-verification/v4` 形状；为关系标签字号、节点文字适配、纵向间距、PNG 白边四条约束新增合法近似正例；新增遍历全部合同用例复算退出码的回归测试。
- stage-map 登记 `cn-patent-inventive-step-map/v1`、`cn-patent-pending-decisions/v1` 与 `CLEARED_WITH_PENDING` 交接；权利要求规则矩阵与跨文档规则标注产出者。

- 新增待决事项机制 `cn-patent-pending-decisions/v1`：阶段门（检索/范本/IPC 缺用户原话）、台账（未检索/缺效果/表述抽象）、架构门（简要性与核心保护点复核未批准）、附图（视觉复核与样式简报未批准）等判断题门不再阻断，改为保守默认 + `pending_decisions` + 继续；`collect_pending_decisions.py` 汇总为 JSON 与《待决事项清单.md》；DOCX 组装新增 `--copy review|submission`，审稿版对 `【待决-Dnnn】` 段落黄色高亮，提交副本剥离标记并由 `DOCX-PENDING-MARKS` 复核。产物有效性门（哈希、编号、引用、DOCX 结构）保持硬阻断。
- 实现创造性防御地图 `cn-patent-inventive-step-map/v1`（schema、`validate_inventive_step_map.py`、参考文档）：特征 × 对比文件矩阵含 `COMMON_KNOWLEDGE` 虚拟条目；最小集合覆盖复算、显式优先级分级、耦合须有说明书逐字锚点且无单篇同时覆盖；claim_set 由权利要求自动推导（每个独权及其直接从属项各自成组）；partial 不计覆盖但过半提示，公知常识 medium 与未检索特征按最坏情况参与分级并写入待决；核心保护点须为最小 defensible 特征集之一。
- 台账构建器新增 `CN-LEDGER-ABSTRACT-001`（区别特征表述缺少条件/位置/参数/绑定/时序限定时提示复核，判句法结构不判词表）；`CN-LEDGER-PRIOR-002` 升级为阻断。新增创造性防御地图 `cn-patent-inventive-step-map/v1` 设计稿（`docs/process-improvements/2026-09-22-inventive-step-map/`，待实现）。
- 新增区别特征形态清单（`references/distinguishing-feature-patterns.md`）与抽象层级测试；阶段 1 和 2-C 按六种形态发现区别特征，2-C 增加"争议地带"第三态；权利要求 1 增加句法规则与起草期删除测试；阶段 5a 攻击响应改为换特征→重述问题→降层级→加特征强制顺序，向权 1 加字须书面说明。

- 新增权利要求分项字数上限与核心保护点落位门：权利要求 1 ≤400 字（`CN-CLAIM-LENGTH-002`）、权利要求 2 ≤500 字（`CN-CLAIM-LENGTH-003`），其余各项沿用 600 字（`CN-CLAIM-LENGTH-001`），三者均为上限而非目标；`CN-CLAIM-CORE-001` 检查权利要求 2 直接且仅引用权利要求 1；`cn-patent-claim-architecture/v1` 新增必填 `core_protection_point`，登记权利要求 2 承载的核心区别特征并要求复核批准。
- 公式规范化支持常见 LaTeX 符号宏和函数名宏按最长匹配转为 Unicode/普通名称；`\frac`、`\sqrt`、`\text`、修饰宏及 `\_` 等不支持项 fail-closed 报错，不再把反斜杠静默写入 Word 公式。
- 关闭状态审计 F01—F11 的工程缺口：起草报告防输入/输出别名覆盖；引用区间完整有界展开；交付时独立复算当前 DOCX、Draw.io 和 PNG；保留母版箭头与命名形状，绑定真假分支及完整节点文字。
- DOCX 步骤编号按模板实际层级选择，最终 ZIP/XML 编号引用由当前编号定义复算；相对证据路径按组装报告目录解析。合成 DOCX 的 PDF 渲染测试改为显式授权后运行，默认回归不导出。
- 安装器增加运行时与七个入口的统一事务、SIGTERM 回滚和启动恢复；安装与包检查共用源文件分发策略，阻断嵌套本地归档和未经审核的二进制产物。此修复不包含发布或全局安装。

- 收紧附图形状与关系标签门禁：圆柱型节点仅用于明确存储/记录语义；原生关系标签字号不小于相邻节点字号的三分之二，纵向标签上下各保留至少一个箭头头部高度。
- 新增中国专利 Draw.io 附图统一术语表，明确节点、节点外框、节点文字、独立文本节点、关系边、原生关系标签、端口、路由点和有效空白高度的统一称呼。
- 新增用户修改附图安全重建：提取紧凑布局指标，同时从原始母版恢复关系ID、source/target和原生线条文字，自动剔除绝对端点、自连接、独立标签和额外关系。
- DOCX 组装新增说明书与权利要求版式门禁：移除说明书段落号、方法步骤分段、附图说明一图一句，并要求“实施例1。”及实施例逐图引用。
- 附图交付链路移除 SVG 过程文件，只保留可编辑 `.drawio` 母版、预览 PNG 和最终 PNG。
- 关系说明、分支条件和数据流名称改用 Draw.io 原生 edge label，禁止以独立文本框模拟线条文字。
- 收紧节点文字适配门禁：节点每个可见行最多12个汉字，外框高度不得超过实际文字块高度的2倍，并继续检查A4归一化字号和文本容量。
- 调整纵向间距门禁：直接上下相连节点扣除原生关系标签和一个箭头头部后的有效空白，必须处于相邻节点较小字体行高的2倍至3倍之间。
- Draw.io PNG 改为按实际图形边界导出，移除整页导出产生的大面积无意义白边。
- 新增用户范例差异分析器与 `cn-patent-drawing-style-brief/v1`，分离技术变化、视觉变化和Draw.io编辑副作用。
- 新增PNG白边像素门禁和附图—DOCX最终交付验证器，确保当前最终PNG实际嵌入当前DOCX。
- 范本权利要求分析支持“如/按照权利要求”及“1-3”“1至3”等从属引用写法。
- 阶段门接受“同意”“是”等非空简短用户原话，不再以字符数否定有效授权。
- 包边界检查跳过根级本地案件归档、虚拟环境和生成元数据目录；分发树内部的本地归档目录必须阻断，且不读取其中客户材料。

- 新增 `CN-CLAIM-LENGTH-001`：每项权利要求按 Word 中文字数口径不得超过 600 字，完整公式或特殊公式变量整体计 1。
- 将新案件技术台账升级为 `cn-patent-feature-ledger/v2`，增加数据流、动作阶段、方法—系统覆盖和异常终态复算。
- 新增 `cn-patent-claim-architecture/v1`，把独权载体分工、父从权继承拓扑和方法步骤边界变为强制起草门。
- 新增 `cn-patent-drawing-brief/v4`，方法流程图强制绑定权利要求架构合同，并复算步骤、判断节点和循环返回点同构。
- 新增 `cn-patent-drawing-brief/v3` 与 `cn-patent-drawing-visual-review/v2`，绑定单图阅读合同、图文表达范围和最终 PNG 观察证据。
- DOCX 组装报告升级为 v2，并新增输入/输出哈希新鲜度验证器。
- 修复包边界检查误扫 `.git` 内部备份的问题。
- 综合审查链增加可选 `provenance_artifacts`，将检索、范本选择、阶段门、特征台账和权利要求架构纳入独立的来源哈希绑定与新鲜度校验。

## [0.2.0] - 2026-09-06

### Added

- 新增 `scripts/install_codex_skill.py`，一条命令把完整运行时、虚拟环境和七个 Codex 文件系统 Skill 安装到 `${CODEX_HOME:-$HOME/.codex}`。
- `cn-patent-workflow` 成为统一入口，按阶段读取并调用六个专业子 Skill。
- DOCX 组装器直接生成可编辑 OMML 原生公式，Linux/macOS 不再依赖 Microsoft Word COM；视觉检查使用 LibreOffice 导出 PDF。

### Changed

- 所有 Skill 名称统一为 Codex 校验要求的全小写 hyphen-case。
- 修复 setuptools 自动包发现，使 `pip install -e '.[dev,docx]'` 可直接安装开发环境。
- README 重写为安装、Skill 职责、完整流程、失效传播和跨平台 DOCX 说明。

## [0.1.0] - 2026-08-29

### Added

- 从 `Claude-Patent-Creator` 独立出中国专利起草、审查、附图、DOCX 和本地法源能力。
- 新增轻量 `cn-patent-workflow` 总入口，按阶段调用既有中国专利 Skill。
- 新增独立包边界检查，禁止引入主项目 MCP、MPEP RAG、向量索引和 GPU 依赖。
