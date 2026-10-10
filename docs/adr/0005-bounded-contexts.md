---
status: accepted
---

# 五個 bounded context，前後端都照它分資料夾

v2 要把後端分層、把前端改寫成 React（`docs/architecture/plan-v2.md`），兩邊都需要「依領域分檔」，但 v1 只有一份扁平的詞彙表，`services/` 與 `logic.js` 各自用自己的切法（例如 `presets.py` 與 `preset_library.py` 分屬搜尋與整理、`logic.js` 一支檔案裝了滑桿、裁切、匯出與縮圖格）。所以先把領域切成五個 context，詞彙依 context 寫在 `CONTEXT.md`，後端模組、前端資料夾與型別名都從同一份清單推出來；以後新增檔案先問「它屬於哪個 context」，不屬於任何一個就是 `utils`／`common`（2026-10-10 v2 施工時定）。

## Context 清單

| Context | slug | 責任 | 擁有的資料 |
|---|---|---|---|
| Preset 庫 | `preset` | 找到、整理、保存 preset；整理只寫索引 | preset 原檔（唯讀）、`library.json` 索引、`import/`、`user/`、`semantic.json` |
| 編輯（調色＋幾何） | `edit` | 一張照片要變成什麼樣子：強度、微調、最終參數、幾何；畫出預覽 | 編輯的內容規則（不含儲存位置）、滑桿表 |
| 照片庫 | `library` | 記住每張照片目前的編輯；照片資料夾與縮圖格 | `data_dir/edits/`（以照片指紋）、上一份編輯、`thumbs/`、`index/` |
| 匯出 | `export` | 照片＋編輯 → 全解析度新檔，永不覆蓋 | 匯出設定、`export-presets.json`、寫出的匯出檔 |
| 設定與能力 | `settings` | 這台電腦的設定、能做什麼與原因、受管理執行環境 | 設定檔、能力偵測結果、`<app data>/runtime/` |

「入口」（HTTP／CLI／MCP）與核心函式庫 `darkroom/`（xmp 解析、torch 渲染、讀寫影像、幾何運算）不是 context：入口橫跨全部 context（ADR-0001），`darkroom/` 是各 context 共用的 shared kernel，它不認識任何 context。校正集／擬合是開發用的工具，不在執行期。

## 彼此的關係（上游 → 下游）

```
設定與能力 ──(路徑、開關、能力原因)──▶ 全部
Preset 庫 ──(Params 快照)──▶ 編輯 ──(Edit)──▶ 照片庫
                               │                 │
                               └──(最終參數)──▶ 匯出 ◀──(存好的編輯)──┘
編輯（渲染）──▶ Preset 庫的語意索引（把 preset 畫在公開標準圖上）
```

- **Preset 庫 → 編輯**：編輯在套用當下抄一份 Preset 快照。這是刻意的防腐層：preset 之後被改名、改內容、刪掉，都不會傳進已經套上的編輯（ADR-0002 的延伸）。編輯只拿 preset id 去換快照，不讀索引的其他欄位。
- **編輯 → 照片庫**：編輯定義「一份編輯長什麼樣、怎麼驗證、怎麼算最終參數」；照片庫照抄這個模型（conformist），只負責以照片指紋存取、保留上一份編輯、產縮圖。照片庫不自己發明編輯欄位。
- **編輯＋照片庫 → 匯出**：匯出拿最終參數與幾何去渲染；沒給參數時向照片庫要存好的編輯。匯出不改編輯、不改照片庫。
- **編輯 → Preset 庫（語意索引）**：語意索引借用編輯的渲染畫 preset 效果，只用公開標準圖，不碰照片庫。這是唯一一條「下游回頭用上游」的線，只允許經過渲染函式，不允許讀編輯或照片庫的資料。
- **設定與能力 → 全部**：其他 context 只透過組裝點（`composition.py`）拿到設定給的路徑與開關，不自己讀設定檔；功能被關掉時用能力給的那一句原因。設定改了就重組，不需要各 context 自己監聽。

## 命名規則

後端（`darkroom_app/`，plan-v2 §1）：

| 層 | 規則 | 現有對照 |
|---|---|---|
| `services/` | 一個模組只屬於一個 context；檔名以該 context 的詞開頭 | Preset 庫：`presets.py`（列表、搜尋、細節；裡面的滑桿表操作屬於編輯，是目前唯一跨 context 的模組，下次動到時搬去編輯）、`preset_library.py`（整理、匯入、自存、匯出 .xmp）、`semantic_index.py`；編輯：`preview.py`；照片庫：`photos.py`、`photo_library.py`；匯出：`export.py`、`export_presets.py`；設定與能力：`capabilities.py`（v2 新增的設定 service 叫 `settings.py`） |
| `domain/` | 同上；跨 context 共用的只有 `errors.py`、`messages.py`、`sentinels.py` | 編輯：`adjustment.py`、`sliders.py`；Preset 庫：`skips.py`；匯出：`formats.py`；設定：`settings.py` |
| `adapters/persist/` | `<資料>_store.py`，每個 store 只被擁有該資料的 context 的 service 使用 | `preset_index.py`、`semantic_store.py`（Preset 庫）；`edit_store.py`、`thumb_store.py`（照片庫）；`export_presets_store.py`（匯出）；`settings_store.py`（設定） |

前端（`web/src/`，plan-v2 §2），slug 一律英文小寫：

| 資料夾 | 規則 | Preset 庫 | 編輯 | 照片庫 | 匯出 | 設定與能力 |
|---|---|---|---|---|---|---|
| `domain/` | 一個 context 一支 `<slug>.ts`（純型別與純函式，配 `<slug>.test.ts`）；幾何量大，拆成編輯底下的 `geometry.ts` | `preset.ts` | `edit.ts`、`geometry.ts` | `library.ts` | `export.ts` | `settings.ts` |
| `requests/` | 一個 context 一支，檔名用 HTTP 資源的複數名；全部經 `client.ts` | `presets.ts`（`/api/presets*`、`/api/preset_flags`、`/api/preset-library/*`） | `edits.ts`（`/api/edit*`、`/api/preview`、`/api/sliders`） | `library.ts`（`/api/open`、`/api/folder*`、`/api/thumbnail`） | `exports.ts`（`/api/export`、`/api/export-presets`） | `settings.ts`（`/api/settings*`、`/api/capabilities`、`/api/version`） |
| `components/` | 一個 context 一個子資料夾（沿用 plan-v2 的名字）；跨 context 的放 `common/` | `presets/` | `editor/` | `library/` | `export/` | `settings/` |
| `hooks/` | 平放，`use<Context 詞>.ts`；一個 hook 只碰一個 context 的 request／store | `usePresets`、`usePresetLibrary` | `useEdit`、`usePreview`、`useGeometry` | `usePhotoFolder`、`useThumbnails` | `useExport`、`useExportPresets` | `useSettings`、`useCapabilities` |

- `/api/sliders` 歸編輯（滑桿是編輯 context 的詞），放 `requests/edits.ts`。
- 型別名用 `CONTEXT.md` 每個詞條括號裡的英文名（`Edit`、`Geometry`、`PhotoFingerprint`、`ExportPreset`…），不另取別名；同一個詞前後端同名。
- `components/` 用 `presets/`、`editor/` 而不是 slug 本身，是沿用 plan-v2 已定的畫面區塊名；`domain/`、`requests/`、`hooks/` 一律以 context 判斷歸屬。
- 一個 context 的檔案長到要拆時，`<slug>.ts` 變成 `<slug>/index.ts`，對外匯入路徑不變。

## Considered Options

- **照畫面切（編輯器、縮圖格、匯出對話框）**：v1 `static/` 大致是這樣，結果裁切規則同時散在編輯器與縮圖格，匯出對話框又自己算一次最終參數。照畫面切會把同一條規則複製到多個地方。
- **照技術層切（全部 request 一支、全部型別一支）**：小專案方便，但 Rust 逐塊替換（plan-v2 §5）是一個 service 一個 service 換，切口要跟 context 對齊才換得乾淨。

## Consequences

- 改一個詞（例如把「微調」改名）時，`CONTEXT.md`、後端 domain、前端 `domain/` 型別要一起改；詞彙表是單一來源。
- 「Agent 設定」（darkroom 自己呼叫 Claude）跟「代理」（外面的 AI 透過 CLI／MCP 操作 darkroom）是兩個詞，分屬設定與入口；程式裡 `agent.*` 設定鍵與 `agent_sdk` 能力指的都是前者。
