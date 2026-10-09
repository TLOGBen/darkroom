"""Named export presets kept in the photo library's data folder (CONTRACT-s2-export-detect E12, E13).

`data_dir/export-presets.json` holds {"schema": "darkroom-export-presets/1", "presets": {name: settings}}, the
presets sorted by name (casefold), each value the 8 normalised export settings of E1 (`export.normalize_settings`,
the one rule; no second validation here). Writes only go through `safe_write` with data_dir as root and the preset
folder in use as `preset_dir=` (CONTRACT-write-guard G10, patch WG17): create_new(tmp) + replace_into under the
cross-process lock `export-presets.json.lock` (5 s -> conflict). A file that does not parse, or is not exactly the
schema, reads as empty; before the next write a byte copy `export-presets.json.bad-{unix seconds}` is kept (as SIP7).
Nothing here touches a photo, the GPU, torch or cv2. `SafeWriteRefused` is never caught.
"""
import json
import msvcrt
import os
import secrets
import time
import unicodedata

from .. import messages as M
from .. import safe_write
from ..errors import DarkroomError
from .export import SETTING_KEYS, normalize_settings

FILE_NAME = "export-presets.json"                        # verbatim (E12)
SCHEMA = "darkroom-export-presets/1"                     # verbatim (E12)
NAME_MAX = 60                                            # verbatim (E13)
PRESETS_MAX = 200                                        # verbatim (E13)
LOCK_WAIT_S, LOCK_POLL_S = 5.0, 0.02                     # as KP8
REPLACE_RETRIES, REPLACE_RETRY_S = 200, 0.01             # as KP21
N_MAX = 9999


def _one_line(e):
    return " ".join(str(e).split()) or type(e).__name__


def clean_name(name):
    """E13: control characters removed, then stripped; None when not a string or not 1..60 characters."""
    if not isinstance(name, str):
        return None
    n = "".join(c for c in name if unicodedata.category(c) != "Cc").strip()
    return n if 1 <= len(n) <= NAME_MAX else None


def _sorted(presets):
    return {k: presets[k] for k in sorted(presets, key=lambda s: (s.casefold(), s))}


SCHEMA_PREFIX = "darkroom-export-presets/"


def valid_entry(name, s):
    """True when one preset is a clean name with exactly the 8 normalised settings (E12)."""
    if clean_name(name) != name or not isinstance(s, dict) or list(s) != list(SETTING_KEYS):
        return False
    try:
        return normalize_settings(s) == s
    except DarkroomError:
        return False


def read_file(obj):
    """(presets kept, "ok" | "bad" | "foreign") of a parsed file (E12a, seal F2): another version of the schema is
    "foreign" (never rewritten, as PL9); otherwise only the presets that are not valid are dropped (state "bad", so
    the byte copy is kept before the next write) - one bad entry never empties the whole list."""
    if isinstance(obj, dict) and isinstance(obj.get("schema"), str) and obj["schema"] != SCHEMA \
            and obj["schema"].startswith(SCHEMA_PREFIX):
        return {}, "foreign"
    if not isinstance(obj, dict) or list(obj) != ["schema", "presets"] or obj["schema"] != SCHEMA \
            or not isinstance(obj["presets"], dict):
        return {}, "bad"
    kept = {k: v for k, v in obj["presets"].items() if valid_entry(k, v)}
    if len(kept) > PRESETS_MAX:
        kept = dict(list(kept.items())[:PRESETS_MAX])
    return kept, ("ok" if len(kept) == len(obj["presets"]) else "bad")


def valid_file(obj):
    """True when obj is exactly the E12 schema with normalised settings."""
    return read_file(obj)[1] == "ok"


class ExportPresetService:
    def __init__(self, data_dir_of, preset_dir):
        self._data_dir_of = data_dir_of          # () -> data_dir; DarkroomError unavailable when it is not usable
        self.preset_dir = preset_dir             # the preset folder in use, for safe_write

    # ------------------------------------------------------------------ the file
    def _paths(self):
        d = self._data_dir_of()
        return d, os.path.join(d, FILE_NAME)

    def _unavailable(self, reason):
        return DarkroomError("unavailable", M.XP_UNAVAILABLE.format(reason=reason))

    def _sw(self, fn, *args):
        return fn(*args, preset_dir=self.preset_dir)

    @staticmethod
    def _read_raw(path):
        for attempt in range(10):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except FileNotFoundError:
                return None
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.1)

    def _read(self):
        """(presets dict, raw bytes or None, "missing" | "ok" | "bad"); another schema version -> conflict."""
        _, path = self._paths()
        try:
            raw = self._read_raw(path)
        except OSError as e:
            raise self._unavailable(_one_line(e)) from None
        if raw is None:
            return {}, None, "missing"
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {}, raw, "bad"
        presets, state = read_file(obj)
        if state == "foreign":                                    # E12a: another version is never overwritten
            raise DarkroomError("conflict", M.XP_FOREIGN.format(schema=obj["schema"]))
        return presets, raw, state

    def _root(self):
        d, _ = self._paths()
        if not os.path.isdir(d):
            parent = os.path.dirname(os.path.abspath(d))
            if not os.path.isdir(parent):
                raise self._unavailable(M.PL_PARENT_MISSING.format(parent=parent))
            try:
                self._sw(safe_write.make_dirs, d, parent)
            except OSError as e:
                raise self._unavailable(_one_line(e)) from None
        return d

    def _acquire(self, root):
        lock = os.path.join(root, FILE_NAME + ".lock")
        try:
            fd = self._sw(safe_write.open_lock, lock, root)
        except OSError as e:
            raise self._unavailable(_one_line(e)) from None
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise DarkroomError("conflict", M.XP_BUSY) from None
                time.sleep(LOCK_POLL_S)

    @staticmethod
    def _release(fd):
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

    def _keep_bad(self, root, raw):
        base = os.path.join(root, f"{FILE_NAME}.bad-{int(time.time())}")
        for n in range(1, N_MAX + 1):
            path = base if n == 1 else f"{base}-{n}"
            try:
                self._sw(safe_write.create_new, path, root, raw)
                return path
            except FileExistsError:
                continue
            except OSError as e:
                raise self._unavailable(_one_line(e)) from None
        raise self._unavailable("no free .bad name")

    def _write(self, root, presets):
        dest = os.path.join(root, FILE_NAME)
        tmp = os.path.join(root, f"{FILE_NAME}.tmp-{os.getpid()}-{secrets.token_hex(6)}")
        data = json.dumps({"schema": SCHEMA, "presets": _sorted(presets)}, ensure_ascii=False).encode("utf-8")
        try:
            self._sw(safe_write.create_new, tmp, root, data)
        except OSError as e:
            raise self._unavailable(_one_line(e)) from None
        try:
            for attempt in range(REPLACE_RETRIES):
                try:
                    self._sw(safe_write.replace_into, tmp, dest, root)
                    return
                except PermissionError as e:
                    if attempt == REPLACE_RETRIES - 1:
                        raise self._unavailable(_one_line(e)) from None
                    time.sleep(REPLACE_RETRY_S)
                except OSError as e:
                    raise self._unavailable(_one_line(e)) from None
        finally:
            if os.path.exists(tmp):
                self._sw(safe_write.remove, tmp, root)

    def _mutate(self, change):
        """Lock -> read -> change(presets) -> (bad copy kept first) -> atomic write; returns change's result."""
        root = self._root()
        fd = self._acquire(root)
        try:
            presets, raw, state = self._read()
            result = change(presets)
            if state == "bad":
                self._keep_bad(root, raw)
            self._write(root, presets)
            return result
        finally:
            self._release(fd)

    # ------------------------------------------------------------------ lookups (export E14)
    def find(self, name):
        """(stored name, settings) of a preset (casefold), else not_found."""
        n = clean_name(name)
        presets, _, _ = self._read()
        for k, v in presets.items():
            if n is not None and k.casefold() == n.casefold():
                return k, v
        raise DarkroomError("not_found", M.XP_NOT_FOUND.format(name=name))

    # ------------------------------------------------------------------ operations (E13)
    def list_export_presets(self):
        presets, _, _ = self._read()
        return {"presets": [{"name": k, "settings": v} for k, v in _sorted(presets).items()]}

    def save_export_preset(self, name, settings):
        n = clean_name(name)
        if n is None:
            raise DarkroomError("invalid", M.XP_NAME_LENGTH)
        if not isinstance(settings, dict):
            raise DarkroomError("invalid", M.XP_SETTINGS_NOT_OBJECT.format(settings=settings))
        if "dest_dir" in settings:
            raise DarkroomError("invalid", M.XP_NO_DEST_DIR)
        for key in settings:
            if key not in SETTING_KEYS:
                raise DarkroomError("invalid", M.XP_UNKNOWN_KEY.format(key=key))
        s = normalize_settings(settings)

        def change(presets):
            previous = None
            for k in list(presets):
                if k.casefold() == n.casefold():
                    previous = presets.pop(k)
            presets[n] = s
            if len(presets) > PRESETS_MAX:
                raise DarkroomError("invalid", M.XP_TOO_MANY)
            return {"name": n, "settings": s, "previous": previous}
        return self._mutate(change)

    def delete_export_preset(self, name):
        n = clean_name(name)

        def change(presets):
            for k in list(presets):
                if n is not None and k.casefold() == n.casefold():
                    return {"name": k, "settings": presets.pop(k)}
            raise DarkroomError("not_found", M.XP_NOT_FOUND.format(name=name))
        return self._mutate(change)

