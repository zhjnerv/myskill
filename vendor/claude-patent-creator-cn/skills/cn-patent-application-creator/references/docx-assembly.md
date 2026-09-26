# 中国发明专利申请文件 DOCX 组装规范

本规范用于把 `02-申请文件` 中的权利要求书、说明书、说明书摘要和说明书附图，按照用户提供的 Word 模板组装为一个可编辑 `.docx`。它不替代四文书源文件；DOCX 是从已验证源文件机械生成的交付副本。

## 触发条件

满足任一条件时执行：

- 用户要求“合并成一个 Word / DOCX”；
- 交付要求明确包含单一 DOCX 申请文件。

默认模板是仓库根目录的 `模版.docx`。未找到该文件时不得猜造专用模板，也不得改用案件目录中的 `输出模版.docx`。可以继续交付四文书源文件，并把 DOCX 组装标记为待完成。只有显式传入 `--template` 才替换项目模板。

## 输入合同

案件目录至少包含：

```text
<案件目录>/
└─ 02-申请文件/
   ├─ 权利要求书.md
   ├─ 说明书.md
   ├─ 说明书摘要.md
   ├─ 说明书附图.md
   └─ 说明书附图/
      ├─ 图1-....png
      └─ ...
```

项目模板位于：

```text
<仓库根目录>/模版.docx
```

`模版.docx` 正文中的示例权利要求、说明书、图号和示例图只用于展示版式，不是申请内容。组装前会删除全部正文，只保留分节、页眉页脚、页码、行号、样式和权利要求编号定义。最终文字只来自本案四文书，最终图片只来自本案 PNG。模板里的占位句、旧发明名称和示例图不得出现在成品页面中。

模板必须满足：

1. 恰好包含五个新页分节，页眉依次为“权利要求书、说明书、说明书附图、说明书摘要、摘要附图”；
2. 首段带有可复用的权利要求自动编号定义；
3. 存在 `Normal (Web)`、`Title`、`Heading 1`、`正文2`、`附图图号` 段落样式；
4. 存在 Word 内置 `Strong` 字符样式；中文 Word 界面显示为“要点”；
5. 分节内已经定义所需页边距、行号、页码、页眉和页脚。

模板合同不满足时必须 fail-fast，不得用手工加粗、手工页码或临时样式静默替代。

`权利要求书.md` 以行首 `N.` 识别权利要求边界；相邻权利要求可以只用换行
分隔，也可以使用空行分隔。单项权利要求跨多行时，未出现新编号的非空行并入
当前项。组装器必须核对编号从 1 连续递增，不能把紧凑编号列表合并为一项。

## Markdown 公式合同

### 推荐写法

行内公式使用：

```markdown
患者年龄为 $a$，相邻年龄档为 $a_i$ 和 $a_(i+1)$。
```

独立公式使用：

```markdown
$$
C(P,a)=C(P,a_i)+(a-a_i)×[C(P,a_(i+1))-C(P,a_i)]/(a_(i+1)-a_i)
$$
```

或者：

````markdown
```math
ED_CT=Q_CT×C_CT(P,a)
```
````

为兼容现有案件，脚本也会识别“独立成段、包含等号、无中文正文”的线性公式。新案件不得依赖模糊猜测，应优先使用 `$...$`、`$$...$$` 或 `math` 代码块明确标记。

### LaTeX 宏兼容

组装器支持常见 LaTeX 宏按最长匹配转为 Unicode 或普通标识符：希腊字母 `\alpha`、`\beta`、`\Gamma` 等转为 α、β、Γ；大型运算符 `\sum`、`\prod`、`\int` 转为 ∑、∏、∫；二元运算符 `\cdot`、`\times`、`\pm` 转为 ·、×、±；关系符 `\leq`、`\in`、`\subset` 转为 ≤、∈、⊂；逻辑集合符 `\forall`、`\emptyset` 等转为 ∀、∅；箭头 `\leftarrow`、`\Rightarrow` 等转为 ←、⇒；定界符与省略号 `\langle`、`\ldots`、`\cdots` 转为 ⟨、…、⋯。函数名宏 `\max`、`\min`、`\log`、`\sin` 等去掉反斜杠后保留为普通名称，例如 `\max_{w}` 转为 `max_{w}`。

结构宏如 `\frac`、`\sqrt`、`\text`、修饰宏如 `\hat`、`\vec` 以及转义 `\_`、`\\` 等不支持，组装器会报错并列出宏名；请改写为 `a/b`、`x_{i}`、`x^{2}` 或直接用 Unicode 符号。组装后的 OMML 中不含反斜杠。

### Word 公式要求

- 公式必须转换为 Word 原生 `m:oMath` 对象；
- 组装器直接生成 OMML 的 `m:f`、`m:sSub`、`m:sSup`、`m:sSubSup` 和 `m:d` 等结构，不依赖 Microsoft Word COM；
- Linux、macOS 和 Windows 生成的下标、上标、分式及括号必须保持可编辑结构；
- 普通字符、图片公式和仅设置 Cambria Math 字体均不算公式转换完成；
- 保存后必须检查实际 `m:oMath` 数量与登记数量一致，并拒绝任何遗留公式占位符。

## 说明书与权利要求排版合同

- 说明书正文不得输出 `[0001]`、`[0002]` 等段落编号；解析旧源文件时统一移除该类前缀。
- 方法权利要求包含连续 `Sxxx：` 步骤时，权利要求首句保留一级自动编号，各步骤分别形成独立段落。步骤层级优先采用模板正文已经示范的 `numId/ilvl`；`模版.docx` 的示范是权利要求 `numId=29` 的第 2 层（`numFmt=none`，不额外生成字母编号）。模板没有示范步骤段时，才退回已定义的最小子层；单级模板使用第 0 层。
- `模版.docx` 的权利要求编号通过 `w:numStyleLink` 指向编号样式，抽象编号本身没有 `w:lvl`。组装和复验必须顺着样式解析真实层级，不能把这种编号当成空定义。
- “附图说明”必须一图一句，只说明图名，不展开解释图中模块、流程、分支或技术效果；随后单独保留一段以“图中：”开头的附图标记说明。
- “具体实施方式”标题之后先写结合附图说明具体实施例的引导段，再设置明显的“实施例1。”标题，然后进入实施例正文。
- 实施例正文必须穿插引用全部说明书附图，例如“如图1所示”“结合图2所示”，不得把附图解释全部堆在“附图说明”中。

## 待决标记

最终文档可输出两种副本，由 `--copy {review,submission}` 控制。待决事项会以 `【待决-D001】` 等形式标记在原文。
- **review (默认)**：客户审稿版。标记保留在文中，并且包含标记的整个段落会被添加黄色高亮（`w:highlight w:val="yellow"`），公式保持不变。此副本供发明人或代理人结合上下文决策。
- **submission**：提交副本。标记会被正则表达式 `【待决-D\d{3}】` 自动剥离，且不添加高亮。剥离后若检测到残缺的“【待决”字样，将引发组装错误。
组装报告和独立验证工具也会校验：review 版须包含所有收集到的待决标记 ID，而 submission 版须绝对不含任何“【待决”或黄色高亮。

## 样式映射

| 内容 | 模板样式 |
|---|---|
| 权利要求 | 复制模板首项权利要求的段落属性和自动编号 |
| 说明书发明名称 | `Title` |
| 技术领域、背景技术、发明内容、附图说明、具体实施方式 | `Heading 1` 段落 + `Strong` 字符样式（中文界面“要点”） |
| 说明书正文 | `正文2` |
| 独立公式 | `正文2`，取消首行缩进并居中，内容为原生 Word 公式 |
| 附图及图号 | `附图图号`，图片居中、图号置于图下 |
| 摘要正文 | `正文2` |

不得仅写 `run.bold = True` 冒充“要点”样式。模板样式是事实来源，直接格式只用于公式段落的必要居中和图片尺寸。

## 附图和摘要附图

1. 从 `说明书附图.md` 的 `## 图N ...` 与紧随其后的图片链接读取图号和顺序；
2. 当前流程的 Markdown 图片链接必须指向最终 PNG；历史文件若仍链接 SVG，可兼容读取同名 PNG，但不得据此重新生成 SVG；
3. 每幅说明书附图独占一页，图号放在图下，不在图面重复写图号；
4. 摘要附图编号从 `说明书摘要.md` 的“摘要附图：图N。”读取；
5. 图片使用内嵌方式，不使用浮动环绕；不得拉伸、裁剪或跨页拆分。

## 执行命令

```powershell
python skills/cn-patent-application-creator/scripts/assemble_application_docx.py `
  --case-dir "中国发明专利申请-YYYY-MM-DD-名称"
```

常用覆盖参数：

```powershell
python skills/cn-patent-application-creator/scripts/assemble_application_docx.py `
  --case-dir "<案件目录>" `
  --template "<仅在替换项目模板时传入>" `
  --source-dir "<案件目录>/02-申请文件" `
  --output "<案件目录>/发明名称-专利申请文件.docx" `
  --work-dir "<案件目录>/03-审查工作区/docx组装-YYYYMMDD-HHMMSS"
```

默认不导出 PDF/PNG，也不执行视觉确认。只有用户明确要求检查 Word 版式、逐页截图或视觉效果时，才增加 `--visual-review`：

```powershell
python skills/cn-patent-application-creator/scripts/assemble_application_docx.py `
  --case-dir "<案件目录>" `
  --visual-review
```

`--no-render` 仅作为旧调用的兼容参数保留；新流程无需使用。

## 运行依赖

- Python 3.10+；
- `python-docx`；
- 项目已有依赖 `lxml`、`Pillow`；
- Poppler 的 `pdftoppm` 和 `pdfinfo`（仅在用户明确要求视觉检查时需要）；
- Linux/macOS 视觉检查需要 LibreOffice；
- Windows 视觉检查可使用 Microsoft Word 桌面版和 `pywin32`。

生成 Word 原生公式本身不再要求 Windows、Microsoft Word 或 `pywin32`。默认交付不依赖 PDF/PNG。仅当用户明确要求视觉检查时，当前平台缺少 Word/LibreOffice、PDF 或逐页 PNG 无法生成才属于该次视觉检查未完成；不得因此否定已经通过的 DOCX 结构校验。

## 机器验收

脚本输出 `docx-assembly-report.json`（`cn-patent-docx-assembly/v2`），至少记录：

- 模板和输出 DOCX 路径及哈希；
- 权利要求书、说明书、摘要、附图索引和每幅实际嵌入图片的路径及 SHA-256；
- 权利要求数、说明书内容项数；
- 使用“要点”样式的说明书小标题数；
- 原生 Word 公式对象数；
- 说明书附图数、内嵌图片总数；
- 分节数、页眉序列；请求视觉检查时另记录所用渲染引擎和 PDF 页数；
- 是否请求视觉检查；
- 用户明确要求视觉检查时生成的 PDF 和逐页 PNG 路径；
- `visual_review_completed` 状态：未请求时为 `null`，请求后初始为 `false`。

默认状态为 `STRUCTURE_VERIFIED`，表示机器结构校验已完成且未请求视觉检查。只有用户明确要求视觉检查时，脚本才生成视觉检查材料并进入 `STRUCTURE_VERIFIED_VISUAL_REVIEW_PENDING`；操作者查看每一页 PNG 后，才能在外部验收记录中把视觉复核标记为完成。

## 硬失败条件

- 模板不是五分节，或页眉顺序不符；
- 模板缺少“要点”/`Strong` 等必需样式；
- 权利要求编号不连续；
- 说明书缺少发明名称或五个法定章节；
- 摘要未指定摘要附图，或指定图号不存在；
- 附图编号不连续、图片缺失或只有不可内嵌格式；
- 任一公式未生成 `m:oMath`，或 OMML 原生公式对象数与登记数不一致；
- 任一说明书小标题未应用“要点”样式；
- 用户明确要求视觉检查时，PDF 页数与逐页 PNG 数量不一致；
- DOCX ZIP 包损坏。
- `word/document.xml` 的 `mc:Ignorable` 引用未声明的命名空间前缀；此缺陷会触发 Microsoft Word 的“发现无法读取的内容/是否恢复”提示。

## 按需视觉复核清单

本节只在用户明确要求视觉检查时执行。逐页以 100% 比例检查：

- 五类页眉和每节重新起算的页码；
- 权利要求编号与行号；
- 五个说明书小标题是否为“要点”粗体；
- 所有公式是否显示为专业格式，特别是上下标、分式和幂；
- 图1至图N及摘要附图是否完整、清晰、居中；
- 是否存在文字裁切、对象重叠、孤立图号、异常空白页或字体替换。

## 新鲜度复验

组装完成后必须运行：

```bash
python skills/cn-patent-application-creator/scripts/verify_docx_assembly.py \
  --report "<案件>/03-审查工作区/docx组装-*/docx-assembly-report.json" \
  --output "<案件>/03-审查工作区/docx组装-*/docx-assembly-verification.json"
```

验证器只证明报告绑定的模板、四文书、嵌入图片和 DOCX 当前仍是同一字节版本；不证明法律实体条件或未执行的视觉检查。附图流程还必须运行 `cn-patent-diagram-generator/scripts/verify_drawing_docx_delivery.py`，交叉核对最终附图验证、DOCX报告中的逐图路径/SHA-256和DOCX新鲜度。若用户明确要求Word视觉检查，记录应符合 `references/docx-visual-review-schema.json`。


### 编号与路径边界（审计修复）

- 步骤段落只能引用模板中实际定义的 `numId/ilvl`。单级模板使用 0 层；不能固定使用未定义的第 2 层。
- 组装后和独立复验均读取最终 DOCX 的 `word/document.xml`、`word/numbering.xml`；缺失定义、损坏 XML 或无真实 `w:lvl` 的新增层级必须失败。`numId=0` 表示取消编号，不是编号实例引用。
- 组装报告内相对 `output`、`inputs.template` 和 `inputs.artifacts[].path` 均以报告所在目录解析，不以调用命令时的工作目录解析。
- 最终交付时重新复算当前组装报告及 DOCX；历史 freshness PASS 不替代当前字节检查。每幅图必须提供 Draw.io 和最终 PNG 路径，两者均须与附图验证报告的当前哈希一致。
- 默认测试也不进行 DOCX 视觉导出。仅用户明确授权后，才设置 `CN_PATENT_RUN_VISUAL_TESTS=1` 运行专门的合成 DOCX 渲染测试；普通机器检查不能被表述为人工视觉验收。

## 阶段 6 组装门禁（自 SKILL.md 下沉）

> 本节中的 `$ROOT` 为 `SKILL.md`「运行根目录」一节定义的运行根目录变量。

当用户要求单一 Word 文件时，读取 `$ROOT/skills/cn-patent-application-creator/references/docx-assembly.md`，运行 `scripts/assemble_application_docx.py`。默认模板是 `$ROOT/模版.docx`。DOCX 是四类技术文书的机械组装形式，不改变“四文书”业务边界。

必须遵守以下门禁：

- 模板是版式和样式的唯一事实来源；必须复用五个分节、页眉页脚、页码、行号、页边距、权利要求自动编号和既有样式，不得另造近似版式；
- “技术领域、背景技术、发明内容、附图说明、具体实施方式”使用模板的 `Heading 1` 段落样式，并对标题文字应用 Word `Strong` 字符样式（中文界面显示为“要点”），不得只设置 `bold=True`；
- 数学表达式必须直接生成 Word 原生 OMML `m:oMath` 对象；使用 `m:f`、`m:sSub`、`m:sSup`、`m:sSubSup` 和 `m:d` 保留下标、上标、分式与括号结构。Linux、macOS 和 Windows 均不得依赖普通字符、公式截图或仅设置数学字体冒充原生公式；
- 说明书附图按 `说明书附图.md` 顺序读取当前流程生成的 PNG；摘要附图从 `说明书摘要.md` 的“摘要附图：图N。”机械确定；
- 脚本必须输出 `cn-patent-docx-assembly/v2` 报告。默认机器校验五分节、页眉序列、标题“要点”样式数量、原生公式对象数量、图片数量和 DOCX ZIP 完整性，并逐一绑定模板、四文书、全部嵌入图片和输出 DOCX 的 SHA-256；只有请求视觉检查时才记录 PDF 页数；
- **视觉检查默认关闭。** 不得仅因生成或修改了 Word 就导出 PDF、渲染 PNG、截图或逐页目视确认。只有用户明确要求检查 Word 版式、逐页截图或视觉效果时，才传入 `--visual-review`；Windows 使用 Word、Linux/macOS 使用 LibreOffice 导出 PDF，再校验 PDF 页数与 PNG 页数一致并由操作者目视复核。未请求视觉检查不构成交付缺陷。
- 未请求视觉检查时，报告写入 `render.requested=false`、`visual_review_completed=null` 和 `status=STRUCTURE_VERIFIED`；请求后写入 `render.requested=true`、`visual_review_completed=false`，待外部人工复核记录完成状态。组装后必须运行 `scripts/verify_docx_assembly.py` 复算当前输入和输出哈希；任一源文书或附图变化都使旧 DOCX 报告失效。
- 附图属于交付范围时，附图最终验证通过后必须重新组装DOCX，并运行 `cn-patent-diagram-generator/scripts/verify_drawing_docx_delivery.py`，证明DOCX报告中的逐图路径和SHA-256等于当前最终PNG；不得只凭图片数量相同沿用旧Word。用户明确要求逐页视觉检查时，视觉记录使用 `references/docx-visual-review-schema.json`。
