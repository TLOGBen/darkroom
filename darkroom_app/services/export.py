"""Exporting photos at full resolution (CONTRACT-export X1-X15, XP1-XP15).

Every rule of an export lives here: request checks (invalid -> 400 / 2 / isError), per-item checks (an item that
fails is `ok:false` in `results`, the others go on), the final parameters (the preview's own functions, X2), the
output folder (X8), names (X9) and the three-stage pipeline (XP7):

    read (one reader thread, in order) -> render on the Engine's darkroom-gpu executor (one export job at a
    time) -> encode + write (two writer threads)

with at most MAX_IN_FLIGHT full-resolution images between "read started" and "written". Encoding runs on both
writer threads at once, but names are claimed strictly in item order (seal F2: two photos with the same stem get
`{stem}` and `{stem} (2)` in list order, every time). Any exception while reading a photo makes only that item fail
(seal F1: OpenCV raises cv2.error, not ValueError, on some damaged TIFFs). Files are written only
through `safe_write.create_new` into the export folder, which is that call's root, with the preset folder in use
(CONTRACT-write-guard G10, export XP10 / XP12). `SafeWriteRefused` is never caught here (G8).
"""
import contextlib
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
FORMATS = {"jpeg": (".jpg", 8), "tiff": (".tif", 16)}   # verbatim format values and extensions (X1, X9)
N_MAX = 9999                            # verbatim (XP2)
MAX_IN_FLIGHT = 3                       # verbatim (XP7)
ITEM_KEYS = ("image_id", "path", "preset_id", "strength", "overrides")


@dataclass
class _Job:
    index: int
    source: str
    path: str
    params: object


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


def _one_line(e):
    return " ".join(str(e).split()) or type(e).__name__


def _failed(source, reason):
    return {"ok": False, "source": source, "error": M.EXPORT_FAILED.format(file_name=source, reason=reason)}


def _is_oom(e):
    import torch
    return isinstance(e, torch.cuda.OutOfMemoryError)


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


class ExportService:
    def __init__(self, library, engine_ref, preset_dir, photo_library):
        self.library = library
        self.engine_ref = engine_ref
        self.preset_dir = preset_dir            # the preset folder in use, for safe_write (XP12)
        self.photo_library = photo_library      # resolve_params: the edit's snapshot first (photo library PL5)

    # ------------------------------------------------------------------ checks
    def _request(self, items, format, quality, dest_dir):
        if not isinstance(items, list) or not items:
            raise DarkroomError("invalid", M.EXPORT_NOTHING)
        if not isinstance(format, str) or format not in FORMATS:
            raise DarkroomError("invalid", M.EXPORT_BAD_FORMAT.format(format=format))
        if quality is None:
            quality = DEFAULT_QUALITY
        elif isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
            raise DarkroomError("invalid", M.EXPORT_BAD_QUALITY.format(quality=quality))
        if dest_dir is not None and (not isinstance(dest_dir, str) or not os.path.isabs(dest_dir)
                                     or not os.path.isdir(dest_dir)):
            raise DarkroomError("invalid", M.EXPORT_NO_DEST.format(dest_dir=dest_dir))
        return quality

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

    def _job(self, index, item):
        if not isinstance(item, dict):
            raise _ItemFailed("", M.EXPORT_ITEM_NOT_OBJECT)
        for key in item:
            if key not in ITEM_KEYS:
                raise _ItemFailed("", M.EXPORT_ITEM_UNKNOWN_KEY.format(key=key))
        name, path = self._source(item)
        params = None
        preset_id = item.get("preset_id")
        if preset_id is not None:               # PLP5: the photo is hashed again, the edit's snapshot wins
            try:
                fp = fingerprint(path)
            except OSError as e:
                raise _ItemFailed(name, _one_line(e)) from None
            try:
                params = self.photo_library.resolve_params(fp, preset_id)
            except DarkroomError as e:
                raise _ItemFailed(name, e.message) from None
        try:
            strength = semantics.validate_strength(item.get("strength", 100))
            overrides = semantics.validate_overrides(item.get("overrides"))
        except ValueError as e:
            raise _ItemFailed(name, str(e)) from None
        return _Job(index, name, path, semantics.effective_params(params, strength, overrides))   # X2

    # ------------------------------------------------------------------ the operation
    def export(self, items, format, quality=None, dest_dir=None):
        quality = self._request(items, format, quality, dest_dir)
        results = [None] * len(items)
        jobs = []
        for i, item in enumerate(items):
            try:
                jobs.append(self._job(i, item))
            except _ItemFailed as f:
                results[i] = _failed(f.source, f.reason)
        if jobs:
            for job, res in zip(jobs, self._run(jobs, format, quality, dest_dir)):
                results[job.index] = res
        return {"results": results}

    def _run(self, jobs, format, quality, dest_dir):
        ext, bits = FORMATS[format]
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
                out[k] = self._write(job, pixels, exif, ext, bits, quality, dest_dir, claim)
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

    def _write(self, job, pixels, exif, ext, bits, quality, dest_dir, claim=contextlib.nullcontext):
        icc = encoding.srgb_icc()
        try:
            if bits == 8:
                data = encoding.jpeg_bytes(pixels, quality, exif, icc)
            else:
                data = encoding.tiff_bytes(pixels, exif, icc)
        except Exception as e:      # cv2.error / struct.error / ValueError refusing the data: this item only (N1)
            with claim():
                return _failed(job.source, M.EXPORT_RENDER_FAILED.format(detail=_one_line(e)))
        del pixels
        with claim():                              # names in item order (seal F2)
            return self._claim(job, data, ext, dest_dir)

    def _claim(self, job, data, ext, dest_dir):
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
                return {"ok": True, "source": job.source, "output": path}
        except OSError:
            return _failed(job.source, M.EXPORT_CANNOT_WRITE.format(folder=folder))
        return _failed(job.source, M.EXPORT_NAMES_USED_UP.format(stem=stem, n_max=N_MAX))


class _Aborted(Exception):
    pass
