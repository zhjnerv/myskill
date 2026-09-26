---
name: cn-patent-reviewer
description: 本技能应在对中国发明专利申请进行权利要求、说明书、形式及实体条件的综合审查并汇总整改顺序时使用。不要用于：自行执行专利检索、把生产者的自报状态当作最终验证，或直接承诺授权与可申报。
---

# 中国发明专利综合审查

本技能编排三个原始检查器和独立语义审查，形成证据绑定、可独立复算的综合审查包。现有专利检索结果只作只读输入；本技能不改变也不重建检索能力。

运行环境为 Python 3.10 及以上版本，仅使用标准库。全过程不发起网络请求、不加载模型、不构建索引。

## 闭环

```text
UTF-8 申请文件
  -> prepare    冻结输入/规则/工具身份，运行三个真实检查器
  -> 三份原始报告 + 41 维语义审查输入模板
  -> 独立语义审查（新上下文或专利代理师完成）
  -> finalize   校验新鲜度，守恒转换全部 finding/gap，构造 bundle
  -> 独立 verifier  复算哈希、规范、状态、覆盖、守恒与边界
  -> 机械渲染 review-summary.md
```

四个环节的产物互不覆盖；任一环节的输入字节变化都会使下游证据失效。

## 共享本地法源（执行前读取）

涉及中国专利法律规则、条款或审查方法时，优先读取仓库内的统一法源，不再为已收录内容默认联网搜索：

- 法源先读取 `${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/source-index.json`，再按主题读取分章；不得默认加载 `guide-full.md`。
- 专利法：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/专利法(2020-10-17).md`
- 专利法实施细则：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/专利法实施细则(2023-12-21).md`
- 审查指南全文：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/审查指南2026MD/guide-full.md`
- 审查指南分章：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/审查指南2026MD/chapters/`
- 统一法源目录：`${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-reviewer/references/cn-source-catalog.md`

本地文本用于条款和章节目定位。只有核对后续修订、施行状态，或处理本地文本缺失与冲突时才联网，并优先使用 CNIPA 官方来源。

## 必需输入

同一目录下的真实 UTF-8 无 BOM 文件：

- 权利要求书（纯文本）；
- 说明书（纯文本）；
- 候选技术特征 JSON（由人工或 Skill 逐项权利要求提取）；
- 形式审查 manifest（`cn-patent-application-manifest/v2`）。

以及一份 `cn-patent-review-prepare-input/v2` 声明，指向上述四个文件并给出 `application_id`。被引用路径必须位于声明文件所在目录之下。

声明可以增加可选的 `provenance_artifacts`，用于把前置流程证据纳入同一条可复算来源链：

```json
[
  {"artifact_id": "search-query", "path": "01-检索/search-query.json"},
  {"artifact_id": "template-candidates", "path": "01-检索/template-candidates.json"},
  {"artifact_id": "template-selection", "path": "01-检索/template-selection.json"},
  {"artifact_id": "stage2-gate", "path": "01-检索/stage2-gate.json"},
  {"artifact_id": "feature-ledger", "path": "01-检索/feature-ledger.json"},
  {"artifact_id": "claim-architecture", "path": "03-审查工作区/claim-architecture.json"}
]
```

也可以写成 `artifact_id -> 相对路径` 对象。prepare 会校验 ID 唯一、路径不越界、UTF-8 无 BOM、字节长度和文件哈希，并在 `prepare-manifest`、语义输入和 bundle 中分别保存工件数组及 `provenance_set_sha256`。该集合只证明来源可复算，不把检索清单升级为新颖性、创造性或其他法律结论。

PDF、DOCX、扫描件和仅含图片的附图不在本轮范围，必须 fail-fast 或明确保留为未验证。

## 先读参考

- [审查规范与状态](references/review-contract.md)（机读规范：[cn-review-contract-v2.json](references/cn-review-contract-v2.json)）
- [中国法源目录](references/cn-source-catalog.md)
- [实体审查规则](references/substantive-review-rules.md)
- [跨文件一致性](references/cross-document-rules.md)
- [基准与逃逸反例](references/benchmark-cases.md)

## 工作流

1. **prepare**：冻结证据并运行三个真实检查器。

   ```bash
   python3 "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/scripts/run_python.py" "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-reviewer/scripts/build_review_bundle.py" prepare \
     --application "<prepare-input.json>" \
     --workspace "<工作目录>"
   ```

   产出 `raw/claims.json`、`raw/specification.json`、`raw/formalities.json`、`prepare-manifest.json` 和 `review-input-template.json`。如声明了 `provenance_artifacts`，其字节和集合哈希也会被冻结。任一原始报告或 provenance 工件不符合规范即整体失败，不产出下游工件。

2. **独立语义审查**：在新上下文中填写 `review-input-template.json`。模板的 41 个维度默认全部失败关闭为"未评估"（覆盖度 `NONE`、结论 `INCONCLUSIVE`、证据 `NONE/MISSING`），审查者只升级自己确有证据的维度。

   逐维度必须给出 `coverage`、`result`、`evidence.mode`、`evidence.sufficiency`、`severity`，并绑定证据工件。规范的状态不变量会拒绝任何不自洽的组合，例如证据不足却给出"无问题"。

   新颖性和创造性另有硬边界：未使用逐项权利要求与单一现有技术方案的比对证据（`evidence.mode = PRIOR_ART_COMPARISON` 且绑定已声明工件）时，结论必须保持 `INCONCLUSIVE`。检索清单结构有效不能替代该比对。

3. **finalize**：守恒转换并构造 bundle。

   ```bash
   python3 "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/scripts/run_python.py" "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-reviewer/scripts/build_review_bundle.py" finalize \
     --workspace "<工作目录>" \
     --review-input "<已完成的语义审查输入.json>" \
     --output "<review-bundle.json>"
   ```

   finalize 逐字节核对冻结证据的新鲜度；申请文件、规则矩阵、原始报告或工具身份中任何一项变化，都会使本轮证据失效并要求重新 prepare。review-input 顶层字段必须与规范 `exact_fields.review_input` 完全一致，多出或缺少字段以退出码 3 拒绝。

   全部原始 finding 和 gap 由工具机械并入其所属法律维度。审查者无法通过省略把仍有确定性失败的维度签为无问题——该组合会被状态不变量直接拒绝且不产出 bundle。

4. **独立验证与摘要**：

   ```bash
   python3 "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/scripts/run_python.py" "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-reviewer/scripts/verify_review_bundle.py" \
     --workspace "<工作目录>" \
     --bundle "<review-bundle.json>" \
     --output "<bundle-verification.json>" \
     --summary "<review-summary.md>"
   ```

   验证器不采信 bundle 自报的任何值：从磁盘原字节复算证据绑定、逐条比较原始报告与专项报告、检查 41 维覆盖、搜索证据边界和资源上限。处置状态只能由验证器派生；存在规范、工具或资源错误时不存在申请处置，且工具故障使用 `CN-VERIFY-*` 规则 ID，不伪造中国专利法引用。

5. 修改申请文件前向用户展示整改计划并取得确认。修改后旧证据全部失效，必须从 prepare 重新开始。

## 41 个法律维度

分为四组，由规范固定，条件维度不得静默消失：

- **实体核心 17 项**：第五条、第二十五条、技术方案、实用性、充分公开、新颖性、创造性、权利要求清楚、说明书支持、必要技术特征、单一性、修改超范围、分案超范围、同样的发明创造、保密审查、遗传资源披露、诚实信用；
- **有效日与宽限期 4 项**：优先权享有与有效日、逐项权利要求优先权、部分与多项优先权、第二十四条宽限期；
- **申请文件与程序 17 项**：核心文件与申请类型、请求书字段与主体身份、语言格式与签章、名称一致性、说明书结构、权利要求呈现、单项 600 字与引用形式、摘要内容与字数、摘要附图指定、附图必要性与存在、图号标记与图形、序列表、生物材料保藏、遗传资源声明、优先权声明与文件、第二十四条声明与证明、分案程序、实审请求程序；
- **条件特殊领域 3 项**：计算机与人工智能、化学与生物技术、中药。

三个原始检查器的 rule_id 由规范的 `rule_dimension_map` 映射到唯一维度；缺映射是规范错误，不允许猜测归属。输出保护、资源上限和 verifier 自身规则列在 `tool_only_rules`，不进入 41 个法律维度。

## 状态

原始 finding 只用四种状态：

- `DETERMINISTIC_FAIL`：当前工件可客观确认的结构、缺件、哈希或契约错误；
- `REVIEW_REQUIRED`：需要专利代理师、技术专家或独立语义审阅；
- `WARNING`：非阻塞的形式或策略风险；
- `NOT_VERIFIED`：材料、检索证据、验证能力或审查范围不足。

处置状态由验证器按规范优先级派生，取 `NOT_ASSESSED`、`BLOCKING_ISSUE_FOUND`、`REVIEW_INCOMPLETE`、`REMEDIATION_REQUIRED`、`NO_BLOCKING_ISSUE_FOUND_IN_SCOPE` 之一。

不得输出合规分、总体通过、`ready_to_file`、可申报或保证授权，也不得通过嵌套或改名字段携带上述结论。没有 finding 不等于实体条件已经满足。

## 退出码

| 码 | 含义 |
|---|---|
| `0` | 工具执行成功；仍须读取结构化结果，不表示任何法律结论成立 |
| `2` | 存在 `DETERMINISTIC_FAIL`（prepare/finalize）或处置为 `BLOCKING_ISSUE_FOUND`（verifier） |
| `3` | 输入、路径、编码、新鲜度或规范错误 |
| `4` | 资源上限失败；属工具错误，不生成任何法律 finding |

## 完成条件

本轮审查只有在以下条件同时满足时才算完成：

- 三份原始报告存在且逐份通过规范校验；
- 41 个维度各有且仅有一条原子评估，条件维度已完成评估、以充分证据确认不适用或明确记录审查未完成；
- 全部原始 finding 与 gap 在下游恰好出现一次且未被降级或改写；
- 验证器读取真实文件并独立复算全部哈希，返回零错误；
- `review-summary.md` 由验证器机械渲染；
- 法律语义结论已由独立新上下文或专利代理师复核。

验证器返回 `0` 仅表示未发现可确定的规范错误，不能替代法律专业判断，也不代表官方审查结论。
