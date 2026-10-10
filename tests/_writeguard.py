"""Runtime write guard for the whole test suite (CONTRACT-write-guard G1-G7, G9).

Importing this module arms it: a `sys.addaudithook` hook that blocks every write-class event whose target is not
inside a writable root declared by a fixture (`new_root` / `release_root`, used by `_util.tmpdir`), plus process
launches and ctypes loads by the wrong initiator. A blocked event raises `WriteGuardViolation` (a BaseException, so
`except Exception` / `except OSError` in product code cannot swallow it) and is recorded in the violation table; the
test that was running is failed afterwards even when the exception was swallowed or raised on another thread.
There is no switch, environment variable or API that pauses or disarms the hook; audit hooks cannot be removed.

Under `tests/_guardrun.py` (child processes) the same hook runs with the roots handed down by the parent; each
violation is also appended to the parent's report folder so the parent test turns red, and the child exits 86.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import traceback

tempfile.gettempdir()           # W2: tempfile's writability probe happens before arming and is not a violation

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
GUARDRUN = os.path.join(TESTS, "_guardrun.py")

VIOLATION_LINE = "寫檔守門：{event} → {target}（測試 {test_id}）"         # verbatim (G5)
CHILD_EXIT = 86                                                           # verbatim (G6)
PYCACHE_NAME = re.compile(r"^[^\\/]+\.cpython-\d+(\.opt-\d)?\.pyc(\.\d+)?$")   # verbatim (G4)
WRITE_FLAGS = (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND   # verbatim (G2)
               | os.O_TEMPORARY | os.O_SHORT_LIVED)                                # patch WG13: delete on close
WRITE_MODE_CHARS = frozenset("wax+")                                       # verbatim (G2)
TEST_EXECUTABLES = ("python.exe", "node.exe", "pwsh.exe", "taskkill.exe")  # verbatim (G3); python only via _guardrun;
#   cmd.exe (WG3 constant row) is NOT in this tuple: only the exact mklink /J shape in _popen_allowed lets it run
PRODUCT_SUBPROCESSES = {"darkroom_app/utils/gpucheck.py": ("nvidia-smi.exe",),   # v2: utils/ (plan-v2 §1)
                        "darkroom_app/services/semantic_index.py": ("op.exe",)}   # verbatim (G3, patch WG15)
OP_REF = re.compile(r'^op://[^\s/"&|<>^%!]+(/[^\s/"&|<>^%!]+){2,3}$')     # verbatim (WG15): the 1Password reference
OP_MODULE = "darkroom_app/services/semantic_index.py"
ALWAYS_VIOLATION = ("os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile")   # G3
PHOTOS = os.path.join(REPO, ".claude", "wayfinder", "darkroom", "prototypes", "llm-pick-experiment", "photos")

PATH_EVENTS = {     # event -> indexes of the target arguments (G2; patch WG2 adds the _winapi events)
    "open": (0,), "os.rename": (0, 1), "os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.chmod": (0,),
    "os.utime": (0,), "os.truncate": (0,), "os.link": (0, 1), "os.symlink": (1,), "shutil.copyfile": (1,),
    "shutil.copytree": (1,), "shutil.move": (0, 1), "shutil.rmtree": (0,), "shutil.make_archive": (0,),
    "shutil.unpack_archive": (1,), "tempfile.mkstemp": (0,), "tempfile.mkdtemp": (0,), "sqlite3.connect": (0,),
    "dbm.open": (0,), "_winapi.CopyFile2": (1,), "_winapi.CreateJunction": (1,), "_winapi.CreateFile": (0,),
}
PROCESS_EVENTS = ("subprocess.Popen", "_winapi.CreateProcess")                   # patch WG9
CMD_SPECIAL = frozenset('&|<>^%!"' + chr(13) + chr(10))                                         # patch WG3
WATCHED = frozenset(PATH_EVENTS) | frozenset(ALWAYS_VIOLATION) | frozenset(PROCESS_EVENTS) | {"ctypes.dlopen",
                                                                                              "ctypes.dlsym"}
# _winapi.CreateFile (patch WG13): any write / delete access right, DELETE_ON_CLOSE, or a creating disposition
_WRITE_ACCESS = (0x40000000 | 0x10000000 | 0x02000000 | 0x2 | 0x4 | 0x10 | 0x100 | 0x10000 | 0x40000 | 0x80000)
_DELETE_ON_CLOSE, _CREATE_DISPOSITIONS = 0x04000000, (1, 2, 4, 5)

_BASE = os.path.normcase(os.path.realpath(sys.base_prefix))
_STDLIB = (os.path.join(_BASE, "python313.zip") + os.sep, os.path.join(_BASE, "lib") + os.sep)
_SITE = os.path.join(_BASE, "lib", "site-packages") + os.sep
_HERE = os.path.normcase(os.path.abspath(__file__))
_N_TESTS = os.path.normcase(TESTS) + os.sep
_N_PRODUCT = (os.path.normcase(os.path.join(REPO, "darkroom_app")) + os.sep,
              os.path.normcase(os.path.join(REPO, "darkroom")) + os.sep)
_N_GUARDRUN = os.path.normcase(GUARDRUN)
_DEVNULL = (os.path.normcase(os.path.realpath(os.devnull)), os.path.normcase(os.devnull))


class WriteGuardViolation(BaseException):
    """A write outside the declared roots (or a forbidden launch); BaseException on purpose (G5)."""


_lock = threading.RLock()
_tl = threading.local()
_roots = []                  # normcase(realpath) of the writable roots
_table = []                  # every violation: {"event", "target", "test_id", "stack"}
_claimed = 0                 # _table[:_claimed] has already failed a test
_current = [None]            # id of the running test (or class / module fixture)
_child = None                # {"report": path} under _guardrun.py
_report_dir = None           # parent: folder the children write their violations into
_report_seen = {}            # report file -> characters already read
_snapshot_at_arm = None


# ---------------------------------------------------------------- classification
def _norm(path):
    return os.path.normcase(os.path.realpath(os.fsdecode(os.fspath(path))))


def _inside(n, root):
    return n == root or n.startswith(root + os.sep)


def _category(filename):
    if filename.startswith("<frozen"):
        return "stdlib"
    n = os.path.normcase(os.path.abspath(filename)) if not filename.startswith("<") else filename
    if n.startswith(_SITE):
        return "third-party"
    if n.startswith(_STDLIB):
        return "stdlib"
    if n.startswith(_N_TESTS):
        return "test"
    if n.startswith(_N_PRODUCT):
        return "product"
    return "other"


def initiator():
    """(category, repo-relative file) of the frame nearest the event whose file is not stdlib (G3)."""
    f = sys._getframe(1)
    while f is not None:
        gf = f.f_globals.get("__file__")         # stdlib frames from python313.zip carry relative co_filenames
        fn = gf if isinstance(gf, str) and os.path.isabs(gf) else f.f_code.co_filename
        if os.path.normcase(fn) != _HERE:
            cat = _category(fn)
            if cat != "stdlib":
                rel = os.path.relpath(fn, REPO).replace("\\", "/") if cat in ("test", "product") else fn
                return cat, rel
        f = f.f_back
    return "stdlib", None


def split_cmdline(s):
    """Windows command line -> argv (CommandLineToArgvW rules for backslashes and quotes)."""
    out, cur, i, quoted, have = [], [], 0, False, False
    while i < len(s):
        c = s[i]
        if c == "\\":
            j = i
            while j < len(s) and s[j] == "\\":
                j += 1
            n = j - i
            if j < len(s) and s[j] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')
                    i = j + 1
                else:
                    i = j
                have = True
                continue
            cur.append("\\" * n)
            i = j
            have = True
            continue
        if c == '"':
            quoted = not quoted
            have = True
        elif c in " \t" and not quoted:
            if have:
                out.append("".join(cur))
                cur, have = [], False
        else:
            cur.append(c)
            have = True
        i += 1
    if have:
        out.append("".join(cur))
    return out


def _outside(target):
    """None when the target may be written, else its normalized spelling (G2, G4)."""
    if isinstance(target, int):
        return None
    try:
        raw = os.fsdecode(os.fspath(target))
    except TypeError:
        return repr(target)
    if os.path.normcase(raw) in _DEVNULL:
        return None
    n = _norm(raw)
    if n in _DEVNULL:
        return None
    parts = n.split(os.sep)
    if "__pycache__" in parts[:-1] and PYCACHE_NAME.match(parts[-1]):
        return None
    with _lock:
        if any(_inside(n, r) for r in _roots):
            return None
    return n


def _in_fixture_root(path):
    """Strictly inside a registered fixture root: no devnull / pycache allowance (patch WG3)."""
    n = _norm(path)
    with _lock:
        return any(_inside(n, r) for r in _roots)


def _frame_file(f):
    gf = f.f_globals.get("__file__")
    return gf if isinstance(gf, str) and os.path.isabs(gf) else f.f_code.co_filename


_HOOK_FUNCS = ("_hook", "judge", "_report_cleanup", "_from_cleanup", "_caller_frame")


def _caller_frame():
    """The Python frame right below the hook (the code whose call raised the audit event)."""
    f = sys._getframe(1)
    while f is not None and os.path.normcase(_frame_file(f)) == _HERE and f.f_code.co_name in _HOOK_FUNCS:
        f = f.f_back
    return f


def _from_cleanup():
    """WG4: the first non-stdlib frame is this module's own atexit cleanup."""
    f = _caller_frame()
    while f is not None and _category(_frame_file(f)) == "stdlib":
        f = f.f_back
    return f is not None and f.f_code is _cleanup_report_dir.__code__      # code object, not name / __file__


def _execute_child_code():
    import subprocess                   # already imported by whoever starts a process
    return subprocess.Popen._execute_child.__code__


def popen_permit():
    """WG9: True only while the approved Popen's _execute_child frame is still on this thread's stack."""
    permit = getattr(_tl, "permit_frame", None)
    f = sys._getframe(1)
    while f is not None:
        if f is permit:
            return True
        f = f.f_back
    return False


def _cleanup_report_dir():
    """atexit: delete the report folder (the only deletion _report_cleanup lets through)."""
    shutil.rmtree(_report_dir, True)


def _report_cleanup(event, args):
    """Parent only (patch WG4): rmtree / rmdir of the report folder itself, os.remove of <folder>/<digits>.jsonl."""
    if _child or not _report_dir or not args or isinstance(args[0], int) or not _from_cleanup():
        return False
    n, folder = _norm(args[0]), _norm(_report_dir)
    if event in ("shutil.rmtree", "os.rmdir"):
        return n == folder
    return event == "os.remove" and os.path.dirname(n) == folder and re.fullmatch(r"\d+\.jsonl", os.path.basename(n))


def _sqlite_target(db):
    if isinstance(db, (bytes, bytearray)):
        db = os.fsdecode(bytes(db))
    if not isinstance(db, str):
        db = os.fspath(db)
    if db == ":memory:":
        return None
    if db.startswith("file:"):
        from urllib.parse import parse_qs, unquote, urlsplit
        u = urlsplit(db)
        if parse_qs(u.query).get("mode") == ["memory"]:
            return None
        path = unquote(u.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return _outside(path or "")
    return _outside(db)


def _popen_allowed(executable, args, who):
    argv = split_cmdline(args) if isinstance(args, str) else [os.fsdecode(a) for a in args]
    exe = os.path.basename(os.fsdecode(executable) if executable else (argv[0] if argv else "")).lower()
    if exe and not os.path.splitext(exe)[1]:
        exe += ".exe"                    # what CreateProcess does with a bare name (taskkill, cmd, nvidia-smi)
    cat, rel = who
    if cat == "product":
        if exe not in PRODUCT_SUBPROCESSES.get(rel, ()):
            return False
        if exe == "op.exe":         # patch WG15: only `op read <op://vault/item/[section/]field>`, nothing else
            raw = args if isinstance(args, str) else " ".join(argv)
            if rel != OP_MODULE or CMD_SPECIAL & set(raw):
                return False
            if len(argv) == 2:      # patch WG16: also exactly `op whoami` (2 arguments, case-sensitive)
                return argv[1] == "whoami"
            return len(argv) == 3 and argv[1] == "read" and bool(OP_REF.match(argv[2]))
        return True
    if cat != "test":
        return False
    if exe == "python.exe":
        rest = argv[1:]
        while rest and rest[0] in ("-s", "-u", "-B"):
            rest = rest[1:]
        return bool(rest) and os.path.normcase(os.path.abspath(rest[0])) == _N_GUARDRUN
    if exe == "cmd.exe":        # patch WG3: test_cli's junction, both ends strictly inside a fixture root
        raw = args if isinstance(args, str) else " ".join(argv)
        return (len(argv) == 6 and [a.lower() for a in argv[1:4]] == ["/c", "mklink", "/j"]
                and not CMD_SPECIAL & set(raw) and _in_fixture_root(argv[4]) and _in_fixture_root(argv[5]))
    return exe in TEST_EXECUTABLES


def judge(event, args):
    """None, or the target string of a violation."""
    if event not in PROCESS_EVENTS:
        _tl.permit_frame = None         # WG9: any other watched event clears the CreateProcess permit
    if event in PATH_EVENTS:
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                return None
            if not ((mode is not None and WRITE_MODE_CHARS & set(mode)) or (flags or 0) & WRITE_FLAGS):
                return None
        elif event == "sqlite3.connect":
            return _sqlite_target(args[0])
        elif event == "_winapi.CreateFile":
            name, access, _share, disposition = args[:4]
            flags_attrs = args[4] if len(args) > 4 and isinstance(args[4], int) else 0
            if str(name).startswith("\\\\.\\pipe\\"):       # patch WG2: named pipes are not files
                return None
            if not (access & _WRITE_ACCESS or flags_attrs & _DELETE_ON_CLOSE or disposition in _CREATE_DISPOSITIONS):
                return None
        if event in ("shutil.rmtree", "os.rmdir", "os.remove") and _report_cleanup(event, args):
            return None
        for i in PATH_EVENTS[event]:
            if i < len(args):
                bad = _outside(args[i])
                if bad is not None:
                    return bad
        return None
    if event in ALWAYS_VIOLATION:
        return str(args[0] if args else "")
    who = initiator()
    if event == "subprocess.Popen":
        executable, cmd = args[0], args[1]
        _tl.permit_frame = None
        ok = _popen_allowed(executable, cmd, who)
        if ok:                          # WG9: the permit is this very _execute_child frame, nothing else
            f = _caller_frame()
            if f is not None and f.f_code is _execute_child_code():
                _tl.permit_frame = f
        return None if ok else str(cmd)
    if event == "_winapi.CreateProcess":
        # patch WG9: multiprocessing goes straight here. CPython 3.13 hands this event a garbled command line,
        # so the only process start allowed is the one a just-approved subprocess.Popen on this thread makes.
        permit, _tl.permit_frame = getattr(_tl, "permit_frame", None), None
        f = _caller_frame()             # WG9: the same _execute_child frame the approved Popen event came from
        ok = permit is not None and f is permit and f.f_code is _execute_child_code()
        return None if ok else f"{args[0] or '（命令列不可讀）'}（發起者 {who[1]}）"
    if event in ("ctypes.dlopen", "ctypes.dlsym"):      # G3: third-party only (patch WG2: also dlsym)
        return None if who[0] == "third-party" else f"{args[-1]}（發起者 {who[1]}）"
    return None


# ---------------------------------------------------------------- the hook
def _test_id():
    return _child["test_id"] if _child else (_current[0] or "無")


def format_violation(v):
    return VIOLATION_LINE.format(event=v["event"], target=v["target"], test_id=v["test_id"]) + "\n" + v["stack"]


def _hook(event, args):
    if event not in WATCHED or getattr(_tl, "busy", False):
        return
    _tl.busy = True
    try:
        target = judge(event, args)
        if target is None:
            return
        v = {"event": event, "target": target, "test_id": _test_id(),
             "stack": "".join(traceback.format_stack(sys._getframe(1)))}
        with _lock:
            _table.append(v)
        if _child:
            with open(_child["report"], "a", encoding="utf-8") as f:     # inside the hook: not re-judged
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
    finally:
        _tl.busy = False
    raise WriteGuardViolation(format_violation(v))


# ---------------------------------------------------------------- roots (G4)
def new_root(prefix="darkroom-test-"):
    """Register a fresh path under %TEMP% as a writable root, then create it (never the other way round)."""
    while True:
        d = os.path.join(tempfile.gettempdir(), prefix + secrets.token_hex(6))
        n = _norm(d)
        if not os.path.lexists(d):
            break
    with _lock:
        _roots.append(n)
    try:
        os.mkdir(d)
    except BaseException:
        _unregister(n)
        raise
    return d


def release_root(d):
    """Delete the root, then unregister it; a root that cannot be deleted fails the test (no silent leak)."""
    import gc
    import time
    try:
        for attempt in range(5):
            shutil.rmtree(d, True)
            if not os.path.lexists(d):
                break
            gc.collect()                 # e.g. a connection object still holding a file open
            time.sleep(0.2)
    finally:
        _unregister(_norm(d))
    if os.path.lexists(d):
        raise AssertionError(f"暫存根目錄刪不掉（有檔案還開著？）：{d}")


def _unregister(n):
    with _lock:
        if n in _roots:
            _roots.remove(n)


def roots():
    with _lock:
        return list(_roots)


# ---------------------------------------------------------------- protected folders (G7)
def protected_folders():
    """The three folders snapshotted at arming and in test_zz_writeguard."""
    d = os.environ.get("DARKROOM_PRESET_DIR")         # same resolution as _util.preset_dir()
    if not d:
        from darkroom_app import config
        d = config.preset_dir()
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return [PHOTOS, os.path.dirname(os.path.abspath(d)), os.path.join(local, "darkroom")]


def snapshot_folder(root):
    """{relative name: sha256 | "<dir>"} recursively, or None when the folder does not exist."""
    if not os.path.isdir(root):
        return None
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in dirs:
            out[os.path.relpath(os.path.join(base, name), root)] = "<dir>"
        for name in sorted(files):
            p = os.path.join(base, name)
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[os.path.relpath(p, root)] = h.hexdigest()
    return out


def snapshot(folders=None):
    return {f: snapshot_folder(f) for f in (folders or protected_folders())}


def snapshot_diff(before, after):
    """Sorted list of changed paths ("<folder>" itself when it appeared or disappeared)."""
    out = []
    for folder in sorted(set(before) | set(after)):
        a, b = before.get(folder), after.get(folder)
        if (a is None) != (b is None):
            out.append(folder)
            continue
        for name in sorted(set(a or {}) | set(b or {})):
            if (a or {}).get(name) != (b or {}).get(name):
                out.append(os.path.join(folder, name))
    return out


def arm_snapshot():
    return _snapshot_at_arm


def protect(testcase, folder):
    """Declare a (synthetic) folder protected: its snapshot is compared after the test (G7)."""
    before = snapshot([folder])

    def check():
        diff = snapshot_diff(before, snapshot([folder]))
        if diff:
            raise AssertionError("受保護資料夾內容改變：" + "、".join(diff))
    testcase.addCleanup(check)


# ---------------------------------------------------------------- violations
def collect_child_reports():
    if not _report_dir or not os.path.isdir(_report_dir):
        return
    for name in sorted(os.listdir(_report_dir)):
        p = os.path.join(_report_dir, name)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        seen = _report_seen.get(p, 0)
        new, _report_seen[p] = text[seen:], len(text)
        with _lock:
            _table.extend(json.loads(line) for line in new.splitlines() if line.strip())


def violations():
    collect_child_reports()
    with _lock:
        return list(_table)


def _take_unclaimed():
    global _claimed
    collect_child_reports()
    with _lock:
        new, _claimed = _table[_claimed:], len(_table)
    return new


def _error_for(new):
    extra = f"\n（另有 {len(new) - 1} 筆違規：" + "；".join(f"{v['event']} → {v['target']}" for v in new[1:]) + "）" \
        if len(new) > 1 else ""
    return WriteGuardViolation(format_violation(new[0]) + extra)


class expect_violation:
    """test_writeguard.py only (test_guard_has_no_pause checks it): the block must hit the guard at least once;
    the violations it caused are handed to the caller and taken out of the table. The hook keeps blocking."""

    def __enter__(self):
        collect_child_reports()
        with _lock:
            self.start, self.claimed = len(_table), _claimed
        self.caught = []
        return self

    def __exit__(self, *exc):
        global _claimed
        collect_child_reports()
        with _lock:
            self.caught = _table[self.start:]
            del _table[self.start:]
            _claimed = min(max(_claimed, self.claimed), len(_table))
        if exc[0] is not None and not issubclass(exc[0], WriteGuardViolation):
            return False
        if not self.caught:
            raise AssertionError("expected the write guard to block this block, it did not")
        return True


# ---------------------------------------------------------------- unittest wiring (G5)
def _install_unittest():
    import unittest
    import unittest.suite as suite

    original_run = unittest.TestCase.run

    def run(self, result=None):
        prev = _current[0]
        _current[0] = self.id()
        self.addCleanup(_check_test)
        try:
            return original_run(self, result)
        finally:
            _current[0] = prev

    def _check_test():
        new = _take_unclaimed()
        if new:
            raise _error_for(new)

    def wrap_fixture(name, label):
        original = getattr(suite.TestSuite, name)

        def wrapped(self, test, result):
            prev = _current[0]
            cls = test.__class__ if name != "_handleModuleFixture" else None
            if name == "_tearDownPreviousClass":
                cls = getattr(result, "_previousTestClass", None)
            desc = f"{cls.__module__}.{cls.__qualname__}.{label}" if cls else f"{test.__class__.__module__}.{label}"
            _current[0] = desc
            try:
                return original(self, test, result)
            finally:
                _current[0] = prev
                new = _take_unclaimed()
                if new and result is not None:
                    try:
                        raise _error_for(new)
                    except WriteGuardViolation:
                        result.addError(suite._ErrorHolder(desc), sys.exc_info())
        setattr(suite.TestSuite, name, wrapped)

    unittest.TestCase.run = run
    wrap_fixture("_handleClassSetUp", "setUpClass")
    wrap_fixture("_tearDownPreviousClass", "tearDownClass")
    wrap_fixture("_handleModuleFixture", "setUpModule")


# ---------------------------------------------------------------- child processes (G6)
def python_cmd():
    """argv prefix for a guarded child python: [python, -s, _guardrun.py, --roots, …, --report, …, --test-id, …]."""
    return [sys.executable, "-s", GUARDRUN, "--roots", json.dumps(roots()), "--report", _report_dir,   # WG4: no report
            "--test-id", _test_id()]


def child_exit_code():
    """Under _guardrun.py: 86 when this process hit the guard, else None."""
    with _lock:
        return CHILD_EXIT if _table else None


def first_violation_text():
    with _lock:
        return format_violation(_table[0]) if _table else ""


def _arm_child(argv):
    global _child
    opts = dict(zip(argv[0::2], argv[1::2]))
    with _lock:
        _roots.extend(json.loads(opts["--roots"]))
    _child = {"report": os.path.join(opts["--report"], f"{os.getpid()}.jsonl"), "test_id": opts["--test-id"]}
    sys.addaudithook(_hook)


def _arm_parent():
    global _report_dir, _snapshot_at_arm
    _snapshot_at_arm = snapshot()
    _report_dir = os.path.join(tempfile.gettempdir(), f"darkroom-guard-{os.getpid()}-{secrets.token_hex(6)}")
    os.mkdir(_report_dir)                       # the guard's own report folder, made before the hook exists
    # patch WG4: the report folder is NOT a root; only _report_cleanup's three exact events are let through
    import atexit
    atexit.register(_cleanup_report_dir)
    _install_unittest()
    sys.addaudithook(_hook)


ARMED = True
if os.path.normcase(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else "")) == _N_GUARDRUN:
    _arm_child(sys.argv[1:7])
else:
    _arm_parent()
