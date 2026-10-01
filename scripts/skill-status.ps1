<#
.SYNOPSIS
    列出所有 skill 的来源与改动状态，并校验 registry.json 与磁盘是否一致。

.DESCRIPTION
    默认离线：比较 skill 当前 tree 与 registry 里的 lastSyncTree，
    回答"上次同步之后我自己动过哪些"。

    加 -Remote 时联网做三层对比，默认走 GitHub API（秒级）：
        本地  vs  我的 fork      -> 有没有该推上去的改动
        本地  vs  原作者仓库     -> 上游到底变了哪些文件
        fork  vs  原作者仓库     -> fork 落后了多少

    加 -Full 时改用 git subtree split + git diff 做同样的事（合集仓库
    一次 split 可能十分钟级）。gh 不可用或缺登录时自动回退到这条路。

.PARAMETER Name
    只看指定 skill。

.PARAMETER Remote
    联网做内容级对比。

.PARAMETER Full
    配合 -Remote：改用 git subtree split 对比，不调用 GitHub API。

.PARAMETER Fix
    重新计算所有 vendored skill 的 lastSyncTree 并写回 registry，修复状态失效问题。
#>
[CmdletBinding()]
param(
    [string]$Name,
    [switch]$Remote,
    [switch]$Full,
    [switch]$Fix
)

. "$PSScriptRoot\_common.ps1"

# 常规状态查询必须保持只读；只有显式 -Fix 才允许改写 registry.json。

# ---------------------------------------------------------------- -Fix 模式
if ($Fix) {
    Write-Step '修复 lastSyncTree 状态'
    $registry = Read-Registry
    $targets = @($registry.skills | Where-Object { $_.origin -eq 'vendored' })
    if ($Name) { $targets = @($targets | Where-Object { $_.name -eq $Name }) }

    $updated = 0
    foreach ($e in $targets) {
        $path = Get-SkillPath $e.name
        if (-not (Test-Path $path)) {
            Write-Warn2 "$($e.name): 磁盘上不存在，跳过"
            continue
        }
        $newTree = Get-SkillTreeHash $e.name
        if (-not $newTree) {
            Write-Warn2 "$($e.name): 无法计算 tree hash，跳过"
            continue
        }
        if ($e.lastSyncTree -ne $newTree) {
            $e.lastSyncTree = $newTree
            $e.lastSync = Get-UtcNow
            Write-Registry (Set-SkillEntry -Registry $registry -Entry $e)
            Write-Ok "$($e.name): 已更新 lastSyncTree"
            $updated++
        } else {
            Write-Host "  --  $($e.name): 无需更新" -ForegroundColor DarkGray
        }
    }

    if ($updated -gt 0) {
        Invoke-Git @('add', 'registry.json') | Out-Null
        Invoke-Git @('commit', '-m', "registry: fix lastSyncTree for $updated skill(s)") | Out-Null
        Write-Ok "已修复 $updated 个 skill 的状态"
    } else {
        Write-Host '所有 skill 状态正常。' -ForegroundColor Green
    }
    return
}

# ---------------------------------------------------------------- 常规状态显示

$registry = Read-Registry
$entries = @($registry.skills)
if ($Name) { $entries = @($entries | Where-Object { $_.name -eq $Name }) }

$skillsDir = Join-Path (Get-RepoRoot) 'skills'
$onDisk = @()
if (Test-Path $skillsDir) { $onDisk = @(Get-ChildItem -Path $skillsDir -Directory | Select-Object -ExpandProperty Name) }

if ($entries.Count -eq 0) {
    Write-Host 'registry.json 里还没有 skill。' -ForegroundColor DarkGray
    Write-Hint '自研：scripts\skill-new.ps1 -Name <name> -Description "..."'
    Write-Hint '引入：scripts\skill-vendor.ps1 -Name <name> -Upstream <owner/repo> [-Subpath <子目录>]'
} else {
    $rows = @()
    foreach ($e in $entries) {
        $state = ''; $detail = ''
        # 路径以 localPrefix 为准：整仓包放在 vendor/，不能只看 skills/ 下有没有同名目录
        if (-not (Test-Path (Get-SkillPath $e.name))) {
            $state = '缺失'; $detail = "磁盘上找不到 $(Get-SkillPrefix $e.name)"
        } elseif ($e.origin -eq 'own') {
            $state = '自研'
        } elseif (-not $e.lastSyncTree) {
            $state = '未知'; $detail = 'registry 缺 lastSyncTree，跑一次 skill-sync 补齐'
        } elseif ((Get-SkillTreeHash $e.name) -eq $e.lastSyncTree) {
            $state = '同步态'
        } else {
            $state = '本地已改'; $detail = '可用 skill-push 提 PR'
        }

        $forkShort = '-'
        if ($e.fork) { $forkShort = ($e.fork -replace '^https://github\.com/', '') }

        $rows += [pscustomobject]@{
            Skill    = $e.name
            来源     = $(if ($e.origin -eq 'own') { '自研' } else { '引入' })
            状态     = $state
            我的fork = $forkShort
            子目录   = $(if ($e.subpath) { $e.subpath } else { '-' })
            上次同步 = $(if ($e.lastSync) { ([string]$e.lastSync).Substring(0, 10) } else { '-' })
            备注     = $detail
        }
    }
    $rows | Format-Table -AutoSize -Wrap
}

# registry 未登记但磁盘存在的目录
$unregistered = @($onDisk | Where-Object { $n = $_; -not ($registry.skills | Where-Object { $_.name -eq $n }) })
if ($unregistered.Count -gt 0 -and -not $Name) {
    Write-Warn2 "以下目录未登记到 registry.json：$($unregistered -join ', ')"
    Write-Hint '自研的用 skill-new.ps1 -Register，外部引入的用 skill-vendor.ps1'
}

if (-not $Remote) { return }

# ---------------------------------------------------------------- 联网比对辅助

function Get-RepoSlug {
    <# 'https://github.com/owner/repo' / 'owner/repo' -> 'owner/repo' #>
    param([Parameter(Mandatory)][string]$Url)
    return (($Url -replace '^git@github\.com:', '' -replace '^https?://github\.com/', '') -replace '\.git$', '').TrimEnd('/')
}

function Invoke-GhApiJq {
    <# 调 gh api 并返回 jq 的输出行；失败抛异常，由调用方决定是提示还是回退 #>
    param([Parameter(Mandatory)][string]$Endpoint, [Parameter(Mandatory)][string]$Jq)
    $out = & gh api $Endpoint --jq $Jq 2>&1
    if ($LASTEXITCODE -ne 0) { throw (($out | Out-String).Trim()) }
    return @($out)
}

function Get-RemoteTreeSha {
    <# 远端仓库中某个子目录的 tree object sha；Subpath 为空表示整仓根 #>
    param([Parameter(Mandatory)][string]$Slug, [Parameter(Mandatory)][string]$Ref, [string]$Subpath)
    if (-not $Subpath) {
        $sha = @(Invoke-GhApiJq "repos/$Slug/commits/$Ref" '.commit.tree.sha')[0]
        return ([string]$sha).Trim()
    }
    $slash = $Subpath.LastIndexOf('/')
    if ($slash -lt 0) { $parent = ''; $leaf = $Subpath }
    else { $parent = $Subpath.Substring(0, $slash); $leaf = $Subpath.Substring($slash + 1) }
    $endpoint = if ($parent) { "repos/$Slug/contents/$parent`?ref=$Ref" } else { "repos/$Slug/contents?ref=$Ref" }
    $jq = ".[] | select(.name==`"$leaf`") | .sha"
    $sha = @(Invoke-GhApiJq $endpoint $jq)[0]
    if (-not $sha) { throw "$Slug@$Ref 下找不到 $Subpath" }
    return ([string]$sha).Trim()
}

function Get-RemoteTreeMap {
    <# 递归列出 tree 下所有 blob：@{相对路径 = blob sha} #>
    param([Parameter(Mandatory)][string]$Slug, [Parameter(Mandatory)][string]$TreeSha)
    $map = [ordered]@{}
    foreach ($line in (Invoke-GhApiJq "repos/$Slug/git/trees/${TreeSha}?recursive=1" '.tree[] | select(.type=="blob") | "\(.path)\t\(.sha)"')) {
        $parts = ([string]$line) -split "`t"
        if ($parts.Count -eq 2 -and $parts[1] -match '^[0-9a-f]{40}$') { $map[$parts[0]] = $parts[1] }
    }
    return $map
}

function Get-LocalTreeMap {
    <# HEAD 中 <Prefix> 下的所有 blob：@{相对路径 = blob sha} #>
    param([Parameter(Mandatory)][string]$Prefix)
    $map = [ordered]@{}
    $out = Invoke-Git @('ls-tree', '-r', '-z', "HEAD:$Prefix") -AllowFail
    if ($global:LastGitExitCode -ne 0) { return $null }
    foreach ($line in ($out -split "`0")) {
        $parts = $line -split "`t"
        if ($parts.Count -eq 2) { $map[$parts[1]] = (($parts[0] -split ' ')[2]) }
    }
    return $map
}

function Compare-TreeMap {
    <# 返回 @{ OnlyLocal; OnlyRemote; Changed }，均为已排序的相对路径数组 #>
    param($Local, $Remote)
    return @{
        OnlyLocal  = @($Local.Keys  | Where-Object { -not $Remote.Contains($_) } | Sort-Object)
        OnlyRemote = @($Remote.Keys | Where-Object { -not $Local.Contains($_) } | Sort-Object)
        Changed    = @($Local.Keys  | Where-Object { $Remote.Contains($_) -and $Local[$_] -ne $Remote[$_] } | Sort-Object)
    }
}

function Show-TreeDiff {
    <# 打印文件级差异；LeftLabel 是本地，RightLabel 是远端仓库 #>
    param($Diff, [string]$LeftLabel, [string]$RightLabel, [int]$Max = 20)
    $total = $Diff.Changed.Count + $Diff.OnlyLocal.Count + $Diff.OnlyRemote.Count
    Write-Host "  $LeftLabel 相对 $RightLabel : $total 个文件有差异" -ForegroundColor Yellow
    $shown = 0
    foreach ($p in $Diff.Changed) {
        if ($shown -ge $Max) { break }
        Write-Host "        改  $p" -ForegroundColor DarkYellow; $shown++
    }
    foreach ($p in $Diff.OnlyLocal) {
        if ($shown -ge $Max) { break }
        Write-Host "        仅本地  $p" -ForegroundColor DarkYellow; $shown++
    }
    foreach ($p in $Diff.OnlyRemote) {
        if ($shown -ge $Max) { break }
        Write-Host "        仅远端  $p" -ForegroundColor DarkYellow; $shown++
    }
    if ($total -gt $shown) { Write-Hint "…… 另有 $($total - $shown) 个文件未列出" }
}

# ---------------------------------------------------------------- 联网比对入口

# 默认走 API；只有找不到 gh 才回退到 -Full。
# 不预检 `gh auth status`：它会打一次网络，抖动时会把快路径误判成不可用，
# 白白退回分钟级的 subtree split。真正的失败交给下面的逐项 API 调用兜住。
if (-not $Full -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Warn2 '找不到 gh 命令，回退到 -Full 的 subtree split 比对'
    $Full = $true
}

# ---------------------------------------------------------------- -Full：subtree split 比对

if ($Full) {
    foreach ($e in @($entries | Where-Object { $_.origin -eq 'vendored' })) {
        if (-not (Test-Path (Get-SkillPath $e.name))) { continue }
        Write-Host ''
        Write-Step $e.name

        # ---- 本地 vs 我的 fork
        try {
            $resolved = Resolve-SkillRef -Url $e.fork -Branch $e.branch -Subpath $e.subpath
        } catch {
            Write-Warn2 "拉取 fork 失败：$($_.Exception.Message)"
            continue
        }
        # 把 fork 的 ref 取进本仓库，才能在同一个对象库里 diff
        $ref = "refs/myskill/fork/$($e.name)"
        Invoke-Git @('fetch', '--no-tags', '--force', $resolved.Mirror, "+$($resolved.Ref):$ref") | Out-Null

        # 两边的根都是 skill 根（子目录情形已由 subtree split 抹平），可直接对比
        $diff = Invoke-Git @('diff', '--stat', "${ref}:", "HEAD:$(Get-SkillPrefix $e.name)") -AllowFail
        if (-not $diff) {
            Write-Ok '本地与 fork 一致'
        } else {
            Write-Host '  本地相对 fork：' -ForegroundColor Yellow
            Write-Host $diff -ForegroundColor Yellow
            Write-Hint "提 PR：scripts\skill-push.ps1 -Name $($e.name)"
        }

        # ---- 我的 fork vs 原作者
        if (-not $e.upstream) { continue }
        $upRef = Resolve-RepoRef $e.upstream
        $mirror = $resolved.Mirror
        Invoke-Git @('remote', 'remove', 'upstream') -WorkDir $mirror -AllowFail | Out-Null
        Invoke-Git @('remote', 'add', 'upstream', $upRef.Url) -WorkDir $mirror | Out-Null
        Invoke-Git @('fetch', '--force', 'upstream', "+refs/heads/$($e.branch):refs/remotes/upstream/$($e.branch)") -WorkDir $mirror -AllowFail | Out-Null
        if ($global:LastGitExitCode -ne 0) { Write-Warn2 '拉取原作者仓库失败'; continue }

        $counts = Invoke-Git @('rev-list', '--left-right', '--count',
                               "origin/$($e.branch)...upstream/$($e.branch)") -WorkDir $mirror
        $parts = $counts -split '\s+'
        if ([int]$parts[1] -eq 0) {
            Write-Ok "fork 与 $($upRef.Display) 齐平"
        } else {
            Write-Warn2 "fork 落后 $($upRef.Display) $($parts[1]) 个提交"
            Write-Hint "追平：scripts\skill-fork-sync.ps1 -Name $($e.name)"
        }
    }
    return
}

# ---------------------------------------------------------------- 默认：GitHub API 比对

$vendored = @($entries | Where-Object { $_.origin -eq 'vendored' })
$compareCache = @{}
$apiFailed = 0

foreach ($e in $vendored) {
    Write-Host ''
    Write-Step $e.name
    $prefix = Get-SkillPrefix $e.name

    if (-not (Test-Path (Get-SkillPath $e.name))) {
        Write-Warn2 "磁盘上找不到 $prefix，跳过"
        continue
    }
    $localTree = (Invoke-Git @('rev-parse', "HEAD:$prefix") -AllowFail).Trim()
    if ($global:LastGitExitCode -ne 0) {
        Write-Warn2 "读不到 HEAD:$prefix（可能尚未提交），跳过"
        continue
    }

    $forkSlug = if ($e.fork) { Get-RepoSlug $e.fork } else { $null }
    $upstreamSlug = if ($e.upstream) { Get-RepoSlug $e.upstream } else { $null }
    $sameRepo = ($forkSlug -and $forkSlug -eq $upstreamSlug)

    # 先取两侧 tree sha：相等就不拉文件清单，省掉一半调用
    $forkTree = $null; $upTree = $null
    if ($forkSlug) {
        try { $forkTree = Get-RemoteTreeSha -Slug $forkSlug -Ref $e.branch -Subpath $e.subpath }
        catch { Write-Warn2 "取 fork tree 失败：$($_.Exception.Message)"; $apiFailed++ }
    }
    if ($upstreamSlug -and -not $sameRepo) {
        try { $upTree = Get-RemoteTreeSha -Slug $upstreamSlug -Ref $e.branch -Subpath $e.subpath }
        catch { Write-Warn2 "取原作者 tree 失败：$($_.Exception.Message)"; $apiFailed++ }
    }

    # ---- 本地 vs 我的 fork
    if ($forkTree) {
        if ($forkTree -eq $localTree) {
            Write-Ok "本地与 $forkSlug 一致"
        } else {
            try {
                $diff = Compare-TreeMap (Get-LocalTreeMap $prefix) (Get-RemoteTreeMap -Slug $forkSlug -TreeSha $forkTree)
                Show-TreeDiff $diff '本地' $forkSlug
                Write-Hint "提 PR：scripts\skill-push.ps1 -Name $($e.name)"
            } catch {
                Write-Warn2 "取 fork 文件清单失败：$($_.Exception.Message)"
                $apiFailed++
            }
        }
    }

    # ---- 本地 vs 原作者
    if ($upTree) {
        if ($upTree -eq $localTree) {
            Write-Ok "本地与 $upstreamSlug 一致（无上游更新）"
        } elseif ($forkTree -and $upTree -eq $forkTree) {
            Write-Hint "上游 $upstreamSlug 与 fork 内容一致：本地差异是本地改动，同步不会带来新内容"
        } else {
            try {
                $upDiff = Compare-TreeMap (Get-LocalTreeMap $prefix) (Get-RemoteTreeMap -Slug $upstreamSlug -TreeSha $upTree)
                Write-Host "  上游 $upstreamSlug 有差异：" -ForegroundColor Yellow
                Show-TreeDiff $upDiff '本地' $upstreamSlug
                Write-Hint "同步：scripts\skill-sync.ps1 -Name $($e.name) -FromUpstream"
            } catch {
                Write-Warn2 "取上游文件清单失败：$($_.Exception.Message)"
                $apiFailed++
            }
        }
    }

    # ---- 我的 fork vs 原作者（提交层面；按仓库缓存，合集仓库只查一次）
    if ($forkSlug -and $upstreamSlug -and -not $sameRepo) {
        $cacheKey = "$forkSlug#$upstreamSlug#$($e.branch)"
        if (-not $compareCache.ContainsKey($cacheKey)) {
            try {
                $forkOwner = ($forkSlug -split '/')[0]
                $cmpJson = (Invoke-GhApiJq "repos/$upstreamSlug/compare/$($e.branch)...${forkOwner}:$($e.branch)" '{status: .status, ahead: .ahead_by, behind: .behind_by}' | Out-String)
                $compareCache[$cacheKey] = ($cmpJson | ConvertFrom-Json)
            } catch {
                Write-Warn2 "对比 fork 与原作者失败：$($_.Exception.Message)"
                $compareCache[$cacheKey] = $null
                $apiFailed++
            }
        }
        $cmp = $compareCache[$cacheKey]
        if ($cmp) {
            if ([int]$cmp.behind -eq 0) {
                Write-Ok "fork 与 $upstreamSlug 齐平"
            } else {
                Write-Warn2 "fork 落后 $upstreamSlug $($cmp.behind) 个提交"
                Write-Hint "追平：scripts\skill-fork-sync.ps1 -Name $($e.name)"
            }
        }
    }
}

if ($apiFailed -gt 0) {
    Write-Host ''
    Write-Warn2 "$apiFailed 处 GitHub API 调用失败（多为网络抖动）"
    Write-Hint '重跑一次通常即可；持续失败时用 -Full 走 subtree split 兜底'
}
