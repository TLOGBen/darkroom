# CONTRACT — darkroom S1「體驗與修正」（介面質感、A/B 對照、已編輯徽章與篩選、還原成原圖／取回上一份、審查必修）
<!-- 此處採預設：合約未經人工確認即釘死（2026-10-10 工作流程派工；決定由主 session 的 s1-brief.md 做完，不問使用者） -->

## 目標
使用者只專注修圖：換照片中途動滑桿不會把上一張的狀態寫進新照片；preset 改了或不見了，滑桿仍以當時的快照為基準、換回去也不會被庫現值蓋掉；黑白 Look 的 preset 真的是黑白；預覽與匯出的顆粒／銳利化／紋理觀感一致。多了 A/B 對照、縮圖格的已編輯徽章與篩選、「還原成原圖」與「取回上一份」。介面改成無彩灰階、只有照片有顏色。

## 前提（Premises）
- P1 已驗（`static/app.js:615-637`）：`scheduleSave` 只記 dirty、`flushSave` 送出當下的 `st.image.path`；`openPhoto:598` 換 `st.image` 後還要等 `/api/folder`、`/api/edit` 才 `restore`。
- P2 已驗（`services/photo_library.py:593-637`、`:647-675`）：`set_edit` 換 id 一律重取 Library 快照；`paste_edit(edit=…)` 整份原樣寫入、不重取快照、`fingerprint` 改成 target 的（PL8）。`_answer` 回 `{fingerprint, edit, preset_status}`（PL7，`test_get_set_clear_shapes` 釘 list 順序）。
- P3 已驗（`darkroom/_xmp.py:252-255`、`_coverage.py`）：`<crs:Look>` 一律進 skipped「Look（{name}）」；preset 庫裡 Look 名稱＝`Adobe Monochrome` 的 8 個檔都沒有 `ConvertToGrayscale="True"`（grep 實測）。
- P4 已驗（`darkroom/_render.py:561-578`、`:274`）：Grain sigma 只在長邊 > 2000 才放大、Sharpen 半徑是絕對像素、Texture 以 2500 切頻帶。實測（scratchpad/s1/grain_exp.py，real-landscape 4096 對 1024）：顆粒 std 比 1.34、銳利化差 0.0131、紋理差 0.0044；sigma ∝ L/3000 且振幅 × min(1, L/3000)^0.5 時顆粒比 0.98。
- P5 已驗（`tests/test_layering.py:287-336`）：facade 每個操作都要有 http／cli／mcp 三入口、`FakeDarkroom` 同步、`PHOTO_TOOLS` 順序；`AGENTS.md`、`README.md`、`docs/agent-install.md`、`CLAUDE.md` 寫死「24 個工具」。
- P6 已驗（`tests/test_app_frontend.py:98-118`）：H11 判官只看 `@media` 內的藏法；`PROTECTED` 清單以子字串比對選擇器。
- P7 已驗（`server.py:53-55`、`app.js:922-924`）：`_lenient_int` 用 `isdigit`；`?path=` 直接 `openPhoto`。
- P8 已驗（`tests/_writeguard.py`、`config.local.json` 不進 git）：測試全程掛寫檔守門；worktree 要有 `config.local.json`（或 `LOCALLLMS_ROOT`）與既有 `__pycache__` 才能跑。
- P9 不入條文：Bahnschrift／Segoe UI Variable 在其他機器上是否存在（字型只列 fallback，不下載）。

## 可斷言條文
### 資料不被蓋掉（最優先）
- [ ] S1：自動存檔送出的 `path` 與 body 一律是「排程當下」那張照片的（`scheduleSave` 時一起記下）；`openPhoto` 在換掉 `st.image` 之前先 `flushSave` 並清空排程；從換掉 `st.image` 到 `loadEdit` 的 `restore` 完成之間，任何 dispatch 都不排程存檔；`restore`／`loadEdit` 只套用 `st.image.path === path` 的回應；`openPhoto` 採最新一次優先（舊的 `/api/open` 回應丟掉）。釘死：`test_autosave_targets_the_photo_it_was_scheduled_for`（結構）＋ `tests/js` 的 `L.editRequest`。
- [ ] S2（修訂 PL4 的 App 行為；PL4 後端規則不變）：前端對開啟中的照片記住每個 preset id 的快照（來自 `GET /api/edit`、`PUT /api/edit`、貼上後重讀的 `edit.preset`）；自動存檔時 `ed.presetId` 有記住的快照 → 走 `POST /api/edit/paste {targets:[path], edit}`（快照原樣）再 `GET /api/edit` 刷新，否則走 `PUT /api/edit`。效果：換 preset 再換回、Ctrl+Z、preset 為 `changed`／`missing` 都保住舊快照；`missing` 時存檔不得回 not_found。釘死：`tests/js` `L.editRequest`、`test_autosave_uses_remembered_snapshot`（aiohttp：改 preset 檔後 App 的存檔路徑結果＝舊快照）。
- [ ] S3（修訂 PLP9 還原條文）：還原的編輯有 preset 時，滑桿基準值與曲線小圖取自快照 `edit.preset.params`（不是 `GET /api/presets/{id}` 的現值）；preset 不在庫裡（404）時不得拋 TypeError，名稱用快照的 `name`，提示列、滑桿欄、強度、樹一樣重繪。釘死：`tests/js` `L.detailFromSnapshot`、`test_restore_uses_snapshot_values`（結構：`loadPreset` 的名稱與 values 來源）。
- [ ] S4（新操作，facade 第 25 個，修訂 PL6／PL7／PL10）：`restore_edit(path)` ｜ `POST /api/edit/restore {path}` ｜ `edit restore <photo>` ｜ `darkroom_edit_restore`（annotations 同 edit_set）。清除編輯（`clear_edit`、或 `set_edit` 什麼都不給）前，把原編輯原樣寫到 `edits/{fp[0:2]}/{fp}.prev.json`（原子寫入；每個指紋只留最近一份；取回後保留）；`restore_edit` 把它寫回編輯檔並回 `_answer`；沒有 → not_found（常數）。`get_edit`／`set_edit`／`clear_edit`／`restore_edit` 的回應恰為 `{"fingerprint","edit","preset_status","previous"}`（`previous`＝該指紋有無 `.prev.json`，bool）。除了這一條，`edits/` 的檔不刪不改名（PL10 照舊）。釘死：`test_restore_previous_edit`（clear→restore 內容逐位元組相同、paste 不建 prev、set 換 preset 不建 prev、無 prev 的 not_found 句）、`test_operation_coverage`、`FakeDarkroom`、parity 的 photo library 情境加 restore。
### 核心渲染（修訂 CONTRACT-core-library；補丁 K3、K4 記在該合約）
- [ ] S5（K3）：`<crs:Look>` 的 `Name` 符合「黑白 Look 判準」（常數）時，`values["ConvertToGrayscale"]=True`（已是 True 不變），skipped 項改記「Look（{name}，已以黑白近似）」（常數）；其他 Look 照舊「Look（{name}）」。`skips.level` 把「已以黑白近似」判為 minor，`label`＝「描述檔外觀（{name}，已以黑白近似）」。釘死：`test_monochrome_look_renders_gray`（合成 xmp 無 ConvertToGrayscale、Look=Adobe Monochrome → render 每像素 R=G=B 差 ≤ 1e-4；Look=Adobe Color → 不是）、`test_library_monochrome_looks`（使用者庫 Look 符合判準的恰 8 個，全部 ConvertToGrayscale True、flag 為 minor 而非 major）。
- [ ] S6（K4）：Grain、Sharpness、Texture 以影像長邊 L 對 `REF_LONG_EDGE=3000` 的比例縮放：Sharpen 高斯 sigma＝`max(0.3, SharpenRadius × L/3000)`；Grain sigma＝`max(0.3, (0.3+1.5×GrainSize/100) × L/3000)`、振幅係數 `0.12 × min(1, L/3000)^0.5`；Texture 頻帶＝`(2+s, 3+s)`、`s=round(log2(L/3000))`、下限 (1,2)。釘死 `test_detail_effects_scale_with_size`（real-landscape-4096 對其 1/4 area 縮圖：只開 Grain 60 → 兩者對原圖差的 std 比在 0.8～1.25；只開 Sharpness 100／Radius 1.5 → `mean|down(big)−direct|` ≤ 0.008；只開 Texture ±60 → ≤ 0.006）；A8（強度 0 恆等）、A17、A19 不變。
### 新功能
- [ ] S7（A/B 對照）：預覽工具列 `[按住看原圖｜對照]` 一組；`#ab-btn`（`aria-pressed`）、快捷鍵 `Y`（焦點不在輸入框、無修飾鍵）；原圖 `<img id="ab-orig">` 疊在 `#preview-img` 同一矩形、`clip-path: inset(0 calc(100% - var(--split)) 0 0)`；左原圖、右編輯後，角落標籤「原圖」「編輯後」；拖 `#ab-divider` 期間不得發出任何 `/api/preview` 請求；雙擊把手回 50%；`#ab-handle` `role=slider`、`aria-valuenow`、←→ 1%、Shift 10%、Home/End；split 記 `sessionStorage`（鍵 `darkroom.abSplit`）；不進 `L.reduce`、不進復原歷史；`\` 仍整張換原圖；換照片後原圖重抓。釘死：`tests/js` `L.abStep`、`test_ab_compare_structure`、瀏覽器量測（拖動期間 preview 請求數 0；截圖）。
- [ ] S8（已編輯徽章）：`GET /api/thumbnail` 有編輯時多一個標頭 `X-Edit`＝`encodeURIComponent(JSON)`（`{"preset":name|null,"strength":n,"status":"current"|"changed"|"missing"|null}`），沒編輯時沒有這個標頭；CLI／MCP 的 thumbnail 結果形狀不變。縮圖右下角 `.mark`：`.edited` 實心琥珀點；`status` 為 changed／missing 時加 `.stale`（空心環）；格子 `title`＝「{preset 名或「只有微調」}　{strength}%」加「（preset 已變更）」／「（preset 已不在庫裡）」。釘死：`test_thumbnail_edit_header`（三種狀態、沒編輯無標頭、名稱含中文可還原）、`test_grid_badge_structure`。
- [ ] S9（篩選）：縮圖格上方 `#grid-filter`（三顆 `aria-pressed` 鈕：全部／已編輯／未編輯）；切換時重新 `GET /api/folder/thumbnails`，已編輯＝`edited===true`、未編輯＝`edited===false`、`null` 只在「全部」出現；`#grid-count` 的 m＝顯示的張數；`null` 張數 >0 且非「全部」時 `#grid-pending` 顯示「還有 {k} 張尚未判定」（常數）；選取只在顯示的格子裡。釘死：`tests/js` `L.gridFilter`、`test_grid_filter_structure`。
- [ ] S10（還原成原圖／取回上一份，三入口）：編輯器 `#reset-original-btn`（reducer 動作 `resetToOriginal`：preset null、微調清空、一步歷史，Ctrl+Z 拿回；存檔後 `previous` 為 true）；`#restore-previous-btn` 只在 `st.edit` 為 null 且 `previous` 為 true 時可用，按下走 `POST /api/edit/restore` 並以 restore 流程還原；縮圖格 `#grid-reset-original-btn`／`#grid-restore-btn` 對選取逐張 `DELETE /api/edit`／`POST /api/edit/restore`，先 `confirm`（常數），結果句（常數）＋失敗逐筆列在結果面板。釘死：`tests/js`（reducer、句子）、`test_reset_original_structure`。
### 審查必修（前端）
- [ ] S11（沿用 vs 已存；修訂 R5「換照片提示」）：`#carry-hint` 只在「已開照片、`st.edit` 為 null、且有 preset 或微調」時顯示，文字與 title＝常數「沿用提示」；有編輯時不顯示。按「匯出」時若處於沿用狀態，先把目前設定存成這張的編輯（`PUT`，成功後 `st.edit` 非 null）再匯出。釘死：`tests/js` `L.carryHintVisible(ed, hasImage, hasEdit)`、`test_photo_switch_hint`（新句）、`test_export_commits_carried_state`。
- [ ] S12（略過提示可完整閱讀；R4 工具列一行不變）：`#skip-banner`／`#skip-note` 可點，開啟覆蓋在預覽上方的 `#skip-detail`（`role=dialog`、可換行、Esc 或再點關閉），內容＝完整 banner＋note；開關時 `#preview` 的位置與大小不變（`test_banner_does_not_move_preview` 照舊）。釘死：`test_skip_detail_structure`。
- [ ] S13（前端雜項，各自釘死）：(a) 匯出所選進行中 `#export-selected-btn` disabled、文字＝`L.EXPORT_BUSY`，連點不得發第二個 `/api/export`；(b) 貼上／匯出所選／還原／取回的單筆 `error` 逐筆列進 `#grid-result`（沿用 `.import-result` 樣式），摘要 toast 不得蓋掉原因；(c) ←／→ 在 `select`／`textarea`／`input` 焦點時不換照片、`e.repeat` 不連發；(d) `window` `blur`／`visibilitychange` 隱藏時 `st.holding` 歸 false 並復原畫面；(e) `renderGrid` 重建前對舊格子 `revokeObjectURL`＋`unobserve`，`img.onload` 後即 revoke；(f) `showGrid(true)` 只在 `st.grid.folder` 為 null 時改用目前照片的資料夾；(g) `beforeunload` 時不等在途 promise，直接以 keepalive 再送一筆最新 body；`sendSave` 失敗 → `save.dirty=true`、退避 2 秒重排一次；(h) `pasteEdit` 在 `confirm` 之前 `await flushSave()`；(i) 開檔失敗：`st.image=null`、預覽清空（`#preview-img` hidden、`#preview-empty` 顯示失敗原因）、位置列回「尚未開啟照片」；(j) 空資料夾：`#grid-cells` 顯示常數「空資料夾提示」；(k) `#grid-count` `white-space: nowrap`（820 寬量測不換行）；(l) `index.html` `<link rel="icon" href="/static/logo.svg">`，`static/logo.svg` 與 `docs/assets/logo.svg` 位元組相同。
- [ ] S14（錯誤句中文化，只在顯示層）：`L.explain(msg)` 對「英文原句對照表」（常數）逐字比對（含 `{…}` 佔位的前綴式）回中文，其餘原樣；toast／狀態列／開檔失敗都經它顯示，`title` 放原句；三入口的 service 句子（L3／PL 常數）一個位元組都不改。釘死：`tests/js` `L.explain`、`test_toasts_go_through_explain`（結構：`toast(` 的參數經 `L.explain`）。
### 伺服器小修
- [ ] S15：`_lenient_int` 改 `isdecimal`（`²`、`①` 回原字串 → service 的 400 句，不再 500）；`?path=` 只填進 `#photo-path`、不自動開啟（`lastPath` 還原照舊；`?path=` 有值時優先填入但不開）。釘死：`test_lenient_int_unicode_digits`、`test_query_path_not_auto_opened`（結構）。
### 介面質感（R6／H11 照舊；常數句另見 Verbatim）
- [ ] S16：`:root` 色票恰為常數表；介面無彩（除 `--tweak`、`--clamp`、`--err`、`--ok` 四個語意色與 HSL 色相點外，`app.css` 不得出現其他彩色色碼：`#rgb`／`#rrggbb` 須 R=G=B）；選取／開啟中用白（`.tnode.preset.active` 白 7% 底＋2px 白左緣；`button.on`／`[aria-pressed="true"]` 白底黑字）；藍色 `#4a9eff`、`#2f6fbf`、`#29466b` 不得出現。釘死：`test_css_palette_is_neutral`。
- [ ] S17：`input[type=range]` 自繪（`appearance:none`、2px 軌道、10px 把手），`updateRow`／`renderStrength` 寫入 `--base`、`--lo`、`--hi`（preset 落點、差值段）；`.sl.bipolar`（min<0<max）畫中點刻度；夾值用 `.sl.clamped` 方形把手＋端蓋；強度列有 0／100／200 刻度數字與 100% 長刻度、>100% 半段較亮、讀數 22px；HSL 色相列標籤前 6px 色點；數字用 `--num` 字型（常數）＋`tabular-nums`；`#preview-img` 永遠不加 `transition`；`prefers-reduced-motion` 全關；`#preview-img[hidden]{display:none}`；預覽底色 `body[data-canvas="dark"|"black"|"mid"]` 三段、`.canvas-pick` 三鈕、記 `localStorage` 鍵 `darkroom.canvas`；樹列 `.fav`／`.row-menu` 平常 `opacity:.35`（不在 media query 內）、hover／`focus-within`／已最愛 1；上方列 `.seg` 分組、Unicode 圖示換行內 SVG（`#toggle-lib #toggle-sl #undo #redo #prev #next` 與 `.btn-icon`）；狀態列「● 已更新」毫秒在 title。釘死：`tests/js` `L.sliderVars`、`test_slider_vars_structure`、瀏覽器截圖（1600 編輯器、A/B、縮圖格、820）。
- [ ] S18（窄視窗不准藏，修訂 R6／PLP9 清單）：`PROTECTED` 與 `index.html` 的 `hidden` 檢查加入 `#ab-btn`、`#reset-original-btn`、`#restore-previous-btn`（依狀態由程式 disabled，不用 hidden）、`#grid-filter`、`#grid-reset-original-btn`、`#grid-restore-btn`、`.canvas-pick`；820 寬：`#strength` ≥ 200px、`.pv-wrap` ≥ 400px、以上按鈕全部可見。
- [ ] S19（回歸）：`python -s -m unittest discover -s tests` 結束碼 0；`node --test tests/js/test_logic.cjs` fail 0；preset 合併雜湊仍 `15C015CC0C080FF9`；`AGENTS.md`／`README.md`／`docs/agent-install.md`／`CLAUDE.md` 的工具數改成 25 並列出 `edit restore`／`darkroom_edit_restore`。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 自動存檔的目標照片（S1） | path＝排程當下 | 使用者的編輯 → 上一張的狀態蓋掉新照片存好的編輯，無備份｜不可逆／資料 | `test_autosave_targets_the_photo_it_was_scheduled_for`、`L.editRequest` |
| 快照保留（S2、S3） | paste 帶快照 | 使用者的編輯 → 換回 preset 後顏色悄悄變成新版、滑桿值≠渲染值｜不可逆／資料 | `test_autosave_uses_remembered_snapshot`、`L.detailFromSnapshot` |
| `.prev.json` 與 `previous`（S4） | 常數形狀 | 使用者按錯「還原成原圖」→ 拿不回來｜不可逆／資料 | `test_restore_previous_edit`、parity |
| 黑白 Look（S5） | R=G=B | 使用者的黑白 preset → 匯出是彩色的｜邏輯核心 | `test_monochrome_look_renders_gray`、`test_library_monochrome_looks` |
| 尺度縮放（S6） | 常數公式與門檻 | 使用者看到的預覽 → 匯出比畫面軟、顆粒粗細不同｜邏輯核心 | `test_detail_effects_scale_with_size` |
| 三入口 restore（S4） | 同一句、同形狀 | 代理 → 三入口說法不同｜上下游契約 | `test_operation_coverage`、`test_photo_library_parity` |
| `X-Edit` 標頭（S8） | encodeURIComponent(JSON) | 前端徽章 → 讀不到就全顯示成未編輯｜上下游契約 | `test_thumbnail_edit_header` |
| 沿用提示、還原確認句、結果句、錯誤中文（S10、S11、S14） | 常數 | 使用者 → 以為已存其實沒存、不知道還原影響幾張｜UI/UX | `test_photo_switch_hint`、`tests/js` 句子測試 |
| 窄視窗按鈕（S18） | H11 清單 | 使用者 → 窄視窗找不到對照／還原／篩選｜UI/UX | `test_narrow_windows_keep_function_buttons`、`test_layout_820` |

## Verbatim Constants
```text
restore_edit(path) ｜ POST /api/edit/restore ｜ edit restore <photo> ｜ darkroom_edit_restore ｜ 第 25 個操作，接在 save_edit_as_preset 之後
上一份編輯檔：edits/{fp[0:2]}/{fp}.prev.json ｜ 回應鍵順序：fingerprint, edit, preset_status, previous
not_found（S4）：這張照片沒有上一份編輯可以取回：{file_name}
黑白 Look 判準（S5，對 Look 的 Name，不分大小寫）：regex  monochrome|black\s*(?:&|and)\s*white|\bb&w\b
黑白 Look 略過項（S5）：Look（{name}，已以黑白近似） ｜ label：描述檔外觀（{name}，已以黑白近似） ｜ level：minor
REF_LONG_EDGE = 3000 ｜ Sharpen sigma = max(0.3, SharpenRadius × L/3000) ｜ Grain sigma = max(0.3, (0.3 + 1.5×GrainSize/100) × L/3000)
Grain 振幅 = 0.12 × GrainAmount/100 × min(1, L/3000)^0.5 × wt ｜ Texture 頻帶 = (2+s, 3+s)，s = round(log2(L/3000))，下限 (1, 2)
S6 門檻（4096 對 1024）：Grain std 比 0.8～1.25 ｜ Sharpen mean|Δ| ≤ 0.008 ｜ Texture mean|Δ| ≤ 0.006
X-Edit：encodeURIComponent(JSON.stringify({"preset": name|null, "strength": n, "status": "current"|"changed"|"missing"|null}))
徽章 title：{preset 名｜只有微調}　{strength}% ｜ 後綴：（preset 已變更）／（preset 已不在庫裡）
篩選鈕：全部／已編輯／未編輯 ｜ 尚未判定：還有 {k} 張尚未判定 ｜ 空資料夾提示：這個資料夾沒有支援的照片（JPEG／PNG／TIFF／HEIC）
沿用提示（S11，取代 R5「目前修改尚未儲存，切換照片會沿用」）：沿用上一張的設定（還不是這張的編輯，會再沿用到下一張） ｜ 圖示版：沿用中
還原確認（grid）：要把 {n} 張照片還原成原圖嗎？（可用「取回上一份」拿回來） ｜ 還原結果：已還原 {ok} 張，失敗 {failed} 張 ｜ 取回結果：已取回 {ok} 張，失敗 {failed} 張
單張還原 toast：已還原成原圖（Ctrl+Z 可拿回） ｜ 取回 toast：已取回上一份編輯
A/B：按鈕文字「對照」 ｜ 標籤「原圖」「編輯後」 ｜ 快捷鍵 Y ｜ sessionStorage 鍵 darkroom.abSplit ｜ 預設 split 0.5
英文原句對照表（S14，前綴式以「{…}」結尾者取其後為 {x}）：
  path is required → 請輸入照片路徑
  photo not found: {x} → 找不到照片：{x}
  unsupported photo format (JPEG/PNG/TIFF/HEIC) → 不支援的照片格式（只接受 JPEG／PNG／TIFF／HEIC）
  unknown image_id → 照片已不在記憶體裡，請重新開啟
  unknown preset {x} → 找不到 preset：{x}
  unknown or unsupported preset {x} → 找不到或不支援的 preset：{x}
  strength must be a number in 0..200 → 強度要在 0～200 之間
  strength must be within 0..200, got {x} → 強度要在 0～200 之間：{x}
  unknown slider key {x} → 未知的滑桿：{x}
  body must be JSON → 請求格式錯誤（不是 JSON）
  request refused: {x} → 伺服器拒絕了這個請求：{x}
色票（:root）：--bg0 #121212 ｜ --bg1 #191919 ｜ --bg2 #202020 ｜ --bg3 #2a2a2a ｜ --line rgba(255,255,255,.07) ｜ --line-2 rgba(255,255,255,.12)
  --text #e6e6e6 ｜ --text-2 #a9a9a9 ｜ --text-3 #8a8a8a ｜ --tweak #d9a85b ｜ --clamp #d27a7a ｜ --err #e06b6b ｜ --ok #8fbf93
  預覽底色：dark #151515 ｜ black #000000 ｜ mid #4a4a4a ｜ localStorage 鍵 darkroom.canvas
字型：--font "Segoe UI Variable Text","Segoe UI","Noto Sans TC","Microsoft JhengHei UI",system-ui,sans-serif ｜ --num "Bahnschrift","Segoe UI Variable Small","Segoe UI",system-ui,sans-serif（font-stretch 87.5%）
字級：11／12／13／14 ｜ 強度讀數 22px ｜ 動效 120ms（只回應操作）
滑桿 CSS 變數：--base（preset 落點 %）、--lo／--hi（差值段兩端 %），百分比＝(v−min)/(max−min)×100，兩位小數
```

## 修訂既有合約的條文（本合約生效後以此為準）
- CONTRACT-app-shell：R5「換照片提示」常數與顯示條件 → S11；R6／H11 不准藏清單 → S18；`?path=` 不再自動開啟（S15）。
- CONTRACT-photo-library：PL4 的 App 端行為 → S2；PL6／PL7／PL10 → S4（第 25 個操作、`previous` 鍵、`.prev.json`）；PLP9 還原與清單 → S3、S9、S18；`X-Edit` 標頭（S8）為 HTTP 專用資訊，CLI／MCP 形狀不變。
- CONTRACT-core-library：補丁 K3（S5）、K4（S6）；A13 的 skipped 規則對黑白 Look 改記近似項。
- 不在 S1（記錄，不修）：review findings [0] preset 庫根落在照片資料夾、[1] PLP1 祖先規則、[2] CLI thumbnails 背景工作、[3] data_dir 啟動偵測、[11]～[17] 匯出於 preset 資料夾內、相對 --data-dir、壞 config、入口結束碼、rebuild body、註解、paste NaN 驗值。
