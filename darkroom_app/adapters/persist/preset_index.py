"""The preset library on disk: the three preset folders, `library.json` and `semantic.json` (plan-v2 §1).

Layer: adapters/persist. Two classes:

* `Library` - the read side and the in-process view. It scans `preset_dir`, `<root>/import/` and `<root>/user/`,
  parses each xmp once per (path, mtime, size), reads `library.json` (K4) and `semantic.json` (SI6), and keeps the
  view merge(index on disk, the three folders) (K5) up to date: the view is rebuilt when library.json's
  (st_ino, st_mtime_ns, st_size) changes (KP8) or after this process wrote it (`adopt`). What the bytes mean and
  what the editor sees (merge, the row, detail, flags, the group tree) are rules in `domain/presets.py`; the
  methods here only feed them.
* `PresetLibraryStore` - the write side: the cross-process lock `library.json.lock`, the atomic replacement of
  library.json, the `.bad-{t}` copy of an unreadable index, and new xmp files in import/, user/ or a folder the user
  chose (numbered names, never overwriting). Every write goes through `safe_write` with the library root as `root`
  and the preset folder in use as `preset_dir=` (CONTRACT-write-guard G8 / G10, patch KP1). The rules deciding
  *what* to write (names, groups, dedup, the user preset's bytes) stay in services/preset_library.py.

Depends on domain (presets rules, errors, messages), utils (safe_write via persist/locks) and the core
`darkroom.load_preset`; never on services, the facade, composition or config.

Why the view is cached and re-validated by a stat key: parsing all 1466 presets takes seconds, but several processes
(the App, a CLI command, the MCP server) may organise the library at the same time. Comparing library.json's
(inode, mtime_ns, size) before each use is cheap and notices another process's write; each xmp is re-parsed only
when its own (mtime, size) changed.

Contract codes: K1 / KP2 = where the root and folders are; K4 = index bytes and relative "file" paths; K5 = the
merge rule and the .bad copy; K10 = the group tree; K15 / KP8 = lock and change detection; KP1 = writes through the
guarded write module; KP4 = uploads are parsed through a temporary file that is always removed; KP9 = paths on
another drive stay absolute; KP21 = replace retries; SI6 = semantic.json; E17 = writing presets into a user-chosen
folder; B3 / K9 / SI10 / R4 = the row, favorites, tags and skip levels the view serves.
"""
import hashlib
import json
import os
import threading

from darkroom import UnsupportedPresetError, load_preset

from ...domain import messages as M
from ...domain.presets import (IMPORT_DIR, IMPORT_PREFIX, INDEX_NAME, SEMANTIC_NAME, USER_DIR, USER_PREFIX,
                               PresetFile, build_view, detail, empty_semantic, flags, group_tree, index_bytes, merge,
                               meta_of, row, stem_of, valid_index, valid_semantic)
from ...utils import safe_write
from ...utils.text import one_line
from . import locks

def _rel(path, root):
    """K4: the path relative to the library root with "/" separators; absolute when on another drive (KP9)."""
    try:
        rel = os.path.relpath(path, root)
    except ValueError:              # another drive (KP9)
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


def _parse_json(raw):
    """JSON of file bytes; a UTF-8 BOM is accepted (some editors add one), as K4 requires."""
    return json.loads(raw.decode("utf-8-sig"))


class Library:
    """The preset library as the editor sees it: id, group, name, supported, skipped, favorite (read only)."""

    def __init__(self, preset_dir, library_dir=None):
        """Scan and parse everything once. preset_dir: the purchased .xmp folder (must exist, FileNotFoundError
        otherwise); library_dir: the library root, default the preset folder's parent. Reads only."""
        self.preset_dir = preset_dir
        if not os.path.isdir(preset_dir):
            raise FileNotFoundError(f"preset folder not found: {preset_dir}")
        self.root = os.path.abspath(library_dir if library_dir is not None
                                    else os.path.dirname(os.path.abspath(preset_dir)))
        self.index_path = os.path.join(self.root, INDEX_NAME)
        self.import_dir = os.path.join(self.root, IMPORT_DIR)
        self.user_dir = os.path.join(self.root, USER_DIR)
        self.semantic_path = os.path.join(self.root, SEMANTIC_NAME)
        self._lock = threading.RLock()
        self._cache = {}          # normcase(path) -> PresetFile
        self._stamp = None        # stat key of library.json behind the current view (None: missing)
        self._semantic = (None, empty_semantic(), "missing")   # (stamp, index, state) of semantic.json (SI6)
        self._load()

    # ---------------------------------------------------------------- the semantic index (read only, SI6)
    @staticmethod
    def _stat_key(path):
        """(inode, mtime_ns, size) of a file, None when it does not exist: "has this file changed?"."""
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def read_semantic(self):
        """(index, state): the semantic index on disk, or the empty one; state missing | ok | bad. A bad or
        unparsable file is left alone (never renamed or deleted)."""
        raw = locks.read_retry(self.semantic_path)
        if raw is None:
            return empty_semantic(), "missing"
        try:
            obj = _parse_json(raw)
        except (UnicodeDecodeError, ValueError):
            return empty_semantic(), "bad"
        return (obj, "ok") if valid_semantic(obj) else (empty_semantic(), "bad")

    def semantic_raw(self):
        """The bytes of semantic.json, None when missing (the store keeps a copy before replacing a bad one)."""
        return locks.read_retry(self.semantic_path)

    def semantic(self):
        """The semantic index, re-read when semantic.json changed (stat key, like library.json)."""
        stamp = self._stat_key(self.semantic_path)
        with self._lock:
            if stamp != self._semantic[0]:
                try:
                    index, state = self.read_semantic()
                except PermissionError:
                    return self._semantic[1]
                self._semantic = (stamp, index, state)
            return self._semantic[1]

    def semantic_state(self):
        """"missing" | "ok" | "bad" of semantic.json as last read."""
        self.semantic()
        return self._semantic[2]

    def sha_of(self, pid):
        """The content sha256 of a preset in the view (None when unknown)."""
        f = self.files().get(pid)
        return None if f is None else f.sha256

    def semantic_entry(self, pid):
        """The semantic index entry of a preset (looked up by its content hash), or None."""
        sha = self.sha_of(pid)
        return None if sha is None else self.semantic()["entries"].get(sha)

    # ---------------------------------------------------------------- reading files
    @staticmethod
    def stem_name(pid):
        """"user:暖調" -> "暖調" (the file stem, the display name of a new preset without crs:Name)."""
        return stem_of(pid)[1]

    def path_of(self, pid):
        """The .xmp path of a preset id: preset_dir/<stem>.xmp, import/<stem>.xmp or user/<stem>.xmp."""
        prefix, stem = stem_of(pid)
        folder = {IMPORT_PREFIX: self.import_dir, USER_PREFIX: self.user_dir}.get(prefix, self.preset_dir)
        return os.path.join(folder, stem + ".xmp")

    def file_info(self, path, stamp=None):
        """PresetFile for an xmp path (cached per (mtime, size)); None when it cannot be read."""
        try:
            if stamp is None:
                st = os.stat(path)
                stamp = (st.st_mtime_ns, st.st_size)
            key = os.path.normcase(os.path.abspath(path))
            with self._lock:
                hit = self._cache.get(key)
            if hit is not None and hit.stamp == stamp:
                return hit
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        try:
            params = load_preset(path)
            supported, skipped = True, list(params.skipped)
        except (UnsupportedPresetError, OSError, ValueError, LookupError):   # LookupError: unknown XML encoding
            params, supported, skipped = None, False, []
        name, group = meta_of(data) if supported else ("", "")
        info = PresetFile(path, _rel(path, self.root), stamp, hashlib.sha256(data).hexdigest(), supported, skipped,
                          params, name, group)
        with self._lock:
            self._cache[key] = info
        return info

    def scan(self):
        """{id: PresetFile} for the first-level *.xmp of preset_dir, import/ and user/ (K5)."""
        out = {}
        for folder, prefix in ((self.preset_dir, ""), (self.import_dir, IMPORT_PREFIX), (self.user_dir, USER_PREFIX)):
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except (FileNotFoundError, NotADirectoryError):
                continue
            for e in entries:
                stem, ext = os.path.splitext(e.name)
                if ext.lower() != ".xmp" or stem_of(prefix + stem) is None:
                    continue
                try:
                    if not e.is_file():
                        continue
                    st = e.stat()
                except OSError:
                    continue
                info = self.file_info(e.path, (st.st_mtime_ns, st.st_size))
                if info is not None:
                    out[prefix + stem] = info
        return out

    def index_stamp(self):
        """library.json's current stat key (None when missing)."""
        return self._stat_key(self.index_path)

    def read_index(self):
        """(index or None, raw bytes or None, "missing" | "ok" | "bad"); the file is closed right after reading."""
        raw = locks.read_retry(self.index_path)
        if raw is None:
            return None, None, "missing"
        try:
            obj = _parse_json(raw)
        except (UnicodeDecodeError, ValueError):
            return None, raw, "bad"
        return (obj, raw, "ok") if valid_index(obj) else (None, raw, "bad")

    def merged(self, index, files=None):
        """The K5 merge of an index (None = no index yet) with the presets found in the folders."""
        return merge(index, self.scan() if files is None else files, self.stem_name)

    @staticmethod
    def read_bytes(path):
        """The bytes of one preset file (export / download); OSError to the caller."""
        with open(path, "rb") as f:
            return f.read()

    # ---------------------------------------------------------------- the view
    def _load(self):
        """(Re)build the view from disk. If library.json is momentarily locked by a writer, keep the current view
        (or start from no index on the very first load)."""
        with self._lock:
            stamp = self.index_stamp()
            try:
                index, _, _ = self.read_index()
            except PermissionError:
                if hasattr(self, "_entries"):
                    return
                index = None
            files = self.scan()
            self._set_view(merge(index, files, self.stem_name), files, stamp)

    def refresh(self):
        """Re-read the index when library.json changed since the view was built (K15, KP8)."""
        if self.index_stamp() != self._stamp:
            self._load()

    def adopt(self, index, files):
        """The view after this process wrote `index` (files: {id: PresetFile} it was built from)."""
        with self._lock:
            self._set_view(index, files, self.index_stamp())

    def _set_view(self, index, files, stamp):
        """Install a new view (sorted rows, rows by id, Params by id) and remember which library.json it reflects."""
        entries, by_id, params = build_view(index, files)
        self._index, self._files = index, files
        self._entries, self._by_id, self._params = entries, by_id, params
        self._stamp = stamp

    # Each accessor below first checks whether another process changed library.json (refresh), so callers always see
    # the current organisation without restarting.
    @property
    def entries(self):
        """Rows sorted by group / name / id (6 columns, without tags)."""
        self.refresh()
        return self._entries

    @property
    def by_id(self):
        """{id: row}."""
        self.refresh()
        return self._by_id

    @property
    def params(self):
        """{id: Params} for the supported presets only."""
        self.refresh()
        return self._params

    @property
    def index(self):
        """The merged index object (library.json's shape)."""
        self.refresh()
        return self._index

    def files(self):
        """{id: PresetFile} the view was built from."""
        self.refresh()
        return self._files

    def get(self, pid):
        """Params for a supported preset id, else KeyError."""
        return self.params[pid]

    def row(self, pid):
        """The 7-column row (B3, K9, SI10)."""
        return row(self.by_id[pid], self.semantic_entry(pid))

    def detail(self, pid):
        """One preset's detail (domain.presets.detail); KeyError for an unknown id."""
        return detail(pid, self.by_id[pid], self._params.get(pid))

    def flags(self):
        """{id: "major"|"minor"} for presets with skipped settings (contract R4)."""
        return flags(self.entries)

    def group_tree(self):
        """K10: the group tree with counts (domain.presets.group_tree)."""
        entries = self.entries
        return group_tree(entries, self._index)


class PresetLibraryStore:
    """Writes of the preset library: library.json (locked, atomic, bad copy) and new xmp files (never overwriting)."""

    def __init__(self, library, preset_dir):
        """library: the Library whose root is written; preset_dir: protected by every write."""
        self.library = library
        self.preset_dir = preset_dir           # the purchased preset folder in use, for safe_write (KP1)

    @property
    def root(self):
        """The library root (the write module's root for every write here, except create_in)."""
        return self.library.root

    def locked(self):
        """The cross-process lock `<root>/library.json.lock` (busy -> conflict LIB_BUSY, K15)."""
        return locks.held(os.path.join(self.root, INDEX_NAME + ".lock"), self.root, preset_dir=self.preset_dir,
                          busy=M.LIB_BUSY, unavailable=M.LIB_INDEX_UNAVAILABLE)

    def keep_bad(self, raw, now):
        """K5 / KP1: a byte copy library.json.bad-{unix seconds} (-{n} when that second is taken)."""
        return locks.keep_bad(self.root, INDEX_NAME, raw, now, preset_dir=self.preset_dir,
                              unavailable=M.LIB_INDEX_UNAVAILABLE)

    def write_index(self, index):
        """library.json replaced atomically (K4 bytes); PermissionError retried with the KP21 budget."""
        locks.replace_atomic(self.library.index_path, self.root, index_bytes(index), tmp_name=locks.tmp_name(INDEX_NAME),
                             preset_dir=self.preset_dir, unavailable=M.LIB_INDEX_UNAVAILABLE)

    def _make_dir(self, folder):
        """Create import/ or user/ under the root when missing."""
        if not os.path.isdir(folder):
            safe_write.make_dirs(folder, self.root, preset_dir=self.preset_dir)

    def create_numbered(self, folder, stems, data, unavailable, used_up):
        """create_new {stem}.xmp for the first free stem of `stems` ({stem}, {stem} (2) ... - the service's naming
        rule, K11 / K12) in folder (import/ or user/); (final stem, path). Never overwrites.

        `unavailable(reason)` builds the exception raised when nothing could be written; `used_up` is the reason
        when every name is taken."""
        try:
            self._make_dir(folder)
            for s in stems:
                path = os.path.join(folder, s + ".xmp")
                if os.path.dirname(os.path.abspath(path)) != os.path.abspath(folder):    # K14: stays in folder
                    continue
                try:
                    safe_write.create_new(path, self.root, data, preset_dir=self.preset_dir)
                    return s, path
                except FileExistsError:
                    continue
        except OSError as e:
            raise unavailable(one_line(e)) from None
        raise unavailable(used_up)

    def check_upload(self, data, token, failed):
        """load_preset on uploaded bytes: a temporary import/.upload-{pid}-{token}.tmp, always removed (KP4).

        `failed(reason)` builds the exception raised when the temporary file cannot be written; load_preset's own
        errors (UnsupportedPresetError, ValueError, ...) go out unchanged for the caller to word."""
        import_dir = self.library.import_dir
        tmp = os.path.join(import_dir, f".upload-{os.getpid()}-{token}.tmp")
        try:
            self._make_dir(import_dir)
            safe_write.create_new(tmp, self.root, data, preset_dir=self.preset_dir)
        except OSError as e:
            raise failed(one_line(e)) from None
        try:
            load_preset(tmp)
        finally:
            safe_write.remove(tmp, self.root, preset_dir=self.preset_dir)

    def create_in(self, dest_dir, name, data):
        """A new file `dest_dir/name` (the folder the user chose for `presets export`, E17); FileExistsError when the
        name is taken, other OSError as is. dest_dir itself is the safe_write root (never created)."""
        path = os.path.join(dest_dir, name)
        safe_write.create_new(path, dest_dir, data, preset_dir=self.preset_dir)
        return path

