"""Every sentence the services put in a DarkroomError (verbatim, CONTRACT-layering constants).

The validate_* sentences of darkroom_app.preview are raised there and passed on as str(e) unchanged.
Interfaces never build these sentences themselves.
"""

PATH_REQUIRED = "path is required"
PHOTO_NOT_FOUND = "photo not found: {path}"
UNSUPPORTED_FORMAT = "unsupported photo format (JPEG/PNG/TIFF/HEIC)"
UNKNOWN_IMAGE = "unknown image_id"
UNKNOWN_PRESET = "unknown preset {pid}"
UNKNOWN_OR_UNSUPPORTED_PRESET = "unknown or unsupported preset {pid}"
OPEN_ERROR = "照片讀取失敗：{file_name}：{reason}"   # verbatim (CONTRACT-heic)

OFFSET_INVALID = "offset must be an integer >= 0"
LIMIT_INVALID = "limit must be an integer in 1..200"
MAX_PIXELS_INVALID = "max_pixels must be an integer in 65536..1500000"

# CONTRACT-export (verbatim constants; X1, X11, X12, XP2)
EXPORT_NOTHING = "沒有要匯出的照片"
EXPORT_BAD_FORMAT = "不支援的匯出格式：{format}（可用 jpeg、tiff）"
EXPORT_BAD_QUALITY = "JPEG 品質要在 1～100 之間：{quality}"
EXPORT_NO_DEST = "找不到匯出資料夾：{dest_dir}"
EXPORT_FAILED = "匯出失敗：{file_name}：{reason}"
EXPORT_OOM = "顯示卡記憶體不足，可能有其他程式正在使用 GPU；關掉它們後再匯出一次"
EXPORT_RENDER_FAILED = "渲染失敗：{detail}"
EXPORT_CANNOT_WRITE = "無法寫入匯出資料夾：{folder}"
EXPORT_NAMES_USED_UP = "{stem} 的匯出檔名已用到 ({n_max})，請清理匯出資料夾後再試"
EXPORT_ITEM_NOT_OBJECT = "each item must be an object {image_id | path, preset_id, strength, overrides}"
EXPORT_ITEM_UNKNOWN_KEY = "unknown item key {key!r} (allowed: image_id, path, preset_id, strength, overrides)"

LIMIT_MAX = 200
MAX_PIXELS_MIN = 65536
MAX_PIXELS_MAX = 1500000

# CONTRACT-preset-library (verbatim constants; K6-K12, K15, KP4, KP9)
LIB_NAME_LENGTH = "preset 名稱要 1～100 個字"
LIB_GROUP_INVALID = "群組名稱不能是空的，也不能有空的層級：{group}"
LIB_FAVORITE_INVALID = "favorite 必須是 true 或 false"
LIB_NOTHING_TO_IMPORT = "沒有要匯入的 xmp 檔"
LIB_NOTHING_TO_SAVE = "沒有可以存的設定（沒選 preset 也沒有微調）"
LIB_FILES_INVALID = "files 必須是 [{name, data_base64}] 陣列"
LIB_GROUP_NOT_FOUND = "找不到群組：{group}"
LIB_GROUP_EXISTS = "群組已存在：{group}"
LIB_BUSY = "preset 庫正被其他程式修改，請稍後再試"
LIB_INDEX_UNAVAILABLE = "無法寫入 preset 庫索引：{reason}"
LIB_SAVE_UNAVAILABLE = "無法寫入自存 preset：{reason}"
LIB_IMPORT_MISSING = "找不到檔案：{path}"
LIB_IMPORT_NOT_XMP = "不是 .xmp 檔：{file_name}"
LIB_IMPORT_UNREADABLE = "無法讀取 preset：{file_name}：{reason}"
LIB_IMPORT_DUPLICATE = "已在 preset 庫裡（{name}），未重複匯入"
LIB_IMPORT_WRITE_FAILED = "無法寫入 preset 庫：{file_name}：{reason}"

# CONTRACT-photo-library (verbatim constants; PL7-PL9, PL11, PL13, PLP1, PLP3, PLP8)
PL_NO_EDIT = "這張照片沒有編輯：{file_name}"
PL_FOLDER_NOT_FOUND = "找不到照片資料夾：{folder}"
PL_SOURCE_OR_EDIT = "source 與 edit 要恰好給一個"
PL_EDIT_INVALID = "edit 不是 darkroom-edit/1 編輯：{reason}"
PL_TARGETS_INVALID = "targets 要是 1～500 個照片路徑"
PL_THUMB_FAILED = "縮圖產生失敗：{file_name}：{reason}"
PL_SCHEMA_CONFLICT = "編輯檔版本不支援：{schema}（{file_name}）"
PL_EDIT_CORRUPT = "照片庫的編輯檔損壞：{edit_file}"
PL_CANNOT_WRITE = "無法寫入照片庫：{data_dir}：{reason}"
PL_CANNOT_READ = "無法讀取照片庫：{edit_file}：{reason}"
PL_DATA_DIR_INSIDE = "照片庫資料區不能在照片或 preset 資料夾底下：{data_dir}"
# reasons inside PL_EDIT_INVALID and the corrupt-file judgement (PLP8)
PL_EDIT_NOT_OBJECT = "not an object"
PL_EDIT_KEYS = "keys must be exactly schema, fingerprint, preset, strength, overrides"
PL_EDIT_SCHEMA = "schema is {schema!r}, not darkroom-edit/1"
PL_EDIT_PRESET = "preset must be null or {id, name, group, params}"
PL_EDIT_PARAMS = "params: {reason}"
