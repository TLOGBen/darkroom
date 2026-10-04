"""Shared test helpers (tests only)."""
import glob
import hashlib
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The darkroom runtime is an embedded CPython whose python313._pth ignores the working directory and
# PYTHONPATH, so the repo root has to be put on sys.path explicitly (tests import _util first).
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PHOTOS = os.path.join(REPO, ".claude", "wayfinder", "darkroom", "prototypes", "llm-pick-experiment", "photos")


def preset_dir():
    """User's preset folder: DARKROOM_PRESET_DIR, else <LOCALLLMS_ROOT>/artifact/11_preset/xmp."""
    d = os.environ.get("DARKROOM_PRESET_DIR")
    if d:
        return d
    root = os.environ.get("LOCALLLMS_ROOT", "C:/Users/powde/workspace/LocalLLMs")
    return os.path.join(root, "artifact", "11_preset", "xmp")


def preset_files():
    return sorted(glob.glob(os.path.join(preset_dir(), "*.xmp")))


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def find_preset(pattern, exclude=None):
    """First preset (sorted by name) whose text matches regex `pattern` (and not `exclude`)."""
    for p in preset_files():
        t = read_text(p)
        if re.search(pattern, t) and not (exclude and re.search(exclude, t)):
            return p
    raise LookupError(pattern)


def presets_hash(d=None):
    """Combined hash: SHA256 over the concatenated upper-case per-file SHA256 hex (files sorted by name), first 16 hex."""
    files = sorted(glob.glob(os.path.join(d or preset_dir(), "*.xmp")), key=os.path.basename)
    parts = []
    for f in files:
        with open(f, "rb") as fh:
            parts.append(hashlib.sha256(fh.read()).hexdigest().upper())
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest().upper()[:16]


# Equivalent of `python -m darkroom ...` that also works under the embedded runtime's ._pth (see above).
_BOOT = "import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('darkroom', run_name='__main__', alter_sys=True)"


def run_cli(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-s", "-c", _BOOT, REPO, *args], cwd=REPO, capture_output=True, env=env)
    return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")


def tmpdir(testcase):
    d = tempfile.mkdtemp(prefix="darkroom-test-")
    import shutil
    testcase.addCleanup(shutil.rmtree, d, True)
    return d
