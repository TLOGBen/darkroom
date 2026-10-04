# ① App 的執行環境與啟動

Type: grilling
Status: resolved

## Question

① 開工前要先定：App 用哪個 Python（這台單一連線很慢，pip 直接下載 torch 約 3GB 可能要好幾小時；ComfyUI 可攜版的 Python 已有 torch 2.14+cu130、OpenCV、numpy），以及怎麼啟動（LocalLLMs 的操作台啟動時會停掉其他模型，但 App 本身只佔少量 VRAM、又要視需要呼叫 llama-server 與 ComfyUI）。

## Answer

**使用者決定（2026-10-04）：**
- **Python：複製 ComfyUI 可攜版的 `python_embeded` 當 darkroom 專用的一份**（約 5GB，放 `C:/Users/powde/workspace/LocalLLMs/runtimes/darkroom-python/<版本>/`；LocalLLMs 的 `runtimes/` 不進 git）。不用下載、torch 現成；之後 darkroom 裝套件不影響 ComfyUI；符合 LocalLLMs「Python 執行程式用專用 CPython、不用 venv」的規則（venv 的 python.exe 只是啟動器，停止時會留孤兒）。裝套件照 LocalLLMs 慣例把現有套件當 constraints，避免動到 torch／numpy／opencv。注意：可攜版 Python 原本缺 `Include/Python.h` 與 `libs/`，ComfyUI 那份已從官方 CPython 3.13.14 NuGet 補過（見 LocalLLMs `projects/comfyui/NOTES.md`），複製時一併帶過來。
- **啟動：darkroom 自己的啟動捷徑**（repo 裡的 pwsh 啟動檔＋本機捷徑，不進 git），**不加進 LocalLLMs 的操作台**（選項：加進操作台但不踢掉其他程式）。
- **GPU 協調（實作時照做）**：App 本身只佔少量 VRAM；要用 PE（llama-server）或 Qwen／SeedVR2（ComfyUI）時由 App 自己處理——先查 LocalLLMs 操作台狀態（`launcher.ps1 -Status`）與 GPU 用量，不要打斷使用者正在跑的工作；llama-server 用完即關（同 `ComfyUI-LlamaServer-PE` 的做法）；NVIDIA「偏好最高效能」設定改設在這份專用的 python.exe。
