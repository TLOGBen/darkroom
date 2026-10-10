"""Image helpers without business knowledge: content fingerprint, JPEG header reading, thumbnail pixels.

Layer: utils (plan-v2 §1). Imports only the standard library, `darkroom.Geometry` (applying a crop to a thumbnail)
and - lazily, inside the functions that need them - cv2, numpy and pillow-heif, so importing this module stays light
(the edit / thumbnails CLI commands never load torch or cv2 unless a thumbnail is actually made, L9 / PLP8).
It never writes a file; `fingerprint` reads one photo in 1 MiB chunks and nothing else here opens a file.

Who uses what:
* `fingerprint` / `fingerprint_bytes` - the photo library's photo identity (CONTRACT-photo-library PL2): the SHA-256
  of the whole file, nothing but the bytes. open_photo, previews, exports and the edit commands all use this one.
* `jpeg_info` / `jpeg_size` - a JPEG's size, EXIF orientation and embedded thumbnail from its header (no decode);
  thumbnails use the embedded preview, the semantic index sizes its four calibration photos with it.
* `make_thumbnail` / `apply_geometry` - the 256 px thumbnail pixels (PL11, CONTRACT-s3-crop C18).

The constants marked verbatim are pinned by the contracts; services/photo_library.py re-exports them.

Contract codes: PL2 = a photo is identified by the SHA-256 of its bytes only (moving / renaming keeps its edit);
PL11 = thumbnail size, quality and which source is used; B4 = previews are at most 1.5 MP; C18 = the cached
thumbnail is the unedited original and the saved crop is applied when it is served; L9 / PLP8 = the CLI's library
commands stay free of heavy imports.
"""
import hashlib
import math
import struct

from darkroom import Geometry

THUMB_LONG_EDGE = 256                                    # verbatim (PL11)
THUMB_QUALITY = 80                                       # verbatim (PL11)
EMBEDDED_MIN_EDGE = 160                                  # verbatim (PL11)
EMBEDDED_ASPECT_TOL = 0.01                               # verbatim (PL11)
CHUNK = 1 << 20                                          # fingerprint read size: 1 MiB
PREVIEW_MAX_PIXELS = 1500000                             # verbatim constant (B4): the App's preview size limit
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}   # JPEG start-of-frame markers


# ---------------------------------------------------------------------- fingerprint (PL2)
def fingerprint(path):
    """SHA-256 (lower-case hex) of the whole file, read in 1 MiB chunks: nothing but the bytes (PL2).

    One reusable buffer (readinto) keeps memory flat for a 100 MB TIFF; OSError goes to the caller, which turns it
    into the photo's read error sentence."""
    h = hashlib.sha256()
    buf = bytearray(CHUNK)
    view = memoryview(buf)
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            h.update(view[:n])
    return h.hexdigest()


def fingerprint_bytes(data):
    """The same fingerprint for bytes already in memory (the thumbnail worker reads a photo once for both)."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------- preview size (B4)
def preview_size(width, height, limit=PREVIEW_MAX_PIXELS):
    """Largest size with the photo's aspect ratio and width * height <= limit (never upscaled).

    Pure arithmetic, so the preview service can tell the output size without importing torch; the Engine
    (adapters/gpu/engine.py) re-exports it as `engine.preview_size`."""
    if width * height <= limit:
        return width, height
    s = math.sqrt(limit / (width * height))
    pw = max(1, int(width * s))
    ph = max(1, round(pw * height / width))
    while pw * ph > limit:
        pw -= 1
        ph = max(1, round(pw * height / width))
    return pw, ph


# ---------------------------------------------------------------------- JPEG headers
def _tiff_ifd(t, e, off):
    """{tag: value} of the SHORT / LONG single-value entries of one IFD, plus the next IFD offset."""
    out = {}
    (n,) = struct.unpack_from(e + "H", t, off)
    for i in range(n):
        tag, typ, count = struct.unpack_from(e + "HHI", t, off + 2 + 12 * i)
        if count == 1 and typ in (3, 4):
            out[tag] = struct.unpack_from(e + ("H" if typ == 3 else "I"), t, off + 2 + 12 * i + 8)[0]
    (nxt,) = struct.unpack_from(e + "I", t, off + 2 + 12 * n)
    return out, nxt


def jpeg_info(data):
    """(width, height, orientation, embedded thumbnail bytes or None, thumbnail orientation) of JPEG bytes.

    Walks the markers up to the first scan: SOF gives the size, the first APP1 Exif segment gives IFD0's
    Orientation (274) and IFD1's JPEGInterchangeFormat (513) / Length (514). A damaged EXIF block is ignored
    (orientation 1, no thumbnail); width / height are None when no SOF is found."""
    w = h = None
    orientation, thumb, thumb_orient = 1, None, None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        m = data[pos + 1]
        if m == 0xFF:
            pos += 1
            continue
        if m in (0x01, 0xD8) or 0xD0 <= m <= 0xD7:
            pos += 2
            continue
        if m in (0xD9, 0xDA):
            break
        (n,) = struct.unpack_from(">H", data, pos + 2)
        seg = data[pos + 4:pos + 2 + n]
        if m in _SOF and len(seg) >= 5:
            h, w = struct.unpack_from(">HH", seg, 1)
        elif m == 0xE1 and seg[:6] == b"Exif\0\0" and thumb is None:
            try:
                t = seg[6:]
                e = "<" if t[:2] == b"II" else ">"
                (ifd0,) = struct.unpack_from(e + "I", t, 4)
                tags0, nxt = _tiff_ifd(t, e, ifd0)
                orientation = tags0.get(274, 1) if tags0.get(274, 1) in range(1, 9) else 1
                if nxt:
                    tags1, _ = _tiff_ifd(t, e, nxt)
                    o, ln = tags1.get(513), tags1.get(514)
                    if o and ln and o + ln <= len(t):
                        thumb = bytes(t[o:o + ln])
                        thumb_orient = tags1.get(274)
            except struct.error:
                pass
        pos += 2 + n
    return w, h, orientation, thumb, thumb_orient


def jpeg_size(data):
    """(width, height) of JPEG bytes from the header only (None, None when there is no SOF)."""
    w, h, _, _, _ = jpeg_info(data)
    return w, h


# ---------------------------------------------------------------------- thumbnail pixels (PL11, C18)
def turn(a, orientation):
    """Display orientation of an HxWxC array by EXIF Orientation (as PIL ImageOps.exif_transpose)."""
    if orientation == 2:
        return a[:, ::-1]
    if orientation == 3:
        return a[::-1, ::-1]
    if orientation == 4:
        return a[::-1]
    if orientation == 5:
        return a.transpose(1, 0, 2)
    if orientation == 6:
        return a.transpose(1, 0, 2)[:, ::-1]
    if orientation == 7:
        return a.transpose(1, 0, 2)[::-1, ::-1]
    if orientation == 8:
        return a.transpose(1, 0, 2)[::-1]
    return a


def fit(w, h):
    """Size with the long edge at most THUMB_LONG_EDGE (never upscaled)."""
    long = max(w, h)
    if long <= THUMB_LONG_EDGE:
        return w, h
    s = THUMB_LONG_EDGE / long
    return max(1, round(w * s)), max(1, round(h * s))


def embedded_ok(tw, th, fw, fh):
    """PL11: the turned embedded thumbnail is big enough and has the full image's aspect ratio (no letterbox)."""
    if max(tw, th) < EMBEDDED_MIN_EDGE or not fw or not fh:
        return False
    return abs(tw / th - fw / fh) / (fw / fh) <= EMBEDDED_ASPECT_TOL


def make_thumbnail(data, ext):
    """JPEG q80 bytes with the long edge <= 256 in display orientation, from one copy of the file bytes (PL11).

    The cheapest source that is good enough wins: (1) the embedded EXIF / libheif thumbnail when it is at least
    160 px and has the photo's aspect ratio, (2) a JPEG decoded at 1/8, 1/4 or 1/2 scale, (3) a full 8-bit decode.
    Raises ValueError (or cv2 / pillow-heif errors) when the bytes cannot be decoded; the caller words the failure."""
    import cv2
    import numpy as np
    arr = None
    if ext in (".jpg", ".jpeg"):
        w, h, orientation, thumb, thumb_orient = jpeg_info(data)
        if w is None or h is None:
            raise ValueError("cannot decode image")
        fw, fh = (h, w) if orientation in (5, 6, 7, 8) else (w, h)
        if thumb is not None:                                                  # (1) embedded thumbnail
            t = cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            if t is not None:
                t = turn(t, thumb_orient if thumb_orient in range(1, 9) else orientation)
                if embedded_ok(t.shape[1], t.shape[0], fw, fh):
                    arr = t
        if arr is None:                                                        # (2) reduced decode
            flag = cv2.IMREAD_COLOR
            for n, f in ((8, cv2.IMREAD_REDUCED_COLOR_8), (4, cv2.IMREAD_REDUCED_COLOR_4),
                         (2, cv2.IMREAD_REDUCED_COLOR_2)):
                if max(w, h) // n >= THUMB_LONG_EDGE:
                    flag = f
                    break
            a = cv2.imdecode(np.frombuffer(data, np.uint8), flag | cv2.IMREAD_IGNORE_ORIENTATION)
            if a is None:
                raise ValueError("cannot decode image")
            arr = turn(a, orientation)
    elif ext in (".heic", ".heif"):
        import io
        import pillow_heif
        hf = pillow_heif.open_heif(io.BytesIO(data))
        fw, fh = hf.size
        if hf.info.get("thumbnails"):                                          # (1) libheif thumbnail, upright
            t = np.asarray(hf[0].get_thumbnail(0).to_pillow().convert("RGB"))[..., ::-1]
            if embedded_ok(t.shape[1], t.shape[0], fw, fh):
                arr = t
        if arr is None:                                                        # (3) full decode, 8-bit
            arr = np.asarray(hf.to_pillow().convert("RGB"))[..., ::-1]
    else:                                                                      # (3) PNG / TIFF: cv2 turns TIFF
        a = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if a is None:
            raise ValueError("cannot decode image")
        arr = a
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    nw, nh = fit(w, h)
    if (nw, nh) != (w, h):
        arr = cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, THUMB_QUALITY])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


def apply_geometry(jpeg, geometry):
    """CONTRACT-s3-crop C18: the photo's geometry on a 256 px thumbnail (CPU, never enlarged), JPEG q80 again.

    The cached thumbnail is always the original's; the crop / rotation of the saved edit is applied on the way out.
    Bytes that do not decode are returned as they are (the grid still shows something)."""
    import cv2
    import numpy as np
    a = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if a is None:
        return jpeg
    out = Geometry.from_dict(geometry).apply(a)
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(out), [cv2.IMWRITE_JPEG_QUALITY, THUMB_QUALITY])
    return buf.tobytes() if ok else jpeg
