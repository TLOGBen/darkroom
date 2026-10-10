"""Where the user's settings file, LocalLLMs checkout and preset folder are (never hard-coded).

Layer: entry / composition only (plan-v2 §1): the three entry points (`__main__`, the CLI, the MCP server) and
`darkroom_app.composition` may read the configuration; services, domain and the persist stores never do - they are
handed values or zero-argument functions by the composition.

The settings file (plan-v2 §3): `DARKROOM_CONFIG` -> config.local.json at the repo root -> the platform's settings
file (`adapters/persist/settings_store.locate`). Its keys are described in `domain/settings.py`; this module keeps
the readers the entry points have always used, now reading the new key names too (agent.api_key_ref,
agent.budget_usd) with the old names as a fallback:

Order for the LocalLLMs root: environment variable LOCALLLMS_ROOT, then the file's localllms_root. preset_dir
defaults to <localllms_root>/artifact/11_preset/xmp. preset_library_dir (the preset library root: library.json,
import/, user/) has no default here: callers fall back to dirname(preset_dir) (CONTRACT-preset-library K1, KP2).
data_dir (the photo library: edits/, thumbs/, index/) defaults to %LOCALAPPDATA%/darkroom (CONTRACT-photo-library PL1).

Dependencies: adapters/persist/settings_store (locating and parsing the file), domain.settings (key names,
defaults, flattening), domain.messages, domain.errors. Must not depend on services, the facade or entry adapters.
Every reader re-reads the file on each call (cheap, and it means a settings change is seen without a restart);
nothing in this module writes. Raises ConfigError (a one-line, user-facing reason) for a missing preset folder or
an unreadable settings file.

Contract codes used here:
    K1 / KP2   preset library root = preset_library_dir, else dirname(preset_dir); the file's key only counts when
               the preset folder also comes from the file.
    PL1 / PLP8 the photo library's data folder: key data_dir, else the platform default, resolved when first used.
    E18 / PLP18  the platform defaults for data_dir on Windows, macOS and Linux (XDG).
    E19        relative folders in the settings file are relative to that file; a broken file is one clear line.
    SI2 / SI3 / SI8  semantic index: where the API key reference and calibration photos come from, that the secret
               is only ever held in memory, and the spending cap per build.
"""
import os
import sys

from .adapters.persist import settings_store
from .domain import messages as M
from .domain import settings as S
from .domain.errors import DarkroomError

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO, "config.local.json")
ENV_ROOT = S.ENV_ROOT
ENV_CONFIG = settings_store.ENV_CONFIG
ENV_API_KEY = "DARKROOM_ANTHROPIC_API_KEY"          # verbatim (CONTRACT-semantic-index SI2)
PYTHON_REL = ("runtimes", "darkroom-python", "py3.13.14-torch2.14.0-cu130", "python.exe")
DATA_DIR_ERROR = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在"   # verbatim (PL1)
SEMANTIC_BUDGET_DEFAULT_USD = S.DEFAULT_BUDGET_USD   # verbatim (SI8): key semantic_index_budget_usd / agent.budget_usd
SOURCES_REL = S.SOURCES_REL                          # default calibration_sources_dir under localllms_root
DATA_DIR_ERROR_POSIX = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 HOME 存在"   # verbatim (S2 E18)
BAD_CONFIG = M.SET_FILE_BROKEN                       # verbatim (S2 E19)
RELATIVE_KEYS = S.RELATIVE_KEYS                      # S2 E19: relative to the config file


class ConfigError(RuntimeError):
    """The configuration cannot answer (no preset folder, no data folder, broken settings file); str(e) is the
    one-line reason shown to the user (CLI "darkroom：..." exit 2)."""


def config_path(env=None):
    """The settings file in use (it may not exist yet): DARKROOM_CONFIG -> CONFIG_FILE -> the platform file."""
    return settings_store.locate(CONFIG_FILE, env)


def _read(config_file=None):
    """The configuration object; ConfigError (one line: file, line, column) when the file is not valid JSON (E19).

    data_dir / preset_dir / preset_library_dir given as relative paths are made absolute against the folder of the
    configuration file (CONTRACT-s2-export-detect E19), before anything uses them."""
    path = config_path() if config_file is None else config_file
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        raw = f.read()
    try:
        cfg = settings_store.parse(raw, os.path.basename(path))
    except DarkroomError as e:
        raise ConfigError(e.message) from None
    base = os.path.dirname(os.path.abspath(path))
    for key in RELATIVE_KEYS:
        v = cfg.get(key)
        if isinstance(v, str) and v.strip() and not os.path.isabs(v):
            cfg[key] = os.path.normpath(os.path.join(base, v))
    return cfg


def written(config_file=None):
    """{flat key: value} written in the settings file (domain.settings.flatten; no defaults)."""
    path = config_path() if config_file is None else config_file
    return S.flatten(_read(path), os.path.dirname(os.path.abspath(path)))


def load(config_file=None, env=None):
    """{"localllms_root": str|None, "preset_dir": str|None}."""
    env = os.environ if env is None else env
    cfg = _read(config_file)
    root = env.get(ENV_ROOT) or cfg.get("localllms_root") or None
    preset_dir = cfg.get("preset_dir") or (os.path.join(root, *S.PRESET_REL) if root else None)
    return {"localllms_root": root, "preset_dir": preset_dir}


def preset_dir(config_file=None, env=None):
    """The preset folder (key preset_dir, else <localllms_root>/artifact/11_preset/xmp); ConfigError when unknown.

    The folder's existence is not checked here (the preset library reports a missing folder in its own words)."""
    d = load(config_file, env)["preset_dir"]
    if not d:
        # Says how to fix it for every kind of install: the desktop app's first-run page asks for the folder; the
        # CLI's `settings set` writes the same file (an installed copy has no config.local.json to hand-edit).
        raise ConfigError(M.NO_PRESET_DIR.format(env=ENV_ROOT, path=config_file or config_path(env)))
    return d


def preset_library_dir(config_file=None):
    """The configured preset library root (key preset_library_dir), or None (then dirname(preset_dir), KP2)."""
    return _read(config_file).get("preset_library_dir") or None


def anthropic_api_key_ref(config_file=None):
    """The 1Password reference (key agent.api_key_ref, old name anthropic_api_key_ref, e.g. op://vault/item/credential)
    or None. Never a key: the secret itself is only ever read into memory by services/semantic_index.py (SI3)."""
    ref = S.raw_value(_read(config_file), "agent.api_key_ref")
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def semantic_index_budget_usd(config_file=None):
    """Spending cap for one `presets semantic build` (key agent.budget_usd, old name semantic_index_budget_usd;
    SI8). A value `settings set` would refuse (not a positive finite number) -> the default; judged by
    domain.settings.usable, the same rule get_settings shows the value with."""
    v = S.usable("agent.budget_usd", S.raw_value(_read(config_file), "agent.budget_usd"))
    return SEMANTIC_BUDGET_DEFAULT_USD if v is None else float(v)


def calibration_sources_dir(config_file=None, env=None):
    """The folder of the four public calibration photos (key calibration_sources_dir; default
    <localllms_root>/scratch/lr-calibration/sources; SI2). None when neither is known."""
    env = os.environ if env is None else env
    cfg = _read(config_file)
    d = cfg.get("calibration_sources_dir")
    if isinstance(d, str) and d.strip():
        return d
    root = env.get(ENV_ROOT) or cfg.get("localllms_root") or None
    return os.path.join(root, *SOURCES_REL) if root else None


def comfyui_url(config_file=None):
    """ComfyUI's API address (key comfyui_url; default http://127.0.0.1:8188).

    A hand-edited value `settings set` would refuse (not loopback, a path, credentials...) is never used: it falls
    back to the default, exactly as get_settings shows it (domain.settings.usable), so darkroom never connects to
    another machine because of the file (plan-v2 §3: loopback only)."""
    v = S.usable("comfyui_url", _read(config_file).get("comfyui_url"))
    return v or S.DEFAULT_COMFYUI_URL


def _home(home):
    """The user's home folder (`home` overrides it in tests); see domain.settings.home_folder."""
    return S.home_folder(home)


def data_dir(config_file=None, env=None, platform=None, home=None):
    """The photo library's data folder (CONTRACT-photo-library PL1 / PLP8, revised by S2 E18 = PLP18): the config key
    data_dir, else the platform's convention - win32 %LOCALAPPDATA%/darkroom, darwin ~/Library/Application
    Support/darkroom, others $XDG_DATA_HOME/darkroom (an absolute XDG_DATA_HOME only) or ~/.local/share/darkroom;
    ConfigError when none is known (Windows: the PL1 sentence unchanged)."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    d = _read(config_file).get("data_dir")
    if isinstance(d, str) and d.strip():
        return d
    d = S.default_data_dir(env, platform, home)
    if d:
        return d
    raise ConfigError(DATA_DIR_ERROR if platform == "win32" else DATA_DIR_ERROR_POSIX)
