---
status: superseded
superseded-by: 0004
---

> **Superseded by [0004](0004-migrate-backend-to-rust.md)**（2026-10-10）：理由不是本文的判斷錯了——效能上它仍然成立——而是決定的依據從「效能」換成「打包與硬體相容性」，見 0004 與 `docs/rust-evaluation.md`。下面保留原文。

# 先量測，只有量到純 Python 熱點才用 Rust

darkroom 的重活已經在原生程式或 GPU 上（torch 渲染、libheif、cv2／PIL 編解碼、hashlib），換語言幾乎沒有收益；批次的瓶頸靠「讀檔 → GPU → 編碼」三段管線平行解決（這些 C 函式庫會放開 GIL）。所以效能目標寫成合約裡的數字（批次匯出、縮圖格），達不到才 profile；確認卡在無法向量化、也沒有現成 C 函式庫可用的 Python 迴圈時，才開切片用 pyo3＋maturin 把那個 service 換成 Rust 實作（使用者 2026-10-09 同意）。
