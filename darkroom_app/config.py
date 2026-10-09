"""Where the user's LocalLLMs checkout and preset folder are (never hard-coded).

Order: environment variable LOCALLLMS_ROOT, then config.local.json at the repo root (keys: localllms_root,
preset_dir, preset_library_dir; the file is not in git). preset_dir defaults to <localllms_root>/artifact/11_preset/xmp.
preset_library_dir (the preset library root: library.json, import/, user/) has no default here: callers fall back to
dirname(preset_dir) (CONTRACT-preset-library K1, KP2).
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO, "config.local.json")
ENV_ROOT = "LOCALLLMS_ROOT"
PYTHON_REL = ("runtimes", "darkroom-python", "py3.13.14-torch2.14.0-cu130", "python.exe")


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
