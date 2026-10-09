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
- [ ] X11：GPU：匯出在同一條 GPU executor 與 stream 上跑，不呼叫 `torch.cuda.synchronize()`；顯存不足（`torch.cuda.OutOfMemoryError`）→ 該筆 `ok:false`、句子見常數「顯存不足」，不自動重試、不偷偷改用 CPU；其他渲染例外 → 「渲染失敗」句型（單行、不含 traceback）。之後 `/api/preview`、`/api/open` 照常回 200。~~每筆完成後釋放全解析度張量：`torch.cuda.memory_reserved()` 回到匯出前 + 256 MiB 以內。~~【已由補丁 XP7 取代】
- [ ] X12：讀檔失敗的原因＝`read_image` 的 `str(e)` 原樣（同 HEIC H13），包在「匯出失敗」句型裡；寫入失敗（權限、磁碟滿）→「無法寫入」句型。
- [ ] X13：前端：預覽工具列有「匯出」按鈕、格式選單（JPEG／TIFF）與 JPEG 品質輸入（1～100、預設 92，選 TIFF 時停用）；沒開照片時按鈕停用；匯出中按鈕停用並顯示「匯出中…」；完成或失敗顯示常數句型；R6／H11 的「窄視窗不得藏掉」清單加入這三個控制項。匯出不改變編輯狀態（不進復原紀錄、不清微調）。
- [ ] X14：B12 修訂（App 外殼合約加補丁 R9）：~~伺服器只在 `/api/export` 寫檔~~【已由補丁 XP5 取代：只有 facade 操作 `export`（三個入口）寫檔】，且只寫 X9 命名的新檔進 X8 決定的資料夾（暫存檔也只能在那裡、結束前清掉）、只可能建立 `darkroom 匯出` 這一層資料夾；不得改寫、刪除、改名任何既有檔案；preset 檔一律只讀；跑完全部測試後 preset 合併雜湊仍為 `15C015CC0C080FF9`。`server.py` 的模組說明同步改掉「沒有匯出」。
- [ ] X15：核心：`darkroom_app` 只用 `darkroom` 的公開名稱；若為了 ICC／EXIF 擴充公開 API，核心合約 A2 的名稱清單同步改；~~CLI `apply` 的輸出行為不變（本片不動）。~~【已由補丁 XP9 取代】`python -s -m unittest discover -s tests` 結束碼 0；測試只用程式產生的照片（含帶 EXIF／方向的 JPEG、P3 HEIC、無 EXIF 的 PNG），不用使用者照片。
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

## 條文補丁（Patches）— 依分層合約 L15（2026-10-09，開工前補；X1～X15 照舊有效，劃線處以補丁為準）
前提補充：XQ1 已驗（`CONTRACT-layering.md` L2／L7／L9～L13、`tests/test_app_server.py:489` `test_app_has_no_write_path` 遞迴禁 `write_image`／`imwrite`）。XQ2 已驗（ADR-0003）：效能目標寫成數字，達不到才 profile。XQ3 推估、非本 repo 量測：24MP HEIC 開檔熱機約 0.53 秒（派工提供；H12 上限 1.5 秒）、預覽 1.5MP 往返 p50 約 30 ms（App 外殼 P2）、全域管線 1.5MP 14～18 ms（核心 A17）→ 24MP 渲染約 16 倍像素，推估 0.25～0.35 秒；24MP JPEG 解碼與 q92 編碼各推估 0.2～0.4 秒。串行約 0.8～1.1 秒／張，三段重疊後瓶頸約 0.4 秒／張。
- [ ] XP1（分層）：匯出只走 facade 操作 `export(items, format, quality=None, dest_dir=None)` → `ExportService`（`darkroom_app/services/export.py`）。L2「恰 7 個」改為恰 8 個，`export` 排第 8；`DarkroomFacade.export` 本體恰一個 `return`；`OPERATIONS["export"]` 登錄 HTTP `POST /api/export`、CLI `export`、MCP `darkroom_export`，`test_operation_coverage` 照 L2 檢查三者都存在。X1 的請求與回應形狀、全部 400 句子逐字不變；驗證與 X2 參數計算只在 service，controller 不得呼叫 `validate_*`／`effective_params`（L13 照舊）。`FakeDarkroom` 同步加 `export`。
- [ ] XP2（錯誤種類）：X1 的請求層錯誤（items 空、format、quality、dest_dir 不存在或非絕對路徑）＝ invalid → HTTP 400／CLI 2／MCP `isError:true`，三入口 message 逐字等於 X1 常數。單筆失敗不是 kind：留在 `results` 裡 `ok:false`，整個操作仍算成功（HTTP 200／CLI 0／MCP `isError:false`）。撞名一律照 X9 改用編號名，不回 conflict；不存在才建立的開檔連續失敗到 `n=9999` 仍拿不到檔名 → 該筆 `ok:false`、reason＝「檔名用完」常數；本片不產生 conflict／unavailable kind（L7 預留不動）。禁止：撞名時覆蓋、回 409、整批中止。
- [ ] XP3（CLI）：`export <photo>… [--preset ID] [--strength S] [--override KEY=VALUE]… [--format jpeg|tiff] [--quality N] [--dest-dir D] --json` 可選；每張照片各成一個 item、共用同一組參數，`--format` 預設 `jpeg`。`--json` stdout 恰一行 `{"ok":true,"result":{"results":[…]}}`（results 每筆形狀同 X1）；不帶 `--json` 時每筆一行：成功印「已匯出：{output_path}」、失敗印單筆 error 句（stdout），stderr 空。照片路徑走 `path` item，不經 `open_photo`、不佔 `MAX_OPEN_IMAGES`。
- [ ] XP4（MCP）：工具 `darkroom_export` 加在 L10 工具清單最後；annotations 恰為 `readOnlyHint:false`、`destructiveHint:false`、`idempotentHint:false`、`openWorldHint:false`（L10「全部工具標 readOnlyHint:true」對此工具不適用）；inputSchema 根層 `type:"object"`、`additionalProperties:false`，必填 `items`、`format`；成功 `content:[{type:"text", text:<{"results":…} 的 JSON>}]`＋`structuredContent:{"results":[…]}`，不回傳圖片位元組。
- [ ] XP5（寫檔守門，修訂 X14、L12、L13）：`test_app_has_no_write_path` 與 L13 的 `write_image`／`imwrite` 遞迴掃描改為只放行 `darkroom_app/services/export.py` 這一個檔（白名單恰 1 項，路徑比對，不用 glob）；其他模組含 `server.py`、`cli.py`、`mcp_server/**` 照禁。`darkroom_app/**` 中只有 `services/export.py` 可出現以寫入模式（`"w"`、`"a"`、`"x"`、`"+"`）開檔、`os.replace`、`os.rename`、`os.remove`、`os.unlink`、`shutil.`（AST 檢查 `test_only_export_service_writes`）。`test_server_never_writes` 與 `test_cli_mcp_never_write` 改成：非匯出情境照舊零寫入；匯出情境只准在該情境的暫存 `dest_dir` 新增 X9 命名的檔。
- [ ] XP6（三入口一致性，加入 `tests/test_interface_parity.py`）：每個 driver 各用自己的空暫存 `dest_dir`，Outcome 加比 `results` 每筆的 `(ok, basename(output) 或 error)`。情境至少：items 空、format `png`、quality 0、quality `true`、dest_dir 相對路徑、dest_dir 不存在（以上 invalid）；單筆未知 preset、單筆路徑不存在、壞 JPEG（ok:false 句子三邊相同）；合成 JPEG 成功（`{stem}.jpg`）；預先放 `{stem}.jpg` → `{stem} (2).jpg`；兩筆一好一壞同序回傳。
- [ ] XP7（管線，取代 X11 最後一句）：多筆匯出時讀檔 → GPU 渲染 → 編碼／寫檔三段重疊：讀檔與編碼在 GPU executor 之外的執行緒做，渲染仍只在 `darkroom-gpu` executor 與既有 stream（X11 其餘照舊）。同一時間送進 GPU executor 的匯出工作最多 1 個（預覽最多等一張全解析度渲染）；在途全解析度影像（已讀未寫完）最多 3 張。`results` 仍與 `items` 同序。整批結束後 `torch.cuda.memory_reserved()` ≤ 匯出前 + 256 MiB。
- [ ] XP8（批次吞吐量，ADR-0003）：`tools/bench_export.py` 與 `test_export_batch_throughput`：程式產生 20 張 24MP（6000×4000）8-bit sRGB JPEG（不同雜訊內容、帶 EXIF、Orientation 1），套一個含曲線的合成 preset、強度 100，經 `build_facade(...).export` 一次匯出成 JPEG q92 到暫存資料夾；先匯出另一張暖機不計。(a) 總牆鐘時間 ÷ 20 ≤ 0.8 秒／張；(b) 重疊有效：牆鐘時間 ≤ 0.7 × 各張讀檔＋渲染＋編碼寫檔分段耗時加總；印出每段中位數。量測前照 App 外殼補丁 R1（B7 (a)(b)(c)）判斷 GPU 是否忙碌，忙碌或無 CUDA 才跳過並印出原因，不得默默通過；`--force` 強制量測。目標理由見 XQ3：0.8 秒＝串行推估下限，只有真的重疊才穩定達到，且為重疊後推估瓶頸的 2 倍餘裕。達不到 → 先 profile 三段並把結果記進本合約；不放寬門檻（要放寬須使用者同意）；只有 profile 證明熱點是無法向量化、也沒有現成 C 函式庫可用的純 Python 迴圈時，才另開切片用 Rust（pyo3＋maturin）換掉那一段（ADR-0003；本片不用 Rust、不加依賴）。TIFF 16-bit 不設吞吐量目標。
- [ ] XP9（核心補丁，修訂 X6／X15）：X6 的 JPEG／TIFF 轉正改的是核心 `darkroom/_io.py` 的 `read_image`，必須在同一個 commit 於 `CONTRACT-core-library.md` 補丁區加一行（照抄常數「核心補丁 K2」）；核心 A2 公開名稱不變。因此 `python -m darkroom apply` 對方向 3／6／8 的 JPEG／TIFF 輸出改成轉正後的像素（X15 原「apply 輸出行為不變」只對方向 1 與 PNG／HEIC 成立）；`test_cli` 若有方向案例照此修正並記成本補丁。PNG 與 HEIC 行為不變。

| 補丁表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 寫檔白名單（XP5） | 恰 1 個模組可寫 | 使用者照片與 preset → 別的入口或模組長出寫檔路徑，改寫原檔｜不可逆／資料 | `test_app_has_no_write_path`、`test_only_export_service_writes`、`test_cli_mcp_never_write` |
| 三入口匯出結果（XP1～XP4、XP6） | X1 形狀、XP2 對照 | 代理 → 同一批匯出三個入口說法不同或把失敗當成功｜上下游契約 | `test_interface_parity`、`test_operation_coverage`、`test_cli_export_json`、`test_mcp_export_annotations` |
| 撞名（XP2） | 編號名、不 409 | 使用者先前的匯出檔 → 被覆蓋｜不可逆／資料 | `test_export_never_overwrites`、`test_export_name_exhausted` |
| 批次吞吐量（XP7、XP8） | ≤ 0.8 秒／張、重疊比 ≤ 0.7 | 使用者 → 20 張要等半分鐘以上，或匯出期間預覽卡住｜穩定性可靠性 | `test_export_batch_throughput`、`test_export_one_gpu_job_in_flight` |
| 核心方向（XP9） | 轉一次 | 直拍照 → apply 與匯出方向不一致｜邏輯核心 | `test_read_image_orientation_jpeg_tiff`、`test_export_orientation_jpeg` |

```text
facade 操作：export（第 8 個）｜ HTTP：POST /api/export ｜ CLI：export ｜ MCP：darkroom_export（工具清單最後）
MCP annotations：readOnlyHint false ｜ destructiveHint false ｜ idempotentHint false ｜ openWorldHint false
寫檔白名單：darkroom_app/services/export.py
檔名用完（reason）：{stem} 的匯出檔名已用到 ({n_max})，請清理匯出資料夾後再試 ｜ n_max＝9999
CLI 人看成功行：已匯出：{output_path}
吞吐量：20 張 6000×4000 JPEG → JPEG q92，平均 ≤ 0.8 秒／張；重疊比 ≤ 0.7；暖機 1 張不計
管線上限：GPU executor 內匯出工作 ≤ 1 ｜ 在途全解析度影像 ≤ 3 ｜ 整批後 memory_reserved ≤ 匯出前 + 256 MiB
核心補丁 K2：K2（2026-10-09，匯出合約 X6／XP9）`read_image` 讀 JPEG／TIFF 時依 EXIF Orientation 轉正像素（3／6／8 等於 PIL `ImageOps.exif_transpose`）；PNG 與 HEIC 行為不變；取代 K1 中「忽略 EXIF 方向」對 JPEG／TIFF 的部分。
```

## 條文補丁第 2 批（2026-10-09，主 session 裁決，開工前補；與條文同等效力，劃線與「取代」處以本批為準）
- [ ] XP10（寫檔，取代 XP5 的寫檔部分；依 `CONTRACT-write-guard.md` G8／G10 與其「後續三片」XP5 列）：`darkroom_app/services/export.py` 是 G10 白名單（`tests/test_layering.py` `SAFE_WRITE_USERS`）上唯一新增的模組（0 → 1，常數見下）；只有它可以 import `safe_write`。匯出一律先在記憶體裡編碼成位元組——JPEG：`cv2.imencode`，sRGB 描述檔（APP2 `ICC_PROFILE`）與 EXIF（APP1 `Exif`）插進位元組；TIFF 16-bit：自組 TIFF 位元組（像素、ICC 34675、Exif 子 IFD 34665、GPS 子 IFD 34853）——再呼叫 `safe_write.create_new(path, root=目的資料夾, data)`；`darkroom 匯出` 資料夾以 `safe_write.make_dirs(path, root=照片所在資料夾)` 建立；撞名靠 `create_new` 原樣拋出的 `FileExistsError` 換下一個序號（X9）。`darkroom_app/**` 禁用核心 `write_image`、`cv2.imwrite`、`.save(`、`.tofile(`，白名單模組也一樣（G10 原文不改；所以 PIL 寫進 `BytesIO` 也不用，JPEG 走 `cv2.imencode`）。**撤銷**：XP5「`services/export.py` 可用 `write_image`／`imwrite`」「`test_app_has_no_write_path` 與 L13 掃描放行 `services/export.py`」「只有 `services/export.py` 可出現寫入模式開檔、`os.replace`…」三句全部撤銷——`test_app_has_no_write_path`、L13 的 `write_image`／`imwrite` 掃描照舊不放行任何檔；`services/export.py` 自己也不得開檔寫入，`test_no_file_write_path_anywhere` 照樣掃它（G10：只有 `safe_write.py` 不掃）；XP5 的 `test_only_export_service_writes` 由 G10 的 `test_only_safe_write_writes` 取代。X10／X14 的「暫存檔」：本片不用暫存檔（`create_new` 直接建最終檔名，寫失敗時由它刪掉半份檔）。
- [ ] XP11（部分失敗，修訂 XP2／XP3／XP4）：批次裡只要有任何一筆 `ok:false`：CLI 結束碼 6，stdout 照樣輸出完整結果（`--json`：恰一行 `{"ok":true,"result":{"results":[…]}}`；不帶 `--json`：每筆一行），stderr 空；MCP `structuredContent` 恰為 `{"results":[…],"failed":n}`（n＝`ok:false` 的筆數，全部成功時也帶 `"failed":0`），`content` 的 text＝`structuredContent` 的 JSON，`isError` 仍為 false（不帶 `isError` 鍵）；HTTP 照舊 200 `{"results":[…]}`（形狀同 X1，不加 `failed`）。全部成功 → CLI 0。`failed` 只是從 `results` 數出來的格式欄位，由 MCP 入口計數，不進 service。請求層錯誤（XP2 invalid）照舊 400／2／`isError:true`。
- [ ] XP12（WG10(b) 收斂，修訂 G8）：`safe_write` 五個函式各加一個僅限關鍵字的參數 `preset_dir=None`（G8「公開恰 5 個函式」不變）。`ExportService` 由 composition 傳入「這次實際使用中的 preset 資料夾」（`build_facade` 用的那個 `Library.preset_dir`，CLI／MCP 的 `--preset-dir` 也一樣），每次呼叫 `safe_write` 都帶上；寫到它底下一律 `SafeWriteRefused`「refused: {path} is inside the preset folder」。`config.preset_dir()` 解析得到時也照查（兩個都查，只收緊）。`preset_dir` 沒傳、`config.preset_dir()` 又丟 `ConfigError` → `SafeWriteRefused`（句子見常數），不是 `ConfigError`。`SafeWriteRefused` 照 G8 不被 service 接住：整個 `export` 以未預期錯誤結束（HTTP 500／CLI 1／MCP -32603），已寫完的前面幾筆保留、不留半份檔。釘死：`test_safe_write_refusals` 加「config 指 A、傳入 B，寫到 B 底下被拒」「缺設定且沒傳 → SafeWriteRefused」；`test_export_refuses_preset_folder`（`dest_dir`＝使用中的 preset 資料夾 → 被拒、資料夾內容不變）。
- [ ] XP13（必要情境，加進 XP6 `tests/test_interface_parity.py`）：目的資料夾＝照片所在資料夾、而且同名檔已存在（`dest_dir`＝照片的資料夾，照片本身就是 `{stem}.jpg`）→ 新檔命名 `{stem} (2).jpg`，三個入口結果相同；匯出前後照片原檔 SHA-256 不變。每個 driver 各用自己的照片資料夾（XP6「各用自己的空 dest_dir」在本情境改為各用自己的照片資料夾）。
- [ ] XP14（ride-along，WG10 (c) ④，只收緊）：`tests/test_writeguard.py` 加一支釘死探針：以產品身分對**根目錄外的既有檔**呼叫 `_winapi.CreateFile(p, GENERIC_READ 0x80000000, 7, 0, OPEN_EXISTING 3, FILE_FLAG_DELETE_ON_CLOSE 0x04000000, 0)`（不帶 DELETE 位元）→ 必須被攔（違規表多一筆 `_winapi.CreateFile`），而且斷言檔案仍在、內容 SHA-256 不變。根目錄外的既有檔由 fixture 根內建好後暫時註銷那個根取得（只縮小可寫範圍，不是暫停守門），探針後重新登記再釋放。拿掉 `_writeguard.py` 的 `flags_attrs & _DELETE_ON_CLOSE` 判斷時這支必須變紅。
- [ ] XP15（重申 XP9）：X6 的 JPEG／TIFF 轉正改核心 `darkroom/_io.py` `read_image`；實作的那個 commit 同時在 `CONTRACT-core-library.md` 補丁區加「核心補丁 K2」一行（常數照抄 XP9 區塊）。

```text
G10 寫檔白名單（SAFE_WRITE_USERS）：("services/export.py",)
編碼：JPEG＝cv2.imencode＋APP1 Exif＋APP2 ICC_PROFILE ｜ TIFF＝自組 16-bit RGB（34675 ICC、34665 Exif、34853 GPS）｜ 寫檔＝safe_write.create_new(path, root=目的資料夾, data, preset_dir=使用中的 preset 資料夾)
結束碼：6 部分失敗（批次裡有任一筆 ok:false；stdout 照樣是完整結果，stderr 空）
MCP 部分失敗：structuredContent {"results":[…],"failed":n}（全部成功 failed 0）｜ isError false
SafeWriteRefused 新句（XP12）：refused: no preset folder is known, cannot protect it
XP14 探針：_winapi.CreateFile(p, 0x80000000, 7, 0, 3, 0x04000000, 0) 對根目錄外既有檔 → 攔、檔在、SHA-256 不變
```

## 條文補丁第 3 批（2026-10-09，主 session 裁決：commit 安全審查在 4117f0d 抓到的外部威脅，本片必修，封緘一併驗）
- [ ] XP16（跨站請求與 DNS rebinding，修訂 X1、XP1；App 外殼補丁 R10）：威脅＝使用者瀏覽器裡的任何網頁（不屬 WG14 的「意外寫入」）。舊行為：`server.py` 不看 `Host`、`Origin`、`Content-Type`，任何 Content-Type 的 body 都當 JSON 解析 → 外站可用 `fetch(…, {mode:"no-cors", body: JSON 字串})`（text/plain 屬 simple request、沒有 preflight）讓 App 讀任意路徑的照片並匯出到攻擊者指定的 `dest_dir`；加上 DNS rebinding（Host＝攻擊者網域）連 `/api/open`、`/api/preview` 的回應都讀得到。修法：(1) 所有路由（GET、POST 都算，含靜態檔與 `/`）先過 middleware：`Host` 必須恰為 `127.0.0.1:{port}` 或 `localhost:{port}`（{port}＝這個連線實際的本機埠，不分大小寫），否則 421＋常數句；(2) 帶 `Origin` 的請求，`Origin` 必須恰為 `http://127.0.0.1:{port}` 或 `http://localhost:{port}`，否則 403＋常數句（`Origin: null` 也拒）；(3) 所有 POST 的 `Content-Type` 媒體類型必須是 `application/json`（可帶 charset 等參數），否則 415＋常數句——跨站請求因此一定觸發 preflight，伺服器不回任何 CORS 標頭，瀏覽器就擋下；(4) HTTP 的 `/api/export` 不接受 `dest_dir`：body 帶了 `dest_dir` 鍵（任何值，含 null）→ 400＋常數句，屬入口自己的規則（同 L7「入口自己的錯誤留在入口」），不呼叫 facade；前端本來就不選資料夾（X8），`dest_dir` 只開放給 CLI 與 MCP。XP6 的 dest_dir 情境（相對路徑、不存在）與 XP13（目的資料夾＝照片資料夾）改為只跑 CLI／MCP；HTTP 的匯出情境改用預設資料夾（`<照片資料夾>/darkroom 匯出`）。(5) 前端 `app.js` 的 `api()` 對有 body 的請求一律帶 `Content-Type: application/json`。檢查順序：Host → Origin → Content-Type → 路由本身。(6) 釘死：`tests/test_http_security.py`——錯的 Host（`evil.example:{port}`、`127.0.0.1:{別的埠}`）、`text/plain` 的 POST（`/api/export`、`/api/open`、`/api/preview`）、外站 Origin（`http://evil.example`、`null`）、HTTP 帶 `dest_dir`，四種都被拒且什麼都不寫、不讀照片（facade 沒被呼叫）；正常流程（同源 Origin、`localhost:{port}`、`application/json; charset=utf-8`）照常 200。`test_http_golden` 只為這條新增斷言（Host／Origin／Content-Type 三種拒絕的狀態碼與句子），既有斷言一條不改。
```text
Host 錯（421）：{"error": "request refused: Host must be 127.0.0.1:{port} or localhost:{port}"}
Origin 錯（403）：{"error": "request refused: cross-site Origin {origin}"}
Content-Type 錯（415）：{"error": "request refused: POST body must be application/json"}
HTTP 帶 dest_dir（400）：{"error": "dest_dir is not accepted over HTTP (use the CLI or MCP)"}
檢查順序：Host → Origin → Content-Type → 路由
```

## 實作補丁（2026-10-09，實作時的決定與量測；只收緊或補常數，與條文同等效力）
- XP17（單筆失敗的形狀，補 X1／X12 沒釘的句子）：每筆失敗一律 `{"ok":false,"source":S,"error":"匯出失敗：{S}：{reason}"}`；S＝照片檔名（basename）；`image_id` 未知時 S＝傳入的 image_id 字串、reason「unknown image_id」；沒有 path 或不是物件時 S＝空字串。item 同時有 `image_id` 與 `path` 時以 `image_id` 為準。item 只接受 `image_id`、`path`、`preset_id`、`strength`、`overrides` 五個鍵，多一個鍵 → 該筆 `ok:false`（打錯鍵名不會默默匯出沒套 preset 的檔）。新句：`each item must be an object {image_id | path, preset_id, strength, overrides}` ｜ `unknown item key {key!r} (allowed: image_id, path, preset_id, strength, overrides)`。quality 的句子 `{quality}` 用 Python `str()`（JSON true → `True`、92.0 → `92.0`，非整數一律拒）。CLI `--quality` 不是整數時原字串交給 service 判斷（三入口同句）。
- XP18（描述檔，X5 實測）：PIL `ImageCms.createProfile("sRGB")`（LittleCMS 內建）用 `darkroom._icc` 讀回時純青 (0,1,1) 的紅色得 0.0025，超過 X5 的 1e-3；改由 `darkroom_app/encoding.py` 自組 ICC v4 矩陣／曲線 sRGB 描述檔（ICC 標準 D50 colorants、parametricCurveType 3、Bradford chad），每次位元組相同，誤差 3.4e-4；LittleCMS 讀得進去、轉回其內建 sRGB 8-bit 差 0。
- XP19（方向，X6 實測）：OpenCV 5.0.0 的 TIFF 解碼器不管旗標都已依 Orientation 轉正（1～8、8／16-bit 都等於 `exif_transpose`），所以核心只轉 JPEG（見核心 K2 補註）；X6 的 TIFF 部分原本就成立。
- XP20（EXIF 細節，X7）：輸出 EXIF 一律 little-endian 重組；來源 IFD0 的影像結構標籤（尺寸、壓縮、strip、YCbCr、XMP 700、ICC 34675、IFD1 指標等）不複製；Interop 子 IFD 保留；JPEG 的 APP1 超過 65533 位元組時先丟 MakerNote，仍超過就不帶 EXIF（不報錯）。JPEG 段落順序 SOI、APP0 JFIF、APP1 Exif、APP2 ICC。TIFF：每 16 列一個 strip、無壓縮、SampleFormat 1、Orientation 1。
- XP21（GPU，XP7）：整批結束後（與 OOM 之後）在 GPU executor 上呼叫 `torch.cuda.empty_cache()`（不是 `synchronize`），`memory_reserved` 回到匯出前 + 256 MiB 以內（`test_export_releases_memory`）。`SafeWriteRefused` 由寫檔執行緒往外拋，整批結束時以未預期錯誤離開（XP12）。
- XP22（XP8 實測，2026-10-09 GPU 閒置、`tools/bench_export.py` 與 `test_export_batch_throughput` 各一次）：0.392 秒／張（門檻 0.8）、重疊比 0.557（門檻 0.7）；每段中位數 讀檔 0.370、渲染 0.252、編碼寫檔 0.077 秒；瓶頸是讀檔（cv2 解碼＋轉 float），不需 profile、不需 Rust。
- XP23（既有測試改動逐處紀錄）：`test_layering`（白名單 0→1、services 檔案集合加 `export.py`、操作清單加 `export`、export 工具 annotations、三個 controller 的 export 翻譯測試）、`test_app_mcp`（工具清單加 `darkroom_export`、它的 annotations）、`test_http_golden`（路由 9→10，測試名改 `test_exactly_ten_routes`；新增 `TestGoldenCrossSite` 三條拒絕斷言，既有斷言不動）、`test_app_server.test_server_never_writes`（加匯出情境，只准新增到預設匯出資料夾）、`test_interface_parity`（export driver、`test_export_parity`、`test_cli_mcp_never_write` 加匯出情境）、`test_writeguard`（XP12 的 preset_dir 拒絕、XP14 探針；`refused()` 小幫手接關鍵字參數）、`_fakes.FakeDarkroom.export`、`test_app_frontend`（R6／H11 保護清單加三個控制項、X13 結構測試）、`tests/js/test_logic.cjs`（X13）。新增：`test_core_orientation.py`、`test_export.py`、`test_http_security.py`。

## 封緘第 1 次派遣處置紀錄（2026-10-09；依 Loose-Criterion Escalation／R10，與條文同等效力）
- XP24（F4，R10 有證據的偏離，記錄）：X4「PIL、tifffile、cv2 三者讀回值相同」對 PIL 不成立——PIL 12.3.0 把 16-bit RGB TIFF 開成 8-bit `RGB`（實測 `[3007 4007 5007]` → `[11 15 19]`＝高位元組）。改為：tifffile 與 cv2 逐值相同；PIL 讀得開、尺寸正確、像素＝16-bit 值的高位元組。釘死：`test_export_tiff_16bit_readers_agree`（直接斷言 mode `RGB`、uint8、高位元組）。
- XP25（F5，跨 UI）：「已匯出：{output_path}」與「匯出失敗：{file_name}：{reason}」在 Python（`cli.EXPORTED`、`messages.EXPORT_FAILED`）與 JS（`logic.js` `exportDone`／`exportFailed`）各一份，跨語言無法共用 helper；改由一支測試把兩邊範本逐字對齊（`test_exported_sentence_same_in_cli_and_page`），兩條真實呼叫路徑各自釘死：CLI `test_cli_export_json`、頁面 `test_export_controls`（`exportPhoto` 內的兩個 `toast(...)` 呼叫與忙碌文字逐字比對；F3 探針「成功句當失敗句用」重放即紅）。
- XP26（F1，X1／X12 收緊）：讀檔階段（`read_image`＋`read_exif`）丟出任何 `Exception`——不只 `ValueError`／`OSError`，例如 OpenCV 對受損 TIFF 丟的 `cv2.error`——都只讓該筆 `ok:false`，reason＝單行 `str(e)`；其他筆照常。釘死：`test_unexpected_read_error_fails_one_item`。
- XP27（F2，X9 收緊）：同一份清單裡同 stem 的照片，檔名一律依 items 順序編號（先到的 item 拿 `{stem}`、下一個拿 `{stem} (2)`…），與哪一張先編碼完無關；編碼仍在兩條寫檔執行緒平行，只有「取檔名＋建檔」依序。釘死：`test_same_stem_in_one_list`（讓第一張故意慢 0.3 秒、重複 3 輪）。
- XP28（F6，覆蓋補強）：EXIF 測試補 little-endian（II）來源、Interop 子 IFD 保留、MakerNote 保留，以及 APP1 超過 64 KB 時丟 MakerNote（`test_export_exif_little_endian_interop_and_maker_note`）；核心 K2 補 II 方向 1～8（`test_read_image_orientation_jpeg_tiff`）。

## 封緘第 2 次派遣（複驗）處置紀錄（2026-10-09）
- XP29（N1，穩定性：第 1 輪 F2 修正帶進的退化，修正並釘死）：編碼階段丟出 `ValueError`／`OverflowError` 以外的例外（例如 `cv2.error`）時，那一號從沒取檔名，`_Turns` 的序號不再前進，8 張以上的批次永久卡死。改為：編碼的任何 `Exception` 都只讓該筆 `ok:false`（「渲染失敗：{detail}」），而且寫檔執行緒不論怎麼離開都保證讓自己那一號過去（沒取過檔名就空轉一次）。釘死：`test_encode_error_neither_hangs_nor_stops_the_batch`（8 張、第 1 張編碼丟 `cv2.error`，60 秒內結束、只 1 筆失敗、其餘 7 張寫出）。
- N2（測試空心，已修）：`test_same_stem_in_one_list` 末段拿自己的雜湊比自己，刪除；檔名順序的斷言保留（已證明會紅）。
