# 後端語言評估：留在 Python，還是遷移到 Rust

> 2026-10-10 寫。結論與決定記在 [ADR-0004](adr/0004-migrate-backend-to-rust.md)（取代 [ADR-0003](adr/0003-rust-only-after-measurement.md)）。
> 下面的 Rust 套件對照是撰寫時的認知，**進入每個階段前要先確認版本與功能**（特別是「編碼器支不支援某個選項」這類細節）。

## 1. 結論

- **效能不是換語言的理由。** 重活本來就在原生程式或 GPU 上，Python 只是膠水；現有的速度已經達標（見 §2）。ADR-0003 的判斷在效能上仍然成立。
- **打包與硬體才是。** 現在的安裝方式要使用者第一次開啟時下載約 3 GB（Python＋CUDA 版 PyTorch），而且 GPU 加速只支援 NVIDIA；這兩件事都卡在 PyTorch，換掉渲染核心才會消失。
- 使用者 2026-10-10 的決定：**不計風險時選最推薦的方案**——長期把後端遷移到 Rust，用「逐塊替換、Python 當黃金對照」的方式走（§5）。v2 這一輪只做 Rust 外殼（Tauri）與 CLI 執行檔，Python 後端整理好分層，讓之後換實作時入口不用動。

## 2. 現況：重活在哪裡

| 熱點 | 現在用什麼 | 在哪 | 量到的數字 |
|---|---|---|---|
| 調色渲染（曝光、對比、亮部陰影、HSL、色彩分級、曲線、漸層遮罩、清晰度／紋理／去朦朧的近似） | PyTorch（CUDA，float32） | `darkroom/_render.py`（715 行）、`adapters/gpu/engine.py` | 1.5MP 預覽 15～20 ms；拉直拖動中位數 24.7 ms；裁切後第一張清楚的預覽 65 ms |
| 讀檔 | Pillow、tifffile（16-bit TIFF）、pillow-heif（libheif，HEIC 10-bit） | `darkroom/_io.py`、`_heif.py` | — |
| 色彩管理 | 自己寫的 ICC 解析與轉換（Display P3 → sRGB） | `darkroom/_icc.py`（205 行） | — |
| 縮放、模糊、預覽 JPEG 編碼 | OpenCV（cv2） | engine、export、imaging | — |
| 匯出編碼（JPEG／PNG／TIFF／WebP、EXIF、嵌 ICC、檔案大小上限的二分搜尋） | Pillow、cv2、tifffile＋自己組的 EXIF／ICC 區段 | `darkroom_app/utils/encoding.py`（409 行） | 24MP 匯出 0.424 秒／張（讀檔、GPU、編碼三段重疊） |
| 照片指紋 | hashlib SHA-256 | `utils/imaging.py` | 500 張暖縮圖格 0.52 秒（有索引時不重算） |
| xmp 解析 | expat／ElementTree | `darkroom/_xmp.py` | — |
| HTTP、CLI、MCP | aiohttp、argparse、手寫 JSON-RPC | `darkroom_app/adapters/` | — |
| 語意索引 | anthropic SDK（Message Batches） | `services/semantic_index.py` | — |

這些 C 函式庫與 CUDA kernel 在工作時都會放開 GIL，三段管線已經讓 CPU 與 GPU 重疊；量測沒有找到「卡在純 Python 迴圈」的熱點。程式規模：核心函式庫約 2,200 行、App 約 9,200 行（含相容 shim），Python 測試 552 個。

## 3. 打包的痛點

| 痛點 | 為什麼 | 換成 Rust 之後 |
|---|---|---|
| **第一次要下載約 3 GB** | PyTorch 的 CUDA 版約 2.5 GB，加上 Python 與相依套件 | 渲染改 wgpu 後不需要 PyTorch；整個後端是一個執行檔，安裝檔預估幾十 MB（未量測） |
| **安裝檔裝不下 torch** | GitHub Release 單檔上限 2 GB，所以 torch 只能第一次開啟時才下載（要網路、要使用者同意） | 限制消失，安裝檔就是全部 |
| **GPU 只支援 NVIDIA** | 用的是 CUDA 版 PyTorch；AMD、Intel、Apple Silicon 只能走 CPU（慢很多） | wgpu 跑 Vulkan／DX12／Metal，各家顯示卡都能用 GPU，也打開 macOS |
| **兩套執行環境** | Tauri（Rust）外殼要管理一套 Python venv：uv、標記檔、版本對齊、子程序 | Tauri 直接內嵌後端，沒有子程序、沒有受管理環境 |
| **原生函式庫散在 wheel 裡** | libheif、OpenCV、libjpeg 各自隨 Python 套件來，版本由 pip 決定 | 由 Cargo 鎖定（仍有部分是 C 函式庫的綁定，見 §4） |

## 4. Rust 生態對照

| 現在 | Rust 候選 | 注意 |
|---|---|---|
| PyTorch 渲染 | **wgpu**＋WGSL compute shader | 最大的一塊。逐像素的運算（曝光、曲線、HSL、色彩分級）直接對應；清晰度／紋理／去朦朧的近似需要多階段模糊，要自己寫成多個 pass；float32 精度跟 torch 一致才比得了黃金對照 |
| cv2 縮放（INTER_AREA）、高斯模糊 | `fast_image_resize`、自己寫在 shader 裡 | INTER_AREA 的結果要逐像素對過 |
| JPEG 解碼 | `zune-jpeg`（純 Rust、快）或 `image` | EXIF 方向、CMYK、漸進式都要測 |
| JPEG 編碼 | `jpeg-encoder`（純 Rust）或 `turbojpeg`／`mozjpeg`（C 綁定） | 要能嵌 ICC、寫 APP1（EXIF）；「檔案大小上限」靠反覆編碼的二分搜尋，編碼速度直接影響匯出 |
| PNG／TIFF（含 16-bit） | `image`、`png`、`tiff` | 16-bit TIFF 與嵌 ICC 要確認 |
| WebP | `image`（只有無失真）、`webp`（libwebp 綁定，有失真） | 現在的 WebP 匯出有品質參數，需要有失真編碼 → 用 libwebp 綁定 |
| HEIC（pillow-heif） | **`libheif-rs`** | 仍是 C 的 libheif（加上它的解碼器），打包時要一起帶；授權（LGPL 等）要確認 |
| ICC 轉換（自己寫） | **`lcms2`**（Little CMS 綁定）或純 Rust 的 `moxcms` | 現有的轉換是自己寫的，換之前先用它當對照 |
| EXIF 讀 | **`kamadak-exif`** | 只能讀。寫入（篩選中繼資料、拿掉 GPS）現在就是自己組區段，照搬成 Rust |
| SHA-256 | `sha2` | 結果要跟 hashlib 逐位元組相同（指紋是照片庫的 key） |
| xmp 解析 | `quick-xml` | — |
| aiohttp | **`axum`**（tokio） | 本機檢查的中介層、路由、503 頁面照搬；HTTP 黃金測試直接拿來驗 |
| argparse | `clap` | 結束碼、`--json` 信封、錯誤句子逐字一致 |
| MCP（手寫 JSON-RPC） | 照搬手寫版本，或評估官方 Rust SDK `rmcp` | 工具清單（名稱、schema、annotations、順序）要逐位元組相同 |
| anthropic SDK | `reqwest` 直接打 Messages／Message Batches HTTP API | **Anthropic 沒有官方 Rust SDK**；請求格式、重試、批次輪詢自己寫 |
| 1Password（`op read`） | `std::process::Command` | 一樣是呼叫 `op`，金鑰只放記憶體 |
| 跨程序鎖、原子取代 | `fs4`／`fd-lock`、`tempfile`＋`rename` | Windows 上的 `PermissionError` 重試規則要照搬 |

過渡期用 **pyo3＋maturin** 把 Rust crate 接回 Python，所以每一塊都能先在現有的 Python 測試底下跑。

## 5. 四階段路線（v3 起）

每一階段的原則：**Python 實作留著當黃金對照**——同樣的輸入，兩邊的輸出差異在容許值內才算完成；完成前預設仍走 Python，切換用一個開關，出事可以立刻切回去。

| 階段 | 換什麼 | 怎麼接 | 驗收 |
|---|---|---|---|
| 1. utils | EXIF、ICC、編碼（JPEG／PNG／TIFF／WebP）、指紋 → Rust crate | pyo3 包成 Python 模組，`utils/encoding.py`、`imaging.py` 改呼叫它 | 指紋與 hashlib 逐位元組相同；PNG／TIFF 解碼後逐像素相同、EXIF 與 ICC 區段逐位元組相同；JPEG 解碼後與 Python 版的差異在容許值內（例如 PSNR ≥ 45 dB，數值在開工合約裡定）；整套 Python 測試在 Rust 實作下全過；`bench_export`、`bench_photo_library` 不變慢 |
| 2. 渲染核心 | `darkroom/_render.py` → wgpu compute shader（WGSL） | 先以 pyo3 接回 `Engine`，torch 與 wgpu 並存可切換 | 黃金集＝4 張校準標準圖＋測試影像 ×（全部 1,466 個 preset 在強度 0／50／100／200）＋逐一滑桿掃描；與 torch float32 的輸出比較：8-bit sRGB 下 99.9% 的像素差 ≤ 1、最大差 ≤ 3、平均 ΔE00 ≤ 0.5（提案值，在開工合約裡定）；預覽延遲不輸給 torch（1.5MP 15～20 ms）；在 AMD／Intel 顯示卡上能跑 |
| 3. persist＋services | 檔案儲存與業務規則 → Rust | facade 背後換成 Rust 實作（pyo3），入口仍是 Python | 所有檔案格式雙向相容（Python 寫的 Rust 讀得懂，反過來也是）：`library.json`、編輯、縮圖索引、`export-presets.json`、`semantic.json`、設定檔；整套 Python 測試（含三入口一致性、寫檔守門）對 Rust 實作全過 |
| 4. 入口 | HTTP／CLI／MCP → Rust（axum、clap、MCP） | Tauri 直接內嵌後端；Python 退場 | `test_http_golden` 的每個請求回應相同；CLI 的 `--json` 信封、結束碼、錯誤句子逐字相同；MCP `tools/list` 逐位元組相同；安裝檔不再下載 PyTorch；寫檔守門的保證（只建新檔、不碰照片與 preset）以 Rust 測試重新釘死 |

語意索引在第 3 或第 4 階段改成直接打 Anthropic HTTP API（Messages＋Message Batches）。

順序的理由：先換最小、最好對照的 utils，把 pyo3 管線與黃金對照的流程跑通；渲染核心是收益最大（打包與硬體）也最難的一塊，放第二；service 與入口的規則多但都有現成的測試釘著，最後搬。

## 6. 成本

粗估、沒有量測依據，進入每階段前在開工合約裡重估：

| 階段 | 相對大小 | 主要工作 |
|---|---|---|
| 1. utils | 小 | 編碼器選型、EXIF／ICC 照搬、pyo3 管線、CI 加 maturin |
| 2. 渲染核心 | **大** | 715 行 tensor 運算改成 WGSL、多 pass 模糊、精度對齊、各家 GPU 驗證、校準比對工具 |
| 3. persist＋services | 中～大 | 約 5,000 行規則與錯誤句子照搬、檔案相容、跨程序鎖 |
| 4. 入口 | 中 | 路由、CLI、MCP 照搬；Tauri 內嵌；打包流程改寫 |

另外的長期成本：遷移期間兩套實作並存（改功能要改兩邊，或先凍結該塊的功能）；CI 多一套 Rust 建置；HEIC 仍要帶 C 函式庫。

## 7. 風險（決定時已知，使用者選擇不以風險為優先）

- 渲染結果對不齊：近似算法本來就是擬合出來的，換一套實作可能讓顏色微妙地不同。→ 黃金對照的容許值寫進合約，對不齊就不切換。
- wgpu 與各家驅動的相容性問題。→ 保留 CPU 退路（wgpu 的軟體後端或 Rust CPU 實作）。
- 工作量大、時程長，期間功能開發變慢。→ 逐塊替換，每塊都能獨立停在「Python 仍是預設」的狀態。
- 第 4 階段之前，Python 後端與 PyTorch 下載都還在，打包的痛點要到渲染核心（第 2 階段）完成後才開始消失、到第 4 階段才完全消失。
