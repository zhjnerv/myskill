# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

个人 Skill 集合仓库。没有构建、没有测试套件、没有运行时——**产物就是 `skills/` 下的目录本身**。
仓库的全部复杂度集中在一件事：让自研 skill 和外部引入的 skill 共存于同一个可直接编辑的工作区，
并且都能双向同步。

## 常用命令

```powershell
.\scripts\skill-new.ps1       -Name <name> -Description "<何时用/何时不用>"   # 新建自研
.\scripts\skill-new.ps1       -Name <name> -Register                          # 已有目录补登记
.\scripts\skill-vendor.ps1    -Name <name> -Upstream <owner/repo> [-Subpath <子目录>] [-Fork <我的fork>] [-CreateFork]
.\scripts\skill-fork-sync.ps1 [-Name <name>] [-DryRun] [-Force]               # ① fork 追平原作者
.\scripts\skill-sync.ps1      [-Name <name>] [-DryRun] [-FromUpstream]        # ② fork -> 本仓库
.\scripts\skill-push.ps1      -Name <name> [-Branch <分支>] [-Pr] [-Force]    # ③ 本仓库 -> fork，可开 PR
.\scripts\skill-status.ps1    [-Name <name>] [-Remote]                        # 状态；-Remote 做内容级对比
.\scripts\skill-deploy.ps1    [-TargetRoot <路径>] [-Force] [-Prune] [-DryRun] # junction 到 Agent skills 目录
```

没有 lint / test 命令。改完 skill 的验证方式是部署后在真实会话里触发它。

面向使用者的操作手册在 `docs/usage.md`（按场景查），设计理由与取舍在 `docs/fork-workflow.md`。
改动脚本行为时这两份都要同步更新——尤其是 `docs/usage.md` 的故障排查表，它记的是真实撞过的坑。

## 架构：四个必须一起看才成立的设计

### 1. fork 是唯一同步源，原作者仓库只喂 fork

外部 skill 一律先 fork 到自己账号下，本仓库只与 fork 交互。原作者仓库（registry 的 `upstream`）
只在 `skill-fork-sync.ps1` 里用到，作用是把 fork 追平。

**由此推出一条硬约束：个性修改绝不能落到 fork 的默认分支。**
`skill-push.ps1` 推的是 `myskill/<skill>` 特性分支，默认分支留作原作者的镜像，
这样 fork 追平永远是快进。要改这部分逻辑前先想清楚会不会破坏这条不变量。

### 2. `registry.json` 是唯一元数据来源

`skills/` 下的目录本身不携带来源信息（vendor 时 `--squash` 压掉了历史，也没有 `.git`）。
一个 skill 是自研还是引入、fork 在哪、原作者是谁、是否改过，**全部只记在 `registry.json`**。
任何脚本改动 skill 状态后都必须写回 registry 并提交，否则下一次同步失去基准。

字段语义（`scripts/_common.ps1: New-SkillEntry`）：

- `origin` = `own` / `vendored`。
- `fork` = 主 remote，vendor / sync / push 都走它。
- `upstream` = 原作者仓库，只用于 `skill-fork-sync.ps1` 和 PR 的目标。
- `subpath` 非空 = skill 是合集仓库里的一个子目录。这个字段决定 vendor / sync / push
  各自走哪条分支，是整个仓库最重要的开关。
- `lastSyncTree` = 上次同步完成时 `git rev-parse HEAD:skills/<name>` 的 tree 哈希。
  离线判断"是否被本地改过"完全依赖它，不要手工改。

### 3. subtree（而非 submodule），且 `--squash` 全程一致

选型理由见 `docs/fork-workflow.md`。对后续操作有约束力的两条：

- vendor 用了 `--squash`，之后**每一次** pull 都必须带。漏了会让 subtree 找不到上一次的压缩记录，
  把 fork 的完整历史重放进本仓库。脚本已写死，不要绕过脚本手敲 `git subtree pull`。
- 子目录形态不能直接 `subtree add`，必须先在镜像里 `git subtree split --prefix=<subpath>`
  抽出"根即 skill"的分支。`Resolve-SkillRef`（`_common.ps1`）封装了这个分叉，
  vendor / sync / status -Remote 三处都走它，改同步逻辑只改这一个函数。

镜像克隆按**仓库**缓存在 `%LOCALAPPDATA%\myskill-cache\`（`MYSKILL_CACHE` 可覆盖），
不按 skill——一个合集 fork 供多个 skill 使用时只该有一份克隆。刻意在仓库外，因为仓库位于 Google Drive 同步目录。

### 4. 回贡按 `subpath` 分两条路

`skill-push.ps1`：

- 无 `subpath` → `git subtree push`，保留历史。
- 有 `subpath` → **快照方式**：克隆 fork、从原作者分支切特性分支、robocopy `/MIR` 覆盖到子目录、提交推送。
  不保留逐次历史，但产出的分支目录形状正确、能直接开 PR。`subtree push` 在这种情形会把内容推到
  fork 的仓库根，形状对不上，PR 不可用——这是刻意取舍，不要"优化"回 subtree push。

## 对外动作的边界

三个脚本会改动 GitHub 上的状态，改它们时保持这个分级：

- `skill-vendor.ps1 -CreateFork` —— 建 fork，必须显式加标志。
- `skill-fork-sync.ps1` —— push 到自己的 fork；非快进时拒绝执行，要 `-Force` 才强推。
- `skill-push.ps1 -Pr` —— 只用 `gh pr create --web` 打开预填页面，不在命令行里直接建 PR。
  PR 是发到别人仓库的动作，留人工确认这一步。

## 环境约束

- **行尾**：`.gitattributes` 强制全仓库 `eol=lf`。外部 skill 几乎都在 Linux/macOS 维护，
  工作区出现 CRLF 会让 `subtree pull` 把整文件判成改动，制造大量伪冲突。不要放宽这条。
- **符号链接**：本机未开 Windows 开发者模式，符号链接需要管理员权限。
  部署一律用 NTFS junction（`New-Item -ItemType Junction`）。
- **Google Drive**：仓库路径在 `D:\谷歌硬盘\PC同步\` 下，Drive 会同步 `.git`。
- **gh**：已安装并以 `zhjnerv` 登录。`Test-GhReady` 会检查可用性，不可用时相关能力降级为提示，
  不要让脚本在没有 gh 时直接失败。
- 脚本全部 PowerShell，`Set-StrictMode -Version Latest` + `$ErrorActionPreference='Stop'`
  在 `_common.ps1` 中统一设置。新脚本第一行点入 `. "$PSScriptRoot\_common.ps1"`，
  不要各自重复定义 git 封装。

## 修改 skill 内容时

- `skills/<name>/` 目录名必须与该 skill `SKILL.md` frontmatter 的 `name` 一致。
- 改 vendored skill 前先跑 `skill-status.ps1 -Remote -Name <name>` 看清相对 fork 的差异，
  以及 fork 有没有落后原作者——避免把上游已经修过的问题再修一遍。
