# CONTRACT — darkroom S3「裁切、拉直、旋轉、鏡像」（幾何存進編輯、渲染前決定畫面範圍、裁切模式、三入口與縮圖／匯出）
> STATUS: sealed（2026-10-10）— 決定由主 session 裁決（2026-10-10）；C1～C29 符合（D1 依 M1 定案為 (A)、D12 依 M2 維持雙三次）；2 次派遣：第 1 次 F1 退化遮罩配幾何崩潰（已修並釘死）、F2 C22 條文太鬆（條文補丁）、F3 未釘表面（已補釘），另依主 session 裁決新增 C29 讀不到已存編輯時不自動存檔（已修並以真 app.js 行為測試釘死）；複驗探針 3/3 仍攔、修正回合新判官 11 支出生證明全紅，全部逐位元組還原；常數零漂移；複驗新發現 N-1 只記錄
<!-- 基準數字（main b2fc4d3）：facade 操作 33、MCP 工具 33、HTTP 路由 35、G10 白名單 5、核心公開名稱 7；本合約一律寫成實數 -->

## 目標
使用者只專注修圖：按「裁切」（或 R）進裁切模式，拖框、挑比例（原始、1:1、4:5、5:7、2:3、3:4、16:9、自由，直式／橫式一鍵換）、拉直滑桿轉正（邊緣空白自動裁掉），也能向左／向右轉 90°、水平／垂直鏡像；Enter 完成、Esc 取消，完成後 Ctrl+Z 一步拿回。幾何存在這張照片的編輯裡，重開、縮圖、匯出、三個入口都看到同一個畫面範圍。暈影套在裁切後的畫面上，漸層遮罩跟著畫面內容一起轉、一起鏡像。貼上編輯預設只貼顏色、不帶裁切（勾選才帶）。照片與買來的 preset 照舊一個位元組都不動；沒有幾何的照片，所有輸出與今天逐位元組相同。

## 前提（Premises）
- G1 已驗（`darkroom/_render.py:308-372`）：漸層遮罩在 `_shape_mask` 以「目前這張影像」的 0～1 相對座標算（`_pixel_grid(H, W)`）；`_vignette`（:535）也以目前影像的中心與長寬算。所以「先把影像換成裁切後的畫面再渲染」暈影自然變成 post-crop，但遮罩會跟著畫面跑掉——遮罩必須改成以來源座標評估。
- G2 已驗（`_render.py:207-230`、`:285-296`）：Dehaze 的大氣光 A 取整張畫面暗通道前 0.1% 的平均，Texture 的雜訊門檻取整個頻帶的 `|d|` 平均——兩者都是**整張畫面的統計**，畫面範圍一變就變。使用者庫 1466 個 preset 中 `Dehaze` 不為 0 的有 673 個、`Texture` 不為 0 的 324 個（2026-10-10 grep）。這是 D1 的根據。
- G3 已驗（`E:/llm/artifact/11_preset/xmp`，2026-10-10 grep）：1466 個 preset 沒有任何一個帶 `crs:HasCrop`、`CropTop`、`CropLeft`、`CropBottom`、`CropRight`、`CropAngle`、`CropConstrainAspectRatio`、`CropWidth`、`CropHeight`、`Orientation`；434 個帶 `crs:CropConstrainToWarp="0"`；`Perspective*`、`LensManualDistortionAmount` 全為 0；`PostCropVignetteAmount` 不為 0 的 350 個；含 `Mask/Gradient`／`Mask/CircularGradient` 的 27 個。`_xmp.py:21` 把 `CropConstrainToWarp` 列在 `KNOWN_NUMERIC`。
- G4 已驗（`darkroom_app/engine.py:68-85`）：`Engine.open` 只留 ≤ `PREVIEW_MAX_PIXELS`（1500000）的預覽底圖在 GPU，全解析度讀完就丟。直接從這張底圖切，裁掉一半長邊時預覽只剩約 375k 像素（D6）。
- G5 已驗（`services/photo_library.py:44`、`:96-103`、`:735-764`）：`EDIT_KEYS` 恰 5 個、`edit_problem` 要求鍵集合完全相同、`schema` 不是 `darkroom-edit/1` → conflict（PL9）；`paste_edit` 把 target 整份換成來源的 preset／strength／overrides。
- G6 已驗（`static/logic.js:420-427`、`app.js:876`）：S1 的自動存檔在「記得快照」時走 `POST /api/edit/paste {targets:[path], edit}`（S2）——所以「貼上預設不帶裁切」若不加相容補丁，自動存檔會把使用者剛裁好的框丟掉（C14 的 S2b）。
- G7 已驗（`app.js:206-216`）：A/B 與按住 `\` 的原圖來自 `POST /api/preview {preset_id:null, strength:100, overrides:{}}`，快取鍵只有 `image_id`（`st.originalFor`）。
- G8 已驗（`darkroom/__init__.py`）：核心公開名稱恰 7 個（A2）；`darkroom_app` 不准 import `darkroom._*`（B1／L13）；`thumbnail` 可載入 cv2、不得載入 torch（PLP8 L9 擴充）。
- G9 不入條文為事實（未驗）：Lightroom 自己的漸層遮罩座標是相對「未裁切、已轉正」的畫面還是感光元件原始方向；Lightroom 的 Dehaze 是否隨裁切變；`CropTop/Left/Bottom/Right` 在有 `CropAngle` 時的確切定義。使用者已退訂，無法實機比對（D5 建議不讀 preset 的裁切，所以本片不依賴後兩項）。

## 可斷言條文

### 一、幾何的定義（一份規則，Python 與前端共用案例表）
- [ ] C1（幾何物件）：幾何＝`null` 或恰為常數「幾何 schema」的 5 個鍵 `rotate`、`flip`、`angle`、`aspect`、`crop`；`rotate` ∈ {0, 90, 180, 270}（順時針，int）；`flip` 布林（水平鏡像，套在 rotate 之後）；`angle` 有限數 −45～45（度，正值＝畫面內容順時針轉）；`aspect` ＝ `"original"`、`"free"` 或 `"{w}:{h}"`（兩個 1～65535 的十進位整數，存成約分後的值）；`crop` ＝ `null`（自動：見 C3）或恰 4 鍵 `left`、`top`、`right`、`bottom`（有限數，0 ≤ left < right ≤ 1、0 ≤ top < bottom ≤ 1）。驗證唯一一份：核心 `Geometry.from_dict`（D2(A)），`darkroom_app/preview.py` 的 `validate_geometry` 只把 `ValueError` 轉成 invalid、不另寫規則；`bool` 不算數字（同 XP17）；錯誤句見常數。正規化：`rotate 0、flip false、angle 0、crop null` ＝恆等 → 一律存成／回傳 `null`（不論 aspect）。釘死：`test_geometry_validate_and_canonical`（常數表每一句一案例、恆等 → null、`"8:10"` 存成 `"4:5"`）。
- [ ] C2（座標與順序）：來源＝`read_image` 轉正後的影像 W×H（K1／K2：JPEG／TIFF 已依 EXIF、HEIC 依 libheif）。順序固定：rotate（順時針）→ flip（水平）→ angle（繞畫面中心轉，畫布大小不變，＝框 W′×H′；rotate 90／270 時 W′＝H、H′＝W）→ crop。輸出第 (i, j) 個像素中心的取樣點依常數「反向對應」算到來源座標。`angle == 0` 時只做整數像素的 rot90／flip／切片（不重取樣），輸出與 `np.rot90`／`np.fliplr`／陣列切片**逐位元組相同**；`angle != 0` 時以常數「重取樣」取樣（D12）。釘死：`test_geometry_rotate_flip_exact`（4 種 rotate × flip，對 `np.rot90(..., k=-r/90)`／`np.fliplr` 逐位元組）、`test_geometry_crop_exact_slice`、`test_geometry_inverse_map_cases`（案例表的取樣點）。
- [ ] C3（裁切框解析，唯一一份，`Geometry.resolve(W, H)`）：依常數「解析步驟」：(1) `crop` 為 null → 以畫面中心、比例 ρ（`original`／`free` ＝ W′:H′；`"w:h"` ＝ w/h）在有效區內最大的框；(2) 有 `crop`、aspect 不是 `free`、而且框的像素比例與 ρ 相差 > 0.1% → 以框中心與面積重設成比例 ρ；(3) 框中心不在有效區內 → 中心移到畫面中心；(4) 依常數「最大縮放」以框中心等比縮小到完全落在畫布與有效區內（已在內就不動，**永不放大**）；(5) 四邊以 `floor(x + 0.5)` 取整成像素，寬高至少 1。有效區＝轉正前的 W′×H′ 矩形繞中心轉 angle 之後與畫布的交集（angle 0 時就是整個畫布，所以 angle 0 的手動框只做 clamp、不改）。結果 `{left, top, right, bottom}`（像素，int）與輸出寬高。Python 與前端用同一份案例表 `tests/cases/s3_geometry_cases.json`（同 S2 E8 做法：`test_geometry_shared_cases` 與 `tests/js/test_logic.cjs` 的 `L.fitCrop`），至少涵蓋：四種 rotate、flip、angle ±0.1／±12.5／±45、crop null＋原始／4:5／16:9／自由、手動框超出有效區、框中心在空白角、比例不符要重設、1 像素邊、方形照片、直拍（方向 6）；數值容差 1e-9（正規化座標）、像素結果逐值相同。
- [ ] C4（使用者操作的正規化）：前端的「向右轉」「向左轉」「水平鏡像」「垂直鏡像」「直式／橫式」只改幾何物件、依常數「操作表」換算（框跟著畫面內容走、`"w:h"` 隨 90° 轉換成 `"h:w"`、鏡像使 angle 變號）；純函式 `L.geometryAction(g, action)`，同一份案例表 `tests/cases/s3_geometry_actions.json`。Python 端不重寫這張表，改以像素驗它：`test_geometry_actions_match_pixels` 對表中每一筆 `angle == 0` 的案例斷言 `render(src, after)` ＝ 對 `render(src, before)` 做同一個 rot90／flip（逐位元組），`angle != 0` 的案例斷言平均絕對差 ≤ 1/255。
- [ ] C5（輸出尺寸）：一張照片的「輸出尺寸」＝ C3 解析後的寬高（沒有幾何＝轉正後原圖寬高，與今天相同）；預覽、縮圖、匯出、`used.width／height`、EXIF `PixelXDimension／PixelYDimension` 都以它為準（C17～C19）。

### 二、渲染（核心）
- [ ] C6（核心 API，D2(A)）：`darkroom/__init__.py` `__all__` 由 7 個變 8 個，加 `Geometry`（常數「核心公開名稱」）；`render(image, params, strength=1.0, device=None, *, geometry=None)`，`geometry` 是 `Geometry` 或 None；None → 與今天逐位元組相同（A8、A17、A19、K4 不變）。`Geometry` 公開：`from_dict(obj)`、`to_dict()`（恆等回 None）、`resolve(width, height)`、`output_size(width, height)`、`apply(array)`（CPU：numpy＋cv2、不 import torch，給縮圖用）。幾何程式在新私有模組 `darkroom/_geometry.py`（只 import numpy、math；cv2 延遲 import；torch 只在 `_render.py`）。釘死：`test_public_api_eight_names`（取代 A2 的 7 個）、`test_render_without_geometry_unchanged`（同輸入不給與給 None 逐位元組相同）、`test_geometry_module_torch_free`（`sys.modules`）。
- [ ] C7（先決定畫面範圍再渲染，D1）：`render` 先把來源依 C2／C3 取樣成輸出畫面，再對輸出畫面跑整條管線（`_pipeline` 順序不變）；因此暈影的中心、長寬、圓度都是裁切後的畫面（Lightroom 的 post-crop vignette），Grain／Sharpen／Texture 的 K4 長邊 L＝輸出長邊。D1 選 (B) 時另加：Dehaze 的大氣光 A 與 Texture 雜訊門檻取自常數「統計來源」（轉正後、未裁切的整張來源縮到 ≤ 1500000 像素），所以裁切不改變保留區的顏色（暈影、顆粒圖樣除外）。釘死：`test_vignette_is_post_crop`（只開暈影：`render(src, g)` ＝ `render(src 的切片, 同參數)` 差 ≤ 1e-5；與「整張渲染再切」不同）、D1(B) 時 `test_crop_keeps_colors`（只開 Dehaze 40／Texture 40：保留區與整張渲染再切的平均絕對差 ≤ 常數「保留區容差」）。
- [ ] C8（遮罩跟著內容走）：線性與放射漸層的座標照舊是 preset 的 0～1 值，但改以**來源座標**評估：每個輸出像素用 C2 反向對應到的來源點算遮罩值（不是輸出畫面的座標）。所以 rotate／flip／angle／crop 之後，遮罩蓋住的還是同一塊畫面內容。暈影、顆粒用輸出座標。釘死：`test_masks_follow_content`（合成 preset：上方 0～0.3 的線性漸層＋左下放射漸層、只有遮罩內曝光 +1：rotate 90 → 等於整張渲染後 rot90（逐位元組，angle 0）；flip → 等於 fliplr；crop 下半部 → 等於整張渲染後切下半部（差 ≤ 1e-5）；angle 10 → 與「整張渲染後同一重取樣」平均差 ≤ 1/255）。
- [ ] C9（重取樣與空白）：GPU 用 `torch.nn.functional.grid_sample`（常數「重取樣」：模式、`align_corners=False`、`padding_mode="border"`，結果 clamp 0～1）；一般模式下取樣點落在來源外時取邊緣像素（框已在有效區內，只有取整那半個像素會碰到）。`frame` 模式（C17，裁切模式用）忽略 crop、輸出整個框 W′×H′，來源外的像素＝常數「空白填色」。CPU `Geometry.apply` 用 `cv2.warpAffine`（同一個 2×3 矩陣、常數對應的插值與 `BORDER_REPLICATE`）；兩者對同一張 8-bit 圖平均絕對差 ≤ 1/255、最大差 ≤ 常數（M2 實測後寫入）。釘死：`test_geometry_cpu_matches_gpu`、`test_frame_mode_fill`。
- [ ] C10（preset 帶的裁切欄位，D5(A)）：`load_preset` 永遠不把 xmp 的 `HasCrop`、`CropTop`、`CropLeft`、`CropBottom`、`CropRight`、`CropAngle`、`CropConstrainToWarp`、`CropConstrainAspectRatio`、`CropWidth`、`CropHeight`、`CropUnit` 轉成幾何；`HasCrop="True"`，或 `CropAngle` ≠ 0，或四邊不等於 (0, 0, 1, 1) → `skipped` 加一項常數「preset 裁切略過項」（`skips.level`＝minor，不進觀感級提示列）；其他情況（含 434 個 `CropConstrainToWarp="0"`）不列。釘死：`test_preset_crop_never_applied`（合成 xmp：HasCrop True＋CropAngle 5 → 渲染與去掉這些屬性的同一個 preset 逐位元組相同、skipped 恰多那一項）、`test_library_has_no_crop_presets`（使用者庫 1466 個中這一項出現 0 次；A13 全庫測試照舊）。
- [ ] C11（效能）：A17（1.5MP 全管線中位數 ≤ 25 ms）對「angle 7.5＋4:5 裁切」再量一次，門檻不變；達不到先 profile 記進本合約。`tools/bench_preview.py --geometry` 加一個情境（拖拉直滑桿），門檻同 B7。釘死：`test_render_with_geometry_latency`（GPU 忙碌規則同 R1）。

### 三、編輯與照片庫
- [ ] C12（編輯檔，D3(A)，修訂 PL3／PL9／PLP8）：沒有幾何的編輯照舊寫 `darkroom-edit/1`（5 鍵，位元組與今天相同）；有幾何的寫 `darkroom-edit/2`（常數「編輯檔 /2 鍵與順序」，多一個 `geometry`，值＝C1 正規化後的物件）。讀：`/1` 視為 `geometry: null`；`/2` 的 `geometry` 不合 C1 → PL9「損壞」unavailable；其他版本照舊 conflict、不覆寫。`get_edit` 等回應的 `edit` 一律是磁碟上那份（`/1` 就沒有 `geometry` 鍵）；前端以 `edit.geometry ?? null` 讀。「沒有編輯」（PL3 刪檔）改為 preset null、overrides 空、**而且** geometry null。`.prev.json`（S4）照存整份；S4a 的「與上一份相同」比較含 geometry。`_edit_summary`、`saved_params`、`edit_params`、`resolve_params` 都能讀兩種版本。釘死：`test_edit_v1_bytes_unchanged`（沒幾何的 set_edit 寫出與 S2 時代逐位元組相同）、`test_edit_v2_roundtrip`、`test_edit_v3_conflict_not_overwritten`、`test_restore_compares_geometry`。
- [ ] C13（`set_edit` 的幾何，D4(A)，修訂 PL7）：`set_edit(path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP)`：參數省略（HTTP body 沒有 `geometry` 鍵、MCP 沒給、CLI 沒有任何幾何旗標）＝沿用這張已存的幾何；`null`（CLI `--no-geometry`）＝清除；物件＝取代。驗證順序：路徑 → preset → strength → overrides → geometry（C1 句）。釘死：`test_set_edit_geometry_tristate`（省略保留、null 清除、物件取代；只有幾何也是一份編輯；清除後三者皆空 → 刪檔）。
- [ ] C14（貼上，修訂 PL8；相容補丁 S2b）：`paste_edit(targets, source=None, edit=None, *, with_geometry=False)`；`with_geometry` 不是布林 → invalid 常數句。`False`：每個 target 的顏色（preset 快照、strength、overrides）換成來源的，**target 原本的幾何保留**（沒有就沒有）；來源的顏色部分是空的（preset null、overrides 空）→ 整批 invalid 常數「只有幾何不能只貼顏色」句、什麼都不寫。`True`：連來源的幾何一起整份取代（來源沒有幾何＝清掉 target 的幾何）。幾何以正規化座標原樣貼過去，換到不同長寬比的照片時由 C3 在渲染時重新套進有效區與比例（不在貼上時改寫）。**S2b**：S1 的自動存檔 PASTE 路徑（`L.editRequest`）一律帶 `with_geometry: true`，`edit` 依 C12 帶 `geometry`（有幾何時 schema `/2`）。釘死：`test_paste_keeps_target_geometry`、`test_paste_with_geometry`、`test_paste_geometry_only_refused`、`tests/js` `L.editRequest`（PASTE 分支帶 `with_geometry:true`）、`test_autosave_keeps_crop`（aiohttp：裁切後走 PASTE 存檔，`GET /api/edit` 讀回同一個幾何）。
- [ ] C15（存成 preset 不帶幾何）：`save_edit_as_preset`、`save_user_preset` 寫出的 xmp 不含 C10 列的任何 `Crop*`／`HasCrop` 屬性（preset＝調色；幾何是這張照片的）；E16 `preset_files` 不變。釘死：`test_saved_preset_has_no_crop`。
- [ ] C16（還原成原圖，D8(A)，修訂 S10）：`resetToOriginal` 也把幾何清成 null（一步歷史，Ctrl+Z 拿回）；縮圖格的「還原成原圖」（`DELETE /api/edit`）照舊整份刪除、`.prev.json` 含幾何，「取回上一份」拿回裁切。釘死：`tests/js` reducer、`test_restore_previous_edit` 加幾何案例。

### 四、預覽、縮圖、匯出
- [ ] C17（預覽，修訂 L5／B4）：`preview(image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, geometry=KEEP, frame=False)`；`geometry` 三態同 C13（省略＝這張照片已存的幾何，經 `Engine.get(image_id)["fingerprint"]` 讀編輯；讀不到時的錯誤句同 PLP5）；`frame` 布林（否則 invalid 常數句）。輸出尺寸＝`preview_size(輸出尺寸 C5, max_pixels 或 1500000)`；`frame=True` 時＝`preview_size(W′, H′, …)`。預覽底圖（D6(B)）：輸出尺寸對應到底圖上不足 `preview_size(輸出尺寸)` 的像素時，Engine 改用較大的底圖（常數「細節底圖」上限）取樣，輸出解析度不因裁切變低；底圖只是實作細節，輸出尺寸與上面的式子相同。`open_photo` 回應形狀不變（L8 golden 不動；`preview_width／height` 仍是未裁切的值）。釘死：`test_preview_geometry_size`、`test_preview_geometry_omitted_uses_saved`、`test_preview_frame_mode`、`test_preview_crop_stays_sharp`（裁掉 3/4 面積後輸出寬高＝`preview_size(輸出尺寸)`，且與「全解析度渲染後縮到同尺寸」的平均絕對差 ≤ 2/255）；延遲見 M3。
- [ ] C18（縮圖，D7(A)，修訂 PL11／PL13／S8）：`thumbnail(path)` 照舊產生並快取「未編輯的原圖縮圖」（`thumbs/` 檔案與規則不變）；回傳前若這張有幾何，以 `Geometry.apply` 在 256 px 縮圖上套用（CPU、不放大：長邊＝`min(256, 縮圖上裁切區的長邊)`），回傳的 `width／height` 是套用後的。不新增快取檔。`X-Edit` 多兩個鍵（常數「X-Edit」）：`geometry`（bool）、`tweaks`（bool，有微調）；格子 `title` 依常數「徽章 title」。PL16 (b) 熱快取 500 張 ≤ 2 秒照舊（M5）。釘死：`test_thumbnail_applies_geometry`（rotate 90＋4:5：寬高與 `Geometry.apply` 結果相同、照片資料夾開檔次數同 PLP8）、`test_thumbnail_edit_header`（加兩鍵）、`bench_photo_library.py` (b)。
- [ ] C19（匯出，修訂 X3／E8／E15／E15a／XP30）：item 多一個可選鍵 `geometry`（三態同 C13：省略＝已存的幾何）；E15「三個鍵都省略＝已存編輯」改為四個鍵（`preset_id`、`strength`、`overrides`、`geometry`）。輸出像素寬高＝C5 輸出尺寸（不再是「轉正後原圖寬高」）；E8 縮放以輸出尺寸為 (w, h)；EXIF `PixelXDimension／PixelYDimension`＝最後寫出的寬高、`Orientation`＝1（X6 照舊）。CLI `--no-edit` ＝ `preset_id: null` 且 `geometry: null`（原圖就是原圖）。E15a：編輯器匯出的 `currentRequest()` 帶畫面當下的 `geometry`（明確值，null 也送）。像素：`render_full` 走同一個 `render(..., geometry=)`；X2 等式改為「與同幾何、同參數的預覽管線全解析度渲染相同」。釘死：`test_export_applies_geometry`（rotate 90＋angle 0＋crop → 輸出＝`render_full` 量化、寬高＝輸出尺寸）、`test_export_saved_geometry`（只送 path → 用存好的幾何；`--no-edit` → 原圖尺寸）、`test_export_resize_after_crop`、`test_export_exif_dimensions_after_crop`；XP8／E11 吞吐量情境加 `angle 3＋3:2 裁切`（M4）。

### 五、三入口
- [ ] C20（操作數與簽名）：**不新增操作、工具、路由**：facade 操作 33、MCP 工具 33、HTTP 路由 35、G10 白名單 5 全部不變（`test_exactly_thirty_five_routes` 照舊）。改變的只有簽名與 schema（常數「簽名變化」）：`preview`、`set_edit`、`paste_edit`、`export` 的 item；`DarkroomFacade` 照舊一行 `return`；`FakeDarkroom` 同步新參數。HTTP：`POST /api/preview` body 加 `geometry`、`frame`；`PUT /api/edit` 加 `geometry`；`POST /api/edit/paste` 加 `with_geometry`；`POST /api/export` items 加 `geometry`；全部照舊過 `_local_only`（R10～R12）。CLI：常數「CLI 幾何旗標」加到 `preview`、`edit set`、`export`；`preview --frame`；`edit paste --with-geometry`；旗標值不合法時原字串交給 service 判（同 XP17），句子三入口相同；`--no-geometry` 與其他幾何旗標同時給 → argparse 用法錯誤（結束碼 2）。MCP：`darkroom_preview`、`darkroom_edit_set`、`darkroom_export`（items）加 `geometry`（常數「MCP geometry schema」），`darkroom_preview` 加 `frame`，`darkroom_edit_paste` 加 `with_geometry`；annotations 不變。L9：`edit *`、`thumbnails` 照舊不得載入 torch（`Geometry` 驗證不 import torch，C6）。釘死：`test_layering`（簽名、OPERATIONS 不變、FakeDarkroom）、`test_app_mcp`（inputSchema）、`test_cli_geometry_flags`、`test_http_golden`（新欄位的錯誤句、路由數 35）。
- [ ] C21（三入口一致性，加入 `tests/test_interface_parity.py`）：每個 driver 自己的暫存 data_dir 與照片複本。情境至少：geometry 每一種 invalid 句（rotate 45、angle 46、aspect `0:3`、crop left ≥ right、多一個鍵、`flip:"yes"`）三邊同句；`frame:1` invalid；set_edit 帶幾何 → get 相同；省略 geometry 再 set → 幾何保留；`null` → 清除；只有幾何的編輯；paste 預設保留 target 幾何；`with_geometry:true` 帶過去；來源只有幾何 → invalid 同句；`darkroom-edit/3` 編輯檔 → conflict；preview 帶幾何（三邊寬高相同）；thumbnail 有幾何（寬高與 fingerprint 相同）；export 只送 path、照片有存好的幾何（三邊輸出寬高與 SHA-256 相同）；export `--no-edit`（原圖尺寸）。

### 六、前端
- [ ] C22（裁切模式的進出與復原，D10(A)）：工具列 `#crop-btn`（文字「裁切」、`aria-pressed`、快捷鍵 `R`，焦點不在輸入框、無修飾鍵）。進入時把目前幾何複製成草稿 `crop.draft`（不進 `L.reduce`），畫面改成 `frame` 預覽＋裁切框覆蓋層；草稿自己的復原堆疊（Ctrl+Z／Ctrl+Shift+Z 只動草稿，上限 50 步）。**確認**＝Enter、`#crop-done`、再按 `#crop-btn`／`R`、換照片、開縮圖格、開匯出對話框：草稿與進入時不同 → `dispatch({type:'setGeometry', geometry})` 一步歷史（之後照常自動存檔）；相同 → 什麼都不做。**取消**＝Esc、`#crop-cancel`：丟掉草稿、畫面回到進入前，不進歷史、不存檔。裁切模式中不排程任何存檔（S1 的 dispatch 規則照舊，草稿不經 dispatch）。確認後 Ctrl+Z 一次就回到進入前的幾何。釘死：`tests/js` `L.cropSession`（enter／change／undo／commit／cancel 的純狀態機）、`test_crop_mode_structure`（Enter／Esc 綁定、確認路徑清單、取消不呼叫 dispatch）。
- [ ] C23（裁切框操作）：覆蓋層 `#crop-box`（8 個把手：四角＋四邊、框內拖曳＝移動；框外變暗；拖動時顯示三分線）；所有拖動的結果由純函式 `L.cropDrag(draft, frameSize, handle, dx, dy)` 算出、最後一律經 `L.fitCrop`（＝C3，同一份案例表）；比例鎖定時拖邊或角都保持比例；最小框邊＝常數「最小框」。**拖框期間不得發出任何 `/api/preview` 請求**（同 S7 對照的規則；放開後也不發——框只是覆蓋層，畫面在確認後才換）。`#crop-aspect`（select，選項依常數「比例選單」、預設「原始」，D11）、`#crop-orient`（「直式／橫式」，快捷鍵 `X`，1:1 與自由時 disabled）、拉直 `#crop-angle`（range −45～45、step 0.1，雙擊歸 0；旁邊數字輸入）、`#rotate-left`、`#rotate-right`（快捷鍵 Ctrl+[、Ctrl+]，裁切模式外也可用＝直接一步 `setGeometry`）、`#flip-h`、`#flip-v`、`#crop-reset`（草稿幾何改成 null）、`#crop-done`、`#crop-cancel`；`#crop-hint` 顯示常數「裁切模式提示」。拉直滑桿拖動時照「最新一次優先」請求 `frame` 預覽（同滑桿，B7），框依 `L.fitCrop` 自動縮進有效區（空白自動裁掉）。框可聚焦：方向鍵移動 0.5%、Shift 5%。釘死：`tests/js` `L.cropDrag`、`L.fitCrop`、`L.geometryAction`、`test_crop_controls_structure`、瀏覽器量測（拖框期間 preview 請求數 0；截圖 1600 與 820）。
- [ ] C24（reducer 與自動存檔）：`snap` 加 `geometry`；新 action `setGeometry`（一步歷史）；`restoreEdit` 讀 `edit.geometry ?? null`；`undo／redo` 帶幾何；`L.editBody` 一律帶 `geometry`（null 也送）；`currentRequest()` 帶 `geometry`。**換照片時幾何不沿用**：R5／S11 的「沿用」只沿用 preset、強度、微調；新照片沒有編輯 → 幾何 null（`carryHintVisible` 判準不變，只看顏色）。釘死：`tests/js`（reducer、`editBody`、`L.carryGeometry`＝固定回 null）、`test_photo_switch_drops_geometry`（結構：openPhoto 後的沿用路徑把 geometry 設 null）。
- [ ] C25（A/B 與原圖，D9(A)，修訂 S7）：裁切模式外，A/B 的「原圖」與按住 `\` 的原圖用**同一個幾何**、不套調色（左右兩半對得上）；快取鍵改為 `image_id`＋幾何的正規化 JSON。裁切模式中 `#ab-btn` disabled、title＝常數「A/B 停用原因」、`Y` 無效；已開著的 A/B 在進入裁切模式時先關掉，離開後不自動打開；按住 `\` 在裁切模式中顯示 `frame` 模式的原圖。釘死：`test_ab_compare_structure`（快取鍵、裁切模式 disabled）、`tests/js` `L.originalKey`。
- [ ] C26（縮圖格）：`#paste-edit-btn` 旁加勾選框 `#paste-geometry`（標籤常數「貼上連同幾何」，預設不勾、不記憶）；貼上時 `with_geometry`＝它的值；確認句沿用 PL 常數，勾選時後面加常數「貼上確認附註」。縮圖顯示套用幾何後的比例（`object-fit: contain`）。釘死：`test_grid_paste_geometry_structure`、`tests/js` `L.pasteConfirm`。
- [ ] C27（窄視窗，修訂 S18／E30 清單）：`PROTECTED` 與 `index.html` 的 `hidden` 檢查加入 `#crop-btn`、`#crop-aspect`、`#crop-orient`、`#crop-angle`、`#rotate-left`、`#rotate-right`、`#flip-h`、`#flip-v`、`#crop-reset`、`#crop-done`、`#crop-cancel`、`#paste-geometry`（裁切面板本身可用 `hidden`，它是一個模式）；820×600 時裁切面板全部控制項可見或可捲到，`.pv-wrap` ≥ 400px。釘死：`test_narrow_windows_keep_function_buttons`、瀏覽器量測。

### 七、回歸與文件
- [ ] C28：`python -s -m unittest discover -s tests` 結束碼 0；`node --test tests/js/test_logic.cjs` fail 0；preset 合併雜湊仍 `15C015CC0C080FF9`、1466 個；真實 data_dir 與 preset 庫快照不變（G7）；不新增依賴（grid_sample／warpAffine 都是既有 torch／cv2）。既有測試只准改：本合約補丁點名的地方（A2 名稱數、PL3 刪檔判準、S8 `X-Edit` 鍵、S7 原圖快取鍵、PROTECTED、`FakeDarkroom` 簽名、MCP inputSchema），逐處記成實作補丁。文件：`AGENTS.md`（CLI 表加幾何旗標、`edit paste --with-geometry`、`preview --frame`；MCP 表；食譜 3 註明貼上預設不帶裁切；工具數 33 不變）、`CONTEXT.md`（新詞：幾何、裁切、拉直、裁切模式；「編輯」含幾何；「複製／貼上編輯」改為預設只貼顏色）、`darkroom-edit` skill（裁切、旋轉、貼上帶幾何）、`README.md`。

## 對既有合約的補丁提案（本合約封緘時一併寫進各合約補丁區）
- K5（核心，修訂 A2、A6 說明、A13）：公開名稱 7 → 8（加 `Geometry`）；`render` 加僅限關鍵字的 `geometry`；`Params` 與 `darkroom-params/1` 不變（幾何不是調色參數，不受強度縮放）；A13 的 skipped 對 preset 裁切記 C10 的近似項。
- PL3'／PL8'／PL9'／PLP8'（照片庫）：C12（`/1`、`/2` 兩種版本、刪檔判準）、C13（set_edit 三態）、C14（paste `with_geometry`）。CONTEXT.md「複製編輯／貼上編輯」定義同步改。
- S2b（S1 自動存檔）：PASTE 路徑帶 `with_geometry: true`（C14）。S4a'：比較含幾何（C12）。S7'：原圖同幾何、裁切模式停用（C25）。S8b：`X-Edit` 加 `geometry`、`tweaks`（C18）。S10'：還原成原圖清幾何（C16）。S11'：沿用不含幾何（C24）。S18'：清單（C27）。
- XP35（匯出，修訂 X3、X2、XP30、E8、E15、E15a、E26 `--no-edit`）：C19。
- L5'（預覽尺寸）：C17 的輸出尺寸式子取代「預覽底圖的寬高」；HTTP 不傳 `max_pixels` 時照舊。
- PL11'／PL13'（縮圖）：C18（快取不變、回傳時套幾何）。

## 主 session 裁決（2026-10-10；以下 D1～D13 原為待裁決選項，全部採「建議」那一項，條文以本節「定案」為準）

### 定案（主 session 2026-10-10，與條文同等效力）
- D1＝(B)：先切出輸出畫面再渲染；Dehaze 大氣光與 Texture 雜訊門檻取自「轉正後、未裁切、縮到 ≤ 1500000 像素的整張」（常數「統計來源」）。**例外**：M1 實測「直接用裁切後的畫面算統計」（=(A)）的保留區色差 p95 ≤ 2/255 時改採 (A)，C7 的 D1(B) 句與 `test_crop_keeps_colors` 一起拿掉，寫成實作補丁。
- D2＝(A)：核心多一個公開名稱 `Geometry`（7 → 8）＋`render(..., geometry=)`。
- D3＝(A)：沒有幾何照寫 `darkroom-edit/1`（位元組不變）；有幾何才寫 `/2`。
- D4＝(A)：省略＝沿用已存的幾何，`null`＝清除。
- D5＝(A)：preset 帶的裁切欄位永遠不套用；有實際裁切時列 minor 略過項。
- D6＝(B)：預覽改用細節底圖（上限 4 × 1500000 像素）。
- D7＝(A)：縮圖快取照舊，回傳時在 256 px 上套幾何。
- D8＝(A)：「還原成原圖」連幾何一起清。
- D9＝(A)：A/B 在裁切模式中停用；模式外兩邊同一個幾何。
- D10＝(A)：只有 Esc／取消鈕算取消，其他離開方式都算確認。
- D11＝(A)：預設比例＝原始（鎖定）。
- D12＝(A)：拉直用雙三次；M2 GPU／CPU 平均差超過 1/255 就改雙線性（寫成實作補丁）。
- D13＝(A)：縮圖格批次旋轉不在 S3（33／33／35 不動）。

### 原選項（存檔備查）
- D1（C7，渲染順序與整張統計）：(A) 先切出輸出畫面再渲染，Dehaze／Texture 的統計也用輸出畫面——最簡單、最快，但**裁切會讓保留區的顏色改變**（673 個 preset 有 Dehaze）；(B) 先切再渲染，但 Dehaze 大氣光與 Texture 雜訊門檻取自「轉正後、未裁切、縮到 ≤ 1.5MP 的整張」（核心內部先算統計再渲染輸出畫面）——裁切不改顏色、預覽與匯出用同一份統計（順帶讓兩者更一致），代價是核心多一段統計程式、有 Dehaze 時每次渲染多算一次小圖；(C) 整個框渲染完再切，暈影改用裁切框座標——顏色最穩，但 GPU 成本按未裁切面積、預覽在重裁切時會糊（與 D6(B) 互斥）。**建議 (B)**，但先做 M1：(A) 的保留區色差若 p95 ≤ 2/255 就改採 (A)（省掉統計程式），條文 C7 的 D1(B) 句與 `test_crop_keeps_colors` 一起拿掉。
- D2（C6，幾何放在哪）：(A) 核心新公開名稱 `Geometry`（7→8）＋`render(..., geometry=)`，驗證、解析、CPU 套用都只有這一份，縮圖（CPU）、預覽／匯出（GPU）共用同一個矩陣；(B) 放進 `Params.values`（用 crs 鍵名）——會被強度縮放（A7）、`darkroom-params/1` 要升版，preset 的 Crop 欄位也會混進來；(C) 留在 `darkroom_app`，核心只多收一個「遮罩座標轉換矩陣」——幾何規則散在兩層，縮圖還要第三份。**建議 (A)**。
- D3（C12，編輯檔版本）：(A) 沒幾何照寫 `/1`（位元組不變）、有幾何才寫 `/2`；(B) 一律寫 `/2`；(C) `/1` 加一個可選鍵。**建議 (A)**：既有測試與使用者現有編輯完全不動；舊版 darkroom 讀到 `/2` 是 conflict（不覆寫，PL9），比 (C) 被舊版判成「損壞」清楚。
- D4（C13、C17、C19，省略幾何參數的意思）：(A) 省略＝沿用這張已存的幾何，`null`＝清除；(B) 省略＝沒有幾何。**建議 (A)**：代理照 AGENTS.md 食譜 4 `edit set --preset …` 或 `export --preset …` 不會悄悄丟掉使用者裁好的框；前端一律送明確值，不受影響。
- D5（C10，preset 帶的 Crop 欄位）：(A) 永遠不套，有實際裁切時列 minor 略過項；(B) 照片還沒有幾何時，套 preset 的裁切當初值（要先查證 Lightroom 的 Crop 座標定義，G9）；(C) 不套也不列。**建議 (A)**：使用者庫 1466 個裡 0 個帶裁切（G3），preset 是調色、裁切是每張照片自己的；列出來是誠實回報（A13 精神），minor 不打擾。
- D6（C17，預覽解析度）：(A) 一律從現有 1.5MP 底圖切——裁掉 3/4 面積時預覽只剩約 375k 像素、明顯變糊；(B) 輸出尺寸照式子算，底圖不夠時 Engine 改用較大的「細節底圖」（上限見常數；可保留目前照片的全解析度主機複本或重讀原檔，實作自選，量 M3）。**建議 (B)**（省心：裁切後看得清楚對焦）。
- D7（C18，縮圖）：(A) 快取照舊存原圖縮圖，回傳時在 256 px 上套幾何（不放大，重裁時會小一點）；(B) 另存一份「套幾何後」的縮圖快取（鍵含幾何雜湊，要多一套失效規則）。**建議 (A)**：零新快取檔，PL16 仍成立；縮圖本來就「只用來挑照片」（CONTEXT）。
- D8（C16，「還原成原圖」清不清幾何）：(A) 清（原圖就是原圖，Ctrl+Z／取回上一份拿得回來）；(B) 只清顏色。**建議 (A)**。
- D9（C25，A/B 在裁切模式）：(A) 裁切模式停用 A/B（disabled＋原因），模式外原圖與編輯後同幾何；(B) 裁切模式中 A/B 也照常（原圖也是整框）。**建議 (A)**：裁切時在看構圖不是看顏色，少一種疊圖狀態要處理。
- D10（C22，怎樣算確認）：(A) 只有 Esc／取消鈕是取消，其他離開方式（Enter、完成、再按裁切、換照片、開縮圖格、匯出）都算確認（Lightroom 做法）；(B) 只有 Enter／完成是確認，其他都算取消。**建議 (A)**：使用者裁好就去下一張，不會白裁；萬一不要，Ctrl+Z 一步拿回。
- D11（C23，預設比例）：(A) 原始比例（鎖定）；(B) 自由。**建議 (A)**（Lightroom 預設、拉直時自動裁掉空白最自然）。
- D12（C2、C9，angle ≠ 0 的重取樣）：(A) 雙三次（`grid_sample` bicubic／`cv2.INTER_CUBIC`）；(B) 雙線性。**建議 (A)**，但以 M2 的 GPU／CPU 一致性實測為準；不一致超過 1/255 平均就改 (B)。
- D13（範圍，縮圖格批次旋轉）：(A) 不在 S3（要旋轉就開進編輯器，或用 CLI／MCP `edit set --rotate`）；(B) 新增操作 `rotate_photos(paths, rotate)`（34／34／36）。**建議 (A)**：手機照片方向大多已由 EXIF 轉正；保持 33／33／35 不動。

## 需要先實測（開工第一步，結果記成實作補丁）
- M1（D1）：專用 Python、真實 preset 庫中 Dehaze 不為 0 的 673 個 × 3 張程式產生／測試照片（含天空在上方的）：「裁下半部再渲染」對「整張渲染再切」的保留區平均絕對差，印 p50／p95／max；決定 D1 (A) 或 (B)。另量 Texture 不為 0 的 324 個。
- M2（D12、C9）：`grid_sample`（bicubic、bilinear，`align_corners=False`、`border`）與 `cv2.warpAffine`（`INTER_CUBIC`、`INTER_LINEAR`、`BORDER_REPLICATE`）在 angle 0.1／7.5／45 時的平均與最大差；確認兩邊像素中心慣例一致（常數「反向對應」），寫入 C9 的最大差常數。
- M3（C11、C17、D6）：A17 加幾何的中位數；B7 拉直滑桿拖動延遲；D6(B) 確認裁切後第一張清晰預覽的延遲（草稿目標 ≤ 600 ms）與之後每張（門檻同 B7）、細節底圖的顯存用量。
- M4（C19）：XP8 情境（20 張 24MP）加 `angle 3＋3:2 裁切`：每張秒數（門檻照 E11 0.8 秒）與 `grid_sample` 在 24MP 的峰值顯存（grid 本身約 192 MB）。
- M5（C18）：`bench_photo_library.py` (b) 熱快取 500 張、其中一半有幾何：≤ 2 秒。
- M6（C23）：瀏覽器（1600×900、820×600）拖框 5 秒：`/api/preview` 請求數 0、主執行緒無 > 50 ms 的長任務；拉直滑桿拖動時的預覽請求為最新一次優先。

## 不在 S3（記錄，不做）
- 透視校正（Upright、Vertical／Horizontal）、鏡頭校正（扭曲、暗角、色差、描述檔）、`Perspective*` 與 `LensManualDistortionAmount` 的套用（使用者庫全為 0，G3）。
- AI 構圖建議、自動拉直（偵測地平線）、自動裁切、臉部置中。
- 讀 Lightroom sidecar `.xmp` 或照片裡 XMP 的裁切（ADR-0002：照片資料夾永遠不寫；也不讀別人的編輯）、把幾何寫成 sidecar。
- 尺寸以英吋／公分指定的裁切、固定像素尺寸的裁切（`CropWidth／CropHeight`、`CropUnit`）、自訂比例存成清單、黃金比例／螺旋等其他構圖線。
- 縮圖格批次旋轉（D13）、預覽縮放（放大到 100% 檢查）。
- 從 preset 套用裁切（D5 選 (B) 才另開）。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 自動存檔丟掉裁切（C14 S2b） | PASTE 帶 `with_geometry:true` | 使用者剛裁好的框 → 下一次自動存檔被貼上預設清掉，重開就不見｜不可逆／資料 | `test_autosave_keeps_crop`、`L.editRequest` |
| 貼上覆蓋別張的裁切（C14） | 預設保留 target 幾何 | 使用者每張各自裁好的框 → 批次貼顏色時全被換掉｜不可逆／資料 | `test_paste_keeps_target_geometry`、parity |
| 編輯檔版本（C12） | `/1` 位元組不變、`/2`、其他 conflict | 使用者現有編輯 → 升級後讀不回或被舊版覆寫｜不可逆／資料 | `test_edit_v1_bytes_unchanged`、`test_edit_v3_conflict_not_overwritten` |
| 代理省略幾何（C13、C19） | 省略＝沿用 | 使用者裁好的照片 → 代理 `edit set`／`export` 後裁切悄悄消失｜邏輯核心 | `test_set_edit_geometry_tristate`、`test_export_saved_geometry` |
| 遮罩與暈影位置（C7、C8） | 遮罩用來源座標、暈影用輸出座標 | 使用者的成品 → 旋轉後天空漸層跑到地上、暈影偏到原圖中心｜邏輯核心 | `test_masks_follow_content`、`test_vignette_is_post_crop` |
| 裁切改變顏色（C7，D1） | 統計來源 | 使用者 → 裁一下顏色就跳｜邏輯核心 | `test_crop_keeps_colors`（D1(B)） |
| 框解析的雙邊一致（C3、C4） | 共用案例表 | 使用者 → 畫面上的框跟匯出的範圍不一樣｜上下游契約 | `test_geometry_shared_cases`、`L.fitCrop`、`test_geometry_actions_match_pixels` |
| 沒幾何的照片不變（C6、C12） | 逐位元組 | 使用者所有既有照片 → 升級後預覽／匯出悄悄改變｜邏輯核心 | `test_render_without_geometry_unchanged`、既有 golden |
| 取消真的取消（C22） | 草稿不經 dispatch | 使用者按 Esc → 框還是被存進去｜UI/UX | `L.cropSession`、`test_crop_mode_structure` |
| 三入口簽名（C20） | 33／33／35 不變 | 代理 → 工具清單與文件對不上｜上下游契約 | `test_layering`、`test_app_mcp`、`test_http_golden` |
| 窄視窗（C27） | H11 清單 | 使用者 → 820 寬找不到完成／取消｜UI/UX | `test_narrow_windows_keep_function_buttons` |

## Verbatim Constants
```text
幾何 schema（鍵與順序）：{"rotate": 0|90|180|270, "flip": bool, "angle": number, "aspect": "original"|"free"|"{w}:{h}", "crop": null|{"left","top","right","bottom"}}
幾何範圍：rotate 順時針度數 ｜ angle −45～45（度，正＝內容順時針）｜ aspect w、h 為 1～65535 的整數，存約分後 ｜ crop 0 ≤ left < right ≤ 1、0 ≤ top < bottom ≤ 1
恆等幾何：rotate 0、flip false、angle 0、crop null（aspect 不論）→ null
順序：來源（轉正後 W×H）→ rotate → flip（水平）→ angle（繞框中心，畫布 W′×H′ 不變）→ crop
反向對應（輸出像素 (i, j) → 來源點 (x, y)，像素中心慣例，c′ = (W′/2, H′/2)）：
  p = (L + i + 0.5, T + j + 0.5)；q = Rot(−angle)(p − c′) + c′，Rot(φ) = [[cos φ, −sin φ], [sin φ, cos φ]]（y 向下，正 φ 為畫面上的順時針）
  flip 時 q.x = W′ − q.x
  rotate 0：(x, y) = (q.x, q.y) ｜ 90：(q.y, H − q.x) ｜ 180：(W − q.x, H − q.y) ｜ 270：(W − q.y, q.x)
  遮罩值在 (x / W, y / H) 評估（C8）；暈影在輸出座標評估
解析步驟（C3）：(1) crop null → 中心 c′、比例 ρ 的最大框 ｜ (2) aspect 非 free 且 |w/h − ρ| / ρ > 0.001 → 同中心、同面積改成 ρ ｜ (3) 中心不在有效區 → 移到 c′ ｜ (4) 最大縮放 ｜ (5) 四邊 floor(x + 0.5)，寬高 ≥ 1
ρ：original 與 free ＝ W′/H′ ｜ "w:h" ＝ w/h
最大縮放（框中心 m、半寬高向量 e_k = (±w/2, ±h/2)，a = Rot(−angle)(m − c′)，b_k = Rot(−angle) e_k）：
  s* = min(1, 對每個角 k 與每一軸：(W′/2 − sgn(b)·a)/|b|、(H′/2 − sgn(b)·a)/|b|（有效區）以及 (W′/2 − sgn(e)·(m − c′))/|e|、(H′/2 − …)/|e|（畫布）中 b、e ≠ 0 的值）；新框 = m ± s*·e_k；永不放大
重取樣：angle ≠ 0 → grid_sample(mode="bicubic", align_corners=False, padding_mode="border") 後 clamp 0～1 ｜ CPU：cv2.warpAffine(INTER_CUBIC, BORDER_REPLICATE) ｜ angle 0 → 只做 rot90／flip／切片（逐位元組）
空白填色（frame 模式）：0（黑）
統計來源（D1(B)）：轉正後、未裁切的整張來源，preview_size(W′, H′, 1500000)，INTER_AREA ｜ 保留區容差：平均絕對差 ≤ 1/255
細節底圖上限（D6(B)）：長邊不超過原圖、像素數 ≤ 4 × 1500000
操作表（C4，框 (l, t, r, b) 正規化）：
  向右轉 90°：flip false → rotate + 90，flip true → rotate − 90（mod 360）；框 → (1 − b, l, 1 − t, r)；"w:h" → "h:w"；angle 不變
  向左轉 90°：flip false → rotate − 90，flip true → rotate + 90；框 → (t, 1 − r, b, 1 − l)；"w:h" → "h:w"；angle 不變
  水平鏡像：flip = !flip；angle = −angle；框 → (1 − r, t, 1 − l, b)
  垂直鏡像：flip = !flip；rotate + 180；angle = −angle；框 → (l, 1 − b, r, 1 − t)
  直式／橫式：original → 約分後的 "H′:W′"；"w:h" → "h:w"；1:1 與 free 不動；框以中心依 C3 (2)～(5) 重算
比例選單（值 ｜ 顯示）：original 原始 ｜ free 自由 ｜ 1:1 ｜ 4:5（8×10）｜ 5:7 ｜ 2:3（4×6）｜ 3:4 ｜ 16:9 ｜ 預設 original
  （直式顯示上面的值；橫式時為 5:4、7:5、3:2、4:3、9:16 的對調）
最小框：螢幕上 32 px（且輸出寬高 ≥ 1）
編輯檔 /2 鍵與順序：{"schema":"darkroom-edit/2","fingerprint","preset","strength","overrides","geometry"} ｜ 沒有幾何照寫 darkroom-edit/1（5 鍵）
核心公開名稱（8 個）：load_preset、Params、render、read_image、write_image、SCHEMA_VERSION、UnsupportedPresetError、Geometry
render 簽名：render(image, params, strength=1.0, device=None, *, geometry=None)
簽名變化（操作數不變：facade 33 ｜ MCP 33 ｜ HTTP 路由 35 ｜ G10 白名單 5）：
  preview(image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, geometry=KEEP, frame=False)
  set_edit(path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP)
  paste_edit(targets, source=None, edit=None, *, with_geometry=False)
  export(items, …)：item 鍵 image_id|path、preset_id、strength、overrides、geometry（皆可省略）
CLI 幾何旗標（preview、edit set、export）：--rotate 0|90|180|270 ｜ --flip ｜ --angle DEG ｜ --aspect original|free|W:H ｜ --crop L,T,R,B ｜ --no-geometry
  （給了任何幾何旗標＝以旗標組一個新幾何，未給的欄位取恆等值、aspect original；不與已存的合併）
  preview --frame ｜ edit paste --with-geometry ｜ export --no-edit ＝ preset_id null 且 geometry null
MCP geometry schema：{"type":["object","null"],"properties":{"rotate":{"enum":[0,90,180,270]},"flip":{"type":"boolean"},"angle":{"type":"number","minimum":-45,"maximum":45},"aspect":{"type":"string"},"crop":{"type":["object","null"],"properties":{"left":{"type":"number"},"top":{"type":"number"},"right":{"type":"number"},"bottom":{"type":"number"}},"additionalProperties":false}},"additionalProperties":false}
  darkroom_preview 加 geometry、frame（boolean）｜ darkroom_edit_set 加 geometry ｜ darkroom_export items 加 geometry ｜ darkroom_edit_paste 加 with_geometry（boolean）

invalid：
  幾何要是物件或 null：{geometry}
  幾何設定不認得的鍵：{key}（可用 rotate、flip、angle、aspect、crop）
  rotate 要是 0、90、180、270 其中之一：{rotate}
  flip 必須是 true 或 false
  拉直角度要在 -45～45 度之間：{angle}
  不支援的裁切比例：{aspect}（可用 original、free，或「寬:高」兩個 1～65535 的整數）
  裁切框要是 {"left","top","right","bottom"}，而且 0 ≤ left < right ≤ 1、0 ≤ top < bottom ≤ 1：{crop}
  frame 必須是 true 或 false
  with_geometry 必須是 true 或 false
  只有幾何不能只貼顏色：這份編輯只有裁切／旋轉，要貼上請連同幾何一起貼（with_geometry）
  CLI：--crop 要是 L,T,R,B 四個 0～1 的數：{value}
preset 裁切略過項（C10）：裁切（preset 帶的裁切與拉直不會套用） ｜ label：裁切（preset 帶的，不套用）｜ level：minor

X-Edit（S8b）：encodeURIComponent(JSON.stringify({"preset": name|null, "strength": n, "status": "current"|"changed"|"missing"|null, "geometry": bool, "tweaks": bool}))
徽章 title：{preset 名｜只有微調（tweaks 且無 preset）｜只有裁切／旋轉（geometry 且無 preset、無 tweaks）}　{strength}%（只有 preset 時才顯示 %）｜ 有幾何且有顏色時加「・已裁切」｜ 後綴照 S8

前端：
  #crop-btn 文字「裁切」｜ 快捷鍵 R（無修飾鍵、焦點不在輸入框）｜ 直式／橫式 快捷鍵 X ｜ 向左轉 90° Ctrl+[ ｜ 向右轉 90° Ctrl+]
  按鈕文字：拉直 ｜ 向左轉 90° ｜ 向右轉 90° ｜ 水平鏡像 ｜ 垂直鏡像 ｜ 重設 ｜ 完成 ｜ 取消 ｜ 直式 ／ 橫式
  裁切模式提示：拖曳框或把手調整範圍；Enter 完成、Esc 取消
  A/B 停用原因：裁切模式中不能對照，完成或取消後再用
  貼上連同幾何：連同裁切與旋轉 ｜ 貼上確認附註：（連同裁切與旋轉）
  草稿復原上限：50 步 ｜ 拉直 step 0.1、雙擊歸 0 ｜ 框方向鍵 0.5%、Shift 5%
案例表：tests/cases/s3_geometry_cases.json（C3）｜ tests/cases/s3_geometry_actions.json（C4）
preset 合併雜湊：15C015CC0C080FF9 ｜ 數量：1466
```

## 實作補丁（2026-10-10，實作時的決定與量測；與條文同等效力，只收緊或補常數；放寬處逐項標明並說理由）
- IP1（M1 → D1 定案為 (A)）：專用 Python、真實 preset 庫（只讀）、3 張測試照（含天空在上方的 landscape_lighthouse），暈影與顆粒歸零後「裁下半部再渲染」對「整張渲染再切」的保留區平均絕對差：Dehaze 不為 0 的 673 個 × 3 張（2019 筆）p50 0.292/255、p95 1.008/255、max 10.355/255；Texture 不為 0 的 324 個 × 3 張（972 筆）p50 0.374/255、p95 1.100/255、max 1.977/255。兩者 p95 都 ≤ 2/255 → 依主 session 裁決改採 (A)：統計直接取自裁切後的畫面。C7 的「D1 選 (B) 時另加…」句、常數「統計來源」「保留區容差」與 `test_crop_keeps_colors` 一起拿掉（錯不起表面「裁切改變顏色」由這筆量測承擔）。
- IP2（M2 → D12 維持 (A)、C9 常數）：1067×1600 8-bit 照片，angle 0.1／7.5／45／−12.5：`grid_sample` bicubic 對 `cv2.warpAffine` INTER_CUBIC 平均差 ≤ 0.0007/255、最大差 1/255（bilinear 對 INTER_LINEAR 平均 ≤ 0.0005/255、最大 1/255）；兩邊像素中心慣例一致（angle 0 的 4 種 rotate × flip，GPU 與 CPU 都與 numpy 逐位元組相同）。C9 的最大差常數＝1/255。釘死：`test_geometry_cpu_matches_gpu`。
- IP3（C1，放寬並說理由）：`Geometry.from_dict` 缺的鍵取恆等值（rotate 0、flip false、angle 0、aspect original、crop null）；「多一個鍵」照舊 invalid。理由：MCP schema 沒有 required，代理只給 `{"rotate": 90}` 是常見寫法；存檔與回傳一律是 5 鍵正規化物件。
- IP4（C6）：`Geometry` 除了 from_dict／to_dict／resolve／output_size／apply，另有 `identity`、`frame_size`、`ratio`、`matrix`、`sampling`、`bound(width, height, out_width, out_height, frame=False)`（預覽從縮小的底圖取樣、frame 模式用；`render` 簽名不變）。核心公開名稱仍恰 8 個。
- IP5（C13／C20）：「省略」的哨兵 `KEEP` 放在 `darkroom_app/facade.py`（三個入口都可以 import facade，不准 import preview／services，L13）。
- IP6（C1 句子）：句中的 `{值}` 文字原樣、其他用 JSON 並把整數值的浮點數寫成整數（CLI 的 46.0 與網頁的 46 同句）。
- IP7（XP35 常數）：`EXPORT_ITEM_NOT_OBJECT`、`EXPORT_ITEM_UNKNOWN_KEY` 的鍵清單加 `geometry`。PL8 的 /2 鍵集合不對時 reason＝「keys must be exactly schema, fingerprint, preset, strength, overrides, geometry」。
- IP8（C10）：preset 的數值型 Crop 屬性照舊留在 `Params.values`（434 個帶 `CropConstrainToWarp` 的 preset 參數不變，既有編輯的 preset_status 不會因升級變 changed）；只是不進未套用清單、不渲染；C15 存成 preset 時一律不寫。
- IP9（C20 CLI）：`--no-edit` 與任何幾何旗標同給 → argparse 用法錯誤；`export` 只給幾何旗標不給顏色 → 該 item 只有 geometry（顏色＝不套 preset，與 HTTP／MCP 的 item 規則一致，AGENTS.md 已註明）；`--aspect` 單獨給＝恆等＝沒有裁切（C1 原文，AGENTS.md 已註明）。
- IP10（C17）：沒有幾何（或恆等）時走舊路徑，`frame` 只檢查型別；有幾何時輸出尺寸與 `preview_target` 同一份式子。細節底圖＝每張開啟的照片在主機留一份 16-bit 的 ≤ 6000000 像素複本，第一次需要時上傳 GPU，GPU 上只留最近一張。取樣比例超過 1.5 個來源像素／輸出像素時先 area 縮小再 `grid_sample`（防鋸齒）。
- IP11（C22 前端）：完成時若框是自動（crop null）而比例是「寬:高」，把自動框寫成實際的框再正規化（否則恆等規則會把比例丟掉）。草稿的框存使用者給的值，畫面與完成都經 `L.fitCrop`。旋轉／鏡像按鈕在裁切面板裡；模式外用 Ctrl+[／Ctrl+] 一步旋轉。
- IP12（既有測試的修改，皆在本合約補丁點名範圍內）：`test_api`（A2→8 名）、`test_layering` 與 `test_s2_entries`（`--no-edit` 帶 `geometry: null`）、`test_photo_library`（/2 的 reason、/3 的 schema 句、X-Edit 多兩鍵）、`test_export`（item 句子）、`test_s2_export`（省略 geometry 會讀編輯）、`test_app_frontend`（PROTECTED 與 hidden 清單、貼上確認與 body、currentRequest 帶 geometry）、`tests/js`（editBody／editRequest／badgeTitle）。
- IP13（量測工具）：`tools/bench_preview.py --geometry`（拉直滑桿 frame 預覽＋裁切後清晰預覽延遲）、`tools/bench_export.py --s3`（拉直 3°＋3:2，並一律用暫存 data_dir）、`tools/bench_photo_library.py --geometry`（一半照片有幾何）。
- C11 量測：`test_render_with_geometry_latency`，24MP 照片的 1.5MP 預覽（1095×1369，angle 7.5＋4:5）全管線中位數 19.08 ms（門檻 25 ms）。
- M3（C11、C17、D6；`tools/bench_preview.py --geometry`，24MP 6557×3660，GPU 閒置）：拉直滑桿 60 Hz 拖 10 秒（frame 預覽、最新一次優先）往返中位數 24.7 ms、p95 25.9 ms、最大 34.1 ms，後端渲染中位數 19.1 ms（門檻同 B7：中位數 < 100、p95 < 150，通過）；裁掉 3/4 面積後第一張清晰預覽 65 ms（含細節底圖上傳 GPU；草稿目標 ≤ 600 ms），之後中位數 20 ms；開啟 24MP 321 ms（含建細節底圖）。細節底圖在 GPU 上＝≤ 6000000 像素 × 3 × float32 ≈ 72 MB（只留一張）。對照組（同一次、無幾何的 B7）往返中位數 19.9 ms、p95 21.2 ms。
- M4（C19；`tools/bench_export.py --s3`）：20 張 6000×4000，拉直 3°＋3:2（輸出 5570×3714）0.424 秒／張（門檻 ≤ 0.8，通過）；批次 GPU 峰值記憶體 2644 MiB（含 grid 與全解析度管線）；分段中位數讀 0.396、渲染 0.312、寫 0.070 秒。
- M5（C18；`tools/bench_photo_library.py --geometry`，500 張中 250 張有幾何）：(b) 熱快取 folder_thumbnails 0.10 s、500 張 thumbnail() 0.52 s（門檻 ≤ 2 s）、照片檔開啟 0 次；PL16 其餘各項全部達標。
- M6（C23、C27；Playwright，暫存 data_dir 與 preset 庫複本，1600×900 與 820×600）：拖右下把手 2.5 秒＋拖框 2.5 秒（166 次移動）期間 `/api/preview` 請求 0 次、主執行緒 > 50 ms 長任務 0 個；拉直滑桿 121 個 input 事件送出 112 個請求、最後送出的角度＝草稿角度（-5.4，frame:true），最新一次優先；Enter 完成後編輯檔為 `darkroom-edit/2`、幾何與畫面一致；再進裁切模式轉 90° 後 Esc → 幾何不變；Ctrl+Z 一次回到沒有幾何。820×600：裁切面板 11 個控制項全部在視窗內可見、`.pv-wrap` 寬 529 px、`#export-btn` 可見、`#ab-btn` disabled 且 title＝A/B 停用原因。截圖（不進 git）：`.playwright-mcp/s3-crop-1600.png`、`s3-crop-820.png`。
- C28 全套：`python -s -m unittest discover -s tests` Ran 561 tests OK；`node --test tests/js/test_logic.cjs` pass 45、fail 0。

## 封緘第 1 次派遣處置紀錄（2026-10-10；依 Loose-Criterion Escalation／R10，與條文同等效力）
- F1（中高，邏輯核心，已修並釘死）：`_shape_mask` 在有幾何（grid 分支）時，退化的漸層遮罩（線性的零點＝滿點、放射的寬或高為 0）回傳的是來源尺寸的零張量，遮罩有實際 Local 效果時預覽與匯出 RuntimeError。改為回傳與取樣點同尺寸的零（`torch.zeros_like(xs + ys)`，沒有幾何時尺寸與數值不變）。C8 補一句：「退化形狀的遮罩值為 0，任何幾何下都照常渲染」。釘死：`test_degenerate_masks_with_geometry`（退化線性、退化放射、退化＋正常；rotate 90 逐位元組＝整張渲染後 rot90、下半部裁切 ≤ 1e-5、angle 5 尺寸正確；修正前三個情境都 RuntimeError）。使用者目前庫中 7 個 preset 帶退化形狀但沒有 Local 效果，實際未觸發。
- C29（新條文，主 session 裁決必修；S3 之前就有、S3 讓損失變大）：開啟照片時讀已存編輯失敗（`loadEdit` 失敗分支），這張照片進入「讀不到已存的編輯」狀態：`#edit-status` 顯示常數「讀不到已存的編輯：這張的修改先不會自動存檔（以免蓋掉原本存的裁切與顏色），請重新開啟這張照片」；這段期間 `scheduleSave` 對這張照片一律不排程（不送 `PUT /api/edit`、不送 `POST /api/edit/paste`），直到同一張照片的 `GET /api/edit` 重讀成功才恢復（重新開啟、或縮圖格操作後的重讀）。判準是純函式 `L.saveAllowed(unreadablePath, path)`。釘死：`tests/js` 的「C29 (seal)」以真的 `app.js`（假 DOM、假 fetch）模擬讀取失敗後動滑桿與幾何、等過自動存檔並 flush，斷言沒有任何取代已存編輯的請求，且狀態列顯示該句；對照組（讀取成功）同樣操作恰送出一次 PUT（出生證明：拿掉 `scheduleSave` 的守門那一行就紅）。
- F2（低，條文太鬆，條文補丁）：C22「裁切模式中不排程任何存檔」改為「裁切模式的草稿不排程任何存檔（草稿不經 dispatch）」；裁切模式中顏色控制項（滑桿、preset 樹）照常可用，它們的改變照常一步歷史與自動存檔；Ctrl+Z／Ctrl+Shift+Z 在裁切模式只作用於草稿，顏色的復原在離開裁切模式後照常。不改程式。
- F3（低，G4 未釘表面，已補釘）：`#crop-orient` 在 1:1／自由時 disabled、`X` 跟著它、按鈕文字依方向切換、按住 `\` 在裁切模式取草稿的 frame 原圖，都補進 `test_crop_controls_structure`／`test_ab_crop_mode_structure`；`tests/js` 補 `ORIENT_PORTRAIT`／`ORIENT_LANDSCAPE`。
- 探針 3/3 被攔：自動存檔 PASTE 的 `with_geometry` 條件化（tests/js S1/S2）、`edit=` 貼上一律帶幾何（`test_paste_keeps_target_geometry`）、匯出省略 geometry 不讀已存（`test_export_saved_geometry`）；皆已逐位元組還原。
- 記錄、不修（低）：parity 沒有覆蓋「用 edit 物件貼到自己有幾何的 target」與「有 preset_id 但省略 geometry 的匯出」兩條分支（探針 2、3 各只有一個測試攔到）。

## 封緘第 2 次派遣（複驗）處置紀錄（2026-10-10）
- F1、F2、F3、C29 在原引用處回歸皆符合；第 1 次派遣咬到的 3 支探針重打仍各自讓測試變紅；修正回合新判官（退化遮罩線性／放射兩分支、C29 的守門／catch 設旗標／狀態列選字、F3 的 5 條 assertIn 與 ORIENT 常數）各自出生證明全紅；全部逐位元組還原，git status 空。
- N-1（記錄、不修，低，只是降級不會遺失資料）：C29 的「重讀成功就恢復自動存檔」那一行（ 成功分支清掉 ）沒有測試攔得到；刪掉後只有縮圖格操作後的重讀不會恢復，要重新開啟照片才恢復（狀態列的提示本來就叫使用者重開）。下一片可在 tests/js 的 C29 補「先失敗→重讀成功→動滑桿恰送出一次 PUT」。
- 備註：F1 對 C8 的補句、F2 對 C22 的改字以第 1 次處置紀錄為準（與條文同等效力）。
