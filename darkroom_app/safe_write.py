"""The one place in darkroom_app that writes files (CONTRACT-write-guard G8).

Five functions, nothing else: `create_new` (new files only, never overwrites), `make_dirs`, `replace_into` (moves a
file this process created with `create_new` over `dest`), `remove` and `open_lock`. Every call first checks:

* `root` is an existing absolute folder;
* the parent of `realpath(path)` is inside `realpath(root)` (normcase + commonpath, junctions and symlinks resolved);
* the target is not inside `config.preset_dir()`;
* for `replace_into` (dest) and `remove`, the extension is neither a photo extension (`engine.PHOTO_EXT`) nor `.xmp`.

A failed check raises `SafeWriteRefused` (an Exception, not an OSError: services must not catch it). Data is bytes
only; this module never takes a function that opens a file by itself. Which services may import this module is a
constant whitelist in tests/test_layering.py (`test_only_safe_write_writes`).
"""
import os

from . import config

REFUSED_OUTSIDE = "refused: {path} is outside {root}"                   # verbatim (G8)
REFUSED_PRESET = "refused: {path} is inside the preset folder"            # verbatim (G8)
REFUSED_PROTECTED = "refused: {path} is a photo or preset file"           # verbatim (G8)
REFUSED_NOT_OURS = "refused: {tmp} was not created by safe_write"         # verbatim (G8)
REFUSED_ROOT = "refused: root {root} is not an existing absolute folder"  # verbatim (G8)
REFUSED_LOCK = "refused: {path} is not a .lock file"                      # verbatim (patch WG6)

_CREATE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_BINARY
_LOCK_FLAGS = os.O_RDWR | os.O_CREAT | os.O_BINARY
_created = set()          # normcase(realpath) of the files create_new made in this process


class SafeWriteRefused(Exception):
    """A write safe_write will not do (not an OSError on purpose)."""


def _real(p):
    return os.path.normcase(os.path.realpath(os.fspath(p)))


def _under(p, folder):
    try:
        return os.path.commonpath([p, folder]) == folder
    except ValueError:            # different drives
        return False


def _check(path, root, protected_ext=False):
    """normcase(realpath(path)) after every G8 check."""
    if not isinstance(root, (str, os.PathLike)) or not os.path.isabs(root) or not os.path.isdir(root):
        raise SafeWriteRefused(REFUSED_ROOT.format(root=root))
    real, real_root = _real(path), _real(root)
    if not _under(os.path.dirname(real), real_root):
        raise SafeWriteRefused(REFUSED_OUTSIDE.format(path=path, root=root))
    if _under(real, _real(config.preset_dir())):
        raise SafeWriteRefused(REFUSED_PRESET.format(path=path))
    if protected_ext:
        from .engine import PHOTO_EXT     # the one extension table (CONTRACT-heic H7)
        if os.path.splitext(real)[1] in PHOTO_EXT + (".xmp",):
            raise SafeWriteRefused(REFUSED_PROTECTED.format(path=path))
    return real


def create_new(path, root, data):
    """Write `data` (bytes) to a file that must not exist yet; FileExistsError as is. A failed write leaves no file."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("safe_write.create_new takes bytes")
    real = _check(path, root)
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


def make_dirs(path, root):
    """Create the folder (and missing parents) inside root."""
    _check(path, root)
    os.makedirs(path, exist_ok=True)
    return path


def replace_into(tmp, dest, root):
    """Move `tmp` (made by create_new in this process) over `dest`."""
    real_tmp = _check(tmp, root)
    if real_tmp not in _created:
        raise SafeWriteRefused(REFUSED_NOT_OURS.format(tmp=tmp))
    _check(dest, root, protected_ext=True)
    os.replace(tmp, dest)
    _created.discard(real_tmp)
    return dest


def remove(path, root):
    """Delete one file inside root (never a photo or a preset)."""
    _check(path, root, protected_ext=True)
    os.remove(path)
    _created.discard(_real(path))


def open_lock(path, root):
    """fd of a `.lock` file inside root, opened read-write, created when missing, never truncated."""
    if not os.path.basename(os.fspath(path)).endswith(".lock"):
        raise SafeWriteRefused(REFUSED_LOCK.format(path=path))
    _check(path, root)
    return os.open(path, _LOCK_FLAGS, 0o666)
