# ① 校正集要渲染哪些圖、怎麼做？

Type: task
Status: resolved

## Question

使用者決定用 Lightroom 免費試用期一次性渲染校正集（見「① 「像 Lightroom」的驗收方式？」）。要寫出一份使用者照做就能完成的清單：用哪幾張標準照片（含灰階漸層卡、色卡、人像、風景、高反差場景；照片從哪裡來、授權），哪些滑桿要掃（優先亮部、陰影、白、黑、曝光，再來清晰度、去朦朧、紋理、對比、鮮豔度、飽和度、白平衡增量、HSL 抽樣、顏色分級抽樣），每個滑桿的取值（例如 -100、-50、-25、+25、+50、+100），怎麼用 Lightroom 批次做（建立 preset 並批次匯出），匯出格式（16-bit TIFF、色彩空間），檔名規則，總張數與預估時間；再加幾個真實 preset 的整體渲染當驗收。產出放 `prototypes/calibration/`。AFK：代理寫清單與準備標準照片，不需要使用者參與；實際在 Lightroom 操作是之後的事。

## Answer

（2026-10-04，執行子代理；全部在 [prototypes/calibration/](../prototypes/calibration/)。主 session 驗收：必做 preset 71 個、選做 130 個、3 張合成標準圖（16-bit TIFF）＋`layout.json`、README 約 235 行；子代理在 scratchpad 完整跑過一次 `build`，773 個檔案產生、4 張真實照片 SHA1 相符、TIFF 讀回像素一致、201 個 preset 與內嵌 XMP 都能解析。）

- **使用者操作清單**：`README.md`（裝試用版、匯入、抽查 3 張、匯出設定、用 `check` 比對有沒有漏、搬檔、第 7 天前取消試用；備案、來源授權、完整掃描表、檔名規則、已知限制）。`make_calibration_set.py build` 產生合成圖、下載驗證真實照片、產生 preset 與檔案（大檔放 `scratch/lr-calibration/`）；`check <匯出資料夾>` 列出缺的圖。
- **標準照片**：合成圖 `syn-tone`（漸層、21 階灰、線性光對數漸層、黑白兩端細階）、`syn-detail`（7 種頻率條紋、光暈稜線、細雜訊、中頻紋理）、`syn-color`（ColorChecker 24 色、16 膚色、36 色相 × 6 明度飽和）；真實照片 4 張都是 Wikimedia Commons CC0（人像、高反差風景、夜景、霧景）。
- **方案 A（主要）**：每張標準圖 × 每個設定各一份檔案、Camera Raw 設定預先寫進檔案，匯入後全選一次匯出——未在 Lightroom 實測，README 第 3 步要使用者先抽查 3 張；讀不到時先試「從檔案讀取中繼資料」，再不行改方案 B（匯入 preset zip 逐個套）。
- **張數**：必做 71 個設定、429 張、約 4～5GB（全歸零基準；曝光 -2～+2 EV 8 階；亮部、陰影、白、黑各 8 階；對比、清晰度、去朦朧、紋理各 4 階；4 組相加檢查；10 個真實 preset 整體驗收含 PV 15.4 與 6.7 各一）。選做 130 個、344 張、約 3～4GB（鮮豔度、飽和度、白平衡、HSL 48、顏色分級 22、曲線 16、校正、暗角、黑白、顆粒、解析度相依——README 建議一定要做，關係到 1.5MP 預覽與 24MP 輸出看起來一不一樣）。
- **使用者操作時間**：方案 A 實際動手約 30～40 分鐘、全程約 1～1.5 小時；只走方案 B 必做再多 30～40 分鐘、選做再多 50～60 分鐘。
- **使用者要自己做的**：註冊試用（要登錄付款方式）、安裝 Lightroom Classic、匯入、抽查、匯出、取消試用；跑一次 `build`。
- **匯出位置（主 session 照 repo 規則決定）**：`outputs/lr-calibration/`，檔名前加 `<YYYY-MM-DD>-`，Lightroom 版本記在 `<YYYY-MM-DD>-lr-version.txt`；已請子代理改 README 與 `check`（忽略日期前綴）。


## Comments

（2026-10-04 使用者確認時機）校正集由使用者在 **① 引擎做出 alpha 版（能套 preset）之後** 才開始 Lightroom 試用並渲染，目的是在同一個 7 天試用內先校一輪，發現缺的取值還能補渲染；不要提早做。
