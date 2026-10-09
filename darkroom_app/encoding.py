"""Export file bytes (CONTRACT-export X4, X5, X7, XP10). Builds bytes in memory only; never opens a file to write.

* JPEG: `cv2.imencode` (8-bit, the given quality), then an APP1 `Exif` segment and an APP2 `ICC_PROFILE` segment
  (the sRGB profile) are spliced in after the JFIF APP0 segment.
* TIFF: a 16-bit RGB baseline TIFF assembled here: IFD0 (pixels in strips, ICC 34675, the source's IFD0 metadata),
  the Exif sub-IFD (34665, with its Interop IFD 40965) and the GPS sub-IFD (34853). Little-endian.

EXIF from the source photo (`read_exif`): IFD0, Exif and GPS IFDs of a JPEG's first APP1 Exif segment, of a TIFF
file's IFD0, or of a HEIC's Exif item; PNG never carries EXIF here. IFD1 (the thumbnail) is never read, so it is
never written. On output: Orientation is 1 (pixels are upright), PixelXDimension / PixelYDimension (when present)
are the output size, every tag occurs once per IFD, image-structure tags of the source are dropped.
"""
import os
import struct

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
_NUM = {3: "H", 4: "I", 5: "II", 8: "h", 9: "i", 10: "ii", 11: "f", 12: "d", 13: "I"}
_BYTES = (1, 2, 6, 7)
EXIF_IFD, GPS_IFD, INTEROP_IFD = 34665, 34853, 40965
ORIENTATION, ICC_TAG = 274, 34675
PIXEL_X, PIXEL_Y = 40962, 40963
MAKER_NOTE = 37500
# image structure / pointers / colour that describe the source file's pixels, never copied from IFD0
_IFD0_DROP = frozenset({254, 255, 256, 257, 258, 259, 262, 263, 266, 273, 274, 277, 278, 279, 280, 281, 284, 288,
                        289, 290, 291, 292, 293, 317, 318, 319, 320, 322, 323, 324, 325, 330, 338, 339, 340, 341,
                        347, 512, 513, 514, 515, 517, 518, 519, 520, 521, 529, 530, 531, 532, 700, ICC_TAG,
                        EXIF_IFD, GPS_IFD, 34692, 37724})
APP1_MAX = 65533 - 2          # segment length field counts itself


class Exif:
    """Parsed EXIF: {ifd name: {tag: (type, count, little-endian payload)}} for ifd0, exif, gps, interop."""

    def __init__(self, ifds):
        self.ifds = ifds

    def get(self, ifd, tag):
        return self.ifds.get(ifd, {}).get(tag)


# ---------------------------------------------------------------- reading
def _read_ifd(t, e, off):
    """{tag: (type, count, LE payload)} of the IFD at `off`; entries that do not fit are skipped."""
    (n,) = struct.unpack_from(e + "H", t, off)
    out = {}
    for i in range(n):
        tag, typ, count, raw = struct.unpack_from(e + "HHI4s", t, off + 2 + 12 * i)
        size = TYPE_SIZE.get(typ)
        if size is None or count == 0 or tag in out:
            continue
        nbytes = size * count
        if nbytes <= 4:
            data = raw[:nbytes]
        else:
            (at,) = struct.unpack(e + "I", raw)
            if at + nbytes > len(t):
                continue
            data = t[at:at + nbytes]
        if typ not in _BYTES and e != "<":
            fmt = _NUM[typ]
            vals = struct.unpack(e + fmt * count, data)
            data = struct.pack("<" + fmt * count, *vals)
        out[tag] = (typ, count, bytes(data))
    return out


def _pointer(entries, tag):
    v = entries.pop(tag, None)
    if v is None or v[0] not in (4, 13) or v[1] != 1:
        return None
    return struct.unpack("<I", v[2])[0]


def parse_tiff_exif(t, ifd0_drop=()):
    """Exif from TIFF-structured bytes (header at 0); None when it holds nothing usable."""
    if t[:4] == b"II*\0":
        e = "<"
    elif t[:4] == b"MM\0*":
        e = ">"
    else:
        return None
    try:
        (off,) = struct.unpack_from(e + "I", t, 4)
        ifd0 = _read_ifd(t, e, off)
        ifds = {"ifd0": ifd0}
        exif_at, gps_at = _pointer(ifd0, EXIF_IFD), _pointer(ifd0, GPS_IFD)
        if exif_at:
            ifds["exif"] = _read_ifd(t, e, exif_at)
            interop_at = _pointer(ifds["exif"], INTEROP_IFD)
            if interop_at:
                ifds["interop"] = _read_ifd(t, e, interop_at)
        if gps_at:
            ifds["gps"] = _read_ifd(t, e, gps_at)
    except struct.error:
        return None
    for tag in ifd0_drop:
        ifd0.pop(tag, None)
    ifd0.pop(ORIENTATION, None)
    if not any(ifds.values()):
        return None
    return Exif(ifds)


def _jpeg_app1_exif(data):
    if data[:2] != b"\xff\xd8":
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        m = data[pos + 1]
        if m == 0xFF:
            pos += 1
            continue
        if m in (0x01, 0xD8) or 0xD0 <= m <= 0xD7:
            pos += 2
            continue
        if m in (0xD9, 0xDA):
            return None
        (n,) = struct.unpack_from(">H", data, pos + 2)
        seg = data[pos + 4:pos + 2 + n]
        if m == 0xE1 and seg[:6] == b"Exif\0\0":
            return seg[6:]
        pos += 2 + n
    return None


def read_exif(path):
    """Exif of the source photo (read-only), or None (no EXIF, PNG, unreadable metadata)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        with open(path, "rb") as f:
            t = _jpeg_app1_exif(f.read())
        return None if t is None else parse_tiff_exif(t, _IFD0_DROP)
    if ext in (".tif", ".tiff"):
        with open(path, "rb") as f:
            return parse_tiff_exif(f.read(), _IFD0_DROP)
    if ext in (".heic", ".heif"):
        try:
            import pillow_heif
            raw = pillow_heif.open_heif(path).info.get("exif")
        except Exception:          # the photo itself was already read; metadata problems only drop EXIF
            return None
        if not raw:
            return None
        return parse_tiff_exif(raw[6:] if raw[:6] == b"Exif\0\0" else raw, _IFD0_DROP)
    return None


# ---------------------------------------------------------------- writing
def _entry(typ, values):
    if typ in _BYTES:
        data = bytes(values)
        return typ, len(data), data
    fmt = _NUM[typ]
    flat = [x for v in values for x in (v if isinstance(v, tuple) else (v,))]
    return typ, len(values), struct.pack("<" + fmt[0] * len(flat), *flat)


def _ifd_block(entries, start, next_ifd=0):
    """IFD (sorted tags) + its out-of-line data, placed at offset `start` (offsets from the TIFF header)."""
    tags = sorted(entries)
    data_at = start + 2 + 12 * len(tags) + 4
    head, data = [struct.pack("<H", len(tags))], bytearray()
    for tag in tags:
        typ, count, payload = entries[tag]
        if len(payload) <= 4:
            head.append(struct.pack("<HHI", tag, typ, count) + payload.ljust(4, b"\0"))
        else:
            if (data_at + len(data)) % 2:
                data += b"\0"                    # word-aligned values
            head.append(struct.pack("<HHII", tag, typ, count, data_at + len(data)))
            data += payload
    head.append(struct.pack("<I", next_ifd))
    out = b"".join(head) + bytes(data)
    return out + (b"\0" if len(out) % 2 else b"")


def _layout(ifd0, subs, start):
    """bytes of IFD0 followed by its sub-IFDs [(pointer tag in parent, parent name, name, entries)], from `start`."""
    blocks = {"ifd0": dict(ifd0)}
    for ptag, parent, name, entries in subs:
        blocks[name] = dict(entries)
        blocks[parent][ptag] = (4, 1, b"\0\0\0\0")       # placeholder: pointer sizes do not change the layout
    order = ["ifd0"] + [s[2] for s in subs]
    for _ in range(2):                                   # 1st pass sizes, 2nd pass with the real offsets
        at, offsets = start, {}
        for name in order:
            offsets[name] = at
            at += len(_ifd_block(blocks[name], at))
        for ptag, parent, name, _ in subs:
            blocks[parent][ptag] = (4, 1, struct.pack("<I", offsets[name]))
    return b"".join(_ifd_block(blocks[n], offsets[n]) for n in order), at


def _metadata(exif, width, height):
    """(ifd0 entries, [sub IFDs]) of the output; the source's tags, fixed per X7."""
    ifd0 = {ORIENTATION: _entry(3, (1,))}
    subs = []
    if exif is None:
        return ifd0, subs
    ifd0.update(exif.ifds.get("ifd0", {}))
    ifd0[ORIENTATION] = _entry(3, (1,))
    ex = dict(exif.ifds.get("exif", {}))
    for tag, value in ((PIXEL_X, width), (PIXEL_Y, height)):
        if tag in ex:
            ex[tag] = _entry(4, (value,))
    if ex or exif.ifds.get("interop"):
        subs.append((EXIF_IFD, "ifd0", "exif", ex))
        if exif.ifds.get("interop"):
            subs.append((INTEROP_IFD, "exif", "interop", exif.ifds["interop"]))
    if exif.ifds.get("gps"):
        subs.append((GPS_IFD, "ifd0", "gps", exif.ifds["gps"]))
    return ifd0, subs


def exif_tiff_bytes(exif, width, height):
    """TIFF-structured EXIF (header + IFD0 + sub-IFDs) for a JPEG APP1 segment."""
    ifd0, subs = _metadata(exif, width, height)
    body, _ = _layout(ifd0, subs, 8)
    return b"II*\0" + struct.pack("<I", 8) + body


def _segment(marker, body):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(body) + 2) + body


def jpeg_bytes(bgr8, quality, exif, icc):
    """JPEG (8-bit, `quality`) of an HxWx3 BGR uint8 array, with sRGB ICC and (when given) EXIF."""
    import cv2
    ok, enc = cv2.imencode(".jpg", bgr8, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("JPEG encoding failed")
    data = enc.tobytes()
    h, w = bgr8.shape[:2]
    segs = []
    if exif is not None:
        body = b"Exif\0\0" + exif_tiff_bytes(exif, w, h)
        if len(body) > APP1_MAX and exif.get("exif", MAKER_NOTE):          # too big: the maker note goes first
            exif = Exif({k: {t: v for t, v in d.items() if not (k == "exif" and t == MAKER_NOTE)}
                         for k, d in exif.ifds.items()})
            body = b"Exif\0\0" + exif_tiff_bytes(exif, w, h)
        if len(body) <= APP1_MAX:
            segs.append(_segment(0xE1, body))
    segs.append(_segment(0xE2, b"ICC_PROFILE\0\x01\x01" + icc))
    at = 2
    if data[2:4] == b"\xff\xe0":                         # keep JFIF APP0 first
        at = 4 + struct.unpack_from(">H", data, 4)[0]
    return data[:at] + b"".join(segs) + data[at:]


TIFF_ROWS_PER_STRIP = 16


def tiff_bytes(rgb16, exif, icc):
    """16-bit RGB baseline TIFF (uncompressed, contiguous, no alpha) of an HxWx3 uint16 array."""
    import numpy as np
    h, w = rgb16.shape[:2]
    row = w * 3 * 2
    rps = min(TIFF_ROWS_PER_STRIP, h)
    n = (h + rps - 1) // rps
    counts = [row * min(rps, h - i * rps) for i in range(n)]
    ifd0, subs = _metadata(exif, w, h)
    ifd0.update({
        256: _entry(4, (w,)), 257: _entry(4, (h,)), 258: _entry(3, (16, 16, 16)), 259: _entry(3, (1,)),
        262: _entry(3, (2,)), 273: _entry(4, (0,) * n), 277: _entry(3, (3,)), 278: _entry(4, (rps,)),
        279: _entry(4, tuple(counts)), 284: _entry(3, (1,)), 339: _entry(3, (1, 1, 1)), ICC_TAG: (7, len(icc), icc),
    })
    head, end = _layout(ifd0, subs, 8)
    pixels_at = end + (end % 2)
    offsets = tuple(pixels_at + sum(counts[:i]) for i in range(n))
    ifd0[273] = _entry(4, offsets)
    head, end2 = _layout(ifd0, subs, 8)
    assert end2 == end
    out = bytearray(b"II*\0" + struct.pack("<I", 8) + head)
    out += b"\0" * (pixels_at - len(out))
    out += np.ascontiguousarray(rgb16, dtype="<u2").data
    return out


# ---------------------------------------------------------------- the sRGB profile (X5)
# An ICC v4 matrix/TRC display profile written out here, byte for byte the same every time: the D50-adapted
# (Bradford) sRGB colorants as stored in ICC sRGB profiles, the sRGB tone curve as parametricCurveType 3 and the
# Bradford D65 -> D50 'chad'. (LittleCMS's built-in sRGB rounds its colorants differently: pure cyan came back
# with red 0.0025 instead of 0, over X5's 1e-3; its bytes also carry the creation time.)
_D50 = (0.9642, 1.0, 0.8249)
_SRGB_COLORANTS = ((0.4360747, 0.2225045, 0.0139322), (0.3850649, 0.7168786, 0.0971045),
                   (0.1430804, 0.0606169, 0.7141733))
_SRGB_CURVE = (2.4, 1 / 1.055, 0.055 / 1.055, 1 / 12.92, 0.04045)
_BRADFORD_D65_D50 = (1.0478112, 0.0228866, -0.0501270, 0.0295424, 0.9904844, -0.0170491,
                     -0.0092345, 0.0150436, 0.7521316)
_SRGB = []


def _s15(v):
    return struct.pack(">i", int(round(v * 65536)))


def _mluc(text):
    enc = text.encode("utf-16-be")
    return b"mluc" + b"\0" * 4 + struct.pack(">II", 1, 12) + b"enUS" + struct.pack(">II", len(enc), 28) + enc


def _icc_xyz(xyz):
    return b"XYZ " + b"\0" * 4 + b"".join(_s15(v) for v in xyz)


def _srgb_profile():
    curve = b"para" + b"\0" * 4 + struct.pack(">HH", 3, 0) + b"".join(_s15(v) for v in _SRGB_CURVE)
    tags = [(b"desc", _mluc("sRGB IEC61966-2.1 (darkroom)")), (b"cprt", _mluc("No copyright, use freely")),
            (b"wtpt", _icc_xyz(_D50)), (b"chad", b"sf32" + b"\0" * 4 + b"".join(_s15(v) for v in _BRADFORD_D65_D50)),
            (b"rXYZ", _icc_xyz(_SRGB_COLORANTS[0])), (b"gXYZ", _icc_xyz(_SRGB_COLORANTS[1])),
            (b"bXYZ", _icc_xyz(_SRGB_COLORANTS[2])), (b"rTRC", curve), (b"gTRC", curve), (b"bTRC", curve)]
    offset = 128 + 4 + 12 * len(tags)
    entries, data = [], b""
    for sig, body in tags:
        entries.append(struct.pack(">4sII", sig, offset + len(data), len(body)))
        data += body + b"\0" * (-len(body) % 4)
    size = offset + len(data)
    header = (struct.pack(">I", size) + b"\0" * 4 + struct.pack(">I", 0x04300000) + b"mntr" + b"RGB " + b"XYZ "
              + struct.pack(">6H", 2026, 10, 9, 0, 0, 0) + b"acsp" + b"\0" * 4 + b"\0" * 4 + b"\0" * 8
              + b"\0" * 8 + b"\0" * 4 + b"".join(_s15(v) for v in _D50) + b"\0" * 4 + b"\0" * 16 + b"\0" * 28)
    assert len(header) == 128
    return header + struct.pack(">I", len(tags)) + b"".join(entries) + data


def srgb_icc():
    """The sRGB ICC profile embedded in every export (same bytes every time)."""
    if not _SRGB:
        _SRGB.append(_srgb_profile())
    return _SRGB[0]
