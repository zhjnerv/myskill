# choice-oracle 任务清单

## 未完成
- 用真实图片组（非纯色测试图）验证 `--pick` 排名是否符合人工直觉。
- 等真实场景评分卡：现有 generic_quality / cover_selection 是示例口径，需要按实际用途替换维度与权重。

## 已完成
- 改名 image-score → choice-oracle（选择之神）；决赛低置信（<0.2）改用逐项第一名。
- 文字候选 + `--split`；5 段开头实测排名合理，决赛冠军概率 0.88；图片回归通过。
- `--pick` 海选择优 + 目录输入 + 吸睛度评分卡；6 张测试图实机跑通（逐图 6 次 + 决赛 1 次）。
- 建 skill 骨架并登记 registry（origin=own）。
- 实测 `clef-flash` 网关：`/v1/systemone` 可用、图片 data URL 可用、UA 必需。
- `scripts/score_clef.py`：逐图评分、多图择优、dry-run、JSON 输出、错误码。
- `assets/scorecards/`：通用画质、封面可用性两张评分卡。
- `references/api.md`、`references/scorecard-format.md`。
- 实机验证：单图 8.09 分；双图择优命中 image1；错误路径无 traceback。
- skill-creator `quick_validate.py` 通过。