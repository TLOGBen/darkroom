# ① 跟萬事通的關係？

Type: grilling
Blocked by: 02
Status: resolved

## Question

獨立一份 workflow（例如「9 相片編輯」）、放進 7 萬事通當一個區塊、還是單一節點可以接在任何 workflow 後面（萬事通出圖後接、或單獨修照片）。影響輸出接法與 SeedVR2、存檔怎麼串。

## Answer

**使用者決定（2026-10-04）：做成單一節點，可接在任何 workflow 後面；另附一份現成的「9 相片編輯」workflow 當入口；7 萬事通不改**（選項 A；另兩個是放進萬事通當一個區塊、只做節點不附 workflow）。「9 相片編輯」的骨架：讀圖 → 相片編輯節點（B 版小節點）→ SeedVR2 放大（選用、預設關，接法照萬事通的開關）→ 存檔（前綴照使用者慣例 `<資料夾>/%date:yyyy-MM-dd%-<名稱>`）。萬事通出圖後要調色時，把節點接在萬事通的輸出後面即可；節點的 `params` 輸入／輸出可把參數帶到下一張。workflow 照慣例由 `projects/comfyui/tools/` 的產生器產出。


## Comments

（2026-10-04）這個答案假設載體是 ComfyUI；使用者質疑後開了「① 載體：放在 ComfyUI，還是做成獨立的本機修圖 App？」，那張的答案可能推翻本票。

（2026-10-04 更新）**本票答案已被「① 載體：放在 ComfyUI，還是做成獨立的本機修圖 App？」取代**：不再做「單一節點＋9 相片編輯 workflow」，改為獨立 App；萬事通不改的部分仍成立；App 出圖後要接萬事通或 SeedVR2 時透過 ComfyUI API。
