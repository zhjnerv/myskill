<#
.SYNOPSIS
    把"我的 fork"追平原作者仓库（fork <- upstream）。

.DESCRIPTION
    本仓库的同步源永远是自己的 fork。fork 不主动追平原作者就会烂掉：
    拿不到上游修复，日后开 PR 的 base 也是陈旧的。这个脚本负责那一步。

    按**仓库**去重，不按 skill：一个合集 fork 供 12 个 skill 使用时只同步一次。

    默认要求快进。fork 的默认分支应当始终是原作者分支的镜像——
    你的个性修改由 skill-push.ps1 推到 myskill/<skill> 特性分支，不该落到默认分支上。
    因此快进失败通常意味着有人往 fork 的默认分支直接提交过，需要你确认后再用 -Force。

.PARAMETER Name
    指定某个 skill，同步它所属的 fork。省略则同步全部 vendored skill 涉及的 fork。

.PARAMETER Force
    快进失败时强制把 fork 分支重置成原作者分支（会丢弃 fork 默认分支上的独有提交）。

.PARAMETER DryRun
    只报告两边的差距，不改动 GitHub 上的任何东西。
#>
[CmdletBinding()]
param(
    [string]$Name,
    [switch]$Force,
    [switch]$DryRun
)

. "$PSScriptRoot\_common.ps1"

$registry = Read-Registry
$entries = @($registry.skills | Where-Object { $_.origin -eq 'vendored' })
if ($Name) {
    $entries = @($entries | Where-Object { $_.name -eq $Name })
    if ($entries.Count -eq 0) { throw "registry.json 中没有 vendored skill：$Name" }
}
$entries = @($entries | Where-Object { $_.fork -and $_.upstream })

if ($entries.Count -eq 0) {
    Write-Host '没有同时记录了 fork 与 upstream 的 skill，无需同步。' -ForegroundColor DarkGray
    return
}

# 按 fork+分支去重：一个合集 fork 只处理一次
$jobs = @{}
foreach ($e in $entries) {
    $key = "$($e.fork)#$($e.branch)"
    if (-not $jobs.ContainsKey($key)) {
        $jobs[$key] = [pscustomobject]@{
            Fork     = $e.fork
            Upstream = $e.upstream
            Branch   = $e.branch
            Skills   = @()
        }
    }
    $jobs[$key].Skills += $e.name
}

$ghReady = Test-GhReady
$failed = @()

foreach ($job in $jobs.Values) {
    $forkRef = Resolve-RepoRef $job.Fork
    $upRef = Resolve-RepoRef $job.Upstream
    Write-Step "$($forkRef.Display) [$($job.Branch)]  <-  $($upRef.Display)"
    Write-Hint "涉及 skill：$($job.Skills -join ', ')"

    # 先在本地镜像里量一下差距，DryRun 和实际同步都需要这个信息
    try {
        $mirror = Sync-Mirror -Url $forkRef.Url -Branch $job.Branch -Slug $forkRef.Slug
        Invoke-Git @('remote', 'remove', 'upstream') -WorkDir $mirror -AllowFail | Out-Null
        Invoke-Git @('remote', 'add', 'upstream', $upRef.Url) -WorkDir $mirror | Out-Null
        Invoke-Git @('fetch', '--force', 'upstream', "+refs/heads/$($job.Branch):refs/remotes/upstream/$($job.Branch)") -WorkDir $mirror | Out-Null
    } catch {
        Write-Warn2 "拉取失败：$($_.Exception.Message)"
        $failed += $forkRef.Repo
        continue
    }

    $counts = Invoke-Git @('rev-list', '--left-right', '--count',
                           "origin/$($job.Branch)...upstream/$($job.Branch)") -WorkDir $mirror
    $parts = $counts -split '\s+'
    $ahead = [int]$parts[0]   # fork 独有的提交
    $behind = [int]$parts[1]  # 原作者领先的提交

    if ($behind -eq 0) {
        Write-Ok "已是最新（fork 独有提交 $ahead 个）"
        continue
    }
    Write-Hint "落后原作者 $behind 个提交；fork 默认分支独有 $ahead 个提交"

    if ($DryRun) { continue }

    if ($ahead -gt 0 -and -not $Force) {
        Write-Warn2 "无法快进：fork 的 $($job.Branch) 上有 $ahead 个独有提交"
        Write-Hint '个性修改本该走 skill-push.ps1 推到 myskill/<skill> 特性分支，而不是默认分支。'
        Write-Hint "确认这些提交可以丢弃后，重跑并加 -Force。"
        $failed += $forkRef.Repo
        continue
    }

    if ($ghReady -and -not $forkRef.IsLocal) {
        # gh repo sync 在服务端完成，不需要本地推送
        $args = @('repo', 'sync', "$($forkRef.Owner)/$($forkRef.Repo)",
                  '--source', "$($upRef.Owner)/$($upRef.Repo)", '--branch', $job.Branch)
        if ($Force) { $args += '--force' }
        $out = (& gh @args 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 'gh repo sync 失败'
            Write-Host $out.TrimEnd() -ForegroundColor DarkYellow
            # 上游提交碰了 .github/workflows/ 时，OAuth token 必须带 workflow scope，
            # 否则 GitHub 直接拒绝。这个坑对任何带 Actions 的上游都会复现。
            if ($out -match 'workflow scope|workflow` scope') {
                Write-Hint '这个错误只需授权一次：gh auth refresh -s workflow'
            }
            $failed += $forkRef.Repo
            continue
        }
    } else {
        # 无 gh 时走本地：把 fork 分支推成原作者分支
        $push = @('push', 'origin', "refs/remotes/upstream/$($job.Branch):refs/heads/$($job.Branch)")
        if ($Force) { $push = @('push', '--force-with-lease', 'origin', "refs/remotes/upstream/$($job.Branch):refs/heads/$($job.Branch)") }
        Invoke-Git $push -WorkDir $mirror -AllowFail | Out-Null
        if ($global:LastGitExitCode -ne 0) { Write-Warn2 '推送 fork 失败'; $failed += $forkRef.Repo; continue }
    }

    # 镜像立刻刷新，免得紧接着的 skill-sync 拿到旧状态
    Invoke-Git @('fetch', '--force', 'origin', "+refs/heads/$($job.Branch):refs/remotes/origin/$($job.Branch)") -WorkDir $mirror | Out-Null
    Write-Ok "已追平（+$behind）"
}

if ($failed.Count -gt 0) {
    Write-Warn2 "未完成：$(($failed | Select-Object -Unique) -join ', ')"
    exit 1
}

if (-not $DryRun) { Write-Hint '接着把更新拉进本仓库：scripts\skill-sync.ps1' }
