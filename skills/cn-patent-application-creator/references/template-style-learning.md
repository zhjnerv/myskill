# 2-B：提取范本风格并生成起草简报

### 2-B：提取范本风格并生成起草简报

范本全文优先通过现有 BigQuery 专利全文工具获取；无法获取时由用户提供权利要求书、说明书和可选摘要的 UTF-8 文本。每篇范本分别运行分析器：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/analyze_template_style.py" \
  --patent-number "<范本专利号>" \
  --claims "<范本权利要求书.txt>" \
  --specification "<范本说明书.txt>" \
  --abstract "<范本摘要.txt>" \
  --output "<template-style-guide.json>"
```

输出必须通过 `cn-patent-template-style/v1` 合同校验。分析器只提取权利要求数量与依赖结构、平均篇幅、说明书章节与段落分布、实施例数量与**组织方式**、描述倾向、术语/句式、附图类型与标记模式、摘要结构；它不判断范本技术价值或法律有效性。

**实施例数量必须与组织方式一并消费。** `embodiment_organization` 有三个取值：

| 取值 | 含义 | 起草含义 |
|---|---|---|
| `sectioned` | 实施例以独立标题分节，各节平行展开 | 可按数量拆成 `### 实施例N` |
| `single_flow` | 只有一条实施方式脉络，编号仅在行文中提及 | **收敛为一个实施方式**，变体作为替代路径写在同一脉络内 |
| `none` | 全文没有实施例编号 | 具体实施方式为不编号的连续叙述 |

判据是"是否存在实施例标题行"，不是"是否出现实施例三个字"。一个只输出实施例数量的风格指南无法回答说明书该长什么形态——把 `single_flow` 的范本按数量拆成 N 个平行实施例，是范本学习最容易发生也最难察觉的失真。

多篇范本必须用合成脚本产出复合指南，**不得手写**：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/merge_template_styles.py" \
  --guide "<范本1/template-style-guide.json>" \
  --guide "<范本2/template-style-guide.json>" \
  --override "<字段路径>=<新值>=<理由>=<依据>" \
  --output "<composite-template-style-guide.json>"
```

合成规则：数值取中位数，枚举取多数，列表按出现顺序去重合并；组织方式取**最保守值**（`none` < `single_flow` < `sectioned`），因为把单脉络范本误判成分节范本的代价远大于反向。任何偏离机器合成结果的人工值必须经 `--override` 提供，并携带机器值、人工值、理由和依据写入 `provenance.manual_overrides`。**手写的、无审计的复合指南一律校验失败**——手改数字而不留审计，正是错误值一路走到起草端的通道。

确定当前方案实际披露的技术特征数、变体数和可视化组件/流程数后，生成阶段 3 的唯一风格交接文件：

```bash
python3 "$ROOT/scripts/run_python.py" "$ROOT/skills/cn-patent-application-creator/scripts/style_applicator.py" \
  --style-guide "<template-style-guide.json>" \
  --available-features <技术特征数> \
  --available-variations <已披露变体数> \
  --available-components <可视化组件或流程数> \
  --output "<style-brief.json>"
```

未选择范本时省略 `--style-guide`，仍生成默认 `style-brief.json`。输入计数必须大于等于 1；风格指南缺字段、枚举非法或权利要求总数不守恒时必须失败，不得带病回退到默认风格。

`style-brief.json` 固定使用 `cn-patent-style-brief/v1`，只允许影响结构、篇幅和句法偏好。执行优先级不可倒置：

1. 本申请已披露的技术事实；
2. 中国专利法律与形式要求；
3. 现有技术检索后的权利要求边界；
4. 范本风格简报。

严禁从范本复制技术内容、凭风格建议新增未披露特征、为贴近范本删除必要技术特征，或让范本篇幅偏好覆盖 10 项以上权利要求附加费和摘要 300 字等法定/费用边界。

