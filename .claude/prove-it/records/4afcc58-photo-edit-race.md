# prove-it 紀錄：照片編輯競態 P1、P2（修正前）

- 版本：`4afcc58`（git worktree，`darkroom_app/` 與 `e4ebbb5` 完全相同、沒有未提交改動）
- 日期：2026-10-24 13:00 前後（+08:00）
- 平台：Windows 11 Pro 10.0.26300；Python 3.13.14（`E:/llm/runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe`）；OpenJDK 25.0.4.1；TLC2 2.19
- 執行步驟：`.claude/prove-it/recipe.md`；功能：`.claude/prove-it/features/photo-edit.md`
- 證據：本檔旁邊的 `4afcc58-photo-edit-race/`

## 要證的主張（問題主張）

- **P1（規則 R1）**：使用者在 App 按「取回上一份」，取回讀完目前和上一份編輯、還沒寫入的這段時間裡，AI 代理經 MCP 存了一份新編輯 B 並收到「已存」；取回照樣寫入上一份 A，B 從此消失。
- **P2（規則 R2）**：照片沒有編輯，使用者在 App 按「還原成原圖」，清除讀到「沒有編輯」之後，AI 代理經 MCP 存了編輯 A 並收到「已存」；清除照樣刪檔，A 消失，也沒有留成上一份。

## 假說

```
$ hypothesis-status.py --files darkroom_app/services/photo_library.py darkroom_app/adapters/persist/edit_store.py
photo-edit	established	2	4afcc58	violated: R1; violated: R2
```

假說 photo-edit 第 4 版（同步點 4afcc58）成立，R1、R2 被打破，所以照規則：重跑檢查，並在真的 App 上照路徑強制順序重播。

- 重跑檢查（第 4 版複製到暫存目錄，結果見 `hypothesis-check.txt`）：R2 在 6 步內被打破（208 個狀態），R1 單獨檢查時在 10 步內被打破（1,174 個狀態），加鎖對照組守住（15 個狀態）。與發布時的 `check.txt` 一致。
- 狀態指令完整輸出：`hypothesis-status.txt`。

## 怎麼跑的

```
PY -s .claude/prove-it/tools/photo_edit_race.py --repo <scratch>/wt-4afcc58 --out <scratch>/pi/4afcc58/P1 --path P1
PY -s .claude/prove-it/tools/photo_edit_race.py --repo <scratch>/wt-4afcc58 --out <scratch>/pi/4afcc58/P2 --path P2
```

- App：真的 `darkroom_app.__main__`（aiohttp，127.0.0.1 隨機埠），由 `gated_app.py` 啟動，`--preset-dir`／`--data-dir` 指向這次的暫存資料夾。請求走跟頁面按鈕一樣的路由（`web/src/requests/edits.ts`：`PUT /api/edit`、`DELETE /api/edit`、`POST /api/edit/restore`），帶 `X-Darkroom: 1`。
- AI 代理：真的 MCP stdio server（`darkroom_app.mcp_server`，另一個行程），先 `initialize`，再用唯讀的 `darkroom_edit_get` 暖機，然後 `tools/call darkroom_edit_set`。
- 讀回：App 的 `GET /api/edit`、第三個行程的 CLI `edit get --json`、`<data>/edits/` 底下的檔案。
- **強制順序用的手段**：`gated_app.py` 在 App 行程裡包住 `EditStore.read_previous`（P1）與 `EditStore.read` 回傳 None／`EditStore.exists` 回傳 False（P2），在讀完之後停下來，等驅動程式放行。讀的結果原樣傳回，其他程式碼都沒動；AI 代理的行程完全沒有改動。只有靠這個手段才排得出這個順序，因為兩者之間只差幾毫秒。
- **偏離使用者路徑的地方**：這台的專用 Python 的 `python313._pth` 把 import 路徑寫死成已經不存在的 `D:/Code/darkroom`，`python -s -m darkroom_app…` 從 repo 根目錄跑會 `No module named darkroom_app`。所以三個行程都透過 `run_module.py`／`gated_app.py`，把 checkout 放到 `sys.path` 第一個，再照 `-m` 的方式執行同一個模組。
- 沒有開瀏覽器點按鈕：這兩條主張講的是伺服器怎麼處理請求，不是畫面怎麼顯示。

## 結果

### P1：證實

時間軸（`P1/transcript.json`，秒）：

```
2.951 PUT /api/edit 200 edit=('p-expo', 130) previous=False         ← 1. 編輯 A
2.987 DELETE /api/edit 200 edit=None previous=True                   ← 2. 清除：A 留成上一份
3.223 App 停在 EditStore.read_previous（取回已讀到「沒有編輯」與「上一份是 A」）← 3、4
3.223 MCP darkroom_edit_set p-strong@70                              ← 5. AI 代理存 B
3.233 MCP 回應 isError=False edit=('p-strong', 70)                    ← 代理被告知 B 已存
3.234 放行
3.249 POST /api/edit/restore 200 edit=('p-expo', 130)                ← 6. 取回照樣寫入 A
3.253 GET /api/edit 200 edit=('p-expo', 130)
3.564 CLI edit get edit=('p-expo', 130) previous=True
```

編輯檔（`P1/edits-files-after.json`）：`<fp>.json` 是 p-expo@130，`<fp>.prev.json` 也是 p-expo@130。B（p-strong@70）在哪裡都找不到，而 AI 代理收到的是成功回應。主張的錯誤結果完整重現。

### P2：證實

時間軸（`P2/transcript.json`，秒）：

```
3.103 GET /api/edit 200 edit=None previous=False                     ← 1. 沒有編輯
3.123 App 停在 EditStore.read -> None（清除已讀到「沒有編輯」）          ← 2
3.123 MCP darkroom_edit_set p-expo@130                               ← 3. AI 代理存 A
3.143 MCP 回應 isError=False edit=('p-expo', 130)                     ← 代理被告知 A 已存
3.144 放行
3.155 DELETE /api/edit 200 edit=None previous=False                  ← 4–6. 清除照樣刪檔
3.158 GET /api/edit 200 edit=None previous=False
3.461 CLI edit get edit=None previous=False
```

編輯檔（`P2/edits-files-after.json`）：`{}`，`edits/` 底下什麼都沒有。A 被刪掉，也沒有 `.prev.json`，「取回上一份」救不回來。主張的錯誤結果完整重現。

## 清理

App 與 MCP 都由驅動程式用自己啟動時拿到的行程把手停掉（App terminate 結束碼 1、MCP 關 stdin 後結束碼 0），每次的暫存 `run/` 資料夾已刪；worktree 在紀錄完成後移除。證據留在 `4afcc58-photo-edit-race/`。

prove-it 完成：2 項證實、0 項推翻、0 項無法到達；紀錄：.claude/prove-it/records/4afcc58-photo-edit-race.md；版本：4afcc58。
