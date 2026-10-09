"""Exporting photos at full resolution (CONTRACT-export X1-X15, XP1-XP34; CONTRACT-s2-export-detect E1-E15, E21).

Every rule of an export lives here: the export settings (`normalize_settings`, the one rule for format, bit depth,
quality, size limit, resize, metadata and output sharpening, E1 / E2), request checks (invalid -> 400 / 2 /
isError), per-item checks (an item that fails is `ok:false` in `results`, the others go on), the final parameters
(the preview's own functions, X2; the photo library's saved edit when an item names none, E15), the output folder
(X8), names (X9) and the three-stage pipeline (XP7, E11):

    read (one reader thread, in order) -> render on the Engine's darkroom-gpu executor (full resolution, one export
    job at a time) -> resize + output sharpening + quantise + encode + write (two writer threads)

with at most MAX_IN_FLIGHT full-resolution images between "read started" and "written". Encoding runs on both
writer threads at once, but names are claimed strictly in item order (seal F2: two photos with the same stem get
`{stem}` and `{stem} (2)` in list order, every time). Any exception while reading a photo makes only that item fail
(seal F1: OpenCV raises cv2.error, not ValueError, on some damaged TIFFs). Files are written only
through `safe_write.create_new` into the export folder, which is that call's root, with the preset folder in use
(CONTRACT-write-guard G10, export XP10 / XP12). `SafeWriteRefused` is never caught here (G8).
"""
import contextlib
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from darkroom import read_image

from .. import encoding
from .. import messages as M
from .. import preview as semantics
from .. import safe_write
from ..errors import DarkroomError
from . import on_gpu
from .photo_library import fingerprint
from .photos import _photo_ext

EXPORT_DIR = "darkroom 匯出"            # verbatim (X8)
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
LUMA = (0.2126, 0.7152, 0.0722)         # verbatim (E10)
WEBP_MAX_EDGE = 16383                   # verbatim (E6)
COPYRIGHT_TAG = 33432
N_MAX = 9999                            # verbatim (XP2)
MAX_IN_FLIGHT = 3                       # verbatim (XP7)
ITEM_KEYS = ("image_id", "path", "preset_id", "strength", "overrides")
PARAM_KEYS = ("preset_id", "strength", "overrides")


# ---------------------------------------------------------------------- settings (E1, E2)
def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) and math.isfinite(v)


def _invalid(text):
    return DarkroomError("invalid", text)


def _resize(r):
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
    """E8: (w', h') of an upright width x height image; never enlarged (s >= 1 keeps the size)."""
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


def output_sharpen(rgb, target, amount):
    """E10: x' = clip(x + a * (Y - GaussianBlur(Y, sigma)), 0, 1) on sRGB-encoded float RGB, one difference for the
    three channels (no colour fringes)."""
    import cv2
    import numpy as np
    sigma, a = SHARPEN[target][amount]
    y = (rgb[..., 0] * LUMA[0] + rgb[..., 1] * LUMA[1] + rgb[..., 2] * LUMA[2]).astype(np.float32)
    d = (y - cv2.GaussianBlur(y, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REFLECT_101)) * a
    return np.clip(rgb + d[..., None], 0.0, 1.0)


def filtered_exif(exif, metadata, remove_gps):
    """E9: the EXIF written for a metadata choice (None = no EXIF at all)."""
    if exif is None or metadata == "none":
        return None
    if metadata == "copyright":
        c = exif.get("ifd0", COPYRIGHT_TAG)
        return None if c is None else encoding.Exif({"ifd0": {COPYRIGHT_TAG: c}})
    if remove_gps:
        return encoding.Exif({k: v for k, v in exif.ifds.items() if k != "gps"})
    return exif


# ---------------------------------------------------------------------- jobs
@dataclass
class _Job:
    index: int
    source: str
    path: str
    params: object
    params_from: str


class _Turns:
    """Name claims in submission order: turn(w) waits until claims 0..w-1 are done (or the batch aborts)."""

    def __init__(self, abort):
        self.next, self.abort, self.cv = 0, abort, threading.Condition()

    @contextlib.contextmanager
    def turn(self, w):
        with self.cv:
            while self.next != w:
                if self.abort.is_set():
                    raise _Aborted()
                self.cv.wait(0.05)
        try:
            yield
        finally:
            with self.cv:
                self.next += 1
                self.cv.notify_all()


class _ItemFailed(Exception):
    def __init__(self, source, reason):
        super().__init__(reason)
        self.source, self.reason = source, reason


class _Refused(Exception):
    """An item that cannot be encoded as asked (size limit, WebP size): the reason is a constant sentence."""


def _one_line(e):
    return " ".join(str(e).split()) or type(e).__name__


def _failed(source, reason):
    return {"ok": False, "source": source, "error": M.EXPORT_FAILED.format(file_name=source, reason=reason)}


def _is_oom(e):
    import torch
    return isinstance(e, torch.cuda.OutOfMemoryError)


def _under(path, folder):
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def output_folder(photo, dest_dir):
    """(folder, root for creating it or None): X8."""
    if dest_dir is not None:
        return dest_dir, None
    folder = os.path.dirname(os.path.abspath(photo))
    if os.path.normcase(os.path.basename(folder)) == os.path.normcase(EXPORT_DIR):
        return folder, None
    return os.path.join(folder, EXPORT_DIR), folder


def candidate_names(stem, ext):
    """{stem}.ext, {stem} (2).ext ... {stem} (N_MAX).ext (X9)."""
    yield f"{stem}{ext}"
    for n in range(2, N_MAX + 1):
        yield f"{stem} ({n}){ext}"


def jpeg_within(bgr8, quality, max_kb, exif, icc):
    """E7: (JPEG bytes, quality used). With a size limit: `quality` when the whole file fits, else the highest
    quality in 1..quality-1 whose whole file fits (binary search, at most 8 encodes); _Refused when quality 1 does
    not fit either."""
    data = encoding.jpeg_bytes(bgr8, quality, exif, icc)
    if max_kb is None or len(data) <= max_kb * KB:
        return data, quality
    size1 = len(data) if quality == 1 else None
    lo, hi, best = 1, quality - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        d = encoding.jpeg_bytes(bgr8, mid, exif, icc)
        if mid == 1:
            size1 = len(d)
        if len(d) <= max_kb * KB:
            best, lo = (d, mid), mid + 1
        else:
            hi = mid - 1
    if best is None:
        raise _Refused(M.EXPORT_TOO_BIG_FOR_KB.format(max_kb=max_kb, actual_kb=math.ceil(size1 / KB)))
    return best


class ExportService:
    def __init__(self, library, engine_ref, preset_dir, photo_library, export_presets=None, feature=None):
        self.library = library
        self.engine_ref = engine_ref
        self.preset_dir = preset_dir            # the preset folder in use, for safe_write (XP12)
        self.photo_library = photo_library      # resolve_params / saved_params: the edit's snapshot first (PL5, E15)
        self.export_presets = export_presets    # ExportPresetService (E14)
        self.feature = feature                  # (name) -> (available, reason): capability detection (E23)

    # ------------------------------------------------------------------ checks
    def settings(self, export_preset=None, **given):
        """E14 + E1: the normalised settings of a request (the export preset is looked up first, not_found)."""
        preset = None
        if export_preset is not None:
            _, preset = self.export_presets.find(export_preset)
        return normalize_settings(given, preset)

    def _request(self, items, dest_dir, export_preset, given):
        if not isinstance(items, list) or not items:
            raise DarkroomError("invalid", M.EXPORT_NOTHING)
        s = self.settings(export_preset, **given)
        if dest_dir is not None and (not isinstance(dest_dir, str) or not os.path.isabs(dest_dir)
                                     or not os.path.isdir(dest_dir)):
            raise DarkroomError("invalid", M.EXPORT_NO_DEST.format(dest_dir=dest_dir))
        if s["format"] == "webp" and self.feature is not None:
            ok, reason = self.feature("webp")
            if not ok:
                raise DarkroomError("unavailable", reason)
        return s

    def _source(self, item):
        """(file name shown, photo path) of one item; _ItemFailed when it cannot be exported."""
        image_id = item.get("image_id")
        if image_id is not None:
            eng = self.engine_ref.peek()
            if not isinstance(image_id, str) or eng is None or image_id not in eng.images:
                raise _ItemFailed(str(image_id), M.UNKNOWN_IMAGE)
            try:
                path = eng.get(image_id)["path"]
            except KeyError:
                raise _ItemFailed(image_id, M.UNKNOWN_IMAGE) from None
            return os.path.basename(path), path
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise _ItemFailed("", M.PATH_REQUIRED)
        path = path.strip().strip('"')
        name = os.path.basename(path)
        if not os.path.isfile(path):
            raise _ItemFailed(name, M.PHOTO_NOT_FOUND.format(path=path))
        if os.path.splitext(path)[1].lower() not in _photo_ext():
            raise _ItemFailed(name, M.UNSUPPORTED_FORMAT)
        return name, os.path.abspath(path)

    def _fingerprint(self, name, path):
        try:
            return fingerprint(path)
        except OSError as e:
            raise _ItemFailed(name, _one_line(e)) from None

    def _job(self, index, item, dest_dir):
        if not isinstance(item, dict):
            raise _ItemFailed("", M.EXPORT_ITEM_NOT_OBJECT)
        for key in item:
            if key not in ITEM_KEYS:
                raise _ItemFailed("", M.EXPORT_ITEM_UNKNOWN_KEY.format(key=key))
        name, path = self._source(item)
        if dest_dir is None and _under(os.path.dirname(path), self.preset_dir):      # E21: before any rendering
            raise _ItemFailed(name, M.EXPORT_PHOTO_IN_PRESET_DIR)
        if not any(k in item for k in PARAM_KEYS):        # E15: the photo library's saved edit, or the photo as is
            try:
                final, params_from = self.photo_library.saved_params(path, self._fingerprint(name, path))
            except DarkroomError as e:                    # never silently the original instead
                raise _ItemFailed(name, e.message) from None
            return _Job(index, name, path, final, params_from)
        params = None
        preset_id = item.get("preset_id")
        if preset_id is not None:               # PLP5: the photo is hashed again, the edit's snapshot wins
            fp = self._fingerprint(name, path)
            try:
                params = self.photo_library.resolve_params(fp, preset_id)
            except DarkroomError as e:
                raise _ItemFailed(name, e.message) from None
        try:
            strength = semantics.validate_strength(item.get("strength", 100))
            overrides = semantics.validate_overrides(item.get("overrides"))
        except ValueError as e:
            raise _ItemFailed(name, str(e)) from None
        return _Job(index, name, path, semantics.effective_params(params, strength, overrides), "request")   # X2

    # ------------------------------------------------------------------ the operation
    def export(self, items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None,
               metadata=None, remove_gps=None, sharpen=None, export_preset=None):
        s = self._request(items, dest_dir, export_preset,
                          {"format": format, "bit_depth": bit_depth, "quality": quality, "max_kb": max_kb,
                           "resize": resize, "metadata": metadata, "remove_gps": remove_gps, "sharpen": sharpen})
        results = [None] * len(items)
        jobs = []
        for i, item in enumerate(items):
            try:
                jobs.append(self._job(i, item, dest_dir))
            except _ItemFailed as f:
                results[i] = _failed(f.source, f.reason)
        if jobs:
            for job, res in zip(jobs, self._run(jobs, s, dest_dir)):
                results[job.index] = res
        return {"results": results}

    @staticmethod
    def _render_bits(s):
        """8 or 16: the GPU result. Resizing or sharpening work on the 16-bit result (E11), else the output depth."""
        return 16 if (s["resize"] is not None or s["sharpen"] is not None) else s["bit_depth"]

    def _run(self, jobs, s, dest_dir):
        bits = self._render_bits(s)
        eng = self.engine_ref.get()
        slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
        abort = threading.Event()
        out = [None] * len(jobs)
        turns = _Turns(abort)

        def read(job):
            while not slots.acquire(timeout=0.05):
                if abort.is_set():
                    raise _Aborted()
            try:
                return read_image(job.path), encoding.read_exif(job.path)
            except BaseException:
                slots.release()
                raise

        def write(k, w, job, pixels, exif):
            claimed = []

            def claim():
                claimed.append(w)
                return turns.turn(w)
            try:
                out[k] = self._write(job, pixels, exif, s, bits, dest_dir, claim)
            except BaseException:
                if not claimed:                 # seal N1: turn w must pass even if it never got to claim
                    with turns.turn(w):
                        pass
                raise
            finally:
                slots.release()

        reader = ThreadPoolExecutor(1, thread_name_prefix="darkroom-export-read")
        writer = ThreadPoolExecutor(2, thread_name_prefix="darkroom-export-write")
        writes = []
        try:
            reads = [reader.submit(read, job) for job in jobs]
            for k, (job, rf) in enumerate(zip(jobs, reads)):
                try:
                    image, exif = rf.result()
                except _Aborted:
                    raise
                except Exception as e:      # X12: read_image's reason as is (one line); cv2.error too (seal F1)
                    out[k] = _failed(job.source, _one_line(e))
                    continue
                try:
                    pixels = on_gpu(eng, eng.render_full, image, job.params, bits)
                except Exception as e:                              # X11
                    slots.release()
                    if _is_oom(e):
                        on_gpu(eng, eng.release_cached_memory)
                        out[k] = _failed(job.source, M.EXPORT_OOM)
                    else:
                        out[k] = _failed(job.source, M.EXPORT_RENDER_FAILED.format(detail=_one_line(e)))
                    continue
                finally:
                    del image
                writes.append(writer.submit(write, k, len(writes), job, pixels, exif))
                del pixels
            for wf in writes:
                wf.result()                                         # SafeWriteRefused and the unexpected go out
        finally:
            abort.set()
            reader.shutdown(wait=True, cancel_futures=True)
            writer.shutdown(wait=True, cancel_futures=True)
            on_gpu(eng, eng.release_cached_memory)                  # XP7: reserved memory back after the batch
        return out

    @staticmethod
    def _finish(pixels, s, bits):
        """The rendered pixels -> the encoder's array (E11 order: resize -> sharpen -> quantise): uint8 BGR for an
        8-bit output, uint16 RGB for a 16-bit one."""
        import numpy as np
        if bits == s["bit_depth"] and s["resize"] is None and s["sharpen"] is None:
            return pixels
        import cv2
        x = pixels                                   # uint16 RGB at full resolution (bits 16)
        h, w = x.shape[:2]
        tw, th = resize_target(w, h, s["resize"])
        if (tw, th) != (w, h):
            x = cv2.resize(x, (tw, th), interpolation=cv2.INTER_AREA)
        if s["sharpen"] is None and s["bit_depth"] == 16:
            return np.ascontiguousarray(x)
        f = x.astype(np.float32) * np.float32(1 / 65535)
        if s["sharpen"] is not None:
            f = output_sharpen(f, s["sharpen"]["target"], s["sharpen"]["amount"])
        if s["bit_depth"] == 8:
            return np.ascontiguousarray((f * 255.0 + 0.5).astype(np.uint8)[..., ::-1])
        return np.ascontiguousarray((f * 65535.0 + 0.5).astype(np.uint16))

    @staticmethod
    def _encode(img, s, exif, icc):
        """(bytes, quality used or None) of one finished image."""
        import numpy as np
        fmt = s["format"]
        if fmt == "jpeg":
            return jpeg_within(img, s["quality"], s["max_kb"], exif, icc)
        if fmt == "webp":
            h, w = img.shape[:2]
            if w > WEBP_MAX_EDGE or h > WEBP_MAX_EDGE:
                raise _Refused(M.EXPORT_WEBP_TOO_LARGE.format(width=w, height=h))
            return encoding.webp_bytes(img, s["quality"], exif, icc), s["quality"]
        if fmt == "png":
            bgr = img if img.dtype == np.uint8 else np.ascontiguousarray(img[..., ::-1])
            return encoding.png_bytes(bgr, exif, icc), None
        rgb = img if img.dtype == np.uint16 else np.ascontiguousarray(img[..., ::-1])
        return encoding.tiff_bytes(rgb, exif, icc), None

    def _write(self, job, pixels, exif, s, bits, dest_dir, claim=contextlib.nullcontext):
        icc = encoding.srgb_icc()
        try:
            img = self._finish(pixels, s, bits)
            del pixels
            data, used_quality = self._encode(img, s, filtered_exif(exif, s["metadata"], s["remove_gps"]), icc)
        except _Refused as e:
            with claim():
                return _failed(job.source, str(e))
        except Exception as e:      # cv2.error / struct.error / ValueError refusing the data: this item only (N1)
            with claim():
                return _failed(job.source, M.EXPORT_RENDER_FAILED.format(detail=_one_line(e)))
        h, w = img.shape[:2]
        del img
        used = {"params_from": job.params_from, "quality": used_quality, "width": w, "height": h}   # D1
        with claim():                              # names in item order (seal F2)
            return self._claim(job, data, FORMATS[s["format"]], dest_dir, used)

    def _claim(self, job, data, ext, dest_dir, used):
        folder, make_root = output_folder(job.path, dest_dir)
        stem = os.path.splitext(job.source)[0]
        try:
            if make_root is not None and not os.path.isdir(folder):
                safe_write.make_dirs(folder, make_root, preset_dir=self.preset_dir)      # only this one level
            taken = {n.casefold() for n in os.listdir(folder)}
            for name in candidate_names(stem, ext):
                if name.casefold() in taken:
                    continue
                path = os.path.join(folder, name)
                try:
                    safe_write.create_new(path, folder, data, preset_dir=self.preset_dir)
                except FileExistsError:
                    continue
                return {"ok": True, "source": job.source, "output": path, "used": used}
        except OSError:
            return _failed(job.source, M.EXPORT_CANNOT_WRITE.format(folder=folder))
        return _failed(job.source, M.EXPORT_NAMES_USED_UP.format(stem=stem, n_max=N_MAX))


class _Aborted(Exception):
    pass
