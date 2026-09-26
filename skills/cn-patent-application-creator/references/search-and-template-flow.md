# 2-A：生成检索清单并人工筛选范本

### 2-A：生成检索清单并人工筛选范本

先把阶段 1 的幸存方案整理成 UTF-8 JSON。**查找范本之前必须先判断目标技术方案的 IPC 分类号**，并把人工判断后的分类号显式写入 `ipc_codes`；自动领域映射只能作为建议，不能替代这一判断。至少还应提供一个可检索的关键词、部件、算法、技术问题、技术方案或 CPC 分类号；能人工确定的英文词放进 `keywords_en`，不要要求脚本猜译专有名词：

```json
{
  "technical_problem": "网络抖动时分布式锁一致性下降",
  "technical_solution": "通过租约续期和版本戳校验恢复一致性",
  "key_components": ["租约管理器", "仲裁节点"],
  "algorithms": ["版本戳校验算法"],
  "field": "分布式数据处理与网络通信",
  "keywords_en": ["lease renewal", "version stamp"],
  "ipc_codes": ["G06F11/30"],
  "cpc_codes": ["G06F11/30"]
}
```

运行：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/generate_search_query.py" \
  --features "<technical-features.json>" \
  --output "<search-query.json>"
```

`search-query.json` 固定输出 `cn-patent-template-search/v1`，包含 `uyanip_plan`（度衍首选检索方案）、中文关键词、可确定映射的英文关键词、`untranslated_cn_terms`、IPC/CPC 建议、`target_ipc` 判定状态、可在 Google Patents Public Datasets `publications` 表执行的 BigQuery SQL，以及 CNIPA 人工检索清单。`target_ipc.status` 只有在 `technical-features.json` 显式提供 `ipc_codes` 时才为 `determined`；仅由关键词映射得到时为 `suggested`，不得进入范本排序。出现以下任一情况必须停止并修正输入：

- 输入不是 UTF-8 JSON 或字段类型错误；
- 没有任何关键词或分类号，脚本拒绝生成全表查询；
- `target_ipc.status` 不是 `determined`，却开始搜索或选择范本；
- `untranslated_cn_terms` 未人工补齐，却准备把英文检索称为已完成；
- BigQuery 结果被误当成 CNIPA 官方库检索结果。

**检索渠道优先级：① 度衍命令检索（uyanip.com，首选）→ ② CNIPA 专利检索及分析系统人工检索 → ③ Google Patents Public Datasets BigQuery（补充验证）。**

`search-query.json` 的 `uyanip_plan` 已给出首选渠道的现成检索式与结果页 URL（`priority=1`）：

- 入口：`https://www.uyanip.com/search/command`
- 结果页直开模板：`https://www.uyanip.com/result?fromMode=5&exp=<URL编码检索式>&country=<URL编码范围>`
- `country_filter` 默认 `AND GJ:(CN)`（中国）；其他国家改 `AND GJ:(US)`、`AND GJ:(WO)` 等
- `expressions`：`purpose=determined_ipc` 是人工确定分类的主检索式；`purpose=broad_expansion` 只作扩展，**不得据宽分类判定范本相似度**
- 布尔运算 `AND`/`OR`/`NOT`、括号分组与嵌套、`*` 前缀通配符均可用
- 详情页 `https://www.uyanip.com/detail?aid=<申请号>` 可直接读取权利要求与说明书正文，并获取附图与 PDF 下载
- 所有 `window.open` 类操作要求标签页处于前台，否则改用结果页 URL 直开
- 完整字段表、实测数据与自动化要点见仓库 `docs/uyanip-command-search-sop.md`

随后在 CNIPA 专利检索及分析系统人工执行并留档检索日期、检索式、命中数和筛选理由。结果同时完成两件事：

1. 找对抗性文献，用于阶段 2-C 的逐要素攻击；
2. 形成 1—10 篇 `cn-patent-template-candidates/v1` 范本候选，逐篇给出 `technical_relevance_score`（0—1）及理由，并逐篇著录 **`applicant`（申请人）与 `agency`（专利代理机构）**。著录项取自度衍详情页或 CNIPA 检索结果的申请人、代理机构字段，不得凭印象填写。

候选优先同领域、已授权、权利要求不少于 10 项、说明书和附图完整；但**技术与 IPC 通常多篇同时达标，真正决定范本的是撰写主体**——申请人/代理机构默认合计占一半权重，未著录主体信息的候选按 0 分计并在阶段门触发待决项。

候选 IPC 获取顺序固定为：**EPO OPS provider → 有来源记录的分类缓存 → 候选输入**。通过 `--epo-provider-command` 或 `CN_PATENT_EPO_PROVIDER_COMMAND` 调用独立 provider，不下载 PDF，也不得反向 import 其他项目；provider 未配置、EPO 未收录或调用失败时，必须记录失败状态和降级来源。未取得逐篇 IPC 的候选不得成为推荐或最终范本。

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/rank_template_candidates.py" \
  --search-query "<search-query.json>" \
  --candidates "<template-candidates.json>" \
  --classification-cache "<可选的ipc-cache.json>" \
  --output "<template-selection.json>"
```

输出 `cn-patent-template-selection/v2` 的 `template-selection.json`。默认综合得分为：

```text
综合得分 = 技术相关性×0.30 + IPC相似度×0.20 + 申请人质量×0.25 + 代理机构质量×0.25
```

IPC 相似度按“完全相同 → 同主组 → 同小类 → 同大类 → 同部”的层级计算。主体质量分按名单命中折算：Tier 1 = 1.00、Tier 2 = 0.70、有名称但不在 `references/notable-entities.txt` = 0.30、未著录 = 0.00。名单命中只是“属于知名实体”的标记，不等于对该机构撰写质量的实质评价。

四项权重可按案件整体调整（`--technical-weight`、`--ipc-weight`、`--applicant-weight`、`--agency-weight`），但必须**同时给出且之和为 1**，`technical_relevance` 与 `ipc_similarity` 都必须保持正权重，不能退化为只看标题、摘要或主体名单。人工偏离加权最高候选时，必须通过 `--selected` 和 `--selection-reason` 留下理由。

仓库没有 CNIPA 官方检索接口。人工检索未完成时必须写“未完成”，不得静默继续或声称检索穷尽。

**范本由用户确认，不由本技能替用户选定。** `template-selection.json` 只是带 IPC 证据的机器推荐；哪几篇作为撰写范本，仍须用户明确指定。用户未指定前，阶段门把 `template_selection.status=pending` 写入待决清单并按默认起草策略继续（见 2-E）；只有文件缺失、哈希不一致或 schema 错误才阻断。新案件必须使用 `cn-patent-stage2-gate/v2`，登记 `search_query_path`、`candidate_manifest_path` 和 `selection_report_path`；阶段门会核对输入哈希、EPO 优先尝试、候选 IPC、四项权重与四项加权得分、主体著录与候选清单一一致性，以及已确认风格指南是否指向同一公开号。

完整字段、评分算法、EPO 降级规则和 v2 阶段门示例见 `references/template-ipc-selection.md`。

