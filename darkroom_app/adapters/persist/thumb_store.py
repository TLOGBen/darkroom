"""Thumbnail files and the thumbnail index of the photo library (CONTRACT-photo-library PL1, PL11-PL13, PLP8).

Layer: adapters/persist. Two kinds of file under data_dir:

* `thumbs/{fp[0:2]}/{fp}.jpg` - one 256 px JPEG per photo content (the fingerprint is the name, so the same content
  shares one thumbnail). Written with create_new only: a thumbnail is never replaced or removed (the write module
  cannot replace a .jpg anyway).
* `index/{sha256(normcase(realpath(folder)))[:16]}.json` - per photo folder, {name: {size, mtime_ns, fingerprint}},
  so a warm grid knows each photo's fingerprint without reading the photo (PL16 b). Kept in memory, loaded once per
  folder, written when the folder's background work is done (`flush`); an unreadable index is treated as empty.

Depends on `DataFolder` (data_dir, the PLP1 guard, writes) and domain; never on services, the facade or config.
Making the thumbnail pixels is `utils/imaging.py`; deciding when to make them is `services/photo_library.py`.

Thread safety: the background thumbnail workers and request threads share one ThumbStore; the in-memory index is
guarded by a re-entrant lock, and the file write of an index happens outside it (a slow disk must not block lookups).
Contract codes: PL1 = the folder names under data_dir; PL11 / PL12 / PL13 = thumbnail files, background generation,
the grid listing; PL16 b = a warm grid never opens the photos; PLP1 = the guard before every write; PLP8 = the index
schema.
"""
import hashlib
import json
import os
import threading

from ...domain.errors import DarkroomError
from ...utils.text import is_int, one_line
from .data_folder import log

THUMBS_DIR, INDEX_DIR = "thumbs", "index"                # verbatim (PL1)
INDEX_SCHEMA = "darkroom-thumb-index/1"                  # verbatim (PLP8)


class ThumbStore:
    """Cached thumbnails (content-addressed) and the per-folder name -> fingerprint index."""

    def __init__(self, folder):
        """folder: the shared DataFolder."""
        self.folder = folder                     # DataFolder
        self._lock = threading.RLock()
        self._index = {}                         # folder key -> {"folder", "key", "files": {name: {...}}, "dirty"}

    # ------------------------------------------------------------------ thumbnails
    def path(self, fp):
        """data_dir/thumbs/<fp[:2]>/<fp>.jpg."""
        return self.folder.path(THUMBS_DIR, fp[:2], fp + ".jpg")

    def exists(self, fp):
        """Is a thumbnail of this content cached?"""
        return os.path.exists(self.path(fp))

    def read(self, fp):
        """The cached thumbnail's bytes, None when there is none yet."""
        tp = self.path(fp)
        return self.folder.read(tp) if os.path.exists(tp) else None

    def create(self, fp, jpeg):
        """Keep `jpeg` as the thumbnail of fp (create_new); when another thread wrote the same content first, its
        bytes are returned instead. Unavailable (PL_CANNOT_WRITE) when it cannot be written."""
        tp = self.path(fp)
        self.folder.root()
        self.folder.make_dirs(os.path.dirname(os.path.dirname(tp)))
        self.folder.make_dirs(os.path.dirname(tp))
        try:
            self.folder.create_new(tp, jpeg)
        except FileExistsError:                      # another thread just wrote the same content's thumbnail
            return self.folder.read(tp) or jpeg
        except OSError as e:
            raise self.folder.cannot_write(one_line(e)) from None
        return jpeg

    # ------------------------------------------------------------------ the index (PL13, PLP8)
    @staticmethod
    def folder_key(folder):
        """(realpath of the folder, 16-hex key of its normcased realpath): the index file name, so the same folder
        reached through a junction or a different case shares one index."""
        real = os.path.realpath(folder)
        return real, hashlib.sha256(os.path.normcase(real).encode("utf-8")).hexdigest()[:16]

    def _index_path(self, key):
        """data_dir/index/<key>.json."""
        return self.folder.path(INDEX_DIR, key + ".json")

    def index_for(self, folder):
        """The in-memory index of a folder (loaded from disk once; unreadable = empty)."""
        real, key = self.folder_key(folder)
        with self._lock:
            idx = self._index.get(key)
            if idx is None:
                files = {}
                try:
                    raw = self.folder.read(self._index_path(key))
                    obj = json.loads(raw.decode("utf-8")) if raw else None
                    if (isinstance(obj, dict) and obj.get("schema") == INDEX_SCHEMA
                            and isinstance(obj.get("files"), dict)):
                        files = {n: e for n, e in obj["files"].items()
                                 if isinstance(e, dict) and is_int(e.get("size")) and is_int(e.get("mtime_ns"))
                                 and isinstance(e.get("fingerprint"), str)}
                except (OSError, ValueError, UnicodeDecodeError):
                    files = {}
                idx = self._index[key] = {"folder": real, "key": key, "files": files, "dirty": False}
            return idx

    def lookup(self, folder, name, st):
        """The fingerprint remembered for this file when its size and mtime still match, else None."""
        idx = self.index_for(folder)
        with self._lock:
            e = idx["files"].get(name)
            if e and e["size"] == st.st_size and e["mtime_ns"] == st.st_mtime_ns:
                return e["fingerprint"]
        return None

    def remember(self, folder, name, st, fp):
        """Record name -> (size, mtime, fingerprint) in memory and mark the index dirty (written by flush)."""
        idx = self.index_for(folder)
        with self._lock:
            idx["files"][name] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "fingerprint": fp}
            idx["dirty"] = True

    def flush(self, folder):
        """Write the folder's index when it changed; a failure keeps it in memory (written again next time)."""
        idx = self.index_for(folder)
        with self._lock:
            if not idx["dirty"]:
                return
            obj = {"schema": INDEX_SCHEMA, "folder": idx["folder"], "files": dict(idx["files"])}
            idx["dirty"] = False
        try:
            self.folder.write_json(self._index_path(idx["key"]), obj, "." + idx["key"], idx["folder"])
        except DarkroomError as e:
            with self._lock:
                idx["dirty"] = True              # kept in memory; written again next time
            log(f"index not written: {e.message}")
