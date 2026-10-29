# CHANGELOG

## [0.4.0] - 2026-10-30

### 变更
- 改名：`image-score` → `choice-oracle`（选择之神）。名字由本 skill 自评选出（加强中二权重，7.90 分第一）。

### 修复
- 决赛 confidence < 0.2 时不再拿它定冠军，改用逐项第一名，`decided_by=per_item_score_low_final_confidence`；决赛失败的回退值改为 `per_item_score`。

## [0.3.0] - 2026-10-30

### 新增
- 文字候选：`.txt/.md` 文件每个一个候选；`--split` 按空行把一个文件切成多段候选。文字写进 state，不传图片。
- 文字决赛最多 10 个（`--finalists`）；文字候选必须显式传 `--scorecard`。

### 变更
- 逐项模式的 `mode` 字段由 `per_image` 改为 `per_item`，并新增 `candidate_kind`；决赛 `winner` 字段由 `image_id` 改为 `id` + `index`。

## [0.2.0] - 2026-10-30

### 新增
- `--pick` 海选择优：逐图打分排名，前 `--finalists` 名（默认 4）决赛，输出冠军与完整排名；张数不限。
- 图片参数可传目录。
- `assets/scorecards/eye_catching.json`：吸睛度 / 诱惑力评分卡（`--pick` 默认）。

### 变更
- SKILL.md 改为通用流程：按用户问题现场设计评分卡，再交给决策模型打分择优。
- 逐图模式取消 4 张上限（每张本来就是独立请求）。

### 修复
- 多图时 `usage` 只统计了最后一次请求，现在逐次累加。

## [0.1.0] - 2026-10-30

### 新增
- `scripts/score_clef.py`：调用 clef-flash 决策模型，支持逐图评分与多图择优。
- `assets/scorecards/generic_quality.json`：通用画质评分卡（2 门槛 + 4 评分）。
- `assets/scorecards/cover_selection.json`：封面可用性评分卡（含归类与比较题）。
- `references/api.md`：System One API 实测约束与踩坑。
- `references/scorecard-format.md`：评分卡写法。
- `config.example.json`：后端配置模板。