# Brief — darkroom 照片編輯狀態圖（三張）

Form: diagram
Delivery: 多件
Approach: diagram-system
When: cjk-labels, quick
Why: 要一眼看懂一張照片在「編輯／清除／取回上一份」之間的狀態與轉移，以及兩方同時操作時編輯鎖怎麼擋住競態；這是狀態結構，三張靜態狀態機圖最直接。

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
3. `d3-locked.html` 加一部分「編輯鎖」（第 5 版改畫；第 4 版是兩條錯誤路徑 P1、P2，已修好，現在沒有問題路徑）。兩欄，握著鎖的狀態用 accent tint 並附圖例；AI 代理的操作用虛線。
   - 取回上一份：沒有編輯，上一份留著 → 取回中：已讀到沒有編輯（握著鎖）[取回：拿鎖、先讀] → 有編輯：取回的上一份 [寫入上一份、放鎖] → 有編輯：AI 代理的新編輯 [AI 代理等到鎖才存]
   - 清除編輯：有編輯 → 清除中：已讀到目前的編輯（握著鎖）[清除：拿鎖、先讀] → 沒有編輯，上一份留著 [留上一份、刪檔、放鎖] → 有編輯：AI 代理的編輯 [AI 代理等到鎖才存]
   - 圖例：握著鎖：AI 代理這時要存，只能等；另一方（AI 代理）的操作。
   - 第 5 版的 d3 是沿用 d3-paths 的樣式直接改寫的，沒有重新呼叫 /draw。

Real assets: none needed (no logo, no data). Missing: none.

## Decided picture choices
- Type: State Machine (`references/diagram/type-state.md`); one look shared by all three pieces.
- Theme-aware (light/dark via prefers-color-scheme), phone-safe (SVG scales to width, no horizontal scroll), Traditional Chinese labels ≥ 12 px.
- d2 marks the new part (in-between states) with a distinct group/tint; d3 marks the states that hold the lock with the accent tint and a legend.
- Labels are user-facing words only — never variable or function names.
