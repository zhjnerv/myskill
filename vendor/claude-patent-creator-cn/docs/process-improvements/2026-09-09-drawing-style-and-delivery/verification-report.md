# 用户范例、附图导出与 DOCX 交付闭环验证记录

日期：2026-09-09

## 问题来源

三案实际制图暴露出以下问题：

- SVG 时代的独立标签节点规则与 Draw.io 原生 edge label 冲突；
- 节点尺寸、字号和文本容量缺少联动，出现大框小字或文字溢出；
- 长中文标签未强制显式换行，且纵向相邻方框间空白过大；
- 用户修改范例同时包含视觉意图和 Draw.io 手工编辑副作用，不能整图盲目复制；
- PNG 按整页导出时产生大面积无意义白边；
- 附图变化后，最终 DOCX 可能继续绑定旧图片。

## 当前实现

### 用户范例样式合同

新增：

- `cn-patent-drawing-style-brief/v1`；
- `analyze_drawing_reference.py`；
- `validate_drawing_style_brief.py`。

分析器依次按稳定 ID、部件/步骤标记和可见标签匹配节点，将差异拆分为技术变化、视觉变化和结构异常。范例需绑定修改前母版和原始范例的 SHA-256，经用户确认后只允许复用主链方向、同层分支、汇聚方式、节点尺寸、字号、网格、颜色、形状和连线语法。元素、关系和 source/target 仍以 drawing brief 为准。

### Draw.io 与 PNG

- 正式关系文字使用原生 edge `value`；
- 不生成 SVG；
- `node_text_policy` 检查显式字号、每行最多12个汉字、A4归一化字号、外框不超过文字块高度2倍和文本容量；
- `vertical_spacing_policy` 检查直接上下相连节点扣除原生关系标签和一个箭头头部后的有效空白处于相邻节点较小字体行高的2倍至3倍之间；
- `node_shape_policy` 限制圆柱型节点仅用于明确存储、记录、数据库、数据表、缓存或仓库语义；
- `relation_label_policy` 要求原生关系标签字号不小于相邻节点字号的三分之二，且纵向标签上下各至少保留一个箭头头部高度；
- `sanitize_drawing_reference.py` 从原始母版安全重建用户修改布局，保留基准拓扑并剔除绝对端点、自连接、独立标签和额外关系；
- `png_margin_policy` 要求使用 Draw.io Desktop CLI `--size diagram`，并按像素复算四边白边；
- 白边超过合同上限触发 `DRAWING-EXCESSIVE-MARGIN`。

### 用户修改稿紧凑布局与安全重建

对01、02案共14幅 `-zhj.drawio` 修改稿进行真实回放：11幅图明显压缩了整体包围盒，02案图2的包围盒面积约降至原图的32.8%，图3约降至34.0%；共同规律是保持24号字体，优先缩短节点高度、收紧纵向空白、让主链居中并把同层分支靠近判断节点。

修改稿同时暴露30项硬结构副作用：19条绝对端点、10个从原生edge label拆出的独立文字节点、1条自连接，以及2组重复标签警告。新增 `reusable_style.compactness`、`sanitization_plan` 和 `sanitize_drawing_reference.py`：从原始母版保留技术节点、关系ID、source/target和原生edge value，只应用匹配节点几何及白名单样式，所有边重新交给Draw.io正交路由，参考图中的额外节点、额外边、绝对端点和自连接不传播。

14幅修改稿全部完成安全重建回放；重建结果再次与原始母版对比时 `technical_diff` 全空、结构异常为0，且14/14通过drawio-skill strict lint。安全重建结果只标记为 `STRUCTURE_SAFE_VISUAL_REVIEW_REQUIRED`，仍须官方PNG预览和视觉迭代，不能把结构安全冒充为视觉完成。

### DOCX 交付

新增 `verify_drawing_docx_delivery.py`，交叉核对：

- drawing brief 与最终附图验证；
- DOCX 组装报告和新鲜度报告；
- DOCX 报告中每幅图片的路径和 SHA-256 是否等于当前最终 PNG。

用户明确要求 Word 逐页视觉检查时，使用 `cn-patent-docx-visual-review/v1`；默认仍只做结构和哈希检查。

## 现役流程

```text
冻结技术事实
→ drawing brief v4
→ 可选：原图/用户范例差异分析
→ 用户确认 style brief v1
→ drawio-skill 制图
→ 技术拓扑、节点文字、纵向有效空白、原生标签和配色门禁
→ Draw.io CLI 按 diagram 边界导出 PNG
→ DPI、白边、哈希与最终视觉复核
→ 重新组装 DOCX
→ DOCX 新鲜度与附图—DOCX交付绑定验证
→ 可选：用户明确要求时做 DOCX 逐页视觉复核
```

## 验证结果

- 全量测试：`257 passed, 107 subtests passed`；
- 新增范例分析、白边、节点文字、纵向间距和 DOCX 交付专项测试：通过；
- 包边界检查：`PASS`；
- Python 编译、JSON 解析、UTF-8 无 BOM、`git diff --check`：通过；
- Skill Lint Harness 静态审查：`PASS`；
- Instruction Stability：`NOT_VERIFIED`，原因仍是缺少候选外签名硬约束基线，不是实现测试失败。

## 文件治理

- 客户确认文档和三案一次性脚本已移入本地忽略目录 `.local-case-archive/2026-09-08-case-work/`，不进入公共仓库；
- 通用复盘源文档归档到 `docs/process-improvements/2026-09-01-second-draft-retrospective/00-source-retrospective.md`；
- 公共 `scripts/` 仅保留可复用运行时脚本。
