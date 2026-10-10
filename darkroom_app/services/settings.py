"""Settings operations: read, change, export, import, and the version report (plan-v2 §3).

Layer: services. Depends on domain (`domain.settings`: keys, defaults, checks, the file shape; errors; messages),
utils (`runtime_info`) and what the composition hands in: the `SettingsStore` (adapters/persist/settings_store.py),
the environment and platform to compute defaults from, a folder check, the preset folder in use, the capability
service, `pinned` - the folders the command line fixed for this process - and `on_applied` - the composition's
callback that rebuilds the app from the new settings. Never imports the facade, the entry adapters or config.

"Set" is all-or-nothing: every value is judged first (`validate_changes`), then the settings as a whole after the
change (`_check_whole`: there must still be a preset folder, and it must exist - a localllms_root that exists but
holds no artifact/11_preset/xmp is refused here, before the file is touched). Only then is the file replaced
atomically and `on_applied(keys)` rebuilds what depends on them (the preset library view, the photo library's data
folder, the capability cache) and returns the capability service to measure the checks with. If that rebuild still
fails, the previous file content is written back and the call is `unavailable` with SET_APPLY_FAILED - never an
HTTP 500, never a file the next start-up cannot use. Requests already running keep the objects they started with;
the next request sees the new ones.

Folders pinned by the command line (`--preset-dir`, `--data-dir`; `pinned`) win over the file for the life of the
process: get_settings reports them as in use with source "cli", and a set that changes one writes the file (it is
used from the next start without the flag) but lists the key in `pending_restart`, not in `applied`.

Side effects: set / import write the settings file (and only it); export with a destination writes one new file
(never overwriting). The API key itself is never read, stored or returned here: only a 1Password reference is a
valid value, and a value that looks like a key is refused without being echoed back.
"""
import json
import os
import sys

from ..domain import messages as M
from ..domain import settings as S
from ..domain.errors import DarkroomError
from ..utils.runtime_info import version_info
from ..utils.text import one_line

CHECKS = ("comfyui", "agent_sdk", "photo_library", "preset_library_writes")   # measured again after a change


class SettingsService:
    """get / set / export / import settings and the version report (operations 34..38)."""

    def __init__(self, store, *, app_version, env=None, platform=None, is_dir=os.path.isdir, preset_dir_of=None,
                 capabilities=None, on_applied=None, pinned=None):
        """Every dependency is injected (see the comments); env / platform / is_dir are replaceable for tests."""
        self.store = store                       # SettingsStore
        self.app_version = app_version           # darkroom_app.__version__ (the one version source)
        self.env = os.environ if env is None else env
        self.platform = platform                 # None: the running platform
        self.is_dir = is_dir
        self.preset_dir_of = preset_dir_of       # () -> the preset folder in use, or None (not configured yet)
        self.capabilities = capabilities         # CapabilityService of this composition (or None)
        self.on_applied = on_applied             # (keys) -> CapabilityService of the rebuilt app, or None
        self.pinned = dict(pinned or {})         # {key: folder} fixed by the command line for this process

    # ------------------------------------------------------------------ reading
    def _written(self):
        """(the parsed file object, {flat key: value} written in it)."""
        obj = self.store.read()
        base = os.path.dirname(os.path.abspath(self.store.path))
        return obj, S.flatten(obj, base)

    def _effective(self, written):
        """(settings, defaults, sources) the file and the environment give (no command-line pins)."""
        return S.effective(written, self.env, self.platform or sys.platform)

    def _in_use(self, written):
        """(settings, defaults, sources) actually in use by this process: the file's values with the folders the
        command line pinned put over them (source "cli")."""
        settings, defaults, sources = self._effective(written)
        for key, value in self.pinned.items():
            settings[key], sources[key] = value, "cli"
        return settings, defaults, sources

    def get_settings(self):
        """{settings, defaults, sources: {key: file | env | cli | default}, config_file}: the values in use."""
        _, written = self._written()
        settings, defaults, sources = self._in_use(written)
        return {"settings": settings, "defaults": defaults, "sources": sources, "config_file": self.store.path}

    # ------------------------------------------------------------------ changing
    def _protected(self, changes, current):
        """The preset folder the write module must keep out of: the new one, else the one in use, else the
        configured one; unavailable when none is known yet."""
        in_use = self.preset_dir_of() if self.preset_dir_of is not None else None
        d = changes.get("preset_dir") or in_use or current.get("preset_dir")
        if not d:
            raise DarkroomError("unavailable", M.SET_NEED_PRESET_DIR)
        return d

    def _checks(self, caps):
        """Re-measure the capability items a settings change can affect, so the reply says at once whether e.g.
        the new ComfyUI URL answers."""
        if caps is None:
            return {}
        out = {}
        for name in CHECKS:
            ok, reason = caps.feature(name, refresh=True)
            out[name] = {"available": ok, "reason": reason}
        return out

    def _check_whole(self, obj, changes):
        """The settings as a whole after `changes` must still name an existing preset folder (judged on the file's
        values, so the next start-up - without command-line flags - can use the file). Only when a key the preset
        folder is derived from changes: an unrelated change (language) is never blocked by an old problem.

        Raises invalid SET_NO_PRESET_DIR_AFTER (none left, e.g. preset_dir reset with no localllms_root) or
        SET_PRESET_DIR_AFTER_MISSING (e.g. a localllms_root without artifact/11_preset/xmp)."""
        if not set(changes) & set(S.LIBRARY_KEYS):
            return
        base = os.path.dirname(os.path.abspath(self.store.path))
        after, _, _ = self._effective(S.flatten(S.file_with(obj, changes), base))
        d = after.get("preset_dir")
        if not d:
            raise DarkroomError("invalid", M.SET_NO_PRESET_DIR_AFTER)
        if not self.is_dir(d):
            raise DarkroomError("invalid", M.SET_PRESET_DIR_AFTER_MISSING.format(value=d))

    def _apply(self, values):
        """Validate everything -> write the file atomically -> rebuild the app ->
        {settings, applied, pending_restart, checks}.

        Raises invalid (a bad value, or settings that no longer add up; nothing written), unavailable (no preset
        folder known to protect; or the rebuild failed - then the previous file content is back)."""
        obj, written = self._written()
        current, _, _ = self._effective(written)
        changes = S.validate_changes(values, current, self.is_dir, written)   # all judged before anything is written
        self._check_whole(obj, changes)
        protect = self._protected(changes, current)
        self.store.write(S.file_with(obj, changes), protect)
        applied = [k for k in changes if k not in self.pinned]
        pending = [k for k in changes if k in self.pinned]
        try:
            caps = self.on_applied(list(changes)) if self.on_applied is not None else self.capabilities
        except Exception as e:                      # the running app keeps its old objects; so does the file
            self.store.write(obj, protect)
            reason = e.message if isinstance(e, DarkroomError) else one_line(e)
            raise DarkroomError("unavailable", M.SET_APPLY_FAILED.format(reason=reason)) from None
        _, written = self._written()
        settings, _, _ = self._in_use(written)
        return {"settings": settings, "applied": applied, "pending_restart": pending, "checks": self._checks(caps)}

    def set_settings(self, values):
        """Partial update: {key: value, ...} (null resets a key); all valid or nothing is written."""
        return self._apply(values)

    # ------------------------------------------------------------------ export / import
    def export_settings(self, dest=None):
        """{format, version, settings} of what is written in the settings file; with dest (CLI / MCP) also written to
        that new file (never overwriting) and `output` added."""
        _, written = self._written()
        doc = S.export_document(written, self.app_version)
        if dest is None:
            return doc
        current, _, _ = self._effective(written)
        data = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        out = self.store.write_new(dest, data, self._protected({}, current))
        return {**doc, "output": out}

    def import_settings(self, document=None, path=None):
        """Apply an export document (given, as an object or JSON text, or read from `path`) exactly like set:
        an unknown key or a wrong format is invalid and nothing is written."""
        if (document is None) == (path is None):
            raise DarkroomError("invalid", M.SET_IMPORT_SOURCE)
        if path is not None:
            if not isinstance(path, str) or not path.strip():
                raise DarkroomError("invalid", M.SET_IMPORT_SOURCE)
            document = self.store.read_document(path.strip().strip('"')).decode("utf-8-sig", "replace")
        if isinstance(document, (bytes, str)):
            try:
                document = json.loads(document)
            except ValueError as e:
                raise DarkroomError("invalid", M.SET_DOC_JSON.format(reason=" ".join(str(e).split()))) from None
        return self._apply(S.document_values(document))

    # ------------------------------------------------------------------ version
    def version(self):
        """{version, python, torch, cuda, platform}."""
        return version_info(self.app_version)
