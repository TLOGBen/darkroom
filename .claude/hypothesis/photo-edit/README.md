# 假說：一張照片的編輯、清除、取回上一份

> 狀態以這行指令為準，不以本頁為準：`python3 D:\Workspace\01_Plugin\baransu\plugins\baransu\skills\hypothesis\scripts\hypothesis-status.py --area photo-edit`

## 一句話

同一張照片同時被 App 和 AI 代理操作時，清除與取回都不能讓任何一份編輯消失；加上編輯鎖之後，兩條都守住。

## 規則

| # | 種類 | 規則 | 出處 | 發布時 |
|---|---|---|---|---|
| R1 | 安全 | 取回上一份編輯時，絕不蓋掉一份不同的編輯。 | `darkroom_app/services/photo_library.py:391-395`（S4a） | 守住 |
| R2 | 安全 | 被清掉的編輯，一定先留成「上一份」。 | `darkroom_app/adapters/persist/edit_store.py:139`（S4） | 守住 |
| G1 | 目標 | 一張照片可以設定編輯、清除、再取回。 | `photo_library.py:335-365`、`:367-376`、`:378-397` | 走得到 |

規則依據程式自己寫下的兩條承諾（S4、S4a）挑選，使用者已於 2026-10-24 逐條確認 R1、R2、G1。

## 找到的問題

目前沒有：兩條規則都守住，沒有問題路徑。

上一版（第 4 版，4afcc58）找到的兩條，已經在 a35545f 修好：

- **原本的 P1　取回上一份時，蓋掉了 AI 代理剛存的新編輯。** 取回先讀到「沒有編輯」，AI 代理這時存了一份新的，取回照樣寫入。現在取回從讀到寫都握著編輯鎖，AI 代理要存得等取回做完，所以它的新編輯會在取回之後寫入，不會被蓋掉。
- **原本的 P2　清除編輯時，把 AI 代理剛存的編輯刪掉，連「上一份」都沒留。** 清除先讀到「沒有編輯」，AI 代理這時存了一份，清除照樣刪檔。現在清除先看編輯檔在不在，不在就什麼都不做；在的話，從讀到刪都握著鎖，刪掉的就是它讀到、並且留成上一份的那一份。

兩條的劇本、紅燈測試在 commit e4ebbb5（`tests/test_photo_library.py` 的 `TestConcurrentClearRestore`，現在是綠燈）。沒有鎖的舊程式仍然留在模型裡當對照組（`variants/R1-Unlocked.cfg`、`variants/R2-Unlocked.cfg`），兩條規則都會被抓到。

## 圖

[diagrams.html](diagrams.html)：

- 圖 1　正常流程：存一份編輯、清除時留下上一份、再取回。
- 圖 2　加上「另一方同時操作」：每個操作都是「先讀、再寫」。
- 圖 3　加上「編輯鎖」：從先讀到寫入都握著鎖，另一方要等鎖放開才能存。

## 範圍

一張照片；兩個同時操作的請求（App、AI 代理）；兩份不同的編輯 A、B；每個請求可以做「設定、清除、取回」任意次。窮舉的結論只在這個範圍內成立。

假設：
- 每一次寫入編輯檔，都是整檔原子替換（`locks.replace_atomic`），不會寫到一半。
- 讀檔一次讀到整份內容。
- 編輯鎖同一時間只有一方拿得到：跨行程靠 `edits/edits.lock` 的位元組鎖（`locks.held`），同一個行程的不同執行緒靠行程內的鎖（POSIX 的檔案鎖不擋同一個行程）。
- 設定編輯在鎖外的第一輪只檢查參數、不寫，真正的決定在鎖裡重讀之後才做，所以在模型裡設定是握著鎖的一步。

沒涵蓋：貼上編輯（`paste_edit`）的多張流程、存成 preset、縮圖、多張照片之間的互動（見下方原因紀錄）。貼上每一張目標的「讀、寫」也握著同一把鎖，對單張照片來說跟設定是同一步。

## 怎麼檢查的

- 工具：TLA+，TLC2 2.19；這是「事件順序會不會出錯」的問題，所以用模型檢查。
- 指令：`pwsh -File model/check.ps1`（每個設定檔跑一次 `java -cp <tla2tools.jar> tlc2.TLC -deadlock -config <cfg> PhotoEdit.tla`，jar 預設 `D:\Workspace\00_Env\tla\tla2tools.jar`，可用 `-Jar` 或 `TLA2TOOLS_JAR` 換）。
- 現行程式（`model/PhotoEdit.cfg`）：17,837 個狀態，R1、R2 都守住，不到 1 秒。
- 看過它失敗：拿掉編輯鎖（回到 4afcc58 的程式），R1 在 10 步內被打破（`variants/R1-Unlocked.cfg`，1,174 個狀態），R2 在 6 步內被打破（`variants/R2-Unlocked.cfg`，208 個狀態）。
- 看過它成功：G1 走得到（`model/Goal.cfg`，13 個狀態長的路徑）；拿掉「取回上一份」之後走不到（`variants/G1-NoRestore.cfg`，351 個狀態）。
- 改前改後各跑一次，原始輸出都在 [check.txt](check.txt)。

## 對應表

| 模型 | 程式 |
|---|---|
| `Set` | `photo_library.py:335-365`（鎖在 `:349`，寫入 `:364`）→ `edit_store.py:136`；貼上每張目標 `photo_library.py:432-437` |
| `ClearCheck` | `photo_library.py:371-372` |
| `ClearLock`、`RestoreLock` | `photo_library.py:373`、`:385` → `edit_store.py:112-130` → `locks.py:76-102` |
| `ClearRead` | `photo_library.py:374` |
| `ClearExists` | `edit_store.py:141` |
| `ClearKeep` | `edit_store.py:143-145` |
| `ClearRemove` | `edit_store.py:147` |
| `RestoreCheck` | `photo_library.py:382-384` |
| `RestoreRead` | `photo_library.py:386` |
| `RestorePrev` | `photo_library.py:387-389` |
| `RestoreWrite` | `photo_library.py:393-396` |
| `Release` | `edit_store.py:128-130` |
| 兩方同時操作 | `adapters/http/server.py:130`（worker thread）、`adapters/mcp_server/__init__.py:1`（另一個行程） |

## 沒有形式化的部分

| 哪一段 | 原因類別 | 具體情況 | 要什麼才能形式化／現在走哪條路 |
|---|---|---|---|
| `photo_library.py:400-441` 貼上編輯 | 交給別份假說 | 貼上會對多張照片逐張讀寫，屬於另一個流程 | 另寫一份假說 `photo-edit-paste`；現在不處理 |
| `adapters/persist/locks.py:120-142` Windows 上 rename 遇到 PermissionError 的重試 | 無法建模 | 取決於作業系統什麼時候放開檔案 | 無；現在照 darkroom 現有的測試 |
| 編輯內容本身是否正確（preset、強度、幾何） | 符合不觸發條件 | 「跑一次就能確認的主張」（formal.md 不觸發第 1 條） | 無；紅綠測試 |

## 同步點

由發布腳本寫入 `hypothesis.json`（第 5 版，程式 a35545f，2026-10-24 發布）。涵蓋的檔案改過，本頁結論就失效，以指令輸出為準。
