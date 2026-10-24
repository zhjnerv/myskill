# 2-D：区别特征表（阶段 3 的唯一事实来源）

### 2-D：区别特征表（阶段 3 的唯一事实来源）

权利要求书、说明书和说明书附图各自持有一份技术事实副本、彼此只靠散文连接，是本工作流最深的结构性缺陷：范本学习、检索边界和起草三段各记一套特征编号，谁也对不上谁。**这三份法定文件必须由同一张台账派生。**

新案件固定使用 `cn-patent-feature-ledger/v2`（schema 见 `references/feature-ledger-schema-v2.json`）；v1 schema 已移至 `references/legacy/`，仅供旧案件回放对照，脚本不再加载。v2 台账，每个特征登记一次并绑定它在三份文件中的落点：

- `classification`：`preamble`（与最接近现有技术共有，写入独权前序）／`distinguishing`（区别特征，写入特征部分或从属项）／`fallback_only`（不进权利要求，仅作第三十三条弹药写入说明书）；
- `prior_art_status.verdict`：**没有 `novel` 这个取值**。检索只支持"截至〔日期〕在〔已检索出口〕中未发现"，不支持"不存在现有技术"；
- `evidence`：来自**实现本身**的证据位置，不是挖掘 agent 的摘要；
- `flow`：逐特征记录动作阶段、输入对象、处理主体、处理动作、输出对象、下游特征和异常路径；
- `claim_data_flows`：逐项独立权利要求记录入口、顺序链、汇合点、正常出口、异常出口和存储点；
- `method_system_pairs`：复算方法独权和系统独权是否覆盖同一必要数据链，系统侧必须登记实际处理模块；
- `exception_paths`：按触发条件、分支动作、结果值、置信度、检查级终态、原因码和存储字段闭合；
- `claim_sites` / `spec_sites` / `drawing_sites`：三份文件中的落点。附图落点区分 `component`（部件标记，须进附图标记清单）与 `step`（步骤号，**不进**附图标记清单）——两者共用同一数字空间时，任何按数字做的图文自动核对都会误报。

建立台账后跑四向对账，并产出人类可读的区别特征表：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/build_feature_ledger.py" \
  --ledger "<feature-ledger.json>" \
  --claims "<权利要求书.txt>" \
  --specification "<说明书.txt>" \
  --output "<feature-ledger-report.json>" \
  --table "<区别特征表.md>" \
  --drawing-brief "<drawing-brief.json>"  # 绘图合同形成后追加复算
```

对账方向是四条，缺一不可：台账→权利要求（登记的落点在原文中确实存在）、权利要求→台账（每一项权利要求都有台账来源，没有孤儿项）、台账→说明书（每个特征在说明书有可检索到的落点）、台账↔附图标记清单（互为全集，且步骤号不混入清单）。

首次建立台账时权利要求与说明书尚未撰写，此时只需通过合同校验；阶段 3 每完成一份文件即重跑一次，阶段 5 收窄权利要求后必须重跑。**退出码 `0` 只表示四向登记可对账，不代表清楚、支持、必要技术特征或创造性成立。**

