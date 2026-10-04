"""Colour profiles of decoded photos -> the core's sRGB encoding.

Matrix/TRC ICC profiles (rXYZ/gXYZ/bXYZ + curv/para curves; Display P3 and sRGB are of this kind):
  tone curve -> linear -> XYZ (D50 PCS) -> linear sRGB (Bradford-adapted D50 matrix) -> clip 0..1 -> sRGB curve.
Colours outside the sRGB gamut are clipped (the renderer works in linear sRGB).

Decoded photos are integer codes (8/10/12 bit), so the fast path (Converter.from_codes) evaluates the tone curve
once per code level (lookup table), mixes in float32 and encodes through a 65536-entry sRGB table, in row
chunks on a few threads (24 MP in about 0.3 s instead of 4 s with float64 arrays; difference about 1e-4).
"""
import os
import struct
from concurrent.futures import ThreadPoolExecutor

import numpy as np

# sRGB -> XYZ D50 (Bradford), as stored in ICC sRGB profiles; its inverse maps the PCS to linear sRGB.
SRGB_TO_XYZ_D50 = np.array([[0.4360747, 0.3850649, 0.1430804],
                            [0.2225045, 0.7168786, 0.0606169],
                            [0.0139322, 0.0971045, 0.7141733]])
XYZ_D50_TO_SRGB = np.linalg.inv(SRGB_TO_XYZ_D50)
# Display P3 colorants (D50-adapted), for HEIC files that describe P3 with nclx instead of an ICC profile.
P3_TO_XYZ_D50 = np.array([[0.515121, 0.291977, 0.157104],
                          [0.241196, 0.692245, 0.066574],
                          [-0.001053, 0.041885, 0.784073]])

ENC_SIZE = 1 << 16
ROWS = 128
WORKERS = max(1, min(8, os.cpu_count() or 1))
_ENC = None


def srgb_decode(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def srgb_encode(v):
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def _enc_table():
    global _ENC
    if _ENC is None:
        _ENC = srgb_encode(np.linspace(0.0, 1.0, ENC_SIZE)).astype(np.float32)
    return _ENC


def _rows(h, fn):
    """Run fn(y0, y1) over row chunks on a small thread pool (numpy releases the GIL in these loops)."""
    spans = [(y, min(h, y + ROWS)) for y in range(0, h, ROWS)]
    if len(spans) == 1 or WORKERS == 1:
        for a, b in spans:
            fn(a, b)
        return
    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(lambda s: fn(*s), spans))


def codes_to_float(codes, levels):
    """Integer codes HxWx3 -> float32 0..1 (no colour change)."""
    h = codes.shape[0]
    out = np.empty(codes.shape[:2] + (3,), np.float32)
    scale = np.float32(1.0 / (levels - 1))

    def job(a, b):
        np.multiply(codes[a:b, :, :3], scale, out=out[a:b], casting="unsafe")
    _rows(h, job)
    return out


def _s15(b):
    return struct.unpack(">i", b)[0] / 65536.0


def _tags(data):
    if len(data) < 132 or data[36:40] != b"acsp":
        return None
    n = struct.unpack(">I", data[128:132])[0]
    out = {}
    for i in range(n):
        entry = data[132 + 12 * i: 144 + 12 * i]
        if len(entry) < 12:
            return None                       # tag table cut short: not a usable profile
        sig, off, size = struct.unpack(">4sII", entry)
        if off + size <= len(data):
            out[sig] = data[off:off + size]
    return out


def _xyz(tag):
    if tag is None or tag[:4] != b"XYZ " or len(tag) < 20:
        return None
    return [_s15(tag[8 + 4 * k: 12 + 4 * k]) for k in range(3)]


def _curve(tag):
    """Tone curve tag -> function mapping encoded 0..1 to linear, or None if unsupported."""
    if tag is None or len(tag) < 12:
        return None
    kind = tag[:4]
    if kind == b"curv":
        n = struct.unpack(">I", tag[8:12])[0]
        if n == 0:
            return lambda v: v
        if n == 1:
            if len(tag) < 14:
                return None
            g = struct.unpack(">H", tag[12:14])[0] / 256.0
            return lambda v: np.power(np.clip(v, 0, 1), g)
        if len(tag) < 12 + 2 * n:
            return None
        table = np.frombuffer(tag[12:12 + 2 * n], ">u2").astype(np.float64) / 65535.0
        xs = np.linspace(0.0, 1.0, n)
        return lambda v: np.interp(v, xs, table)
    if kind == b"para":
        ftype = struct.unpack(">H", tag[8:10])[0]
        count = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}.get(ftype)
        if count is None or len(tag) < 12 + 4 * count:
            return None
        p = [_s15(tag[12 + 4 * k: 16 + 4 * k]) for k in range(count)]
        g = p[0]
        if ftype == 0:
            return lambda v: np.power(np.clip(v, 0, 1), g)
        if ftype == 1:
            a, b = p[1], p[2]
            return lambda v: np.where(v >= -b / a, np.power(np.clip(a * v + b, 0, None), g), 0.0)
        if ftype == 2:
            a, b, c = p[1], p[2], p[3]
            return lambda v: np.where(v >= -b / a, np.power(np.clip(a * v + b, 0, None), g) + c, c)
        if ftype == 3:
            a, b, c, d = p[1], p[2], p[3], p[4]
            return lambda v: np.where(v >= d, np.power(np.clip(a * v + b, 0, None), g), c * v)
        a, b, c, d, e, f = p[1:7]
        return lambda v: np.where(v >= d, np.power(np.clip(a * v + b, 0, None), g) + e, c * v + f)
    return None


class Converter:
    def __init__(self, curves, rgb_to_xyz_d50):
        self.curves = curves
        self.m = XYZ_D50_TO_SRGB @ np.asarray(rgb_to_xyz_d50, dtype=np.float64)

    def __call__(self, img):
        """Float path for HxWx3 encoded values (small images, tests)."""
        x = np.asarray(img, dtype=np.float64)
        lin = np.stack([self.curves[k](x[..., k]) for k in range(3)], -1)
        return srgb_encode(lin @ self.m.T).astype(np.float32)

    def from_codes(self, codes, levels):
        """Fast path for integer codes HxWx3 (or more channels: extra ones ignored)."""
        xs = np.arange(levels, dtype=np.float64) / (levels - 1)
        luts = [np.asarray(self.curves[k](xs), dtype=np.float32) for k in range(3)]
        if any(not np.isfinite(t).all() for t in luts):
            raise ValueError("tone curve gives non-finite values")
        m = self.m.astype(np.float32)
        enc = _enc_table()
        top = np.float32(ENC_SIZE - 1)
        h, w = codes.shape[:2]
        out = np.empty((h, w, 3), np.float32)

        def job(a, b):
            c = codes[a:b]
            r, g, bl = luts[0][c[..., 0]], luts[1][c[..., 1]], luts[2][c[..., 2]]
            for k in range(3):
                v = m[k, 0] * r
                v += m[k, 1] * g
                v += m[k, 2] * bl
                np.clip(v, 0.0, 1.0, out=v)
                v *= top
                v += 0.5
                out[a:b, :, k] = enc[v.astype(np.int32)]
        _rows(h, job)
        return out


def from_icc(data):
    """Converter for a matrix/TRC RGB profile, else None (unusable or other kind of profile)."""
    tags = _tags(data or b"")
    if tags is None or data[16:20] != b"RGB " or data[20:24] != b"XYZ ":
        return None
    cols = [_xyz(tags.get(s)) for s in (b"rXYZ", b"gXYZ", b"bXYZ")]
    curves = [_curve(tags.get(s)) for s in (b"rTRC", b"gTRC", b"bTRC")]
    if any(c is None for c in cols) or any(c is None for c in curves):
        return None
    return Converter(curves, np.array(cols).T)


def from_nclx(nclx):
    """Converter for nclx colour information: primaries 12 (Display P3) -> P3 with the sRGB curve; else None."""
    if not nclx or nclx.get("color_primaries") != 12:
        return None
    return Converter([srgb_decode] * 3, P3_TO_XYZ_D50)


def littlecms_8bit(img, icc):
    """Fallback for other ICC profiles (LUT based): LittleCMS at 8 bits (known precision limit)."""
    import io

    from PIL import Image, ImageCms
    src = Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    out = ImageCms.profileToProfile(src, prof, srgb, outputMode="RGB")
    return (np.asarray(out, dtype=np.float32) / 255.0)
