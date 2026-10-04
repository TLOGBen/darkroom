# AI 補強實驗：未公開項目「程式近似 vs Qwen 修圖」＋「加強」混合（2026-10-04）

- 執行：2026-10-04 13:19～13:42（Qwen 17 支），桌機 RTX 4070 Ti SUPER、ComfyUI 0.38 headless、7 萬事通 Qwen-Image 2.1（UC Q8 GGUF、kitchen 注意力開）。
- 「代理意見」＝我看圖的主觀判斷；其餘是量測數字。

## 照片（photos.json）

| id | 內容 | 原圖尺寸 | 來源／授權 |
|---|---|---|---|
| portrait_laughing | 真人正面大笑（牙齒、髮絲） | 1280×1515 | [Commons: Laughing woman.jpg](https://commons.wikimedia.org/wiki/File:Laughing_woman.jpg)，CC BY-SA 4.0，Basile Morin |
| portrait_oldman | 真人特寫（皺紋、白鬍渣） | 1280×853 | [Commons: Old man face.jpg](https://commons.wikimedia.org/wiki/File:Old_man_face.jpg)，CC BY-SA 4.0，Basile Morin |
| portrait_studio | 棚拍側臉（AI 生成） | 896×1152 | repo 內 `ComfyUI/input/portrait_model_denim.png` |
| landscape_lighthouse | 暴風雨海岸燈塔（AI 生成） | 1376×768 | repo 內 `outputs/comfyui/qw/2026-10-04-lr-latency-busy_00001_.png` |
| fog_karst | 雲霧山谷（霧景／低反差） | 1280×853 | [Commons: Green karst peaks … with fog, Vang Vieng Laos](https://commons.wikimedia.org/wiki/File:Green_karst_peaks_seen_from_the_top_of_Mount_Nam_Xay_a_sunny_morning_with_fog_Vang_Vieng_Laos.jpg)，CC BY-SA 4.0，Basile Morin |

Commons 取 1024px 縮圖 API 給的檔（實際 1280 寬）。送 Qwen 的那份複製在 `ComfyUI/input/aib_<id>.png`。

## 做法

- **程式側**（`approx.py`，照 research/03 的推薦）：去朦朧＝暗通道＋fast guided filter（線性光、亮度比例與逐通道各半）；清晰度＝fast local Laplacian（K=12、σ=0.2、α=1−0.6·c/100）乘中間調權重；紋理＝Laplacian 金字塔第 1～2 層增益＋軟閾值去雜訊。正組＝清晰度 +40、去朦朧 +30、紋理 +40（`prog/<id>_pos.png`）；負組＝清晰度 −40（`prog/<id>_neg.png`）。修掉原型 `bench.py` 的一個錯：金字塔 `up()` 對塞零的影像做 replicate 補邊，左／上邊緣會出現一條暗線，改成 normalized convolution。
- **AI 側**（`run_ai.py` → 本資料夾的 `aio.py`／`wait.py` 副本，不寫進 repo 的 harness）：圖 1＝原照片、`--size 0`（跟著圖 1）、res1 1024。A 組英文指令兩種寫法（`--pe 0` 直接用、`--pe 1` PE 改寫），取樣主要用 Pruna 8 步（s1），laughing 加跑一支「自訂」euler_cfg_pp 32 步（s0）；負組（柔焦）跑 oldman 一支。B 組每張一組「想要／不想要」（`jobs.py`），`--pe 1 --sampler 0`，「不想要」同時寫進文字（Avoid: …）並放 `--neg`。
- **量測**（`measure.py`、`blend.py`、`common.py`）：Qwen 輸出用 lanczos 縮回原圖尺寸再比。位移＝16 塊區塊比對（template matching）的中位數與範圍，並由「位移對座標的斜率」估縮放；另有 Farneback 光流 p50/p95、SSIM、MAE（0～255）、Canny 邊緣 F1（容許 1.5 px）、ECC affine 對齊後的 SSIM。臉＝人像的臉框；風景是主體框（燈塔、山峰）。
- 原始數字：`metrics_A.json`／`metrics_A.md`、`metrics_B.json`／`metrics_B.md`；每次的時間：`runs.tsv`；PE 改寫後的全文：`pe_texts.json`；送出的 API 圖：`api/submitted/`。

## 時間

| 項目 | 時間 |
|---|---|
| 程式近似（正組三項全開），GPU | 1.0～1.5 MP：**42～69 ms**／張（`prog_timing_gpu.txt`；負組 35～51 ms） |
| 程式近似，CPU（16 核） | 0.8～2.7 s／張 |
| Qwen Pruna 8 步、PE 關 | **24 s**（第一支含載入 47 s）；8 步約 2.1 s/it |
| Qwen Pruna 8 步、PE 開 | 69～83 s（PE 走 llama-server 約 45～50 s） |
| Qwen 自訂 32 步、PE 關 | 78 s（2.11 s/it） |
| Qwen 自訂 32 步、PE 開＋負面提示詞（B 組） | 127～153 s |

## A：未公開項目（清晰度 +40、去朦朧 +30、紋理 +40）

### 尺寸
`--size 0` 會把圖 1 縮到約 1 MP、長寬取 32 的倍數，**不是原尺寸**：1280×1515 → 928×1120（長寬比差 −1.93%）、1280×853 → 1248×832（−0.04%）；896×1152、1376×768 本來就合規，不變。所以 Qwen 的結果一律比原圖小（1.3～1.9 MP 的照片會丟掉 30～45% 像素），要放回原圖得放大，細節變軟（fog_karst 最明顯）。

### 數字（節錄；完整見 `metrics_A.md`）

| 支 | 秒 | 位移 dx,dy（px，原圖座標） | 區塊 dx 範圍 | SSIM 對原圖 全/臉：Qwen | 程式 | 邊緣 F1：Qwen／程式 | ECC 對齊後 Qwen SSIM 全/臉 |
|---|---|---|---|---|---|---|---|
| laughing pe0 Pruna | 47 | **−26, +3** | −34～−20 | 0.403/0.189 | 0.981/0.979 | 0.539／0.874 | 0.673/0.500 |
| laughing pe1 Pruna | 83 | −28, +3 | −35～−21 | 0.400/0.194 | 0.981/0.979 | 0.537／0.874 | 0.662/0.492 |
| laughing pe0 **自訂 32 步** | 78 | **−3, −5** | −6～−1 | 0.436/0.241 | 0.981/0.979 | 0.659／0.874 | 0.610/0.483 |
| oldman pe0 Pruna | 24 | −23, +4 | −26～−18 | 0.460/0.137 | 0.982/0.977 | 0.694／0.888 | 0.775/0.608 |
| oldman pe1 Pruna | 69 | −23, +4 | −26～−18 | 0.469/0.142 | 0.982/0.977 | 0.695／0.888 | 0.790/0.625 |
| studio pe0 Pruna | 24 | −14, +1 | −34～−13 | 0.659/0.627 | 0.980/0.976 | 0.087／0.785 | 0.858/0.909 |
| studio pe1 Pruna | 73 | −15, +1 | −34～−14 | 0.662/0.625 | 0.980/0.976 | 0.084／0.785 | 0.859/0.893 |
| lighthouse pe0 Pruna | 24 | −18, +4 | −20～−16 | 0.636/0.662 | 0.980/0.971 | 0.497／0.889 | 0.891/0.946 |
| lighthouse pe1 Pruna | 76 | −17, +3 | −24～−16 | 0.574/0.652 | 0.980/0.971 | 0.461／0.889 | 0.805/0.874 |
| fog pe0 Pruna | 24 | −21, +5 | −25～−17 | 0.290/0.099 | 0.983/0.987 | 0.771／0.952 | 0.587/0.483 |
| fog pe1 Pruna | 73 | −20, +5 | −23～−17 | 0.280/0.101 | 0.983/0.987 | 0.770／0.952 | 0.559/0.432 |
| 負組 oldman 清晰度 −40，pe0 Pruna | 25 | −23, +4 | −26～−18 | 0.508/0.174 | 0.994/0.992 | 0.684／0.929 | 0.820/0.635 |

（dx 負＝內容往左移。縮放估計 sx 0.985～1.001、sy 0.985～1.000：Pruna 除了平移，水平還縮了約 0.7～1.5%。）

### 觀察
- **Pruna 8 步每張都整張往左移 14～28 px（Qwen 原生像素約 14～22 px）、往下 1～5 px**，跟照片、PE 開關無關；自訂 32 步只有 3～5 px。B 組（全是自訂 32 步）也只有 0～7 px（見下）。這是取樣設定本身的系統性偏移，不是隨機的。
- 程式側對原圖 SSIM 0.98 上下、邊緣 F1 0.79～0.95：只改色調與局部對比，幾何完全不動（照定義本來就該這樣）。
- Qwen 就算用 ECC 把平移與縮放扳正，SSIM 也只回到 0.56～0.89、臉部 0.43～0.95：剩下的差異是**重畫內容**，不是位移。
- PE 開或關：數字幾乎一樣（同種子、同取樣時構圖與位移一致），PE 多花約 45～50 秒。看圖差異也不大；PE 寫得更長、更強調「不要改臉」，但結果沒有比較守規矩。oldman 那支 PE 輸出開頭多了 `{"`（萬事通剝 JSON 的 RegexReplace 沒剝乾淨），仍正常出圖。

### 並排圖（原圖｜程式｜Qwen，下排臉／主體放大）
- [A laughing pe0 Pruna](panels/A_aib-A-portrait_laughing-pe0-s1.png)、[pe1 Pruna](panels/A_aib-A-portrait_laughing-pe1-s1.png)、[pe0 自訂 32 步](panels/A_aib-A-portrait_laughing-pe0-s0.png)
- [A oldman pe0](panels/A_aib-A-portrait_oldman-pe0-s1.png)、[pe1](panels/A_aib-A-portrait_oldman-pe1-s1.png)、[負組 清晰度 −40](panels/A_aib-Aneg-portrait_oldman-pe0-s1.png)
- [A studio pe0](panels/A_aib-A-portrait_studio-pe0-s1.png)、[pe1](panels/A_aib-A-portrait_studio-pe1-s1.png)
- [A lighthouse pe0](panels/A_aib-A-landscape_lighthouse-pe0-s1.png)、[pe1](panels/A_aib-A-landscape_lighthouse-pe1-s1.png)
- [A fog pe0](panels/A_aib-A-fog_karst-pe0-s1.png)、[pe1](panels/A_aib-A-fog_karst-pe1-s1.png)

**代理意見：A 組每一張都是程式比較好。**
- Qwen 把「清晰度／去霧／紋理」理解成「整體重調色＋重畫細節」：laughing 自訂 32 步那支變得更飽和、更暗、反差更硬，嘴形和眼型也被改（笑容變窄）；Pruna 那支色調較接近，但牙齒、皺紋是重畫的。oldman 的皺紋紋理被換成另一套，白鬍渣減少。fog 的山峰因為縮到 1 MP 再放大，樹叢細節反而變糊，山峰輪廓有小改動。
- 程式側：效果幅度可預測、不碰幾何、不改人。弱點是清晰度 +40 在 laughing 的背景與皮膚上有點「髒」（LLF 參數沒校）、去朦朧在沒霧的人像上會讓整體變暗一點（平均約 −2～−3／255）。這些是調參問題，不是方向問題。
- 負組（柔焦 −40）：程式側變化很小（MAE 1.2，太保守，係數要加大）；Qwen 沒有做出柔焦，反而照樣重畫了皮膚紋理。

## B：加強（想要／不想要），與程式結果 25／50／75／100% 混合

B 組的「想要／不想要」寫在 `jobs.py`（例如 laughing：想要「更通透、皮膚乾淨、暖一點」，不想要「過度飽和、塑膠皮膚、改變牙齒或表情」）。混合公式：`(1−a)·程式正組 + a·Qwen（縮回原圖尺寸）`。

| photo | 秒 | 區塊比對位移 dx,dy（程式→Qwen） | 光流 p95 全圖／臉 | 各細節區光流 p95 | ECC 對齊後光流 p95 | Qwen vs 程式 SSIM（對齊前→後） |
|---|---|---|---|---|---|---|
| portrait_laughing | 153 | −3.5, −7 | 9.45／9.69 | eyes 8.8、hair 6.3、teeth 10.0 | 1.27 | 0.456 → 0.656 |
| portrait_oldman | 149 | −1, 0 | 2.76／2.59 | eyes 2.4、hair 3.6、mouth 1.9 | 1.59 | 0.665 → 0.716 |
| portrait_studio | 127 | −2, −4.5（sy 0.98） | 6.05／4.11 | eye 4.0、hair 3.5、zip 6.1 | 1.14 | 0.736 → 0.837 |
| landscape_lighthouse | 134 | 0, 0 | 46.8／6.2（天空整片重畫，光流失效） | tower 7.6、waves 1.1、rock 1.2 | 38.3 | 0.704 → 0.626 |
| fog_karst | 145 | −2, +1 | 4.16／3.04 | crag 3.2、fog 3.9、fields 3.0 | 1.51 | 0.400 → 0.523 |

並排圖（第一排整張 0～100%，下面每排是一個細節區放大）：
[laughing](panels/B_portrait_laughing.png)、[oldman](panels/B_portrait_oldman.png)、[studio](panels/B_portrait_studio.png)、[lighthouse](panels/B_landscape_lighthouse.png)、[fog](panels/B_fog_karst.png)；混合圖本身在 `blends/<id>_<百分比>.png`。

對齊後再混（50%，直接混｜ECC 對齊後混｜光流對齊後混）：
[laughing](panels/B50_aligned_portrait_laughing.png)、[oldman](panels/B50_aligned_portrait_oldman.png)、[studio](panels/B50_aligned_portrait_studio.png)、[lighthouse](panels/B50_aligned_landscape_lighthouse.png)、[fog](panels/B50_aligned_fog_karst.png)

### 重影（代理意見，看放大圖）
- **laughing（錯位約 4～10 px）：25% 就看得出重影**（牙齒邊緣兩層、眼睛輪廓雙線），50～75% 最嚴重。而且 Qwen 重畫了下排牙齒與舌頭，就算對齊也是「兩副不同的牙齒疊在一起」。
- **studio（4～6 px）：25% 在側臉輪廓（鼻樑、嘴唇、睫毛）開始有淡淡的雙邊**，50% 明顯。頭髮因為本身是雜亂紋理，看不太出來。Qwen 還把領口羅紋改成另一種條紋。
- **oldman（2～3.6 px）：25% 幾乎看不出；50% 在白髮與鬍渣的細線上開始變糊、有雙線**；Qwen 把白鬍渣大部分抹掉了（違反「不想要：磨皮」），混越多鬍渣越少。
- **lighthouse：天空的雲被整片換掉**（光束也不見了），25% 就是兩層雲疊在一起的「雙重曝光」；燈塔、浪、岩石本身錯位小（1～8 px），重影不明顯。
- **fog：錯位 3～4 px，25～50% 在山峰岩壁、田埂上輕微變糊**，因為原圖細節多，看起來像對焦不準，而不是明顯雙線。Qwen 那張本身的岩壁與樹叢也比原圖糊（1 MP 再放大），雲霧反而變得更濃更白。
- **先對齊再混能消掉大部分「位移造成的重影」**：ECC affine 對齊後殘餘光流 p95 降到 1.1～1.6 px；laughing 的牙齒在 50% 從明顯雙層變成單層（見 B50_aligned 圖）。但 Qwen 重畫掉的內容（雲、牙齒形狀、鬍渣）對齊也救不回來，只是變成「兩種內容的平均」。

### B 的加強效果本身（代理意見）
- 「暖一點、更通透」這類**整體色調**的要求 Qwen 有做到，有時做得比要求更重（laughing 偏飽和、反差偏硬；fog 綠色變深、細節變糊，倒沒有過飽和），儘管「不想要：過度飽和」寫在文字與負面提示詞裡。
- 「不要改臉／牙齒／鬍子／雲」這類保留要求**沒被遵守**：每張都有內容被重畫。

## 結論與建議

1. **未公開項目（清晰度、去朦朧、紋理）全由程式近似**——支持使用者的暫定方向。程式：40～70 ms、幾何零位移、可逆、可調強度；Qwen：24～150 s、位移與重畫、改人。A 組沒有任何一張是 Qwen 比較好。
2. **AI「加強」若要跟程式結果混合，一定要做到這三件事，否則 25% 就會看到重影**：
   - 取樣用「自訂 32 步」或之後驗證過的設定，**不要用 Pruna 8 步**（系統性左移 14～28 px）。
   - 不要用 `--size 0` 的 1 MP 輸出直接混：要不在原尺寸（或至少照原長寬比、不捨入）跑，要不混合前先 **ECC／光流對齊**到程式結果（本實驗對齊後殘餘 1.1～1.6 px）。
   - 混合強度預設低（≤25%），而且最好是**分區遮罩混合**（例如只取 Qwen 的皮膚／天空色調，臉部五官、牙齒、頭髮、鬍渣排除），或乾脆只取 Qwen 結果的**低頻（色調／色彩）**套回程式結果，高頻細節保留程式的——推論，尚未實測。
3. PE（`--pe 1`）在這類「保留構圖的微調」上沒帶來可量測的好處，多 45～50 秒；直接寫英文修圖指令即可。
4. 程式側要調的：清晰度 + 紋理在人像皮膚上偏「髒」、去朦朧在無霧人像上整體偏暗、清晰度負值太弱。

## 最大的不確定點

- **Qwen 的內容重畫是否能靠設定壓下來**（例如降低 denoise、ControlNet／參考約束、改用局部遮罩修圖）：這次只用 7 萬事通的現成選項（denoise 固定 1.0），沒有測。如果能做到「只改色調不改內容」，第 2 點的結論會變。
- Pruna 左移的原因（LoRA、deis_2m、還是 8 步本身）沒拆開測；只確定跟照片、PE 無關、自訂 32 步沒有這個問題。
- 程式側參數都是推論的初值，沒有對 Adobe 校正；「程式比較好」是指「忠實、可控」，不代表它像 Lightroom。
- 照片只有 5 張、每個設定只跑一個種子（20260929）。
