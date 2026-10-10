"""The one place in darkroom_app that writes files (CONTRACT-write-guard G8).

Five functions, nothing else: `create_new` (new files only, never overwrites), `make_dirs`, `replace_into` (moves a
file this process created with `create_new` over `dest`), `remove` and `open_lock`. Every call first checks:

* `root` is an existing absolute folder;
* the parent of `realpath(path)` is inside `realpath(root)` (normcase + commonpath, junctions and symlinks resolved);
* the target is not inside the preset folder in use (keyword `preset_dir=`, passed in by the composition:
  CONTRACT-export XP12) nor inside the configured preset folder when one is known; with neither known it is refused;
* for `replace_into` (dest) and `remove`, the extension is neither a photo extension (`formats.PHOTO_EXT`, re-exported as `engine.PHOTO_EXT`) nor `.xmp`.

A failed check raises `SafeWriteRefused` (an Exception, not an OSError: services must not catch it). Data is bytes
only; this module never takes a function that opens a file by itself. Which services may import this module is a
constant whitelist in tests/test_layering.py (`test_only_safe_write_writes`).

Layer: utils (plan-v2 §1). The one exception to "utils imports nothing of darkroom_app": the photo extension table
`domain.formats.PHOTO_EXT` (a constant tuple with no imports; L3 forbids a second copy of it). The configured preset
folder is not read from the configuration here any more (v2): the composition sets `configured_preset_dir`, a
zero-argument function returning that folder or None, when it builds the app. Until it is set only the folder
passed as `preset_dir=` is known.

Why one module: "darkroom never writes a photo or a purchased preset" is the product's main promise. Funnelling every
write through five checked functions makes that promise auditable in one file, and the test suite's write guard
(tests/_writeguard.py) proves at run time that nothing else writes. Callers pass bytes they built in memory; the
module decides nothing about content.

Contract codes: G8 = the five functions and their checks / sentences; G10 = only whitelisted modules may import this
one; XP12 = the in-use and the configured preset folders are both protected, and with neither known every write is
refused; WG6 = a lock file must end in .lock; H7 = the photo extension table includes HEIC / HEIF; L3 = one
extension table, no copies.
"""
import os

from ..domain.formats import PHOTO_EXT     # the one extension table (CONTRACT-heic H7; engine re-exports it)

REFUSED_OUTSIDE = "refused: {path} is outside {root}"                   # verbatim (G8)
REFUSED_PRESET = "refused: {path} is inside the preset folder"            # verbatim (G8)
REFUSED_PROTECTED = "refused: {path} is a photo or preset file"           # verbatim (G8)
REFUSED_NOT_OURS = "refused: {tmp} was not created by safe_write"         # verbatim (G8)
REFUSED_ROOT = "refused: root {root} is not an existing absolute folder"  # verbatim (G8)
REFUSED_LOCK = "refused: {path} is not a .lock file"                      # verbatim (patch WG6)
REFUSED_NO_PRESET = "refused: no preset folder is known, cannot protect it"   # verbatim (CONTRACT-export XP12)

_CREATE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_BINARY
_LOCK_FLAGS = os.O_RDWR | os.O_CREAT | os.O_BINARY
_created = set()          # normcase(realpath) of the files create_new made in this process


class SafeWriteRefused(Exception):
    """A write safe_write will not do (not an OSError on purpose)."""


def _real(p):
    """The canonical spelling of a path: links / junctions resolved, case folded on Windows."""
    return os.path.normcase(os.path.realpath(os.fspath(p)))


def _under(p, folder):
    """Is the canonical path `p` the canonical `folder` or inside it? (both already passed through _real)."""
    try:
        return os.path.commonpath([p, folder]) == folder
    except ValueError:            # different drives
        return False


configured_preset_dir = None   # () -> the configured preset folder or None; set by darkroom_app.composition


def _configured():
    """The configured preset folder, or None when it is unknown (no hook set, or the hook knows none)."""
    hook = configured_preset_dir
    if hook is None:
        return None
    try:
        return hook()
    except Exception:             # a configuration that cannot be read protects nothing extra; never a crash here
        return None


def _preset_folders(preset_dir):
    """The preset folders to keep out of: the one in use (when given) and the configured one (when it resolves)."""
    out = [] if preset_dir is None else [_real(preset_dir)]
    configured = _configured()
    if configured:
        out.append(_real(configured))
    elif preset_dir is None:
        raise SafeWriteRefused(REFUSED_NO_PRESET) from None
    return out


def _check(path, root, protected_ext=False, preset_dir=None):
    """normcase(realpath(path)) after every G8 check.

    Checks, in order: root is an existing absolute folder; the target's parent lies inside root (so `..` or a
    symlink cannot escape); the target is not inside a preset folder; with protected_ext, the target is not a photo
    or .xmp file. Raises SafeWriteRefused with the first failing check's sentence."""
    if not isinstance(root, (str, os.PathLike)) or not os.path.isabs(root) or not os.path.isdir(root):
        raise SafeWriteRefused(REFUSED_ROOT.format(root=root))
    real, real_root = _real(path), _real(root)
    if not _under(os.path.dirname(real), real_root):
        raise SafeWriteRefused(REFUSED_OUTSIDE.format(path=path, root=root))
    if any(_under(real, folder) for folder in _preset_folders(preset_dir)):
        raise SafeWriteRefused(REFUSED_PRESET.format(path=path))
    if protected_ext:
        if os.path.splitext(real)[1] in PHOTO_EXT + (".xmp",):
            raise SafeWriteRefused(REFUSED_PROTECTED.format(path=path))
    return real


def create_new(path, root, data, *, preset_dir=None):
    """Write `data` (bytes) to a file that must not exist yet; FileExistsError as is. A failed write leaves no file.

    O_EXCL makes "must not exist" atomic (no check-then-write race with another process). The created file is
    remembered so replace_into can later accept it as a temporary file of ours. Returns `path`. Raises TypeError for
    non-bytes data, SafeWriteRefused for a refused target, OSError for disk errors."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("safe_write.create_new takes bytes")
    real = _check(path, root, preset_dir=preset_dir)
    fd = os.open(path, _CREATE_FLAGS, 0o666)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
    except BaseException:
        os.close(fd)
        os.remove(path)
        raise
    os.close(fd)
    _created.add(real)
    return path


def make_dirs(path, root, *, preset_dir=None):
    """Create the folder (and missing parents) inside root. Returns `path`; an existing folder is fine."""
    _check(path, root, preset_dir=preset_dir)
    os.makedirs(path, exist_ok=True)
    return path


def replace_into(tmp, dest, root, *, preset_dir=None):
    """Move `tmp` (made by create_new in this process) over `dest`.

    This is the atomic-update pattern: write the full new content to a temporary file, then rename it over the old
    one, so a reader never sees a half-written file and a crash leaves either the old or the new version. Only files
    this process created may be moved (an arbitrary existing file can never be renamed over something), and dest
    may not be a photo or preset. Returns `dest`."""
    real_tmp = _check(tmp, root, preset_dir=preset_dir)
    if real_tmp not in _created:
        raise SafeWriteRefused(REFUSED_NOT_OURS.format(tmp=tmp))
    _check(dest, root, protected_ext=True, preset_dir=preset_dir)
    os.replace(tmp, dest)
    _created.discard(real_tmp)
    return dest


def remove(path, root, *, preset_dir=None):
    """Delete one file inside root (never a photo or a preset)."""
    _check(path, root, protected_ext=True, preset_dir=preset_dir)
    os.remove(path)
    _created.discard(_real(path))


def open_lock(path, root, *, preset_dir=None):
    """fd of a `.lock` file inside root, opened read-write, created when missing, never truncated.

    The caller (adapters/persist/locks.py) takes an OS byte-range lock on this fd; the lock is released by the OS
    when the process dies, so a crashed writer never leaves the library locked forever."""
    if not os.path.basename(os.fspath(path)).endswith(".lock"):
        raise SafeWriteRefused(REFUSED_LOCK.format(path=path))
    _check(path, root, preset_dir=preset_dir)
    return os.open(path, _LOCK_FLAGS, 0o666)
