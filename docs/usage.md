# 使用手册

按场景查。设计理由和踩坑在 [fork-workflow.md](fork-workflow.md)，这里只讲怎么操作。

所有命令都在仓库根目录下执行。

---

## 1. 引入一个别人的 skill

### 先判断是哪种形态

决定要不要加 `-Subpath` 的唯一依据：`SKILL.md` 在仓库根目录，还是在某个子目录里。

```powershell
gh api "repos/<原作者>/<仓库>/git/trees/HEAD?recursive=1" --jq '.tree[] | select(.path|endswith("SKILL.md")) | .path'
```

- 输出 `SKILL.md` → 整个仓库就是一个 skill，不加 `-Subpath`
- 输出 `skills/git-workflow/SKILL.md`、`skills/skill-lint/SKILL.md`… → 合集仓库，
  每个 skill 单独引入，`-Subpath` 填**去掉 `/SKILL.md` 之后的完整路径**

别凭直觉猜子目录路径。`cat-xierluo/legal-skills` 的 skill 在 `skills/<name>/` 下而不是 `<name>/` 下，
猜错的话 subtree 会引入一个空目录或错误内容。

### 引入

```powershell
# 整仓库即 skill
.\scripts\skill-vendor.ps1 -Name qu-ai-wei -Upstream LifelongLazyLearner/qu-ai-wei

# 合集仓库里的一个子目录（路径以上面的 gh 命令输出为准）
.\scripts\skill-vendor.ps1 -Name git-workflow -Upstream cat-xierluo/legal-skills -Subpath skills/git-workflow

# 还没 fork 过，让脚本用 gh 帮你建
.\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool -CreateFork

# fork 改过名字，显式指定
.\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool -Fork zhjnerv/my-pdf-tool
```

`-Name` 是它在本仓库和 `.claude\skills` 下的目录名，**必须与 `SKILL.md` 里的 `name` 一致**。
fork 地址默认按「你的 GitHub 账号 + 原仓库名」推导，不用填。

同一个合集 fork 供多个 skill 用时，`-CreateFork` 只在第一条命令上加。

### 部署

```powershell
.\scripts\skill-deploy.ps1 -Name qu-ai-wei          # 单个
.\scripts\skill-deploy.ps1                          # 全部
.\scripts\skill-deploy.ps1 -TargetRoot "$env:USERPROFILE\.codex\skills"   # 部署给别的 Agent
```

目标位置已经被别的东西占了会拒绝执行并说明原因，加 `-Force` 才替换（实体目录先带时间戳备份）。

---

## 2. 日常更新

```powershell
.\scripts\skill-fork-sync.ps1 -DryRun     # 只看：哪些 fork 落后原作者多少
.\scripts\skill-sync.ps1 -FromUpstream    # 一路做完：fork 追平原作者 -> 拉进本仓库
```

想只更新一个：加 `-Name <skill>`。

不加 `-FromUpstream` 时只做「fork → 本仓库」这一段，不碰 GitHub 上的 fork。

### 遇到冲突

只有你改过的 skill 才会冲突。脚本会停下并列出冲突文件，处理方式和普通 merge 一样：

```powershell
git status                              # 看冲突文件
# 编辑，解掉 <<<<<<< ======= >>>>>>> 标记
git add <文件>
git commit
.\scripts\skill-sync.ps1 -Name <skill>  # 重跑，刷新 registry 的 lastSync
```

脚本遇到冲突会停止处理后面的 skill——工作区已经脏了，接着往下走会把几个 skill 的冲突搅在一起。

---

## 3. 我改了 skill，想回贡给原作者

```powershell
.\scripts\skill-status.ps1 -Remote -Name <skill>   # 先看清改了什么
.\scripts\skill-push.ps1 -Name <skill> -Pr         # 推到 fork 的特性分支 + 打开 PR 页面
```

`-Pr` 只是打开预填好的 PR 页面，要你在浏览器里确认后才提交。不加 `-Pr` 就只推分支，之后自己去 GitHub 上开。

推的是 fork 的 `myskill/<skill>` 分支，不碰 fork 的默认分支——默认分支要留着当原作者的镜像，否则以后追平就得强推，你的提交会丢。

原作者合并之后，下一次 `skill-sync.ps1 -FromUpstream` 会把它作为上游内容正常拉回来。

---

## 4. 看状态

```powershell
.\scripts\skill-status.ps1            # 离线，秒回
.\scripts\skill-status.ps1 -Remote    # 联网，逐个对比
```

两者回答的问题不同，别混：

| | 回答什么 | 什么时候用 |
|---|---|---|
| 离线 | 上次同步之后我动过哪些 | 想知道有没有未提交/未回贡的改动 |
| `-Remote` | 本地 vs fork 差什么、fork 落后原作者多少 | 决定要不要回贡、要不要追平 |

离线显示「同步态」不代表和 fork 一致——如果你改完之后已经 sync 过一次，离线就看不出来了，只有 `-Remote` 能查出来。

---

## 5. 把现在 `.cc-switch` 里的 skill 迁进来

`~\.cc-switch\skills\` 下那些是 skill-manager 装的静态副本（`.git` 被删掉了）。迁移之前先确认你有没有就地改过它，改过的话要保住。

### 第一步：找到它的来源

```powershell
Get-Content "$env:USERPROFILE\.cc-switch\skills\<name>\SKILL.md" -TotalCount 10 -Encoding UTF8
```

frontmatter 里的 `homepage` 就是上游。没有 `homepage` 的只能靠搜索或回忆。

### 第二步：fork 上游，然后引入

按上面第 1 节做。引入之后 `skills/<name>/` 是 fork 的内容。

### 第三步：比对，确认有没有本地改动被落下

**必须在第四步之前做，也必须在任何一次 `skill-fork-sync` 之前做。**
比对的前提是「本仓库的内容 = 你正在用的那份的来源版本」。一旦先升级了，
输出里全是版本演进带来的差异，你的个性修改会淹没在里面，认不出来。

```powershell
$V = "<本仓库路径>\skills\<name>"
$L = "$env:USERPROFILE\.cc-switch\skills\<name>"
function Get-Map([string]$root) {
  $m = @{}
  Get-ChildItem $root -Recurse -File -Force | Where-Object { $_.FullName -notmatch '\\\.git\\' } | ForEach-Object {
    $rel = $_.FullName.Substring($root.Length + 1) -replace '\\', '/'
    # 归一化行尾再算哈希，避免 CRLF/LF 差异造成假阳性
    $text = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($_.FullName)) -replace "`r`n", "`n"
    $m[$rel] = [System.BitConverter]::ToString(
      [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text)))
  }
  return $m
}
$mv = Get-Map $V; $ml = Get-Map $L
Write-Output "=== 只在你正在用的那份里有 ==="; $ml.Keys | Where-Object { -not $mv.ContainsKey($_) } | Sort-Object
Write-Output "=== 两边都有但内容不同 ===";     $ml.Keys | Where-Object { $mv.ContainsKey($_) -and $mv[$_] -ne $ml[$_] } | Sort-Object
```

只在 fork 里有 `.github/`、`.gitignore`、`.cursorrules` 这类文件是正常的——skill-manager 安装时会剥掉，不是你删的。

上面两组输出为空 → 没改过，直接进第四步。
有内容 → 把那些文件从 `.cc-switch` 那份拷到 `skills/<name>/`，`git commit`，这样改动就进了本仓库，之后还能用 `skill-push.ps1` 回贡。

### 第四步：升级并切换部署

```powershell
.\scripts\skill-sync.ps1 -Name <name> -FromUpstream    # 顺便追平原作者的新版本
.\scripts\skill-deploy.ps1 -Name <name> -Force
```

`.claude\skills\<name>` 原来的符号链接被换成指向本仓库的 junction。
`.cc-switch` 那份不会被动，确认新的能用之后再删。

---

## 6. 新机器 / 重装之后

```powershell
git clone https://github.com/zhjnerv/myskill.git
cd myskill
.\scripts\skill-deploy.ps1
```

skill 内容都在仓库里，不需要额外拉取。只有 `gh` 需要单独登录：`gh auth login`。

---

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `gh repo sync` 报 `workflow scope` | 上游提交改过 `.github/workflows/`，token 权限不够 | `gh auth refresh -s workflow --hostname github.com`，一次性 |
| `工作区有未提交改动` | sync / push 前必须干净 | `git status` 看一眼，该提交提交，该 stash stash |
| `无法快进：fork 的 main 上有 N 个独有提交` | 有人往 fork 默认分支直接提交过 | 确认那些提交可以丢弃后加 `-Force`；正确做法是改动走 `skill-push.ps1` 推特性分支 |
| `skills/<name> 下没有 SKILL.md` | `-Subpath` 指错了目录 | 用第 1 节的 gh 命令确认 SKILL.md 的真实路径，删掉重引 |
| deploy 说「目标是实体目录，加 -Force」 | 那个位置已经有真实文件夹 | 确认里面没有要保留的东西，加 `-Force`（会先带时间戳备份） |
| Agent 里 skill 没生效 | 目录名和 `SKILL.md` 的 `name` 不一致 | 改成一致，或重新部署 |
| 大量文件莫名其妙变成「已修改」 | 行尾被改成 CRLF 了 | `git checkout -- skills/` 复原，别动 `.gitattributes` 里的 `eol=lf` |
| `status` 里 `lastSyncTree` 缺失或状态混乱 | 冲突后手工 commit 忘记重跑 sync，或手工编辑 registry 后没更新 | `.\scripts\skill-status.ps1 -Fix` 重新计算所有 tree hash |
| `skill-push -Pr` 报「fork 落后原作者 N 个提交」 | 改动前没先追平 fork，推的 PR 会包含大量无关 diff | `.\scripts\skill-fork-sync.ps1 -Name <skill>` 追平后重试 |
| 镜像缓存占用过多磁盘空间 | 删除 skill 后镜像仍在 `%LOCALAPPDATA%\myskill-cache\` | `.\scripts\skill-cache-clean.ps1` 清理不再使用的镜像 |

---

## 实例：qu-ai-wei

本仓库第一个 skill，完整过程留档：

```powershell
# 1. 已在 GitHub 上 fork 好 LifelongLazyLearner/qu-ai-wei -> zhjnerv/qu-ai-wei
# 2. 确认 SKILL.md 在根目录，所以不加 -Subpath
.\scripts\skill-vendor.ps1 -Name qu-ai-wei -Upstream LifelongLazyLearner/qu-ai-wei

# 3. 比对确认 .cc-switch 那份和 fork 逐字节一致，无本地改动要抢救

# 4. fork 落后原作者 2 个提交，一路追平并拉进来
gh auth refresh -s workflow --hostname github.com     # 上游改过 workflows，一次性授权
.\scripts\skill-sync.ps1 -Name qu-ai-wei -FromUpstream

# 5. 切换部署
.\scripts\skill-deploy.ps1 -Name qu-ai-wei -Force
```

结果：v0.8.2 → v0.8.4，本地 = fork = 原作者三层齐平。
上游在 v0.8.4 里做了一次瘦身（删 67 个文件），把 skill 自身的开发文档从发布物里拿掉了。
