---
name: darkroom-start
description: 啟動、停止、健康檢查 darkroom 的本機 Web App，換埠、指定 --preset-dir／--data-dir。使用者說「啟動 darkroom」「開 darkroom」「打開修圖」「darkroom 關掉」「停止 darkroom」「darkroom 還活著嗎」「換個埠」「start darkroom」「run darkroom」「stop darkroom」「darkroom health」「darkroom port」時用。裝都還沒裝的話先用 darkroom-setup。
---

# darkroom-start

## 什麼時候用

使用者要開 darkroom 的瀏覽器介面、要關掉它、想知道它有沒有在跑、要用別的埠或別的 preset／資料夾跑一次。
還沒安裝（沒有 `.venv` 或還沒設 preset 資料夾）→ 先走 `darkroom-setup`。

**安裝檔版**（桌面 App）：使用者直接開 darkroom App，App 自己起後端（空埠、只綁 127.0.0.1）並在關閉時收掉，你不用也不要另外啟動。要在瀏覽器裡用同一套就 `darkroom app --port 8799`（參數同下面的 `python -s -m darkroom_app`）。

## 安全規則

- 只綁 `127.0.0.1`。不要改成 `0.0.0.0`、不要加代理、不要開防火牆、不要用 80 埠。
- 瀏覽器一律開 `http://127.0.0.1:<埠>/`；其他主機名會被伺服器拒絕（421／403）。
- 使用者沒說要一直開著，任務結束就關掉。
- `--data-dir` 不要指到照片資料夾或 preset 資料夾裡面。

## 指令（`python` ＝ repo 的 Python，一般使用者是 `.\.venv\Scripts\python.exe`；在 repo 根目錄執行）

```powershell
# 啟動：前景執行，就緒時 stdout 印「darkroom 已啟動：http://127.0.0.1:8765/」；Ctrl+C 或關視窗停止
python -s -m darkroom_app

# 換埠
python -s -m darkroom_app --port 8799

# 這一次用別的 preset 資料夾／照片庫資料夾（不改 config.local.json）
python -s -m darkroom_app --preset-dir D:/Presets/xmp --data-dir D:/darkroom-data

# 健康檢查：200 且內容 {"ok": true} 就是活著
Invoke-WebRequest http://127.0.0.1:8765/api/health -UseBasicParsing
```

`--help` 只有這三個選項：`--port`、`--preset-dir`、`--data-dir`。

原始碼版的頁面是 `web/` 的建置結果：沒有 `web/dist` 時伺服器照樣起來、API 能用，但頁面回 HTTP 503「網頁介面還沒建置」。先建一次：`cd web; npm ci; npm run build`（第一次 1～3 分鐘），拉到前端更新後再建。
設定錯誤（找不到 preset 資料夾）會印 `darkroom：…` 並以結束碼 2 退出；埠被占用是 `darkroom：無法啟動伺服器：…`，結束碼 1 → 換埠。

作者環境另有 `pwsh -File tools/start.ps1 [-Port N] [-NoBrowser] [-RebuildWeb] [-TimeoutSec N]`：從 `config.local.json` 的 `localllms_root` 找專用 Python、沒有 `web/dist` 時先 `npm ci`＋`npm run build`（`-RebuildWeb` 強制重建）、等 `/api/health` 回 200 再開瀏覽器；已經在跑就只開瀏覽器。一般使用者（venv）不用它。

## 建議流程（代理代為啟動時）

1. 先健康檢查：已經活著就不要再開第二個（同一埠會起不來）。
2. 在背景啟動（PowerShell：`Start-Process` 並把 stdout／stderr 導到暫存檔，或工具的背景執行），**不要**用會卡住前景的方式等它。
3. 輪詢 `/api/health`，最多等 90 秒左右（第一次要暖機 GPU）；成功再把網址給使用者或開瀏覽器。
4. 失敗：把 stderr 原文給使用者看。常見是 preset 資料夾沒設對（→ `darkroom-setup`）或埠被占用（→ 換埠）。
5. 停止：結束那個 Python 行程（Ctrl+C／關視窗／`Stop-Process -Id <pid>`），再健康檢查確認已經連不上。沒有「停止指令」或 API。

## 要先問使用者的時機

- 他沒說埠、沒說要不要開瀏覽器：用預設 8765、啟動後告訴他網址即可，不用問。
- 要用非設定檔的 preset 資料夾或 `data_dir` 跑：先確認那個路徑是他要的。
- 任務結束要不要關掉：他沒交代就關；他說「開著」就留著並告訴他怎麼關。

## 同時使用

設定（`settings set`，見 `darkroom-setup`）改了不用重開：App 下一個請求就用新設定。
App 跑著的時候 CLI／MCP 可以照常用（`darkroom-edit`、`darkroom-presets`）：preset 庫索引有跨程序鎖、照片庫以內容指紋對應，不會互相蓋掉；App 下一次列 preset 就會看到 CLI 匯入或另存的新 preset。
