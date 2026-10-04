# AI 修圖助理：LLM 看照片直接給 Lightroom 滑桿數值（35B-A3B vs PE-I2I）

2026-10-04，桌機 RTX 4070 Ti SUPER 16GB，llama.cpp b11223 CUDA（`-dev CUDA0 -c 32768 -np 1 -fa on --jinja`，預設 `--fit`），兩個模型都**關思考**（`chat_template_kwargs.enable_thinking=false`），用 `response_format: json_schema` 強制輸出格式。

- **A**：Qwen3.6-35B-A3B HauhauCS Q4_K_P＋mmproj f16，搭 `projects/qwen3.6-35b-a3b/chat-template.jinja`
- **B**：PE-I2I Heretic Q8_0＋mmproj bf16（gguf 內建模板）
- 取樣：temperature 0.7、top_p 0.9、top_k 20、min_p 0；每張照片 seed 101、202 各一次；max_tokens 2000
- 照片：沿用 `../llm-pick-experiment/photos/` 的 9 張（來源與授權見該資料夾 `photos.json`），圖送 1024 長邊 JPEG
- 提示詞與 schema 在 `run_sliders.py`（`SYSTEM`、`SLIDER_GUIDE`、`TASK`、`build_schema()`）。提示詞要求先診斷、再只針對診斷出的問題給數值、保守但有效、尊重場景氣氛；逐條寫出每個滑桿正負值的意義，Blacks2012 特別寫明「負＝壓黑、正＝抬黑變霧面，不要用正值來加反差」。
- schema：`diagnosis`（subject、white_balance 列舉、exposure 列舉、contrast 列舉、main_problems 陣列）→ `adjustments`（Exposure2012 小數 -5～5；其他 12 個基本滑桿與 6 色 × 3 的 HSL（Red/Orange/Yellow/Green/Aqua/Blue 的 Hue/Saturation/Luminance）整數 -100～100，全部必填）→ `intent`。

## 數字

| | A 35B-A3B | B PE-I2I |
|---|---|---|
| 載入到 /health ok（秒，檔案已在快取） | 15.2 | 5.1 |
| VRAM（nvidia-smi，載入前約 1.55GB 是桌面） | 15.7GB（`--fit` 吃滿） | 12.1GB |
| 每次請求秒數 平均（最小–最大） | **10.5**（9.5–13.5） | **9.6**（8.6–10.5） |
| 生成 tokens 平均／生成速度 | 531／58.6 tok/s | 567／61.0 tok/s |
| 提示詞處理速度（第一次看圖時，約 1.2K–1.75K tokens） | 約 260 tok/s* | 約 1680 tok/s* |
| JSON 合格（`json.loads`）| 24/24 | 24/24 |
| 欄位齊全＋範圍合法（自己的驗證，含 Exposure 的 ±5） | 24/24 | 24/24 |
| 兩次數值差異：基本 12 個整數滑桿平均絕對差 | **7.1** | **3.5** |
| 兩次數值差異：Exposure2012 平均絕對差（EV） | 0.23 | 0.24 |
| 兩次數值差異：HSL 18 鍵平均絕對差 | 1.6 | 0.3 |
| 兩次都非 0 的滑桿，正負號一致 | 92/97（95%） | 89/91（98%） |
| 兩次「動不動這個滑桿」一致 | 85% | 92% |
| 兩次診斷相同（白平衡／曝光／反差，9 張中） | 5／7／9 | 9／7／8 |
| 每次動了幾個滑桿（31 個中） | 12.8 | 11.3 |
| 18 次中用到 HSL 的次數 | 12 | 2 |
| 照片專屬方向檢查（下表） | **17/18** | **18/18** |
| 自我一致（自己的診斷 → 自己的數值方向） | 55/57 | 49/57（其中 2 條是要求冷調造成的，扣掉後 49/55） |
| 想要／不想要檢查（3 張 × 2 次，共 26 條） | 22/26 | 25/26（見下） |

\* 第二次同一張圖時 llama-server 會重用快取（`prompt_n` 只剩 4），所以秒數主要是生成時間。兩個模型生成速度差不多，生成量約 500–600 tokens，**每次都約 10 秒**；上一輪挑 preset 時 B 快 3 倍的差距（來自 8–10K tokens 的候選清單）在這裡幾乎消失，因為提示詞只有約 1.5K tokens。

各滑桿兩次平均絕對差（9 張平均）：

| 滑桿 | A | B |
|---|---|---|
| Contrast2012 | 5.6 | 3.7 |
| Highlights2012 | 11.7 | 2.9 |
| Shadows2012 | 16.7 | 6.2 |
| Whites2012 | 6.1 | 2.9 |
| Blacks2012 | 7.8 | 2.8 |
| IncrementalTemperature | 8.0 | 6.4 |
| IncrementalTint | 5.8 | 1.8 |
| Vibrance | 6.1 | 3.7 |
| Saturation | 2.8 | 1.3 |
| Clarity2012 | 4.4 | 2.7 |
| Dehaze | 6.7 | 4.0 |
| Texture | 3.9 | 3.7 |

### 方向檢查（我定義的明確規則，中性提示詞的 2 次都算）

| 檢查 | A | B |
|---|---|---|
| 偏藍暗照：Exposure > 0 | 2/2 | 2/2 |
| 偏藍暗照：Temperature > 0（往暖） | 2/2 | 2/2 |
| 偏藍暗照：Contrast > 0 或 Blacks < 0 | 2/2 | 2/2 |
| 偏藍暗照診斷：白平衡 cool | 2/2 | 2/2 |
| 偏藍暗照診斷：曝光 under | 2/2 | 2/2 |
| 夕陽：Temperature ≥ 0（不中和夕陽） | 2/2 | 2/2 |
| 夕陽：Highlights ≤ 0 | 2/2 | 2/2 |
| 夜景：Highlights ≤ 0 | 2/2 | 2/2 |
| 夜景：Exposure ≤ +0.7（不拉成白天） | 1/2（s202 給 +1.25） | 2/2 |
| 全部照片：\|Exposure\| ≤ 1.5 | 18/18 | 17/18（偏藍暗照 s202 給 +1.6） |
| 全部照片：\|Saturation\| ≤ 30 | 18/18 | 18/18 |
| 全部照片：沒有「Contrast > +10 且 Blacks > +20」的矛盾 | 18/18 | 18/18 |

**Blacks2012 方向**：36 次中性回應的 Blacks 全部是負值（A -30～-5、B -20～-10），沒有任何一次用正值去「加反差」。提示詞裡寫清楚正負意義後，上一輪 preset 描述寫反造成的問題沒有出現。

自我一致的失敗：
- A：portrait_studio s101 診斷「偏藍」卻給 Temp -15（更冷）；night_street 想要救暗部 s101 診斷「偏藍」卻給 Temp -15。
- B：night_street s202 診斷「偏藍」、intent 也寫「remove the cool blue cast」，卻給 Temp -14（同一張 s101 給 +12，正負相反）；landscape s202 診斷「slightly overexposed」卻 Exposure +0.3；night_street 想要救暗部兩次：s101 診斷 under 卻 EV 0、s202 診斷 over 卻 EV +0.3，兩次都診斷偏藍但 Temp 兩次都是 0。street_rain 想要冷調兩次診斷偏藍、給 Temp -15/-16，是照使用者要求，不算錯。

### 想要／不想要（每項 seed 101／202，詳細數值在 `results-data.md`）

| 照片與要求 | A | B |
|---|---|---|
| food_breakfast：想要「溫暖、明亮、日系清新」，不想要「過飽和」 | 5/6、3/6：Exposure 有加（+0.4/+0.6）、Contrast 有降（中性 +20 → +15）、Temp 只 +5（比中性平均 +6 還低）；s202 還加了 Sat +5、Vibrance +20 | **6/6**、5/6：s101 Exposure +1.2、Contrast -30、Temp +15、Sat -10，最像日系清新；s202 比較保守（EV +0.7、Temp +8、Contrast +10） |
| street_rain：想要「冷調電影感」，不想要「暖／黃」 | 3/3、3/3：Temp -8／-15（中性平均 +5） | 3/3、3/3：Temp -15／-16（中性平均 +10.5）；s202 是唯一一次大量用 HSL（全部色相、飽和、亮度都往負推） |
| night_street：想要「救暗部」，不想要「霧面扁平」 | 4/4、4/4：Shadows +60／+50（中性平均 +37.5），Blacks -20／-15，Contrast +15／+10 | 4/4、4/4：Shadows +30／+40（中性平均 +9），Blacks -10／0，只動 3 個滑桿 |

（表內是我定義的檢查：見 `analyze.py` 的 `wish_checks()`；要求本身比較寬，兩個模型的方向基本都照做。）

## 每張照片：兩模型的診斷與數值（seed 101；s202 與完整問題清單見 `results-data.md`）

並排圖：`panels/<照片>.png`（原圖｜35B 第 1 次｜PE-I2I 第 1 次，下方附診斷與數值）；想要／不想要：`panels/wish_<照片>.png`（原圖｜35B 中性｜35B 依要求｜PE 中性｜PE 依要求）。

| 照片 | A 35B 診斷 → 主要數值 | B PE-I2I 診斷 → 主要數值 |
|---|---|---|
| portrait_studio（棚拍、灰藍背景） | 偏藍、曝光不足、低反差 → EV +0.8、Shadows +35、**Temp -15**（與診斷相反）、Clarity +15、Dehaze +15 | 偏藍、略暗、低反差 → EV +0.6、Shadows +10、Blacks -14、Temp +8 |
| landscape_lighthouse（暴風雨海岸） | 中性、略暗、低反差 → EV +0.8、Shadows +40、Clarity +25、Dehaze +15 | 偏藍、略暗、低反差 → EV +0.5、Temp +6、Dehaze +6（s202 改說「略過曝」但 EV 仍 +0.3） |
| night_street（魁北克夜景，實際偏暖） | 中性、略暗 → EV +0.55、Highlights -40、Shadows +30、Clarity +20（s202：偏藍、EV +1.25、Temp +12） | **偏藍**（錯，畫面是暖黃路燈）→ Temp +12（s202 同樣說偏藍但給 Temp -14） |
| street_rain（白天陰雨巷子） | 中性、曝光不足 → EV +0.45、Contrast +25、Blacks -20、Clarity +20 | 偏藍、略暗 → EV +0.4、Temp +6、Clarity +14 |
| food_breakfast（英式早餐） | 偏藍、略暗 → EV +0.35、Contrast +25、Shadows +30、Blacks -25、Temp +12 | 中性、略暗 → EV +0.4、Contrast +15、Shadows +25（s202 改說略過曝，EV -0.4） |
| interior_cafe（暖黃燈光拱頂） | 中性、曝光不足 → EV +0.75、Highlights -30、Shadows +30、Vibrance +25、多色 HSL（s202：EV +1.25、**Highlights -75、Shadows +80**、Clarity/Dehaze +35） | **偏暖（鎢絲燈）** → Temp -12、EV +0.4、Contrast +12 |
| sunset_kite（夕陽逆光） | 中性、曝光不足 → Highlights -35、Shadows +40、Dehaze +20、Temp +5 | 偏暖（夕陽，保留）→ Contrast +25、Highlights -15、Dehaze +12、Temp +5 |
| portrait_balaclava（戶外午後人像） | 中性、略暗 → EV +0.3、Contrast +15、Shadows +20；兩次都說是「beekeeper（養蜂人）」 | 偏暖、略過曝 → **EV -0.3、Temp -12**（把午後暖光當偏色修掉）；描述正確（女性、防曬帽遮臉） |
| food_bluecast_dark（人工偏藍＋太暗） | 偏藍、曝光不足、低反差 → EV +1.5、Shadows +60、Temp +25、Contrast +15、Blacks -15 | 偏藍、曝光不足、低反差 → EV +1.2、Shadows +40、Temp +12、Contrast +20、Blacks -15 |

兩個模型第 1 次的數值差：Shadows 平均差 17.8、Whites 13.3、Temperature 10.3、Highlights 10.2、Contrast 7.3、Exposure 0.22 EV。

## 觀察（代理意見）

1. **格式不是問題了**：`json_schema` 強制後兩者 48/48 全部合格（含範圍），Exposure 的小數範圍也被遵守。llama.cpp 的 json_schema 能吃 `minimum/maximum` 和 `enum`。
2. **速度兩者差不多**：每次約 10 秒，幾乎都花在生成約 550 tokens（31 個必填滑桿＋診斷文字）。想再快可以縮短 schema（HSL 改選填或只給 4 色）或限制 main_problems 長度；B 的診斷文字很長（subject 動輒一大段），可以加 `maxLength`。
3. **兩者都有「固定套路」偏差**：36 次中性回應裡，Contrast 全部為正、Blacks 全部為負、Clarity 全部為正、Highlights 幾乎全部為負；反差 35/36 次判為「low」。A 的曝光 18/18 都往上加、曝光判斷 18/18 都是「不足」，連午後人像、夕陽也一樣。B 更像填模板：大多數照片都是 Contrast +12、Highlights -10～-15、Whites -8、Blacks -14、Clarity +8 這組，只有偏藍暗照與要求明確時才大動。**B「兩次差異小」有一部分就是因為它套模板，不完全是「判斷穩」**。
4. **白平衡判斷兩者都不可靠**：B 把 9 張中的 5 張判成偏藍（含明顯偏暖的夜景街道），還出現「說要去藍卻往冷調」的正負相反；A 白平衡兩次一致只有 5/9，也有 1 次正負相反，但不會亂說偏藍。反過來，B 抓到了咖啡館的鎢絲燈偏暖（A 兩次都說中性），A 則漏掉。人工偏藍暗照兩者都抓到且方向全對。
5. **看圖內容**：這輪 B 沒有看到不存在的東西，描述反而比 A 細（雨巷招牌文字都讀出來）；A 兩次把戴防曬頭套的女生說成養蜂人。B 的毛病在「顏色判斷與數值對不上」，不是內容幻覺。
6. **保守度**：B 比較保守（Highlights/Shadows 多在 ±20 內），A 偶爾很猛（咖啡館 s202 Highlights -75、Shadows +80、Clarity/Dehaze +35；夜景 s202 EV +1.25）。「保守但有效」的要求 B 做得比較像。
7. **想要／不想要大致都照做**：冷調、救暗部兩者全對；日系清新 A 只過 8/12（暖得不夠、第二次還加飽和），B 11/12；B 的反應幅度比較大、比較像要求的樣子（日系清新 s101 降反差 -30、降飽和 -10），A 的「溫暖」只加 Temp +5，還在第二次加了飽和。
8. **HSL 幾乎沒在用**：B 18 次中只有 2 次碰 HSL；A 12 次有用但幅度小（±5～±15）。若要 HSL 有意義，提示詞要給明確情境（例如膚色、天空、植物）。

## 建議

- **預設用 B（PE-I2I，關思考）**，理由：同樣約 10 秒、VRAM 少 3.6GB、它本來就在萬事通裡、方向檢查和想要／不想要都不輸 A、數值比較保守。**但要配兩道防線**：
  1. **白平衡不要完全交給模型**：程式先量照片的灰世界／中性區偏色（例如中間調的 Lab a、b），把量到的結果寫進提示詞，或直接用量測值決定 Temperature/Tint 的方向，模型只決定幅度與是否保留（夕陽、暖光人像）。
  2. **規則檢查**：診斷與數值方向矛盾時（說偏藍卻往冷、說過曝卻加曝光）重問一次或把那個滑桿歸零。
- 想降低「每張都加反差、壓黑、加清晰度」的套路：在提示詞裡加「如果照片沒問題，大部分滑桿應該是 0」並給一個「不用修」的例子；或讓模型先輸出每個問題的嚴重度（0–3），程式依嚴重度換算幅度。
- A 留作備選：它曝光判斷有往上加的偏差、偶爾很猛，但白平衡不會亂判偏藍；如果之後要「描述照片內容」比較重要的功能，再重新比較。

## 最大的不確定點

1. **渲染器是粗略近似，不是最終引擎**：`render.py` 的每個滑桿強度都沒有對 Adobe 校準（例如 EV +1.5 在近似渲染裡看起來還是偏暗），並排圖只能看方向與大小，不能拿來判斷「調得好不好」。
2. **沒有標準答案**：方向檢查只有 9 條我能確定的規則（集中在偏藍暗照、夕陽、夜景），其他照片的「對不對」是代理主觀判斷；白平衡判斷的對錯是我看圖加平均 RGB 判斷的（夜景平均 RGB 約 100/78/59 明顯偏暖、雨巷 65/64/62 接近中性）。
3. **只有 2 個 seed**：兩次差異是溫度 0.7 下的取樣差異，樣本小；B 的低差異可能來自套模板，而不是判斷穩定。

## 檔案

- `run_sliders.py`：自己開／關 llama-server（port 8092），每張照片跑 seed 101/202，加 3 張想要／不想要；`python -s run_sliders.py --model A|B [--only id,...]`（用 ComfyUI 內建 Python）
- `render.py`：近似渲染器（CPU torch；WB/曝光在線性光、Highlights/Shadows 用 guided filter 底層、Contrast S 曲線、Whites/Blacks 端點曲線、簡化去朦朧、大半徑清晰度、小半徑紋理、鮮豔度／飽和度、HSL 8 色帶）
- `analyze.py` → `results-data.md`（全部數字、每張照片兩次的完整診斷、問題、數值、intent）
- `make_panels.py` → `panels/*.png`
- `raw/A/`、`raw/B/`：每次的原始回應（`<照片>__<run>.json`，含 content、timings、解析結果、驗證錯誤）、`summary.json`、`llama-server.log`；`raw/B/summary_food_bluecast_dark.json` 是正式跑之前的單張煙霧測試（照片檔已被正式跑覆蓋）
- `run-A.log`、`run-B.log`：執行過程
