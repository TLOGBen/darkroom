---
name: darkroom-edit
description: 用 darkroom 的 CLI／MCP 幫使用者修照片：找 preset、預覽（MCP 會回圖片，可以先看再決定）、套用並保存編輯、複製／貼上編輯到其他照片、匯出 JPEG／PNG／TIFF／WebP（品質、檔案大小上限、縮小尺寸、中繼資料、移除 GPS、輸出銳利化、匯出預設、目的資料夾；不給參數就用存好的編輯）、整個資料夾批次處理與部分失敗（結束碼 6）。使用者說「幫我修這張」「套這個 preset」「強度 80%」「這批照片都套」「匯出」「複製修改到其他張」「預覽看看」「edit photo with darkroom」「apply preset」「export photos」「batch export」「paste edit」「匯出給網頁」「縮小到 2048」「限 800 KB」「拿掉 GPS」「存成匯出預設」時用。
---

# darkroom-edit

## 什麼時候用

使用者要你用 darkroom 處理照片：挑 preset 套上、看效果、保存這張的編輯、把編輯複製到別張、匯出成檔案、整批處理。
preset 庫的整理（群組、最愛、匯入、存成 preset）→ `darkroom-presets`；App 開關 → `darkroom-start`。

## 安全規則

- 照片原檔只讀。darkroom 不會改它，你也不准搬、改名、刪、覆蓋。匯出只產生新檔，同名自動加序號。
- `edit set`／`edit paste`／`edit clear` 會**取代**照片原本的編輯：影響超過一張、或那張本來就有編輯（`edit get` 的 `edit` 不是 `null`）時先問。
- 匯出目的資料夾：使用者沒說就用預設 `<照片資料夾>/darkroom 匯出`；要寫到別處用 `--dest-dir`，而且那個資料夾要先存在（不存在會 `找不到匯出資料夾：…`，結束碼 2）。不要自己 `mkdir` 到使用者的照片資料夾以外、沒告知的位置。
- 不要用 AI 自動挑 preset 替使用者決定風格；給候選、預覽、讓他選。
- 任何失敗把 `error` 原句給使用者，不猜。

## 指令（`python` ＝ repo 的 Python，一律加 `-s` 與 `--json`，路徑用絕對路徑）

```powershell
# 找 preset：--query 比對名稱或群組子字串，不分大小寫；查不到就換關鍵字（底片／膠捲／film／kodak…）
python -s -m darkroom_app.cli presets list --query film --limit 20 --json
python -s -m darkroom_app.cli presets groups --json
python -s -m darkroom_app.cli presets show <id> --json        # 滑桿值、略過的設定（level major 要提醒）

# 滑桿鍵名（--override 只收這些），值是「差值」，加在 preset×強度之後
python -s -m darkroom_app.cli sliders --json

# 開照片、列同資料夾
python -s -m darkroom_app.cli open <photo> --json
python -s -m darkroom_app.cli folder <photo> --json

# 預覽：不加 --json 是 JPEG 位元組，要導向檔案；加 --json 回 jpeg_base64
python -s -m darkroom_app.cli preview <photo> --preset <id> --strength 80 > preview.jpg
python -s -m darkroom_app.cli preview <photo> --preset <id> --strength 80 --override Exposure2012=0.3 --max-pixels 200000 --json

# 套用並保存（照片庫，以內容 SHA-256 對應；什麼都不給＝移除）
python -s -m darkroom_app.cli edit set <photo> --preset <id> --strength 80 --override Exposure2012=0.2 --json
python -s -m darkroom_app.cli edit get <photo> --json
python -s -m darkroom_app.cli edit clear <photo> --json

# 複製／貼上：把 <photo-a> 的顏色貼到 1～500 張（各張自己的裁切／旋轉保留）
python -s -m darkroom_app.cli edit paste --from <photo-a> <photo-b> <photo-c> --json
# 連裁切／旋轉一起貼（會換掉它們的裁切，先確認）
python -s -m darkroom_app.cli edit paste --from <photo-a> <photo-b> --with-geometry --json
# 裁切、拉直、旋轉、鏡像（存在這張的編輯裡；沒給幾何旗標的 edit set 會保留原本的裁切）
python -s -m darkroom_app.cli edit set <photo> --preset <id> --rotate 90 --angle 2.5 --aspect 4:5 --json
python -s -m darkroom_app.cli edit set <photo> --aspect free --crop 0.1,0.05,0.9,0.95 --json
python -s -m darkroom_app.cli edit set <photo> --preset <id> --no-geometry --json      # 拿掉裁切
python -s -m darkroom_app.cli preview <photo> --rotate 90 --angle 2.5 --frame > frame.jpg   # 整個畫面（忽略框）

# 匯出：不給 --preset／--strength／--override 就每張用存好的編輯（沒有編輯＝原圖）；給了就每張同一組參數；永不覆蓋
python -s -m darkroom_app.cli export <photo-a> <photo-b> --dest-dir <dest> --json
python -s -m darkroom_app.cli export <photo-a> <photo-b> --preset <id> --strength 80 --quality 92 --dest-dir <dest> --json
python -s -m darkroom_app.cli export <photo-a> --no-edit --dest-dir <dest> --json                 # 原圖，不用存好的編輯
# 格式：jpeg（8-bit，品質預設 92）｜png（預設 8-bit，--bit-depth 16）｜tiff（預設 16-bit，--bit-depth 8）｜webp（8-bit）
python -s -m darkroom_app.cli export <photo-a> --format tiff --dest-dir <dest> --json
python -s -m darkroom_app.cli export <photo-a> --format png --bit-depth 16 --metadata copyright --dest-dir <dest> --json
# 給網頁：只縮不放（long_edge|short_edge|width|height=像素、megapixels=N、percent=N）、JPEG 限檔案大小（KB＝1024 位元組）、輸出銳利化
python -s -m darkroom_app.cli export <photo-a> --resize long_edge=2048 --max-kb 800 --sharpen screen=standard --remove-gps --dest-dir <dest> --json
# 匯出預設：具名的匯出設定（不含資料夾），同名會取代並回 previous；--export-preset 套用，旗標明確給的優先
python -s -m darkroom_app.cli export-presets save --name 網頁 --resize long_edge=2048 --max-kb 800 --sharpen screen=standard --json
python -s -m darkroom_app.cli export <photo-a> --export-preset 網頁 --dest-dir <dest> --json
python -s -m darkroom_app.cli export-presets list --json
python -s -m darkroom_app.cli export-presets delete 網頁 --json

# 把這張的編輯存成自存 preset（細節在 darkroom-presets）
python -s -m darkroom_app.cli edit save-preset <photo> --name "人像暖調 80" --json
```

## MCP（已註冊時優先用，因為預覽直接回圖）

`darkroom_open_photo{path}` → `image_id` → `darkroom_preview{image_id, preset_id, strength, overrides, max_pixels, geometry, frame}` 回 `image/jpeg` 內容，**你可以直接看圖**，不滿意就改參數再預覽；確定了再 `darkroom_edit_set{path, preset_id, strength, overrides}` 或 `darkroom_export{items:[{path|image_id, preset_id, strength, overrides}], format, quality, dest_dir, bit_depth, max_kb, resize:{mode,value}, metadata, remove_gps, sharpen:{target,amount}, export_preset}`（只有 `items` 必填；item 只給 `path` ＝用存好的編輯）。`darkroom_export` 每張可以不同參數；匯出預設用 `darkroom_export_presets_list`／`darkroom_export_preset_save{name, settings}`／`darkroom_export_preset_delete{name}`；`darkroom_edit_paste{targets, source|edit, with_geometry}`（預設只貼顏色）；幾何（`geometry: {rotate, flip, angle, aspect, crop}`）沒給＝用／保留存好的，`null`＝拿掉；`darkroom_edit_get{path}`。工具總表見 `AGENTS.md`。

## 關鍵事實

- **強度** 0～200，100 ＝ preset 原樣；**微調**是差值不是絕對值；兩者都會夾進滑桿範圍。
- `export` 沒給 `--preset`／`--strength`／`--override`／`--no-edit` 時，**每張用照片庫裡存好的編輯**（存編輯當時的 preset 快照，preset 檔後來改過也一樣），沒有編輯就輸出原圖。每筆成功結果的 `used.params_from` 是 `edit`／`original`／`request`，回報時講清楚哪幾張是原圖；`used.quality` 是實際品質（有 `--max-kb` 時可能比 92 低），`used.width`／`height` 是輸出尺寸。照片庫讀不到時那一筆失敗、原因原樣給，不會默默輸出原圖。
- `--max-kb` 只對 JPEG；品質 1 都塞不下會那一筆失敗（`無法壓到 … KB 以內：品質 1 也有 … KB`）。`--resize` 絕不放大。WebP 最大 16383×16383，更大的要先 `--resize`。
- `--metadata all`（預設，含 GPS）／`copyright`（只留版權）／`none`；分享到網路建議加 `--remove-gps`，先問使用者。顏色描述檔（sRGB）一律嵌入。
- 某格式被偵測關掉（例如這台 OpenCV 不能寫 WebP）會 unavailable（結束碼 5）並說原因；`capabilities` 看全部。
- `edit set` 在當下拍 preset 參數的快照；之後 preset 檔改了，這份編輯不變。
- `presets show` 的 `skipped`／`level`：`major` ＝ 畫面會明顯不同（相機描述檔、Adobe Look、絕對白平衡等），要先講；`minor` 幾乎沒差。
- HEIC 要有 `pillow-heif`；RAW 還不支援。

## 批次與部分失敗（結束碼 6）

`export`、`edit paste`（與 `presets import`）是批次：stdout 的 `results` 每筆對應一個輸入，順序一樣，`{ok:true, …}` 或 `{ok:false, source|target, error}`；只要有一筆失敗結束碼就是 6，**成功的那些已經完成**（檔案已寫、編輯已貼）。處理方式：

1. 不要整批重跑（會再產生一份加序號的新檔）。
2. 逐筆把 `ok:false` 的 `error` 原句列給使用者（常見：`photo not found: …`、格式不支援、讀檔失敗）。
3. 問要不要只重試失敗那幾張（修正路徑後只傳那幾張）。

一次很多張：先用 `folder <photo>` 或 `thumbnails <folder>` 取得清單，確認數量與目的地後再匯出；24MP 一張約 0.4 秒，幾百張也請告訴使用者大概要等多久。

## 要先問使用者的時機

- 不知道要套哪個 preset、哪個強度：列候選＋預覽一張，讓他挑；不要替他決定風格。
- 匯出格式／品質／目的資料夾沒說：JPEG 92、預設資料夾可以直接用，但要在回報裡講清楚寫到哪；TIFF／PNG 16-bit、縮小、拿掉中繼資料或其他位置要先問。
- 同名存匯出預設會取代舊的、刪除匯出預設：先問（回傳的 `previous`／被刪內容可以拿來復原）。
- 會取代既有編輯、或貼到超過一張。
- 預覽結果有 `major` 級略過設定。
