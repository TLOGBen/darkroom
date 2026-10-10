"""Image IO: read JPEG/PNG/TIFF (8 or 16-bit, assumed sRGB) and HEIC/HEIF (pillow-heif: colour profile,
10-bit, orientation; see _heif) as HxWx3 float32 0..1 in sRGB encoding;
write 16-bit PNG/TIFF or 8-bit JPEG. Unicode paths are fine (bytes go through numpy).

Orientation (core patch K2): JPEG and TIFF pixels come out upright by their EXIF / TIFF Orientation tag (the
same transposition as PIL ImageOps.exif_transpose). OpenCV's TIFF decoder already turns TIFF pixels whatever the
flags (measured 2026-10-09, all 8 values, 8 and 16-bit), so only JPEG is turned here; PNG is never turned; HEIC is
turned by libheif only (_heif).

Layer: core library. Depends on numpy, OpenCV (imported lazily) and `_heif`; nothing in darkroom_app. The App
reads photos through `read_image` but encodes its exports itself (darkroom_app's encoding utilities, which add
ICC / EXIF handling); `write_image` is used by the core CLI (`python -m darkroom apply`) and tests.

Data in: a path (photo files are only ever opened with "rb"). Data out: a C-contiguous HxWx3 float32 array in
0..1, RGB order, still sRGB-encoded (no linearisation here; _render does that). Alpha is dropped, grey is
replicated to three channels. Files are read as bytes and decoded from memory, which is why non-ASCII Windows
paths work (cv2.imread cannot open them).
"""
import os
import struct

import numpy as np

from . import _heif

READ_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff") + _heif.EXT
WRITE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")

# EXIF Orientation -> transform of an HxWxC array, as PIL ImageOps.exif_transpose: 2 FLIP_LEFT_RIGHT,
# 3 ROTATE_180, 4 FLIP_TOP_BOTTOM, 5 TRANSPOSE, 6 ROTATE_270, 7 TRANSVERSE, 8 ROTATE_90 (PIL turns counter-clockwise)
_ORIENT = {
    2: lambda a: a[:, ::-1],
    3: lambda a: a[::-1, ::-1],
    4: lambda a: a[::-1],
    5: lambda a: a.transpose(1, 0, 2),
    6: lambda a: a.transpose(1, 0, 2)[:, ::-1],
    7: lambda a: a.transpose(1, 0, 2)[::-1, ::-1],
    8: lambda a: a.transpose(1, 0, 2)[::-1],
}


def _tiff_orientation(t):
    """Orientation (tag 274) in IFD0 of TIFF-structured bytes; 1 when absent or not 1..8."""
    if t[:4] == b"II*\0":
        e = "<"
    elif t[:4] == b"MM\0*":
        e = ">"
    else:
        return 1
    (ifd,) = struct.unpack_from(e + "I", t, 4)
    (n,) = struct.unpack_from(e + "H", t, ifd)
    for i in range(n):
        tag, typ, count = struct.unpack_from(e + "HHI", t, ifd + 2 + 12 * i)
        if tag == 274 and typ == 3 and count >= 1:
            (v,) = struct.unpack_from(e + "H", t, ifd + 2 + 12 * i + 8)
            return v if v in _ORIENT else 1
    return 1


def _jpeg_exif(data):
    """TIFF-structured bytes of the first APP1 Exif segment before the image data of a JPEG, else None."""
    if data[:2] != b"\xff\xd8":
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        m = data[pos + 1]
        if m == 0xFF:                      # fill byte
            pos += 1
            continue
        if m in (0x01, 0xD8) or 0xD0 <= m <= 0xD7:
            pos += 2
            continue
        if m in (0xD9, 0xDA):              # end of image / start of scan: no metadata after this
            return None
        (n,) = struct.unpack_from(">H", data, pos + 2)
        seg = data[pos + 4:pos + 2 + n]
        if m == 0xE1 and seg[:6] == b"Exif\0\0":
            return seg[6:]
        pos += 2 + n
    return None


def _jpeg_orientation(data):
    """EXIF Orientation (1..8) of JPEG file bytes; 1 when absent or unreadable."""
    try:
        t = _jpeg_exif(data)
        return 1 if t is None else _tiff_orientation(t)
    except struct.error:
        return 1


def read_image(path):
    """Decode a JPEG/PNG/TIFF/HEIC file into an upright HxWx3 float32 sRGB array in 0..1.

    The extension decides the decoder (READ_EXT); HEIC goes to _heif.read (colour profile converted to sRGB).
    8-bit codes are divided by 255, 16-bit by 65535, float TIFFs are clipped. Raises ValueError for an
    unsupported extension, an undecodable file or an odd sample type; OSError when the file cannot be read.
    Read-only: the photo is opened with "rb" and never touched again.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in READ_EXT:
        raise ValueError(f"unsupported input format {ext!r} (JPEG/PNG/TIFF/HEIC)")
    if ext in _heif.EXT:
        return _heif.read(path)
    import cv2  # imported lazily so `import darkroom` stays light
    with open(path, "rb") as f:
        data = f.read()
    a = cv2.imdecode(np.frombuffer(data, np.uint8),
                     cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_IGNORE_ORIENTATION)
    if a is None:
        raise ValueError(f"cannot decode image {path}")
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, 2)
    elif a.shape[2] == 4:
        a = a[..., :3]
    elif a.shape[2] == 1:
        a = np.repeat(a, 3, 2)
    a = a[..., ::-1]  # BGR -> RGB
    turn = _ORIENT.get(_jpeg_orientation(data)) if ext in (".jpg", ".jpeg") else None   # K2: exactly once
    if turn is not None:
        a = turn(a)
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
    """Encode `img` (HxWx3 float in 0..1, RGB) to `path`: 8-bit JPEG at `jpeg_quality`, else 16-bit PNG/TIFF.

    Values are clipped to 0..1 and rounded (+0.5) to the nearest code. Raises ValueError for an extension outside
    WRITE_EXT or an encoder failure. Side effect: creates / overwrites `path` (callers are responsible for never
    passing a photo or preset path; the core CLI checks this, the App does not use this function for exports).
    No ICC profile or EXIF is embedded.
    """
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
