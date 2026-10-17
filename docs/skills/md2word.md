# md2word 本地账

上游的 [CHANGELOG.md](../../skills/md2word/CHANGELOG.md)、[TASKS.md](../../skills/md2word/TASKS.md)、[DECISIONS.md](../../skills/md2word/DECISIONS.md) 继续只承接上游。2026-10-04 之前写进那些文件的本地记录留在原地，不要再往里加。

## 落地前已有的本地改动

- `1.3.9-skr.1`、`1.3.9-skr.2` 在 skill 自己的 CHANGELOG 里：斯可睿抬头、Windows GBK 控制台输出、页脚高度和模板部件映射。细节以那两节为准。
- 2026-10-01，`9b27127`：`SKILL.md` 的 description 增加精确唤起词 `2word`。这条没有写进 CHANGELOG。

## 以后

新的本地需求和更新只写在本文件。

## 2026-10-10 Word 原生标题样式（可导航、可自动编号）

- 问题：转换产物的 `#`~`####` 是普通段落 + 直接格式，没有 `w:pStyle`。Word 样式框选不出"标题 1/2/3/4"，导航窗格为空，手动加标题不会自动带格式，多级自动编号不可用。
- 范围：`skills/md2word/scripts/md2word.py`（标题分支）、`scripts/formatter.py`（标题基础格式从 run 直接格式改为物化进 HeadingN 样式定义）；新增多级编号部件与配置键 `titles.numbering`；6 预设 + config-template（book-publish 默认开，其余关）；SKILL.md、references/config-reference.md。
- 非目标：不自动插入目录域；不做中文编号（第一章/一、）；不改非标题内容的渲染（正文、表格、引用框、脚注、图片、代码块、letterhead 逐字不变）；不写 skill 内上游账本，不 bump SKILL.md version。
- 设计取舍：编号用阿拉伯多级 `1 / 1.1 / 1.1.1 / 1.1.1.1` 挂在 Heading1..4 样式的 `w:numPr` 上（Word 新建标题即自动编号）；`--template` 模板缺 Heading 样式时新建；伪标题"目录"页保持普通段不进 TOC；`_apply_heading_pagination` 的 pageBreakBefore 保持段落级直接格式。
- 怎样算做完：① 全部预设产物 H1~H4 段落含正确 `w:pStyle`，样式外观与预设 `titles.levelN` 一致且与改动前视觉对照无差异；② book-publish 产物标题渲染 1/1.1/1.1.1，其余预设无 numPr；③ `python -X utf8 -m unittest test_regressions` 全绿 + GBK 轮全绿，新增 pStyle/样式/numPr/letterhead 正文不变断言；④ 用户 Word 手工验收：导航窗格层级正确、手动新增标题自动编号且外观一致。
- 关联计划：[TASK_PLAN_md2word-heading-styles.md](../../TASK_PLAN_md2word-heading-styles.md)
