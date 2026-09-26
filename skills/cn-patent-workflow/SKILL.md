---
name: cn-patent-workflow
description: 中国发明专利工作的轻量总入口。用于用户要求撰写、审查、检索范本、生成说明书附图或组装中国专利四文书时，先识别当前阶段，再只调用对应的中国专利 Skill 和必要参考文件。不要用于美国、EPO 或 PCT 申请，也不要一次性加载全部中国法源和全部阶段说明。
allowed-tools: Bash, Read, Write
---

# 中国专利轻量工作流

本 Skill 只负责路由、阶段状态和交接，不复制各阶段的法律规则或操作细节。

## 运行根目录

按以下优先级确定项目根目录，并在本次任务的每条命令中使用同一个值：

1. `CN_PATENT_CREATOR_ROOT`；
2. 兼容变量 `CLAUDE_PATENT_CREATOR_CN_ROOT`；
3. 插件环境的 `CLAUDE_PLUGIN_ROOT`；
4. Codex Skill 一键安装默认目录 `${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn`。

根目录必须同时存在 `.codex-plugin/plugin.json`、`skills/` 和
`references/cn-legal-sources/source-index.json`，否则立即停止，不得猜测路径。
一键安装后的 Python 解释器位于根目录 `.venv`；涉及 DOCX 时必须使用该解释器。

## 子 Skill 调用方式

“调用子 Skill”不是复制其规则正文。路由确定后，读取
`<项目根目录>/skills/<子 Skill 名>/SKILL.md`，再严格按该文件执行；完成当前阶段后回到
本路由检查交接物和下一阶段。完整流程允许依次调用多个子 Skill，但任一时刻只加载当前阶段。

## 第一原则

1. 先判断用户当前要完成的唯一阶段，不因“中国专利”四个字加载整个工作流。
2. 规则、法源和脚本只在对应阶段读取。
3. 阶段之间只通过版本化 JSON、申请文件和哈希报告交接。
4. 没有被当前任务消费的资料不进入上下文。
5. 中国法结论只能来自本项目法源和对应 CN Skill，不借用 MPEP、USPTO、EPO 或 PCT 实体规则。
6. 法源先读取 `references/cn-legal-sources/source-index.json`，只加载当前主题列出的分章；不得默认加载审查指南全文。

## 路由

- 完整起草、区别特征表、阶段门、范本风格：调用 `cn-patent-application-creator`。
- 权利要求专项检查：调用 `cn-patent-claims-analyzer`。
- 说明书充分公开和支持：调用 `cn-patent-specification-reviewer`。
- 文件形式与完整性：调用 `cn-patent-formalities-reviewer`。
- 完整申请审查和证据绑定：调用 `cn-patent-reviewer`。
- 中国专利说明书附图：调用 `cn-patent-diagram-generator`。
- DOCX 只在用户要求 Word 交付时组装，默认模板是仓库根目录 `模版.docx`；读取 `cn-patent-application-creator/references/docx-assembly.md`。

## 连续工作

完整申请依次执行：

```text
检索与范本
→ 区别特征表和阶段门
→ 权利要求及说明书
→ 数据流/方法—系统/异常出口复算
→ 权利要求架构门（载体分工/继承拓扑/方法步骤）
→ drawing brief v4与步骤同构门
→ 可选用户范例差异分析与style brief v1确认
→ 原始母版安全重建（同图修改稿）
→ 附图
→ 综合审查
→ 可选 DOCX
→ DOCX 输入/输出哈希复验
→ 附图—DOCX最终交付绑定验证
```

各阶段的入口、必需输入、输出和停止条件见 `references/stage-map.md`。

## 依赖边界

- 不启动 MCP Server，不构建 RAG、FAISS、BM25 或 Embedding 索引。
- EPO/BigQuery 只作为可选数据 provider；缺失时使用有来源的结构化输入或明确停止。
- 附图阶段按需使用 `drawio-skill` 和 Draw.io Desktop CLI。
- DOCX 阶段按需使用 Office 依赖。
