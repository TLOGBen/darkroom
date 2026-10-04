# 12 自動挑 preset 的現有做法（研究）

- 日期：2026-10-04
- 對應票：`issues/12-auto-preset-research.md`
- 前提：1466 個 Lightroom XMP preset（150 群組），我們自己寫程式照 xmp 數值調色；本機 RTX 4070 Ti SUPER 16GB、64GB RAM、Windows、Python 3.13、torch 2.14+cu130；已有 llama-server（Qwen3.6-35B-A3B 視覺、Qwen3.5 9B PE-I2I）。
- 標記：**「推論」**＝來源沒明講、是我依來源與本機條件推出來的；沒標的都有來源。

## 來源清單

Adobe／商業產品
- S1 Adobe Lightroom 說明：Apply presets（Recommended 用 Adobe Sensei、會隨學習調整、Subtle/Strong/B&W/Cool/Warm/Cinematic… 篩選、"More like this"）https://helpx.adobe.com/lightroom/web/edit-photos/use-presets/apply-presets.html
- S2 Adobe Blog 2022-09-26 Lightroom Discover：「Recommended Presets are sourced from the Lightroom community. Using machine learning developed by Adobe, Recommended Presets shows you how photographers processed similar images to yours」https://blog.adobe.com/en/publish/2022/09/26/lightroom-discover-boost-your-photo-editing-skills
- S3 Adobe 社群提問（使用者轉述「比對相似主題與直方圖的社群照片」，無官方回覆）https://community.adobe.com/questions-680/lightroom-recommended-presets-and-content-analysis-926326
- S4 Matt Kloskowski／Lightroom Killer Tips：Adaptive presets（Portrait／Sky／Subject 三組，靠 AI 遮罩）https://lightroomkillertips.com/adaptive-presets-in-lightroom-classic-part-1/
- S5 Shotkit：Adaptive presets 說明 https://shotkit.com/lightroom-adaptive-presets/
- S6 Matiash 部落格：Recommended presets https://www.matiash.com/blog/lightroom-recommended-presets
- S7 Imagen AI：Personal AI Profile（至少 2,000 張修過的照片、學每張參數）https://imagen-ai.com/post/create-ai-editing-profile/ 、https://shotkit.com/imagen-personal-ai-profile/
- S8 Skylum：Luminar「For This Photo」https://blog.skylum.com/luminar-presets/ 、https://support.skylum.com/presets/working-with-presets
- S9 ON1 Photo RAW：AI Adaptive Presets、AI Style Advisor https://www.on1.com/products/photo-raw/features/

圖文 embedding
- S10 SigLIP 2（HF/Voxel51 文件，B/L/So400m/g 四種尺寸）https://docs.voxel51.com/plugins/plugins_ecosystem/siglip2.html
- S11 jina-clip-v2（865M、89 語言、512px）https://huggingface.co/jinaai/jina-clip-v2 、https://arxiv.org/abs/2412.08802
- S12 Color in Visual-Language Models: CLIP deficiencies（arXiv 2502.04470）https://arxiv.org/abs/2502.04470
- S13 When are Lemons Purple? Concept Association Bias（arXiv 2212.12043）https://arxiv.org/pdf/2212.12043
- S14 CSD：Measuring Style Similarity in Diffusion Models（ECCV 2024）https://arxiv.org/abs/2404.01292 ；其侷限 https://arxiv.org/pdf/2605.09030

色彩統計
- S15 Rubner et al. Earth Mover's Distance 影像檢索 https://people.eecs.berkeley.edu/~efros/courses/LBMV07/Papers/rubner-jcviu-00.pdf
- S16 Neumann & Neumann 2005 Color Style Transfer（Reinhard 均值/標準差轉移的延伸）https://www.cg.tuwien.ac.at/research/publications/2005/lneumann-2005-cst/lneumann-2005-cst-PDF.pdf

美感評分
- S17 NIMA（AVA SRCC 0.612；MobileNet 0.534／Inception-v2 0.636）https://arxiv.org/abs/1709.05424
- S18 Aesthetic Predictor V2.5（SigLIP 為底、1–10 分）https://github.com/discus0434/aesthetic-predictor-v2-5 ；ComfyUI 節點 https://api.comfyonline.app/comfyui-nodes/ComfyUI-Aesthetic-Predictor-V2.5
- S19 LAION-Aesthetics predictor 稽核（偏好動漫與隨手拍、西方視角）arXiv 2601.09896 https://arxiv.org/pdf/2601.09896
- S20 Q-Align（ICML 2024；AVA SRCC 0.822、OneAlign 0.823）https://arxiv.org/abs/2312.17090 ；模型卡 https://huggingface.co/q-future/one-align
- S21 ArtiMuse（8B，AVA SRCC 0.827；GPT-4o 0.509、Gemini-2.0-flash 0.474）https://arxiv.org/abs/2507.14533
- S22 UniPercept（2025-12，美感＋品質＋結構）https://arxiv.org/html/2512.21675v1
- S23 2AFC Prompting of LMMs for IQA（兩兩比較、順序一致性）https://arxiv.org/pdf/2402.01162 ；Co-Instruct／視覺品質比較 https://arxiv.org/pdf/2402.16641
- S24 Image Color Aesthetics Assessment（ICCV 2023，色彩美感專用資料集）https://openaccess.thecvf.com/content/ICCV2023/html/He_Thinking_Image_Color_Aesthetics_Assessment_Models_Datasets_and_Benchmarks_ICCV_2023_paper.html

LLM 選擇
- S25 Mitigating Boundary Ambiguity and Inherent Bias for Text Classification in the Era of LLMs（選項越多越不準：gpt-3.5 從 2 類 94.29% 掉到 60 類 32.51%；位置偏差可達 35～50%）https://arxiv.org/pdf/2406.07001
- S26 JarvisArt（NeurIPS 2025，MLLM 代理操作 Lightroom 200+ 工具）https://arxiv.org/abs/2506.17612
- S27 MonetGPT（SIGGRAPH 2025，Adobe Research；MLLM 規劃程序式修圖操作）https://arxiv.org/abs/2505.06176 、https://github.com/niladridutt/monetgpt

學術：調色／增強
- S28 Image-adaptive 3D LUT（小 CNN 預測多個 basis LUT 的權重，<600K 參數，4K 小於 2ms）https://arxiv.org/abs/2009.14468
- S29 StarEnhancer（style encoder，多風格單模型）https://arxiv.org/abs/2107.12898
- S30 PieNet：Personalized Image Enhancement with Masked Style Modeling https://arxiv.org/abs/2306.09334
- S31 RSFNet（白箱、區域濾鏡參數）https://arxiv.org/abs/2303.08682
- S32 Neural Preset for Color Style Transfer（CVPR 2023，用約 5000 個 LUT 訓練）https://arxiv.org/abs/2303.13511
- S33 Automatic Photo Adjustment Using Deep Neural Networks（Yan et al.）https://arxiv.org/abs/1412.7725

---

## 0. 先釐清：「挑 preset」其實是兩種問題

1. **配合這張照片**（沒有目標，只要「適合、好看」）：要判斷「這個轉換套在這種內容上好不好看」。這是推薦／排序問題。
2. **照某個目標風格**（使用者給參考圖或一句話「藍色東京感」「富士膠捲」）：要判斷「套完之後像不像目標」。這是檢索／比對問題。

preset 不是一張圖，而是一個**轉換**。同一個 preset 套在雪景與夜景上的結果差很多，所以「照片 ↔ preset 縮圖」直接比相似度，本質上是在比「內容像不像」，不是「這個轉換適不適合」（推論）。這點決定了下面幾種做法各自適合哪一段。

我們有一個商業軟體沒有的優勢：**preset 的渲染器是自己寫的，可以直接把候選 preset 套在使用者「這張照片」的小圖上**，不必依賴預先做好的縮圖。xmp 裡的全域色調／顏色操作（曝光、對比、色調曲線、HSL、分離色調、色彩分級、校準、白平衡）大多是逐像素的，能先烘成每個 preset 一張 3D LUT（例如 33³），1466 張 LUT 套在一張 256px 小圖上，在 GPU 上是秒級的工作（推論；清晰度、紋理、去朦朧、暈影、顆粒、局部遮罩不是逐像素，篩選階段可先忽略，進最後幾名再用完整渲染）。S28 的 3D LUT 研究也是把「調色」表示成 LUT 再由小網路挑權重，代表 LUT 是調色的合理近似表示。

---

## 1. 圖文 embedding 檢索（CLIP／OpenCLIP／SigLIP2／Jina-CLIP）

**做法**
- (a) 照片 embedding ↔ preset 縮圖 embedding（以圖找圖）。
- (b) preset 文字描述 embedding ↔ 照片 embedding（以文找圖），描述可來自群組名、preset 名、或視覺 LLM 寫的描述。
- (c) 使用者一句話 ↔ preset 描述（純文字檢索，可用一般文字 embedding 或 LLM）。
- (d) **套用後檢索**：把候選 preset 套在使用者照片上，算「結果 ↔ 目標文字」（例如「cinematic teal and orange」）的 CLIP 分數。

**模型與本機可行性**
| 模型 | 大小 | 中文 | 本機 |
|---|---|---|---|
| OpenCLIP ViT-L/14 | 約 0.4B | 弱 | 可，fp16 1GB 上下（推論） |
| SigLIP2 So400m（patch14/16，224～512px） | 視覺塔約 400M（S10） | 多語（S10） | 可；CPU 也跑得動單張查詢（推論） |
| SigLIP2 g | 約 1B（S10） | 多語 | 可 |
| jina-clip-v2 | 865M（文 561M＋圖 304M），512px，89 語言（S11） | 有 | 可；要 `trust_remote_code`，Python 3.13 相容性要實測（推論） |
| CSD（風格 embedding，ViT-L 在 WikiArt 微調）（S14） | 約 0.3B | 無文字端 | 可，但偏「畫風」，不是攝影調色（推論） |

- 前處理：一次性算 1466（×N 張標準照）的 embedding，存成 numpy；查詢時算一張。SigLIP2 So400m 在 4070 Ti SUPER 上批次算一萬多張預估是分鐘級（推論）。
- GPU 衝突：llama-server 跑 35B 時 VRAM 約 15.8GB，一次只能一個程式用 GPU（CLAUDE.md 規則）。查詢時的單張 embedding 可以放 CPU（7950X），避免跟 LLM 搶卡（推論）。

**準不準的證據**
- CLIP 對顏色的理解有已知缺陷：對白／灰／黑這類無彩色有偏差、文字優先於視覺色彩、顏色專屬神經元少（S12）；還有「檸檬是黃的」這種概念聯想偏差，會依物體常識回答顏色（S13）。調色差異很多是細微的色偏、對比、去飽和，**正好是 CLIP 弱的地方**（推論）。
- CLIP／SigLIP 的 embedding 主要編碼「內容語意」，同一張照片套不同 preset，embedding 差距遠小於換一張照片的差距（推論，常識上成立但沒找到量化論文）。因此 (a) 會傾向找「縮圖內容跟你照片最像的 preset」，而不是「調色最適合的 preset」。
- (d) 在「目標描述很具體的風格詞」（黑白、暖色、藍調、霓虹夜景）上應該有用，因為那是粗顏色語意；在「富士 Classic Chrome vs Pro 400H」這種細差異上不可靠（推論）。
- 沒找到「用 CLIP 挑攝影 preset」的公開準確度數字。**證據缺口。**

**適合**：粗篩（1466 → 前 50～100）、文字指令檢索。不適合單獨做全自動決定。

---

## 2. 色彩統計／色調特徵比對

**做法**
- 特徵：LAB 的 L/a/b 均值與標準差（Reinhard 式統計，S16）、L 直方圖（亮度分佈＝曝光與對比）、a-b 二維直方圖（色偏）、色相直方圖加權飽和度、陰影／中間調／高光三段的平均色（＝split toning／color grading 的直接對應）、主色調色盤（k-means 5～8 色）。
- 距離：直方圖用 EMD（Rubner，S15：比其他距離更接近人眼的相似感）、或 χ²／Bhattacharyya；統計向量用加權歐氏距離。
- 兩種用法：
  - **有參考圖**：把每個候選 preset 套在使用者照片上，比「結果的統計 ↔ 參考圖的統計」，取最近的。這是有明確答案的最佳化問題，非常適合全自動（推論）。
  - **沒參考圖**：統計只能當「健康檢查」：剔除套完後過曝／死黑大量裁切、膚色色相偏離正常範圍、飽和爆掉的候選（推論）。
- 另一個用法：preset 本身的「轉換特徵」可直接從 xmp 數值或 LUT 算出（例如 LUT 把中灰映到哪裡、平均飽和度增減、陰影／高光偏色方向），不需要任何照片。用這組特徵可以把 1466 個分群、去重（很多 preset 其實很像）、做「More like this」（推論）。

**本機可行性**：純 numpy／torch，不需模型，毫秒級。完全可行。

**準不準的證據**
- EMD 對色彩分佈檢索比 bin-to-bin 距離更符合人眼（S15）。Reinhard 系統計轉移是調色轉移的經典基線（S16）。
- Adobe 的 Recommended presets 據使用者轉述會比「相似主題與直方圖」（S3，非官方說法），代表直方圖類特徵至少被認為是合理訊號（弱證據）。
- 統計比對不懂內容：同樣的色彩分佈在人像與風景上好不好看不同。沒參考圖時無法單獨挑（推論）。

**適合**：「照參考圖配色」模式的主力；全自動模式的過濾器與去重工具；強度微調（見第 7 節）。

---

## 3. 美感評分模型（套用後挑最好看）

**模型**
| 模型 | 大小 | AVA SRCC | 本機 |
|---|---|---|---|
| NIMA（S17） | 數百萬～2 千萬參數 | 0.612（Inception-v2 0.636） | 輕鬆 |
| LAION Aesthetic Predictor v2（CLIP L/14＋MLP） | 0.4B | 未公布正式 SRCC | 輕鬆 |
| Aesthetic Predictor V2.5（SigLIP＋MLP，1–10 分）（S18） | 約 0.4B | 未公布 | 輕鬆，已有 ComfyUI 節點（S18） |
| Q-Align／OneAlign（mPLUG-Owl2 底）（S20） | 約 7～8B | 0.822／0.823 | fp16 約 16GB，放不進 16GB 要量化；模型卡要求 transformers 4.36.1＋`trust_remote_code`，跟 Python 3.13／新 transformers 的相容性有風險（推論） |
| ArtiMuse（S21） | 8B | 0.827 | 同上，要量化，依底層架構而定（推論） |
| UniPercept（S22） | MLLM | 論文宣稱勝過現有 MLLM | 未評估 |
| 通用 MLLM 直接打分（GPT-4o） | — | 0.509（S21 報告） | 參考：通用模型打絕對分數不準 |

**準不準的證據**
- AVA 的分數主要反映內容、構圖、題材；而我們的候選是**同一張照片、只差調色**。AVA 訓練的模型對「同內容不同調色」的分辨力沒有公開驗證（推論，證據缺口）。有專門的「色彩美感」資料集與模型（S24），代表學界也認為一般美感模型沒涵蓋好色彩美感。
- LAION 系預測器被稽核出偏好動漫與隨手拍、反映特定文化品味（S19）。
- 美感模型普遍偏好高飽和、高對比、暖色（S24 搜尋結果引用的心理學研究：美感評分與飽和度正相關、偏好暖色）（推論延伸）。若直接拿美感分最高的 preset，結果可能永遠是「最鮮豔」那幾個，喪失「戲劇色調」「低飽和膠捲」這類風格（推論）。
- 兩兩比較（2AFC）比絕對打分穩：S23 把 LMM 改成兩兩挑好的，並用「換順序是否一致」量信心；Co-Instruct 在兩兩比較上勝過 GPT-4V（S23）。

**適合**：最後幾名（3～10 個）之間的排序與「保險」；不適合在 1466 個裡直接挑（會集中到最鮮豔的）。建議用「相對分數」：同一張照片原圖分數當基準，只看 preset 有沒有讓分數明顯變差（推論）。

---

## 4. 視覺 LLM 直接挑

**做法**
- 單階段：照片＋1466 個名稱 → LLM 選。**不建議**：S25 顯示選項從 2 個增到 60 個，gpt-3.5 準確率從 94.29% 掉到 32.51%；開源模型（LLaMA、Qwen）還有很強的位置偏差，正確答案擺第一位時表現波動 35～38%。1466 個名稱還會吃掉大量 context（每個名稱十幾個 token，約 2～3 萬 token，35B 的提示詞處理約 590 t/s → 約 40～60 秒才開始回答）（推論）。
- 分層：先問「照片類型、光線、情緒、適合方向」→ 選 3～5 個群組（150 選幾個，仍偏多，可再分大類：顏色／電影／地區／器材…）→ 群組內 5～20 個 preset 選。群組名稱語意清楚（「器材 - 膠捲 - 富士」），LLM 判斷「這張適合膠捲感」比判斷「哪個富士 preset」可靠（推論）。
- **看結果挑**（最推薦的 LLM 用法）：把前 N 個候選真的套在照片上，排成編號縮圖九宮格（contact sheet）丟給 Qwen3.6-35B-A3B，請它選前 3 並說明。這把問題從「想像 preset 名稱的效果」變成「看圖比較」，跟 S23 的兩兩比較同一路線（推論）。要對付位置偏差：打亂順序跑兩次，取兩次都入選的（S23 的一致性做法、S25 的位置偏差）。
- 強度：讓 LLM 給「弱／中／強」三檔（對應 0.4／0.7／1.0），比要它給精確百分比穩（推論；Q-Align 也發現「離散等級比直接數字好學」，S20）。

**本機可行性**：Qwen3.6-35B-A3B 已在 llama-server 上（約 42～50 tok/s 生成；呼叫方說約 60）。一次判斷（一張 3×3 或 4×5 縮圖格＋短回答）預估 10～30 秒（推論）。Qwen3.5 9B 更快，但判斷細微調色差異的能力未驗證。

**準不準的證據**
- 通用 MLLM 當美感「絕對打分器」很差（GPT-4o AVA SRCC 0.509，S21），但「規劃修圖參數」的研究很活躍：JarvisArt（S26）用 MLLM 操作 Lightroom 200+ 工具，在其基準上像素指標比 GPT-4o 好 60%；MonetGPT（S27，Adobe Research）讓 MLLM 規劃程序式修圖。這兩個都要特別訓練過，代表**沒訓練的通用 MLLM 對調色細節的判斷力有限**（推論）。
- 沒找到「通用 VLM 從 preset 清單挑選」的準確度數字。**證據缺口**，要自己做小規模盲測。

**適合**：「給候選讓人選」時寫推薦理由（使用者看得懂為什麼）；全自動模式裡當最終裁判（在 ≤20 個已渲染候選之間）。

---

## 5. 商業／開源產品怎麼做

| 產品 | 官方怎麼說 | 本質（推論） |
|---|---|---|
| Lightroom **Recommended presets** | 「preset 來自 Lightroom 社群；用 Adobe 開發的機器學習，給你看攝影師如何處理**跟你相似的照片**」（S2）；說明頁：用 Adobe Sensei 依照片產生、會隨 AI 學習調整，有 Subtle／Strong／B&W／Cool／Warm／Dark／Bright／Cinematic／HDR 篩選、"More like this"（S1）。使用者轉述「比對相似主題與直方圖的社群照片」（S3，無官方確認）。也會從使用者套用行為學習（S6，第三方說法）。 | **以照片找照片**的協同過濾：找內容／直方圖相似的社群照片 → 拿那些照片作者用的 preset。核心資料是「真實照片 ↔ 作者選的 preset」配對，這是我們沒有的。給一排候選讓人選，不是單一全自動答案。 |
| Lightroom **Adaptive presets** | Portrait／Sky／Subject 三組，每次用 AI 遮罩重新偵測人物／天空／主體，把設定套在遮罩上（S4、S5）；人像的 glamour 預設會建 7 個遮罩（S5）。 | 不是「挑」preset，而是讓 preset **自適應內容**。對我們的啟示：xmp 裡有遮罩的 preset，要靠分割模型（票 09／10 範圍）才能還原。 |
| Luminar **For This Photo** | AI 辨識照片、推薦最適合的 preset **集合**（例：夜景推「Light Chaser」等三組）（S8） | 先做**場景分類**，再推薦集合（群組層級），不是單一 preset。跟「分層：先挑群組」一致。 |
| ON1 **AI Style Advisor** | 學使用者偏好、推薦個人化 preset（S9） | 依使用歷史個人化。 |
| **Imagen AI** Personal Profile | 上傳至少 2,000 張自己修過的照片，學每張的參數；套用時每張照片的參數都依內容調整；靠使用者修正再上傳迭代（S7） | 不是挑 preset，是**直接回歸參數**（像 S28、S30 的個人化增強）。要大量自己的修圖資料，不適用我們的情境。 |

學術上相關的方向：
- 「選／混合預設風格」：S28 用小 CNN 預測多個 basis 3D LUT 的權重；S29 StarEnhancer 用 style encoder 在多風格間映射；S30 PieNet 從使用者風格範例推個人化增強；S32 Neural Preset 用 5000 個 LUT 訓練色彩風格轉移。這些都需要**成對訓練資料**（原圖→專家修圖），我們沒有，而且產物是「直接調出結果」而不是「挑出 1466 中哪一個」。
- 沒找到專門做「從大型 preset 庫推薦」並公開準確度的論文；Instagram 濾鏡相關研究多半是**移除**或**辨識**濾鏡，不是推薦（搜尋結果 S33 所在的那批）。**證據缺口**：這個題目沒有現成可抄的基準，準確度只能自己量。

---

## 6. 建索引：把 preset 套在標準照片上

**做法**
1. 挑 N 張標準照片：人像（室內／室外）、風景（白天）、夜景、食物、街景、雪景／高調，N＝6～8。
2. 每個 preset 套在 N 張上，輸出 256～512px 縮圖：1466 × 8 ≈ 1.2 萬張。
3. 對每張算：SigLIP2 embedding、色彩統計、美感分數（相對於原圖的變化量）。
4. 每個 preset 拼一張 N 格縮圖給視覺 LLM 寫描述：「整體偏暖、陰影偏青、高光偏橘、低飽和、對比中等；適合人像與街景，不適合食物（綠色變灰）」＋標籤（暖／冷、強度、黑白、膠捲、適合題材、不適合題材）。

**成本估算（全部推論）**
| 步驟 | 估計 |
|---|---|
| 渲染 1.2 萬張 512px（自寫渲染器；全域操作烘成 LUT 時） | 分鐘級；含清晰度等非逐像素操作的完整渲染，視實作約 0.05～0.3 秒／張 → 10 分鐘～1 小時 |
| SigLIP2 So400m embedding 1.2 萬張 | GPU 數分鐘 |
| 美感模型 V2.5 1.2 萬張 | GPU 數分鐘 |
| Qwen3.6-35B 寫 1466 段描述（每段一張 N 格縮圖＋約 150 token 輸出） | 每段約 5～10 秒 → 2～4 小時，一次性，可放隔夜 |
| 儲存 | 1.2 萬張 512px JPEG 約 1～2GB；embedding 不到 100MB |

**效果證據**：Recommended presets 的作法本身就是「看 preset 在真實照片上的樣子」，Adobe 是用社群真實作品而不是標準照（S2）。標準照的效果沒有公開證據（推論：比只用 preset 名稱好，因為名稱常是行銷詞；但比不上「套在使用者這張照片上」直接看）。

**我們的做法建議**：索引最有價值的產物不是 embedding，而是 **LLM 寫的「適合／不適合題材」標籤與描述**、以及**從 LUT 算出的轉換特徵**——前者用來分層篩選，後者用來去重與「More like this」。embedding 留作文字指令檢索用。

---

## 7. 強度怎麼定

- 強度＝把 preset 參數對「中性值」做線性插值（或渲染結果與原圖混合，兩者效果不同：參數插值對曲線類較自然；像素混合實作簡單）（推論）。
- 自動強度候選：在 {0.4, 0.7, 1.0} 三檔各渲染一次，用（a）統計健康檢查（裁切比例、膚色色相、飽和上限）刪掉壞的，（b）美感相對分或 LLM 兩兩比較挑一檔（推論）。
- 有參考圖時：強度可以直接最佳化——在 0～1.2 之間找讓「結果統計 ↔ 參考統計」距離最小的值（推論）。

---

## 8. 推薦組合

**全自動模式（沒有目標，只要好看）**
1. **場景理解（LLM，一次）**：Qwen3.6 看照片，輸出結構化欄位：題材（人像／風景／夜景／食物…）、光線、目前色調、建議方向 3～5 個（例：「暖色膠捲」「低飽和電影」），可選地輸出 3～5 個群組名。
2. **篩到前 ~100**：用索引的「適合題材」標籤 ＋ 方向詞的文字檢索（SigLIP2／jina-clip-v2 的文字端，或直接在 LLM 給的群組內）。
3. **套在這張照片上 → 篩到前 ~20**：100 個候選以 LUT 近似渲染在 256px 小圖上；統計健康檢查剔除壞結果；用 LUT 轉換特徵去重（太像的只留一個）；美感相對分刪掉明顯變差的。
4. **LLM 看圖挑前 3**：20 個結果排成編號縮圖格，Qwen3.6 選 3 個並給強度（弱／中／強）與一句理由；打亂順序再問一次，兩次都入選的優先。
5. **完整渲染前 3 × 強度**，第一名自動套用，第二、三名放旁邊一鍵切換。

**照參考圖／照一句話模式**
- 參考圖：所有 1466 個以 LUT 套在使用者照片小圖上 → 和參考圖比色彩統計（EMD／LAB 統計）→ 前 10 → LLM 或使用者看圖決定；強度用統計距離最佳化。
- 一句話：文字 → 群組／標籤檢索與 CLIP 套用後分數 → 前 20 → 同上第 4 步。

**理由**
- 每一層用它最強的地方：LLM 懂內容與語意（但選項多就亂）；embedding 便宜但看不清細微色調（S12、S13）；色彩統計精準但不懂內容；美感模型能擋爛結果但會偏好鮮豔（S19、S24）。
- 「套在這張照片上再比」把 preset 的「轉換」本質處理掉了，這是只能拿預製縮圖的商業產品做不到、而我們有自寫渲染器才做得到的（推論）。
- 每個 LLM 判斷都控制在 ≤20 個選項、看圖不看名稱，避開 S25 的選項數與位置偏差問題。
- 最後給前 3 而不是只給 1：Lightroom（S1）與 Luminar（S8）都是給一排／一組候選讓人挑，沒有產品敢宣稱「AI 挑的唯一答案」。
- 全部模型都已在本機或很小：LLM 已有；SigLIP2／美感 V2.5 各約 0.4B，可放 CPU 或在 LLM 閒時用 GPU。不需要 Q-Align／ArtiMuse 這種 8B 模型（16GB 卡與 llama-server 會互搶）。

**建議的第一個驗證實驗（推論）**：取 30 張使用者自己的照片，請使用者從 1466 個中各挑出喜歡的 1～3 個當「答案」（或從系統給的 20 個中選），量上面流程「前 3 命中率」與「前 20 召回率」，並比較 (a) 只用 LLM 分層、(b) 只用美感分、(c) 完整組合。沒有公開基準，只能這樣自建。

---

## 9. 最大的不確定點

1. **沒有公開準確度證據**：「從大型 preset 庫自動挑」沒有學術基準，Adobe／Skylum 也沒公布準確度。所有效果判斷都是推論，必須用使用者自己的照片做盲測。
2. **通用視覺 LLM 能不能分辨細微調色差異**：已知通用 MLLM 美感打分弱（GPT-4o AVA SRCC 0.509），專門做修圖的 JarvisArt／MonetGPT 都經過特別訓練。Qwen3.6-35B 在 20 格縮圖裡分辨「Classic Chrome vs Pro Neg」等級的差異能力未知；縮圖格每格只有約 200px，細節會損失。
3. **美感模型對「同內容不同調色」的分辨力**：AVA 系模型沒有這方面的驗證，可能系統性偏好高飽和。
4. **LUT 近似的誤差**：含遮罩、清晰度、去朦朧的 preset，LUT 篩選結果可能跟完整渲染差很多；需要量多少比例的 preset 有這些非逐像素操作。
5. **品味主觀**：沒有使用者回饋就沒有個人化（Imagen 要 2,000 張、Adobe 靠社群行為）。之後可以記錄使用者最後選了哪個，當作排序的加分訊號（推論）。
