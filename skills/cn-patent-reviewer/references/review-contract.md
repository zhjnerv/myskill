# 中国发明专利审查规范（CN v2）

机器可读的唯一规范位于 [cn-review-contract-v2.json](cn-review-contract-v2.json)。生产者、三个原始检查器、`prepare`、`finalize`、独立 verifier 和摘要渲染器都必须以该文件为准；不得保留或增加 v1 兼容层。

## 适用范围

本规范只覆盖直接提交的中国发明专利申请。PCT 国家阶段的请求书、进入期限、译文和程序规则不在本规范范围；输入声明为 PCT 国家阶段时，必须被拒绝或交给后续条件模块，不得套用直接申请规则。

所有生产输出固定 `legal_effect = ADVISORY_ONLY`。对象白名单拒绝未知字段，生产者不得输出总体裁决、评分、通过、可申报、授权或等效字段。

## 原子评估

每个法律评估是唯一的 `rule_id × target_id` 原子项。它必须带有 `coverage`、`result`、`evidence.mode`、`evidence.sufficiency`、`severity`、`finding_ids` 和 `gap_ids`。`MIXED` 只能由聚合层表示多个子项的不同 `result`，不能进入原子项。完整的组合不变量和 disposition 优先级位于 JSON 的 `state_invariants`、`aggregation` 与 `disposition`。

## 原始报告与守恒

三个原始检查器均输出 `raw_report` schema。每一个 finding 和 gap 有稳定 ID；下游报告只通过 `origin_raw_finding_id` 或 `origin_raw_gap_id` 引用它们。一个原始 finding 必须在下游恰好出现一次，且不得改变其 `rule_id`、目标/位置、问题或补救建议。原始 `DETERMINISTIC_FAIL` 与 `REVIEW_REQUIRED` 不得被丢失、合并或降级。检查器 `rule_id` 必须出现在规范 `rule_dimension_map` 中，或明确列入 `tool_only_rules`；缺映射是规范错误，不允许猜测归属。

原始报告固定使用 `cn-patent-review-raw-report/v2`，并记录生效的 `resource_limits` 与实际 `resource_usage`。finding/gap 的证据项只允许工件 ID、位置和原文摘录；三个检查器不得各自扩展 schema。

`checks_performed` 中每项均采用 `raw_check` 精确字段。finding 和 gap 的 `check_id` 必须引用唯一存在的检查项；所有下游来源引用必须恰好指向一个原始 finding 或 gap，未知字段、缺字段、悬空引用、双重来源和伪造来源均为规范错误。

工具、规范或资源错误使用工具/验证器规则 ID，不能伪造中国专利法 finding，也不得派生任何申请处置。资源越限统一返回退出码 `4`，且不生成法律 finding。

## 检索边界

`cn-patent-search-manifest/v1` 是只读消费者规范。结构有效的 manifest 只能证明其记录和绑定可复算，不能证明新颖性、创造性、抵触申请身份、检索完整性或法律结论。新颖性必须逐项权利要求与一项单独技术方案比较；创造性必须保留最接近现有技术、区别特征、技术效果、实际技术问题和技术启示。

## 前置流程 provenance

`prepare-input` 可以通过 `provenance_artifacts` 声明检索清单、范本候选、范本选择、阶段门、区别特征台账和权利要求架构等前置工件。生产器把这些工件规范化为独立数组，逐项冻结 `artifact_id`、绝对路径、SHA-256、字节长度、媒体类型和编码；路径必须位于 `prepare-input` 所在目录或其子目录内，工件 ID 不得与其他证据集合重复。

当该数组存在时，`prepare-manifest`、语义审查输入和 bundle 必须原样传递它，并增加 `evidence_binding.provenance_set_sha256`。`finalize` 和独立 verifier 都从磁盘重新读取工件、检查字节新鲜度并复算集合哈希；任何缺失、越界、重复或篡改都属于工具/合同错误，不得转化为中国专利法 finding。没有声明 provenance 的旧 v2 bundle 仍可按兼容规则验证，但不能据此声称前置流程证据已经闭合。

## 资源与写入

默认资源上限和统一退出码在 JSON 的 `resource_limits` 中。输入只接受 UTF-8 无 BOM 的文本、Markdown 和 JSON；PDF、DOCX、扫描件和仅含图片的附图必须 fail-fast 或明确作为未验证材料。输出采用独立路径、同目录临时文件、`fsync` 和原子替换，替换前再次检查与任一证据路径的别名冲突。
