# 权利要求架构与流程图同构门实施验证记录

日期：2026-09-03

## 问题来源

本次改造来自某高校电子类案件预审意见中的三项指摘：

- 独立方法权利要求同时展开多组公式、符号定义和实施动作，缺少载体分工复核；
- 从属权利要求增加中间模块后，与父项继承的直接连接关系冲突；
- 权利要求、说明书和流程图采用不同步骤边界，图中步骤号与权利要求错位。

## 已落地

### 权利要求架构门

新增：

- `cn-patent-claim-architecture/v1`；
- `validate_claim_architecture.py`；
- 独权载体分工、人工简要性决定和文本可观察公式数量复算；
- 父从权关系递归合并和排他端口冲突检查；
- 方法步骤、说明书锚点、判断节点和循环返回点冻结；
- 当前权利要求书、说明书、特征台账SHA-256绑定。

### 绘图合同v4

新增：

- `cn-patent-drawing-brief/v4`；
- `claim_architecture`来源绑定；
- `step_bindings`、`decision_bindings`、`loop_bindings`；
- 图框文字必须等于步骤号加权利要求动作原文；
- 图中步骤/判断节点集合不得多于或少于权利要求架构合同；
- 判断分支目标和循环返回步骤必须一致；
- 权利要求架构合同变化后，旧绘图合同因哈希不一致而失效。

### 工作流和规则

已同步：

- `cn-patent-application-creator`；
- `cn-patent-diagram-generator` 4.0.0；
- `cn-patent-workflow`及阶段路由；
- 权利要求规则矩阵、综合审查实体规则和跨文件规则；
- README、CHANGELOG、质量门和Draw.io执行规则。

## 故障注入

新增回归覆盖：

- 高复杂度独权未批准；
- 文本存在公式而合同低报；
- 独权、全部权利要求拓扑或方法步骤合同漏登记；
- 父项直接连接与从项中间模块连接在继承后冲突；
- 权利要求步骤缺失或顺序不一致；
- 循环指向不存在或错误步骤；
- 流程图漏步骤、多步骤、合并步骤或自行概括文字；
- 图面存在未绑定判断节点；
- 循环返回目标错误；
- 旧权利要求架构合同哈希继续用于新图。

## 验证结果

- 全量测试：`198 passed, 107 subtests passed`；
- 包边界：PASS；
- Python编译：PASS；
- Skill目录全部JSON解析：PASS；
- `git diff --check`：PASS；
- 两个重大修改Skill的Harness Failure Audit：PASS，均为0 hard、0 warning；
- 安全扫描：无critical/high。现有外部进程调用均使用参数数组和`shell=False`；绘图Skill已补充本地进程、文件边界和`LOCALAPPDATA`用途披露。

## Skill Lint边界

- `cn-patent-application-creator`：Instruction Stability为`NOT_VERIFIED`，原因是该大型既有Skill尚无覆盖全部历史硬约束的追踪合同、候选外基线和三轮签名产物。不能把本次领域测试通过扩大为整个Skill多轮稳定。
- `cn-patent-diagram-generator`：v4稳定性合同结构可解析，新增步骤同构约束具有正例、mutation和历史反例；仍因缺少候选外独立硬约束基线而为`NOT_VERIFIED`。
- 上述`NOT_VERIFIED`是外部证据闭环不足，不是领域验证器失败。领域脚本、回归测试、包边界和静态Harness审查均已通过。

## 证据边界

本次机器门能够证明登记关系、新鲜度、排他端口冲突和步骤同构；不能自动证明：

- 权利要求最终必然清楚、简要或得到说明书支持；
- 未声明为排他端口的连接一定能够共存；
- 技术方案具备新颖性、创造性或授权前景；
- Skill已经获得候选外签名的三轮指令稳定性证明。
