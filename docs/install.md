# 安裝 darkroom

兩種裝法，選一種就好：

| 裝法 | 適合誰 | 需要先有 |
|---|---|---|
| [安裝檔](#一安裝檔建議) | 只想修照片的人 | 網路（第一次開啟會下載約 3 GB） |
| [從原始碼](#二從原始碼) | 要改程式、或想自己管 Python 環境的人 | Python 3.13、Node.js 22+、git |

兩種都需要**你自己的 Lightroom `.xmp` preset**（darkroom 不附任何 preset），建議有 **NVIDIA 顯示卡**（見 [GPU 與 CUDA](#三gpu-與-cuda)）。
目前支援 Windows 10／11 與 Linux（x64）；macOS 還沒有。

裝好之後看 [5 分鐘上手](quick-start.md)。

---

## 一、安裝檔（建議）

### 1. 下載

到 [GitHub Releases](https://github.com/TLOGBen/darkroom/releases) 挑最新版本：

| 系統 | 檔案 |
|---|---|
| Windows | `.msi`（Windows Installer）或 `-setup.exe`（NSIS），擇一 |
| Linux | `.deb`（Debian／Ubuntu）或 `.AppImage`（免安裝，`chmod +x` 後直接執行） |
| 命令列（可選） | `darkroom-<版本>-windows-x64.exe`、`darkroom-<版本>-linux-x64.tar.gz`：只有 `darkroom` 這個指令，給 AI 代理或腳本用 |

安裝檔本身很小：Python 與 PyTorch 不在裡面（PyTorch 的 CUDA 版約 2.5 GB，超過 GitHub Release 單檔 2 GB 的上限），第一次開啟時才下載。

### 2. 第一次開啟：同意後才下載

開啟 darkroom 後會先看到一頁說明（依系統語言顯示中文或英文），寫清楚：

- **會下載什麼**：Python 3.13、PyTorch 2.14.0、darkroom 需要的套件。偵測到 NVIDIA 顯示卡（`nvidia-smi` 找得到）就裝 CUDA 13.0 版，否則裝 CPU 版（能用，但預覽與匯出慢很多）。
- **下載量、佔用空間、裝到哪裡**。
- 只從 Python 官方來源與 PyTorch 官方下載站下載，不上傳任何東西，不碰你的照片與 preset。

按「同意並開始下載」才會開始；按「先不要」什麼都不下載。安裝中可以取消，已下載的部分會留著，下次接著裝。裝好之後自動起動後端（只綁 `127.0.0.1` 的空埠），視窗切到編輯畫面。

下載的東西全放在 App 自己的資料夾（「受管理執行環境」）：

| 系統 | 位置 |
|---|---|
| Windows | `%LOCALAPPDATA%\io.github.tlogben.darkroom\` |
| Linux | `$XDG_DATA_HOME/io.github.tlogben.darkroom/`（沒設就是 `~/.local/share/io.github.tlogben.darkroom/`） |

裡面的 `runtime/` 是 Python 環境、`uv/` 是下載的 Python 與快取、`logs/backend.log` 是後端最後一次的輸出。**整個資料夾刪掉＝回到第一次開啟的狀態**。App 更新版本後，下次開啟會再問一次，只補下載有變動的部分。

### 3. 指定 preset 資料夾

darkroom 要知道你的 `.xmp` 放在哪裡。**桌面版第一次開啟時，執行環境裝好後會直接問你**：按「選擇資料夾…」挑放 preset 的資料夾，再按「用這個資料夾」就會存進設定檔、接著啟動。之後 preset 資料夾被搬走、啟動失敗時，錯誤頁也有「改 preset 資料夾」可以重選。

不用桌面版（從原始碼、或只用 `darkroom` 指令）時，沒設 preset 資料夾會看到這一行：

```text
darkroom：還沒設定 preset 資料夾：執行 settings set preset_dir=<資料夾>（桌面版：開啟 darkroom App 選資料夾；或設環境變數 LOCALLLMS_ROOT）。設定檔：<設定檔路徑>
```

照下面任一種設好，再重新開啟 darkroom：

- **用 `darkroom` 指令**（裝了命令列執行檔時）：`settings` 指令不需要先有 preset 資料夾。

  ```powershell
  darkroom settings set preset_dir=D:/Presets/xmp
  ```

- **自己寫設定檔**：Windows 是 `%APPDATA%\darkroom\config.json`，Linux 是 `~/.config/darkroom/config.json`（有設 `XDG_CONFIG_HOME` 就在它底下）：

  ```json
  { "preset_dir": "D:/Presets/xmp" }
  ```

之後要改資料夾、語言等，在 App 的「設定」頁改，按「套用」立即生效。每個鍵的意思見 [設定](configuration.md)。

### 4. 命令列執行檔 `darkroom`（可選）

`darkroom` 是一支很小的 Rust 程式：找到 App 裝好的 Python 環境，把參數原封不動交給 darkroom 的 Python 程式，stdin／stdout／stderr 與結束碼都原樣轉回來。

```powershell
darkroom --version                           # 這支執行檔自己的版本，例如「darkroom 0.1.0」
darkroom version --json                      # 後端的版本與執行環境（Python、torch、CUDA）
darkroom presets list --limit 3 --json       # = python -s -m darkroom_app.cli presets list ...
darkroom mcp                                 # = python -s -m darkroom_app.mcp_server（MCP stdio server）
darkroom app --port 8799                     # = python -s -m darkroom_app（瀏覽器版，只綁 127.0.0.1）
```

它找 Python 的順序：環境變數 `DARKROOM_PYTHON`（任何能 `import darkroom_app` 的直譯器）→ App 的受管理執行環境。兩個都沒有時印一行中英說明、結束碼 5：

```text
darkroom：找不到 darkroom 的 Python 環境（…\io.github.tlogben.darkroom\runtime）；請先開啟 darkroom App 完成第一次設定，或用環境變數 DARKROOM_PYTHON 指定直譯器。 / darkroom: Python environment not found (…); open the darkroom app once to finish setup, or set DARKROOM_PYTHON.
```

把它註冊成 Claude Code 的 MCP server：

```powershell
claude mcp add darkroom -- "C:\path\to\darkroom.exe" mcp
```

---

## 二、從原始碼

以 Windows（PowerShell 7）為例；Linux 把 `.\.venv\Scripts\python.exe` 換成 `./.venv/bin/python`。
要讓 AI 代理替你裝，把 [`agent-install.md`](agent-install.md) 交給它（每一步都有檢查，該問你的會先問）。

### 1. 取得程式碼、建環境

```powershell
git clone https://github.com/TLOGBen/darkroom.git
cd darkroom
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
# PyTorch 先從它自己的下載站裝（CUDA 版約 2～3 GB）；沒有 NVIDIA 顯示卡就把 cu130 換成 cpu
.\.venv\Scripts\python.exe -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 裡的 `pillow-heif`（讀 HEIC）與 `anthropic`（preset 語意索引）是選用的，不裝也能跑，只是那兩個功能會關掉並說明原因。

### 2. 建置網頁

編輯畫面是 `web/` 裡的 React 程式，伺服器只供應它的建置結果 `web/dist`。第一次約 1～3 分鐘（主要在下載 npm 套件），之後拉到前端的更新時再建一次：

```powershell
cd web; npm ci; npm run build; cd ..
```

沒建置也能啟動，API 照常可用，但打開頁面會看到 HTTP 503 與同樣的建置指令。

### 3. 指定 preset 資料夾

在 repo 根目錄建 `config.local.json`（不進 git），至少寫 preset 資料夾：

```json
{ "preset_dir": "D:/Presets/xmp" }
```

或用指令寫（`settings` 不需要先有 preset 資料夾）：

```powershell
.\.venv\Scripts\python.exe -s -m darkroom_app.cli settings set preset_dir=D:/Presets/xmp
```

其他鍵（照片庫資料區 `data_dir`、語言、AI、ComfyUI…）見 [設定](configuration.md)。

### 4. 啟動與檢查

```powershell
.\.venv\Scripts\python.exe -s -m darkroom_app            # 印出「darkroom 已啟動：http://127.0.0.1:8765/」
Invoke-WebRequest http://127.0.0.1:8765/api/health -UseBasicParsing   # 回 {"ok": true}
.\.venv\Scripts\python.exe -s -m darkroom_app.cli --version          # darkroom 0.1.0
```

瀏覽器開 <http://127.0.0.1:8765/>。`--port` 換埠（不要用 80），`--preset-dir`／`--data-dir` 只覆蓋這一次執行。Ctrl+C 停止。

（作者環境另有 `pwsh -File tools/start.ps1`：從 `config.local.json` 找專用 Python、沒有 `web/dist` 時先建置、等就緒再開瀏覽器；`-Port`、`-NoBrowser`、`-RebuildWeb`、`-TimeoutSec` 可調。一般使用者用上面的指令即可。）

### 5. 跑測試（建議）

```powershell
.\.venv\Scripts\python.exe -s -m unittest discover -s tests
```

幾分鐘，最後印 `OK`（GPU 忙碌時計時類測試會自動跳過）。測試只寫暫存資料夾；寫到別處的測試會直接失敗。前端與桌面的測試見 [開發](development.md)。

---

## 三、GPU 與 CUDA

- darkroom 用 PyTorch 渲染。**有 NVIDIA 顯示卡＋CUDA 版 PyTorch** 時預覽約 15～20 ms（1.5MP）；沒有時自動改用 CPU，功能一樣但慢很多（`capabilities` 的 `gpu` 會寫「關閉」與原因）。
- 驅動要夠新：`nvidia-smi` 右上角的「CUDA Version」要 ≥ 你裝的 PyTorch 的 CUDA 版本（預設 cu130＝13.0）。驅動太舊時改裝 PyTorch 提供的較舊 CUDA 版本（例如 cu128），或更新驅動。
- AMD、Intel 顯示卡與 Apple Silicon 目前只能用 CPU。長期計畫是把渲染核心改寫成 Rust＋wgpu（Vulkan／DX12／Metal），就不再綁 NVIDIA 與 PyTorch，見 [語言評估](rust-evaluation.md)。
- 檢查：

  ```powershell
  .\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
  .\.venv\Scripts\python.exe -s -m darkroom_app.cli version --json    # 回 version、python、torch、cuda、platform
  ```

---

## 四、疑難排解

| 狀況 | 原因／怎麼辦 |
|---|---|
| `darkroom：還沒設定 preset 資料夾…` | 還沒設 preset 資料夾。見上面「指定 preset 資料夾」。 |
| `darkroom：preset folder not found: …` | `preset_dir` 指到不存在的資料夾。`settings get` 看目前用的是哪個設定檔、哪個值。 |
| `… 不是正確的 JSON（第 N 行第 M 欄）…` | 設定檔手改壞了。照行號欄號修好；darkroom 不會覆蓋壞掉的設定檔。 |
| 打開頁面是「網頁介面還沒建置」（HTTP 503） | 從原始碼執行但沒建 `web/dist`。`cd web; npm ci; npm run build`。 |
| 每個請求都回 421／403 | 用了 `127.0.0.1`／`localhost` 以外的主機名，或透過代理。一律開 `http://127.0.0.1:<埠>/`。 |
| `darkroom：無法啟動伺服器：…`（結束碼 1） | 埠被占用，換 `--port`。 |
| `torch.cuda.is_available()` 是 `False` | 裝到 CPU 版 PyTorch，或驅動太舊。照「GPU 與 CUDA」重裝。 |
| HEIC 照片被拒 | 沒裝 `pillow-heif`（`pip install pillow-heif==1.8.0`）。 |
| 有按鈕變灰／功能被關掉 | `darkroom_app.cli capabilities`（或 App 頂列的「功能狀態」）逐項列出 `gpu`、`heic`、`webp`、`photo_library`、`preset_library_writes`、`semantic_index`、`onepassword`、`comfyui`、`agent_sdk` 與原因，照原因處理。 |
| 安裝檔第一次開啟的下載失敗 | 說明頁會附安裝程式最後的輸出；常見是網路中斷或磁碟空間不足。按「再試一次」從中斷處接著裝。 |
| 桌面 App 顯示「後端啟動後馬上結束了」 | 下面附的就是後端自己的錯誤句子（多半是設定問題），也寫在 `logs/backend.log`。 |
| preset 顯示「有設定無法套用」 | 預期行為（相機描述檔、Adobe Look、絕對白平衡），其餘設定照常套用。 |
