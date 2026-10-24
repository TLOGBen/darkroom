# 假說：縮圖格的背景縮圖佇列

> 狀態以這行指令為準，不以本頁為準：`python3 D:\Workspace\01_Plugin\baransu\plugins\baransu\skills\hypothesis\scripts\hypothesis-status.py --area thumbnail-queue`

## 一句話

縮圖格在背景幫資料夾做縮圖時，做好的縮圖不會再做一次，除非照片本身改過；修正後三條規則都守住。

## 規則

| # | 種類 | 規則 | 出處 | 發布時 |
|---|---|---|---|---|
| R1 | 安全 | 同一張照片同時只會有一個縮圖工作。 | 合約 PLP8；`darkroom_app/services/photo_library.py:151-154` | 守住 |
| R2 | 安全 | 一張照片的縮圖做好之後，只有照片本身更新過，才會重新縮一次。 | 合約 PLP8「已在快取的照片在排入前就以索引過濾掉」；`photo_library.py:155-158`、`:546-547`、`:567-568`；使用者 2026-10-24 改寫為「更新後才會重縮」 | 守住 |
| R3 | 安全 | 重新列一次資料夾，被重做的照片不會超過工作執行緒數。 | `tests/test_photo_library.py:1151`（原本是測試的假設；修正後測試斷言剛好 24，也就是不重做） | 守住 |
| G1 | 目標 | 列一次資料夾之後，每張照片終究都有縮圖。 | `photo_library.py:533-547`、`:190-219`、`:480-504` | 走得到 |

使用者已於 2026-10-24 確認 R1、R2（改寫後）、R3、G1。本假說由 `/hunt` 案件 HUNT-2026-001 起案。

## 找到的問題

目前沒有：三條規則都守住，沒有問題路徑。

第 1 版（17f91bc）找到的兩條已經修好（HUNT-2026-001）：

- **原本的 P1　重新整理資料夾時，排在後面、還沒開始的縮圖也會被重做，重做的張數可以超過工作執行緒數。** 程式先把整個資料夾查一遍、查完才排進去，查詢期間做好並離開「處理中」的照片會被當成新工作再做一次；CI 上兩次 `27 not less than or equal to 26` 就是它。
- **原本的 P2　直接要一張縮圖時，背景剛好把它做完，結果又被做一次。**

修法：`_ThumbQueue.submit` 多了 `done` 檢查（`:155-158`）。排進佇列時若這張不在「處理中」，就握著佇列鎖再查一次索引，已經做好就不排；直接請求拿到「已經做好」時改讀快取（`:569-575`）。工作執行緒是先記進索引（`:501`）、後離開處理中（`:212`），所以握著佇列鎖時「不在處理中」只會是「沒排過」或「已經記進索引」，再查一次不會漏。

兩條的強制時序測試在 `tests/test_photo_library.py` 的 `test_relisting_never_remakes_a_thumbnail_made_while_the_folder_was_checked`、`test_direct_request_never_remakes_a_thumbnail_made_meanwhile`（修正前紅、修正後綠）。沒有「再查一次」的舊程式留在模型裡當對照組（`variants/R2-NoRecheck.cfg`、`variants/R3-NoRecheck.cfg`），兩條規則都會被抓到。

## 圖

[diagrams.html](diagrams.html)：

- 圖 1　正常流程：排隊、做縮圖、記進索引，再列資料夾直接用快取。
- 圖 2　加上「重新列資料夾分兩段」：先查完、再排入；工作執行緒同時在跑。
- 圖 3　加上「排進佇列時再查一次」：查的當下沒縮圖、之後做好的照片不再排。

這組圖沒有呼叫 `/draw`，是沿用假說 photo-edit 圖組的樣式以腳本生成（見 `diagrams/docs/brief.md`）。

## 範圍

一個資料夾；3 張照片（R3 用 4 張：測試的情境裡最後一張會被直接請求先做完，要容得下另外 3 張重做才看得出 R3，至少要 4 張）；2 個工作執行緒（每個能同時跑多份的角色至少兩份）；主執行緒照測試的順序：列一次資料夾 → 直接要最後一張 → 再列一次；R1、R2 另外允許每張照片被改一次（大小或修改時間變了）。窮舉的結論只在這個範圍內成立。

假設：
- 佇列的每個操作（排入含「再查一次」、取出、離開處理中）都握著 `self.cv`，一步做完。
- 查一張照片有沒有縮圖（`lookup`＋`exists`，`_cached_fingerprint :506-513`）是一步；工作執行緒「記進索引」（`:501`）與「離開處理中」（`:212`）是分開的兩步，前者在前。
- 工作執行緒讀檔時的版本，就是記進索引的版本（`_generate :486-488` 的 `stat` 與 `:501` 的 `remember`）。

沒涵蓋：縮圖內容、索引寫回磁碟、換資料夾作廢舊工作、工作失敗、快取資料夾被外部清掉（見下方原因紀錄）。

## 怎麼檢查的

- 工具：TLA+，TLC2 2.19；這是「事件順序會不會出錯」的問題（formal.md H1：一份狀態多個寫入者、檢查與寫入分開）。
- 指令：`pwsh -File model/check.ps1`（每個設定檔跑一次 `java -cp <tla2tools.jar> tlc2.TLC -deadlock -config <cfg> ThumbQueue.tla`）。
- 現行程式：R1 守住（`model/R1.cfg`，21,956 個狀態）；R2 守住（`model/R2.cfg`，21,956 個狀態）；R3 守住（`model/R3.cfg`，4 張照片，2,129 個狀態）。
- 看過它失敗：R1——送進佇列不看「處理中」（`variants/R1-NoInflightCheck.cfg`）在 10 步內被抓到；R2、R3——拿掉「再查一次」（＝17f91bc 的程式，`variants/R2-NoRecheck.cfg`、`variants/R3-NoRecheck.cfg`）各在 18、38 步內被抓到。
- 看過它成功：G1 走得到（`model/Goal.cfg`）；拿掉「做完記進索引」之後走不到（`variants/G1-NoMake.cfg`）。
- 改模型前後各跑一次，原始輸出都在 [check.txt](check.txt)。

## 對應表

| 模型 | 程式 |
|---|---|
| `ver`、`Cached`、`Update` | `adapters/persist/thumb_store.py:104-111`；`photo_library.py:506-513` |
| `idx`、`WorkDone` | `photo_library.py:501` → `thumb_store.py:113-118` |
| `SubmitQ`（含 `RecheckInSubmit`） | `photo_library.py:136-166`（`done`：`:155-158`） |
| `ListLookup` | `photo_library.py:533-544` |
| `ListGen` | `photo_library.py:545`、`:168-172` |
| `ListSubmit` | `photo_library.py:546-547` |
| `DirectLook`、`DirectSubmit`、`DirectWait` | `photo_library.py:560-565`、`:567-575` |
| `Take` | `photo_library.py:194-206` → `_generate :486-488` |
| `Release` | `photo_library.py:211-214` |
| 主執行緒的情境 | `tests/test_photo_library.py:1123-1147` |

## 沒有形式化的部分

| 哪一段 | 原因類別 | 具體情況 | 要什麼才能形式化／現在走哪條路 |
|---|---|---|---|
| `photo_library.py:492-500`、`utils/imaging` 縮圖內容 | 符合不觸發條件 | 「跑一次就能確認的主張」 | 無；既有縮圖測試 |
| `photo_library.py:502-503`、`thumb_store.py:120-` 索引寫回磁碟 | 符合不觸發條件 | 寫回時機不影響會不會重做 | 無；`test_index_file` |
| 換到另一個資料夾時作廢舊工作（`:198` 跨資料夾） | 交給別份假說 | 這次的失敗在同一個資料夾 | 另寫假說 `thumbnail-queue-folders`；現在不處理 |
| `photo_library.py:207-210` 工作失敗 | 符合不觸發條件 | 例外的傳遞跑一次就能確認 | 無；`test_background_failures_are_logged_to_stderr` |
| `photo_library.py:571-573` 快取資料夾在「再查一次」之後被外部清掉 | 無法建模 | 取決於別的程式什麼時候刪 data_dir 裡的檔 | 無；這時直接請求改成排一個工作重做（程式內寫明） |

## 同步點

由發布腳本寫入 `hypothesis.json`。涵蓋的檔案改過，本頁結論就失效，以指令輸出為準。
