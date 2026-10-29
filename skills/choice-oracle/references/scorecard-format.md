# 评分卡格式

评分卡就是一个 JSON 文件，直接对应决策模型的 `questions`。脚本负责把占位符换成真实值、
把概率换算成分数。默认评分卡在 `assets/scorecards/`。

## 骨架

```json
{
  "name": "评分卡名称",
  "version": "1.0",
  "purpose": "写进 state 的一句话：这张图要被判决成什么",
  "gate_policy": "report",
  "cap_score": 4.0,
  "questions": {
    "<问题 id>": { "type": "noul | choice | score", "...": "..." }
  },
  "weights": { "<score 题 id>": 1.5 },
  "grade_bands": [ { "min": 8.5, "grade": "优秀" } ]
}
```

## 三类问题

**noul（门槛）** —— 用来卡硬性合格线，比如"有没有水印""是不是真实图片"。

```json
"has_watermark": {
  "type": "noul",
  "instructions": "画面主要信息是否没有被大面积水印遮挡？",
  "criteria": { "true": "干净", "false": "被压住" },
  "pass_if_yes_at_least": 0.6
}
```

`pass_if_yes_at_least` 是判定阈值，默认 0.5。门槛题不参与加权。

**score（评级）** —— 返回概率加权的等级，脚本归一到 0-10。

```json
"sharpness": {
  "type": "score",
  "instructions": "评估清晰度",
  "criteria": ["最差", "较差", "一般", "较好", "最好"]
}
```

`criteria` 必须是 2-10 项的**有序数组，最低档在前**。写具体可观察的描述，
不要写"1 分/2 分"——模型是按语义对号入座的。

**choice（归类/择优）** —— 返回选中项与逐项概率。

```json
"style": {
  "type": "choice",
  "instructions": "判断视觉风格",
  "criteria": { "photo": "真实照片", "illustration": "插画" }
}
```

## 权重与评级

- `weights` 只对 `score` 题生效，缺省权重 1.0。
- 总分 = 各 score 维度归一化分数的加权平均。
- `grade_bands` 从高到低写，脚本取第一个满足 `min` 的档。

## 门槛制裁

`gate_policy`：

- `report`（默认）：只报告门槛是否通过，分数不动。
- `cap`：任一门槛不过，总分压到 `cap_score`（默认 4.0），并标记 `capped_by_gate`。

## 比较题（择优）

多图择优用 `mode: "compare"` 的 choice 题，`<option>` 是选项模板，`{id}` 会被替换成
`image1`、`image2`……：

```json
"pick_best": {
  "type": "choice",
  "mode": "compare",
  "instructions": "选出最适合做封面的一张",
  "criteria": { "<option>": "候选图 {id}" }
}
```

比较题只在 `--compare` 模式下发送；普通逐图模式会跳过它。

## 写评分卡的要点

- `instructions` 决定模型在判什么，要用问句，别用祈使句。
- 分档描述写**可观察的视觉特征**，不写主观形容词堆砌，否则档与档之间会糊。
- 一个维度只问一件事。要拆"清晰度"和"噪点"，不要合成一个"画质"。
- 门槛题和评分题分开：门槛是布尔红线，评分是可以拉开的连续量。
- 模型只给概率，**不要让它输出文字理由**——它不生成文本。