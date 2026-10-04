# 03 研究：Adobe 未公開演算法的公開近似法

- 日期：2026-10-04
- 票：`issues/03-proprietary-approximations.md`（研究票，狀態由主 session 判斷）
- 範圍：Clarity2012、Dehaze、Texture、PV2012 的 Highlights／Shadows／Whites／Blacks、PV2012 Exposure 的高光滾降；另評估 ComfyUI「LRTemplate Loader／Apply」節點。
- 標記：**「推論」**＝來源沒有明說、是我依來源與程式推出來的；**「本機實測」**＝我在這台 RTX 4070 Ti SUPER 上用 ComfyUI 內建 Python（torch 2.14.0+cu130）跑的原型數字。其餘每句事實附來源編號。

## 來源清單

| # | 來源 | 用途 |
|---|---|---|
| S1 | Adobe Lightroom Journal〈Magic or Local Laplacian Filters?〉2012-02 https://blogs.adobe.com/lightroomjournal/2012/02/magic-or-local-laplacian-filters.html （直接連線憑證錯誤，內容取自搜尋摘要） | Adobe 自己說 PV2012 的 Highlights／Shadows／Clarity 源自 local Laplacian filter |
| S2 | Paris, Hasinoff, Kautz, *Local Laplacian Filters*, SIGGRAPH 2011 https://people.csail.mit.edu/sparis/publi/2011/siggraph/ | LLF 原始論文 |
| S3 | Aubry et al., *Fast Local Laplacian Filters: Theory and Applications*, TOG 2014 https://imagine.enpc.fr/~aubrym/projects/llf/texts/2014-fast-laplacian-filter.pdf | 快速 LLF、GPU 時間、光暈與金字塔層數的關係 |
| S4 | Adobe Blog〈From the ACR Team: Introducing the Texture Control〉2019-05-14（Max Wendt）https://blog.adobe.com/en/publish/2019/05/14/from-the-acr-team-introducing-the-texture-control | Texture 的頻帶與跟 Clarity 的差別 |
| S5 | DPReview〈Lightroom 4 Review〉PV2012 頁 https://www.dpreview.com/articles/7481161037/lightroom-4-review/2 | PV2012 Exposure 滾降、Clarity 光暈改善 |
| S6 | DPReview〈Extreme contrast edits in Lightroom 4 and ACR 7〉 https://www.dpreview.com/articles/1205103502/extreme-contrast-edits-in-lightroom-4-and-acr-7 | PV2012 控制項是 scene adaptive |
| S7 | Adobe Help〈Tone Control Adjustment in Lightroom Classic and ACR〉（Web Archive 2025-01-15）https://web.archive.org/web/20250115232702/https://helpx.adobe.com/lightroom-classic/help/tone-control-adjustment.html | 「Basic panel Tone controls are image adaptive」、Whites／Blacks 設定裁切點 |
| S8 | darktable `src/develop/lightroom.c`（Lightroom XMP 匯入）https://github.com/darktable-org/darktable/blob/master/src/develop/lightroom.c | Clarity2012 → local contrast detail ±0.65 的對照表；沒有對 Highlights/Shadows/Dehaze/Texture 做對應 |
| S9 | darktable `src/common/locallaplacian.c` https://github.com/darktable-org/darktable/blob/master/src/common/locallaplacian.c | 一條重映射曲線同時帶 shadows／highlights／clarity；預覽緩衝補邊 |
| S10 | darktable 手冊 local contrast https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/local-contrast/ | LLF 模式抗光暈、bilateral grid 模式 |
| S11 | darktable `src/iop/hazeremoval.c` https://github.com/darktable-org/darktable/blob/master/src/iop/hazeremoval.c ＋手冊 https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/haze-removal/ | Dark channel prior＋guided filter；A0 從預覽管線算一次 |
| S12 | darktable 手冊 tone equalizer https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/tone-equalizer/ | guided filter 遮罩＋分 EV 區增益、光暈警告 |
| S13 | RawTherapee `rtengine/ipdehaze.cc` https://github.com/RawTherapee/RawTherapee/blob/dev/rtengine/ipdehaze.cc | DCP＋guided filter、strength×0.9、depth、luminance／RGB 混合（saturation） |
| S14 | RawTherapee `rtengine/iplocalcontrast.cc` https://github.com/RawTherapee/RawTherapee/blob/dev/rtengine/iplocalcontrast.cc | 大半徑 unsharp（L 通道，暗／亮分開倍率） |
| S15 | RawTherapee `rtengine/ipshadowshighlights.cc` https://github.com/RawTherapee/RawTherapee/blob/dev/rtengine/ipshadowshighlights.cc | guided filter 平滑遮罩＋gamma 曲線混合 |
| S16 | He, Sun, Tang, *Single Image Haze Removal Using Dark Channel Prior*, TPAMI 2011（DOI 10.1109/TPAMI.2010.168）；*Guided Image Filtering*, ECCV 2010（DOI 10.1007/978-3-642-15549-9_1）（引自 S11 檔頭） | 去霧與 guided filter 原論文 |
| S17 | Adobe DNG SDK `dng_render.cpp`（GoPro 鏡像）https://github.com/gopro/gpr/blob/master/source/lib/dng_sdk/dng_render.cpp | Adobe 公開參考渲染器的曝光函式：負曝光用二次曲線讓白仍對到白 |
| S18 | mcaishao123/ComfyUI-lut（MIT）https://github.com/mcaishao123/ComfyUI-lut | **LRTemplate Loader／Apply 的出處** |
| S19 | comfyai.run 節點文件 https://comfyai.run/documentation/LRTemplate%20Apply （現已轉址到 stackblend.com，內容取自搜尋摘要） | 節點說明 |
| S20 | markyip/RAWviewer（MIT）https://github.com/markyip/RAWviewer （`src/raw_pv2012.py`、`raw_effects.py`、`raw_detail_enhance.py`、`docs/EDIT_PIPELINE.md`） | 另一個讀寫 XMP 的開源重現（啟發式） |
| S21 | tedyeng/LumiBase PR #7 https://github.com/tedyeng/LumiBase/pull/7 （repo 無授權條款） | 宣稱用 12 點取樣對 Lightroom Classic 校正 PV2012 負 Highlights |
| S22 | RenderDeMartes/VibePhoto（MIT）https://github.com/RenderDeMartes/VibePhoto （`src/vibephoto/processing/ops.py`） | 另一個 XMP 匯入＋簡化 dehaze |
| S23 | discuss.pixls.us〈Dehaze equivalent in darktable or RawTherapee〉 https://discuss.pixls.us/t/dehaze-equivalent-in-darktable-or-rawtherapee/310 | 社群觀察：LR Dehaze 有光暈、保色較好 |
| S24 | John Paul Caponigro〈A Quick Cure For Dehaze Color Shifts〉 https://johnpaulcaponigro.com/blog/?p=19313 ；Adobe 社群 bug〈Dehaze altering the color balance〉 https://community.adobe.com/t5/camera-raw-bugs/p-camera-raw-lightroom-dehaze-altering-the-color-balance-white-balance-of-photos/idi-p/12239991/page/2 （皆取自搜尋摘要） | Dehaze 的色偏（中性變洋紅、暗部偏藍綠、整體變冷變飽和） |
| S25 | Adobe〈Clarity slider〉指南 https://adobe.com/creativecloud/photography/hub/guides/clarity-slider ；Peachpit（Martin Evening）〈Using the Clarity Slider in Lightroom〉 https://peachpit.com/articles/article.aspx?p=1223083 （取自搜尋摘要） | Clarity 只動中間調；早期 Clarity＝大半徑低量 USM＋中間調對比 |
| S26 | kornia `filters.guided_blur` https://kornia.readthedocs.io/en/stable/filters.html | 現成的 PyTorch guided filter（含 subsample＝fast guided filter） |
| S27 | LYL1015/JarvisArt https://github.com/LYL1015/JarvisArt | 學術修圖代理：產出 .lrtemplate 後仍要在 Lightroom Classic 裡套用 |

---

## 0. 先看資料：使用者的 1466 個 preset 實際怎麼用這幾項（本機統計）

對 `artifact/11_preset/xmp` 全部 xmp 做統計（2026-10-04）：

| 參數 | 非零個數 | 平均 \|值\| | 最大 \|值\| | \|值\|≥50 的個數 | 正／負 |
|---|---|---|---|---|---|
| Highlights2012 | 1352 | 46.1 | 100 | **566** | 253／1099 |
| Shadows2012 | 1353 | 41.1 | 100 | **458** | 1172／181 |
| Blacks2012 | 1324 | 38.3 | 100 | **384** | 811／513 |
| Whites2012 | 1316 | 36.2 | 100 | **332** | 551／765 |
| Clarity2012 | 1083 | 16.7 | 99 | 33 | 848／235 |
| Dehaze | 673 | 17.6 | 79 | 9 | 579／94 |
| Texture | 324 | 16.4 | 80 | 2 | 245／79 |
| Exposure2012 | 1015 | 0.4 EV | 2.4 EV | — | 561／454 |

ProcessVersion：11.0（PV2012/第 5 版）1277 個、10.0 有 31 個、15.4 有 101 個、**6.7 有 57 個**（6.7 是 PV2010，用的是 Recovery／FillLight 那套舊滑桿，不在這張票的範圍，要另外處理或標示不支援——推論，需另行確認）。

**結論（推論）**：決定「像不像」的大頭是 **Highlights／Shadows／Whites／Blacks**——幾乎每個 preset 都用、而且數值大；Blacks 有 811 個是「正值」（把黑色抬起來＝霧面感的主要來源）。Clarity／Dehaze／Texture 雖然常出現，但多半是 ±10～30 的輕調，近似誤差的影響小得多。所以調校精力應該先花在亮部／陰影／白／黑。

---

## 1. 共通設計原則（各項都適用）

1. **在線性光或感知亮度上做、只改亮度再把比例套回 RGB**。RawTherapee 的 dehaze 有「只動亮度」和「每通道」兩種結果可混合（S13 的 `satBlend`）；darktable 的 local contrast 只動 Lab 的 L（S10）。推論：只動亮度比較不會色偏；要模仿 Adobe 的「順帶變飽和」再刻意混入每通道結果。
2. **半徑要跟著圖的尺寸走，不能用固定像素**。darktable 的 hazeremoval 依縮放比例算視窗大小（S11：`w1 = 2 + ceil(4*wscale)`），RawTherapee 的 dehaze `patchsize = max(5/scale, 2)`（S13），local contrast `sigma = radius / scale`（S14）。我們預覽 1.5MP、輸出 24MP，半徑一律用「長邊的比例」定義（推論）。
3. **整張圖的統計值（去霧的大氣光 A、白／黑的百分位數）在預覽圖算一次、全尺寸沿用**。darktable 的 hazeremoval 就是從預覽管線取 A0 與最大距離給其他管線用，避免預覽跟輸出不一致（S11）。darktable 的 LLF 也特別處理「用預覽緩衝補邊」讓區塊處理結果一致（S9）。
4. **光暈是共同風險**：Aubry 等人指出 LLF 金字塔層數在中間時會出光暈、很淺或完整金字塔時通常不會（S3）；tone equalizer 手冊警告平滑度與邊緣保留要取捨，太平滑會出光暈（S12）。

---

## 2. LRTemplate Loader／Apply：出處與值不值得參考

- **出處**：GitHub `mcaishao123/ComfyUI-lut`（MIT，最後 commit 2026-03-08）。README 列出 8 個節點，其中「LRTemplate Loader 📷」「LRTemplate Apply 🎨（支援強度調節）」「LRTemplate Manual」「LRTemplate Search Loader」（S18）。comfyai.run 的文件頁也描述同名節點「載入 .lrtemplate／.xmp、以可調強度套用」（S19）。
- **支援的參數**：曝光、對比、Highlights／Shadows／Whites／Blacks、Clarity、自然飽和度／飽和度、色溫色調、曲線、HSL、分離色調、暗角、顆粒（S18 README）。**沒有 Dehaze、沒有 Texture**。
- **實作（讀 `lr_adjust.py`，S18）**：
  - Exposure：`factor = 2 ** (exposure / 2.0)`，註解寫「LR uses ~stops, we halve for subtlety」——**直接把 EV 減半、在 sRGB 值上乘**，沒有線性化、沒有滾降。
  - Highlights／Shadows／Whites／Blacks：用**全域**亮度遮罩加減固定量（例如 Highlights：`mask = clip((x-0.5)*2)`，`x -= h*0.3*mask`），沒有任何局部（空間）成分。
  - Clarity：PIL `GaussianBlur(radius=max(3, min(h,w)//20))` 的 unsharp mask，`amount = clarity/100*0.5`，作用在 RGB 三通道、全亮度範圍。
  - README 自己承認複雜 preset「純 Python 節點無法 100% 完美解析」，建議用 Photoshop Camera Raw 對 HALD 圖套 preset 抽成 `.cube`（`hald_tool.py`）——這條路需要 Photoshop，對我們沒用（S18 README）。
- **評估（推論）**：**不值得參考演算法**。它的亮部／陰影是全域曲線（做不出 PV2012「壓亮部但保留雲的層次」的局部效果）、曝光倍率是拍腦袋、Clarity 是全色版大半徑 USM（大值會出光暈、會改色）。可以借的只有「xmp 解析＋強度內插」的節點介面形狀，而我們 repo 裡的 `ComfyUI-LightroomXMP` 已經有自己的解析器。

### 其他「在 Lightroom 外重現 XMP」的開源專案（都是啟發式，沒有一個公開了對 Adobe 的系統性量測）

| 專案 | Clarity | Dehaze | Texture | H/S/W/B | 備註 |
|---|---|---|---|---|---|
| darktable XMP 匯入（S8） | → local contrast（bilateral），detail = ±0.65 線性對應 ±100，sigma_r = sigma_s = 100 | 不匯入 | 不匯入 | 只匯入 Blacks（→exposure 模組 black，±100 對 −0.010～+0.020）與 Exposure | 最老牌的開源對照表，但只有 Clarity 與 Blacks |
| RAWviewer（S20，MIT） | 亮度 unsharp，sigma 10 px、強度 c/100×0.75 | 簡化 DCP（≤720px 上算、高斯平滑透射率、t≥0.12），負值往大氣光混 | 無 | 線性光「分區曝光」：Shadows 最多 ±1.75 stop、Highlights ±1.55 stop，用平滑亮度遮罩；另有感知空間曲線 | 註解裡記了很多「調了會反轉／出雜色」的踩坑；沒有對 Adobe 的量測 |
| LumiBase（S21，無授權） | CoreImage unsharp 半徑 12 | 併進 Contrast（+0.4×）與飽和度 | 半徑 1.2 銳化／1.5 柔化 | 曲線＋guided filter（eps 0.08²）去地平線光暈 | PR 宣稱「12 點取樣與 Lightroom Classic 緊密一致」「雲的動態範圍在 3 階以內」，但只針對負 Highlights，且無授權不能抄碼 |
| VibePhoto（S22，MIT） | 亮度 unsharp（大半徑） | 暗通道 85 百分位當霧幕減掉＋Contrast＋飽和度 | 同函式小半徑 | 全域亮度遮罩 | 簡化版 |
| JarvisArt（S27） | — | — | — | — | 學術修圖代理，產出 .lrtemplate 後仍要丟回 Lightroom Classic 套用——連研究專案也沒有自己的渲染器 |

---

## 3. Clarity（清晰度，Clarity2012）

**已知事實**
- Adobe 自己說 PV2012 的 Clarity（與 Highlights、Shadows）是受 local Laplacian filter 研究啟發（S1，作者 Sylvain Paris 是 Adobe 研究員，S2）。
- PV2012 的 Clarity 比 PV2010 版「調高也不容易在高反差邊緣出光暈」（S5）。
- Adobe 的說法是 Clarity 只影響中間調、最亮與最暗不動（S25）；早期（PV2003/2010）的 Clarity 是「大半徑低量 USM＋中間調對比」的混合（S25 Peachpit）。
- Clarity 改變亮度與飽和度的幅度比 Texture 大、作用在較大的色調區塊（S4）。

**候選方法**

| 方法 | 做法 | −100～+100 對應（推論，初值待校） | 成本（本機實測，見 §8） | 跟 Adobe 的差異／風險 |
|---|---|---|---|---|
| A. 快速 local Laplacian（Aubry 2014）＋中間調權重 | 在 log 亮度（或 L*）上做 LLF，重映射函式 r(i)= g + sign(d)·σr·(\|d\|/σr)^α（\|d\|<σr），α<1 增強細節、α>1 平滑；再乘一個中間調鐘形權重 w(L) | α = 1 − 0.6·c/100（c>0）、α = 1 + 0.8·\|c\|/100（c<0）；σr ≈ 0.15～0.25（log2 亮度單位）；w(L)=4L(1−L) 類鐘形 | K=8 單通道：1.5MP **10 ms**、24MP **92 ms**（峰值 7 GB fp32，要 fp16 或分塊） | Adobe 明說 PV2012 Clarity 源自這族方法，**最接近**；LLF 本身抗光暈與梯度反轉（S10）。風險：σr 與中間調權重形狀不知道 Adobe 怎麼取，大正值時質感（「髒」的程度）可能不同 |
| B. guided filter 基底／細節分解 | base = guided(log Y)，detail = logY − base，out = base + (1+k)·detail·w(L) | k = 0.8·c/100（負值時 k 下限 −0.9） | r≈長邊 2%、subsample 4：1.5MP **0.5 ms**、24MP **7 ms** | 單一尺度，強邊緣處仍可能有輕微光暈（eps 小較好）；比 LLF 便宜十倍以上 |
| C. 大半徑 unsharp mask（RT local contrast、darktable XMP 匯入、ComfyUI-lut、RAWviewer 都是這類） | Y + a·(Y − Gauss_σ(Y))，σ 為長邊 1～3% | a = 0.5～0.75·c/100（各專案的值，S14/S18/S20）；darktable 匯入用 detail ±0.65（S8） | 用金字塔做大模糊：1.5MP **0.5 ms**、24MP **3.6 ms** | **這正是 PV2010 以前出光暈的做法**（S5 說 PV2012 改善的就是這點）；在天空／建築邊緣大值會有明顯白邊 |

**推薦：A（快速 LLF）**，B 當備案或預覽加速用。理由：Adobe 自己證實 PV2012 Clarity 是 LLF 系（S1）；這台 GPU 上 24MP 不到 0.1 秒、1.5MP 10 ms，拖滑桿即時沒問題；preset 的 Clarity 多數只有 ±10～30，A 在小值時跟 B、C 差不多，但少數大值（33 個 ≥50）時 A 不出光暈。darktable 的 `locallaplacian.c`（S9）是現成的可讀參考（GPL，**只能參考思路、不能直接抄進非 GPL 程式**——推論）。

---

## 4. Dehaze（去朦朧）

**已知事實**
- Adobe 沒公開演算法。社群觀察：LR 的 Dehaze 在物體邊緣會出光暈（S23），但「保留原色較好」（S23）；大正值時會讓中性變洋紅、暗部偏藍綠、整體變暗變冷變飽和（S24）。
- 開源的兩家都用 He 等人的 dark channel prior＋guided filter（S11、S13、S16）：
  - RawTherapee：`strength = clamp(s/100 × 0.9)`；先用 guided filter 平滑 RGB 求暗通道與大氣光（取最霧的 5% 區塊）；透射率再用 guided filter（radius = patch×4、eps 1e-5）細化；`depth` 決定透射率下限 `t0 = exp(−depth × maxDistance)`；最後在「只按亮度比例恢復」與「每通道恢復」之間用 saturation 參數混合（S13）。負值時走「加霧」分支（S13 `add_haze`）。
  - darktable：strength −1～1、distance 0～1；guided filter eps = √0.025；`t_min = exp(−distance × distance_max)`；A0 與 distance_max 從預覽管線算一次給全尺寸用（S11）。手冊提醒：它會增加對比，但不是拿來當對比工具，沒有霧的圖上常會失敗（S11 手冊）。

**候選方法**

| 方法 | 做法 | 對應（推論） | 成本（本機實測） | 差異／風險 |
|---|---|---|---|---|
| A. DCP＋guided filter（RT／darktable 路線） | 暗通道（patch ≈ 長邊 0.5%）→ 大氣光 A（預覽上取最亮暗通道 0.1%）→ t = 1 − ω·dark(I/A) → guided filter 細化（subsample 4）→ J = (I−A)/max(t,t0)+A；負值：I' = I + ω·(1−t)·(A−I) | ω = 0.9·d/100（照 RT）；t0 ≈ 0.1～0.2；亮度／每通道混合比例 m ≈ 0.5 起調（m 越大越飽和、越容易色偏，對應 S24 的現象） | 1.5MP **2.1 ms**、24MP **25.6 ms**（含 GF；24MP 時 A 用預覽值） | 物理模型與 Adobe 的副作用（變暗、變飽和、白平衡偏移）方向一致——推論：S24 描述的色偏正是 A 不中性時每通道恢復會出的現象。風險：沒霧的圖（多數人像 preset 也會 +10～+20 Dehaze）上 DCP 的 t 估計不穩，天空會過暗、出光暈 |
| B. 全域「霧幕扣除＋對比＋飽和」（VibePhoto／LumiBase 路線） | 用暗通道某百分位當霧幕 v，out = (I − a·v)/(1 − a·v)，再加 Contrast 與 Saturation | VibePhoto：a·v×0.5、contrast a×30、saturation a×25（S22）；LumiBase：把 0.4×Dehaze 加到 Contrast（S21） | <1 ms（只是 LUT 與一次百分位，推論） | 沒有局部性：遠景霧跟近景同量處理；但**不會有光暈也不會失敗**，對小值（preset 平均 17.6）其實可能更像 |
| C. A 與 B 混合（依數值大小或霧度切換） | 小值或圖上估不出霧時偏向 B，大值且有霧時偏向 A | 混合權重 = f(\|d\|, 預覽上估的 distance_max) | A＋B | 實作稍複雜；需要校正兩套參數 |

**推薦：A（DCP＋guided filter），但 t0 給偏高、亮度恢復為主（m 偏低），並保留 C 的「霧估不出來就退回 B」的保險**。理由：只有 A 能產生「遠處去霧多、近處少」的局部效果與 Adobe 的典型副作用；24MP 26 ms 夠快；RT／darktable 兩個成熟實作都是這條路、參數範圍可直接借（S11、S13）。風險已知且可控：A、t0、m 都在預覽上決定一次。

---

## 5. Texture（紋理）

**已知事實（S4，Adobe 主導工程師 Max Wendt 的說明）**
- Sharpening 作用在高頻（邊緣、細節），Texture 作用在**中頻**；「雜訊大致不動，雜訊以下的中頻特徵被加強」。
- 負值（−1～−100）是平滑，常被拿來跟降噪比，可以把皮膚弄平又不抹掉細節。
- Clarity 比 Texture 強、會改更多亮度與飽和度，Texture 較細膩。

**候選方法**

| 方法 | 做法 | 對應（推論） | 成本（本機實測） | 差異／風險 |
|---|---|---|---|---|
| A. Laplacian 金字塔中頻帶增益＋coring | 對 log 亮度建 Laplacian 金字塔，只放大／縮小「中頻」那幾層（以長邊比例定義，例如細節尺寸約長邊 0.05%～0.4%：24MP 約 3～24 px、1.5MP 約 1～6 px），每層係數先過一個軟閾值（coring）避開雜訊再乘增益 | gain = 1 + 1.0·t/100（t>0）、gain = 1 − 0.8·\|t\|/100（t<0）；coring 閾值依層估的雜訊 σ（MAD）×1～2 | 跟 Clarity 共用金字塔時幾乎免費；單獨做：1.5MP **0.5 ms**、24MP **3.6 ms** 量級（同金字塔 down/up 的實測） | 最貼近 Adobe「只動中頻、不動雜訊」的描述（S4）；風險是 1.5MP 預覽時中頻落在 1～2 px，預覽與輸出的觀感會有差（解析度本身的限制，推論） |
| B. 雙尺度 DoG（guided filter 版） | detail = guided(Y, r1) − guided(Y, r2)，r1 小、r2 中，加回 k 倍 | k = 0.8·t/100 | 兩次 GF：1.5MP 約 1 ms、24MP 約 14 ms（依 §8 的單次 GF 推估） | 邊緣保留較好；頻帶不如金字塔乾淨 |
| C. 小半徑 unsharp／模糊（LumiBase、VibePhoto） | 正值半徑 ~1.2 px 銳化、負值 ~1.5 px 模糊 | — | 極便宜 | 其實是在做 Sharpening（高頻），**跟 Adobe 說的正好相反**（S4），會放大雜訊 |

**推薦：A（金字塔中頻帶＋coring）**，而且跟 Clarity 的 LLF 共用同一個金字塔（推論：LLF 的輸出本來就是一個 Laplacian 金字塔，Texture 只要在重建前對中間幾層再乘增益）。理由：最符合 Adobe 公開的頻帶描述；324 個 preset 用到、數值多半 ±16，風險小。

---

## 6. PV2012 Highlights／Shadows／Whites／Blacks

**已知事實**
- Highlights、Shadows（與 Clarity）是受 LLF 啟發的局部處理（S1）。
- Highlights、Shadows 分別控制「中間調到亮部」「中間調到暗部」，兩者有重疊（S6）；Whites、Blacks 管直方圖最兩端、範圍最窄（S5）。
- **PV2012 的 Tone 控制項是 image adaptive**，連預設值的行為都依照片而定（S6、S7）；Whites／Blacks 設定白／黑裁切點（S7）。
- Adobe 的建議流程：Highlights 救回過曝區、Shadows 顯出暗部細節，一般照片「+Shadows 與 −Highlights 同量」效果就好（S7）。

**候選方法**

| 方法 | 做法 | 對應（推論） | 成本（本機實測） | 差異／風險 |
|---|---|---|---|---|
| A. guided filter 基底層＋分區曲線（tone equalizer／RT shadows-highlights 路線） | log 亮度的平滑基底 B = guided(logY, r≈長邊 2～4%, eps 小)；Highlights／Shadows 是作用在 B 上的分區增益曲線（B 的亮區／暗區、以預覽直方圖百分位定區界，兩區有重疊）；細節 logY−B 原封加回 → 大幅壓亮部時雲層紋理保留。Whites／Blacks 另做（見 C） | Highlights −100 ≈ 亮區基底壓 1～1.5 stop、Shadows +100 ≈ 暗區基底抬 1.5～2 stop（RAWviewer 用 1.55／1.75 stop 當上限，S20）；區界用預覽亮度的百分位（image adaptive） | GF subsample 4：1.5MP **0.5 ms**、24MP **7 ms**；曲線是 LUT，可忽略 | darktable tone equalizer（S12）與 RT shadows/highlights（S15：guided filter 平滑遮罩、tonal width、gamma 曲線混合）都是這條路；風險：單尺度基底在強邊緣（天際線）仍可能光暈，eps 要小（LumiBase 為了去地平線光暈把 eps 壓到 0.08²，S21） |
| B. LLF 重映射同時帶 shadows／highlights／clarity（darktable `locallaplacian.c`） | 重映射曲線 r(c)：\|c\|>2σ 時斜率分別由 shadows、highlights 決定，中間加 clarity 項 `clarity·c·exp(−c²/(2σ²/3))`（S9） | 斜率 = 1 ± k·值/100 | 跟 Clarity 共用一次 LLF：24MP 92 ms | 最接近 Adobe 說的技術來源（S1）；但 darktable 的參數是「相對於局部參考值的偏差」而不是「亮區／暗區」，跟 Adobe 滑桿的語意不同，**數值對應最難校** |
| C. 全域亮度遮罩曲線（ComfyUI-lut、VibePhoto、RAWviewer 的感知路徑） | 以像素自身亮度做遮罩加減 | ComfyUI-lut：Highlights 遮罩 (x−0.5)×2、幅度 0.3；Whites 遮罩 (x−0.7)/0.3、幅度 0.2（S18） | 可忽略 | 沒有空間性：−85 Highlights 會把亮部整片壓平、雲失去層次，**跟 PV2012 差最多**；但**Whites／Blacks 本來就是窄範圍的端點控制**（S5、S7），用全域曲線做是合理的 |

**推薦：Highlights／Shadows 用 A（guided filter 基底＋分區曲線），Whites／Blacks 用 C 型的「影像自適應端點曲線」**：
- Whites／Blacks（推論的具體做法）：在預覽上取亮度 0.5%／99.5% 百分位 p_lo、p_hi；Whites 移動 p_hi 被映射到的位置（+100 推到裁切以上、−100 拉到約 0.8），Blacks 移動 p_lo 的位置（−100 壓到 0 以下裁切、+100 抬到約 0.10～0.15 形成霧面黑）；曲線只影響最兩端（Adobe 文件說 Whites 對應 90～100% 區段——這句只在搜尋摘要看到，未取得原文），用平滑曲線在感知空間做。**811 個正 Blacks 的「抬黑量」是霧面感的關鍵，+100 到底抬多少完全不知道，必須校正。**
- 理由：A 的語意直接對到 Adobe 的「亮區／暗區、可重疊」描述（S6），而且局部性讓大值不會壓平細節；成本極低，拖滑桿時可每格重算。B 留作「A 在天際線出光暈且調不掉」時的升級路線（與 Clarity 共用同一次 LLF，額外成本是零）。

---

## 7. PV2012 Exposure 的高光滾降

**已知事實**
- PV2012 的曝光往亮部與暗部端「滾降較平緩，離開中間調的過渡對比較低」（S5）；Highlight recovery 在 PV2012 自動啟用，預設下比 PV2010 更少高光裁切（S5 搜尋摘要）。
- Adobe 公開的 DNG SDK 參考渲染器（不是 PV2012，但同一家的公開程式）：**負曝光**用 `dng_function_exposure_tone`——最暗 0.25 以下乘 2^EV，最高兩檔用二次式 `a = 16/9·(1−slope)`、`b = slope − a/2`、`c = 1 − a − b`，讓「純白仍對到純白」；**正曝光**則是把白點設在 1/2^EV 的線性斜坡、硬裁切（S17）。

**候選方法**

| 方法 | 做法 | 對應 | 成本 | 差異／風險 |
|---|---|---|---|---|
| A. 線性光增益＋平滑肩部（推論的 PV2012 模仿） | sRGB 解碼成線性 → 乘 2^EV → 對「最大通道或亮度」套 C¹ 連續肩部（膝點約線性 0.6～0.8，之上漸近 1），以比例套回 RGB 保色相；負 EV 用 DNG SDK 的二次式讓白仍是白 | EV 直接用 xmp 的值（不要像 ComfyUI-lut 減半，S18）；膝點與肩部硬度待校 | 逐像素 LUT，可忽略（推論 <1 ms／~5 ms） | 方向與 S5 描述一致；肩部形狀不知道。JPEG 輸入沒有高光餘裕，正 EV 時已裁切的白救不回（推論） |
| B. 純增益＋裁切 | 線性光 ×2^EV 後 clip | — | 可忽略 | 等於 DNG SDK 的正曝光（S17）＝PV2003/2010 行為；PV2012 正是改掉了這點，+1 EV 以上亮部會硬爆 |
| C. 在 sRGB 值上乘（ComfyUI-lut） | `x · 2^(EV/2)` | — | 可忽略 | 在 gamma 空間乘、又減半，亮度量與色彩都不對（S18） |

**推薦：A**。理由：唯一跟「PV2012 有滾降」相符的選項；preset 的曝光平均只有 0.4 EV、最大 2.4 EV，肩部形狀的誤差只在 +1 EV 以上的少數 preset 明顯。負 EV 直接借 Adobe 公開的 DNG SDK 二次式，至少有「Adobe 某一代確實這樣做」的根據（S17）。

---

## 8. GPU 成本（本機實測，2026-10-04）

環境：RTX 4070 Ti SUPER 16GB、torch 2.14.0+cu130（ComfyUI 可攜版內建 Python）、fp32、合成亂數圖、未最佳化的原型（box filter 用 `avg_pool2d`，非積分圖；LLF 未做 fp16 或分塊）。腳本在 scratchpad（`bench.py`，不進 repo）。

| 運算 | 1.5MP（1500×1000） | 24MP（6000×4000） |
|---|---|---|
| guided filter 單通道 r=16、全解析度 | 4.3 ms | 67.4 ms |
| guided filter 單通道 r=64、subsample 4（fast guided filter） | **0.5 ms** | **7.0 ms** |
| 大半徑模糊（5 層高斯金字塔 down/up）＋unsharp | 0.5 ms | 3.6 ms |
| 快速 LLF（Aubry，K=8，單通道亮度） | **10.1 ms** | **92.0 ms** |
| Dehaze：DCP（min-pool 15）＋guided filter（s=4）＋恢復 | 2.1 ms | 25.6 ms |
| 峰值顯存（整批） | 0.44 GiB | **6.98 GiB**（主要是 LLF 的 K 個金字塔累加，fp32） |

對照文獻：Aubry 等人的 GPU 版在 GTX 480 上 1MP 約 49 ms、4MP 約 116 ms（S3）——這台快約 5 倍。

**推論**：這幾項全開在 1.5MP 預覽約 15 ms，拖滑桿即時沒問題；24MP 輸出約 0.15 秒，但 LLF 的 7 GB 峰值要處理（改 fp16、K 降到 6、或逐層累加後釋放），否則跟 ComfyUI 其他模型同時在 VRAM 時會爆。

---

## 9. 建議的處理順序（推論，供 ① 規格參考）

1. sRGB → 線性光；白平衡（公開部分，不在本票）
2. Exposure（§7 A，線性光增益＋肩部）
3. Dehaze（§4 A，線性光；A／t0 用預覽值）
4. 轉 log 亮度 → guided filter 基底：Highlights／Shadows 分區曲線（§6 A）
5. 同一份 log 亮度建 LLF：Clarity（§3 A）＋Texture 中頻帶（§5 A）
6. Whites／Blacks 自適應端點曲線（§6）＋Contrast＋曲線、HSL 等公開部分
7. 亮度比例套回 RGB、轉回 sRGB

順序的依據只有「Dehaze 是物理模型、要在線性光做」（S16 的模型 I = J·t + A(1−t) 是線性光的）與「Whites／Blacks 是端點裁切、應在局部處理之後」兩點；Adobe 實際順序不明。

---

## 10. 最大的不確定點與降低風險的辦法

1. **沒有 Adobe 參考渲染就無法校數值**。所有「−100～+100 → 參數」的對應都是推論初值；特別是 **Blacks 正值抬多少、Highlights −85 壓多少、Whites 的影像自適應範圍**，直接決定霧面感，而這幾項偏偏是用得最多、數值最大的。降低風險：
   - 用 preset 賣家附的前後對比圖做反推（票 05 的議題）。
   - 推論、需使用者決定：若能短期取得 Lightroom／Camera Raw（例如 Adobe 的試用期），一次渲染一組「單一滑桿掃描」的校正集（灰階階梯＋幾張代表照片，每個滑桿 −100/−50/+50/+100），之後就能離線擬合所有曲線；LumiBase 就是這樣用取樣點對 Lightroom 校正的（S21）。
2. **image adaptive 的規則不明**（S6、S7 只說會依照片調整，沒說怎麼調）。用預覽直方圖百分位當錨點是推論的近似。
3. **Dehaze 在沒霧的照片上**（人像 preset 常 +10～+20）DCP 可能估錯；需要保險（§4 C）。
4. **授權**：darktable、RawTherapee 是 GPL，只能參考演算法與參數範圍，不能把程式碼抄進非 GPL 的節點（推論，視 ① 最後的授權決定）；LumiBase 無授權條款，不能抄。
5. **PV2010（ProcessVersion 6.7）的 57 個 preset** 用的是舊滑桿，不在這張票的方法內。
