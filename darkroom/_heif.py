"""HEIC / HEIF reading (pillow-heif): primary image only, full bit depth, colour profile, orientation by libheif.

libheif applies the irot/imir transforms, so the pixels already have the display orientation; the EXIF
Orientation tag (still present in the file) must not be applied a second time.
Every failure, including a damaged embedded colour profile, is a single-line ValueError (CONTRACT-heic H6).
"""
import io
import os

import numpy as np

from . import _icc

EXT = (".heic", ".heif")
MISSING = "讀 HEIC 需要 pillow-heif（python -s -m pip install --no-deps pillow-heif==1.8.0）"
DECODE_FAILED = "HEIC 解碼失敗：{detail}"
PROFILE_BROKEN = "HEIC 解碼失敗：內嵌色彩描述檔損壞（{detail}）"
DECODE_THREADS = max(1, min(16, os.cpu_count() or 1))   # iPhone files are 512 px grids decoded tile by tile


def one_line(e):
    """Exception -> single-line reason (library messages may contain newlines)."""
    return " ".join(str(e).split()) or type(e).__name__


def _decode(data):
    try:
        import pillow_heif
    except ImportError:
        raise ValueError(MISSING) from None
    pillow_heif.options.DECODE_THREADS = DECODE_THREADS
    try:
        hf = pillow_heif.open_heif(io.BytesIO(data), convert_hdr_to_8bit=False)
        mode, (w, h) = hf.mode, hf.size
        raw, stride = hf.data, hf.stride          # decodes the primary image only
        info = dict(hf.info)
    except Exception as e:  # libheif reports every decoding problem as an exception
        raise ValueError(DECODE_FAILED.format(detail=one_line(e))) from None
    return mode, w, h, raw, stride, info


def _codes(mode, w, h, raw, stride, info):
    """Pixel buffer -> (HxWx3 integer codes in RGB order, number of levels)."""
    base = mode.split(";")[0]
    channels = {"RGB": 3, "RGBA": 4, "BGR": 3, "BGRA": 4, "L": 1, "LA": 2}.get(base)
    if channels is None:
        raise ValueError(DECODE_FAILED.format(detail=f"不支援的像素格式 {mode}"))
    if mode.endswith(";16"):
        a = np.frombuffer(raw, np.uint16).reshape(h, stride // 2)[:, : w * channels].reshape(h, w, channels)
        bits = int(info.get("bit_depth") or 16)
        a = a >> (16 - bits) if bits < 16 else a
        levels = 1 << bits
    else:
        a = np.frombuffer(raw, np.uint8).reshape(h, stride)[:, : w * channels].reshape(h, w, channels)
        levels = 256
    if base.startswith("BGR"):
        a = a[..., [2, 1, 0]]
    elif channels in (1, 2):
        a = np.repeat(a[..., :1], 3, 2)
    return a, levels


def _colour(codes, levels, info):
    icc = info.get("icc_profile")
    if icc:
        conv = _icc.from_icc(icc)
        if conv is None:
            return _icc.littlecms_8bit(_icc.codes_to_float(codes, levels), icc)
        return conv.from_codes(codes, levels)
    conv = _icc.from_nclx(info.get("nclx_profile"))
    if conv is not None:
        return conv.from_codes(codes, levels)
    return _icc.codes_to_float(codes, levels)


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError(DECODE_FAILED.format(detail="檔案是空的"))
    mode, w, h, raw, stride, info = _decode(data)
    codes, levels = _codes(mode, w, h, raw, stride, info)
    try:
        out = _colour(codes, levels, info)
    except Exception as e:  # damaged ICC / nclx data: struct errors, LittleCMS errors, ...
        raise ValueError(PROFILE_BROKEN.format(detail=one_line(e))) from None
    if out.dtype != np.float32 or not out.flags.c_contiguous:
        out = np.ascontiguousarray(out, dtype=np.float32)
    return out
