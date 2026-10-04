# ② 35B vs PE-I2I：誰適合當修圖助理？（實驗）

Type: task
Status: resolved

## Question

使用者要先實驗再決定「② AI 修圖助理用哪個 LLM」。同一批照片（6～10 張，人像、風景、夜景、食物、街景各有），讓 Qwen3.6-35B（`models/qwen3.6-35b-a3b`，mmproj）與 PE-I2I Heretic（`models/qwen-image-2.1/text-encoders/pe-i2i-heretic`）都用 llama-server 跑三件事：(1) 看照片寫結構化描述（題材、光線、色調、問題點）；(2) 給照片＋一組候選 preset 的文字描述（用 `ComfyUI-LightroomXMP` 的 `describe()` 產生，每次 15～20 個、跨不同群組），挑前 3＋強度＋理由，打亂順序再問一次看一致性；(3) 照指定 JSON 格式輸出（欄位用 xmp 鍵名）的遵守率。量速度、JSON 合格率、兩次挑選的一致性，並把挑選結果與理由列表給使用者判斷合不合理。產出放 `prototypes/llm-pick-experiment/`。

## Answer

（2026-10-04，執行子代理；詳見 [prototypes/llm-pick-experiment/results.md](../prototypes/llm-pick-experiment/results.md)。主 session 驗收：results.md 存在、llama-server 已全部關閉；主 session 另以自己的腳本重算前三輪數字一致。35B 思考模式（第一張 5 分鐘以上未完成）由使用者決定中止。）

| | 35B 不思考 | PE-I2I 不思考 | PE-I2I 思考 |
|---|---|---|---|
| 載入 | 16.7 秒 | 8.7 秒 | 4.6 秒 |
| 描述一張 | 6.4 秒 | 4.4 秒 | 28.5 秒 |
| 挑一次 preset（提示 8～10K tokens） | 17.5 秒 | 5.1 秒 | 88.6 秒 |
| 提示詞處理 | 651 tok/s | 4959 tok/s | 4941 tok/s |
| JSON 直接 parse／欄位齊全 | 27／27 | 27／25 | 25／26（各 27） |
| 打亂順序前 3 名重疊 | 1.3／3 | 1.3／3 | 1.4／3 |
| 兩次第 1 名相同 | 2／9 | 5／9 | 1／9 |
| 挑中對題 preset（隨機約 22%） | 48% | 48% | 65% |

- **看圖準確度：35B 明顯較好。** PE-I2I 會幻覺——夕陽照兩種模式都說有上下黑邊（實際沒有），白天雨巷說成夜景並以「霓虹夜巷」為理由挑霓虹 preset；35B 沒有這類錯誤，對人工「偏藍＋太暗」的照片四個問題全抓到（但挑的 preset 跟自己的診斷對不上）。
- **挑選都不穩、強度不分高低**（強度 159 次中只有 3 次低於 70）；兩模型彼此前 3 名平均只重疊 0.9。
- **已知限制**：候選描述有「黑色方向寫反」的錯（主 session 已修，未重跑）；9 張、單一 seed、無標準答案；描述含 preset 名稱，對題率可能部分來自看名字。
- **對決策的影響**：使用者據此把「AI 自動挑 preset」移出範圍（見「② preset 效果概念地圖怎麼建、AI 怎麼挑？」）。② 改為「LLM 給滑桿數值」後，**看圖準不準比挑選更關鍵**——這點 35B 佔優、PE-I2I 速度佔優；交給「② AI 修圖助理用哪個 LLM 看圖、輸出什麼格式？」。

