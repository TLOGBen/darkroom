---
name: darkroom-setup
description: 安裝、第一次設定、改設定與疑難排解 darkroom（本機 Lightroom preset 修圖工具）。使用者說「安裝 darkroom」「幫我裝 darkroom」「設定 darkroom」「darkroom 跑不起來」「preset 找不到」「config.local.json」「註冊 MCP」「setup darkroom」「install darkroom」「configure darkroom」「darkroom troubleshooting」時用。步驟以 docs/agent-install.md 為準，本 skill 只補要先問的問題、安全規則與檢查方式。
---

# darkroom-setup

## 什麼時候用

- 使用者要在這台電腦第一次裝 darkroom。
- 要改設定：preset 資料夾、`preset_library_dir`、`data_dir`、介面語言、AI 金鑰參照、ComfyUI 位址、換 Python 環境；備份／還原設定。
- darkroom 起不來、CLI 回設定錯誤、HEIC 讀不了、GPU 用不到、App 裡有按鈕變灰（功能被偵測關掉）。
- 要把 darkroom 註冊成 MCP server。

## 步驟的唯一來源

**先分清楚是哪一種安裝**：

- **安裝檔版**（使用者只想修照片）：請他從 GitHub Releases 下載 `.msi`／`-setup.exe`／`.deb`／`.AppImage`，第一次開啟時他自己按同意下載 Python＋PyTorch（約 3 GB）。說明在 `docs/install.md`。代理用的指令是 `darkroom`（同一頁的 `darkroom-<版本>-windows-x64.exe`／`linux-x64.tar.gz`），等於 `python -s -m darkroom_app.cli`。**目前沒設 preset 資料夾時桌面版後端起不來**：問到資料夾後用 `darkroom settings set preset_dir=…`，再請他重開 App。
- **原始碼版**：**照 `docs/agent-install.md` 從頭做到尾**，每一步的 check 通過才往下；不要另外發明步驟，也不要跳步。這份 skill 不重抄那些指令，避免兩邊分歧。它第 0～8 步分別是：安裝檔或原始碼 → 檢查機器 → 取得程式碼 → 建 `.venv` 並裝 torch（CUDA）與 `requirements.txt` → 用 `settings set preset_dir=…` 指到 preset → 跑測試 → 建置網頁（`cd web; npm ci; npm run build`）並啟動、健康檢查 → （可選）註冊 MCP → 回報。疑難排解表在同一份文件最後。

## 動手前先問使用者

1. `.xmp` preset 放在哪個資料夾？（絕對不要猜；確認資料夾存在、數一下有幾個 `.xmp` 再寫進設定）
2. 要下載 PyTorch CUDA 版（約 2～3 GB），可以嗎？
3. 要不要註冊 MCP（讓代理之後能直接操作 darkroom）？
4. 要不要跑完整測試（幾分鐘）？
5. 想不想另外指定 `data_dir`（照片庫的編輯、縮圖快取與匯出預設；預設 Windows `%LOCALAPPDATA%\darkroom`、macOS `~/Library/Application Support/darkroom`、Linux `$XDG_DATA_HOME/darkroom` 或 `~/.local/share/darkroom`）？

使用者用 README 的「貼給你的 Agent」那段話來找你時，這五個問題他大多已經回答了一部分；沒回答的再問。

## 安全規則

- 照片資料夾、preset 資料夾只讀：不複製、不搬、不改名、不「整理」。
- 不動系統 Python、PATH、其他專案的環境；只用 repo 裡的 `.venv`（作者環境例外，見 `CLAUDE.md` 最後一節）。
- `config.local.json` 不進 git；`preset_library_dir`、`data_dir` 不可以放在照片資料夾或 `preset_dir` 裡面。
- 只綁 `127.0.0.1`，不開到網路、不用 80 埠。
- 任何 check 失敗：把原始輸出給使用者看、停下來，不要硬繞過。

## 設定速查

設定檔依序找第一個存在的：`DARKROOM_CONFIG` → repo 根目錄 `config.local.json` → 平台設定資料夾（Windows `%APPDATA%\darkroom\config.json`、Linux `~/.config/darkroom/config.json`）。`settings get --json` 的 `config_file` 告訴你用的是哪個。

**改設定一律用 `settings set`**（全部驗證通過才寫、寫完 App 與 MCP 立即生效、還沒有 preset 資料夾時也能用），不要手改檔案：

```powershell
python -s -m darkroom_app.cli settings get --json
python -s -m darkroom_app.cli settings set preset_dir=D:/Presets/xmp --json
python -s -m darkroom_app.cli settings set data_dir=D:/darkroom-data language=en-US --json
python -s -m darkroom_app.cli settings set data_dir=null --json            # null＝回到預設
python -s -m darkroom_app.cli settings export --out D:/backup/darkroom-settings.json --json
python -s -m darkroom_app.cli settings import D:/backup/darkroom-settings.json --json
```

任何一個值不對就整批不寫（`invalid`，結束碼 2），把錯誤原句給使用者。全部的鍵與驗證規則在 `docs/configuration.md`；常用的：

| 鍵 | 意思 | 預設 |
|---|---|---|
| `preset_dir` | 買來的 `.xmp` 所在資料夾（只讀） | 無；一般使用者必填 |
| `preset_library_dir` | 索引 `library.json`、`import/`、`user/` 放哪 | `preset_dir` 的上一層 |
| `data_dir` | 照片庫：`edits/`、`thumbs/`、`index/`、`export-presets.json` | Windows `%LOCALAPPDATA%\darkroom`；macOS `~/Library/Application Support/darkroom`；其他 `$XDG_DATA_HOME/darkroom`（要是絕對路徑），否則 `~/.local/share/darkroom` |
| `localllms_root` | 作者自己的環境根目錄 | 一般使用者不用 |
| `language` | 介面語言 `zh-TW`／`en-US` | `zh-TW` |
| `agent.api_key_ref` | Anthropic 金鑰的 1Password 參照 `op://…`（舊名 `anthropic_api_key_ref` 照樣讀）；**絕不放金鑰本身**，`settings set` 會拒絕 | 無（語意索引關閉） |
| `agent.budget_usd` | 一次語意索引 build 的費用上限（舊名 `semantic_index_budget_usd`） | `5` |
| `comfyui_url` | ComfyUI API，只接受本機位址 | `http://127.0.0.1:8188` |

單次覆蓋：啟動 App、CLI、MCP server 都吃 `--preset-dir DIR`、`--data-dir DIR`；給了 `--preset-dir` 時庫根目錄就是它的上一層（不會用設定檔的 `preset_library_dir`）。

相對路徑：設定檔裡的 `preset_dir`／`preset_library_dir`／`data_dir` 以設定檔所在資料夾為基準；`--preset-dir`／`--data-dir` 以目前工作目錄為基準。設定檔不是正確的 JSON 時會一行說哪一行哪一欄錯（`darkroom：config.local.json 不是正確的 JSON（第 N 行第 M 欄）：…`，結束碼 2），照著修。

## 裝好的驗證（讀取類，不寫檔）

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
.\.venv\Scripts\python.exe -s -m darkroom_app.cli version --json        # version、python、torch、cuda、platform
.\.venv\Scripts\python.exe -s -m darkroom_app.cli presets list --limit 3 --json
.\.venv\Scripts\python.exe -s -m darkroom_app.cli presets groups --json
```

第二行要印出一行 `{"ok":true,…}`；`darkroom：preset folder not found: …` 或 `darkroom：set LOCALLLMS_ROOT or write config.local.json …`（結束碼 2）就是 `preset_dir` 沒設對。列 preset、看群組不會建立 `library.json`，可以放心對真實 preset 庫跑。

## 疑難排解的入口

先查 `docs/agent-install.md` 的 Troubleshooting 表；再看 `AGENTS.md`「結束碼與錯誤怎麼讀」。常見：

- `torch.cuda.is_available()` 是 `False`：裝到 CPU 版 torch，或驅動太舊；照安裝文件第 3 步重裝 CUDA 版。
- HEIC 被拒：`pillow-heif` 沒裝（選用，`pip install pillow-heif==1.8.0`）。
- 有功能被關掉、按鈕變灰：`.\.venv\Scripts\python.exe -s -m darkroom_app.cli capabilities` 逐項列出 `gpu`、`heic`、`webp`、`photo_library`、`preset_library_writes`、`semantic_index`、`onepassword`、`comfyui`、`agent_sdk` 可不可用與原因（`--json` 是結構化結果、`--refresh` 重測）。照原因處理，例如 preset 庫在照片資料夾裡 → 把 `preset_library_dir` 設到別處；照片庫資料區找不到 → 設 `data_dir`。設定了 `agent.api_key_ref`（舊名 `anthropic_api_key_ref`）時它會跑一次 `op whoami`（只查登入，不讀秘密）；沒用 1Password 時 `onepassword` 顯示關閉是正常的。
- 打開頁面是「網頁介面還沒建置」（HTTP 503）：原始碼版沒建 `web/dist`，`cd web; npm ci; npm run build`。
- 瀏覽器打開全是 421／403：用了 `localhost` 以外的主機名或 80 埠；一律 `http://127.0.0.1:<埠>/`。
- preset 顯示「有設定無法套用」：預期行為（相機描述檔、Adobe Look、絕對白平衡），其餘仍會套；`presets show <id>` 的 `note` 有中文說明。

## 完成時回報

裝在哪、Python 與 PyTorch 版本、GPU、preset 資料夾與數量、測試結果、怎麼啟動（`darkroom-start`）、有沒有註冊 MCP。
