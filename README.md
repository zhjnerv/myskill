# myskill

个人 Claude Code / Codex Skill 集合。装两类东西：自己写的 skill，以及从别人那里引入的 skill。

外部 skill **一律以自己的 fork 为基线**，不直接对接原作者仓库。fork 负责日常同步与回贡，
原作者仓库只用来把 fork 追平。

```
   原作者仓库              我的 fork                  本仓库
   upstream/main          zhjnerv/xxx                skills/<name>/
        │                      │                          │
        │ ① skill-fork-sync    │                          │
        └───── 追平 ──────────►│                          │
                               │ ② skill-sync             │
                               ├───── subtree pull ──────►│
                               │                          │
                               │ ③ skill-push             │
     ◄── ④ PR ── myskill/<name>│◄──── subtree push ───────┤
```

## 布局

```
myskill/
├── registry.json          # 每个 skill 的来源与同步状态（唯一元数据来源）
├── skills/<name>/         # 一个目录一个 skill，SKILL.md 必需
├── scripts/               # 引入 / 同步 / 回贡 / 部署
└── docs/fork-workflow.md  # 工作流细节与踩坑
```

## 命令

```powershell
# 自研
.\scripts\skill-new.ps1 -Name contract-review -Description "当用户需要审查合同条款风险时使用。不要用于合同起草。"

# 引入（-Subpath 用于"skill 是合集仓库里的一个子目录"；没 fork 过就加 -CreateFork）
.\scripts\skill-vendor.ps1 -Name git-workflow -Upstream cat-xierluo/legal-skills -Subpath git-workflow
.\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool-skill -CreateFork

# 看状态
.\scripts\skill-status.ps1            # 离线：相对上次同步点改了哪些
.\scripts\skill-status.ps1 -Remote    # 联网：本地 vs fork、fork vs 原作者

# 同步
.\scripts\skill-fork-sync.ps1         # ① fork 追平原作者
.\scripts\skill-sync.ps1              # ② fork -> 本仓库
.\scripts\skill-sync.ps1 -FromUpstream    # ①②一起

# 回贡
.\scripts\skill-push.ps1 -Name pdf-tool -Pr

# 部署到 Agent（NTFS junction，改仓库即时生效）
.\scripts\skill-deploy.ps1 -Prune
.\scripts\skill-deploy.ps1 -TargetRoot "$env:USERPROFILE\.codex\skills"
```

所有脚本都支持 `-DryRun` 或 `-WhatIf` 语义的预览（见各脚本 `Get-Help`）。

## 部署模型

`skills/<name>/` 通过 NTFS 目录联接挂到 `~\.claude\skills\<name>`。
用 junction 而非符号链接是因为 junction 不需要管理员权限；用链接而非复制是因为
单一事实来源必须是本仓库，复制会立刻产生"改了哪边"的歧义。

## 依赖

- Git（含 `git subtree`，Git for Windows 自带）
- GitHub CLI `gh`，已登录。用于推导 fork 地址、创建 fork、`gh repo sync`、开 PR。
  没有 `gh` 时这些能力降级为手工操作，subtree 部分不受影响。
