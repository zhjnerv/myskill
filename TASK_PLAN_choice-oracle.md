# TASK_PLAN：choice-oracle（选择之神，原 image-score）

## 目标与范围
在 `skills/choice-oracle/` 建一个自研 skill：把图片交给 Cloudflare `clef-flash` 决策模型
（System One API），按评分卡输出结构化的门槛判断、0-10 维度分、加权总分、评级或多图择优结论。

覆盖：单图/多图逐图评分、门槛卡控、多图择优、自定义评分卡、结果 JSON 落盘。
不覆盖：图片描述、OCR、自由问答（用 `image-analysis-fallback` / `legal-ocr`）。

## 关键事实（实测 2026-10-30）
- 网关 `https://emrank.tech`，可用端点只有 `/v1/systemone`（`/systemone` 405，`/v1/clef` 404）。
- 模型名必须带前缀：`cloudflare/clef-flash`。
- 缺浏览器 UA 会被 Cloudflare 挡：`403` + `error code: 1010`。脚本已内置 UA 与重试。
- 图片必须内联（data URL 或 `{content_type, base64}`），最多 4 张，PNG/JPEG/WebP。
- 一次请求只产出一份答案；`score` 题在多图请求里无法拆成逐图分数。
- `output_tokens` 恒为 0，计费只按输入 token。

## 重要约束
- 路径 `skills/choice-oracle/`，自研 skill 平铺在 `skills/` 顶层，记账用目录内三份账本。
- **密钥不进仓库**：实机配置在 `~/.clef/config.json`；仓库内只放 `config.example.json`，
  `skills/**/config.local.json` 已加入 `.gitignore`。
- 分档归一化、加权、门槛制裁由脚本确定性计算，模型只交概率。
- 目录名必须等于 `SKILL.md` 的 `name`。

## 步骤与验证
- [x] `skill-new.ps1` 建骨架并登记 registry（`origin=own`）。
- [x] 实测网关端点与鉴权：`/v1/systemone` 200；无 UA 时 403/1010；换浏览器 UA 成功。
- [x] 实测图片输入：data URL 形式可用，模型正确识别颜色/形状/文字。
- [x] 写 `scripts/score_clef.py`：配置查找、UA 重试、评分卡校验、图片校验、
      逐图判决、择优、dry-run、JSON 输出。验证：`--help`、AST 解析通过。
- [x] 写 `assets/scorecards/generic_quality.json`（2 门槛 + 4 评分）与
      `cover_selection.json`（2 门槛 + 4 评分 + 1 归类 + 1 比较）。
- [x] 写 `references/api.md`（接口实测结论）与 `references/scorecard-format.md`（评分卡写法）。
- [x] 写 `SKILL.md`，接入两份 reference。
- [x] 实机验证逐图评分：vision_test.png → 8.09 分 / 良好 / 门槛通过，退出码 0。
- [x] 实机验证择优：2 张候选图 `--compare` → 正确返回 winner 与逐项概率，退出码 0。
- [x] 实机验证无环境变量时从 `~/.clef/config.json` 读配置，`config_source` 正确。
- [x] 错误路径：缺图 / 不支持格式 / 无 key / 1 张图用 `--compare`，全部干净退出（2/1），无 traceback。
- [x] 修 Windows GBK 控制台中文乱码：脚本内 reconfigure stdout/stderr 为 UTF-8。
- [x] `quick_validate.py` 校验通过（需 `PYTHONUTF8=1`，否则校验器自身按 GBK 读文件报错）。

## 当前进度
skill 已完成并实机验证，未提交。

## 下一步动作
等用户确认是否提交、是否要按实际场景替换/新增评分卡。
---

## 第二阶段：从任意多张图里挑出最吸睛的一张（2026-10-30）

用户需求：不要封面/画质综合分，只要"所有图片里最有诱惑力、最抢眼的那张"。
现状缺口：逐图模式硬限 4 张；评分卡维度是封面可用性，吸引力只占一项。

方案：新增 `--pick` 模式 = 逐图打"吸睛度"分（N 次请求，图片数不限）→ 取前 4 名放一个请求决赛（1 次请求）→ 输出冠军与完整排名。
决赛用 compare 纠正逐图绝对分的漂移；只有 1 张时不跑决赛。

用户补充（同日）：吸睛只是一个场景。通用流程是"用户提问 → 我按问题设计评分卡（分档文字描述，换算 0-10）→ 决策模型打分 → 返回结果"。脚本本就支持任意评分卡，因此改动落在 SKILL.md 工作流。

- [x] 新增评分卡 [eye_catching.json](skills/choice-oracle/assets/scorecards/eye_catching.json)：4 个吸睛维度 + 1 道决赛题。
- [x] [score_clef.py](skills/choice-oracle/scripts/score_clef.py)：取消逐图 4 张上限；新增 `--pick`、`--finalists`、目录输入；修 usage 只计最后一次。
- [x] [SKILL.md](skills/choice-oracle/SKILL.md) 改为通用工作流（按问题现场设计评分卡）；更新 TASKS / CHANGELOG。
- [x] 验证：6 张测试图 `--pick --finalists 3` 实机跑通，`decided_by=final_compare`，退出码 0；`--compare` 传 6 张正确报错提示改用 `--pick`；dry-run 输出合法。

## 当前进度
第二阶段完成，未提交。下一步：用户拿真实图片组试一次，确认排名口径。

---

## 第三阶段：文字候选（多段文字 / 多段话）按用户需求评价（2026-10-30）

需求：候选从图片扩展到文字，流程不变（用户提问 → 我写评分卡 → 决策模型打分 → 排名/择优）。
设计：文字放进 `state`，不传 `images`。输入 `.txt/.md` 文件每个算一个候选；`--split` 按空行把文件切成多段，每段一个候选。
同一次运行不混用图片和文字。文字决赛不受 4 图限制，`--finalists` 上限放宽到 10。

- [x] 实测：不带 `images` 的纯文字请求可用。
- [x] 脚本：候选抽象（图片/文字）、`--split`、文字逐段评分与决赛、结果字段 `item` 标识候选。
- [x] 文档：SKILL.md、references/api.md、CHANGELOG、TASKS。
- [x] 验证：图片 `--pick` 回归通过；文字 5 段 `--pick --split` 冠军概率 0.88；缺评分卡、混用两类报错退出码 2。

## 当前进度
第三阶段完成，未提交。待用户决定：是否提交；是否把 skill 改名（已不止图片）。

---

## 第四阶段：改名为 choice-oracle（选择之神）并提交推送（2026-10-30）

依据：用 skill 自评 6 个候选名（加强中二权重），`选择之神（choice-oracle）` 7.90 分第一。用户确认按结果改名，并 commit + push。

- [x] 决赛低置信回退：决赛 confidence < 0.2 时改用逐项第一名，`decided_by=per_item_score_low_final_confidence`，保留 `final` 供查看。
- [x] 改名：`git mv`/移动目录 → `skills/choice-oracle/`；frontmatter `name`；registry 条目；文档内旧名；计划文件更名为 `TASK_PLAN_choice-oracle.md`。
- [x] 验证：`quick_validate`；文字 `--pick` 实跑一次走通。
- [ ] 只提交本 skill 相关文件（skill 目录、registry.json、.gitignore、计划文件），推送 origin/main。

结果：`quick_validate` 通过；6 名字文字海选走通，决赛 confidence 0.037 → `per_item_score_low_final_confidence`，冠军 choice-oracle。
