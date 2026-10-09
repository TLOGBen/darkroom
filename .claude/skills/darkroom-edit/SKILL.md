---
name: darkroom-edit
description: 用 darkroom 的 CLI／MCP 幫使用者修照片：找 preset、預覽（MCP 會回圖片，可以先看再決定）、套用並保存編輯、複製／貼上編輯到其他照片、匯出 JPEG／TIFF（品質、目的資料夾）、整個資料夾批次處理與部分失敗（結束碼 6）。使用者說「幫我修這張」「套這個 preset」「強度 80%」「這批照片都套」「匯出」「複製修改到其他張」「預覽看看」「edit photo with darkroom」「apply preset」「export photos」「batch export」「paste edit」時用。
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

# 複製／貼上：把 <photo-a> 的編輯原樣貼到 1～500 張（取代它們的編輯）
python -s -m darkroom_app.cli edit paste --from <photo-a> <photo-b> <photo-c> --json

# 匯出：每張同一組參數；JPEG 品質 1..100 預設 92；TIFF 16-bit；永不覆蓋
python -s -m darkroom_app.cli export <photo-a> <photo-b> --preset <id> --strength 80 --quality 92 --dest-dir <dest> --json
python -s -m darkroom_app.cli export <photo-a> --preset <id> --format tiff --dest-dir <dest> --json

# 把這張的編輯存成自存 preset（細節在 darkroom-presets）
python -s -m darkroom_app.cli edit save-preset <photo> --name "人像暖調 80" --json
```

## MCP（已註冊時優先用，因為預覽直接回圖）

`darkroom_open_photo{path}` → `image_id` → `darkroom_preview{image_id, preset_id, strength, overrides, max_pixels}` 回 `image/jpeg` 內容，**你可以直接看圖**，不滿意就改參數再預覽；確定了再 `darkroom_edit_set{path, preset_id, strength, overrides}` 或 `darkroom_export{items:[{path|image_id, preset_id, strength, overrides}], format, quality, dest_dir}`。`darkroom_export` 每張可以不同參數；`darkroom_edit_paste{targets, source|edit}`；`darkroom_edit_get{path}`。工具總表見 `AGENTS.md`。

## 關鍵事實

- **強度** 0～200，100 ＝ preset 原樣；**微調**是差值不是絕對值；兩者都會夾進滑桿範圍。
- `export` **不會**自動讀照片庫裡保存的編輯。要匯出「已保存的編輯」：`edit get` → 取 `edit.preset.id`、`edit.strength`、`edit.overrides` → 傳給 `export`。`preset_status` 是 `changed`／`missing` 時先告訴使用者（匯出用的是現在的 preset 檔，不是當時的快照）。
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
- 匯出格式／品質／目的資料夾沒說：JPEG 92、預設資料夾可以直接用，但要在回報裡講清楚寫到哪；TIFF 或其他位置要先問。
- 會取代既有編輯、或貼到超過一張。
- 預覽結果有 `major` 級略過設定。
