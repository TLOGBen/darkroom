# CONTRACT — darkroom preset 庫（索引、群組、最愛、匯入、自存 preset）

## 目標
Preset 庫有一份索引 `library.json`：左欄可看群組樹、最愛、改 preset 顯示名稱、搬群組、建／改群組、匯入 xmp、把目前編輯存成自存 preset。整理只寫索引，買來的 xmp 一個位元都不變；索引刪掉也能從磁碟重建。App、CLI、MCP 同時用也不會掉資料。每個新操作走 ADR-0001 分層：一個 service 方法＋facade＋`OPERATIONS`＋HTTP＋CLI（`--json`）＋MCP。 <!-- 此處採預設：合約未經人工確認即釘死（2026-10-09，由工作流程子代理依指揮部已定決策撰寫） -->

## 前提（Premises）
- P1 已驗（`darkroom_app/presets.py`@eef3a46）：`Library` 只 glob `preset_dir` 第一層 `*.xmp`；id＝檔名 stem；name／group 讀 `crs:Name`／`crs:Group` 的 rdf:Alt；列順序 (group, name, id) casefold。前端 `app.js` `splitGroup` 只在第一個「 - 」切兩層（B9），詳情請求已 `encodeURIComponent(id)`。
- P2 已驗（`tests/_util.py` `presets_hash`、`test_zz_integrity`）：雜湊與 1466 這個數量都只算 `preset_dir` 第一層 `*.xmp`；`config.preset_dir()` 預設 `<localllms_root>/artifact/11_preset/xmp`；實查 `artifact/11_preset` 目前只有 `xmp/`（另有一個 `Index_*.dat`），沒有 `library.json`、`user/`。
- P3 已驗（`darkroom/_xmp.py`）：數字只吃 `^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$`（不收指數）；布林只吃 true／false（不分大小寫）；曲線依 x 排序並夾 0..255；遮罩只收 `What="Correction"`，形狀規則見 `_shape`；DTD 一律拒絕。 另 P4 已驗（`preview.effective_params` → `Params.clamped()`）：`Temperature`／`Tint` 也被夾進 -100..100（不在 UNCLAMPED 排除內），所以最終參數裡的這兩個值沒有意義。
- P5 已驗（2026-10-09 實測，專用 Python）：`Library` 載入真實 1466 個 = 0.96 s；全部 sha256 = 0.09 s（7.7 MB）；150 個群組，最深 3 層（「A - B - C」）；casefold 子字串搜尋 0.85 ms。 另 P6 已驗（2026-10-09 scratchpad 實測）：Windows 上另一個 handle 開著目標檔時 `os.replace` 拋 `PermissionError`（winerror 5），關掉後就成功；`msvcrt` 可用。
- P7 依賴：`CONTRACT-layering.md`（L1～L13）與 `CONTRACT-export.md` 的 L15 補丁先實作完才開工；本合約的 OPERATIONS／driver／錯誤對照都以那兩份為準。 P8 未驗、不入條文：真的 Lightroom 能不能讀回自存 preset（地圖「還看不清楚」的匯出項）。

## 可斷言條文
- [ ] K1（位置，不寫死）：庫根目錄＝`config.local.json` 的 `library_dir`，沒有就是 `dirname(preset_dir)`；索引＝`<根>/library.json`，鎖檔＝`<根>/library.json.lock`，匯入區＝`<根>/import/`，自存區＝`<根>/user/`。禁止：任何新檔寫進 `preset_dir`（含暫存檔）；程式出現 `11_preset`、`C:/Users/` 字面值（config 的預設組路徑除外）。
- [ ] K2（買來的 xmp 只讀）：所有測試與 bench 跑完後真實庫的合併雜湊仍為 `15C015CC0C080FF9`、數量仍 1466；寫入類測試一律用 `tests/_xmpgen.py` 產生的合成庫（`library_dir` 指到暫存資料夾），真實庫只准讀；`import/`、`user/` 裡的既有檔也不改寫、不刪、不改名（本片沒有刪除操作）。
- [ ] K3（只讀不寫）：`list_presets`、`preset_detail`、`preset_flags`、`preset_groups` 不得建立或改寫任何檔案；`library.json` 不存在時索引只在記憶體裡建，第一次「整理類」操作（K6～K10）或 `rebuild_library` 才落檔（`test_read_ops_never_write_index`，對真實庫跑也成立）。
- [ ] K4（索引格式）：UTF-8 無 BOM（讀時接受 BOM）、內容恰為常數「索引 schema」；`presets` 鍵＝id；`file` 是相對庫根目錄、用 `/` 的路徑；`sha256` 小寫 64 hex。id：買來的＝stem（不變，B3 與既有編輯照舊對得上）；匯入的＝`import:{stem}`；自存的＝`user:{stem}`。
- [ ] K5（可重建）：`rebuild_library()` 掃 `preset_dir`、`import/`、`user/` 第一層 `*.xmp`：檔案還在的 id 保留 name／group／favorite（內容變了只更新 sha256）；新檔用 `crs:Name`（空則 stem）與 `crs:Group` 加入；檔案不見的 id 移除；`groups` 只留仍合法的明列群組。回傳 `{added, removed, kept}`（整數）。刪掉 `library.json` 再 rebuild → 跟全新庫逐鍵相同。索引無法解析或 schema 不對 → 先改名成 `library.json.bad-{unix秒}` 保留，再 rebuild，不得直接覆蓋掉。
- [ ] K6（改名）：`rename_preset(preset_id, name)`：name `strip()` 後 1～100 字；只改索引的 name，不動檔案；Params、id、群組不變；同名允許。 K7（搬移）：`move_preset(preset_id, group)`：group 正規化＝用「 - 」切開、每段 strip、再用「 - 」接回；空字串或有空段 → invalid；目標群組不存在就隱含建立。
- [ ] K8（群組）：`create_group(group)`：正規化同 K7；已存在（有 preset 或已明列，casefold 比較）→ conflict；建立的空群組出現在樹裡（count 0）。`rename_group(group, new_name)`：找不到 → not_found；新路徑已存在 → conflict（不合併）；改掉它與所有以「{group} - 」開頭的子路徑（preset 與明列群組都改）。
- [ ] K9（最愛）：`set_favorite(preset_id, favorite)`：favorite 必須是 bool（`1`、`"true"` 都算錯）；冪等。最愛檢視＝`list_presets(..., favorites=True)` 只列 favorite 的；其他規則同 L4。B3 補丁：`GET /api/presets` 每列恰為 `id, group, name, supported, skipped, favorite` 六個欄位（修訂 B3／L4 的五欄，`test_api_presets_shape` 同步改）；`GET /api/presets?favorites=1` 只列最愛。
- [ ] K10（群組樹）：`preset_groups()` 回傳常數「群組樹形狀」；切層規則同 B9（只在第一個「 - 」切）；排序 casefold；頂層 count＝頂層字串相同的全部 preset；子層 count＝group 完全相同的 preset；沒有群組的 preset 只算進 `ungrouped`。
- [ ] K11（匯入）：`import_presets(paths, group=None)`：paths 是非空字串陣列，否則 invalid；資料夾 → 其第一層 `*.xmp`（依檔名排序）。每筆照順序獨立處理，回傳與展開後清單同長同序，每筆恰為 `{"ok":true,"source":檔名,"id":id}` 或 `{"ok":false,"source":檔名,"error":句子}`（重複時多一個 `"duplicate_of":id`）。sha256 與庫裡任何檔（含同一批前面的）相同 → 重複、不複製；不是 `.xmp`、讀不到、`load_preset` 失敗 → 該筆失敗、不複製。成功：位元組原樣複製到 `import/{stem}.xmp`，撞名（不分大小寫）依序 `{stem} (2)`…，用「不存在才建立」開檔；有 group 就照 K7 放進去。來源檔 SHA-256 與修改時間不變。
- [ ] K12（自存 preset）：`save_user_preset(name, group=None, preset_id=None, strength=100, overrides=None)`：驗證順序＝name（K6 規則）→ preset_id（同 L3 的 not_found 句）→ `validate_strength` → `validate_overrides` → 沒選 preset 也沒有微調 → invalid。Params＝`effective_params(lib.get(preset_id) 當下的快照, s, o)`（與預覽同一份函式，禁止另寫公式）；group 預設常數「自存群組」。寫成 `user/{安全檔名}.xmp`（常數規則），撞名同 K11、用「不存在才建立」，永不覆蓋；失敗不留檔（含暫存）。回傳 `{id, name, group, file}`。
- [ ] K13（自存 xmp 內容與往返）：結構＝常數「自存 xmp」：`x:xmpmeta`／`rdf:RDF`／單一 `rdf:Description`，`crs:PresetType="Normal"`、`crs:ProcessVersion="15.4"`、`crs:HasSettings="True"`；數值寫成 crs 屬性，文字滿足 P3 的 regex 且 `float(文字) == 值`（不得出現指數）；`ConvertToGrayscale` 寫 `True`／`False`；曲線寫 `rdf:Seq` 的 `x, y`；遮罩寫回 `crs:MaskGroupBasedCorrections`（`What="Correction"`、`CorrectionAmount`、`CorrectionName`、Local* 屬性、`CorrectionMasks` 的形狀欄位照 `_shape`）；Name／Group 寫 rdf:Alt `x-default`，用 XML 函式庫跳脫。不寫 `Temperature`、`Tint`、`WhiteBalance`（P4）。往返：`load_preset(存出的檔).to_dict()` 的 values（扣掉 Temperature／Tint）、curves、masks 與存入的 Params 完全相等（`==`，不用容差）；skipped 是原 skipped 的子集。案例至少：曲線、線性與放射遮罩、色相鍵、強度 0／150／200、微調夾到上下限、`1e-05` 這類小數、名稱含 `<&"'` 與中文。
- [ ] K14（安全檔名）：`<>:"/\|?*` 與控制字元換成 `_`、去掉結尾的點與空白、Windows 保留名（CON、PRN、AUX、NUL、COM1～9、LPT1～9，不分大小寫）前面加 `_`、空的 → `preset`、最多 80 字。最終路徑的上一層必須就是 `user/`（`..\x`、`a/b` 都不得跑出去）。
- [ ] K15（並發與原子寫）：每個整理類操作：取跨程序互斥鎖（`<根>/library.json.lock`，持有程序死掉就自動釋放，例 `msvcrt.locking`）→ 重讀磁碟上的索引 → 套用 → 寫 `library.json.tmp-{pid}-{亂數}` → `os.replace`。`PermissionError` 重試最多 10 次、共約 1 秒（P6），還失敗 → unavailable；等鎖超過 5 秒 → conflict。讀索引也在同一把鎖下、讀完立刻關檔。任何失敗後不留 tmp 檔。程序內的索引在每次操作前比對 `library.json` 的 (mtime_ns, size)，變了就重讀；別的程序匯入或自存的新檔，下一次 `list_presets` 就列得到（Params 第一次用到時才讀）。測試：App（in-process）＋2 個 CLI 子程序各對不同 id 切換最愛 20 次 → 結果 40 筆都在；同時有執行緒反覆 `json.loads(library.json)` 一次都不失敗。
- [ ] K16（九個新操作，三入口全開）：依序加在 L2 的 7 個之後，名稱、HTTP、CLI、MCP 見常數「操作表」；每個都是一個 service 方法＋facade 一行 `return`＋`OPERATIONS` 一筆＋路由＋子指令（`--json`，信封同 L9）＋MCP 工具；`list_presets` 加 `favorites=False`（CLI `--favorites`、MCP `favorites`）。MCP 註記：讀取類 `readOnlyHint:true`；其他 `readOnlyHint:false`、`destructiveHint:false`、`openWorldHint:false`，`idempotentHint:true` 只給 rename／move／favorite／rebuild。錯誤 kind 與對照照 L7（conflict 409／4、unavailable 503／5 本片開始產生）；新句子見常數，三入口逐字相同。
- [ ] K17（一致性測試）：`tests/test_interface_parity.py` 加情境（三 driver 結果相同）：群組樹、改名成空白、未知 preset 改名、搬到「A -  - B」、建已存在的群組、改名到已存在的群組、未知群組改名、favorite 給 `1`、最愛檢視、匯入（成功＋重複＋`.txt`＋壞 xmp 同一批）、自存成功（之後 `preset_detail` 可讀、值等於 K13）、自存沒選也沒微調、強度 250、鎖被占住（測試持鎖 → conflict）。每個情境用自己的合成庫複本。
- [ ] K18（分層與寫檔守門修訂）：L13／X14 的寫檔掃描與 `test_server_never_writes`、`test_cli_mcp_never_write` 改為：preset 庫的寫入只准出現在 `darkroom_app/services/library.py`，目標只准是 `library.json`、它的 `.lock`／`.tmp-*`／`.bad-*`、`import/`、`user/` 底下的新檔；其他入口與 service 照舊禁止寫檔；讀取類情境照舊零寫入。
- [ ] K19（前端，修訂 B9 與 R6）：左欄最上方是「★ 最愛」區（沒有最愛時顯示常數空狀態句），下面是群組樹；每列 preset 有最愛切換鈕（☆／★，`aria-pressed`）；群組與 preset 列有動作選單（改名、搬到…、新群組、群組改名）；左欄有「匯入」（輸入一行或多行路徑）；預覽工具列有「存成 preset」（沒選 preset 也沒有微調時停用；按下要輸入名稱，群組預設「自存群組」）。成功或失敗用常數句型；匯入結果逐筆列出。存成 preset 不改變編輯狀態（不進 R5 復原紀錄）；新列沿用 R6 的 tree 鍵盤規則。R6／H11「窄視窗不得藏掉」清單加入：最愛切換鈕、動作選單鈕、匯入、存成 preset。
- [ ] K20（效能，ADR-0003）：`tools/bench_library.py` 把真實 1466 個 xmp 複製到暫存庫再量（只讀真實庫）：冷載入（沒有索引）中位數 ≤ 2.0 s（3 次）；`list_presets(query)`、`preset_groups()` 各 200 次 p95 ≤ 20 ms；rename／move／favorite 各 50 次（含鎖、重讀、原子寫）p95 ≤ 150 ms；匯入 20 個 ≤ 1.5 s；`save_user_preset` 20 次 p95 ≤ 300 ms；別的程序改過索引後下一次 `list_presets` ≤ 200 ms。跳過規則同 R1／B7（`gpucheck.gpu_busy`：使用率取樣中位數 > 15% 或 ComfyUI 佇列非空才跳過並印原因；`--force` 照量）。沒達標 → 先 profile（cProfile 前 20 名寫進 bench 輸出）再修；只有證明熱點是無法向量化、也沒有現成 C 函式庫的純 Python 迴圈時，才另開切片用 pyo3＋maturin 換掉那個 service。本片不用 Rust、不新增依賴。
- [ ] K21（回歸）：`python -s -m unittest discover -s tests` 結束碼 0；`node --test` 前端測試照 B13 不得跳過；HTTP golden（L8）除 K9 的第六欄外逐字不變。不做（留給之後）：刪除 preset、編輯既有 xmp 內容、匯出成 Lightroom 相容 xmp 的驗證、preset 縮圖、從照片庫的編輯（含快照）直接存——照片庫切片要補成以該編輯的快照為來源。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 買來的 xmp 與匯入來源（K1、K2、K11） | 只讀、不寫進 preset_dir | 使用者花錢買的 preset → 被改寫或數量變了，無法復原｜不可逆／資料 | `test_presets_untouched_hash`、`test_import_source_untouched`、`test_no_write_into_preset_dir` |
| 自存與匯入檔（K11、K12、K14） | 不覆蓋、不逃出資料夾 | 使用者先前存的 preset → 被同名新檔蓋掉｜不可逆／資料 | `test_save_never_overwrites`、`test_import_name_collision`、`test_safe_filename_stays_in_user` |
| 索引（K4、K5、K15） | 原子寫、鎖、壞檔保留 | 使用者整理好的名稱、群組、最愛 → 並發或寫一半後全部消失｜不可逆／資料 | `test_index_concurrent_processes`、`test_index_atomic_reader_never_fails`、`test_bad_index_kept` |
| 自存往返（K13） | `==` 完全相等 | 使用者 → 存起來的 preset 套回去跟當時畫面不一樣｜邏輯核心 | `test_user_preset_roundtrip` |
| 三入口操作（K16、K17） | 操作表、句子逐字 | 代理 → 同一個整理動作在 CLI／MCP 與 App 結果不同，照錯的去改｜上下游契約 | `test_interface_parity`、`test_operation_coverage` |
| `/api/presets` 列（K9） | 六欄 | 前端與之後的照片庫 → 欄位對不上整個左欄壞掉｜上下游契約 | `test_api_presets_shape` |
| 左欄與按鈕（K19） | 句型、窄視窗不藏 | 使用者 → 窄視窗找不到存成 preset、不知道匯入哪幾個失敗｜UI/UX | `tests/js/test_logic.cjs` 庫訊息、`test_narrow_windows_keep_function_buttons` |

## Verbatim Constants
```text
索引 schema：{"schema":"darkroom-preset-library/1","groups":[群組路徑…],"presets":{"<id>":{"file":"xmp/<stem>.xmp","sha256":"<64 hex>","name":"…","group":"…","favorite":false}}}
id 前綴：import: ｜ user:   群組分隔：" - "   自存群組：自存 preset   設定鍵：library_dir   群組樹形狀：{"groups":[{"name":"電影","path":"電影","count":N,"children":[{"name":"暖調","path":"電影 - 暖調","count":n}]}],"ungrouped":n}
自存 xmp：<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Normal" crs:ProcessVersion="15.4" crs:HasSettings="True" …>   數字文字：符合 ^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$ 且 float(文字)==值（例：format(Decimal(repr(v)), "f")）
安全檔名替換字元：<>:"/\|?* 與 \x00-\x1f → _ ；最長 80；空 → preset；撞名：{stem} ({n}).xmp（n 從 2 起）
操作表（facade ｜ HTTP ｜ CLI ｜ MCP，以「；」分隔）：preset_groups() ｜ GET /api/library/groups ｜ presets groups ｜ darkroom_preset_groups；rename_preset(preset_id,name) ｜ POST /api/library/rename ｜ presets rename <id> <name> ｜ darkroom_preset_rename；move_preset(preset_id,group) ｜ POST /api/library/move ｜ presets move <id> <group> ｜ darkroom_preset_move
  set_favorite(preset_id,favorite) ｜ POST /api/library/favorite ｜ presets favorite <id> on|off ｜ darkroom_preset_favorite；create_group(group) ｜ POST /api/library/groups/create ｜ groups create <group> ｜ darkroom_group_create；rename_group(group,new_name) ｜ POST /api/library/groups/rename ｜ groups rename <group> <new> ｜ darkroom_group_rename
  import_presets(paths,group=None) ｜ POST /api/library/import ｜ presets import <path>… [--group G] ｜ darkroom_presets_import；save_user_preset(name,group=None,preset_id=None,strength=100,overrides=None) ｜ POST /api/library/save ｜ presets save --name N [--group G] [--preset ID] [--strength S] [--override K=V]… ｜ darkroom_preset_save；rebuild_library() ｜ POST /api/library/rebuild ｜ presets rebuild ｜ darkroom_library_rebuild
invalid：preset 名稱要 1～100 個字 ｜ 群組名稱不能是空的，也不能有空的層級：{group} ｜ favorite 必須是 true 或 false ｜ 沒有要匯入的 xmp 檔 ｜ 沒有可以存的設定（沒選 preset 也沒有微調）   not_found：unknown preset {pid}（沿用 L3） ｜ 找不到群組：{group}
conflict：群組已存在：{group} ｜ preset 庫正被其他程式修改，請稍後再試   unavailable：無法寫入 preset 庫索引：{reason} ｜ 無法寫入自存 preset：{reason}
匯入單筆 error：找不到檔案：{path} ｜ 不是 .xmp 檔：{file_name} ｜ 無法讀取 preset：{file_name}：{reason} ｜ 已在 preset 庫裡（{name}），未重複匯入
前端：已存成 preset：{name} ｜ 已匯入 {ok} 個，{fail} 個沒有匯入 ｜ 還沒有最愛，按 preset 旁的 ☆ 加入   鎖：等待上限 5 s ｜ os.replace 重試 10 次約 1 s ｜ 合併雜湊：15C015CC0C080FF9（1466 個）
效能：冷載入 ≤ 2.0 s ｜ 查詢、群組樹 p95 ≤ 20 ms ｜ 整理類 p95 ≤ 150 ms ｜ 匯入 20 個 ≤ 1.5 s ｜ 自存 p95 ≤ 300 ms ｜ 外部變更後重讀 ≤ 200 ms ｜ 跳過：使用率中位數 > 15% 或 ComfyUI 佇列非空
```
