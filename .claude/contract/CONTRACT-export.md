# CONTRACT — darkroom 匯出（全解析度 JPEG／TIFF，保留 ICC 與 EXIF）

## 目標
使用者在 App 按「匯出」，目前照片照畫面上的 preset＋強度＋微調，用全解析度渲染成 JPEG（8-bit，品質可選、預設 92）或 TIFF（16-bit），存進照片旁的「darkroom 匯出」資料夾；顏色帶 sRGB 描述檔、EXIF 照留、方向是正的。原照片一個位元都不變，既有檔案永遠不被覆蓋。API 先吃清單，給之後照片庫的多張匯出用。

## 前提（Premises）
- P1 已驗（`darkroom/_io.py:23`）：JPEG／PNG／TIFF 以 `IMREAD_IGNORE_ORIENTATION` 讀，像素是感光元件方向；HEIC 像素已由 libheif 轉正但 EXIF 仍寫原方向（`_heif.py:3`、HEIC 合約 P4）。
- P2 已驗（`_io.py:43`）：現有 `write_image` 走 cv2，不寫 ICC、不寫 EXIF，JPEG 預設品質 95；CLI `apply` 用它。
- P3 已驗（`darkroom_app/engine.py:84`）：`Engine.open` 縮成預覽尺寸後丟掉全解析度，只留 `path`；`MAX_OPEN_IMAGES = 8`，舊的 `image_id` 會被擠掉；GPU 工作只有一條 executor 執行緒。
- P4 已驗（2026-10-09 實測 `scratchpad/tiffprobe*.py`）：PIL 12.3.0 寫 JPEG 帶 `icc_profile`＋`exif` 可讀回；tifffile 2026.9.20 寫 16-bit RGB＋ICC 可以，但拒寫 ExifIFD 指標（tag 34665）；自組的 16-bit RGB TIFF（含 34665 子 IFD 與 34675 ICC）PIL／tifffile／cv2 都能逐值讀回。`ImageCms.createProfile("sRGB")` 的位元組含建立時間，每次不同 → 不能用位元組比對描述檔。
- P5 未驗、不入條文：24MP 全解析度渲染的顯存峰值（隨 ComfyUI 等其他程式變動）。

## 可斷言條文
- [ ] X1：`POST /api/export` 主體 `{"items":[{"image_id"|"path", "preset_id"|null, "strength", "overrides"}…], "format":"jpeg"|"tiff", "quality"?, "dest_dir"?}`；回 200 `{"results":[…]}`，與 `items` 同長同序，每筆恰為 `{"ok":true,"source":檔名,"output":完整路徑}` 或 `{"ok":false,"source":檔名,"error":句子}`。一筆失敗不影響其他筆。`items` 空、`format` 不對、`quality` 非 1～100 整數（`true` 也算錯）、`dest_dir` 不存在或不是絕對路徑 → 400（句型見常數）且什麼都不寫。單筆的 `strength`／`overrides` 不合法、未知 `image_id`／`preset_id` → 該筆 `ok:false`。
- [ ] X2：每筆的最終參數一律由 `preview.validate_strength`、`preview.validate_overrides`、`preview.effective_params` 算出（與 `/api/preview` 同一份函式，不得另寫一份 R3 公式）；同一組輸入在匯出與預覽得到相等的 `Params`（`to_json()` 相同）。
- [ ] X3：全解析度：每筆從原檔重新 `read_image`，輸出像素寬高＝轉正後的原圖寬高（不縮放、不裁切）；TIFF 讀回值與 `render(全圖, 最終參數)` 量化到 16-bit 的結果最大差 ≤ 1/65535。
- [ ] X4：JPEG：8-bit 三通道、品質＝`quality`（預設 92），量化表等於 PIL 以同品質存同一張圖的量化表。TIFF：16-bit 無號整數、RGB 三樣本、無 alpha，PIL、tifffile、cv2 三者都讀得出且值相同。
- [ ] X5：色彩：兩種格式都嵌入 sRGB 描述檔：用 `darkroom._icc` 讀回時判定為矩陣／曲線型，轉換 sRGB 測試色（含 0、0.5、1 的組合）誤差 ≤ 1e-3。禁止：嵌入來源照片的描述檔（例：Display P3 的 HEIC 匯出後不得帶 P3 描述檔——像素已轉成 sRGB，再帶 P3 會轉兩次）；禁止不帶描述檔。
- [ ] X6：方向（只轉一次）：輸出像素是顯示方向，EXIF `Orientation` 寫 1。JPEG／TIFF 來源方向 3／6／8 → 輸出等於 PIL `ImageOps.exif_transpose` 的結果（8-bit 容差同 HEIC H4）；HEIC 來源方向 6 → 不再轉（等於 libheif 讀出的像素）。App 預覽與 `/api/open` 的寬高同樣是轉正後的（JPEG／TIFF 的轉正放在 `read_image`，核心合約記補丁；HEIC 行為不變）。
- [ ] X7：EXIF：來源有 EXIF 時保留 IFD0、Exif 子 IFD、GPS 子 IFD；`Make`、`Model`、`DateTimeOriginal`、`ExposureTime`、`FNumber`、`ISOSpeedRatings`、`FocalLength`、`LensModel` 與 GPS 各標籤和來源相等（來源有才比）；`PixelXDimension`／`PixelYDimension` 若存在，改成輸出寬高。禁止：`Orientation` ≠ 1、保留 IFD1 縮圖（方向與內容都已過時）、同一標籤出現兩次。來源沒有 EXIF（例：PNG）→ 輸出不帶 EXIF，不得報錯。
- [ ] X8：位置：預設 `<照片所在資料夾>/darkroom 匯出`（不存在就建立，只建這一層）；照片本身已在名為 `darkroom 匯出` 的資料夾時，就存在同一個資料夾（不再巢狀）；有 `dest_dir` 時存進它（不自動建立）。
- [ ] X9：檔名＝`{stem}.jpg` 或 `{stem}.tif`（副檔名小寫）；已存在（不分大小寫）就依序試 `{stem} (2)`、`{stem} (3)`…；用「不存在才建立」的方式開檔，兩個同時進行的匯出不得寫到同一個檔名。同一份清單裡同 stem 的兩張（例：`IMG_1.heic` 與 `IMG_1.jpg`）各得一個檔。
- [ ] X10：原檔與既有檔：匯出前後照片原檔的 SHA-256 相同；匯出資料夾裡原有檔案的內容與修改時間不變。失敗（任何原因）後匯出資料夾不留任何新檔（含暫存檔、0 byte 檔、寫一半的檔）。
- [ ] X11：GPU：匯出在同一條 GPU executor 與 stream 上跑，不呼叫 `torch.cuda.synchronize()`；顯存不足（`torch.cuda.OutOfMemoryError`）→ 該筆 `ok:false`、句子見常數「顯存不足」，不自動重試、不偷偷改用 CPU；其他渲染例外 → 「渲染失敗」句型（單行、不含 traceback）。之後 `/api/preview`、`/api/open` 照常回 200。每筆完成後釋放全解析度張量：`torch.cuda.memory_reserved()` 回到匯出前 + 256 MiB 以內。
- [ ] X12：讀檔失敗的原因＝`read_image` 的 `str(e)` 原樣（同 HEIC H13），包在「匯出失敗」句型裡；寫入失敗（權限、磁碟滿）→「無法寫入」句型。
- [ ] X13：前端：預覽工具列有「匯出」按鈕、格式選單（JPEG／TIFF）與 JPEG 品質輸入（1～100、預設 92，選 TIFF 時停用）；沒開照片時按鈕停用；匯出中按鈕停用並顯示「匯出中…」；完成或失敗顯示常數句型；R6／H11 的「窄視窗不得藏掉」清單加入這三個控制項。匯出不改變編輯狀態（不進復原紀錄、不清微調）。
- [ ] X14：B12 修訂（App 外殼合約加補丁 R9）：伺服器只在 `/api/export` 寫檔，且只寫 X9 命名的新檔進 X8 決定的資料夾（暫存檔也只能在那裡、結束前清掉）、只可能建立 `darkroom 匯出` 這一層資料夾；不得改寫、刪除、改名任何既有檔案；preset 檔一律只讀；跑完全部測試後 preset 合併雜湊仍為 `15C015CC0C080FF9`。`server.py` 的模組說明同步改掉「沒有匯出」。
- [ ] X15：核心：`darkroom_app` 只用 `darkroom` 的公開名稱；若為了 ICC／EXIF 擴充公開 API，核心合約 A2 的名稱清單同步改；CLI `apply` 的輸出行為不變（本片不動）。`python -s -m unittest discover -s tests` 結束碼 0；測試只用程式產生的照片（含帶 EXIF／方向的 JPEG、P3 HEIC、無 EXIF 的 PNG），不用使用者照片。
- 不做（留給之後）：存成 xmp、批次匯出佇列介面、浮水印、縮放尺寸、自選匯出資料夾的介面（API 已有 `dest_dir`）。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 照片原檔與既有檔（X9、X10、X14） | 只讀／不覆蓋 | 使用者照片與先前匯出 → 被蓋掉或改寫，無法復原｜不可逆／資料 | `test_export_never_touches_source`、`test_export_never_overwrites`、`test_export_concurrent_names`、`test_export_failure_leaves_no_file` |
| 色彩描述檔（X5） | sRGB、不帶來源描述檔 | 使用者成品 → 在別的軟體或印刷顏色偏掉｜邏輯核心 | `test_export_embeds_srgb`、`test_export_p3_heic_not_double_converted` |
| 方向（X6） | 轉一次、Orientation=1 | 成品 → 直拍照躺著或轉兩次｜邏輯核心 | `test_export_orientation_jpeg`、`test_export_orientation_heic_once` |
| EXIF（X7） | 保留清單、禁止清單 | 使用者的拍攝資料 → 相簿軟體依日期排序錯亂、GPS 遺失｜不可逆／資料 | `test_export_exif_kept` |
| 匯出 API 形狀（X1） | 見條文 | 之後照片庫的多張匯出 → 欄位一變整批壞掉｜上下游契約 | `test_api_export_shape` |
| 預覽與匯出同參數（X2） | 同一份函式 | 使用者 → 匯出的跟畫面看到的不同｜邏輯核心 | `test_export_params_equal_preview` |
| GPU 忙碌（X11） | 錯誤句、伺服器存活 | App → 顯存不足時伺服器當掉、編輯器失效｜穩定性可靠性 | `test_export_oom_message_and_server_alive`、`test_export_releases_memory` |
| 錯誤句（X1、X11、X12、X13） | 見常數 | 使用者 → 不知道為什麼失敗、該關程式還是換資料夾｜UI/UX | `test_export_error_texts`、`tests/js/test_logic.cjs` 匯出訊息 |

## Verbatim Constants
```text
匯出資料夾名稱：darkroom 匯出
檔名：{stem}.jpg ／ {stem}.tif；重名：{stem} ({n}).jpg ／ {stem} ({n}).tif（n 從 2 起）
JPEG 品質：預設 92，範圍 1～100（整數）
format 值：jpeg、tiff
記憶體釋放門檻：匯出前 memory_reserved + 256 MiB
成功（前端）：已匯出：{output_path}
匯出中（按鈕）：匯出中…
匯出失敗（單筆 error 與前端）：匯出失敗：{file_name}：{reason}
顯存不足（reason）：顯示卡記憶體不足，可能有其他程式正在使用 GPU；關掉它們後再匯出一次
渲染失敗（reason）：渲染失敗：{detail}
無法寫入（reason）：無法寫入匯出資料夾：{folder}
400：沒有要匯出的照片
400：不支援的匯出格式：{format}（可用 jpeg、tiff）
400：JPEG 品質要在 1～100 之間：{quality}
400：找不到匯出資料夾：{dest_dir}
```
