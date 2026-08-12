<#
.SYNOPSIS
    清理不在 registry 中的镜像缓存。

.DESCRIPTION
    扫描 %LOCALAPPDATA%\myskill-cache\ 下的镜像目录，删除那些不再被任何
    vendored skill 引用的镜像，释放磁盘空间。

.PARAMETER DryRun
    不删除，只列出可清理的目录。
#>
[CmdletBinding()]
param(
    [switch]$DryRun
)

. "$PSScriptRoot\_common.ps1"

$cache = Get-MirrorCacheRoot
if (-not (Test-Path $cache)) {
    Write-Host '缓存目录不存在，无需清理。' -ForegroundColor Green
    return
}

$registry = Read-Registry
$inUse = @()

# 收集所有仍在使用的镜像 slug
foreach ($e in $registry.skills) {
    if ($e.origin -eq 'vendored' -and $e.fork) {
        $ref = Resolve-RepoRef $e.fork
        if (-not $ref.IsLocal) {
            $inUse += $ref.Slug
        }
    }
}

$allDirs = @(Get-ChildItem -Path $cache -Directory | Select-Object -ExpandProperty Name)
$toRemove = @($allDirs | Where-Object { $inUse -notcontains $_ })

if ($toRemove.Count -eq 0) {
    Write-Host '没有需要清理的镜像。' -ForegroundColor Green
    return
}

Write-Step "发现 $($toRemove.Count) 个不再使用的镜像"

foreach ($dir in $toRemove) {
    $fullPath = Join-Path $cache $dir
    $size = (Get-ChildItem -Path $fullPath -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $sizeMB = [math]::Round($size / 1MB, 2)

    if ($DryRun) {
        Write-Host "  [DryRun] 将删除：$dir (${sizeMB} MB)" -ForegroundColor Yellow
    } else {
        Write-Host "  删除：$dir (${sizeMB} MB)" -ForegroundColor DarkGray
        Remove-Item -Recurse -Force -LiteralPath $fullPath
    }
}

if ($DryRun) {
    Write-Hint "重跑不带 -DryRun 以执行清理"
} else {
    Write-Ok "已清理 $($toRemove.Count) 个镜像"
}
