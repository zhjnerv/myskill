# 实施与验证记录

日期：2026-09-01

## 已落地

- 新增 `cn-patent-feature-ledger/v2`，将输入、处理主体、动作、输出、下游、动作阶段、方法—系统映射和异常终态纳入台账。
- `build_feature_ledger.py` 兼容 v1 回放并严格复算 v2；报告升级为 v2，绑定输入哈希并声明证据范围。
- 新增 `cn-patent-drawing-brief/v3`，要求单图唯一问题、阅读方向、层级、复杂度预算、独立线路通道、正常/异常出口和 `spec_assertions`。
- 新增 `cn-patent-drawing-visual-review/v2`，绑定绘图合同、导出报告和最终 PNG，并要求 100%/缩小比例及逐项观察记录。
- 绘图验证器对 v3/v2 新合同执行新鲜度与观察记录检查，旧 v2/v1 仅保留历史兼容。
- DOCX 组装报告升级为 `cn-patent-docx-assembly/v2`，逐文件绑定四文书和嵌入图片；新增 `verify_docx_assembly.py`。
- 阶段门对新案件要求 feature ledger v2；总入口、阶段路由、跨文件规则、README 和 CHANGELOG 已同步。
- 修复 `verify_package.py` 误扫描 `.git` 内部备份的问题。

## 验证结果

- 全量测试：`177 passed, 107 subtests passed`。
- 新增/受影响定向测试：`36 passed`。
- 包边界检查：`PASS`。
- Python 编译检查：通过。
- JSON 解析检查：通过。
- `git diff --check`：通过。

## Skill Lint

- 安全扫描：无 critical/high；现有外部进程调用和环境变量定位被标记为 medium/low 提醒，均使用参数数组且属于既有 Draw.io/Word/EPO provider 能力。
- Instruction Stability 静态审查：`NOT_VERIFIED`。原因是缺少候选外签名基线、held-out 正反例和三轮真实产物回执；这类外部评估证据未在本次代码修改中伪造。
- 已同步 `cn-patent-diagram-generator` 的 Skill 版本与稳定性合同版本为 `3.0.0`。

## 使用边界

新增机器门禁证明的是合同完整性、引用关系、哈希身份和记录新鲜度，不替代专利代理师对清楚性、支持、必要技术特征、新颖性、创造性和最终图面观感的专业判断。
