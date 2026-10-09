"""The one photo extension table (CONTRACT-heic H7), in a module that imports nothing.

`engine.PHOTO_EXT` is this same tuple (re-exported); the write module checks against it without importing torch / cv2
(CONTRACT-preset-library KP11: the `presets *` CLI commands that write the library stay torch-free, L9).
"""
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif")   # CONTRACT-heic H7
