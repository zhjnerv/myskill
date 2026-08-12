# _common.ps1 —— 所有 skill-*.ps1 共用的基础函数
# 用法：. "$PSScriptRoot\_common.ps1"

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 路径与仓库

function Get-RepoRoot {
    <#
      .SYNOPSIS 返回本仓库根目录（scripts/ 的上一级）。
      不依赖 git rev-parse，避免 git 状态异常时连路径都取不到。
    #>
    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Get-SkillPath {
    param([Parameter(Mandatory)][string]$Name)
    return (Join-Path (Join-Path (Get-RepoRoot) 'skills') $Name)
}

function Get-SkillPrefix {
    <# git subtree --prefix 必须是相对仓库根的正斜杠路径 #>
    param([Parameter(Mandatory)][string]$Name)
    return "skills/$Name"
}

function Get-MirrorCacheRoot {
    <#
      .SYNOPSIS fork 镜像克隆的存放根目录。
      刻意放在仓库外（%LOCALAPPDATA%），避免镜像克隆被纳入版本控制。
      确保目录存在后再返回。
    #>
    $cache = if ($env:MYSKILL_CACHE) { $env:MYSKILL_CACHE } else { (Join-Path $env:LOCALAPPDATA 'myskill-cache') }
    if (-not (Test-Path $cache)) { New-Item -ItemType Directory -Force -Path $cache | Out-Null }
    return $cache
}

# ---------------------------------------------------------------- git 封装

function Invoke-Git {
    <#
      .SYNOPSIS 执行 git，非零退出即抛异常。
      .PARAMETER AllowFail 为真时不抛异常，由调用方检查 $global:LastGitExitCode
    #>
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$WorkDir,
        [switch]$AllowFail
    )
    if (-not $WorkDir) { $WorkDir = Get-RepoRoot }
    Push-Location $WorkDir
    try {
        $output = & git @Arguments 2>&1 | Out-String
        $global:LastGitExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($global:LastGitExitCode -ne 0 -and -not $AllowFail) {
        throw "git $($Arguments -join ' ') 失败（exit $global:LastGitExitCode）：`n$output"
    }
    return $output.TrimEnd()
}

function Assert-CleanWorktree {
    <#
      subtree add/pull 会产生 merge 提交。工作区脏的时候一旦冲突，
      分不清哪些改动是这次合并带来的，现场就废了。
    #>
    $status = Invoke-Git @('status', '--porcelain')
    if ($status) { throw "工作区有未提交改动，请先提交或 stash：`n$status" }
}

function Get-SkillTreeHash {
    <#
      .SYNOPSIS HEAD 中 skills/<Name> 的 tree 哈希。
      判断"上次同步之后有没有被本地改过"的离线依据。
    #>
    param([Parameter(Mandatory)][string]$Name)
    $out = Invoke-Git @('rev-parse', "HEAD:$(Get-SkillPrefix $Name)") -AllowFail
    if ($global:LastGitExitCode -ne 0) { return $null }
    return $out.Trim()
}

# ---------------------------------------------------------------- 仓库地址

function Resolve-RepoRef {
    <#
      .SYNOPSIS 把各种写法的 GitHub 仓库地址统一成 Owner / Repo / Url / Slug。
      支持 owner/repo、https://github.com/owner/repo[.git]、git@github.com:owner/repo.git，
      以及本地路径（自测用）。
    #>
    param([Parameter(Mandatory)][string]$Ref)

    if ($Ref -match '^[A-Za-z]:[\\/]' -or $Ref -match '^[\\/]{2}') {
        $leaf = (Split-Path $Ref -Leaf) -replace '\.git$', ''
        return @{ Owner = ''; Repo = $leaf; Url = $Ref; Slug = "local-$leaf"; Display = $leaf; IsLocal = $true }
    }

    $owner = ''; $repo = ''
    if ($Ref -match '^git@[^:]+:(?<o>[^/]+)/(?<r>[^/]+?)(\.git)?$') { $owner = $Matches['o']; $repo = $Matches['r'] }
    elseif ($Ref -match '^(https?://)?[^/]*github\.com/(?<o>[^/]+)/(?<r>[^/]+?)(\.git)?/?$') { $owner = $Matches['o']; $repo = $Matches['r'] }
    elseif ($Ref -match '^(?<o>[A-Za-z0-9._-]+)/(?<r>[A-Za-z0-9._-]+)$') { $owner = $Matches['o']; $repo = $Matches['r'] }
    else { throw "无法解析仓库地址：$Ref" }

    return @{
        Owner   = $owner
        Repo    = $repo
        Url     = "https://github.com/$owner/$repo"
        Slug    = "$owner-$repo"
        Display = "$owner/$repo"
        IsLocal = $false
    }
}

# ---------------------------------------------------------------- 镜像与 split

function Sync-Mirror {
    <#
      .SYNOPSIS 确保 <cache>/<Slug> 是该仓库的本地克隆并把指定分支拉到最新。

      按**仓库**而非 skill 命名：一个 fork 往往是包含几十个 skill 的合集，
      12 个 skill 引自同一个 fork 时只该有一份克隆。
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Branch,
        [string]$Slug
    )
    if (-not $Slug) { $Slug = (Resolve-RepoRef $Url).Slug }
    $cache = Get-MirrorCacheRoot

    $mirror = Join-Path $cache $Slug
    if (-not (Test-Path (Join-Path $mirror '.git'))) {
        Write-Host "[镜像] 克隆 $Url" -ForegroundColor DarkGray
        # 完整克隆：subtree split 需要完整历史和 tree 对象，浅克隆会中途失败
        Invoke-Git @('clone', $Url, $mirror) -WorkDir $cache | Out-Null
    }
    Invoke-Git @('remote', 'set-url', 'origin', $Url) -WorkDir $mirror | Out-Null

    # refspec 必须全限定。写成简写 `+main:refs/remotes/origin/main` 时 git 无法把
    # 简写映射回远端命名空间，配 --prune 会把 refs/remotes/origin/main 判成 stale 删掉。
    Invoke-Git @('fetch', '--force', 'origin', "+refs/heads/${Branch}:refs/remotes/origin/$Branch") -WorkDir $mirror | Out-Null
    return $mirror
}

function Resolve-SkillRef {
    <#
      .SYNOPSIS 返回可供 subtree add/pull 使用的 (Mirror, Ref)，Ref 的根一定就是 skill 根。

      Subpath 为空 → 整个仓库就是这个 skill，直接用分支。
      Subpath 非空 → 上游是合集仓库。必须先 `git subtree split --prefix=<subpath>`
      把该子目录的历史抽成独立分支，否则 subtree add 会把整个合集拖进来。
      split 是确定性的：上游有新提交时重跑只在同一分支上追加，因此可以反复 pull。
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Branch,
        [string]$Subpath,
        [string]$Slug,
        [switch]$Verify  # 验证 SKILL.md 是否在 split 后的根目录
    )
    $mirror = Sync-Mirror -Url $Url -Branch $Branch -Slug $Slug

    if (-not $Subpath) {
        # 落成本地分支：git fetch <path> <ref> 对 refs/heads/* 的解析最稳
        $track = "myskill/track/$Branch"
        Invoke-Git @('branch', '-f', $track, "origin/$Branch") -WorkDir $mirror | Out-Null
        return @{ Mirror = $mirror; Ref = $track }
    }

    # 分支名用 subpath 的 hash 避免冲突（skills/foo-bar 和 skills/foo/bar 都会映射成 skills-foo-bar）
    $hash = [System.BitConverter]::ToString(
        [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Subpath))
    ).Replace('-','').Substring(0, 8).ToLower()
    $split = "myskill/split/$hash"
    Write-Host "[镜像] split $Subpath -> $split" -ForegroundColor DarkGray
    # 分支已存在且可快进时 split 会自动更新；上游 force-push 过历史时会因
    # "不是祖先"失败，此时删掉重建（结果等价，只丢弃本地缓存分支）
    Invoke-Git @('subtree', 'split', "--prefix=$Subpath", '-b', $split, "origin/$Branch") -WorkDir $mirror -AllowFail | Out-Null
    if ($global:LastGitExitCode -ne 0) {
        Invoke-Git @('branch', '-D', $split) -WorkDir $mirror -AllowFail | Out-Null
        Invoke-Git @('subtree', 'split', "--prefix=$Subpath", '-b', $split, "origin/$Branch") -WorkDir $mirror | Out-Null
    }

    # 验证 SKILL.md 是否在 split 后的根目录
    if ($Verify) {
        $hasSkillMd = Invoke-Git @('ls-tree', '--name-only', $split) -WorkDir $mirror -AllowFail
        if ($hasSkillMd -notmatch '(?m)^SKILL\.md$') {
            throw "split 后的分支根目录下没有 SKILL.md。请检查 -Subpath 是否正确。`n可用此命令查看正确路径：`n  gh api `"repos/<owner>/<repo>/git/trees/HEAD?recursive=1`" --jq '.tree[] | select(.path|endswith(`"SKILL.md`")) | .path'"
        }
    }

    return @{ Mirror = $mirror; Ref = $split }
}

# ---------------------------------------------------------------- gh

function Test-GhReady {
    <# gh 存在且已登录才算可用；否则所有 gh 相关能力降级为手工提示 #>
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { return $false }
    & gh auth status *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-GhUser {
    if (-not (Test-GhReady)) { return $null }
    $u = (& gh api user --jq .login 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    return $u.Trim()
}

function Test-GhRepoExists {
    param([Parameter(Mandatory)][string]$OwnerRepo)
    & gh repo view $OwnerRepo *> $null
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------- registry

function Get-RegistryPath { return (Join-Path (Get-RepoRoot) 'registry.json') }

function Read-Registry {
    $path = Get-RegistryPath
    if (-not (Test-Path $path)) { return [ordered]@{ version = 2; skills = @() } }
    $obj = (Get-Content -Path $path -Raw -Encoding UTF8) | ConvertFrom-Json
    $skills = @()
    if ($obj.PSObject.Properties.Name -contains 'skills' -and $null -ne $obj.skills) { $skills = @($obj.skills) }

    # ConvertFrom-Json 会把 ISO 8601 字符串自动识别成 [DateTime]。不还原成字符串有两个后果：
    # 调用方按字符串用（.Substring）时抛异常；写回时 ConvertTo-Json 换一种格式序列化，
    # registry.json 每次提交都出现伪 diff。
    foreach ($s in $skills) {
        foreach ($f in @('vendoredAt', 'lastSync')) {
            if ($s.PSObject.Properties.Name -contains $f -and $s.$f -is [datetime]) {
                $s.$f = ([datetime]$s.$f).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            }
        }
    }
    return [ordered]@{ version = $obj.version; skills = $skills }
}

function Write-Registry {
    param([Parameter(Mandatory)]$Registry)
    # 按名称排序：避免多台机器写入顺序不同造成的伪 diff
    $out = [ordered]@{ version = $Registry.version; skills = @($Registry.skills | Sort-Object -Property name) }
    $json = ($out | ConvertTo-Json -Depth 12) -replace "`r`n", "`n"
    if (-not $json.EndsWith("`n")) { $json += "`n" }
    [System.IO.File]::WriteAllText((Get-RegistryPath), $json, (New-Object System.Text.UTF8Encoding($false)))
}

function New-SkillEntry {
    <#
      统一字段顺序，保证 registry.json 的 diff 可读。

      fork 是主 remote：引入、同步、回贡全部走它。
      upstream 只用于把 fork 追平原作者（skill-fork-sync.ps1），不作为同步源——
      这样 fork 的默认分支永远是 upstream 的镜像，能一直快进。
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('own', 'vendored')][string]$Origin,
        [string]$Fork, [string]$Upstream, [string]$Branch, [string]$Subpath,
        [string]$Notes = ''
    )
    return [ordered]@{
        name         = $Name
        origin       = $Origin
        fork         = $(if ($Fork) { $Fork } else { $null })
        upstream     = $(if ($Upstream) { $Upstream } else { $null })
        branch       = $(if ($Branch) { $Branch } else { $null })
        subpath      = $(if ($Subpath) { $Subpath } else { $null })
        vendoredAt   = $null
        lastSync     = $null
        lastSyncTree = $null
        notes        = $Notes
    }
}

function Get-SkillEntry {
    param([Parameter(Mandatory)]$Registry, [Parameter(Mandatory)][string]$Name)
    return ($Registry.skills | Where-Object { $_.name -eq $Name } | Select-Object -First 1)
}

function Set-SkillEntry {
    param([Parameter(Mandatory)]$Registry, [Parameter(Mandatory)]$Entry)
    $n = $Entry.name
    $Registry.skills = @(@($Registry.skills | Where-Object { $_.name -ne $n }) + @($Entry))
    return $Registry
}

function Get-UtcNow { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

# ---------------------------------------------------------------- 输出

function Write-Step  { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Message) Write-Host "  OK  $Message" -ForegroundColor Green }
function Write-Warn2 { param([string]$Message) Write-Host "  !!  $Message" -ForegroundColor Yellow }
function Write-Hint  { param([string]$Message) Write-Host "      $Message" -ForegroundColor DarkGray }
