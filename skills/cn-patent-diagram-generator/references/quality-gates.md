# 中国专利附图质量门禁

## 生产者与验证者

- **技术内容生产者**：专利起草工作流，输出 `cn-patent-drawing-brief/v4`。
- **图面生产者**：`drawio-skill`，输出 `.drawio` 和官方 CLI 导出图。
- **结构验证器**：`drawio-skill/scripts/validate.py --strict --json`。
- **专利领域验证器**：`scripts/verify_patent_drawings.py`，复算合同、标记、拓扑、配色、导出和视觉记录。
- **视觉验证者**：人工或具备视觉能力的独立审阅者，查看官方 CLI 导出的最终 PNG，写入 `cn-patent-drawing-visual-review/v2`。

生产者不得给自己签发最终 PASS。任何源文件、`.drawio` 或 PNG 变化后，旧验证记录失效。

## 硬失败

<!-- skill-lint:constraint PATENT-DRAWING-SOURCE-BINDING -->
- 绘图合同缺失、来源文件哈希陈旧或技术锚点不存在；
- 单图未冻结唯一问题、阅读方向、层级、复杂度预算、独立线路通道或正常/异常出口；
- 正文图示声明引用不存在的元素/关系，或图中技术元素/关系没有正文声明覆盖；
- `drawio-skill` 或 Draw.io Desktop CLI 不可用，却用自制渲染器替代正式输出；
- `.drawio` 不是未压缩 `mxfile/mxGraphModel`；
<!-- skill-lint:constraint PATENT-DRAWING-STYLE-REFERENCE -->
- 使用了用户范例，却没有保存修改前母版、原始范例及其SHA-256；
- 样式合同来源哈希陈旧；
- 批量套用范例时改变了drawing brief的元素ID、标签、关系ID、source/target、步骤、判断或循环；
- 把范例中的绝对端点、断连、无来源辅助边或技术文字改动作为样式传播；
<!-- skill-lint:constraint PATENT-DRAWING-TECH-COVERAGE -->
- 合同元素或关系缺失，或图中新增无来源的技术元素/关系；
- 部件标记或步骤号错误、重复或混用；
- 图号或标题写入画布；
<!-- skill-lint:constraint PATENT-DRAWING-STEP-ISOMORPHISM -->
- 方法流程图未绑定当前 `claim-architecture.json`，或该来源哈希陈旧；
- 权利要求步骤集合、顺序与图中步骤不一致；
- 图框文字不是步骤号加权利要求动作原文，而是制图端自行概括；
- 判断节点、真假分支或循环返回步骤与权利要求架构合同不一致；
<!-- skill-lint:constraint PATENT-DRAWING-DIRECT-CONNECTOR -->
- 合同有关系文字但 edge 未使用原生 `value`，文字内容与合同不一致，或另建独立文本框模拟线条文字；
- 应直连的关系被拆为多条边，或出现绝对端点、未登记自连接、自交、折返、重叠、无意义环绕；
- 线路穿过无关节点、标签或容器标题；
<!-- skill-lint:constraint PATENT-DRAWING-PNG-MARGIN -->
- PNG未按 `diagram` 图形边界导出，或任一方向白边超过 `png_margin_policy.maximum_margin_pixels`；
- 通过后期裁剪PNG掩盖母版或导出模式问题；
合法近似正例：`assets/stability/near-miss-legal-PATENT-DRAWING-PNG-MARGIN.json`
<!-- skill-lint:constraint PATENT-DRAWING-OFFICIAL-EXPORT -->
- Draw.io 官方 CLI 导出报告缺失，或报告源 SHA 与当前 `.drawio` 不一致；
- 最终 PNG 哈希与导出报告不一致；
<!-- skill-lint:constraint PATENT-DRAWING-VISUAL-BINDING -->
- 视觉复核缺失，或绑定旧绘图合同、旧导出报告、旧 PNG；
- 未记录 100% 比例、缩小比例和逐项具体观察；
<!-- skill-lint:constraint PATENT-DRAWING-NODE-SHAPE -->
- 普通模块、动作、步骤、判断、事实、状态或一般结果使用圆柱型节点；
- 圆柱型节点未在drawing brief中登记为`data_store`，或节点文字未明确表达存储、记录、数据库、数据表、缓存或仓库语义；
<!-- skill-lint:constraint PATENT-DRAWING-EDGE-LABEL-READABILITY -->
- 原生关系标签未显式设置字号，或字号小于相邻节点文字字号的三分之二；
- 纵向相邻节点间的原生关系标签未居中，或标签文字块上方/下方任一净空小于一个箭头头部高度；
合法近似正例：`assets/stability/near-miss-legal-PATENT-DRAWING-EDGE-LABEL-READABILITY.json`
<!-- skill-lint:constraint PATENT-DRAWING-NODE-TEXT-FIT -->
- 技术节点未显式设置字号或未启用自动换行；
- 任一可见行包含超过12个汉字，却没有使用 `<br>` 或换行符显式换行；
- A4归一化字号小于合同下限，节点宽度与字号比例超过合同上限，或外框高度超过实际文字块高度的2倍；
- 预计换行数超过上限，或按字体、行高和内边距估算后文字无法容纳在节点中；
- 通过缩小字体把长文字硬塞进固定节点，或通过扩大整张画布绕过字号门禁；
合法近似正例：`assets/stability/near-miss-legal-PATENT-DRAWING-NODE-TEXT-FIT.json`
<!-- skill-lint:constraint PATENT-DRAWING-VERTICAL-SPACING -->
- 直接上下相连节点的垂直净距在扣除原生关系标签文字块高度和一个箭头头部高度后，有效空白小于相邻节点较小字体行高的2倍，或大于该字体行高的3倍；
- 把关系标签或箭头头部计入节点外框/节点文字高度，或通过缩小字号、放大画布、增设无语义空节点规避2—3倍字体行高门禁；
合法近似正例：`assets/stability/near-miss-legal-PATENT-DRAWING-VERTICAL-SPACING.json`
<!-- skill-lint:constraint PATENT-DRAWING-COLOR -->
- 使用渐变、阴影、暗色背景、过量颜色，或颜色成为唯一语义载体；
- 同一申请的附图风格、字体、编号方式或配色无理由漂移。

## 机器检查与视觉检查边界

机器可检查：XML结构、ID、来源哈希、标记、原生线条文字、独立标签文本框、直接边、显式路由、自交/重叠、颜色数量、圆柱节点语义、原生关系标签字号与上下净空、A4归一化字号、每行汉字数、外框/文字块高度比例、估算换行与文本容量、扣除关系标签和箭头头部后的2—3倍字体行高纵向空白、方法步骤/判断/循环同构、Draw.io CLI导出证据、PNG尺寸/DPI和记录新鲜度。

视觉必须检查：实际字体替换、文字裁切、原生线条文字是否位于正确分支且不遮挡线条或节点、自动路由的隐藏交叉、无意义折返/回钩、箭头方向、字体与节点一致性、整体留白、视觉层级、灰度可读性和是否“像正式专利附图”。

不得用 XML lint 代替最终 PNG 的视觉复核，也不得用视觉审阅者自报 PASS 代替哈希和结构检查。

## 回炉规则

- 技术内容或标记错误：退回专利起草端，更新说明书/台账/绘图合同。
- 布局、路由、字体或配色错误：退回 `drawio-skill` 修改 `.drawio`。
- 导出错误：重新运行 Draw.io Desktop CLI，不得编辑 PNG。
- 视觉记录陈旧：重新查看最终 PNG 并生成新记录。
- 最终PNG变化：重新组装DOCX并复验DOCX图片哈希；不得沿用旧Word。


### 状态审计补强

- 安全重建的箭头端与命名形状继承原始母版，范例不能反转关系边方向。冻结节点文字按合法换行/空白规范化后完整比较，不采用子串匹配。
- v4 方法图 `decision_bindings` 的 `true_branch` / `false_branch` 各自显式包含 `relation_id`、`target_step_id`、`label`；与架构合同中的目标步骤及关系实际端点逐一核对。旧 brief 缺少该绑定时须补齐、重新冻结和验证，不回退为无序目标集合比较。
- 最终交付除绑定 brief 外，还须检查图号集合、当前 Draw.io/PNG 路径与 SHA-256；旧附图报告或旧 DOCX freshness 不可重放为当前通过证据。
