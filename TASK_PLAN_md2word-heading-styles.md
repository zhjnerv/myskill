# TASK_PLAN：md2word 输出 Word 原生标题样式（可导航、可自动编号）

## 目标与范围
让 md2word 转换出的 docx 中，Markdown `#`~`####` 标题使用 Word 原生标题样式（Heading 1~4），而不是当前"普通段落 + 直接格式"的做法。达成三点：

1. **可选中**：Word 样式框显示"标题 1/2/3/4"，导航窗格/大纲完整列出标题层级。
2. **格式自持**：预设 `titles.levelN` 的外观物化进标题样式定义（styles.xml），用户之后在 Word 里手动加标题、套样式即自动同格式，无需重设字体字号。
3. **自动编号（可选、配置开关）**：标题样式挂多级列表（`1 / 1.1 / 1.1.1 / 1.1.1.1`），开关打开时新增标题自动编号。

需求来源：用户 2026-10-10 提出；本地账见 [docs/skills/md2word.md](docs/skills/md2word.md)。

## 现状证据（已核实）
- 标题生成为普通段落：[skills/md2word/scripts/md2word.py L1275-L1302](skills/md2word/scripts/md2word.py#L1275) `doc.add_paragraph()` 后直接调 `parse_text_formatting(p, title, title_level=N)` + `set_paragraph_format(p, title_level=N)`。
- 字体/字号/加粗/颜色/对齐/缩进全部是 run/段落级直接格式：[skills/md2word/scripts/formatter.py](skills/md2word/scripts/formatter.py) `set_run_format_with_styles`（L361 起 title_level 分支）与 `set_paragraph_format`（L453 起）。
- 全文无 `w:pStyle` 设置 → Word 视角不存在标题。文档基底为 python-docx 默认模板（md2word.py L961 `Document()`），内置 Heading 1-9 样式可用；`--template` 时取决于模板。
- 伪标题"目录"页为居中加粗普通段（md2word.py L825 注释），故意不用 Heading，避免被 TOC 收入——保持该行为。
- 上游检查：`skill-status.ps1 -Remote` 因 gh 未登录取不到 fork/上游 tree（本机限制）；已直接拉取上游 CHANGELOG 确认最新仍为 1.3.8（2026-09-23），无标题样式相关改动。

## 重要约束
- 改法按仓库 skill 记账规则执行：本地需求/决策只写 [docs/skills/md2word.md](docs/skills/md2word.md)，**不写** skill 内的 CHANGELOG/TASKS/DECISIONS（那是上游账）；不 bump SKILL.md 的 version 字段。
- 只改 `skills/md2word/` 目录；验证后同步到安装目录 `C:\Users\ZhouH\.codex\skills\md2word\`（清 `__pycache__`）。
- 非标题内容（正文、表格、引用框、脚注/尾注、图片、代码块、抬头 letterhead）的渲染结果必须逐字不变。
- 默认不提交；用户明确要求时才 commit（skill 改动与账本同一提交）。

## 设计要点
1. H1~H4 段落设置 `p.style = doc.styles['Heading 1'..'Heading 4']`（内置 styleId Heading1..4）。
2. 新增"标题样式物化"步骤：按当前预设 `titles.levelN`（font/font_alt/size/bold/color/align/indent/space_before/space_after/line_spacing）改写 HeadingN 样式的 rPr/pPr。标题 run 不再写基础直接格式（字号/字体/加粗/颜色交给样式）；标题文本内的行内 Markdown 格式（`**粗体**`、`` `code` `` 等）仍按现有逻辑保留为直接格式。
3. `_apply_heading_pagination`（本章小结/动手练习 pageBreakBefore）保持段落级直接 pPr，不改样式。
4. 自动编号：`--template` 与否都可用；开启时生成多级 numbering（decimal，`%1` / `%1.%2` / `%1.%2.%3` / 四级），通过样式 pPr 的 `w:numPr` 绑定到 Heading1..4（Word 行为：新建标题自动编号）。
5. 配置键（新增，`titles` 下）：`numbering: bool`，语义"是否给标题样式挂多级编号"。预设默认：**book-publish=true**，其余 5 个预设与 config-template=false（保证法律/学术等现有版式零变化）。
6. `--template` 兼容：模板已有 HeadingN 样式则物化进模板样式；缺失则新建。模板缺 numbering 部件时正常生成。

## 假设（如与实际意图不符请指出）
- A1：自动编号默认只开 book-publish；法律文书等不编号。
- A2：编号格式用阿拉伯多级 `1 / 1.1 / 1.1.1`，不做"第一章/一、/（一）"中文编号。
- A3：编号开启时，book-publish 的 level2/level3 首行缩进 24 由编号缩进接管，细调使视觉与现状一致。
- A4：不在转换时自动插入目录域（TOC 字段）——标题样式就位后用户在 Word 里手动插入目录即可，本任务只做前置条件。

## 步骤与验证
- [ ] S1 基线留档：选真实样例（book：书稿 ch12；legal：王丽英事实梳理稿），按 book-publish 与 legal 各转一份 docx 并导出 PDF，存 `docs/skills/baseline-heading/` 作视觉对照基线。完成标准：4 份文件在档。
- [ ] S2 标题样式化重构：md2word.py 标题分支 + formatter.py 样式物化；跑 `python -X utf8 -m unittest test_regressions` 看现有断言哪些因 pStyle/直接格式变化而失败，逐一判定是"预期变化"还是"回归"。完成标准：全部预设 H1~H4 段落 XML 含正确 `w:pStyle`，HeadingN 样式 rPr/pPr 与预设值一致；原有失败断言全部有判定记录。
- [ ] S3 `--template` 路径兼容：用最小模板验证有/无 Heading 样式两种情况。完成标准：两种情况均得到正确样式与外观。
- [ ] S4 自动编号：numbering 生成 + 配置键 + 预设默认值 + 文档。完成标准：book-publish 产物 Heading1..4 带 numPr 且渲染为 1/1.1/1.1.1；其余预设产物无 numPr。
- [ ] S5 回归测试补充：test_regressions.py 新增用例（pStyle 断言、样式 rPr/pPr 断言、numPr 开/关断言、legal+letterhead 正文与现状逐字一致断言、伪标题"目录"仍是普通段断言）。完成标准：`python -X utf8 -m unittest test_regressions` 全绿 + `PYTHONIOENCODING=gbk:strict` 一轮全绿；`py_compile` 全部脚本；7 份 YAML 解析通过；`git diff --check` 干净。
- [ ] S6 视觉对照：同 S1 样例重新转换导 PDF，与基线逐页对照标题几何（字体/字号/颜色/对齐/间距/编号位置）。完成标准：除 book 预设多出编号外，无肉眼可见差异。
- [ ] S7 文档：SKILL.md（用法说明）、references/config-reference.md（numbering 键）、[docs/skills/md2word.md](docs/skills/md2word.md) 补完成记录（日期/改动/证据/遗留）。
- [ ] S8 同步安装目录：复制到 `C:\Users\ZhouH\.codex\skills\md2word\`，删 `__pycache__`。完成标准：两目录文件级 diff 仅剩 `__pycache__` 差异为 0。
- [ ] S9 用户手工验收（留档说明）：Word 打开 book 产物——导航窗格层级正确；手动新建一段套"标题 2"→ 自动编号 + 外观一致；legal 产物目录/版式不变。完成标准：用户确认或指出偏差。

## 当前进度
计划已写好，需求已落账本（S0 完成）。S1 未开始。上游核对完成（gh 未登录，改用直接拉取上游 CHANGELOG，确认无冲突）。

## 下一步动作
S1：选样例并生成基线 docx/PDF。
