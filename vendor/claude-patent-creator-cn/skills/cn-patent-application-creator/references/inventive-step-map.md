# 创造性防御地图 (Inventive Step Map)

## 1. 用途
用于在进入权利要求架构门之前，系统化评估案件的创造性防线（Inventive Step Map）。它将“区别特征”与“对比文件及公知常识”进行映射计算，提前暴露被多篇文献组合击穿的风险，确保最终交付权利要求的防御力。

## 2. 字段集
- `source_artifacts`: 绑定的上游文件指纹，必须包含 claims、specification、feature_ledger、claim_architecture。
- `references`: 参引文献集合，含对比文件和必选虚拟条目 `COMMON_KNOWLEDGE`。
- `cells`: 特征覆盖矩阵。
  - 对于对比文件：描述 `disclosed`（yes/no/partial），`locator` 或 `searched_scope`。
  - 对于公知常识：描述 `common_knowledge_risk`（high/medium/low）及 `evidence_type`。
- `couplings`: 多个特征间的耦合关系记录，需说明 `dependency` 并包含在说明书可严格定位的 `statement_anchor`。
- `claim_assessments`: 记录各个子集合的防御等级评估复算结果。

## 3. 分级规则
针对给定的特征集合，计算使这些特征被完全覆盖的最少文献数 `min_refs_to_cover`：
1. **novelty_risk**: 若 `min_refs_to_cover == 1`，则被单篇文献完全覆盖，属新颖性风险或无创造性。
2. **defensible**: 若 `min_refs_to_cover >= 3`，或 `min_refs_to_cover == 2` 但至少满足其一：(a) 存在有效耦合 `coupling_evidence=true`；(b) 所有被不同文献覆盖的特征其 `function_match` 均为 `different`。
3. **weak**: 不满足上述条件的其他情形，通常指 `min_refs_to_cover == 2` 但缺乏协同或用途不同的充分证据。

## 4. 错误码与待决键对照表

### 错误码 (Error)
| 错误码 | 描述 |
| --- | --- |
| `ISM-SOURCE-*` | 来源缺失、哈希过期或绑定集合不正确 |
| `ISM-REF-001` | 缺少 `COMMON_KNOWLEDGE` 虚拟条目或 role 错误 |
| `ISM-CELL-*` | 缺 disclosed/locator/searched_scope，或者未完整覆盖特征×文献矩阵 |
| `ISM-COVER-001` | 区别特征数 > 15，防计算爆炸保护 |
| `ISM-COUPLING-001`| 耦合锚点在说明书中定位失败，或特征不在本集内 |
| `ISM-CLAIMSET-001`| 合同中 claim_set 与权利要求依赖拓扑推导集合不匹配 |
| `ISM-GRADE-001` | 声明 grade 与复算 grade 不一致（禁止人工篡改复算结果） |

### 待决事项 (Pending Decision)
| 待决键 (Key) | 描述 |
| --- | --- |
| `inventive.core_set_not_defensible` | 核心特征集不足以支持 defensible，建议补充机理链或更换 |
| `inventive.assessment_review_pending` | review.status 非 approved |
| `inventive.core_point_not_minimal` | 架构中登记的核心保护点并非使该组特征 defensible 的最小子集之一 |
| `inventive.partial_disclosure_heavy` | `disclosed=partial` 特征数大于或等于区别特征总数一半 |
| `inventive.common_knowledge_medium` | 公知常识判定为 medium，程序将其保守视同 high，交人工定夺 |
| `inventive.core_dependent_missing` | 缺失引独权的第一直接从权，无核心保护点 |

## 5. 与 core_protection_point 的关系
架构合同中的 `core_protection_point`（核心保护点）代表代理师选定的攻防焦点。防线地图必须验证：该核心特征集合，必须是使本专利处于 `defensible` 状态的“最小特征支撑集”之一。若其中有多余冗余特征，则该特征本应下放。

## 6. 边界
本验证主要执行确定性的集合覆盖、哈希校验及锚点查找。它不负责对发明内容的语义评估，也不验证耦合事实能否说服审查员，其作用在于限制随意组合特征的草率行为。
