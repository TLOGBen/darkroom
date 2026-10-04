# CONTRACT — darkroom HEIC 支援（讀檔、色彩、方向、App 與 CLI）

## 目標
使用者的 iPhone 24MP HEIC 照片能直接在 darkroom 開啟、預覽、上一張／下一張，也能當 `python -m darkroom apply` 的輸入；顏色照照片內嵌的描述（Display P3）轉換、10-bit 不先降成 8-bit、直拍方向正確。RAW 不在這一片。

## 前提（Premises）
- P1 已驗（2026-10-04 實測 `scratchpad/heic_probe.py`）：pillow-heif 1.8.0（libheif 1.23.4、x265 編碼、libde265 解碼）裝在 darkroom 專用 Python，`pip install --dry-run` 確認只新增 pillow-heif、不動 pillow 12.3.0 與 numpy。
- P2 已驗：寫進 HEIC 的 ICC（588 bytes）用 `open_heif(...).info["icc_profile"]` 原樣讀回。
- P3 已驗：16-bit 來源存成 HEIC 是 10-bit；加 `matrix_coefficients=0` 時 8／10-bit 都是逐位元無損（實測原始像素誤差 0）；`open_heif(convert_hdr_to_8bit=False)` 回傳 mode `RGB;16`、`info["bit_depth"]=10`，值左移 6 位（最大 65472、低 6 位全 0）；`quality=-1, chroma=444` 存回的誤差：10-bit 最大 127/65535，8-bit 最大 1/255。
- P4 已驗：EXIF Orientation=6 存檔後，libheif 讀出的像素已是顯示方向（等於 PIL `ROTATE_270`，誤差 ≤ 1/255），但 `HeifFile.info` 的 EXIF 仍寫 6 → 讀檔時不得再套一次 EXIF 方向。
- P5 未驗、不入條文：iPhone 真實檔案的 HDR 增益圖（aux image）與 Apple 的 Display P3 描述檔細節（沒有可公開的 iPhone 樣本；不用使用者私人照片）。超出 sRGB 色域的 P3 顏色會被夾到 sRGB（核心工作空間是 sRGB 線性）。

## 可斷言條文
- [ ] H1：`read_image` 讀 `.heic`／`.heif`（副檔名不分大小寫）；只讀檔、只解主影像（primary），縮圖、第二張影像、深度圖與輔助影像（含 HDR 增益圖）一律忽略，不得讓讀檔失敗。核心合約補丁 K1 記此行為改變（其餘格式不變）。
- [ ] H2：10／12-bit 以 `convert_hdr_to_8bit=False` 解碼，換算＝`(v >> (16 − bit_depth)) / (2^bit_depth − 1)`；1024 階的 10-bit 漸層讀回後同一通道至少 1000 個不同值（8-bit 最多 256）。
- [ ] H3：色彩：內嵌 ICC 為矩陣／曲線型（`rXYZ/gXYZ/bXYZ` ＋ `curv`/`para` 曲線）時，以 float 精度轉成 sRGB 編碼（曲線 → XYZ D50 → Bradford 調適的 sRGB 矩陣 → 夾 0～1 → sRGB 曲線），輸出與 `read_image` 既有約定相同（HxWx3 float32、0～1、sRGB 編碼，`render` 內再轉線性）；沒有 ICC 時看 nclx：色彩原色 12（P3）照 P3 轉，其餘當 sRGB；其他型態的 ICC（LUT 型）改用 LittleCMS 8-bit 轉換（已知限制）。
- [ ] H4：容差（測試 HEIC 用真正無損編碼：`quality=-1, chroma=444, matrix_coefficients=0`，像素原樣存回；P3 的期望值由測試用公開的 P3／sRGB D65 矩陣獨立算出）：
  sRGB 8-bit 對 PNG：最大差 ≤ 2/255、平均差 ≤ 0.5/255；sRGB 10-bit 對 16-bit PNG：最大差 ≤ 0.004、平均差 ≤ 0.001（sRGB 編碼值）；
  Display P3 對期望 sRGB 在線性光比較（P3→sRGB 會把暗通道的量化誤差在 sRGB 編碼上放大約 9 倍，故不在編碼值上比）：10-bit 最大差 ≤ 0.003、平均差 ≤ 0.0005；8-bit 最大差 ≤ 0.008、平均差 ≤ 0.0015；忽略描述檔讀同一張 P3 圖時，誤差必須大於 10 倍容差（證明真的有轉換）。
- [ ] H5：方向：像素照 libheif 套用 irot／imir 後的結果，不再套 EXIF Orientation；EXIF 方向 3、6、8 的測試檔讀回後等於來源經 PIL 對應轉置（3＝ROTATE_180、6＝ROTATE_270、8＝ROTATE_90），差在 H4 的 8-bit 容差內。
- [ ] H6：壞檔（截斷、空檔、亂碼、副檔名對但內容不是 HEIC）→ `read_image` 拋 `ValueError`（原因句型見常數），程序不得當掉；影像資料部分損毀但 libheif 仍解得出時，回傳解出的像素或 `ValueError`，兩者皆可、不得當掉；CLI `apply` 印「錯誤（照片）」行、結束碼 2、不產生輸出；App `POST /api/open` 回 400 與「App 開檔錯誤」句型，之後的請求照常回應。
- [ ] H7：App：`.heic`／`.heif` 出現在開啟允許的格式與 `GET /api/folder` 清單（依檔名排序規則不變）；`/api/open` 的 `width`／`height` 是轉正後的尺寸；B7 延遲驗收照舊（R1 跳過規則）。
- [ ] H8：CLI：`apply` 接受 HEIC 輸入，輸出格式不變（`.heic` 當輸出＝「錯誤（格式）」）。
- [ ] H9：測試只用程式產生的 HEIC（`tests/_heicgen.py`：Display P3 與 sRGB 各一、8-bit 與 10-bit 各一、方向標記、含縮圖與第二張影像各一），Display P3 描述檔由 `tests/_iccgen.py` 組出；不用使用者照片；`python -s -m unittest discover -s tests` 結束碼 0、preset 合併雜湊仍為 `15C015CC0C080FF9`。
- [ ] H10（App 外殼 N1）：`app.js` 對 `ed` 的賦值恰為 `let ed = L.initialEditor()` 與 `ed = L.reduce(ed, action)` 兩處（結構測試），反向驗證：在 `selectPreset` 加 `ed = Object.assign({}, ed, {strength: 100, tweaks: {}})` 必須變紅。
- [ ] H11（App 外殼 N2）：R6「不得藏掉」的禁止清單擴充為 `display:none`、`visibility:hidden`、`width:0`、`height:0`、`opacity:0`（任何 media query），以及 `index.html` 裡這些元素不得帶 `hidden` 屬性（換照片提示除外：它依 R5 條件由程式切換）。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 色彩轉換（H3、H4） | 見條文 | 使用者照片 → 顏色偏掉、P3 照片變灰或過飽和｜邏輯核心 | `test_p3_10bit_matches_reference`、`test_srgb_8bit_matches_png` |
| 位元深度（H2） | 10-bit 保留 | 漸層 → 出現色階斷層｜邏輯核心 | `test_10bit_not_reduced_to_8bit` |
| 方向（H5） | 不重複套 EXIF | 直拍照片 → 躺著或倒過來｜UI/UX | `test_orientation_applied_once` |
| 壞檔（H6） | ValueError／400 | App → 伺服器當掉、整個編輯器失效｜可用性 | `test_broken_heic_*` |
| 照片原檔（H6、H7） | 只讀 | 使用者照片 → 被改寫｜不可逆／資料 | `test_server_never_writes`（加 HEIC） |

## Verbatim Constants
```text
支援副檔名（讀）：.jpg .jpeg .png .tif .tiff .heic .heif（不分大小寫）
套件：pillow-heif==1.8.0（darkroom 專用 Python：python -s -m pip install --no-deps pillow-heif==1.8.0）
缺套件原因：讀 HEIC 需要 pillow-heif（python -s -m pip install --no-deps pillow-heif==1.8.0）
解碼失敗原因：HEIC 解碼失敗：{detail}
App 開檔錯誤：照片讀取失敗：{file_name}：{reason}
CLI 錯誤（照片）：沿用核心常數「照片讀取失敗：{input_path}：{reason}」
容差：見 H4（數字逐字照抄進 tests/test_heic.py）
```
