# CONTRACT — darkroom S2「匯出完整版與能力偵測」（格式／尺寸／中繼資料／輸出銳利化／匯出預設、preset 匯出成 .xmp、export 預設用已存編輯、資料區位置、能力偵測）
> STATUS: sealed（2026-10-10）— 決定由主 session 裁決（2026-10-10）；E1～E34＋IP1～IP13＋E12a／E15a 符合；2 次派遣：第 1 次 7 項 findings（F1 單張匯出存檔失敗會默默匯出原圖、F2 一筆壞預設清空全部、F3 勾選框未釘、F4 群組下載超過 500、F6 版本不支援無判官已修並各附釘死測試，F5 IP3／IP4／IP10 依 R10 判符合，F7 備註）；複驗 3 支舊探針重發仍攔、13 支新判官出生證明各紅，探針 19/19 被攔、全數逐位元組還原；常數零漂移；複驗新發現 3 項只記錄
<!-- 基準數字（主 session 2026-10-10 確認：S1 已合併 main 0f55a67）：facade 操作 27、MCP 工具 27、HTTP 路由 29、G10 白名單 4；本合約一律寫成實數 -->

## 目標
使用者只專注修圖。按「匯出」跳出一個對話框，預設值就能直接按下去：JPEG／PNG／TIFF（8／16-bit）／WebP、JPEG 可限檔案大小、只縮不放的尺寸（長邊、短邊、寬、高、百萬像素、百分比）、中繼資料三選一外加「移除 GPS」、螢幕／霧面紙／光面紙三種輸出銳利化各三檔；常用的組合存成具名「匯出預設」一鍵套用。export 沒給 preset／強度／微調時，自動用照片庫裡這張存好的編輯，沒有編輯就輸出原圖。preset 庫裡的 preset（含自存的）可以匯出成 Lightroom 讀得到的 `.xmp`，永不覆蓋。資料區預設位置照各平台慣例；啟動時偵測 GPU、HEIC、WebP、照片庫資料區、preset 庫位置、語意索引、1Password 登入狀態，偵測不到的功能安靜關掉，三個入口給同一句中文原因。照片與買來的 preset 照舊一個位元組都不動。

## 前提（Premises）
- Q1 已驗（`darkroom_app/services/export.py`、`encoding.py`）：現行 `ExportService.export(items, format, quality=None, dest_dir=None)`；`FORMATS = {"jpeg": (".jpg", 8), "tiff": (".tif", 16)}`；JPEG 走 `cv2.imencode`＋自插 APP1／APP2，TIFF 走自組位元組（`encoding.tiff_bytes`）；寫檔只經 `safe_write.create_new`（XP10）。G10 禁 `darkroom_app/**` 用 `.save(`／`.tofile(`／`imwrite`，所以新格式也只能 `cv2.imencode`＋自組容器位元組。
- Q2 已驗（`services/export.py:_job`）：item 沒有 `preset_id` 時 `params=None`，`strength` 預設 100、`overrides` 預設空 → 輸出＝原圖的最終參數（恆等）。所以「沒編輯就輸出原圖」與現行行為逐位元組相同，E15 只在「這張有存好的編輯」時改變結果。
- Q3 已驗（`config.py:data_dir`）：只認設定鍵 `data_dir` 與 `LOCALAPPDATA`；非 Windows 沒有 `LOCALAPPDATA` → `ConfigError`（PL1 常數句）。
- Q4 已驗（`composition.py:build_facade`、S1 審查 findings `[0]`）：明確指定 `--preset-dir` 時庫根＝`dirname(preset_dir)`（KP2），沒有任何檢查擋它是照片資料夾；`[3]` 照片庫資料區沒有啟動偵測、`ConfigError` 變 HTTP 500；`[11]` 照片在 preset 資料夾內時 `SafeWriteRefused` 讓整批匯出以未預期錯誤中止；`[12]` 相對 `--data-dir` 先建資料夾再被 safe_write 拒；`[13]` 壞 JSON 設定檔變 traceback。
- Q5 已驗（`services/semantic_index.py:155`、`CONTRACT-write-guard.md` WG15）：產品唯一能開 `op` 的模組是 `services/semantic_index.py`，形狀寫死 `op read <op://…>` 恰 3 參數；現行逾時句「op read 逾時」看不出是沒登入。
- Q6 已驗（`E:/llm/artifact/11_preset/xmp`，2026-10-10 grep）：1466 個買來的 xmp 全部帶 `crs:UUID` 與 `crs:SupportsAmount`；自存 xmp（K13 常數「自存 xmp」）兩者都沒有。
- Q7 已驗（`static/index.html:57-60`、`app.js:1108`）：工具列有 `#export-format`（JPEG／TIFF）、`#export-quality`、`#export-btn`；縮圖格「匯出所選」先逐張 `GET /api/edit` 再組 items（E15 之後可以只送路徑）。
- Q8 未驗、不入條文為事實：(a) OpenCV 5.0.0 的 `cv2.haveImageWriter(".webp")` 在專用 Python 上為 True、16-bit PNG `imencode` 可用——開工第一步實測記成實作補丁；(b) `op whoami` 在 1Password App 整合模式、App 鎖住時是回非 0 還是等解鎖（會等就靠 E24 的逾時句）；(c) 自存 preset 補上 E16 的屬性後真的 Lightroom 讀得進去——使用者已退訂，只能以「結構與買來的 xmp 同形」驗收，Lightroom 實機驗證記為已知缺口。
- Q9 推估、不入條文為事實：輸出銳利化（E10）沒有 Lightroom 參考渲染，常數表是初值；驗收只斷言公式與單調性，不斷言「像 Lightroom」。

## 可斷言條文

### 一、匯出設定（一份規則，三入口共用）
- [ ] E1（設定物件、預設值與優先序）：匯出設定恰為 9 個鍵 `format`、`bit_depth`、`quality`、`max_kb`、`resize`、`metadata`、`remove_gps`、`sharpen`（加上 export 自己的 `dest_dir`，不屬匯出預設）；預設值見常數「預設值」。唯一一份正規化函式 `services/export.py` `normalize_settings(given, preset=None)`：每個鍵取「這次明確給的值（不是 None）」→「匯出預設裡的值」→「常數預設」；`bit_depth` 沒給時依格式取預設（jpeg／webp／png 8、tiff 16）；結果一律 9 鍵齊全。export、`save_export_preset`、前端顯示用的摘要都吃這份結果（前端只有顯示用鏡像 `L.exportSummary`，不驗證）。禁止第二份驗證規則。釘死：`test_normalize_settings_defaults_and_precedence`（空 → 常數預設；只給 tiff → bit_depth 16；預設＋明確值 → 明確值贏）。
- [ ] E2（請求層驗證順序與句子）：`export` 依序檢查 items（X1 句子不變）→ `export_preset`（E14）→ format → bit_depth → quality → max_kb → resize → metadata → remove_gps → sharpen → dest_dir（X1 句子不變）；任何一項不合 → invalid、常數句、什麼都不寫、不讀照片。格式合法但功能被偵測關掉（WebP，E23）→ unavailable、該功能的關閉原因句。`quality` 對 png／tiff 照 X13 忽略（不報錯）；`bool` 一律不算數字（同 XP17）；句子裡的值用 Python `str()`（同 XP17）。釘死：`test_export_settings_errors`（常數表每一句各一案例、且照片資料夾與 dest_dir 前後快照相同）。
- [ ] E3（寫檔守門不放寬）：新格式、縮放、銳利化、中繼資料全部在記憶體完成，最後照舊一次 `safe_write.create_new(path, root=目的資料夾, data, preset_dir=…)`（XP10／XP12）；`darkroom_app/**` 照舊禁 `write_image`、`imwrite`、`.save(`、`.tofile(`（PIL 不寫任何東西，含 `BytesIO`）。G10 白名單的變化只有 E12 一項（D4 已裁決）。釘死：既有 `test_only_safe_write_writes`、`test_no_file_write_path_anywhere`、`test_layering` `SAFE_WRITE_USERS` 常數。

### 二、格式
- [ ] E4（PNG）：`format:"png"`，副檔名 `.png`，`bit_depth` 8 或 16（預設 8，D14 已裁決）；`cv2.imencode(".png", …, [IMWRITE_PNG_COMPRESSION, 3])` 之後在 IHDR 之後、第一個 IDAT 之前插入 `iCCP`（描述檔名 `sRGB`、zlib 壓縮的 XP18 sRGB 描述檔）與 `eXIf`（內容＝`encoding.exif_tiff_bytes` 的 TIFF 結構 EXIF，E9 決定有沒有）；不寫 `sRGB`、`gAMA`、`tEXt` 等其他輔助區塊；每個區塊 CRC 正確。讀回：cv2 `IMREAD_UNCHANGED` 得 uint8／uint16 三通道、值＝`render_full` 量化結果（8-bit 差 ≤ 1、16-bit 差 ≤ 1/65535，同 X3）；PIL `Image.open` 的 `info["icc_profile"]` 用 `darkroom._icc` 判為 sRGB（X5 判準）、`getexif()` 的標籤符合 E9。釘死：`test_export_png_8_and_16`、`test_export_png_chunks`。
- [ ] E5（TIFF 8／16-bit）：`format:"tiff"` 的 `bit_depth` 8 或 16（預設 16，X4 不變）；8-bit 走同一個自組 TIFF 函式（BitsPerSample 8、其餘 XP20 結構不變），副檔名都是 `.tif`。8-bit 讀回：PIL、tifffile、cv2 三者值相同（8-bit 沒有 XP24 的 PIL 例外）。釘死：`test_export_tiff_8bit_readers_agree`；16-bit 既有 `test_export_tiff_16bit_readers_agree` 不改。
- [ ] E6（WebP）：`format:"webp"`，副檔名 `.webp`，只有 8-bit、有損、`quality` 1～100（預設 92）；`cv2.imencode(".webp", …, [IMWRITE_WEBP_QUALITY, q])`（q 永遠 ≤ 100，不開無損）後重包成擴充格式：`RIFF` → `VP8X`（ICC 旗標，有 EXIF 時加 EXIF 旗標，canvas 寬高－1 各 24 位元）→ `ICCP` → 原本的 `VP8 ` 區塊 →（有的話）`EXIF`；RIFF 長度與奇數補位正確。寬或高 > 16383 → 該筆 `ok:false`、reason＝常數「WebP 太大」。讀回：PIL 開得起來、尺寸正確、`info["icc_profile"]` 判為 sRGB、`getexif()` 符合 E9；cv2 解碼值與「同品質直接 `imencode` 再解碼」逐值相同（重包不動到影像資料）。釘死：`test_export_webp_container`、`test_export_webp_too_large`。
- [ ] E7（JPEG 檔案大小上限）：`max_kb` 只對 `format:"jpeg"`（其他格式給了 → invalid 常數句）；整數 10～1048576，單位 1 KB＝1024 位元組（D13 已裁決）。計算的是**完整輸出檔**的位元組（含 APP1 EXIF、APP2 ICC）。規則：先用 `quality` 編碼，≤ 上限就用它；否則在 `[1, quality−1]` 二分搜尋最大的、整檔 ≤ 上限的品質（每張最多 8 次編碼）；品質 1 仍超過 → 該筆 `ok:false`、reason＝常數「壓不下」（不寫任何檔）。量化表仍等於 PIL 同品質的量化表（X4 判準，品質＝實際採用的那個）。釘死：`test_export_max_kb`（輸出 ≤ 上限、且品質再 +1 就會超過，或已是 `quality`）、`test_export_max_kb_impossible`。

### 三、尺寸、中繼資料、銳利化
- [ ] E8（只縮不放）：`resize` 為 null 或 `{"mode", "value"}`，mode 恰為 `long_edge`、`short_edge`、`width`、`height`、`megapixels`、`percent`；以**轉正後**寬高 (w, h) 計算縮放比 s：long_edge＝value/max(w,h)、short_edge＝value/min(w,h)、width＝value/w、height＝value/h、megapixels＝sqrt(value×10⁶/(w×h))、percent＝value/100。s ≥ 1 → 不縮（輸出＝原尺寸，不報錯）。s < 1 → 被指定的那一邊恰等於 value（megapixels、percent 沒有指定邊），另一邊（或兩邊）＝`floor(邊×s + 0.5)`，最小 1；megapixels 兩邊改用 `floor(邊×s)` 保證 w′×h′ ≤ value×10⁶。縮放用 `cv2.resize(…, INTER_AREA)`，在渲染之後、銳利化與量化之前（D2 已裁決）；EXIF `PixelXDimension`／`PixelYDimension` 改成輸出寬高（X7）。Python 與前端用同一份案例表 `tests/cases/s2_resize_cases.json`（同 R7 做法：`test_resize_shared_cases` 與 `tests/js/test_logic.cjs` 的 `L.resizeTarget`），至少涵蓋六種 mode、直拍（方向 6）、s ≥ 1、s 剛好 1、1 像素邊。釘死：`test_export_resize_pixels`（輸出＝`cv2.resize(render_full(...), (w′,h′), INTER_AREA)` 量化，8-bit 差 ≤ 1）。
- [ ] E9（中繼資料）：`metadata` 恰為 `all`、`copyright`、`none`；`remove_gps` 布林。`all`＋`remove_gps:false`＝X7 原樣（含 GPS）。`all`＋`remove_gps:true`＝X7 但輸出沒有 GPS 指標（34853）與 GPS 子 IFD，其餘標籤與 X7 相同。`copyright`：來源 IFD0 有 `Copyright`（33432）時，輸出 EXIF 恰為 IFD0 兩個標籤 `Orientation`=1 與 `Copyright`（值逐位元組相同），沒有 Exif／GPS／Interop 子 IFD、沒有 MakerNote；來源沒有版權 → 輸出不帶 EXIF。`none`：輸出不帶任何 EXIF（JPEG 沒有 APP1、PNG 沒有 `eXIf`、WebP 沒有 `EXIF` 與 EXIF 旗標、TIFF 沒有 34665／34853，TIFF 自己的影像結構標籤照 XP20）。`copyright`／`none` 時 `remove_gps` 不影響結果（不報錯）。三種都照舊嵌入 sRGB 描述檔（X5：描述檔是顏色、不是中繼資料），都不寫 XMP、IPTC。釘死：`test_export_metadata_modes`（四種格式 × 三種 metadata ＋ remove_gps，逐一列出標籤集合）。
- [ ] E10（輸出銳利化）：`sharpen` 為 null 或 `{"target","amount"}`，target 恰為 `screen`、`matte`、`glossy`，amount 恰為 `low`、`standard`、`high`；(σ, a) 見常數表。作用在縮放後、量化前的 sRGB 編碼值 x（0～1 浮點，CPU、寫檔執行緒）：Y＝0.2126R＋0.7152G＋0.0722B，x′＝clip(x＋a·(Y − GaussianBlur(Y, σ)), 0, 1)，三通道加同一個差值（不產生色邊）。null → 輸出像素與不銳利化逐位元組相同。釘死：`test_output_sharpen_formula`（與測試內獨立寫的 numpy 參考實作差 ≤ 1 個 8-bit 碼）、`test_output_sharpen_monotonic`（同一 target：低 < 標準 < 高 的拉普拉斯變異數；同一 amount：screen < glossy < matte）、`test_output_sharpen_off_is_identity`。
- [ ] E11（管線順序與效能）：每筆順序固定：讀檔 → GPU 渲染（全解析度，XP7 不變）→ 縮放 → 銳利化 → 量化與編碼（含大小上限搜尋）→ 取檔名＋建檔（XP27 順序）。縮放與銳利化在寫檔執行緒（GPU executor 之外）。XP8 預設情境（JPEG q92、無縮放、無銳利化）的門檻與量測不變；`tools/bench_export.py --s2` 加一個情境：同 20 張 24MP、`resize long_edge 2048`＋`sharpen screen standard`＋`max_kb 800`，平均 ≤ 0.8 秒／張（判斷 GPU 忙碌的規則同 XP8／R1）。達不到 → 先 profile 記進本合約，不放寬。釘死：`test_export_batch_throughput`（既有）、`test_export_batch_throughput_s2`。

### 四、匯出預設（存成具名預設、套用）
- [ ] E12（儲存）：匯出預設存在 `data_dir/export-presets.json`，內容恰為常數「匯出預設 schema」（`presets` 依名稱 casefold 排序，值是 E1 正規化後的 9 鍵）；UTF-8 無 BOM。寫入只在新模組 `darkroom_app/services/export_presets.py`（G10 白名單 4→5，D4 已裁決），全走 `safe_write`（root＝data_dir、帶 `preset_dir=`）：`create_new(export-presets.json.tmp-{pid}-{12 hex})`＋`replace_into`，鎖＝`open_lock(export-presets.json.lock)` 等 5 秒 → conflict 常數句；失敗一律 `remove(tmp)`。讀：檔不存在＝空；壞 JSON 或 schema 不對 → 讀取當成空、下一次寫入前先 `create_new` 留一份逐位元組相同的 `export-presets.json.bad-{unix秒}`（同秒 `-{n}`，同 SIP7）。data_dir 的位置規則與 unavailable 句子照 PLP1／PLP17（資料區不能在照片或 preset 資料夾底下）。釘死：`test_export_presets_storage`（原子寫、壞檔保留、鎖 conflict、safe_write 根）。
- [ ] E13（三個操作）：`list_export_presets()` → `{"presets":[{"name","settings"}…]}`；`save_export_preset(name, settings)`：name 去頭尾空白、移除控制字元後 1～60 字，否則 invalid；settings 經 E1／E2 同一份驗證（錯誤句相同；`dest_dir` 不屬匯出預設，帶了 → invalid 常數句）；同名（casefold）→ 取代（D5 已裁決），回 `{"name","settings","previous":舊 settings 或 null}`；新增後超過 200 個 → invalid。`delete_export_preset(name)` → 回 `{"name","settings"}`（被刪的內容，給「復原」用：再 save 一次就回來）；不存在 → not_found 常數句。三者都不碰照片、不碰 GPU、不 import torch／cv2（`sys.modules` 斷言同 L9）。釘死：`test_export_presets_ops`（存→列→同名取代回 previous→刪→用回傳值存回，內容逐位元組相同）。
- [ ] E14（套用）：`export(..., export_preset=name)`：先找預設（找不到 → not_found 常數句、什麼都不做），再照 E1 優先序與明確給的參數合併；三入口同名參數（CLI `--export-preset NAME`、MCP `export_preset`、HTTP body `export_preset`）。釘死：`test_export_with_export_preset`（預設是 png 16-bit＋long_edge 1000，明確給 `format:"jpeg"` → JPEG 8-bit、長邊 1000）。

### 五、export 預設用已存編輯（相容補丁見 XP30）
- [ ] E15（已存編輯）：item **沒有** `preset_id`、`strength`、`overrides` 三個鍵（鍵不存在；值為 null 算「有給」）時，參數來自照片庫：算指紋（`photo_library.fingerprint`）→ 讀編輯 → 有編輯：`effective_params(Params.from_dict(edit.preset.params) 或 None, validate_strength(edit.strength), validate_overrides(edit.overrides))`（同 PLP6 `save_edit_as_preset` 的算法，快照優先、preset 是 `changed`／`missing` 也照用快照）；沒有編輯 → 原圖（`effective_params(None, 100, {})`，與現行逐位元組相同，Q2）。照片庫讀不到（資料區 unavailable、編輯檔壞掉、版本不支援）→ 該筆 `ok:false`、reason＝那句原樣（**不得**默默改匯出原圖）。三個鍵有任一個 → 照舊 X1／PLP5 的規則（`preset_id:null` 明確表示「原圖＋給的微調」）。`image_id` item 同樣適用（用該 image 的 path 算指紋）。結果每筆多一個鍵 `"params_from"`：`"edit"`／`"original"`／`"request"`（D1 已裁決）。釘死：`test_export_uses_saved_edit`（有編輯 → 像素＝以同參數 preview 管線全解析度渲染；同一張再給 `preset_id:null` → 原圖）、`test_export_saved_edit_snapshot_after_preset_changed`、`test_export_saved_edit_library_unavailable`。

### 六、preset 匯出成 .xmp
- [ ] E16（`preset_files(preset_ids)`，唯讀）：`preset_ids` 是 1～500 個字串的陣列，否則 invalid 常數句；回 `{"files":[…]}` 與輸入同長同序，每筆 `{"ok":true,"preset_id","file_name","data_base64"}` 或 `{"ok":false,"preset_id","error"}`（未知 id → `unknown preset {pid}`，L3 原句）。內容：買來的與匯入的 preset（id 不以 `user:` 開頭）＝ preset 資料夾／`import/` 裡的原檔位元組原樣（SHA-256 等於索引記錄的 `sha256`；D6 已裁決）；自存 preset（`user:`）＝庫裡的檔，在 `crs:PresetType="Normal"` 之後補上常數「Lightroom 必要屬性」中缺的那幾個（`crs:UUID`＝該檔 SHA-256 前 32 位大寫 hex，同一份內容每次相同），其餘位元組不動。`file_name`＝K14 `safe_stem(顯示名稱)`＋`.xmp`；同一次清單內撞名（casefold）依序加 ` (2)`、` (3)`…。不寫任何檔、不 import torch／cv2。釘死：`test_preset_files_bytes`（買來的位元組相同；自存的 `load_preset` 讀回 values／curves／masks 與庫裡的相等、必要屬性各恰一次、UUID 兩次匯出相同）、`test_preset_files_names`。
- [ ] E17（`export_preset_files(preset_ids, dest_dir)`，CLI／MCP 寫檔）：preset_ids 規則同 E16；`dest_dir` 必填、必須是已存在的絕對路徑資料夾（句子沿用 X1「找不到匯出資料夾：{dest_dir}」），而且 `realpath` 不得在使用中的 preset 資料夾或 preset 庫根之內（→ invalid 常數句，事先擋下，不靠 `SafeWriteRefused`）。每個檔 `safe_write.create_new(dest_dir/{file_name}, root=dest_dir, data, preset_dir=…)`，已存在（不分大小寫）→ 依序 `{stem} (2).xmp`… 到 9999（XP2 句型「檔名用完」）；永不覆蓋、不建資料夾。寫入在 `services/preset_library.py`（已在 G10 白名單，不增項）。回 `{"results":[{"ok":true,"preset_id","output"}｜{"ok":false,"preset_id","error"}…]}`；部分失敗照 XP11（CLI 結束碼 6、MCP `failed`）。HTTP 不收 dest_dir：`POST /api/preset-library/export` 一律 400 常數句、不呼叫 facade（同 SI11 做法）；網頁改用 E16＋瀏覽器下載（D7 已裁決）。釘死：`test_export_preset_files_never_overwrite`、`test_export_preset_files_refuses_preset_folder`、`test_preset_export_refused_over_http`。

### 七、資料區與 preset 庫位置
- [ ] E18（data_dir 平台慣例，修訂 PL1／PLP8）：`config.data_dir(config_file=None, env=None, platform=None, home=None)`：設定鍵 `data_dir`（非空字串）優先；否則依 `platform`（預設 `sys.platform`）：`win32` → `{LOCALAPPDATA}/darkroom`；`darwin` → `{home}/Library/Application Support/darkroom`；其他 → `XDG_DATA_HOME` 非空且是絕對路徑時 `{XDG_DATA_HOME}/darkroom`，否則 `{home}/.local/share/darkroom`（`home` 預設 `os.path.expanduser("~")`，展開失敗或不是絕對路徑＝沒有）。找不到：Windows 照 PL1 原句逐字不變；其他平台用常數「data_dir 找不到（非 Windows）」。釘死：`test_data_dir_platform_defaults`（注入 platform／env／home，七種情況：設定鍵、win32 有／無 LOCALAPPDATA、darwin、linux 有 XDG、XDG 為相對路徑、無 XDG）。
- [ ] E19（相對路徑與壞設定檔，收 S1 findings [12]／[13]，D11 已裁決）：設定鍵 `data_dir`／`preset_dir`／`preset_library_dir` 是相對路徑時以設定檔所在資料夾為基準轉成絕對路徑；CLI／App 的 `--data-dir`、`--preset-dir` 相對路徑以目前工作目錄 `abspath`；轉換在建任何資料夾之前。`config._read` 遇到 JSON 或編碼錯誤 → `ConfigError`（常數「設定檔壞了」，含檔名、行、欄），所以 App 與 CLI 都是「darkroom：{e}」一行、結束碼 2（L9），不是 traceback。釘死：`test_relative_data_dir_is_made_absolute`（不留空資料夾）、`test_bad_config_json_is_config_error`。
- [ ] E20（preset 庫位置偵測，收 S1 finding [0]，範圍D9 已裁決）：啟動時（`build_facade` 之後第一次 `capabilities()`，也就是 App 就緒前與 CLI／MCP 第一次寫庫前）判斷「庫根落在照片資料夾裡」：從 `realpath(庫根)` 往上逐層，任何一層的**第一層**有副檔名在 `formats.PHOTO_EXT` 的檔案 → 成立（草稿值：跳過磁碟根目錄與使用者家目錄本身，D9 已裁決）。成立時 preset 庫的所有寫入操作（rename_preset、move_preset、set_favorite、create_group、rename_group、import_presets、save_user_preset、rebuild_library、save_edit_as_preset、semantic_build 的寫索引）在寫之前一律 unavailable、常數「preset 庫在照片資料夾裡」句、什麼都不寫；讀取類（list、groups、show、preset_files）照常。偵測只用 `os.scandir` 讀名稱、不開任何檔、不寫。釘死：`test_library_root_in_photo_folder_disables_writes`（庫根本身有 jpg、庫根上一層有 jpg、兩者都沒有三種；成立時 9 個寫入操作同句、庫根快照不變、讀取類照常）。
- [ ] E21（照片在 preset 資料夾裡的匯出，收 S1 finding [11]，D11 已裁決）：`dest_dir` 為 None、而且照片的 `realpath(dirname)` 在使用中的 preset 資料夾或庫根之內 → 該筆在 `_job` 階段就 `ok:false`、reason＝常數「照片在 preset 資料夾裡」，不渲染；其他筆照常（X1「一筆失敗不影響其他筆」恢復成立）；`safe_write` 照舊兜底。釘死：`test_export_photo_inside_preset_folder_fails_one_item`（6 張中 1 張在 preset 資料夾：5 張寫出、1 筆該句、結束碼 6）。

### 八、能力偵測
- [ ] E22（操作 `capabilities(refresh=False)`）：回 `{"features":{…}}`，鍵恰為常數「能力項目」7 個、依此順序，每個值恰為 `{"available": bool, "reason": str|null}`（available 為 true 時 reason 為 null）。結果在程序內快取，`refresh=True` 才重測。偵測不寫任何檔、不碰照片、不連網（`op whoami` 例外：見 E24）；全部偵測總時間上限 = 1Password 逾時 10 秒＋其他項 ≤ 2 秒。App：`start()` 在背景執行緒先跑一次，不延後「darkroom 已啟動」那一行（B2）；前端就緒後 `GET /api/capabilities`。可注入：`build_facade(..., detect=None)`（dict，每項一個偵測函式），測試一律注入。釘死：`test_capabilities_shape_and_cache`、`test_capabilities_never_write`（write-guard 全程）、`test_app_ready_line_not_delayed_by_detection`。
- [ ] E23（各項的判準與「關掉」的意思）：
  - `gpu`：`torch.cuda.is_available()`；false → 常數「沒有 GPU」句；**不關閉**預覽與匯出（改用 CPU，同 `Engine` 現行行為），前端狀態列顯示這句（D8 已裁決）。
  - `heic`：`import pillow_heif` 成功；否則 reason＝`darkroom/_heif.py` `MISSING` 原句（與開 HEIC 失敗時同一句，H 系列不變）。
  - `webp`：`cv2.haveImageWriter(".webp")`；false → 常數「WebP 不能寫」句；export 選 webp → unavailable 這句（E2）；前端 WebP 選項 disabled、title＝這句。
  - `photo_library`：`config.data_dir()` 解析得到、是絕對路徑、上層資料夾存在、不在使用中的 preset 資料夾或庫根之內；否則 reason＝對應那句（ConfigError 原句、PLP17「上層資料夾不存在」句、PLP1「資料區不能在…底下」句）。false 時：get／set／clear／paste／restore／save_edit_as_preset、export 的 E15 一律 unavailable 同句（`ConfigError` 不再變 HTTP 500，收 S1 finding [3]）；前端停止自動存檔、縮圖格的編輯按鈕 disabled，只在狀態列顯示一次這句（不每次變動都跳 toast）。
  - `preset_library_writes`：E20。
  - `semantic_index`：等於 `semantic_status()` 的 `available`／`reason`（SI2 三句）；SI2 成立、用的是 `anthropic_api_key_ref`、而 `onepassword` 不可用 → false、reason＝`onepassword` 的 reason。
  - `onepassword`：E24。
  三入口對同一項給同一句（parity）。釘死：`test_capability_rules`（每項的成立／不成立各一案例，句子逐字比對常數）、`test_photo_library_unavailable_is_503_not_500`。
- [ ] E24（1Password 登入偵測與句子，WG16／SIP10 補丁）：只有 `config.anthropic_api_key_ref()` 有值時才偵測，否則 `onepassword`＝`{available:false, reason:常數「沒用到 1Password」}`。偵測＝`services/semantic_index.py` 的 `op_signed_in()` 呼叫 `subprocess.run(["op","whoami"], capture_output=True, timeout=10)`（WG16 新形狀，恰 2 參數；別的模組不准開 op）：結束碼 0 → 可用；非 0 → 常數「1Password 尚未登入」；`FileNotFoundError` → `SEM_KEY_NO_OP` 原句；逾時 → 常數「1Password 尚未登入或還在等解鎖（op whoami 逾時）」。stdout／stderr 一律不進任何句子、結果、log（同 SI3）。`semantic_build` 取金鑰前先跑一次 `op_signed_in()`，不可用 → unavailable「無法取得 Anthropic 金鑰：{reason}」（SI3 句型）、不跑 `op read`；`op read` 本身逾時的 reason 改為常數「1Password 尚未登入或還在等解鎖（op read 逾時）」（SIP10，取代「op read 逾時」）。釘死：`test_onepassword_detection`（假 runner：0、1、FileNotFoundError、逾時、沒設 ref 五種）、`test_semantic_build_checks_signin_first`（未登入時 `op read` 沒被呼叫）、`test_initiator_rules` 加 WG16 形狀。測試不准真的跑 op（WG15 照舊）。

### 九、三入口與前端
- [ ] E25（操作登錄與數字）：facade 新增 6 個操作，依序接在第 27 個（`semantic_status`）之後、為第 28～33 個：`list_export_presets`、`save_export_preset`、`delete_export_preset`、`preset_files`、`export_preset_files`、`capabilities`；`export` 簽名擴充為 `export(items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None, metadata=None, remove_gps=None, sharpen=None, export_preset=None)`（不是新操作）。每個新操作照 L2：service 方法、`DarkroomFacade` 一行 `return`、`OPERATIONS` 一筆、HTTP 路由、CLI 子指令（`--json` 信封同 L9）、MCP 工具；`FakeDarkroom` 同步；`test_operation_coverage` 照舊。數字：facade 操作 27→33、MCP 工具 27→33、HTTP 路由 29→35（`test_http_golden` 的 `test_exactly_twenty_nine_routes` 改名 `test_exactly_thirty_five_routes`）。名稱見常數「操作表」。
- [ ] E26（CLI）：`export` 加 `--format jpeg|png|tiff|webp`（預設照 E1，不再寫死 jpeg 在 argparse）、`--bit-depth 8|16`、`--max-kb N`、`--resize MODE=VALUE`、`--metadata all|copyright|none`、`--remove-gps`、`--sharpen TARGET=AMOUNT`、`--export-preset NAME`、`--no-edit`（＝每個 item 帶 `preset_id: null`，用原圖）；沒給 `--preset`／`--strength`／`--override`／`--no-edit` 時 item 只有 `path`（E15）。新子指令：`export-presets list`、`export-presets save --name N [匯出設定旗標…]`、`export-presets delete <name>`、`presets files <id>…`（不帶 `--json` 時每筆一行「{file_name}\t{位元組數}」）、`presets export <id>… --dest-dir D`（不帶 `--json` 成功行＝常數「已匯出 preset：{output_path}」）、`capabilities [--refresh]`（不帶 `--json` 每項一行「{項目}\t可用」或「{項目}\t關閉：{reason}」）。旗標值不合法時原字串交給 service 判（同 XP17 的 `--quality`），句子三入口相同。`export-presets *`、`presets files`、`capabilities` 以外的新指令不 import torch（`capabilities` 會 import torch 測 GPU，允許）。釘死：`test_cli_s2_flags`、`test_cli_export_no_edit`、`test_cli_capabilities_human`。
- [ ] E27（MCP）：工具與 annotations 見常數；`darkroom_export` 的 inputSchema 加 E1 的 7 個設定欄位與 `export_preset`，`required` 改為只有 `items`（format 有預設，XP32）；`darkroom_preset_files` 成功時 `structuredContent`＝`{"files":[…]}`（base64 文字，不回 MCP 圖片）；`darkroom_presets_export` 部分失敗照 XP11（`failed`）。釘死：`test_app_mcp` 工具清單與 annotations、`test_mcp_s2_schemas`。
- [ ] E28（HTTP）：新路由見常數；全部過 `_local_only`（Host → Sec-Fetch-Site → Origin → Content-Type → X-Darkroom → 路由，R10／R11）；`GET /api/capabilities` 會回本機路徑（原因句），加進 R11 的「必須帶 `X-Darkroom: 1`」清單（R12），並以 `allow_head=False` 登記（PLP12）。`POST /api/export` 照舊不收 `dest_dir`（XP16）；匯出預設不含 dest_dir，所以 HTTP 永遠沒有能指定寫入位置的欄位。`POST /api/preset-library/export` 一律 400（E17）。`PUT /api/export-presets`、`DELETE /api/export-presets?name=` 寫的是 data_dir（位置不由請求決定，PLP2 精神）。釘死：`test_http_security` 加新路由、`test_http_golden` 新路由的錯誤句與路由數。
- [ ] E29（前端匯出對話框，修訂 X13，D3 已裁決）：`#export-btn` 與 `#export-selected-btn` 都打開同一個 `#export-dialog`（`role="dialog"`、`aria-modal="true"`、`aria-labelledby`），內容依序：匯出預設 `#xd-preset`（select，第一項「（自訂）」）＋`#xd-preset-save`＋`#xd-preset-delete`；格式 `#xd-format`（JPEG／PNG／TIFF／WebP）；位元深度 `#xd-bit-depth`；品質 `#xd-quality`；大小上限 `#xd-max-kb-on`＋`#xd-max-kb`；尺寸 `#xd-resize-mode`（不縮放＋六種）＋`#xd-resize-value`；中繼資料 `#xd-metadata`＋`#xd-remove-gps`；銳利化 `#xd-sharpen-target`（不銳利化＋三種）＋`#xd-sharpen-amount`；一行摘要 `#xd-summary`（`L.exportSummary`，例：常數「摘要範例」）；`#xd-go`（文字「匯出」，Enter 觸發）、`#xd-cancel`（Esc 也關）。哪些欄位 disabled 只由純函式 `L.exportDialogState(settings, caps)` 決定（png／tiff 停用品質、jpeg／webp 只有 8-bit、大小上限只在 jpeg、WebP 在 `caps.webp` 不可用時 disabled 且 title＝原因、尺寸值的 min／max 依 mode）；打開時填「上次用的設定」（`localStorage` 鍵 `darkroom.exportSettings`，讀寫包 try/catch，讀不到用常數預設）。存成預設用 `prompt` 取名；更新或刪除後的 toast 帶「復原」按鈕（按下＝用回傳的 `previous`／被刪內容再 `PUT` 一次）。匯出期間 `#xd-go` disabled 並顯示 `L.EXPORT_BUSY`（S13 (a) 同規則）；沿用狀態先存成編輯（S11 照舊）；縮圖格「匯出所選」改為只送 `{path}` items（E15，取代 `L.exportItems` 逐張讀編輯）。對話框不改編輯狀態、不進復原紀錄（X13）。工具列原本的 `#export-format`、`#export-quality` 移進對話框（X13 補丁 XP33）。釘死：`tests/js` `L.exportDialogState`、`L.exportSummary`、`L.resizeTarget`；`test_export_dialog_structure`；瀏覽器截圖（1600 寬、820×600）。
- [ ] E30（前端：能力狀態、preset 下載、窄視窗）：狀態列 `#cap-btn`：全部可用時文字「功能正常」，否則常數「功能狀態」句；點開 `#cap-detail`（`role="dialog"`，每項一行：名稱＋可用／關閉原因），`GET /api/capabilities?refresh=1` 的「重新偵測」鈕 `#cap-refresh`。被關掉的功能對應的按鈕 disabled、title＝原因（不藏）。preset 樹列的 `.row-menu` 加「下載 .xmp」；群組資料夾的選單加「下載整個群組的 .xmp」（≤ 500 個）；兩者走 `POST /api/preset-library/files`、以 Blob＋`<a download>` 逐檔下載，失敗逐筆列在 `#import-result`（沿用樣式）。H11／S18 不准藏清單加入：`#export-dialog` 內全部控制項、`#cap-btn`、`#cap-refresh`、`.row-menu` 新項目；820 寬時對話框 `max-width: min(560px, 100vw − 32px)`、`max-height: calc(100vh − 32px)` 內部捲動，全部控制項可捲到、不被裁掉。釘死：`test_narrow_windows_keep_function_buttons`（PROTECTED 擴充）、`test_cap_status_structure`、`test_preset_download_structure`、瀏覽器量測（820×600 對話框每個控制項的 bounding box 都在可捲動範圍內）。

### 十、一致性、回歸與文件
- [ ] E31（三入口一致性，加入 `tests/test_interface_parity.py`）：每個 driver 自己的暫存 data_dir、照片複本、preset 庫、dest_dir（HTTP 用預設匯出資料夾）。情境至少：format `bmp`、bit_depth 16＋jpeg、quality 0＋webp、max_kb＋png、resize mode 錯、percent 150、metadata 錯、sharpen amount 錯（以上 invalid 三邊同句）；webp 被偵測關掉（unavailable 三邊同句）；png 16-bit 成功（三邊 basename 相同）；long_edge 1000 成功（寬高相同）；export_preset 不存在（not_found）；有已存編輯時不給參數（三邊 `params_from:"edit"`、輸出 SHA-256 相同）；沒有編輯（`original`）；匯出預設 save→list→delete（三邊結果相同）；preset_files 未知 id＋已知 id 一好一壞；export_preset_files（只跑 CLI／MCP）撞名 → ` (2)`；capabilities 注入相同偵測器（三邊相同）；preset 庫在照片資料夾時 rename_preset（unavailable 三邊同句）。
- [ ] E32（回歸、文件、相依）：`python -s -m unittest discover -s tests` 結束碼 0；`node --test tests/js/test_logic.cjs` fail 0；preset 合併雜湊仍 `15C015CC0C080FF9`、1466 個；真實 data_dir 與 preset 庫快照不變（G7）。不新增任何依賴（WebP／PNG 用既有 cv2，不裝 Pillow 外掛、不用 Rust，ADR-0003）。既有測試只准改：本合約補丁點名的常數與數字、`FakeDarkroom` 加 6 個方法、PROTECTED 清單、`test_http_golden` 路由數、`test_app_mcp` 工具清單，逐處記成實作補丁。文件：`AGENTS.md`（CLI 表、MCP 表、食譜 1／3 改成「不給參數就用存好的編輯」、刪掉「export 不會自動用照片庫裡保存的編輯」那段、加 `--no-edit`）、`CLAUDE.md`、`README.md`、`docs/agent-install.md` 的工具數 27 改成 33；`darkroom-edit` skill（新格式、尺寸、匯出預設）、`darkroom-presets` skill（下載／匯出 .xmp）、`darkroom-setup` skill（能力偵測、mac／Linux 的 data_dir 預設）。

- [ ] E33（雜項：logo.svg 行尾，主 session 2026-10-10 交辦，方案D15 已裁決）：`tests/test_app_frontend.py` `test_front_end_housekeeping`（S13 (l)）逐位元組比對 `darkroom_app/static/logo.svg` 與 `docs/assets/logo.svg`，在 `core.autocrlf=true` 的 checkout 上兩份可能各被轉成不同行尾而失敗。草稿採 (A)：repo 根目錄新增 `.gitattributes` 一行 `*.svg text eol=lf`，並以 `git add --renormalize` 確認兩份 svg 在 index 與工作目錄都是 LF；判官照舊逐位元組比對（S13 (l) 原文不改）。釘死：`test_svg_line_endings_pinned`（讀 `.gitattributes` 斷言含該行；兩份 svg 位元組都不含 `
`）；驗收另在一個 `core.autocrlf=true` 的新 clone 跑 `test_front_end_housekeeping` 綠（主 session 手動一次，記成實作補丁）。
- [ ] E34（`op` 沒登入的錯誤句）：維持 E24／SIP10 的寫法——沒登入一律寫「1Password 尚未登入」，逾時句也帶這幾個字，不只寫「逾時」（主 session 2026-10-10 確認）。

## 對既有合約的補丁提案（本合約封緘時一併寫進各合約補丁區）
- XP30（修訂 X1、X2、XP3、XP6；E15）：X1 item 的 `preset_id` 由「`preset_id`|null」改為「可省略」：三個鍵全省略＝用已存編輯（沒有編輯＝原圖，與舊行為相同）；`preset_id:null` 照舊＝不套 preset。X1「每筆恰為 `{ok,source,output}`」改為多一個 `params_from`（D1 已裁決；成功與失敗都有？草稿：只有成功筆有）。X2 等式對「給了參數」的 item 照舊；對 E15 的 item，等式的另一邊改成「以同一組編輯參數做 preview」。XP3 CLI 沒給 `--preset`／`--strength`／`--override` 的行為改變（以前＝原圖）。既有測試的暫存 data_dir 裡沒有編輯，所以結果不變；有編輯的情境另寫新測試。
- XP31（修訂 X1 常數）：「不支援的匯出格式：{format}（可用 jpeg、tiff）」改為「不支援的匯出格式：{format}（可用 jpeg、png、tiff、webp）」；「JPEG 品質要在 1～100 之間：{quality}」對 JPEG 逐字不變，WebP 用同句型「WebP 品質…」。`test_http_golden` 只為這兩句改斷言，其餘不動。
- XP32（修訂 XP4）：`darkroom_export` inputSchema `required` 由 `["items","format"]` 改為 `["items"]`；`format` enum 加 `png`、`webp`。
- XP33（修訂 X13、R6／H11／S18 清單）：工具列的 `#export-format`、`#export-quality` 移進 `#export-dialog`；不准藏清單裡這兩項改指向對話框內的 `#xd-format`、`#xd-quality`，`#export-btn` 照舊在工具列。
- XP34（修訂 X15「不做」清單）：「存成 xmp」「縮放尺寸」從「不做」移除（E16、E17、E8）。
- WG16（修訂 WG15 的 G3 產品子程序清單，只多一個形狀）：`services/semantic_index.py` 的 `op.exe` 另外允許恰 2 個參數、第 2 個恰為 `whoami`（不分大小寫比對執行檔 basename，參數本身區分大小寫）；多一個參數（例如 `--format json`）、`op signin`、`op account list`、別的模組開 `op` → 一律違規。`_popen_allowed` 純函式測試：允許 `op whoami`、`op.exe whoami`；拒絕 `op whoami --format json`、`op WHOAMI`、`op signin`、`op`（1 參數）、`gpucheck.py` 開 `op whoami`、測試身分開 `op whoami`。G2 事件清單與 CreateFile 位元清單不動（WG14 凍結照舊）。
- SIP10（修訂 SI3 常數）：`op read 逾時` 改為「1Password 尚未登入或還在等解鎖（op read 逾時）」；新增 reason「1Password 尚未登入（請解鎖 1Password App 或執行 op signin）」（`op whoami` 非 0 時）。`test_key_failures_are_fixed_sentences` 改這一句、加一句。
- PLP18（修訂 PL1／PLP8 的 data_dir 預設）：見 E18；Windows 行為與句子逐字不變。
- R12（修訂 R11 清單）：必須帶 `X-Darkroom: 1` 的 GET 由 4 條變 5 條（加 `/api/capabilities`）。
- KP22（修訂 K16 錯誤 kind）：preset 庫寫入操作新增一種 unavailable（E20 常數句），三入口照 L7（503／5／isError）。
- L2（數字）：facade 操作數 27 → 33，順序見常數。

## 主 session 裁決（2026-10-10；以下 D1～D15 原為待裁決選項，全部採「建議」那一項，條文以本節「定案」為準）

### 定案（主 session 2026-10-10，與條文同等效力）
- D1＝(C)：每筆**成功**的匯出結果多一個鍵 `used`＝`{"params_from","quality","width","height"}`（鍵恰此 4 個、依此順序）：`params_from` 為 `edit`／`original`／`request`；`quality`＝實際採用的品質（JPEG 經大小上限搜尋後的值、WebP 的品質；PNG／TIFF 為 null）；`width`／`height`＝輸出檔的寬高（縮放後、轉正後）。失敗筆照 XP17 不帶 `used`。E15、XP30、E31 寫的「`params_from`」一律讀成 `used.params_from`；成功筆的形狀＝`{ok, source, output, used}`。
- D2＝(A)：先全解析度渲染，再縮小（E8、E11 原文）。
- D3＝(A)：`#export-btn`、`#export-selected-btn` 一律打開 `#export-dialog`，帶上次的設定，按 Enter 就匯出（E29 原文）。
- D4＝(A)：新模組 `darkroom_app/services/export_presets.py`；G10 白名單 4→5（E12、常數「數字」原文）。
- D5＝(A)：同名（casefold）存檔＝取代，回 `previous`，前端 toast 帶「復原」（E13、E29 原文）。
- D6＝(A)：買來的與匯入的 preset 匯出＝原檔位元組原樣；自存 preset 補常數「Lightroom 必要屬性」中缺的（E16 原文）。
- D7＝(A)：網頁的 preset 匯出＝瀏覽器端逐檔下載（`preset_files`），不打包 zip；伺服器不寫檔（E17、E30 原文）。
- D8＝(A)：沒有 CUDA 照常用 CPU，狀態列說明（E23 `gpu` 原文）。
- D9＝(C)：庫根與它的各層上層都看，但跳過磁碟根目錄與使用者家目錄本身（E20 原文）。
- D10＝(A)：PLP1 的祖先規則本片不碰（另開一片）。
- D11：S1 審查 [11]（E21）、[12]、[13]（E19）三項都收。
- D12＝(A)：`remove_gps` 預設 false。
- D13＝(A)：1 KB＝1024 位元組。
- D14＝(A)：PNG 預設 8-bit。
- D15＝(A)：repo 根目錄 `.gitattributes` 加一行 `*.svg text eol=lf`（E33 原文；判官維持逐位元組）。
- 文字釐清（不改語意）：E1「恰為 9 個鍵」＝常數「匯出設定鍵」的 8 個設定鍵＋export 自己的 `dest_dir`；`normalize_settings` 的結果與匯出預設存的都是那 8 個鍵（E12 schema 的「9 個設定鍵」同讀為 8 個）。

### 原選項（存檔備查）
- D1（E15／XP30）匯出結果要不要多帶「這張用了什麼參數」：(A) 不加，X1 形狀不動；(B) 加 `params_from`（edit／original／request）；(C) 加 `used:{params_from, quality, width, height}`（大小上限搜尋後實際品質、縮放後尺寸都看得到）。建議 (C)：使用者與代理要知道「這次是用存好的編輯」「壓到品質幾」，否則以為沒套；代價是 X1／XP6／golden 斷言要改。
- D2（E8／E11）縮放放在渲染前還是後：(A) 渲染全解析度後再縮（Lightroom 做法、局部效果最準，花的 GPU 時間不變）；(B) 先縮再渲染（快很多，S1 的 K4 已讓顆粒／銳利／紋理隨尺寸縮放，但 Clarity／Dehaze 的金字塔不一定尺度不變）。建議 (A)。
- D3（E29）匯出按鈕：(A) 一律跳對話框（帶上次設定、Enter 就匯出）；(B) 按鈕直接用上次設定匯出、旁邊另一顆「匯出設定…」開對話框。建議 (A)：多按一次 Enter，換來每次都看得到格式與位置，不會匯成上次的 16-bit TIFF 還不知道。
- D4（E12）匯出預設寫在哪個模組：(A) 新模組 `services/export_presets.py`（G10 白名單 4→5，職責清楚）；(B) 塞進 `services/photo_library.py`（白名單不變，但照片庫模組變更大）。建議 (A)。
- D5（E13）同名存檔：(A) 取代，回傳 `previous` 讓前端「復原」；(B) conflict，要使用者換名或先刪。建議 (A)：省心，而且可復原。
- D6（E16）買來的 preset 匯出內容：(A) 原檔位元組原樣（Lightroom 看到的是商家原名，不是在 darkroom 改過的顯示名稱；檔名用顯示名稱）；(B) 改寫 `crs:Name`／`crs:Group` 成 darkroom 的顯示名稱與群組（要改 XML，有讀不回去的風險）。建議 (A)；自存 preset 一律補 Lightroom 必要屬性。
- D7（E17／E30）網頁的 preset 匯出：(A) 瀏覽器下載（`preset_files`，伺服器不寫檔，位置由瀏覽器決定）；(B) 伺服器寫到一個固定的預設資料夾（例如 `<文件>/darkroom preset 匯出`；要新增寫入位置規則）。建議 (A)；多個檔時要不要打包成 zip（伺服器在記憶體組 zip，controller 做格式轉換）也一併裁決，草稿＝逐檔下載、不打包。
- D8（E23）沒有 CUDA 時：(A) 照常用 CPU，狀態列說明「會慢很多」；(B) 關掉預覽與匯出。建議 (A)：關掉等於整個 App 不能用。
- D9（E20）「庫根落在照片資料夾裡」的範圍：(A) 只看庫根自己的第一層；(B) 庫根與所有上層；(C) 庫根與上層、但跳過磁碟根目錄與使用者家目錄本身（避免 `E:\` 或家目錄放了一張 jpg 就把整理功能關掉）。建議 (C)。
- D10（連帶 S1 finding [1]）PLP1 的「祖先」規則把預設 data_dir 判成在照片資料夾底下（照片放在 `C:\Users\<名>` 這類上層時存不了編輯）：(A) 本片不碰；(B) 改成跟 D9 同一套判準（只收緊不放寬的原則會被打破：資料區放在照片資料夾的子資料夾將變成允許）。建議 (A)，另開一片專門處理，因為這是放寬已封緘的安全條文。
- D11（E19、E21）S1 審查的 [11]（照片在 preset 資料夾內整批匯出中止）、[12]（相對 data_dir）、[13]（壞設定檔 traceback）要不要隨本片修：建議三個都收（都很小、都是「出事時看不懂原因」或「一筆壞掉拖垮整批」，跟本片的偵測主題同一類）。
- D12（E9）`remove_gps` 預設：(A) false（X7 相容、Lightroom 預設）；(B) true（分享到網路時保護位置）。建議 (A)，對話框的「移除 GPS」放在中繼資料旁邊、一眼看得到。
- D13（E7）大小上限的 KB：(A) 1024 位元組（Windows 檔案總管顯示的 KB）；(B) 1000 位元組。建議 (A)。
- D14（E4）PNG 預設位元深度：(A) 8-bit（檔案小、到處能開）；(B) 16-bit。建議 (A)。
- D15（E33）logo.svg 行尾：(A) `.gitattributes` 固定 `*.svg text eol=lf`（git 層面一次解決，之後任何 checkout 兩份都一樣；判官維持最嚴的逐位元組）；(B) 判官比對前先把 `
` 正規化成 `
`（不動 git 設定，但判官變鬆：只有行尾不同的兩份會被當成相同，S13 (l)「位元組相同」要改條文）。建議 (A)：修的是根因、不放寬判官，而且 svg 是文字檔，固定 LF 對瀏覽器沒有任何影響。

## 不在 S2（記錄，不做）
- 裁切、旋轉、鏡像（S3）。
- 尺寸單位英吋／公分與解析度 ppi 欄位、浮水印、檔名範本（例 `{日期}-{序號}`）、匯出後動作（開資料夾、上傳）、匯出佇列介面、色彩空間選擇（Display P3／Adobe RGB；X5 照舊只 sRGB）、WebP 無損、AVIF／HEIC／JPEG XL 輸出。
- 把匯出預設匯出成 Lightroom 的 `.lrtemplate`；把 darkroom 的編輯寫成照片旁的 sidecar `.xmp`（ADR-0002：照片資料夾永遠不寫）。
- 匯出預設的跨裝置同步、內建（出廠）匯出預設。
- S1 審查其他 findings（[1] 見 D10；[2] CLI thumbnails 背景工作；[9] `--port 80`；[14]～[27]）。
- SIP9（壞索引丟掉在途 batch）。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 已存編輯被默默忽略（E15） | params_from、unavailable 不改原圖 | 使用者 → 批次匯出了一堆沒修過的原圖還以為修好了｜邏輯核心 | `test_export_uses_saved_edit`、`test_export_saved_edit_library_unavailable` |
| 匯出檔與原檔（E3、E17） | 只 `create_new`、永不覆蓋 | 使用者照片、先前匯出、別人的 xmp → 被覆蓋｜不可逆／資料 | `test_export_never_overwrites`、`test_export_preset_files_never_overwrite`、`test_export_preset_files_refuses_preset_folder` |
| 中繼資料（E9） | 標籤集合逐一列出 | 使用者的位置與拍攝資料 → 選了「移除 GPS」卻帶出去｜不可逆／資料 | `test_export_metadata_modes` |
| 只縮不放（E8） | 案例表雙邊共用 | 使用者成品 → 被放大變糊，或前端摘要寫 2048 實際不是｜邏輯核心 | `test_resize_shared_cases`、`test_export_resize_pixels` |
| 大小上限（E7） | 整檔 ≤ 上限、品質最大 | 上傳網站 → 檔案超過限制被拒｜上下游契約 | `test_export_max_kb`、`test_export_max_kb_impossible` |
| 新容器格式（E4、E6） | 區塊順序、CRC、旗標 | 使用者成品 → 別的軟體打不開或顏色偏掉｜上下游契約 | `test_export_png_chunks`、`test_export_webp_container` |
| preset 庫位置（E20） | 寫入一律 unavailable | 使用者的照片資料夾 → 被寫進 library.json、user/、import/ 同步上雲｜不可逆／資料 | `test_library_root_in_photo_folder_disables_writes` |
| 匯出預設檔（E12、E13） | 原子寫、壞檔保留、可復原 | 使用者存好的預設 → 寫一半全丟或刪了拿不回來｜不可逆／資料 | `test_export_presets_storage`、`test_export_presets_ops` |
| 1Password 子程序（E24、WG16） | 恰 2 參數 whoami | 使用者的金鑰與帳號 → 多開一個能讀秘密的 op 形狀｜不可逆／資料 | `test_initiator_rules`、`test_onepassword_detection` |
| 能力偵測句（E22～E24） | 三入口同句 | 使用者與代理 → 功能沒反應卻不知道為什麼、照錯的原因去修｜UI/UX | `test_capability_rules`、`test_interface_parity` |
| 三入口數字（E25） | 33／33／35 | 代理 → 工具清單與文件對不上｜上下游契約 | `test_operation_coverage`、`test_app_mcp`、`test_http_golden` |
| 窄視窗（E29、E30） | H11 清單 | 使用者 → 820 寬看不到匯出按鈕或對話框下半截｜UI/UX | `test_narrow_windows_keep_function_buttons`、瀏覽器量測 |

## Verbatim Constants
```text
匯出設定鍵（順序）：format, bit_depth, quality, max_kb, resize, metadata, remove_gps, sharpen
預設值：format jpeg ｜ bit_depth：jpeg 8、png 8、webp 8、tiff 16 ｜ quality 92（jpeg、webp）｜ max_kb null ｜ resize null ｜ metadata all ｜ remove_gps false ｜ sharpen null
format 值與副檔名：jpeg .jpg ｜ png .png ｜ tiff .tif ｜ webp .webp
PNG：IMWRITE_PNG_COMPRESSION 3 ｜ 區塊順序 IHDR → iCCP（名稱 sRGB）→ eXIf → IDAT… → IEND
WebP：IMWRITE_WEBP_QUALITY 1..100 ｜ 容器順序 RIFF → VP8X → ICCP → VP8 → EXIF ｜ 最大邊 16383
max_kb：整數 10..1048576 ｜ 1 KB = 1024 位元組 ｜ 二分搜尋最多 8 次編碼
resize mode：long_edge ｜ short_edge ｜ width ｜ height ｜ megapixels ｜ percent ｜ 邊長值 1..65535 整數 ｜ megapixels (0, 1000] ｜ percent (0, 100] ｜ 圓整 floor(x+0.5)（megapixels 用 floor）｜ 插值 INTER_AREA
metadata：all ｜ copyright（IFD0 恰 Orientation=1、Copyright 33432）｜ none ｜ remove_gps 去掉 34853
銳利化（σ px, a）：screen low (0.5, 0.35) standard (0.6, 0.55) high (0.7, 0.80) ｜ glossy low (0.7, 0.45) standard (0.8, 0.70) high (1.0, 1.00) ｜ matte low (0.8, 0.60) standard (1.0, 0.90) high (1.2, 1.25)
銳利化公式：Y = 0.2126R + 0.7152G + 0.0722B ｜ x′ = clip(x + a·(Y − GaussianBlur(Y, σ)), 0, 1)
匯出預設 schema：{"schema":"darkroom-export-presets/1","presets":{"<name>":{9 個設定鍵}}} ｜ 檔案：export-presets.json ｜ export-presets.json.tmp-{pid}-{12 hex} ｜ export-presets.json.lock ｜ 壞檔：export-presets.json.bad-{unix秒}（同秒 -{n}，n 從 2 起）｜ 名稱 1～60 字 ｜ 上限 200 個
params_from：edit ｜ original ｜ request
Lightroom 必要屬性（自存 preset 匯出時缺的才補，依此順序接在 crs:PresetType="Normal" 之後）：crs:UUID="{sha256 前 32 位大寫}" crs:SupportsAmount2="True" crs:SupportsAmount="True" crs:SupportsColor="True" crs:SupportsMonochrome="True" crs:SupportsHighDynamicRange="True" crs:SupportsNormalDynamicRange="True" crs:SupportsSceneReferred="True" crs:SupportsOutputReferred="True" crs:RequiresRGBTables="False" crs:Version="15.4"
preset_ids：1～500 個
能力項目（順序）：gpu ｜ heic ｜ webp ｜ photo_library ｜ preset_library_writes ｜ semantic_index ｜ onepassword
op whoami：["op","whoami"] ｜ timeout 10 s ｜ 偵測總上限：op 10 s ＋ 其他 ≤ 2 s
data_dir 預設：win32 {LOCALAPPDATA}/darkroom ｜ darwin {home}/Library/Application Support/darkroom ｜ 其他 {XDG_DATA_HOME}/darkroom（XDG 須為非空絕對路徑），否則 {home}/.local/share/darkroom
localStorage 鍵：darkroom.exportSettings

invalid（請求層）：
  不支援的匯出格式：{format}（可用 jpeg、png、tiff、webp）
  JPEG 品質要在 1～100 之間：{quality} ｜ WebP 品質要在 1～100 之間：{quality}
  位元深度要是 8 或 16：{bit_depth}
  JPEG 只能輸出 8-bit：{bit_depth} ｜ WebP 只能輸出 8-bit：{bit_depth}
  檔案大小上限只適用於 JPEG
  檔案大小上限要是 10～1048576 之間的整數（KB）：{max_kb}
  尺寸設定要是 {"mode": …, "value": …}：{resize}
  不支援的尺寸方式：{mode}（可用 long_edge、short_edge、width、height、megapixels、percent）
  {mode} 的值要是 1～65535 的整數：{value}
  megapixels 的值要是大於 0、不超過 1000 的數：{value}
  percent 的值要是大於 0、不超過 100 的數（不會放大）：{value}
  不支援的中繼資料選項：{metadata}（可用 all、copyright、none）
  remove_gps 必須是 true 或 false
  銳利化設定要是 {"target": …, "amount": …}：{sharpen}
  不支援的銳利化對象：{target}（可用 screen、matte、glossy）
  不支援的銳利化強度：{amount}（可用 low、standard、high）
  匯出預設名稱要 1～60 個字 ｜ 匯出預設最多 200 個 ｜ 匯出預設不包含匯出資料夾（dest_dir）
  preset_ids 要是 1～500 個 preset id
  不能把 preset 匯出到 preset 資料夾或 preset 庫裡：{dest_dir}
not_found：找不到匯出預設：{name}
conflict：匯出預設正被其他程式修改，請稍後再試
unavailable：無法寫入匯出預設：{reason}
單筆 reason（包在「匯出失敗：{file_name}：{reason}」裡，X 系列句型不變）：
  壓不下：無法壓到 {max_kb} KB 以內：品質 1 也有 {actual_kb} KB
  WebP 太大：WebP 最大 16383×16383 像素，這張是 {width}×{height}；請縮小尺寸後再匯出
  照片在 preset 資料夾裡：照片在 preset 資料夾裡，請指定匯出資料夾（dest_dir）
HTTP 入口句（400）：{"error": "preset export to a folder is not accepted over HTTP (use the CLI or MCP; the page downloads the files)"}
CLI 人看：已匯出 preset：{output_path} ｜ capabilities：{項目}\t可用 ／ {項目}\t關閉：{reason} ｜ presets files：{file_name}\t{位元組數}

能力關閉原因：
  gpu：沒有偵測到可用的 NVIDIA 顯示卡（CUDA），預覽與匯出改用 CPU，會慢很多
  heic：讀 HEIC 需要 pillow-heif（python -s -m pip install --no-deps pillow-heif==1.8.0）（＝darkroom/_heif.py MISSING 原句）
  webp：這台電腦的 OpenCV 不能寫 WebP，WebP 匯出先關閉
  photo_library：（PL1 ConfigError 原句 ｜ PLP17 上層資料夾不存在句 ｜ PLP1 資料區位置句）
  preset_library_writes：preset 庫的位置 {root} 在照片資料夾裡（{photo_folder} 有照片），為了不在照片資料夾裡寫檔，整理 preset、匯入、存成 preset 先關閉；請在 config.local.json 把 preset_library_dir 設到別的資料夾
  semantic_index：（SI2 三句原樣）｜ 或 onepassword 的原因
  onepassword：1Password 尚未登入（請解鎖 1Password App 或執行 op signin） ｜ 找不到 op（1Password CLI） ｜ 1Password 尚未登入或還在等解鎖（op whoami 逾時） ｜ 沒有用到 1Password（config.local.json 沒有 anthropic_api_key_ref）
SI3 reason 補丁（SIP10）：1Password 尚未登入或還在等解鎖（op read 逾時）（取代「op read 逾時」）
data_dir 找不到（非 Windows）：找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 HOME 存在
設定檔壞了（E19）：{file_name} 不是正確的 JSON（第 {line} 行第 {col} 欄）：{msg}

前端：功能正常 ｜ 功能狀態：{n} 項關閉 ｜ 重新偵測 ｜ 下載 .xmp ｜ 下載整個群組的 .xmp
前端：已存成匯出預設：{name} ｜ 已更新匯出預設：{name} ｜ 已刪除匯出預設：{name} ｜ 復原 ｜ （自訂）
摘要範例：JPEG 品質 92 ・長邊 2048 px ・全部中繼資料 ・螢幕銳利化（標準）

操作表（facade ｜ HTTP ｜ CLI ｜ MCP ｜ annotations），第 28～33 個，接在 semantic_status（第 27 個）之後：
  list_export_presets() ｜ GET /api/export-presets ｜ export-presets list ｜ darkroom_export_presets_list ｜ readOnlyHint true、openWorldHint false
  save_export_preset(name, settings) ｜ PUT /api/export-presets ｜ export-presets save --name N [匯出設定旗標…] ｜ darkroom_export_preset_save ｜ readOnlyHint false、destructiveHint true、idempotentHint true、openWorldHint false
  delete_export_preset(name) ｜ DELETE /api/export-presets?name= ｜ export-presets delete <name> ｜ darkroom_export_preset_delete ｜ readOnlyHint false、destructiveHint true、idempotentHint false、openWorldHint false
  preset_files(preset_ids) ｜ POST /api/preset-library/files ｜ presets files <id>… ｜ darkroom_preset_files ｜ readOnlyHint true、openWorldHint false
  export_preset_files(preset_ids, dest_dir) ｜ POST /api/preset-library/export（入口拒絕）｜ presets export <id>… --dest-dir D ｜ darkroom_presets_export ｜ 同 EXPORT_ANNOTATIONS（readOnlyHint false、destructiveHint false、idempotentHint false、openWorldHint false）
  capabilities(refresh=False) ｜ GET /api/capabilities?refresh= ｜ capabilities [--refresh] ｜ darkroom_capabilities ｜ readOnlyHint true、openWorldHint false
數字：facade 操作 27→33 ｜ MCP 工具 27→33 ｜ HTTP 路由 29→35 ｜ G10 白名單 4→5（D4 選 A 時）：("services/export.py", "services/preset_library.py", "services/photo_library.py", "services/semantic_index.py", "services/export_presets.py")
export 簽名：export(items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None, metadata=None, remove_gps=None, sharpen=None, export_preset=None)
CLI export 新旗標：--format jpeg|png|tiff|webp ｜ --bit-depth 8|16 ｜ --max-kb N ｜ --resize MODE=VALUE ｜ --metadata all|copyright|none ｜ --remove-gps ｜ --sharpen TARGET=AMOUNT ｜ --export-preset NAME ｜ --no-edit
WG16 形狀：services/semantic_index.py → op|op.exe whoami（恰 2 參數）
preset 合併雜湊：15C015CC0C080FF9 ｜ 數量：1466
```

## 實作補丁（2026-10-10，實作時的決定與量測；與條文同等效力，只收緊或補常數；放寬處逐項標明並說理由）
- IP1（Q8 (a) 實測，2026-10-10 03:59，專用 Python）：OpenCV 5.0.0 `cv2.haveImageWriter(".webp")` = True、`.png` = True；`cv2.imencode(".png", uint16 HxWx3, [IMWRITE_PNG_COMPRESSION, 3])` 成功，`IMREAD_UNCHANGED` 讀回 uint16 逐值相同；`cv2.imencode(".webp", …, [IMWRITE_WEBP_QUALITY, 92])` 與 q=100 都產生 `RIFF…WEBPVP8 `（有損 VP8，單一區塊，沒有 VP8X）；PNG 8-bit 輸出區塊為 IHDR → IDAT… → IEND。→ WebP 與 16-bit PNG 都可行，不需要關閉；`webp` 偵測照 E23 保留（別台電腦的 OpenCV 可能不行）。PIL 12.3.0、tifffile 2026.9.20 只用來在測試裡讀回。
- IP2（Q8 (b) 實測，2026-10-10 03:59，只跑 `op whoami`、15 秒上限、沒跑 `op read`）：1Password App 執行中、CLI 整合模式，`op whoami` 0.89 秒就結束、結束碼 1（stderr 一行 `account is not signed in`），沒有卡住等解鎖。→ 非 0 走「1Password 尚未登入（…）」句；10 秒逾時與逾時句照 E24 保留當保險。
- IP3（D9 細化，**放寬一處、說理由**）：E20 往上逐層判斷時，除了磁碟根目錄與使用者家目錄本身，系統暫存資料夾本身（環境變數 `TMPDIR`／`TEMP`／`TMP` 指到的那一層）也不判。理由：`%TEMP%` 本身常放別的程式留下的 .jpg／.png（本機實測有 3 個），不跳過的話所有放在暫存區底下的 preset 庫（含每個測試的庫根）整理功能都會被關掉；暫存區不是使用者的照片資料夾。暫存區底下的子資料夾、以及更上層照常判。釘死：`test_photo_folder_skips_home_temp_and_drive_root`。主 session 封緘時請確認。
- IP4（E21、E23 細化）：E21「照片在 preset 資料夾或庫根之內」與 E23 `photo_library`「不在 preset 資料夾或庫根之內」的「庫根」拿掉，只看使用中的 preset 資料夾。理由：safe_write 只擋 preset 資料夾（XP12），庫根預設＝preset 資料夾的上一層，照片或資料區在庫根底下（不在 preset 資料夾裡）寫檔本來就合法；照舊條文會讓預設版面（照片、data、presets 同層）整批失敗。E17 的 dest_dir 仍兩者都擋（寫 .xmp 進庫裡會變成新 preset）。
- IP5（E1 細化）：`bit_depth`、`quality`、`max_kb` 跟格式綁在一起，只有在最後的格式＝匯出預設的格式時才從預設取；否則用該格式的常數預設（E14 範例「預設 png 16-bit、明確 jpeg → JPEG 8-bit」即此規則）。`quality` 對 png／tiff 正規化成 null。
- IP6（E22 細化）：App 啟動的背景預熱只跑不開子程序的 5 項（gpu、heic、webp、photo_library、preset_library_writes）；`onepassword`（`op whoami`）與依賴它的 `semantic_index` 等第一次 `capabilities()` 才測。理由：測試會啟動真的 App 子程序，WG15「測試不准真的跑 op」。
- IP7（E24 細化）：「先跑 `op whoami`」放在預設的金鑰讀取函式 `op_key`（whoami → read）裡；測試注入的 `key_reader` 不經過它。`onepassword` 能力用 `SemanticIndexService.signin_check`（預設 `op_signed_in`）。
- IP8（補常數）：匯出預設的 settings 不是物件 →「匯出設定要是物件：{settings}」；有不認得的鍵 →「匯出設定不認得的鍵：{key}（可用 format、bit_depth、quality、max_kb、resize、metadata、remove_gps、sharpen）」；E7「壓不下」句的 `{actual_kb}`＝ceil(品質 1 的整檔位元組／1024)。heic 關閉句在 `messages.CAP_NO_HEIC` 複製一份（darkroom_app 不准 import `darkroom._heif`，B1），測試釘死兩者相等。
- IP9（E26 補）：`presets files` 有任一筆失敗時 CLI 結束碼 6（同 XP11）；MCP `darkroom_preset_files` 照 E27 不加 `failed`。`PUT /api/export-presets` 帶 `data_dir` → 400 `DATA_DIR_REFUSED`（PLP2 精神）。
- IP10（PLP19 細化，不放寬已封緘的 PLP17）：資料區「上層不存在」與「在 preset 資料夾裡」時，`photo_library` 能力回報 false 與原因句，但讀取（get_edit、E15 讀編輯）照 PLP17 已封緘行為照常（那兩種情況下本來就沒有編輯檔可讀），寫入照舊同句 unavailable；只有 ConfigError（資料區解析不到）讓所有照片庫操作 unavailable。
- IP11（E8／E11 實作）：有縮放或銳利化時，GPU 回 16-bit RGB，寫檔執行緒做 `cv2.resize(uint16, INTER_AREA)` → float → 銳利化 → 量化；都沒有時照舊直接用 GPU 量化結果（XP8 預設情境逐位元組不變）。`tools/bench_export.py --s2` 實測 0.385～0.411 秒／張（門檻 0.8，GPU 閒置，2026-10-10）。
- IP12（既有測試改動逐處，E32 授權範圍）：`test_export`（3 處成功結果加 `used`、bmp 取代 png 的格式錯誤句、ExportCase／TestHttpExport 改用暫存 data_dir）、`test_interface_parity`（format png → bmp 與句子、主 setUp 的 facade 加暫存 data_dir）、`test_http_golden`（路由測試改名 `test_exactly_thirty_five_routes`＋6 條路由）、`test_app_mcp`（工具清單＋6、S2 annotations）、`test_layering`（SAFE_WRITE_USERS 4→5、services 檔案集合加 2 個、操作清單＋6、export required、CLI export 預期改成只有 path／format None、S2 工具段）、`test_semantic_index`（SIP10 句）、`test_app_launch`（相對 preset_dir 變絕對，E19）、`test_app_cli`（`test_cli_data_dir_config_error_is_exit_2` 改為 `…_is_unavailable`：結束碼 5，PLP19）、`test_writeguard`（WG16 形狀）、`test_app_frontend`（XP33 兩個 id 改名、`api('PUT'` 計數由 1 改為「/api/edit 恰 1 次、/api/export-presets 恰 1 次」、`test_restore_uses_snapshot_values` 改斷言匯出所選只送 path（E29 取代 `L.exportItems`））、`test_http_security`（6 條新路由加入既有檢查）。
- IP13（E29／E30 瀏覽器量測，2026-10-10，暫存 preset 複本＋暫存 data_dir、埠 8799）：1600×900 與 820×600 都截圖（`.playwright-mcp/s2-dialog-1600.png`、`s2-dialog-820x600.png`）；820×600 時對話框 560×364、17 個控制項逐一捲入後 bounding box 全在視窗內、頁面無橫向捲動；實際按「匯出」產出 WebP（長邊 2048）、toast「已匯出：…」、`darkroom.exportSettings` 寫入；`#cap-btn` 顯示「功能狀態：3 項關閉」（preset 庫在照片資料夾裡、1Password 未登入兩項）。

## 封緘第 1 次派遣處置紀錄（2026-10-10；依 Loose-Criterion Escalation／R10，與條文同等效力）
- F1（E15／E29 條文太鬆，邏輯核心，已修）：網頁單張「匯出」原本先存編輯再只送 `{path}`，存檔失敗（例如照片在預設 data_dir 的上層，PLP1）時會默默匯出舊編輯或原圖。補條文 **E15a**：編輯器匯出目前這張時，item 一律帶畫面當下的參數（`currentRequest()`：image_id、preset_id、strength、overrides；`used.params_from`＝`request`），照片庫可用時仍先 flushSave／flushRetries（S11）；只送 path 只用於縮圖格「匯出所選」與 CLI／MCP 沒給參數的 item。釘死：`test_export_dialog_structure`（`currentExportItems` 整段 regex、只有一個 return、不含 `{path: st.image.path}`、`currentRequest` 回傳形狀）。
- F2（E12 條文太鬆，資料，已修）：一筆預設不合規則就把整個檔當壞檔、下一次存檔只剩新的一筆。補條文 **E12a**：只丟掉不合規則的那幾筆、其餘保留（照樣先留 `.bad-{秒}` 位元組複本）；`schema` 是 `darkroom-export-presets/` 開頭但不是 `/1` → 每個操作（list／save／delete／export 的 export_preset）一律 conflict 常數「匯出預設檔版本不支援：{schema}（export-presets.json）」、檔案一個位元組都不改（同 PL9）。釘死：`test_export_presets_keep_good_entries_and_foreign_version`。
- F3（G4 未釘表面，已修）：`formValues()` 讀「移除 GPS」「檔案上限」勾選框的那兩行原本沒有判官。釘死：`test_export_dialog_structure` 逐字斷言 `remove_gps: $('#xd-remove-gps').checked`、`max_kb_on: $('#xd-max-kb-on').checked`、`metadata: $('#xd-metadata').value` 與 `dialogSettings` 經 `L.settingsFromForm(formValues())`。
- F4（E30「≤ 500 個」偏離，已修回條文）：群組超過 500 個 preset 時不再分批連續下載，改為拒絕並 toast 常數「這個群組有 {n} 個 preset，一次最多下載 500 個；請先下載裡面的子群組」（`L.downloadTooMany`），在任何請求之前。釘死：`test_preset_download_structure`、`tests/js/test_logic.cjs`。
- F5（R10 裁決）：IP3（跳過暫存資料夾本身）、IP4（E21／E23 只看 preset 資料夾）、IP10（資料區上層不存在／在 preset 資料夾時讀取照 PLP17）皆有第一手證據（`%TEMP%` 第一層實有 3 個相片副檔名檔；`safe_write._preset_folders` 只擋 preset 資料夾；`Library` 只掃 preset_dir／import／user），判**符合**，維持實作補丁。
- F6（E15 第三種「讀不到」沒有判官，已補）：`test_export_saved_edit_library_unavailable` 加「編輯檔版本 darkroom-edit/99 → 該筆失敗、句子＝PL_SCHEMA_CONFLICT、不輸出原圖」。
- F7（備註）：瀏覽器量測（IP13）為實作者第一手量測，派遣代理無瀏覽器工具；靜態 CSS 規則已有 regex 判官。

## 封緘第 2 次派遣（複驗）處置紀錄（2026-10-10）
- (a) F1～F6 回歸逐項符合；(b) 第 1 次派遣咬到的 3 支探針重發全部被攔；(c) 修正輪新判官 13 條各自出生證明紅（P4～P15），探針全數以自存複本寫回並 cmp 逐位元組確認。
- 只記錄、不修（低嚴重度）：N1 foreign schema 段的 save／delete／export 與「檔案位元組不變」斷言沒有各自的紅（四個操作共用同一個 `_read`）；N2 F3 的 `metadata: $('#xd-metadata').value` 與 `dialogSettings` 兩條斷言沒有出生證明；N3 派遣 scratch 目錄 seal2 內有既存檔，代理改用子目錄 `seal2/d2/`，舊檔未動。
