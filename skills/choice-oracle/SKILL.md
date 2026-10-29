---
name: choice-oracle
description: 用户手头有一组同类图片或多段文字（标题、开头、文案、回复等），并提出一个判断问题（哪张最吸睛、哪段最能打动人、是否合格等）时使用：按问题现场设计评分卡，交给决策模型（Cloudflare clef-flash / System One API）逐项打 0-10 分并择优，返回排名与结论。不要用于图片描述、OCR、改写文字或自由问答。
---

# 选择之神：按问题给一组图片或文字打分择优

决策模型 `clef-flash` 不生成文字：输入 `state`（背景）+ `questions`（类型化问题），
只返回每个选项的概率。**把用户的问题翻译成评分卡是你的活**，打分交给模型，
分档、加权、排名、决赛由脚本确定性计算。

接口细节和实测坑在 [references/api.md](references/api.md)，评分卡写法在
[references/scorecard-format.md](references/scorecard-format.md)。

## 工作流

1. **理解问题**：用户想按什么标准挑图？要唯一冠军、完整排名，还是合格/不合格？
   问题含糊到会改变评分方向时才追问，否则直接按合理理解设计。
2. **设计评分卡**：把问题拆成 2-5 个 `score` 维度，每个维度写 5 档可观察的文字描述
   （最低档在前），按问题侧重给权重；硬性条件写成 `noul` 门槛；要择优就加一道
   `mode: "compare"` 的决赛题，题干直接复述用户的问题。
   写到临时目录（不要写进本仓库），格式见 scorecard-format。
   **每次都按这组图和这个问题重新写，不要直接套示例。** 区分度的关键：
   - 维度要贴合题材（人像写真看眼神、姿势、表情、构图；产品图看主体、光线、卖点；
     文章开头看悬念、具体程度、与读者的相关性）。
   - 文字候选没有默认评分卡，必须自己写；`purpose` 里交代文字的用途和读者。
   - 同组同风格的图片，模型会给出相近分数；最高档要写得苛刻（"整组里的高光时刻"），
     并在 `purpose` 里说明"同一组、按严格标准判断"，避免所有图都落进同一档。
   现成示例只作写法参考：
   - `assets/scorecards/eye_catching.json`：最吸睛 / 最有诱惑力（`--pick` 默认用它）
   - `assets/scorecards/cover_selection.json`：封面可用性
   - `assets/scorecards/generic_quality.json`：通用画质
3. **跑模型**（见下方用法），结果落盘到 JSON。
   **检查区分度**：若全部图片加权分极差 < 1.0，说明评分卡没拉开，
   收紧档位描述后重跑一次，再汇报；不要把"改评分卡"留给用户。
4. **汇报**：先给结论（冠军/是否合格），再列排名和关键维度分，
   说明用的评分维度与权重，让用户能判断口径对不对。

## 用法

候选参数可以是图片（PNG/JPEG/WebP）、文字文件（.txt/.md）或目录（不递归）。同一次运行不混用图片和文字。

文字候选的组织方式：
- 每个文件一个候选：多个 `.txt/.md` 文件，或放进一个目录。
- 一个文件多段：用户直接贴来的几段话，写进一个临时 `.md`，段与段空一行，加 `--split`，
  每段成为一个候选（结果里标为 `路径#段号`，并带 `text` 原文）。

海选择优（张数不限）：逐图打分排名 → 前 `--finalists` 名（默认 4）放一个请求决赛 → 冠军：

```powershell
python "<skill>/scripts/score_clef.py" <图片目录> --pick `
  --scorecard <临时评分卡.json> --context "<用户的问题或背景>" --output result.json
```

文字示例（一个文件里 5 段候选，全部进决赛）：

```powershell
python "<skill>/scripts/score_clef.py" candidates.md --split --pick --finalists 5 `
  --scorecard <临时评分卡.json> --output result.json
```

只要逐项分数（不决赛）：去掉 `--pick`。2-4 张只想直接比一次：用 `--compare`。
先看请求、不花钱：加 `--dry-run`。

请求数：每个候选 1 次，`--pick` 再加 1 次决赛。计费只按输入 token，
图很多时先告诉用户张数再跑。

## 读结果

- `pick.winner`：冠军；`pick.decided_by` 为 `final_compare`（决赛选出）、
  `per_item_score_low_final_confidence`（决赛 confidence < 0.2，等于随机，改用逐项第一）、
  `per_item_score`（决赛失败，退回逐项第一，此时有 `final_error`）或 `only_candidate`。
- `pick.ranking`：按逐项加权分的完整排名；`pick.final.comparison` 是决赛逐项概率。
- `verdicts[].dimensions`：每个维度的 `score_0_10`、`confidence`；`verdicts[].gates` 是门槛结果。
- 决赛冠军与逐项第一不一致时如实告诉用户，两者都是模型判断。

汇报直接用这些字段，不要自己另算；`confidence` < 0.4 要主动提示。

## 前置条件

脚本默认从 `~/.clef/config.json` 读后端配置：

```json
{ "base_url": "https://emrank.tech", "api_key": "...", "model": "cloudflare/clef-flash" }
```

模型名必须保留前缀。也可用环境变量 `CLEF_BASE_URL` / `CLEF_API_KEY` / `CLEF_MODEL` 覆盖。
密钥不要写进本仓库。

## 关键约束

- 一次请求只产出一份答案：逐项分数必须一项一请求；多图请求只能做择优题。
- 单次请求最多 4 张图，所以图片决赛最多 4 个；文字放在 state 里，决赛最多 10 个（`--finalists`）。图片单张 ≤4 MiB / 16 百万像素，只收 PNG/JPEG/WebP。
- 网关在 Cloudflare 后面，缺浏览器 UA 会 `403 + error code 1010`；脚本已处理。
- 分数不替用户做最终决定：口径都写在评分卡里，用户不认同就改评分卡重跑。
