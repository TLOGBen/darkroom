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

LIMIT_MAX = 200
MAX_PIXELS_MIN = 65536
MAX_PIXELS_MAX = 1500000
