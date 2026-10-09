# ③ 去雜物、去路人：用什麼模型、怎麼指定、怎麼保證不動到別處

日期：2026-10-04（研究票 `issues/10-object-removal-model.md` 的研究結果；票的狀態未更動）

## 來源清單

Qwen-Image 修圖的副作用與遮罩接法
- [S1] lilting.ch〈Qwen-Image 2.1 Edit pixel-perfect output resolution〉（2026-09-22）https://lilting.ch/en/articles/qwen-image-2-1-edit-pixel-perfect-output-resolution
- [S2] lilting.ch〈Qwen-Image-Edit pixel-perfect ReferenceLatent〉（測 2511）https://lilting.ch/en/articles/qwen-image-edit-pixel-perfect-referencelatent
- [S3] RunComfy〈Qwen Image 2.1 Inpainting | No-Offset Edits〉https://www.runcomfy.com/comfyui-workflows/qwen-image-2-1-inpainting-in-comfyui-no-offset-edits
- [S4] LockPixelQwenEncode 節點 https://comfy.icu/node/LockPixelQwenEncode ；Rennart Pixel Drift Fix https://comfy.icu/node/RennartPixelDriftFix
- [S5] QIE-2511-Object-Remover-v2（Qwen-Image-Edit 2509/2511 的移除 LoRA）https://huggingface.co/prithivMLmods/QIE-2511-Object-Remover-v2
- [S6] Qwen-Image 2.1 授權改為非商用研究授權 https://alternativeto.net/news/2026/9/alibaba-launches-qwen-image-2-1-a-7b-ai-model-with-native-transparency-and-a-license-change/ ；https://www.eesel.ai/blog/qwen-image-2-1
- [S7] 本機原始碼：`runtimes/comfyui/v0.39.0-portable-nvidia/ComfyUI_windows_portable/ComfyUI/comfy_extras/nodes_qwen.py`（`TextEncodeQwenImage21`）、`projects/comfyui/tools/make_all_in_one.py`（萬事通的接法）

專門的補圖模型
- [S8] Acly/comfyui-inpaint-nodes（LaMa、MAT、Fooocus、Fill Masked、Color Match，GPL-3.0）https://github.com/Acly/comfyui-inpaint-nodes
- [S9] LaMa（advimman/lama，Apache-2.0）https://github.com/advimman/lama ；big-lama.pt https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt
- [S10] MAT（fenglinglwb/MAT，「research purposes only」）https://github.com/fenglinglwb/MAT ；fp16 版 https://huggingface.co/Acly/MAT
- [S11] FLUX.1 Fill [dev] 模型卡 https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev ；GGUF 版 VRAM 估計 https://www.promptlayer.com/models/flux1-fill-dev-gguf
- [S12] FLUX.2 [klein]（4B Apache-2.0、9B 非商用）https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence ；klein 移除 workflow https://www.runcomfy.com/comfyui-workflows/flux-klein-unified-image-editing-inpaint-remove-outpaint-in-comfyui-advanced-image-restoration
- [S13] LanPaint（免訓練遮罩補圖取樣器，支援 Qwen-Image 2.1，GPL-3.0）https://github.com/scraed/LanPaint
- [S14] ObjectClear（SDXL-Inpainting 底、NTU S-Lab 非商用授權）https://github.com/zjx0101/ObjectClear ；論文 https://arxiv.org/abs/2505.22636
- [S15] OmniEraser（FLUX.1-dev 底，連陰影倒影一起移除）https://github.com/PRIS-CV/OmniEraser ；論文 https://arxiv.org/abs/2501.07397
- [S16] RORem（SDXL-Inpainting 底，Apache-2.0，有 4 步版）https://github.com/leeruibin/RORem

指定要移除的東西（分割）
- [S17] ComfyUI 官方 SAM 3.1 文件 https://docs.comfy.org/tutorials/utility/video-segment-sam3 ；模型 https://huggingface.co/Comfy-Org/sam3.1 （`sam3.1_multiplex_fp16.safetensors`，1,745,546,848 bytes，SAM License）
- [S18] 本機原始碼：`comfy_extras/nodes_sam3.py`（`SAM3_Detect`：文字、框、正負點）
- [S19] 本機原始碼：`custom_nodes/ComfyUI-KJNodes`（`PointsEditor`，輸出 `positive_coords`／`negative_coords`／`bbox`，標示 WORK IN PROGRESS）
- [S20] kijai/ComfyUI-segment-anything-2（Apache-2.0）https://github.com/kijai/ComfyUI-segment-anything-2
- [S21] PozzettiAndrea/ComfyUI-SAM3 https://github.com/PozzettiAndrea/ComfyUI-SAM3 ；https://www.runcomfy.com/comfyui-nodes/ComfyUI-SAM3/sam3-grounding
- [S22] kijai/ComfyUI-Florence2（MIT）https://github.com/kijai/ComfyUI-Florence2 ；transformers 升級後壞掉的回報 https://github.com/kijai/ComfyUI-Florence2/issues/135
- [S23] storyicon/comfyui_segment_anything（GroundingDINO＋SAM，2024-07 後沒更新）https://github.com/storyicon/comfyui_segment_anything

合成（遮罩外保證原圖）
- [S24] lquesada/ComfyUI-Inpaint-CropAndStitch（GPL-3.0，2026-09 仍在更新）https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch
- [S25] ComfyUI 官方 inpaint 教學 https://docs.comfy.org/tutorials/basic/inpaint

本機查到的環境（2026-10-04）：ComfyUI 0.38 可攜版 Python 3.13.14、transformers 5.17.0、已裝 `spandrel 0.4.2`、`opencv-python-headless 5.0.0.93`、`segment-anything 1.0`、`timm`、`kornia`；已裝 custom nodes 含 KJNodes、Impact-Pack、Easy-Use、essentials、was-node-suite。**核心已內建 `SAM3_Detect`**，也有 `ImageCompositeMasked`、`GrowMask`、`FeatherMask`、`DifferentialDiffusion`、`SetLatentNoiseMask`。

---

## 1. 用 Qwen-Image 2.1 提示詞移除（萬事通現況）

### 1.1 副作用：整張重畫

- Qwen-Image 修圖本質上是**每次都重新生成整張圖**，沒被要求改的地方也是重畫出來的 [S2]。
- **位置偏移**：參考圖被縮到約 1MP、輸出 latent 卻是原尺寸時，網格對不齊，未改的區域會水平偏移約 8px、垂直約 3px（2511 實測）[S2]；Qwen-Image 2.1 預設設定同樣約 8px，人物變窄約 2.7% [S1]。把參考圖與輸出用同一尺寸（2.1 的 `output_resolution` 設成 √(原圖面積)、尺寸取 32 的倍數）後，整張偏移降到約 ±0.1px [S1]。
- **萬事通已避開位置偏移**：`make_all_in_one.py` 把 `TextEncodeQwenImage21` 的 `resolution` 設 0（圖已在前面縮好、保持原尺寸），並用編碼節點輸出的 latent（跟圖 1 同尺寸）去取樣 [S7]；本機節點原始碼也寫明「其他尺寸會讓修圖位移」[S7]。注意 `resolution=0` 仍會把長寬**捨入到 32 的倍數**，不是 32 倍數的原圖會被 lanczos 微縮放 [S7]——要做像素級貼回時，必須先把原圖裁／補到 32 倍數，或貼回時縮回原尺寸（推論）。
- **就算位置對齊，像素仍會變**：2.1 在對齊後換表情的測試裡，臉以外仍有 **2.6%** 的像素被改（舊版 Qwen-Image-Edit 是 0.7%），輪廓變細、膚色陰影變淡——是輕度重畫，不只是位移 [S1]。
- **臉與顏色漂移**：2511 測試觀察到重畫的臉會套上模型自己的「house style」、來回修圖時配色被重新發明 [S2]。這正是使用者「臉、構圖、顏色要保持原樣」最在意的部分。
- 本機輸出的 latent 是**全零的空 latent**（denoise 1.0 從頭生成），不是原圖編碼 [S7]，所以現在的萬事通流程沒有任何「遮罩外保留」的機制。

結論：**單靠提示詞「remove the person on the left」不能保證遮罩外不變**；位置偏移萬事通已處理，但輕度重畫（約 2～3% 像素）、臉與色調漂移無法用提示詞消除。

### 1.2 讓 Qwen 只在遮罩內重畫的接法

| 接法 | 做法 | 能否保證遮罩外原像素 | 來源 |
|---|---|---|---|
| A. 潛空間遮罩 | `VAEEncode(原圖)` → `SetLatentNoiseMask(遮罩)` → 取樣（條件仍用 `TextEncodeQwenImage21`＋原圖當參考） | 否。取樣時遮罩外的 latent 會被拉回原圖，但 VAE 來回一次仍會改像素；而且 Qwen 2.1 的 latent 是 1/16 解析度（64 通道、`h//16`）[S7]，遮罩邊界以 16px 為一格，很粗 | [S3]（明說「不保證遮罩外像素相同、邊緣附近可能有微小變化」）、[S7] |
| B. LanPaint 取樣器 | 免訓練的遮罩條件取樣，每步多想 N 次（建議 5，等於慢 5 倍）；附 `LanPaint Mask Blend` 把原圖貼回 | 有了 Mask Blend 才算保證 | [S13]（已支援 Qwen-Image 2.1） |
| C. 差分遮罩合成 | 讓 Qwen 自由修圖，再算「輸出 vs 原圖」差異 → 門檻 → 擴張 → 只把差異區貼回原圖 | 是（遮罩外直接是原圖） | [S2] 建議「透過差分遮罩把輸出合成回原圖，差異集中在修改區，用門檻幾乎可自動建遮罩」 |
| D. 使用者遮罩合成 | 不管用哪種生成，最後一步 `ImageCompositeMasked(原圖, 生成圖, 遮罩)` | 是 | [S24][S25]；本機核心節點 |
| E. 專用移除 LoRA | QIE-2511-Object-Remover-v2：在圖上把要移除的東西塗紅，提示詞「Remove the red highlighted object from the scene.」 | 否（仍是整張重畫） | [S5]（只支援 Qwen-Image-Edit 2509／2511，**不是 2.1**；Apache-2.0） |

重點：**A、B、E 都只能「傾向」不動遮罩外；真正的保證只能來自最後的像素合成（C 或 D）**。這跟生成用哪個模型無關。

授權註記：Qwen-Image 2.1 權重改成非商用研究授權 [S6]；使用者修自己的照片自用不受影響（推論），但不能拿去做商業服務。

---

## 2. 專門的補圖（inpainting）模型

| 模型 | 類型 | 效果特性 | 權重大小／VRAM | ComfyUI 節點 | 授權 | 16GB 卡可行性 |
|---|---|---|---|---|---|---|
| **LaMa（big-lama）** | 非擴散，快速傅立葉卷積 | 只看周圍補紋理，**不會憑空生出新東西**；規則紋理（牆、地板、天空、草地）很好；以 256px 訓練但能類推到約 2K [S9]；大面積、複雜結構（人站在有細節的背景前）容易糊、重複紋理（推論，社群普遍經驗） | 205,669,692 bytes（`big-lama.pt`）[S9]；推論時 VRAM 約 1～2GB（推論） | `comfyui-inpaint-nodes` 的 `Load Inpaint Model`＋`Inpaint (using Model)` [S8]；也有 art-venture 的 `LaMaInpaint`、`Comfyui-lama-remover` | 程式與權重 Apache-2.0 [S9]；節點包 GPL-3.0 [S8] | 輕鬆。依賴 `spandrel`、`opencv`，本機都已裝 |
| **MAT（Places512）** | 非擴散，Transformer | 大洞補圖比 LaMa 有結構感，但只吃 512 的倍數 [S10] | fp16 125,280,278 bytes [S10] | 同上 [S8] | 「research purposes only」，GitHub 判定 NOASSERTION [S10] | 輕鬆，但授權限研究、解析度受限；不建議當主力 |
| **FLUX.1 Fill [dev]** | 12B 擴散，專門補圖訓練 | 依提示詞補內容，結構與光線比 LaMa 好；模型卡自承**未填區域可能有輕微色偏**、複雜紋理邊緣有瑕疵 [S11] | Q4 約 8GB、Q8 約 16GB（只算本體）[S11]；另需 T5-XXL＋CLIP-L | 核心 `InpaintModelConditioning`＋ComfyUI-GGUF（已裝）| FLUX.1 [dev] 非商用授權，產出可商用 [S11] | Q5／Q6 GGUF 可行，T5 放系統記憶體（推論）；要另外下載約 10～20GB |
| **FLUX.2 [klein]** | 4B／9B 擴散，生成＋編輯統一 | 有社群「遮罩＋提示詞移除」workflow，附色彩校正 [S12] | 4B 約 13GB、9B 約 24GB（官方，fp 未量化）；FP8 少約 40% [S12] | 社群 workflow [S12] | 4B Apache-2.0、9B 非商用 [S12] | 4B 可行；要另外下載 |
| **LanPaint**（取樣器，非模型） | 讓任何模型做遮罩補圖 | 支援 Qwen-Image 2.1、Flux 2、Z-Image…；移除時要把目標寫進負面提示詞 [S13] | 用現有 Qwen 2.1，不增加權重；時間約 ×5 | `LanPaint` 節點包 [S13] | GPL-3.0 | 可行，**唯一不必下載新大模型就能讓 Qwen 2.1 做遮罩補圖的現成方案**；但慢 |
| **ObjectClear** | SDXL-Inpainting 底＋目標感知注意力 | 連陰影、倒影一起移除，背景保真度高 [S14] | 未公布 | **沒有 ComfyUI 節點** [S14] | NTU S-Lab 非商用 [S14] | 只能另開 Python 環境跑；暫不考慮 |
| **OmniEraser** | FLUX.1-dev 底 | 移除物件＋其陰影倒影，野外場景強 [S15] | 未公布（FLUX 12B 底，推論需 Q8 級量化才放得下） | 沒有官方節點 [S15] | GitHub 未標授權 [S15] | 不確定；暫不考慮 |
| **RORem** | SDXL-Inpainting 底 | 專門移除，有 4 步 LoRA 版 [S16] | 未公布（SDXL 級，推論 6～8GB） | 沒有 ComfyUI 節點 [S16] | Apache-2.0 [S16] | 要自己包節點 |
| VOID（核心 `nodes_void.py`） | CogVideoX 影片物件移除 | 影片用 | — | 本機核心已內建 [S18 同目錄] | — | 照片不適用 |

觀察：
- 2025～2026 的「物件＋陰影一起移除」研究（ObjectClear、OmniEraser）效果好，但都**沒有 ComfyUI 節點、授權不清或非商用**，短期接不進來。
- **最省事、本機現成依賴已齊的是 LaMa**；**品質上限高、又不必下載新大模型的是 Qwen 2.1＋遮罩（LanPaint 或 SetLatentNoiseMask）**。FLUX Fill／klein 是第三條路，但要多下載 10GB 以上、又多一套模型要維護。

---

## 3. 使用者怎麼指定要移除的東西

| 方式 | ComfyUI 現成做法 | Windows＋Python 3.13 能不能裝 | 來源 |
|---|---|---|---|
| 筆刷塗遮罩 | 核心 `Load Image` 的 Mask Editor | 內建 | [S25] |
| 框選 | 核心 `SAM3_Detect` 吃 `bboxes`；框可來自 KJNodes `PointsEditor`（Ctrl＋拖曳畫框，輸出 `bbox`）| 內建＋已裝 | [S18][S19] |
| 點選（正／負點） | `SAM3_Detect` 吃 `positive_coords`／`negative_coords`，格式是 JSON `[{"x":..,"y":..}]`（像素座標），**正好是 KJNodes `PointsEditor` 的輸出格式**（Shift＋左鍵正點、Shift＋右鍵負點） | 內建＋已裝；但 `PointsEditor` 自己標 WORK IN PROGRESS | [S18][S19] |
| 文字描述 | `SAM3_Detect` 吃 `CLIPTextEncode` 的條件（開放詞彙，如「person on the left」「trash can」）；官方文件說每個提示最多 32 token、可用逗號列多個物件並加 `:N` 限數量 | 內建；只需下載 `sam3.1_multiplex_fp16.safetensors`（約 1.75GB）放 `models/checkpoints/` | [S17][S18] |
| 文字描述（替代） | Florence-2（`ComfyUI-Florence2`）出框 → SAM2 | 有風險：transformers 升級後常壞，社群解法是降到 4.49；本機是 transformers 5.17 | [S22] |
| 文字描述（替代） | GroundingDINO＋SAM（`comfyui_segment_anything`） | 2024-07 後沒更新，不建議 | [S23] |
| 點／框（替代） | Kijai `ComfyUI-segment-anything-2`（SAM2，Apache-2.0）| 純 torch 可跑；遮罩後處理需編 CUDA 擴充、預設關閉 | [S20] |
| 自動偵測 | Impact-Pack（已裝）的 BBOX／SEGM 偵測器＋SAM | 已裝 | Impact-Pack |

結論：**ComfyUI 0.38 核心內建的 `SAM3_Detect` 一顆節點就涵蓋文字、框、點三種指定方式**，不必再裝 Florence-2、GroundingDINO 或 SAM2 節點包，也避開 Python 3.13＋transformers 5 的相容問題。SAM License 允許使用、修改、再散布，要求遵守法規與出口管制、發表研究時註明 [S17]。

注意：官方 SAM 3.1 文件只示範文字提示 [S17]，但本機 `SAM3_Detect` 原始碼有 `bboxes`、`positive_coords`、`negative_coords` 輸入 [S18]——點與框模式在本機能不能用，要實測（推論）。

「去路人」要注意：分割遮罩**只含人本身、不含影子與倒影**（推論；ObjectClear／OmniEraser 正是為此而生 [S14][S15]）。實務上要把遮罩往外擴張，或讓使用者補塗影子。

---

## 4. 遮罩內重畫、遮罩外保證原圖像素的合成做法

1. **遮罩前處理**：分割遮罩先 `GrowMask` 擴張（約 8～24px，蓋住邊緣光暈與髮絲；推論數值），必要時加補塗的影子。
2. **裁切放大再補**（`Inpaint Crop` ✂️）：只把遮罩周圍的情境區域裁出來，縮放到模型適合的尺寸（Qwen 約 1MP、32 倍數）再生成，比整張補圖快、細節多；`Inpaint Stitch` 貼回時**不改動遮罩外的區域** [S24]。這也順便解決 Qwen 尺寸要 32 倍數、原圖尺寸任意的問題（推論）。
3. **生成**：LaMa 直接補；或 Qwen 2.1＋`SetLatentNoiseMask`／LanPaint；可先用 LaMa 或 `Fill Masked`（telea／navier-stokes）預填遮罩區，再讓擴散模型以較低 denoise 修細節 [S8]。
4. **色彩校正（選用）**：`Color Match (Masked)` 讓補出的區域亮度、色調貼近周圍 [S8]（FLUX Fill 自承會色偏 [S11]）。
5. **像素合成**：`ImageCompositeMasked(destination=原圖, source=生成圖, mask=羽化遮罩)`。**羽化只往外不往內**：先擴張再模糊，確保遮罩值為 0 的區域＝原圖，羽化帶落在已擴張的範圍裡（推論）。
6. **驗收**：在遮罩值為 0 的區域算 `|輸出 − 原圖|` 的最大值，應為 0（8-bit 存檔後也應為 0，JPEG 重壓縮除外）。這可以寫成自動檢查（推論）。

不用使用者遮罩時（純提示詞修圖），可用 **差分遮罩** [S2]：`|Qwen 輸出 − 原圖|` → 門檻 → 去小雜點、取最大連通區 → 擴張羽化 → 合成。風險是 2.1 的全圖輕度重畫（約 2.6% 像素）會產生雜訊，門檻要調（推論）。

---

## 5. 推薦做法

**「SAM3 指定 → 擴張遮罩 → Crop → 補圖（LaMa 快速 / Qwen 2.1 精修兩檔）→ Stitch 像素合成」**，遮罩外一律是原圖像素。

- **指定**：核心 `SAM3_Detect`。三種入口：文字（「左邊那個人」交給 PE／②助理轉成英文名詞）、點選（KJNodes `PointsEditor`）、框選；Mask Editor 筆刷補漏（影子）。只需下載 1.75GB 的 SAM 3.1。
- **補圖・快速檔（預設）**：LaMa。理由：本機依賴已齊、約 200MB、秒級、**不會生出新東西也不會改臉**（只看周圍紋理），最符合「不要動到沒指定的地方」；Apache-2.0。適合小～中型雜物、簡單背景前的路人。
- **補圖・精修檔**：Qwen-Image 2.1（已在機器上）做遮罩補圖——先試 `VAEEncode＋SetLatentNoiseMask`（零安裝），效果不夠再裝 LanPaint；LaMa 預填當起點。適合大面積、背景結構複雜（建築、人群）的情況。
- **合成**：不論哪一檔，最後一律 `Inpaint Stitch`／`ImageCompositeMasked` 貼回原圖，並加「遮罩外差值＝0」的自動檢查。這一步才是「臉、構圖、顏色保持原樣」的真正保證，模型只負責遮罩裡那一塊。
- **暫不採用**：FLUX Fill／klein（要多下載 10GB 以上、多維護一套模型，等 Qwen 精修檔實測不夠再考慮）；ObjectClear／OmniEraser／RORem（沒有 ComfyUI 節點、授權不清）；MAT（研究授權、512 限制）；QIE Remover LoRA（只支援 2509／2511，不是 2.1）；純提示詞整張重畫（不保證遮罩外不變）。

符合地圖已定原則：AI 只負責「找位置（SAM3 遮罩）」與「重畫遮罩內內容」，保留原圖的合成由程式做。

## 6. 不確定點（需要實測）

1. **最大的不確定：Qwen-Image 2.1 做遮罩補圖的品質**。它不是專門的補圖模型，`SetLatentNoiseMask` 在 1/16 解析度的 latent 上遮罩很粗，可能在遮罩邊緣出現接縫或「把人重畫回去」；LanPaint 慢 5 倍。要拿使用者的照片做 LaMa vs Qwen（SetLatentNoiseMask）vs Qwen（LanPaint）A/B。
2. LaMa 對「人站在複雜背景前」的大面積移除會不會糊到不能用——決定精修檔是不是必要。
3. 本機 `SAM3_Detect` 的點／框模式能不能用（官方文件只示範文字）；KJNodes `PointsEditor` 標為實驗中，可能要自己做簡單的點選介面（可併入 02 節點介面票）。
4. 影子／倒影：SAM 遮罩不含影子，自動擴張夠不夠、還是要使用者補塗。
5. 尺寸：原圖不是 32 倍數時，Crop／Stitch 的縮放對齊是否完全無損（應無損，因為 Stitch 只貼回遮罩區，推論）。
