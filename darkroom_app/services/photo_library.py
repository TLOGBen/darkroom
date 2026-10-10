"""The photo library: edits keyed by photo fingerprint, thumbnails, the thumbnail index (CONTRACT-photo-library).

Layer: services. The rules live here - which edit a photo has, what set / clear / restore / paste do, which Params a
preview or an export uses (`resolve_params`, PL5 / PLP5), when thumbnails are made. The files are the stores the
composition hands in: `EditStore` (edits/ and the kept previous edit) and `ThumbStore` (thumbs/ and index/), both
on one `DataFolder` (adapters/persist). The edit object's schema and canonical form are `domain/edits.py`; the
thumbnail pixels are `utils/imaging.py`. Never imports the facade, the entry adapters, config or the write module.

Everything the library knows lives under data_dir (edits/, thumbs/, index/; ADR-0002), never in a photo folder.
A photo is identified by its fingerprint, the SHA-256 of the whole file (PL2): the same content shares one edit,
a moved or renamed file keeps it, a file changed by another program is a new photo (the old edit stays, PL10).
An edit (`darkroom-edit/1`) holds the preset snapshot (name, group, Params) taken when it was chosen, the strength
and the overrides (PL3, PL4); a preset changed later never changes an edit already applied. An edit with a geometry
is `darkroom-edit/2` (CONTRACT-s3-crop C12).

Thumbnails (PL11, PL12): long edge 256, display orientation, JPEG q80, read from one copy of the file bytes that
also gives the fingerprint; made on this module's own `darkroom-thumb-*` worker threads from a priority queue
(direct requests first), never on the GPU executor. cv2 and pillow-heif are imported lazily (L9 / PLP8).

Data flow of an edit operation: photo path -> checked (exists, supported) -> fingerprint (hash of the file) ->
EditStore reads data_dir/edits/<fp[:2]>/<fp>.json -> the rule (set / clear / paste / restore) builds the new edit
with domain.edits.canonical_edit -> EditStore writes it atomically (and keeps the cleared one as "previous").
Data flow of a thumbnail: path -> the ThumbStore's index (folder, name, size, mtime -> fingerprint) -> cached JPEG in
thumbs/ if present, else a worker reads the bytes once, hashes them, makes the 256 px JPEG and stores it.

Contract codes used here (CONTRACT-photo-library unless noted): PL2 = identity is the content hash; PL3 = the edit
file's exact shape; PL4 = the preset snapshot is taken when chosen and kept while the same preset stays chosen,
preset_status says whether the preset file changed since; PL5 / PLP5 = one function decides the base Params (the
snapshot wins); PL7 = check order of the edit operations; PL8 / PLP4 = paste to 1..500 targets, per-target results;
PL9 = an edit file of another schema version is never overwritten or deleted (conflict); PL10 = old edits are never
deleted by anything but clear; PL11 / PL12 / PL13 / PL16 = thumbnail size and source, worker threads and priority,
the grid's shape, the warm-cache performance; PLP1 = writes only under data_dir, guarded; PLP6 = save an edit as a
user preset; ADR-0002 = edits live in data_dir keyed by content. CONTRACT-s1-experience S4 / S4a = restore the
cleared edit, never over a different one; S8 / S8b = the edit summary shown on a thumbnail badge.
CONTRACT-s3-crop C12 / C13 / C14 / C17 / C18 / C19 = the geometry in edits, set, paste, preview, thumbnails, export.
CONTRACT-s2-export-detect E12 / E15 / E23 = export presets in data_dir, exporting the saved edit, availability.
"""
import heapq
import os
import sys
import threading
import time
from dataclasses import dataclass

from ..domain import messages as M
from ..domain.adjustment import ORIGINAL, Adjustment, validate_flag, validate_geometry
from ..domain.edits import (EDIT_KEYS, EDIT_KEYS_V2, EDIT_SCHEMA, EDIT_SCHEMA_V2, PRESET_KEYS,  # noqa: F401
                            canonical_edit, colourless, edit_base_params, edit_geometry, edit_problem)
from ..domain.errors import DarkroomError
from ..domain.sentinels import KEEP
from ..utils.imaging import (EMBEDDED_ASPECT_TOL, EMBEDDED_MIN_EDGE, THUMB_LONG_EDGE, THUMB_QUALITY,  # noqa: F401
                             apply_geometry, fingerprint, fingerprint_bytes, jpeg_size, make_thumbnail)   # fingerprint: re-exported (tests)
from ..utils.text import is_int, one_line
from .photos import checked_photo_path, list_photos, photo_fingerprint

ANSWER_KEYS = ("fingerprint", "edit", "preset_status", "previous")   # verbatim order (S4, revising PL7)
THUMB_THREAD_PREFIX = "darkroom-thumb"                   # verbatim (PL12)
THUMB_WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))   # verbatim (PL12)
TARGETS_MAX = 500                                        # verbatim (PL8)


def _log(text):
    """One stderr line for failures nobody waits for (a background thumbnail)."""
    sys.stderr.write(f"[darkroom-photo-library] {text}\n")
    sys.stderr.flush()


@dataclass(frozen=True)
class ThumbnailResult:
    """A thumbnail as served: JPEG bytes (with the saved crop applied), the photo's fingerprint, whether it has an
    edit, the JPEG's size and the edit summary for the grid's badge."""
    jpeg: bytes
    fingerprint: str
    edited: bool
    width: int
    height: int
    edit: object = None      # S8 / S8b: {"preset", "strength", "status", "geometry", "tweaks"} when edited (X-Edit), else None


# ---------------------------------------------------------------------- the thumbnail queue (PL12)
class _Job:
    """One queued thumbnail: ordered by (priority, submission order); `generation` marks which folder listing
    asked for it, so background work for a folder the user already left can be dropped."""
    __slots__ = ("priority", "seq", "key", "path", "folder", "generation", "future", "background")

    def __init__(self, priority, seq, key, path, folder, generation):
        self.priority, self.seq, self.key, self.path = priority, seq, key, path
        self.folder, self.generation = folder, generation
        self.background = bool(priority)        # counted in pending_bg even after a direct request bumps it
        self.future = _Future()

    def __lt__(self, other):
        return (self.priority, self.seq) < (other.priority, other.seq)


class _Future:
    """A minimal one-shot result holder (set once by a worker, waited on by any number of requesters)."""

    def __init__(self):
        self.ev = threading.Event()
        self.result = self.error = None

    def set(self, result=None, error=None):
        """Publish the result (or the exception) and wake every waiter."""
        self.result, self.error = result, error
        self.ev.set()

    def wait(self):
        """Block until set; re-raise the worker's exception in the waiting thread."""
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
        """Start the daemon worker threads on first use (called with the condition held)."""
        if not self.started:
            self.started = True
            for i in range(THUMB_WORKERS):
                threading.Thread(target=self._run, name=f"{THUMB_THREAD_PREFIX}-{i}", daemon=True).start()

    def submit(self, path, folder, priority):
        """Queue a thumbnail for `path` (or join the job already queued / running for it) -> its _Future.

        priority 0 = someone is waiting for this thumbnail now, 1 = background pre-generation for a folder."""
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
        """Number of background jobs of `folder` not finished yet."""
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
        """Worker loop: take the most urgent job, skip it if it is stale background work, else run it and publish
        the result; when a folder's background work is done, flush that folder's index (outside the lock)."""
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
                        _log(f"background thumbnail of {job.path} failed: {type(e).__name__}: {one_line(e)}")
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
        """Hook called when a folder has no background work left (the service writes its index then)."""


# ---------------------------------------------------------------------- the service
class PhotoLibraryService:
    """Edits, thumbnails and the base-Params rule shared with preview / export (operations 18..25)."""

    def __init__(self, library, folder, edits, thumbs, preset_library=None):
        """library: the preset view; folder: DataFolder; edits: EditStore; thumbs: ThumbStore; preset_library:
        PresetLibraryService (only for save_edit_as_preset)."""
        self.library = library
        self.folder = folder                    # DataFolder: data_dir, availability, the PLP1 guard
        self.edits = edits                      # EditStore
        self.thumbs = thumbs                    # ThumbStore
        self.preset_dir = folder.preset_dir     # the preset folder in use (PLP1)
        self.preset_library = preset_library    # PresetLibraryService, for save_edit_as_preset (PLP6)
        self._queue = _ThumbQueue(self._generate)
        self._queue.on_folder_idle = self.thumbs.flush

    # ------------------------------------------------------------------ data_dir
    @property
    def data_dir(self):
        """The resolved data folder (raises unavailable when it cannot be resolved)."""
        return self.folder.data_dir

    def usable_data_dir(self):
        """data_dir for a write that is about no photo (the export presets, S2 E12)."""
        return self.folder.usable()

    def availability(self):
        """(available, reason) of the photo library (S2 E23)."""
        return self.folder.availability()

    # ------------------------------------------------------------------ answers
    def _status(self, preset):
        """PL4 preset_status: null / "missing" / "current" / "changed" (params only)."""
        if preset is None:
            return None
        params = self.library.params
        if preset["id"] not in params:
            return "missing"
        return "current" if params[preset["id"]].to_dict() == preset["params"] else "changed"

    def _fingerprint(self, path):
        """Content fingerprint of a checked photo path; a read failure is the photo's read error (invalid)."""
        return photo_fingerprint(path)

    def _answer(self, fp, edit):
        """The answer of every edit operation: {fingerprint, edit, preset_status, previous} (S4 key order)."""
        return {"fingerprint": fp, "edit": edit, "preset_status": self._status(edit["preset"] if edit else None),
                "previous": self.edits.has_previous(fp)}

    def _edit_summary(self, fp):
        """S8 / S8b: what the thumbnail grid shows about an edit: ({"preset": name|None, "strength", "status",
        "geometry": bool, "tweaks": bool}, the geometry object | None); (None, None) when the photo has no edit or its
        file cannot be read (the badge then only says "edited")."""
        obj = self.edits.read_quiet(fp)
        if obj is None:
            return None, None
        preset = obj["preset"]
        geometry = edit_geometry(obj)
        return {"preset": preset["name"] if preset else None, "strength": obj["strength"],
                "status": self._status(preset), "geometry": geometry is not None,
                "tweaks": bool(obj["overrides"])}, geometry

    def _resolve(self, edit, preset_id):
        """PL5: the snapshot when the edit holds this preset id, else the library's Params (not_found otherwise)."""
        if preset_id is None:
            return None
        if edit is not None and edit["preset"] is not None and edit["preset"]["id"] == preset_id:
            return edit_base_params(edit)
        if not isinstance(preset_id, str) or preset_id not in self.library.params:
            raise DarkroomError("not_found", M.UNKNOWN_OR_UNSUPPORTED_PRESET.format(pid=preset_id))
        return self.library.get(preset_id)

    def resolve_params(self, fingerprint, preset_id):
        """The one rule for the preset Params a preview, an export or set_edit uses (PL5, PLP5).

        fingerprint: the photo's content hash; preset_id: the preset asked for (None = no preset -> None).
        Returns Params: the edit's snapshot when the photo's saved edit uses this very preset, else the preset as
        it is in the library now. Raises not_found (unknown / unsupported preset), conflict (foreign edit schema)
        or unavailable (data folder). Reads the edit file; writes nothing."""
        if preset_id is None:
            return None
        return self._resolve(self.edits.read(fingerprint, fingerprint), preset_id)

    def saved_geometry(self, fingerprint):
        """CONTRACT-s3-crop C17 / C19 (D4): the geometry object of the photo's saved edit, None when it has none;
        conflict / unavailable as PLP5."""
        return edit_geometry(self.edits.read(fingerprint, fingerprint))

    # ------------------------------------------------------------------ edits (PL3, PL4, PL9)
    def get_edit(self, path):
        """The photo's saved edit -> {fingerprint, edit or None, preset_status, previous}. Read-only."""
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        return self._answer(fp, self.edits.read(fp, os.path.basename(path)))

    def set_edit(self, path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP):
        """Replace the photo's edit; returns the same answer shape as get_edit.

        geometry: KEEP (left out) keeps the saved crop, None removes it, a dict sets it. With no preset, no
        override and no geometry the edit is removed (and kept as "previous"). Choosing the preset the edit already
        has keeps its snapshot (so re-saving never silently picks up a changed preset file). Raises invalid /
        not_found / conflict / unavailable in the PL7 order. Writes data_dir/edits/ only."""
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        existing = self.edits.read(fp, os.path.basename(path))
        self._resolve(existing, preset_id)                                   # not_found before validate_* (PL7)
        adj = Adjustment.from_request(strength, overrides)                   # VO -> BO (invalid: the same sentences)
        if geometry is KEEP:                                       # C13 (D4): left out = the saved one
            g = edit_geometry(existing)
        else:
            g = validate_geometry(geometry)
            g = None if g is None else g.to_dict()
        if preset_id is None and adj.is_empty and g is None:                 # PL3': no edit at all (C12)
            self.edits.remove(path, fp, keep=existing)
            return self._answer(fp, None)
        preset = None
        if preset_id is not None:
            if existing is not None and existing["preset"] is not None and existing["preset"]["id"] == preset_id:
                preset = existing["preset"]                                  # PL4: the snapshot is kept
            else:
                row = self.library.by_id[preset_id]
                preset = {"id": preset_id, "name": row["name"], "group": row["group"],
                          "params": self.library.get(preset_id).to_dict()}
        edit = canonical_edit(fp, preset, strength, adj.overrides, g)
        self.edits.write(path, edit)
        return self._answer(fp, edit)

    def clear_edit(self, path):
        """Remove the photo's edit (kept as "previous" for restore_edit); conflict for a foreign schema version."""
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        existing = self.edits.read(fp, os.path.basename(path))               # PL9: a foreign version is not deleted
        self.edits.remove(path, fp, keep=existing)
        return self._answer(fp, None)

    def restore_edit(self, path):
        """S4: the edit kept when this photo's edit was last cleared goes back as its edit (the kept copy stays)."""
        path = checked_photo_path(path)
        fp = self._fingerprint(path)
        current = self.edits.read(fp, os.path.basename(path))                # conflict / unavailable first (PL9)
        prev = self.edits.read_previous(fp)
        if prev is None:
            raise DarkroomError("not_found", M.PL_NO_PREVIOUS.format(file_name=os.path.basename(path)))
        edit = canonical_edit(fp, prev["preset"], prev["strength"], prev["overrides"], edit_geometry(prev))
        # S4a / S4a': never over a different edit (it has no copy anywhere; the geometry counts too); the same edit
        # again is a no-op success
        if current is not None and canonical_edit(fp, current["preset"], current["strength"],
                                                  current["overrides"], edit_geometry(current)) != edit:
            raise DarkroomError("conflict", M.PL_RESTORE_OVER_EDIT.format(file_name=os.path.basename(path)))
        self.edits.write(path, edit)
        return self._answer(fp, edit)

    # ------------------------------------------------------------------ paste (PL8, PLP4)
    def paste_edit(self, targets, source=None, edit=None, *, with_geometry=False):
        """Copy one edit to each target -> {"results": [{ok, target[, error]}]}.

        Exactly one of `source` (a photo with an edit) or `edit` (an edit object) must be given. Without
        with_geometry only the colour part is copied and each target keeps its own crop; an edit that is only a crop
        is then refused. Request-level problems raise invalid / not_found; a target's own problem is its result
        entry. Writes data_dir/edits/ for each successful target."""
        if (source is None) == (edit is None):
            raise DarkroomError("invalid", M.PL_SOURCE_OR_EDIT)
        if (not isinstance(targets, list) or not 1 <= len(targets) <= TARGETS_MAX
                or not all(isinstance(t, str) for t in targets)):
            raise DarkroomError("invalid", M.PL_TARGETS_INVALID)
        validate_flag(with_geometry, M.WITH_GEOMETRY_INVALID)                # C14
        if source is not None:
            spath = checked_photo_path(source)
            src = self.edits.read(self._fingerprint(spath), os.path.basename(spath))
            if src is None:
                raise DarkroomError("not_found", M.PL_NO_EDIT.format(file_name=os.path.basename(spath)))
        else:
            reason = edit_problem(edit)
            if reason is not None:
                raise DarkroomError("invalid", M.PL_EDIT_INVALID.format(reason=reason))
            src = edit
        if not with_geometry and colourless(src):      # C14: only a geometry, and the geometry is not pasted
            raise DarkroomError("invalid", M.PASTE_GEOMETRY_ONLY)
        results = []
        for t in targets:
            name = os.path.basename(t.strip().strip('"'))
            try:
                tp = checked_photo_path(t)
                name = os.path.basename(tp)
                tfp = self._fingerprint(tp)
                current = self.edits.read(tfp, name)                         # conflict / unavailable: this item
                # C14: the colours of the source; its geometry only with with_geometry, else the target keeps its own
                g = edit_geometry(src) if with_geometry else edit_geometry(current)
                self.edits.write(tp, canonical_edit(tfp, src["preset"], src["strength"], src["overrides"], g))
                results.append({"ok": True, "target": name})
            except DarkroomError as e:
                results.append({"ok": False, "target": name, "error": e.message})
        return {"results": results}

    # ------------------------------------------------------------------ save as preset (PLP6)
    def save_edit_as_preset(self, path, name, group=None):
        """The edit's snapshot x strength + overrides written as a user preset by the preset library's K12 flow."""
        params = self.edit_params(path)
        return self.preset_library.save_params(name, group, params)

    @staticmethod
    def _final(edit):
        """Final Params of a stored edit: its snapshot at its strength plus its overrides (a valid edit, PL3)."""
        return Adjustment.from_request(edit["strength"], edit["overrides"]).final(edit_base_params(edit))

    def edit_params(self, path):
        """Final Params of a photo's edit (snapshot, strength, overrides); not_found when it has no edit."""
        path = checked_photo_path(path)
        edit = self.edits.read(self._fingerprint(path), os.path.basename(path))
        if edit is None:
            raise DarkroomError("not_found", M.PL_NO_EDIT.format(file_name=os.path.basename(path)))
        return self._final(edit)

    def saved_params(self, path, fp):
        """S2 E15: (final Params, "edit" | "original", geometry object | None) of the photo's saved edit (the snapshot
        first, as edit_params; its geometry, CONTRACT-s3-crop C19); no edit -> the photo as it is. DarkroomError
        (unavailable, conflict) as the edit commands give."""
        edit = self.edits.read(fp, os.path.basename(path))
        if edit is None:
            return ORIGINAL.final(None), "original", None
        return self._final(edit), "edit", edit_geometry(edit)

    # ------------------------------------------------------------------ thumbnails (PL11-PL13)
    def _generate(self, path):
        """Worker: one read of the bytes -> fingerprint + thumbnail -> thumbs/ -> index. (fingerprint, jpeg)."""
        folder = os.path.dirname(os.path.abspath(path))
        name = os.path.basename(path)
        self.folder.guard_folder(folder)                 # PLP1, before anything: a cache hit still writes the index
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            raise DarkroomError("invalid", M.PL_THUMB_FAILED.format(file_name=name, reason=one_line(e))) from None
        fp = fingerprint_bytes(data)
        jpeg = self.thumbs.read(fp)
        if jpeg is None:
            try:
                jpeg = make_thumbnail(data, os.path.splitext(path)[1].lower())
            except Exception as e:                       # cv2.error, ValueError, pillow-heif errors
                raise DarkroomError("invalid", M.PL_THUMB_FAILED.format(file_name=name,
                                                                        reason=one_line(e))) from None
            del data
            jpeg = self.thumbs.create(fp, jpeg)
        self.thumbs.remember(folder, name, st, fp)
        if self._queue.background_pending(folder) == 0:
            self.thumbs.flush(folder)
        return fp, jpeg

    def folder_thumbnails(self, folder, offset=0, limit=None):
        """The grid of a folder -> {folder, items: [{name, path, fingerprint, edited, cached}], total, next_offset}.

        Answers immediately from the index (fingerprint / edited are None until a thumbnail was made) and queues
        background generation for every photo without a cached thumbnail; a newer call for the same folder drops
        the older call's background jobs not yet started. Writes thumbs/ and index/ (in the background)."""
        if not isinstance(folder, str) or not folder.strip():
            raise DarkroomError("invalid", M.PATH_REQUIRED)
        folder = folder.strip().strip('"')
        if not os.path.isdir(folder):
            raise DarkroomError("not_found", M.PL_FOLDER_NOT_FOUND.format(folder=folder))
        if not is_int(offset) or offset < 0:
            raise DarkroomError("invalid", M.OFFSET_INVALID)
        if limit is not None and (not is_int(limit) or not 1 <= limit <= M.LIMIT_MAX):
            raise DarkroomError("invalid", M.LIMIT_INVALID)
        folder = os.path.abspath(folder)
        files = list_photos(folder)
        items, todo = [], []
        for f in files:
            fp = cached = None
            try:
                fp = self.thumbs.lookup(folder, f["name"], os.stat(f["path"]))
            except OSError:
                fp = None
            if fp is not None:
                cached = self.thumbs.exists(fp)
            items.append({"name": f["name"], "path": f["path"], "fingerprint": fp,
                          "edited": self.edits.exists(fp) if fp else None, "cached": bool(cached)})
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
        """One thumbnail -> ThumbnailResult; from the cache without opening the photo when possible, else made now
        at top priority. The saved crop is applied to the cached original on the way out."""
        path = checked_photo_path(path)
        folder = os.path.dirname(os.path.abspath(path))
        try:
            fp = self.thumbs.lookup(folder, os.path.basename(path), os.stat(path))
        except OSError:
            fp = None
        jpeg = None
        if fp is not None:
            jpeg = self.thumbs.read(fp)                      # warm: the photo file is not opened (PL16 b)
        if jpeg is None:
            fp, jpeg = self._queue.submit(path, folder, 0).wait()
        edited = self.edits.exists(fp)
        summary, geometry = self._edit_summary(fp) if edited else (None, None)
        if geometry is not None:                             # C18 (D7): the cached thumbnail is the original's
            jpeg = apply_geometry(jpeg, geometry)
        w, h = jpeg_size(jpeg)
        return ThumbnailResult(jpeg, fp, edited, w, h, summary)

    def wait_thumbnails(self, timeout=None):
        """Testing / bench helper: wait until the background queue is empty."""
        return self._queue.wait_idle(timeout)
