# Lightroom 校正集：照著做就能完成的清單

## 當天照這張做就好（先看這段）

下面的指令都在 **pwsh** 裡跑。開一個 pwsh 視窗，先貼這三行（整天都用同一個視窗的話只要貼一次）：

```powershell
cd D:\Code\darkroom
$PY  = "C:/Users/powde/workspace/LocalLLMs/runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe"
$GEN = ".claude/wayfinder/darkroom/prototypes/calibration/make_calibration_set.py"
```

1. **先設提醒（30 秒）**：手機行事曆設「試用第 6 天：取消 Adobe 試用」。試用要登錄付款方式，第 7 天前沒取消就會扣款。
2. **產生要匯入的檔案（約 2 分鐘，前一天先做也可以）**：`& $PY -s $GEN build`。最後出現「設定數：必做 71、選做 130；方案 A 檔數：必做 429、選做 344」就是成功，檔案在 `C:\Users\powde\workspace\LocalLLMs\scratch\lr-calibration\`。
3. **安裝 Lightroom Classic（動手 10 分鐘，下載安裝另等 5～15 分鐘）**：Adobe 官網 → Photography 方案 7 天免費試用 → 用 Creative Cloud 裝 **Lightroom Classic**（不是雲端版「Lightroom」）。打開後新建 catalog `D:\lr-calibration\calib.lrcat`；編輯 → 偏好設定 →「預設集」確認**沒有**勾「套用自動色調調整」。（詳細：下面第 1 步）
4. **匯入（動手 3 分鐘，等約 5 分鐘）**：來源選 `C:\Users\powde\workspace\LocalLLMs\scratch\lr-calibration\planA\must`（有空也加 `optional`）；上方選「**新增**」；取消勾「不要匯入可疑的重複項目」；修片設定「無」、中繼資料「無」。（詳細：第 2 步）
5. **抽查 3 張（1～3 分鐘）**：到修片模組看第 3 步表格裡那 3 張，滑桿數字對就繼續。全是 0 → 圖庫模組 Ctrl+A，「中繼資料 → 從檔案讀取中繼資料」再看；還是 0 → 改走下面的方案 B。
6. **匯出（動手 5 分鐘，等 10～25 分鐘）**：Ctrl+A 全選 → 匯出到 `C:\Users\powde\workspace\LocalLLMs\outputs\lr-calibration`（不要勾子資料夾）；檔名範本 `{自訂文字}-{檔名}`，自訂文字填**今天日期**（例如 `2026-10-20`）；**TIFF、ZIP 壓縮、sRGB、16 位元**；不縮圖、不輸出銳利化。（完整設定表：第 4 步）
7. **記版本（1 分鐘）**：在同一個資料夾新增文字檔 `<今天日期>-lr-version.txt`，寫 Lightroom Classic 版本（說明 → 系統資訊第一行）和 Camera Raw 版本。
8. **檢查有沒有漏（1 分鐘）**：`& $PY -s $GEN check C:/Users/powde/workspace/LocalLLMs/outputs/lr-calibration`。必做要「缺 0」，有缺就回 Lightroom 補匯出那幾張。匯出到別的資料夾或忘了加日期：`& $PY -s $GEN stamp <那個資料夾> <今天日期>`，會補前綴並搬過去。
9. **擬合（電腦自己跑約 3～5 分鐘；先關掉 ComfyUI 這類佔 GPU 的程式）**：

   ```powershell
   & $PY -s .claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py fit
   ```

   它讀上面那個匯出資料夾，標準圖用 `C:\Users\powde\workspace\LocalLLMs\scratch\lr-calibration\planB_base\`，報告寫到 `D:\Code\darkroom\outputs\calibration\<今天日期>-fit-report.md`。只給建議常數，不會改程式。GPU 記憶體不夠就加 `--stride 3`。
10. **趁試用還在，看一下報告**：把報告交給 Claude。報告說某個滑桿「撞到搜尋邊界」或「擬合後平均 ΔE 仍 > 3」，代表光調常數不夠，可能要補渲染別的取值——這時 Lightroom 還能用。
11. **取消試用**：`check` 缺 0、擬合也跑完以後，到 account.adobe.com → 方案 → 取消方案，確認收到取消信。

**時間**：你要動手的大約 **40～50 分鐘**；從頭到尾大約 **1.5～2 小時**（其他時間是等下載、匯入、匯出、擬合）。只做必做的話匯出少等約 10 分鐘。

---

- 日期：2026-10-04
- 票：`issues/14-calibration-set.md`
- 產生器：`make_calibration_set.py`（可重跑；用 darkroom 專用 Python，只用它內建的 numpy／PIL／cv2）
- 擬合工具：本資料夾的 `fit_calibration.py`（它要讀核心內部常數，所以放在原型資料夾，不放 `tools/`）（`fit` 擬合、`selftest` 用假 Lightroom 驗證流程）
- 路徑（2026-10-09 更新）：這個資料夾現在在 darkroom repo 的 `.claude/wayfinder/darkroom/prototypes/calibration/`；大檔與匯出仍放 LocalLLMs（`scratch/lr-calibration/`、`outputs/lr-calibration/`）

## 目的

darkroom 自己寫的 Lightroom XMP 調色，有幾項 Adobe 沒公開演算法（亮部、陰影、白、黑、清晰度、去朦朧、紋理、PV2012 曝光滾降），只能先用近似法加上猜的初始值（見 `research/03-proprietary-approximations.md` §10）。這份校正集是：**趁 Lightroom 7 天免費試用，一次把「只動一個滑桿」的結果全部渲染出來**。之後就能離線把我們的曲線擬合到 Lightroom 的結果（用 ΔE、亮度曲線差來量；工具是 `.claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py`），不必再開 Lightroom。

## 總量與時間

| | 設定數（＝preset 數） | 要匯出的圖（方案 A） | 匯出後大小（估） |
|---|---|---|---|
| **必做** | 71 | **429 張** | 約 4～5 GB |
| 選做 | 130 | 344 張 | 約 3～4 GB |
| 合計 | 201 | 773 張 | 約 8 GB |

**預估時間（方案 A）**：你實際要動手的大約 **40～50 分鐘**，從開始到結束大約 1.5～2 小時（中間是電腦自己匯出、擬合）。

| 步驟 | 你要動手 | 電腦自己跑 |
|---|---|---|
| 0. 產生檔案（一行指令） | 1 分 | 約 1 分（第一次會下載 4 張照片，約 42 MB） |
| 1. 裝 Lightroom Classic、開始試用 | 10 分 | 下載安裝 5～15 分 |
| 2. 匯入 773 個檔案 | 3 分 | 約 5 分 |
| 3. 抽查 3 張，確認設定有讀進來 | 3 分 | — |
| 4. 設定匯出、按匯出 | 5 分 | 必做約 8～15 分；選做再約 8～12 分 |
| 5. 用 `check` 比對有沒有漏 | 2 分 | — |
| 6. 記版本、搬檔案 | 3 分 | — |
| 7. 跑擬合、看報告，再取消試用 | 5 分 | 約 3～5 分 |

只做「必做」也可以；選做是加分，有空就一起做（方案 A 多做選做，你只多花 1 分鐘，主要是電腦多跑 10 分鐘）。

## 怎麼做：方案 A（主要做法，一次匯出）

**原理**：Lightroom 匯入 JPEG／TIFF 時，會讀取檔案裡面內嵌的 Camera Raw 設定（XMP 的 `crs:` 欄位）當作這張的編輯設定；用 Bridge／Camera Raw 修過的 JPEG 匯入 Lightroom 後還看得到修圖，就是這個原理。所以產生器替「每張標準圖 × 每個設定」各做一份檔案，設定先寫在檔案裡面。匯入以後**全選、匯出一次就完成**，不必一個一個套 preset。

### 0. 產生檔案（pwsh，在 darkroom 根目錄 `D:\Code\darkroom` 跑）

```powershell
cd D:\Code\darkroom
$PY  = "C:/Users/powde/workspace/LocalLLMs/runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe"
$GEN = ".claude/wayfinder/darkroom/prototypes/calibration/make_calibration_set.py"
& $PY -s $GEN plan    # 只看數量（不下載、不寫檔），可省略
& $PY -s $GEN build
```

- 用 darkroom 專用 Python，不用 ComfyUI 的 `python_embeded`。LocalLLMs 的位置從環境變數 `LOCALLLMS_ROOT` 或 darkroom 根目錄 `config.local.json` 的 `localllms_root` 讀。
- 指令裡的 `$GEN` 是相對路徑，所以一定要先 `cd D:\Code\darkroom`（不是 LocalLLMs 根目錄）。
- 會產生到 `<LocalLLMs>/scratch/lr-calibration/`（隨時能重產，所以放 scratch）：
  - `planA/must/`（429 個）、`planA/optional/`（344 個）：設定已經寫在檔案裡面的圖檔
  - `planB_base/`：沒有設定的乾淨原圖（方案 B 用）
  - `sources/`：從 Wikimedia Commons 下載的原檔（會驗 SHA1）
- 結尾印出「設定數：必做 71、選做 130；方案 A 檔數：必做 429、選做 344」就是成功了。
- 照片下載失敗的話，它會列出網址和要存的位置，手動下載後加 `--no-download` 再跑一次。

### 1. 安裝試用版

1. 到 Adobe 官網選 **Photography 方案（含 Lightroom Classic）的 7 天免費試用**；要登錄付款方式，第 7 天前沒取消就會開始扣款。**請先在手機行事曆設好第 6 天提醒「取消 Adobe 試用」**。
2. 用 Creative Cloud 安裝 **Lightroom Classic**（不是雲端版「Lightroom」；雲端版沒有這裡用到的匯出選項）。
3. 打開後新建一個 catalog（例如 `D:\lr-calibration\calib.lrcat`），不要跟別的東西混在一起。
4. 編輯 → 偏好設定 → 「預設集」分頁：確認沒有勾「套用自動色調調整」。

### 2. 匯入

1. 檔案 → 匯入相片和視訊 → 來源選 `C:\Users\powde\workspace\LocalLLMs\scratch\lr-calibration\planA\must`（要做選做的話，在左邊來源欄也勾 `optional`，或匯入兩次）。
2. 上方選 **「新增」**（Add，檔案原地不動，不要選拷貝／移動）。
3. 右邊「檔案處理」：建立預覽選「最小」；**取消勾選「不要匯入可疑的重複項目」**。
4. 右邊「匯入時套用」：**修片設定選「無」**、中繼資料選「無」。
5. 按匯入。左下角進度跑完就好。

### 3. 抽查（很重要，30 秒就能確認方案 A 行不行）

切到「修片」模組，看這 3 張的「基本」面板：

| 檔案 | 應該看到 |
|---|---|
| `A02-01_Highlights2012_m100__real-landscape` | 亮部 = -100，其他都是 0；雲層明顯變暗 |
| `A05-08_Blacks2012_p100__syn-tone` | 黑色 = +100；黑色區塊變灰 |
| `A11-07_Preset_2f20566e__real-portrait` | 黑白、對比 +5、亮部 -41、陰影 +20 |

- 看得到 → 方案 A 可行，繼續第 4 步。
- 全部是 0 → 在圖庫模組按 Ctrl+A 全選，選單 **中繼資料 → 從檔案讀取中繼資料**，再看一次。
- 還是 0 → 改走下面的方案 B。

### 4. 匯出

圖庫模組 → Ctrl+A 全選 → 檔案 → 匯出 → 「匯出至：硬碟」，設定如下（設好後可以在左邊「新增」存成匯出預設集）：

| 區塊 | 設定 |
|---|---|
| 匯出位置 | 指定資料夾：`C:\Users\powde\workspace\LocalLLMs\outputs\lr-calibration`，**不要勾「置於子資料夾」**（不開日期資料夾）；現有檔案：詢問 |
| 檔案命名 | 勾「重新命名為」→「編輯…」建一個檔名範本：**`{自訂文字}-{檔名}`**（中間一個減號），存成範本「校正-日期」；「自訂文字」欄填**今天的渲染日期**，例如 `2026-10-08`。匯出結果像 `2026-10-08-A02-03_Highlights2012_m050__real-portrait.tif`。不要用範本裡的「日期」權杖：那是照片的拍攝日期，不是今天 |
| 檔案設定 | 影像格式 **TIFF**；壓縮 **ZIP**；色彩空間 **sRGB**；位元深度 **16 位元／色版**；如果有「HDR 輸出」選項，**不要勾** |
| 調整影像尺寸 | **不要勾**（保持原尺寸，局部運算的半徑跟尺寸有關） |
| 輸出銳利化 | **不要勾** |
| 中繼資料 | 「全部」或「僅版權」都可以 |
| 浮水印 | 不要勾 |
| 後製處理 | 不執行任何動作 |

按匯出，等左上角進度條跑完。

**忘了加日期、或匯出到別的資料夾也沒關係**：用 `stamp` 補日期前綴並搬到 `<LocalLLMs>/outputs/lr-calibration/`（已經有日期前綴的檔案只搬、不會重複加）：

```powershell
& $PY -s $GEN stamp <匯出資料夾> 2026-10-08
```

**為什麼選 16-bit TIFF＋sRGB**：16-bit 才量得到 Blacks／Whites 端點附近 1～2 碼的細微差異（8-bit 會被量化吃掉）；PNG 在 Lightroom Classic 不一定能匯出，TIFF 一定可以。色彩空間用 sRGB，因為 darkroom 吃 sRGB、吐 sRGB，比較時要同一個空間；ProPhoto 雖然不會裁切飽和色，但我們之後還得自己轉換，多一個誤差來源，所以不用。

### 5. 比對有沒有漏

```powershell
& $PY -s $GEN check C:/Users/powde/workspace/LocalLLMs/outputs/lr-calibration
```

會列出必做／選做各缺幾張；缺的話回 Lightroom 找那幾張補匯出。`check` 會忽略檔名開頭的 `YYYY-MM-DD-`，有沒有日期前綴都認得。

### 6. 收尾

1. 匯出的檔案直接放在 `C:\Users\powde\workspace\LocalLLMs\outputs\lr-calibration\`（不開子資料夾、不開日期資料夾；`outputs/` 不進 git），檔名是 `<渲染日期>-<原本的檔名>.tif`。另外在同一個資料夾放 `<渲染日期>-lr-version.txt`，內容寫 Lightroom Classic 的版本號（說明 → 系統資訊，第一行）跟 Camera Raw 版本。日期前綴後面的部分不要改，後面的分析靠它找設定。
2. 確認 `check` 說「缺 0」、也跑完第 7 步擬合以後（報告有問題還能趁試用補渲染），**到 Adobe 帳號頁面取消試用**（account.adobe.com → 方案 → 取消方案），確認收到取消信。
3. 想清空間的話，`<LocalLLMs>/scratch/lr-calibration/planA/` 可以刪（之後可以重產）；**`planB_base/` 先留著**，`.claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py` 拿它當 darkroom 那一側的輸入。

### 7. 擬合（`.claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py`）

```powershell
& $PY -s .claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py fit                     # 預設讀 <LocalLLMs>/outputs/lr-calibration
& $PY -s .claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py fit --input lr-baseline # darkroom 改用 Lightroom 的 A00 全歸零輸出當輸入
& $PY -s .claude/wayfinder/darkroom/prototypes/calibration/fit_calibration.py selftest                # 假 Lightroom：用已知常數渲染，確認擬合找得回來
```

- 對亮部、陰影、白、黑（A02～A05）各算擬合前的平均 ΔE2000 與亮度曲線差，再對 `_render.py` 的常數（0.30、0.35、0.18、0.12／0.10）做一維最小平方搜尋，輸出擬合前後的表與建議常數。
- darkroom 那一側用公開 API `darkroom.load_preset`（讀 `presets/must/` 同一個 xmp）＋`render`；搜尋時用工具裡的色調鏡像，開跑前會逐張確認鏡像在目前常數下跟 `render` 一樣，不一樣就停下來。
- 報告在 `D:\Code\darkroom\outputs\calibration\<日期>-fit-report.md`。**不會改 `darkroom/_render.py`**，改常數另開切片。
- 報告裡的「基準」表是 A00 全歸零時 Lightroom 跟原圖的差，等於誤差下限；這個值明顯大於 0（Lightroom 對 JPEG／TIFF 有預設處理）時，改用 `--input lr-baseline` 再跑一次比較。

## 方案 B（備案：方案 A 讀不到內嵌設定時）

1. 匯入 `C:\Users\powde\workspace\LocalLLMs\scratch\lr-calibration\planB_base\` 的 9 張乾淨原圖（同樣選「新增」、修片設定「無」）。
2. 修片模組左邊「預設集」面板 → 「＋」→ 匯入預設集 → 選 `presets/presets_must.zip`（選做再匯入 `presets_optional.zip`）。會出現「校正 - 基準」「校正 - Highlights2012」…等群組，名稱前面有代碼，照順序排好。
3. 做一個匯出預設集：設定同上表，檔案命名改成自訂範本 **`{自訂文字}__{檔名}`**（中間是兩個底線）。
4. 每個 preset：全選 9 張 → 點 preset → 匯出 → 「自訂文字」填「渲染日期-代碼」（例如 `2026-10-08-A02-03`，代碼是 preset 名稱最前面那段）→ 匯出。檔名會是 `2026-10-08-A02-03__real-portrait.tif`。
   - 套「校正 - 驗收」裡的真實 preset 前，**先套一次 `A00-01 Baseline all0`**，因為有些真實 preset 不包含某些欄位，會沿用上一個 preset 的值。
5. `check` 一樣可以用（它只看代碼和圖名）。方案 B 每張圖都套了每個 preset，所以會多出一些清單外的檔案，不影響。
6. 時間：每個 preset 大約 20～30 秒，必做 71 個大約 30～40 分鐘、選做 130 個再 50～60 分鐘。

## 標準照片

### 合成圖（`charts/`，16-bit TIFF，內嵌 sRGB ICC；色塊位置在 `charts/layout.json`）

| 檔案 | 內容 | 主要量什麼 |
|---|---|---|
| `syn-tone.tif` | ① sRGB 碼值 0→1 連續漸層 ② 21 階灰階（相鄰無縫）③ 線性光 12 檔對數漸層（暗部取樣密）④ 兩端細階（黑端 0～22/255、白端 233～255/255，每 2 碼一階）⑤ 11 個獨立灰塊（四周是 18% 灰） | 曝光、亮部／陰影／白／黑、對比、曲線的色調響應；④ 專門抓白／黑的裁切點與「抬黑」量 |
| `syn-detail.tif` | 正弦條紋：3 種底色 × 2 種振幅 × 7 種週期（2～128 px）；亮天空＋暗山稜線（量光暈）；細雜訊塊；中頻帶通紋理塊 | 清晰度、紋理、去朦朧的頻率響應、光暈寬度；紋理「不放大雜訊」的特性 |
| `syn-color.tif` | ColorChecker 24 色（X-Rite 公布的 sRGB 近似值）、16 個膚色塊、36 色相 × 6 種明度／飽和度 | HSL 八個色帶的範圍與權重、鮮豔度／飽和度、白平衡、顏色分級、相機校正、黑白混合 |

合成圖是 TIFF（不是 JPEG）：16-bit 漸層才不會有色階斷層。JPEG 跟 TIFF 在 Lightroom 裡都是「非 RAW」，走同一條處理流程。

### 真實照片（Wikimedia Commons，全部 **CC0 1.0**，可自由使用、不需署名；產生器自動下載並驗 SHA1，資訊也存在 `sources.json`）

| 代號 | Commons 頁面 | 作者 | 用途 |
|---|---|---|---|
| `real-portrait` | https://commons.wikimedia.org/wiki/File:Woman_in_a_headwrap_in_Quebec_City.jpg | Wilfredor | 人像：膚色、黑布料暗部、亮背景 |
| `real-landscape` | https://commons.wikimedia.org/wiki/File:Wetterspitzen_(Stubaier_Alpen).jpg | Jörg Braukmann | 風景高反差：白雲＋陰影山壁、藍天、綠地 |
| `real-night` | https://commons.wikimedia.org/wiki/File:Saint_Peter%27s_Basilica,_Sant%27Angelo_bridge,_by_night,_Rome,_Italy.jpg | Jebulon | 夜景：大片暗部、點光源、鈉燈色 |
| `real-fog` | https://commons.wikimedia.org/wiki/File:Jetty_in_fog_at_Holl%C3%A4ndar%C3%B6d_1.jpg | W.carter | 低對比霧景：由近到遠霧越濃（去朦朧用） |

處理方式：依 EXIF 轉正 → 轉成 sRGB → 縮到長邊 2048（Lanczos）→ 存 JPEG 品質 95、4:4:4，只保留 sRGB ICC（原檔的 EXIF／XMP 都拿掉，避免攝影師原本的 Camera Raw 設定混進來）。風景照另外做了長邊 1024 與 4096 兩個版本，給選做 B12「解析度相依」用。

## 掃哪些滑桿（完整清單在 `manifest.csv`）

圖代號：T＝syn-tone、D＝syn-detail、C＝syn-color、P／L／N／F＝人像／風景／夜景／霧景。

### 必做（71 個設定、429 張）

| 代碼 | 群組 | 取值 | 套用的圖 | 張數 |
|---|---|---|---|---|
| A00 | 基準（全部 0） | — | 全 7 張 | 7 |
| A01 | Exposure2012 | -2、-1.5、-1、-0.5、+0.5、+1、+1.5、+2 EV | T C P L N F | 48 |
| A02 | Highlights2012 | -100、-75、-50、-25、+25、+50、+75、+100 | T D P L N F | 48 |
| A03 | Shadows2012 | 同上 | T D P L N F | 48 |
| A04 | Whites2012 | 同上 | T D P L N F | 48 |
| A05 | Blacks2012 | 同上 | T D P L N F | 48 |
| A06 | Contrast2012 | -100、-50、+50、+100 | T C P L N F | 24 |
| A07 | Clarity2012 | 同上 | T D P L N F | 24 |
| A08 | Dehaze | 同上 | 全 7 張（含色卡，看色偏） | 28 |
| A09 | Texture | 同上 | D P L F | 16 |
| A10 | 組合（效果能不能相加） | 亮-50＋影+50、亮-100＋影+100、白-50＋黑+50、曝光+1＋亮-50 | T P L N F | 20 |
| A11 | 真實 preset 驗收（10 個） | 見下表 | 全 7 張 | 70 |

### 選做（130 個設定、344 張）

| 代碼 | 群組 | 取值 | 套用的圖 | 張數 |
|---|---|---|---|---|
| B01 | Vibrance | ±50、±100 | C P L | 12 |
| B02 | Saturation | ±50、±100 | C P L | 12 |
| B03 | 白平衡增量 Temp（`IncrementalTemperature`） | ±25、±50 | T C P L | 16 |
| B04 | 白平衡增量 Tint（`IncrementalTint`） | ±25、±50 | T C P L | 16 |
| B05 | HSL：8 色 × 色相／飽和度／明度 | ±50 | C P | 96 |
| B06 | 顏色分級：陰影、亮部色相各 6 個（飽和度 50）、中間調 3 個、整體 3 個、平衡 ±50、混合 50 vs 100 | — | T C P | 66 |
| B07 | 曲線：8 條點曲線（抬黑霧面、中度 S、強 S、膠片霧面 S、壓白、提亮中間、紅通道抬暗、藍通道褪色）＋ 4 個區域曲線滑桿 ±50 | — | T C P L | 64 |
| B08 | 相機校正（陰影色調、紅綠藍原色的色相／飽和度） | ±50 | C P | 28 |
| B09 | 裁切後暗角（亮部優先、預設羽化） | ±50 | T P L | 6 |
| B10 | 黑白：中性混合、紅+50、綠+50、藍-50 | — | C P L | 12 |
| B11 | 顆粒 25／50／100（隨機，只比統計量） | — | T P | 6 |
| B12 | 解析度相依：亮-100、影+100、清晰度+100、去朦朧+100、紋理+100 | — | 風景 1024 與 4096 版 | 10 |

B12 是回答「Lightroom 的局部運算半徑是不是跟著圖的尺寸縮放」，這會決定我們 1.5MP 預覽跟 24MP 輸出看起來一不一樣，建議有空一定要做。

### 驗收用的 10 個真實 preset（`校正 - 驗收`）

| 代碼 | 原檔（前 8 碼） | 原名稱 | 為什麼挑它 |
|---|---|---|---|
| A11-01 | 0467a0ad | RETRO 02 | 霧面：正 Blacks +84＋曲線抬黑 |
| A11-02 | 132c4109 | 06 Faded Black 06 | 霧面：曲線大幅抬黑（0→66）、絕對色溫 |
| A11-03 | 2970af8c | 05 Film 05 | 膠片：低對比、曲線抬黑、絕對色溫 |
| A11-04 | 0b8938e5 | Kodak Portra 4 | 膠片＋顆粒 80（顆粒只比統計量） |
| A11-05 | 2464bac9 | 08 Cinematic 08 | 電影色調：Contrast -75、Whites -61 |
| A11-06 | 11e359dc | J11 | 高反差：亮部 -100、陰影 +60、白 -88、黑 +88、清晰度 +42 |
| A11-07 | 2f20566e | 12 Black and White 12 | 黑白（Embedded profile） |
| A11-08 | 999ff87d | 時尚黑白 1 | 黑白（Default Monochrome profile）、白 -100、去朦朧 +21 |
| A11-09 | 0ec7b00a | 皇家黑鑽3 | ProcessVersion 15.4（新版處理流程） |
| A11-10 | 0b10ebcc | New York 04 | ProcessVersion 6.7（PV2010 舊版處理流程） |

篩選條件：沒有 Look／創意描述檔、沒有遮罩、沒有鏡頭描述檔。A11-02／03／05／10 的白平衡是「絕對色溫」（從 RAW 存的），順便觀察 Lightroom 套到 JPEG 上時怎麼處理。這些 preset 保留原本的銳利化與降噪，這是 preset 本來的樣子。

## 檔名規則

匯出後：`<渲染日期>-<代碼>_<滑桿>_<取值>__<標準圖>.tif`，例如 `2026-10-08-A02-03_Highlights2012_m050__real-portrait.tif`（照 repo 的產出規則，日期放檔名最前面）。產生器做出來的輸入檔、`expected_*.txt` 與 `manifest.csv` 不含日期；`check` 會忽略日期前綴。

- 代碼 `A02-03`：A＝必做、B＝選做；02＝群組；03＝群組內第幾個（照取值由小到大）。
- 取值：`m`＝負、`p`＝正；滑桿是三位數（`m050`＝-50），曝光是 EV（`p1p50`＝+1.50 EV）。
- 兩個底線 `__` 後面是標準圖代號。方案 B 的檔名是 `<代碼>__<標準圖>`，分析時只看代碼和圖名，兩種都能對應回 `manifest.csv`。

## preset 格式

- 每個 preset 只改要掃的那個滑桿，**其他設定全部寫成 0／預設值**（包括銳利化 0、降噪 0、曲線線性、鏡頭校正關、`CameraProfile="Embedded"`、`ColorGradeBlending=50`），所以不管先前套了什麼，套下去的狀態都一樣。
- 欄位排列照使用者現有的 xmp：`crs:Version="15.2"`、`crs:ProcessVersion="11.0"`、`PresetType="Normal"`、`Supports*="True"`、`RequiresRGBTables="False"`；`crs:Group`＝「校正 - <滑桿名>」；`crs:Name`＝「<代碼> <滑桿> <取值>」；UUID 由代碼固定算出來（重跑不會變）。
- 驗收用的真實 preset 是複製原檔，只換 Name、Group、UUID（換 UUID 是為了不跟你原本匯入的同一個 preset 衝突）；原本的 1466 個檔案沒動。
- 寫進圖檔裡的版本（方案 A）是同一組設定，拿掉 preset 才有的欄位，加上 `crs:HasSettings="True"`、`crs:AlreadyApplied="False"`。

## 這個資料夾裡有什麼

| 路徑 | 內容 |
|---|---|
| `make_calibration_set.py` | 產生器（`plan`／`build`／`check`／`stamp`） |
| `charts/` | 3 張合成標準圖＋`layout.json`（每個色塊的位置與原始值） |
| `presets/must/`、`presets/optional/` | 201 個 preset xmp；`presets_must.zip`、`presets_optional.zip` 可以直接匯入 Lightroom |
| `manifest.csv` | 每個設定的代碼、群組、改了什麼、套哪些圖、說明（UTF-8 BOM，Excel 打得開） |
| `expected_must.txt`、`expected_optional.txt` | 應該匯出的檔名清單（`check` 用） |
| `sources.json` | 真實照片的來源、作者、授權、SHA1 |

## 已知限制

- 方案 A 靠「Lightroom 匯入時讀內嵌 XMP」，我沒辦法在這台機器上先實測 Lightroom，所以第 3 步的抽查一定要做；讀不到時有「從檔案讀取中繼資料」和方案 B 兩層備案。
- 只做 JPEG／TIFF（非 RAW）。RAW 的處理流程不一樣（相機描述檔、絕對白平衡），等 JPEG 版定案後另外處理。
- 白平衡只掃增量（JPEG 本來就只有增量）；絕對色溫只靠 4 個驗收 preset 觀察。
- 顆粒是隨機的，只能比統計量（顆粒大小、振幅），沒辦法逐像素比。
- ColorChecker 色值是公開的 sRGB 近似值，不是實際量測的色卡；校正時當「已知輸入」用，不當色彩標準。
