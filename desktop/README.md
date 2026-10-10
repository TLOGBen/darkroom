# desktop/ — darkroom 桌面外殼與 CLI 執行檔

Tauri 2 的 Cargo workspace（施工依據：`docs/architecture/plan-v2.md` §4）。

| 路徑 | 是什麼 |
|---|---|
| `src-tauri/` | 桌面 App（crate `darkroom-desktop`）：主視窗先顯示 `bootstrap/`；檢查受管理的 Python 環境、使用者同意後用附帶的 `uv` 安裝、起 `python -s -m darkroom_app --port <空埠>`（只綁 127.0.0.1）、等 `/api/health` 成功後把視窗導向編輯器；App 關閉時收掉子程序 |
| `bootstrap/` | 第一次啟動的設定頁：純 HTML／CSS／JS，zh-TW／en-US 依系統語言，不依賴 `web/` |
| `cli/` | CLI 執行檔（crate `darkroom-cli`，產出 `darkroom`／`darkroom.exe`）：找到環境後原樣轉給 `python -s -m darkroom_app.cli` |
| `scripts/sync-version.mjs` | 把 `darkroom_app/__init__.py` 的 `__version__` 寫進 `tauri.conf.json` 與兩個 `Cargo.toml`（`--check` 只檢查） |
| `scripts/hatch_build.py` | `pyproject.toml` 用的 hatchling hook：`web/dist` 存在時放進 wheel 的 `darkroom_app/web_dist/` |

## 受管理環境放哪

`<app_local_data_dir>/runtime/`，`app_local_data_dir` 是 Tauri 的本機資料夾＋識別碼 `io.github.tlogben.darkroom`：

- Windows：`%LOCALAPPDATA%\io.github.tlogben.darkroom\runtime\`
- Linux：`$XDG_DATA_HOME/io.github.tlogben.darkroom/runtime/`（沒設就是 `~/.local/share/...`）

同一個資料夾裡還有 `uv/python/`（uv 下載的 Python）、`uv/cache/`（下載快取，取消後再裝會接著用）、`logs/backend.log`。
`runtime/darkroom-runtime.json` 是安裝全部成功後才寫的標記；沒有它就當作沒裝好。整個資料夾刪掉＝回到第一次啟動。
CLI 執行檔用同一個規則找；也可以用環境變數 `DARKROOM_PYTHON` 指定任何能 `import darkroom_app` 的直譯器。

## 開發

```powershell
cd desktop
npm ci                                   # 只裝釘住版本的 @tauri-apps/cli
cargo fmt --all --check; cargo clippy --workspace --all-targets -- -D warnings; cargo test --workspace

# 用現成的 Python 跑桌面 App（跳過下載；debug 版會在 repo 根目錄執行它）
$env:DARKROOM_PYTHON = "<能 import darkroom_app 的 python.exe>"
npx tauri dev

# CLI 執行檔
cargo build -p darkroom-cli
.\target\debug\darkroom.exe --version
```

開發時沒有 sidecar：`uv` 依序找 `DARKROOM_UV` → 執行檔旁邊的 `uv` → PATH 上的 `uv`；
darkroom wheel 依序找 `DARKROOM_WHEEL` → 安裝檔資源 `wheels/*.whl` → （只有 debug 版）repo 根目錄原始碼。

## 打包（CI 的 release.yml 做的事）

`tauri.bundle.conf.json` 只在打包時用 `--config` 疊上去：它加入 `externalBin`（`binaries/uv-<target triple>[.exe]`）與
`resources`（`resources/wheels/` 裡的 darkroom wheel）。不放進 `tauri.conf.json` 是因為 tauri-build 在檔案不存在時
連 `cargo build`／`clippy` 都會失敗。

```powershell
node desktop/scripts/sync-version.mjs
# 準備 desktop/src-tauri/binaries/uv-x86_64-pc-windows-msvc.exe 與 desktop/src-tauri/resources/wheels/darkroom-*.whl
cd desktop; npx tauri build --config src-tauri/tauri.bundle.conf.json --bundles msi,nsis
```

圖示由 `docs/assets/logo.svg` 產生：`npx tauri icon ../docs/assets/logo.svg -o src-tauri/icons`
（之後刪掉 `android/`、`ios/`、`Square*.png`、`StoreLogo.png`、`64x64.png`，桌面版用不到）。
