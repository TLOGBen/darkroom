"""Where the user's LocalLLMs checkout and preset folder are (never hard-coded).

Order: environment variable LOCALLLMS_ROOT, then config.local.json at the repo root (keys: localllms_root,
preset_dir, preset_library_dir, data_dir; the file is not in git). preset_dir defaults to
<localllms_root>/artifact/11_preset/xmp. preset_library_dir (the preset library root: library.json, import/, user/)
has no default here: callers fall back to dirname(preset_dir) (CONTRACT-preset-library K1, KP2). data_dir (the photo
library: edits/, thumbs/, index/) defaults to %LOCALAPPDATA%/darkroom (CONTRACT-photo-library PL1).
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO, "config.local.json")
ENV_ROOT = "LOCALLLMS_ROOT"
ENV_API_KEY = "DARKROOM_ANTHROPIC_API_KEY"          # verbatim (CONTRACT-semantic-index SI2)
PYTHON_REL = ("runtimes", "darkroom-python", "py3.13.14-torch2.14.0-cu130", "python.exe")
DATA_DIR_ERROR = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在"   # verbatim (PL1)
SEMANTIC_BUDGET_DEFAULT_USD = 5.0                    # verbatim (SI8): key semantic_index_budget_usd
SOURCES_REL = ("scratch", "lr-calibration", "sources")   # default calibration_sources_dir under localllms_root


class ConfigError(RuntimeError):
    pass


def _read(config_file=None):
    path = CONFIG_FILE if config_file is None else config_file
    cfg = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            cfg = json.loads(f.read().decode("utf-8-sig"))
        if not isinstance(cfg, dict):
            raise ConfigError(f"{os.path.basename(path)} must hold a JSON object")
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


def data_dir(config_file=None, env=None):
    """The photo library's data folder (CONTRACT-photo-library PL1, PLP8): the config key data_dir, else
    %LOCALAPPDATA%/darkroom; ConfigError when neither is known."""
    env = os.environ if env is None else env
    d = _read(config_file).get("data_dir")
    if isinstance(d, str) and d.strip():
        return d
    local = env.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "darkroom")
    raise ConfigError(DATA_DIR_ERROR)
