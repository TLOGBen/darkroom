"""The settings file on disk: which file, reading it, and replacing it atomically (plan-v2 §3).

Layer: adapters/persist. File mechanics only; what the keys mean and which values are allowed is
`domain/settings.py`, the operations are `services/settings.py`.

Which file (the first that exists; writes go to the same file):

    1. the environment variable DARKROOM_CONFIG (used as given, even when the file does not exist yet)
    2. config.local.json at the repository root (running from source)
    3. the platform's settings folder: Windows %APPDATA%\\darkroom\\config.json, Linux
       $XDG_CONFIG_HOME/darkroom/config.json (default ~/.config), macOS ~/Library/Application Support/darkroom/config.json

When none exists, the platform file is the one a first save creates (its folder is made when its parent exists).

Writing: UTF-8 JSON, indented for people, through the write module (create_new tmp + replace_into, PermissionError
retried; root = the file's folder; `preset_dir=` the preset folder in use, so a settings file can never be written
into the preset folder). No cross-process lock: one small file replaced atomically, the last writer wins - a lock
file would sit next to config.local.json in the repository root. SafeWriteRefused is never caught.

Depends on domain (errors, messages, home_folder) and persist/locks; never on services, the facade or config (config
calls `locate` / `parse` from here, not the other way round). Secrets never pass through this module: the file holds
a 1Password reference at most.
"""
import json
import os
import sys

from ...domain import messages as M
from ...domain.errors import DarkroomError
from ...domain.settings import home_folder
from ...utils import safe_write
from ...utils.text import one_line
from . import locks

ENV_CONFIG = "DARKROOM_CONFIG"
FILE_NAME = "config.json"                  # the platform file's name (the repository's is config.local.json)


def platform_path(env=None, platform=None, home=None):
    """The platform's settings file (see the module docstring), or None when no folder is known."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        base = env.get("APPDATA")
        return os.path.join(base, "darkroom", FILE_NAME) if base else None
    h = home_folder(home)
    if platform == "darwin":
        return os.path.join(h, "Library", "Application Support", "darkroom", FILE_NAME) if h else None
    xdg = env.get("XDG_CONFIG_HOME")
    if isinstance(xdg, str) and xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "darkroom", FILE_NAME)
    return os.path.join(h, ".config", "darkroom", FILE_NAME) if h else None


def locate(repo_file, env=None, platform=None, home=None):
    """The settings file in use: DARKROOM_CONFIG -> repo_file when it exists -> the platform file when it exists ->
    the platform file to create (repo_file when no platform folder is known)."""
    env = os.environ if env is None else env
    given = env.get(ENV_CONFIG)
    if isinstance(given, str) and given.strip():
        return os.path.abspath(given.strip())
    if os.path.isfile(repo_file):
        return repo_file
    plat = platform_path(env, platform, home)
    if plat and os.path.isfile(plat):
        return plat
    return plat or repo_file


def parse(raw, file_name):
    """The settings object of the file's bytes; DarkroomError unavailable (one line: file, line, column) when it is
    not valid JSON or not an object - a broken file is never overwritten by a save."""
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as e:
        line = raw[:e.start].count(b"\n") + 1
        col = e.start - (raw.rfind(b"\n", 0, e.start) + 1) + 1
        raise DarkroomError("unavailable", M.SET_FILE_BROKEN.format(file_name=file_name, line=line, col=col,
                                                                     msg=e.reason)) from None
    except ValueError as e:
        raise DarkroomError("unavailable", M.SET_FILE_BROKEN.format(
            file_name=file_name, line=getattr(e, "lineno", 1), col=getattr(e, "colno", 1),
            msg=getattr(e, "msg", str(e)))) from None
    if not isinstance(obj, dict):
        raise DarkroomError("unavailable", M.SET_FILE_NOT_OBJECT.format(file_name=file_name))
    return obj


class SettingsStore:
    """Read / replace the settings file, read an import document, write an export document."""

    def __init__(self, path_of):
        """path_of: () -> the settings file path, evaluated on every use (DARKROOM_CONFIG may change in tests)."""
        self.path_of = path_of               # () -> the settings file (config.config_path; tests: a temporary file)

    @property
    def path(self):
        """The settings file in use now."""
        return self.path_of()

    def read(self):
        """The parsed settings object ({} when the file does not exist)."""
        path = self.path
        try:
            raw = locks.read_retry(path)
        except OSError as e:
            raise DarkroomError("unavailable", M.SET_CANNOT_WRITE.format(path=path, reason=one_line(e))) from None
        return {} if raw is None else parse(raw, os.path.basename(path))

    def write(self, obj, preset_dir):
        """Replace the settings file with `obj` (atomic). preset_dir: the folder the write module must keep out of."""
        path = self.path
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            parent = os.path.dirname(folder)
            if not os.path.isdir(parent):
                raise DarkroomError("unavailable", M.SET_CANNOT_WRITE.format(
                    path=path, reason=M.PL_PARENT_MISSING.format(parent=parent)))
            try:
                safe_write.make_dirs(folder, parent, preset_dir=preset_dir)
            except OSError as e:
                raise DarkroomError("unavailable", M.SET_CANNOT_WRITE.format(path=path, reason=one_line(e))) from None
        data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        locks.replace_atomic(path, folder, data, tmp_name=locks.tmp_name(os.path.basename(path)),
                             preset_dir=preset_dir, unavailable=M.SET_CANNOT_WRITE, fields={"path": path})

    @staticmethod
    def read_document(path):
        """The bytes of an export document to import; not_found when it does not exist."""
        try:
            raw = locks.read_retry(path)
        except OSError as e:
            raise DarkroomError("invalid", M.SET_DOC_JSON.format(reason=one_line(e))) from None
        if raw is None:
            raise DarkroomError("not_found", M.SET_IMPORT_NOT_FOUND.format(path=path))
        return raw

    @staticmethod
    def write_new(dest, data, preset_dir):
        """A new file `dest` (an export document); never overwrites (conflict), the folder must exist (invalid)."""
        folder = os.path.dirname(dest) if isinstance(dest, str) else None
        if not isinstance(dest, str) or not os.path.isabs(dest) or not os.path.isdir(folder):
            raise DarkroomError("invalid", M.SET_EXPORT_DEST.format(path=dest))
        try:
            safe_write.create_new(dest, folder, data, preset_dir=preset_dir)
        except FileExistsError:
            raise DarkroomError("conflict", M.SET_EXPORT_EXISTS.format(path=dest)) from None
        except OSError as e:
            raise DarkroomError("unavailable", M.SET_CANNOT_WRITE.format(path=dest, reason=one_line(e))) from None
        return dest
