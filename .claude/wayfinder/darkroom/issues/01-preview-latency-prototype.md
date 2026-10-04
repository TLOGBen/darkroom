# ① 預覽速度原型：後端 GPU 預覽一次往返能不能在約 0.1 秒內？

Type: task
Status: resolved

## Question

拖動滑桿要即時（使用者選）。做一個最小原型量實際延遲：ComfyUI 自訂路由收參數 → torch 在 GPU 上對約 1.5MP 的縮小圖套一組代表性運算（曝光、曲線、HSL、局部反差）→ 編成 JPEG 傳回瀏覽器；量從送出到畫面更新的時間（p50／p95），同時跑著 ComfyUI 其他模型閒置時的情況。結果決定預覽在後端算（計畫的做法）還是改瀏覽器 WebGL。AFK：代理可以自己做完並回報數字。


（2026-10-04：研究「① 未公開演算法…」量到全部運算 1.5MP 約 15 ms，運算本身不是瓶頸；這張要量的是傳輸、JPEG 編碼與瀏覽器更新的整趟往返。）

## Answer

（2026-10-04，執行子代理；原型與重跑方式在 [prototypes/preview-latency/](../prototypes/preview-latency/)。主 session 驗收：custom_nodes 複本已刪、測試輸出已清、`git status` 無其他改動。測試圖 1013×1481（1.5MP，由 24MP 縮出），JPEG q85。）

**賭注成立：連續拖動遠低於 100 ms。** 往返 p50 24～29 ms、p95 28～34 ms；滑桿動到畫面更新 p50 29～37 ms、p95 39～45 ms；38～54 fps。運算約 15～19 ms（伺服器微基準整套 15.1～15.8 ms），傳輸約 2 ms、瀏覽器解碼約 4 ms。ComfyUI 載著大模型（VRAM 13.6GB）時一樣快。→ **預覽在後端算（計畫的做法）確定，不需要改瀏覽器 WebGL 當主要路徑。**

實作要照的寫法：
- **專用的高優先 CUDA stream、只同步自己那條**，不要 `torch.cuda.synchronize()`：ComfyUI 正在取樣時，舊寫法每張預覽要等一個取樣步（約 1.7 秒）；專用 stream 可達 16.7 fps、延遲 p50 40 ms、p95 98 ms，代價是出圖每步慢約 12%（1.71 → 1.91 秒，停手即恢復）。
- **JPEG 用 CPU 的 cv2 編碼**（2.5～3 ms、0 張壞）；GPU nvjpeg 在 GPU 忙時卡 400～830 ms 且吐壞檔，目前這套 torch 2.14／torchvision 0.29 上不安全。
- **HTTP POST＋「最新一次優先」**即可；WebSocket 沒有比較快（本機多 2～3 ms）。
- GPU 工作放在單一執行緒 executor，不卡 aiohttp 事件迴圈。
- 運算受 kernel 啟動開銷限制（像素數影響小：0.75MP 14 ms、3MP 24 ms）；CUDA graph／`torch.compile` 合併 local Laplacian 小 kernel 可再省幾 ms（CUDA graph 錄製要先把參數改成預先放好的 GPU tensor）。

**已知的例外：閒置後的第一次點擊** p50 50～130 ms、p95 110～300 ms，原因是 GPU 閒置 0.5 秒以上就降頻（P5／P8，210～675 MHz；連續工作時 2655 MHz、P2），約 5 張內恢復。軟體對策（背景 keep-alive、點擊前暖身、懸停暖身）都不穩。可靠的兩條路：(a) NVIDIA 控制台把 ComfyUI 的 `python.exe` 設成「偏好最高效能」——驅動設定，依 CLAUDE.md 要問使用者；(b) 前端先用 WebGL 做便宜近似（曝光、白平衡、曲線、HSL）立刻顯示，再用後端結果覆蓋。選哪條見 Comments。


## Comments

（2026-10-04）**使用者決定閒置後第一下的處理：選 A——在 NVIDIA 控制台把 ComfyUI 的 `python.exe`（`runtimes/comfyui/<版本>/ComfyUI_windows_portable/python_embeded/python.exe`）設成「電源管理模式：偏好最高效能」**（另兩個選項：前端 WebGL 簡化版預覽、不處理）。驅動設定由使用者在實作階段照步驟清單自己操作（管理 3D 設定 → 程式設定 → 加入該 python.exe → 電源管理模式），做完重跑原型的單次點擊測試確認；換新版可攜版時路徑會變，要重設。若效果不夠再考慮 WebGL 簡化版。

（2026-10-04）載體改為獨立 App：預覽路由改掛在 App 自己的伺服器上，量到的做法（HTTP POST＋最新一次優先、cv2 編碼、單一執行緒 executor）照用；「專用高優先 CUDA stream」在 ComfyUI 同時出圖時仍需要（兩個程序共用 GPU）；NVIDIA「偏好最高效能」改設在 App 的 python.exe。
