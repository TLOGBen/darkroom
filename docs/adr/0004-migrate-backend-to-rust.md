---
status: accepted
supersedes: 0003
---

# 後端長期遷移到 Rust，逐塊替換、Python 當黃金對照

- **Status**：Accepted（2026-10-10）
- **Supersedes**：[0003 先量測，只有量到純 Python 熱點才用 Rust](0003-rust-only-after-measurement.md)

ADR-0003 說「效能上換語言沒有收益，量到純 Python 熱點才用 Rust」，這在效能上仍然成立（重活在 torch、libheif、cv2、PIL、hashlib 裡，量測沒有找到 Python 迴圈熱點）。但 v2 要做桌面安裝檔時，真正的問題變成打包與硬體：PyTorch 的 CUDA 版約 2.5 GB，超過 GitHub Release 單檔 2 GB 上限，只能讓使用者第一次開啟時同意下載約 3 GB；GPU 加速只支援 NVIDIA；Tauri 外殼還得管理一整套 Python 環境。這些都綁在 PyTorch 與 Python 執行環境上，量測再多也不會消失。

使用者 2026-10-10 的決定：**不計風險時選最推薦的方案**。最推薦的終點是單一 Rust 執行檔：渲染改 wgpu（Vulkan／DX12／Metal，各家 GPU 都能用、打開 macOS），Tauri 直接內嵌後端，安裝檔就是全部。所以後端長期遷移到 Rust。

## 怎麼走

- **逐塊替換**，順序：utils（EXIF、ICC、編碼、指紋）→ 渲染核心（`darkroom/_render.py` → WGSL compute shader）→ persist＋services → HTTP／CLI／MCP 入口（axum），Python 退場。前三塊用 pyo3＋maturin 接回 Python。
- **Python 實作當黃金對照**：同樣的輸入，兩邊輸出差異在合約寫定的容許值內才切換；切換前預設仍走 Python，出事可以切回去。現有的 Python 測試（三入口一致性、HTTP 黃金測試、寫檔守門）就是驗收工具。
- **入口合約不變**（ADR-0001）：HTTP 路由、CLI 子指令與結束碼、MCP 工具名與 schema、錯誤句子都不因換實作而改，v2 先把它們整理乾淨正是為了這個。
- 語意索引改直接打 Anthropic Messages／Message Batches HTTP API（沒有官方 Rust SDK）。
- v2 這一輪只寫 Rust 的外殼（Tauri）與 CLI 執行檔；遷移從 v3 開始。

各階段的換法、Rust 套件對照、驗收方式與成本在 [`docs/rust-evaluation.md`](../rust-evaluation.md)。

## Considered Options

- **維持 0003（Python 為主，量到熱點才換）**：風險最低、工作量最小，但打包 3 GB 與只支援 NVIDIA 的問題永遠在。
- **只把渲染核心換成 Rust＋wgpu，其餘留 Python**：解決硬體問題，但 Python 執行環境還在，安裝檔仍要帶或下載 Python，Tauri 仍要管子程序。
- **一次重寫**：沒有黃金對照可以逐塊驗，顏色差異與規則遺漏很難抓。

## Consequences

- 遷移期間兩套實作並存；改到正在遷移的那一塊時，兩邊要一起改或先凍結功能。
- CI 多一套 pyo3／maturin 建置；HEIC 仍需要 C 的 libheif（`libheif-rs`），授權與打包要處理。
- 打包痛點在第 2 階段（渲染核心）完成後開始消失，第 4 階段完成後完全消失；在那之前桌面版仍是「第一次開啟時下載 Python＋PyTorch」。
- 新功能優先寫在已經分好層的 service 裡，讓之後的搬遷單位清楚（ADR-0005 的 context 就是搬遷的切口）。
