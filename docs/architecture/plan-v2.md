# darkroom v2 架構規劃（施工依據）

> **現況請看 [`docs/architecture.md`](../architecture.md)**（v2 完工後對照實際程式寫的版本，含跟這份計畫不一樣的地方）。這份保留做決策紀錄，不再更新。

> 2026-10-10 定稿。這份是 v2 改造的**共同依據**：所有實作者（人或代理）照這裡的分層、目錄、介面施工；要偏離先改這份。
> 完工後的現況說明寫在 `docs/architecture.md`（給讀者看），這份保留做決策紀錄。

## 0. 已定的決策

| 項目 | 決定 | 理由 |
|---|---|---|
| 前端 | React 19＋TypeScript＋Vite＋MUI v7＋Sass（CSS modules）；i18next | 使用者指定 React＋MUI；MUI 自帶 emotion，再混 Tailwind 會有兩套樣式系統互搶 |
| 桌面外殼 | Tauri 2（Rust） | 生態成熟、安裝檔小（Windows .msi／NSIS .exe、Linux .deb／.AppImage）、本身就是 Rust，跟後端遷移方向一致 |
| 後端語言 | **長期遷移到 Rust**（取代 ADR-0003），用「逐塊替換」：每次換一個 service，Python 測試當對照基準 | 不計風險時的最佳終點：單一執行檔、安裝檔小、不綁 NVIDIA／torch（wgpu 跑 Vulkan／DX12／Metal）。細節見 `docs/adr/0004-*` 與 `docs/rust-evaluation.md` |
| v2 這一輪 | Python 後端留著、整理分層；Rust 只寫外殼與 CLI launcher | 先把介面（HTTP／CLI／MCP 合約）理乾淨，之後換實作時入口不用動（ADR-0001） |
| 版本號 | 只有一個來源：`darkroom_app/__init__.py` 的 `__version__` | pyproject、Tauri、`/api/version`、`cli --version` 全部讀它（CI 在打包前同步） |

## 1. 後端分層（Python，`darkroom_app/`）

依賴只能由外往內：`adapters → facade → services → domain → utils`；`darkroom/`（核心函式庫）不認識 `darkroom_app`。

```
darkroom/                    核心：xmp 解析、參數、torch 渲染、讀寫影像、幾何（不動結構）
darkroom_app/
  adapters/                  最外圈（clean architecture 的 adapter 層，彼此同層）
    http/server.py           aiohttp 路由：解析 request → 呼叫 facade → 轉 HTTP 狀態碼
    http/middleware.py       只綁本機的檢查（Host／Sec-Fetch-Site／Origin／Content-Type／X-Darkroom）
    cli.py                   argparse → facade → 結束碼／--json 信封
    mcp_server/              stdio JSON-RPC → facade → MCP 結果
    persist/                 所有檔案儲存：locks.py（跨程序鎖＋壞檔備份）、edit_store.py、thumb_store.py、
                             preset_index.py（library.json）、export_presets_store.py、semantic_store.py、
                             settings_store.py
    gpu/engine.py            torch GPU 轉接
  facade.py                  三入口共用的唯一介面（Facade Protocol＋DarkroomFacade）
  operations.py              操作清單（MCP 工具順序、參數 schema）
  composition.py             唯一的組裝點：讀設定、建 persist／service、注入；設定改了就重組（見 §3）
  config.py                  只有 composition 與入口可以讀
  services/                  業務邏輯；只吃 domain 物件，不碰 request、不直接讀設定、不自己開檔
  domain/                    業務物件與規則：adjustment.py（Adjustment.from_request＝VO→BO 驗證）、
                             sentinels.py（KEEP）、errors.py、messages.py、sliders.py、skips.py、formats.py、
                             settings.py（Settings 物件與驗證）
  utils/                     無業務知識的工具：safe_write.py、encoding.py、imaging.py（縮圖、EXIF、fingerprint）、
                             text.py（_one_line 等）、gpucheck.py
```

規則：
- **VO → BO**：入口拿到的原始參數（dict／argparse／JSON）在 facade 邊界轉成 domain 物件（`Adjustment`、`Geometry`、`Settings`、`ExportOptions`），驗證失敗就是 `invalid`，錯誤句子一字不改（三入口一致性測試把關）。
- service 不 import facade、adapters、config；需要的東西由 composition 注入。
- 舊模組路徑（`darkroom_app.preview`、`.engine`、`.presets`、`.server`…）留 re-export shim，讓既有測試與外部指令不壞；shim 檔頭註明「相容用，新程式不要 import」。
- 已封緘合約（`CONTRACT-layering` 等）被這次搬家影響的條文，在該合約補「v2 修訂紀錄」一節，不刪原文。

## 2. 前端（`web/`）

```
web/
  index.html  package.json  vite.config.ts  tsconfig.json  DESIGN.md（設計系統說明）
  static/                    公開靜態檔（Vite publicDir 指到這裡）：logo、favicon
  src/
    main.tsx  App.tsx        進入點、Provider（Theme、i18n、Router、QueryClient）
    pages/                   一個路由一頁：EditorPage、SettingsPage
    layouts/                 AppLayout（頂列＋導覽）、EditorLayout（三欄）
    components/              依領域分子資料夾：common/、presets/、editor/、library/、export/、settings/
    hooks/                   React 的 composables：usePreview（只送最新一次）、useEdit、useSettings…
    domain/                  前端業務型別與純函式（依 bounded context 分檔：preset、edit、geometry、library、
                             export、settings），由舊 logic.js 移植，配單元測試
    requests/                fetch 層：client.ts（統一信封、錯誤 kind）＋每個領域一支（presets.ts、edits.ts…）
    middlewares/             request 攔截器：本機標頭（X-Darkroom）、錯誤正規化、取消過期請求
    i18n/                    i18next 設定＋locales/zh-TW.json、en-US.json
    styles/                  theme.ts（MUI theme）、_tokens.scss、global.scss
    utils/                   無業務知識的工具（格式化、debounce…）
```

- 狀態：伺服器資料用 TanStack Query；編輯中的 UI 狀態用 zustand（每個領域一個 store）。
- i18n：所有給人看的字都走 `t()`；預設語言＝設定 `language` → 瀏覽器語言 → `zh-TW`。後端錯誤句子目前是中文原句，前端照原樣顯示（v2 不翻後端句子；之後加錯誤代碼再翻）。
- 開發：`npm run dev`（5173），Vite proxy 把 `/api` 轉到 `127.0.0.1:8765`，proxy 要改寫 `Host`／`Origin` 才過得了本機檢查；`npm run build` 輸出到 `web/dist`，Python 伺服器從 `web/dist` 供應頁面。
- 功能要跟舊 `darkroom_app/static/` 完全對齊（三欄編輯、preset 搜尋／群組／最愛、強度、滑桿、HSL、A/B 對照、裁切、縮圖格、匯出對話框、匯出預設、復原／重做、快捷鍵）；對齊之後才刪舊 static。

## 3. 設定（Settings）

**檔案位置**（依序找第一個存在的；寫入時寫到同一個）：環境變數 `DARKROOM_CONFIG` → repo 根目錄 `config.local.json`（原始碼執行時）→ 平台設定資料夾（Windows `%APPDATA%\darkroom\config.json`、Linux `$XDG_CONFIG_HOME/darkroom/config.json`、macOS `~/Library/Application Support/darkroom/config.json`）。

**鍵**（全部可選；沒寫就用預設）：

| 鍵 | 型別／預設 | 生效方式 |
|---|---|---|
| `language` | `"zh-TW"`｜`"en-US"`，預設 `zh-TW` | 立即（前端切換、存檔） |
| `preset_dir`、`preset_library_dir`、`data_dir`、`localllms_root` | 路徑 | 驗證資料夾存在後立即重組 composition |
| `comfyui_url` | 預設 `http://127.0.0.1:8188`，只接受 loopback | 立即；capabilities 的 `comfyui` 重測連線 |
| `comfyui_root` | ComfyUI 安裝資料夾（可空） | 立即；檢查資料夾存在 |
| `agent.api_key_ref` | 1Password 參照 `op://…`（**絕不存金鑰本身**；替代是環境變數 `DARKROOM_ANTHROPIC_API_KEY`） | 立即；capabilities 的 `agent_sdk` 重測 |
| `agent.model` | 預設 `claude-haiku-5-5` | 立即 |
| `agent.budget_usd` | 正數，預設 5（舊鍵 `semantic_index_budget_usd` 繼續讀） | 立即 |
| `calibration_sources_dir` | 路徑 | 立即 |

舊鍵 `anthropic_api_key_ref`、`semantic_index_budget_usd` 讀的時候照樣認；寫入一律用新鍵。

**介面**（三入口都有，ADR-0001）：

| HTTP | CLI | MCP | 說明 |
|---|---|---|---|
| `GET /api/settings` | `settings get` | `darkroom_settings_get` | `{settings, defaults, sources: {鍵: "file"｜"env"｜"default"}, config_file}` |
| `PUT /api/settings` | `settings set KEY=VALUE...` | `darkroom_settings_set` | 部分更新；**全部驗證通過才寫**（原子寫入），寫完立即套用；回 `{settings, applied: [鍵], checks: {comfyui, agent_sdk, …}}` |
| `GET /api/settings/export` | `settings export [--out FILE]` | `darkroom_settings_export` | `{format: "darkroom-settings/1", version, settings}` |
| `POST /api/settings/import` | `settings import FILE` | `darkroom_settings_import` | 同 PUT 的驗證與套用；未知鍵與格式不對→invalid，整份不寫 |
| `GET /api/version` | `--version` | `darkroom_version` | `{version, python, torch, cuda, platform}` |

`capabilities` 增加 `comfyui`、`agent_sdk` 兩項（`{available, reason}`）。

## 4. 打包與發佈

```
desktop/                     Tauri 2 工作區
  src-tauri/                 Rust：視窗、啟動流程、後端子程序管理、關閉時收掉子程序
  bootstrap/                 第一次啟動的設定頁（純 HTML＋少量 JS，zh-TW／en-US），不依賴 web/
  cli/                       Rust crate `darkroom`：CLI launcher（找到受管理的 Python 環境 → 執行
                             `python -s -m darkroom_app.cli …`；`darkroom mcp` 起 MCP server；`darkroom app` 起 App）
pyproject.toml               Python 套件（版本動態讀 `darkroom_app.__version__`），CI 打 wheel 放進安裝檔
.github/workflows/ci.yml     push／PR：Python 測試（Ubuntu＋Windows，CPU 版 torch）、web lint／test／build、cargo fmt／clippy／test
.github/workflows/release.yml  推 `v*` tag：tauri-action 產 Windows .msi＋.exe、Linux .deb＋.AppImage；CLI 執行檔
                             （windows-x64 .exe、linux-x64）另外上傳到 GitHub Release
```

**啟動流程**：App 開啟 → 找受管理環境（`<app data>/runtime/`）→ 沒有就顯示 bootstrap 頁，說明要下載約 2～3 GB（Python＋CUDA 版 torch），**使用者按同意才下載**（用安裝檔附的 `uv`）→ 環境就緒後起 `python -s -m darkroom_app --port <空埠>`，等 `/api/health` 回 200 → 主視窗導向 `http://127.0.0.1:<埠>/`。只綁 127.0.0.1。
GitHub Release 單檔 2 GB 上限，所以 torch 不進安裝檔；這個限制在 Rust 渲染核心完成後消失。

## 5. Rust 遷移路線（v3 起）

逐塊替換，每塊用 Python 實作當黃金對照（同輸入、輸出差異在容許值內）：
1. `utils`（EXIF、ICC、編碼）→ Rust crate，pyo3 接回 Python；
2. 渲染核心 `darkroom/_render.py` → wgpu compute shader（WGSL），校準影像比對；
3. persist＋services → Rust；
4. HTTP／CLI／MCP 入口改由 Rust（axum）提供，Python 退場，Tauri 直接內嵌後端。
語意索引改直接打 Anthropic Messages／Batches HTTP API（Rust 沒有官方 SDK）。

## 6. 文件規劃（`docs/`）

| 檔 | 內容 |
|---|---|
| `README.md` | 只留：是什麼、截圖、功能表、下載安裝（一段）、快速開始連結、安全保證、授權。**不放架構** |
| `docs/install.md` | 安裝：安裝檔（Windows／Linux）、從原始碼、GPU／CUDA、疑難排解 |
| `docs/quick-start.md` | 5 分鐘上手：第一次啟動 → 指 preset 資料夾 → 修一張 → 匯出；CLI 與 MCP 各一個例子 |
| `docs/architecture.md` | 詳細架構：分層圖、每層職責、依賴規則、請求走一遍（預覽、匯出）、資料存在哪、前端結構、打包 |
| `docs/configuration.md` | 設定檔位置、每個鍵、三入口的設定指令 |
| `docs/development.md` | 開發環境、測試、前端 dev server、Tauri 開發、發版流程 |
| `docs/rust-evaluation.md` | 語言評估：現況熱點、Rust 生態對照、成本、路線 |
| `docs/adr/0004-*.md` | 後端長期遷移到 Rust（取代 0003） |
| `docs/agent-install.md`、`AGENTS.md` | 補設定指令、MCP 工具數、安裝檔路徑 |

## 7. 檔案所有權（v2 施工時同時開工，避免互相覆蓋）

| 誰 | 只改這些 |
|---|---|
| 後端重構 | `darkroom_app/`（不含 `static/`）、`tests/`（Python）、`.claude/contract/` 的修訂紀錄 |
| 前端 | `web/` |
| 桌面與 CI | `desktop/`、`.github/`、`pyproject.toml` |
| 整合 | 切換供應頁面到 `web/dist`、刪舊 `darkroom_app/static/` 與對應舊測試、`tools/` |
| 文件 | `README.md`、`docs/`、`AGENTS.md`、`CONTEXT.md`（領域模型）、`.claude/skills/*` 的指令更新 |
