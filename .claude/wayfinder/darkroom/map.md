# 本機專業相片編輯（Lightroom preset＋AI）

## Destination

三塊——① 調色引擎＋preset 庫、② AI 修圖助理、③ 自動修圖——的範圍、先後順序與彼此的交接方式（② ③ 怎麼把結果交給 ① 執行）都定案；① 的規格細到可以直接分片開工，② ③ 方向清楚、等 ① 做出來再細化。

## Notes

- **專案位置（2026-10-04 起）**：本專案是獨立 repo `D:/Code/darkroom`（使用者指定；D 槽是 SATA，程式碼放這裡沒問題，大檔案與模型仍在 C 槽）。地圖、計畫檔、研究、原型都從 LocalLLMs 搬來。**票裡寫的 `models/`、`runtimes/`、`projects/comfyui/`、`launcher/`、`artifact/11_preset/`、`outputs/`、`scratch/` 這類路徑，根目錄都是 `C:/Users/powde/workspace/LocalLLMs`**（模型、llama.cpp、ComfyUI、使用者的 preset 都在那裡）；`prototypes/`、`.claude/` 則是本 repo。
- **領域**：本機相片編輯——2026-10-04 起載體改為「核心函式庫＋獨立本機 App」，ComfyUI 0.38 只當擴散模型後端（RTX 4070 Ti SUPER 16GB）；使用者退了 Lightroom 訂閱，要用買來的 preset（`artifact/11_preset/xmp`，1466 個 xmp、150 個群組、第一層 11 類）。
- **先讀**：`.claude/think/comfyui-lightroom-preset-editor.md`（① 的計畫：確認過的理解第 3 版、Building／Not building／Approach／Key decisions／Unknowns）。地圖上的票都從它的未決點與三塊分工來。
- **已定原則（使用者 2026-10-04）**：xmp 的設定一律由程式執行；提示詞（PE＋Qwen 修圖）只做「加強」與「Adobe 未公開演算法的補強」。AI 只負責看懂畫面、找出位置（遮罩、關鍵點）、重畫內容；要用滑桿調、要能重複的部分由程式做。拖動預覽要即時；JPEG 先、RAW 後；「專案資料夾」＝preset 的資料夾分組；preset 庫不改原檔。② 的方向（2026-10-04 改）：**LLM 看圖直接決定滑桿數值（程式套用）＋可選 Qwen 重畫（混合強度）**；不做 AI 自動挑 preset。AI 功能（LLM 給數值、AI 補強／重畫）都吃兩個使用者輸入：**想要的方向**與**不想要的方向**（使用者 2026-10-04）。
- **已有的東西**：`prototypes/xmp-describe/`（xmp → 英文描述，原本是 LocalLLMs 的 ComfyUI-LightroomXMP，2026-10-04 搬來，Blacks 方向已修正）；`ComfyUI-LlamaServer-PE`（PE 走 llama-server）；7 萬事通（Qwen 修圖、PE 模式）；已裝 BiRefNet、DWPose、SeedVR2、sageattention。
- **工具路由（baransu 已裝，固定照這樣走）**：grilling 票的設計取捨用 `/baransu:think`；research 票用 `/common:research` 子代理，需要存原文時用 `/baransu:read`；task 票的實作切片用 `/baransu:contract` 釘驗收、`/baransu:seal` 收尾；session 收尾用 `/baransu:ship`。
- **語言**：地圖與票用繁體中文（台灣）；HTML 介面用預設 zh-TW。
- **規則**：本 repo 的 `CLAUDE.md`；動到 LocalLLMs 的東西（模型、ComfyUI、llama-server）時遵守 LocalLLMs 的 CLAUDE.md（模型下載要驗 SHA256、ComfyUI 自己跑一律 headless、測完關模型）。

## Decisions so far

- [① App 的執行環境與啟動](issues/21-app-runtime.md) — 複製 ComfyUI 的 python_embeded 當專用（LocalLLMs runtimes/darkroom-python/），darkroom 自己的啟動捷徑；App 自己協調 llama-server／ComfyUI

- [三塊的先後順序與交接點？](issues/11-sequencing.md) — ① alpha（函式庫＋App＋校正）→ RAW → ② AI 建議 → AI 遮罩 → ③（去雜物、美顏、身形、放大／重畫、光線調整）；交接用參數 JSON／遮罩圖＋參數／新圖層程式貼回

- [① 載體：放在 ComfyUI，還是做成獨立的本機修圖 App？](issues/20-host-platform.md) — 核心函式庫＋獨立本機 App（Python 後端＋Web 前端、直呼 llama-server），ComfyUI 只當擴散模型後端；取代「單一節點＋9 相片編輯」

- [別人的 AI 修圖都怎麼做？（研究）](issues/19-ai-photo-editing-landscape.md) — 商業產品 AI 以參數式為主、生成只用在移除；建議核心函式庫＋獨立本機 App、ComfyUI 只當擴散模型後端（前例 RapidRAW、Krita）；ComfyUI 讀寫 8-bit、無 ICC／EXIF

- [② AI 修圖助理用哪個 LLM 看圖、輸出什麼格式？](issues/08-assistant-llm-and-schema.md) — PE-I2I 不思考＋json_schema；白平衡由程式先量、矛盾就重問或歸零

- [② 35B vs PE-I2I：直接給滑桿數值（實驗，不思考）](issues/18-llm-slider-experiment.md) — 兩者都 JSON 全合格、偏藍暗照全對；短提示詞下速度相近；白平衡兩者都會判錯、都有固定套路 → 建議程式先量白平衡、規則檢查

- [① AI 補強實驗：程式近似 vs Qwen、混合會不會重影？](issues/16-ai-boost-experiment.md) — 清晰度去霧紋理 5/5 程式勝；Qwen 會重畫臉與細節、Pruna 整張位移；混合 25% 就有重影，對齊可減輕
- [① AI 補強怎麼接？](issues/04-ai-boost-wiring.md) — 定案：AI 只做加強、未公開項目全由程式；Qwen 混合要先對齊、預設 ≤25%、不用 Pruna

- [② 35B vs PE-I2I：誰適合當修圖助理？（實驗）](issues/15-llm-pick-experiment.md) — 挑 preset 兩者都不穩；PE-I2I 快 3 倍但看圖會幻覺，35B 看得準；思考模式不值得

- [① 校正集要渲染哪些圖、怎麼做？](issues/14-calibration-set.md) — 清單與產生腳本完成：必做 429 張／選做 344 張，設定預寫進檔案一次匯出（需抽查），使用者動手約 30～40 分鐘

- [① 含遮罩的 27 個 preset 怎麼套？](issues/17-gradient-masks.md) — 全是幾何漸層（線性 191、放射 13），程式照原位置重現；AI 對位（SAM3 找天空）當開關，可手動拖

- [① 跟萬事通的關係？](issues/07-relation-to-aio.md) — 單一節點可接任何 workflow，附「9 相片編輯」入口（讀圖→編輯→SeedVR2 選用→存檔），萬事通不改

- [① 預覽速度原型](issues/01-preview-latency-prototype.md) — 賭注成立：連續拖動延遲 p50 約 30 ms、40～50 fps；要用專用高優先 CUDA stream＋cv2 編碼＋HTTP 最新一次優先；閒置後第一下會慢（GPU 降頻）

- [① 節點介面長怎樣？](issues/02-node-ui-prototype.md) — B 版小節點＋全螢幕編輯器、可展開成內嵌 A 版；強度 0～200% 換 preset 回 100%；上一張／下一張；保留 params 輸入輸出

- [① 「像 Lightroom」的驗收方式？](issues/05-fidelity-acceptance.md) — 用 Lightroom 試用期一次性渲染單一滑桿掃描校正集，以誤差為準
- [① preset 庫的資料格式？](issues/06-preset-library-format.md) — 索引 artifact/11_preset/library.json、自存 preset 放 user/，原檔不改

- [① 未公開演算法各用哪個公開方法近似？](issues/03-proprietary-approximations.md) — Clarity／Texture 用 local Laplacian 金字塔、Dehaze 用暗通道去霧、亮部陰影用 guided filter 分層；全開 1.5MP 約 15 ms；調校先花在亮部陰影白黑（抬黑 811 個），對應數值沒參考渲染只是初值

- [③ 去雜物、去路人用什麼？](issues/10-object-removal-model.md) — SAM3（核心內建）指定＋補圖（LaMa 快速／Qwen 遮罩補圖精修）＋程式貼回原圖，保證遮罩外不變
- [③ 美顏、身形需要哪些模型？](issues/09-retouch-face-body-models.md) — AI 只找位置（BiSeNet 臉部解析、DWPose／SDPose 關鍵點、BiRefNet 人物遮罩），磨皮、去斑、液化都自己寫成滑桿；瘦腰要人物遮罩、大幅瘦身要先補背景
- [② 自動挑 preset 的現有做法？](issues/12-auto-preset-research.md) — 套在照片小圖上再比（LUT 快篩）＋檢索粗篩＋視覺 LLM 從 20 張縮圖挑前 3；準確度沒有公開證據，要盲測

## Not yet specified

- **RAW 管線細節**：解馬賽克用哪個、相機色彩描述檔（preset 裡 `CameraProfile` 是 Default Color 687、Embedded 603、Adobe Standard 37…）怎麼對應、白平衡從絕對值還是增量；等 ① 的 JPEG 版定案後才問得清楚。
- **80 個引用 Adobe 內建 Look 的 preset**：有沒有合法的描述檔來源（Adobe DNG Converter？）。
- **② 的互動方式**：AI 建議怎麼呈現給使用者（一鍵套用？逐項接受？），系統提示詞內容。
- **③ 的滑桿介面**：美顏、身形各要哪些滑桿、預設值。
- **匯出**：把自己的微調另存成 xmp 的格式細節（能不能讓真的 Lightroom 讀回去）。

- ~~57 個舊版處理流程（PV2010）的 preset~~（2026-10-04 更正：實查這 57 個 ProcessVersion 6.7 全部使用 `*2012` 鍵，是 PV2012 而非 PV2010；核心函式庫合約已改為支援）。


## Out of scope

- [② preset 效果概念地圖怎麼建、AI 怎麼挑？](issues/13-preset-concept-map.md) — **AI 自動挑 preset 與靈感模式拿掉**（使用者 2026-10-04，看過實驗後判斷不值得：LLM 挑選不穩定）；preset 由使用者自己挑

- **照片專案／目錄**（像 Lightroom 那樣管理一批照片與各自的設定）：使用者確認「專案資料夾」指 preset 分組。
- **用 AI 取代程式調色**（整個 preset 寫成提示詞讓 Qwen 重畫）：違反已定原則。
- **逐像素重現 Adobe 的結果**：演算法未公開，做不到；目標是觀感相近。
