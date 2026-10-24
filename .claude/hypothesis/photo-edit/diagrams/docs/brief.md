# Brief — darkroom 照片編輯狀態圖（三張）

Form: diagram
Delivery: 多件
Approach: diagram-system
When: cjk-labels, quick
Why: 要一眼看懂一張照片在「編輯／清除／取回上一份」之間的狀態與轉移，以及兩條競態錯誤路徑；這是狀態結構，三張靜態狀態機圖最直接。

## Request
`/baransu:draw --lane diagram --quick --out <this folder>` — 一個 seed 直出，不用細修（由 /hypothesis 呼叫）。

## Fixed facts (labels are exactly these user-facing words)
Subject: darkroom 的一張照片：編輯、清除、取回上一份。

1. `d1-happy.html` 正常流程（≤ 7 states）
   - 沒有編輯 → 有編輯 [存一份編輯]
   - 有編輯 → 沒有編輯，上一份留著 [清除編輯]
   - 沒有編輯，上一份留著 → 有編輯 [取回上一份]
   - 有編輯 → 有編輯 [改成另一份編輯]（self-loop）
2. `d2-two-parties.html` 加一部分「另一方同時操作」：App 和 AI 代理（透過 MCP）可能同時對同一張照片操作。
   - 沒有編輯，上一份留著 → 取回中：已讀到目前沒有編輯 [取回：先讀] → 有編輯 [取回：寫入]
   - 有編輯 → 清除中：已讀到目前的編輯 [清除：先讀] → 沒有編輯，上一份留著 [清除：留上一份、刪檔]
   - Caption: 每個操作都是「先讀、再寫」，中間另一方可以插進來。
3. `d3-paths.html` 兩條編號錯誤路徑，壞掉的狀態用 bad style 並附圖例
   - P1: 沒有編輯，上一份留著 → 取回中：已讀到目前沒有編輯 [取回：先讀] → 取回中，AI 代理剛存了新編輯 [AI 代理存一份新編輯] → P1 新編輯被蓋掉，沒有備份 [取回照樣寫入上一份]
   - P2: 沒有編輯 → 清除中：已讀到沒有編輯 [清除：先讀] → 清除中，AI 代理剛存了編輯 [AI 代理存一份編輯] → P2 編輯被刪掉，也沒留上一份 [清除照樣刪檔]

Real assets: none needed (no logo, no data). Missing: none.

## Decided picture choices
- Type: State Machine (`references/diagram/type-state.md`); one look shared by all three pieces.
- Theme-aware (light/dark via prefers-color-scheme), phone-safe (SVG scales to width, no horizontal scroll), Traditional Chinese labels ≥ 12 px.
- d2 marks the new part (in-between states) with a distinct group/tint; d3 marks broken states with the bad style and a legend.
- Labels are user-facing words only — never variable or function names.
