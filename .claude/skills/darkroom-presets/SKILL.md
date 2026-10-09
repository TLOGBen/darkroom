---
name: darkroom-presets
description: 管理 darkroom 的 preset 庫：搜尋 preset、看群組樹、最愛、改顯示名稱、搬群組、建／改群組、匯入 .xmp、把編輯存成自存 preset、重建索引；說明哪些操作會寫檔、寫到哪。使用者說「找 preset」「有哪些 preset」「加到最愛」「整理 preset」「preset 改名」「搬到群組」「匯入 preset」「存成 preset」「重建索引」「preset library」「search presets」「favorite preset」「import xmp」「save as preset」「rebuild index」時用。
---

# darkroom-presets

## 什麼時候用

使用者要在 preset 庫裡找東西、整理（群組、最愛、名稱）、把新買的 `.xmp` 加進來、把調好的效果存成自己的 preset、或索引壞了要重建。
把 preset 套到照片、預覽、匯出 → `darkroom-edit`。

## 安全規則與寫檔位置

- 買來的 `.xmp`（`preset_dir` 裡的檔）**一個位元都不會變**；整理只寫索引。不要自己去改名、搬動、刪除 `preset_dir` 裡的檔案，也不要把東西放進去。
- 寫檔只會落在 preset 庫根目錄（`preset_library_dir`，沒設就是 `preset_dir` 的上一層）：

| 操作 | 寫到哪 |
|---|---|
| `presets list`／`show`／`flags`／`groups` | 不寫檔（索引不存在也只在記憶體裡建） |
| `presets rename`／`move`／`favorite`、`groups create`／`rename`、`presets rebuild` | `<庫根>/library.json`（原子寫入、跨程序鎖 `library.json.lock`） |
| `presets import` | `<庫根>/import/<檔名>.xmp`（複製；來源不動）＋索引 |
| `presets save`、`edit save-preset` | `<庫根>/user/<安全檔名>.xmp`（新檔，永不覆蓋，撞名加 ` (2)`）＋索引 |

- 沒有刪除操作：這一版不能從庫裡刪 preset 或群組；使用者要刪，告訴他只能自己動檔案（`import/`、`user/` 裡的檔刪掉後 `presets rebuild`），買來的不要刪。
- 一次影響很多 preset 的改名／搬移／群組改名：先列出會動到的清單給使用者確認。

## 指令（`python` ＝ repo 的 Python，一律加 `-s` 與 `--json`）

```powershell
# 搜尋：--query 比對名稱或群組的子字串（不分大小寫），不做同義詞；沒 --limit 會全列（可能上千行）
python -s -m darkroom_app.cli presets list --query film --limit 50 --json
python -s -m darkroom_app.cli presets list --query 膠捲 --limit 50 --json
python -s -m darkroom_app.cli presets list --favorites --json
python -s -m darkroom_app.cli presets show <id> --json
python -s -m darkroom_app.cli presets flags --json                 # {id: major|minor}
python -s -m darkroom_app.cli presets groups --json                # 群組樹；第一個 " - " 分上下層

# 整理（只改索引）
python -s -m darkroom_app.cli presets favorite <id> on --json      # on|off
python -s -m darkroom_app.cli presets rename <id> "暖調底片" --json   # 1～100 字，檔案不變
python -s -m darkroom_app.cli groups create "底片 - 暖調" --json      # 已存在 → conflict（結束碼 4）
python -s -m darkroom_app.cli presets move <id> "底片 - 暖調" --json  # 群組不存在就建
python -s -m darkroom_app.cli groups rename "底片" "膠卷" --json      # 子群組一起改；目標已存在 → conflict，不合併

# 匯入：檔案或資料夾（只取第一層 *.xmp）；內容相同的不重複匯入
python -s -m darkroom_app.cli presets import D:/new-presets --group "新買的" --json
python -s -m darkroom_app.cli presets import D:/a.xmp D:/b.xmp --json

# 存成自存 preset（群組預設「自存 preset」，id 會是 user:<名稱>）
python -s -m darkroom_app.cli presets save --name "我的暖調" --preset <id> --strength 120 --override Contrast2012=10 --json
python -s -m darkroom_app.cli edit save-preset <photo> --name "人像暖調 80" --group "我的" --json

# 重建索引：手動加減過 import/、user/ 的檔、或索引壞掉時；回 {added, removed, kept}
python -s -m darkroom_app.cli presets rebuild --json
```

MCP 對應：`darkroom_presets_list`、`darkroom_preset_show`、`darkroom_preset_flags`、`darkroom_preset_groups`、`darkroom_preset_rename{preset_id,name}`、`darkroom_preset_move{preset_id,group}`、`darkroom_preset_favorite{preset_id,favorite}`、`darkroom_group_create{group}`、`darkroom_group_rename{group,new_name}`、`darkroom_presets_import{paths|files,group}`、`darkroom_preset_save{name,group,preset_id,strength,overrides}`、`darkroom_presets_rebuild`、`darkroom_edit_save_preset{path,name,group}`。

## 怎麼找得準

1. 先 `presets groups` 看群組樹——買來的 preset 通常依主題分組（人物、器材、地區、復古……），使用者說的「底片」很可能在「器材 - 膠捲 - …」底下。
2. `--query` 多試幾個詞：中文（底片、膠捲、膠卷、菲林）、英文（film、kodak、fuji、portra、35mm）、品牌／型號。
3. 回報列 `id`、`group`、`name`；`skipped` 非空的註明「有部分設定套不上」（`presets show` 的 `note` 有中文說明；`level` 是 `major` 要講）。
4. 使用者要挑時，用 `darkroom-edit` 預覽幾個候選。

## 匯入的結果怎麼讀

`presets import` 是批次：`results` 每個檔一筆，`{ok:true, source, id}` 或 `{ok:false, source, error}`（重複的多一個 `duplicate_of`）；有任何一筆失敗結束碼就是 6，但成功的已經複製進 `import/` 並登錄。重複（`已在 preset 庫裡（<name>），未重複匯入`）不是錯，照實告訴使用者就好。

## 要先問使用者的時機

- 匯入要不要統一指定群組（`--group`）；沒說就用檔案裡的 `crs:Group`。
- 存成 preset 的名稱與群組；沒說群組就用預設「自存 preset」。
- 群組改名／搬移會動到很多 preset 時。
- 使用者要「刪 preset」：先說明這一版沒有刪除功能、買來的檔不能刪，再問他要怎麼處理。
