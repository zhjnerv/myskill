# 商标分类检索

知产实务工作台 · 实务技能 | `cn-trademark-goods-services-recommender`

中国商标商品与服务选类推荐引擎（Agent Skill）

一个完全独立、零外部依赖（纯 Python 3 标准库）、可离线运行的中国商标申请选类推荐与申报文件生成 Skill。基于国家知识产权局《类似商品和服务区分表》（尼斯分类），通过三轮专业推断漏斗（大类初筛 → 类似群定位 → 具体商品/服务匹配），为企业产品与商业服务推荐最佳商标保护组合，并支持一键生成符合商标局网上申请系统规范的 Excel 导入模版和 CSV 清单。

---

## 核心特性

- **纯标准库实现**：无第三方依赖（无 Node.js、无 openpyxl、无 requests），纯 Python 3.8+ 标准库即可运行，解压/复制即可在任意主机或 Agent 宿主环境中使用。
- **三轮递进推断**：
  - **第一轮：大类初选（45 选 ≤10）**：区分“核心业务”与“扩展保护”（销售渠道、平台服务、软件载体等），给出推荐度与选类理由。
  - **第二轮：类似群定位（选 ≤20）**：精确下钻到相关类似群，展示官方审查注释与跨类别交叉检索规则。
  - **第三轮：商品/服务项选取（每群 1~10 项）**：涵盖规范项（带官方 6 位代码）、重点推荐项（带※）与非规范项目，覆盖关键分段。
- **严格存在性校验与去重**：校验拟申报项目是否真实收录于官方区分表对应群组，自动补齐商品代码，去除重复条目，并把群组代码标准化为申报所需的两位群码。
- **商标局官方 Excel 导入模版导出**：使用原生 `zipfile` + XML 生成完全合规的 `.xlsx` 表格，包含“导入商品信息”工作表、两位群码转换、类间空行分隔以及大类推荐顺位浅色阶背景高亮；同时支持带 UTF-8 BOM 的 CSV 导出。
- **全量内置数据集**：内嵌 45 个大类、498 个类似群、31,749 项商品/服务条目的完整离线索引及审查注释。

---

## 目录结构

```
cn-trademark-goods-services-recommender/
├── SKILL.md                          # Agent Skill 核心规范与指令入口 (<400行)
├── README.md                         # 项目开源说明与数据合规声明
├── TASKS.md                          # 任务清单与验证记录
├── DECISIONS.md                      # 维护决策与取舍
├── CHANGELOG.md                      # 已完成版本记录
├── assets/                           # 静态资源与官方空模板
│   └── 导入商品信息.xlsx             # 商标局网上申请系统空白导入模版
├── data/                             # 区分表完整离线数据集 (~5.3MB)
│   ├── manifest.json                 # 数据清单与元数据
│   ├── classes.json                  # 45 个大类定义及注释
│   ├── groups/                       # 45 个大类的类似群索引 JSON
│   └── details/                      # 498 个类似群的明细 JSON
├── references/                       # 深度领域规范与知识库
│   ├── three_round_methodology.md   # 三轮选类方法学与常见行业保护策略
│   ├── data_schema.md                # 区分表数据集字段字典与结构
│   └── export_template_spec.md       # 商标局申报表格格式约束
├── scripts/                          # 纯标准库自包含 CLI 工具集
│   ├── build_data.py                 # 数据包校验与构建工具
│   ├── list_classes.py               # 第一轮：大类查询与关键词检索
│   ├── list_groups.py                # 第二轮：类似群查询
│   ├── list_items.py                 # 第三轮：类似群内商品项及审查注释查看
│   ├── search_items.py               # 全局跨类别关键词检索
│   ├── validate_selection.py         # 选类结果合法性校验与去重
│   └── export_selection.py           # 导出商标局申报 Excel / CSV
└── tests/                            # 自动化测试套件
    └── test_recommender.py           # 基于 Python 标准库 unittest 的单元测试
```

---

## 快速使用

### 1. 命令行直接调用

```bash
# 1. 查找大类（例如查找关于“智能宠物设备”的相关大类）
python3 scripts/list_classes.py -q "器具"

# 2. 查看第 21 类和第 09 类的类似群
python3 scripts/list_groups.py 21 09

# 3. 检索群内具体商品项目（例如类似群 2114）
python3 scripts/list_items.py 2114 -q "喂食"

# 4. 全局搜索具体关键词
python3 scripts/search_items.py "宠物自动喂食器"

# 5. 校验选类 JSON 文件
python3 scripts/validate_selection.py selection.json -o validated.json

# 6. 导出为商标局网报 Excel 模版
python3 scripts/export_selection.py validated.json -o 商标申报表.xlsx
```

### 2. 结合 AI Agent（如 Claude Code / OpenClaw / Codex / Antigravity）使用

将本目录直接复制到项目的 `.claude/skills/` 或 Agent 的技能目录下，当用户提出类似“帮我推荐商标类别”、“做宠物智能硬件该注册哪些商标”等问题时，Agent 会自动阅读 `SKILL.md`，自主调用脚本完成检索、推断、校验并输出导出文件。

---

## 数据来源与版本说明

- **官方源头**：中华人民共和国国家知识产权局商标局（CNIPA）公布的《类似商品和服务区分表》（基于世界知识产权组织 WIPO《商标注册用商品和服务国际分类》（尼斯分类 Nice Classification）第十二版）。
- **当前数据版本**：2026 年数据快照（对应 `data/manifest.json`，数据采集时间 2026-06，共收录 45 大类、498 类似群、12,576 项官方规范项、19,173 项历年已接受非规范项及 1,006 条审查注释）。

---

## 时效性与免责声明

1. **时效性提示**：国家知识产权局商标局通常于每年 1 月 1 日前后发布当年度《类似商品和服务区分表》微调及《类似商品和服务区分表补充分类》通知。如遇商标局新增或调整项目，请以商标局最新官方公告为准。
2. **法律责任免除**：本 Skill 的推断结果基于区分表结构与商业惯例推荐，仅供企业规划与代理人核稿参考，**不构成正式的商标法律意见**，亦不承诺商标必然通过商标局的形式审查与实质审查。进行正式网上申报前，请由专业商标代理师进行商标近似检索与禁用条款审查。

---

## 许可证

原创代码与文档采用 [MIT](LICENSE)。随包数据、模板和第三方资料的来源与许可边界见 [NOTICE.md](NOTICE.md)。
