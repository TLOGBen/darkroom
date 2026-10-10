"""Settings: the keys, their defaults, their checks, the file shape and the export document (plan-v2 §3).

Layer: domain. Pure: nothing here opens a file or reads the environment by itself. The settings file is read and
written by `adapters/persist/settings_store.py`; `services/settings.py` runs the operations; `darkroom_app.config`
(the old entry-point readers) and the composition read the same file through `flatten` / `effective`.

Keys (all optional; a key that is not written takes its default). The API uses flat dotted names; the file nests the
`agent.*` keys under one "agent" object:

    language                  "zh-TW" | "en-US"                         default zh-TW
    preset_dir                the purchased .xmp folder                 default <localllms_root>/artifact/11_preset/xmp
    preset_library_dir        library.json, import/, user/              default the parent of preset_dir
    data_dir                  the photo library (edits, thumbnails)     default the platform's data folder
    localllms_root            the LocalLLMs checkout                    environment LOCALLLMS_ROOT wins
    comfyui_url               ComfyUI's API, loopback only              default http://127.0.0.1:8188
    comfyui_root              ComfyUI's install folder                  default none
    agent.api_key_ref         a 1Password reference op://...            never the key itself
    agent.model               the Claude model for agent work           default claude-haiku-5-5
    agent.budget_usd          spending cap of one semantic build        default 5
    calibration_sources_dir   the four public calibration photos        default <localllms_root>/scratch/lr-calibration/sources

Old keys are still read: `anthropic_api_key_ref` (= agent.api_key_ref) and `semantic_index_budget_usd`
(= agent.budget_usd); a write always uses the new key and drops the old one.

`validate_changes` is the one check for a partial update (PUT /api/settings, `settings set`, MCP, import): every
value is judged before anything is written, and the first bad value is `DarkroomError("invalid", <sentence>)` with
the sentences in `domain/messages.py` (SET_*). `null` (or an empty string) resets a key to its default.

Contract codes used here: E19 (CONTRACT-s2-export-detect) = relative folders in the file are relative to the file's
own folder; PL1 / PLP18 (CONTRACT-photo-library) = the default data folder per platform; PL9 = the data folder may
not exist yet but its parent must; SI8 = the default spending cap (5 USD) of one semantic build; WG15
(CONTRACT-write-guard) = an API key reference has the 1Password shape op://vault/item/field and is never a secret.
"""
import math
import os
import re
from urllib.parse import urlsplit

from . import messages as M
from .errors import DarkroomError

FORMAT = "darkroom-settings/1"                      # the export document's format tag (plan-v2 §3)
LANGUAGES = ("zh-TW", "en-US")
KEYS = ("language", "preset_dir", "preset_library_dir", "data_dir", "localllms_root", "comfyui_url", "comfyui_root",
        "agent.api_key_ref", "agent.model", "agent.budget_usd", "calibration_sources_dir")
PATH_KEYS = ("preset_dir", "preset_library_dir", "data_dir", "localllms_root", "comfyui_root",
             "calibration_sources_dir")
# keys the composition is built from: changing one rebuilds the preset library view and the photo library
LIBRARY_KEYS = ("preset_dir", "preset_library_dir", "localllms_root")
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_BUDGET_USD = 5.0                            # = the old semantic_index_budget_usd default (SI8)
STATIC_DEFAULTS = {"language": "zh-TW", "comfyui_url": DEFAULT_COMFYUI_URL, "agent.model": DEFAULT_MODEL,
                   "agent.budget_usd": DEFAULT_BUDGET_USD}
LEGACY = {"anthropic_api_key_ref": "agent.api_key_ref", "semantic_index_budget_usd": "agent.budget_usd"}
ENV_ROOT = "LOCALLLMS_ROOT"
PRESET_REL = ("artifact", "11_preset", "xmp")
SOURCES_REL = ("scratch", "lr-calibration", "sources")
RELATIVE_KEYS = ("data_dir", "preset_dir", "preset_library_dir")      # S2 E19: relative to the config file's folder
MODEL_MAX = 100
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
OP_REF = re.compile(r'^op://[^\s/"&|<>^%!]+(/[^\s/"&|<>^%!]+){2,3}$')   # the WG15 shape of a 1Password reference
_SECRET_SHAPE = re.compile(r"sk-ant-", re.IGNORECASE)


# ---------------------------------------------------------------------- the file <-> flat values
def _nested(key):
    """"agent.model" -> ("agent", "model"); "language" -> (None, "language")."""
    head, sep, tail = key.partition(".")
    return (head, tail) if sep else (None, key)


def raw_value(obj, key):
    """The value written in a parsed file for one flat key (the new key first, then its old name), or None."""
    group, name = _nested(key)
    if group is not None:
        sub = obj.get(group)
        if isinstance(sub, dict) and name in sub:
            return sub[name]
    else:
        if key in obj:
            return obj[key]
    for old, new in LEGACY.items():
        if new == key and old in obj:
            return obj[old]
    return None


def flatten(obj, base_dir=None):
    """{flat key: value} of the keys written in a parsed settings file (no defaults); empty strings count as unset.

    Paths of the S2 E19 keys given relative are made absolute against `base_dir` (the file's folder)."""
    out = {}
    for key in KEYS:
        v = raw_value(obj, key)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if key in RELATIVE_KEYS and isinstance(v, str) and base_dir and not os.path.isabs(v):
            v = os.path.normpath(os.path.join(base_dir, v))
        out[key] = v
    return out


def file_with(obj, changes):
    """A new file object: `obj` with `changes` applied ({flat key: value or None = remove}). Keys written in the new
    shape (agent.* nested), the old names of a changed key dropped; keys this module does not know are kept as they
    are, so a hand-edited file loses nothing."""
    out = dict(obj)
    for key, value in changes.items():
        for old, new in LEGACY.items():
            if new == key:
                out.pop(old, None)
        group, name = _nested(key)
        if group is None:
            if value is None:
                out.pop(key, None)
            else:
                out[key] = value
            continue
        sub = dict(out.get(group)) if isinstance(out.get(group), dict) else {}
        if value is None:
            sub.pop(name, None)
        else:
            sub[name] = value
        if sub:
            out[group] = sub
        else:
            out.pop(group, None)
    return out


# ---------------------------------------------------------------------- defaults and effective values
def home_folder(home=None):
    """An absolute home folder, or None (never "~" itself)."""
    if home is None:
        try:
            home = os.path.expanduser("~")
        except Exception:
            return None
    return home if isinstance(home, str) and home and home != "~" and os.path.isabs(home) else None


def default_data_dir(env, platform, home=None):
    """The platform's data folder (CONTRACT-photo-library PL1 / PLP18): win32 %LOCALAPPDATA%/darkroom, darwin
    ~/Library/Application Support/darkroom, others $XDG_DATA_HOME/darkroom (absolute only) or
    ~/.local/share/darkroom; None when none is known (the caller words the error)."""
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        return os.path.join(local, "darkroom") if local else None
    h = home_folder(home)
    if platform == "darwin":
        return os.path.join(h, "Library", "Application Support", "darkroom") if h else None
    xdg = env.get("XDG_DATA_HOME")
    if isinstance(xdg, str) and xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "darkroom")
    return os.path.join(h, ".local", "share", "darkroom") if h else None


def effective(written, env, platform, home=None):
    """(settings, defaults, sources) for the values written in the file.

    settings: {key: the value in use}; defaults: {key: what it would be with nothing written}; sources:
    {key: "file" | "env" | "default"}. LOCALLLMS_ROOT in the environment wins over the file (as config.load);
    preset_dir, preset_library_dir and calibration_sources_dir default from localllms_root / preset_dir."""
    env_root = env.get(ENV_ROOT) or None
    settings, sources = {}, {}
    for key in KEYS:
        if key == "localllms_root" and env_root:
            settings[key], sources[key] = env_root, "env"
        elif key in written and usable(key, written[key]) is not None:
            settings[key], sources[key] = usable(key, written[key]), "file"
        else:
            sources[key] = "default"
    root = settings.get("localllms_root")
    defaults = dict.fromkeys(KEYS)
    defaults.update(STATIC_DEFAULTS)
    defaults["data_dir"] = default_data_dir(env, platform, home)
    defaults["preset_dir"] = os.path.join(root, *PRESET_REL) if root else None
    defaults["calibration_sources_dir"] = os.path.join(root, *SOURCES_REL) if root else None
    for key in KEYS:
        if key == "preset_library_dir":
            continue
        if sources[key] == "default":
            settings[key] = defaults[key]
    preset_dir = settings.get("preset_dir")
    defaults["preset_library_dir"] = os.path.dirname(os.path.abspath(preset_dir)) if preset_dir else None
    if sources["preset_library_dir"] == "default":
        settings["preset_library_dir"] = defaults["preset_library_dir"]
    return {k: settings[k] for k in KEYS}, defaults, sources


# ---------------------------------------------------------------------- checks
def _invalid(text):
    """The error every refused setting raises (kind invalid, sentence unchanged)."""
    return DarkroomError("invalid", text)


def _under(path, folder):
    """Is `path` the folder itself or inside it? Compared after resolving links and case (so a junction or a
    different spelling cannot sneak a write target into the preset folder); False across drives."""
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def _check_url(value):
    """ComfyUI's URL: http(s) to a loopback host with an explicit port, no credentials / path / query; returned
    without a trailing slash. Loopback only because darkroom never talks to another machine."""
    if not isinstance(value, str):
        raise _invalid(M.SET_URL.format(value=value))
    try:
        u = urlsplit(value.strip())
        port = u.port
    except ValueError:
        raise _invalid(M.SET_URL.format(value=value)) from None
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in LOOPBACK_HOSTS or port is None \
            or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise _invalid(M.SET_URL.format(value=value))
    return value.strip().rstrip("/")


def looks_secret(value):
    """Does this value carry something shaped like an Anthropic API key (sk-ant-...)?

    Checked on every key (nested lists / objects included) before any per-key rule: a key pasted into the wrong
    field (agent.model, comfyui_url, a path...) is refused with M.SET_SECRET - a sentence that never contains the
    value - so it is neither written to the file nor echoed back in an error sentence (HTTP body, CLI stdout)."""
    if isinstance(value, str):
        return bool(_SECRET_SHAPE.search(value))
    if isinstance(value, dict):
        return any(looks_secret(k) or looks_secret(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(looks_secret(v) for v in value)
    return False


def _check_one(key, value, is_dir):
    """The normalised value of one key, or invalid with its sentence. None means "reset to the default"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if looks_secret(value):
        raise _invalid(M.SET_SECRET)                    # never the key itself, and never echoed back (any key)
    if key == "language":
        if value not in LANGUAGES:
            raise _invalid(M.SET_LANGUAGE.format(value=value))
        return value
    if key in PATH_KEYS:
        if not isinstance(value, str) or not os.path.isabs(value.strip()):
            raise _invalid(M.SET_PATH_TYPE.format(key=key, value=value))
        p = os.path.normpath(value.strip())
        if key == "data_dir":                       # created by the first write; its parent must exist (PL9)
            if not is_dir(p) and not is_dir(os.path.dirname(p)):
                raise _invalid(M.SET_DATA_DIR_PARENT.format(value=value))
        elif not is_dir(p):
            raise _invalid(M.SET_PATH_MISSING.format(key=key, value=value))
        return p
    if key == "comfyui_url":
        return _check_url(value)
    if key == "agent.api_key_ref":
        if not isinstance(value, str) or not OP_REF.match(value.strip()):
            raise _invalid(M.SET_KEY_REF.format(value=value))
        return value.strip()
    if key == "agent.model":
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= MODEL_MAX or any(c.isspace()
                                                                                          for c in value.strip()):
            raise _invalid(M.SET_MODEL.format(value=value))
        return value.strip()
    if key == "agent.budget_usd":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise _invalid(M.SET_BUDGET.format(value=value))
        return value
    raise _invalid(M.SET_UNKNOWN_KEY.format(key=key, keys="、".join(KEYS)))


def validate_changes(values, current, is_dir, written=None):
    """{flat key: normalised value or None} of a partial update, or invalid on the first bad value.

    values: the request's object; current: the settings in use (effective) and written: the values written in the
    file, for the cross check; is_dir: the folder check (the service passes os.path.isdir). Unknown keys are refused
    before any value is judged, so a typo never half-applies. preset_library_dir and data_dir may not lie inside the
    preset folder (they are written into; the preset folder never is) - judged for the values in this update and,
    when preset_dir itself changes, for the ones already written."""
    if looks_secret(values):                        # before any sentence could echo a key or a value back
        raise _invalid(M.SET_SECRET)
    if not isinstance(values, dict):
        raise _invalid(M.SET_NOT_OBJECT.format(value=values))
    for key in values:
        if key not in KEYS:
            raise _invalid(M.SET_UNKNOWN_KEY.format(key=key, keys="、".join(KEYS)))
    if not values:
        raise _invalid(M.SET_NOTHING)
    out = {key: _check_one(key, values[key], is_dir) for key in values}       # in the request's order
    written = written or {}
    preset_dir = out.get("preset_dir") or (None if "preset_dir" in out else current.get("preset_dir"))
    if preset_dir:
        for key in ("preset_library_dir", "data_dir"):
            p = out.get(key) if key in out else (written.get(key) if "preset_dir" in out else None)
            if p and _under(p, preset_dir):
                raise _invalid(M.SET_INSIDE_PRESET_DIR.format(key=key, value=p))
    return out


SCALAR_KEYS = ("language", "comfyui_url", "agent.model", "agent.budget_usd")   # judged again when read from the file


def usable(key, value):
    """A value written in the settings file, judged by the same rule a `set` uses; None when it does not pass.

    Only for the scalar keys (SCALAR_KEYS): a hand-edited file with comfyui_url=http://example.com:1 or
    agent.budget_usd=-3 then shows - and uses - the default, never a non-loopback URL nor a value no `set` would
    accept. `effective` (what get_settings shows) and the config.py readers (what the app uses) both call this, so
    the shown value and the used value come from one rule. Folders are not judged here (their existence is checked
    where they are used)."""
    if key not in SCALAR_KEYS:
        return value
    try:
        return _check_one(key, value, lambda _p: True)
    except DarkroomError:
        return None


# ---------------------------------------------------------------------- the export document
def export_document(written, version):
    """{format, version, settings}: the values written in the settings file (not defaults, not the environment),
    flat, ready to be imported on another machine or after a reinstall."""
    return {"format": FORMAT, "version": version, "settings": {k: written[k] for k in KEYS if k in written}}


def document_values(doc):
    """The settings object of an export document, or invalid (wrong format, extra keys, not an object)."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("settings"), dict) \
            or set(doc) - {"format", "version", "settings"}:
        raise _invalid(M.SET_DOC_FORMAT.format(format=FORMAT))
    return doc["settings"]
