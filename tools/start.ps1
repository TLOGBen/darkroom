<#
.SYNOPSIS
  Start the darkroom editor: the preview server on 127.0.0.1 with the darkroom Python, then open the browser.

.DESCRIPTION
  The LocalLLMs checkout (where the darkroom Python and the presets live) comes from the environment variable
  LOCALLLMS_ROOT or from config.local.json at the repo root (keys: localllms_root, preset_dir).
  Closing this window (or Ctrl+C) stops the server.

  The page is the React build in web/dist (plan-v2 §2); the server only serves that build. When web/dist/index.html
  is missing (a fresh checkout), this script first builds it: `npm ci` then `npm run build` in web/ (needs node / npm
  on PATH; the first time takes about 1-3 minutes, mostly downloading the npm packages, later builds ~20 seconds).
  -RebuildWeb forces that build even when web/dist exists (after pulling front-end changes).
  When DARKROOM_WEB_DIST is set the server serves that folder instead, and nothing is built.

.EXAMPLE
  pwsh -File tools/start.ps1
  pwsh -File tools/start.ps1 -Port 8800 -NoBrowser
  pwsh -File tools/start.ps1 -RebuildWeb
#>
param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$RebuildWeb,
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

# The page: build web/dist when it is missing (or -RebuildWeb). Done before the server starts so the first page load
# is the editor, not the server's "not built yet" 503 page.
$webDir = Join-Path $repo 'web'
$webIndex = Join-Path $webDir 'dist/index.html'
if (-not $env:DARKROOM_WEB_DIST -and ($RebuildWeb -or -not (Test-Path $webIndex))) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "darkroom：找不到 npm，沒辦法建置網頁介面（web/dist）。請先安裝 Node.js（含 npm），或在別台電腦建好 web/dist 再複製過來" -ForegroundColor Red
        exit 2
    }
    $why = if ($RebuildWeb) { '依 -RebuildWeb 重新建置' } else { '找不到 web/dist（第一次執行）' }
    Write-Host "darkroom：$why，先建置網頁介面：npm ci → npm run build"
    Write-Host "          第一次約 1～3 分鐘（大部分時間在下載 npm 套件），之後重建約 20 秒；請稍候……"
    $started = Get-Date
    Push-Location $webDir
    try {
        & $npm.Source ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Write-Host "darkroom：npm ci 失敗（結束碼 $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { Write-Host "darkroom：npm run build 失敗（結束碼 $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
    }
    finally { Pop-Location }
    if (-not (Test-Path $webIndex)) {
        Write-Host "darkroom：建置完成但找不到 $webIndex" -ForegroundColor Red
        exit 1
    }
    Write-Host ("darkroom：網頁介面建置完成（{0:N0} 秒）" -f ((Get-Date) - $started).TotalSeconds)
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
