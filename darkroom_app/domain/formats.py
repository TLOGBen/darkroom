"""The one photo extension table (CONTRACT-heic H7), in a module that imports nothing.

`engine.PHOTO_EXT` is this same tuple (re-exported); the write module checks against it without importing torch / cv2
(CONTRACT-preset-library KP11: the `presets *` CLI commands that write the library stay torch-free, L9).

Layer: domain - the one domain module utils may import (the write module protects photo extensions with it).

Contract codes: H7 = HEIC / HEIF count as photos everywhere a photo is listed or opened; KP11 = the extension table
lives in a module without heavy imports so writers can use it; L9 = the CLI's preset commands must not load torch.
"""
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif")   # CONTRACT-heic H7
