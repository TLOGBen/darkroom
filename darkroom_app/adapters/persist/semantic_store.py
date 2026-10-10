"""The semantic index file `<library root>/semantic.json` on the write side (CONTRACT-semantic-index SI6, SIP7).

Layer: adapters/persist. Reading the index (and caching it per stat key) is `Library.semantic()` in
`preset_index.py`; this store is the lock `semantic.json.lock` (busy -> conflict LIB_BUSY), the byte copy
`semantic.json.bad-{clock}` of an unreadable file - the user paid for those tags, nothing of theirs is overwritten
silently (SIP7) - and the atomic replacement (KP21 retry budget). Root = the library root, `preset_dir=` the preset
folder in use. SafeWriteRefused is never caught.

Depends on `locks` and domain; never on services, the facade or config. Contract codes: SI6 = the file's schema and
location (the library root); SIP7 = the .bad copy before replacing an unreadable index; KP21 = the replace retries.
"""
import json
import os
import threading
import time

from ...domain import messages as M
from ...domain.presets import SEMANTIC_NAME
from . import locks


def _json_bytes(index):
    """Compact UTF-8 JSON (non-ASCII tags stay readable in the file)."""
    return json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SemanticStore:
    """The write side of semantic.json: lock, .bad copy, atomic replace."""

    def __init__(self, library, preset_dir, clock=None):
        """library: the preset view (knows the root and reads the file); preset_dir: protected by every write."""
        self.library = library
        self.preset_dir = preset_dir
        self.clock = clock                       # the injected clock names the .bad copy (tests use a fake)
        self.tlock = threading.Lock()            # one writer per process; the file lock covers other processes

    @property
    def root(self):
        """The preset library root folder."""
        return self.library.root

    def locked(self):
        """Context manager holding semantic.json.lock (conflict after 5 s)."""
        return locks.held(os.path.join(self.root, SEMANTIC_NAME + ".lock"), self.root, preset_dir=self.preset_dir,
                          busy=M.LIB_BUSY, unavailable=M.SEM_INDEX_UNAVAILABLE)

    def keep_bad(self):
        """SIP7: before a bad semantic.json is replaced, keep a byte copy semantic.json.bad-{unix seconds}
        (-{n} when that second is taken); None when there is no file."""
        raw = self.library.semantic_raw()
        if raw is None:
            return None
        return locks.keep_bad(self.root, SEMANTIC_NAME, raw, (self.clock or time.time)(), preset_dir=self.preset_dir,
                              unavailable=M.SEM_INDEX_UNAVAILABLE)

    def write(self, index):
        """Replace semantic.json atomically with `index`; unavailable when it cannot be written."""
        locks.replace_atomic(self.library.semantic_path, self.root, _json_bytes(index),
                             tmp_name=locks.tmp_name(SEMANTIC_NAME), preset_dir=self.preset_dir,
                             unavailable=M.SEM_INDEX_UNAVAILABLE)
