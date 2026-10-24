# prove-it 紀錄：照片編輯競態 P1、P2（修正後）

- 版本：`e4550aa`（分支 `fix/photo-edit-race`；程式修正在 `a35545f`，之後只動 `.claude/`；跑的時候 `darkroom_app/` 沒有未提交改動，工作目錄另有這次新增、尚未提交的 `.claude/prove-it/`）
- 日期：2026-10-24 13:00 前後（+08:00）
- 平台：Windows 11 Pro 10.0.26300；Python 3.13.14（`E:/llm/runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe`）；OpenJDK 25.0.4.1；TLC2 2.19
- 執行步驟：`.claude/prove-it/recipe.md`；功能：`.claude/prove-it/features/photo-edit.md`
- 證據：本檔旁邊的 `e4550aa-photo-edit-race/`
- 對照：修正前的紀錄 `4afcc58-photo-edit-race.md`（同樣的驅動程式、同樣的順序，兩條都證實會掉編輯）

## 要證的主張（完成主張）

- **P1 已修好（規則 R1）**：照 P1 的順序，使用者按「取回上一份」、取回讀完之後 AI 代理經 MCP 存新編輯 B；結果 B 不會被蓋掉，代理收到成功時，B 就是最後的編輯。
- **P2 已修好（規則 R2）**：照 P2 的順序，照片沒有編輯，使用者按「還原成原圖」、清除看到「沒有編輯」之後，AI 代理經 MCP 存編輯 A；結果 A 不會消失，代理收到成功時，A 是目前的編輯或上一份。

## 假說

```
$ hypothesis-status.py --files darkroom_app/services/photo_library.py darkroom_app/adapters/persist/edit_store.py
photo-edit	established	2	a35545f	-
$ hypothesis-status.py --rules photo-edit
R1	safety	held	取回上一份編輯時，絕不蓋掉一份不同的編輯。
R2	safety	held	被清掉的編輯，一定先留成「上一份」。
G1	goal	reached	一張照片可以設定編輯、清除、再取回。
```

假說 photo-edit 第 5 版成立，每條規則都守住，所以照規則：在暫存目錄重跑它的檢查，結果寫在這裡（`hypothesis-check.txt`）：

```
model/PhotoEdit.cfg: states=17837 steps=0 Model checking completed. No error has been found.
model/Goal.cfg: states=358 steps=13 Error: Invariant NeverRestored is violated.        ← G1 走得到（預期）
variants/G1-NoRestore.cfg: states=351 steps=0 Model checking completed. No error has been found.
variants/R1-Unlocked.cfg: states=1174 steps=10 Error: Invariant NoRestoreOverDifferent is violated.  ← 拿掉鎖就抓到（預期）
variants/R2-Unlocked.cfg: states=208 steps=6 Error: Invariant NoLostEdit is violated.               ← 同上
```

假說在它的範圍內（一張照片、兩方、兩份編輯、次數不限）成立；下面的重播證明的是使用者實際會走的那兩條順序。

## 怎麼跑的

```
PY -s .claude/prove-it/tools/photo_edit_race.py --repo D:\Workspace\02_Project\code\darkroom --out <scratch>/pi/e4550aa/P1 --path P1
PY -s .claude/prove-it/tools/photo_edit_race.py --repo D:\Workspace\02_Project\code\darkroom --out <scratch>/pi/e4550aa/P2 --path P2
```

跟修正前完全相同的驅動程式和手段（真的 App HTTP、真的 MCP 行程、CLI 讀回；用 `gated_app.py` 在 App 行程的 `EditStore` 讀取點停下來強制順序；因 `._pth` 問題改用 `run_module.py` 載入模組），細節見修正前紀錄的「怎麼跑的」。P1 的閘門在修正後位於編輯鎖裡面（`read_previous` 在 `restore_edit` 握著編輯鎖的區塊之內，`photo_library.py:385-397`），P2 的閘門位於鎖外「先看在不在」那一步（`EditStore.exists` 回傳 False）。

## 結果

### P1 已修好：證實

時間軸（`P1/transcript.json`，秒）：

```
2.545 PUT /api/edit 200 edit=('p-expo', 130) previous=False          ← 1. 編輯 A
2.567 DELETE /api/edit 200 edit=None previous=True                   ← 2. 清除：A 留成上一份
2.729 App 停在 EditStore.read_previous（握著編輯鎖）                    ← 3、4
2.729 MCP darkroom_edit_set p-strong@70                              ← 5. AI 代理存 B
4.229 1.5 秒內 MCP 沒有回應                                            ← 代理在等鎖，沒有插進去
4.230 放行
4.238 POST /api/edit/restore 200 edit=('p-expo', 130)                ← 6. 取回寫入 A、放開鎖
4.269 MCP 回應 isError=False edit=('p-strong', 70)                    ← 代理拿到鎖後才存 B
4.279 GET /api/edit 200 edit=('p-strong', 70) previous=True
4.503 CLI edit get edit=('p-strong', 70) previous=True
```

編輯檔（`P1/edits-files-after.json`）：`<fp>.json` 是 p-strong@70（B），`<fp>.prev.json` 是 p-expo@130（A），另有 `edits/edits.lock`。代理收到成功，B 就是最後的編輯，A 也還留著，沒有任何一份消失。跟修正前（B 被蓋掉）對照，修正生效。

### P2 已修好：證實

時間軸（`P2/transcript.json`，秒）：

```
2.686 GET /api/edit 200 edit=None previous=False                     ← 1. 沒有編輯
2.712 App 停在 EditStore.exists -> False（清除看到「沒有編輯」）         ← 2
2.712 MCP darkroom_edit_set p-expo@130                               ← 3. AI 代理存 A
2.722 MCP 回應 isError=False edit=('p-expo', 130)
2.723 放行
2.733 DELETE /api/edit 200 edit=None previous=False                  ← 清除：本來就沒東西，什麼都不做
2.736 GET /api/edit 200 edit=('p-expo', 130) previous=False
2.955 CLI edit get edit=('p-expo', 130) previous=False
```

編輯檔（`P2/edits-files-after.json`）：`<fp>.json` 是 p-expo@130（A），另有 `edits/edits.lock`。A 還在。清除回應的 `edit: null` 描述的是它看到的當下（沒有編輯）；事件順序等於「清除先、存檔後」，沒有任何編輯消失。跟修正前（A 被刪掉、沒留上一份）對照，修正生效。

## 沒有涵蓋的

- 只重播了兩條假說路徑，各跑一次（順序是用閘門強制的，所以結果是確定的，不靠運氣）。其他交錯由假說的窮舉涵蓋，沒有在 App 上逐一重播。
- 「照片已經有編輯時，清除握著鎖、代理同時存檔」這個順序沒有在 App 上重播（假說涵蓋，單元測試 `test_previous_is_written_before_the_edit_is_removed` 與 `TestConcurrentClearRestore` 也有）。
- 鎖被握住超過 5 秒時，代理會收到 conflict「照片的編輯正被其他程式修改，請稍後再試」：沒有在 App 上驅動。
- 沒有開瀏覽器點按鈕（主張講的是伺服器行為）。

## 清理

App 與 MCP 都由驅動程式用自己的行程把手停掉，暫存 `run/` 已刪；證據留在 `e4550aa-photo-edit-race/`。

prove-it 完成：2 項證實、0 項推翻、0 項無法到達；紀錄：.claude/prove-it/records/e4550aa-photo-edit-race.md；版本：e4550aa，工作目錄有未提交改動（僅 `.claude/prove-it/`，本次新增）。
