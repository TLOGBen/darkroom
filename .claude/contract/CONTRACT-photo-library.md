# CONTRACT — darkroom 照片庫（最小版：縮圖格、自動存編輯、複製／貼上編輯、匯出所選）
<!-- 此處採預設：合約未經人工確認即釘死（2026-10-09 工作流程派工；決定由主 session 做完，不問使用者） -->

## 目標
App 多一個縮圖格看照片資料夾；每張照片的編輯（preset 快照＋強度＋微調）自動存進照片庫（App 資料區，以照片指紋對應），重開照片時 preset、強度滑桿、微調原樣回來；可把一張的編輯貼到選取的多張、選取多張一起匯出。照片資料夾一個位元組、一個檔名都不變。三個入口（HTTP／CLI／MCP）都能讀寫清除編輯、貼上、取縮圖，結果與錯誤句相同。

## 前提（Premises）
- Q1 已驗（ADR-0002、`CONTEXT.md`「照片與編輯」）：編輯存 App 資料區、以內容指紋對應；同內容共用一份；內容變了＝新照片、舊編輯保留；編輯含 preset 調色參數快照。地圖 Decisions 寫的「`darkroom-params/1` 參數檔」由本合約改為 `darkroom-edit/1` 編輯檔（內含 `darkroom-params/1` 快照）。
- Q2 已驗（`darkroom/_params.py:85` `Params.to_dict`／`from_dict`，schema 不符拋 `ValueError`；`darkroom_app/presets.py` `Library.params` 只放支援的 preset）。
- Q3 已驗（`server.py:116` `folder_listing`：`engine.PHOTO_EXT`、`(casefold, name)` 排序、只列檔案；`engine.py:80` `Engine.open` 用 `read_image` 讀全解析度 float32）→ 縮圖不能走這條路。
- Q4 已驗（`CONTRACT-export.md` XP1／XP5：facade 已有 8 個操作、寫檔白名單恰 `services/export.py` 1 項；`CONTRACT-layering.md` L14 把 `resolve_params` 列為待決，本合約 PL5 結案）。
- Q5 未驗、不入條文為事實：cv2 `IMREAD_REDUCED_*` 對 PNG／TIFF 是否省解碼；pillow-heif `thumbnails` 是否已套 irot／imir；相機內嵌 EXIF 縮圖是否帶黑邊。條文一律以結果（方向、比例、開檔次數）斷言。
- Q6 推估、非本 repo 量測（效能數字的理由）：12MP JPEG 以 1/8 縮小解碼約 10～25 ms／張；hashlib SHA-256（OpenSSL）單執行緒 ≥ 1 GB/s；4 MB 檔在 OS 快取中讀取 < 3 ms。

## 可斷言條文
- [ ] PL1（資料區）：`config.data_dir(config_file=None, env=None)`：`config.local.json` 鍵 `data_dir` 優先，否則 `%LOCALAPPDATA%/darkroom`；兩者都沒有 → `ConfigError`（常數）。`build_facade(..., data_dir=None)` 可注入；CLI 與 MCP 加全域選項 `--data-dir D`。照片庫只寫 data_dir 底下 `edits/`、`thumbs/`、`index/`（不存在才建立）。測試一律注入暫存 data_dir；`test_tests_never_touch_real_data_dir`：全套跑完，真的 `%LOCALAPPDATA%/darkroom` 不出現或內容與檔名清單不變。
- [ ] PL2（照片指紋）：＝原檔全部位元組的 SHA-256 小寫 hex（64 字），不得混入路徑、檔名、mtime；搬移／改名後相同，改一個位元組後不同。`open_photo` 與每個編輯操作都對原檔重算；只有縮圖格的 `fingerprint`／`edited` 與快取命中可以用 `index/` 的（正規化絕對路徑, size, mtime_ns）→ 指紋索引，任一項變了就重算。`open_photo` 回應形狀不變（L8 golden 不動）。
- [ ] PL3（編輯檔）：`edits/{fp[0:2]}/{fp}.json`，UTF-8、`ensure_ascii=False`，內容恰為常數的鍵與順序；`strength` 0～200、`overrides` 為 `validate_overrides` 的結果。寫入＝同資料夾暫存檔 → `os.replace`；任何失敗後不得留下半份編輯或暫存檔。`preset` 為 null 且 `overrides` 空＝沒有編輯：`set_edit` 刪掉該檔、回 `edit:null`。
- [ ] PL4（快照）：`set_edit` 選某 preset 時快照取自當下 `Library.params[id].to_dict()`；同一指紋再 set 同一個 preset id → 沿用原快照（不重讀）；換 id 才重取。之後 preset 檔改了或移走都不改已存的編輯。`preset_status`＝`"current"`（快照等於 Library 現值）／`"changed"`／`"missing"`／null（沒有 preset）。
- [ ] PL5（`resolve_params`）：預覽與匯出的 preset 基底一律由 service 的單一函式 `resolve_params(fingerprint, preset_id)` 決定：該指紋有編輯且快照 id＝preset_id → 用快照（Library 沒有這個 preset 也照用）；否則用 `Library.params`，沒有 → 照舊 not_found「unknown or unsupported preset {pid}」。之後才是既有 `validate_*`／`effective_params`（X2 等式照舊）。禁止第二份解析規則；export 的 `path` item 也走它。
- [ ] PL6（facade 新增 6 個操作，第 9～14 個，依常數順序）：每個都要有 service 方法、`DarkroomFacade` 一行 `return`、`OPERATIONS` 項、HTTP 路由、CLI 子指令（接受 `--json`，信封同 L9）、MCP 工具（常數）；`FakeDarkroom` 同步；`test_operation_coverage` 照 L2。controller 不得呼叫 `hashlib`、`os.replace` 或讀寫 data_dir（L13 掃描加這三項）。
- [ ] PL7（編輯操作規則）：路徑檢查順序與句子同 L3 open_photo；`set_edit` 依序：路徑 → preset（PL5 的 not_found）→ `validate_strength` → `validate_overrides`（原樣 `str(e)`）。get／set／clear 都回 `{"fingerprint","edit","preset_status"}`；`clear_edit` 沒有編輯也成功（冪等）。
- [ ] PL8（貼上）：`source`（照片路徑）與 `edit`（`darkroom-edit/1` 物件）恰給一個，否則 invalid；`source` 沒有編輯 → not_found；`edit` 不合 PL3 或 `params` 不能 `Params.from_dict` → invalid；`targets` 須為 1～500 個字串，否則 invalid（句子皆見常數）。每個 target 各自處理，回 `{"results":[{"ok":true,"target":檔名}|{"ok":false,"target":檔名,"error":句子}]}`，同長同序、一筆失敗不影響其他筆、整體仍成功（同 XP2）。貼上＝target 的編輯整份換成來源那份（快照、強度、微調原樣，`fingerprint` 改成 target 的），不重取快照。
- [ ] PL9（版本守門）：既有編輯檔 `schema` 不是 `darkroom-edit/1` → 該張 conflict（HTTP 409／CLI 4／MCP isError），不覆寫、不刪；JSON 壞掉 → unavailable（503／5），同樣不覆寫；data_dir 無法建立或寫入 → unavailable。paste 時這些是單筆 `ok:false`（同句）。本片首次產生 conflict／unavailable，照 L7 對照。
- [ ] PL10（舊編輯保留）：除了 `clear_edit` 與 PL3「空編輯」刪掉自己那個指紋的檔之外，沒有任何路徑刪除、改名 `edits/` 的檔；照片內容被改過（新指紋）後，舊指紋的編輯檔位元組不變。本片不做清理。
- [ ] PL11（縮圖產生）：長邊 256 px、等比例、顯示方向的 JPEG q80，存 `thumbs/{fp[0:2]}/{fp}.jpg`（同內容共用）。來源依序：(1) 內嵌縮圖（JPEG／TIFF 的 EXIF IFD1、HEIC 的 pillow-heif thumbnails），只有轉正後長邊 ≥ 160 且長寬比與原圖相差 ≤ 1% 才用；(2) JPEG 用 `IMREAD_REDUCED_COLOR_{2,4,8}` 中縮小後長邊仍 ≥ 256 的最大倍率；(3) 其他情況才完整解碼（HEIC 解成 8-bit）。每張照片的位元組只讀一次（同一份 bytes 算指紋與解碼）。禁止：`Engine.open`、`read_image`、torch、`darkroom-gpu` executor、保留全解析度 float32、寫進照片資料夾。失敗 → invalid「縮圖產生失敗」句型，前端顯示佔位格與檔名。
- [ ] PL12（排程）：縮圖工作在獨立執行緒池（`max(1, min(4, os.cpu_count()//2))` 個，前綴常數）；`folder_thumbnails` 呼叫後在背景依排序預產整個資料夾；`thumbnail(path)` 的直接請求插隊最前；換資料夾時丟掉前一個資料夾還沒開始的工作。縮圖產生期間 B7 預覽延遲照樣要過（`bench_preview.py --with-thumbnails`）。
- [ ] PL13（清單與單張）：`folder_thumbnails` 回 `{"folder","items":[{"name","path","fingerprint","edited","cached"}],"total","next_offset"}`；資料夾不存在 → not_found（常數）；清單＝`folder_listing` 那一份規則（禁止第三份副檔名表或第二套排序）；offset／limit 規則與句子同 L4，MCP 預設 limit 50；索引沒有時 `fingerprint`／`edited` 為 null（清單本身不讀照片內容）。`thumbnail` 回 JPEG＋`{fingerprint, edited, width, height}`：HTTP `image/jpeg`＋`X-Fingerprint`、`X-Edited`（`0`／`1`）、`Cache-Control: no-store`；CLI 同 L9 preview 的位元組／TTY 規則；MCP 回 image content＋structuredContent。
- [ ] PL14（照片資料夾唯讀，修訂 XP5）：縮圖格、產生全部縮圖、get／set／clear／paste 編輯跑完後，照片資料夾每個檔的 SHA-256 與遞迴檔名清單不變、不多任何檔或資料夾（`test_photo_folder_untouched`，三個入口都跑；匯出情境照 XP5）。寫檔白名單改為恰 2 項（常數）；`services/library.py` 的每次寫入都落在 data_dir 底下（執行期監看寫入模式 `open`、`os.replace`、`os.makedirs`、`os.remove`）。preset 合併雜湊仍為 `15C015CC0C080FF9`。
- [ ] PL15（App 前端）：工具列加「縮圖格」切換鈕（`#grid` ↔ 編輯器，加入 R6／H11 窄視窗不得藏掉清單）；只先請求看得到的縮圖；有編輯的格加 `.edited`；點＝單選、Ctrl＝加減選、Shift＝範圍選；雙擊或 Enter 開進編輯器。編輯器任何變動（點 preset、強度、微調、單項還原）停 500 ms 後 `set_edit`（最新一次優先、不累積）；切換照片前先送出未送的那筆。開照片後先 `get_edit`：有編輯 → preset 選取、強度滑桿、全部微調與 `.adjusted` 照編輯還原，再出第一張預覽；沒有 → 照今天預設。禁止：還原過程本身觸發 `set_edit`；`get_edit` 失敗時自動存檔（會用預設值蓋掉編輯）。`preset_status` 為 changed／missing 時工具列顯示常數提示。「複製編輯」把 `get_edit` 回的那份物件存進前端剪貼簿（沒編輯時停用）；「貼上編輯」在剪貼簿有內容且有選取時啟用，先跳確認（常數）再 `paste_edit(edit=…)`，完成後更新標記、目前照片在 targets 裡就重新載入。「匯出所選」用選取照片各自的編輯組 export items（path＋preset id＋strength＋overrides，PL5 保證用快照），完成後顯示常數摘要。
- [ ] PL16（效能，ADR-0003；`tools/bench_library.py`，程式產生照片、暫存 data_dir）：(a) 500 張 4000×3000 JPEG q90、無內嵌縮圖、縮圖快取空：從 `folder_thumbnails` 呼叫起，前 40 張（第一屏）都可取得 ≤ 1.5 秒，500 張全進快取 ≤ 15 秒；(b) 快取已滿：`folder_thumbnails`（不設 limit）≤ 0.3 秒，500 張 `thumbnail` 全取完 ≤ 2 秒且照片資料夾的檔被開啟 0 次；(c) 50 張 4000×3000 HEIC、無內嵌縮圖：第一屏 ≤ 4 秒、全部 ≤ 12 秒；(d) 指紋：2 GB 已在 OS 快取的檔，單執行緒 ≥ 600 MB/s；約 10 MB 照片的 `open_photo` 因指紋多出 ≤ 30 ms。「冷」只指縮圖快取空，OS 檔案快取不控制、印出狀態。理由（Q6）：(a) 500×25 ms÷4 執行緒≈3 秒，15 秒留給 SATA 冷讀（2 GB÷0.5 GB/s≈4 秒）與 5 倍餘裕；第一屏 40 張≈0.25 秒＋清單；(d) 取 OpenSSL 下限的 6 成。量測前照 App 外殼補丁 R1（B7 (a)(b)(c)）判斷 GPU 忙碌，忙碌才跳過並印出原因、不得默默通過；`--force` 強制量測。達不到 → 先 profile（讀檔／指紋／解碼／編碼／寫檔分段）並記進本合約，不放寬門檻（放寬須使用者同意）；只有 profile 證明熱點是無法向量化、也沒有現成 C 函式庫可用的純 Python 迴圈時，才另開切片用 Rust（pyo3＋maturin）換掉那一段。本片不用 Rust、不加依賴。
- [ ] PL17（三入口一致性，加入 `tests/test_interface_parity.py`）：每個 driver 各用自己的暫存 data_dir 與照片資料夾複本。情境至少：get_edit 檔案不存在、`.txt`、沒有編輯；set_edit 強度 250、未知滑桿鍵、未知 preset、成功後 get 相等、空編輯變 null；clear 冪等；paste source 與 edit 都給、source 沒編輯、targets 空、兩筆一好一壞；`darkroom-edit/9` 編輯檔（conflict）、壞 JSON（unavailable）；folder_thumbnails 不存在、limit 0、成功（items 相同）；thumbnail 壞 JPEG、成功（寬高與 fingerprint 相同）。subprocess 冒煙：CLI `edit set` → `edit get --json`；MCP `darkroom_edit_get`。
- [ ] PL18（回歸與範圍）：既有測試照 L12；`python -s -m unittest discover -s tests` 結束碼 0；測試只用程式產生的照片（含方向 6＋EXIF 縮圖的 JPEG、帶黑邊內嵌縮圖的 JPEG、HEIC、PNG）。不做：星等、旗標、收藏集、搜尋、縮圖反映編輯後顏色、快取清理、跨機同步、存成 xmp、跨程序鎖（App 與 MCP 同時寫同一份編輯＝最後寫的贏）。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 照片資料夾（PL11、PL14） | 不寫、不多檔 | 使用者照片與同步資料夾 → 多出檔案被同步到雲端或原檔被改｜不可逆／資料 | `test_photo_folder_untouched`、`test_only_export_and_library_write`、`test_library_writes_under_data_dir` |
| 編輯檔（PL3、PL9、PL10、PL15） | darkroom-edit/1、原子寫入 | 使用者調好的編輯 → 當機、升級、照片被改或還原失敗後被蓋掉｜不可逆／資料 | `test_edit_atomic_write`、`test_edit_future_schema_not_overwritten`、`test_old_edit_kept_after_content_change`、`tests/js` 還原不觸發存檔 |
| 快照與解析（PL4、PL5） | 單一 `resolve_params` | 使用者成品 → preset 改了後重開或匯出顏色跟當初不同｜邏輯核心 | `test_snapshot_survives_preset_change`、`test_export_uses_snapshot`、`test_preview_uses_snapshot` |
| 指紋（PL2） | SHA-256 hex | 編輯 → 對到別張照片，或搬移後找不到｜邏輯核心 | `test_fingerprint_content_only`、`test_open_rehashes_after_change` |
| 三入口結果（PL6～PL9、PL13、PL17） | 常數句、L7 對照 | 代理 → 三入口說法不同，或把 conflict 當成功繼續覆寫｜上下游契約 | `test_interface_parity`、`test_operation_coverage`、`test_mcp_library_annotations` |
| 縮圖與效能（PL11、PL12、PL16） | 數字、不上 GPU | 使用者 → 500 張資料夾等半分鐘、拖滑桿卡頓｜穩定性可靠性 | `bench_library.py`、`test_thumbs_not_on_gpu_executor`、`test_warm_grid_opens_no_photo` |
| 縮圖外觀（PL11） | 顯示方向、無黑邊 | 使用者挑照片 → 直拍躺著或帶黑邊，挑錯張｜UI/UX | `test_thumb_orientation`、`test_thumb_rejects_letterboxed_exif` |
| 前端句子（PL15） | 常數 | 使用者 → 不知道貼上會取代誰的編輯｜UI/UX | `tests/js/test_logic.cjs` 照片庫訊息 |

## Verbatim Constants
```text
編輯檔 schema：darkroom-edit/1 ｜ 鍵與順序：{"schema","fingerprint","preset":null|{"id","name","group","params"},"strength","overrides"}
資料區：config 鍵 data_dir ｜ 預設 %LOCALAPPDATA%/darkroom ｜ 子資料夾 edits/ thumbs/ index/ ｜ edits/{fp[0:2]}/{fp}.json ｜ thumbs/{fp[0:2]}/{fp}.jpg
ConfigError：找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在
操作（第 9～14 個）｜HTTP｜CLI｜MCP：
  get_edit(path) ｜ GET /api/edit?path= ｜ edit get <photo> ｜ darkroom_edit_get
  set_edit(path, preset_id=None, strength=100, overrides=None) ｜ PUT /api/edit ｜ edit set <photo> [--preset ID] [--strength S] [--override KEY=VALUE]… ｜ darkroom_edit_set
  clear_edit(path) ｜ DELETE /api/edit?path= ｜ edit clear <photo> ｜ darkroom_edit_clear
  paste_edit(targets, source=None, edit=None) ｜ POST /api/edit/paste ｜ edit paste --from <photo> <target>… ｜ darkroom_edit_paste
  folder_thumbnails(folder, offset=0, limit=None) ｜ GET /api/folder/thumbnails?folder=&offset=&limit= ｜ thumbnails <folder> [--offset N] [--limit N] ｜ darkroom_folder_thumbnails
  thumbnail(path) ｜ GET /api/thumbnail?path= ｜ thumbnail <photo> ｜ darkroom_thumbnail
MCP annotations：edit_get／folder_thumbnails／thumbnail＝readOnlyHint true ｜ edit_set／edit_clear／edit_paste＝readOnlyHint false、destructiveHint true、idempotentHint true ｜ 全部 openWorldHint false
寫檔白名單（恰 2 項）：darkroom_app/services/export.py ｜ darkroom_app/services/library.py
not_found：這張照片沒有編輯：{file_name} ｜ 找不到照片資料夾：{folder}
invalid：source 與 edit 要恰好給一個 ｜ edit 不是 darkroom-edit/1 編輯：{reason} ｜ targets 要是 1～500 個照片路徑 ｜ 縮圖產生失敗：{file_name}：{reason}
conflict：編輯檔版本不支援：{schema}（{file_name}）
unavailable：照片庫的編輯檔損壞：{edit_file} ｜ 無法寫入照片庫：{data_dir}：{reason}
縮圖：長邊 256 ｜ JPEG q80 ｜ 內嵌縮圖門檻：轉正後長邊 ≥ 160、長寬比差 ≤ 1% ｜ 執行緒前綴 darkroom-thumb ｜ 數量 max(1, min(4, os.cpu_count()//2))
自動存檔：停 500 ms 後送出
前端：preset 已變更，這份編輯用的是當時的 preset 快照 ｜ preset 已不在庫裡，這份編輯用的是當時的 preset 快照
前端：已複製 {source_name} 的編輯 ｜ 要用 {source_name} 的編輯取代 {n} 張照片的編輯嗎？ ｜ 已貼上 {ok} 張，失敗 {failed} 張 ｜ 已匯出 {ok} 張，失敗 {failed} 張
效能：500 JPEG 4000×3000 冷：第一屏 40 張 ≤ 1.5 s、全部 ≤ 15 s ｜ 熱：清單 ≤ 0.3 s、500 張取完 ≤ 2 s、開檔 0 次 ｜ 50 HEIC：第一屏 ≤ 4 s、全部 ≤ 12 s ｜ 指紋 ≥ 600 MB/s、open_photo 多 ≤ 30 ms
```
