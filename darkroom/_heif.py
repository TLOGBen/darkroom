"""HEIC / HEIF reading (pillow-heif): primary image only, full bit depth, colour profile, orientation by libheif.

libheif applies the irot/imir transforms, so the pixels already have the display orientation; the EXIF
Orientation tag (still present in the file) must not be applied a second time.
"""
import io

import numpy as np

from . import _icc

EXT = (".heic", ".heif")
MISSING = "讀 HEIC 需要 pillow-heif（python -s -m pip install --no-deps pillow-heif==1.8.0）"
DECODE_FAILED = "HEIC 解碼失敗：{detail}"


def _decode(data):
    try:
        import pillow_heif
    except ImportError:
        raise ValueError(MISSING) from None
    try:
        hf = pillow_heif.open_heif(io.BytesIO(data), convert_hdr_to_8bit=False)
        mode, (w, h) = hf.mode, hf.size
        raw, stride = hf.data, hf.stride          # decodes the primary image only
        info = dict(hf.info)
    except Exception as e:  # libheif reports every decoding problem as an exception
        detail = " ".join(str(e).split()) or type(e).__name__     # libheif messages may end with newlines
        raise ValueError(DECODE_FAILED.format(detail=detail)) from None
    return mode, w, h, raw, stride, info


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError(DECODE_FAILED.format(detail="檔案是空的"))
    mode, w, h, raw, stride, info = _decode(data)
    base = mode.split(";")[0]
    channels = {"RGB": 3, "RGBA": 4, "BGR": 3, "BGRA": 4, "L": 1, "LA": 2}.get(base)
    if channels is None:
        raise ValueError(DECODE_FAILED.format(detail=f"不支援的像素格式 {mode}"))
    if mode.endswith(";16"):
        a = np.frombuffer(raw, np.uint16).reshape(h, stride // 2)[:, : w * channels].reshape(h, w, channels)
        bits = int(info.get("bit_depth") or 16)
        a = (a >> (16 - bits)).astype(np.float64) / float((1 << bits) - 1)
    else:
        a = np.frombuffer(raw, np.uint8).reshape(h, stride)[:, : w * channels].reshape(h, w, channels)
        a = a.astype(np.float64) / 255.0
    if base.startswith("BGR"):
        a = a[..., [2, 1, 0] + ([3] if channels == 4 else [])]
    if channels in (1, 2):
        a = np.repeat(a[..., :1], 3, 2)
    a = np.clip(a[..., :3], 0.0, 1.0)

    icc = info.get("icc_profile")
    if icc:
        conv = _icc.from_icc(icc)
        out = conv(a) if conv is not None else _icc.littlecms_8bit(a, icc)
    else:
        conv = _icc.from_nclx(info.get("nclx_profile"))
        out = conv(a) if conv is not None else a
    return np.ascontiguousarray(np.clip(out, 0.0, 1.0), dtype=np.float32)
