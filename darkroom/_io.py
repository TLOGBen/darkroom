"""Image IO: read JPEG/PNG/TIFF (8 or 16-bit, assumed sRGB) as HxWx3 float32 0..1;
write 16-bit PNG/TIFF or 8-bit JPEG. Unicode paths are fine (bytes go through numpy)."""
import os

import numpy as np

READ_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
WRITE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


def read_image(path):
    import cv2  # imported lazily so `import darkroom` stays light
    ext = os.path.splitext(path)[1].lower()
    if ext not in READ_EXT:
        raise ValueError(f"unsupported input format {ext!r} (JPEG/PNG/TIFF)")
    with open(path, "rb") as f:
        buf = np.frombuffer(f.read(), np.uint8)
    a = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_IGNORE_ORIENTATION)
    if a is None:
        raise ValueError(f"cannot decode image {path}")
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, 2)
    elif a.shape[2] == 4:
        a = a[..., :3]
    elif a.shape[2] == 1:
        a = np.repeat(a, 3, 2)
    a = a[..., ::-1]  # BGR -> RGB
    if a.dtype == np.uint8:
        out = a.astype(np.float32) / 255.0
    elif a.dtype == np.uint16:
        out = a.astype(np.float32) / 65535.0
    elif a.dtype in (np.float32, np.float64):
        out = a.astype(np.float32)
    else:
        raise ValueError(f"unsupported sample type {a.dtype}")
    return np.ascontiguousarray(np.clip(out, 0.0, 1.0))


def write_image(path, img, jpeg_quality=95):
    import cv2
    ext = os.path.splitext(path)[1].lower()
    if ext not in WRITE_EXT:
        raise ValueError(f"unsupported output format {ext!r} (PNG/TIFF 16-bit, JPEG 8-bit)")
    a = np.clip(np.asarray(img, dtype=np.float32), 0.0, 1.0)[..., ::-1]  # RGB -> BGR
    if ext in (".jpg", ".jpeg"):
        data = (a * 255.0 + 0.5).astype(np.uint8)
        ok, enc = cv2.imencode(ext, data, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
    else:
        data = (a * 65535.0 + 0.5).astype(np.uint16)
        ok, enc = cv2.imencode(".png" if ext == ".png" else ".tif", data)
    if not ok:
        raise ValueError(f"cannot encode {path}")
    with open(path, "wb") as f:
        f.write(enc.tobytes())
