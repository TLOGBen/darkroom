# ① 載體：放在 ComfyUI，還是做成獨立的本機修圖 App？

Type: grilling
Status: resolved

## Question

已定的「① 跟萬事通的關係？」假設載體是 ComfyUI（單一節點＋「9 相片編輯」入口）。使用者在 AI 補強實驗後指出：AI 重畫若第一版不做，核心只剩程式調色與 LLM 給數值，ComfyUI 串接 AI 模型的強項用不到。要定：載體選 ComfyUI 節點、獨立本機 App（例如 Python 後端＋Web 前端，直接呼叫 llama-server、需要時才呼叫 ComfyUI 跑 Qwen／SeedVR2）、或兩者（核心做成函式庫，App 與 ComfyUI 節點都包它）。答案可能改寫「① 跟萬事通的關係？」、介面草圖的 B 版設計、預覽路由（目前假設掛在 ComfyUI 的伺服器上）。依據：研究「別人的 AI 修圖都怎麼做？」。

## Answer

**使用者決定（2026-10-04）：核心做成函式庫，主介面是獨立的本機修圖 App；ComfyUI 只當擴散模型的後端**（選項 A；另兩個是維持 ComfyUI 節點、兩者第一版並重）。
- **核心函式庫**：版本化的參數 JSON schema（欄位用 xmp 的 crs 鍵名）＋torch GPU 渲染（程式調色、漸層遮罩、近似演算法）；讀寫 16-bit、保留 ICC 與 EXIF。
- **App**：Python 後端＋Web 前端（介面照「① 節點介面長怎樣？」的全螢幕三欄編輯器），預覽路由沿用「① 預覽速度原型」的做法（HTTP POST＋最新一次優先、cv2 編碼），改掛在 App 自己的伺服器上；直接呼叫 llama-server（② 的 PE-I2I）。
- **ComfyUI 的角色**：只在需要擴散模型時透過它的 API 呼叫（Qwen 移除／重畫、SeedVR2 放大），前例 RapidRAW、Krita AI Diffusion；ComfyUI 節點（包同一個函式庫）列為選配、後做。
- **依據**：研究「別人的 AI 修圖都怎麼做？」——ComfyUI 核心讀寫 8-bit、不處理 ICC／EXIF（原始碼已查）、介面是按執行排隊；商業產品沒有用排隊流程修圖。
- **連帶修改**：「① 跟萬事通的關係？」的「單一節點＋9 相片編輯 workflow」作廢（改為 App；萬事通仍不改）；「① 節點介面長怎樣？」的全螢幕編輯器變成 App 主畫面，B 版小節點只在之後做 ComfyUI 節點時才用；「① 預覽速度原型」的閒置降頻設定（NVIDIA「偏好最高效能」）改設在 App 用的 python.exe。

