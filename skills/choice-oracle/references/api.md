# Clef / System One 接口实测结论

来源：<https://developers.cloudflare.com/workers-ai/models/clef-flash/>，
并用 `https://emrank.tech` 网关实跑校验（2026-10-30）。

## 端点

```
POST {base_url}/v1/systemone
Authorization: Bearer {key}
Content-Type: application/json
User-Agent: <浏览器 UA>    # 必需
```

- 用 `https://emrank.tech` 时，`/v1/systemone` 可用；`/systemone` 返回 405，`/v1/clef` 返回 404。
- **不带浏览器 UA 会被 Cloudflare 挡住**，返回 `403` + 正文 `error code: 1010`。
  脚本已带 Chrome UA，并在 403/1010 时换 UA 重试。
- 模型名必须保留前缀：`cloudflare/clef-flash`（走网关时）；直连 Cloudflare 原生 API 才是 `@cf/cloudflare/clef-flash`。

## 请求

```json
{
  "model": "cloudflare/clef-flash",
  "state": "任意字符串，或结构化 JSON",
  "images": ["data:image/png;base64,..."],
  "questions": {
    "q1": { "type": "noul",   "instructions": "...", "criteria": {"true": "...", "false": "..."} },
    "q2": { "type": "choice", "instructions": "...", "criteria": {"a": "...", "b": "..."} },
    "q3": { "type": "score",  "instructions": "...", "criteria": ["最低档", "...", "最高档"] }
  }
}
```

约束：

- `state` 必填；`questions` 1-64 个，id 只能用字母数字 `_ . -`，≤100 字符。
- `score.criteria` 是**有序数组，2-10 档，最低档在前**，等级下标从 0 开始。
- `choice.criteria` 是**对象**，2-255 个选项。
- 不带 `images` 的纯文字请求可用（2026-10-30 实测），文字候选直接写进 `state`。
- `images` 是可选扩展，**最多 4 张**；每张 PNG/JPEG/WebP，≤4 MiB、≤16 百万像素，
  解码后合计 ≤8 MiB，整个请求体 ≤13 MiB。**不接受远程 URL**，必须是内联数据。
- `images` 可写成 data URL 字符串，也可写成 `{"content_type": "image/png", "base64": "..."}`。

## 响应

```json
{
  "model": "cloudflare/clef-flash",
  "answers": {
    "q1": { "type": "noul",   "noul": 0.9094 },
    "q2": { "type": "choice", "choice": "a", "confidence": 0.9182, "probabilities": { "a": 0.96, "b": 0.04 } },
    "q3": { "type": "score",  "score": 2.8899, "confidence": 0.7789,
            "legend": { "0": "最低档", "4": "最高档" },
            "probabilities": { "0": 0.02, "1": 0.02, "2": 0.02, "3": 0.90, "4": 0.02 } }
  },
  "usage": { "input_tokens": 509, "output_tokens": 0 }
}
```

- `noul` 只给"是"的概率，没有"否"字段。
- `score.score` 是**概率加权的等级下标**，可落在两档之间；换算成 0-10 用
  `score / (档数 - 1) * 10`。
- 各题答案**互不依赖**，一次请求只产出一份答案。同一请求里问多个"评分"题，
  得到的是"对这批图整体"的判断，无法拆成逐图分数。

## 对脚本的影响

- 逐图评分：一张图一个请求。
- 多图择优：一次请求放 2-4 张图，只问 `choice` 题（哪张最好）。
- `output_tokens` 恒为 0，计费只按输入 token。