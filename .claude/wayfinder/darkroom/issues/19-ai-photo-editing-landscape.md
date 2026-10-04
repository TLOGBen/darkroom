# 別人的 AI 修圖都怎麼做？（研究）

Type: research
Status: resolved

## Question

使用者質疑：如果 AI 重畫（Qwen）第一版不做，還需不需要放在 ComfyUI。查商業產品（Lightroom、Luminar Neo、Photoshop、Imagen AI、Aftershoot、Evoto、Pixelmator Pro、Capture One）的 AI 修圖功能哪些是參數式、哪些是生成式；學術與開源（VLM 產生修圖參數：JarvisArt、MonetGPT 等；學習式調色；agent 式修圖；darktable／RawTherapee／digiKam 的 AI）；ComfyUI 生態的相片修圖做法（IC-Light、Flux Kontext／Qwen-Image Edit、遮罩局部修圖、人像節點包）與把 ComfyUI 當相片編輯器的優缺點；比較「ComfyUI 節點」與「獨立本機修圖 App」作為載體。產出：`research/19-ai-photo-editing-landscape.md`。

## Answer

（2026-10-04，研究子代理；詳見 [research/19-ai-photo-editing-landscape.md](../research/19-ai-photo-editing-landscape.md)，334 行，9 份來源用 `/baransu:read` 擷取到 `.claude/read/material/`。主 session 抽查屬實：ComfyUI `nodes.py` 的 SaveImage 把影像轉 `np.uint8`、只寫 `PngInfo`（不寫 ICC、不帶 EXIF），LoadImage 以 `/255.0` 讀入、EXIF 只用來轉正方向。）

**(a) 載體：不建議以 ComfyUI 為主。** 建議核心做成函式庫（版本化的參數 JSON schema＋torch GPU 渲染），主介面是獨立本機 App（Python 後端＋Web 前端），直接呼叫 llama-server；只有擴散模型（Qwen 移除、SeedVR2）才透過 ComfyUI API 呼叫；ComfyUI 薄節點選配、後做。前例：**RapidRAW**（即時預覽、本機 SAM2／U-2-Net／LaMa，生成式才經 AI-Connector 呼叫 ComfyUI）、**Krita AI Diffusion**（ComfyUI 當後端）。ComfyUI 弱在相片編輯最在意的地方：核心讀寫 8-bit、不處理 ICC／EXIF；App Mode 仍是按 Run 排隊；現有即時滑桿節點都得把算式寫兩份（JS 與 Python）；商業產品沒有一家用排隊流程修圖。

**(b) 值得做的 AI 功能（優先序）**：
1. AI 遮罩＋局部調整，含「preset 只套在遮罩內」（＝Lightroom Adaptive preset）——各家都有、參數式、本機小模型。
2. 「自動」：LLM 給滑桿初值＋三道保護（白平衡改由程式或專用模型量、規則壓套路、「渲染→再看→修正」迴圈）。商業 Auto 都是用大量修前修後配對專門訓練；論文指出通用 VLM 易過度編修、顏色數值判斷弱（RetouchIQ、VLM-CC、ColorBench）。要更穩可考慮 MonetGPT（MIT、7B、輸出含 temperature／tint，唯一能本機跑、不綁 Lightroom 的訓練過模型）。
3. ML 去噪、放大：獨立一步、處理完烘成新檔。
4. 移除雜物：預設 LaMa，大面積才用擴散，只貼回遮罩區。
5. 景深模糊、重打光：用「深度圖＋參數」，不用 IC-Light。
6. 全畫面 Qwen 重畫：商業產品沒人用來調色、本專案實驗也失敗，降為實驗功能。

**未知**：白平衡專用模型（Deep-WB、ABC-Former 等）只輸出校正後影像、沒有直接給 Temp/Tint，回推換算未經公開驗證；Deep-WB 非商用、ABC-Former 未標授權——建議用校正集做小實驗。reddit 擋爬蟲，社群評價只引 GitHub issue；Adobe 部分功能本機或雲端沒拿到一手來源；預覽從 ComfyUI 搬到獨立 App 的工作量要看預覽原型程式碼。

