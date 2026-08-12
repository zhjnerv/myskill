<#
.SYNOPSIS
    把自己 fork 上的内容拉进本仓库（fork -> myskill，git subtree pull）。

.DESCRIPTION
    同步源永远是自己的 fork，不是原作者仓库。想先让 fork 追平原作者，
    要么先跑 skill-fork-sync.ps1，要么给本脚本加 -FromUpstream（内部代跑一次）。

    本仓库对该 skill 有个性修改时，pull 会产生一次 merge，冲突要手工解：
        1. git status                 看冲突文件
        2. 编辑解掉 <<<<<<< 标记
        3. git add <文件> && git commit
        4. 重跑本脚本，刷新 registry.json 的 lastSync

.PARAMETER Name
    指定 skill；省略则同步全部 vendored skill。

.PARAMETER FromUpstream
    先跑 skill-fork-sync.ps1 把 fork 追平原作者，再拉进本仓库。

.PARAMETER DryRun
    只报告 fork 上的最新提交，不做任何合并。
#>
[CmdletBinding()]
param(
    [string]$Name,
    [switch]$FromUpstream,
    [switch]$DryRun
)

. "$PSScriptRoot\_common.ps1"

if ($FromUpstream) {
    $fsArgs = @{}
    if ($Name) { $fsArgs['Name'] = $Name }
    if ($DryRun) { $fsArgs['DryRun'] = $true }
    & "$PSScriptRoot\skill-fork-sync.ps1" @fsArgs
    if ($LASTEXITCODE -ne 0) { throw 'fork 追平原作者未完成，先处理掉再同步' }
    Write-Host ''
}

$registry = Read-Registry
$targets = @($registry.skills | Where-Object { $_.origin -eq 'vendored' })
if ($Name) {
    $targets = @($targets | Where-Object { $_.name -eq $Name })
    if ($targets.Count -eq 0) { throw "registry.json 中没有 vendored skill：$Name" }
}

if ($targets.Count -eq 0) {
    Write-Host '没有需要同步的外部 skill。' -ForegroundColor DarkGray
    return
}

if (-not $DryRun) {
    # 检查是否在继续解决上一次的冲突
    $mergeHeadPath = Join-Path (Get-RepoRoot) '.git\MERGE_HEAD'
    $resumingMerge = $false
    $resumeSkillName = $null

    if (Test-Path $mergeHeadPath) {
        # 检查最近一次 commit 是否是 subtree sync
        $lastMsg = Invoke-Git @('log', '-1', '--format=%s') -AllowFail
        if ($lastMsg -match '^subtree: sync (\S+) from fork$') {
            $resumeSkillName = $Matches[1]
            # 确认冲突已解决（没有 unmerged 文件）
            $unmerged = Invoke-Git @('diff', '--name-only', '--diff-filter=U') -AllowFail
            if (-not $unmerged) {
                $resumingMerge = $true
                Write-Step "检测到正在完成 $resumeSkillName 的冲突解决"
            }
        }
    }

    if (-not $resumingMerge) {
        Assert-CleanWorktree
    }
}

$failed = @()

foreach ($entry in $targets) {
    $n = $entry.name
    $prefix = Get-SkillPrefix $n

    # 如果在恢复模式且当前 skill 不是待恢复的，跳过
    if ($resumingMerge -and $n -ne $resumeSkillName) {
        continue
    }

    # 如果在恢复模式且是待恢复的 skill，直接跳到更新 registry
    if ($resumingMerge -and $n -eq $resumeSkillName) {
        Write-Step "完成 $n 的冲突解决并更新 registry"
        Invoke-Git @('commit', '--no-edit') -AllowFail | Out-Null
        if ($global:LastGitExitCode -ne 0) {
            Write-Warn2 "提交失败，请检查工作区状态"
            $failed += $n
            break
        }
        $newTree = Get-SkillTreeHash $n
        $entry.lastSync = Get-UtcNow
        $entry.lastSyncTree = $newTree
        Write-Registry (Set-SkillEntry -Registry $registry -Entry $entry)
        Invoke-Git @('add', 'registry.json') | Out-Null
        Invoke-Git @('commit', '-m', "registry: sync $n", '--allow-empty') | Out-Null
        Write-Ok "$n 冲突已解决并完成同步"
        continue
    }

    Write-Step "同步 $n  <-  $($entry.fork) [$($entry.branch)]$(if ($entry.subpath) { " :: $($entry.subpath)" })"

    if (-not (Test-Path (Get-SkillPath $n))) {
        Write-Warn2 "skills/$n 不存在，跳过（registry 与磁盘不一致）"
        $failed += $n
        continue
    }

    try {
        $resolved = Resolve-SkillRef -Url $entry.fork -Branch $entry.branch -Subpath $entry.subpath
    } catch {
        Write-Warn2 "获取 fork 失败：$($_.Exception.Message)"
        $failed += $n
        continue
    }

    if ($DryRun) {
        $head = Invoke-Git @('log', '-1', '--format=%h %s (%cr)', $resolved.Ref) -WorkDir $resolved.Mirror
        Write-Hint "fork 最新：$head"
        Write-Hint "上次同步：$($entry.lastSync)"
        continue
    }

    # --squash 必须与 vendor 时一致，否则 subtree 找不到上一次的压缩记录，
    # 会把 fork 的完整历史重放进本仓库
    Invoke-Git @('subtree', 'pull', "--prefix=$prefix", $resolved.Mirror, $resolved.Ref, '--squash',
                 '-m', "subtree: sync $n from fork") -AllowFail | Out-Null

    if ($global:LastGitExitCode -ne 0) {
        $conflicts = Invoke-Git @('diff', '--name-only', '--diff-filter=U') -AllowFail
        Write-Warn2 "$n 同步中断，需要手工处理"
        if ($conflicts) {
            Write-Host '      冲突文件：' -ForegroundColor Yellow
            $conflicts -split "`n" | ForEach-Object { if ($_) { Write-Host "        $_" -ForegroundColor Yellow } }
        }
        Write-Hint '解决后：git add <文件> && git commit，再重跑本脚本刷新 lastSync'
        $failed += $n
        # 工作区已脏，继续处理下一个只会把几个 skill 的冲突搅在一起
        break
    }

    $newTree = Get-SkillTreeHash $n
    $changed = ($newTree -ne $entry.lastSyncTree)

    $entry.lastSync = Get-UtcNow
    $entry.lastSyncTree = $newTree
    Write-Registry (Set-SkillEntry -Registry $registry -Entry $entry)
    Invoke-Git @('add', 'registry.json') | Out-Null
    Invoke-Git @('commit', '-m', "registry: sync $n", '--allow-empty') | Out-Null

    if ($changed) { Write-Ok "$n 已更新" } else { Write-Ok "$n 已是最新" }
}

if ($failed.Count -gt 0) {
    Write-Warn2 "未完成：$($failed -join ', ')"
    exit 1
}
