"""The export presets file `data_dir/export-presets.json` on disk (CONTRACT-s2-export-detect E12, E13).

Layer: adapters/persist. File mechanics only - where the file is, the cross-process lock
`export-presets.json.lock` (5 s -> conflict XP_BUSY), reading with retries, the byte copy
`export-presets.json.bad-{unix seconds}` of a file that did not read cleanly, and the atomic replacement. What the
file must contain and which presets are kept is `services/export_presets.py`'s business.

The data folder is resolved by a function the composition hands in (`data_dir_of`, which raises
DarkroomError unavailable when the photo library's data folder cannot be used, S2 E23), so this store never reads the
configuration. Writes go through the write module with data_dir as root and the preset folder in use as `preset_dir=`
(CONTRACT-write-guard G10, patch WG17). SafeWriteRefused is never caught.

Contract codes: E12 = file name and location; E13 = the operations this file serves; E23 = unavailable when the data
folder cannot be used; G10 / WG17 = this module is on the write module's whitelist.
"""
import os
import time

from ...domain import messages as M
from ...domain.errors import DarkroomError
from ...domain.export_options import EXPORT_PRESETS_FILE
from ...utils import safe_write
from ...utils.text import one_line
from . import locks

FILE_NAME = EXPORT_PRESETS_FILE                          # verbatim (E12)


class ExportPresetStore:
    """File mechanics of export-presets.json (see the module docstring)."""

    def __init__(self, data_dir_of, preset_dir, clock=None):
        """data_dir_of: () -> data_dir (may raise unavailable); preset_dir: protected by every write; clock: tests."""
        self.data_dir_of = data_dir_of            # () -> data_dir; DarkroomError unavailable when it is not usable
        self.preset_dir = preset_dir              # the preset folder in use, for the write module
        self.clock = clock                        # names the .bad-{t} copy

    def _unavailable(self, reason):
        """The export-presets unavailable error with `reason`."""
        return DarkroomError("unavailable", M.XP_UNAVAILABLE.format(reason=reason))

    def paths(self):
        """(data_dir, data_dir/export-presets.json); raises unavailable when data_dir cannot be resolved."""
        d = self.data_dir_of()
        return d, os.path.join(d, FILE_NAME)

    def read_raw(self):
        """The file's bytes, None when it does not exist (PermissionError retried; other OSError -> unavailable)."""
        _, path = self.paths()
        try:
            return locks.read_retry(path)
        except OSError as e:
            raise self._unavailable(one_line(e)) from None

    def root(self):
        """data_dir, created when its parent exists (the first save makes it); unavailable otherwise."""
        d, _ = self.paths()
        if not os.path.isdir(d):
            parent = os.path.dirname(os.path.abspath(d))
            if not os.path.isdir(parent):
                raise self._unavailable(M.PL_PARENT_MISSING.format(parent=parent))
            try:
                safe_write.make_dirs(d, parent, preset_dir=self.preset_dir)
            except OSError as e:
                raise self._unavailable(one_line(e)) from None
        return d

    def locked(self, root):
        """Context manager holding export-presets.json.lock (conflict XP_BUSY after 5 s)."""
        return locks.held(os.path.join(root, FILE_NAME + ".lock"), root, preset_dir=self.preset_dir,
                          busy=M.XP_BUSY, unavailable=M.XP_UNAVAILABLE)

    def keep_bad(self, root, raw):
        """Keep a byte copy export-presets.json.bad-{t} of a damaged file before it is replaced; its path."""
        return locks.keep_bad(root, FILE_NAME, raw, (self.clock or time.time)(), preset_dir=self.preset_dir,
                              unavailable=M.XP_UNAVAILABLE)

    def write(self, root, data):
        """Replace export-presets.json atomically with `data` (bytes)."""
        locks.replace_atomic(os.path.join(root, FILE_NAME), root, data, tmp_name=locks.tmp_name(FILE_NAME),
                             preset_dir=self.preset_dir, unavailable=M.XP_UNAVAILABLE)
