# ③ 美顏、身形需要哪些模型？（研究）

- 日期：2026-10-04（研究票 `issues/09-retouch-face-body-models.md` 的研究結果；票的狀態未更動）
- 前提：本機 ComfyUI 0.38（Windows、NVIDIA 可攜版，內嵌 Python 3.13、torch 2.14.0+cu130、RTX 4070 Ti SUPER 16GB）。原則：**AI 只找位置（遮罩、關鍵點），程式做調整，強度用滑桿**。
- 標記：**「推論」**＝來源沒明講、是我依來源與本機條件推出來的；沒標的都有來源（以 [S#] 標示）。**「本機」**＝直接看這台的檔案確認。

## 來源清單

臉部解析／臉部關鍵點
- [S1] jonathandinu/face-parsing（SegFormer mit-b5、CelebAMask-HQ 19 類、「non-commercial research and educational purposes」）https://huggingface.co/jonathandinu/face-parsing （檔案大小由 HF API 查得：`model.safetensors` 338.6 MB、`onnx/model.onnx` 340.3 MB、`onnx/model_quantized.onnx` 89.4 MB）
- [S2] zllrunning/face-parsing.PyTorch（BiSeNet，程式 MIT，權重 `79999_iter.pth`）https://github.com/zllrunning/face-parsing.PyTorch
- [S3] yakhyo/face-parsing（BiSeNet ResNet18 約 43MB／ResNet34 約 82MB，有 ONNX，MIT，facefusion 採用）https://github.com/yakhyo/face-parsing
- [S4] SegFace（MIT；LaPa mean F1 93.03、CelebAMask-HQ 88.96、MobileNetV3 版 87.91 @ 95.96 FPS）https://huggingface.co/kartiknarayan/SegFace ；程式 https://github.com/Kartik-3004/SegFace ；論文 arXiv 2412.08647（檔案大小由 HF API 查得：swinb 各版約 1093 MB、mobilenet_celeba_512 84.9 MB）
- [S5] MediaPipe Face Landmarker（BlazeFace＋Face Mesh V2 478 點＋52 blendshape）https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
- [S6] MediaPipe Image Segmenter（SelfieMulticlass 256×256：背景／頭髮／身體皮膚／臉部皮膚／衣服／配件；CPU 217.76ms、GPU 71.24ms）https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter
- [S7] PyPI mediapipe（本次用 PyPI JSON API 查：0.10.31 起 Windows 只發 `py3-none-win_amd64` wheel；最新 1.0.1，2026-08-14，相依含 `opencv-contrib-python`、`matplotlib`、`sounddevice`）https://pypi.org/project/mediapipe/
- [S8] mediapipe issue #6192：0.10.31 起 Python 套件沒有 `mediapipe.solutions`（舊的 face_mesh API 消失）https://github.com/google-ai-edge/mediapipe/issues/6192 ；舊 issue（cp313 沒 wheel 的時期）https://github.com/google-ai-edge/mediapipe/issues/5769
- [S9] SelfieMulticlass 授權 Apache-2.0（第三方 NOTICE 轉述）https://cdn.jsdelivr.net/npm/react-native-webrtc-kaleidoscope@2.7.9/NOTICE.md
- [S10] InsightFace 2.1（PyPI：程式 MIT，「pretrained models … for non-commercial research only」）https://pypi.org/project/insightface/
- [S11] PyPI onnxruntime-gpu 1.30.0（有 cp313 win_amd64；`cuda` extra 依賴 `nvidia-cuda-runtime~=13.0`、`nvidia-cudnn-cu13`）https://pypi.org/project/onnxruntime-gpu/
- [S12] PyPI ultralytics 8.4.172（AGPL-3.0）https://pypi.org/project/ultralytics/

ComfyUI 節點包（臉）
- [S13] Ryuukeisyou/comfyui_face_parsing（MIT；用 [S1] 加 YOLOv8 face；附 guided filter 磨皮；需 `opencv-contrib-python`）https://github.com/Ryuukeisyou/comfyui_face_parsing
- [S14] dchatel/comfyui_facetools（BiSeNetMask、JonathandinuMask、DetectFaces、AlignFaces、WarpFacesBack；YOLO 偵測）https://github.com/dchatel/comfyui_facetools ；https://www.runcomfy.com/comfyui-nodes/comfyui_facetools
- [S15] djbielejeski/a-person-mask-generator（MIT；用 SelfieMulticlass 與 face_landmarker.task 出背景／頭髮／身體／臉／衣服遮罩，以及臉輪廓、眉、眼、瞳孔、嘴唇遮罩）https://github.com/djbielejeski/a-person-mask-generator
- [S16] 1038lab/ComfyUI-RMBG（GPL-3.0；Face Segment 19 類、Body Segment、Clothes Segment、SAM3、BiRefNet；requirements 同時列 `onnxruntime` 與 `onnxruntime-gpu`）https://github.com/1038lab/ComfyUI-RMBG
- [S17] Fannovel16/comfyui_controlnet_aux 的 MediaPipe-FaceMeshPreprocessor https://runcomfy.com/comfyui-nodes/comfyui_controlnet_aux/MediaPipe-FaceMeshPreprocessor

磨皮與修圖節點／演算法
- [S18] jetthuangai/ComfyUI-JH-PixelPro（Apache-2.0；GPU Frequency Separation、Edge-Aware Skin Smoother（bilateral）、High-Frequency Detail Masker、Face Landmarks 468、Face Warp（Delaunay）、Face Beauty Blend；README 寫 ComfyUI ≥ 0.43.x）https://github.com/jetthuangai/ComfyUI-JH-PixelPro ；https://comfy.icu/extension/jetthuangai__ComfyUI-JH-PixelPro
- [S19] comfyUI_FrequencySeparation_RGB-HSV https://www.runcomfy.com/comfyui-nodes/comfyUI_FrequencySeparation_RGB-HSV ；ComfyUI-Image-Filters FrequencySeparate https://www.runcomfy.com/comfyui-nodes/ComfyUI-Image-Filters/FrequencySeparate ；RC High/Low Frequency Skin Smoothing（列表頁）https://comfyai.run/custom_node/ComfyUI-MachinePaintingNodes
- [S20] 本機：`custom_nodes/RES4LYF/__init__.py` 第 348～350 行（`Frequency Separation Linear Light／Hard Light／Hard Light LAB`），`RES4LYF/images.py`
- [S21] 本機：內嵌 Python 的 `kornia 0.8.3`（`kornia/filters/guided.py: guided_blur`、`bilateral.py: bilateral_blur／joint_bilateral_blur`、`median.py`）、`opencv_python_headless 5.0.0.93`（沒有 contrib，沒有 `cv2.ximgproc`）、`scipy 1.18.1`、`scikit_image 0.26.0`、`onnxruntime 1.30.0`（CPU 版，`capi/` 裡沒有 CUDA provider DLL）
- [S22] 四種 Photoshop 磨皮手法比較（Gaussian blur、Inverted High-Pass、Frequency Separation、Dodge & Burn）https://www.diyphotography.net/?p=25081 ；保留細節的 high-pass 磨皮 https://www.tipsquirrel.com/keeping-the-details-skin-smoothing-the-smart-way/
- [S23] Guided filter：He, Sun, Tang〈Guided Image Filtering〉ECCV 2010／TPAMI 2013（kornia `guided_blur` 即此演算法，見 [S21]）

身形液化
- [S24] Jarvis73/Moving-Least-Squares（MIT；NumPy 與 PyTorch 版；affine／similarity／rigid；2000×2000、64 控制點：NumPy 61.9 秒、PyTorch CUDA 1.8 秒、約 4.2GB）https://github.com/Jarvis73/Moving-Least-Squares ；原論文 Schaefer et al. 2006〈Image Deformation Using Moving Least Squares〉
- [S25] MLS 其他實作：molesq（PyPI）https://pypi.org/project/molesq ；Rust crate（有 dense 與 sparse grid 兩種 warp）https://crates-io.ganymede-static.progval.net/crates/moving-least-squares-image/0.1.1
- [S26] Gustafsson〈Interactive Image Warping〉1993 碩論（局部平移／縮放 warp，液化筆刷的經典做法）https://www.gson.org/thesis/warping-thesis.pdf
- [S27] o-l-l-i/ComfyUI-Olm-Liquify（互動式液化編輯器：Push／Pull／Twirl／Pinch／Expand／Smooth，可存 .npz warp 場）https://comfy.icu/extension/o-l-l-i__ComfyUI-Olm-Liquify
- [S28] FlowBasedBodyReshaping（CVPR 2022，BR-5K；「For academic and non-commercial use only」；靠 OpenPose）https://github.com/JianqiangRen/FlowBasedBodyReshaping ；論文 https://openaccess.thecvf.com/content/CVPR2022/html/Ren_Structure-Aware_Flow_Generation_for_Human_Body_Reshaping_CVPR_2022_paper.html
- [S29] 只改關鍵點、不改圖的節點：ComfyUI-ProportionChanger https://github.com/grmchn/ComfyUI-ProportionChanger ；ComfyUI-BodyRatioMapper https://github.com/wuwukaka/ComfyUI-BodyRatioMapper ；ComfyUI-SAM3D-BodyMod https://github.com/Burgstall-labs/ComfyUI-SAM3D-BodyMod
- [S30] 本機：`models/dwpose/`（`yolox_l.onnx`、`dw-ll_ucoco_384.onnx`，Apache-2.0，133 點＝身體 17＋腳 6＋臉 68＋手 42）與 `docs/models.md`：**ComfyUI 沒有裝 DWPose 節點**，目前是 scratch 裡的 rtmlib 0.0.16 獨立腳本（跑在 ComfyUI 內嵌 Python）
- [S31] 本機：`comfy_extras/nodes_sdpose.py`（內建 `SDPoseKeypointExtractor`、`SDPoseFaceBBoxes`、`CropByBBoxes`、`SDPoseDrawKeypoints`；輸出轉成 OpenPose 134 點格式：身體 18＋腳 6＋臉 68＋左右手各 21）；官方文件 https://docs.comfy.org/tutorials/utility/pose-detection-sdpose ；權重 https://huggingface.co/Comfy-Org/SDPose （HF API：`sdpose_wholebody_fp16.safetensors` 1916.6 MB、`rt_detr_v4-x-hgnet_fp16.safetensors` 124.0 MB）；授權 Apache-2.0 https://comfyui-wiki.com/en/models/sdpose/sdpose

人體分割
- [S32] 本機：`models/birefnet/birefnet.safetensors`（MIT，ComfyUI 0.38 內建 `Load Background Removal Model`＋`Remove Background`，見 `docs/models.md`，尚未實測）
- [S33] 本機：`comfy_extras/nodes_sam3.py`（內建 `SAM3_Detect`：文字條件、框、正負點）；權重 https://huggingface.co/Comfy-Org/sam3.1 （`sam3.1_multiplex_fp16.safetensors` 1,745,546,848 bytes，SAM License：免權利金、可商用，禁止事項為軍事、違反制裁等）
- [S34] Sapiens（v1）body-part 28 類清單（含 Face_Neck、Torso、Left/Right_Upper_Leg、Lower/Upper_Lip、Lower/Upper_Teeth、Tongue）https://github.com/facebookresearch/sapiens/blob/main/lite/docs/SEG_README.md ；v1 授權 CC-BY-NC-4.0 https://huggingface.co/facebook/sapiens-seg-1b-torchscript
- [S35] Sapiens2（29 類，1024×768 輸入，1B 版 1.462B 參數，Sapiens2 License：可商用與非商用，禁止監控、生物辨識、deepfake 等）https://huggingface.co/facebook/sapiens2-seg-1b ；授權 https://github.com/facebookresearch/sapiens2/blob/main/LICENSE.md ；ComfyUI 節點 https://github.com/kijai/ComfyUI-Sapiens2 、https://github.com/starsFriday/ComfyUI-Sapiens2
- [S36] SCHP 人體解析（LIP 20 類／ATR 18 類）ComfyUI 節點 cozymantis/human-parser-comfyui-node（GPL-3.0）https://github.com/cozymantis/human-parser-comfyui-node

---

## 一、結論先講（推薦組合）

**美顏**
1. **臉部區域**：主力用 **BiSeNet 臉部解析（yakhyo/face-parsing 的 ResNet34 ONNX，約 82MB，19 類）** 出皮膚／眉／眼／鼻／上下唇／口內／頭髮／耳／脖子遮罩；用 **MediaPipe Face Landmarker（478 點，含虹膜 10 點）** 補「虹膜／眼白」與精確的眼、嘴輪廓。兩者都是 CPU 就夠快的小模型。
2. **調整**：自己寫一個節點包（純 torch＋kornia，本機已經有），不裝現成美顏包：
   - 磨皮＝**頻率分離**：低頻層用 guided filter／bilateral 磨平色塊，高頻層（毛孔紋理）保留並可用滑桿只衰減「中頻」；強度滑桿＝混合比例。
   - 去斑／痘＝在皮膚遮罩內找高頻能量的局部離群小點，對低頻層做小範圍補色（或 `cv2.inpaint`），高頻層換成鄰近皮膚紋理。
   - 亮眼＝虹膜／眼白遮罩內提亮、加局部對比；白牙＝口內遮罩 ∩ 亮且低飽和像素，LAB 降 b*、拉 L*。
3. **不要**一開始就上 SegFormer（jonathandinu，340MB、非商用）或 SegFace（1.1GB 的 swin-b）：精度略好，但大很多；BiSeNet 不夠準時再升級（SegFace 是最強的替代，MIT）。

**身形**
1. **關鍵點**：用 **ComfyUI 內建 SDPose**（Apache-2.0，1.9GB＋0.12GB，輸出 OpenPose 134 點 `POSE_KEYPOINT`），或把已有的 **DWPose（rtmlib）包成節點**（模型已在 `models/dwpose/`，不用再下載）。兩者點位相同（身體 17/18＋腳 6＋臉 68＋手 42）。
2. **人物範圍**：用已下載的 **BiRefNet**（內建節點）出人物遮罩，量腰寬、腿寬，並決定變形只作用在人身上。要分到「軀幹／大腿／小腿」再用 **Sapiens2 0.4B／1B 分割**（可商用授權，但模型大、要另裝節點）——第一版不需要。
3. **變形**：自己寫 **MLS（similarity/rigid）在粗網格上算位移場 → 平滑 → `grid_sample`**，或更簡單的**局部平移／局部縮放 warp**（Gustafsson 液化筆刷公式）。強度滑桿直接乘位移量。背景保護用「固定錨點」＋人物遮罩外的位移衰減；大幅瘦身時才需要補背景（接 ticket 10 的補圖模型）。

理由：所有 AI 模型都只負責定位，且都是**個人可用、多數可商用**的授權（BiSeNet 程式 MIT／MediaPipe Apache／SDPose Apache／BiRefNet MIT），模型小、CPU/GPU 都跑得動；調整全部是確定性的影像處理，滑桿 0 就是原圖，可重現、不會「AI 重畫臉」。

---

## 二、臉部解析／關鍵點候選

### 2.1 比較表

| 候選 | 輸出 | 授權 | 大小 | 精度（來源） | ComfyUI 現成節點 | 本機能不能裝 |
|---|---|---|---|---|---|---|
| **BiSeNet**（zllrunning 原版 [S2]／yakhyo 重訓版 [S3]） | 19 類分割：皮膚、左右眉、左右眼、眼鏡、左右耳、耳環、鼻、口內、上唇、下唇、脖子、項鍊、衣服、頭髮、帽子 | 程式 MIT；權重用 CelebAMask-HQ 訓練（資料集限非商用研究，**權重能否商用沒明講**；個人使用沒問題——推論） | 原版約 53MB（推論，常見數字）；yakhyo R18 43MB／R34 82MB [S3] | 論文級中等；512×512 輸入，臉要先裁切對齊（推論） | comfyui_facetools 的 `BiSeNetMask` [S14]；facexlib 內建 parsing（推論） | yakhyo 有 ONNX，`onnxruntime` CPU 版本機已裝 [S21]，**零新增套件就能跑**（推論） |
| **SegFormer face-parsing**（jonathandinu）[S1] | 同 19 類 | **非商用研究與教育** | 338.6MB（fp32）／量化 ONNX 89.4MB | 比 BiSeNet 邊緣乾淨（社群共識，推論） | comfyui_face_parsing [S13]、ComfyUI-RMBG Face Segment [S16]、facetools `JonathandinuMask` [S14] | `transformers 5.17` 本機已有 [S21]；但 comfyui_face_parsing 還要 `ultralytics`（AGPL）與 `opencv-contrib-python`（會跟本機的 `opencv-python-headless 5.0` 打架）[S13] |
| **SegFace** [S4] | LaPa 11 類／CelebAMask-HQ 19 類／Helen | **MIT** | swin-b 各版 1.09GB（.pt，可能含訓練狀態）；MobileNetV3 85MB | LaPa mean F1 93.03、CelebA 88.96；Mobile 87.91 @ 96 FPS | 沒找到 | 純 PyTorch，`timm` 本機已有；要自己包節點（推論） |
| **MediaPipe Face Landmarker** [S5] | 478 個 3D 點（含左右虹膜各 5 點）＋52 blendshape | 程式與模型 Apache-2.0（推論：MediaPipe 模型卡普遍標 Apache；SelfieMulticlass 有第三方 NOTICE 佐證 [S9]） | `face_landmarker.task` 約 3～4MB（推論） | 臉部點最密；側臉、遮擋時會飄（推論） | a-person-mask-generator 的臉部遮罩節點 [S15]；JH-PixelPro Face Landmarks [S18]；controlnet_aux FaceMesh [S17]（用舊 `solutions` API，見下） | 見 2.2 |
| **MediaPipe SelfieMulticlass** [S6] | 6 類：背景／頭髮／**身體皮膚**／**臉部皮膚**／衣服／配件 | Apache-2.0 [S9] | 約 16MB | 輸入只有 256×256，邊緣粗（推論） | a-person-mask-generator [S15] | 見 2.2 |
| **InsightFace**（2d106／buffalo_l）[S10] | 5 點或 106 點關鍵點、偵測框 | 程式 MIT，**預訓練模型只限非商用研究** | buffalo_l 約 300MB（推論） | 偵測強 | ReActor、IPAdapter 系列 | 2.1 版是 `py3-none-any`，依 onnxruntime；可裝（推論）。只拿來當關鍵點不划算 |
| **SAM 3.1**（本機內建節點）[S33] | 文字或點提示的任意遮罩 | SAM License（可商用） | 1.75GB fp16 | 「teeth」「eyes」這種細部文字提示效果**未知**（推論） | ComfyUI 0.38 內建 `SAM3_Detect` | 不用裝節點，只要下載權重；ticket 10 也會用到 |
| **Sapiens／Sapiens2 分割** [S34][S35] | 28／29 類，含 Face_Neck、上下唇、**上下排牙齒**、舌頭、軀幹、四肢 | v1：CC-BY-NC；**v2：Sapiens2 License，可商用** | v2 0.4B～5B（1B＝1.46B 參數） | 全身人像解析最細 | kijai／starsFriday 的 ComfyUI-Sapiens2 | 要另裝節點與權重；1024×768 dense，VRAM 吃重（[S35] 的節點文件有警告） |

### 2.2 本機安裝面的關鍵事實

- **mediapipe 現在能裝在 Python 3.13 上（推論，未實測）**：PyPI 從 0.10.31（2025-12）起 Windows 只發 `py3-none-win_amd64` wheel，不綁 CPython 版本，最新 1.0.1（2026-08-14）[S7]。舊資料說「沒有 cp313 wheel」[S8 舊 issue] 是 0.10.21 以前的狀況。
  - 但 0.10.31 起**沒有 `mediapipe.solutions`**（舊的 `mp.solutions.face_mesh` 不見了）[S8]，只剩 `mediapipe.tasks`。所以 controlnet_aux 的 FaceMesh 這類用舊 API 的節點會壞（推論）；用 Tasks API（`face_landmarker.task`）的 a-person-mask-generator 比較有機會能用（推論，要看它的程式碼）。
  - 相依會拉 `opencv-contrib-python`、`matplotlib`、`sounddevice` [S7]：本機已經有 `opencv-python-headless 5.0`，兩個 cv2 套件會互相覆蓋。**要用 `--no-deps` 裝 mediapipe，再補 `absl-py`、`flatbuffers` 等**（推論）。
  - MediaPipe Python 在 Windows 上走 CPU（推論；官方 GPU delegate 主要支援 Android／Linux）。對單張照片無妨：Face Landmarker 是毫秒級模型。
- **onnxruntime**：本機是 CPU 版 1.30（`capi/` 沒有 CUDA provider DLL）[S21]。`onnxruntime-gpu 1.30.0` 有 cp313 Windows wheel，CUDA 13（`nvidia-cuda-runtime~=13.0`），跟 torch cu130 同代 [S11]。但 GPU 版跟 CPU 版是**同一個 `onnxruntime` 套件名稱空間，不能並存**，換之前要先移除 CPU 版（推論）。臉部解析／DWPose 這些小模型用 CPU 跑一張照片就夠快，**第一版不需要換 GPU 版**（推論）。
- **避開 `ultralytics`**：AGPL-3.0 [S12]，而且相依會拉 `opencv-python`，還可能動到 torch（本機規則要用 `torch-pin.txt` 鎖版本）。comfyui_face_parsing、comfyui_facetools 都靠它做臉部偵測 [S13][S14]——這是不直接裝它們的主因之一。臉部偵測改用 MediaPipe BlazeFace，或直接用 SDPose／DWPose 的臉部 68 點算臉框（本機 `SDPoseFaceBBoxes` 就是這樣做）[S31]。
- **ComfyUI-RMBG** 雖然一包搞定（Face Segment＋BiRefNet＋SAM3），但 requirements 同時列 `onnxruntime` 與 `onnxruntime-gpu`、還有 GPL-3.0 [S16]；裝下去會動到本機的 onnxruntime（推論）。它的 Face Segment 用的是 jonathandinu 的非商用 SegFormer。
- **JH-PixelPro**（功能最接近需求：頻率分離、bilateral 磨皮、高頻遮罩、468 點、Face Warp）README 寫需要 **ComfyUI ≥ 0.43.x**，本機是 0.38 [S18]——直接裝可能不相容；但 Apache-2.0，**可以參考它的演算法自己寫**。

### 2.3 每個美顏功能要的遮罩對應

| 功能 | 需要的區域 | 首選來源 | 備援 |
|---|---|---|---|
| 磨皮 | 臉部皮膚（扣掉眉、眼、唇、鼻孔、頭髮）；可選脖子、身體皮膚 | BiSeNet 的 skin（+neck） | SelfieMulticlass 的 face-skin／body-skin（解析度低，只當補充） |
| 去斑／痘 | 同上，再內縮幾像素避開五官邊緣 | BiSeNet skin 遮罩侵蝕後 | — |
| 亮眼 | 虹膜、眼白 | Face Landmarker 虹膜 5 點畫圓＋眼眶輪廓點畫多邊形 | BiSeNet 的 l_eye／r_eye（含眼白與虹膜，分不開） |
| 白牙 | 口內 ∩ 牙齒色 | BiSeNet 的「mouth（口內）」再用顏色門檻（亮度高、飽和低）挑出牙齒（推論） | Sapiens 有 Upper/Lower_Teeth 類別 [S34]，但模型大 |
| 瘦臉 | 下顎線 | SDPose／DWPose 臉部 68 點的 0～16（下顎輪廓） | Face Landmarker 的臉輪廓點 |

---

## 三、磨皮／美顏演算法與現成節點

### 3.1 本機已經有的

- **RES4LYF**：`Frequency Separation Linear Light／Hard Light／Hard Light LAB`，可拆高頻／低頻、再合回 [S20]。缺點：只做拆合，低頻要自己接模糊節點；程式寫死 `.to('cuda')`、float64（看原始碼，本機）。
- **kornia 0.8.3**：`guided_blur`（He 等人的 guided filter [S23]）、`bilateral_blur`、`joint_bilateral_blur`、`median_blur`，都是 GPU torch 實作 [S21]——**自己寫磨皮節點的核心零件都在了**。
- **OpenCV headless 5.0**：有 `cv2.inpaint`（Telea／NS）、`bilateralFilter`、`edgePreservingFilter`；**沒有** `cv2.ximgproc.guidedFilter`（那在 contrib 版）[S21]。這也是 comfyui_face_parsing 要求 `opencv-contrib-python` 的原因 [S13]。

### 3.2 現成可裝的（只當參考）

| 節點包 | 有什麼 | 備註 |
|---|---|---|
| ComfyUI-JH-PixelPro [S18] | GPU 頻率分離、Edge-Aware Skin Smoother（bilateral）、High-Frequency Detail Masker、Face Warp、Face Beauty Blend（強度混合） | 最接近需求；要 ComfyUI ≥ 0.43；Apache-2.0 |
| comfyui_face_parsing [S13] | 臉部解析＋guided filter 磨皮 | 拉 ultralytics、opencv-contrib；SegFormer 非商用 |
| RC High/Low Frequency Skin Smoothing [S19] | 低頻半徑、高頻強度、膚色保護 | 細節不明 |
| comfyUI_FrequencySeparation_RGB-HSV、ComfyUI-Image-Filters [S19] | 頻率分離（相減／相除） | 只做拆合 |

### 3.3 演算法（自己寫的建議做法）

Photoshop 常見四種：高斯模糊、Inverted High-Pass、頻率分離、Dodge & Burn；比較文章結論是 Inverted High-Pass 會讓顏色糊、紋理變少，頻率分離與 D&B 保留紋理較好 [S22]。建議：

1. **頻率分離磨皮（保留毛孔）**
   - `low = guided_blur(img, guide=img, radius=r, eps)`（或 bilateral）；`high = img - low`（線性光式相減，或 RES4LYF 的 hard light 版）。
   - 低頻層再做一次大半徑的保邊平滑，抹平色斑、泛紅、明暗不均；**高頻層原封保留**（毛孔、細毛）。
   - 想更細：拆三層（細紋理／中頻／低頻），滑桿只衰減中頻（痘疤、細紋的尺度），細紋理層完全保留——這就是「保留毛孔質感」的關鍵（推論，三層拆法是修圖常見手法的延伸）。
   - 輸出 `out = lerp(img, low' + high, strength * mask_feathered)`；遮罩要羽化，避免臉緣出現邊界。
   - 半徑要跟臉的大小成比例（用臉框寬度換算），不然大頭照與全身照效果差很多（推論）。
2. **去斑／痘**：在皮膚遮罩內，對「中頻層」取絕對值或用 DoG 找比周圍暗或紅的小圓點（面積上限依臉寬換算），得到斑點遮罩；對低頻層用 `cv2.inpaint` 或周圍均值補色，高頻層換成鄰近皮膚的高頻（或直接降低）。強度滑桿控制偵測門檻與補色比例（推論；JH-PixelPro 的 High-Frequency Detail Masker 是類似思路 [S18]）。
3. **亮眼**：虹膜／眼白遮罩內做 L 通道曲線提亮＋小半徑 unsharp mask；眼白可再降飽和（去血絲）。強度滑桿乘曲線幅度（推論）。
4. **白牙**：口內遮罩內挑出 L 高、飽和低的像素當牙齒，LAB 空間降 b*（去黃）、L* 稍拉高；嘴唇不能被選到，所以先扣掉上下唇遮罩（推論）。

---

## 四、身形液化

### 4.1 現成的 ComfyUI 節點：沒有「關鍵點驅動、自動瘦腰拉腿」的

- **Olm Liquify**：互動式筆刷液化（Push、Pull、Twirl、Pinch、Expand、Smooth），能存 .npz warp 場 [S27]——是手動工具，不吃關鍵點。
- WAS `Image Displacement Warp`（本機已有）：給一張位移圖就能扭（本機原始碼），可當「位移場 → 套到圖上」的現成積木，但位移場還是要自己算。
- ProportionChanger、BodyRatioMapper、SAM3D-BodyMod：只改**關鍵點／3D 姿勢資料**（給 ControlNet 用），不改照片本身 [S29]。
- 學術方法 FlowBasedBodyReshaping（CVPR 2022，學出位移場）：**限學術非商用**、依賴 OpenPose、PyTorch 1.2 年代的程式 [S28]——不建議。

結論：**要自己寫一個「身形液化」節點**（位移場計算＋`torch.nn.functional.grid_sample`），這也符合「程式執行調整、滑桿控制強度」的原則。

### 4.2 演算法

- **MLS（Moving Least Squares）**：給一組控制點（原位置 p → 目標位置 q），算出整張圖平滑的變形；rigid／similarity 版不會產生不自然的剪切 [S24][S25]。直接逐像素算很慢（2000×2000、64 點：PyTorch CUDA 1.8 秒、約 4.2GB）[S24]；**在粗網格（例如每 8～16 像素一格）上算，再雙線性放大位移場**，就能快很多（Rust 實作的 sparse warp 就是這做法 [S25]；放大位移場的速度數字是推論）。
- **局部平移／縮放 warp（液化筆刷公式）**：以圓心、半徑、方向定義一個平滑衰減的位移（Gustafsson 1993 的交互式 warping [S26]）。瘦臉、瘦腰的手機 App 多用這種（推論）。實作簡單、每一筆是一個解析式，GPU 上幾乎即時。
- **拉腿長**：最常見的是「髖部以下（或膝蓋以下）的水平帶狀區域做垂直拉伸」，等於非均勻的 y 方向縮放；畫布高度會變，或把上半身略壓縮（推論，美圖類 App 的常見效果）。

### 4.3 DWPose／SDPose 關鍵點夠不夠

點位（DWPose 133 點 [S30]；SDPose 轉成 OpenPose 134 點 [S31]）：身體有鼻、眼、耳、**肩、肘、腕、髖、膝、踝**，腳 6 點（大拇趾、小趾、腳跟），臉 68 點，手 42 點。

| 變形 | 需要的位置 | 關鍵點夠不夠 |
|---|---|---|
| 瘦臉 | 下顎輪廓 | **夠**：臉 68 點的 0～16 就是下顎線（本機 h3-likeness 實驗已用它量臉型 [S30]）。把下顎點往臉中線（鼻樑點）拉近，當 MLS 控制點或局部平移中心 |
| 拉腿長 | 髖、膝、踝高度 | **夠**：髖點以下（或膝）到踝之間做垂直拉伸；腳 6 點可保護腳掌不被拉變形 |
| 瘦腰 | 腰的高度與**左右輪廓邊緣** | **不夠，只有一半**：沒有「腰」這個點。高度可用肩與髖之間內插（約肩→髖 60～70% 處，推論）；但**腰的左右邊緣在哪**關鍵點給不出來（髖點是骨盆關節位置，不在身體輪廓上）→ 要人物遮罩（BiRefNet）在那個高度掃出左右邊界 |
| 瘦手臂、瘦大腿 | 肢段中線＋輪廓 | 中線夠（肩-肘-腕、髖-膝-踝連線）；寬度要遮罩，衣服寬鬆時遮罩也只會量到衣服（推論） |

所以：**關鍵點負責「在哪個高度、往哪個方向」，人物遮罩負責「輪廓邊緣在哪」**。

**DWPose 在本機的現況要注意**：ComfyUI **沒有** DWPose 節點，現在是 scratch 裡的 rtmlib 獨立腳本 [S30]。兩條路：
- (a) 把 rtmlib 那段包成自寫節點（模型已在 `models/dwpose/`，onnxruntime CPU 就能跑；但 rtmlib 是 `--no-deps` 裝在 scratch，scratch 會被清，要搬到正式位置）。
- (b) 用 **ComfyUI 0.38 內建的 SDPose**（`SDPoseKeypointExtractor` 輸出 `POSE_KEYPOINT`，Apache-2.0）[S31]，零節點安裝，但要多下載約 2GB 權重；它是擴散模型骨幹，速度與 VRAM 比 DWPose 重（推論）。
- 單張修圖兩者都可；若想跟影片流程共用，(a) 比較省（推論）。

### 4.4 要不要人體分割？要，用已裝的 BiRefNet

- **用途 1：量輪廓**（上一節，瘦腰／瘦腿必需）。
- **用途 2：防背景扭曲**：液化是整張圖的位移場，腰往內縮時，腰旁邊的背景也會被拉過去；有直線的背景（門框、牆角、地板線）會彎，非常明顯（推論，液化的常見破綻）。做法由便宜到貴：
  1. **錨點法**：在人物遮罩外、離輪廓一段距離的地方放「不動的控制點」（MLS 的 p=q），讓位移在背景迅速衰減到 0；小幅度（滑桿前段）通常就夠（推論）。
  2. **位移場遮罩**：位移場乘上「人物遮罩向外羽化一圈」的權重，只讓人和緊貼的背景動（推論）。
  3. **前景/背景分層**：只扭前景（人），背景用補圖模型先把人挖掉補好（clean plate），再把扭過的人貼回去——瘦很多時唯一乾淨的做法，但要用到 ticket 10 的補圖模型（LaMa 等）（推論）。
- BiRefNet 本機已下載，ComfyUI 0.38 內建節點直接讀，MIT [S32]；**尚未實測**品質。若髮絲／衣服邊緣不夠，SAM 3.1 的「person」提示是第二選擇 [S33]。
- 要分出軀幹／大腿／小腿（例如只瘦大腿不動小腿、或衣服寬鬆時區分）才需要 **Sapiens2**（Torso、Upper/Lower_Leg 等 29 類，Sapiens2 License 可商用）[S34][S35]；v1 是 CC-BY-NC。第一版不需要。SCHP（LIP/ATR）是較舊、較小的替代，但節點包 GPL-3.0 [S36]。

---

## 五、推薦組合與理由（總整理）

| 用途 | 推薦 | 授權 | 大小 | 安裝成本 |
|---|---|---|---|---|
| 臉部區域分割 | BiSeNet ResNet34 ONNX（yakhyo）[S3] | 程式 MIT；權重訓練資料 CelebAMask-HQ（個人使用 OK） | 82MB | **零新套件**（本機 onnxruntime CPU） |
| 眼、虹膜、精細臉部點 | MediaPipe Face Landmarker（Tasks API）[S5] | Apache-2.0（推論） | 數 MB | `pip install mediapipe --no-deps`＋補少數相依（推論）；要實測 |
| 臉框（裁切給 BiSeNet） | MediaPipe BlazeFace 或 SDPose/DWPose 臉部 68 點算框 | Apache-2.0 | 小 | 同上／已有 |
| 身體關鍵點 | DWPose 包成節點（已下載）或內建 SDPose | Apache-2.0 | 已有／約 2GB | 自寫小節點／只下載權重 |
| 人物遮罩 | BiRefNet（已下載、內建節點）[S32] | MIT | 444MB | 零 |
| 升級選項 | SegFace（臉，MIT）、Sapiens2（身體部位，可商用）、SAM 3.1（任意物件，ticket 10 共用） | 見上 | 0.1～3GB | 中 |
| 調整演算法 | 自寫節點：頻率分離＋guided/bilateral（kornia）、斑點偵測＋inpaint（OpenCV）、MLS 粗網格＋`grid_sample` 液化 | 自有 | — | 零新套件 |

**理由**
1. **符合原則**：所有模型只定位；調整全部是可重現的影像處理，滑桿 0＝原圖，不會像擴散模型那樣「重畫」臉而改變長相。
2. **授權乾淨**：避開 SegFormer face-parsing（非商用）、InsightFace 模型（非商用研究）、FlowBasedBodyReshaping（學術非商用）、Sapiens v1（CC-BY-NC）、ultralytics（AGPL）。個人使用其實都可以，但選可商用或 MIT/Apache 的留後路。
3. **不弄壞環境**：避開會拉 `opencv-contrib-python`、`ultralytics`、`onnxruntime-gpu` 的節點包（本機是 `opencv-python-headless 5.0`＋CPU onnxruntime＋鎖版 torch）；核心零件（kornia、OpenCV、scipy、onnxruntime、transformers、timm）本機都已經有。
4. **VRAM 友善**：臉部模型都在 100MB 以下、可跑 CPU；最大的 SDPose/SAM3 也只有約 2GB，可以跟 Qwen-Image 工作流分開跑。

---

## 六、最大的不確定點（要實測）

1. **mediapipe 1.0.x 在 ComfyUI 內嵌 Python 3.13 上能不能真的跑**：wheel 標籤看起來可裝（`py3-none-win_amd64`），但官方 classifiers 只列到 3.12、且 `solutions` 已移除；`--no-deps` 避開 opencv-contrib 後是否缺東西也未知（推論）。若失敗，備案是：虹膜／眼白改用 BiSeNet 的眼睛類別＋DWPose/SDPose 臉部 68 點的眼眶 6 點近似，或改跑 Face Mesh 的 ONNX 轉檔版（未查證來源）。
2. **BiSeNet 在高解析人像上的邊緣品質**：它是 512×512 輸入，大圖要先裁臉再放大遮罩，髮際、鬍鬚、眼鏡附近可能不準；若磨皮溢出到眉毛、髮際，就要升級 SegFace 或 SegFormer（後者非商用）。
3. **白牙、斑點的「顏色門檻」做法**（完全是推論）在不同光線、膚色下穩不穩，需要用實際照片調參。
4. **身形液化背景保護的成本**：錨點法對小幅度應該夠，但「大幅瘦腰」需要背景補圖（ticket 10），兩張票之間有相依。
5. **BiRefNet、SDPose 在本機都還沒實測**（`docs/models.md` 標「尚未實測」）；SDPose 2GB 擴散骨幹的速度、DWPose 包成節點的工作量，都要量過才知道哪條路比較划算。
