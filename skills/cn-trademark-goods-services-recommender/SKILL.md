---
name: cn-trademark-goods-services-recommender
description: 根据用户的业务经营描述、产品形态或服务链路，依照中国国家知识产权局公布的《类似商品和服务区分表》（基于尼斯分类）执行三轮递进式商标选类推荐（大类初筛 → 类似群定位 → 具体商品与服务项匹配），并提供本地存在性校验、去重及一键导出商标局网报 Excel/CSV 导入模版。触发场景：(1) 用户需要推荐商标注册类别/类似群/项目，(2) 询问某软硬件产品或商业服务应注册哪些商标大类，(3) 为企业商业项目规划核心与扩展防御类别清单，(4) 生成商标局网报申报导入表格。不要用于：商标近似检索与在先权利冲突比对、商标显著性与绝对禁用条款审查、出具正式商标法律意见、商标驳回复审或异议争议程序。
---

# 商标分类检索

知产实务工作台 · 实务技能 | `cn-trademark-goods-services-recommender`

本 Skill 旨在辅助代理人或申请人完成中国商标注册选类的全流程工作。基于本地离线区分表数据（45 大类、498 类似群、31,700+ 项目），Agent 采用**三轮递进推断法**，配合 Python 标准库工具脚本，闭环完成：
1. **第一轮：大类初筛**（45 选 ≤10 类，区分核心推荐与扩展保护）；
2. **第二轮：类似群定位**（选 ≤20 类似群，核查交叉检索注释）；
3. **第三轮：商品/服务项选取**（每群选 1~10 项，优先官方 6 位码规范项）；
4. **校验与导出**（验证存在性、去重、标准化两码群号并导出商标局导入文件）。

---

## 推荐方法学与决策规则

选类时遵循四大基本原则（详见 [three_round_methodology.md](references/three_round_methodology.md)）：

1. **核心与扩展梯队原则**：
   - **核心推荐**：直接对应产品物理形态或服务本体（如智能宠物喂食器的主体属 `第 21 类 2114` 宠物用器具）。
   - **扩展保护**：覆盖数字化载体与渠道（如控制硬件与 App 归 `第 09 类 0901`；销售推销归 `第 35 类 3503`；云端 SaaS 平台归 `第 42 类 4220`）。
2. **推荐度分级**：分为`强推荐`（核心产品/服务，裸奔致命）、`推荐`（关键业务延伸）、`可考虑`（未来 1-2 年规划方向）、`弱相关`（防卫性防御储备）。
3. **规范项优先原则**：
   - 优先选择带 6 位官方代码的标准商品项（standard），避免审查补正通知。
   - 特殊创新商品若规范表未收录，选取历年审查已接受的非规范项目（nonstandard）。
4. **官方规费优化原则**：中国商标按“每类 10 个商品/服务项目”为基准，单个大类累计超过 10 项时商标局将逐项加收超项官费；单个类似群建议精简挑选 1~10 个核心代表项以聚焦保护范围。

---

## Agent 标准执行工作流

当用户提出选类需求时，Agent 按以下五步执行：

```
[用户输入业务场景]
       │
       ▼
步骤 1: 第一轮大类推理 ──> 运行 `scripts/list_classes.py` 查阅 45 类范围
       │
       ▼
步骤 2: 第二轮类似群定位 ──> 运行 `scripts/list_groups.py <选中大类>` 筛选群组
       │
       ▼
步骤 3: 第三轮商品匹配 ──> 运行 `scripts/list_items.py <类似群>` 挑选代表项
       │
       ▼
步骤 4: 校验与规范化 ──> 运行 `scripts/validate_selection.py` 严格校验
       │
       ▼
步骤 5: 导出申报表格 ──> 运行 `scripts/export_selection.py` 生成 Excel/CSV
```

---

### 步骤 1：第一轮大类初筛

根据用户业务，查看 45 个大类定义并选出最相关的类别（最多 10 个）：

```bash
# 查看所有 45 个大类的范围与官方注释
python3 scripts/list_classes.py

# 或使用关键词检索相关类别（如“软件”、“医疗”、“餐饮”）
python3 scripts/list_classes.py -q "软件"

# 查看特定大类详情（如 09 类）
python3 scripts/list_classes.py 09 -v
```

**Agent 输出要求**：
- 列出选出的大类编号及名称（如 `第 09 类 科学仪器`、`第 21 类 厨房洁具`、`第 35 类 广告销售`、`第 42 类 网站服务`）；
- 标明每个大类的`推荐度`（强推荐/推荐/可考虑/弱相关）与`保护类型`（核心推荐/扩展保护）；
- 给出简明的选类理由。

---

### 步骤 2：第二轮类似群定位

针对第一轮选出的大类，列出其包含的所有类似群，选出 ≤20 个核心群组：

```bash
# 批量列出选定大类下的类似群
python3 scripts/list_groups.py 09 21 35 42

# 或在选中类下按关键词过滤群组
python3 scripts/list_groups.py 21 -q "器具"
```

**Agent 输出要求**：
- 说明选中的类似群编号（如 `0901`、`2114`、`3503`、`4220`）；
- 结合大类理由，明确该群组在业务中对应的具体产品组件或服务环节。

---

### 步骤 3：第三轮商品与服务项选取

为每个入选类似群挑选 1~10 项具体商品/服务：

```bash
# 查看类似群 2114 的所有商品候选（包含官方审查注释）
python3 scripts/list_items.py 2114

# 在群内检索关键词（如“喂食器”）
python3 scripts/list_items.py 2114 -q "喂食器"

# 若群内未找到，可使用全局跨类搜索（支持 --any 多词 OR 检索）
python3 scripts/search_items.py "茶饮料" "加奶" --any -c 30
```

**Agent 决策注意**：
- **拆词与同义词检索**：区分表商品条目使用法定学名，字面检索可能无法直接命中新兴商业用语（如直接搜索“奶茶”无法命中第 30 类的“加奶的茶饮料”）。Agent 应主动进行拆词、同义词展开与多次检索（例如将“奶茶”拆为“奶”、“茶饮料”、“乳”等），或使用 `search_items.py` 的 `--any` 多关键词 OR 选项；
- 细读输出的 `[审查注释与交叉检索]`，注意类似群之间是否存在相互保护或跨类检索规则（如 2907“奶茶（以奶为主）”与 3002“加奶的茶饮料”的归类区分）；
- 优先选择带 6 位编码的规范项并记录其 code；若涉及不同分段（段落），尽量跨段各选 1 项以防抢注。

---

### 步骤 4：校验与去重

将三轮推理形成的选类结果组装为 JSON 并执行自动化校验：

```bash
# 将选类 JSON 送入校验器
python3 scripts/validate_selection.py selection.json -o validated.json
```

**输入 JSON 格式参考（推荐带 code 写法）**：
```json
{
  "classes": [
    {
      "classCode": "21",
      "recommendation": "强推荐",
      "reason": "宠物喂食器硬件主体",
      "protectionType": "核心推荐",
      "groups": [
        {
          "groupCode": "2114",
          "recommendation": "强推荐",
          "reason": "包含小动物及宠物喂食器",
          "protectionType": "核心推荐",
          "items": [
            { "name": "宠物自动喂食器", "code": "" },
            { "name": "小动物喂食器", "code": "" },
            { "name": "宠物自动喂食碗", "code": "210415" }
          ]
        }
      ]
    }
  ]
}
```

**注意事项与校验机制**：
- **群号规格**：`groupCode` 必须使用 4 位完整类似群编号（如 `2114`、`0901`、`3002`），不得填 2 位；2 位申报群码由导出脚本自动换算；若误填 2 位，校验器将明确提示改用 4 位群号。
- **项目编码与星号容错**：推荐尽可能附带 6 位官方 `code`，校验器会优先按 `code` 锁定规范项并核验名称一致性；未附带 `code` 时按名称智能对齐，并支持自动回退去除末尾星号（如填“茶”自动对齐“茶* 300037”）。
- **去重与官费预警**：自动去除群内重复项目；若单个大类累计申报项目超过 10 项，校验器会精确告警超出项数及超项规费风险；类似群层面给出 1~10 项核心聚焦提示。

---

### 步骤 5：导出申报表格

将校验通过的 JSON 导出为符合国家知识产权局商标局网上申请系统要求的导入模版：

```bash
# 导出为商标局申报 Excel 文件（带大类梯度着色）
python3 scripts/export_selection.py validated.json -o 商标申请清单.xlsx

# 或导出为 UTF-8 BOM CSV 文本格式
python3 scripts/export_selection.py validated.json -f csv -o 商标申请清单.csv
```

导出格式规范详见 [export_template_spec.md](references/export_template_spec.md)。

---

## 脚本速查表

| 脚本路径 | 核心功能 | 常用参数 |
| --- | --- | --- |
| `scripts/list_classes.py` | 列出或检索 45 个大类 | `[class_code]`, `-q/--query`, `-v/--verbose`, `--json` |
| `scripts/list_groups.py` | 列出指定大类下的类似群 | `class_codes...`, `-c/--classes`, `--all`, `-q/--query`, `--json` |
| `scripts/list_items.py` | 列出群下商品项与审查注 | `group_code`, `-q/--query`, `-t/--type standard`, `-n/--limit`, `--json` |
| `scripts/search_items.py` | 全局跨类别关键词检索 | `query`, `-c/--classes`, `-t/--type item`, `-n/--limit`, `--json` |
| `scripts/validate_selection.py` | 校验存在性、去重与标准化 | `input.json`, `-o output.json`, `--json` |
| `scripts/export_selection.py` | 导出商标局申报表格 | `input.json`, `-o file.xlsx`, `-f xlsx/csv` |
| `scripts/build_data.py` | 数据包构建与完整性校验 | `--validate-only`, `--source <dir>`, `--output <dir>` |

---

## 领域知识与数据规范参考

- **[选类三轮推断方法学](references/three_round_methodology.md)**：深入了解核心类别、防御类别规划策略及常见行业（硬件/软件/新零售/食品）标准保护矩阵。
- **[数据结构与规范定义](references/data_schema.md)**：数据字典定义、区分表层级关系与版本说明。
- **[商标局网报模版规范](references/export_template_spec.md)**：Excel 导入模板单元格对齐、两位类似群转换机制及类间空行规范。
