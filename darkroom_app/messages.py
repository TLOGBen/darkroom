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
EXPORT_BAD_FORMAT = "不支援的匯出格式：{format}（可用 jpeg、png、tiff、webp）"   # XP31
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
PL_PARENT_MISSING = "上層資料夾不存在：{parent}"      # the reason inside PL_CANNOT_WRITE (PLP17, seal F1)
PL_NO_PREVIOUS = "這張照片沒有上一份編輯可以取回：{file_name}"   # verbatim (CONTRACT-s1-experience S4), not_found
PL_RESTORE_OVER_EDIT = "這張照片已經有別的編輯，取回上一份會蓋掉它；要取回請先還原成原圖：{file_name}"   # verbatim (S4a), conflict

# CONTRACT-semantic-index (verbatim constants; SI2, SI3, SI7-SI9)
SEM_NEED_PACKAGE = "需要 anthropic 套件：python -s -m pip install anthropic==1.13.0"
SEM_NEED_KEY = ("需要在 config.local.json 設定 anthropic_api_key_ref（1Password 參照，例如 op://<vault>/<item>/credential），"
                "或設定環境變數 DARKROOM_ANTHROPIC_API_KEY")
SEM_NEED_SOURCES = "需要標準圖：{dir} 裡要有 real-portrait.jpg、real-landscape.jpg、real-night.jpg、real-fog.jpg"
SEM_KEY_FAILED = "無法取得 Anthropic 金鑰：{reason}"
SEM_KEY_NO_OP = "找不到 op（1Password CLI）"
SEM_KEY_OP_EXIT = "op read 結束碼 {code}"
SEM_KEY_OP_TIMEOUT = "1Password 尚未登入或還在等解鎖（op read 逾時）"   # SIP10 (was "op read 逾時")
SEM_KEY_OP_EMPTY = "op read 回傳空值"
SEM_API_ERROR = "Anthropic API 錯誤：{detail}"
SEM_INDEX_UNAVAILABLE = "無法寫入語意索引：{reason}"
SEM_LIMIT_INVALID = "limit 必須是 1 以上的整數"
SEM_WAIT_INVALID = "wait_seconds 必須是 0 以上的數"
SEM_OVER_BUDGET = "預估費用 {usd:.4f} 美元超過上限 {budget:.2f} 美元（設定鍵 semantic_index_budget_usd）"
SEM_BAD_RESPONSE = "回應不合格式：{reason}"
SEM_BATCH_RESULT = "批次結果：{result_type}"

# CONTRACT-s2-export-detect (verbatim constants; E2, E7, E9, E10, E12-E17, E20, E21, E23, E24, XP31, SIP10)
EXPORT_BAD_WEBP_QUALITY = "WebP 品質要在 1～100 之間：{quality}"
EXPORT_BAD_BIT_DEPTH = "位元深度要是 8 或 16：{bit_depth}"
EXPORT_JPEG_8BIT = "JPEG 只能輸出 8-bit：{bit_depth}"
EXPORT_WEBP_8BIT = "WebP 只能輸出 8-bit：{bit_depth}"
EXPORT_MAX_KB_JPEG_ONLY = "檔案大小上限只適用於 JPEG"
EXPORT_BAD_MAX_KB = "檔案大小上限要是 10～1048576 之間的整數（KB）：{max_kb}"
EXPORT_BAD_RESIZE = '尺寸設定要是 {"mode": …, "value": …}：'          # + str(resize)
EXPORT_BAD_RESIZE_MODE = "不支援的尺寸方式：{mode}（可用 long_edge、short_edge、width、height、megapixels、percent）"
EXPORT_BAD_RESIZE_EDGE = "{mode} 的值要是 1～65535 的整數：{value}"
EXPORT_BAD_RESIZE_MP = "megapixels 的值要是大於 0、不超過 1000 的數：{value}"
EXPORT_BAD_RESIZE_PERCENT = "percent 的值要是大於 0、不超過 100 的數（不會放大）：{value}"
EXPORT_BAD_METADATA = "不支援的中繼資料選項：{metadata}（可用 all、copyright、none）"
EXPORT_BAD_REMOVE_GPS = "remove_gps 必須是 true 或 false"
EXPORT_BAD_SHARPEN = '銳利化設定要是 {"target": …, "amount": …}：'        # + str(sharpen)
EXPORT_BAD_SHARPEN_TARGET = "不支援的銳利化對象：{target}（可用 screen、matte、glossy）"
EXPORT_BAD_SHARPEN_AMOUNT = "不支援的銳利化強度：{amount}（可用 low、standard、high）"
EXPORT_TOO_BIG_FOR_KB = "無法壓到 {max_kb} KB 以內：品質 1 也有 {actual_kb} KB"
EXPORT_WEBP_TOO_LARGE = "WebP 最大 16383×16383 像素，這張是 {width}×{height}；請縮小尺寸後再匯出"
EXPORT_PHOTO_IN_PRESET_DIR = "照片在 preset 資料夾裡，請指定匯出資料夾（dest_dir）"
XP_NAME_LENGTH = "匯出預設名稱要 1～60 個字"
XP_TOO_MANY = "匯出預設最多 200 個"
XP_NO_DEST_DIR = "匯出預設不包含匯出資料夾（dest_dir）"
XP_SETTINGS_NOT_OBJECT = "匯出設定要是物件：{settings}"                     # IP8
XP_UNKNOWN_KEY = "匯出設定不認得的鍵：{key}（可用 format、bit_depth、quality、max_kb、resize、metadata、remove_gps、sharpen）"   # IP8
XP_NOT_FOUND = "找不到匯出預設：{name}"
XP_BUSY = "匯出預設正被其他程式修改，請稍後再試"
XP_FOREIGN = "匯出預設檔版本不支援：{schema}（export-presets.json）"     # E12a (seal F2), conflict
XP_UNAVAILABLE = "無法寫入匯出預設：{reason}"
PRESET_IDS_INVALID = "preset_ids 要是 1～500 個 preset id"
PRESET_EXPORT_INTO_LIBRARY = "不能把 preset 匯出到 preset 資料夾或 preset 庫裡：{dest_dir}"
LIB_IN_PHOTO_FOLDER = ("preset 庫的位置 {root} 在照片資料夾裡（{photo_folder} 有照片），為了不在照片資料夾裡寫檔，整理 preset、"
                       "匯入、存成 preset 先關閉；請在 config.local.json 把 preset_library_dir 設到別的資料夾")
CAP_NO_GPU = "沒有偵測到可用的 NVIDIA 顯示卡（CUDA），預覽與匯出改用 CPU，會慢很多"
CAP_NO_HEIC = "讀 HEIC 需要 pillow-heif（python -s -m pip install --no-deps pillow-heif==1.8.0）"   # = darkroom/_heif.py MISSING (E23; a test pins the equality)
CAP_NO_WEBP = "這台電腦的 OpenCV 不能寫 WebP，WebP 匯出先關閉"
OP_NOT_SIGNED_IN = "1Password 尚未登入（請解鎖 1Password App 或執行 op signin）"
OP_WHOAMI_TIMEOUT = "1Password 尚未登入或還在等解鎖（op whoami 逾時）"
OP_NOT_USED = "沒有用到 1Password（config.local.json 沒有 anthropic_api_key_ref）"
