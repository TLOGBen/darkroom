# 假說：縮圖格的背景縮圖佇列

> 狀態以這行指令為準，不以本頁為準：`python3 D:\Workspace\01_Plugin\baransu\plugins\baransu\skills\hypothesis\scripts\hypothesis-status.py --area thumbnail-queue`

## 一句話

縮圖格在背景幫資料夾做縮圖時，做好的縮圖不該再做一次；現行程式在「查的當下還沒做好、排進去時已經做好」的空檔裡會重做，而且重做的張數可以超過工作執行緒數。

## 規則

| # | 種類 | 規則 | 出處 | 發布時 |
|---|---|---|---|---|
| R1 | 安全 | 同一張照片同時只會有一個縮圖工作。 | 合約 PLP8；`darkroom_app/services/photo_library.py:143-150` | 守住 |
| R2 | 安全 | 一張照片的縮圖做好之後，只有照片本身更新過，才會重新縮一次。 | 合約 PLP8「已在快取的照片在排入前就以索引過濾掉」；`photo_library.py:516-530`；使用者 2026-10-24 改寫為「更新後才會重縮」 | 被打破（P1、P2） |
| R3 | 安全 | 重新列一次資料夾，被重做的照片不會超過工作執行緒數。 | `tests/test_photo_library.py:1141`（測試的假設，不是合約） | 被打破（P1） |
| G1 | 目標 | 列一次資料夾之後，每張照片終究都有縮圖。 | `photo_library.py:516-530`、`:182-211`、`:472-496` | 走得到 |

使用者已於 2026-10-24 確認 R1、R2（改寫後）、R3、G1。本假說由 `/hunt` 案件 HUNT-2026-001 起案。

## 找到的問題

**P1　重新整理資料夾時，排在後面、還沒開始的縮圖也會被重做，重做的張數可以超過工作執行緒數。** 程式先把整個資料夾查一遍、查完才排進去；查的當下還沒做好、排進去時已經做好並離開「處理中」的照片，會被當成新工作再做一次。查詢是一段時間，這段時間裡陸續開始又做完的都算，所以不只是當下正在做的那幾張。傷害是浪費（多讀原圖、多算指紋），以及測試 `:1141` 的上限在慢機器上會被超過——CI 上兩次 `27 not less than or equal to 26` 就是它。
細節：`folder_thumbnails` 的查詢迴圈 `:516-527` 與排入迴圈 `:529-530` 之間沒有鎖，`submit` 只看 `inflight`（`:143`）、不再查索引。劇本：[paths/P1.md](paths/P1.md)，圖 3。

**P2　直接要一張縮圖時，背景剛好把它做完，結果又被做一次。** `thumbnail` 查索引（`:543-548`）到排入（`:550`）之間沒有鎖，背景工作做完並離開「處理中」可以落在中間。傷害是浪費，這次請求多等一件工作。劇本：[paths/P2.md](paths/P2.md)，圖 3。

## 圖

[diagrams.html](diagrams.html)：

- 圖 1　正常流程：排隊、做縮圖、記進索引，再列資料夾直接用快取。
- 圖 2　加上「重新列資料夾分兩段」：先查完、再排入，排入只看處理中；工作執行緒同時在跑。
- 圖 3　P1、P2 兩條重做路徑。

這組圖沒有呼叫 `/draw`，是沿用假說 photo-edit 圖組的樣式以腳本生成（見 `diagrams/docs/brief.md`）。

## 範圍

一個資料夾；3 張照片（R3 用 4 張：測試的情境裡最後一張會被直接請求先做完，要容得下另外 3 張重做，至少要 4 張）；2 個工作執行緒（每個能同時跑多份的角色至少兩份）；主執行緒照測試的順序：列一次資料夾 → 直接要最後一張 → 再列一次；R1、R2 另外允許每張照片被改一次（大小或修改時間變了）。窮舉的結論只在這個範圍內成立。

假設：
- 佇列的每個操作（排入、取出、離開處理中）都握著 `self.cv`，一步做完。
- 查一張照片有沒有縮圖（`lookup`＋`exists`）是一步；工作執行緒「記進索引」（`:493`）與「離開處理中」（`:204`）是分開的兩步，前者在前。
- 工作執行緒讀檔時的版本，就是記進索引的版本（`_generate :478-480` 的 `stat` 與 `:493` 的 `remember`）。

沒涵蓋：縮圖內容、索引寫回磁碟、換資料夾作廢舊工作、工作失敗（見下方原因紀錄）。

## 怎麼檢查的

- 工具：TLA+，TLC2 2.19；這是「事件順序會不會出錯」的問題（formal.md H1：一份狀態多個寫入者、檢查與寫入分開沒有鎖）。
- 指令：`pwsh -File model/check.ps1`（每個設定檔跑一次 `java -cp <tla2tools.jar> tlc2.TLC -deadlock -config <cfg> ThumbQueue.tla`）。
- R1 守住（`model/R1.cfg`，35,822 個狀態）；R2 在 18 步內被打破（`model/R2.cfg`，3,727 個狀態，P2）；R3 在 38 步內被打破（`model/R3.cfg`，4 張照片，3,288 個狀態，P1）。
- 看過它失敗：R1——送進佇列不看「處理中」（`variants/R1-NoInflightCheck.cfg`）在 10 步內被抓到；R2、R3——現行程式本身就打破（`model/R2.cfg`、`model/R3.cfg`）。
- 看過它成功：G1 走得到（`model/Goal.cfg`）；拿掉「做完記進索引」之後走不到（`variants/G1-NoMake.cfg`）。
- 修法對照：送進佇列時（握著佇列鎖）不在處理中就再查一次索引（`variants/Fix-RecheckInSubmit.cfg`，4 張照片），R1、R2、R3 都守住（222,006 個狀態）。這是參考，不是本假說的結論。
- 在真的程式上驗證 P1（HUNT-2026-001 推測 3）：只在第二次列資料夾時放慢，10 次裡 7 次超過上限，重做的照片時間軸都是「查不到 → 做完 → 排成新工作」。
- 原始輸出：[check.txt](check.txt)。

## 對應表

| 模型 | 程式 |
|---|---|
| `ver`、`Cached`、`Update` | `adapters/persist/thumb_store.py:104-111`（比大小與修改時間） |
| `idx`、`WorkDone` | `photo_library.py:493` → `thumb_store.py:113-118` |
| `SubmitQ` | `photo_library.py:136-158` |
| `ListLookup` | `photo_library.py:516-527` |
| `ListGen` | `photo_library.py:528`、`:160-164` |
| `ListSubmit` | `photo_library.py:529-530` |
| `DirectLook`、`DirectSubmit`、`DirectWait` | `photo_library.py:543-548`、`:550` |
| `Take` | `photo_library.py:186-198` → `_generate :478-480` |
| `Release` | `photo_library.py:203-206` |
| 主執行緒的情境 | `tests/test_photo_library.py:1113-1137` |

## 沒有形式化的部分

| 哪一段 | 原因類別 | 具體情況 | 要什麼才能形式化／現在走哪條路 |
|---|---|---|---|
| `photo_library.py:484-492`、`utils/imaging` 縮圖內容 | 符合不觸發條件 | 「跑一次就能確認的主張」 | 無；既有縮圖測試 |
| `photo_library.py:494-495`、`thumb_store.py:120-` 索引寫回磁碟 | 符合不觸發條件 | 寫回時機不影響會不會重做 | 無；`test_index_file` |
| 換到另一個資料夾時作廢舊工作（`:190` 跨資料夾） | 交給別份假說 | 這次的失敗在同一個資料夾 | 另寫假說 `thumbnail-queue-folders`；現在不處理 |
| `photo_library.py:199-202` 工作失敗 | 符合不觸發條件 | 例外的傳遞跑一次就能確認 | 無；`test_background_failures_are_logged_to_stderr` |

## 同步點

由發布腳本寫入 `hypothesis.json`。涵蓋的檔案改過，本頁結論就失效，以指令輸出為準。
