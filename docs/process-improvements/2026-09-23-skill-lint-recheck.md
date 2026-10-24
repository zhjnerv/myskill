# Skill Lint 复查报告（第 2 轮）

**复查日期**：2026-09-23
**复查对象**：`/data/SynologyDrive/PC同步/GitHub/claude-patent-creator-cn`（7 个 Skill 的 monorepo）
**上一轮报告**：`docs/process-improvements/2026-09-23-skill-lint-review.md`（结论「有条件通过」，3 项 Hard Fail + 8 项修正顺序）
**审查配置**：skill-lint 2.9.0（通用规则）+ 仓库 `AGENTS.md`
**复查性质**：关联复查（承接上一轮，非首次审查）

## 一、上一轮 8 项修正顺序的复核结果

| # | 上一轮要求 | 状态 | 本轮证据 |
| --- | --- | --- | --- |
| 1 | 替换真实案件示例与本地路径 | ✅ 已关闭 | `skills/`、插件清单、README、AGENTS 隐私 grep 零命中；`docs/` 本地路径零命中，2026-09-03 报告已脱敏为「某高校」 |
| 2 | 阶段门措辞改为待决语义 | ✅ 已关闭（本轮收口） | `SKILL.md:163`、`:300`、`:304` 与 `check_stage_gate.py` 的 `TEMPLATE_STATES={"confirmed","declined","pending"}` 及 `gate.pending(...)` 一致；**遗留的 `:447` 旧句本轮改写为「把检索未完成写成已完成」** |
| 3 | 外部引用加 `drawio-skill/` 前缀 | ✅ 已关闭 | `SKILL.md:26` 显式声明前缀指向外部 Skill 根目录；`drawio-execution.md:11-14,37` 同步 |
| 4 | 修正 schema 名 | ✅ 已关闭 | `claims-rule-matrix.md:63` 与合同、脚本均为 `cn-patent-review-raw-report/v2` |
| 5 | v4 正向夹具 + 合法近似正例 | ✅ 已关闭 | `instruction_stability_gate.py assess` 对附图 Skill 只剩 ISG-006（与上一轮设定的目标一致） |
| 6 | review-input 顶层白名单 | ✅ 已关闭 | `build_review_bundle.py:695-700` 以 `contract["exact_fields"]["review_input"]` 严格比对，多出/缺少即抛错 |
| 7 | stage-map 登记待决合同、矩阵加产出者列、登记 `ARCH-*` | ✅ 已关闭 | `stage-map.md:14,20` 已登记 `collect_pending_decisions.py`、`cn-patent-pending-decisions/v1`、`CLEARED_WITH_PENDING`；规则矩阵含「产出者」列；合同已登记 `ARCH-*` |
| 8 | SKILL.md 下沉、`$ROOT` 收敛、孤儿 schema 归位、版本切 0.3.0 | ✅ **已关闭** | `$ROOT` 收敛 ✓；app-creator 2 个孤儿 schema → `references/legacy/` 且文档登记 ✓；`scripts/` 内测试与演示文件 → `tests/` ✓；版本 0.3.0 三处一致 ✓；**本轮补完**：diagram-generator 的 v1/v3 旧 schema 移入 `references/legacy/` 并在 `SKILL.md:78` 登记（原先只改名未归位）；**SKILL.md 480 → 208 行**，9 个新 reference（全部被引用），必留字符串 18/18 校验通过 |

**Hard Fail 关闭情况：3/3 全部关闭。**

## 二、本轮门禁脚本结果

| 门禁 | 结果 | 说明 |
| --- | --- | --- |
| `security_scan.py audit` × 7 Skill | 5 PASS / 2 WARN | **critical 0 / high 0**；WARN 均为已披露的 `SEC-SUBPROCESS`（`shell=False` 参数数组）与 `SEC-CREDENTIAL`（环境变量定位外部工具） |
| `harness_failure_audit.py batch` | **PASS** | 7 skills / 0 findings / 0 hard / 0 warning |
| `instruction_stability_gate.py assess` × 7 | 7/7 `NOT_VERIFIED` | 附图 Skill 仅 ISG-006；其余报 ISG-001/002/003/004/005，属既有缺口 |
| 引用可达性（确定性扫描） | 61 处引用 / 0 处真实断裂 | 3 处 `references/cn-legal-sources/…` 相对运行根目录引用，可达；跨 Skill 引用均带命名空间 |
| `scripts/verify_package.py` | PASS | errors 为空 |
| `pytest -q`（全量） | 401 passed / 1 skipped / 107 subtests | 1 skip 为视觉导出（未授权） |
| `docs/` 隐私扫描 | 零命中 | 本地路径与客户案件词均无命中 |

## 三、本轮新发现与处理

1. **`SKILL.md:447` 旧语义残留**（本轮发现并修复）：原文要求「跳过阶段门必须带用户原话」，与 `:304`「无用户原话时按保守默认继续」冲突；已改写为「`pending` 只表示登记进待决清单并按保守默认继续，不表示检索或确认已完成」。
2. ~~**SKILL.md 体积**~~（本轮关闭）：已由 480 行下沉至 **208 行**；下沉内容原文完整保留在 9 个新 reference（`us-cn-differences` / `history-mining` / `search-and-template-flow` / `template-style-learning` / `distinguishing-feature-ledger` / `stage2-gate` / `claim-first-drafting` / `red-team-and-packaging` / `failure-modes`），SKILL.md 保留指针与全部契约字符串（18/18 校验通过）。
3. **diagram-generator 旧 schema 归位不完整**（本轮发现并补完）：两个文件此前仅改名为 `legacy-*` 前缀留在 `references/` 根目录，既未进入 `legacy/` 子目录，也未在文档登记；已移入 `references/legacy/` 并在 `SKILL.md:78` 登记，54 项附图测试与 `verify_package` 复验通过。
4. **零引用 schema 的性质**（信息项）：反向扫描发现 `template-candidates/selection/style-schema.json` 与 `pending-decisions-schema-v1.json` 无文件名引用，但对应 `schema_id` 均以脚本常量内联定义（`check_stage_gate.py:33-34`、`rank_template_candidates.py:22`、`collect_pending_decisions.py:13`、`analyze_template_style.py:682`），属参考型文档而非运行时依赖，不构成孤儿缺陷。
5. **指令稳定性**（长期项，本轮不可闭合）：7/7 需候选外 evaluator 签名基线与三轮独立运行证据；取得前不得在任何文档声称「多轮稳定」。
4. **工具链限制**：本轮原计划用子代理并行审查结构与流程，实际因 API 429 限流失败；结构审查改用确定性脚本完成，结论已并入本表，不影响复查覆盖度。

## 四、最终处理意见

**有条件通过（较上一轮显著提升）**：上一轮的 3 项 Hard Fail 与 8 项修正顺序中 7 项已完整关闭，仅「SKILL.md 瘦身」属非阻断遗留。

- **可对外发布 0.3.0**：版本号三处一致，发布态已收敛。
- **仍不得声称**：多轮指令稳定性、业务功能（真实案件回放）验证通过。
- **建议的下一步**：① SKILL.md 继续下沉至 ≤250 行；② 为 7 个 Skill 建立候选外签名稳定性基线；③ 把 `references/cn-legal-sources/…` 引用统一注明「相对运行根目录」。

## 五、复查清单

- [x] 严重问题已全部关闭（3/3）
- [x] 警告问题已处理或登记为后续任务
- [x] 引用可达性已机器扫描（0 处真实断裂）
- [x] 隐私扫描零命中（`skills/`、`docs/`、插件清单、README）
- [x] 安全评估无 critical/high
- [x] Harness 失效审计 PASS（7/7）
- [x] 发布态三处版本一致（0.3.0）
- [ ] 指令稳定性签名基线（未生成，不得声称稳定）
- [ ] SKILL.md ≤250 行（当前 480 行）
