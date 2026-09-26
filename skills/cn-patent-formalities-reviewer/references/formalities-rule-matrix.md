# 中国直接发明申请形式与程序规则矩阵（CN v2）

本矩阵与 `skills/cn-patent-reviewer/references/cn-review-contract-v2.json` 共同构成形式原始检查器的规则输入。检查器只接受直接中国发明申请；PCT 国家阶段不在本矩阵范围内。所有输出均为 `ADVISORY_ONLY`，不表示官方受理、通过、授权或可申报。

本地正文统一存放于：

- `${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/专利法(2020-10-17).md`
- `${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/专利法实施细则(2023-12-21).md`
- `${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/审查指南2026MD/guide-full.md`
- `${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/references/cn-legal-sources/审查指南2026MD/chapters/`

| rule_id | 最低法源定位 | 适用性与证据边界 |
|---|---|---|
| `form_core_documents_and_application_type` | 专利法第二十六条第一款；实施细则第四十三条、第四十四条 | 请求书、说明书、权利要求书、摘要和直接发明申请类型；未知文件只能形成 gap，确认缺件才是确定性 finding。 |
| `form_request_fields_and_party_identity` | 实施细则第十七条、第十九条；指南第一部分第一章4.1 | 请求书名称、申请人、发明人、地址、代理及签章字段；字段存在不证明权属或身份真实性。 |
| `form_language_format_and_execution` | 实施细则第二条、第三条、第四十四条、第一百四十六条；指南第五部分第一章 | 语言、译文、电子/纸件介质、签字盖章和官方格式；UTF-8 无 BOM 是产品输入规范，不等同全部法定电子格式。 |
| `form_title_consistency_and_quality` | 实施细则第二十条；指南第一部分第一章4.1.1、4.2及第二部分第二章2.2.1 | 三份真实文书名称应一致、清楚、简要；manifest 自报标题最多形成人工复核 gap。 |
| `form_specification_structure_and_drafting` | 实施细则第二十条；指南第一部分第一章4.2及第二部分第二章2.2 | 技术领域、背景技术、发明内容、附图说明、具体实施方式；章节缺失不自动等同充分公开不足。 |
| `form_claim_presentation_and_reference_form` | 实施细则第二十二条至第二十五条；指南第一部分第一章4.4及第二部分第二章3.3 | 编号、主题、独立/从属结构和引用形式（含多项从属择一与基础限制）；形式筛查不替代清楚、支持和必要技术特征审查；一项发明一个独立权利要求不等于整件申请只能有一个独立权利要求。 |
| `form_abstract_content_and_length` | 实施细则第二十六条第一款；指南第一部分第一章4.5.1 | 摘要名称、技术领域、问题、方案要点、用途和不超过300字；内容准确性仍需人工复核。 |
| `form_abstract_figure_designation` | 实施细则第二十六条第二款；指南第一部分第一章4.5.2 | 有附图时的摘要附图指定；无附图或适用性不明时输出条件 gap。 |
| `form_drawings_requiredness_and_presence` | 专利法第二十六条第三款；实施细则第二十条、第二十一条、第四十六条 | 发明申请按实际需要附图，正文明确引用时核对存在性；缺图补交或取消附图说明适用第四十六条；不得机械套用实用新型规则。 |
| `form_drawing_numbering_reference_signs_and_graphic_form` | 实施细则第二十一条；指南第一部分第一章4.3及第二部分第二章2.3 | 图号、附图说明、实施方式引用、标记和真实图面质量；文本或 manifest 不能证明视觉事实。附图标记清单应为附图说明章节末尾"图中：100-…、110-…。"的单段句式；脚本对该章节内的表格、项目符号和逐行清单三种形态做确定性文本筛查并记 `WARNING`（形态不合撰写惯例与 CPC 文本导入要求，但无直接法源禁止，故不升级为 `DETERMINISTIC_FAIL`）；标记名称是否与正文一致、标记指向是否正确仍须人工与图面核验。 |
| `form_sequence_listing` | 实施细则第二十条第四款；指南第一部分第一章4.2及第二部分第二章2.2 | 涉及核苷酸/氨基酸序列时检查序列表及计算机可读文件；适用性不明形成条件 gap。 |
| `form_biological_material_deposit` | 实施细则第二十七条；指南第一部分第一章5.2 | 新生物材料公众不可得且文字不足以实施时检查保藏单位、日期、编号和证明；生物技术标签不当然触发。 |
| `form_genetic_resource_statement` | 专利法第二十六条第五款；实施细则第二十九条；指南第一部分第一章5.3 | 依赖遗传资源时检查请求书说明、直接/原始来源或无法说明理由；来源披露不等于获取合法。 |
| `form_priority_declaration_and_documents` | 专利法第二十九条、第三十条；实施细则第三十四条至第三十七条；指南第一部分第一章6.2 | 主张优先权时检查声明、基础申请、证明副本、转让和费用记录；手续存在不等于逐项权利要求享有优先权。 |
| `form_article_24_declaration_and_proof` | 实施细则第三十三条；指南第一部分第一章6.3 | 主张第二十四条公开例外时检查声明、公开事件、日期和证明；不替代实体宽限期判断。 |
| `form_divisional_filing_procedure` | 实施细则第四十八条、第四十九条；指南第一部分第一章5.1 | 分案申请的原申请号、类型、日期、程序状态和分案请求；字段正确不证明内容未超范围。 |
| `form_substantive_examination_request_procedure` | 专利法第三十五条、第三十六条；实施细则第五十五条；指南第一部分第一章6.4 | 直接发明申请实审请求、有效日期、费用和参考资料；提出请求不证明实体条件。 |

资源规范：形式文书总字节数不超过 25,165,824（24 MiB），manifest 不超过 4,194,304，单文书不超过 8,388,608，文书不超过 256，JSON 深度不超过 64，字符串不超过 1,048,576，findings/gaps/checks 分别不超过 5,000/5,000/10,000，报告不超过 16,777,216 字节；资源失败退出码固定为 `4`，且不得生成法律 finding。
