<#
.SYNOPSIS
  Start the darkroom editor: the preview server on 127.0.0.1 with the darkroom Python, then open the browser.

.DESCRIPTION
  The LocalLLMs checkout (where the darkroom Python and the presets live) comes from the environment variable
  LOCALLLMS_ROOT or from config.local.json at the repo root (keys: localllms_root, preset_dir).
  Closing this window (or Ctrl+C) stops the server.

.EXAMPLE
  pwsh -File tools/start.ps1
  pwsh -File tools/start.ps1 -Port 8800 -NoBrowser
#>
param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [int]$TimeoutSec = 120
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$configFile = Join-Path $repo 'config.local.json'

$root = $env:LOCALLLMS_ROOT
if (-not $root -and (Test-Path $configFile)) {
    $cfg = Get-Content -Raw -Encoding utf8 $configFile | ConvertFrom-Json
    $root = $cfg.localllms_root
}
if (-not $root) {
    Write-Host "darkroom：找不到 LocalLLMs 的位置。請設定環境變數 LOCALLLMS_ROOT，或在 $configFile 寫入 {`"localllms_root`": `"...`"}" -ForegroundColor Red
    exit 2
}
$python = Join-Path $root 'runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe'
if (-not (Test-Path $python)) {
    Write-Host "darkroom：找不到 darkroom 專用 Python：$python" -ForegroundColor Red
    exit 2
}

$url = "http://127.0.0.1:$Port/"
function Test-Ready {
    try { (Invoke-WebRequest -Uri "${url}api/health" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch { $false }
}

if (Test-Ready) {
    Write-Host "darkroom 已經在執行：$url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

$Host.UI.RawUI.WindowTitle = "darkroom（關閉此視窗＝停止）"
$env:PYTHONIOENCODING = 'utf-8'
$proc = Start-Process -FilePath $python -ArgumentList @('-s', '-m', 'darkroom_app', '--port', "$Port") `
    -WorkingDirectory $repo -NoNewWindow -PassThru
try {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (-not (Test-Ready)) {
        if ($proc.HasExited) { Write-Host "darkroom：伺服器啟動失敗（結束碼 $($proc.ExitCode)）" -ForegroundColor Red; exit 1 }
        if ((Get-Date) -gt $deadline) { Write-Host "darkroom：等了 $TimeoutSec 秒伺服器還沒就緒" -ForegroundColor Red; exit 1 }
        Start-Sleep -Milliseconds 300
    }
    if (-not $NoBrowser) { Start-Process $url }
    $proc.WaitForExit()
}
finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}
