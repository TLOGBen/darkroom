# ③ 美顏、身形需要哪些模型？

Type: research
Status: resolved

## Question

美顏（磨皮、亮眼、白牙、去斑，滑桿調強度）要找出臉、五官、皮膚範圍；身形（瘦腰、拉腿長，液化變形，滑桿調強度）要身體各部位的位置。查：臉部分割／關鍵點模型的候選（授權、大小、ComfyUI 有沒有現成節點、Windows＋torch 2.14 能不能裝）；已裝的 DWPose 夠不夠做身形液化；開源的液化／瘦身演算法。

## Answer

（2026-10-04，研究子代理；詳見 [research/09-retouch-face-body-models.md](../research/09-retouch-face-body-models.md)，36 個來源。主 session 抽查屬實：核心有 `SDPoseKeypointExtractor`（`nodes_sdpose.py`）；onnxruntime 1.30.0（CPU 版）、kornia 0.8.3 已裝；DWPose 模型在 `models/dwpose/`，執行它的 `rtmlib` 只在 `scratch/pylib-rtmlib/`，沒有 ComfyUI 節點——scratch 會被清，要搬到正式位置。）

- **美顏找位置**：臉部各區域用 BiSeNet 臉部解析（yakhyo 的 ResNet34 ONNX 版，約 82MB、19 類、MIT），用已裝的 CPU 版 onnxruntime 就能跑；虹膜、眼白等細部可用 MediaPipe Face Landmarker（478 點）補——但 mediapipe 在 Python 3.13 能不能跑未確認（新版沒有 `mediapipe.solutions`、會拉 `opencv-contrib-python` 要用 `--no-deps`），備案是 BiSeNet 的眼睛類別＋68 點眼眶點。
- **美顏做調整（程式，滑桿控制）**：自己寫，零件都有（kornia `guided_blur`／`bilateral_blur`、OpenCV `cv2.inpaint`）。磨皮＝三層頻率分離、只衰減中頻、細紋理層不動（保留毛孔）；去斑＝中頻找小點再補色；亮眼、白牙＝遮罩內調 LAB。顏色門檻選像素是推論，要拿真照片調。
- **身形**：關鍵點用 DWPose（要包成節點）或核心內建 SDPose（134 點、Apache-2.0，要再下載約 2GB）；人物範圍用已有的 BiRefNet。變形自己寫：MLS 在粗網格算位移場、`grid_sample` 套圖，強度滑桿乘位移量。瘦臉（下顎點）、拉腿長（髖膝踝）關鍵點夠；**瘦腰不夠**（沒有腰點、沒有輪廓），要搭人物遮罩量。小幅度靠遮罩外固定錨點、位移衰減到 0；**大幅瘦身要先補背景，跟「③ 去雜物、去路人用什麼？」的補圖流程相依**。
- **沒有現成的「吃關鍵點自動瘦腰拉腿」節點**；Olm Liquify 是手動筆刷；JH-PixelPro 要 ComfyUI ≥ 0.43，可參考其演算法（Apache-2.0）。
- **避開**：SegFormer face-parsing（jonathandinu）、InsightFace 預訓練模型、FlowBasedBodyReshaping、Sapiens v1（非商用或學術限定）；會拉 `ultralytics`（AGPL）、`opencv-contrib-python`、`onnxruntime-gpu` 的節點包（會跟本機套件打架）。Sapiens2 可商用，可當身體部位分割的升級選項。
- **未知**：mediapipe 能不能裝；BiSeNet 輸入 512×512 在高解析人像上邊緣準不準；BiRefNet、SDPose 在這台都還沒測。

