---
name: cn-patent-specification-reviewer
description: 本技能应在审查中国发明专利说明书是否清楚完整、能够实现、支持权利要求，或核对实施方式、技术效果、术语和附图一致性时使用。不要用于：仅凭关键词命中签发充分公开结论，或代替权利要求结构和形式完整性专项检查。
---

# 中国发明专利说明书审查

本技能把“文本证据定位”和“法律上的充分公开、说明书支持”严格分开。证据脚本只回答候选技术特征在哪里出现；是否足以使本领域技术人员实现，必须独立进行技术和法律语义审查。

运行环境为 Python 3.10 及以上版本，仅使用标准库。

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

必需输入：

- 说明书全文；
- 权利要求书；
- 待核对的候选技术特征列表。

视审查范围提供：附图、附图标记清单、原始申请文件、修改对照、实验或验证材料。未提供的材料对应 `NOT_VERIFIED`，不得推定实际不存在。

## 工作流

1. 保留说明书原稿并计算 SHA-256。
2. 从权利要求中人工提取需要核对的技术特征。不得让无语义脚本自行决定哪些内容构成必要技术特征。
3. 运行证据定位脚本：

   ```bash
   python3 "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/scripts/run_python.py" "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/skills/cn-patent-specification-reviewer/scripts/build_support_matrix_cn.py" \
     --specification "<说明书.txt>" \
     --features "<候选特征.json>" \
     --output "<说明书原始报告.json>"
   ```

   `--output` 必须与说明书和候选特征 JSON 分离，也不得是其中任一输入的符号链接、硬链接或规范化后的同一路径。脚本以同目录临时文件写入并原子替换独立报告。

4. 依据 [说明书规则矩阵](references/specification-rule-matrix.md) 审查：
   - 技术问题、技术手段和技术效果是否形成可实施的技术方案；
   - 说明书是否清楚、完整并达到本领域技术人员能够实现的程度；
   - 权利要求的概括范围是否得到说明书支持；
   - 对产品权利要求中的功能性或效果限定先审查允许边界：通常应尽量避免；仅在结构特征无法限定，或结构限定不如功能/效果限定恰当，且该功能/效果能够直接、肯定验证时，才可能允许。该限定原则上覆盖所有能够实现所述功能的实施方式，必须审查概括范围是否得到说明书支持；纯功能性权利要求不得认定为得到说明书支持；
   - 术语、附图说明、具体实施方式和权利要求是否一致；
   - 涉及算法或人工智能时，按两条并列技术路径审查充分公开：
     - 路径 A：处理具有确切技术含义的数据，并用于具体技术领域或场景产生技术效果；核对相应领域的输入输出设置及作用机制；
     - 路径 B：算法与计算机系统内部结构存在特定技术关联，提升硬件运算效率、减少存储或传输量、提高处理速度等内部性能；不得把外部具体应用领域作为本路径的必备条件；
     - 两条路径均须说明技术特征与算法特征如何共同作用并产生技术效果。不得仅因未提交源码、模型权重或全部训练数据认定公开不足。
5. 对每个语义 finding 记录说明书段落、对应权利要求、缺口、法源和判断理由。
6. 修改前取得用户确认；修改后重新生成证据矩阵，并重新评估是否引入超范围风险。

## 状态

- `DETERMINISTIC_FAIL`：当前输入可客观确认的文件或数据结构错误；
- `REVIEW_REQUIRED`：需要本领域技术和法律语义判断；
- `WARNING`：低风险一致性问题或启发式候选；
- `NOT_VERIFIED`：材料不足、未执行或超出脚本能力。

精确文本命中不等于得到说明书支持；未命中也不等于必然缺乏支持。同义表达、隐含公开和本领域普通技术知识均需人工核对。

## 候选特征 JSON 契约

接受字符串数组，或包含 `features` 数组的对象。对象项格式为：

```json
{"id":"F001","text":"候选技术特征","variants":["显式变体"]}
```

- `id` / `feature_id`、`text` 和每个 `variant` 必须是字符串；禁止把 `null`、数字或布尔值隐式转成文本；
- ID 和主特征文本必须非空，ID 在 Unicode 规范化和大小写折叠后必须唯一；
- 空 variant、与主文本相同或规范化后重复的 variant 会被去除；
- 模式错误返回退出码 `3`，不生成伪矩阵或伪命中。

## 原始报告契约

脚本输出 `cn-patent-review-raw-report/v2`，字段集合由 [CN v2 审查规范](../cn-patent-reviewer/references/cn-review-contract-v2.json) 固定，不得增删：

- `checks_performed`：每个 rule_id 恰好一个 raw_check，状态取 `COMPLETED` / `PARTIAL` / `SKIPPED` / `NOT_VERIFIED`；
- `findings`：确定性缺陷和需人工复核的候选，状态取 `DETERMINISTIC_FAIL` / `REVIEW_REQUIRED` / `WARNING` / `NOT_VERIFIED`；
- `gaps`：输入缺失、解析未决和语义未执行，类别取规范枚举；命中证据以 `SEMANTIC_REVIEW_NOT_PERFORMED` 缺口承载，明示"已定位文本但未作法律判断"；
- `evidence_binding` / `tool_identity`：绑定本轮输入、规则和工具字节，供独立 verifier 复算。

说明书为空时，`CN-SPEC-MATCH-001` 的 raw_check 状态为 `SKIPPED`，并生成 `INPUT_UNAVAILABLE` 缺口，不得生成"未找到特征"的伪 finding。段落标记只在行首识别；重复段落号输出 `CN-SPEC-PARAGRAPH-001 / DETERMINISTIC_FAIL`，命中位置用 `段落号#出现序号` 区分各次出现。

每条命中证据的 `location` 记录 `段落号#出现序号[起:止]:匹配模式`，`excerpt` 为围绕命中位置截取的上下文。默认保留拉丁字母和数字之间的空格，只对汉字之间的排版空白容错。

CLI 退出码：

- `0`：脚本完成并写出原始报告；不表示充分公开或说明书支持成立；
- `2`：报告中存在 `DETERMINISTIC_FAIL`；
- `3`：输入模式、输入输出路径、文件、编码或工具执行错误；
- `4`：资源上限失败，属工具错误，不生成任何法律 finding；
- argparse 参数错误沿用退出码 `2`，且不会生成原始报告。

资源上限与规范一致：说明书 8 MiB、候选特征 4 MiB、段落 100,000、候选特征 20,000、单特征 variant 32、单特征命中 1,000、总命中 100,000、编排时限 180 秒。

## 输出

脚本输出原始报告；本技能的完整交付还应包含：

- 候选技术特征在说明书中的命中位置及上下文（由原始报告的证据承载）；
- 充分公开、支持、功能性限定和技术效果的独立语义分析；
- 每条语义结论对应的说明书段落、权利要求、法源和判断理由；
- 修改建议及潜在超范围风险。

`input_artifacts[].sha256`、`rule_sources[].sha256` 和 `tool_identity.tool_sha256` 绑定本轮读取的字节版本，只证明证据来源，不证明法律判断正确。

`--output` 必须与说明书和候选特征 JSON 分离，也不得是其中任一输入的符号链接、硬链接或规范化后的同一路径。说明书和候选特征均必须是 UTF-8 无 BOM。
