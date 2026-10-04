# darkroom — 本機專業相片編輯（Lightroom preset＋AI）

回覆一律用繁體中文（台灣用語）。程式碼、識別字、指令、路徑維持原文。

## 這是什麼

使用者退了 Lightroom 訂閱，要在本機用自己買的 Lightroom XMP preset 修照片：點 preset → 調強度 → 微調滑桿，拖動即時預覽；AI 只做程式做不到的部分。
2026-10-04 從 LocalLLMs repo 的規劃獨立出來（使用者指定放 `D:/Code/darkroom`）。

## 目前狀態：核心函式庫已封緘；App 外殼（`darkroom_app/`）已做

- 啟動：`tools/start.ps1`（專用 Python 跑 `python -s -m darkroom_app`，只綁 127.0.0.1、預設埠 8765，就緒後開瀏覽器）；桌面捷徑用 `tools/make-shortcut.ps1` 產生。LocalLLMs 路徑來自 `LOCALLLMS_ROOT` 或 `config.local.json`（不進 git，鍵：localllms_root、preset_dir）。
- 延遲驗收：`python -s tools/bench_preview.py`（GPU 真的忙碌才跳過：使用率取樣中位數 > 15% 或 ComfyUI 佇列非空；`--force` 強制量測）。
- 測試：`python -s -m unittest discover -s tests`。

- **先讀地圖**：`.claude/wayfinder/darkroom/map.md`（Destination、已定原則、Decisions so far、還看不清楚、不在範圍內）；每個決定的細節在 `issues/`，研究在 `research/`，實驗與原型在 `prototypes/`。用 `/common:wayfinder` 帶這個地圖路徑繼續；HTML 檢視：`map.html`（不要手改，改 markdown 後重跑 wayfinder 的 `render_map.py`）。
- **計畫檔**：`.claude/think/comfyui-lightroom-preset-editor.md`（最初的 ① 調色引擎計畫；開頭註明載體已改，其餘仍有效）。
- 研究擷取的原文在 `.claude/read/material/`。

## 已定的大方向（細節以地圖為準）

- **載體**：核心做成函式庫（版本化的參數 JSON schema，欄位用 xmp 的 crs 鍵名＋torch GPU 渲染），主介面是獨立本機 App（Python 後端＋Web 前端）；直接呼叫 llama-server；只有擴散模型（Qwen 移除／重畫、SeedVR2 放大）才透過 ComfyUI API 呼叫。理由：ComfyUI 讀寫 8-bit、不保留 ICC／EXIF、介面是排隊執行。
- **原則**：xmp 的設定一律由程式執行；AI 只負責看懂畫面、找出位置（遮罩、關鍵點）、重畫內容；要用滑桿調、要能重複的部分由程式做。
- **② AI 修圖助理**：PE-I2I（不思考）看圖給滑桿數值，json_schema 強制格式；白平衡由程式先量，診斷與數值矛盾就重問或歸零。不做 AI 自動挑 preset。

## 依賴 LocalLLMs（`C:/Users/powde/workspace/LocalLLMs`）

模型、執行程式與使用者的 preset 都在 LocalLLMs，**不要複製進本 repo**：
- preset：`artifact/11_preset/xmp`（1466 個；preset 庫索引 `artifact/11_preset/library.json`、自存 preset `artifact/11_preset/user/`）
- llama-server：`runtimes/llama.cpp/b11223-cuda/llama-server.exe`；PE-I2I：`models/qwen-image-2.1/text-encoders/pe-i2i-heretic/`（Q8 gguf＋mmproj）
- ComfyUI：`launcher/launcher.ps1 -Start comfyui -Headless`，API 在 `http://127.0.0.1:8188`
- 動到 LocalLLMs 的東西時遵守它的 CLAUDE.md：模型下載要驗 SHA256、ComfyUI 自己跑一律 headless、測完關模型、同一時間只讓一個程式佔 GPU（16GB）。
- 程式裡的 LocalLLMs 路徑不要寫死：用設定檔或環境變數（例如 `LOCALLLMS_ROOT`）。

## 慣例

- Windows 端腳本用 PowerShell 7（pwsh），不寫 `.cmd`／`.bat`。
- commit 訊息用 conventional commits（feat／fix／docs／chore…）。
- App 執行環境＝LocalLLMs 的 darkroom 專用 Python（`runtimes/darkroom-python/...`）；操作台（LocalLLMs launcher）項目還沒加。
