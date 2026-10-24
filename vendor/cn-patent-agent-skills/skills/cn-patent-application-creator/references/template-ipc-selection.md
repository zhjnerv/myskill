# 范本判定与加权选择规范（技术 + IPC + 申请人 + 代理机构）

本规范用于在中国发明专利起草阶段选择撰写范本。目标是同时避免两种偏差：只凭标题或摘要选范本，以及只凭申请人/代理机构知名度选范本。技术相关性与 IPC 判断“能不能借鉴”，申请人/代理机构判断“文本质量值不值得学”；四者共同进入加权评分，任何一项都不单独决定结果。

## 零、检索渠道优先级

1. **度衍命令检索（uyanip.com，首选）**：由 `generate_search_query.py` 的 `uyanip_plan` 直接给出检索式与结果页直开 URL；入口 `https://www.uyanip.com/search/command`。默认范围为中国（`country_filter = AND GJ:(CN)`）。
2. **CNIPA 专利检索及分析系统（人工）**：作为官方库留档渠道。
3. **Google Patents Public Datasets / BigQuery**：作为补充验证渠道。

候选发现与全文/附图/PDF 取证优先在度衍完成；逐篇候选 IPC 仍按第三节的 EPO OPS 优先顺序获取，两条证据链互不替代。

`uyanip_plan.expressions` 的用途分级必须遵守：`determined_ipc` 为人工确定分类的主检索式；`broad_expansion` 仅用于扩大检索面，不得据宽分类判定范本相似度。

## 一、目标 IPC 必须先确定

`technical-features.json` 必须显式填写经人工判断的 `ipc_codes`：

```json
{
  "technical_problem": "……",
  "technical_solution": "……",
  "ipc_codes": ["G06F11/36"],
  "cpc_codes": ["G06F11/36"]
}
```

`generate_search_query.py` 会在 `search-query.json` 中生成：

```json
{
  "target_ipc": {
    "status": "determined",
    "ipc_codes": ["G06F11/36"],
    "suggested_ipc_codes": ["G06F"],
    "source": "technical_features_explicit"
  }
}
```

只有显式填写的 IPC 进入范本相似度计算。关键词映射产生的宽分类仅放入 `suggested_ipc_codes`，防止宽泛的 `G06F`、`H04L` 把无关候选错误评为完全匹配。

若未显式填写，状态为 `suggested` 或 `unresolved`，`rank_template_candidates.py` 必须拒绝继续。

## 二、候选清单

候选文件使用 `cn-patent-template-candidates/v1`：

```json
{
  "schema_id": "cn-patent-template-candidates/v1",
  "searched_at": "2026-08-27",
  "database": "Google Patents",
  "candidates": [
    {
      "publication_number": "CN104978263B",
      "title": "一种移动端应用程序测试方法及系统",
      "applicant": "腾讯科技（深圳）有限公司",
      "agency": "深圳市深佳知识产权代理事务所（普通合伙）",
      "search_rank": 7,
      "technical_relevance_score": 0.9,
      "technical_relevance_reason": "同属移动端应用自动化测试，并包含测试任务、设备故障处理和结果校验"
    }
  ]
}
```

`technical_relevance_score` 由起草者基于技术问题、核心机制、系统边界和文书完整度评定，不得只把搜索排名换算为相关性。

`applicant`（申请人）与 `agency`（专利代理机构）是**必填著录项**，取自度衍详情页或 CNIPA 检索结果的著录字段（旧清单使用的 `assignee`、`patent_agency` 仍可被识别）。二者直接进入综合评分，缺失按 0 分计并在阶段门触发待决项。

## 三、候选 IPC 来源顺序

`rank_template_candidates.py` 对每个候选按以下顺序取 IPC：

1. **EPO OPS**：通过 `--epo-provider-command` 或 `CN_PATENT_EPO_PROVIDER_COMMAND` 调用独立 provider；provider 接收公开号参数并输出 `{"ipc_codes": [...]}`，新项目不得反向 import 其他仓库；
2. **分类缓存**：例如先前 EPO/BigQuery 查询结果，必须登记 `source`；
3. **候选输入**：候选 JSON 已携带 `ipc_codes` 和 `classification_source`；
4. 仍无 IPC：标记 `unresolved`，不得入选。

EPO OPS 需要：

```text
EPO_OPS_KEY
EPO_OPS_SECRET
```

不得记录、打印或提交真实凭据。EPO 失败时报告必须保留 `unavailable`、`not_found` 或 `error` 状态及原因，不能静默改用其他来源。

## 四、IPC 相似度

针对目标 IPC 与候选 IPC 的所有组合取最高值：

| 层级 | 分值 |
|---|---:|
| 完整分类号相同 | 1.00 |
| 同主组 | 0.85 |
| 同小类（如 G06F） | 0.65 |
| 同大类（如 G06） | 0.45 |
| 同部（如 G） | 0.20 |
| 无共同层级 | 0.00 |

输入中的空格、版本括号和分隔符会先规范化，例如 `G06F 11/36 (2006.01)` 归一为 `G06F11/36`。

## 五、主体质量分层

申请人/代理机构不是由模型评价“写得好不好”，而是对 `references/notable-entities.txt` 做名单判定，
输出 0—1 的分值：

| 情形 | 分值 |
|---|---:|
| 命中 Tier 1 | 1.00 |
| 命中 Tier 2 | 0.70 |
| 命中 Tier 3 及以后 | `1.00 - 0.30 × (Tier - 1)`，保底 0.40 |
| 有名称但不在名单 | 0.30 |
| 未著录名称 | 0.00（报告中标记 `missing`） |

匹配规则：名称去掉括号备注与`股份有限公司/有限公司/集团`等后缀后完全相等，或较短名称不少于 4 个字符时按包含匹配。
"不在名单 = 0.30"是中性起点，不表示该机构低质；"未著录 = 0.00"只表示证据缺失，阶段门会据此产生待决项。

## 六、综合评分

默认：

```text
综合得分 = 技术相关性 × 0.30 + IPC相似度 × 0.20 + 申请人质量 × 0.25 + 代理机构质量 × 0.25
```

技术相关性与 IPC 合计 0.50：它们在多数案件里很容易同时被满足，但仍是不可退化的准入门槛；
申请人、代理机构各 0.25，合计 0.50，是范本之间真正的区分项。

四项权重可按案件整体调整，但必须同时给出、之和为 1，且 `technical_relevance` 与 `ipc_similarity`
都必须为正权重——不得把范本选择退化为只看标题、摘要或主体名单。

运行：

```bash
python skills/cn-patent-application-creator/scripts/rank_template_candidates.py \
  --search-query "01-检索/search-query.json" \
  --candidates "01-检索/template-candidates.json" \
  --classification-cache "01-检索/ipc-cache.json" \
  --output "01-检索/template-selection.json"
```

调整权重时必须四项同时给出：

```bash
python skills/cn-patent-application-creator/scripts/rank_template_candidates.py \
  ... \
  --technical-weight 0.30 --ipc-weight 0.20 --applicant-weight 0.25 --agency-weight 0.25 \
  --output "01-检索/template-selection.json"
```

人工选择不同于加权最高候选时：

```bash
python skills/cn-patent-application-creator/scripts/rank_template_candidates.py \
  ... \
  --selected "CN……" \
  --selection-reason "虽然IPC仅同小类，但说明书的系统时序结构更接近本案"
```

## 七、阶段门

新案件使用 `cn-patent-stage2-gate/v2`，在 `template_selection` 中登记：

```json
{
  "status": "confirmed",
  "style_guides": ["01-检索/范本提取/CN……/template-style-guide.json"],
  "search_query_path": "01-检索/search-query.json",
  "candidate_manifest_path": "01-检索/template-candidates.json",
  "selection_report_path": "01-检索/template-selection.json",
  "user_authorization": {
    "user_quote": "……",
    "granted_at": "YYYY-MM-DD"
  }
}
```

阶段门核对：

- 目标 IPC 已确定且非空；
- IPC 相似度与技术相关性均具有正权重，四项权重之和为 1；
- 选定范本的申请人/代理机构著录与候选清单一一致；缺著录时产生待决项而非静默按 0 分排序；
- 选定候选取得逐篇 IPC；
- EPO OPS 是第一尝试来源；
- 降级来源及原因可追溯；
- 搜索清单和候选清单哈希未变化；
- 选定公开号与 `template-style-guide.json` 一致；
- 偏离推荐候选时有明确理由。
