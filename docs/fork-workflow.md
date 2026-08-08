# Fork 工作流

本仓库对外部 skill 只认一个来源：**我自己的 fork**。原作者仓库不作为同步源。

```
   原作者仓库                 我的 fork                      本仓库
   upstream/main             zhjnerv/xxx                    skills/<name>/
        │                         │                              │
        │  ① skill-fork-sync      │                              │
        └──────── 追平 ──────────►│                              │
                                  │  ② skill-sync                │
                                  ├────── subtree pull ─────────►│
                                  │                              │
                                  │  ③ skill-push                │
      ◄── ④ PR ───  myskill/<name>│◄───── subtree push ──────────┤
```

## 为什么以 fork 为基线，而不是直接对接原作者

直接从原作者仓库 pull、只在要提 PR 时才用 fork，会出两个问题：PR 的 base 是陈旧的 fork，
diff 里混进一堆与你的改动无关的内容；fork 长期不动，哪天原作者仓库没了你也没有完整备份。

以 fork 为基线，四步各司其职，每一步的失败都不牵连其他步：① 只动 GitHub 上的 fork，
② 只动本仓库，③ 只动 fork 的特性分支，④ 是人工确认的对外动作。

**关键约束：个性修改不落到 fork 的默认分支。**
`skill-push.ps1` 推的是 `myskill/<skill>` 特性分支。默认分支要留着当原作者的镜像，
这样 ① 永远能快进。一旦有人往 fork 的 main 直接提交，① 就只能靠 `-Force` 强推，
那些提交会丢。

## 为什么用 git subtree 而不是 submodule

submodule 只在父仓库存一个 commit 指针，skill 内容不在父仓库工作区里。三个后果：

1. 改一行提示词要先进 submodule、切分支、提交，再回父仓库更新指针；
2. 换台机器克隆忘了 `submodule update --init` 就是一堆空目录，而空目录会让 Agent 静默少掉一批 skill；
3. `.claude/skills` 通过 junction 指向工作区目录，submodule 的空目录直接把这条链路打断。

subtree 把内容真正放进工作区，代价是仓库历史里混入外部历史——用 `--squash` 压成一条。

**`--squash` 必须全程一致**：vendor 用了 `--squash`，之后每次 pull 也必须带。
脚本已写死，不要绕过脚本手敲 `git subtree pull`，否则 subtree 找不到上一次的压缩记录，
会把 fork 的完整历史重放进来。

## 整仓库即 skill vs 合集仓库的一个子目录

很多 skill 发布在合集仓库里（`owner/some-skills/<skill-name>/`）。`registry.json` 的 `subpath`
字段区分这两种形态，它决定 vendor / sync / push 各自走哪条分支，是整个仓库最重要的开关。

子目录形态不能直接 `subtree add`，否则整个合集都会被拖进来。做法是先在 fork 的本地镜像里
`git subtree split --prefix=<子目录>`，把该子目录的历史抽成"根就是 skill"的独立分支再 add。
split 是确定性的：fork 有新提交时重跑只在同一条分支上追加，所以可以反复 pull。

镜像克隆按**仓库**缓存在 `%LOCALAPPDATA%\myskill-cache\`（`MYSKILL_CACHE` 可覆盖）。
一个合集 fork 供 12 个 skill 使用时只有一份克隆。放在仓库外是因为本仓库在 Google Drive 同步目录里。

---

## 操作

### 引入

前提是你已经 fork 过原作者仓库。没 fork 的话加 `-CreateFork`，脚本用 `gh` 帮你建。

```powershell
# 合集仓库里的一个 skill
.\scripts\skill-vendor.ps1 -Name git-workflow -Upstream cat-xierluo/legal-skills -Subpath git-workflow

# 整个仓库就是一个 skill，顺手创建 fork
.\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool-skill -CreateFork

# fork 改过名，显式指定
.\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool-skill -Fork zhjnerv/my-pdf-tool
```

fork 地址默认按「你的 GitHub 账号 + 原仓库名」推导，账号取自 `gh api user`。

### 同步

```powershell
.\scripts\skill-sync.ps1 -DryRun                  # 看 fork 上有没有新东西
.\scripts\skill-sync.ps1                          # fork -> 本仓库
.\scripts\skill-sync.ps1 -FromUpstream            # 先让 fork 追平原作者，再拉进来
.\scripts\skill-fork-sync.ps1 -DryRun             # 只看 fork 落后原作者多少
```

`-FromUpstream` 会 push 到你的 fork。`skill-fork-sync.ps1` 按仓库去重，一个合集 fork 只同步一次。

改过的 skill 在 pull 时可能冲突，脚本会停下并列出冲突文件：

```powershell
git status                     # 看冲突文件
# 编辑，解掉 <<<<<<< ======= >>>>>>> 标记
git add <文件>
git commit
.\scripts\skill-sync.ps1 -Name <skill>    # 重跑，刷新 registry 的 lastSync
```

冲突时脚本 `break` 而不是接着处理下一个——工作区已经脏了，硬往下走会把几个 skill 的冲突搅在一起。

### 看状态

```powershell
.\scripts\skill-status.ps1            # 离线：相对"上次同步点"改了哪些
.\scripts\skill-status.ps1 -Remote    # 联网：本地 vs fork、fork vs 原作者
```

离线判断依据是 `registry.json` 的 `lastSyncTree`（同步完成时记下的 `skills/<name>` tree 哈希）。
`-Remote` 才回答"我到底改了什么"和"fork 烂了没有"。

### 回贡

```powershell
.\scripts\skill-push.ps1 -Name pdf-tool           # 推到 fork 的 myskill/pdf-tool 分支
.\scripts\skill-push.ps1 -Name pdf-tool -Pr       # 推完打开预填的 PR 页面
```

`-Pr` 用 `gh pr create --web` 打开浏览器草稿，不在命令行里直接建 PR——PR 是发到别人仓库的对外动作，
应该过目之后再提交。

按 `subpath` 分两条路：

- **无 subpath** → `git subtree push`，保留提交历史。
- **有 subpath** → 快照方式：克隆 fork、从原作者分支切出特性分支、把 `skills/<Name>/` 整体覆盖到
  `<subpath>/`、提交推送。不保留逐次历史，换来一个**目录形状正确、能直接开 PR** 的分支。
  `subtree push` 在这种情形会把内容推到 fork 的仓库根，形状对不上，PR 没法看。

---

## 引入之后立刻要做的一件事

引入别人的 skill 等于把别人的提示词和脚本放进你的 Agent 执行链路。至少扫一遍：

- `scripts/` 下有没有联网、写工作目录之外的路径、读取凭证的动作；
- `SKILL.md` 里有没有指示 Agent 收集信息并外发的内容；
- 有没有硬编码的 API Key / Token。

## 已知坑

**上游带 GitHub Actions 时首次追平会被拒**：上游提交只要碰了 `.github/workflows/`，
推送就要求 OAuth token 带 `workflow` scope，`gh repo sync` 会直接报错。授权一次即可，全局生效：

```powershell
gh auth refresh -s workflow
```

**Google Drive 同步 `.git`**：本仓库在 `D:\谷歌硬盘\PC同步\` 下，Drive 会在 git 写对象时同时上传 `.git`，
理论上存在索引损坏风险。要么把这个目录排除出 Drive 同步（GitHub 已经是异地备份），要么接受风险并保证及时 push。

**行尾**：`.gitattributes` 强制全仓库 LF。外部 skill 几乎都在 Linux/macOS 维护，工作区一旦出现 CRLF，
`subtree pull` 会把整个文件判成改动，制造大量伪冲突。PowerShell 的 `Set-Content` / `Add-Content` 默认写 CRLF，
靠 `.gitattributes` 在提交时归一化。

**skill 目录名 = SKILL.md 的 name**：Claude Code 按目录发现 skill，两者不一致时行为容易误判。
`-Name` 可以和上游目录名不同，但改了就要同步改 `SKILL.md`。
