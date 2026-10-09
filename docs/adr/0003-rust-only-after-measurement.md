# 先量測，只有量到純 Python 熱點才用 Rust

darkroom 的重活已經在原生程式或 GPU 上（torch 渲染、libheif、cv2／PIL 編解碼、hashlib），換語言幾乎沒有收益；批次的瓶頸靠「讀檔 → GPU → 編碼」三段管線平行解決（這些 C 函式庫會放開 GIL）。所以效能目標寫成合約裡的數字（批次匯出、縮圖格），達不到才 profile；確認卡在無法向量化、也沒有現成 C 函式庫可用的 Python 迴圈時，才開切片用 pyo3＋maturin 把那個 service 換成 Rust 實作（使用者 2026-10-09 同意）。
