# skill 改动记账

本仓库继续用 `skills/<name>/` 汇合 skill，来源只记在 `registry.json`。每个 skill 自己的需求和更新另记账。不建仓库级 `CHANGELOG.md`。

改哪个 skill，就只改那一棵树，并在同一次提交里带上对应账本。个性化改动默认不向上游开 PR；只有用户明确要求时才用 `skill-push.ps1 -Pr`。

## 引入的 skill

上游自己的 `CHANGELOG.md`、`TASKS.md`、`DECISIONS.md` 是上游的账。不要把我们的需求、决策或版本记录写进去。

自动同步碰到同一文件两边都改过时，会整份留下本仓库的版本，上游对这个文件的后续说明就不会再进来。所以本地账放在 skill 目录外面：

`docs/skills/<registry 里的 name>.md`

`vendor/` 下的整包也用 registry 的 `name`，不按里面的子 skill 拆账。没有本地改动就不建文件。

每次改一个引入的 skill：

1. 跑 `.\scripts\skill-status.ps1 -Remote -Name <name>`，确认不是上游已经修过的问题。
2. 先在账本里写下要解决的问题、改哪些、明确不改什么、怎样算做完。
3. 只改这个 skill 的目录。
4. 验证之后补上日期、解决了什么、改了什么、证据、还留下什么。
5. skill 改动和这条记录一起提交。

账本用下面的样子，一条更新一块：

```markdown
## YYYY-MM-DD 短标题

- 问题：
- 范围：
- 非目标：
- 改动：
- 证据：
- 遗留：
```

有取舍时在同一条里加「放弃的方案」和「怎样回退」，不另开决策文件。

## 自研 skill

`scripts/skill-new.ps1` 会在 `skills/<name>/` 里放三份空账：

- `TASKS.md`：未完成在上。每条写问题、范围、非目标、验收。做完后挪到已完成，并写证据。
- `DECISIONS.md`：只在有取舍时追加。写背景、决定、放弃的方案、影响与回退。
- `CHANGELOG.md`：只记已经做完的版本，标题用 `## [版本] - YYYY-MM-DD`。分类用新增、改进、修复。不要写 `Unreleased`。

## 已有账本

- [md2word](md2word.md)
- [gzh-design](gzh-design.md)
