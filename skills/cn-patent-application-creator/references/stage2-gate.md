# 2-E：阶段门（未过门不得起草）

### 2-E：阶段门（未过门不得起草）

约束写成文档口号就等于没有约束。"人工检索未完成时必须写未完成"这句话，在"写了未完成再继续"的路径下字面合规——上一轮正是这样在检索未完成、范本未确认的情况下产出了权利要求和说明书，事后才补范本学习并返工三轮。

因此检索、IPC 判定、范本加权选择、用户确认和区别特征表必须变成机器状态位。新案件写进 `cn-patent-stage2-gate/v2`（schema 见 `references/stage2-gate-schema-v2.json`）；v1 只用于旧案件回放，不满足新流程的 IPC 证据要求：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/check_stage_gate.py" \
  --state "<stage2-gate.json>" \
  --workspace "<案件根目录>" \
  --output "<stage2-gate-report.json>"
```

| 状态位 | 放行条件 |
|---|---|
| `cnipa_manual_search.status` | `completed` 须附逐条检索记录；`partial`／`not_completed` 无用户原话时按保守默认继续并写入待决清单 |
| `template_selection.status` | `confirmed` 须列出已生成的 style-guide；`declined` 和 `pending` 无用户原话时按保守默认继续并写入待决清单 |
| 范本选择报告 | `cn-patent-template-selection/v2`，四项权重之和为 1、技术/IPC 正权重、四项加权得分可复算、选定范本主体著录与候选清单一一致 |
| 选定范本主体著录 | 缺申请人或代理机构时按 0 分计并写入待决清单，指向技术+IPC 退化风险 |
| `style_brief_path` | 存在、schema 正确、来源模式与范本确认状态一致、含 `organization` |
| `feature_ledger_path` | 存在、schema 正确、至少有一个区别特征 |

对于缺少用户原话的情况，阶段门不再阻断，而是无用户原话时按保守默认继续并写入待决清单。只有文件缺失、哈希不一致、schema 错误才阻断。这确保在保证产物有效性的前提下，不因子环节等待人为确认而中断撰写。待决事项详情参见 `references/pending-decisions.md`。退出码 `2` 表示未过门（遇文件/哈希/schema级硬阻断），此时不得开始撰写权利要求与说明书。

