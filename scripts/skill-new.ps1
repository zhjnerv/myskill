<#
.SYNOPSIS
    新建一个自研 skill 的骨架，或把已存在的目录登记进 registry.json。

.PARAMETER Name
    skill 目录名，同时写入 SKILL.md 的 name 字段（保持一致，Claude Code 按目录名发现 skill）。

.PARAMETER Description
    SKILL.md 的 description。这是唯一决定 skill 能否被正确触发的字段，
    要写清楚"什么时候用"和"什么时候不要用"。

.PARAMETER Register
    目录已存在时，只补登记 registry.json，不改动任何文件。

.EXAMPLE
    .\scripts\skill-new.ps1 -Name contract-review -Description "当用户需要审查合同条款风险时使用。不要用于合同起草。"

.EXAMPLE
    # 把手工放进 skills/ 的目录补登记为自研
    .\scripts\skill-new.ps1 -Name my-tool -Register
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$Description = '',
    [switch]$Register
)

. "$PSScriptRoot\_common.ps1"

if ($Name -notmatch '^[a-z0-9]+(-[a-z0-9]+)*$') {
    throw "skill 名必须是小写 kebab-case（如 contract-review），当前：$Name"
}

$skillPath = Get-SkillPath $Name
$registry = Read-Registry

if (Get-SkillEntry -Registry $registry -Name $Name) { throw "registry.json 中已有 $Name" }

if ($Register) {
    if (-not (Test-Path $skillPath)) { throw "skills/$Name 不存在，去掉 -Register 以创建骨架" }
} else {
    if (Test-Path $skillPath) { throw "skills/$Name 已存在，加 -Register 只补登记" }
    New-Item -ItemType Directory -Force -Path $skillPath | Out-Null

    $skillMd = @"
---
name: $Name
description: $Description
---

# $Name

## 何时使用

<!-- 触发场景。写具体的用户措辞和任务形态，不要写"处理相关任务"这种空话。 -->

## 何时不要使用

<!-- 明确排除的场景，防止误触发。 -->

## 工作流程

1.
2.
3.
"@
    $skillMd = $skillMd -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText((Join-Path $skillPath 'SKILL.md'), $skillMd,
                                   (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok "已创建 skills/$Name/SKILL.md"
}

$entry = New-SkillEntry -Name $Name -Origin 'own'
$registry = Set-SkillEntry -Registry $registry -Entry $entry
Write-Registry $registry

Write-Ok "已登记 $Name（origin=own）"
Write-Host "     提交：git add skills/$Name registry.json && git commit -m `"skill: add $Name`"" -ForegroundColor DarkGray
