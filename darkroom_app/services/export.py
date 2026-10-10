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

Layer: services. Depends on domain (`Adjustment`, `export_options`, errors, messages), utils (encoders, the write
module, fingerprint) and what the composition hands in (the Engine, the photo library, the export presets, the
capability check). The exported files are the one kind of file a service writes directly: they are the product the
user asked for, written into the export folder through the write module's `create_new` (never a store's data).

Why three overlapping stages: a 24 MP export spends comparable time reading / decoding, rendering on the GPU and
encoding / writing. Overlapping them keeps the GPU busy while the CPU threads decode the next photo and encode the
previous one; MAX_IN_FLIGHT bounds the memory (each image in flight is ~300 MB as float32).

Contract codes used here (CONTRACT-export unless noted): X1 / XP2 = request-level checks are invalid for the whole
call; XP17 = a failed item is {ok: false, source, error: "匯出失敗：..."} and the rest continue; X2 = the final
parameters use the same functions as the preview; X8 = the default output folder "<photo folder>/darkroom 匯出";
X9 = names "{stem}.ext", "{stem} (2).ext", ...; X11 = GPU out-of-memory is reported per item and the cache freed;
X12 = a read failure's reason is passed through; XP7 = the three-stage pipeline and its in-flight limit; XP10 /
XP12 / G8 / G10 = files are only written through the guarded write module, protecting the preset folder;
XP35 / C19 = per-item geometry (left out = the saved crop). CONTRACT-s2-export-detect: E1 / E2 = settings and
check order; E6 = WebP limits; E7 = the JPEG size cap; E9 = metadata filtering; E10 = output sharpening; E11 = the
order resize -> sharpen -> quantise; E14 = export presets; E15 = no colour keys = the saved edit; E21 = a photo in
the preset folder is never exported next to it; E23 = WebP availability; D1 = the `used` report per item.
"""
import contextlib
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from darkroom import Geometry, read_image

from ..domain import messages as M
from ..domain.adjustment import DEFAULT_STRENGTH, Adjustment, validate_geometry
from ..domain.errors import DarkroomError
from ..domain.export_options import (DEFAULT_BITS, DEFAULT_QUALITY, EDGE_MAX, FORMATS, KB,  # noqa: F401
                                     MAX_KB_MAX, MAX_KB_MIN, METADATA, MP_MAX, PERCENT_MAX, RESIZE_MODES,
                                     SETTING_KEYS, SHARPEN, SHARPEN_AMOUNTS, SHARPEN_TARGETS, normalize_settings,
                                     resize_target)
from ..utils import encoding
from ..utils import safe_write
from ..utils.imaging import fingerprint
from ..utils.text import one_line as _one_line
from . import on_gpu
from .photos import is_photo_name

EXPORT_DIR = "darkroom 匯出"            # verbatim (X8)
LUMA = (0.2126, 0.7152, 0.0722)         # verbatim (E10)
WEBP_MAX_EDGE = 16383                   # verbatim (E6)
COPYRIGHT_TAG = 33432
N_MAX = 9999                            # verbatim (XP2)
MAX_IN_FLIGHT = 3                       # verbatim (XP7)
ITEM_KEYS = ("image_id", "path", "preset_id", "strength", "overrides", "geometry")   # + geometry (S3 C19)
PARAM_KEYS = ("preset_id", "strength", "overrides", "geometry")     # none of these = the saved edit (E15, XP35)


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
    """One item that passed its checks: where it goes in `results`, its name and path, and what to render."""
    index: int
    source: str
    path: str
    params: object
    params_from: str
    geometry: object = None       # darkroom.Geometry or None (CONTRACT-s3-crop C19)


class _Turns:
    """Name claims in submission order: turn(w) waits until claims 0..w-1 are done (or the batch aborts)."""

    def __init__(self, abort):
        self.next, self.abort, self.cv = 0, abort, threading.Condition()

    @contextlib.contextmanager
    def turn(self, w):
        """Context manager: block until it is claim w's turn, run the body, then let w + 1 go.

        Raises _Aborted when the batch is being torn down, so a waiting writer thread never hangs forever."""
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
    """One item cannot be exported: `source` is the file name shown, `reason` the one-line why."""

    def __init__(self, source, reason):
        super().__init__(reason)
        self.source, self.reason = source, reason


class _Refused(Exception):
    """An item that cannot be encoded as asked (size limit, WebP size): the reason is a constant sentence."""


def _failed(source, reason):
    """The result entry of a failed item (XP17 shape and sentence)."""
    return {"ok": False, "source": source, "error": M.EXPORT_FAILED.format(file_name=source, reason=reason)}


def _is_oom(e):
    """Is `e` CUDA running out of memory? (torch is imported here only; it is already loaded by then)."""
    import torch
    return isinstance(e, torch.cuda.OutOfMemoryError)


def _under(path, folder):
    """Is `path` the folder or inside it, after resolving links and case? False across drives."""
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def output_folder(photo, dest_dir):
    """(folder, root for creating it or None): X8.

    With dest_dir: that folder (it must already exist; nothing is created). Without: "<photo folder>/darkroom 匯出",
    created on demand with the photo's folder as the write root (one level only); a photo that already sits in such
    a folder exports next to itself instead of into a nested one."""
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
    """The export operation (see the module docstring for the whole flow)."""

    def __init__(self, library, engine_ref, preset_dir, photo_library, export_presets=None, feature=None):
        """All dependencies are handed in by the composition; nothing is read from the configuration here."""
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
        """Request-level checks (whole call refused): items non-empty, settings valid, dest_dir an existing absolute
        folder, WebP available. Returns the normalised settings."""
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
        if not is_photo_name(path):

            raise _ItemFailed(name, M.UNSUPPORTED_FORMAT)
        return name, os.path.abspath(path)

    def _fingerprint(self, name, path):
        """Content fingerprint of the photo; a read error fails this item only."""
        try:
            return fingerprint(path)
        except OSError as e:
            raise _ItemFailed(name, _one_line(e)) from None

    def _job(self, index, item, dest_dir):
        """Turn one request item into a _Job (what to read and render), or raise _ItemFailed.

        Without any of preset_id / strength / overrides / geometry the photo library's saved edit decides (E15;
        params_from "edit" or "original"); otherwise the item's own values do (params_from "request")."""
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
                final, params_from, g = self.photo_library.saved_params(path, self._fingerprint(name, path))
            except DarkroomError as e:                    # never silently the original instead
                raise _ItemFailed(name, e.message) from None
            return _Job(index, name, path, final, params_from, Geometry.from_dict(g))
        params = None
        fp = None
        preset_id = item.get("preset_id")
        if preset_id is not None:               # PLP5: the photo is hashed again, the edit's snapshot wins
            fp = self._fingerprint(name, path)
            try:
                params = self.photo_library.resolve_params(fp, preset_id)
            except DarkroomError as e:
                raise _ItemFailed(name, e.message) from None
        try:                                    # VO -> BO; a refused value fails this item only (XP17)
            adj = Adjustment.from_request(item.get("strength", DEFAULT_STRENGTH), item.get("overrides"))
        except DarkroomError as e:
            raise _ItemFailed(name, e.message) from None
        try:                                    # XP35 (D4): left out = the photo's saved geometry, null = none
            if "geometry" in item:
                geometry = validate_geometry(item["geometry"])
            else:
                geometry = Geometry.from_dict(self.photo_library.saved_geometry(
                    fp if fp is not None else self._fingerprint(name, path)))
        except DarkroomError as e:
            raise _ItemFailed(name, e.message) from None
        return _Job(index, name, path, adj.final(params), "request", geometry)                       # X2

    # ------------------------------------------------------------------ the operation
    def export(self, items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None,
               metadata=None, remove_gps=None, sharpen=None, export_preset=None):
        """Export every item -> {"results": [one entry per item, in order]}.

        Raises DarkroomError for request-level problems (nothing exported). Per-item problems become ok:false
        entries. Side effects: new files in the output folder(s) (and the "darkroom 匯出" folder when it was
        missing); photos and presets are never written. SafeWriteRefused propagates (it means a bug)."""
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
        """Run the read -> render -> write pipeline over `jobs`; returns one result per job, in job order.

        The calling thread is the conductor: it takes decoded images from the reader in order, renders them on the
        GPU executor (one at a time) and hands the pixels to the writer pool. A semaphore of MAX_IN_FLIGHT slots is
        taken when a read starts and released when the write ends, which bounds memory. On any escape (abort) every
        pool is shut down and the GPU cache released."""
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
                    extra = () if job.geometry is None else (job.geometry,)    # C19: no geometry = as before
                    pixels = on_gpu(eng, eng.render_full, image, job.params, bits, *extra)
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
        """Finish, encode and write one item (runs on a writer thread) -> its result entry.

        Encoding happens outside the name turn (in parallel); only claiming a file name waits for the turn, so names
        are deterministic while the expensive work overlaps."""
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
        """Write `data` under the first free name in the output folder -> the result entry.

        create_new's O_EXCL makes "free" race-proof against other programs; an OSError (permission, disk full)
        becomes the "cannot write" sentence for this item."""
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
    """Internal: the batch is being torn down; waiting reader / writer threads stop."""
