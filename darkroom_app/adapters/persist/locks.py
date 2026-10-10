"""Cross-process file locks, atomic JSON replacement, retried reads and bad-file copies (plan-v2 §1: persist/locks.py).

Layer: adapters/persist. Every store that keeps a JSON file next to other processes (the preset library index
`library.json`, the semantic index `semantic.json`, the export presets `export-presets.json`, the photo library's
edits and thumbnail index, the settings file) uses these helpers; before v2 each service carried its own copy.
Depends on utils (`safe_write`, the only module that writes; `text.one_line`) and domain (`DarkroomError`); never on
services, the facade, composition or config.

The rules, unchanged from the copies they replace:

* lock: `<file>.lock` opened through `safe_write.open_lock` (created when missing, never truncated), a one-byte
  lock taken with `msvcrt.locking(LK_NBLCK)` (POSIX: `fcntl.lockf(LOCK_EX | LOCK_NB)`), polled every LOCK_POLL_S;
  waiting longer than LOCK_WAIT_S raises conflict with the caller's sentence (K15, KP8). The OS releases the lock
  when the holder dies, so a crashed process never wedges the library.
* replace: `safe_write.create_new(tmp)` + `safe_write.replace_into(tmp, dest)`; a PermissionError from the rename
  (a reader holding dest open on Windows) is retried REPLACE_RETRIES x REPLACE_RETRY_S (KP21: about 2 s; collisions
  come in streaks, so many short tries, not a few long ones); the tmp file never outlives the call.
* read: the bytes of a file, None when it is missing; a PermissionError (a replace in progress) retried
  READ_RETRIES x READ_RETRY_S (KP12 / PLP3).
* bad copy: a byte copy `<file>.bad-{unix seconds}` (`-{n}` when that second is taken) made before an unreadable
  file is replaced (K5, SIP7, E12): nothing the user owns is overwritten silently. safe_write has no rename, so it
  is a copy, never a move.

Error sentences are never built here: the caller passes the conflict sentence (`busy`) and the unavailable template
(`unavailable`, formatted with `reason=` plus the caller's `fields`), so each store keeps its verbatim wording.
The timing constants are read when a function runs (not bound as defaults), so tests may patch them on this module.

Contract codes: K15 / KP8 = the cross-process lock and its 5 s wait; KP12 = a reader may hit PermissionError while
a writer replaces the file on Windows, so reads retry; KP21 / PLP3 = the writer's retry budget (200 x 10 ms); K5 /
SIP7 / E12 = keep a byte copy of an unreadable file before replacing it; G8 = all writes through the guarded write
module, SafeWriteRefused never caught.
"""
import contextlib
import os
import secrets
import sys
import time

from ...domain.errors import DarkroomError
from ...utils import safe_write
from ...utils.text import one_line

LOCK_WAIT_S = 5.0                               # verbatim (K15, KP8): longer -> conflict
LOCK_POLL_S = 0.02
REPLACE_RETRIES, REPLACE_RETRY_S = 200, 0.01   # verbatim (K15 as revised by KP21; PLP3)
READ_RETRIES, READ_RETRY_S = 10, 0.1           # verbatim (KP12, PLP3)
BAD_N_MAX = 9999                               # .bad-{t}, .bad-{t}-2 ... .bad-{t}-9999


def _unavailable(template, reason, fields):
    """DarkroomError unavailable with the caller's template filled with `reason` and its extra fields."""
    return DarkroomError("unavailable", template.format(reason=reason, **(fields or {})))


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd):
        """Try once to lock byte 0 of the lock file; OSError when another process holds it."""
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:                                           # Linux / macOS (CI): the same one-byte advisory lock
    import fcntl

    def _try_lock(fd):
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)

    def _unlock(fd):
        fcntl.lockf(fd, fcntl.LOCK_UN, 1, 0)


@contextlib.contextmanager
def held(lock_path, root, *, preset_dir, busy, unavailable, fields=None):
    """Hold the cross-process lock `lock_path` (a `.lock` file inside `root`) for the `with` block.

    busy: the conflict sentence when the lock stays taken longer than LOCK_WAIT_S;
    unavailable: the template (with `{reason}`) when the lock file cannot be opened."""
    try:
        fd = safe_write.open_lock(lock_path, root, preset_dir=preset_dir)
    except OSError as e:
        raise _unavailable(unavailable, one_line(e), fields) from None
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            _try_lock(fd)
            break
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise DarkroomError("conflict", busy) from None
            time.sleep(LOCK_POLL_S)
    try:
        yield
    finally:
        try:
            _unlock(fd)
        finally:
            os.close(fd)


def read_retry(path):
    """The bytes of `path`, None when it does not exist; PermissionError retried (a replace in progress), then
    raised. The file is closed right after reading, so a reader never blocks a writer's rename for long."""
    for attempt in range(READ_RETRIES):
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except PermissionError:
            if attempt == READ_RETRIES - 1:
                raise
            time.sleep(READ_RETRY_S)


def replace_atomic(dest, root, data, *, tmp_name, preset_dir, unavailable, fields=None):
    """Write `data` over `dest` atomically: tmp `<folder of dest>/<tmp_name>` created, then renamed over dest.

    Every OSError becomes unavailable with the caller's template; SafeWriteRefused is never caught (G8)."""
    tmp = os.path.join(os.path.dirname(dest), tmp_name)
    try:
        safe_write.create_new(tmp, root, data, preset_dir=preset_dir)
    except OSError as e:
        raise _unavailable(unavailable, one_line(e), fields) from None
    try:
        for attempt in range(REPLACE_RETRIES):
            try:
                safe_write.replace_into(tmp, dest, root, preset_dir=preset_dir)
                return
            except PermissionError as e:          # a reader has dest open (P6 / KP21)
                if attempt == REPLACE_RETRIES - 1:
                    raise _unavailable(unavailable, one_line(e), fields) from None
                time.sleep(REPLACE_RETRY_S)
            except OSError as e:
                raise _unavailable(unavailable, one_line(e), fields) from None
    finally:
        if os.path.exists(tmp):
            safe_write.remove(tmp, root, preset_dir=preset_dir)


def tmp_name(base):
    """`{base}.tmp-{pid}-{12 hex}`: the temporary name used next to the file being replaced."""
    return f"{base}.tmp-{os.getpid()}-{secrets.token_hex(6)}"


def keep_bad(root, file_name, raw, now, *, preset_dir, unavailable, fields=None):
    """A byte copy `<root>/<file_name>.bad-{int(now)}` (`-{n}` when taken) of an unreadable file; its path.

    `now` is the caller's clock (seconds), so a store with an injected clock names copies deterministically."""
    base = os.path.join(root, f"{file_name}.bad-{int(now)}")
    for n in range(1, BAD_N_MAX + 1):
        path = base if n == 1 else f"{base}-{n}"
        try:
            safe_write.create_new(path, root, raw, preset_dir=preset_dir)
            return path
        except FileExistsError:
            continue
        except OSError as e:
            raise _unavailable(unavailable, one_line(e), fields) from None
    raise _unavailable(unavailable, "no free .bad name", fields)
