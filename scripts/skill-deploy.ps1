<#
.SYNOPSIS
    把本仓库的 skills/ 部署到 Agent 的 skills 目录（默认 ~\.claude\skills）。

.DESCRIPTION
    用 NTFS 目录联接（junction）而不是复制：
    - junction 在 Windows 上不需要管理员权限，符号链接需要（本机未开开发者模式）；
    - 部署后编辑仓库里的文件即时生效，不存在"改了源没同步到 Agent"的问题；
    - 单一事实来源仍是本仓库，Agent 目录只是入口。

    本仓库位于 Google Drive 同步目录，junction 建在 .claude 下指向 D 盘本地路径，
    Drive 不会看到 junction 本身，不会产生同步冲突。

.PARAMETER TargetRoot
    目标 skills 目录，默认 $env:USERPROFILE\.claude\skills。
    部署到其他 Agent 就换路径，例如 $env:USERPROFILE\.codex\skills。

.PARAMETER Name
    只部署指定 skill。

.PARAMETER Force
    目标已存在且不是指向本仓库时，允许替换（实体目录会先带时间戳备份）。

.PARAMETER Prune
    删除目标目录中指向本仓库、但本仓库已不再有对应 skill 的残留 junction。

.PARAMETER DryRun
    只打印将要执行的操作。
#>
[CmdletBinding()]
param(
    [string]$TargetRoot = (Join-Path $env:USERPROFILE '.claude\skills'),
    [string]$Name,
    [switch]$Force,
    [switch]$Prune,
    [switch]$DryRun
)

. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-RepoRoot
$skillsDir = Join-Path $repoRoot 'skills'
if (-not (Test-Path $skillsDir)) { throw "skills/ 不存在：$skillsDir" }

if (-not (Test-Path $TargetRoot)) {
    if ($DryRun) { Write-Host "[dry-run] 创建 $TargetRoot" }
    else { New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null }
}

function Get-LinkTarget {
    <# PS 5.1 用 .Target（数组），PS 6+ 用 .LinkTarget，这里统一取字符串 #>
    param([Parameter(Mandatory)]$Item)
    if ($Item.PSObject.Properties.Name -contains 'LinkTarget' -and $Item.LinkTarget) { return $Item.LinkTarget }
    if ($Item.PSObject.Properties.Name -contains 'Target' -and $Item.Target) { return @($Item.Target)[0] }
    return $null
}

function Test-IsReparse {
    param([Parameter(Mandatory)]$Item)
    return (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}

$sources = @(Get-ChildItem -Path $skillsDir -Directory)
if ($Name) { $sources = @($sources | Where-Object { $_.Name -eq $Name }) }
# 只有 -Prune 时允许没有可部署项：删光 skill 后仍然要能清理残留链接
if ($sources.Count -eq 0 -and -not $Prune) { throw "没有可部署的 skill$(if ($Name) { "：$Name" })" }

if ($sources.Count -gt 0) { Write-Step "部署 $($sources.Count) 个 skill -> $TargetRoot" }

foreach ($src in $sources) {
    $link = Join-Path $TargetRoot $src.Name

    if (Test-Path -LiteralPath $link) {
        $item = Get-Item -LiteralPath $link -Force
        if (Test-IsReparse $item) {
            $current = Get-LinkTarget $item
            if ($current -and ($current.TrimEnd('\') -ieq $src.FullName.TrimEnd('\'))) {
                Write-Host "  --  $($src.Name) 已就位" -ForegroundColor DarkGray
                continue
            }
            if (-not $Force) {
                Write-Warn2 "$($src.Name) 已链接到 $current，加 -Force 才会替换"
                continue
            }
            if ($DryRun) { Write-Host "[dry-run] 移除旧链接 $link （原指向 $current）" }
            else { (Get-Item -LiteralPath $link -Force).Delete() }
        } else {
            if (-not $Force) {
                Write-Warn2 "$($src.Name) 目标是实体目录，加 -Force 才会备份并替换"
                continue
            }
            $backup = "$link.bak-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
            if ($DryRun) { Write-Host "[dry-run] 备份实体目录 $link -> $backup" }
            else { Move-Item -LiteralPath $link -Destination $backup }
            Write-Warn2 "$($src.Name) 原实体目录已备份到 $backup"
        }
    }

    if ($DryRun) { Write-Host "[dry-run] junction $link -> $($src.FullName)"; continue }
    New-Item -ItemType Junction -Path $link -Value $src.FullName | Out-Null
    Write-Ok "$($src.Name)"
}

if (-not $Prune) { return }

Write-Step '清理指向本仓库的失效链接'
foreach ($item in (Get-ChildItem -Path $TargetRoot -Force)) {
    if (-not (Test-IsReparse $item)) { continue }
    $t = Get-LinkTarget $item
    if (-not $t) { continue }
    # 只动指向本仓库 skills/ 的链接，别人的链接一概不碰
    if ($t -notlike "$skillsDir*") { continue }
    if (Test-Path -LiteralPath $t) { continue }
    if ($DryRun) { Write-Host "[dry-run] 删除失效链接 $($item.FullName) -> $t" }
    else { $item.Delete(); Write-Ok "已删除失效链接 $($item.Name)" }
}
