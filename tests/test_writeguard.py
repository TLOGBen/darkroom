"""CONTRACT-write-guard G1-G8, G11: the runtime write guard (tests/_writeguard.py) and darkroom_app/safe_write.py.

Probes run "as the product": their code is compiled with a file name under darkroom_app/ and executed in a fresh
namespace, so the guard sees a product frame as the initiator. Every blocked probe runs inside
`_writeguard.expect_violation()`, which requires the block to hit the guard and takes the violations it caused out of
the table (the hook itself keeps blocking).
"""
import ast
import builtins
import os
import re
import secrets
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import _util
import _writeguard
from darkroom_app import safe_write

TESTS = os.path.join(_util.REPO, "tests")
PRODUCT_FILE = os.path.join(_util.REPO, "darkroom_app", "_writeguard_probe.py")   # never exists on disk
VIOLATION_LINE = "寫檔守門：{event} → {target}（測試 {test_id}）"                    # verbatim (G5)
CHILD_EXIT = 86                                                                    # verbatim (G6)

# (constant name, probe source, first event the guard must block) - the 13 of G11, verbatim names
PROBES_13 = [
    ('open(p,"wb")', 'open(p, "wb").close()', "open"),
    ('m="w"+"b"; open(p,m)', 'm = "w" + "b"\nopen(p, m).close()', "open"),
    ("os.open(p,O_CREAT|O_WRONLY)", "import os\nos.close(os.open(p, os.O_CREAT | os.O_WRONLY))", "open"),
    ("Path(p).write_bytes", "from pathlib import Path\nPath(p).write_bytes(b'x')", "open"),
    ("Path(a).replace(p)", "from pathlib import Path\nPath(a).replace(p)", "os.rename"),
    ('gzip.open(p,"wb")', 'import gzip\ngzip.open(p, "wb").close()', "open"),
    ('zipfile.ZipFile(p,"w")', 'import zipfile\nzipfile.ZipFile(p, "w").close()', "open"),
    ('tarfile.open(p,"w")', 'import tarfile\ntarfile.open(p, "w").close()', "open"),
    ('lzma.open(p,"wb")', 'import lzma\nlzma.open(p, "wb").close()', "open"),
    ("shelve.open(p)", "import shelve\nshelve.open(p).close()", "os.utime"),
    ("sqlite3.connect(p)", "import sqlite3\nc = sqlite3.connect(p)\nc.execute('create table t(x)')\nc.close()",
     "sqlite3.connect"),
    ('subprocess.run(["cmd","/c","echo x>"+p])',
     "import subprocess\nsubprocess.run(['cmd', '/c', 'echo x>' + p], capture_output=True)", "subprocess.Popen"),
    ('ctypes.WinDLL("kernel32").CreateFileW(p,…)',
     "import ctypes\nk = ctypes.WinDLL('kernel32')\nh = k.CreateFileW(p, 0x40000000, 0, None, 2, 0x80, None)\n"
     "k.CloseHandle(h)", "ctypes.dlopen"),
]
# the bypasses CONTRACT-layering handed over (AST could not see them) plus the _winapi writes of patch WG2
PROBES_HANDOFF = [
    ('open(p, **{"mode":"wb"})', 'open(p, **{"mode": "wb"}).close()', "open"),
    ('open(*[p,"wb"])', 'open(*[p, "wb"]).close()', "open"),
    ('o = open; o(p,"wb")', 'o = open\no(p, "wb").close()', "open"),
    ("def f(p, opener=open)", 'def f(q, opener=open):\n    opener(q, "wb").close()\nf(p)', "open"),
    ("logging.FileHandler", "import logging\nlogging.FileHandler(p).close()", "open"),
    ("sqlite3.connect (file: URI)", "import sqlite3, pathlib\nc = sqlite3.connect(pathlib.Path(p).as_uri(), uri=True)\n"
     "c.execute('create table t(x)')\nc.close()", "sqlite3.connect"),
    ("os.utime", "import os\nos.utime(p)", "os.utime"),
    ('zipfile.ZipFile(p,"w") via a', 'import zipfile\nwith zipfile.ZipFile(p, "w") as z:\n    z.write(a, "a")', "open"),
    ('gzip.GzipFile(p,"wb")', 'import gzip\ngzip.GzipFile(p, "wb").close()', "open"),
    ("os.system", "import os\nos.system('echo x>' + p)", "os.system"),
    ("ctypes (cached windll)", "import ctypes\nctypes.windll.kernel32.CreateFileW", ("ctypes.dlopen", "ctypes.dlsym")),
    ('dbm.open(p,"c")', 'import dbm\ndbm.open(p, "c").close()', "os.utime"),
    ("shutil.copy2(a,p)", "import shutil\nshutil.copy2(a, p)", "_winapi.CopyFile2"),
    ("shutil.copyfile(a,p)", "import shutil\nshutil.copyfile(a, p)", "shutil.copyfile"),
    ("os.replace(a,p)", "import os\nos.replace(a, p)", "os.rename"),
    ("os.mkdir(p)", "import os\nos.mkdir(p)", "os.mkdir"),
    ("os.link(p, inside)", "import os\nos.link(p, a + '.lnk')", "os.link"),     # patch WG12: hard link in
    # patch WG13: rights other than GENERIC_WRITE that still change or delete an existing file
    ("_winapi.CreateFile GENERIC_ALL", "import _winapi\nh = _winapi.CreateFile(p, 0x10000000, 0, 0, 3, 0x80, 0)\n"
     "_winapi.CloseHandle(h)", "_winapi.CreateFile"),
    ("_winapi.CreateFile DELETE_ON_CLOSE", "import _winapi\nh = _winapi.CreateFile(p, 0x10000, 7, 0, 3, 0x04000000, 0)\n"
     "_winapi.CloseHandle(h)", "_winapi.CreateFile"),
    ("os.open(p,O_RDONLY|O_TEMPORARY)", "import os\nos.close(os.open(p, os.O_RDONLY | os.O_TEMPORARY))", "open"),
    ("_winapi.CreateFile", "import _winapi\nh = _winapi.CreateFile(p, 0x40000000, 0, 0, 2, 0x80, 0)\n"
     "_winapi.CloseHandle(h)", "_winapi.CreateFile"),
    ("_winapi.CreateJunction", "import _winapi\n_winapi.CreateJunction(os.path.dirname(a), p)",
     "_winapi.CreateJunction"),
    # patch WG9 (seal probe X1): multiprocessing spawns through _winapi.CreateProcess, no subprocess.Popen event
    ("ProcessPoolExecutor", "from concurrent.futures import ProcessPoolExecutor\nfrom pathlib import Path\n"
     "with ProcessPoolExecutor(1) as ex:\n    ex.submit(Path(p).write_bytes, b'x').result()",
     "_winapi.CreateProcess"),
    ("multiprocessing.Process", "import multiprocessing\nfrom pathlib import Path\n"
     "q = multiprocessing.Process(target=Path(p).write_bytes, args=(b'x',))\nq.start()\nq.join()",
     "_winapi.CreateProcess"),
]
# G3: blocked whatever the path (the product may not start processes or load DLLs) - patch WG5, WG9
EXISTING_P = ("os.utime", "os.link(p, inside)", "_winapi.CreateFile GENERIC_ALL",
              "_winapi.CreateFile DELETE_ON_CLOSE", "os.open(p,O_RDONLY|O_TEMPORARY)")
NOT_PATH_BASED = {"subprocess.Popen", "_winapi.CreateProcess", "ctypes.dlopen", "ctypes.dlsym", "os.system", "os.fork",
                  "os.posix_spawn"}

# POSIX (CI on Linux): there is no _winapi, cmd, kernel32 or O_TEMPORARY. The Windows-only probes are left out, the
# others keep their names and either run as they are or try the same thing through the POSIX means, and two probes
# are added for what POSIX has instead (a symlink in place of a junction, os.posix_spawn in place of CreateProcess).
WINDOWS = sys.platform == "win32"
WINDOWS_ONLY_PROBES = {"_winapi.CreateFile GENERIC_ALL", "_winapi.CreateFile DELETE_ON_CLOSE",
                       "os.open(p,O_RDONLY|O_TEMPORARY)", "_winapi.CreateFile", "_winapi.CreateJunction"}
POSIX_PROBES = {   # name -> (source or None = the same source, first event(s) the guard must block)
    'ctypes.WinDLL("kernel32").CreateFileW(p,…)': (
        "import ctypes\nlibc = ctypes.CDLL(None)\nlibc.close(libc.open(p.encode(), 0o101, 0o644))", "ctypes.dlopen"),
    "ctypes (cached windll)": ("import ctypes\nctypes.CDLL(None).open", ("ctypes.dlopen", "ctypes.dlsym")),
    "shelve.open(p)": (None, ("os.utime", "open", "sqlite3.connect")),       # dbm.sqlite3 is the default there
    'dbm.open(p,"c")': (None, ("os.utime", "open", "sqlite3.connect")),
    "shutil.copy2(a,p)": (None, "shutil.copyfile"),                           # no CopyFile2: copyfile's own event
    "ProcessPoolExecutor": (None, "os.fork"),                                # multiprocessing forks on Linux
    "multiprocessing.Process": (None, "os.fork"),
}
POSIX_EXTRA_PROBES = [
    ("os.symlink(dir, p)", "import os\nos.symlink(os.path.dirname(a), p)", "os.symlink"),
    ("os.posix_spawn", "import os\nos.posix_spawn('/bin/sh', ['sh', '-c', 'echo x>' + p], {})", "os.posix_spawn"),
]


def platform_probes():
    """PROBES_13 + PROBES_HANDOFF as they run on this platform."""
    probes = PROBES_13 + PROBES_HANDOFF
    if WINDOWS:
        return probes
    out = []
    for name, src, event in probes:
        if name not in WINDOWS_ONLY_PROBES:
            psrc, pevent = POSIX_PROBES.get(name, (None, event))
            out.append((name, psrc or src, pevent))
    return out + POSIX_EXTRA_PROBES


def run_as_product(src, **names):
    ns = {"__name__": "darkroom_app._writeguard_probe", "__builtins__": builtins, "os": os, **names}
    exec(compile(src, PRODUCT_FILE, "exec"), ns)


def outside_path(ext=".bin"):
    """A path in %TEMP% itself (exists, writable, but not a declared root)."""
    return os.path.join(tempfile.gettempdir(), f"darkroom-probe-{secrets.token_hex(6)}{ext}")


class TestWriteGuardProbes(unittest.TestCase):  # G2, G3, G11
    def test_writeguard_probes(self):
        root = _util.tmpdir(self)
        for name, src, event in platform_probes():
            with self.subTest(probe=name):
                a = os.path.join(root, f"a-{secrets.token_hex(4)}.bin")
                with open(a, "wb") as f:
                    f.write(b"a")
                p = outside_path()
                with _writeguard.expect_violation() as ev:
                    run_as_product(src, p=p, a=a)
                self.assertFalse(os.path.lexists(p), name)
                self.assertIn(ev.caught[0]["event"], event if isinstance(event, tuple) else (event,), name)
                self.assertIn(ev.caught[0]["test_id"], self.id())

    def test_probes_inside_root_pass(self):  # G11: same writes into a fixture root are allowed
        root = _util.tmpdir(self)
        for name, src, event in platform_probes():
            with self.subTest(probe=name):
                a = os.path.join(root, f"a-{secrets.token_hex(4)}.bin")
                with open(a, "wb") as f:
                    f.write(b"a")
                p = os.path.join(root, f"p-{secrets.token_hex(4)}.bin")
                if name in EXISTING_P:   # these need an existing p
                    with open(p, "wb"):
                        pass
                events = event if isinstance(event, tuple) else (event,)
                if set(events) & NOT_PATH_BASED:
                    with _writeguard.expect_violation() as ev:
                        run_as_product(src, p=p, a=a)
                    self.assertIn(ev.caught[0]["event"], events, name)
                    self.assertFalse(os.path.lexists(p), name)
                    continue
                before = len(_writeguard.violations())
                run_as_product(src, p=p, a=a)
                self.assertEqual(len(_writeguard.violations()), before, name)
                if name not in ("_winapi.CreateFile DELETE_ON_CLOSE", "os.open(p,O_RDONLY|O_TEMPORARY)"):
                    self.assertTrue(os.path.lexists(p), name)     # (those two delete it: allowed in a root)

    @unittest.skipUnless(WINDOWS, "Windows only: _winapi.CreateFile with FILE_FLAG_DELETE_ON_CLOSE")
    def test_read_only_delete_on_close_probe(self):  # CONTRACT-export XP14 (WG10 (c) 4): no DELETE bit at all
        """GENERIC_READ + FILE_FLAG_DELETE_ON_CLOSE on an existing file outside every root: blocked, file kept.

        The existing outside file is made inside a fresh fixture root, which is then unregistered for the probe
        (the writable area only shrinks; the guard is never paused) and registered again before it is released.
        """
        import hashlib
        root = _writeguard.new_root("darkroom-test-")
        n = _writeguard._norm(root)
        p = os.path.join(root, "existing.jpg")
        body = b"keep me " * 64
        with open(p, "wb") as f:
            f.write(body)
        src = ("import _winapi\nh = _winapi.CreateFile(p, 0x80000000, 7, 0, 3, 0x04000000, 0)\n"
               "_winapi.CloseHandle(h)")
        _writeguard._unregister(n)
        try:
            self.assertIsNotNone(_writeguard._outside(p))          # really outside every root now
            with _writeguard.expect_violation() as ev:
                run_as_product(src, p=p)
            self.assertEqual(ev.caught[0]["event"], "_winapi.CreateFile")
            self.assertTrue(os.path.isfile(p))
            with open(p, "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), hashlib.sha256(body).hexdigest())
        finally:
            with _writeguard._lock:
                _writeguard._roots.append(n)
            _writeguard.release_root(root)

    def test_probe_names_are_the_contract_constant(self):
        self.assertEqual(" ｜ ".join(n for n, _, _ in PROBES_13),
                         'open(p,"wb") ｜ m="w"+"b"; open(p,m) ｜ os.open(p,O_CREAT|O_WRONLY) ｜ Path(p).write_bytes ｜ '
                         'Path(a).replace(p) ｜ gzip.open(p,"wb") ｜ zipfile.ZipFile(p,"w") ｜ tarfile.open(p,"w") ｜ '
                         'lzma.open(p,"wb") ｜ shelve.open(p) ｜ sqlite3.connect(p) ｜ '
                         'subprocess.run(["cmd","/c","echo x>"+p]) ｜ ctypes.WinDLL("kernel32").CreateFileW(p,…)')

    def test_initiator_rules(self):  # G3
        root = _util.tmpdir(self)
        # tests may start node / pwsh / taskkill, and python only through _guardrun.py
        with _writeguard.expect_violation() as ev:
            subprocess.run([sys.executable, "-s", "-c", "pass"], capture_output=True)
        self.assertEqual(ev.caught[0]["event"], "subprocess.Popen")
        with _writeguard.expect_violation():
            subprocess.run(["cmd", "/c", "echo", "x"], capture_output=True)
        with _writeguard.expect_violation():      # the junction exemption (patch WG3) needs both ends in a root
            subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(root, "j"), tempfile.gettempdir()],
                           capture_output=True)
        r = subprocess.run([*_util.guarded_python(), "-c", "print('ok')"], capture_output=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, b"ok"))
        # the product may start nvidia-smi from gpucheck only
        with _writeguard.expect_violation():
            run_as_product("import subprocess\nsubprocess.run(['nvidia-smi', '-L'], capture_output=True)")
        # patch WG15: services/semantic_index.py may run exactly `op read <op://...>` (checked as a pure function:
        # tests never start op); every other shape, module or initiator is refused
        allowed = _writeguard._popen_allowed
        sem, gpu = ("product", _writeguard.OP_MODULE), ("product", "darkroom_app/gpucheck.py")
        self.assertEqual(_writeguard.PRODUCT_SUBPROCESSES,
                         {"darkroom_app/utils/gpucheck.py": ("nvidia-smi.exe",), _writeguard.OP_MODULE: ("op.exe",)})   # v2: utils/
        self.assertTrue(allowed(None, ["op", "read", "op://Personal/ClaudeAPIKey/credential"], sem))
        self.assertTrue(allowed(None, ["op.exe", "read", "op://v/i/s/f"], sem))
        for bad in (["op", "read", "op://v/i/s/f", "--no-newline"], ["op", "item", "get", "x"], ["op", "read"],
                    ["op", "read", "x"], ["op", "read", "op://v"], ["op", "read", "op://v/i"],
                    ["op", "read", "op://v/i/f&echo"], ["op", "read", "op://v/i/f/g/h"], ["op", "signin"]):
            self.assertFalse(allowed(None, bad, sem), bad)
        self.assertFalse(allowed(None, ["op", "read", "op://v/i/f"], gpu))
        self.assertFalse(allowed(None, ["op", "read", "op://v/i/f"], ("test", "tests/test_x.py")))
        # patch WG16: exactly `op whoami` too (2 arguments), from the same module only
        self.assertTrue(allowed(None, ["op", "whoami"], sem))
        self.assertTrue(allowed(None, ["op.exe", "whoami"], sem))
        self.assertTrue(allowed(None, ["OP.EXE", "whoami"], sem))            # the executable name ignores case
        for bad in (["op", "whoami", "--format", "json"], ["op", "whoami", "--format=json"], ["op", "WHOAMI"],
                    ["op", "Whoami"], ["op", "signin"], ["op", "account", "list"], ["op"], ["op", "whoami "],
                    ["op", "whoami&echo"], ["op", "user", "get", "--me"]):
            self.assertFalse(allowed(None, bad, sem), bad)
        self.assertFalse(allowed(None, ["op", "whoami"], gpu))
        self.assertFalse(allowed(None, ["op", "whoami"], ("test", "tests/test_x.py")))
        self.assertFalse(allowed(None, ["op", "whoami"], ("product", "darkroom_app/services/capabilities.py")))
        self.assertFalse(allowed(None, "op whoami --format json", sem))
        self.assertFalse(allowed(None, ["nvidia-smi", "-L"], sem))
        self.assertEqual(_writeguard.judge("ctypes.dlopen", ("kernel32",)) is not None, True)   # test frame
        for ev in ("os.system", "os.startfile", "os.exec", "os.spawn", "os.posix_spawn"):
            self.assertIsNotNone(_writeguard.judge(ev, ("x",)), ev)

    @unittest.skipUnless(WINDOWS, "Windows only: the cmd /c mklink /J junction exemption")
    def test_mklink_exemption_is_exact(self):  # patch WG3 (tightened 2026-10-09)
        root = _util.tmpdir(self)
        report = _writeguard._report_dir

        def popen(cmdline):
            return _writeguard.judge("subprocess.Popen", (None, cmdline, None, None))
        self.assertIsNone(popen(f"cmd /c mklink /J {root}\\j {root}"))
        cp = ("_winapi.CreateProcess", (None, "\x02", None))     # 3.13 passes a garbled command line here
        self.assertIsNotNone(_writeguard.judge(*cp))   # approved, but not called from Popen._execute_child (WG9)
        popen(f"cmd /c mklink /J {root}\\j {root}")
        self.assertIsNotNone(_writeguard.judge(*cp))   # still not _execute_child, and the permit is gone now
        for bad in (f"cmd /c mklink /J nul {root}",                                         # devnull end
                    f"cmd /c mklink /J C:\\Windows\\__pycache__\\j.cpython-313.pyc {root}",  # pycache end
                    f"cmd /c mklink /J {root}\\x&echo>C:\\evil.txt {root}",                 # cmd metacharacters
                    f"cmd /c mklink /J {root}\\x|y {root}", f"cmd /c mklink /J {root}\\x^y {root}",
                    f"cmd /c mklink /J {root}\\%x% {root}", f"cmd /c mklink /J {root}\\x!y! {root}",
                    f"cmd /c mklink /J {root}\\x<y {root}", f'cmd /c mklink /J "{root}\\x" {root}',
                    f"cmd /c mklink /J {root}\\x\ny {root}", f"cmd /c mklink /J {root}\\x\ry {root}",
                    f"cmd /c mklink /J {report}\\j {root}",                                 # report folder end
                    f"cmd /c mklink /J {root}\\j {tempfile.gettempdir()}",                  # target outside
                    f"cmd /c mklink /J {root}\\j {root} extra", f"cmd /c echo {root}"):
            with self.subTest(bad=bad):
                self.assertIsNotNone(popen(bad))

    @unittest.skipIf(WINDOWS, "POSIX only: Popen starts processes through os.posix_spawn there")
    def test_posix_spawn_permit(self):
        self.assertTrue(subprocess._USE_POSIX_SPAWN)
        self.assertIsNotNone(_writeguard.judge("os.posix_spawn", ("/bin/true", ["true"], {})))   # no approved Popen
        # an approved Popen that takes the posix_spawn path (absolute executable, no cwd, close_fds=False) runs
        r = subprocess.run([*_util.guarded_python(), "-c", "print('ok')"], capture_output=True, close_fds=False)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, b"ok"))
        self.assertFalse(_writeguard.popen_permit())               # nothing left behind
        with _writeguard.expect_violation() as ev:                 # a direct os.posix_spawn is still blocked
            subprocess.run([sys.executable, "-s", "-c", "pass"], capture_output=True, close_fds=False)
        self.assertEqual(ev.caught[0]["event"], "subprocess.Popen")
        p = outside_path()
        with _writeguard.expect_violation() as ev:
            run_as_product("import os\nos.posix_spawn('/bin/sh', ['sh', '-c', 'echo x>' + p], {})", p=p)
        self.assertEqual(ev.caught[0]["event"], "os.posix_spawn")
        self.assertFalse(os.path.lexists(p))

    @unittest.skipUnless(WINDOWS, "Windows only: taskkill and _winapi.CreateProcess")
    def test_createprocess_permit_cannot_be_reused(self):  # patch WG9 (tightened 2026-10-09)
        mp = ("import multiprocessing\nfrom pathlib import Path\n"
              "q = multiprocessing.Process(target=Path(p).write_bytes, args=(b'x',))\nq.start()\nq.join()")
        # an approved Popen that raises before CreateProcess must not leave a permit behind
        with self.assertRaises(ValueError):
            subprocess.Popen(["taskkill", "/?"], cwd="a\0b", stdout=subprocess.DEVNULL)
        p = outside_path()
        with _writeguard.expect_violation() as ev:
            run_as_product(mp, p=p)
        self.assertEqual(ev.caught[0]["event"], "_winapi.CreateProcess")
        self.assertFalse(os.path.lexists(p))
        # the same from test code
        with self.assertRaises(ValueError):
            subprocess.Popen(["taskkill", "/?"], cwd="a\0b", stdout=subprocess.DEVNULL)
        with _writeguard.expect_violation() as ev:
            exec(compile(mp, __file__, "exec"), {"__name__": "probe", "p": p})
        self.assertEqual(ev.caught[0]["event"], "_winapi.CreateProcess")
        # any other watched event in between clears the permit
        root = _util.tmpdir(self)
        f = os.path.join(root, "f")
        open(f, "wb").close()
        with self.assertRaises(ValueError):
            subprocess.Popen(["taskkill", "/?"], cwd="a\0b", stdout=subprocess.DEVNULL)
        self.assertFalse(_writeguard.popen_permit())               # a failed approved Popen leaves no permit
        os.remove(f)
        self.assertFalse(_writeguard.popen_permit())
        with self.assertRaises(ValueError):
            subprocess.Popen(["taskkill", "/?"], cwd="a\0b", stdout=subprocess.DEVNULL)
        with _writeguard.expect_violation() as ev:
            run_as_product("import os\ntry:\n    os.remove(a)\nexcept OSError:\n    pass\n" + mp, p=p,
                           a=os.path.join(root, "missing"))
        self.assertEqual(ev.caught[0]["event"], "_winapi.CreateProcess")
        # a forged _execute_child (same name, globals claiming to be subprocess) does not count: code object check
        forged = ("import _winapi, subprocess\n"
                  "def _execute_child():\n"
                  "    return _winapi.CreateProcess(None, 'cmd /c exit 0', None, None, False, 0, None, None,\n"
                  "                                 subprocess.STARTUPINFO())\n")
        ns = {"__name__": "subprocess"}
        exec(compile(forged, os.path.join(sys.base_prefix, "Lib", "subprocess.py"), "exec"), ns)
        with _writeguard.expect_violation() as ev:
            try:
                subprocess.Popen(["taskkill", "/?"], cwd="a\0b", stdout=subprocess.DEVNULL)
            except ValueError:
                pass
            permit_left = _writeguard.popen_permit()        # nothing watched in between, and still no permit
            ns["_execute_child"]()
        self.assertFalse(permit_left)
        self.assertEqual(ev.caught[0]["event"], "_winapi.CreateProcess")
        r = subprocess.run(["taskkill", "/?"], capture_output=True)          # a normal approved Popen still works
        self.assertEqual(r.returncode, 0)

    def test_report_folder_is_not_a_root(self):  # patch WG4 (tightened 2026-10-09)
        report = _writeguard._report_dir
        self.assertNotIn(_writeguard._norm(report), _writeguard.roots())
        cmd = _writeguard.python_cmd()
        self.assertNotIn(_writeguard._norm(report), cmd[cmd.index("--roots") + 1].lower().replace("\\\\", "\\"))
        with _writeguard.expect_violation():                       # the parent may not write there either
            open(os.path.join(report, "x.bin"), "wb").close()
        self.assertFalse(os.path.exists(os.path.join(report, "x.bin")))
        # a forged cleanup (same name, __file__ claiming to be the guard) does not count: code object check
        forged = {"__name__": "_writeguard", "__file__": _writeguard.__file__, "_writeguard": _writeguard,
                  "report": report}
        exec(compile("def _cleanup_report_dir():\n    return _writeguard.judge('os.rmdir', (report, None))\n",
                     _writeguard.__file__, "exec"), forged)
        self.assertIsNotNone(forged["_cleanup_report_dir"]())
        # only the guard's own atexit cleanup may delete there (WG4); any other initiator is blocked
        self.assertIsNotNone(_writeguard.judge("os.remove", (os.path.join(report, "123.jsonl"), None)))
        self.assertIsNotNone(_writeguard.judge("os.rmdir", (report, None)))
        self.assertIsNotNone(_writeguard.judge("shutil.rmtree", (report, None)))
        for ev, target in (("os.remove", os.path.join(report, "x.jsonl")), ("os.remove", os.path.join(report, "1.bin")),
                           ("os.rmdir", os.path.join(report, "sub")), ("shutil.rmtree", os.path.dirname(report))):
            self.assertIsNotNone(_writeguard.judge(ev, (target, None)), (ev, target))
        child = ("import os, sys\nd = sys.argv[1]\n"
                 "for name in ('x.bin', '999999999.jsonl'):\n"
                 "    try:\n        open(os.path.join(d, name), 'ab').close()\n"
                 "    except BaseException:\n        pass\n")

        class Inner(unittest.TestCase):
            def test_child_writes_into_report_folder(self):
                subprocess.run([*_util.guarded_python(), "-c", child, report], capture_output=True, timeout=120)

        result = unittest.TestResult()
        case = Inner("test_child_writes_into_report_folder")
        with _writeguard.expect_violation() as ev:
            case.run(result)
        self.assertFalse(result.wasSuccessful())                   # the parent test turns red
        self.assertEqual(sorted(os.path.basename(v["target"]) for v in ev.caught), ["999999999.jsonl", "x.bin"])
        for name in ("x.bin", "999999999.jsonl"):
            self.assertFalse(os.path.exists(os.path.join(report, name)), name)

    def test_classification(self):
        cat = _writeguard._category
        self.assertEqual(cat(os.path.join(_util.REPO, "darkroom_app", "x.py")), "product")
        self.assertEqual(cat(os.path.join(_util.REPO, "darkroom", "x.py")), "product")
        self.assertEqual(cat(os.path.join(TESTS, "x.py")), "test")
        site = os.path.join(sys.base_prefix, "Lib", "site-packages") if WINDOWS else sysconfig.get_paths()["purelib"]
        self.assertEqual(cat(os.path.join(site, "torch", "x.py")), "third-party")
        self.assertEqual(cat(os.path.join(sys.base_prefix, "python313.zip", "subprocess.pyc")), "stdlib")
        self.assertEqual(cat("<string>"), "other")
        self.assertEqual(_writeguard.split_cmdline('"C:\\a b\\python.exe" -s x "y z" "q\\"r"'),
                         ["C:\\a b\\python.exe", "-s", "x", "y z", 'q"r'])

    def test_memory_sqlite_and_devnull_pass(self):  # G2, G4
        import sqlite3
        sqlite3.connect(":memory:").close()
        sqlite3.connect("file:x?mode=memory", uri=True).close()
        with open(os.devnull, "w") as f:
            f.write("x")
        self.assertIsNone(_writeguard.judge("open", (os.path.join(TESTS, "__pycache__", "x.cpython-313.pyc.123"),
                                                     None, os.O_CREAT | os.O_WRONLY)))
        self.assertIsNotNone(_writeguard.judge("open", (os.path.join(TESTS, "__pycache__", "x.pyc"), "wb", 0)))
        self.assertIsNotNone(_writeguard.judge("open", (os.path.join(TESTS, "x.cpython-313.pyc"), "wb", 0)))
        self.assertIsNotNone(_writeguard.judge("sqlite3.connect", ("",)))
        self.assertIsNone(_writeguard.judge("open", (3, "wb", 0)))
        self.assertIsNone(_writeguard.judge("open", (outside_path(), "rb", os.O_RDONLY)))
        for m in ("w", "a", "x", "r+"):
            self.assertIsNotNone(_writeguard.judge("open", (outside_path(), m, 0)), m)
        for flag in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"):
            self.assertIsNotNone(_writeguard.judge("open", (outside_path(), None, getattr(os, flag))), flag)


class TestViolationReporting(unittest.TestCase):  # G5, G6
    def test_violation_message_format(self):
        p = outside_path()
        with _writeguard.expect_violation():
            try:
                run_as_product('open(p, "wb")', p=p)
            except _writeguard.WriteGuardViolation as e:
                msg = str(e)
        first, _, stack = msg.partition("\n")
        self.assertEqual(first, VIOLATION_LINE.format(event="open", target=os.path.normcase(os.path.realpath(p)),
                                                      test_id=self.id()))
        self.assertEqual(_writeguard.VIOLATION_LINE, VIOLATION_LINE)
        self.assertIn("_writeguard_probe.py", stack)
        self.assertIn("test_writeguard.py", stack)
        self.assertTrue(issubclass(_writeguard.WriteGuardViolation, BaseException))
        self.assertFalse(issubclass(_writeguard.WriteGuardViolation, Exception))

    def test_violation_swallowed_still_fails(self):
        p = outside_path()

        class Inner(unittest.TestCase):
            def test_swallowed_base_exception(self):
                run_as_product('try:\n    open(p, "wb")\nexcept BaseException:\n    pass', p=p)

            def test_except_exception_does_not_catch(self):
                run_as_product('try:\n    open(p, "wb")\nexcept Exception:\n    pass', p=p)

            def test_except_oserror_does_not_catch(self):
                run_as_product('try:\n    open(p, "wb")\nexcept OSError:\n    pass', p=p)

            def test_on_worker_thread(self):   # like the darkroom-gpu executor or a thumbnail thread
                with ThreadPoolExecutor(1, thread_name_prefix="darkroom-gpu") as ex:
                    fut = ex.submit(run_as_product, 'open(p, "wb")', p=p)
                    fut.exception()          # swallowed: the future just holds it

        names = ["test_swallowed_base_exception", "test_except_exception_does_not_catch",
                 "test_except_oserror_does_not_catch", "test_on_worker_thread"]
        for name in names:
            with self.subTest(name):
                result = unittest.TestResult()
                case = Inner(name)
                with _writeguard.expect_violation():
                    case.run(result)
                self.assertFalse(result.wasSuccessful(), name)
                text = "".join(t for _, t in result.errors + result.failures)
                self.assertIn(VIOLATION_LINE.format(event="open", target=os.path.normcase(os.path.realpath(p)),
                                                    test_id=case.id()), text)
                self.assertFalse(os.path.lexists(p))

    def test_guardrun_child_violation(self):
        p = outside_path()
        target = os.path.normcase(os.path.realpath(p))
        for code in ('open(sys.argv[1], "wb")',
                     'try:\n    open(sys.argv[1], "wb")\nexcept BaseException:\n    pass\nprint("swallowed")'):
            with self.subTest(code=code), _writeguard.expect_violation() as ev:
                r = subprocess.run([*_util.guarded_python(), "-c", "import sys\n" + code, p], capture_output=True,
                                   timeout=120)
            self.assertEqual(r.returncode, CHILD_EXIT, r.stderr)
            self.assertEqual(r.stderr.decode("utf-8").splitlines()[0],
                             VIOLATION_LINE.format(event="open", target=target, test_id=self.id()))
            self.assertEqual([v["event"] for v in ev.caught], ["open"])     # the parent saw it too
            self.assertFalse(os.path.lexists(p))

    def test_child_inherits_roots(self):
        root = _util.tmpdir(self)
        p = os.path.join(root, "child.bin")
        r = subprocess.run([*_util.guarded_python(), "-c", "import sys\nopen(sys.argv[1], 'wb').write(b'k')", p],
                           capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"k")


class TestGuardWiring(unittest.TestCase):  # G1, G4, G7
    def test_every_module_arms_guard(self):
        def top_imports(path):
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            return {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
        mods = sorted(f for f in os.listdir(TESTS) if f.startswith("test_") and f.endswith(".py"))
        self.assertGreaterEqual(len(mods), 20)
        for m in mods:
            self.assertTrue(top_imports(os.path.join(TESTS, m)) & {"_util", "_writeguard"}, m)
        self.assertIn("_writeguard", top_imports(os.path.join(TESTS, "_util.py")))
        self.assertTrue(_writeguard.ARMED)

    def test_guard_has_no_pause(self):
        banned = re.compile(r"pause|disable|disarm|suspend|unarm|bypass|unhook|silence|^off$|^stop", re.I)
        for f in ("_writeguard.py", "_guardrun.py"):
            path = os.path.join(TESTS, f)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                name = getattr(node, "name", None) or getattr(node, "id", None) or getattr(node, "attr", None)
                if isinstance(name, str):
                    self.assertIsNone(banned.search(name), (f, name))
                if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv", "putenv"):
                    # only the two lookups that resolve the protected folders; nothing that turns the guard off
                    self.assertEqual(f, "_writeguard.py")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" \
                        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "environ":
                    self.assertIn(node.args[0].value, ("DARKROOM_PRESET_DIR", "LOCALAPPDATA"))
            if f == "_writeguard.py":     # the re-entrancy flag is only ever set inside the hook
                for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
                    sets = [n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr == "busy"
                            and isinstance(n.ctx, ast.Store)]
                    self.assertTrue(not sets or fn.name == "_hook", fn.name)
        for f in os.listdir(TESTS):
            if f.endswith(".py") and f not in ("_writeguard.py", "test_writeguard.py"):
                with open(os.path.join(TESTS, f), encoding="utf-8") as fh:
                    self.assertNotIn("expect_violation", fh.read(), f)

    def test_roots_lifecycle(self):  # G4
        seen = {}

        class Inner(unittest.TestCase):
            def test_it(self):
                d = _util.tmpdir(self)
                seen["d"] = d
                seen["registered"] = _writeguard._norm(d) in _writeguard.roots()
                with open(os.path.join(d, "x"), "wb") as f:
                    f.write(b"1")

        result = unittest.TestResult()
        Inner("test_it").run(result)
        self.assertTrue(result.wasSuccessful(), result.errors)
        self.assertTrue(seen["registered"])
        self.assertFalse(os.path.exists(seen["d"]))
        self.assertNotIn(_writeguard._norm(seen["d"]), _writeguard.roots())
        with open(os.path.join(TESTS, "_writeguard.py"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("def new_root"):src.index("def release_root")]
        self.assertLess(body.index("_roots.append"), body.index("os.mkdir"))      # register, then create
        body = src[src.index("def release_root"):src.index("def _unregister")]
        self.assertLess(body.index("rmtree"), body.index("_unregister"))          # delete, then unregister
        for f in os.listdir(TESTS):
            if f.endswith(".py") and f != "test_writeguard.py":
                with open(os.path.join(TESTS, f), encoding="utf-8") as fh:
                    self.assertNotIn("mkdtemp(", fh.read(), f)

    def test_undeletable_root_fails(self):  # patch WG11 / WG13 (3)
        outer = _util.tmpdir(self)
        d = os.path.join(outer, "stuck")
        os.mkdir(d)
        with mock.patch.object(_writeguard.shutil, "rmtree"), mock.patch("time.sleep"):   # rmtree "fails"
            with self.assertRaises(AssertionError) as cm:
                _writeguard.release_root(d)
        self.assertEqual(str(cm.exception).splitlines()[0], f"暫存根目錄刪不掉（有檔案還開著？）：{d}")
        self.assertNotIn(_writeguard._norm(d), _writeguard.roots())

    def test_protected_folders(self):  # G7
        if sys.platform == "win32":
            data = os.path.join(os.environ.get("LOCALAPPDATA"), "darkroom")
        else:
            from darkroom_app.domain import settings
            data = settings.default_data_dir(os.environ, sys.platform)
        self.assertEqual(_writeguard.protected_folders(),
                         [_util.PHOTOS, os.path.dirname(os.path.abspath(_util.preset_dir())), data])
        snap = _writeguard.arm_snapshot()
        lib = snap[os.path.dirname(os.path.abspath(_util.preset_dir()))]
        self.assertEqual(sum(1 for k in lib if k.lower().endswith(".xmp") and os.path.dirname(k) == "xmp"),
                         _util.LIBRARY_SIZE)
        self.assertTrue(snap[_util.PHOTOS])

    def test_protect_fixture(self):  # G7: a fixture-protected synthetic photo folder
        d = os.path.join(_util.tmpdir(self), "photos")
        os.makedirs(d)
        with open(os.path.join(d, "a.jpg"), "wb") as f:
            f.write(b"jpeg")

        class Inner(unittest.TestCase):
            def test_touch(self):
                _writeguard.protect(self, d)
                with open(os.path.join(d, "a.jpg"), "ab") as f:
                    f.write(b"!")
                os.makedirs(os.path.join(d, "new"))

            def test_clean(self):
                _writeguard.protect(self, d)

        result = unittest.TestResult()
        Inner("test_touch").run(result)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("受保護資料夾內容改變：" + os.path.join(d, "a.jpg") + "、" + os.path.join(d, "new"),
                      result.failures[0][1])
        result = unittest.TestResult()
        Inner("test_clean").run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(_writeguard.snapshot_diff({d: None}, {d: {}}), [d])


class TestSafeWrite(unittest.TestCase):  # G8
    def setUp(self):
        self.other = _util.tmpdir(self)     # released after root: root holds a junction into it
        self.root = _util.tmpdir(self)

    def refused(self, sentence, fn, *args, **kw):
        with self.assertRaises(safe_write.SafeWriteRefused) as cm:
            fn(*args, **kw)
        self.assertEqual(str(cm.exception), sentence)

    def test_public_surface(self):
        import inspect
        funcs = sorted(n for n, v in vars(safe_write).items() if inspect.isfunction(v) and not n.startswith("_")
                       and n != "configured_preset_dir")   # v2: the composition's hook (a value, not an API)
        self.assertEqual(funcs, ["create_new", "make_dirs", "open_lock", "remove", "replace_into"])
        self.assertEqual(safe_write.REFUSED_NO_PRESET, "refused: no preset folder is known, cannot protect it")  # XP12
        for n in funcs:      # CONTRACT-export XP12: every function takes the preset folder in use, keyword only
            self.assertIs(inspect.signature(getattr(safe_write, n)).parameters["preset_dir"].kind,
                          inspect.Parameter.KEYWORD_ONLY, n)
        self.assertTrue(issubclass(safe_write.SafeWriteRefused, Exception))
        self.assertFalse(issubclass(safe_write.SafeWriteRefused, OSError))
        self.assertEqual(" ｜ ".join([safe_write.REFUSED_OUTSIDE, safe_write.REFUSED_PRESET, safe_write.REFUSED_PROTECTED,
                                      safe_write.REFUSED_NOT_OURS, safe_write.REFUSED_ROOT]),
                         "refused: {path} is outside {root} ｜ refused: {path} is inside the preset folder ｜ "
                         "refused: {path} is a photo or preset file ｜ refused: {tmp} was not created by safe_write ｜ "
                         "refused: root {root} is not an existing absolute folder")

    def test_safe_write_refusals(self):
        root = self.root
        p = os.path.join(self.other, "x.bin")
        self.refused(f"refused: {p} is outside {root}", safe_write.create_new, p, root, b"x")       # root outside
        p = os.path.join(root, "..", "x.bin")
        self.refused(f"refused: {p} is outside {root}", safe_write.create_new, p, root, b"x")       # .. escape
        j = os.path.join(root, "jx")
        if WINDOWS:
            import _winapi
            _winapi.CreateJunction(self.other, j)                                # junction pointing out of root
        else:
            os.symlink(self.other, j)                                            # POSIX: a symlink does the same
        p = os.path.join(j, "x.bin")
        self.refused(f"refused: {p} is outside {root}", safe_write.create_new, p, root, b"x")
        jd = os.path.join(j, "d")
        self.refused(f"refused: {jd} is outside {root}", safe_write.make_dirs, jd, root)
        self.assertEqual(os.listdir(self.other), [])
        presets = os.path.join(root, "presets")
        os.makedirs(presets)
        with mock.patch.object(safe_write, "configured_preset_dir", lambda: presets):
            p = os.path.join(presets, "new.xmp")
            self.refused(f"refused: {p} is inside the preset folder", safe_write.create_new, p, root, b"x")
            p = os.path.join(presets, "sub")
            self.refused(f"refused: {p} is inside the preset folder", safe_write.make_dirs, p, root)
        # CONTRACT-export XP12 (WG10 (b)): the preset folder in use is passed in while config points elsewhere
        in_use = os.path.join(root, "in-use-presets")
        os.makedirs(in_use)
        with mock.patch.object(safe_write, "configured_preset_dir", lambda: presets):
            for fn, args in ((safe_write.create_new, (b"x",)), (safe_write.make_dirs, ())):
                p = os.path.join(in_use, "new.bin")
                self.refused(f"refused: {p} is inside the preset folder", fn, p, root, *args, preset_dir=in_use)
                p = os.path.join(presets, "new.bin")            # the configured one stays protected as well
                self.refused(f"refused: {p} is inside the preset folder", fn, p, root, *args, preset_dir=in_use)
            p = os.path.join(in_use, "x.lock")
            self.refused(f"refused: {p} is inside the preset folder", safe_write.open_lock, p, root, preset_dir=in_use)
        self.assertEqual(os.listdir(in_use), [])
        # nothing passed and no configuration -> SafeWriteRefused, not ConfigError
        with mock.patch.object(safe_write, "configured_preset_dir", None):
            self.refused("refused: no preset folder is known, cannot protect it", safe_write.create_new,
                         os.path.join(root, "z.bin"), root, b"x")
            self.refused("refused: no preset folder is known, cannot protect it", safe_write.make_dirs,
                         os.path.join(root, "zd"), root)
            p = os.path.join(in_use, "y.bin")
            self.refused(f"refused: {p} is inside the preset folder", safe_write.create_new, p, root, b"x",
                         preset_dir=in_use)
            made = safe_write.create_new(os.path.join(root, "z.bin"), root, b"x", preset_dir=in_use)
            self.assertTrue(os.path.isfile(made))
        self.assertFalse(os.path.exists(os.path.join(root, "zd")))
        self.assertEqual(os.listdir(in_use), [])
        tmp =safe_write.create_new(os.path.join(root, "t1.tmp"), root, b"t")
        for ext in (".jpg", ".JPEG", ".png", ".tif", ".tiff", ".heic", ".HEIF", ".xmp"):
            dest = os.path.join(root, "dest" + ext)
            self.refused(f"refused: {dest} is a photo or preset file", safe_write.replace_into, tmp, dest, root)
            self.refused(f"refused: {dest} is a photo or preset file", safe_write.remove, dest, root)
        mine = os.path.join(root, "plain.tmp")
        with open(mine, "wb") as f:
            f.write(b"not safe_write")
        self.refused(f"refused: {mine} was not created by safe_write", safe_write.replace_into, mine,
                     os.path.join(root, "library.json"), root)
        for bad in (os.path.join(root, "missing"), "relative", os.path.join(root, "t1.tmp")):
            self.refused(f"refused: root {bad} is not an existing absolute folder", safe_write.create_new,
                         os.path.join(root, "y.bin"), bad, b"x")
        self.refused(f"refused: {os.path.join(root, 'x.lck')} is not a .lock file", safe_write.open_lock,
                     os.path.join(root, "x.lck"), root)
        with self.assertRaises(FileExistsError):                                 # already exists
            safe_write.create_new(tmp, root, b"again")
        with self.assertRaises(TypeError):
            safe_write.create_new(os.path.join(root, "f.bin"), root, lambda path: None)
        self.assertFalse(os.path.exists(os.path.join(root, "f.bin")))

    def test_safe_write_never_overwrites(self):
        root = self.root
        p = os.path.join(root, "out.jpg")
        safe_write.create_new(p, root, b"first")
        with self.assertRaises(FileExistsError):
            safe_write.create_new(p, root, b"second")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"first")
        half = os.path.join(root, "half.jpg")
        with mock.patch.object(safe_write.os, "write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                safe_write.create_new(half, root, b"data")
        self.assertFalse(os.path.exists(half))                                   # no half file left behind
        d = safe_write.make_dirs(os.path.join(root, "a", "b"), root)
        self.assertTrue(os.path.isdir(d))
        tmp = safe_write.create_new(os.path.join(d, "library.json.tmp"), root, b'{"v":2}')
        dest = os.path.join(d, "library.json")
        with open(dest, "wb") as f:
            f.write(b'{"v":1}')
        safe_write.replace_into(tmp, dest, root)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b'{"v":2}')
        self.refused(f"refused: {tmp} was not created by safe_write", safe_write.replace_into, tmp, dest, root)
        lock = os.path.join(root, "library.lock")
        with open(lock, "wb") as f:
            f.write(b"held")
        fd = safe_write.open_lock(lock, root)
        os.close(fd)
        with open(lock, "rb") as f:
            self.assertEqual(f.read(), b"held")                                  # never truncated
        safe_write.remove(dest, root)
        self.assertFalse(os.path.exists(dest))


if __name__ == "__main__":
    unittest.main()
