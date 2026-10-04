# 19 別人的 AI 修圖都怎麼做？（研究）

- 日期：2026-10-04
- 對應票：`issues/19-ai-photo-editing-landscape.md`（下游：`issues/20-host-platform.md` ① 載體）
- 前提：本機 Windows、RTX 4070 Ti SUPER 16GB、64GB RAM；xmp 由程式（torch GPU）套用、拖動預覽約 30 ms；LLM（PE-I2I 9B、Qwen3.6-35B）給滑桿數值 JSON 合格，但白平衡會判錯、有固定套路；Qwen-Image 2.1 重畫會改臉與細節，混 25% 就有重影。
- 標記：**「推論」**＝來源沒有明講，是依來源與本專案條件推出來的；沒標的都有來源。
- 限制說明：helpx.adobe.com、support.captureone.com、部分 imagen-ai.com 頁面擋爬蟲（403），這幾項用官方網址加搜尋摘要，標「（摘要）」；reddit 全擋，社群反應改用 GitHub issue／討論串。

## 一頁摘要

**(a) 該不該放在 ComfyUI？不建議當主載體。** 建議「核心做成函式庫＋獨立本機 App 為主，ComfyUI 只當擴散模型的後端（必要時再包一個薄節點）」。理由：

1. 商業產品沒有一家把修圖做成「排隊執行」的流程：全域調色、AI 遮罩、去噪都在編輯器裡即時完成，生成式只用在移除／擴圖這類局部功能，結果另存一層或一個區塊（§1 共通模式）。
2. 最接近本專案的開源前例 RapidRAW（AGPL、10k 星）就是「獨立 App（Tauri/Rust＋React＋WGPU 即時預覽）＋本機 ONNX 遮罩模型＋一個小中介程式在需要生成式修圖時才呼叫 ComfyUI」[C4][C5]。Krita AI Diffusion 也是「外部前端把 ComfyUI 當後端」[C6][C7]。
3. ComfyUI 本身的限制正好卡在相片編輯最在意的地方：核心 LoadImage／SaveImage 是 8-bit、不處理 ICC、不帶 EXIF；官方 App Mode 也還是「按 Run 排隊」；要做到即時滑桿，現有節點包（AfterDark Live Grade、Olm ImageAdjust）都是「先跑一次，再用瀏覽器 shader 重寫一份算式」，兩份實作要人工對齊 [K1][K2][K5][K6]。
4. 本專案的核心（xmp 套用＋LLM 給數值）用不到 ComfyUI 的強項（把模型串成圖）；真正要用擴散模型的只有移除、可選的重畫，這些用 API 呼叫就好（推論，依 [C4][C6]）。

**(b) 哪些 AI 功能真正值得做（依優先序）：**

1. **AI 遮罩＋局部調整**（主體／天空／人物／背景，含「Adaptive preset」＝preset 內容套在 AI 遮罩裡）。所有商業產品與 darktable 5.6、RapidRAW 都有，屬參數式、本機、小模型、結果可再調 [A3][A4][L3][P1][D1][C4]。
2. **自動調整（Auto）＝ AI 算滑桿值，結果留在滑桿上可再改**。商業做法是用大量「修前／修後」配對專門訓練的模型（Adobe Sensei Auto、Pixelmator ML Enhance）[A1][P1]；通用 VLM 直接給數值的研究結論是「容易過度編修」「顏色的數值判斷弱」[R6][R9][R10]。所以 LLM 適合當「理解使用者想要的方向＋給初值」，**白平衡改由程式或專用模型量**，再加規則檢查與「渲染→再看一次→修正」的迴圈 [R3][R5]。
3. **ML 去噪／放大**（非生成式的像素網路，獨立成一步、烘進新檔）：Adobe Denoise、darktable neural restore 都是這個模式 [A6][D1]；本機已有 SeedVR2。
4. **移除雜物**：先用非生成式（LaMa）當本機預設，大面積才用擴散模型；結果只貼回遮罩區域，未修改的像素保持原樣 [A7][L1][C4][K3]。
5. **景深／重打光用「深度圖＋參數」**（Lightroom Lens Blur、Luminar Relight 都是深度圖加滑桿）而不是 IC-Light 重畫 [A8][L5][K4]。
6. 低優先：選片評分（Assisted Culling 類，只寫旗標不動像素）[A9]；個人風格學習（Imagen 至少 2,000 張、Aftershoot 至少 2,500 張修過的照片）[S1][S2]，目前資料量不夠。

**不值得做（或只留實驗）：** 全畫面擴散重畫當作「調色補強」。沒有任何一家商業產品把生成式用在全域調色；本專案實驗也證實會改臉、重影（`issues/16`）。

## 來源清單

**商業產品**
- A1 Adobe Blog 2017-12-12 Lightroom 12 月更新（Auto Settings 用 Adobe Sensei 神經網路）https://blog.adobe.com/en/publish/2017/12/12/announcing-december-update-lightroom
- A2 Adobe Blog 2024-10-14 The Adobe Adaptive Profile https://blog.adobe.com/en/publish/2024/10/14/the-adobe-adaptive-profile ；擷取：`.claude/read/material/adobe-adaptive-profile/index.md`
- A3 Adobe Blog 2022-10-18 Photography at Adobe MAX 2022（Select People／Objects／Background、Adaptive presets、Android 雲端遮罩）https://blog.adobe.com/en/publish/2022/10/18/photography-at-adobe-max-2022-new-features-for-adobe-lightroom-and-more
- A4 Adobe Learn：Adaptive presets https://www.adobe.com/learn/lightroom-cc/web/optimize-workflow-with-adaptive-presets
- A5 Photoshop 說明：Select Subject 裝置／雲端模式（摘要）https://helpx.adobe.com/photoshop/desktop/make-selections/automatic-color-based-selections/improved-select-subject-and-remove-background-results.html
- A6 Adobe Blog 2023-04-18 Denoise demystified https://blog.adobe.com/en/publish/2023/04/18/denoise-demystified ；擷取：`.claude/read/material/adobe-denoise-demystified/index.md`
- A7 Lightroom 說明：Generative Remove FAQ（摘要）https://helpx.adobe.com/lightroom/desktop/using/generative-remove-faq.html ；Lightroom Classic Remove tool（摘要）https://helpx.adobe.com/lightroom-classic/desktop/process-and-develop-photos/remove-tool.html
- A8 Lightroom 說明：Lens Blur（摘要）https://helpx.adobe.com/lightroom/web/edit-photos/apply-effects/apply-lens-blur.html
- A9 Adobe MAX 2025 新聞稿 https://news.adobe.com/news/2025/10/adobe-max-2025-news ；Lightroom Classic 15.0 公告 https://community.adobe.com/announcements-673/from-max-2025-new-features-in-lightroom-classic-15-0-983824
- A10 Adobe Blog 2024-12-12 移除窗戶反光 https://blog.adobe.com/en/publish/2024/12/12/removing-window-reflections-adobe-camera-raw
- A11 Adobe Blog 2026-08-27 Photoshop 新功能（AI Assisted Editor、Instruct Edit with Masks、Light Adjustment Layer）https://blog.adobe.com/en/publish/2026/08/27/new-photoshop-innovations-bring-you-more-choice-control-at-every-stage-of-your-creative-process
- A12 Photoshop 生成式功能疑難排解（需連網）https://helpx.adobe.com/photoshop/kb/troubleshoot-generative-ai-features.html
- A13 Firefly Services Lightroom API：Auto Tone https://developer.adobe.com/firefly-services/docs/lightroom/guides/auto-tone/
- L1 Skylum 新聞稿：生成式功能用 Stable Diffusion、走雲端 https://skylum.com/newsroom/luminar-neo-releases-generative-ai-technology-in-its-awardwinning-photo-editing-software
- L2 Skylum 說明：GenExpand https://support.skylum.com/extra-tools/generative-tools/genexpand.md
- L3 Skylum 說明：Enhance AI https://support.skylum.com/editing-tools/essential-tools/enhance-ai.md ；Sky AI https://support.skylum.com/editing-tools/landscape-tools/sky-ai.md ；Skin AI https://support.skylum.com/editing-tools/portrait-tools/skin-ai.md
- L5 Relight AI（只有二手：imaging-resource／picturecorrect，未找到 Skylum 官方頁）
- P1 Photomator 使用手冊：ML Enhance https://support.pixelmator.com/photomator-user-guide/ai-editing-tools/ml-enhance
- P2 Pixelmator Blog 2019-12-17 ML Super Resolution（摘要）https://www.pixelmator.com/blog/2019/12/17/all-about-the-new-ml-super-resolution-feature-in-pixelmator-pro/
- S1 Imagen AI 說明：Personal AI Profile 需求（摘要）https://support.imagen-ai.com/hc/en-us/articles/6069763238289 ；回傳 XMP（摘要）https://support.imagen-ai.com/hc/en-us/articles/36055702902045
- S2 Aftershoot 說明：建立 Professional AI Profile https://support.aftershoot.com/en/articles/9189902-how-to-build-your-first-professional-ai-profile
- S3 Evoto Trust Center https://www.evoto.ai/privacy-center
- O1 Capture One：Smart Adjustments（摘要）https://support.captureone.com/hc/en-us/articles/7129920998045-Smart-Adjustments ；16.6 Release Notes https://support.captureone.com/hc/en-us/articles/26809869126557-Capture-One-16-6-0-Release-Notes

**學術**
- R1 JarvisArt（arXiv 2506.17612，NeurIPS 2025）https://arxiv.org/html/2506.17612 ；程式 https://github.com/LYL1015/JarvisArt （擷取：`.claude/read/material/jarvisart-readme/index.md`）；權重 https://huggingface.co/JarvisArt/JarvisArt-1208
- R2 JarvisEvo（arXiv 2511.23002）https://github.com/LYL1015/JarvisEvo 、https://huggingface.co/JarvisEvo/JarvisEvo
- R3 MonetGPT（arXiv 2505.06176，SIGGRAPH 2025）https://arxiv.org/html/2505.06176 ；程式 https://github.com/niladridutt/monetgpt （擷取：`.claude/read/material/monetgpt-readme/index.md`）；權重 https://huggingface.co/niladridutt/monetGPT
- R4 PhotoArtAgent（arXiv 2505.23130）https://arxiv.org/html/2505.23130v1
- R5 RetouchLLM（arXiv 2510.08054）https://arxiv.org/html/2510.08054v2
- R6 RetouchIQ（arXiv 2602.17558，CVPR 2026）https://arxiv.org/html/2602.17558v1
- R7 PerTouch（arXiv 2511.12998）https://github.com/Auroral703/PerTouch
- R8 4KAgent（arXiv 2507.07105）https://github.com/taco-group/4KAgent
- R9 VLM-CC（arXiv 2605.19613，CVPR 2026）https://arxiv.org/html/2605.19613 ；https://github.com/NothingIknow/VLM-CC
- R10 ColorBench（arXiv 2504.10514，摘要）https://arxiv.org/html/2504.10514v3
- R11 RetouchGPT（AAAI 2025，摘要）https://ojs.aaai.org/index.php/AAAI/article/view/32980
- R12 AesFormer（arXiv 2605.22126）https://arxiv.org/abs/2605.22126
- T1 Image-Adaptive 3D LUT https://github.com/HuiZeng/Image-Adaptive-3DLUT
- T2 AdaInt https://github.com/ImCharlesY/AdaInt ；T3 SepLUT https://github.com/ImCharlesY/SepLUT
- T4 HDRNet https://github.com/google/hdrnet ；T5 CSRNet https://github.com/hejingwenhejingwen/CSRNet ；T6 MIT-Adobe FiveK https://data.csail.mit.edu/graphics/fivek/
- W1 FC4 https://github.com/yuanming-hu/fc4
- W2 WB_sRGB https://github.com/mahmoudnafifi/WB_sRGB ；W3 Deep White-Balance Editing https://github.com/mahmoudnafifi/Deep_White_Balance ；W4 Mixed-illuminant WB https://github.com/mahmoudnafifi/mixedillWB ；W5 C5 https://github.com/mahmoudnafifi/C5
- W6 WBFlow https://github.com/ChunxiaoLe/WBFlow ；W7 ABC-Former https://github.com/ytpeng-aimlab/ABC-Former
- W8 Exposure Correction https://github.com/mahmoudnafifi/Exposure_Correction

**開源修圖軟體**
- D1 darktable Blog：Meet the new AI tools in darktable 5.6 https://www.darktable.org/2026/06/meet-darktable-5.6-ai-tools/ ；擷取：`.claude/read/material/darktable-5-6-ai-tools/index.md`
- D2 darktable 5.6.0 release https://github.com/darktable-org/darktable/releases/tag/release-5.6.0 ；5.6.1 https://github.com/darktable-org/darktable/releases/tag/release-5.6.1
- D3 digiKam 8.0 https://www.digikam.org/news/2023-04-16-8.0.0_release_announcement/ ；8.7 https://www.digikam.org/news/2025-06-30-8.7.0_release_announcement/ ；9.1 https://www.digikam.org/news/2026-06-07-9.1.0_release_announcement/ ；LLM 搜尋 https://www.digikam.org/news/2026-08-20-advanced_search_improvements_with_llm/
- D4 RawTherapee 5.13 Release Notes https://raw.githubusercontent.com/RawTherapee/RawTherapee/5.13/RELEASE_NOTES.txt ；D5 ART releases https://github.com/artraweditor/ART/releases

**ComfyUI 生態與載體**
- K1 ComfyUI 核心 nodes.py（LoadImage／SaveImage）https://github.com/comfyanonymous/ComfyUI/blob/master/nodes.py ；SaveImageAdvanced https://docs.comfy.org/built-in-nodes/SaveImageAdvanced
- K2 ComfyUI App Mode https://docs.comfy.org/interface/app-mode
- K3 Inpaint-CropAndStitch https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch
- K4 IC-Light https://github.com/lllyasviel/IC-Light ；huchenlei/ComfyUI-IC-Light https://github.com/huchenlei/ComfyUI-IC-Light
- K5 AfterDark Live Grade https://github.com/hackafterdark/ComfyUI-HackAfterDark-Nodes
- K6 Olm ImageAdjust https://github.com/o-l-l-i/ComfyUI-Olm-ImageAdjust
- K7 ComfyUI_LayerStyle https://github.com/chflame163/ComfyUI_LayerStyle ；ComfyUI-Image-Filters https://github.com/spacepxl/ComfyUI-Image-Filters ；ComfyUI_essentials（只維護）https://github.com/cubiq/ComfyUI_essentials
- K8 Qwen-Image-Edit 位移問題 https://lilting.ch/en/articles/qwen-image-edit-pixel-perfect-referencelatent ；LockPixel https://github.com/tori29umai0123/ComfyUI-QwenImageEdit-LockPixel ；Qwen-Image-Edit-2511 模型卡 https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- K9 SeedVR2 節點 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler ；ComfyUI-SUPIR https://github.com/kijai/ComfyUI-SUPIR
- K10 ComfyUI-SAM3 https://github.com/PozzettiAndrea/ComfyUI-SAM3
- K11 comfyui-photoshop issue #67（攝影師回饋）https://github.com/NimaNzrii/comfyui-photoshop/issues/67 ；SD-PPP https://github.com/zombieyang/sd-ppp
- K12 ComfyScript https://github.com/Chaoses-Ib/ComfyScript ；SwarmUI https://github.com/mcmonkeyprojects/SwarmUI ；ViewComfy https://github.com/ViewComfy/ViewComfy
- K13 ICC／metadata 補丁節點 https://comfy.icu/extension/EricRollei__AAA_Metadata_System
- C4 RapidRAW https://github.com/CyberTimon/RapidRAW ；擷取：`.claude/read/material/rapidraw-readme/index.md`
- C5 RapidRAW-AI-Connector https://github.com/CyberTimon/RapidRAW-AI-Connector ；擷取：`.claude/read/material/rapidraw-ai-connector-readme/index.md`；issue #548 https://github.com/CyberTimon/RapidRAW/issues/548 ；#739 https://github.com/CyberTimon/RapidRAW/issues/739 ；#1421 https://github.com/CyberTimon/RapidRAW/issues/1421
- C6 Krita AI Diffusion https://github.com/Acly/krita-ai-diffusion ；擷取：`.claude/read/material/krita-ai-diffusion-readme/index.md`；ComfyUI 設定需求 https://docs.interstice.cloud/comfyui-setup/
- C7 comfyui-tooling-nodes https://github.com/Acly/comfyui-tooling-nodes ；擷取：`.claude/read/material/comfyui-tooling-nodes-readme/index.md`
- C8 IOPaint（2025-08-13 封存）https://github.com/Sanster/IOPaint ；InvokeAI https://github.com/invoke-ai/InvokeAI

---

## 1. 商業產品：哪些是參數式、哪些是生成式

分類定義：**參數式**＝AI 算出滑桿值或遮罩，再用傳統影像處理執行，結果留在滑桿／遮罩上可改；**ML 像素**＝神經網路直接輸出像素但不是生成模型（去噪、放大、去反光）；**生成式**＝擴散／生成模型重畫像素。

| 產品／功能 | 類型 | 本機／雲端 | 結果可再調？ | 來源 |
|---|---|---|---|---|
| Lightroom Auto／Auto Settings | 參數式（Sensei 神經網路，比對「數萬張專業修過的照片」後設定基本面板滑桿） | 各平台都有 | 是，滑桿看得到 | A1；API 另有 Auto Tone 端點 A13 |
| Adobe Adaptive 描述檔 | 參數式但**藏在描述檔裡**：「效果像是 AI 幫你改了曝光、陰影、亮部、混色器、曲線…但這些控制項仍停在中性位置」；只有一個 Amount | 未說明 | 只有強度＋其餘滑桿照常可調 | A2 |
| AI 遮罩（主體／天空／人物／物件／背景／風景） | 參數式（分割＋一般局部調整） | 多半本機；Android 低記憶體機型可走雲端；Photoshop 可選裝置或雲端（雲端「較準」） | 是，可加減修遮罩 | A3、A5（摘要） |
| Adaptive presets（人像／天空／主體） | 參數式：每張照片重新產生 AI 遮罩，遮罩內套固定滑桿值；有 Preset Amount | 同遮罩 | 是 | A3、A4 |
| Denoise／Raw Details／Super Resolution | ML 像素（「深度卷積網路」，以數百萬對高噪／低噪圖塊訓練；在 Bayer 馬賽克上一起去噪＋解馬賽克；用 GPU Tensor Core） | 本機 | 產生新 DNG，「可以像其他 RAW 一樣編輯」，原本的調整會帶過去 | A6 |
| Lens Blur | 參數式＋ML：AI 深度圖＋渲染散景；可看深度圖、手刷修正 | 未查到 | 是 | A8（摘要） |
| 去反光（Distraction Removal: Reflections） | ML 像素，明講「是 AI 但不是生成式 AI」「不會產生原圖沒有的物件」；有 −100～100 的 Amount | 未查到 | 有強度 | A10 |
| 去灰塵（LrC 15） | AI 偵測＋內容感知移除（非生成式） | — | 每個點可刪可重算 | A9 |
| Generative Remove | **生成式**（Firefly） | **雲端**，需連網；一般 Remove／Heal／Clone 可離線 | 結果是一個修補點 | A7（摘要） |
| Assisted Culling | 只分析，寫旗標／星等，不動像素 | — | 條件可開關、有靈敏度 | A9 |
| Photoshop Generative Fill／Expand／Harmonize | **生成式**，**雲端** | 需連網 | 結果放在生成圖層、3 個變體 | A12、A9 |
| Photoshop 2026 AI Assisted Editor／Instruct Edit with Masks | 生成式（Firefly Image 5），只改遮罩範圍；結果是「生成圖層」 | 雲端（推論，Firefly） | 非破壞性圖層 | A11 |
| Luminar Enhance AI（Accent AI） | 參數式「巨集滑桿」：一個滑桿背後「十幾個控制項」 | 本機（推論，未標雲端） | 只有強度，內部參數不公開 | L3 |
| Luminar Sky AI | 分割＋貼上天空圖庫，非生成式 | 本機（推論） | 有遮罩、重打光滑桿 | L3 |
| Luminar Skin AI | 皮膚偵測＋平滑，滑桿控制 | 本機（推論） | 遮罩可改 | L3 |
| Luminar Relight AI | 深度圖＋前景／背景亮度滑桿 | — | 是 | L5（二手） |
| Luminar GenErase／GenSwap／GenExpand | **生成式**，「使用 Stable Diffusion 模型，透過雲端處理」 | **雲端**；GenExpand 最多擴 25% | 可切換變體，輸出 TIF | L1、L2 |
| Pixelmator／Photomator ML Enhance | 參數式：以數百萬對「修壞／專業修過」配對訓練，設定光線、對比、白平衡、色相飽和、色彩平衡、選擇性顏色；每項旁邊的「ML」可單獨關掉 | 本機（Core ML） | 是 | P1 |
| Pixelmator ML Super Resolution／Denoise | ML 像素，29 層 CNN，刻意做小以內建在 App 裡 | 本機 | — | P2（摘要） |
| Imagen AI | 參數式：個人 AI Profile 至少 2,000 張修過的照片（建議 3,000+）；上傳小型預覽，伺服器端算完回傳「一個很小、含所有滑桿調整的文字檔」（XMP） | **雲端** | 是，在 Lightroom 裡繼續改 | S1（摘要） |
| Aftershoot Edits | 參數式：至少 2,500 張（建議 5,000+），學 Tone、白平衡、Presence、Detail、HSL、曲線 | 訓練在雲端，訓練完套用「不再需要網路」 | 是 | S2 |
| Evoto | 「本機專案」也是用 Evoto 雲端的演算法與算力；只傳縮圖、處理完立即刪除 | **雲端** | 滑桿 | S3 |
| Capture One Smart Adjustments | 參數式：依參考圖對齊曝光與白平衡（以臉與膚色為準） | 本機 | 是 | O1（摘要） |
| Capture One AI 遮罩、Retouch Faces | 分割＋圖層調整；修臉有滑桿；16.7.2 加 NPU 加速（推論為本機） | 本機（推論） | 是 | O1（摘要） |

### 商業產品的共通模式（有來源支持）

1. **全域調色＝AI 預測現有滑桿的值**，滑桿看得見、可再改（Adobe Auto、ML Enhance、Smart Adjustments、Imagen、Aftershoot）[A1][P1][O1][S1][S2]。變形是「隱藏參數＋一個強度滑桿」（Adobe Adaptive 描述檔、Luminar Accent AI）[A2][L3]。
2. **局部調整＝AI 分割或深度圖＋傳統調整**（遮罩、Adaptive presets、Lens Blur、Relight、Sky、Skin）[A3][A8][L3]。
3. **畫質修復＝ML 像素、多半本機**，烘成新檔或新層，原本的參數式編輯照樣能做（Denoise 產新 DNG）[A6][A10][P2]。
4. **生成式只用在移除、填補、擴圖、替換、合成，而且都是雲端**，每家都保留非生成式的本機替代（Adobe Remove／Heal 可離線、去反光明講非生成式）；生成結果另放一層或一個修補點，不混進參數式流程 [A7][A10][A12][L1]。
5. **個人風格學習要大量已修好的照片**（Imagen 2,000、Aftershoot 2,500、Evoto 調色約 200 張（摘要））[S1][S2]。
6. **為什麼保留可調**（廠商自己的說法）：Adobe Adaptive：「攝影師心裡可能想要稍微不同的結果，可以用 Camera Raw 的所有控制項微調」[A2]；Photoshop 2026：保留「定義你技藝的判斷力」，生成結果放在自己的圖層 [A11]；Photoshop 助理：可在對話與「滑桿這類手動工具」之間切換，「給專業創作者更多控制」[A9]；Pixelmator：可逐項關掉 ML [P1]。廠商沒有更深的技術理由，講的都是使用者控制、非破壞性、能接回既有流程。

---

## 2. 學術與開源

### 2.1 VLM／LLM 產生修圖參數或操作

| 研究 | 輸出 | 底模／訓練 | 釋出 | 16GB 本機 | 自述弱點 | 來源 |
|---|---|---|---|---|---|---|
| JarvisArt（NeurIPS 2025） | Lightroom 200+ 工具的 Lua／XMP（含 6 種局部遮罩），經「Agent-to-Lightroom」協定送進 Lightroom Classic 執行 | Qwen2.5-VL-7B；CoT SFT＋GRPO-R；MMArt 55K | 程式、權重、資料都有；**JarvisArt 非商用授權** | 8B BF16 約 17GB，要量化（推論）；**需要 Lightroom Classic 才能出圖** | 推理時「做出假設調整（如 highlight+5）卻看不到對應視覺結果」，沒有逐步視覺回饋 | R1 |
| JarvisEvo（CVPR 2026） | Lightroom＋Qwen-Image-Edit；編修者＋評估者自我演化 | Qwen3-VL 8B | 權重有；README 寫非商用、HF 標 apache-2.0（衝突） | 同上 | — | R2 |
| MonetGPT（SIGGRAPH 2025） | 33 種程序式操作，三階段：光線（blacks／contrast／exposure／highlights／whites／shadows）→ saturation／**temperature／tint** → 8 色域 HSL；範圍 −100～+100 | Qwen2-VL-7B，DoRA 微調；8K 張專家修圖；用「解視覺謎題」產生推理資料 | **MIT**，權重＋程式都有；執行端約 80% NumPy、約 20% 需要 GIMP 2.10 | 7B 量化可放進 16GB（推論）；**不需要 Lightroom** | 只做全域、偶爾過飽和、帶修圖師偏好；直接問 Gemini 2.0「結果很差」 | R3 |
| PhotoArtAgent | Lightroom 參數（基本＋白平衡＋HSL），反覆反思 | **免訓練**，GPT-4o 提示詞 agent | 沒找到程式 | 可用本機 VLM 照論文重做（推論） | 少見場景會幻覺 | R4 |
| RetouchLLM | Python 程式碼，7 種操作（含 temperature） | **免訓練**，「視覺評論員」＋「程式產生器」，用參考圖＋CLIP 挑結果 | 程式只在補充資料 | 同上 | 評論員會漏調整、產生的程式有時跑不起來 | R5 |
| RetouchIQ（CVPR 2026） | Lightroom 相容參數 | Qwen2.5-VL-7B，190K SFT＋通用 reward model RL | 未見釋出 | — | 發現 GPT-5 等通用 MLLM「傾向過度編修」、零樣本「難以推出協調自然的參數組合」 | R6 |
| PerTouch（AAAI 2026） | **像素**（擴散模型把參數圖轉成影像）＋VLM＋SAM | — | 權重在 HF | — | — | R7 |
| 4KAgent（NeurIPS 2025） | 調度修復／超解析工具（DiffBIR、Restormer、CodeFormer…），不做調色 | — | Apache-2.0 | — | — | R8 |
| RetouchGPT（AAAI 2025） | 人臉皮膚瑕疵修飾網路，輸出像素，不是參數式 | — | — | — | — | R11（摘要） |
| AesFormer（ICML 2026） | 構圖、視角、姿勢重建，不是調色 | — | — | — | — | R12 |

**通用 VLM 判斷顏色／白平衡弱的證據：**
- VLM-CC：直接叫 VLM 回歸光源 RGB 沒效，改成問「殘留色偏方向（紅／綠／藍）」再反覆修正，而且要 LoRA 微調才行；並引 ColorBench 說 VLM 對顏色「數值準確度有限」[R9]。
- ColorBench：測 32 個 VLM，顏色理解「大致被忽略」，CoT 有幫助 [R10]（摘要）。
- MonetGPT：Gemini 2.0 直接做結果很差 [R3]；RetouchIQ：GPT-5 會過度編修 [R6]。
- → 這和本專案實驗（`issues/18`：白平衡判錯、對比都加、黑色都壓）一致。**推論**：這是通用 VLM 的結構性弱點，換更大的通用模型不一定能解。

### 2.2 學習式調色（輸出像素或 LUT，不是滑桿）

- Image-Adaptive 3D LUT：參數不到 600K，Titan RTX 上 4K 一張不到 2 ms；附預訓練模型，Apache-2.0 [T1]。
- AdaInt、SepLUT：附 FiveK／PPR10K 預訓練，Apache-2.0，但要自訂 CUDA op（Windows 編譯可能麻煩）[T2][T3]。
- HDRNet：手機上毫秒級、1080p 即時；官方 TensorFlow、repo 已封存 [T4]。CSRNet：約 36K 參數，附 FiveK expert C 預訓練 [T5]。
- 共同點：學的是 FiveK 某位修圖師（通常 C）的風格 [T6]，輸出像素／LUT，**沒有滑桿值**，所以不能「接著在滑桿上微調」。**推論**：可當「AI 自動調色」的一個帶強度的 LUT 層，但跟本專案「AI 給滑桿、程式執行」的原則不合，優先度低。

### 2.3 白平衡／光源估計（補 LLM 判錯白平衡）

| 模型 | 輸入 | 輸出 | 授權 | 備註 | 來源 |
|---|---|---|---|---|---|
| FC4（CVPR 2017） | **線性 RAW** | 光源 RGB | MIT | TF1／Python 2.7，不適用 sRGB JPEG | W1 |
| WB_sRGB（CVPR 2019） | sRGB | 校正後影像（KNN 非線性色彩映射） | 研究用 | Matlab／Python | W2 |
| Deep White-Balance Editing（CVPR 2020） | sRGB | AWB／鎢絲／陰天三種**影像** | 非商用 | PyTorch 預訓練 | W3 |
| Mixed-illuminant AWB（WACV 2022） | sRGB（可自動產生需要的預設白平衡版本） | 影像＋權重圖 | 研究用 | 混光場景 | W4 |
| C5（ICCV 2021） | RAW 直方圖＋同相機其他圖 | 光源 RGB | Apache-2.0 | 需 RAW | W5 |
| WBFlow（2024） | sRGB | 校正影像 | 未標 | 可逆 flow | W6 |
| ABC-Former（CVPR 2025） | sRGB | 校正影像（另有混光版） | 未標 | Transformer＋Lab／RGB 直方圖 | W7 |
| VLM-CC（CVPR 2026） | RAW（需相機黑位與 CCM） | 迭代修正 | Apache-2.0 | 實際只能用在它校正過的相機 | R9 |

重點：**沒有一個 sRGB 模型直接吐光源或 Temp/Tint，全部輸出校正後影像** [W2][W3][W4][W6][W7]。**推論**可行做法：在 JPEG 上跑 Deep-WB（AWB 輸出）或 ABC-Former → 用「原圖／校正圖」在中性或全體像素的比值回推各通道增益 → 換算 CCT／Duv → 對應到本專案的 Temp/Tint 實作。這些模型只有幾 MB 到幾十 MB，16GB 卡毫無壓力；JPEG 上只是近似值，要用校正集驗證。RAW 階段則可用 C5 直接拿光源 RGB [W5]。學習式自動曝光（Afifi Exposure Correction）只有 Matlab、研究用 [W8]。

### 2.4 darktable／RawTherapee／digiKam

- **darktable 5.6.0（2026-06-21）**第一次有 AI 功能 [D1][D2]：
  - 選用的 AI 子系統，用 ONNX Runtime 在本機 CPU／GPU 跑（CUDA、DirectML、ROCm、CoreML、OpenVINO）。
  - **AI object mask**：點一下就變成向量遮罩（SAM2.1／SegNext），可以再精修。
  - **neural restore**：RAW 去噪（輸出 DNG）、去噪、放大（RealPLKSR、BSRGAN）。官方說它「不在像素管線裡」，處理完寫回成新影像；放大要放在「交件前最後一步」。
  - 每種 AI 任務都定義了 ONNX 介面（輸入輸出形狀、前後處理），符合介面的模型都能自己裝；「這個版本我們沒有訓練任何一個模型」。
  - 沒有生成式，也沒有 LLM。
  - 5.6.1 修了 Windows ONNX 自動偵測當機 [D2]。
- **digiKam**：8.0 有深度學習美感偵測、人臉流程 [D3]；8.7 的 OpenCV DNN 可走 CUDA [D3]；本機 LLM 自然語言搜尋已進開發版 [D3]。沒有 AI 調色。
- **RawTherapee 5.13（2026-07）、ART**：發布說明裡沒有 AI／ONNX 功能 [D4][D5]。
- **推論**：開源 RAW 軟體跟商業產品同一個路線，AI 只用在遮罩與畫質修復，調色還是參數式；darktable「定義任務介面、模型可抽換」的做法值得照抄。

---

## 3. ComfyUI 生態的相片修圖

### 3.1 現有節點包

- **調色**：
  - ComfyUI_LayerStyle（MIT，約 3.2k 星）有 LUT Apply（.cube）、Levels、AutoAdjust、ColorBalance、ColorTemperature、Exposure、Film，也有 SAM2／BiRefNet／Florence2／PersonMask 遮罩節點，**全部都是排隊執行** [K7]。
  - ComfyUI-Image-Filters 的 AdaIN 節點明講是「用來去掉高 denoise 造成的色偏」[K7]。
  - cubiq ComfyUI_essentials 2025-04 起只做維護，作者說他「已不再把 ComfyUI 當主要工具」[K7]。
- **即時滑桿**：
  - 只有少數節點做得到：AfterDark Live Grade（先跑一次，之後瀏覽器 shader 以「60 FPS」重畫，宣稱和 PyTorch 結果「1:1 一致」）[K5]；Olm ImageAdjust（「要先跑一次 graph 才會更新」，原始碼可看但禁止散布）[K6]。
  - **兩者都是同一套算式寫兩份（JS shader＋Python）**，對齊要靠人工維護。
- **Lightroom XMP preset**：
  - GitHub 上搜「ComfyUI-LightroomXMP」是 0 筆，本 repo 那份是自製、還沒公開的。
  - 有一個 ComfyAI 雲端頁面記載「LRTemplate Loader」節點，但找不到原始碼（https://comfyai.run/documentation/LRTemplate%20Loader）。
  - **推論**：ComfyUI 生態沒有成熟的 Lightroom preset 引擎可以直接接。
- **IC-Light**：
  - 底模是 SD1.5，FC 版用文字、FBC 版用背景當條件；附帶的 BRIA RMBG 是非商用授權 [K4]。
  - huchenlei 版建議接「DetailTransfer 節點來保留高頻細節」，等於承認重打光會改到細節 [K4]。
  - kijai 版 2025-05 後就沒更新了。
- **指令式修圖**：
  - Qwen-Image-Edit 每次都重新編碼整張圖，沒動的地方也會「平移、縮放、偏移」（參考圖被縮放到約 1MP），要用 LockPixel 這類節點修正 [K8]。
  - 官方 2511 版模型卡只說「減輕」影像漂移 [K8]。
  - Flux Kontext 也有同類問題，社群另外做了幾何對齊節點（https://comfy.icu/node/RennartPixelDriftFix）。
  - 常見解法是 Inpaint-CropAndStitch：只把遮罩區域貼回原圖，再加 AdaIN／LAB 對色 [K3]。這和本專案 `issues/16` 的觀察一致：Qwen 整張位移、混合後出現重影。
- **遮罩**：
  - ComfyUI-SAM3（文字提示分割，2026-08 還有更新）[K10]、kijai segment-anything-2、Florence2、BiRefNet 都還在維護。
  - GroundingDINO＋SAM 那個包 2024-07 後就停了。
- **人像**：
  - 有頻率分離、SkinRetouching、ReActor 這類節點。
  - 找不到真正互動式的液化節點；LivePortrait 類 2024-08 後停更。
- **放大**：
  - SeedVR2（Apache-2，約 2.9k 星，內建 LAB／wavelet 等色彩校正）[K9]。
  - ComfyUI-SUPIR 已經併入核心、外掛版只修 bug，SUPIR 權重是非商用 [K9]。

### 3.2 拿 ComfyUI 當相片編輯器：優缺點

- **缺點（有來源）**：
  - 核心 LoadImage 會 `exif_transpose` → `convert("RGB")` → 除以 255，沒處理 ICC，EXIF 也不帶過去；SaveImage 截成 uint8，只寫 prompt／workflow [K1]。
  - SaveImageAdvanced 有 16-bit PNG（只有 sRGB）、EXR、10-bit AVIF，沒有 TIFF，也沒寫 ICC [K1]。ICC／metadata 要靠第三方節點補 [K13]。
  - App Mode（2026-03）還是「排隊、按 Run」，分享連結只能用在 Comfy Cloud [K2]。
  - 攝影師在 comfyui-photoshop #67 說「非常有幫助」，但也回報群組切換壞掉、中日韓文字輸入壞掉、按鈕蓋住圖 [K11]。
  - 節點包常常停更（essentials、IC-Light、LivePortrait、segment_anything）[K4][K7]。
- **優點（有來源）**：模型涵蓋最廣，分割、修圖、放大可以接在同一張圖裡；批次、headless、可重現 [K3][K9][K10]。
- 找不到「有人把 ComfyUI 當日常相片編輯器」的正面一手案例；reddit 被擋，這點沒能直接確認（見不確定點）。

---

## 4. 載體比較

### 4.1 把 ComfyUI 當後端的前端案例

- **Krita AI Diffusion**（GPL-3，約 10.7k 星）：
  - 客戶端用 Python 自己組 workflow，透過 `ws://…/ws?clientId=` 連線，用 `object_info` 檢查需要的節點有沒有裝，再經 `/api/etn/image/{id}` 取回結果。
  - 需要先裝 controlnet_aux、IPAdapter_plus、inpaint-nodes、tooling-nodes 這幾個節點包 [C6]。
  - 可以接現有的本機 ComfyUI（README：「plugin uses ComfyUI as backend」）。
- **comfyui-tooling-nodes**：專門「把 ComfyUI 當外部工具的後端」，提供 Base64 載圖、WebSocket 傳圖、記憶體快取 [C7]。
- **SD-PPP**（Photoshop UXP 外掛）、**SwarmUI**（C# 伺服器自己產生 Comfy workflow）、**ViewComfy**（Next.js，讀 `workflow_api.json`）[K11][K12]。
- **ComfyScript**：「real mode」可以在同一個程序裡直接把 ComfyUI 節點當 Python 函式呼叫 [K12]。

### 4.2 開源本機修圖 App

- **RapidRAW**（AGPL-3，v1.6.4 2026-09-17，持續更新）[C4]：
  - Tauri/Rust 後端＋React 介面＋WGPU 渲染（README 有「Instant image rendering & real-time histogram」「Real-time mask overlay」）。
  - 本機 AI：SAM 2（主體）、U-2-Net（天空／前景）、Depth Anything v2（深度遮罩）、LaMa（輕量本機移除）、CLIP（自動標籤）、AI Lens Blur。
  - 支援 .cube 等 LUT、XMP metadata 讀寫。
  - 生成式修圖另外走 **RapidRAW-AI-Connector**（Python FastAPI）：完整影像只送 ComfyUI 一次，之後只傳遮罩＋提示詞，回傳裁好的修補區塊 [C5]。
  - 實際問題：大圖會 OOM、出現「白色色塊」，維護者自己說整合「還在進行中、效果不太好」（#548）；使用者被三段連接（App→Connector→ComfyUI）的設定搞混（#739）[C5]。
  - #1421 指出編修狀態本來就是宣告式 JSON（`Adjustments` 73 個欄位），已經做出 `--adjustments` 的 headless 匯出，提議再訂版本化的 JSON Schema；但明確把「不做 LLM」列為非目標 [C5]。
- **IOPaint**（前身 lama-cleaner，Python＋Vite 網頁前端）2025-08 已封存 [C8]。InvokeAI 用自己的節點引擎，不是 ComfyUI [C8]。
- **能「讓 LLM 建議修圖參數」的開源 App：沒找到**。最接近的是 JarvisArt，但它要接 Lightroom [R1]。

### 4.3 三種載體比較

| | (a) ComfyUI 節點 | (b) 獨立本機 App（Python 後端＋Web 前端，呼叫 llama-server，擴散模型才呼叫 ComfyUI API） | (c) 核心函式庫，兩邊都包 |
|---|---|---|---|
| 即時滑桿 | 排隊執行；即時要再寫一份 JS shader [K5][K6] | 自己掌控渲染迴圈（本專案原型已經到 30 ms）| 同 (b)，預覽走函式庫 |
| 色彩／檔案 | 核心 8-bit、沒有 ICC／EXIF，要補節點 [K1][K13] | 自己處理 16-bit、ICC、EXIF（推論） | 同 (b) |
| 模型取用 | 最方便 | 經 API 呼叫，要維護 workflow JSON／節點 ID（RapidRAW Connector 要改 `engine.py` 裡的節點 ID）[C5]；Krita 用 `object_info` 檢查節點 [C6] | 同 (b)；ComfyUI 節點可以直接 import 函式庫 |
| GPU 16GB | ComfyUI 自己管 | llama-server 和 ComfyUI 不能同時常駐，要切換（推論，依本 repo CLAUDE.md） | 同 (b) |
| 前例 | 只有零星調色節點 | RapidRAW、Krita、SD-PPP、SwarmUI | ComfyScript（節點當函式）、RapidRAW #1421（版本化 schema＋headless 渲染器）、darktable ONNX 任務介面 [K12][C5][D1] |
| 主要成本 | 使用者體驗受限、節點包常停更 | 多一個要維護的服務、ComfyUI 版本變動時要跟著改 | 一開始要定 schema、版本、往返測試 |

---

## 5. 對本專案的建議

### 5.1 功能優先序（參數式優先，生成式只做局部）

1. **調色引擎＋preset＋強度**（進行中）：這就是商業產品的「全域＝參數式」主幹 [A1][A2]。preset 強度滑桿對應 Adobe 的 Preset Amount／Profile Amount [A2][A3]。
2. **AI 遮罩**（主體、天空、人物、背景）＋「preset 只套在遮罩內」（＝Adaptive preset）[A3][A4]。本機已有 BiRefNet，ComfyUI 生態有 SAM3 [K10]，RapidRAW 用 SAM2／U-2-Net [C4]，darktable 用 SAM2.1 [D1]。遮罩要能手動加減修（各家都有）。**推論**：這是投入少、效益最明確的一項，也是 `issues/17` 天空對位的延伸。
3. **「自動」＝LLM 給滑桿初值，但要加三道保護**：
   - (a) **白平衡不交給 LLM**：程式先量（灰世界、白點這類傳統估計）或用專用 sRGB 白平衡模型（Deep-WB、ABC-Former），把增益換算成 Temp/Tint，當成 LLM 的已知條件或直接覆蓋 [W3][W7][R9]（推論）。這延續 `issues/08`、`issues/18` 的決定。
   - (b) **規則檢查**，壓住「對比都加、黑色都壓」的套路，呼應 RetouchIQ 說的「過度編修」[R6]。
   - (c) **渲染→再看→修正的迴圈**：JarvisArt 自承缺少視覺回饋 [R1]，PhotoArtAgent／RetouchLLM 都是反覆修正 [R4][R5]；本專案渲染只要約 30 ms，讓 LLM 看自己調出來的結果再修一輪，成本很低（推論）。
   - 選配：若要更穩，**MonetGPT（MIT、7B、輸出含 temperature／tint 的程序式操作）**是唯一能在本機跑、授權寬鬆、不需要 Lightroom 的訓練過模型；但操作要對應到本專案的滑桿，執行端依賴 GIMP，要先試 [R3]。JarvisArt 雖然強，但非商用而且綁 Lightroom，不適用 [R1]。
4. **ML 去噪／放大**：當成獨立的一步，處理完烘成新檔（對應 Adobe Denoise 的 DNG 模式、darktable neural restore）[A6][D1]。本機已有 SeedVR2；去噪可參考 darktable 用的 NIND 系列 ONNX 小模型（推論，未在本機驗證）。放大放在最後一步 [D1]。
5. **移除雜物**：預設用 LaMa（非生成式、本機）[C4]，大面積才用擴散模型，結果只貼回遮罩區域（crop-and-stitch）[K3][C5]。跟商業產品一樣「非生成式本機＋生成式加值」[A7]。
6. **景深模糊／重打光**：深度圖（Depth Anything v2）＋參數式調整 [A8][C4][L5]。IC-Light 會改細節、底模是 SD1.5，不建議 [K4]。
7. 之後再說：選片／評分 [A9]、個人風格學習（要上千張修好的照片）[S1][S2]、學習式 3D LUT [T1]。
8. **全畫面 Qwen 重畫當「補強」**：商業產品都沒這樣用，本專案也實驗失敗（`issues/16`）。建議降成實驗功能，或只留給局部（遮罩內）重畫。

### 5.2 載體建議

**建議 (c) 的做法、以 (b) 為主要形態：**

- **核心函式庫**：preset／參數 schema（版本化 JSON）＋torch GPU 渲染＋遮罩介面。LLM 只吐 schema JSON。照抄 RapidRAW #1421 的「宣告式編修狀態＋headless 渲染」與 darktable 的「任務介面固定、模型可換」[C5][D1]。
- **主要介面＝獨立本機 App**（Python 後端＋Web 前端）：
  - 預覽迴圈、16-bit／ICC／EXIF 都自己管。
  - 直接呼叫 llama-server。
  - 遮罩、白平衡、LaMa 這類小模型在 App 程序裡用 torch／ONNX 跑（推論）。
  - 只有擴散模型（Qwen 移除、SeedVR2）才透過 ComfyUI API 呼叫，走 Krita／RapidRAW Connector 的模式：用 `object_info` 檢查節點、圖只傳一次、只傳回修補區塊 [C5][C6][C7]。
- **ComfyUI 薄節點（選配、後做）**：同一個函式庫包成節點，滿足「9 相片編輯」入口與批次需求（`issues/07`）。ComfyScript 證明節點和函式庫可以共用 [K12]。
- **理由**：前三名的功能（調色、遮罩、自動）都不需要擴散模型；即時預覽與檔案品質是相片編輯的基本要求，而這正是 ComfyUI 最弱的地方 [K1][K2]。即時滑桿節點的前例都得把算式寫兩份 [K5][K6]，在 App 裡只要一份。
- **代價**：
  - 現有原型的預覽路由掛在 ComfyUI 伺服器上，要搬到 App 自己的伺服器（推論，工作量看 `issues/01` 原型的結構）。
  - 要處理 GPU 切換：App 用 llama-server 時 ComfyUI 不能常駐，可以沿用操作台的「同時只給一個」機制（推論）。
  - 要跟著 ComfyUI 的版本更新 workflow JSON [C5]。

---

## 6. 不確定點

1. **白平衡專用模型在使用者照片上準不準、換算成 Temp/Tint 的誤差多大**：所有 sRGB 模型都只輸出影像，回推增益的做法是推論，沒有人公開驗證過；Deep-WB 是非商用授權，ABC-Former 沒標授權（個人自用應該沒問題，但要確認）。這是 (b) 第 3 項最大的風險，建議用校正集做一次小實驗。
2. **ComfyUI 當日常相片編輯器的社群評價**：reddit 被擋，只有 GitHub issue 和節點 README 可引用，正面使用案例可能被低估。
3. **Adobe 部分功能是本機還是雲端**（Lens Blur、Adaptive 描述檔）、**Lightroom 移除人物是不是用生成式**、**Luminar Relight 的官方說明**：這幾項沒拿到一手來源。不影響「生成式只用在移除／擴圖」這個結論。
4. **MonetGPT 實際品質與整合成本**：要依賴 GIMP 2.10，操作集和 Lightroom 滑桿不完全一樣，論文的資料是專家修圖、不是 preset 風格。
5. **把預覽從 ComfyUI 搬到獨立 App 的工作量**：取決於 `issues/01` 原型和 ComfyUI 綁得多深，本研究沒有讀那份程式碼。
6. 部分商業資訊（Imagen、Capture One、Pixelmator 2018 公告）只看過搜尋摘要，數字（2,000／2,500 張、37 項調整）以官方頁面為準，日後可能會變。
