<#
.SYNOPSIS
  Create a "darkroom" shortcut (pwsh 7 running tools/start.ps1) on the desktop. The .lnk is not kept in git.

.EXAMPLE
  pwsh -File tools/make-shortcut.ps1
  pwsh -File tools/make-shortcut.ps1 -Destination D:\somewhere
#>
param(
    [string]$Destination = [Environment]::GetFolderPath('Desktop'),
    [string]$Name = 'darkroom'
)
$ErrorActionPreference = 'Stop'
$start = Join-Path $PSScriptRoot 'start.ps1'
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwsh) { $pwsh = Join-Path $PSHOME 'pwsh.exe' }
$lnk = Join-Path $Destination "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $pwsh
$s.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$start`""
$s.WorkingDirectory = Split-Path -Parent $PSScriptRoot
$s.Description = 'darkroom 相片編輯器（關閉視窗＝停止）'
$s.Save()
Write-Host "已建立捷徑：$lnk"
