# 范本选取改造：申请人 / 代理机构进入加权排序

**日期**：2026-09-24
**范围**：`skills/cn-patent-application-creator`（范本候选与选择链）+ `skills/cn-patent-workflow/references/stage-map.md`
**触发**：用户判断——大多数案件里"同领域 + IPC 相近"很容易满足，真正区分范本的是代理机构和申请人。

## 一、改造前的已知缺口

| # | 缺口 | 位置 |
| --- | --- | --- |
| 1 | 代理机构没有任何数值权重，只在散文里写"质量可信" | `references/search-and-template-flow.md:52` |
| 2 | 候选合同只有 `assignee`，没有代理机构字段，代理所信息进不了候选 JSON | `references/template-candidates-schema.json` |
| 3 | 排序脚本只认技术相关性 + IPC，阶段门复算公式里没有主体项 | `rank_template_candidates.py:289`、`check_stage_gate.py:428` |
| 4 | 主体缺失与"主体普通"不可区分，信息缺失会静默退化为只看技术/IPC | 无 |

## 二、改造内容

1. **四因子加权模型**：`综合得分 = 技术相关性×0.30 + IPC相似度×0.20 + 申请人质量×0.25 + 代理机构质量×0.25`。
   技术与 IPC 合计 0.50（仍是不可退化的准入项，二者必须保持正权重）；申请人、代理机构合计 0.50（真正的区分项）。
2. **主体质量分层**：`references/notable-entities.txt` 变成机器可解析名单（`## …（Tier N）` 决定梯队）。
   Tier 1 = 1.00、Tier 2 = 0.70、Tier 3+ 按 0.30 递减保底 0.40、有名称但不在名单 = 0.30、未著录 = 0.00（标 `missing`）。
   匹配规则：去括号备注与 `股份有限公司/有限公司/集团` 后缀后完全相等，或较短名称 ≥ 4 字符时包含匹配。
3. **合同 v2**：`cn-patent-template-selection/v1 → v2`，`weights` 由两项变四项且 `additionalProperties: false`；
   新增 `entity_policy`（分值口径）与 `entity_evidence`（著录覆盖统计）；v1 合同移入 `references/legacy/`。
   候选合同新增 `applicant` / `agency`（`assignee`、`patent_agency` 仍识别为别名）。
4. **阶段门收紧**：四项权重必须非负、和为 1，技术相关性与 IPC 必须为正；四项加权得分可复算；
   报告中的申请人/代理机构名称必须与候选清单一致（防手改，`GATE-IPC-014`）；
   选定范本缺主体著录时产生待决项而不是静默按 0 分排序（`GATE-IPC-015`）。
5. **命令接口**：四项权重必须同时给出（`--technical-weight/--ipc-weight/--applicant-weight/--agency-weight`），
   省略全部则用默认值；单独传一项直接报错，避免"只改一项导致权重和不为 1"的隐性错误。

## 三、设计边界（明确不做什么）

- 名单命中只表示"属于知名实体"，**不是**对机构撰写质量、法律结论或商业信誉的评价；报告 `entity_policy.boundary` 已写入该边界。
- 不引入语义打分或模型评价。"不在名单"是中性 0.30，不是低质判定；Tier 2 名单仍是 TODO，不臆造条目。
- 技术相关性与 IPC 的正权重要求保留，防止范本选择退化成"只看主体名气"的另一种偏差。

## 四、验证证据

| 项目 | 结果 |
| --- | --- |
| `pytest -q`（全量） | **409 passed / 1 skipped / 107 subtests**（skip 为未授权的视觉导出） |
| `tests/test_cn_template_ipc_selection.py` | 20 passed（新增 8 项：名单解析、分层打分、主体决定推荐、缺失标记、权重校验、CLI 部分权重报错、主体缺失待决、主体著录防篡改） |
| `scripts/verify_package.py` | PASS，errors 为空 |
| CLI 端到端 | 技术 0.92 + 小所（0.3） vs 技术 0.85 + Tier 1 主体（1.0×2）→ 推荐后者（0.955 vs 0.626）；`check_stage_gate.py` 输出 `CLEARED` 且 `GATE-IPC-013` 打印主体与四项权重 |
| 修复缺陷 | 改造中曾出现 `selected` 缺 `technical_relevance_score` 导致 CLI 汇总 KeyError，已在同轮修复并复验 |

## 五、Skill Lint 门禁（skill-lint 2.9.0）

| 门禁 | 结果 | 说明 |
| --- | --- | --- |
| `security_scan.py audit` | WARN | critical 0 / high 0，与 2026-09-23 复查一致 |
| `harness_failure_audit.py audit` | PASS | 0 findings / 0 hard |
| `instruction_stability_gate.py assess` | NOT_VERIFIED | ISG-001/002/003/004/005，属既有缺口，本次改造未新增 |

**未闭合项**：多轮指令稳定性基线仍缺（不变）；名单 Tier 2 待补真实条目。

## 六、代理机构名单建档（2026-09-24 检索）

`references/notable-entities.txt` 的代理机构部分由 15 条扩充为 **45 条（Tier 1 × 18、Tier 2 × 27）**，
来源为多口径公开榜单交叉，不以单一榜单定级：

| 维度 | 来源 |
| --- | --- |
| 体量（申请量） | 润桐 RainPat 2025年1-9月/第一季度中国发明申请量代理机构 TOP50 |
| 体量（授权量） | 2025年发明授权量百强榜（专利茶馆/IPRDaily 口径，集佳 14636、三环 13882、品源 11926） |
| 质量综合 | IPRDB 专利代理机构综合排行榜（累计量 + 授权率 + 质量评分） |
| 质量口碑 | Chambers Greater China Region 中国 IP（非诉）Band 1—4 |
| 官方/协会背书 | 北京市专利代理师协会 5A/4A 机构等级评定、国家知识产权局全国知识产权服务品牌（培育）机构 |
| 执业规模 | IPRdaily×incoPat"全国执业百人以上的专利代理机构发明授权排行榜"（13 家） |
| 历史代理量 | incoPat 2023 年发明专利代理量前 10（集佳/三环/品源/华进/清亦华/路浩/嘉权/康信/同立钧成/超凡） |

**定级口径**：Tier 1 = 体量前列且同时命中权威质量榜单；Tier 2 = 单边强（规模居前的区域头部所，或质量背书强、规模中等的精品所）。
同一机构的不同著录写法（如"中国贸促会专利商标事务所有限公司"与旧名"中国国际贸易促进委员会专利商标事务所"）分别列条，
以匹配检索结果中的实际著录。

**已知偏差（已写入名单文件）**：榜单存在公开周期误差与机构合并统计问题；服务体量小但质量高的精品所会缺席；
名单命中只表示"属于知名实体"，不构成机构优劣或法律结论。建议每年一季度榜单发布后复核一次。
