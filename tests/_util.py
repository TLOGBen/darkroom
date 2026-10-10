"""Shared test helpers (tests only)."""
import glob
import hashlib
import os
import re
import subprocess
import sys
import tempfile

import _writeguard  # noqa: F401  arms the runtime write guard for every test module (CONTRACT-write-guard G1)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The darkroom runtime is an embedded CPython whose python313._pth ignores the working directory and
# PYTHONPATH, so the repo root has to be put on sys.path explicitly (tests import _util first).
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PHOTOS = os.path.join(REPO, ".claude", "wayfinder", "darkroom", "prototypes", "llm-pick-experiment", "photos")
HTTP_HEADERS = {"X-Darkroom": "1"}   # what the page's api() sends on every request (CONTRACT-photo-library PLP11)

# The page the server tests see (plan-v2 §2: the server serves only the React build). web/dist exists only after
# `npm run build` and changes with every build, so every test - and every child process a test starts, which copies
# os.environ - is pinned to a small fixed build checked in under tests/. A test that wants the "no build" 503 page
# points DARKROOM_WEB_DIST at an empty folder itself (mock.patch.dict).
WEB_DIST_FIXTURE = os.path.join(REPO, "tests", "web_dist_fixture")
os.environ["DARKROOM_WEB_DIST"] = WEB_DIST_FIXTURE


def preset_dir():
    """User's preset folder: DARKROOM_PRESET_DIR, else LOCALLLMS_ROOT / config.local.json (darkroom_app.config)."""
    d = os.environ.get("DARKROOM_PRESET_DIR")
    if d:
        return d
    from darkroom_app import config
    return config.preset_dir()


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


def run_cli(*args, cwd=None):
    """`python -m darkroom ...` run from a directory outside the repo with no PYTHONPATH (A21: the darkroom
    runtime's python313._pth lists D:/Code/darkroom)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([*guarded_python(), "-m", "darkroom", *args], cwd=cwd or tempfile.gettempdir(),
                       capture_output=True, env=env)
    return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")


def guarded_python():
    """argv prefix for a child python under the write guard (G6): `[*guarded_python(), "-m", mod, ...]`."""
    return _writeguard.python_cmd()


def tmpdir(testcase):
    """Fresh writable root for one test: registered first, then created; deleted, then unregistered (G4)."""
    d = _writeguard.new_root("darkroom-test-")
    testcase.addCleanup(_writeguard.release_root, d)
    return d


def class_tmpdir(cls, prefix="darkroom-test-"):
    """Class-level writable root (setUpClass); released by a class cleanup (G4)."""
    d = _writeguard.new_root(prefix)
    cls.addClassCleanup(_writeguard.release_root, d)
    return d
