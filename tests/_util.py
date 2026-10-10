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
# No preset library of the user's (a clean checkout / CI): the product and every child process find the synthetic
# library through a settings file, the same way they find the user's library through config.local.json.
if _writeguard.synthetic_config():
    os.environ["DARKROOM_CONFIG"] = _writeguard.synthetic_config()


def preset_dir():
    """The preset library the tests read: the user's (DARKROOM_PRESET_DIR, else LOCALLLMS_ROOT / config.local.json),
    or - when there is none, e.g. a clean checkout on CI - the synthetic one the guard made before arming."""
    d = os.environ.get("DARKROOM_PRESET_DIR")
    if d and os.path.isdir(d):
        return d
    if _writeguard.PRESET_DIR:
        return _writeguard.PRESET_DIR
    from darkroom_app import config
    return config.preset_dir()


# True when the tests run against the user's own library (1466 bought presets). Assertions about that library's exact
# contents (counts, hash, which presets have what) only hold there; with the synthetic library they are skipped or
# use LIBRARY_SIZE.
REAL_PRESETS = _writeguard.REAL_PRESETS
NO_REAL_PRESETS = "needs the user's own preset library (config.local.json / LOCALLLMS_ROOT); this run uses the synthetic one"


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


LIBRARY_SIZE = 1466 if REAL_PRESETS else len(preset_files())     # presets in the library the tests read
SYNTHETIC_HASH = None if REAL_PRESETS else presets_hash()        # the synthetic library as it was made


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


_HOLD_LOCK_CHILD = """import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | (os.O_CREAT if sys.argv[2] == "1" else 0))
fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
print("locked", flush=True)
sys.stdin.read()
"""


class held_lock:
    """`with held_lock(path):` - another program holds the one-byte lock on `path` (darkroom_app's persist locks)
    for the duration. Windows: msvcrt.locking from this process (it conflicts with any other descriptor). POSIX:
    fcntl locks belong to the process, so a guarded child takes the lock and keeps it until the block ends."""

    def __init__(self, path, create=False):
        self.path, self.create = path, create

    def __enter__(self):
        if sys.platform == "win32":
            import msvcrt
            self.fd = os.open(self.path, os.O_RDWR | os.O_BINARY | (os.O_CREAT if self.create else 0))
            try:
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            except BaseException:
                os.close(self.fd)
                raise
            return self
        self.proc = subprocess.Popen([*guarded_python(), "-c", _HOLD_LOCK_CHILD, self.path, "1" if self.create else "0"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        line = self.proc.stdout.readline()
        if line.strip() != b"locked":
            self.proc.kill()
            raise AssertionError(f"lock holder did not start: {line!r} {self.proc.stderr.read()!r}")
        return self

    def __exit__(self, *exc):
        if sys.platform == "win32":
            import msvcrt
            try:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(self.fd)
            return False
        self.proc.stdin.close()
        self.proc.wait(timeout=60)
        self.proc.stdout.close()
        self.proc.stderr.close()
        return False


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
