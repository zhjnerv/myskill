<#
.SYNOPSIS
    列出所有 skill 的来源与改动状态，并校验 registry.json 与磁盘是否一致。

.DESCRIPTION
    默认离线：比较 skills/<name> 当前 tree 与 registry 里的 lastSyncTree，
    回答"上次同步之后我自己动过哪些"。

    加 -Remote 时联网做两层对比，这是决定要不要提 PR / 要不要追平原作者的依据：
        本地  vs  我的 fork      -> 有没有该推上去的改动
        fork  vs  原作者仓库     -> fork 落后了多少

.PARAMETER Name
    只看指定 skill。

.PARAMETER Remote
    联网做内容级对比。

.PARAMETER Fix
    重新计算所有 vendored skill 的 lastSyncTree 并写回 registry，修复状态失效问题。
#>
[CmdletBinding()]
param(
    [string]$Name,
    [switch]$Remote,
    [switch]$Fix
)

. "$PSScriptRoot\_common.ps1"

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
            Write-Warn2 "$($e.name): skills/ 下不存在，跳过"
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
        if ($onDisk -notcontains $e.name) {
            $state = '缺失'; $detail = 'registry 有记录但 skills/ 下没有目录'
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

# ---------------------------------------------------------------- 联网对比
foreach ($e in @($entries | Where-Object { $_.origin -eq 'vendored' })) {
    if ($onDisk -notcontains $e.name) { continue }
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
