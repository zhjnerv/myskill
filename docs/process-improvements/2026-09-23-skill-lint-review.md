# Skill 质量意见报告

**报告日期**：2026-09-23
**审查对象**：`/data/SynologyDrive/PC同步/GitHub/claude-patent-creator-cn`（git `d0c68d0`）
**Skill 名称**：`claude-patent-creator-cn` monorepo（7 个 Skill）
**审查范围**：发布前验收（正式验收 + 候选绑定证据门禁 + 静态稳定性评估）
**审查配置**：通用规则（skill-lint 2.9.0）；项目规则取自仓库 `AGENTS.md`
**归档位置**：`archive/20260923_000500_claude-patent-creator-cn/`

## 零、审查单元发现

| 单元路径 | 类型 | 是否纳入 | 说明 |
|----------|------|----------|------|
| `skills/cn-patent-workflow` | 已确认 Skill | 是 | 唯一路由入口，无脚本 |
| `skills/cn-patent-application-creator` | 已确认 Skill | 是 | 起草主链，510 行 SKILL.md，13 个脚本 |
| `skills/cn-patent-claims-analyzer` | 已确认 Skill | 是 | 权利要求原始检查器 |
| `skills/cn-patent-specification-reviewer` | 已确认 Skill | 是 | 说明书支持矩阵 |
| `skills/cn-patent-formalities-reviewer` | 已确认 Skill | 是 | 形式检查器 |
| `skills/cn-patent-reviewer` | 已确认 Skill | 是 | 三检查器编排 + 独立验证 |
| `skills/cn-patent-diagram-generator` | 已确认 Skill | 是 | 附图领域适配，唯一带稳定性合同的单元 |
| `README.md`、`CHANGELOG.md`、`LICENSE`、`AGENTS.md`、`pyproject.toml`、`.claude-plugin/`、`.codex-plugin/`、`scripts/` | 仓库治理文件 | 是（发布治理模块） | 公开 GitHub 仓库 + 两个插件清单，按发布规则审 |
| `references/`（仓库根） | 共享法源 | 是（引用可达性） | 各 Skill 以 `references/cn-legal-sources/...` 相对根目录引用 |
| `docs/process-improvements/` | 仓库治理文件 | 是（隐私模块） | 不进分发树，但在公开 git 历史中 |
| `.local-case-archive/`、`tests/` | 排除 | 否 | 客户材料 / 开发测试，不属发布单元 |

## 一、总体意见

**结论**：有条件通过
**主要原因**：6 个含脚本的 Skill 均通过候选绑定 Harness 门禁（真实执行 + 故障注入 + 哈希绑定），安全评估无 critical/high；但分发树与公开文档中残留真实客户案件信息、附图 Skill 存在以本地路径书写的外部引用、起草 Skill 阶段门措辞前后自相矛盾，三项均属 Hard Fail，须在下一次发布前关闭。指令稳定性 7 个单元均为 `NOT_VERIFIED`，任何"多轮稳定"表述在取得签名基线前都不得出现。

| 维度 | 状态 | 意见摘要 |
|------|------|----------|
| 审查单元发现 | ✅ | 7 个最小单元 + 仓库治理文件识别无误 |
| 结构与文件 | ⚠️ | 附图 Skill 4 处引用不可达；6 个未被引用的 v1 schema；`scripts/` 内混入测试与演示文件；`__pycache__` 残留（未入 git，不分发） |
| Frontmatter 与触发 | ⚠️ | `name` 与目录一致；6/7 缺 `metadata.version`，仅附图 Skill 有；`claims-analyzer` description 未用"应在…时使用／不要用于"格式 |
| 配置与隐私 | ❌ | 起草 SKILL.md 与 claim-architecture.md 使用真实客户案件的发明名称与附图标记清单作示例；复盘文档含真实高校名与案件项目名；两处本地绝对路径 |
| 安全评估 | ✅ | 0 critical/high；9 medium 均为 `shell=False` 参数数组的外部进程调用且已披露；3 low 环境变量读取已在 provider-contracts.md 说明 |
| 发布治理 | ⚠️ | 版本 0.2.0（2026-09-06）之后 31 条 Unreleased 变更未发版；LICENSE/plugin.json/README 一致 |
| 工作流与输出 | ⚠️ | 命令可执行、参数与 argparse 一致；起草 SKILL.md 510 行且同一根路径前缀重复 23 次；claims-analyzer 文档写错输出 schema 名 |
| 业务流深度 | ✅ | Trigger/Intake/Reasoning/Output/Safety 五层在 7 个单元均可辨；ADVISORY_ONLY 边界一致 |
| 可评估性 | ⚠️ | Hard Fail、退出码、schema 明确；三个原始检查器缺输出样例；规则矩阵混入非脚本产出的 rule_id 且无产出者列 |
| Harness 可靠性 | ✅ | 6/7 取得 `HARNESS_REVIEW_VERIFIED`；workflow 为纯路由，无可执行验证路径（`NOT_VERIFIED`，不适用） |
| 指令稳定性 | ❌→`NOT_VERIFIED` | 附图 Skill 有 13 条约束合同与 37 用例但无候选外签名基线（ISG-006）；其余 6 个无约束追踪合同（ISG-001/003/004/005）；正向夹具为 v2 报告，未覆盖 v4 观测量 |

## 二、严重问题

### 1. 分发树与公开文档残留真实客户案件信息

- **位置**：
  - `skills/cn-patent-application-creator/SKILL.md:343-345`、`:355`（"附图说明"与"附图标记清单"示例直接使用某真实预审案件的发明名称、模块名与标记清单）
  - `skills/cn-patent-application-creator/references/claim-architecture.md:55`、`:61`（同一案件的部件连接示例）
  - `docs/process-improvements/2026-09-03-claim-architecture-gates/verification-report.md:7`（真实高校名 + 案件项目名 + "预审意见第 5、7、8 项"）
  - `docs/process-improvements/2026-09-15-status-audit-remediation/report.md:64`、`:67`（本地绝对路径 `/home/<user>/.codex/...`）
- **所属模块**：`configuration-privacy-standards.md`
- **问题说明**：前两处进入 `verify_package` 白名单的 `.md`，随 `install_codex_skill.py` 复制到每个用户的 `$CODEX_HOME/vendor/`；第三处虽不进分发树，但仓库公开在 GitHub，git 历史（`49bb423`、`f3d7be3`）可回溯。案件名称、模块清单与"预审意见第 N 项"组合可反查到具体客户申请。
- **影响**：违反 `AGENTS.md` "不提交客户案件"；触发 Hard Fail "公开文件包含明显真实客户名、案件项目或可反查组合信息"；对代理机构而言是保密义务问题，不是格式问题。
- **修正方式**：
  1. SKILL.md:343-355 与 claim-architecture.md:55-61 改用虚构通用示例（如"图 1 是本发明冷却回路控制系统的结构示意图"、"100-温度传感器、200-回流阀"），并与 `distinguishing-feature-patterns.md` 的虚构示例风格统一。
  2. `docs/process-improvements/2026-09-03-.../verification-report.md:7` 改为"来自某高校案件的预审意见第 5、7、8 项"；两处 `/home/<user>` 路径改为 `<skill-lint>/scripts/...`。
  3. 评估是否需要重写 git 历史（`git filter-repo`）；若仓库已被他人 clone，重写无法追回，至少在 CHANGELOG 记录已脱敏并对客户风险作内部评估。
- **为什么错(原理)**：Skill 是可分发工件，示例即公开内容；用真实案件当示例等于把客户材料打包进产品。
- **最优设计**：示例一律虚构且跨领域中性；在 `AGENTS.md` 加一条"示例不得取自任何真实案件"，并在 `verify_package.py` 加一个可维护的敏感词/案号正则门（与 notable-entities 白名单分离）。
- **复查标准**：按"隐私扫描"证据索引中的正则重跑 grep 零命中；`verify_package.py` 新增门 PASS。

### 2. 附图 Skill 以本地相对路径引用外部 Skill 的四个文件

- **位置**：`skills/cn-patent-diagram-generator/SKILL.md:26`；`skills/cn-patent-diagram-generator/references/drawio-execution.md:11-14`、`:37`
- **所属模块**：`structure-standards.md`
- **问题说明**：`references/diagram-types.md`、`references/xml-authoring.md`、`references/autolayout.md`、`references/troubleshooting.md` 在本 Skill 的 `references/` 下不存在；它们属于外部 `drawio-skill`。行文虽写了"先读取其 SKILL.md"，但路径本身是本地相对形式，`test -e` 失败。
- **影响**：Hard Fail "references 引用不存在，导致使用路径断裂"；执行 agent 在本 Skill 目录下 `cat` 会得到不存在文件，进而要么静默跳过制图规范，要么误读本 Skill 同名文件（`references/patent-diagram-types.md` 与 `diagram-types.md` 极易混淆）。
- **修正方式**：把四处改写为 `drawio-skill/references/diagram-types.md` 形式，并在 SKILL.md 第 26 行明确"以下路径相对 `drawio-skill` 根目录"；同时在阶段 0 加一条"若 `drawio-skill` 不可用则停止并报告依赖缺失"。
- **为什么错(原理)**：跨 Skill 引用必须带命名空间，否则相对路径的解析基准是当前 Skill 目录，引用在语义上就是断的。
- **最优设计**：`按图型需要再读 drawio-skill 的 references/diagram-types.md（相对该 Skill 根目录）`。
- **复查标准**：对 SKILL.md 与 references 中所有 `references/...` 引用执行 `test -e`，仅剩本 Skill 内文件；外部引用均带 `drawio-skill/` 前缀。

### 3. 起草 Skill 阶段门措辞自相矛盾（pending 阻断 vs 待决继续）

- **位置**：`skills/cn-patent-application-creator/SKILL.md:140`（"用户未指定前，阶段门的 `template_selection.status` 保持 `pending`，起草不得开始"）与 `:281`（"阶段门不再阻断，而是无用户原话时按保守默认继续并写入待决清单"）；脚本 `check_stage_gate.py` 现已按后者实现（`CLEARED_WITH_PENDING`，退出码 0）
- **所属模块**：`business-flow-rubric.md` / `harness-reliability-standards.md`
- **问题说明**：同一份权威指令对同一状态位给出相反的通过条件。2026-09-22 把 12 道判断题门改为"保守默认 + 待决 + 继续"时，阶段 2-A 段落的旧句未同步。
- **影响**：Hard Fail "存在自相矛盾的通过条件"；执行 agent 读到第 140 行会停下等待，直接违背项目当日确立的"进入撰写后不得因判断题停止"原则。
- **修正方式**：第 140 行改为"用户未指定前，阶段门把 `template_selection.status=pending` 写入待决清单并按默认起草策略继续；只有文件缺失、哈希不一致、schema 错误才阻断"；全文 grep "不得开始|一律阻断|等待用户确认" 逐条复核。
- **为什么错(原理)**：约束改成机器状态位后，散文必须与状态机一致，否则模型会在两条指令间随机选择。
- **最优设计**：阶段门语义只在 2-E 表格一处定义，其他段落只引用"见 2-E"，不复述通过条件。
- **复查标准**：`grep -nE "不得开始|一律阻断" SKILL.md` 零命中；2-E 表格与 `check_stage_gate.py` 的 decision 枚举逐行对应。

## 三、警告问题

### 1. claims-analyzer 文档写错输出 schema 名

- **位置**：`skills/cn-patent-claims-analyzer/SKILL.md:37`、`references/claims-rule-matrix.md:63`（`cn-patent-claims-raw-report/v2`）；脚本与 `cn-review-contract-v2.json:7` 均为 `cn-patent-review-raw-report/v2`
- **所属模块**：`workflow-output-standards.md`
- **影响**：按文档手写或让模型生成报告时会被编排器以 `CN-VERIFY-CONTRACT-001` 拒绝；脚本本身正确，故为警告。
- **建议修正**：两处改为 `cn-patent-review-raw-report/v2`。
- **为什么错(原理)**：跨 Skill 交接的 schema 名是合同的一部分，文档与脚本必须单源。
- **最优设计**：SKILL.md 直接引用合同文件中的常量名，不手抄字符串。
- **优先级**：高

### 2. 稳定性正向夹具停留在 v2，12/13 条约束共用同一"完全干净"正例

- **位置**：`skills/cn-patent-diagram-generator/assets/stability/positive-final-verification.json:2`（`cn-patent-drawing-verification/v2`）；`config/instruction-stability-contract.json` 中 12 条约束的 positive 用例均指向它；`scripts/check_stability_evidence.py:121-135` 对 EDGE-LABEL-READABILITY / NODE-TEXT-FIT 只检查"无相关错误码 + figures[].drawio 为 dict"
- **所属模块**：`instruction-stability-standards.md`
- **影响**：v2 报告不含 v4 才有的关系标签、节点文字、纵向间距观测量，checker 因"没有错误码"即判通过——正例证明不了 v4 约束被真实测过；缺少"合法近似正例"意味着误报无法被发现。
- **建议修正**：用真实 v4 验证报告替换正向夹具（`verify_patent_drawings.py` 对 v4 brief 已输出 `cn-patent-drawing-verification/v4`）；为每条几何类约束增加一个"合法近似正例"（如标签字号恰等于相邻节点的 2/3）。
- **为什么错(原理)**：正例只证明 checker 不误杀干净输入，不证明它测到了约束；缺乏边界正例的 checker 无法区分"通过"与"没测"。
- **最优设计**：每条约束绑定三类夹具——违规最小反例、合法近似正例、真实产物正例，且 schema 版本与生产者一致。
- **优先级**：高

### 3. 综合审查器对语义审查输入的未知顶层字段静默丢弃

- **位置**：`skills/cn-patent-reviewer/scripts/build_review_bundle.py`（`finalize` 读取 review-input；prepare 输入有 `ALLOWED_PREPARE_FIELDS` 白名单，review-input 顶层无对应白名单）
- **所属模块**：`harness-reliability-standards.md`
- **影响**：本次故障注入证实 `assessments[]` 内部字段严格（自报 NO_ISSUE_FOUND 而证据 MISSING 被以退出码 3 拒绝），但顶层多余键 `overall_verdict` 被忽略、bundle 正常生成、verify 通过。代理师把字段名写错（例如把 `result` 写到顶层）不会得到任何提示。
- **建议修正**：finalize 对 review-input 顶层执行与 prepare 相同的白名单校验，未知字段退出码 3。
- **为什么错(原理)**：白名单只覆盖一半输入面，等于给了一条静默 fail-open 的路径。
- **最优设计**：所有人工填写的 JSON 入口统一走 `contract.exact_fields`，与 raw_report 同一套严格度。
- **优先级**：中

### 4. 规则矩阵混入非本脚本产出的 rule_id，且无产出者列

- **位置**：`skills/cn-patent-claims-analyzer/references/claims-rule-matrix.md:36-37`（`CN-CLAIM-CARRIER-001`、`CN-CLAIM-INHERITED-TOPOLOGY-001` 由 `validate_claim_architecture.py` 以 `ARCH-*` 错误码承载，从未以该 rule_id 输出，也不在 `cn-review-contract-v2.json` 的 `rule_dimension_map`）；`skills/cn-patent-reviewer/references/cross-document-rules.md`（`CN-CROSS-*` 无任何脚本产出，属人工 41 维证据来源）；`CN-CLAIM-RESOURCE-001`、`CN-SPEC-RESOURCE-001` 在合同 `tool_only_rules` 中但矩阵未列
- **所属模块**：`business-flow-rubric.md`
- **影响**：读者无法区分"脚本会输出的 finding"与"人工/其他脚本负责的规则"；若将来某脚本按矩阵输出 `CN-CLAIM-CARRIER-001`，编排器会因缺映射抛 ContractError。
- **建议修正**：矩阵增加"产出者"列（脚本 ID / 人工 / 架构验证器）；把 `ARCH-*` 与 `ISM-*` 错误码在合同中登记到维度或 `tool_only_rules`。
- **为什么错(原理)**：规则表是合同，不是阅读材料；每一行都应能回答"谁产出、谁消费"。
- **最优设计**：矩阵由脚本内常量表生成，人工规则单独成表。
- **优先级**：中

### 5. 待决机制与创造性防御地图未登记进路由 Skill

- **位置**：`skills/cn-patent-workflow/SKILL.md`、`references/stage-map.md`（仅第 11 行加了 inventive step map；无 `pending_decisions`、`CLEARED_WITH_PENDING`、`--copy review|submission` 的任何提及）
- **所属模块**：`workflow-output-standards.md` / `skill-orchestration-guide.md`
- **影响**：路由入口不知道阶段 6 前要运行 `collect_pending_decisions.py`，也不知道阶段门退出码 0 可能带待决；跨 Skill 交接原则表未列 `cn-patent-pending-decisions/v1`。
- **建议修正**：stage-map 交接原则增加待决合同；"Word 交付"行的最少输入加"待决清单"；失效传播加"待决清单变化 → 重生成审稿版 DOCX"。
- **为什么错(原理)**：编排层必须知道每个阶段的全部产物，否则新产物在路由层是孤儿。
- **最优设计**：每新增一个 schema，stage-map 同一提交内登记。
- **优先级**：中

### 6. 起草 SKILL.md 过长且根路径前缀重复

- **位置**：`skills/cn-patent-application-creator/SKILL.md`（510 行；`${CN_PATENT_CREATOR_ROOT:-...}` 前缀出现 23 次）
- **所属模块**：`workflow-output-standards.md`
- **影响**：每次加载吞掉大量上下文；阶段 3 句法规则、5a 红队清单、说明书输出格式等纯规范内容更适合按需读取。
- **建议修正**：把"说明书输出格式"、阶段 5 红队清单、DOCX 组装门禁下沉到 references；在"运行根目录"节定义一次 `ROOT=...`，后续命令用 `$ROOT`。
- **为什么错(原理)**：渐进式披露——SKILL.md 是流程分发站，不是知识堆栈。
- **最优设计**：SKILL.md ≤ 250 行，每阶段一段"做什么 + 读哪个 reference + 跑哪个脚本"。
- **优先级**：中

### 7. 发布版本积压

- **位置**：`CHANGELOG.md:3`（Unreleased 31 条）、`pyproject.toml:3` 与两个 `plugin.json`（0.2.0，2026-09-06）
- **所属模块**：`publishing-standards.md`
- **影响**：安装到 `$CODEX_HOME` 的用户无法用版本号区分含待决机制/创造性地图的运行时与旧版。
- **建议修正**：本轮严重问题关闭后切 `0.3.0`，三处版本同步，CHANGELOG 加日期段。
- **优先级**：中

### 8. 结构残留：孤儿 v1 schema、脚本目录内的测试/演示文件

- **位置**：`skills/cn-patent-application-creator/references/{stage2-gate-schema.json, feature-ledger-schema.json}`、`skills/cn-patent-diagram-generator/references/{patent-drawing-brief-schema.json, patent-drawing-brief-schema-v3.json}`（脚本与文档均不引用；SKILL.md 称"v1 仅用于旧案件回放"但无加载路径）；`skills/cn-patent-application-creator/scripts/{test_style_analyzer.py, demo_style_application.py}`
- **所属模块**：`structure-standards.md`
- **影响**：分发体积与维护噪音；测试文件随运行时安装。
- **建议修正**：历史 schema 移至 `references/legacy/` 并在文档登记，或删除；两个开发文件移至 `tests/`。
- **优先级**：低

### 9. 元数据与触发描述

- **位置**：6/7 `SKILL.md` 无 `metadata.version`（仅附图 Skill 为 4.7.0）；`skills/cn-patent-claims-analyzer/SKILL.md:3` description 未用"本技能应在…时使用。不要用于：…"格式（其余 6 个已用）；`skills/cn-patent-formalities-reviewer/SKILL.md:88` 退出码句缺"退出码 0 不表示法律结论"
- **所属模块**：`frontmatter-metadata-policy.md` / `trigger-description-standards.md`
- **建议修正**：版本策略二选一（全部加或全部不加，由包版本统一）；claims-analyzer 改为"本技能应在审查中国发明专利权利要求编号、引用、分项字数、核心从属落位和草稿残留时使用。不要用于：代替法律语义或现有技术审查"；formalities 补一句免责。
- **优先级**：低

## 四、信息提示

- `skills/*/scripts/__pycache__/` 存在于工作区（未入 git，`install_codex_skill.py` 的 `CACHE_DIRS` 已排除），建议在开发命令统一加 `PYTHONDONTWRITEBYTECODE=1`。
- `skills/cn-patent-diagram-generator/SKILL.md:241` 写"十一类硬约束"，合同实际 13 条。
- `references/cn-legal-sources/...` 在 workflow 与 claim-length-policy 中相对仓库根引用，安装布局保留根 `references/`，可达；建议注明"相对运行根目录"。
- `instruction_stability_gate.py assess` 对 claims/specification/reviewer 报 ISG-002（视觉模态缺口），触发句为资源上限、法律语义等非视觉文本，属工具误报，人工裁决不构成候选缺口；ISG-001/003/004/005 为真实缺口。
- `scripts/test_style_analyzer.py:102` 的 `CN202010123456.X` 为明显虚构号，不构成隐私问题。

## 五、安全评估

| 检查项 | 状态 | 风险级别 | 说明 |
|--------|------|----------|------|
| 凭证与敏感配置 | ✅ | None | 无 API Key/Token/.env；git 历史无 `.env` 或案件目录提交记录 |
| 危险执行与文件操作 | ✅ | Low | 9 处 `subprocess.run(shell=False)` 调用 Draw.io CLI、LibreOffice、EPO provider、官方复导出，均参数数组、超时受控；写入限案件目录并有 `DraftingOutputGuard` 防覆盖输入 |
| 网络外联与数据外传 | ✅ | Low | 仅 EPO provider 由用户通过 `CN_PATENT_EPO_PROVIDER_COMMAND` 显式配置；无内置 endpoint |
| 依赖、安装钩子与 MCP | ✅ | Low | 安装器写入 `$CODEX_HOME`，README:17-19 已披露；无 postinstall、无 MCP 通配权限 |
| 提示词安全 | ✅ | None | 无绕过上层指令、隐藏执行或凭证收集语句 |

### 安全发现

未发现明显安全风险。扫描器 14 项（9 medium / 3 low / 2 info）均为能力提示且已在 README、`references/provider-contracts.md` 或 SKILL.md 披露。

## 六、Harness 可靠性

| 层 | 状态 | 证据或缺口 |
|----|------|------------|
| Contract | ✅ | 输入白名单、输出 schema、退出码 0/2/3/4、ADVISORY_ONLY 在 6 个脚本 Skill 一致；workflow 无契约（纯路由） |
| Producer | ✅ | 本次在最小环境（`env -i`、临时 HOME）用仓库外夹具真实执行 7 项检查 |
| Verifier | ✅ | 原始检查器不采信输入自报；reviewer 的 verify 独立复算哈希与 41 维覆盖；finalize 拒绝证据 MISSING 的自报通过 |
| Evidence Binding | ✅ | 报告携带 input/rule/tool SHA-256；创造性地图与架构合同 SHA 过期 → 退出 2 |
| Fault Injection | ✅ | 9 个反例全部按预期非零退出（见下） |
| Closure | ✅ | reviewer 处置状态由合同派生；附图/DOCX 以 SHA 绑定失效传播 |
| Composition | ⚠️ | 版本化 JSON 合同交接完整，但 stage-map 未登记待决合同（警告 5） |

- **审查证据状态**：`HARNESS_REVIEW_VERIFIED`（claims-analyzer、specification-reviewer、formalities-reviewer、application-creator、diagram-generator、reviewer）；`NOT_VERIFIED`（workflow：无可执行验证路径，纯路由，不适用动态门禁）
- **指令稳定性状态**：`NOT_VERIFIED`（全部 7 个）
- **业务验证状态**：`NOT_VERIFIED`（本次未用真实案件回放领域产物）
- **候选聚合哈希**：application-creator `0754f51a…5ade8`；claims-analyzer `11726226…6164`；diagram-generator `34a12768…82f4`；formalities-reviewer `8b54e43b…e947`；reviewer `039aa589…cdd7`；specification-reviewer `d9ef3edd…0e68`；workflow `013a3b41…`
- **策略聚合哈希**：`74999b90b371ffe368bbba6c2812f270c2bd9ed5145868617dc3edf52197…`（skill-lint 2.9.0，33 个策略文件）
- **稳定性合同 / 签名基线 / Harness evidence 哈希**：附图合同存在（13 约束、37 用例）；候选外 evaluator-signed 基线与 held-out：未生成
- **运行证据/签名回执/受信公钥 ID**：未生成
- **候选信任与执行环境**：自有代码；普通工作区 + 门禁最小环境白名单（非沙箱）
- **故障注入结果**：
  - claims-analyzer：`claim1-401-words` exit 2（`1b2c952d…`）；`claim2-independent` exit 2（`318eaee4…`）
  - specification-reviewer：`duplicate-paragraph` exit 2（`327575be…`）
  - formalities-reviewer：`abstract-301` exit 2（`47c18d22…`）
  - application-creator：`ism-stale-source` exit 2（`bde76dba…`）；`ism-forged-grade` exit 2（`73283d20…`）
  - diagram-generator：`excessive-margin` exit 3（`36f6d3bd…`）；`forged-export` exit 3（`586b52ed…`）
  - reviewer：`self-reported-pass-without-evidence` exit 3（`1af547ea…`）
- **多轮覆盖结果**：未执行（无签名基线，不得声称）
- **总体成熟度**：L3（6 个脚本 Skill）；workflow L1（叙述型路由）
- **剩余人工判断**：清楚/简要/支持/创造性等法律语义、附图视觉复核、待决清单中的每一项决策

## 七、建议修正顺序

| 顺序 | 修正项 | 文件 | 预期结果 | 验证方式 |
|------|--------|------|----------|----------|
| 1 | 替换真实案件示例与复盘文档中的高校/案件名、本地路径 | 起草 SKILL.md:343-355、claim-architecture.md:55-61、docs/…/2026-09-03/verification-report.md:7、docs/…/2026-09-15/report.md:64,67 | 分发树与公开文档零真实案件信息 | 隐私 grep 零命中；`verify_package` PASS |
| 2 | 阶段门旧措辞改为待决语义 | 起草 SKILL.md:140 | 与 2-E 表格及 `check_stage_gate.py` 一致 | `grep -nE "不得开始|一律阻断"` 零命中 |
| 3 | 外部引用加 `drawio-skill/` 前缀 | 附图 SKILL.md:26、drawio-execution.md:11-14,37 | 引用可达性 100% | 引用扫描脚本零断裂 |
| 4 | 修正 schema 名 | claims-analyzer SKILL.md:37、claims-rule-matrix.md:63 | 与合同一致 | `grep -rn claims-raw-report` 零命中 |
| 5 | v4 正向夹具 + 合法近似正例 | 附图 assets/stability、合同 cases | 13 条约束各有真实 v4 正例 | `instruction_stability_gate.py assess` 仅剩 ISG-006 |
| 6 | review-input 顶层白名单 | build_review_bundle.py finalize | 未知字段退出 3 | 新增测试 + 门禁反例 |
| 7 | stage-map 登记待决合同；矩阵加产出者列并登记 ARCH-*/ISM-* | stage-map.md、三份 rule-matrix、cn-review-contract-v2.json | 编排层无孤儿产物 | `test_cn_contract_v2` 通过 |
| 8 | SKILL.md 下沉与 `$ROOT` 收敛；孤儿 schema 与测试文件归位；版本切 0.3.0 | 起草 SKILL.md、references/legacy、tests/、pyproject、plugin.json、CHANGELOG | 发布态一致 | 全量 pytest + verify_package + 本报告复查 |

## 八、复查清单

- [ ] 严重问题已全部关闭
- [ ] 警告问题已处理或记录为后续任务
- [x] 仓库 / monorepo 已先定位最小 Skill 单元
- [x] `SKILL.md` frontmatter 与目录名一致
- [ ] 引用的 references / scripts / assets / templates 文件均存在（附图 Skill 4 处待修）
- [ ] 示例配置不包含真实人名、客户名、案件项目、案号、联系方式或可反查组合信息（严重 1 待修）
- [x] 安全评估已覆盖凭证、危险执行、网络外联、依赖/MCP 和提示词安全
- [ ] 若进入发布流程，LICENSE、CHANGELOG、version、README / Marketplace 已同步（版本待切）
- [x] 输出流程、验收标准和可评估性说明已补齐（样例缺口记为警告）
- [x] 生产器不为自己签发最终 PASS，独立验证器检查真实产物
- [x] 正式验收证据绑定当前候选、当前策略和非空日志
- [x] 至少一个故障注入或逃逸反例已证明会被阻断
- [ ] 每条硬约束已映射到 active checker、正确验证模态、产物阶段和正反例（仅附图 Skill 部分满足）
- [ ] 声称稳定时的签名基线与三轮运行记录（未生成；不得声称稳定）
- [x] 完成结论明确区分 Harness 审查、指令稳定性与业务功能验证

## 九、最终处理意见

有条件通过：Harness 与安全层面达到 L3，可继续内部使用；**在关闭严重问题 1–3 之前不建议对外发布 0.3.0，也不得在任何文档中写"多轮稳定"或"已验证交付"**。严重问题均为一小时内可完成的文本修正；修正后由本技能做复查（关联本归档目录），复查只需重跑隐私 grep、引用扫描与六个 Skill 的候选绑定门禁。

## 十、审查依据

- `references/skill-standards.md`、`repository-skill-discovery-standards.md`、`structure-standards.md`、`frontmatter-metadata-policy.md`、`trigger-description-standards.md`、`skill-merge-standards.md`、`configuration-privacy-standards.md`、`security-assessment-standards.md`、`publishing-standards.md`、`workflow-output-standards.md`、`business-flow-rubric.md`、`harness-reliability-standards.md`、`instruction-stability-standards.md`、`reporting-standards.md`、`archive-standards.md`
- 项目规则：仓库 `AGENTS.md`

## 十一、归档说明

- **是否归档**：是
- **归档目录**：`archive/20260923_000500_claude-patent-creator-cn/`
- **归档文件**：`quality-opinion-report.md` / `review-metadata.json` / `evidence-index.md`
- **脱敏状态**：已检查（报告不含真实高校名、案件名、案号、联系方式；本地路径以 `<user>` 代替）
- **复查关系**：首次审查
