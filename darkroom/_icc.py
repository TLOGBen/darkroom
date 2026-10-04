"""Colour profiles of decoded photos -> the core's sRGB encoding (float precision, numpy).

Matrix/TRC ICC profiles (rXYZ/gXYZ/bXYZ + curv/para curves; Display P3 and sRGB are of this kind):
  tone curve -> linear -> XYZ (D50 PCS) -> linear sRGB (Bradford-adapted D50 matrix) -> clip 0..1 -> sRGB curve.
Colours outside the sRGB gamut are clipped (the renderer works in linear sRGB).
"""
import struct

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


def srgb_decode(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def srgb_encode(v):
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def _s15(b):
    return struct.unpack(">i", b)[0] / 65536.0


def _tags(data):
    if len(data) < 132 or data[36:40] != b"acsp":
        return None
    n = struct.unpack(">I", data[128:132])[0]
    out = {}
    for i in range(n):
        sig, off, size = struct.unpack(">4sII", data[132 + 12 * i: 144 + 12 * i])
        if off + size <= len(data):
            out[sig] = data[off:off + size]
    return out


def _xyz(tag):
    if tag is None or tag[:4] != b"XYZ " or len(tag) < 20:
        return None
    return [_s15(tag[8 + 4 * k: 12 + 4 * k]) for k in range(3)]


def _curve(tag):
    """Tone curve tag -> function mapping encoded 0..1 to linear, or None if unsupported."""
    if tag is None:
        return None
    kind = tag[:4]
    if kind == b"curv":
        n = struct.unpack(">I", tag[8:12])[0]
        if n == 0:
            return lambda v: v
        if n == 1:
            g = struct.unpack(">H", tag[12:14])[0] / 256.0
            return lambda v: np.power(np.clip(v, 0, 1), g)
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


def _converter(curves, rgb_to_xyz_d50):
    m = XYZ_D50_TO_SRGB @ np.asarray(rgb_to_xyz_d50, dtype=np.float64)

    def convert(img):
        x = np.asarray(img, dtype=np.float64)
        lin = np.stack([curves[k](x[..., k]) for k in range(3)], -1)
        return srgb_encode(lin @ m.T).astype(np.float32)
    return convert


def from_icc(data):
    """Converter (HxWx3 encoded -> sRGB-encoded float32) for a matrix/TRC RGB profile, else None."""
    tags = _tags(data or b"")
    if tags is None or data[16:20] != b"RGB " or data[20:24] != b"XYZ ":
        return None
    cols = [_xyz(tags.get(s)) for s in (b"rXYZ", b"gXYZ", b"bXYZ")]
    curves = [_curve(tags.get(s)) for s in (b"rTRC", b"gTRC", b"bTRC")]
    if any(c is None for c in cols) or any(c is None for c in curves):
        return None
    return _converter(curves, np.array(cols).T)


def from_nclx(nclx):
    """Converter for nclx colour information: primaries 12 (Display P3) -> P3 with the sRGB curve; else None."""
    if not nclx or nclx.get("color_primaries") != 12:
        return None
    curve = srgb_decode
    return _converter([curve, curve, curve], P3_TO_XYZ_D50)


def littlecms_8bit(img, icc):
    """Fallback for other ICC profiles (LUT based): LittleCMS at 8 bits (known precision limit)."""
    import io

    from PIL import Image, ImageCms
    src = Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    out = ImageCms.profileToProfile(src, prof, srgb, outputMode="RGB")
    return (np.asarray(out, dtype=np.float32) / 255.0)
