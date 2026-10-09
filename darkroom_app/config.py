"""Where the user's LocalLLMs checkout and preset folder are (never hard-coded).

Order: environment variable LOCALLLMS_ROOT, then config.local.json at the repo root (keys: localllms_root,
preset_dir, preset_library_dir, data_dir; the file is not in git). preset_dir defaults to
<localllms_root>/artifact/11_preset/xmp. preset_library_dir (the preset library root: library.json, import/, user/)
has no default here: callers fall back to dirname(preset_dir) (CONTRACT-preset-library K1, KP2). data_dir (the photo
library: edits/, thumbs/, index/) defaults to %LOCALAPPDATA%/darkroom (CONTRACT-photo-library PL1).
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO, "config.local.json")
ENV_ROOT = "LOCALLLMS_ROOT"
ENV_API_KEY = "DARKROOM_ANTHROPIC_API_KEY"          # verbatim (CONTRACT-semantic-index SI2)
PYTHON_REL = ("runtimes", "darkroom-python", "py3.13.14-torch2.14.0-cu130", "python.exe")
DATA_DIR_ERROR = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在"   # verbatim (PL1)
SEMANTIC_BUDGET_DEFAULT_USD = 5.0                    # verbatim (SI8): key semantic_index_budget_usd
SOURCES_REL = ("scratch", "lr-calibration", "sources")   # default calibration_sources_dir under localllms_root
DATA_DIR_ERROR_POSIX = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 HOME 存在"   # verbatim (S2 E18)
BAD_CONFIG = "{file_name} 不是正確的 JSON（第 {line} 行第 {col} 欄）：{msg}"       # verbatim (S2 E19)
RELATIVE_KEYS = ("data_dir", "preset_dir", "preset_library_dir")              # S2 E19: relative to the config file


class ConfigError(RuntimeError):
    pass


def _read(config_file=None):
    """The configuration object; ConfigError (one line: file, line, column) when the file is not valid JSON (E19).

    data_dir / preset_dir / preset_library_dir given as relative paths are made absolute against the folder of the
    configuration file (CONTRACT-s2-export-detect E19), before anything uses them."""
    path = CONFIG_FILE if config_file is None else config_file
    cfg = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
        name = os.path.basename(path)
        try:
            cfg = json.loads(raw.decode("utf-8-sig"))
        except UnicodeDecodeError as e:
            line = raw[:e.start].count(b"\n") + 1
            col = e.start - (raw.rfind(b"\n", 0, e.start) + 1) + 1
            raise ConfigError(BAD_CONFIG.format(file_name=name, line=line, col=col, msg=e.reason)) from None
        except ValueError as e:
            raise ConfigError(BAD_CONFIG.format(file_name=name, line=getattr(e, "lineno", 1),
                                                col=getattr(e, "colno", 1), msg=getattr(e, "msg", str(e)))) from None
        if not isinstance(cfg, dict):
            raise ConfigError(f"{name} must hold a JSON object")
        base = os.path.dirname(os.path.abspath(path))
        for key in RELATIVE_KEYS:
            v = cfg.get(key)
            if isinstance(v, str) and v.strip() and not os.path.isabs(v):
                cfg[key] = os.path.normpath(os.path.join(base, v))
    return cfg


def load(config_file=None, env=None):
    """{"localllms_root": str|None, "preset_dir": str|None}."""
    env = os.environ if env is None else env
    cfg = _read(config_file)
    root = env.get(ENV_ROOT) or cfg.get("localllms_root") or None
    preset_dir = cfg.get("preset_dir") or (os.path.join(root, "artifact", "11_preset", "xmp") if root else None)
    return {"localllms_root": root, "preset_dir": preset_dir}


def preset_dir(config_file=None, env=None):
    d = load(config_file, env)["preset_dir"]
    if not d:
        raise ConfigError(f"set {ENV_ROOT} or write config.local.json (keys: localllms_root, preset_dir)")
    return d


def preset_library_dir(config_file=None):
    """The configured preset library root (key preset_library_dir), or None (then dirname(preset_dir), KP2)."""
    return _read(config_file).get("preset_library_dir") or None


def anthropic_api_key_ref(config_file=None):
    """The 1Password reference (key anthropic_api_key_ref, e.g. op://vault/item/credential) or None. Never a key:
    the secret itself is only ever read into memory by services/semantic_index.py (CONTRACT-semantic-index SI3)."""
    ref = _read(config_file).get("anthropic_api_key_ref")
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def semantic_index_budget_usd(config_file=None):
    """Spending cap for one `presets semantic build` (key semantic_index_budget_usd; SI8). Not a positive
    number -> the default."""
    v = _read(config_file).get("semantic_index_budget_usd")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
        return SEMANTIC_BUDGET_DEFAULT_USD
    return float(v)


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


def _home(home):
    if home is None:
        try:
            home = os.path.expanduser("~")
        except Exception:
            return None
    return home if isinstance(home, str) and home and home != "~" and os.path.isabs(home) else None


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
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, "darkroom")
        raise ConfigError(DATA_DIR_ERROR)
    h = _home(home)
    if platform == "darwin":
        if h:
            return os.path.join(h, "Library", "Application Support", "darkroom")
        raise ConfigError(DATA_DIR_ERROR_POSIX)
    xdg = env.get("XDG_DATA_HOME")
    if isinstance(xdg, str) and xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "darkroom")
    if h:
        return os.path.join(h, ".local", "share", "darkroom")
    raise ConfigError(DATA_DIR_ERROR_POSIX)
