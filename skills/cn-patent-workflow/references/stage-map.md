# 中国专利阶段路由表

| 当前任务 | 调用 Skill | 最少输入 | 主要输出 | 不应加载 |
|---|---|---|---|---|
| 完整申请 | `cn-patent-application-creator` | 技术交底或代码 | 四文书及工作证据 | MPEP、USPTO、PCT 规则 |
| 范本和 IPC | `cn-patent-application-creator` 的检索阶段 | `technical-features.json`、候选清单 | `search-query.json`、`template-selection.json` | DOCX、附图 XML 规则 |
| 权利要求审查 | `cn-patent-claims-analyzer` | 权利要求文本 | 原始专项报告 | 完整审查指南、DOCX、附图配色 |
| 说明书审查 | `cn-patent-specification-reviewer` | 说明书、权利要求特征 | 支持矩阵和专项报告 | 检索范本、DOCX |
| 形式审查 | `cn-patent-formalities-reviewer` | manifest 和申请文件 | 形式专项报告 | 创造性检索、附图布局 |
| 综合审查 | `cn-patent-reviewer` | 三类申请文件和 manifest | review bundle、验证报告 | 范本风格、DOCX |
| 起草完整性门 | `cn-patent-application-creator` 的台账与架构脚本 | feature ledger v2、权利要求、说明书 | 数据流/异常闭合报告、inventive step map v1及验证报告、claim architecture v1及验证报告 | DOCX、视觉审查 |
| 附图 | `cn-patent-diagram-generator` | drawing brief v4、说明书、台账、claim architecture v1；可选原始母版与用户修改稿 | style brief v1、安全重建报告（同图修改时）、`.drawio`、PNG、visual review v2、验证报告 | 法源全文、DOCX |
| Word 交付 | `cn-patent-application-creator` 的 DOCX 阶段 | 已过门四文书、模板、待决清单 | 审稿版与提交版 DOCX（`--copy review|submission`）、组装报告、新鲜度验证 | 检索、审查指南全文 |
| 待决汇总 | `cn-patent-application-creator` 的 `collect_pending_decisions.py` | 各阶段报告的 `pending_decisions` | `cn-patent-pending-decisions/v1`，以及最终申请文件同目录的 `待决文件.md` | 法源全文、DOCX 规则 |

## 交接原则

- 整个案件以 `cn-patent-workflow-plan/v1` 交接，路径固定为案件目录的 `流程计划.json`。没有这份文件，不得开始第一个阶段。
- 检索阶段以 `cn-patent-template-search/v1`、`cn-patent-template-selection/v2` 交接（v2 把申请人/代理机构质量纳入范本加权）。
- 起草阶段以 `cn-patent-feature-ledger/v2`、`cn-patent-stage2-gate/v2`、`cn-patent-inventive-step-map/v1` 和 `cn-patent-claim-architecture/v1` 交接。
- 判断题类门（检索/范本/IPC 缺用户原话、复核未批准、公知常识 medium、视觉复核未批准等）不阻断，以各报告的 `pending_decisions` 交接；打包前由 `collect_pending_decisions.py` 汇总为 `cn-patent-pending-decisions/v1`，并强制写出最终申请文件同目录的 `待决文件.md`。人的修改由 `read_pending_file.py` 收成 `cn-patent-pending-resolutions/v1`。阶段门 `CLEARED_WITH_PENDING` 与 `CLEARED` 同样允许进入下一阶段。
- 材料未写明公开或优先权时不生成待决。CNIPA 人工检索未完成只保留一条流程待决；权项待决不重复“未检索”或“新颖性、创造性不能下结论”。
- 附图阶段以 `cn-patent-drawing-brief/v4`、可选且已批准的 `cn-patent-drawing-style-brief/v1`、同图修改稿的安全重建报告、`cn-patent-drawing-visual-review/v2` 和最终验证报告交接。
- 审查阶段以 `cn-patent-review-raw-report/v2` 和 review bundle 交接。
- DOCX 阶段只消费已经通过前序门禁的四文书，不反向修改技术事实。待决回读取的是四文书源稿；组装器仍然不改技术内容。

## 失效传播

- 权利要求、说明书或台账变化：重跑数据流门和权利要求架构门，重建 drawing brief v4，并使附图验证、综合审查和 DOCX 证据失效。
- claim architecture变化：重建 drawing brief v4，重新附图验证、综合审查和DOCX组装。
- Draw.io 母版变化：重新官方导出、重新视觉复核、重新附图验证和 DOCX 组装。
- 用户范例或style brief变化：重新分析范例、确认视觉意图；同图修改稿从原始母版安全重建，其他图只复用紧凑布局指标；随后重制附图，并使视觉复核和DOCX证据失效。
- 最终 PNG 变化：重新视觉复核、附图验证和 DOCX 组装；最终交付运行 `verify_drawing_docx_delivery.py`。
- 任一四文书或嵌入图片变化：重新生成 DOCX 并运行 `verify_docx_assembly.py`。
- 待决文件被人工修改：先读 `待决决议.json`，只改已被决定的源稿位置，再重跑受影响的门、重新汇总待决文件并重装审稿版。未决事项在审稿版对应位置写成可直接选择的黄底段落。提交版不插入待决内容，并剥离残留标记。计划中已完成且受影响的步骤用 `reopen --cascade` 打回。
