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
