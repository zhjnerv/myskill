---
name: cn-office-action-prior-art-collector
description: 中国专利审查意见通知书（OA）案卷材料取材与对比文件补齐 Skill。用于在收到中国发明/实用新型专利审查意见通知书（PDF/DOCX/TXT/MD）或技术资料清单时，自动提取著录项目、正文审查意见、对比文件号与本案申请号，规范化多国专利号并校验中国申请号校验位，通过公开渠道（Google Patents / Espacenet）检索公开号并下载对比文件与本案公开说明书 PDF，形成结构化对比文件台账。不用于答复意见撰写、代理人攻防论辩或驳回复审。
---

# 审查意见答复 · 材料准备

知产实务工作台 · 实务技能 | `cn-office-action-prior-art-collector`

本 Skill 聚焦于中国专利"审查中"阶段的材料解析与案卷收集准备，自动化完成通知书解析、专利号规范化、公开文献号检索以及对比文件 PDF 下载补齐。

> **边界说明**：本 Skill 仅负责案卷材料的提取、规范化与对比文件取材补齐，不包含后续的答复思路构思、代理人/审查员攻防演练或意见陈述书撰写（答复撰写属于独立的后续阶段）。

---

## 一、核心工作流程

```
[审查意见通知书 / 资料文档] (.pdf / .docx / .txt / .md)
                │
                ▼
【步骤 1：文档解析与对比文件号抽取】───> python3 scripts/extract_citations.py
                │
                ├─ (解析成功) ──> 结构化案卷 JSON (著录项 + 第5栏对比文件 + 正文意见)
                └─ (解析异常/扫描件) ──> 触发 LLM 兜底阅读 (见 references/llm_fallback_prompt.md)
                │
                ▼
【步骤 2：专利号清洗与校验位规范化】───> python3 scripts/normalize_patent_number.py
                │
                ├─ 中国申请号：验证模 11 校验位，格式化显示，推断专利类型
                └─ 对比文件号：统一 US/WO/CN/EP 标准格式，剔除校验位
                │
                ▼
【步骤 3：公开文献检索与 PDF 取材补齐】─> python3 scripts/fetch_patent_documents.py
                │
                ├─ 本案公开检索：申请号剔除校验位 ──> Google Patents XHR ──> 获取公开号与 PDF
                ├─ 对比文件下载：多候选 URL 抓取 ──> 校验 %PDF- 字节头 ──> 保存本地 PDF
                └─ 失败兜底：自动生成 Espacenet 官方文献页链接
                │
                ▼
【步骤 4：生成对比文件清单台账】──────> 输出结构化 Markdown 表格与案卷摘要
```

---

## 二、详细操作步骤与命令

> **脚本调用路径说明**：下述命令中的脚本路径（如 `python3 scripts/extract_citations.py`）均相对 Skill 根目录。若当前执行环境的工作目录不同，请使用 Skill 根目录的绝对路径或相应相对路径调用（例如 `python3 <skill-dir>/scripts/extract_citations.py`）。

### 步骤 1：文档文本提取与对比文件抽取
运行 `extract_citations.py` 处理用户上传的文档：

```bash
# 自动模式（自动识别正式 OA 通知书或自由文献清单）
python3 scripts/extract_citations.py "path/to/office_action.pdf" -o citations.json

# 或直接传入文本测试
python3 scripts/extract_citations.py --raw-text "..." -m auto
```

**判断规则与注意事项**：
1. **严格区分第 5 栏与检索报告**：正式 OA 必须仅从“第 5 栏”（对比文件引用栏）提取文献号，严禁抓取文档末尾附带的“检索报告”，避免引入无关的背景文献。
2. **剔除本案号码**：若第 5 栏中出现本案申请号本身，自动识别并排除。
3. **正文审查意见解析**：自动按法条依据（如《专利法》第 22 条第 3 款）提取正文段落，并将权利要求范围展开为具体数字列表（如 `[1, 2, 3]`）。
4. **自由资料文档模式**：若输入非正式通知书，脚本自动采用收紧正则召回 CN/US/EP/WO 等有效号码，自动过滤诸如“型号 CN12345”或“US 2024 年”等误命中。

**失败兜底**：若文档为扫描件或提取文本为空，当前 Agent 应参考 [references/llm_fallback_prompt.md](references/llm_fallback_prompt.md) 直接阅读文档多模态内容，按给定 JSON Schema 输出提取结果。

---

### 步骤 2：号码规范化与校验
若需要对单独的专利号、申请号进行校验或格式化：

```bash
# 单号或多号规范化与校验
python3 scripts/normalize_patent_number.py "202410361819.4" "US2014261802A1" "WO0210929A1"

# 从文件批量读取
python3 scripts/normalize_patent_number.py -f numbers.txt -o normalized.json
```

**关键规则**（详见 [references/patent_number_rules.md](references/patent_number_rules.md)）：
- **中国申请号模 11 算法**：权重 `[2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]`，加权和取模 11，余数 0-9 对应数字，10 对应 `'X'`。
- **US 补零**：申请公开号补足 7 位序号（`US2014261802A1` -> `US20140261802A1`）。
- **WO 年份展开**：两位年份展开为四位年份（`WO0210929A1` -> `WO2002010929A1`）。
- **类型推断**：中国申请号第 5 位代码（1/8 为发明，2/9 为实用新型，3 为外观）。

---

### 步骤 3：公开文献检索与 PDF 说明书下载
利用 `fetch_patent_documents.py` 自动化补齐文献材料：

```bash
# 管道级连模式：一步完成从文本提取到批量下载演练（dry-run）
python3 scripts/extract_citations.py "path/to/oa.txt" | python3 scripts/fetch_patent_documents.py --dry-run -o ./downloads

# 读取已生成的 citations.json 进行真实下载
python3 scripts/fetch_patent_documents.py --from-json citations.json -o ./downloads

# 单独根据申请号检索公开号（自动去除校验位后查 Google Patents XHR）
python3 scripts/fetch_patent_documents.py --resolve-app "202210380486.0"

# 单独下载指定公开号 PDF
python3 scripts/fetch_patent_documents.py "CN114528944A" "US20200234567A1" -o ./downloads
```

**网络取材与校验要点**（详见 [references/public_data_sources.md](references/public_data_sources.md)）：
1. **多候选源优先顺序**：直链 -> `zh.pdf`（中文说明书） -> `en.pdf`（英文说明书）。
2. **严格二进制校验**：必须验证响应前 10 字节包含 `b"%PDF-"` 且长度 $> 1000$ 字节，杜绝将 HTML 404 或拦截页面误存为 PDF。
3. **限流保护与预期兜底**：Google Patents 在部分网络环境或高频访问时可能返回 HTTP 503/429 或验证拦截网页。脚本会自动捕获并识别非 PDF 响应，绝不落盘损坏文件，同时自动生成欧洲专利局（Espacenet）官方文献详情页链接（`fallback_url`）。此时引导用户按 Espacenet 链接直接查阅或人工下载说明书，属于系统预期的标准兜底路径。
4. **批量请求延时**：批量下载各对比文件之间主动休眠 1.0~2.0 秒随机延迟，避免触碰源站频率限制。

---

## 三、最终输出规范：对比文件清单台账模板

当完成案卷取材后，向用户或后续流程呈现标准对比文件台账：

> **字段取值与状态说明**：
> - **发文日**：若通知书中未明确标明或无法确定，显示为 `未载明`；
> - **申请号校验位**：根据 `check_digit_valid` 字段取值：`true` 显示为“校验位正确”，`false` 显示为“校验位异常（请核对）”，`null` 显示为“未提供校验位或非标准格式”。

```markdown
### 案卷基础信息
- **发明创造名称**：粉囊包咖啡机的自动掉包装置
- **申请号**：202210380486.0（发明专利，校验位正确）
- **申请人**：宁波示例电器有限公司
- **通知书类别**：第一次审查意见通知书（发文日：2025年07月25日 / 未载明）
- **本案公开号**：CN118161961A（[本地 PDF](file:///path/to/downloads/application/CN118161961A.pdf)）

### 对比文件与取材清单
| 序号 | 标签 | 规范文献号 | 原始出现上下文 | 取材状态 | 本地文件 / 备用查阅入口 |
|:---:|:---:|:---|:---|:---:|:---|
| 1 | 对比文件1 | `CN114528944A` | 第5栏引用 | ✓ 已下载 | [CN114528944A.pdf](file:///path/to/downloads/prior_art/CN114528944A.pdf) |
| 2 | 对比文件2 | `US20200234567A1` | 第5栏引用 | ⚠ 缺PDF | [Espacenet 官方查阅入口](https://worldwide.espacenet.com/publicationDetails/biblio?CC=US&NR=20200234567A1&KC=A1&FT=D) |

### 审查意见核心争点速览
1. **OBJ-1（创造性意见）**：权利要求 1-3 不符合《专利法》第二十二条第三款，审查员认为对比文件 1 公开了主要结构，对比文件 2 公开了掉包检测特征，结合属于公知常识。
```
