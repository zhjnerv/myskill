# 外部能力 Provider 合同

中国专利 Skill 包不反向导入 `Claude-Patent-Creator`，也不启动其 MCP Server。跨项目能力通过进程边界或结构化文件注入。

## EPO IPC Provider

环境变量或参数：

```text
CN_PATENT_EPO_PROVIDER_COMMAND
--epo-provider-command
```

调用方式：

```text
<provider argv...> <publication_number>
```

要求：

- 不经过 shell；
- 退出码 `0` 表示 provider 正常返回；
- stdout 为单个 JSON 对象；
- 成功格式：`{"ipc_codes":["G06F11/36"]}`；
- 失败可返回非零退出码，或 `{"error":"原因"}`；
- 不得在输出中泄露 key、secret 或授权头。

未配置 provider 时，范本选择按“分类缓存 → 候选输入”降级，并保留 EPO 未尝试的原因。

## BigQuery / 检索 Provider

当前 Skill 只生成结构化检索式和检索清单，不直接依赖 BigQuery SDK。调用方可把检索结果整理成候选清单后交回 Skill。

## Draw.io Provider

附图阶段依赖独立 `drawio-skill` 和 Draw.io Desktop CLI。中国专利 Skill 只负责绘图合同、专利样式和最终验收。
用户提供修改后的Draw.io范例时，先由 `analyze_drawing_reference.py` 生成并经用户批准 `cn-patent-drawing-style-brief/v1`；`drawio-skill` 只复用其中的视觉语法，技术节点、关系和端点仍以drawing brief为准。正式PNG必须按 `diagram` 内容边界导出并通过白边像素门禁。
