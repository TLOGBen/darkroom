# 5 分鐘上手

前提：已經照 [安裝說明](install.md) 裝好（安裝檔或原始碼都行），手邊有一個放 Lightroom `.xmp` preset 的資料夾和幾張照片。

## 1. 第一次啟動

- **安裝檔**：開啟 darkroom。第一次會先看到下載說明，按「同意並開始下載」，等它裝完自動進編輯畫面。
- **原始碼**：在 repo 根目錄執行 `.\.venv\Scripts\python.exe -s -m darkroom_app`，瀏覽器開 <http://127.0.0.1:8765/>。

## 2. 指定 preset 資料夾

darkroom 只**讀**這個資料夾，不會改、不會搬裡面任何檔案（子資料夾會變成 preset 群組）。

目前的版本還沒設 preset 資料夾時後端起不來，所以第一次請先用指令設定（`settings` 不需要先有 preset 資料夾）：

```powershell
darkroom settings set preset_dir=D:/Presets/xmp                                   # 安裝檔版
.\.venv\Scripts\python.exe -s -m darkroom_app.cli settings set preset_dir=D:/Presets/xmp   # 原始碼版
```

再開一次 darkroom，左欄就會列出你的 preset 群組。之後要換資料夾，到頂列的「設定」頁改、按「套用」，立即生效。

## 3. 修一張

1. 在頂列的「照片路徑」貼上一張照片的完整路徑（JPEG／PNG／TIFF／HEIC），按「開啟」。同資料夾的其他照片用 ← → 切換，或按「縮圖格」挑。
2. 左欄點一個 preset（上面的搜尋框可以打名稱、群組或風格，例如「底片」）。
3. 下面的「強度」拉到你要的程度（0～200%，100% 就是 preset 原本的樣子）。
4. 右欄的滑桿在 preset 之上再微調；Ctrl+Z／Ctrl+Shift+Z 復原、重做；按住「按住看原圖」對照。
5. 要裁切就按「裁切」（R）：拖框、選比例、拉直，Enter 完成、Esc 取消。

不用按儲存：每張照片的修改會自動存進 darkroom 自己的照片庫（以照片內容對應，搬移、改名都不會掉），照片原檔完全不動。

## 4. 匯出

按「匯出」，選格式（JPEG／PNG／TIFF／WebP）、品質或檔案大小上限、尺寸、中繼資料。預設寫到照片所在資料夾底下的 `darkroom 匯出`；**永遠是新檔**，同名自動加序號。常用的組合可以存成「匯出預設」，下次一個名字套用。

要一次匯出很多張：開「縮圖格」，多選，按「匯出所選」，每張用它自己存好的修改。

---

## CLI：一行套 preset 並匯出

每個子指令加 `--json`，stdout 就是恰好一行 `{"ok":true,"result":…}` 或 `{"ok":false,"error":{…}}`。安裝檔版把 `python -s -m darkroom_app.cli` 換成 `darkroom`。

```powershell
# 找 preset（比對名稱、群組與語意標籤）
python -s -m darkroom_app.cli presets list --query film --limit 5 --json
# 先看一眼（不加 --json 時 stdout 是 JPEG）
python -s -m darkroom_app.cli preview D:/Photos/a.jpg --preset <id> --strength 80 > preview.jpg
# 匯出成給網頁用的 JPEG：長邊 2048、不超過 800 KB、拿掉 GPS
python -s -m darkroom_app.cli export D:/Photos/a.jpg --preset <id> --strength 80 --resize long_edge=2048 --max-kb 800 --remove-gps --json
```

結束碼：`0` 成功、`1` 未預期錯誤、`2` 參數不對、`3` 找不到、`4` 衝突、`5` 暫時無法使用、`6` 批次裡有部分失敗。完整指令表見 [AGENTS.md](../AGENTS.md)。

## MCP：讓 AI 代理直接操作

註冊到 Claude Code（安裝檔版用 `darkroom.exe mcp`）：

```powershell
claude mcp add darkroom -- "<repo>\.venv\Scripts\python.exe" -s -m darkroom_app.mcp_server
claude mcp add darkroom -- "C:\path\to\darkroom.exe" mcp
```

之後可以直接說「用暖色底片 preset 80% 修 D:/Photos/a.jpg，先給我看預覽」。代理會依序呼叫：

```json
{"name": "darkroom_presets_list", "arguments": {"query": "film", "limit": 5}}
{"name": "darkroom_open_photo",   "arguments": {"path": "D:/Photos/a.jpg"}}
{"name": "darkroom_preview",      "arguments": {"image_id": "<open 回的 image_id>", "preset_id": "<id>", "strength": 80}}
{"name": "darkroom_edit_set",     "arguments": {"path": "D:/Photos/a.jpg", "preset_id": "<id>", "strength": 80}}
```

`darkroom_preview` 回傳的是圖片，代理可以先看再決定；`darkroom_edit_set` 存好之後，你在 App 打開這張就會看到同樣的修改。38 個工具的清單見 [AGENTS.md](../AGENTS.md#mcp-工具總表)。

## 接下來

- [設定](configuration.md)：照片庫資料區、語言、AI 與 ComfyUI、設定匯出／匯入。
- [架構](architecture.md)：想知道一次預覽從瀏覽器到 GPU 怎麼走。
