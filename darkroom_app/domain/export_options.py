"""Export options: the 8 export settings and their one normalisation rule (CONTRACT-s2-export-detect E1, E2, E7-E10).

Layer: domain (plan-v2 §1: `ExportOptions`). Pure: no file, no GPU. `services/export.py` (the export itself) and
`services/export_presets.py` (named settings kept in the data folder) both judge settings with `normalize_settings`,
so a setting that is refused is refused with the same sentence whichever way it arrives.

    format (jpeg | png | tiff | webp), bit_depth (8 | 16), quality (1..100, JPEG / WebP), max_kb (JPEG only),
    resize ({mode, value}, never enlarging), metadata (all | copyright | none), remove_gps, sharpen ({target, amount})

Every key is present after normalisation, checked in the E2 order; each value is: the value given now (not None)
-> the export preset's -> the constant default. bit_depth, quality and max_kb depend on the format, so the preset's
are used only when the final format is the preset's own (IP5).

Contract codes used here (CONTRACT-s2-export-detect unless noted): E1 = the settings, their defaults and the
"given now -> export preset -> default" priority; E2 = the order settings are checked in (decides which sentence a
request with several mistakes gets); E7 = max_kb (JPEG file size cap, 10..1048576 KB, 1 KB = 1024 bytes); E8 = resize
only ever shrinks; E9 = which metadata is kept; E10 = output sharpening for screen / matte / glossy; E12 = the export
presets file; IP5 = format-bound settings come from a preset only when the format matches; X4 / X13 / XP31
(CONTRACT-export) = JPEG quality default 92, quality is ignored for PNG / TIFF, the "unsupported format" sentence.
"""
import math

from . import messages as M
from .errors import DarkroomError
from ..utils.text import is_int as _is_int

DEFAULT_QUALITY = 92                    # verbatim (X4)
FORMATS = {"jpeg": ".jpg", "png": ".png", "tiff": ".tif", "webp": ".webp"}   # verbatim values / extensions (E1)
DEFAULT_BITS = {"jpeg": 8, "png": 8, "tiff": 16, "webp": 8}                   # verbatim (E1, D14)
SETTING_KEYS = ("format", "bit_depth", "quality", "max_kb", "resize", "metadata", "remove_gps", "sharpen")   # E1
RESIZE_MODES = ("long_edge", "short_edge", "width", "height", "megapixels", "percent")                       # E8
EDGE_MAX = 65535
MP_MAX, PERCENT_MAX = 1000, 100
MAX_KB_MIN, MAX_KB_MAX = 10, 1048576    # verbatim (E7)
KB = 1024                               # verbatim (E7, D13)
METADATA = ("all", "copyright", "none")  # verbatim (E9)
SHARPEN = {"screen": {"low": (0.5, 0.35), "standard": (0.6, 0.55), "high": (0.7, 0.80)},
           "glossy": {"low": (0.7, 0.45), "standard": (0.8, 0.70), "high": (1.0, 1.00)},
           "matte": {"low": (0.8, 0.60), "standard": (1.0, 0.90), "high": (1.2, 1.25)}}   # verbatim (E10): (sigma, a)
SHARPEN_TARGETS, SHARPEN_AMOUNTS = ("screen", "matte", "glossy"), ("low", "standard", "high")
EXPORT_PRESETS_FILE = "export-presets.json"             # verbatim (E12): data_dir/export-presets.json
EXPORT_PRESETS_SCHEMA = "darkroom-export-presets/1"     # verbatim (E12)


def _is_num(v):
    """A finite JSON number (bool excluded)."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) and math.isfinite(v)


def _invalid(text):
    """The error every refused setting raises (kind invalid, sentence unchanged)."""
    return DarkroomError("invalid", text)


def _resize(r):
    """Check a resize object {mode, value}: edges 1..65535 px (integers), megapixels (0, 1000], percent (0, 100]."""
    if not isinstance(r, dict) or set(r) != {"mode", "value"}:
        raise _invalid(M.EXPORT_BAD_RESIZE + str(r))
    mode, v = r["mode"], r["value"]
    if not isinstance(mode, str) or mode not in RESIZE_MODES:
        raise _invalid(M.EXPORT_BAD_RESIZE_MODE.format(mode=mode))
    if mode == "megapixels":
        if not _is_num(v) or not 0 < v <= MP_MAX:
            raise _invalid(M.EXPORT_BAD_RESIZE_MP.format(value=v))
    elif mode == "percent":
        if not _is_num(v) or not 0 < v <= PERCENT_MAX:
            raise _invalid(M.EXPORT_BAD_RESIZE_PERCENT.format(value=v))
    elif not _is_int(v) or not 1 <= v <= EDGE_MAX:
        raise _invalid(M.EXPORT_BAD_RESIZE_EDGE.format(mode=mode, value=v))
    return {"mode": mode, "value": v}


def _sharpen(s):
    """Check a sharpen object {target: screen | matte | glossy, amount: low | standard | high}."""
    if not isinstance(s, dict) or set(s) != {"target", "amount"}:
        raise _invalid(M.EXPORT_BAD_SHARPEN + str(s))
    if not isinstance(s["target"], str) or s["target"] not in SHARPEN_TARGETS:
        raise _invalid(M.EXPORT_BAD_SHARPEN_TARGET.format(target=s["target"]))
    if not isinstance(s["amount"], str) or s["amount"] not in SHARPEN_AMOUNTS:
        raise _invalid(M.EXPORT_BAD_SHARPEN_AMOUNT.format(amount=s["amount"]))
    return {"target": s["target"], "amount": s["amount"]}


def normalize_settings(given, preset=None):
    """E1 / E2: the 8 export settings, every key present, checked in the E2 order. Each key: the value given now
    (not None) -> the export preset's -> the constant default. bit_depth, quality and max_kb depend on the format,
    so the preset's are used only when the final format is the preset's own (IP5). DarkroomError invalid with the
    constant sentence on the first bad value."""
    given = {k: given.get(k) for k in SETTING_KEYS}
    pre = preset or {}

    def pick(key, same=True):
        if given[key] is not None:
            return given[key]
        return pre.get(key) if same else None

    fmt = pick("format")
    fmt = "jpeg" if fmt is None else fmt
    if not isinstance(fmt, str) or fmt not in FORMATS:
        raise _invalid(M.EXPORT_BAD_FORMAT.format(format=fmt))
    same = bool(pre) and pre.get("format") == fmt
    bits = pick("bit_depth", same)
    bits = DEFAULT_BITS[fmt] if bits is None else bits
    if not _is_int(bits) or bits not in (8, 16):
        raise _invalid(M.EXPORT_BAD_BIT_DEPTH.format(bit_depth=bits))
    if bits == 16 and fmt == "jpeg":
        raise _invalid(M.EXPORT_JPEG_8BIT.format(bit_depth=bits))
    if bits == 16 and fmt == "webp":
        raise _invalid(M.EXPORT_WEBP_8BIT.format(bit_depth=bits))
    quality = None
    if fmt in ("jpeg", "webp"):                         # png / tiff: ignored, never judged (X13, XP31)
        quality = pick("quality", same)
        quality = DEFAULT_QUALITY if quality is None else quality
        if not _is_int(quality) or not 1 <= quality <= 100:
            text = M.EXPORT_BAD_QUALITY if fmt == "jpeg" else M.EXPORT_BAD_WEBP_QUALITY
            raise _invalid(text.format(quality=quality))
    max_kb = given["max_kb"]
    if max_kb is not None and fmt != "jpeg":
        raise _invalid(M.EXPORT_MAX_KB_JPEG_ONLY)
    if max_kb is None and same:
        max_kb = pre.get("max_kb")
    if max_kb is not None and (not _is_int(max_kb) or not MAX_KB_MIN <= max_kb <= MAX_KB_MAX):
        raise _invalid(M.EXPORT_BAD_MAX_KB.format(max_kb=max_kb))
    resize = pick("resize")
    resize = None if resize is None else _resize(resize)
    metadata = pick("metadata")
    metadata = "all" if metadata is None else metadata
    if not isinstance(metadata, str) or metadata not in METADATA:
        raise _invalid(M.EXPORT_BAD_METADATA.format(metadata=metadata))
    remove_gps = pick("remove_gps")
    remove_gps = False if remove_gps is None else remove_gps
    if not isinstance(remove_gps, bool):
        raise _invalid(M.EXPORT_BAD_REMOVE_GPS)
    sharpen = pick("sharpen")
    sharpen = None if sharpen is None else _sharpen(sharpen)
    return {"format": fmt, "bit_depth": bits, "quality": quality, "max_kb": max_kb, "resize": resize,
            "metadata": metadata, "remove_gps": remove_gps, "sharpen": sharpen}


def resize_target(width, height, resize):
    """E8: (w', h') of an upright width x height image; never enlarged (s >= 1 keeps the size).

    s is the scale factor the mode asks for. The constrained edge gets exactly the requested pixels and the other
    edge is rounded half up, so "long edge 2048" really yields 2048. Megapixels floors both edges so the result
    never exceeds the requested pixel count. Every edge is at least 1 px."""
    if resize is None:
        return width, height
    mode, v = resize["mode"], resize["value"]
    s = {"long_edge": lambda: v / max(width, height), "short_edge": lambda: v / min(width, height),
         "width": lambda: v / width, "height": lambda: v / height,
         "megapixels": lambda: math.sqrt(v * 1e6 / (width * height)), "percent": lambda: v / 100}[mode]()
    if s >= 1:
        return width, height

    def rnd(x):
        return max(1, math.floor(x + 0.5))
    if mode == "megapixels":
        return max(1, math.floor(width * s)), max(1, math.floor(height * s))
    if mode == "percent":
        return rnd(width * s), rnd(height * s)
    if mode == "width" or (mode == "long_edge" and width >= height) or (mode == "short_edge" and width <= height):
        return v, rnd(height * s)
    return rnd(width * s), v
