# 权利要求架构合同

`cn-patent-claim-architecture/v1` 位于特征台账与绘图合同之间，用于阻止四类不能靠关键词命中发现的缺陷：

1. 独立权利要求同时承载大量公式、符号定义、实施细节和运行时动作，虽内容完整但不简要；
2. 从属权利要求继承父项后，新增连接与父项既有连接不能同时成立；
3. 方法权利要求、说明书和流程图使用不同步骤编号、动作边界或循环返回点；
4. 最核心的区别特征没有落在紧随独权的权利要求 2，导致独权失守时缺少第一退守位。

Schema：`claim-architecture-schema-v1.json`。

## 输入与执行

合同必须绑定当前权利要求书、说明书和 `feature-ledger.json` 的 SHA-256。完成权利要求和说明书后执行：

```bash
python scripts/validate_claim_architecture.py \
  --contract "<claim-architecture.json>" \
  --case-dir "<案件根目录>" \
  --claims "<权利要求书.md>" \
  --specification "<说明书.md>" \
  --output "<claim-architecture-validation.json>"
```

退出码 `0` 才能进入绘图合同阶段。退出码 `2` 表示结构门未通过；退出码 `3` 表示输入、路径、编码或JSON无效。

## 独权载体分工

`independent_claims` 对每项独立权利要求登记：

- 可明确识别的公式块数量；
- 集中符号定义数量；
- 涉及的执行阶段；
- 公式、符号定义、实施细节、控制时序分别放在独权、从权或说明书的决定及理由；
- 专利代理师或独立审查者的简要性复核状态。

公式块不少于3、符号定义不少于5或跨越不少于3个执行阶段时，验证器输出 `ARCH-CARRIER-COMPLEXITY`，要求人工复核。该 finding 不以字符数直接认定法律缺陷；公式/符号没有逐项载体分配、或者合同低报可从文本确认的公式数量时，必须阻断。复核未批准不阻断，写入待决清单。

## 父从权继承拓扑

`claim_topologies` 不是记录孤立部件名称，而是记录连接边：

```text
source_node_id
→ target_node_id.target_port
→ relation_type
→ exclusive_target_port
```

验证器递归合并全部父项关系，再加入本项关系。若同一 `exclusive_target_port` 在继承后出现两个不同来源，输出 `ARCH-TOPOLOGY-CONFLICT`。

例如父项限定：

```text
温度传感单元 → 回流控制模块.temperature_input
```

从项又限定：

```text
温度传感单元 → 信号调理电路 → 回流控制模块.temperature_input
```

则从项继承后存在冲突。正确做法是在父项使用能够同时覆盖直接和间接实施方式的一般关系，再由从项限定中间模块。

## 方法步骤冻结

`method_claims` 为每项方法权利要求登记：

- 连续且唯一的步骤号；
- 每一步在权利要求中的逐字动作；
- 说明书逐字锚点；
- 判断节点的前置步骤及真假分支目标；
- 循环的起点、返回步骤和条件。

动作必须能在当前权利要求中定位，说明书锚点必须能在当前说明书中定位。合同步骤集合与权利要求实际 `S1—Sn` 集合或顺序不一致时，输出 `ARCH-METHOD-ISOMORPHISM` 并阻断。

## 核心保护点登记

`core_protection_point` 登记最核心的保护点必须落在权利要求 2（直接且仅从属于权利要求 1）。指定承载该保护点的区别特征编号、对标检索结论的说明，并留下人工复核决定。验证器执行四类校验：

- `ARCH-CORE-SHAPE`：权利要求 2 号与父权要求 1 号、非空且无重复的特征 ID 数组、说明文本；
- `ARCH-CORE-CLAIM`：权利要求 2 必须存在、仅引用权利要求 1、拓扑一致；
- `ARCH-CORE-FEATURE`：每项特征必须在台账中找到、分类为 distinguishing、claim_sites 含权利要求 2；
- `ARCH-CORE-REVIEW`：复核状态必须为 pending、approved 或 revise；复核未批准不阻断，写入待决清单。

## 与绘图合同的交接

新案件的 `cn-patent-drawing-brief/v4` 必须把本合同作为 `claim_architecture` 来源绑定。方法流程图的 `step_bindings`、`decision_bindings` 和 `loop_bindings` 必须与本合同完全一致。图框文字必须等于步骤号加权利要求动作；空间不足时扩大节点或画布，不得自行概括技术动作。

## 边界

本验证器证明结构化登记、来源新鲜度、继承关系和步骤同构，不证明：

- 独立权利要求最终必然符合清楚、简要要求；
- 未登记为排他端口的关系必然能够共存；
- 权利要求得到说明书支持或具备新颖性、创造性；
- 核心保护点的特征在法律上确为最具创造性的区别特征。
