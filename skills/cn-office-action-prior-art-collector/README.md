# 审查意见答复 · 材料准备

知产实务工作台 · 实务技能 | `cn-office-action-prior-art-collector`

用于中国专利"审查中"阶段自动化解析审查意见通知书（OA）、提取著录项目与审查意见、规范化专利申请号与公开号，并通过公开开放渠道（Google Patents / Espacenet）检索公开号与批量下载对比文件说明书 PDF 的轻量级开源 Agent Skill。

---

## 特性亮点

1. **零外部强制依赖（Pure Python 3.8+）**：
   - 核心脚本全部使用 Python 标准库（`urllib.request`、`zipfile`、`xml.etree`、`re`、`json`、`argparse`）实现。
   - 解析 DOCX、解析文本、解析基础 PDF、网络检索与下载无需额外 `pip install` 任何第三方包。
   - 可选安装 `pymupdf`（`fitz`）以增强复杂 PDF 文本层的解析精度；若未安装，自动无缝降级至内置轻量流解析器。
2. **严密的专利规则算法库**：
   - 内置中国专利申请号校验位模 11 权重算法（权重数组 `[2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]`）。
   - 覆盖中国 (CN)、美国 (US)、世界知识产权组织 (WO/PCT)、欧洲 (EP)、日本 (JP) 等专利文献号的补零、年份展开与格式规范化。
   - 自动依据中国申请号第 5 位代码或各国种类代码（Kind Code）推断法律类型（发明/实用新型/外观）。
3. **精准的通知书栏目边界控制**：
   - 严格限定仅从通知书“第 5 栏”（对比文件引用栏）抽取对比文件号，自动过滤文末附带的“检索报告”，避免引入无关背景技术文献。
   - 自动识别并排除本案申请号本身。
   - 提取正文审查意见段落、具体法条依据（如《专利法》第 22 条第 3 款），并将权利要求编号范围展开（如 `权利要求1-3` -> `[1, 2, 3]`）。
4. **自由资料文档防误报过滤**：
   - 针对交底书、文献清单等非标准文档，收紧数字位数下限（CN 8位、US 7位、WO/EP 6位），有效屏蔽产品型号（如 `CN12345`）及年份数字（如 `US2024年`）。
5. **健壮的公开网络取材与官方兜底**：
   - 自动将中国申请号去除校验位后请求 Google Patents XHR 检索获取本案公开文献号与著录信息。
   - 多候选 URL 链路（直链 -> `zh.pdf` 中文版 -> `en.pdf` 原文版）下载说明书，严格校验 `%PDF-` 字节头与长度。
   - 当公开源未收录 PDF 时，自动生成欧洲专利局（Espacenet）官方文献页详情链接作为备用查阅入口。
6. **无缝对接 LLM 兜底阅读**：
   - 面向扫描件或非标准版式，提供清晰的 Agent 提示词与标准 JSON Schema，便于多模态大模型直接执行视觉兜底抽取并无缝接入后续下载。

---

## 目录结构

```text
cn-office-action-prior-art-collector/
├── SKILL.md                          # Skill 入口主说明与流程规范
├── README.md                         # 本开源说明文档
├── scripts/                          # 可独立运行的自包含脚本
│   ├── normalize_patent_number.py    # 专利号与申请号清洗、规范化、校验与推断
│   ├── extract_citations.py          # 通知书著录项、对比文件与审查意见抽取
│   ├── fetch_patent_documents.py     # 公开号检索、PDF 下载与 Espacenet 备用链接
│   └── selftest.py                   # 标准库 unittest 单元测试套件
└── references/                       # 按需加载的细则参考文档
    ├── patent_number_rules.md        # 专利号编码规则与校验位算法详述
    ├── oa_structure_guide.md         # 审查意见通知书结构与解析边界要点
    ├── llm_fallback_prompt.md        # 扫描件 LLM 兜底抽取指令与 JSON Schema
    └── public_data_sources.md        # 公开数据接口与网络下载机制说明
```

---

## 快速使用

### 1. 运行自测套件验证环境
```bash
python3 scripts/selftest.py
```

### 2. 专利号规范化与校验
```bash
# 规范化并验证中国申请号校验位
python3 scripts/normalize_patent_number.py "202410361819.4" "202110532557x"

# 规范化美国和 PCT 公开号
python3 scripts/normalize_patent_number.py "US2014261802A1" "WO0210929A1"
```

### 3. 从通知书或资料中抽取对比文件
```bash
# 解析审查意见通知书文件 (.pdf / .docx / .txt / .md)
python3 scripts/extract_citations.py "审查意见通知书.pdf" -o citations.json

# 解析自由技术资料或文献清单
python3 scripts/extract_citations.py "技术资料.docx" -m free -o citations.json
```

### 4. 检索本案公开号与下载对比文件 PDF
```bash
# 从已生成的 citations.json 进行批量下载
python3 scripts/fetch_patent_documents.py --from-json citations.json -o ./downloads

# 演练（dry-run）模式：仅生成候选链接与备用查阅入口，不发起实际下载
python3 scripts/fetch_patent_documents.py --dry-run "CN114528944A" "US20200234567A1"

# 根据申请号查询公开文献号
python3 scripts/fetch_patent_documents.py --resolve-app "202210380486.0"
```

### 5. 一键管道流水线
```bash
# 从原始文本直接解析并执行取材演练
python3 scripts/extract_citations.py "oa_text.txt" | python3 scripts/fetch_patent_documents.py --dry-run -o ./downloads
```

---

## 可选依赖说明

本项目默认不需要安装任何第三方 Python 库即可运行全部功能。若需要增强复杂格式 PDF 的文字提取精度，可按需安装：

```bash
pip install pymupdf
```

- 若安装了 `pymupdf`，`extract_citations.py` 会优先使用其高精度布局引擎提取 PDF 文本；
- 若未安装，将自动使用内置纯 Python 标准库的流解压（`zlib`）与 CMap 解析器，确保开箱即用。

---

## 许可证

原创代码与文档采用 [MIT](LICENSE)。随包数据、模板和第三方资料的来源与许可边界见 [NOTICE.md](NOTICE.md)。
