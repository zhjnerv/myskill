# 创造性防御地图设计稿

日期：2026-09-22

## 1. 问题与边界

当前在审查实务中，审查员常采用“D1 + D2 + 公知常识”的论证逻辑来判定显而易见。大多数具备授权前景的方案往往落在“争议地带”：各特征单独已被公开，但其耦合关系、条件约束、绑定集合或在 D1 语境下的作用未被教导。

**设计目标**：为“三步法”建立一个机器可判读的状态位。在起草阶段，量化评估凑齐权利要求中全部区别特征所需的最小对比文件篇数及作用一致性，进而为权利要求 1（争取宽度）与权利要求 1+2（保底授权）设定创造性风险水位标尺。
**边界**：本工具仅提供量化评估和风险标注，不构成也不替代人工法律结论，其输出始终为 `legal_effect=ADVISORY_ONLY`。

## 2. 合同 `cn-patent-inventive-step-map/v1` 完整 JSON Schema 草案

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "cn-patent-inventive-step-map/v1",
  "title": "创造性防御地图合同 v1",
  "type": "object",
  "required": ["schema_id", "case_id", "legal_effect", "source_artifacts", "references", "cells", "couplings", "claim_assessments"],
  "additionalProperties": false,
  "properties": {
    "schema_id": { "const": "cn-patent-inventive-step-map/v1" },
    "case_id": { "type": "string" },
    "legal_effect": { "const": "ADVISORY_ONLY" },
    "source_artifacts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["artifact_id", "path", "sha256"],
        "properties": {
          "artifact_id": { "enum": ["claims", "specification", "feature_ledger", "claim_architecture"] },
          "path": { "type": "string" },
          "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" }
        },
        "additionalProperties": false
      }
    },
    "references": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["ref_id", "role"],
        "properties": {
          "ref_id": { "type": "string" },
          "role": { "enum": ["closest", "combination", "background", "common_knowledge"] },
          "title": { "type": "string" },
          "date": { "type": "string" }
        },
        "additionalProperties": false
      }
    },
    "cells": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["feature_id", "ref_id"],
        "properties": {
          "feature_id": { "type": "string", "pattern": "^F[0-9]{3}$" },
          "ref_id": { "type": "string" },
          "disclosed": { "enum": ["yes", "partial", "no"] },
          "locator": { "type": "string" },
          "searched_scope": { "type": "string" },
          "function_in_ref": { "type": "string" },
          "function_match": { "enum": ["same", "different", "not_applicable"] },
          "common_knowledge_risk": { "enum": ["high", "medium", "low"] },
          "evidence_type": { "enum": ["教科书", "标准", "手册", "多篇背景文献", "无"] }
        },
        "additionalProperties": false
      }
    },
    "couplings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["feature_a", "feature_b", "dependency", "statement_anchor"],
        "properties": {
          "feature_a": { "type": "string", "pattern": "^F[0-9]{3}$" },
          "feature_b": { "type": "string", "pattern": "^F[0-9]{3}$" },
          "dependency": { "type": "string" },
          "statement_anchor": { "type": "string" }
        },
        "additionalProperties": false
      }
    },
    "claim_assessments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_set", "min_refs_to_cover", "same_function_cover", "coupling_evidence", "grade", "review"],
        "properties": {
          "claim_set": {
            "type": "array",
            "items": { "type": "integer" }
          },
          "min_refs_to_cover": { "type": "integer" },
          "same_function_cover": { "type": "boolean" },
          "coupling_evidence": { "type": "boolean" },
          "grade": { "enum": ["novelty_risk", "weak", "defensible"] },
          "review": {
            "type": "object",
            "required": ["status", "statement", "reviewed_at"],
            "properties": {
              "status": { "enum": ["pending", "approved", "revise"] },
              "statement": { "type": "string" },
              "reviewed_at": { "type": "string" }
            },
            "additionalProperties": false
          }
        },
        "additionalProperties": false
      }
    }
  }
}
```

*注：`references` 必须固定包含一条虚拟条目 `ref_id="COMMON_KNOWLEDGE"`。`cells` 中，对于 yes/partial，`locator` 必填（段落/图号）；对于 no，`searched_scope` 必填。对于 COMMON_KNOWLEDGE 条目，不使用 `disclosed` 等字段，而必须填写 `common_knowledge_risk` 与 `evidence_type`。*

## 3. 验证器算法

**前置与门禁**：
- 区别特征集合来自台账中 `classification=distinguishing` 且其 `claim_sites` 落入当前 `claim_set`（如 [1] 或 [1,2]）的特征。
- `not_searched` 状态的特征不得进入，`cells` 不得留空；若 `locator` 或 `searched_scope` 缺失，则直接 fail-closed。

**指标复算（复杂度与规则）**：
1. **覆盖条件**：
   - 某对比文件当且仅当 `disclosed=yes` 时视为覆盖该特征；`disclosed=partial` 不计为覆盖。
   - 对于 COMMON_KNOWLEDGE，若 `common_knowledge_risk=high`，则视为被公知常识覆盖。
2. **`min_refs_to_cover` (最小集合覆盖)**：
   - 枚举特征被哪些 ref 覆盖，求覆盖全集所需的最小 ref 数量。
   - 复杂度：由于单个权利要求的特征数通常 ≤ 15，允许 $O(2^N)$ 子集枚举。若特征数 > 15，触发资源超限（fail-closed），报告计算无法完成。
3. **`same_function_cover`**：
   - 判定是否存在 ≤2 篇文献（含 COMMON_KNOWLEDGE），能够以 `function_match=same` 覆盖全部区别特征。
4. **`coupling_evidence`**：
   - 检查 `couplings` 记录，若存在至少一对特征 A 与 B 的耦合，且**没有任何**单篇 ref 能够同时以 `disclosed=yes` 覆盖 A 与 B，则置为 true。

**分级规则（按优先级依次判定，命中即止）**：
1. `min_refs_to_cover = 1` → `novelty_risk`（耦合证据不能豁免：单篇已整体公开时不存在“未被教导的联动”）。
2. `min_refs_to_cover >= 3`，或 `coupling_evidence = true`，或（`min_refs_to_cover = 2` 且全部 `function_match=different`）→ `defensible`。
3. 其余（`min_refs_to_cover = 2` 且 `same_function_cover = true`，且无耦合证据）→ `weak`。

**无文献覆盖**：若某区别特征对全部 ref（含 COMMON_KNOWLEDGE）均为 `disclosed=no` 且 `common_knowledge_risk != high`，则该特征“未被已检索出口覆盖”，`min_refs_to_cover` 记为 `null` 并按 `>= 3` 处理进入分级；报告必须同时输出该特征的 `searched_scope` 汇总，提醒该结论仅相对已检索出口成立（与台账 `not_found_in_searched_outlets` 的语言纪律一致）。

**耦合证据的反幻觉约束**：`couplings[].statement_anchor` 必须能在当前说明书正文中逐字定位（因此 `source_artifacts` 绑定 `specification`），且 `feature_a`、`feature_b` 均须为本 claim_set 内的 distinguishing 特征；锚点定位失败 → `ISM-COUPLING-001`，该耦合不计入 `coupling_evidence`。

**状态门拦截**：
- `claim_set=[1]` 允许评价为 `weak`。
- `claim_set=[1,2]` 必须达到 `defensible` 且人工复核 `review.status=approved`。否则，验证器返回退出码 2。

**核心保护点挂钩**：
- 提取 claim-architecture 中登记的 `core_protection_point.feature_ids`。
- 验证器需复算并验证：该组特征必须是使 `[1,2]` 能够达到 `defensible` 状态的“最小特征集”之一（即若移除其中任何特征，`[1,2]` 将跌落为 `weak` 或更低）。若不一致，报 ISM-CORE-* 错误码。

## 4. 错误码表

| 错误码 | 触发条件 | Message 样式 |
|---|---|---|
| `ISM-SOURCE-001` | 绑定工件的路径或 sha256 发生改变且不匹配 | 来源 artifact (如 feature_ledger) 哈希已变，地图失效 |
| `ISM-CELL-001` | cell 的必要字段缺失（如 yes 时无 locator） | 特征 F001 在 D1 disclosed=yes，但未提供 locator |
| `ISM-COVER-001` | 区别特征数超过 15，计算最小覆盖子集超限 | 区别特征数超限，fail-closed 防止计算爆炸 |
| `ISM-GRADE-001` | 人工声明的 grade 与复算结果不一致 | 声明 grade=defensible，复算实际应为 weak |
| `ISM-CORE-001` | 架构中登记的核心特征集不是防御最小支撑集 | 架构合同中的 feature_ids 不满足 defensible 最小支撑条件 |
| `ISM-COUPLING-001` | 耦合记录的说明书锚点无法逐字定位，或特征不在本 claim_set 内 | 耦合 F010↔F011 的 statement_anchor 未在说明书中找到，不计入 coupling_evidence |
| `ISM-REF-001` | references 缺少 `COMMON_KNOWLEDGE` 虚拟条目，或其 role 不是 common_knowledge | 必须固定登记 COMMON_KNOWLEDGE 条目 |
| `ISM-REVIEW-001` | claim_set=[1,2] 并非 approved 却被放行 | claim_set=[1,2] 必须为 defensible 且 review.status=approved |

## 5. 流程位置

- **新阶段**：在 2-D 区别特征表台账之后，进入架构门之前新增 `inventive-step-gate`。
- **阶段 5a 支撑**：攻防环节直接消费 `cells` 作为特征弹药表，快速判断特征是否被击破。审查意见陈述骨架从 `claim_assessments` 报告生成。
- **说明书支持**：背景技术章节需根据地图直接指出 D1 的具体缺陷；发明内容部分需展开说明组合机理链。建议特征台账 `feature-ledger v2` 在顶层新增 `combined_effects[]` (含 feature_ids, effect, why_not_individually, spec_anchor)，以支撑说明书写作。

## 6. 两个虚构通用案例的完整走查

### 6.1 机械/流体案
**场景**：仅在温度回落后才开启回流阀，且阀位由相邻部件决定。
- **References**: D1(closest), COMMON_KNOWLEDGE.
- **Cells**:
  - F001 (温度回落后开阀)：D1 (`disclosed=no`, `searched_scope`="D1全文及常规阀控制"); COMMON_KNOWLEDGE (`common_knowledge_risk=low`, `evidence_type`="无").
  - F002 (阀位由相邻部件决定)：D1 (`disclosed=yes`, `locator`="图3", `function_match`="different"); COMMON_KNOWLEDGE (`common_knowledge_risk=high`, `evidence_type`="手册").
- **Couplings**:
  - `feature_a`: F001, `feature_b`: F002, `dependency`: 阀位决定与开阀时机的联动以锁定防溢出, `statement_anchor`: "段落0045".
- **Claim Assessments 复算**:
  - `claim_set=[1]` (含 F001)：无文献 cover F001，无法完成覆盖，`min_refs_to_cover` 视作无穷或最大，`grade=defensible`。
  - `claim_set=[1,2]` (含 F001, F002)：同样无法完全覆盖 F001，`min_refs>=3` 等效安全，`coupling_evidence=true`，`grade=defensible`，复核 `approved`。

### 6.2 软件案
**场景**：请求标识与会话/设备标识绑定，且仅在播放完成后才释放。
- **References**: D1(closest), D2(combination), COMMON_KNOWLEDGE.
- **Cells**:
  - F010 (双标识绑定)：D1 (`disclosed=partial`, `locator`="段落0012"); D2 (`disclosed=yes`, `locator`="段落0030", `function_match`="same").
  - F011 (播完释放)：D1 (`disclosed=yes`, `locator`="段落0015", `function_match`="same"); D2 (`disclosed=no`, `searched_scope`="D2及播放器缓存逻辑").
- **Couplings**:
  - `feature_a`: F010, `feature_b`: F011, `dependency`: 绑定标识作为播完释放的唯一验证凭证以防盗链, `statement_anchor`: "段落0080".
  - 注：D1、D2 各覆盖一半，不存在单篇 disclosed=yes 覆盖二者。
- **Claim Assessments 复算**:
  - `claim_set=[1]` (若仅含 F010)：被 D2 一篇完全覆盖，`min_refs_to_cover=1`，导致 `grade=novelty_risk`（若并入前序则可能为 weak）。
  - `claim_set=[1,2]` (含 F010, F011)：覆盖必须 D1+D2，`min_refs_to_cover=2`，且两格 `function_match=same` → 若无耦合证据将判 `weak`；但存在说明书可定位的耦合且无单篇文献同时覆盖二者，`coupling_evidence=true`，按优先级第 2 条判 `grade=defensible`，复核 `approved`。这正是“争议地带”被机器状态位承认的典型路径。

## 7. 对既有合同的改动清单

- **feature-ledger v2**：无需大幅改变，建议增加 `combined_effects[]` 支持耦合。`cells` 内的 `function_in_ref` 是对比文件域判断，保留在防御地图中，不回写台账。
- **claim-architecture v1**：在 `source_artifacts` 中新增引用 `inventive-step-map.json` 的 sha256，绑定核心保护点的防线验证数据。
- **工作流与 SKILL.md**：在 `cn-patent-application-creator` 的阶段 2-D 后插入一行修改：“新增 `2-E 创造性防御地图门`，通过后进入 3 权利要求架构”，更新阶段门的检查内容。

## 8. 测试计划

- **正例**：给定标准特征集合与 D1、D2、公知常识组合，断言复算出的 `min_refs_to_cover`、`same_function_cover` 和 `grade` 绝对一致。
- **反例触发**：
  - 改动 `feature-ledger.json` 但不更新本合同的 sha256（抛 ISM-SOURCE-001）。
  - 配置 `disclosed=yes` 但删去 `locator`（抛 ISM-CELL-001）。
  - 传入 16 个有效特征（抛 ISM-COVER-001），断言 fail-closed。
  - 在 JSON 人工将 weak 改为 defensible（抛 ISM-GRADE-001）。
  - 架构合同指向了与防御地图无助力的特征（抛 ISM-CORE-001）。
  - 将 claim_set=[1,2] 的 review status 置为 pending 并尝试通关（抛 ISM-REVIEW-001）。
- **资源限制**：设置穷举子集的执行超时（如 2 秒内必须完成集合覆盖运算）。
- **幂等性与来源过期**：对相同 JSON 执行 10 次输出与退出码应不变，限制集合算法超时必须返回 4。

## 9. 主会话审阅批注（2026-09-22）

以下为对本稿的审阅结论，实现时以此为准：

1. 分级规则已改为显式优先级（novelty_risk → defensible → weak），修正了 6.2 案例按原规则应判 weak 的矛盾；耦合证据不能豁免 `min_refs_to_cover = 1`。
2. `couplings` 新增说明书锚点逐字复算与 claim_set 归属检查（`ISM-COUPLING-001`），否则模型可无成本声明耦合以拿到 defensible。
3. `source_artifacts` 增加 `specification`；`references.role` 增加 `common_knowledge`，并新增 `ISM-REF-001`。
4. Schema 中 `cells` 的字段条件（非 CK 条目必填 `disclosed`；yes/partial 必填 `locator`；no 必填 `searched_scope`；CK 条目必填 `common_knowledge_risk` 与 `evidence_type`）由验证器执行，schema 层用 `if/then` 表达为可选增强。
5. 6.1 案例中“无文献覆盖”按上文新增语义处理，报告须携带 `searched_scope` 汇总。
6. 开放问题 1–3 需专利代理师拍板后再实现；建议默认：partial 不计覆盖但在报告中计数并在 ≥ 区别特征数一半时输出 REVIEW；medium 强制人工改判 high/low；多独权按“每个独权自身 + 其核心从属项”各自成组评估，不互相豁免。

## 10. 开放问题

1. **Partial 的权重计算**：`disclosed=partial` 虽不计入 direct cover，但在实际实务中容易被与公知结合击穿。是否需在此地图的 `weak` 判断中，加入对 `partial` 数目过高时的降级拦截？
2. **公知常识 Medium 的处理**：`common_knowledge_risk=medium` 是直接视作 0.5 篇对比文件进入算计，还是硬性要求专利代理师必填定性（强制转为 high 或 low）？
3. **多独权的 Claim Set 组合方式**：当存在方法和系统多项独权时，`claim_set` 是以各自组合单独证明 defensible，还是可以通过映射直接互相豁免？
