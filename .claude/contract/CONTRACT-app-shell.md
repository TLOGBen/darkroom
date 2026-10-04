# CONTRACT — darkroom App 外殼（啟動、預覽伺服器、三欄編輯器）
> STATUS: sealed（2026-10-04）— 條文 B1～B14＋補丁 R1～R7 符合；複驗 9 項回歸已修、抽查 6/7 被攔截；N1（app.js 整個重新綁定 ed 未被結構測試擋下）、N2（R6 只禁 display:none）併入 HEIC 切片

## 目標
使用者點自己的啟動檔，瀏覽器開出 darkroom：左邊依群組列出 preset、中間是照片預覽、右邊是滑桿。點 preset、拖強度或滑桿時，畫面在 0.1 秒內跟著變；可以上一張／下一張換同資料夾的照片。

## 前提（Premises）
- P1 已驗：核心函式庫 `darkroom`（已封緘，HEAD 1af2d81）公開 API＝load_preset、Params（to_json／from_json／at_strength）、render(image, params, strength, device)、SCHEMA_VERSION、UnsupportedPresetError；讀寫圖在私有 `_io`（read_image／write_image）。
- P2 已驗：專用 Python 有 aiohttp 3.14.3、torch 2.14 cu130、cv2；預覽原型（`.claude/wayfinder/darkroom/prototypes/preview-latency/`）量到 HTTP POST＋最新一次優先＋cv2 編碼＋專用高優先 CUDA stream 時，連續拖動延遲 p50 約 30 ms；GPU 編碼（nvjpeg）在 GPU 忙時會吐壞檔。
- P3 已驗：介面已由使用者定案（`prototypes/node-ui/` 的 B 版全螢幕三欄；強度 0～200%、換 preset 回 100% 並清空微調；上一張／下一張；微調過的滑桿標示並可單項還原）。
- P4 未驗、不入條文：Windows 桌面常駐顯存的實際大小隨使用者開的程式變動。

## 可斷言條文
- [ ] B1：公開 API 擴充為 A2 的 5 個名稱再加 `read_image`、`write_image`；`render` 接受已在 GPU 的 torch 張量並回傳同裝置張量（不得在預覽路徑上來回複製到 CPU，JPEG 編碼那一步除外）；核心合約 A2 一併改為 7 個名稱，`darkroom_app` 只 import `darkroom` 的公開名稱。
- [ ] B2：`tools/start.ps1` 用專用 Python 啟動伺服器、只綁 `127.0.0.1`、埠號可設定（預設 8765），就緒後開瀏覽器；`tools/make-shortcut.ps1` 在桌面建立捷徑（`.lnk` 不進 git）。LocalLLMs 路徑來自環境變數 `LOCALLLMS_ROOT` 或 `config.local.json`（不進 git），程式碼不得寫死 `C:/Users/`。
- [ ] B3：`GET /api/presets` 回傳 JSON 陣列，每筆恰有 `id`、`group`、`name`、`supported`、`skipped` 五個欄位；1466 個 preset 全在、`supported` 全為 true；回應不得含 preset 的完整磁碟路徑。
- [ ] B4：`POST /api/open {"path": ...}` 讀照片並回傳 `image_id`、`width`、`height`、`preview_width`、`preview_height`；預覽圖長寬乘積 ≤ 1,500,000 且等比例；照片原檔只讀。
- [ ] B5：`POST /api/preview {"image_id","preset_id"|null,"strength","overrides"}` 回傳 `image/jpeg`；最終值＝`clamp(preset 在該強度的值 + 微調)`（微調是加在強度之後的差值）；`preset_id` 為 null 時只套微調；回應標頭 `X-Render-Ms` 帶後端渲染毫秒數。【部分失效：「最終值＝clamp(preset 在該強度的值 + 微調)」已由 R3 取代，現行為 clamp(clamp(preset 在該強度的值) + 微調)；其餘仍有效】
- [ ] B6：預覽渲染在專用的高優先 CUDA stream 上、只同步自己那條 stream（不得呼叫 `torch.cuda.synchronize()`）；JPEG 用 cv2 在 CPU 編碼；GPU 工作在單一執行緒 executor，不阻塞事件迴圈。
- [ ] B7：延遲驗收腳本（`tools/bench_preview.py`）對 24MP 測試圖以 60 Hz 模擬拖動 10 秒、最新一次優先：往返中位數 < 100 ms、p95 < 150 ms；量測前判斷 GPU 是否忙碌，忙碌才跳過並印出原因（使用率數字或佇列長度）：(a) 約 1 秒內以 `nvidia-smi --query-gpu=utilization.gpu` 取樣 5 次，中位數 > 15% ＝忙碌；(b) `nvidia-smi --query-compute-apps` 有路徑含 `comfyui` 的程序時，查 `http://127.0.0.1:8188/queue`，`queue_running` 或 `queue_pending` 非空＝忙碌，連不到＝不忙；(c) nvidia-smi 無法執行＝無法判斷，也跳過並印出原因。ComfyUI 常駐但佇列空、使用率不高時照常量測（核心 A17 的跳過判準一併改成這條，取代「已用記憶體扣本程序 > 1 GiB」；2026-10-04 條文補丁 R1，見文末）。釘死測試 `tests/test_app_gpucheck.py`（忙、閒、佇列連不到、nvidia-smi 失敗、門檻邊界）。
- [ ] B8：`GET /api/folder?image_id=` 回傳同資料夾、依檔名排序的 JPEG／PNG／TIFF 清單與目前位置；前端「上一張／下一張」照它切換，第一張按上一張、最後一張按下一張時不動作。
- [ ] B9：前端三欄（`#preset-tree`、`#preview`、`#sliders`）；preset 依 `group` 的「 - 」切成兩層樹，可用名稱搜尋；點 preset 時強度回 100 且清空微調；強度滑桿 0～200 在預覽正下方。【部分失效：「點 preset 時強度回 100 且清空微調」已由 R5 取代（保留強度與微調）；「可用名稱搜尋」已由 R6 擴充為名稱＋分類；其餘仍有效】
- [ ] B10：拖滑桿時前端只保留最新一筆待送參數（最新一次優先），不得累積佇列；微調過的滑桿加 `.adjusted` class，單項還原鈕把該鍵的微調歸零。
- [ ] B11：preset 的 `skipped` 非空時，預覽上方顯示提示列（格式見常數）；為空時不顯示。【已由 R4 取代：分兩級、中文名稱、提示列固定在工具列一行，句型見常數「略過提示列（觀感級，R4）」與「略過附註（細節級，R4）」】
- [ ] B12：伺服器不寫任何照片或 preset 檔（本切片沒有匯出）；跑完全部測試後 preset 合併雜湊仍為 `15C015CC0C080FF9`。
- [ ] B13：`python -s -m unittest discover -s tests` 結束碼 0（含新的 API 與伺服器測試；伺服器測試用 aiohttp 的測試客戶端，不需要開瀏覽器）。前端邏輯測試（`node --test tests/js/test_logic.cjs`，由 `tests/test_app_frontend.py` 呼叫）屬於 B13，不得跳過：找不到 node 視為失敗（2026-10-04 封緘第 1 輪 F3）。
- [ ] B14：核心切片封緘時記下的低嚴重度觀察，一併修掉：(1) `TestCoverage` 改用測試內獨立寫的已渲染鍵清單，並斷言它等於 `_coverage.RENDERED`；(2) 用已知 `skipped` 內容的合成 preset 逐字斷言 `apply` 略過行；(3) 輸出路徑沒有副檔名時，錯誤（格式）的 `{ext}` 顯示 `（無副檔名）`，並補測試（核心合約 Verbatim Constants 一併補註）。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 前後端 JSON（B3～B5、B8） | 見條文 | 之後的 preset 庫、匯出、② AI → 欄位一變前端整個壞掉｜上下游契約 | `test_api_presets_shape`、`test_api_open_shape`、`test_api_preview_semantics`、`test_api_folder` |
| 微調語意（B5） | 強度後加差值再夾 | 使用者的微調 → 跟介面顯示的數值不同，調出來的不是看到的｜邏輯核心 | `test_overrides_added_after_strength` |
| 照片與 preset 原檔（B4、B12） | 只讀 | 使用者照片與 preset → 被寫壞無法復原｜不可逆／資料 | `test_server_never_writes`、`test_presets_untouched_hash` |
| 只綁本機（B2） | 127.0.0.1 | 使用者的照片 → 綁到 0.0.0.0 時區網內任何人都能讀｜不可逆／資料 | `test_server_binds_localhost` |
| 略過提示列（B11） | 見常數 | 使用者 → 不知道 preset 有部分沒套到｜UI/UX | `test_skip_banner_text` |

## Verbatim Constants
```text
預設埠號：8765
略過提示列：這個 preset 有 {n} 項設定無法套用：{items_joined_by_、}（R4 起作廢，改用下兩行）
略過提示列（觀感級，R4）：這個 preset 有 {n} 項會改變觀感的設定無法套用：{items_joined_by_、}
略過附註（細節級，R4）：另有 {n} 項細節設定未套用：{items_joined_by_、}
夾值標示（R3）：（原 {raw}）
滑桿 tooltip（R3，未夾值）：preset × {strength}% = {raw}
夾值 tooltip（R3）：preset × {strength}% = {raw}，已到{上限|下限} {bound}
tooltip 後綴（R3，依序接在上兩行之後）：有微調時「；微調 {±tweak}」，最後一律「；雙擊＝還原這一項」（例：preset × 150% = 120，已到上限 100；微調 -5；雙擊＝還原這一項）
換照片提示（R5）：目前修改尚未儲存，切換照片會沿用
預覽像素上限：1500000
啟動完成（stdout）：darkroom 已啟動：http://127.0.0.1:{port}/
設定檔：config.local.json（鍵：localllms_root、preset_dir）；環境變數：LOCALLLMS_ROOT
```

## 條文補丁（Patches）
- R1（2026-10-04，指揮部判決）B7／A17 跳過判準：原文「`--query-compute-apps` 列出本程序以外的運算型程序就跳過」在 WDDM 下連桌面程式都列出，改成只看 Type C 後，使用者幾乎一直開著的 ComfyUI 仍讓量測永遠跳過，驗收形同虛設；改為「真的有人在用 GPU 才跳過」（使用率取樣中位數 > 15%，或 ComfyUI 佇列非空；佇列連不到當不忙），條文見 B7。
- R2（2026-10-04，指揮部判決，依 R10 判為符合）B14 附帶：核心封緘測試 `test_no_private_imports_outside_tests` 的 regex 由 `from\s+darkroom\.?_\w*` 改為 `from\s+darkroom\._\w*`。證據：舊寫法把 `from darkroom_app import ...`（`tools/bench_preview.py`）誤判為私有 import；新寫法仍攔得住 `from darkroom._io`、`from darkroom import _io`、`import darkroom._render`。
- R3（2026-10-04，介面審查第 4、11 點）微調語意改以畫面值為準（修訂 B5、B10）：
  - 畫面值與後端最終值＝`clamp(clamp(preset 在該強度的值) + 微調)`（B5 原為 `clamp(preset 在該強度的值 + 微調)`）。
  - 使用者把滑桿設到畫面值 v 時，微調＝`v − clamp(preset 在該強度的值)`；|微調| < 半個步長記為 0。例：對比 preset −75、強度 150% → preset×強度 −112.5、畫面 −100；拉到 −100＝微調 0（不得記成 +12.5），拉到 −90＝微調 +10。
  - preset×強度超出範圍被夾住時，該列加 `.clamped`、數值旁顯示「夾值標示」、tooltip 用「夾值 tooltip」句型；tooltip 隨強度與微調即時更新。
  - 微調仍是差值：改強度時畫面值＝`clamp(新的夾後 preset×強度 + 同一微調)`。
  - 釘死測試：`test_overrides_added_after_clamped_strength`（後端）、`tests/js/test_logic.cjs` 的 slider 語意測試（前端）。
- R4（2026-10-04，介面審查第 5 點）略過項分兩級（修訂 B11）：
  - 細節級＝雜色減少（`ColorNoiseReduction*`、`LuminanceSmoothing`、`LuminanceNoiseReduction*`）、`SharpenDetail`、`SharpenEdgeMasking`、`GrainFrequency`、鏡頭校正（`AutoLateralCA`、`LensProfile*`、`Defringe*`、`VignetteAmount`、`VignetteMidpoint`）、`PostCropVignetteHighlightContrast`、`PostCropVignetteStyle`、負的 `PostCropVignetteRoundness`、讀檔時超出範圍被夾值的項目；其餘（白平衡絕對值、Look、CameraProfile、HDR、遮罩、點顏色、未知鍵）＝觀感級。
  - preset 樹：有觀感級才標 ⚠（`.flag.major`）；只有細節級時標淡色小記號（`.flag.minor`）；分級由 `GET /api/preset_flags`（`{id: "major"|"minor"}`，沒有略過項的不列）提供，B3 的 5 個欄位不變。
  - 提示列只列觀感級、用中文名稱（對照表 `darkroom_app/skips.py`），句型見常數；細節級以淡色附註列在後面；提示列固定在預覽工具列的一行，出現或消失都不改變預覽區的位置與大小。
  - 釘死測試：`test_skip_banner_text`、`test_skip_levels`、`test_preset_flags`、`test_banner_does_not_move_preview`（瀏覽器量測，見截圖紀錄）。
- R5（2026-10-04，介面審查第 1、2、12 點）換 preset 與復原（修訂 B9、B10）：
  - 點 preset 時強度與微調都保留（取代 B9「強度回 100 且清空微調」）。
  - 復原／重做：Ctrl+Z／Ctrl+Shift+Z（也接受 Ctrl+Y），至少 50 步，記錄 preset、強度、微調；一次拖動只記一步；換 preset、改強度、單項還原、還原全部、直接輸入數值各記一步；焦點在文字輸入框時不攔截。
  - 未選 preset 時強度滑桿停用（強度值保留給下一個 preset）。換照片沿用目前設定（照片庫那一片再改）。
  - 「換照片提示」的顯示條件＝已開啟照片，且（已選 preset 或至少有一項微調）；兩者皆無時不顯示（封緘第 1 輪 F4）。
  - 狀態轉換（選 preset、強度、數值、單項／全部還原、手勢結束、復原、重做）一律由 `static/logic.js` 的純函式 `reduce` 處理，`app.js` 只派送動作與更新畫面，不得直接改狀態（封緘第 1 輪 F2）。
  - 釘死測試：`tests/js/test_logic.cjs` 的 History 測試。
- R6（2026-10-04，介面審查第 6、7、8 點與鍵盤、搜尋）：
  - 鍵盤：preset 樹 `role=tree`、roving tabindex；↑↓ 移動焦點、Enter 套用 preset（資料夾則展開／收合）、→ 展開資料夾（已展開則移到第一個子項）、← 收合（已收合或是 preset 則移到上一層）；區塊標題是 `<button aria-expanded>`。
  - 搜尋同時比對名稱與分類（group），空白分隔多個關鍵字，全部符合才列出（不分大小寫）；例如「電影」列出電影分類底下全部 preset。
  - 視窗寬 820 時：強度滑桿可見且寬度 ≥ 200px、預覽區寬度 ≥ 400px（左欄自動收合，可用按鈕叫出；右欄縮窄）。
  - 窄視窗不得藏掉功能按鈕或提示（復原、重做、還原全部、上一張／下一張、欄位開關、↺ 100%、換照片提示）：可以縮成圖示，但要保留 tooltip；任何 media query 都不得對它們用 `display: none`、`visibility: hidden`、`width: 0`、`height: 0`（含 `max-` 版本）、`opacity: 0`，`index.html` 裡也不得帶 `hidden` 屬性（換照片提示除外：依 R5 條件由程式切換；縮成圖示時只准裁掉長文字子元素）（封緘第 1 輪 F1、F6；R8 擴充）。判斷方式與完整禁止清單（巢狀 `@media`／`@supports`、逗號逐項判斷、clip、1px、`transform: scale(0)` 等）見 `CONTRACT-heic.md` H11，兩份合約一致。
  - 滑桿數值與強度數值可點兩下直接輸入（Enter 確認、Esc 取消，超出範圍夾值）；數值外觀是文字、重設強度的按鈕是「↺ 100%」按鈕外觀。
  - 曲線區塊上方有唯讀小曲線圖，畫出 preset 套強度後的點曲線（RGB 與存在的各色版）；`GET /api/presets/{id}` 增加 `curves`。
  - 釘死測試：`tests/js/test_logic.cjs`（樹鍵盤、搜尋、數值輸入、曲線強度）、`test_api_preset_detail_curves`、`test_layout_820`（瀏覽器量測，見截圖紀錄）。
- R7（2026-10-04，封緘第 1 輪 F9）R3 公式在前端（`logic.js`）與後端（`preview.effective_params`）各有一份實作，共用一份案例表 `tests/cases/r3_slider_cases.json`，同時驅動 `tests/js/test_logic.cjs` 與 `test_r3_shared_cases`；案例至少涵蓋夾到上限、下限、色相鍵、強度 0／100／200。
- R8（2026-10-04，封緘遺留 N1、N2，於 HEIC 切片收掉，見 `CONTRACT-heic.md` H10、H11）：
  - N1：`app.js` 對 `ed` 的賦值恰為 `let ed = L.initialEditor()` 與 `ed = L.reduce(ed, action)` 兩處，不得 `Object.assign(ed, …)` 或 `ed[…] =`（結構測試 `test_app_changes_state_only_through_the_reducer`）。
  - N2：R6 的禁止清單擴充如上（`test_narrow_windows_keep_function_buttons`）。
