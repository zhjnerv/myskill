# 实施计划

## P0：合同和硬门禁

1. 新增 feature ledger v2 Schema；扩展台账脚本兼容 v1、严格校验 v2。
2. 新增 drawing brief v3 与 visual review v2 Schema；扩展绘图合同和最终验证脚本。
3. 增加数据流、方法—系统、异常路径、图文关系的正反例测试。
4. DOCX 报告升级为 v2，新增新鲜度验证器和无 Word 依赖的哈希回归测试。

## P1：工作流接线

1. 修改 `cn-patent-application-creator/SKILL.md`，把 v2 台账和数据流复算门插入权利要求与说明书阶段。
2. 修改 `cn-patent-diagram-generator/SKILL.md` 和参考文档，要求 v3 合同、v2 视觉记录。
3. 修改总入口 `cn-patent-workflow` 的阶段图和 `stage-map.md`，明确失效传播。
4. 修改 `cn-patent-reviewer/references/cross-document-rules.md`，将图文表达范围、动作阶段、异常闭合列为语义审查输入。
5. 修改 README，公开新的生成闭环和报告边界。

## P2：验证与收尾

1. 修复 `verify_package.py` 扫描 `.git` 内部备份导致的假失败。
2. 运行所有可用单元测试；若环境缺少 pytest，则安装项目已声明的 dev 依赖或用标准库直接执行新增验证器的正反例。
3. 运行 `python3 scripts/verify_package.py`。
4. 对重大修改后的 Skill 运行 Skill Lint 静态审查；无法取得外部签名/三轮 Harness 证据的层明确标记 `NOT_VERIFIED`。
5. 在本目录写入 `04-verification-report.md`，列出实际修改、测试结果、未验证边界和后续案件迁移说明。

## 预计修改文件

### 新增

- `skills/cn-patent-application-creator/references/feature-ledger-schema-v2.json`
- `skills/cn-patent-application-creator/scripts/verify_docx_assembly.py`
- `skills/cn-patent-diagram-generator/references/patent-drawing-brief-schema-v3.json`
- `skills/cn-patent-diagram-generator/references/visual-review-schema-v2.json`
- `tests/test_cn_feature_ledger_v2.py`
- `tests/test_cn_docx_evidence_freshness.py`
- 本目录的分析、计划和验证记录

### 修改

- `skills/cn-patent-application-creator/scripts/build_feature_ledger.py`
- `skills/cn-patent-application-creator/scripts/assemble_application_docx.py`
- `skills/cn-patent-application-creator/SKILL.md`
- `skills/cn-patent-application-creator/references/docx-assembly.md`
- `skills/cn-patent-diagram-generator/scripts/validate_drawing_brief.py`
- `skills/cn-patent-diagram-generator/scripts/verify_patent_drawings.py`
- `skills/cn-patent-diagram-generator/SKILL.md`
- `skills/cn-patent-diagram-generator/references/drawio-execution.md`
- `skills/cn-patent-diagram-generator/references/quality-gates.md`
- `skills/cn-patent-workflow/SKILL.md`
- `skills/cn-patent-workflow/references/stage-map.md`
- `skills/cn-patent-reviewer/references/cross-document-rules.md`
- `tests/test_patent_diagram_generator_zh_v2.py`
- `scripts/verify_package.py`
- `README.md`

## 兼容策略

- v1 feature ledger、v2 drawing brief、v1 visual review保留用于旧案件回放；
- 新案件在工作流文档中强制使用 feature ledger v2、drawing brief v3、visual review v2；
- 不引入第三方运行时依赖；所有新增确定性校验使用 Python 标准库；
- 不修改目录分层，不复制本地法源，不把语义判断改造成关键词硬判定。
