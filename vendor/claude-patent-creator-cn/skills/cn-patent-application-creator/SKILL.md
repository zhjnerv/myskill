---
name: cn-patent-application-creator
description: 本技能应在生成中国发明专利申请文件时使用——从代码库、技术交底书或零散材料出发，完成发明挖掘、检索式生成与 CNIPA 人工检索留档、可选范本风格学习、权利要求优先撰写、说明书法定格式输出、复用 -CN 审查链验证、攻击演练、提交包组装，以及按用户提供的 Word 模板把四文书合并为含原生公式和附图的单一 DOCX；也用于在没有方案通过检索时给出有证据支撑的放弃结论。不要用于：美国临时申请、PCT 国际申请或其他辖区申请文件的起草，也不要用于复制范本技术内容、替代专利代理师判断或输出"可申报""必获授权"结论。
allowed-tools: Bash, Read, Write
---

# 中国发明专利申请文件创作技能

执行一次完整的专利战役：把用户手里的任何材料——代码库、技术交底书、零散笔记——要么变成一份可交专利代理师复核的中国发明专利申请文件包，要么变成一份有理由、有证据支撑的"为什么不申请"的说明。

本技能是 `patent-application-creator-ZH` 的中国辖区版本。战役骨架（挖掘 → 检索 → 权利要求优先 → 机器验证 → 两支红队 → 打包）沿用，但法律武器全部换成中国专利法、实施细则和审查指南；美国特有的临时申请、宽限期、IDS、微实体等内容一律不适用。

## 运行根目录（执行任何命令前先定义一次）

本文所有命令与路径以 `$ROOT` 指代运行根目录；在每个会话第一次执行命令前定义：

```bash
ROOT="${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}"
```

解析顺序与 `cn-patent-workflow` 一致：`CN_PATENT_CREATOR_ROOT` → `CLAUDE_PATENT_CREATOR_CN_ROOT` → `CLAUDE_PLUGIN_ROOT` → Codex 一键安装目录。`$ROOT` 下必须同时存在 `.codex-plugin/plugin.json`、`skills/` 和 `references/cn-legal-sources/source-index.json`，否则停止并报告，不得猜测路径。

## 共享本地法源（执行前读取）

涉及中国专利法律规则、条款或审查方法时，优先读取仓库内的统一法源，不再为已收录内容默认联网搜索：

- 法源先读取 `$ROOT/references/cn-legal-sources/source-index.json`，再按主题读取分章；不得默认加载 `guide-full.md`。
- 专利法：`$ROOT/references/cn-legal-sources/专利法(2020-10-17).md`
- 专利法实施细则：`$ROOT/references/cn-legal-sources/专利法实施细则(2023-12-21).md`
- 审查指南全文：`$ROOT/references/cn-legal-sources/审查指南2026MD/guide-full.md`
- 审查指南分章：`$ROOT/references/cn-legal-sources/审查指南2026MD/chapters/`
- 统一法源目录：`$ROOT/skills/cn-patent-reviewer/references/cn-source-catalog.md`

本地文本用于条款和章节目定位。只有核对后续修订、施行状态，或处理本地文本缺失与冲突时才联网，并优先使用 CNIPA 官方来源。

## 与美国流程的关键差异（动手前先读完这一节）

中国辖区特有：没有临时申请、宽限期、IDS 和微实体；实审请求与优先权有法定时限；说明书必须支持权利要求、修改不得超范围；交付四份技术文书，可选合并为单一 DOCX。逐条对照与常见误植见 `references/us-cn-differences.md`。
## 契约

- **诚实的结果就是交付物。** "以下现有技术足以击毙每个候选方案"是成功，不是失败。"这项可能授权但不值得你花这笔钱和三年时间——不申请，或者做防御性公开"同样是成功。绝不夸大一个孱弱的候选方案。
- **战役守护的是用户的钱，不只是他们的申请。** 值不值得做的问题必须在昂贵阶段之前提出，并且每当权利要求收窄时重新提出。一个只在最后才发现"篱笆很小"的战役，已经把预算花在了回答错误的问题上。
- **机器检查把关，人工验证。** 每一项被标记为低置信度的自动发现都必须人工核实；每一份"全部通过"的健康证明都必须列出运行过的检查和被跳过的检查。
- **中国是先申请制。** 同样的发明谁先申请归谁（专利法第九条）。但这条紧迫性只对**尚未发生**的第三方公开有意义——已经公开的现有技术永远无法被甩在后面。
- **发明人必须是自然人。** AI 不是发明人，用户才是。AI 负责挖掘、检索、撰写和验证。
- **本技能不输出授权前景。** 形式与结构检查通过不代表实体条件通过，任何交付物都是 `ADVISORY_ONLY`，最终必须经专利代理师复核。

## 阶段 0——受理与法定日期审计

原样接受粗略的请求。如果材料是代码库，不要索要交底书——挖掘是阶段 1 的工作。本技能的交付范围固定为权利要求书、说明书、说明书摘要和说明书附图四类技术文书，申请人、发明人、联系电话、地址、联系人及代理机构等请求书主体字段不作为起草输入，也不得阻断四文书生成。只问无法从材料推导且会影响技术文书合法性的日期事实：

1. 该技术是否已经公开、销售、展出、发表或交付第三方，以及最早发生日期；
2. 是否存在可主张优先权的在先申请（专利法第二十九条、第三十条；实施细则第三十四条至第三十七条）。

然后审计申请人自身的公开足迹——已发布产品、演示、公开仓库、营销页面、论文、招标文件——并记录首次公开日。**这一步在中国的分量远大于美国**：专利法第二十四条的宽限期只覆盖四种情形（为公共利益目的在紧急状态或非常情况下首次公开、在中国政府主办或承认的国际展览会上首次展出、在规定的学术会议或技术会议上首次发表、他人未经申请人同意泄露），各为 6 个月，且需按实施细则第三十三条声明并提交证明。**自己把产品上线、把仓库开源、把方案写进公开文档，都不在这四种之内**，公开之日该方案在中国即丧失新颖性。

审计结论若为"核心机制已公开且不属于第二十四条情形"，直接写放弃报告并停止。那份报告就是交付物。

## 阶段 1——发明挖掘

寻找具体的**技术机制**，而不是功能或特性。对于代码库，分派多个阅读者（每个子系统一个），候选方案必须（a）具体且已实现，（b）解决一个技术问题，（c）能落入 `references/distinguishing-feature-patterns.md` 六种形态之一，并且能说出它偏离了什么默认做法。为每个候选方案记录：机制（怎么做，而不是做什么）、证据位置、解决的技术问题、被击败的常规替代方案、这个差异为什么非显而易见。候选创新点在 2-C 检索定出 D1 之前只是**假设**，区别特征只能相对 D1 定义。

然后用以下筛查分类（杀掉／继续）：

- **客体筛查**（专利法第二条第二款、第二十五条；指南第二部分第一章、第九章）。纯商业规则、纯算法、纯数学方法、纯管理流程会被以"智力活动的规则和方法"驳回。判据是能否写出完整的三要素：**技术问题—技术手段—技术效果**。手段必须是遵循自然规律的技术手段（对内部性能的改进、对硬件/数据处理过程的改造），效果必须是技术效果而非商业效果。写不出三要素的候选方案降级或杀掉。涉及计算机程序的方案按指南第二部分第九章第 2、5、6 节组织撰写。
- **拥挤领域筛查**：本领域手册、标准或框架已有成熟通用做法的领域——拥挤领域不杀，但区别特征必须是耦合/时序条件/绑定/参数配比/反默认/失败驱动型，且通过抽象层级测试；机制名称本身不得作为依赖的区别特征。
- **单一性筛查**（专利法第三十一条第一款；实施细则第三十九条；指南第二部分第六章）：寻找一个被多个候选方案实例化的总的发明构思，各方案之间必须存在相同或相应的**特定技术特征**。凑不到一个构思下的，就是两件申请，不要硬塞。
- **值不值得做**：授权后能不能发现侵权（可检测性）？竞争者绕开的成本有多大？三年审查周期结束时这项技术还在不在用？

## 阶段 1-H——历史挖掘（当原始材料是 git 仓库时）

原始材料是 git 仓库时，按 `references/history-mining.md` 的时间线方法挖掘散落方案、识别已被后续提交推翻的旧思路，并落成候选清单；非仓库材料跳过本阶段。
## 阶段 2——现有技术：每一个出口，对抗性地

### 2-A：生成检索清单并人工筛选范本

先把阶段 1 的幸存方案整理成 UTF-8 JSON。**查找范本之前必须先人工判断目标 IPC 并显式写入 `ipc_codes`**；自动领域映射只能作建议。

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/generate_search_query.py" \
  --features "<technical-features.json>" \
  --output "<search-query.json>"
```

**检索渠道优先级：① 度衍命令检索（uyanip.com，首选）→ ② CNIPA 专利检索及分析系统人工检索 → ③ Google Patents / BigQuery（补充验证）**；检索式构造与鼠标操作要点见 `docs/uyanip-command-search-sop.md`。

`search-query.json` 固定输出 `cn-patent-template-search/v1`，含 `uyanip_plan`（现成检索式 + 结果页直开 URL）、`target_ipc` 判定状态、BigQuery SQL 与 CNIPA 人工检索清单；`target_ipc.status` 仅在显式提供 `ipc_codes` 时为 `determined`，否则不得进入范本排序。

形成 1—10 篇 `cn-patent-template-candidates/v1` 候选，优先同领域、已授权、权利要求不少于 10 项、说明书和附图完整，逐篇给出 `technical_relevance_score` 与理由，并**逐篇著录申请人（`applicant`）与代理机构（`agency`）**——这两项直接进入排序，缺一即按 0 分计并触发待决项。候选 IPC 获取顺序固定为 **EPO OPS → 分类缓存 → 候选输入**，未取得 IPC 的候选不得成为推荐或最终范本。

用 `rank_template_candidates.py` 按**技术相关性 0.30 + IPC 相似度 0.20 + 申请人质量 0.25 + 代理机构质量 0.25** 排序，输出 `cn-patent-template-selection/v2`：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/rank_template_candidates.py" \
  --search-query "<search-query.json>" --candidates "<template-candidates.json>" \
  --output "<template-selection.json>"
```

技术相关性与 IPC 决定“能不能借鉴”，很容易同时满足；申请人/代理机构决定“文本质量值不值得学”，默认合计占一半权重。主体质量分来自 `references/notable-entities.txt` 名单命中（Tier 1 = 1.00、Tier 2 = 0.70、未上榜 = 0.30、缺著录 = 0.00）。改权重必须四项同时给出且和为 1；技术相关性与 IPC 必须保持正权重。

**范本由用户确认，不由本技能替用户选定**；未确认前阶段门记 `pending` 并写入待决清单，按默认起草策略继续，只有文件缺失、哈希不一致或 schema 错误才阻断。检索清单生成、候选门槛与排序命令的完整说明见 `references/search-and-template-flow.md`；评分算法、IPC 相似度分层与 EPO 降级规则见 `references/template-ipc-selection.md`。
### 2-B：提取范本风格并生成起草简报

范本全文优先用现有 BigQuery 专利全文工具获取，否则由用户提供 UTF-8 文本。每篇范本运行 `analyze_template_style.py` 生成 `cn-patent-template-style/v1` 风格指南；多篇必须用 `merge_template_styles.py` 合成（禁止手写，组织方式取最保守值）；再由 `style_applicator.py` 生成 `cn-patent-style-brief/v1` 起草简报。

分析器只提取结构与表达特征，不判断范本技术价值或法律有效性。**实施例形态由简报的 `organization` 决定**（`sectioned` 才允许拆成"实施例N"，`single_flow`/`none` 必须收敛为一条脉络）。合成规则、人工覆盖审计、简报字段与冲突处理见 `references/template-style-learning.md`。

**严禁**从范本复制技术内容、凭风格新增未披露特征、为贴近范本删除必要技术特征，或让范本篇幅偏好覆盖权利要求项数与摘要字数的法定/费用边界。
### 2-C：对抗性检索（原有逻辑）

只查专利不够，致命对比文件常常是产品、开源代码、标准和论文。

1. **专利文献**：本仓库的 BigQuery 检索工具（若已配置）覆盖含中国公开文本在内的全球专利。**仓库没有 CNIPA 官方检索接口**，中文关键词与分类号检索必须在 CNIPA 专利检索及分析系统人工补做，检索式、检索日期和命中结果一并留档；这条能力边界必须在文件包里明说，不得让读者以为已做过官方库穷举。
2. **抵触申请单独扫一遍**（专利法第九条；实施细则第四十七条；指南第二部分第三章第六节）。申请日以前提交、申请日以后才公布的在先申请同样破坏新颖性，而这类文献在起草时**原理上检索不到**。文件包必须把它写成一项无法消除的残余风险，而不是假装扫清了。
3. **非专利文献**：按权利要求簇分派对抗性检索，每一路都被指示去**击毙**权利要求——在位产品实际做什么、开源实现读代码、标准组织、arXiv、工程博客、公司技术文档。
4. 每一路返回逐项判定："我们有而它没有的"或"预期（破坏新颖性）"。汇总为：干净地带（写进独立权利要求）、**争议地带**（各特征单独已公开，但其耦合关系、时序条件、绑定集合或在 D1 语境下所起的作用未被任何单篇对比文件教导；中国实务中多数授权专利落在此带）、击杀区（绝不单独主张）、必读对比文件（代理师复核前必须读的）、未解决线索（被反爬拦截的页面等——上报用户，绝不无声丢弃）。

**语言纪律（不可谈判）。** 检索结果只支持"截至〔日期〕在〔已检索的出口〕中未发现预期"这种表述，并以带日期的逐要素对照表为支撑。绝不把"没有人做过""不存在现有技术""已扫清"当作事实写进任何文件。

**决策门（三分支）。** 有干净地带 → 写入独权，正常推进。只有争议地带 → 继续，但 `distinguishing` 特征必须带 `function_in_ref` 判断并进入创造性防御地图（后续 `cn-patent-inventive-step-map/v1`）。干净地带与争议地带皆无 → 输出"可授权最小方案 + 风险等级"的客户沟通稿，是否放弃由专利代理师与客户决定，流程不得自行写放弃报告终止。有幸存者 → 在**清扫后的宽度**上重跑值不值得做：干净地带总是比阶段 1 的候选窄，问题是更小的篱笆是否仍让竞争者付出代价。能被明显变体绕开的幸存者也写进该沟通稿，并给出防御性公开建议（成本近乎为零、永久有效、可用于阻断他人就同一机制在后申请）。

### 2-D：区别特征表（阶段 3 的唯一事实来源）

对比检索结果，逐条登记本申请与最接近现有技术的区别特征，形成后续起草唯一可引用的事实台账；字段、判定口径与常见错误见 `references/distinguishing-feature-ledger.md`。台账缺失或与权利要求不同步时不得进入阶段 3。
### 2-D2 创造性防御地图（强制）

在提取出区别特征表之后，必须建立防线地图（见 `references/inventive-step-map.md` 和 `references/inventive-step-map-schema-v1.json`）。该地图评估区别特征与对比文件及公知常识的被击穿风险：
1. **映射与耦合**：配置区别特征在各文献的 disclosed 状态或公知常识的 risk，并登记说明书中可逐字命名的耦合机理。
2. **复算验证**：执行以下验证，复算并拦截被文献轻易组合击破的弱防线：
```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/validate_inventive_step_map.py" \
  --map "<inventive-step-map.json>" \
  --case-dir "<案件根目录>" \
  --claims "<权利要求书.txt>" \
  --specification "<说明书.txt>"
```
3. 任何非 defensible 的权利要求组，或者包含过多 partial 的情况，都会以 pending decisions 挂起，强制人工定夺风险。

### 2-E：阶段门（未过门不得起草）

运行阶段门脚本，产出 `cn-patent-stage2-gate/v2` 状态位：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/check_stage_gate.py" \
  --search-query "<search-query.json>" --candidates "<template-candidates.json>" \
  --selection "<template-selection.json>" --output "<stage2-gate.json>"
```

判断题类门（检索未完成、范本未确认、IPC 缺用户原话等）**不阻断**：按保守默认继续并写入待决清单（`CLEARED_WITH_PENDING`）。只有文件缺失、哈希不一致或 schema 错误才以退出码 2 阻断。状态位表、`cn-patent-stage2-gate/v2` 字段与待决形状见 `references/stage2-gate.md`。
## 阶段 3——权利要求优先的撰写

先写权利要求再写说明书：权利要求决定保护边界，说明书负责支持与解释。**权利要求书、说明书、说明书摘要、说明书附图必须由同一张特征台账派生**，不得各自维护一套编号。

权利要求结构、独权与从权的分工与下降路径、必要技术特征的取舍标准、以及"机制名称不得直接当区别特征"的判定，见 `references/claim-first-drafting.md`；撰写后必须运行 `validate_claim_architecture.py`，退出码非零不得进入阶段 4。

申请人、发明人、联系电话、地址、联系人、代理机构等著录事项与附图标记分配属于本阶段输出，但**不属于本技能交付范围**的公文（请求书、委托书、费用表等）不在此生成。
## 说明书输出格式（强制）

章节结构、“附图说明”一图一句、附图标记清单句式、正文排版约束与打包前回扫，全部见 `references/specification-output-format.md`；撰写说明书前必须读取，组装与形式检查会机器复核其中可判定项。

## 阶段 4——机器验证循环（复用 -CN 审查链，迭代到干净）

本技能不自带检查器，全部复用仓库内的 `-CN` 审查链。三个原始检查器只读 UTF-8 无 BOM 文本，不联网、不建索引：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-claims-analyzer/scripts/check_claims_cn.py" \
  --input "<权利要求书.txt>" --output "<claims-raw-report.json>"

python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-specification-reviewer/scripts/build_support_matrix_cn.py" \
  --specification "<说明书.txt>" --features "<候选特征.json>" --output "<specification-raw-report.json>"

python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-formalities-reviewer/scripts/check_formalities_cn.py" \
  --manifest "<application-manifest.json>" --output "<formalities-report.json>"
```

退出码统一为：`0` 工具成功执行、`2` 报告含 `DETERMINISTIC_FAIL`、`3` 输入／路径／编码／JSON 无效、`4` 资源越限。**退出码 `0` 不代表申请文件通过审查。**

组装完整申请文件后走一遍完整链（等价于 `/full-review-cn`）：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-reviewer/scripts/build_review_bundle.py" prepare \
  --application "<prepare-input.json>" --workspace "<工作目录>"
# 在新上下文中完成独立语义审查，填写 review-input-template.json
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-reviewer/scripts/build_review_bundle.py" finalize \
  --workspace "<工作目录>" --review-input "<语义审查输入.json>" --output "<review-bundle.json>"
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-reviewer/scripts/verify_review_bundle.py" \
  --workspace "<工作目录>" --bundle "<review-bundle.json>" \
  --output "<bundle-verification.json>" --summary "<review-summary.md>"
```

若申请目录已经产生检索清单、范本候选与选择、阶段门、区别特征台账或权利要求架构合同，应在 `prepare-input.json` 的可选 `provenance_artifacts` 中逐项声明相对路径。审查链会把这些前置工件的字节和集合哈希冻结到 `prepare-manifest`、语义输入和 bundle；任一工件变化都必须从 prepare 重新开始。该绑定只证明流程来源可复算，不替代新颖性、创造性或其他法律判断。

迭代到零个确定性失败：每个被标记的权利要求要素都要逐字织进说明书；人工核实每一条 `REVIEW_REQUIRED` 并记录判定——人工这一轮是工作流的一部分，不是可选项。没有做过现有技术检索时，新颖性与创造性维度按契约必须保持 `INCONCLUSIVE`，这是设计上的 fail-closed，不要试图绕过。

**验证印章携带内容哈希，编辑会使它们失效。** 每条记录的检查结果必须声明其所检查工件文本的 SHA-256。之后任何编辑——加一项权利要求、动一句话——都会使该工件上的所有印章失效，打包前必须从 prepare 整链重跑。一份 README 对验证后又被编辑过的工件说"已验证"，是文件包能携带的最具破坏性的谎言。

## 阶段 5——两支红队，而不是一支

必须跑两支独立红队：一支攻击权利要求的保护范围与创造性，一支攻击组装好的文件包（形式、支持、附图、DOCX）。攻击清单、常见漏攻项与处置规则见 `references/red-team-and-packaging.md`。红队结论写入审查报告并绑定产物哈希。
## 阶段 6——打包

先汇总待决事项再出待决清单与两种副本：一旦进入撰写，流程不因判断题停下，各脚本遇到需人拍板的事项一律采用保守默认继续并在 `pending_decisions` 留痕；打包前由 `collect_pending_decisions.py` 汇总为 `cn-patent-pending-decisions/v1` 与《待决事项清单.md》。交付范围、审稿版/提交副本差异与打包门禁见 `references/red-team-and-packaging.md`。
### Word 模板组装（用户要求单一 Word 文件时）

用户要求单一 Word 文件时，读取 `references/docx-assembly.md`（含阶段 6 组装门禁、待决标记与两种副本）并运行 `scripts/assemble_application_docx.py`。默认模板是仓库根目录 `模版.docx`，不读取案件目录的 `输出模版.docx`；只有显式 `--template` 才替换。随后必须运行 `scripts/verify_docx_assembly.py`，附图属于交付范围时再运行 `cn-patent-diagram-generator/scripts/verify_drawing_docx_delivery.py`。DOCX 是交付容器，不是第五类法定技术文书。

评审版与提交版差异（标记保留/剥离、高亮处理）、原生公式与字符样式要求详见 `references/docx-assembly.md`。
## 本工作流旨在防止的失败模式

全量失败模式清单（含常见误植、越权起草、把机制名称当区别特征、只攻击权利要求不攻击文件包等）见 `references/failure-modes.md`；每次复核前通读一遍。
