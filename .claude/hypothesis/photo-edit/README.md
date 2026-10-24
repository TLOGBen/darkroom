# 假說：一張照片的編輯、清除、取回上一份

> 狀態以這行指令為準，不以本頁為準：`python3 D:\Workspace\01_Plugin\baransu\plugins\baransu\skills\hypothesis\scripts\hypothesis-status.py --area photo-edit`

## 一句話

同一張照片同時被 App 和 AI 代理操作時，清除與取回都不能讓任何一份編輯消失；現行程式兩條都做不到。

## 規則

| # | 種類 | 規則 | 出處 | 發布時 |
|---|---|---|---|---|
| R1 | 安全 | 取回上一份編輯時，絕不蓋掉一份不同的編輯。 | `darkroom_app/services/photo_library.py:371-372`（S4a） | 被打破（P1） |
| R2 | 安全 | 被清掉的編輯，一定先留成「上一份」。 | `darkroom_app/adapters/persist/edit_store.py:97`（S4） | 被打破（P2） |
| G1 | 目標 | 一張照片可以設定編輯、清除、再取回。 | `photo_library.py:351`、`:354-360`、`:362-377` | 走得到 |

規則依據程式自己寫下的兩條承諾（S4、S4a）挑選，使用者已於 2026-10-24 逐條確認 R1、R2、G1。

## 找到的問題

**P1　取回上一份時，蓋掉了 AI 代理剛存的新編輯。** 你在 App 按「取回上一份」的同時，AI 代理剛好存了一份新的編輯，取回照樣寫進去，新編輯消失，哪裡都沒有備份。
細節：`restore_edit` 在 `:366` 讀目前編輯、`:373-376` 比對後寫入，中間沒有重讀也沒有鎖。劇本：[paths/P1.md](paths/P1.md)。

**P2　清除編輯時，把 AI 代理剛存的編輯刪掉，連「上一份」都沒留。** 你按「清除編輯」的同時，AI 代理存了一份編輯，清除照樣刪檔，但它先前讀到的是「沒有編輯」，所以什麼都沒留下。
細節：`clear_edit` 在 `:358` 讀到 `None`，`edit_store.remove` 在 `:99` 看到檔案存在、`:101` 因 `keep is None` 不留上一份、`:105` 刪檔。劇本：[paths/P2.md](paths/P2.md)。

兩條都只在「兩方同時操作同一張照片」時發生：HTTP 請求跑在 worker thread（`adapters/http/server.py:130`），MCP 是另一個行程，共用同一個資料夾；編輯檔的寫入只有整檔原子替換，沒有 `locks.held`（其他 store 有用，例如 `adapters/persist/preset_index.py:321`）。

## 圖

[diagrams.html](diagrams.html)：第 1 張只有正常流程，接著加上「另一方同時操作」，最後一張畫出 P1、P2。

## 範圍

一張照片；兩個同時操作的請求（App、AI 代理）；兩份不同的編輯 A、B；每個請求可以做「設定、清除、取回」任意次。窮舉的結論只在這個範圍內成立。

假設：
- 每一次寫入編輯檔，都是整檔原子替換（`locks.replace_atomic`），不會寫到一半。
- 讀檔一次讀到整份內容。

沒涵蓋：貼上編輯（`paste_edit`）、存成 preset、縮圖、多張照片之間的互動（見下方原因紀錄）。

## 怎麼檢查的

- 工具：TLA+，TLC2 2.19；這是「事件順序會不會出錯」的問題，所以用模型檢查。
- 指令：`java -cp <tla2tools.jar> tlc2.TLC -config model/PhotoEdit.cfg -deadlock -metadir <暫存目錄> model/PhotoEdit.tla`
- 現行程式：208 個狀態，R2 在 6 步內被打破；R1 單獨檢查時 1,174 個狀態，10 步內被打破。
- 看過它失敗：兩條規則都在現行程式上被抓到（`variants/R1-only.cfg`、`variants/R2-only.cfg`）。
- 看過它成功：G1 在 8 步內走得到（`model/Goal.cfg`）；拿掉「取回上一份」之後走不到（`variants/G1-NoRestore.cfg`，1,344 個狀態）。
- 修法對照：把清除與取回各自包在一個鎖裡（`variants/Locked.cfg`），R1、R2 都守住（15 個狀態）。這是參考，不是本假說的結論。

## 對應表

| 模型 | 程式 |
|---|---|
| `Set` | `photo_library.py:351` → `edit_store.py:94` |
| `ClearRead` | `photo_library.py:358` |
| `ClearExists` | `edit_store.py:99` |
| `ClearKeep` | `edit_store.py:101-103` |
| `ClearRemove` | `edit_store.py:105` |
| `RestoreRead` | `photo_library.py:366` |
| `RestorePrev` | `photo_library.py:367-369` |
| `RestoreWrite` | `photo_library.py:373-376` |

## 沒有形式化的部分

| 哪一段 | 原因類別 | 具體情況 | 要什麼才能形式化／現在走哪條路 |
|---|---|---|---|
| `photo_library.py:380-421` 貼上編輯 | 交給別份假說 | 貼上會對多張照片逐張讀寫，屬於另一個流程 | 另寫一份假說 `photo-edit-paste`；現在不處理 |
| `adapters/persist/locks.py:120-142` Windows 上 rename 遇到 PermissionError 的重試 | 無法建模 | 取決於作業系統什麼時候放開檔案 | 無；現在照 darkroom 現有的測試 |
| 編輯內容本身是否正確（preset、強度、幾何） | 符合不觸發條件 | 「跑一次就能確認的主張」（formal.md 不觸發第 1 條） | 無；紅綠測試 |

## 同步點

由發布腳本寫入 `hypothesis.json`。涵蓋的檔案改過，本頁結論就失效，以指令輸出為準。
