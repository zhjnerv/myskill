# 中国专利审查法源目录（CN v2）

机器规范中的每个维度均绑定以下本地法源定位。转换文本只用于定位；条号、例外、程序条件和法律后果以原始文本为准。

统一共享根目录：

```text
${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/
```

| 法源 ID | 正式名称 | 施行/版本 | 本地来源 |
|---|---|---|---|
| `patent-law-2020` | 《中华人民共和国专利法》（2020 年修正） | 2021-06-01 | `${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/专利法(2020-10-17).md` |
| `implementing-rules-2023` | 《中华人民共和国专利法实施细则》（2023 年修订） | 2024-01-20 | `${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/专利法实施细则(2023-12-21).md` |
| `examination-guidelines-2026` | 《专利审查指南》及 2025 年修改决定 | 2026-01-01 | 全文：`${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/审查指南2026MD/guide-full.md`；分章：`${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/审查指南2026MD/chapters/` |

| 主题 | 最低定位 |
|---|---|
| 排除和技术方案 | 专利法第二条第二款、第五条、第二十五条；指南第二部分第一章、第九章 |
| 三性和充分公开 | 专利法第二十二条、第二十六条第三款；指南第二部分第三至第五章 |
| 权利要求 | 专利法第二十六条第四款；实施细则第二十二条、第二十三条、第二十五条；指南第二部分第二章 |
| 优先权和宽限期 | 专利法第二十九条、第三十条、第二十四条；指南第二部分第三章 |
| 申请文件和程序 | 专利法第二十六条、第二十九条、第三十条、第三十五条、第三十六条；实施细则第二条、第三条、第十七条、第十九条至第二十九条、第三十三条至第三十七条、第四十三条至第四十九条、第五十五条、第一百四十六条 |
| 其他法定事项 | 专利法第九条、第十九条、第二十条、第二十六条第五款；实施细则第八条、第九条、第十一条、第四十七条、第五十条、第五十九条 |
| 特殊领域 | 指南第二部分第九章、第十章、第十一章 |

执行既有规则定位时先读取本地文件。只有核对后续修订、施行状态，或发现本地文本缺失、损坏、相互冲突时才联网核验，联网来源优先使用 CNIPA。

法源目录不授予任何法律结论。每个生产 assessment 必须另外记录其实际使用的条款、章节目和证据位置。
