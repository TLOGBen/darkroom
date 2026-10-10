"""Edit files of the photo library: `data_dir/edits/{fp[0:2]}/{fp}.json` and the kept previous edit
`{fp}.prev.json` (CONTRACT-photo-library PL1, PL3, PL9; CONTRACT-s1-experience S4).

Layer: adapters/persist. Reads and writes edit files and nothing else; whether an edit is well-formed is
`domain.edits.edit_problem`, which edit to write is `services/photo_library.py`. Depends on `DataFolder` (where
data_dir is, the PLP1 guard, the atomic JSON write) and domain; never on services, the facade or config.

Reading an edit (PL9): a missing file is "no edit"; a file that cannot be read is unavailable (PL_CANNOT_READ); a
file that is not JSON or not an edit is unavailable (PL_EDIT_CORRUPT); another version of the schema is a conflict
and is never overwritten or deleted (PL_SCHEMA_CONFLICT).

Why files are sharded by the first two hex characters of the fingerprint: a library of tens of thousands of photos
would otherwise put every edit into one folder, which slows down listing and backup tools on Windows.
"""
import json
import os

from ...domain import messages as M
from ...domain.edits import EDIT_SCHEMA, EDIT_SCHEMA_V2, edit_problem
from ...domain.errors import DarkroomError
from ...utils.text import one_line

EDITS_DIR = "edits"                                      # verbatim (PL1)
PREV_SUFFIX = ".prev.json"                               # verbatim (S4): edits/{fp[0:2]}/{fp}.prev.json


class EditStore:
    """Edit files keyed by photo fingerprint (one current edit plus one kept previous edit per fingerprint)."""

    def __init__(self, folder):
        """folder: the shared DataFolder."""
        self.folder = folder                     # DataFolder

    # ------------------------------------------------------------------ paths
    def path(self, fp):
        """data_dir/edits/<fp[:2]>/<fp>.json (the folder is not created here)."""
        return self.folder.path(EDITS_DIR, fp[:2], fp + ".json")

    def prev_path(self, fp):
        """data_dir/edits/<fp[:2]>/<fp>.prev.json: the edit removed last, for restore_edit."""
        return self.folder.path(EDITS_DIR, fp[:2], fp + PREV_SUFFIX)

    def exists(self, fp):
        """True when the photo has an edit file (the thumbnail grid's "edited" flag; never parsed here)."""
        return os.path.exists(self.path(fp))

    # ------------------------------------------------------------------ reading
    def read(self, fp, file_name):
        """The edit object for a fingerprint, None when there is none; conflict / unavailable as PL9."""
        p = self.path(fp)
        try:
            raw = self.folder.read(p)
        except OSError as e:
            raise DarkroomError("unavailable", M.PL_CANNOT_READ.format(edit_file=p, reason=one_line(e))) from None
        if raw is None:
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise DarkroomError("unavailable", M.PL_EDIT_CORRUPT.format(edit_file=p)) from None
        if isinstance(obj, dict) and "schema" in obj and obj["schema"] not in (EDIT_SCHEMA, EDIT_SCHEMA_V2):
            raise DarkroomError("conflict", M.PL_SCHEMA_CONFLICT.format(schema=obj.get("schema"),
                                                                         file_name=file_name))
        if edit_problem(obj) is not None:
            raise DarkroomError("unavailable", M.PL_EDIT_CORRUPT.format(edit_file=p))
        return obj

    def read_quiet(self, fp):
        """The edit object, or None when there is none or it cannot be read (the grid's badge then says less)."""
        try:
            raw = self.folder.read(self.path(fp))
            obj = json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        return obj if isinstance(obj, dict) and edit_problem(obj) is None else None

    def read_previous(self, fp):
        """The kept previous edit of a fingerprint, None when there is none or it is unreadable."""
        try:
            raw = self.folder.read(self.prev_path(fp))
            obj = json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        return obj if isinstance(obj, dict) and edit_problem(obj) is None and obj["fingerprint"] == fp else None

    def has_previous(self, fp):
        """Is there a kept previous edit (the `previous` flag of every edit answer)?"""
        return os.path.exists(self.prev_path(fp))

    # ------------------------------------------------------------------ writing
    def write(self, photo_path, edit):
        """The photo's edit file replaced atomically (PLP1 guard against the photo's own folder first)."""
        fp = edit["fingerprint"]
        self.folder.write_json(self.path(fp), edit, "." + fp, os.path.dirname(os.path.abspath(photo_path)))

    def remove(self, photo_path, fp, keep=None):
        """Delete the edit file; the edit being cleared is first kept as the one previous edit (S4)."""
        p = self.path(fp)
        if os.path.exists(p):
            self.folder.guard_photo(photo_path)
            if keep is not None:
                self.folder.write_json(self.prev_path(fp), keep, "." + fp + ".prev",
                                       os.path.dirname(os.path.abspath(photo_path)))
            try:
                self.folder.remove(p)
            except FileNotFoundError:
                pass
            except OSError as e:
                raise self.folder.cannot_write(one_line(e)) from None
