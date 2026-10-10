# 開發

給要改 darkroom 程式的人。架構先看 [architecture.md](architecture.md)，用詞看 [CONTEXT.md](../CONTEXT.md)，每個功能的驗收合約在 [`.claude/contract/`](../.claude/contract/)。

## 開發環境

| 工具 | 版本 | 用在哪 |
|---|---|---|
| Python | 3.13 | 後端（`darkroom/`、`darkroom_app/`）與測試 |
| PyTorch | 2.14.0（CUDA 13.0 版；沒 NVIDIA 用 CPU 版） | 渲染 |
| Node.js／npm | 22 以上 | `web/` 前端、`desktop/` 的 Tauri CLI、`sync-version.mjs` |
| Rust（stable）＋cargo | — | `desktop/`（Tauri 外殼、CLI 執行檔） |
| uv | 選用 | 打 wheel（`uv build --wheel`）；桌面 App 開發時當安裝工具 |

Python 環境照 [安裝說明：從原始碼](install.md#二從原始碼) 建好（`.venv`）。下面的 `python` 一律指那個環境的直譯器，加 `-s`，在 repo 根目錄執行。

Windows 的腳本一律用 PowerShell 7（`pwsh`），不寫 `.cmd`／`.bat`；commit 訊息用 conventional commits（`feat:`、`fix:`、`docs:`、`chore:`…）。

## 測試

```powershell
# Python（後端＋核心函式庫）：幾分鐘；GPU 忙碌時計時類測試會自動跳過
python -s -m unittest discover -s tests

# web（在 web/ 裡）
cd web
npm ci
npm run lint
npm run typecheck
npm test            # vitest
npm run build       # 輸出 web/dist
cd ..

# desktop（在 desktop/ 裡）
cd desktop
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cd ..
```

CI（`.github/workflows/ci.yml`）每次 push／PR 跑同樣三組：Python 在 Ubuntu＋Windows（CPU 版 torch，沒有 GPU 的路徑會改用 CPU 或自己跳過）並試打一次 wheel；web 的 lint／typecheck／test／build；Rust 的版本同步檢查、fmt、clippy、test。

測試的守則：

- **寫檔守門**：Python 測試全程掛 audit hook（`tests/_writeguard.py`），寫到宣告範圍以外就失敗；測試一律用暫存的 `data_dir`、暫存的設定檔（`DARKROOM_CONFIG`），不碰 repo 的 `config.local.json`。
- **伺服器測試用固定頁面**：`tests/_util.py` 把 `DARKROOM_WEB_DIST` 指到 `tests/web_dist_fixture/`，有沒有跑過 `npm run build` 結果都一樣。
- **分層規則是測試**：`tests/test_layering.py`（依賴方向、入口不放規則、facade 只轉呼叫、只有 `safe_write` 寫檔、文件寫的 MCP 工具數）；三入口一致性在 `tests/test_interface_parity.py`。
- 文件裡寫的 MCP 工具數（README、AGENTS.md、agent-install.md、CLAUDE.md）由 `test_docs_tool_count` 對照 `operations.py`，新增操作時記得一起改。

效能量測（不是單元測試；GPU 忙碌時自動跳過，`--force` 強制量）：

```powershell
python -s tools/bench_preview.py          # 預覽延遲（--with-thumbnails、--geometry）
python -s tools/bench_export.py           # 批次匯出（--s2、--s3）
python -s tools/bench_photo_library.py    # 縮圖、縮圖格、指紋（不用 GPU）
python -s tools/bench_preset_library.py   # preset 庫
```

## 前端開發伺服器

先開後端，再開 Vite：

```powershell
python -s -m darkroom_app --port 8765
cd web; npm run dev                         # http://127.0.0.1:5173/
```

Vite 把 `/api` proxy 到 `127.0.0.1:8765`（後端在別的埠就設 `DARKROOM_PORT`），並改寫 `Origin`、拿掉 `Sec-Fetch-Site`／`Referer`，讓後端的本機檢查放行。5173 被 Windows 保留時用 `DARKROOM_WEB_PORT` 換埠。改完要給 Python 伺服器供應就 `npm run build`。

前端的規矩（細節在 [`web/DESIGN.md`](../web/DESIGN.md)）：給人看的字全部走 `t()`，`zh-TW.json` 與 `en-US.json` 的鍵要一致（有測試）；所有請求經 `requests/client.ts`；純規則寫在 `domain/` 並配測試。

## 桌面 App（Tauri）開發

```powershell
cd desktop
npm ci                                       # 只裝釘住版本的 @tauri-apps/cli
$env:DARKROOM_PYTHON = "<能 import darkroom_app 的 python.exe>"   # 跳過下載，直接用現成的環境
npx tauri dev

cargo build -p darkroom-cli                  # CLI 執行檔
.\target\debug\darkroom.exe --version
```

開發時沒有 sidecar：`uv` 依序找 `DARKROOM_UV` → 執行檔旁邊的 `uv` → PATH；darkroom wheel 依序找 `DARKROOM_WHEEL` → 安裝檔資源 `wheels/*.whl` → （只有 debug 版）repo 根目錄的原始碼。細節在 [`desktop/README.md`](../desktop/README.md)。

## 打 wheel

```powershell
cd web; npm run build; cd ..     # 有 web/dist 時會被放進 wheel 的 darkroom_app/web_dist/
uv build --wheel                 # 或 python -m build --wheel；輸出 dist/darkroom-<版本>-py3-none-any.whl
```

wheel 同時包 `darkroom` 與 `darkroom_app`，沒有 console script（`darkroom` 指令是 Rust 的 CLI 執行檔）；torch 不列依賴，`heic`、`semantic` 是選用 extras。

## 發版

版本號只有一個來源：`darkroom_app/__init__.py` 的 `__version__`（`MAJOR.MINOR.PATCH`，只能是數字，MSI 要求）。

1. 改 `darkroom_app/__init__.py` 的 `__version__`，例如 `"0.2.0"`。
2. 同步到桌面的檔案，並確認一致：

   ```powershell
   node desktop/scripts/sync-version.mjs          # 改 tauri.conf.json 與兩個 Cargo.toml
   node desktop/scripts/sync-version.mjs --check  # 三個都印 (ok)
   ```

3. 跑一次完整測試（上面三組），commit（`chore: release 0.2.0`），推到 `main`。
4. 打 tag 並推上去（tag 必須是 `v` 加上 `__version__`）：

   ```powershell
   git tag v0.2.0
   git push origin v0.2.0
   ```

5. `.github/workflows/release.yml` 會：
   - 先確認 tag 等於 `__version__`，不一致就整個失敗；建立 **draft** release。
   - Windows 與 Ubuntu 22.04 各自：同步版本 → 建 `web/dist` → 打 wheel → 下載 uv（SHA-256 寫死在 workflow 裡驗證）當 sidecar → `tauri-action` 產出 `.msi`＋NSIS `-setup.exe`／`.deb`＋`.AppImage` 並上傳。
   - 另外 build CLI 執行檔，上傳 `darkroom-<版本>-windows-x64.exe` 與 `darkroom-<版本>-linux-x64.tar.gz`。
6. 到 GitHub 的 Releases 檢查 draft 的檔案，沒問題再按 Publish。

## 路線圖

1. ✅ **第一版（alpha）**：核心函式庫、App、HEIC、三入口分層、匯出（多格式、縮小、中繼資料、匯出預設）、preset 庫（含 `.xmp` 匯出與語意搜尋）、照片庫、A/B 對照與還原、裁切／拉直／旋轉／鏡像、能力偵測
2. ✅ **v2**：後端分層（adapters／facade／services／domain／utils）、React＋MUI 前端（zh-TW／en-US）、設定頁與設定 API、Tauri 桌面安裝檔與 `darkroom` CLI 執行檔
3. ⏳ **校正**：用 Lightroom 試用版渲染單一滑桿掃描，把亮部／陰影／白／黑擬合到更接近 Lightroom
4. **AI 助理**（Claude）：一句話修圖、批次處理、選片、preset 推薦
5. **後端逐塊遷移到 Rust**（v3 起，[ADR-0004](adr/0004-migrate-backend-to-rust.md)、[語言評估](rust-evaluation.md)）：不再綁 NVIDIA／PyTorch，macOS 也能用 GPU
6. **RAW**、**AI 修圖建議**（本機視覺模型給滑桿數值）、**AI 遮罩**（主體／天空／人物）、**自動修圖**（去雜物、美顏、放大）

完整的決定紀錄在 [`.claude/wayfinder/darkroom/map.md`](../.claude/wayfinder/darkroom/map.md)。
