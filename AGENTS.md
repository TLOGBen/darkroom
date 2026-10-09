# darkroom — 給 AI 代理的使用手冊

這份給任何打開這個 repo 的 AI 代理（Claude Code、Codex、Cursor……）看：你要替使用者設定、啟動、操作 darkroom。人看的文字用繁體中文（台灣）；指令、路徑、識別字維持原文。
本 repo 作者自己的開發規則在 `CLAUDE.md` 最後一節，跟你替使用者操作 darkroom 無關。

## darkroom 是什麼

在使用者自己的電腦上，用他買來的 Lightroom `.xmp` preset 修照片：挑 preset → 調強度（0～200%）→ 微調滑桿 → 即時預覽 → 匯出成新檔。GPU（CUDA）本機渲染，不上傳雲端。
三個入口共用同一套邏輯，同一件事得到同一個結果、同一句錯誤：

| 入口 | 給誰 | 怎麼叫 |
|---|---|---|
| Web App | 使用者 | `python -s -m darkroom_app`，瀏覽器開 `http://127.0.0.1:8765/` |
| CLI | 你（代理） | `python -s -m darkroom_app.cli <指令> --json` |
| MCP | 你（代理，已註冊時） | stdio server `python -s -m darkroom_app.mcp_server`，27 個 `darkroom_*` 工具 |

本文裡的 `python` 一律指 **這個 repo 用的 Python**：一般使用者是 `.\.venv\Scripts\python.exe`（見 `docs/agent-install.md`）；作者環境是 `config.local.json` 的 `localllms_root` 底下的專用 Python。一律加 `-s`，在 repo 根目錄執行。用詞定義見 `CONTEXT.md`。

## 安全規則（違反＝做錯，沒有例外）

1. **照片原檔只讀。** darkroom 永遠不改寫、不覆蓋、不刪除照片；你也不准用其他方式（複製、搬移、改名、「整理」資料夾）動使用者的照片。匯出只產生新檔，同名自動加序號。
2. **買來的 preset 原檔只讀。** 改名、搬群組、最愛都只寫 preset 庫的索引 `library.json`；匯入是複製一份進 `import/`，自存 preset 寫進 `user/`。不要自己動 `preset_dir` 裡任何檔案。
3. **只綁 `127.0.0.1`。** 不要改成 `0.0.0.0`、不要加反向代理、不要開防火牆、不要用 80 埠。
4. **不替使用者搬動或整理照片。** 使用者說「幫我整理照片」，你能做的只有：用 darkroom 的照片庫（編輯、最愛、群組）與匯出到他指定的資料夾；檔案層級的搬動要他自己來。
5. **先問再做**：第一次設定時的 preset 資料夾位置；下載大型套件（PyTorch 約 2～3 GB）；匯出目的地（沒說就用預設的 `<照片資料夾>/darkroom 匯出`）；會覆蓋既有編輯的操作（`edit set`／`edit paste`／`edit clear`）影響到不只一張時；任何會重命名／搬移群組、影響很多 preset 的整理。
6. **誠實回報。** 指令失敗就把那一行原樣給使用者看，不要猜原因；批次有部分失敗（結束碼 6）要逐筆列出哪些失敗、為什麼。

## 第一次設定

全部步驟、每步的檢查、疑難排解都在 **`docs/agent-install.md`**，照它從頭做到尾，不要自己發明流程。開始前先問使用者這幾個問題（答案會決定後面的步驟）：

1. 你的 Lightroom `.xmp` preset 放在哪個資料夾？（可以有子資料夾；我不會動它們）
2. 裝 PyTorch（CUDA 版）要下載約 2～3 GB，可以嗎？
3. 要不要把 darkroom 註冊成 MCP server，讓我之後能直接操作？（可選）
4. 要不要跑一次完整測試（幾分鐘，只寫暫存資料夾）？（建議）
5. （可選）照片庫的編輯與縮圖快取想放預設位置 `%LOCALAPPDATA%\darkroom`，還是另外指定 `data_dir`？

設定結果落在 repo 根目錄的 `config.local.json`（不進 git）：`preset_dir`（必要）、`preset_library_dir`（可選，預設 `preset_dir` 的上一層）、`data_dir`（可選）。這兩個可選資料夾都不可以在照片資料夾或 `preset_dir` 裡面。
語意索引（可選，沒設就整個功能安靜關閉、搜尋照常）：`anthropic_api_key_ref`（**只放 1Password 參照** `op://<vault>/<item>/credential`，執行 `presets semantic build` 時才 `op read`；**絕不把金鑰本身寫進這個檔**；替代方案是環境變數 `DARKROOM_ANTHROPIC_API_KEY`）、`semantic_index_budget_usd`（一次 build 的費用上限，預設 5）、`calibration_sources_dir`（4 張公開標準圖所在資料夾，預設 `<localllms_root>/scratch/lr-calibration/sources`；只會讀固定的 4 個檔名，放別的照片進去也不會被送出）。

## 啟動、停止、健康檢查

```powershell
# 啟動（前景執行；關掉視窗或 Ctrl+C 就停止）。就緒時印出「darkroom 已啟動：http://127.0.0.1:8765/」
python -s -m darkroom_app
python -s -m darkroom_app --port 8799                       # 換埠（不要用 80）
python -s -m darkroom_app --preset-dir D:/Presets/xmp --data-dir D:/darkroom-data   # 這一次執行覆蓋設定檔

# 健康檢查：回 {"ok": true} 就是活著
Invoke-WebRequest http://127.0.0.1:8765/api/health -UseBasicParsing

# 作者環境另有 tools/start.ps1（從 config.local.json 找專用 Python、等就緒再開瀏覽器）
pwsh -File tools/start.ps1 -Port 8765 -NoBrowser
```

- 一定用 `http://127.0.0.1:<埠>/` 開；用別的主機名會被拒（HTTP 421／403）。
- 停止：結束那個 Python 行程（Ctrl+C、關視窗，或 `Stop-Process`）。沒有「停止指令」。
- 使用者沒說要一直開著，用完就關掉。
- 第一次啟動會暖機 GPU，幾秒到幾十秒；健康檢查等它回 200 再開瀏覽器。
- App 跑著的時候 CLI／MCP 照樣可以同時用：preset 庫索引有跨程序鎖，不會互相蓋掉。

## CLI 用法總表

共通：`python -s -m darkroom_app.cli [--preset-dir DIR] [--data-dir DIR] <指令> ... --json`。
`--json` 讓 stdout **恰好一行** `{"ok":true,"result":…}` 或 `{"ok":false,"error":{"kind":…,"message":…}}`，你一律加。
`<photo>` 一律用絕對路徑；`<id>` 是 `presets list` 回的 preset id。所有子指令與參數跟 `python -s -m darkroom_app.cli <指令> --help` 一致（本表所有範例都實跑過）。

| 指令 | 用途 | 寫檔？ |
|---|---|---|
| `presets list [--query Q] [--offset N] [--limit N] [--favorites]` | 列 preset（id、群組、名稱、是否完整支援、略過的設定、最愛、語意標籤 `tags`）；`--query` 比對名稱、群組**與語意標籤／描述**（中英文都可以，不分大小寫的子字串）；沒 `--limit` 會全列 | 否 |
| `presets show <id>` | 一個 preset 的細節：100% 時每個滑桿的值、曲線、無法套用的設定（`level`：`minor`／`major`，`note` 是給人看的說明） | 否 |
| `presets flags` | `{id: "major"|"minor"}`：哪些 preset 有略過的設定 | 否 |
| `presets groups` | 群組樹（第一個 ` - ` 分上下層）與每組數量 | 否 |
| `presets rename <id> <name>` | 改顯示名稱（1～100 字） | 索引 |
| `presets move <id> <group>` | 搬到群組（`'A - B'` 是子群組；不存在就建） | 索引 |
| `presets favorite <id> on|off` | 標／取消最愛 | 索引 |
| `presets import <path>... [--group G]` | 把 `.xmp`（檔案，或資料夾第一層）**複製**進庫的 `import/`；內容相同的不重複匯入；來源不動 | 庫 `import/`＋索引 |
| `presets save --name N [--group G] [--preset ID] [--strength S] [--override K=V]...` | 把「preset×強度＋微調」存成新的自存 preset（`user/` 新檔，永不覆蓋；群組預設 `自存 preset`） | 庫 `user/`＋索引 |
| `presets rebuild` | 從 preset 資料夾重掃索引（還在的檔保留名稱／群組／最愛）；回 `{added, removed, kept}` | 索引 |
| `presets semantic status` | 語意索引狀態：`available`（能不能建）、`reason`（不能時的固定原因）、`indexed`／`total`／`pending`、還在跑的 batch、預算、上次用量。不需要金鑰、不連網 | 否 |
| `presets semantic build [--limit N] [--dry-run] [--wait-seconds S]` | **會花錢**：把還沒索引的 preset（只送 4 張公開標準圖的渲染結果，絕不送使用者照片）交給 Claude（`claude-haiku-5-5`，Batches 5 折）寫風格標籤，存進 `<庫根>/semantic.json`（以 preset 內容雜湊為 key，改名搬移不重跑）。送出前先印預估費用，超過 `semantic_index_budget_usd`（預設 5 美元）就拒絕；`--dry-run` 只估不送；預設等 3600 秒，`--wait-seconds 0` 送出就回，之後再跑一次 build 收回結果。**先跟使用者確認再跑** | `semantic.json` |
| `groups create <group>` | 建空群組（已存在 → conflict） | 索引 |
| `groups rename <group> <new>` | 群組連同子群組改名（`new` 是完整新路徑；已存在 → conflict，不合併） | 索引 |
| `sliders` | 所有滑桿（Lightroom crs 鍵名、範圍、預設、步進、中文標籤）；`--override` 只接受這些鍵 | 否 |
| `open <photo>` | 開照片（JPEG／PNG／TIFF／HEIC），回 `image_id`、尺寸、預覽尺寸 | 否 |
| `folder <photo>` | 同資料夾裡支援的照片（依檔名排序）與這張的位置 | 否 |
| `preview <photo> [--preset ID] [--strength S] [--override K=V]... [--max-pixels N]` | 渲染縮小的 JPEG 預覽。**不加 `--json` 時 stdout 是 JPEG 位元組**（要 `> out.jpg`）；加 `--json` 回 `jpeg_base64` | 否（導向檔案時是你在寫） |
| `export <photo>... [--preset ID] [--strength S] [--override K=V]... [--format jpeg|tiff] [--quality N] [--dest-dir D]` | 全解析度匯出成**新檔**（JPEG 品質預設 92；TIFF 16-bit），嵌 sRGB、保留 EXIF；預設寫到 `<照片資料夾>/darkroom 匯出`，同名加序號；每張同一組參數 | 新檔 |
| `edit get <photo>` | 照片庫裡這張的編輯（以內容指紋對應）：`edit` 為 `null` 或 `{preset(含快照), strength, overrides}`，`preset_status`：`current`／`changed`／`missing`；`previous`：有沒有一份被清掉、可用 `edit restore` 取回的編輯 | 否 |
| `edit set <photo> [--preset ID] [--strength S] [--override K=V]...` | **取代**這張的編輯（當下把 preset 參數拍快照）；什麼都不給＝移除 | `data_dir/edits/` |
| `edit clear <photo>` | 移除這張的編輯 | `data_dir/edits/` |
| `edit paste --from <photo> <target>...` | 把一張的編輯原樣貼到 1～500 張（**取代**它們原本的編輯） | `data_dir/edits/` |
| `edit save-preset <photo> --name N [--group G]` | 把這張的編輯存成自存 preset（`user/` 新檔） | 庫 `user/`＋索引 |
| `edit restore <photo>` | 取回上一份：`edit clear`（或 `edit set` 什麼都不給）時被清掉的那份編輯會留著，這個指令把它放回去（留著的那份不刪，可重複）；沒有 → not_found；這張現在已經有別的編輯 → conflict（不會蓋掉；要取回先 `edit clear`） | `data_dir/edits/` |
| `thumbnails <folder> [--offset N] [--limit N]` | 縮圖格清單（背景產縮圖；`fingerprint`／`edited` 產好前是 `null`） | `data_dir/thumbs/`、`index/` |
| `thumbnail <photo>` | 一張的縮圖（長邊 256）；不加 `--json` 是 JPEG 位元組 | `data_dir/thumbs/` |

「索引」＝ preset 庫根目錄的 `library.json`（根目錄＝`preset_library_dir`，沒設就是 `preset_dir` 的上一層）。所有寫檔都不碰照片原檔、不碰 `preset_dir` 裡的 `.xmp`。
注意：`export` **不會**自動用照片庫裡保存的編輯；要匯出「已保存的編輯」，先 `edit get` 拿到 preset id／strength／overrides 再明確傳給 `export`（見食譜 3）。

## MCP 工具總表

註冊方式見 `docs/agent-install.md` 第 7 步。工具順序、名稱、參數都來自 `darkroom_app/operations.py`（共 27 個）；參數名跟 CLI 對應（`preset_id`、`strength`、`overrides`、`max_pixels`、`dest_dir`…）。回傳 `structuredContent` 是結構化結果，錯誤時 `isError: true` 且文字就是那句錯誤訊息。

| 工具 | 用途 | 寫檔？ |
|---|---|---|
| `darkroom_presets_list` | 列 preset（`query`、`offset`、`limit` 預設 50、`favorites`） | 否 |
| `darkroom_preset_show` | 一個 preset 的細節（`preset_id`） | 否 |
| `darkroom_preset_flags` | 有略過設定的 preset：`{id: major|minor}` | 否 |
| `darkroom_sliders` | 滑桿表 | 否 |
| `darkroom_open_photo` | 開照片（`path`）→ `image_id` | 否 |
| `darkroom_photo_folder` | 同資料夾的照片（`image_id`） | 否 |
| `darkroom_preview` | 預覽（`image_id`、`preset_id`、`strength`、`overrides`、`max_pixels` 預設 786432）；**回傳 `image/jpeg` 內容，你可以直接看圖再決定** | 否 |
| `darkroom_export` | 匯出（`items: [{path 或 image_id, preset_id, strength, overrides}]`、`format`、`quality`、`dest_dir`）；每張可以不同參數；`failed` 是失敗數 | 新檔 |
| `darkroom_preset_groups` | 群組樹 | 否 |
| `darkroom_preset_rename` | 改顯示名稱（`preset_id`、`name`） | 索引 |
| `darkroom_preset_move` | 搬群組（`preset_id`、`group`） | 索引 |
| `darkroom_preset_favorite` | 最愛（`preset_id`、`favorite: true|false`） | 索引 |
| `darkroom_group_create` | 建群組（`group`） | 索引 |
| `darkroom_group_rename` | 群組改名（`group`、`new_name`） | 索引 |
| `darkroom_presets_import` | 匯入（`paths` 或 `files: [{name, data_base64}]`、`group`）；`failed` 是失敗數 | 庫 `import/`＋索引 |
| `darkroom_preset_save` | 存自存 preset（`name`、`group`、`preset_id`、`strength`、`overrides`） | 庫 `user/`＋索引 |
| `darkroom_presets_rebuild` | 重建索引 | 索引 |
| `darkroom_edit_get` | 讀一張的編輯（`path`） | 否 |
| `darkroom_edit_set` | 取代一張的編輯（`path`、`preset_id`、`strength`、`overrides`） | `data_dir/edits/` |
| `darkroom_edit_clear` | 移除一張的編輯（`path`） | `data_dir/edits/` |
| `darkroom_edit_paste` | 貼編輯（`targets`，來源用 `source` 路徑或 `edit` 物件）；`failed` 是失敗數 | `data_dir/edits/` |
| `darkroom_folder_thumbnails` | 縮圖格清單（`folder`、`offset`、`limit`） | `data_dir/thumbs/`、`index/` |
| `darkroom_thumbnail` | 一張縮圖（`path`）；回傳 `image/jpeg` | `data_dir/thumbs/` |
| `darkroom_edit_save_preset` | 把一張的編輯存成自存 preset（`path`、`name`、`group`） | 庫 `user/`＋索引 |
| `darkroom_edit_restore` | 取回一張最近一次被清掉的編輯（`path`）；`darkroom_edit_get` 的 `previous` 為 true 時才有東西可取回 | `data_dir/edits/` |
| `darkroom_semantic_build` | 建立語意索引（`limit`、`dry_run`、`wait_seconds` 預設 0＝送出就回）；**會花錢、會連 Anthropic**（`openWorldHint: true`），先確認再呼叫；先用 `dry_run: true` 看預估費用 | `semantic.json` |
| `darkroom_semantic_status` | 語意索引狀態（能不能建、原因、進度、預算、上次用量） | 否 |

每個工具都帶 MCP annotations：唯讀的 `readOnlyHint: true`；`darkroom_edit_set`／`clear`／`paste`／`restore` 標 `destructiveHint: true`（會取代舊編輯）。傳了 schema 以外的參數會直接被拒（`Unknown argument for …`）。

## 常見任務食譜

每個食譜的指令都實跑過。`<photo>`、`<folder>`、`<dest>` 請換成絕對路徑；`<id>` 換成 preset id。

### 1. 「把這個資料夾的照片都套某個 preset、強度 80%，匯出」

```powershell
# a. 找 preset（名稱或群組含關鍵字）
python -s -m darkroom_app.cli presets list --query film --limit 20 --json
# b. 看它有沒有無法套用的設定（level 為 major 要先跟使用者說）
python -s -m darkroom_app.cli presets show <id> --json
# c. 列出資料夾裡支援的照片（任一張的路徑都行）
python -s -m darkroom_app.cli folder <folder>/a.jpg --json
# d. 先預覽一張給使用者看（可選）
python -s -m darkroom_app.cli preview <folder>/a.jpg --preset <id> --strength 80 > preview.jpg
# e. 匯出（目的地要先存在；沒給 --dest-dir 就寫到 <folder>/darkroom 匯出）
python -s -m darkroom_app.cli export <folder>/a.jpg <folder>/b.jpg <folder>/c.jpg --preset <id> --strength 80 --quality 92 --dest-dir <dest> --json
```

`export` 的結果是 `results` 陣列，每張一筆 `{ok, source, output}` 或 `{ok:false, source, error}`，順序跟你給的一樣。結束碼 6 ＝ 有些成功有些失敗，成功的檔已經寫好；把失敗那幾筆的 `error` 原句告訴使用者。
要存微調：加 `--override Exposure2012=0.3 --override Contrast2012=10`（鍵名從 `sliders` 查，值是**差值**，加在 preset×強度之後）。要 TIFF：`--format tiff`（`--quality` 只對 JPEG 有效）。

### 2. 「找跟『底片』有關的 preset」

`--query` 比對名稱、群組與**語意標籤**（`presets semantic build` 建好後，每個 preset 有 Claude 看圖寫的中英文風格標籤，例如 底片、電影感、暖調、film、matte）的子字串，不做同義詞；沒建語意索引時只比對名稱與群組，一個詞查不到就換幾個：中文（底片、膠捲、膠卷、菲林）、英文（film、kodak、fuji、portra、35mm）、品牌名。先 `presets semantic status` 看索引建了多少；先看群組樹通常也很快：

```powershell
python -s -m darkroom_app.cli presets groups --json
python -s -m darkroom_app.cli presets list --query 膠捲 --limit 50 --json
python -s -m darkroom_app.cli presets list --query film --limit 50 --json
```

回給使用者時列 `id`、`group`、`name`，`skipped` 非空的註明「有部分設定套不上」。

### 3. 「把這張的修改複製到其他張」／「匯出已保存的編輯」

```powershell
# 先確認來源真的有編輯（edit 不是 null）
python -s -m darkroom_app.cli edit get <photo-a> --json
# 貼到其他張（會取代它們原本的編輯；超過一張先跟使用者確認）
python -s -m darkroom_app.cli edit paste --from <photo-a> <photo-b> <photo-c> --json
```

結束碼 6 ＝ 部分目標失敗（例如檔案不存在），`results` 逐筆列。
要把已保存的編輯匯出成檔案：從 `edit get` 的 `edit.preset.id`、`edit.strength`、`edit.overrides` 取出來，交給 `export --preset … --strength … --override …`。若 `preset_status` 是 `changed`（preset 檔後來改過）或 `missing`，先告訴使用者：匯出用的是現在的 preset，不是當時的快照。

### 4. 「幫這張照片套 preset 並保存」（之後在 App 裡打開會看到）

```powershell
python -s -m darkroom_app.cli edit set <photo> --preset <id> --strength 80 --override Exposure2012=0.2 --json
python -s -m darkroom_app.cli edit get <photo> --json      # 確認
python -s -m darkroom_app.cli edit clear <photo> --json    # 反悔
```

編輯以照片**內容**的 SHA-256 對應，搬移改名不會掉；照片被別的程式改過內容就算另一張。

### 5. 「把這個效果存成 preset」

```powershell
# 從一張照片已保存的編輯存
python -s -m darkroom_app.cli edit save-preset <photo> --name "人像暖調 80" --json
# 或直接指定 preset×強度＋微調
python -s -m darkroom_app.cli presets save --name "我的暖調" --preset <id> --strength 120 --override Contrast2012=10 --json
```

回 `{id: "user:…", name, group: "自存 preset", file: "user/….xmp"}`。永不覆蓋，同名自動加 ` (2)`。之後 `presets list` 就列得到，id 以 `user:` 開頭。

### 6. 「整理最愛」／「整理 preset 群組」

```powershell
python -s -m darkroom_app.cli presets favorite <id> on --json
python -s -m darkroom_app.cli presets favorite <id> off --json
python -s -m darkroom_app.cli presets list --favorites --json
python -s -m darkroom_app.cli presets rename <id> "暖調底片" --json
python -s -m darkroom_app.cli groups create "底片 - 暖調" --json
python -s -m darkroom_app.cli presets move <id> "底片 - 暖調" --json
python -s -m darkroom_app.cli groups rename "底片" "膠卷" --json       # 子群組一起改；目標已存在會 conflict
python -s -m darkroom_app.cli presets import D:/new-presets --group "新買的" --json
python -s -m darkroom_app.cli presets rebuild --json                     # 索引壞了、或手動加減過 xmp 之後
```

這些只改索引（`library.json`）與庫的 `import/`／`user/`，買來的 `.xmp` 一個位元都不變。一次影響很多 preset 的改名／搬移先列清單給使用者確認。

### 7. 「看一下這張套起來長怎樣」（MCP）

`darkroom_open_photo` → `darkroom_preview`（回 JPEG，你直接看）→ 覺得不對就改 `strength`／`overrides` 再預覽 → 使用者滿意再 `darkroom_edit_set` 或 `darkroom_export`。預覽不寫任何檔。

## 結束碼與錯誤怎麼讀

| 結束碼 | 意思 | 你該做什麼 |
|---|---|---|
| 0 | 成功 | — |
| 1 | 未預期錯誤（stderr 一行 `未預期錯誤：<型別>：<訊息>`） | 原句回報，不要重試 |
| 2 | 參數不對／設定不對（`invalid`；也包含 argparse 用法錯誤、找不到設定檔或 preset 資料夾） | 修正參數；設定問題看 `docs/agent-install.md` 疑難排解 |
| 3 | 找不到（`not_found`：preset id、照片、群組） | 檢查 id／路徑 |
| 4 | 衝突（`conflict`：群組已存在、索引鎖等太久） | 換名稱，或稍後再試 |
| 5 | 暫時無法使用（`unavailable`：寫索引／寫檔被擋） | 稍後再試一次；還是失敗就回報 |
| 6 | 批次部分失敗（`export`、`presets import`、`edit paste`） | stdout 仍有完整 `results`；逐筆讀 `ok:false` 的 `error` |

- `--json` 時失敗是 `{"ok":false,"error":{"kind":"invalid|not_found|conflict|unavailable","message":"…"}}`，stderr 保持空。
- 不加 `--json` 時失敗是 stderr 一行；`preview`／`thumbnail` 的 stdout 是 JPEG 位元組，在終端機直接跑會被拒（結束碼 2，提示導向檔案或加 `--json`）。
- 常見訊息：`unknown preset <id>`、`photo not found: <path>`、`unknown slider key '<key>'`、`找不到匯出資料夾：<dir>`（`--dest-dir` 要先存在）、`JPEG 品質要在 1～100 之間：<n>`、`群組已存在：<group>`、`已在 preset 庫裡（<name>），未重複匯入`、`darkroom：preset folder not found: <dir>`（`--preset-dir` 或 `config.local.json` 的 `preset_dir` 錯）。
- MCP：工具錯誤是 `isError: true`＋同一句訊息；參數名打錯是 JSON-RPC `-32602 Unknown argument for <tool>: <key>`。

## 有哪些 skill 可以用

`.claude/skills/` 底下（Claude Code 會自動載入；其他工具直接把對應的 `SKILL.md` 當說明讀）：

| skill | 什麼時候用 |
|---|---|
| `darkroom-setup` | 安裝、第一次設定、改設定、疑難排解（以 `docs/agent-install.md` 為準） |
| `darkroom-start` | 啟動、停止、健康檢查、換埠、指定 `--preset-dir`／`--data-dir` |
| `darkroom-edit` | 用 CLI／MCP 幫使用者修圖：找 preset、預覽、套用並保存、複製貼上、匯出、批次 |
| `darkroom-presets` | preset 庫：搜尋、群組、最愛、改名、搬移、匯入、存成 preset、重建索引 |
| `usage-guard` | 作者自己的 Claude Code mod（顯示用量），跟 darkroom 功能無關，不要改 |
