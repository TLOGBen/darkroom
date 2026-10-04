# CONTRACT — darkroom App 外殼（啟動、預覽伺服器、三欄編輯器）

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
- [ ] B5：`POST /api/preview {"image_id","preset_id"|null,"strength","overrides"}` 回傳 `image/jpeg`；最終值＝`clamp(preset 在該強度的值 + 微調)`（微調是加在強度之後的差值）；`preset_id` 為 null 時只套微調；回應標頭 `X-Render-Ms` 帶後端渲染毫秒數。
- [ ] B6：預覽渲染在專用的高優先 CUDA stream 上、只同步自己那條 stream（不得呼叫 `torch.cuda.synchronize()`）；JPEG 用 cv2 在 CPU 編碼；GPU 工作在單一執行緒 executor，不阻塞事件迴圈。
- [ ] B7：延遲驗收腳本（`tools/bench_preview.py`）對 24MP 測試圖以 60 Hz 模擬拖動 10 秒、最新一次優先：往返中位數 < 100 ms、p95 < 150 ms；量測前判斷 GPU 是否忙碌，忙碌才跳過並印出原因（使用率數字或佇列長度）：(a) 約 1 秒內以 `nvidia-smi --query-gpu=utilization.gpu` 取樣 5 次，中位數 > 15% ＝忙碌；(b) `nvidia-smi --query-compute-apps` 有路徑含 `comfyui` 的程序時，查 `http://127.0.0.1:8188/queue`，`queue_running` 或 `queue_pending` 非空＝忙碌，連不到＝不忙；(c) nvidia-smi 無法執行＝無法判斷，也跳過並印出原因。ComfyUI 常駐但佇列空、使用率不高時照常量測（核心 A17 的跳過判準一併改成這條，取代「已用記憶體扣本程序 > 1 GiB」；2026-10-04 條文補丁 R1，見文末）。釘死測試 `tests/test_app_gpucheck.py`（忙、閒、佇列連不到、nvidia-smi 失敗、門檻邊界）。
- [ ] B8：`GET /api/folder?image_id=` 回傳同資料夾、依檔名排序的 JPEG／PNG／TIFF 清單與目前位置；前端「上一張／下一張」照它切換，第一張按上一張、最後一張按下一張時不動作。
- [ ] B9：前端三欄（`#preset-tree`、`#preview`、`#sliders`）；preset 依 `group` 的「 - 」切成兩層樹，可用名稱搜尋；點 preset 時強度回 100 且清空微調；強度滑桿 0～200 在預覽正下方。
- [ ] B10：拖滑桿時前端只保留最新一筆待送參數（最新一次優先），不得累積佇列；微調過的滑桿加 `.adjusted` class，單項還原鈕把該鍵的微調歸零。
- [ ] B11：preset 的 `skipped` 非空時，預覽上方顯示提示列（格式見常數）；為空時不顯示。
- [ ] B12：伺服器不寫任何照片或 preset 檔（本切片沒有匯出）；跑完全部測試後 preset 合併雜湊仍為 `15C015CC0C080FF9`。
- [ ] B13：`python -s -m unittest discover -s tests` 結束碼 0（含新的 API 與伺服器測試；伺服器測試用 aiohttp 的測試客戶端，不需要開瀏覽器）。
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
略過提示列：這個 preset 有 {n} 項設定無法套用：{items_joined_by_、}
預覽像素上限：1500000
啟動完成（stdout）：darkroom 已啟動：http://127.0.0.1:{port}/
設定檔：config.local.json（鍵：localllms_root、preset_dir）；環境變數：LOCALLLMS_ROOT
```

## 條文補丁（Patches）
- R1（2026-10-04，指揮部判決）B7／A17 跳過判準：原文「`--query-compute-apps` 列出本程序以外的運算型程序就跳過」在 WDDM 下連桌面程式都列出，改成只看 Type C 後，使用者幾乎一直開著的 ComfyUI 仍讓量測永遠跳過，驗收形同虛設；改為「真的有人在用 GPU 才跳過」（使用率取樣中位數 > 15%，或 ComfyUI 佇列非空；佇列連不到當不忙），條文見 B7。
- R2（2026-10-04，指揮部判決，依 R10 判為符合）B14 附帶：核心封緘測試 `test_no_private_imports_outside_tests` 的 regex 由 `from\s+darkroom\.?_\w*` 改為 `from\s+darkroom\._\w*`。證據：舊寫法把 `from darkroom_app import ...`（`tools/bench_preview.py`）誤判為私有 import；新寫法仍攔得住 `from darkroom._io`、`from darkroom import _io`、`import darkroom._render`。
