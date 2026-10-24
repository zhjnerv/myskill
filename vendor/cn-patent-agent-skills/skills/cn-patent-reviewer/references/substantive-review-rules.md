# 中国发明专利实体审查规则（CN v2）

本文件是 [cn-review-contract-v2.json](cn-review-contract-v2.json) 中 17 个实体核心维度、4 个有效日/优先权/宽限期维度及 3 个条件性特殊领域维度的阅读索引。稳定 ID、法源定位和状态要求以 JSON 为唯一机器解释来源。

## 实体审查边界

- `novelty`：逐项权利要求只能与一项单独的现有技术技术方案比较；不得拼接文献或同一文献中相互独立的方案。
- `inventiveness`：保留最接近现有技术、区别特征、区别特征的技术效果、实际技术问题、技术启示和反事后分析记录。
- `claim_clarity`、`claim_support` 与 `essential_features` 是独立维度；结构命中不等同于语义法律结论。
- `claim_clarity`复核必须检查独权载体分工：多组公式、集中符号定义和跨阶段动作只能触发人工简要性复核，不能仅凭字符数下结论；但缺少载体分配和复核决定时不得宣称审查完整。
- 从属权利要求应读取 `claim-architecture.json` 的继承拓扑；节点均已出现不等于连接关系能够在继承后同时成立。
- 方法权利要求存在流程图时，应读取 drawing brief v4 的步骤、判断和循环绑定；图号存在和术语命中不能替代步骤同构审查。
- `priority_entitlement_effective_date`、`claim_level_priority`、`partial_multiple_priority` 与 `article_24_grace_period` 不能折叠为笼统的优先权形式问题。
- `computer_and_ai`、`chemical_and_biotech`、`traditional_chinese_medicine` 即使不适用，也必须有充分适用性证据形成 `NOT_APPLICABLE`，或作为明确 gap 保持审查不完整。

所有实体结论均为咨询性输出，不构成授权、可申报或专业确认。
