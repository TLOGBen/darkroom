"""The photo library: edits keyed by photo fingerprint, thumbnails, the thumbnail index (CONTRACT-photo-library).

Everything the library knows lives under data_dir (edits/, thumbs/, index/; ADR-0002), never in a photo folder.
A photo is identified by its fingerprint, the SHA-256 of the whole file (PL2): the same content shares one edit,
a moved or renamed file keeps it, a file changed by another program is a new photo (the old edit stays, PL10).
An edit (`darkroom-edit/1`) holds the preset snapshot (name, group, Params) taken when it was chosen, the strength
and the overrides (PL3, PL4); a preset changed later never changes an edit already applied.
`resolve_params` is the one rule deciding which Params a preview, an export or set_edit uses (PL5, PLP5).

Every write goes through `safe_write` with data_dir as root and the preset folder in use as `preset_dir=`
(CONTRACT-write-guard G8 / G10, patch PLP1): edits and index files as create_new(tmp) + replace_into (PermissionError
retried with the KP21 budget, PLP3), thumbnails as create_new (a .jpg can never be replaced or removed by safe_write),
clear as remove. Before any write the data folder must not lie inside the photo's folder or the preset folder (PLP1).
`SafeWriteRefused` is never caught here.

Thumbnails (PL11, PL12): long edge 256, display orientation, JPEG q80, from the embedded thumbnail, a reduced JPEG
decode or a full 8-bit decode, read from one copy of the file bytes that also gives the fingerprint; made on this
module's own `darkroom-thumb-*` worker threads from a priority queue (direct requests first), never on the GPU
executor. cv2 and pillow-heif are imported lazily so the edit commands stay light (L9 / PLP8).
"""
import hashlib
import heapq
import json
import os
import secrets
import struct
import sys
import threading
import time
from dataclasses import dataclass

from darkroom import Params

from .. import config
from .. import messages as M
from .. import preview as semantics
from .. import safe_write
from ..errors import DarkroomError
from .photos import checked_photo_path, list_photos, read_error

EDIT_SCHEMA = "darkroom-edit/1"                          # verbatim (PL3)
INDEX_SCHEMA = "darkroom-thumb-index/1"                  # verbatim (PLP8)
EDITS_DIR, THUMBS_DIR, INDEX_DIR = "edits", "thumbs", "index"   # verbatim (PL1)
EDIT_KEYS = ("schema", "fingerprint", "preset", "strength", "overrides")      # verbatim order (PL3)
PREV_SUFFIX = ".prev.json"                               # verbatim (CONTRACT-s1-experience S4): edits/{fp[0:2]}/{fp}.prev.json
ANSWER_KEYS = ("fingerprint", "edit", "preset_status", "previous")   # verbatim order (S4, revising PL7)
PRESET_KEYS = ("id", "name", "group", "params")
THUMB_LONG_EDGE = 256                                    # verbatim (PL11)
THUMB_QUALITY = 80                                       # verbatim (PL11)
EMBEDDED_MIN_EDGE = 160                                  # verbatim (PL11)
EMBEDDED_ASPECT_TOL = 0.01                               # verbatim (PL11)
THUMB_THREAD_PREFIX = "darkroom-thumb"                   # verbatim (PL12)
THUMB_WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))   # verbatim (PL12)
REPLACE_RETRIES, REPLACE_RETRY_S = 200, 0.01             # verbatim (PLP3, as KP21)
READ_RETRIES, READ_RETRY_S = 10, 0.1                     # verbatim (PLP3, as KP12)
TARGETS_MAX = 500                                        # verbatim (PL8)
CHUNK = 1 << 20
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


# ---------------------------------------------------------------------- fingerprint (PL2)
def fingerprint(path):
    """SHA-256 (lower-case hex) of the whole file, read in 1 MiB chunks: nothing but the bytes (PL2)."""
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
    return hashlib.sha256(data).hexdigest()


def _one_line(e):
    return " ".join(str(e).split()) or type(e).__name__


def _log(text):
    """One stderr line for failures nobody waits for (background thumbnails, the index write)."""
    sys.stderr.write(f"[darkroom-photo-library] {text}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------- edit objects (PL3, PLP8)
def _norm_strength(strength):
    v = float(strength)
    return int(v) if v.is_integer() else v


def edit_problem(obj):
    """None when obj is a well-formed darkroom-edit/1 object, else the first reason (PLP8 constants)."""
    if not isinstance(obj, dict):
        return M.PL_EDIT_NOT_OBJECT
    if set(obj) != set(EDIT_KEYS):
        return M.PL_EDIT_KEYS
    if obj["schema"] != EDIT_SCHEMA:
        return M.PL_EDIT_SCHEMA.format(schema=obj["schema"])
    p = obj["preset"]
    if p is not None:
        if not isinstance(p, dict) or set(p) != set(PRESET_KEYS) or not all(isinstance(p[k], str)
                                                                             for k in ("id", "name", "group")):
            return M.PL_EDIT_PRESET
        try:
            Params.from_dict(p["params"])
        except (ValueError, TypeError, AttributeError) as e:
            return M.PL_EDIT_PARAMS.format(reason=_one_line(e))
    try:
        semantics.validate_strength(obj["strength"])
        semantics.validate_overrides(obj["overrides"])
    except ValueError as e:
        return str(e)
    return None


def canonical_edit(fp, preset, strength, overrides):
    """The edit object with the constant keys in order (PL3)."""
    p = None if preset is None else {k: preset[k] for k in PRESET_KEYS}
    return {"schema": EDIT_SCHEMA, "fingerprint": fp, "preset": p, "strength": _norm_strength(strength),
            "overrides": semantics.validate_overrides(overrides)}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class ThumbnailResult:
    jpeg: bytes
    fingerprint: str
    edited: bool
    width: int
    height: int
    edit: object = None      # S8: {"preset": name|None, "strength": n, "status": ...} when edited (HTTP X-Edit), else None


# ---------------------------------------------------------------------- image helpers (lazy cv2)
def _turn(a, orientation):
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


def _jpeg_info(data):
    """(width, height, orientation, embedded thumbnail bytes or None, thumbnail orientation) of JPEG bytes."""
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


def _jpeg_size(data):
    w, h, _, _, _ = _jpeg_info(data)
    return w, h


def _fit(w, h):
    """Size with the long edge at most THUMB_LONG_EDGE (never upscaled)."""
    long = max(w, h)
    if long <= THUMB_LONG_EDGE:
        return w, h
    s = THUMB_LONG_EDGE / long
    return max(1, round(w * s)), max(1, round(h * s))


def _embedded_ok(tw, th, fw, fh):
    """PL11: the turned embedded thumbnail is big enough and has the full image's aspect ratio (no letterbox)."""
    if max(tw, th) < EMBEDDED_MIN_EDGE or not fw or not fh:
        return False
    return abs(tw / th - fw / fh) / (fw / fh) <= EMBEDDED_ASPECT_TOL


def make_thumbnail(data, ext):
    """JPEG q80 bytes with the long edge <= 256 in display orientation, from one copy of the file bytes (PL11)."""
    import cv2
    import numpy as np
    arr = None
    if ext in (".jpg", ".jpeg"):
        w, h, orientation, thumb, thumb_orient = _jpeg_info(data)
        if w is None or h is None:
            raise ValueError("cannot decode image")
        fw, fh = (h, w) if orientation in (5, 6, 7, 8) else (w, h)
        if thumb is not None:                                                  # (1) embedded thumbnail
            t = cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            if t is not None:
                t = _turn(t, thumb_orient if thumb_orient in range(1, 9) else orientation)
                if _embedded_ok(t.shape[1], t.shape[0], fw, fh):
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
            arr = _turn(a, orientation)
    elif ext in (".heic", ".heif"):
        import io
        import pillow_heif
        hf = pillow_heif.open_heif(io.BytesIO(data))
        fw, fh = hf.size
        if hf.info.get("thumbnails"):                                          # (1) libheif thumbnail, upright
            t = np.asarray(hf[0].get_thumbnail(0).to_pillow().convert("RGB"))[..., ::-1]
            if _embedded_ok(t.shape[1], t.shape[0], fw, fh):
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
    nw, nh = _fit(w, h)
    if (nw, nh) != (w, h):
        arr = cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, THUMB_QUALITY])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


# ---------------------------------------------------------------------- the thumbnail queue (PL12)
class _Job:
    __slots__ = ("priority", "seq", "key", "path", "folder", "generation", "future", "background")

    def __init__(self, priority, seq, key, path, folder, generation):
        self.priority, self.seq, self.key, self.path = priority, seq, key, path
        self.folder, self.generation = folder, generation
        self.background = bool(priority)        # counted in pending_bg even after a direct request bumps it
        self.future = _Future()

    def __lt__(self, other):
        return (self.priority, self.seq) < (other.priority, other.seq)


class _Future:
    def __init__(self):
        self.ev = threading.Event()
        self.result = self.error = None

    def set(self, result=None, error=None):
        self.result, self.error = result, error
        self.ev.set()

    def wait(self):
        self.ev.wait()
        if self.error is not None:
            raise self.error
        return self.result


class _ThumbQueue:
    """Priority 0 = a direct thumbnail request, 1 = background pre-generation; one job per photo at a time."""

    def __init__(self, work):
        self.work = work                   # (path) -> result; raises DarkroomError
        self.cv = threading.Condition()
        self.heap, self.inflight, self.seq = [], {}, 0
        self.generation = {}               # folder key -> current generation
        self.pending_bg = {}               # folder key -> background jobs not yet finished
        self.started = False
        self.busy = 0

    def _ensure_workers(self):
        if not self.started:
            self.started = True
            for i in range(THUMB_WORKERS):
                threading.Thread(target=self._run, name=f"{THUMB_THREAD_PREFIX}-{i}", daemon=True).start()

    def submit(self, path, folder, priority):
        key = os.path.normcase(os.path.abspath(path))
        with self.cv:
            self._ensure_workers()
            job = self.inflight.get(key)
            if job is not None:
                if job in self.heap:                                  # not started yet
                    job.generation = self.generation.get(folder, 0)   # asked for again: it is current again
                    if priority < job.priority:                       # a direct request jumps the queue
                        job.priority = priority
                        heapq.heapify(self.heap)
                return job.future
            self.seq += 1
            job = _Job(priority, self.seq, key, path, folder, self.generation.get(folder, 0))
            if priority:
                self.pending_bg[folder] = self.pending_bg.get(folder, 0) + 1
            self.inflight[key] = job
            heapq.heappush(self.heap, job)
            self.cv.notify()
            return job.future

    def new_generation(self, folder):
        """Background jobs of this folder not yet started are dropped when taken (PL12)."""
        with self.cv:
            self.generation[folder] = self.generation.get(folder, 0) + 1
            return self.generation[folder]

    def background_pending(self, folder):
        with self.cv:
            return self.pending_bg.get(folder, 0)

    def wait_idle(self, timeout=None):
        """Testing / bench helper: True when no job is queued or running."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self.cv:
            while self.heap or self.busy:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self.cv.wait(remaining if remaining is not None else 0.5)
            return True

    def _run(self):
        while True:
            with self.cv:
                while not self.heap:
                    self.cv.wait()
                job = heapq.heappop(self.heap)
                stale = job.priority and self.generation.get(job.folder, 0) != job.generation   # never a direct request
                self.busy += 1                      # also for a stale job: its index flush counts as work
                if stale:
                    self.inflight.pop(job.key, None)
                    idle = self._bg_done(job, locked=True)
                    job.future.set(None)
            if not stale:
                try:
                    result, error = self.work(job.path), None
                except BaseException as e:          # DarkroomError, SafeWriteRefused, ...: handed to every waiter
                    result, error = None, e
                    if job.priority and not isinstance(e, DarkroomError):   # nobody waits for a background job
                        _log(f"background thumbnail of {job.path} failed: {type(e).__name__}: {_one_line(e)}")
                with self.cv:
                    self.inflight.pop(job.key, None)
                    idle = self._bg_done(job, locked=True)
                    job.future.set(result, error)
            if idle:
                self.on_folder_idle(job.folder)      # disk I/O outside the queue lock (seal F10)
            with self.cv:
                self.busy -= 1                      # idle only once the folder's index is written
                self.cv.notify_all()

    def _bg_done(self, job, locked):
        """Count a background job as finished; True when its folder has no background work left."""
        if not job.background:
            return False
        left = self.pending_bg.get(job.folder, 0) - 1
        if left <= 0:
            self.pending_bg.pop(job.folder, None)
            return True
        self.pending_bg[job.folder] = left
        return False

    def on_folder_idle(self, folder):      # replaced by the service (flush the index)
        pass


# ---------------------------------------------------------------------- the service
class PhotoLibraryService:
    def __init__(self, library, preset_dir, data_dir=None, preset_library=None):
        self.library = library
        self.preset_dir = preset_dir            # the preset folder in use, for safe_write (PLP1)
        self.preset_library = preset_library    # PresetLibraryService, for save_edit_as_preset (PLP6)
        self._data_dir = data_dir               # None: config.data_dir() on first use (PLP8)
        self._lock = threading.RLock()
        self._index = {}                        # folder key -> {"folder", "files": {name: {...}}, "dirty": bool}
        self._queue = _ThumbQueue(self._generate)
        self._queue.on_folder_idle = self._flush_index

    # ------------------------------------------------------------------ data_dir and paths
    @property
    def data_dir(self):
        if self._data_dir is None:
            self._data_dir = config.data_dir()
        return self._data_dir

    def _sw(self, fn, *args):
        return fn(*args, preset_dir=self.preset_dir)

    def _edit_path(self, fp):
        return os.path.join(self.data_dir, EDITS_DIR, fp[:2], fp + ".json")

    def _thumb_path(self, fp):
        return os.path.join(self.data_dir, THUMBS_DIR, fp[:2], fp + ".jpg")

    def _index_path(self, key):
        return os.path.join(self.data_dir, INDEX_DIR, key + ".json")

    def _guard_folder(self, folder):
        """PLP1: the data folder must not lie inside the photo folder being handled or the preset folder.

        Called by every writing helper (_write_json, the thumbnail write, _remove_edit) before it writes."""
        real = os.path.normcase(os.path.realpath(self.data_dir))
        for f in (folder, self.preset_dir):
            f = os.path.normcase(os.path.realpath(f))
            try:
                if os.path.commonpath([real, f]) == f:
                    raise DarkroomError("unavailable", M.PL_DATA_DIR_INSIDE.format(data_dir=self.data_dir))
            except ValueError:
                pass

    def _guard(self, photo_path):
        self._guard_folder(os.path.dirname(os.path.abspath(photo_path)))

    def _cannot_write(self, reason):
        return DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(data_dir=self.data_dir, reason=reason))

    def _make_dirs(self, folder):
        if not os.path.isdir(folder):
            try:
                self._sw(safe_write.make_dirs, folder, self.data_dir)
            except OSError as e:                     # read-only disk, permissions: PL9 unavailable
                raise self._cannot_write(_one_line(e)) from None

    def _root(self):
        """data_dir itself (safe_write's root must exist): created by the first write only (PL9: a data_dir whose
        parent does not exist cannot be created and is unavailable, not an unexpected error - seal F1)."""
        d = self.data_dir
        if not os.path.isdir(d):
            parent = os.path.dirname(os.path.abspath(d))
            if not os.path.isdir(parent):
                raise self._cannot_write(M.PL_PARENT_MISSING.format(parent=parent))
            try:
                self._sw(safe_write.make_dirs, d, parent)
            except OSError as e:
                raise self._cannot_write(_one_line(e)) from None
        return d

    # ------------------------------------------------------------------ reading and writing JSON (PLP3)
    @staticmethod
    def _read_retry(path):
        """Bytes of the file, None when missing; PermissionError retried like KP12."""
        for attempt in range(READ_RETRIES):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except FileNotFoundError:
                return None
            except PermissionError:
                if attempt == READ_RETRIES - 1:
                    raise
                time.sleep(READ_RETRY_S)

    def _write_json(self, dest, obj, tmp_prefix, photo_folder):
        """create_new(tmp) + replace_into(dest), PermissionError retried with the KP21 budget; tmp never left.
        `photo_folder` is the photo folder this write is about: the PLP1 guard runs first, every time."""
        self._guard_folder(photo_folder)
        self._root()
        folder = os.path.dirname(dest)
        self._make_dirs(os.path.dirname(folder))
        self._make_dirs(folder)
        tmp = os.path.join(folder, f"{tmp_prefix}.tmp-{os.getpid()}-{secrets.token_hex(6)}")
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self._sw(safe_write.create_new, tmp, self.data_dir, data)
        except OSError as e:
            raise DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(data_dir=self.data_dir,
                                                                        reason=_one_line(e))) from None
        try:
            for attempt in range(REPLACE_RETRIES):
                try:
                    self._sw(safe_write.replace_into, tmp, dest, self.data_dir)
                    return
                except PermissionError as e:              # a reader has the file open (P6 / KP21)
                    if attempt == REPLACE_RETRIES - 1:
                        raise DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(
                            data_dir=self.data_dir, reason=_one_line(e))) from None
                    time.sleep(REPLACE_RETRY_S)
                except OSError as e:
                    raise DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(
                        data_dir=self.data_dir, reason=_one_line(e))) from None
        finally:
            if os.path.exists(tmp):
                self._sw(safe_write.remove, tmp, self.data_dir)

    # ------------------------------------------------------------------ edits (PL3, PL4, PL9)
    def _read_edit(self, fp, file_name):
        """The edit object for a fingerprint, None when there is none; conflict / unavailable as PL9."""
        p = self._edit_path(fp)
        try:
            raw = self._read_retry(p)
        except OSError as e:
            raise DarkroomError("unavailable", M.PL_CANNOT_READ.format(edit_file=p, reason=_one_line(e))) from None
        if raw is None:
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise DarkroomError("unavailable", M.PL_EDIT_CORRUPT.format(edit_file=p)) from None
        if isinstance(obj, dict) and "schema" in obj and obj["schema"] != EDIT_SCHEMA:
            raise DarkroomError("conflict", M.PL_SCHEMA_CONFLICT.format(schema=obj.get("schema"),
                                                                         file_name=file_name))
        if edit_problem(obj) is not None:
            raise DarkroomError("unavailable", M.PL_EDIT_CORRUPT.format(edit_file=p))
        return obj

    def _write_edit(self, photo_path, edit):
        self._write_json(self._edit_path(edit["fingerprint"]), edit, "." + edit["fingerprint"],
                         os.path.dirname(os.path.abspath(photo_path)))

    def _prev_path(self, fp):
        return os.path.join(self.data_dir, EDITS_DIR, fp[:2], fp + PREV_SUFFIX)

    def _remove_edit(self, photo_path, fp, keep=None):
        """Delete the edit file; the edit being cleared is first kept as the one previous edit (S4)."""
        p = self._edit_path(fp)
        if os.path.exists(p):
            self._guard(photo_path)
            if keep is not None:
                self._write_json(self._prev_path(fp), keep, "." + fp + ".prev",
                                 os.path.dirname(os.path.abspath(photo_path)))
            try:
                self._sw(safe_write.remove, p, self.data_dir)
            except FileNotFoundError:
                pass
            except OSError as e:
                raise DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(data_dir=self.data_dir,
                                                                            reason=_one_line(e))) from None

    def _read_previous(self, fp):
        """The kept previous edit of a fingerprint, None when there is none or it is unreadable."""
        try:
            raw = self._read_retry(self._prev_path(fp))
            obj = json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        return obj if isinstance(obj, dict) and edit_problem(obj) is None and obj["fingerprint"] == fp else None

    def _has_previous(self, fp):
        return os.path.exists(self._prev_path(fp))

    def _status(self, preset):
        """PL4 preset_status: null / "missing" / "current" / "changed" (params only)."""
        if preset is None:
            return None
        params = self.library.params
        if preset["id"] not in params:
            return "missing"
        return "current" if params[preset["id"]].to_dict() == preset["params"] else "changed"

    def _fingerprint(self, path):
        try:
            return fingerprint(path)
        except OSError as e:
            raise read_error(path, e) from None

    def _answer(self, fp, edit):
        return {"fingerprint": fp, "edit": edit, "preset_status": self._status(edit["preset"] if edit else None),
                "previous": self._has_previous(fp)}

    def _edit_summary(self, fp):
        """S8: what the thumbnail grid shows about an edit: {"preset": name|None, "strength", "status"}; None when
        the photo has no edit or its file cannot be read (the badge then only says "edited")."""
        try:
            raw = self._read_retry(self._edit_path(fp))
            obj = json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(obj, dict) or edit_problem(obj) is not None:
            return None
        preset = obj["preset"]
        return {"preset": preset["name"] if preset else None, "strength": obj["strength"],
                "status": self._status(preset)}

    def _resolve(self, edit, preset_id):
        """PL5: the snapshot when the edit holds this preset id, else the library's Params (not_found otherwise)."""
        if preset_id is None:
            return None
        if edit is not None and edit["preset"] is not None and edit["preset"]["id"] == preset_id:
            return Params.from_dict(edit["preset"]["params"])
        if not isinstance(preset_id, str) or preset_id not in self.library.params:
            raise DarkroomError("not_found", M.UNKNOWN_OR_UNSUPPORTED_PRESET.format(pid=preset_id))
        return self.library.get(preset_id)

    def resolve_params(self, fingerprint, preset_id):
        """The one rule for the preset Params a preview, an export or set_edit uses (PL5, PLP5)."""
        if preset_id is None:
            return None
        return self._resolve(self._read_edit(fingerprint, fingerprint), preset_id)

    def get_edit(self, path):
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        return self._answer(fp, self._read_edit(fp, os.path.basename(path)))

    def set_edit(self, path, preset_id=None, strength=100, overrides=None):
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        existing = self._read_edit(fp, os.path.basename(path))
        self._resolve(existing, preset_id)                                   # not_found before validate_* (PL7)
        try:
            semantics.validate_strength(strength)
            o = semantics.validate_overrides(overrides)
        except ValueError as e:
            raise DarkroomError("invalid", str(e)) from None
        if preset_id is None and not o:                                      # PL3: no edit at all
            self._remove_edit(path, fp, keep=existing)
            return self._answer(fp, None)
        preset = None
        if preset_id is not None:
            if existing is not None and existing["preset"] is not None and existing["preset"]["id"] == preset_id:
                preset = existing["preset"]                                  # PL4: the snapshot is kept
            else:
                row = self.library.by_id[preset_id]
                preset = {"id": preset_id, "name": row["name"], "group": row["group"],
                          "params": self.library.get(preset_id).to_dict()}
        edit = canonical_edit(fp, preset, strength, o)
        self._write_edit(path, edit)
        return self._answer(fp, edit)

    def clear_edit(self, path):
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        existing = self._read_edit(fp, os.path.basename(path))               # PL9: a foreign version is not deleted
        self._remove_edit(path, fp, keep=existing)
        return self._answer(fp, None)

    def restore_edit(self, path):
        """S4: the edit kept when this photo's edit was last cleared goes back as its edit (the kept copy stays)."""
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        self._read_edit(fp, os.path.basename(path))                          # conflict / unavailable first (PL9)
        prev = self._read_previous(fp)
        if prev is None:
            raise DarkroomError("not_found", M.PL_NO_PREVIOUS.format(file_name=os.path.basename(path)))
        edit = canonical_edit(fp, prev["preset"], prev["strength"], prev["overrides"])
        self._write_edit(path, edit)
        return self._answer(fp, edit)

    # ------------------------------------------------------------------ paste (PL8, PLP4)
    def paste_edit(self, targets, source=None, edit=None):
        if (source is None) == (edit is None):
            raise DarkroomError("invalid", M.PL_SOURCE_OR_EDIT)
        if (not isinstance(targets, list) or not 1 <= len(targets) <= TARGETS_MAX
                or not all(isinstance(t, str) for t in targets)):
            raise DarkroomError("invalid", M.PL_TARGETS_INVALID)
        if source is not None:
            spath = checked_photo_path(source)
            src = self._read_edit(self._fingerprint(spath), os.path.basename(spath))
            if src is None:
                raise DarkroomError("not_found", M.PL_NO_EDIT.format(file_name=os.path.basename(spath)))
        else:
            reason = edit_problem(edit)
            if reason is not None:
                raise DarkroomError("invalid", M.PL_EDIT_INVALID.format(reason=reason))
            src = edit
        results = []
        for t in targets:
            name = os.path.basename(t.strip().strip('"'))
            try:
                tp = checked_photo_path(t)
                name = os.path.basename(tp)
                tfp = self._fingerprint(tp)
                self._read_edit(tfp, name)                                   # conflict / unavailable: this item
                self._write_edit(tp, canonical_edit(tfp, src["preset"], src["strength"], src["overrides"]))
                results.append({"ok": True, "target": name})
            except DarkroomError as e:
                results.append({"ok": False, "target": name, "error": e.message})
        return {"results": results}

    # ------------------------------------------------------------------ save as preset (PLP6)
    def save_edit_as_preset(self, path, name, group=None):
        """The edit's snapshot x strength + overrides written as a user preset by the preset library's K12 flow."""
        params = self.edit_params(path)
        return self.preset_library.save_params(name, group, params)

    def edit_params(self, path):
        """Final Params of a photo's edit (snapshot, strength, overrides); not_found when it has no edit."""
        path = checked_photo_path(path)
        edit = self._read_edit(self._fingerprint(path), os.path.basename(path))
        if edit is None:
            raise DarkroomError("not_found", M.PL_NO_EDIT.format(file_name=os.path.basename(path)))
        base = None if edit["preset"] is None else Params.from_dict(edit["preset"]["params"])
        return semantics.effective_params(base, semantics.validate_strength(edit["strength"]),
                                          semantics.validate_overrides(edit["overrides"]))

    # ------------------------------------------------------------------ index (PL13, PLP8)
    @staticmethod
    def _folder_key(folder):
        real = os.path.realpath(folder)
        return real, hashlib.sha256(os.path.normcase(real).encode("utf-8")).hexdigest()[:16]

    def _index_for(self, folder):
        """The in-memory index of a folder (loaded from disk once; unreadable = empty)."""
        real, key = self._folder_key(folder)
        with self._lock:
            idx = self._index.get(key)
            if idx is None:
                files = {}
                try:
                    raw = self._read_retry(self._index_path(key))
                    obj = json.loads(raw.decode("utf-8")) if raw else None
                    if (isinstance(obj, dict) and obj.get("schema") == INDEX_SCHEMA
                            and isinstance(obj.get("files"), dict)):
                        files = {n: e for n, e in obj["files"].items()
                                 if isinstance(e, dict) and _is_int(e.get("size")) and _is_int(e.get("mtime_ns"))
                                 and isinstance(e.get("fingerprint"), str)}
                except (OSError, ValueError, UnicodeDecodeError):
                    files = {}
                idx = self._index[key] = {"folder": real, "key": key, "files": files, "dirty": False}
            return idx

    def _lookup(self, folder, name, st):
        idx = self._index_for(folder)
        with self._lock:
            e = idx["files"].get(name)
            if e and e["size"] == st.st_size and e["mtime_ns"] == st.st_mtime_ns:
                return e["fingerprint"]
        return None

    def _remember(self, folder, name, st, fp):
        idx = self._index_for(folder)
        with self._lock:
            idx["files"][name] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "fingerprint": fp}
            idx["dirty"] = True

    def _flush_index(self, folder):
        idx = self._index_for(folder)
        with self._lock:
            if not idx["dirty"]:
                return
            obj = {"schema": INDEX_SCHEMA, "folder": idx["folder"], "files": dict(idx["files"])}
            idx["dirty"] = False
        try:
            self._write_json(self._index_path(idx["key"]), obj, "." + idx["key"], idx["folder"])
        except DarkroomError as e:
            with self._lock:
                idx["dirty"] = True              # kept in memory; written again next time
            _log(f"index not written: {e.message}")

    # ------------------------------------------------------------------ thumbnails (PL11-PL13)
    def _generate(self, path):
        """Worker: one read of the bytes -> fingerprint + thumbnail -> thumbs/ -> index. (fingerprint, jpeg)."""
        folder = os.path.dirname(os.path.abspath(path))
        name = os.path.basename(path)
        self._guard_folder(folder)                       # PLP1, before anything: a cache hit still writes the index
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            raise DarkroomError("invalid", M.PL_THUMB_FAILED.format(file_name=name, reason=_one_line(e))) from None
        fp = fingerprint_bytes(data)
        tp = self._thumb_path(fp)
        jpeg = self._read_retry(tp) if os.path.exists(tp) else None
        if jpeg is None:
            try:
                jpeg = make_thumbnail(data, os.path.splitext(path)[1].lower())
            except Exception as e:                       # cv2.error, ValueError, pillow-heif errors
                raise DarkroomError("invalid", M.PL_THUMB_FAILED.format(file_name=name,
                                                                        reason=_one_line(e))) from None
            del data
            self._root()
            self._make_dirs(os.path.dirname(os.path.dirname(tp)))
            self._make_dirs(os.path.dirname(tp))
            try:
                self._sw(safe_write.create_new, tp, self.data_dir, jpeg)
            except FileExistsError:                      # another thread just wrote the same content's thumbnail
                jpeg = self._read_retry(tp) or jpeg
            except OSError as e:
                raise DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(data_dir=self.data_dir,
                                                                            reason=_one_line(e))) from None
        self._remember(folder, name, st, fp)
        if self._queue.background_pending(folder) == 0:
            self._flush_index(folder)
        return fp, jpeg

    def _edited(self, fp):
        return os.path.exists(self._edit_path(fp))

    def folder_thumbnails(self, folder, offset=0, limit=None):
        if not isinstance(folder, str) or not folder.strip():
            raise DarkroomError("invalid", M.PATH_REQUIRED)
        folder = folder.strip().strip('"')
        if not os.path.isdir(folder):
            raise DarkroomError("not_found", M.PL_FOLDER_NOT_FOUND.format(folder=folder))
        if not _is_int(offset) or offset < 0:
            raise DarkroomError("invalid", M.OFFSET_INVALID)
        if limit is not None and (not _is_int(limit) or not 1 <= limit <= M.LIMIT_MAX):
            raise DarkroomError("invalid", M.LIMIT_INVALID)
        folder = os.path.abspath(folder)
        files = list_photos(folder)
        items, todo = [], []
        for f in files:
            fp = cached = None
            try:
                fp = self._lookup(folder, f["name"], os.stat(f["path"]))
            except OSError:
                fp = None
            if fp is not None:
                cached = os.path.exists(self._thumb_path(fp))
            items.append({"name": f["name"], "path": f["path"], "fingerprint": fp,
                          "edited": self._edited(fp) if fp else None, "cached": bool(cached)})
            if not cached:
                todo.append(f["path"])
        self._queue.new_generation(folder)
        for p in todo:
            self._queue.submit(p, folder, 1)
        total = len(items)
        end = total if limit is None else offset + limit
        page = items[offset:end]
        nxt = offset + len(page)
        return {"folder": folder, "items": page, "total": total, "next_offset": nxt if nxt < total else None}

    def thumbnail(self, path):
        path = checked_photo_path(path)
        folder = os.path.dirname(os.path.abspath(path))
        try:
            fp = self._lookup(folder, os.path.basename(path), os.stat(path))
        except OSError:
            fp = None
        jpeg = None
        if fp is not None:
            tp = self._thumb_path(fp)
            if os.path.exists(tp):
                jpeg = self._read_retry(tp)                  # warm: the photo file is not opened (PL16 b)
        if jpeg is None:
            fp, jpeg = self._queue.submit(path, folder, 0).wait()
        w, h = _jpeg_size(jpeg)
        edited = self._edited(fp)
        return ThumbnailResult(jpeg, fp, edited, w, h, self._edit_summary(fp) if edited else None)

    def wait_thumbnails(self, timeout=None):
        """Testing / bench helper: wait until the background queue is empty."""
        return self._queue.wait_idle(timeout)
