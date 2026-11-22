# myskill

个人 Claude Code / Codex Skill 集合。装两类东西：自己写的 skill，以及从别人那里引入的 skill。

外部 skill **一律以自己的 fork 为基线**，不直接对接原作者仓库。fork 负责日常同步与提 PR，
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
├── vendor/<package>/     # 独立开源的整仓技能包
├── scripts/               # 引入 / 同步 / 提 PR / 部署
└── docs/
    ├── usage.md           # 按场景查的操作手册 ← 日常看这个
    ├── fork-workflow.md   # 设计理由、取舍、已知坑
    └── skills/            # 引入 skill 的本地改动账，规则在该目录 README.md
```

## 知产实务工作台技能包

以下三个技能在独立仓库 `zhjnerv/ip-practice-workbench-skills` 开发、开源发布，并分别同步到本仓库标准的 `skills/<name>/` 目录，供安装器直接发现。上游仓库根目录的许可证、资料说明和统一验证入口仍保留在 [vendor/ip-practice-workbench-skills](vendor/ip-practice-workbench-skills/README.md)。管理方法见 [技能说明](docs/skills/ip-practice-workbench-skills.md)。

| Skill | 用途 | 使用与数据说明 |
| --- | --- | --- |
| [cn-patent-fast-track-screener](skills/cn-patent-fast-track-screener/SKILL.md) | 专利预审、优先审查与 IPC 分类范围初筛 | [README](skills/cn-patent-fast-track-screener/README.md) |
| [cn-office-action-prior-art-collector](skills/cn-office-action-prior-art-collector/SKILL.md) | 审查意见通知书解析、专利号规范化与对比文件收集 | [README](skills/cn-office-action-prior-art-collector/README.md) |
| [cn-trademark-goods-services-recommender](skills/cn-trademark-goods-services-recommender/SKILL.md) | 商标大类、类似群和商品服务项目推荐，校验后导出申报表 | [README](skills/cn-trademark-goods-services-recommender/README.md) |

按技能名部署，例如 `scripts/skill-deploy.ps1 -Name cn-patent-fast-track-screener`。三个登记项各自从源仓库对应技能目录同步；配置 [最小权限 token](docs/skills/ip-practice-workbench-skills.md) 后，myskill 的技能改动进入 `main` 会自动为源仓库创建/更新 PR。根许可证、资料来源和统一测试入口随 [上游包资料](vendor/ip-practice-workbench-skills/DATA_SOURCES.md) 保留。

```powershell
.\scripts\skill-sync.ps1 -Name cn-patent-fast-track-screener
.\scripts\skill-deploy.ps1 -Name cn-patent-fast-track-screener
```

## 命令速查

完整用法（含合集仓库的处理、迁移已有 skill、故障排查）见 **[docs/usage.md](docs/usage.md)**。

```powershell
# 自研
.\scripts\skill-new.ps1 -Name contract-review -Description "当用户需要审查合同条款风险时使用。不要用于合同起草。"

# 引入（-Subpath 用于"skill 是合集仓库里的一个子目录"；没 fork 过就加 -CreateFork）
.\scripts\skill-vendor.ps1 -Name git-workflow -Upstream cat-xierluo/legal-skills -Subpath skills/git-workflow
.\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool-skill -CreateFork

# 看状态
.\scripts\skill-status.ps1            # 离线：相对上次同步点改了哪些
.\scripts\skill-status.ps1 -Remote    # 联网：本地 vs fork、fork vs 原作者

# 同步
.\scripts\skill-fork-sync.ps1         # ① fork 追平原作者
.\scripts\skill-sync.ps1              # ② fork -> 本仓库
.\scripts\skill-sync.ps1 -FromUpstream    # ①②一起

# 提 PR
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
