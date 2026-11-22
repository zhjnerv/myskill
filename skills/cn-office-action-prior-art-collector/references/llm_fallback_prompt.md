# LLM 兜底抽取指令与 JSON Schema

当规则解析器（`extract_citations.py`）面对扫描版 PDF、OCR 错位、非标准格式或排版混乱的审查意见通知书导致提取失败（如未识别到申请号或第 5 栏对比文件为空）时，调用本 Skill 的 Agent 可直接发挥自身的长文本理解或多模态（视觉）阅读能力，执行兜底提取。

---

## 1. Agent 提示词模板 (Prompt)

向当前 Agent（或多模态模型）输入以下指令和文档内容/页面图像：

```text
你是一名中国专利审查案卷解析专家。请直接阅读所附的中国专利审查意见通知书文本或图像，提取案卷核心字段，并仅输出一个合法的 JSON 对象，不要输出任何额外的解释或 Markdown 包装。

提取规则：
1. application_number: 提取申请号，保留小数点和校验位（如 202210380486.0），若无则为 null。
2. title: 提取发明创造名称。
3. applicant: 提取申请人名称。
4. mailing_date: 提取发文日期。
5. patent_type: 根据申请号第5位或发明名称推断（发明专利、实用新型专利、外观设计专利）。
6. cited_document_ids: 重点！仅提取通知书“第5栏”（即“本通知书是在进行了检索的情况下作出的...本通知书引用下列对比文件...”）中所列出的对比文件号。
   - 严禁提取通知书附页“检索报告”中的文献！
   - 严禁将本案申请号混入对比文件！
   - 仅保留文献号/公开号字符串（如 CN114528944A、US20200234567A1）。
7. objections: 提取正文中的实质审查意见。
   - 识别其涉及的权利要求编号（展开为数组，如 [1, 2, 3]）；
   - 识别法律依据（如“专利法第二十二条第三款”）；
   - 简短概述审查员的核心争点。
8. confidence: 置信度评估（high/medium/low）。
9. notes: 简要说明提取是否完整、是否有扫描模糊或存疑之处。
```

---

## 2. 结构化 JSON Schema

Agent 兜底提取的输出必须遵循如下 JSON Schema：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OfficeActionLLMExtraction",
  "type": "object",
  "required": ["application_number", "cited_document_ids", "objections", "confidence"],
  "properties": {
    "application_number": {
      "type": ["string", "null"],
      "description": "中国专利申请号，含校验位，如 202210380486.0"
    },
    "title": {
      "type": ["string", "null"],
      "description": "发明创造名称"
    },
    "applicant": {
      "type": ["string", "null"],
      "description": "申请人名称"
    },
    "mailing_date": {
      "type": ["string", "null"],
      "description": "通知书发文日，如 2025年07月25日"
    },
    "patent_type": {
      "type": ["string", "null"],
      "enum": ["发明专利", "实用新型专利", "外观设计专利", null]
    },
    "cited_document_ids": {
      "type": "array",
      "items": { "type": "string" },
      "description": "第 5 栏引用的对比文件公开号列表"
    },
    "objections": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["objection_id", "title", "claim_numbers", "legal_basis", "summary"],
        "properties": {
          "objection_id": { "type": "string" },
          "title": { "type": "string" },
          "claim_numbers": {
            "type": "array",
            "items": { "type": "integer" }
          },
          "legal_basis": { "type": ["string", "null"] },
          "summary": { "type": "string" }
        }
      }
    },
    "confidence": {
      "type": "string",
      "enum": ["high", "medium", "low"]
    },
    "notes": {
      "type": "string",
      "description": "提取完整度或异常说明"
    }
  }
}
```

---

## 3. 将兜底结果对接到取材下载脚本

Agent 获取到上述 JSON 后，可以直接组装为符合 `fetch_patent_documents.py` 要求的格式并输入：

```bash
# Agent 将 JSON 写入临时文件或管道
python3 scripts/fetch_patent_documents.py --from-json /path/to/llm_result.json -o ./downloads
```

其中 `llm_result.json` 顶层包含：
- `bibliographic_items.application_number`：用于自动检索公开号并下载本案说明书；
- `cited_documents`：包含 `[{"document_id": "CN..."}]`，驱动批量下载对比文件 PDF。
