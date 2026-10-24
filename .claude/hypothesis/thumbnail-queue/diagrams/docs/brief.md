# Brief — darkroom 縮圖佇列狀態圖（三張）

Form: diagram
Delivery: 多件
Approach: diagram-system
When: cjk-labels, quick
Why: 要一眼看懂縮圖格的背景縮圖怎麼排隊、重新列資料夾為什麼會把做好的縮圖再做一次；狀態結構，三張靜態狀態機圖最直接。

## Request
由 /hypothesis 產生（HUNT-2026-001）。這一組沒有呼叫 /draw：沿用假說 photo-edit 圖組（/draw 產出的 d3 樣式）的同一套 CSS 與 SVG 版面，以腳本生成三張。重畫時可以把下面的事實交給 `/baransu:draw --lane diagram --quick`。

## Fixed facts (labels are exactly these user-facing words)
1. `d1-happy.html` 正常流程（≤ 7 states）
   - 一張照片：沒有縮圖 → 排隊中 [列資料夾：查不到，排進佇列] → 正在做縮圖 [工作執行緒取出來] → 有縮圖 [做完、記進索引]
   - 再列一次資料夾：有縮圖 → 查得到：直接用快取 [重新列資料夾] → 不排隊 [不用再做]
2. `d2-two-steps.html` 加一部分「重新列資料夾分兩段」
   - 主執行緒：一張一張查有沒有縮圖 → 記下沒有縮圖的照片 [查完整個資料夾] → 世代號加一 [準備排入] → 一張一張排進佇列 [只看處理中，不再查縮圖]
   - 同時工作執行緒：正在做縮圖 → 記進索引 [做完] → 離開處理中 [交出結果] → 取下一件 [佇列還有工作]
3. `d3-paths.html` 兩條編號路徑，壞掉的狀態用 bad style 並附圖例
   - P1：查到第 1～3 張沒有縮圖 → 它們陸續做完、離開處理中 [背景工作照常進行] → 排進去：都不在處理中 [主執行緒查完，開始排] → P1 重做 3 張，超過 2 個執行緒 [各建立一個新工作]
   - P2：查到這張沒有縮圖 → 它剛好做完、離開處理中 [背景工作剛好做完它] → 排進去：不在處理中 [請求排進佇列] → P2 同一張又做一次 [建立一個新工作]

## Decided picture choices
- Type: State Machine; one look shared by all three pieces (same as hypothesis photo-edit).
- Theme-aware, phone-safe, Traditional Chinese labels ≥ 12 px; labels are user-facing words only.
