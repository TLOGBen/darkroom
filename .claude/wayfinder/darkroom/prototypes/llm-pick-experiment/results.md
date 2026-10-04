# AI 修圖助理選模型實驗：Qwen3.6-35B-A3B vs PE-I2I Heretic

2026-10-04，桌機 RTX 4070 Ti SUPER 16GB，llama.cpp b11223 CUDA（`-c 32768 -np 1 -fa on --jinja -dev CUDA0`）。

- **A**：Qwen3.6-35B-A3B HauhauCS Q4_K_P＋mmproj f16，搭 `projects/qwen3.6-35b-a3b/chat-template.jinja`，預設 `--fit`
- **B**：PE-I2I Heretic Q8_0＋mmproj bf16，用 gguf 內建模板（模板支援 `enable_thinking`，所以 B 也測了開／關思考兩種）
- 取樣（全部一樣）：temperature 0.7、top_p 0.9、top_k 20、min_p 0、seed 42；關思考時 max_tokens 2000，開思考 12000
- 沒用 grammar / `response_format`：JSON 合不合格完全看模型自己照提示詞寫出來的結果

**跑了三輪：B-think-off、B-think-on、A-think-off。35B 思考模式（A-think-on）因為太慢，由使用者決定中止**：第一張照片的描述花了 24.6 秒（1104 tokens），第一次挑 preset 想了 221 秒、用完 12000 token 上限還沒寫出答案（JSON 0/1），整張照片超過 5 分鐘沒做完。原始紀錄在 `run-A-on.log`。

## 已知問題：preset 描述有錯（挑得合不合理要打折扣）

候選 preset 的文字描述來自 `ComfyUI-LightroomXMP/__init__.py` 的 `describe()`。當時它把 **Blacks2012 的方向寫反了**：正值應該是「黑色抬起、變霧面」，卻寫成「deeper blacks」（例如 `blacks +86 (very strongly deeper blacks)`）。很多膠片／復古／霧面風格的 preset 都有大的正 Blacks 值，模型因此可能把「霧面、抬黑」的 preset 當成「加深黑色、加反差」來挑，理由裡常看到「deepens the blacks」就是這個錯造成的。主 session 已經修好 `__init__.py`，**這次沒有重跑**。

影響：每個模型挑得「合不合理」要打折扣；但兩個模型拿到的是同一份（同樣有錯的）描述，**模型之間的相對比較仍然公平**。

## 做法

- 照片 9 張，題材分散（清單和授權見 `photos.json`，`fetch_photos.py` 可重抓）：
  | id | 題材 | 來源 |
  |---|---|---|
  | portrait_studio | 棚拍人像（AI 生成） | repo 裡的 ComfyUI input `portrait_model_denim.png` |
  | landscape_lighthouse | 暴風雨海岸燈塔（AI 生成） | `outputs/comfyui/qw/2026-10-04-lr-latency-busy_00001_.png` |
  | night_street | 夜景街道 | Wikimedia Commons，Petit Champlain at night, Quebec city，CC0，Wilfredor |
  | street_rain | 雨天街景 | Commons，Rainy day at Merchant's Arch, Dublin，CC BY 4.0，David Kernan |
  | food_breakfast | 食物 | Commons，Full English breakfast at the Chalet Cafe，CC BY-SA 4.0，Acabashi |
  | interior_cafe | 室內（咖啡館拱頂） | Commons，Vault Café Central Vienna，CC0，Jebulon |
  | sunset_kite | 夕陽逆光 | Commons，Kitesurfer at sunset, Workum，CC BY-SA 4.0，Villy Fink Isaksen |
  | portrait_balaclava | 戶外真人人像 | Commons，Portrait of a young woman wearing a gray balaclava，CC BY-SA 4.0，Basile Morin |
  | food_bluecast_dark | **人工製造問題**：偏藍＋曝光不足＋反差低 | 從 Commons「Breakfast in Île d'Orléans 072」（CC0，Wilfredor）用 PIL 壓暗、加藍 |
- 候選：每張 18 個 preset（`build_candidates.py` → `candidates.json`）：2 個「對題」群組各 2 個（P01–P04，例如食物照給「物件 - 食物」）＋12 個大類各 1 個＋2 個隨機。兩個模型拿到完全一樣的候選。
- 給模型的格式：每個候選是「Candidate N:」加 `describe(path, 100)` 的整段英文描述。**描述第一行本來就含 preset 名稱和群組**（例如 `"美食專家8" (category: 物件 - 食物 - 美食專家)`），所以模型看得到名稱，可能會看名字挑。
- 每張照片問 3 次：① 結構化描述 ② 挑前 3 名＋強度 0–150＋理由（原順序）③ 同樣的問題但候選順序打亂、重新編號。②③ 的前 3 名重疊數＝一致性。
- 提示詞與 JSON schema 在 `run_experiment.py`（`DESCRIBE_PROMPT`、`PICK_PROMPT`）。

## 數字

| | A 35B 關思考 | B PE-I2I 關思考 | B PE-I2I 開思考 |
|---|---|---|---|
| 載入到 /health ok（秒，檔案已在快取） | 16.7 | 8.7 | 4.6 |
| VRAM（nvidia-smi，扣掉桌面約 1.9GB） | 約 13.9GB（`--fit`，32K ctx） | 沒量（Q8 9.5GB＋mmproj 0.9GB＋KV，推估 11–12GB） | 同左 |
| 描述一張照片（秒，平均） | 6.4 | 4.4 | 28.5 |
| 挑 preset 一次（秒，平均；提示詞約 7.7K–10.5K tokens） | 17.5 | 5.1 | 88.6 |
| 生成速度 tok/s | 59.8 | 61.7 | 61.6 |
| 提示詞處理 tok/s | 651 | 4959 | 4941 |
| 描述的生成 tokens（平均） | 230 | 245 | 1769（多半是思考） |
| 挑選的生成 tokens（平均） | 205 | 197 | 5269（多半是思考） |
| JSON 直接 `json.loads` 成功 | 27/27（100%） | 27/27（100%） | 25/27（93%） |
| 欄位齊全且合法（schema OK） | 27/27（100%） | 25/27（93%） | 26/27（96%） |
| 兩次前 3 名重疊（平均 /3） | 1.3 | 1.3 | 1.4 |
| 兩次第 1 名相同 | 2/9（22%） | 5/9（56%） | 1/9（11%） |
| 挑中「對題」preset 的比例（隨機約 22%） | 48% | 48% | 65% |
| 強度用到的範圍（平均） | 60–130（96） | 65–120（98） | 70–140（100） |

Schema 失敗的實際內容：
- B 關思考：棚拍人像第 3 名漏了 `strength`；雨天街景把 `"strength"` 寫成 `"street cinematic": 100`。
- B 開思考：燈塔第二次多了一個 `}`，整段 JSON 解不開（思考過程最後還說「Check… Good.」）。
- A 關思考：沒有失敗。

跨模型：A 和 B（都關思考）第一次挑的前 3 名平均只重疊 0.9/3。

細節數字與每張照片的完整挑選見 `results-data.md`（由 `analyze.py` 產生），原始回應在 `raw/<設定>/<照片>.json`（含 content、reasoning、timings、解析結果、候選順序）。

## 每張照片的挑選並排

`*`＝對題群組的 preset；`@`＝強度 %。理由是第一次（原順序）的。

### portrait_studio（棚拍，墨綠上衣、灰藍背景）
- **A**：① Cinematic Light 03 @100（電影） ② 90's Vibes 01 @85（復古） ③ **02 Fitness 02 @110（人物 - 運動者）**；打亂後：質感棚拍 1* @130、Cinematic Light 03、**food 03（食物）@100**
  - 「Fitness preset brightens the exposure and lifts the blacks… high-end commercial look」
- **B**：① Cinematic Light 03 @90 ② 人像聚焦 9* @70 ③ Kodak Portra 9；打亂後：Kodak Portra 9 @120、Cinematic Light 03、質感棚拍 1*
- 代理意見：兩者都選了 Cinematic Light；A 兩次都塞了明顯離題的（運動、食物），B 的三個都說得通（電影光、人像、Portra 膠片）。

### landscape_lighthouse（暴風雨海岸）
- **A**：海洋魄力 4* @100、Dramatic - Tone 5* @100、滄桑歲月2 @120；打亂後：海洋魄力 3*、海洋魄力 4* @120、簡約琢白 4 @60
- **B**：海洋魄力 4* @120、海洋魄力 3* @90、Analog 05 @110；打亂後：海洋魄力 4*、海洋魄力 3*、09 Fitness 09 @90
- 代理意見：兩者第 1 名都是海洋魄力，合理。A 第一次挑 Dramatic（戲劇性）比較貼這張；B 打亂後也混進一個 Fitness。

### night_street（魁北克夜景街道）
- **A**：NEON 05* @85、NEON 11* @85、摩登霓虹3 @75；打亂後完全同一組（3/3）
  - 理由寫得很具體：「recovers the highlights on the illuminated castle… cyan split-toning complements the warm street lamps」
- **B**：摩登霓虹3 @120、N 04*（黑夜）@110、Analog 05 @90；打亂後 NEON 05*、N 06*、N 04*
- 代理意見：都挑夜景／霓虹類，A 這張最穩。

### street_rain（都柏林雨天巷子，白天陰天）
- **A**：12 Cinematic Street 12* @110、NEON Light 14 @80、滄桑歲月7 @90
- **B**：NEON Light 14 @100、Light 02（光明白日）@100、Cinestill 04 @70
- 兩者描述：A 說「cool, desaturated, slightly greenish-blue」；B 說成 **「night street… dim overcast evening light」**，然後用「neon-lit night alley」當理由選霓虹。
- 代理意見：照片是白天陰雨；B 把它看成夜景。A 的 Cinematic Street 比較對。

### food_breakfast（英式早餐）
- **A**：美食專家8* @100、Brunch 05* @100、03 Autumn 03 @85；打亂後 Brunch 03*、Minimal Blogger 02、美食專家13*（重疊 0/3，但兩次都是食物類為主）
- **B**：Brunch 03* @90、**11 Metro 11（地鐵）@70**、Product 04 @65；打亂後 Brunch 03* @120、美食專家8*、Retro Film 08
- 代理意見：A 比較貼題；B 選「地鐵」給早餐有點怪，但理由（加反差、質感）說得通。

### interior_cafe（維也納咖啡館拱頂）
- **A**：Dark Academia 05* @100、Dark Academia 03* @110、Light 04 @80；打亂後 Dark Academia 03*、Dark Academia 05*、復古膠卷3
- **B**：Dark Academia 05* @120、復古膠卷3 @100、City 03 @90；打亂後完全同一組（3/3）
- 代理意見：兩者都抓到「歐式建築棕」，差不多。

### sunset_kite（夕陽風箏衝浪）
- **A**：黃金日落 2* @100、Cinematic Light 05 @75、Explore 07 @80；打亂後 黃金日落 2*、橙霞遠征 6、Cinematic Light 05
- **B**：S12*（海島）@100、Cinematic Light 05 @90、LS 04 @100；打亂後 黃金日落 2*、黃金日落 4*、橙霞遠征 6（重疊 0/3）
- B 兩種思考模式都說照片有 **「black letterbox bars at the top and bottom」**——實際照片沒有黑邊（幻覺）。
- 代理意見：A 兩次都穩定選黃金日落；B 不穩，而且描述有幻覺。

### portrait_balaclava（戶外女性人像，格紋頭套）
- **A**：N03*（皮膚強調）@100、N01* @100、Moody Tones 09 @100
- **B**：日系清新5 @100、Beauty 05*（人物 - 女人）@100、N03* @100
- A 說是「beekeeping suit（養蜂衣）」；B 說「eyes slightly reddened and watery」。
- 代理意見：兩者都合理；B 比較會挑人像／美顏類。

### food_bluecast_dark（人工偏藍＋曝光不足）
- 問題偵測：A 抓到「strong cool color cast (blue/cyan)、underexposed、low contrast、muted」，**4 項全中**；B 關思考抓到「underexposure、cool blue cast、flat」；B 開思考把偏藍說成「slight cool blue cast across the window view」（低估了）。
- **A**：Dark Food Tone 4* @100、Black Paris 15 @85、Cinematic Light 05 @75；打亂後 food 03* @130、Light 02、Dark Food Tone 1*（0/3）
- **B**：food 05* @120、經典款 1 @100、Cinematic Light 05 @90
- 代理意見：照片的問題是「太暗＋偏藍」，最該選的是會提亮、加暖的。B 的第 1 名 food 05（「warm white balance and dehazing, brightens」）對症；A 第 1 名選 Dark Food（讓暗調更暗的風格），理由還說「enhances the moody atmosphere」，跟它自己描述的問題矛盾。兩者都會在第 3 名選 Cinematic Light 05（冷色陰影），對偏藍照片是反效果。

## 觀察（代理意見）

1. **速度：B 快很多。** 生成速度兩者差不多（約 60 tok/s；A 在 32K ctx 下比 NOTES.md 的 42–50 快），差在**提示詞處理**：B 約 4950 tok/s，A 約 650 tok/s（MoE 專家層有一部分在 CPU）。挑 preset 的提示詞有 8–10K tokens，所以 A 每次約 17.5 秒、B 約 5 秒。候選越多差越大。
2. **JSON：A 最乾淨（27/27），B 偶爾漏欄位或打錯鍵名（25/27）。** 實際接進 workflow 時，兩者都該用 llama-server 的 `json_schema`／grammar 強制格式，或加一層補救解析和重試；這樣格式問題基本上就不是選擇因素。
3. **一致性兩者都偏低**：打亂順序後前 3 名平均只留 1.3 個，第 1 名常常換人。18 個候選裡有很多差不多的（同群組兩個），這也是原因之一。實際產品可以考慮：跑 2–3 次取票數，或先讓模型選「方向／群組」再在群組內挑。
4. **看圖：A 比較少幻覺**（B 把雨天白天看成夜晚、看到不存在的黑邊），對人工偏藍照片 A 的問題清單也最完整；但 A 從問題推到挑選時不一定對得上（偏藍暗照第 1 名選了暗調食物）。
5. **強度幾乎不會用**：三輪的強度都集中在 80–120，低於 70 的只有 3/159。想要「弱／中／強」有意義，提示詞要明講什麼情況用低強度，或改讓模型選三段。
6. **思考模式不划算**：B 開思考每次挑選要 89 秒（約 17 倍），對題率從 48% 升到 65%，但一致性沒變好（第 1 名相同從 56% 掉到 11%），JSON 還多一次壞掉。A 開思考第一次挑選就想到 12000 tokens 還沒答。互動式修圖助理應該關思考。
7. **名稱的影響**：描述裡含 preset 名稱與群組，「對題率」有一部分可能是看名字（例如食物照挑「美食專家」）而不是看參數。

## 建議

- **預設用 B（PE-I2I Heretic，關思考）**：快 3 倍以上、VRAM 少，而且它本來就是 7 萬事通裡的 PE，同一個模型可以「挑 preset＋寫修圖提示詞」一起做，不用換模型。挑選品質跟 A 差不多（兩者各有離譜的選項）。
- 搭配：用 `json_schema` 強制輸出格式；在提示詞裡把描述階段找到的問題（偏色、曝光）明確當成挑選條件；把強度規則寫清楚。
- 如果之後更看重「看得準」（偏色、曝光判斷），A 關思考值得留作備選，代價是每次多 10 秒以上。

## 最大的不確定點

1. **preset 描述的 Blacks 方向錯誤**（見上面）：所有「合不合理」的判斷都建立在有錯的描述上；修正後重跑，挑選結果可能明顯不同。
2. **樣本小、沒有標準答案**：9 張照片、每個設定只跑一個 seed；「合不合理」是代理的主觀判斷，沒有人工標註的正確 preset，也沒有實際套用 preset 後看效果。
3. 一致性指標混合了「順序效應」和「取樣隨機性」（打亂順序和 temperature 0.7 同時在變），分不開。

## 檔案

- `fetch_photos.py`：抓照片、做人工偏藍照、寫 `photos.json`
- `build_candidates.py`：產生 `candidates.json`（每張 18 個候選＋描述）
- `run_experiment.py`：自己開／關 llama-server，跑一個設定，例如 `python run_experiment.py --model B --think off`
- `analyze.py`：彙整 `raw/` → `results-data.md`
- `raw/<設定>/`：每張照片的原始回應 JSON、`summary.json`、`llama-server.log`；`run-*.log`：執行過程
