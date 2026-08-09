<#
.SYNOPSIS
    从"我自己的 fork"引入一个外部 skill。

.DESCRIPTION
    本仓库的外部 skill 一律以自己的 fork 为基线，不直接对接原作者仓库。
    给 -Upstream 时脚本会推导出对应的 fork（同名仓库归到你的 GitHub 账号下），
    不存在时可用 -CreateFork 通过 gh 创建。fork 地址与原作者地址都会记进 registry.json：
    fork 用于日常同步与回贡，upstream 只用于 skill-fork-sync.ps1 把 fork 追平原作者。

.PARAMETER Name
    本仓库中的 skill 目录名，落到 skills/<Name>/。

.PARAMETER Upstream
    原作者仓库，如 cat-xierluo/legal-skills 或完整 URL。

.PARAMETER Fork
    显式指定自己的 fork 地址。fork 改过名、或不想按默认推导时用。

.PARAMETER Subpath
    skill 在仓库中的子目录，如 skills/git-workflow。留空表示整个仓库就是这个 skill。
    路径要与仓库里的真实结构一致，可用下面这条确认：
        gh api "repos/<owner>/<repo>/git/trees/HEAD?recursive=1" --jq '.tree[] | select(.path|endswith("SKILL.md")) | .path'

.PARAMETER Branch
    分支，默认 main。

.PARAMETER CreateFork
    fork 不存在时用 gh 自动创建（会在你的 GitHub 账号下新建仓库）。

.EXAMPLE
    # 合集仓库里的一个 skill，fork 已经存在
    .\scripts\skill-vendor.ps1 -Name git-workflow -Upstream cat-xierluo/legal-skills -Subpath skills/git-workflow

.EXAMPLE
    # 整个仓库就是一个 skill，并顺手创建 fork
    .\scripts\skill-vendor.ps1 -Name pdf-tool -Upstream owner/pdf-tool-skill -CreateFork
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$Upstream,
    [string]$Fork,
    [string]$Subpath,
    [string]$Branch = 'main',
    [switch]$CreateFork,
    [string]$Notes = ''
)

. "$PSScriptRoot\_common.ps1"

if (-not $Upstream -and -not $Fork) { throw '至少要给 -Upstream 或 -Fork 其中之一' }

$skillPath = Get-SkillPath $Name
if (Test-Path $skillPath) { throw "skills/$Name 已存在。要重新引入请先删除并提交。" }
Assert-CleanWorktree

$registry = Read-Registry
if (Get-SkillEntry -Registry $registry -Name $Name) {
    throw "registry.json 中已有 $Name，但目录不存在，请先手工清理。"
}

# ------------------------------------------------ 确定 fork 地址
$upstreamRef = $null
if ($Upstream) { $upstreamRef = Resolve-RepoRef $Upstream }

if ($Fork) {
    $forkRef = Resolve-RepoRef $Fork
} else {
    if ($upstreamRef.IsLocal) { throw '本地路径上游必须显式给 -Fork' }
    $me = Get-GhUser
    if (-not $me) { throw "gh 不可用或未登录，无法推导 fork 地址。请显式给 -Fork，或先跑 gh auth login。" }
    $forkRef = Resolve-RepoRef "$me/$($upstreamRef.Repo)"
}

Write-Step "引入 $Name  <-  $($forkRef.Url)$(if ($Subpath) { " :: $Subpath" })"
if ($upstreamRef -and -not $upstreamRef.IsLocal) { Write-Hint "原作者：$($upstreamRef.Url)" }

# ------------------------------------------------ 确保 fork 存在
if (-not $forkRef.IsLocal) {
    if (-not (Test-GhReady)) {
        Write-Warn2 "gh 不可用，跳过 fork 存在性检查。若 $($forkRef.Url) 不存在，下一步克隆会失败。"
    } elseif (-not (Test-GhRepoExists "$($forkRef.Owner)/$($forkRef.Repo)")) {
        if (-not $CreateFork) {
            throw @"
fork 不存在：$($forkRef.Url)
先在 GitHub 上 fork $($upstreamRef.Url)，或加 -CreateFork 让脚本用 gh 创建。
"@
        }
        if (-not $upstreamRef) { throw '要创建 fork 必须同时给 -Upstream' }
        Write-Step "gh repo fork $($upstreamRef.Owner)/$($upstreamRef.Repo)"
        & gh repo fork "$($upstreamRef.Owner)/$($upstreamRef.Repo)" --clone=false
        if ($LASTEXITCODE -ne 0) { throw 'gh repo fork 失败' }
        Write-Ok "已创建 $($forkRef.Url)"
    }
}

# ------------------------------------------------ subtree add
$resolved = Resolve-SkillRef -Url $forkRef.Url -Branch $Branch -Subpath $Subpath -Slug $forkRef.Slug

$prefix = Get-SkillPrefix $Name
Write-Step "git subtree add --prefix $prefix"
# 统一 --squash：上游历史压成一个提交，本仓库不会被几十个来源的完整历史撑爆。
# 代价是后续 pull 也必须一律带 --squash（脚本已保证）。
Invoke-Git @('subtree', 'add', "--prefix=$prefix", $resolved.Mirror, $resolved.Ref, '--squash') | Out-Null

if (-not (Test-Path (Join-Path $skillPath 'SKILL.md'))) {
    Write-Warn2 "skills/$Name 下没有 SKILL.md，确认 -Subpath 是否指对了目录"
}

# ------------------------------------------------ 记录来源
$entry = New-SkillEntry -Name $Name -Origin 'vendored' -Fork $forkRef.Url `
                        -Upstream $(if ($upstreamRef) { $upstreamRef.Url } else { '' }) `
                        -Branch $Branch -Subpath $Subpath -Notes $Notes
$entry.vendoredAt = Get-UtcNow
$entry.lastSync = $entry.vendoredAt
$entry.lastSyncTree = Get-SkillTreeHash $Name

Write-Registry (Set-SkillEntry -Registry $registry -Entry $entry)
Invoke-Git @('add', 'registry.json') | Out-Null
Invoke-Git @('commit', '-m', "registry: vendor $Name from $($forkRef.Display)") | Out-Null

Write-Ok "已引入 skills/$Name"
Write-Hint "改完回贡：scripts\skill-push.ps1 -Name $Name"
Write-Hint "追平原作者：scripts\skill-fork-sync.ps1 -Name $Name"
