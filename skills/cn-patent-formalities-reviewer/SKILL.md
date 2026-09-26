---
name: cn-patent-formalities-reviewer
description: 本技能应在审查中国发明专利申请文件组成、说明书章节、发明名称、摘要字数、图号、附图标记和草稿残留时使用。不要用于：把未提供给工具的材料推定为申请实际缺件，或代替充分公开、新颖性和创造性审查。
---

# 中国直接发明专利申请形式与程序原始审查（CN v2）

本技能只接受直接提交的中国发明专利申请，输出 `cn-patent-review-raw-report/v2`。PCT 国家阶段必须拒绝或交给后续条件模块，不得套用直接申请规则。输出固定 `jurisdiction=CN`、`review_type=formalities`、`legal_effect=ADVISORY_ONLY`；形式检查通过不代表实体授权条件通过，也不产生“可申报”结论。

## 共享本地法源（执行前读取）

涉及中国专利法律规则、条款或审查方法时，优先读取仓库内的统一法源，不再为已收录内容默认联网搜索：

- 法源先读取 `${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/source-index.json`，再按主题读取分章；不得默认加载 `guide-full.md`。
- 专利法：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/专利法(2020-10-17).md`
- 专利法实施细则：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/专利法实施细则(2023-12-21).md`
- 审查指南全文：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/审查指南2026MD/guide-full.md`
- 审查指南分章：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/审查指南2026MD/chapters/`
- 统一法源目录：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-reviewer/references/cn-source-catalog.md`

本地文本用于条款和章节目定位。只有核对后续修订、施行状态，或处理本地文本缺失与冲突时才联网，并优先使用 CNIPA 官方来源。

## 输入

以 `cn-patent-application-manifest/v2` JSON manifest 描述待审文件包。顶层至少提供 `application_scope=direct_cn_invention_application`、`application_type=invention`、`filing_medium`、`documents` 和 `titles`。每份材料必须区分：

- `provided`：已提供，并给出 `path` 或 `content`；
- `confirmed_absent`：申请文件包中经确认实际缺失；
- `unknown`：本轮未提供或无法确认是否存在；
- `not_applicable`：经说明不适用。

`unknown` 必须输出 `NOT_VERIFIED`。只有 manifest 或用户明确确认法定必需文件实际缺失，才能输出 `DETERMINISTIC_FAIL`。

Manifest 版本为 `cn-patent-application-manifest/v2`。本检查器只使用 `invention`，不得缺省推定申请类型；`filing_medium` 只使用 `electronic`、`paper` 或 `unknown`。文书条目采用严格互斥结构：

- `provided` 必须且只能提供一个非空 `path`，或一个字符串 `content`；
- 其他状态不得携带 `path` 或 `content`；
- 相对或绝对 `path` 的解析结果必须位于 manifest 所在目录内；
- 空白文书是当前文件包可客观确认的内容问题，不等同于“工具未收到材料”。

示例：

```json
{
  "schema_version": "cn-patent-application-manifest/v2",
  "application_scope": "direct_cn_invention_application",
  "application_type": "invention",
  "filing_medium": "electronic",
  "documents": {
    "request": {"status": "provided", "path": "request.txt"},
    "specification": {"status": "provided", "path": "specification.txt"},
    "claims": {"status": "provided", "path": "claims.txt"},
    "abstract": {"status": "provided", "path": "abstract.txt"},
    "drawings": {"status": "unknown"}
  },
  "titles": {
    "request": "一种示例装置",
    "specification": "一种示例装置",
    "abstract": "一种示例装置"
  }
}
```

字段级约束：

- `titles` 仅允许 `request`、`specification`、`abstract`，但这些值只是 manifest 人工声明。脚本会先尝试从请求书、说明书和摘要文本中提取真实名称，再把 manifest 声明作为回退与比对线索；提取不到或无法仅凭文本证明正式栏位填写正确时，仍保留结构化 gap；
- `drawing_figures` 只能在 `drawings.status=provided` 时出现，但仍是未经过图面视觉提取核验的 manifest 声明；
- `reference_signs.drawings` 只能在 `drawings.status=provided` 时出现，同样不能代替对真实附图标记的视觉核验。附图未提供或状态未知时，不得用图号、标记清单把未知状态确定化；
- 违反以上 manifest 契约属于输入错误，CLI 返回 `3`，不生成业务 finding。

## 工作流

1. 保留原文件包和 manifest；CLI 对 manifest 原始字节只读取一次，并用同一字节快照完成解码、解析和 SHA-256 绑定。
2. 运行确定性检查。检查器只读取 UTF-8 无 BOM 文本、Markdown 和 JSON，不解析 PDF/DOCX、不运行 OCR、不联网：

   ```bash
   python3 "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/scripts/run_python.py" "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-formalities-reviewer/scripts/check_formalities_cn.py" \
     --manifest "<application-manifest.json>" \
     --output "<formalities-report.json>"
   ```

3. 依据 [形式规则矩阵](references/formalities-rule-matrix.md) 复核脚本发现和例外。
4. 核对图号、摘要附图和附图标记。文本筛查不能证明真实图面、标记指向或图形质量，相关事项必须保留 gap。附图标记的呈现形态由脚本确定性筛查：附图说明章节内出现表格、项目符号或逐行标记清单时输出 `WARNING`（形态问题无直接法源禁止，不升级为 `DETERMINISTIC_FAIL`，也不改变退出码）；标记名称是否与正文首次出现处一致仍须人工核对。`drawings.status=provided` 时，`abstract_figure` 不得声明为 `not_applicable`。
5. 核对草稿信号：结构化占位或内部评注为 `DETERMINISTIC_FAIL`；未加结构标识的“待确认”等弱信号最多为 `REVIEW_REQUIRED`，先排除合法技术状态或枚举值。
6. 对纸件规格、图面清晰度、必要文字、请求书字段等脚本未覆盖事项明确标记 `NOT_VERIFIED`。
7. 修改前展示修改清单并取得用户确认；任何文件变化后重新计算哈希并重跑检查。

CLI 退出码：`0` 表示检查器成功执行且没有确定性失败（不表示申请文件形式合规或任何法律结论成立），`2` 表示报告含确定性失败，`3` 表示 manifest、路径、编码或 JSON 输入无效，`4` 表示资源越限。资源错误不生成报告或中国法 finding。UTF-8 BOM、超过 24 MiB 总文书、单文书/manifest/文书数/JSON 深度/字符串/finding/gap/check/output 上限均 fail-fast。退出码 `0` 不表示申请文件实体或形式已经通过。

## 状态

- `DETERMINISTIC_FAIL`：在当前文件包中客观确认的缺件、矛盾或超限；
- `REVIEW_REQUIRED`：规则例外、图面或语义需要人工判断；
- `WARNING`：可补正的格式候选或低风险草稿问题；
- `NOT_VERIFIED`：未提供、未知、无法读取或脚本能力未覆盖。

不得输出合规分、总体通过或 `ready_to_file`。

## 17 个形式/程序维度

每个维度恰好生成一个 `raw_check`，并绑定其稳定 `finding_id`/`gap_id`：

```text
form_core_documents_and_application_type
form_request_fields_and_party_identity
form_language_format_and_execution
form_title_consistency_and_quality
form_specification_structure_and_drafting
form_claim_presentation_and_reference_form
form_abstract_content_and_length
form_abstract_figure_designation
form_drawings_requiredness_and_presence
form_drawing_numbering_reference_signs_and_graphic_form
form_sequence_listing
form_biological_material_deposit
form_genetic_resource_statement
form_priority_declaration_and_documents
form_article_24_declaration_and_proof
form_divisional_filing_procedure
form_substantive_examination_request_procedure
```

条件维度必须有证据支持的 `not_applicable`，否则输出结构化条件 gap；工具、规范和资源错误不能进入 finding。

## 输出

报告 schema 为 `cn-patent-review-raw-report/v2`，严格遵循 `skills/cn-patent-reviewer/references/cn-review-contract-v2.json` 的字段白名单，至少包含输入/规则工件、工具身份、三项 evidence binding、resource limits/usage、17 项 `checks_performed`、稳定 findings 和结构化 gaps。文件输出使用同目录临时文件，写入后执行 `flush`/`fsync`，并在创建临时文件前及 `os.replace` 前复核输出路径没有与 manifest 或路径型文书形成规范化路径、符号链接或硬链接别名。原件、报告与修改稿分开保存。
