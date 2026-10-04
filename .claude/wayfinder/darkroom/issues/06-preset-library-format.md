# ① preset 庫的資料格式？

Type: grilling
Status: resolved

## Question

已定：資料夾樹、搜尋、改名、搬資料夾、建資料夾、最愛、匯入；不改原檔，改動記在索引。要定：索引檔放哪（跟 preset 一起放在 artifact/11_preset，還是 ComfyUI 的 user 資料夾）、格式、匯入時名稱或檔案重複怎麼處理、匯出成 xmp 的時機與內容、使用者自己存的 preset 放哪。

## Answer

**使用者決定（2026-10-04）：索引檔跟 preset 放一起**——`artifact/11_preset/library.json`；使用者自己存的 preset 放 `artifact/11_preset/user/`（選項 A；另一個選項是放 ComfyUI 的 user 資料夾，換版要搬）。原本的 xmp 不改，改名、搬資料夾、最愛只記在索引。匯入時名稱或檔案重複怎麼處理、匯出 xmp 的細節屬實作細節，由實作者照「不改原檔、可重建」原則決定（已在「還看不清楚」的匯出項）。

