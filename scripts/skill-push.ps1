<#
.SYNOPSIS
    把本仓库里的个性修改推到自己的 fork（myskill -> fork），准备向原作者提 PR。

.DESCRIPTION
    推的是 fork 上的特性分支（默认 myskill/<Name>），不碰 fork 的默认分支——
    默认分支要留着当原作者的镜像，否则 skill-fork-sync.ps1 就没法快进了。

    按 registry 里的 subpath 分两条路：

    A. subpath 为空（整个仓库就是这个 skill）
       git subtree push，保留提交历史。

    B. subpath 非空（skill 是合集仓库里的一个子目录）
       快照方式：克隆 fork -> 从 upstream 默认分支切出特性分支 ->
       把 skills/<Name>/ 整体覆盖到 <subpath>/ -> 提交推送。
       不保留逐次历史，换来的是目录形状正确、能直接开 PR 的分支。
       subtree push 在这种情形会把 skill 内容推到 fork 的仓库根，形状对不上，PR 没法看。

.PARAMETER Name
    要提 PR 的 skill。

.PARAMETER Branch
    fork 上的特性分支名，默认 myskill/<Name>。

.PARAMETER Message
    快照模式下的提交信息。

.PARAMETER Pr
    推送后用 gh 打开预填好的 PR 页面（浏览器里确认后再提交，不会直接建 PR）。

.PARAMETER Force
    快照模式下允许覆盖 fork 上已存在的同名特性分支。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$Branch,
    [string]$Message,
    [switch]$Pr,
    [switch]$Force
)

. "$PSScriptRoot\_common.ps1"

# ---------------------------------------------------------------- 多机自愈
Repair-SkillSyncState -Silent

$registry = Read-Registry
$entry = Get-SkillEntry -Registry $registry -Name $Name
if (-not $entry) { throw "registry.json 中没有 $Name" }
if ($entry.origin -ne 'vendored') { throw "$Name 是自研 skill，没有可提 PR 的目标" }
if (-not $entry.fork) { throw "registry.json 中 $Name 缺少 fork 地址" }

if (-not $Branch) { $Branch = "myskill/$Name" }
Assert-CleanWorktree

$forkRef = Resolve-RepoRef $entry.fork
$prefix = Get-SkillPrefix $Name

# ---------------------------------------------------------- A. 整仓库即 skill
if (-not $entry.subpath) {
    Write-Step "subtree push $prefix -> $($forkRef.Display) : $Branch"
    Invoke-Git @('subtree', 'push', "--prefix=$prefix", $forkRef.Url, $Branch) | Out-Null
    Write-Ok "已推送到 $Branch"
}
else {
    # ------------------------------------------------------ B. 上游子目录：快照
    Write-Step "快照推送 $Name -> $($forkRef.Display) : $Branch （子目录 $($entry.subpath)）"

    $workDir = Join-Path (Get-MirrorCacheRoot) "push-$($forkRef.Slug)"
    if (-not (Test-Path (Join-Path $workDir '.git'))) {
        if (Test-Path $workDir) { Remove-Item -Recurse -Force -LiteralPath $workDir }
        Invoke-Git @('clone', $forkRef.Url, $workDir) -WorkDir (Get-MirrorCacheRoot) | Out-Null
    }
    Invoke-Git @('remote', 'set-url', 'origin', $forkRef.Url) -WorkDir $workDir | Out-Null

    # 基线取原作者的最新分支（没记 upstream 就退回 fork 的分支），
    # 避免 PR 里混进"fork 落后于原作者"造成的无关 diff
    $baseRemote = 'origin'
    if ($entry.upstream) {
        $upRef = Resolve-RepoRef $entry.upstream
        Invoke-Git @('remote', 'remove', 'upstream') -WorkDir $workDir -AllowFail | Out-Null
        Invoke-Git @('remote', 'add', 'upstream', $upRef.Url) -WorkDir $workDir | Out-Null
        Invoke-Git @('fetch', '--force', 'origin', "+refs/heads/$($entry.branch):refs/remotes/origin/$($entry.branch)") -WorkDir $workDir | Out-Null
        Invoke-Git @('fetch', '--force', 'upstream', "+refs/heads/$($entry.branch):refs/remotes/upstream/$($entry.branch)") -WorkDir $workDir | Out-Null

        # 检查 fork 是否落后 upstream
        $counts = Invoke-Git @('rev-list', '--left-right', '--count',
                               "origin/$($entry.branch)...upstream/$($entry.branch)") -WorkDir $workDir
        $parts = $counts -split '\s+'
        $behind = [int]$parts[1]
        if ($behind -gt 0) {
            Write-Warn2 "fork 落后原作者 $behind 个提交，推送的 PR 会包含大量无关 diff"
            Write-Hint "建议先跑：scripts\skill-fork-sync.ps1 -Name $Name"
            throw "fork 未追平，拒绝推送。追平后重试，或确认要包含这些 diff 后重跑。"
        }
        $baseRemote = 'upstream'
    } else {
        Invoke-Git @('fetch', '--force', $baseRemote, "+refs/heads/$($entry.branch):refs/remotes/$baseRemote/$($entry.branch)") -WorkDir $workDir | Out-Null
    }
    Invoke-Git @('checkout', '-B', $Branch, "$baseRemote/$($entry.branch)") -WorkDir $workDir | Out-Null

    $dest = Join-Path $workDir ($entry.subpath -replace '/', '\')
    if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Force -Path $dest | Out-Null }

    # /MIR 让目标子目录与本地 skill 完全一致（含删除）。该子目录不含 .git，镜像是安全的。
    $rc = Start-Process -FilePath 'robocopy' `
                        -ArgumentList @("`"$(Get-SkillPath $Name)`"", "`"$dest`"", '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP') `
                        -NoNewWindow -Wait -PassThru
    if ($rc.ExitCode -ge 8) { throw "robocopy 失败（exit $($rc.ExitCode)）" }

    if (-not (Invoke-Git @('status', '--porcelain') -WorkDir $workDir)) {
        Write-Ok '与基线无差异，无需提 PR。'
        return
    }

    if (-not $Message) { $Message = "$Name`: sync changes from my skill collection" }
    Invoke-Git @('add', '-A', $entry.subpath) -WorkDir $workDir | Out-Null
    Invoke-Git @('commit', '-m', $Message) -WorkDir $workDir | Out-Null

    $push = if ($Force) { @('push', '--force-with-lease', 'origin', $Branch) } else { @('push', 'origin', $Branch) }
    Invoke-Git $push -WorkDir $workDir -AllowFail | Out-Null
    if ($global:LastGitExitCode -ne 0) {
        throw "推送失败。fork 上可能已有同名分支 $Branch，确认可覆盖后加 -Force 重跑。"
    }

    Write-Ok "已推送到 $Branch"
    Write-Hint '本次改动：'
    Invoke-Git @('show', '--stat', '--oneline', 'HEAD') -WorkDir $workDir | Write-Host
}

# ---------------------------------------------------------- PR
if (-not $Pr) {
    Write-Hint "开 PR：重跑并加 -Pr，或直接去 $($forkRef.Url)/tree/$Branch"
    return
}
if (-not $entry.upstream) { Write-Warn2 'registry 里没有 upstream，无法确定 PR 的目标仓库'; return }
if (-not (Test-GhReady)) { Write-Warn2 'gh 不可用，请手工开 PR'; return }

$upRef = Resolve-RepoRef $entry.upstream
Write-Step "打开 PR 草稿页（浏览器里确认后再提交）"
# 用 --web：PR 是发到别人仓库的对外动作，预填好让你过目，不在命令行里直接建
& gh pr create --repo "$($upRef.Owner)/$($upRef.Repo)" `
               --head "$($forkRef.Owner):$Branch" --base $entry.branch --web
