"""Named export presets kept in the photo library's data folder (CONTRACT-s2-export-detect E12, E13).

Layer: services. Depends on domain (`export_options.normalize_settings`, the one rule for export settings; errors;
messages) and on an `ExportPresetStore` the composition hands in (adapters/persist/export_presets_store.py: the
lock, the reads, the bad copy, the atomic write). Never imports the facade, adapters, config or the write module.

`data_dir/export-presets.json` holds {"schema": "darkroom-export-presets/1", "presets": {name: settings}}, the
presets sorted by name (casefold), each value the 8 normalised export settings of E1 (no second validation here).
A file that does not parse, or is not exactly the schema, reads as empty; before the next write a byte copy
`export-presets.json.bad-{unix seconds}` is kept (as SIP7). Another version of the schema is never overwritten
(conflict). Nothing here touches a photo, the GPU, torch or cv2.

Data flow of a change: take the store's lock -> read and sort out the file -> apply the change in memory -> keep a
.bad copy if the old bytes were damaged -> write the whole new file atomically (temp file + replace) -> release.
Readers never lock: the atomic replace means they see either the old or the new file.

Contract codes: E12 = file name, schema and sorting; E12a = a damaged entry only drops itself, a different schema
version is never overwritten; E13 = the three operations, name rules (1..60 characters, case-insensitive match,
same name replaces) and the 200-preset limit; E14 = how export() looks a preset up; SIP7 = the .bad copy convention
borrowed from the semantic index; PL9 = "never overwrite another schema version".
"""
import json
import unicodedata

from ..domain import messages as M
from ..domain.errors import DarkroomError
from ..domain.export_options import EXPORT_PRESETS_FILE, EXPORT_PRESETS_SCHEMA, SETTING_KEYS, normalize_settings

FILE_NAME = EXPORT_PRESETS_FILE                          # verbatim (E12)
SCHEMA = EXPORT_PRESETS_SCHEMA                           # verbatim (E12)
SCHEMA_PREFIX = "darkroom-export-presets/"
NAME_MAX = 60                                            # verbatim (E13)
PRESETS_MAX = 200                                        # verbatim (E13)


def clean_name(name):
    """E13: control characters removed, then stripped; None when not a string or not 1..60 characters."""
    if not isinstance(name, str):
        return None
    n = "".join(c for c in name if unicodedata.category(c) != "Cc").strip()
    return n if 1 <= len(n) <= NAME_MAX else None


def _sorted(presets):
    """The dict re-ordered by name (casefold first, exact spelling as tie-break) so the file is stable."""
    return {k: presets[k] for k in sorted(presets, key=lambda s: (s.casefold(), s))}


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


def file_bytes(presets):
    """The file's bytes for these presets (sorted by name; UTF-8)."""
    return json.dumps({"schema": SCHEMA, "presets": _sorted(presets)}, ensure_ascii=False).encode("utf-8")


class ExportPresetService:
    """The export-preset operations; all file access goes through the injected store."""

    def __init__(self, store):
        """store: adapters/persist/export_presets_store.ExportPresetStore."""
        self.store = store                       # ExportPresetStore (adapters/persist)

    @property
    def _data_dir_of(self):
        """The store's data folder resolver (tests point it at another folder)."""
        return self.store.data_dir_of

    @_data_dir_of.setter
    def _data_dir_of(self, fn):
        self.store.data_dir_of = fn

    # ------------------------------------------------------------------ the file
    def _read(self):
        """(presets dict, raw bytes or None, "missing" | "ok" | "bad"); another schema version -> conflict."""
        raw = self.store.read_raw()
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

    def _mutate(self, change):
        """Lock -> read -> change(presets) -> (bad copy kept first) -> atomic write; returns change's result."""
        root = self.store.root()
        with self.store.locked(root):
            presets, raw, state = self._read()
            result = change(presets)
            if state == "bad":
                self.store.keep_bad(root, raw)
            self.store.write(root, file_bytes(presets))
            return result

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
        """{"presets": [{name, settings}]} sorted by name; conflict for a foreign schema version. Read-only."""
        presets, _, _ = self._read()
        return {"presets": [{"name": k, "settings": v} for k, v in _sorted(presets).items()]}

    def save_export_preset(self, name, settings):
        """Store `settings` (normalised; no dest_dir) under `name` -> {name, settings, previous}.

        A preset with the same name (case-insensitive) is replaced and returned as `previous` so the caller can
        undo by saving it again. Raises invalid (name, settings, too many) or conflict. Writes export-presets.json."""
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
        """Remove one preset -> {name, settings} of what was removed; not_found when missing. Writes the file."""
        n = clean_name(name)

        def change(presets):
            for k in list(presets):
                if n is not None and k.casefold() == n.casefold():
                    return {"name": k, "settings": presets.pop(k)}
            raise DarkroomError("not_found", M.XP_NOT_FOUND.format(name=name))
        return self._mutate(change)
