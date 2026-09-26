# 调用 drawio-skill 的执行约定

开始绘图、修改或复核前，先读取 `drawing-terminology.md`，统一节点、节点文字、关系边、原生关系标签、端口、路由点及间距的称呼。

`cn-patent-diagram-generator` 是专利领域适配层，不维护第二套通用 Draw.io 画法。实际制图必须使用当前环境中的 `drawio-skill`。

## 依赖发现

1. 从可用 Skill 列表定位 `drawio-skill` 并读取其 `SKILL.md`。
2. 按需读取其根目录下的（路径相对 `drawio-skill`，不是本 Skill）：
   - `drawio-skill/references/diagram-types.md`
   - `drawio-skill/references/xml-authoring.md`
   - `drawio-skill/references/autolayout.md`
   - `drawio-skill/references/troubleshooting.md`
3. 检测 Draw.io Desktop CLI：`drawio --version`，再尝试 `draw.io --version`。
4. `drawio-skill` 或官方 CLI 不可用时，停在已校验的 `drawing-brief.json`，报告缺失依赖；不得退回自制 Pillow、canvas 或浏览器截图渲染并声称正式附图完成。

## 用户范例学习

- 范例原文件只读保存并记录SHA-256；不得覆盖或清洗用户原文件。
- 先执行 `analyze_drawing_reference.py`，按稳定ID、标记、可见标签识别同一技术节点。
- 把新增/删除节点、关系端点变化与布局、字号、节点尺寸、网格、配色变化分开报告。
- 范例中的绝对端点、断连、额外辅助边或重复标签属于结构异常，必须向用户说明并在批准记录中确认；批量制图仍使用drawing brief的真实source/target。
- 只有批准的style brief可以交给drawio-skill；未批准或来源哈希陈旧时停止。

## 用户修改稿安全重建

1. 用户修改稿只用于提取布局意图，不得直接覆盖正式 `.drawio`。
2. 先运行 `analyze_drawing_reference.py`，读取 `reusable_style.compactness`：保持字号，优先压缩节点高度、纵向空白和整体包围盒；主链居中、同层分支横排、结果回到主轴。
3. 对同一幅图运行 `sanitize_drawing_reference.py`。脚本从原始母版重建：复制匹配节点几何和白名单样式；保留原始元素/关系 ID、source/target、edge value；移除参考图独立标签、重复辅助节点、额外边、自连接和绝对端点。
4. 安全重建后再次运行差异分析。只有 `technical_diff` 全空、`structural_anomalies` 为空时，才进入 Draw.io 视觉迭代。
5. 对其他附图批量套用时，不复制参考图 XML；仅应用紧凑度、节点尺寸分布、主链/分支/汇聚方式和视觉样式。

## Authoring mode

- 标准流程、状态、时序等图型：优先使用 `drawio-skill` 推荐的原生生成方式。
- 需要专利部件标记、固定节点 ID、精确路由或复杂容器：读取 `drawio-skill/references/xml-authoring.md`，手写或程序生成原生 XML。
- 超过约15个节点、层级或连线较多：优先使用 `drawio-skill/scripts/autolayout.py` 形成候选布局，再按专利要求人工调整；不要直接用大量绝对坐标硬凑。
- 申请文件通常不直接使用 Mermaid 转换结果，因为节点 ID、附图标记、线型和原生线条文字需要严格控制；只有简单图且转换后仍满足交接合同时才可使用。

## 方法流程图文字来源

使用 `cn-patent-drawing-brief/v4` 时，方法流程图必须先读取其绑定的 `claim-architecture.json`：

- 每个步骤框使用 `step_bindings[].claim_action`，图框文字为步骤号加该动作原文；
- 判断框使用 `decision_bindings[].condition`；
- 循环边使用 `loop_bindings` 规定的起点、返回步骤和条件；
- 不得为缩短文字自行概括、合并两个步骤或改变循环归属；
- 文字过长时扩大节点、增加画布高度或拆图，不得改写技术动作。

## ID 与可追溯性

- 每个技术元素的 `mxCell id` 使用绘图合同中的 `elements[].id`。
- 每条技术关系的 edge ID 使用 `relations[].id`。
- 关系文字直接写入对应 edge 的原生 `value`，edge ID 仍使用 `relations[].id`。
- 容器和纯装饰节点使用 `container-*`、`frame-*` 或 `decor-*` 前缀。
- 不得新增合同中不存在的技术元素或关系；需要补充时先回到专利起草端修改合同和来源文件。

## 关系标签

正确结构：

```text
source ───── 是 ─────→ target
         （原生 edge label）
```

禁止：

```text
source ─────────→ target
              是（另建文本框模拟标签）
```

关系说明必须写入对应 edge 的原生 `value`，由 Draw.io 管理文字与线条的相对位置；不得创建 `label-<relation-id>` 等独立文本框替代原生线条文字。

原生关系标签必须显式设置字号，且不得小于相邻两个节点文字字号中较小值的三分之二。对上下相邻节点之间的原生关系标签，标签居中后，其文字块上方和下方各至少保留一个箭头头部高度；需要更多空间时调整节点位置，不得缩小标签字号规避。

## 节点形状语义

- 圆柱型节点只用于明确的存储或记录语义，例如数据存储、数据库、数据表、缓存、仓库和持久化记录。
- 普通模块、执行动作、流程步骤、判断条件、临时事实、状态和一般结果不得仅因视觉区分而使用圆柱形。
- 同一技术对象是否使用圆柱形由 drawing brief 的 `kind=data_store` 与节点文字共同约束；仅有其中一项不能证明圆柱形必要。

## 节点与文字适配

1. 先按合同中的 `node_text_policy` 固定字号，禁止先画固定方框再不断缩小字体。
2. 节点任一可见行最多包含12个汉字；超过时必须在 `value` 中使用 `<br>` 或换行符显式换行，不能只依赖 `whiteSpace=wrap` 自动折行。数字、拉丁字母和标点不计入12字上限。
3. 根据显式换行、显示宽度、字号和行高估算实际文字块高度；外框高度不得超过文字块高度的2倍，同时仍须容纳文字和上下内边距。
4. 每个技术节点必须显式设置 `fontSize`、`whiteSpace=wrap` 和足够内边距；同层节点可以对齐尺寸，但不得因此制造大框小字。
5. 超过四行或扩大节点后仍导致布局拥挤时拆图，不得继续缩小字体或改写技术动作。
6. 预览时同时检查原尺寸和缩小显示；发现溢出、大框小字或未显式换行时修改 `.drawio`，不得仅调整导出 PNG。

## 纵向节点间距

- 对 `preferred_direction=vertical` 且要求直连的上下相邻技术节点，计算两个外框边界之间的垂直净距。
- 从净距中扣除原生关系标签文字块高度和一个箭头头部高度；关系标签与箭头头部均不计入节点外框或节点文字高度。
- 以相邻两个节点中较小的字号计算字体行高：`字体行高 = min(上节点字号, 下节点字号) × line_height_factor`。
- 有效空白高度必须处于字体行高的2倍至3倍之间（含边界）：`2 × 字体行高 <= 有效空白高度 <= 3 × 字体行高`。
- 间距不足时优先下移下节点；间距过大时优先上移下节点。不得通过缩小字号、放大画布、增设无语义空节点或把关系标签移出关系边规避门禁。
- 该门禁只约束直接上下相连节点；跨层回路、横向分支、斜向汇合和不相连节点应保留 `preferred_direction=auto`，避免误判。

## 官方导出

预览图由 `drawio-skill` 官方 CLI 按实际图形边界导出，不嵌入 XML；不得使用 `--size page` 产生无意义大白边：

```bash
drawio -x -f png --size diagram --width 2000 --border 10 \
  -o preview/图1.png 02-申请文件/说明书附图/图1.drawio
```

最终图使用本 Skill 的薄包装器，它仍调用同一 Draw.io Desktop CLI，并写入 DPI 与哈希报告：

```bash
python scripts/export_patent_drawio.py \
  --input 02-申请文件/说明书附图/图1.drawio \
  --png 02-申请文件/说明书附图/图1.png \
  --dpi 300 \
  --report 03-审查工作区/附图/图1-export.json
```

`.drawio` 是唯一母版；最终 PNG 必须由当前母版的官方 CLI 输出，不能由另一套 Pillow/canvas/自绘代码产生。

## 迭代

1. 运行 `drawio-skill/scripts/validate.py --strict --json`。
2. 用官方 CLI 输出宽度不超过2000像素的预览 PNG。
3. 查看预览，检查文字、线路、箭头和配色。
4. 修改 `.drawio`，重复验证与预览；不得只修 PNG。
5. 视觉通过后输出最终 PNG；必须使用 `--size diagram`，并复算四边非白内容边界。
6. 创建 `cn-patent-drawing-visual-review/v2` 的 `visual-review.json`，绑定当前 drawing brief、export report 和最终 PNG 的 SHA-256，并记录 100% 与缩小比例下的逐项观察。
7. 运行 `verify_patent_drawings.py`，通过后才交回专利起草工作流。
8. 如交付DOCX，重新组装并运行 `verify_drawing_docx_delivery.py`；任一最终PNG变化都使旧DOCX证据失效。
