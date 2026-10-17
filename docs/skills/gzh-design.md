# gzh-design 本地账

上游没有这份本地记录。不要把下面的内容补进上游仓库。

## 2026-09-26 文末固定账号二维码

- 问题：本地排版要在文末带上固定的公众号二维码，不能每次手贴，也不该依赖上游主题。
- 范围：`skills/gzh-design/assets/account-qr.jpg`、`skills/gzh-design/scripts/account_qr_block.py`、`skills/gzh-design/SKILL.md`。
- 非目标：不改主题组件，不把这个二维码送回上游。
- 改动：提交 `1bbdfec`。脚本把技能目录里的二维码印成文末 HTML。
- 证据：上述 3 个文件在该提交中。fork 的对应树当时仍是同步基线 `2d6ac9a`，不含这 3 处改动。
- 遗留：无。
