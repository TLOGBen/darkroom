"""The photo library's data folder (`data_dir`): where it is, whether it may be written, and writing JSON into it.

Layer: adapters/persist (shared by `edit_store.py`, `thumb_store.py` and the export presets store; plan-v2 §1 lists
the two stores, this is the part they share). Depends on domain (errors, messages), utils (the write module via
`locks`, `text.one_line`); never on services, the facade, composition or config.

Everything the photo library knows lives under data_dir (edits/, thumbs/, index/; ADR-0002), never in a photo
folder. Where data_dir is comes from `data_dir_of`, a function the composition hands in: it returns the folder or
raises DarkroomError("unavailable", <the configuration's sentence>) (S2 E23 / PLP19: never an HTTP 500 or a CLI
configuration exit). It is resolved on first use only (PLP8), so commands that never touch the photo library never
need it.

Write rules (CONTRACT-write-guard G8 / G10, patch PLP1): every write goes through the write module with data_dir as
root and the preset folder in use as `preset_dir=`; before any write the data folder must not lie inside the photo's
folder or the preset folder (`guard_folder`); data_dir itself is created by the first write only, and only when its
parent exists (PL9, seal F1). SafeWriteRefused is never caught here.

Contract codes: ADR-0002 = the photo library lives in data_dir, keyed by content; PL9 = a missing data folder is
created only when its parent exists, else unavailable; PLP1 = the data folder may never lie inside the photo folder
being handled or the preset folder; PLP3 / KP12 / KP21 = read and replace retries on Windows sharing violations;
PLP8 = resolved on first use; PLP19 / E23 = an unresolvable folder is "unavailable" with the configuration's words.
"""
import json
import os
import sys

from ...domain import messages as M
from ...domain.errors import DarkroomError
from ...utils import safe_write
from ...utils.text import one_line
from . import locks


def log(text):
    """One stderr line for failures nobody waits for (background thumbnails, the index write)."""
    sys.stderr.write(f"[darkroom-photo-library] {text}\n")
    sys.stderr.flush()


class DataFolder:
    """data_dir: resolution, availability, guards and the guarded write helpers the photo-library stores share."""

    def __init__(self, data_dir_of, preset_dir):
        self._data_dir_of = data_dir_of         # () -> path; DarkroomError unavailable when none is configured
        self.preset_dir = preset_dir            # the preset folder in use, for the write module (PLP1)
        self._data_dir = None

    # ------------------------------------------------------------------ where
    @property
    def data_dir(self):
        """The data folder, absolute (S2 E19), resolved once on first use."""
        if self._data_dir is None:
            self._data_dir = os.path.abspath(self._data_dir_of())
        return self._data_dir

    def inside_preset_folder(self):
        """Does data_dir lie inside the preset folder in use (after resolving links and case)?"""
        real = os.path.normcase(os.path.realpath(self.data_dir))
        f = os.path.normcase(os.path.realpath(self.preset_dir))
        try:
            return os.path.commonpath([real, f]) == f
        except ValueError:
            return False

    def usable(self):
        """data_dir for a write that is about no photo (the export presets, S2 E12): unavailable when it cannot be
        resolved or lies inside the preset folder (PLP1 sentence)."""
        if self.inside_preset_folder():
            raise DarkroomError("unavailable", M.PL_DATA_DIR_INSIDE.format(data_dir=self.data_dir))
        return self.data_dir

    def availability(self):
        """(available, reason) of the photo library (S2 E23): resolvable, parent folder there, not in the preset
        folder; the reason is the very sentence the operations give."""
        try:
            d = self.data_dir
        except DarkroomError as e:
            return False, e.message
        if self.inside_preset_folder():
            return False, M.PL_DATA_DIR_INSIDE.format(data_dir=d)
        if not os.path.isdir(d):
            parent = os.path.dirname(os.path.abspath(d))
            if not os.path.isdir(parent):
                return False, M.PL_CANNOT_WRITE.format(data_dir=d, reason=M.PL_PARENT_MISSING.format(parent=parent))
        return True, None

    def path(self, *parts):
        """A path under data_dir (resolving data_dir on first use)."""
        return os.path.join(self.data_dir, *parts)

    # ------------------------------------------------------------------ guards
    def guard_folder(self, folder):
        """PLP1: the data folder must not lie inside the photo folder being handled or the preset folder.

        Called by every writing helper before it writes."""
        real = os.path.normcase(os.path.realpath(self.data_dir))
        for f in (folder, self.preset_dir):
            f = os.path.normcase(os.path.realpath(f))
            try:
                if os.path.commonpath([real, f]) == f:
                    raise DarkroomError("unavailable", M.PL_DATA_DIR_INSIDE.format(data_dir=self.data_dir))
            except ValueError:
                pass

    def guard_photo(self, photo_path):
        """guard_folder for the folder that contains `photo_path`."""
        self.guard_folder(os.path.dirname(os.path.abspath(photo_path)))

    def cannot_write(self, reason):
        """The PL9 "cannot write the data folder" error with `reason`."""
        return DarkroomError("unavailable", M.PL_CANNOT_WRITE.format(data_dir=self.data_dir, reason=reason))

    # ------------------------------------------------------------------ writing
    def make_dirs(self, folder):
        """Create `folder` (inside data_dir) when missing; an OSError becomes unavailable (PL9)."""
        if not os.path.isdir(folder):
            try:
                safe_write.make_dirs(folder, self.data_dir, preset_dir=self.preset_dir)
            except OSError as e:                     # read-only disk, permissions: PL9 unavailable
                raise self.cannot_write(one_line(e)) from None

    def root(self):
        """data_dir itself (the write module's root must exist): created by the first write only (PL9: a data_dir
        whose parent does not exist cannot be created and is unavailable, not an unexpected error - seal F1)."""
        d = self.data_dir
        if not os.path.isdir(d):
            parent = os.path.dirname(os.path.abspath(d))
            if not os.path.isdir(parent):
                raise self.cannot_write(M.PL_PARENT_MISSING.format(parent=parent))
            try:
                safe_write.make_dirs(d, parent, preset_dir=self.preset_dir)
            except OSError as e:
                raise self.cannot_write(one_line(e)) from None
        return d

    def write_json(self, dest, obj, tmp_prefix, photo_folder):
        """dest replaced atomically by obj as UTF-8 JSON (create_new(tmp) + replace_into, PermissionError retried
        with the KP21 budget; tmp never left). `photo_folder` is the photo folder this write is about: the PLP1 guard
        runs first, every time."""
        self.guard_folder(photo_folder)
        self.root()
        folder = os.path.dirname(dest)
        self.make_dirs(os.path.dirname(folder))
        self.make_dirs(folder)
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        locks.replace_atomic(dest, self.data_dir, data, tmp_name=locks.tmp_name(tmp_prefix),
                             preset_dir=self.preset_dir, unavailable=M.PL_CANNOT_WRITE,
                             fields={"data_dir": self.data_dir})

    def create_new(self, path, data):
        """A new file inside data_dir (a thumbnail): FileExistsError as is, other OSError as is."""
        return safe_write.create_new(path, self.data_dir, data, preset_dir=self.preset_dir)

    def remove(self, path):
        """Delete one file inside data_dir (an edit): FileNotFoundError and OSError as is."""
        safe_write.remove(path, self.data_dir, preset_dir=self.preset_dir)

    @staticmethod
    def read(path):
        """Bytes of a file in data_dir, None when missing; PermissionError retried like KP12 (PLP3)."""
        return locks.read_retry(path)
