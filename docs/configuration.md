# 設定

darkroom 的設定是**一個 JSON 檔**。App 的設定頁、CLI、MCP 讀寫的都是同一個檔，改了**立即生效**（不用重開），而且**全部驗證通過才寫入**：一次改五個鍵、其中一個不對，五個都不會寫。

## 設定檔在哪

依序找，**第一個存在的就是它**；寫入時寫回同一個檔：

| 順序 | 位置 | 什麼時候用 |
|---|---|---|
| 1 | 環境變數 `DARKROOM_CONFIG` 指的檔 | 有設就一定用它（檔案還不存在也是，第一次儲存時建立）。測試、暫時換一套設定時用 |
| 2 | repo 根目錄的 `config.local.json` | 從原始碼執行時（不進 git） |
| 3 | 平台的設定資料夾 | Windows `%APPDATA%\darkroom\config.json`；Linux `$XDG_CONFIG_HOME/darkroom/config.json`（沒設就是 `~/.config/darkroom/config.json`）；macOS `~/Library/Application Support/darkroom/config.json` |

三個都不存在時，第一次儲存會建立第 3 個（安裝檔版就是這個）。想知道現在用的是哪個檔：

```powershell
python -s -m darkroom_app.cli settings get --json      # result.config_file
```

檔案壞了（不是正確的 JSON）時，所有入口都會一行說出檔名與行號欄號，例如 `config.local.json 不是正確的 JSON（第 3 行第 5 欄）：…`；darkroom **不會覆蓋壞掉的設定檔**，請先手動修好。
設定檔裡 darkroom 不認得的鍵會原樣保留（手改加的東西不會被儲存吃掉）。

## 每個鍵

全部可選；沒寫就用預設。API 用扁平的鍵名（`agent.model`），檔案裡 `agent.*` 寫成一個巢狀物件：

```json
{
  "preset_dir": "D:/Presets/xmp",
  "data_dir": "D:/darkroom-data",
  "language": "en-US",
  "agent": { "api_key_ref": "op://Personal/Anthropic/credential", "budget_usd": 5 }
}
```

| 鍵 | 值與預設 | 驗證 | 改了之後 |
|---|---|---|---|
| `language` | `"zh-TW"`｜`"en-US"`，預設 `zh-TW` | 只能是這兩個 | 介面語言立即切換（介面語言的順序：這個設定 → 瀏覽器語言 → zh-TW） |
| `preset_dir` | 買來的 `.xmp` 所在資料夾（只讀）。預設 `<localllms_root>/artifact/11_preset/xmp`；一般使用者**必填** | 絕對路徑、資料夾要存在 | 重組整個 App，preset 列表重讀 |
| `preset_library_dir` | preset 庫根目錄：索引 `library.json`、匯入區 `import/`、自存 preset `user/`、語意索引 `semantic.json`。預設 `preset_dir` 的上一層 | 絕對路徑、存在、不可以在 `preset_dir` 裡面 | 重組，preset 列表重讀 |
| `data_dir` | 照片庫：每張照片的修改 `edits/`、縮圖 `thumbs/`、資料夾索引 `index/`、匯出預設 `export-presets.json`。預設 Windows `%LOCALAPPDATA%\darkroom`、macOS `~/Library/Application Support/darkroom`、其他 `$XDG_DATA_HOME/darkroom`（絕對路徑才算）或 `~/.local/share/darkroom` | 絕對路徑；資料夾本身可以還不存在（第一次寫入時建立），但上一層要存在；不可以在 `preset_dir` 裡面 | 重組，下一次存修改就寫到新位置（舊位置的資料不搬） |
| `localllms_root` | 作者自己的模型／執行環境資料夾；一般使用者不用 | 絕對路徑、存在 | 重組（`preset_dir`、`calibration_sources_dir` 的預設跟著變） |
| `comfyui_url` | ComfyUI 的 API 位址，預設 `http://127.0.0.1:8188` | 只接受本機：`http(s)://127.0.0.1:埠`、`localhost:埠`、`[::1]:埠`，不能帶路徑、帳密、query | 能力 `comfyui` 立即重測（直接打 `GET /system_stats`，1 秒逾時，不走 proxy） |
| `comfyui_root` | ComfyUI 安裝資料夾，預設無 | 絕對路徑、存在 | 目前只記錄，給之後的擴散模型功能用 |
| `agent.api_key_ref` | Anthropic 金鑰的 **1Password 參照** `op://<vault>/<item>/<field>`，預設無 | 一定要是 `op://…` 的形狀；**看起來像金鑰本身（`sk-ant-…`）會被拒絕，而且錯誤訊息不回顯** | 回應的 `checks.agent_sdk` 立即重測；能力快取作廢，`semantic_index`、`onepassword` 下次讀能力時重測。金鑰只在要用時才 `op read` 讀進記憶體，從不寫檔 |
| `agent.model` | darkroom 自己呼叫 Claude 時用的模型，預設 `claude-haiku-5-5` | 1～100 字、不含空白 | 目前只記錄，給之後的 AI 助理用；preset 語意索引依合約固定用 `claude-haiku-5-5` |
| `agent.budget_usd` | 一次 `presets semantic build` 的費用上限（美元），預設 `5` | 大於 0 的有限數字 | 下一次 build 用新上限 |
| `calibration_sources_dir` | 語意索引用的 4 張公開標準圖所在資料夾，預設 `<localllms_root>/scratch/lr-calibration/sources` | 絕對路徑、存在 | 下一次 build 用新位置（只讀固定的 4 個檔名） |

規則補充：

- **值給 `null`（或空字串）＝回到預設**，那個鍵會從檔案拿掉。
- 不認得的鍵整次拒絕：`不認得的設定鍵：foo（可用 language、preset_dir、…）`。
- 舊鍵名照樣讀：`anthropic_api_key_ref`（＝`agent.api_key_ref`）、`semantic_index_budget_usd`（＝`agent.budget_usd`）。寫入一律用新鍵，並拿掉對應的舊鍵。
- 檔案裡的 `preset_dir`、`preset_library_dir`、`data_dir` 寫相對路徑時，以**設定檔所在資料夾**為基準；透過設定 API 寫入一律要絕對路徑。
- 還沒有 preset 資料夾時，其他鍵存不進去（`要先設定 preset_dir（preset 資料夾）才能儲存設定`）：第一次請先設 `preset_dir`，或跟其他鍵一起設。
- 改 `preset_dir`、`preset_library_dir`、`localllms_root` 時，會先用「改完之後的整份設定」算一次 preset 資料夾：算不出來（例如把 `preset_dir` 清掉、又沒有 `localllms_root`）回 `這樣改之後就沒有 preset 資料夾了…`，算出來的資料夾不存在（例如 `localllms_root` 底下沒有 `artifact/11_preset/xmp`）回 `這樣改之後的 preset 資料夾不存在：…`，兩種都是 invalid、**設定檔一個字都不改**。萬一寫進去之後重組仍然失敗，會把原本的內容寫回去，回 unavailable `新設定套用不了，設定檔已改回原本的內容：…`。
- **金鑰絕不寫進設定檔**：任何一個鍵（包括 `agent.model`、`comfyui_url`、路徑）的值只要看起來像 Anthropic 金鑰（含 `sk-ant-`），整個請求都拒絕（`不要把金鑰本身存進設定…`），錯誤句子也不會把那個值印出來。
- 手改設定檔寫了不合規則的值（例如 `comfyui_url` 不是本機、`agent.budget_usd` 是負數）時，`settings get` 顯示的與實際使用的都是預設值（來源 `default`），darkroom 不會因為設定檔去連別台機器。
- `preset_library_dir`、`data_dir` 也不要放在照片資料夾裡：preset 庫根目錄落在照片資料夾時，整理／匯入／存成 preset 會被關掉並說明原因（`capabilities` 的 `preset_library_writes`）；照片庫資料區落在某張照片的資料夾裡時，那張的修改不會寫入（寫檔守門拒絕）。

### 每個值從哪裡來（`sources`）

`settings get` 回的 `sources` 告訴你每個鍵現在的值從哪來：

| 值 | 意思 |
|---|---|
| `file` | 寫在設定檔裡 |
| `env` | 環境變數決定（目前只有 `localllms_root` 會被 `LOCALLLMS_ROOT` 蓋過）；App 設定頁上這種欄位是唯讀的 |
| `cli` | 這次啟動時由命令列 `--preset-dir`／`--data-dir` 指定（`--preset-dir` 也決定 `preset_library_dir`）；這次執行期間固定 |
| `default` | 沒寫，用預設 |

`settings` 回的 `settings` 一律是**這個程序實際在用的值**。被命令列固定的鍵照樣可以改：新值寫進設定檔，但回應把它列在 `pending_restart`（不在 `applied`），下次不帶那個旗標啟動才生效。

### 別的程序改了設定

App 開著時用 CLI 或 MCP（另一個程序）改設定，App 在下一個請求前就會發現設定檔變了（比對檔案的修改時間與大小），用跟 App 自己改設定同一條路重組：`data_dir`、`comfyui_url`、`agent.*`… 同時生效，設定頁顯示的就是正在用的。設定檔壞掉（不是 JSON）或新設定組不起來時，App 繼續用原本的設定。

## 三個入口怎麼改

| 做什麼 | HTTP（App 用） | CLI | MCP |
|---|---|---|---|
| 讀 | `GET /api/settings` | `settings get` | `darkroom_settings_get` |
| 改（部分） | `PUT /api/settings`，body `{"values": {鍵: 值}}` | `settings set KEY=VALUE...` | `darkroom_settings_set`（`values`） |
| 匯出 | `GET /api/settings/export`（瀏覽器下載） | `settings export [--out FILE]` | `darkroom_settings_export`（`dest` 給了才寫檔） |
| 匯入 | `POST /api/settings/import`，body `{"document": …}` | `settings import FILE` | `darkroom_settings_import`（`document` 或 `path` 恰好一個） |
| 版本 | `GET /api/version` | `version`（或 `--version` 只印版本號） | `darkroom_version` |

回傳內容：

- **讀**：`{settings: {鍵: 目前的值}, defaults: {鍵: 預設}, sources: {鍵: file|env|cli|default}, config_file}`。
- **改／匯入**：`{settings, applied: [這次改、已生效的鍵], pending_restart: [寫進檔案但被命令列固定、下次啟動才生效的鍵], checks: {comfyui, agent_sdk, photo_library, preset_library_writes}}`，`checks` 每項是 `{available, reason}`，是改完之後立刻重測的結果。
- **匯出**：`{format: "darkroom-settings/1", version, settings}`，只含**寫在設定檔裡**的鍵（不含預設值與環境變數），拿到別台電腦或重灌後匯入。CLI 的 `--out` 只建新檔，**已存在就拒絕、不覆蓋**。
- **版本**：`{version, python, torch, cuda, platform}`。

### CLI 範例

`VALUE` 能當 JSON 解析就用 JSON（`5`、`true`、`null`、`"x"`），否則當字串（`en-US`、`D:/Presets/xmp`）。

```powershell
python -s -m darkroom_app.cli settings get --json
python -s -m darkroom_app.cli settings set language=en-US agent.model=claude-sonnet-5 --json
python -s -m darkroom_app.cli settings set language=null --json                 # 回到預設 zh-TW
python -s -m darkroom_app.cli settings set preset_dir=D:/Presets/xmp data_dir=D:/darkroom-data --json
python -s -m darkroom_app.cli settings export --out D:/backup/darkroom-settings.json --json
python -s -m darkroom_app.cli settings import D:/backup/darkroom-settings.json --json
python -s -m darkroom_app.cli version --json
python -s -m darkroom_app.cli --version
```

驗證失敗是 `invalid`（結束碼 2），例如：

```text
{"ok":false,"error":{"kind":"invalid","message":"comfyui_url 只能是本機位址（http://127.0.0.1:埠、http://localhost:埠 或 http://[::1]:埠）：http://example.com:8188"}}
```

`settings` 與 `version` 在還沒有 preset 資料夾時也能用，所以第一次設定可以直接 `settings set preset_dir=…`。

### HTTP 的額外限制

- 只綁 `127.0.0.1`，並經過本機檢查（Host、Origin、`Sec-Fetch-Site`、Content-Type）。`GET /api/settings` 與 `GET /api/settings/export` 會回本機資料夾路徑，所以要帶 `X-Darkroom: 1` 標頭（別的網頁的 `<img>`／`<script>` 加不了這個標頭）。
- HTTP 匯入只收文件內容，不收路徑：body 有 `path` → 400 `path is not accepted over HTTP (send the document)`。
- HTTP 匯出不寫檔：query 有 `dest` → 400 `dest is not accepted over HTTP (the page downloads the document)`。

## 「立即生效」怎麼做到的

改設定成功後，伺服器（與 MCP server）用新設定**重新組裝**整個 App：preset 庫、照片庫、能力偵測快取都換新的；**GPU 引擎保留**，已經開著的照片不會被關掉。正在跑的請求用舊的那套做完，下一個請求就用新的。細節見 [架構：設定立即生效](architecture.md#6-設定立即生效)。

命令列給的 `--preset-dir`／`--data-dir` 在那個程序結束前**優先於設定檔**：這時在設定頁改 `preset_dir`，會寫進設定檔，但這次執行仍用命令列給的資料夾。

## 環境變數

| 變數 | 誰讀 | 作用 |
|---|---|---|
| `DARKROOM_CONFIG` | 後端 | 設定檔路徑（優先於其他位置） |
| `LOCALLLMS_ROOT` | 後端 | 蓋過設定檔的 `localllms_root`（作者環境） |
| `DARKROOM_ANTHROPIC_API_KEY` | 後端 | 不用 1Password 時的金鑰來源（只在記憶體） |
| `DARKROOM_WEB_DIST` | 後端 | 另一個網頁建置資料夾（有設就只看它；測試用） |
| `DARKROOM_PYTHON` | `darkroom` 執行檔、桌面 App | 指定一個能 `import darkroom_app` 的 Python，跳過受管理執行環境 |
| `DARKROOM_UV`、`DARKROOM_WHEEL` | 桌面 App（開發） | 指定安裝用的 `uv` 與 darkroom wheel |
| `DARKROOM_PORT`、`DARKROOM_WEB_PORT` | `web/` 的開發伺服器 | 後端埠（預設 8765）、Vite 埠（預設 5173） |

## 單次覆蓋

```powershell
python -s -m darkroom_app --preset-dir D:/Presets/xmp --data-dir D:/darkroom-data   # App
python -s -m darkroom_app.cli --preset-dir D:/Presets/xmp presets list --json        # CLI（放在子指令前面）
```

給了 `--preset-dir` 時，preset 庫根目錄是它的上一層（不用設定檔的 `preset_library_dir`）。命令列的相對路徑以目前工作目錄為基準。
