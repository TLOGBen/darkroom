"""App shell launch: B2 (localhost only, port, ready line, start.ps1, shortcut, no hard-coded user paths)."""
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

import _util
import _xmpgen

READY_LINE = "darkroom 已啟動：http://127.0.0.1:{port}/"   # verbatim (contract)
DEFAULT_PORT = 8765                                        # verbatim (contract)
PWSH = shutil.which("pwsh")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def small_presets(testcase):
    d = os.path.join(_util.tmpdir(testcase), "presets")
    os.makedirs(d)
    _xmpgen.write(d, "a.xmp", _xmpgen.xmp_text({"Exposure2012": "+0.50"}, name="A", group="X - Y"))
    return d


def kill_tree(proc):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    if proc.stdout:
        proc.stdout.close()


def wait_line(proc, timeout=180):
    """First stdout line containing 'darkroom', read without blocking past the timeout."""
    import threading
    box = []

    def reader():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if "darkroom" in line:
                box.append(line)
                return
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout)
    return box[0] if box else None


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


class TestBinding(unittest.TestCase):
    def test_server_binds_localhost(self):
        from darkroom_app import server
        self.assertEqual(server.HOST, "127.0.0.1")
        self.assertEqual(server.DEFAULT_PORT, DEFAULT_PORT)
        self.assertEqual(server.READY_LINE, READY_LINE)
        d = small_presets(self)

        async def go():
            runner, port = await server.start(d, port=0, warm_up=False)
            try:
                addrs = runner.addresses
                self.assertTrue(addrs)
                for a in addrs:
                    self.assertEqual(a[0], "127.0.0.1", addrs)
                self.assertEqual(addrs[0][1], port)
            finally:
                await runner.cleanup()
        asyncio.run(go())

    def test_no_host_option_and_no_wildcard_bind(self):
        app = os.path.join(_util.REPO, "darkroom_app")
        for f in os.listdir(app):
            if f.endswith(".py"):
                with open(os.path.join(app, f), encoding="utf-8") as fh:
                    src = fh.read()
                self.assertNotIn("0.0.0.0", src, f)
                self.assertNotIn("--host", src, f)


class TestModuleLaunch(unittest.TestCase):
    def test_module_prints_ready_line_and_serves(self):
        d = small_presets(self)
        port = free_port()
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        p = subprocess.Popen([*_util.guarded_python(), "-m", "darkroom_app", "--port", str(port), "--preset-dir", d],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=os.path.dirname(d))
        try:
            line = wait_line(p)
            self.assertEqual(line, READY_LINE.format(port=port))
            status, body = get(f"http://127.0.0.1:{port}/api/presets")
            self.assertEqual(status, 200)
            self.assertEqual([r["name"] for r in json.loads(body)], ["A"])
            status, body = get(f"http://127.0.0.1:{port}/")
            self.assertIn(b'id="preset-tree"', body)
        finally:
            kill_tree(p)


@unittest.skipUnless(PWSH, "needs pwsh")
class TestScripts(unittest.TestCase):
    def test_start_ps1_runs_server_on_given_port(self):
        port = free_port()
        script = os.path.join(_util.REPO, "tools", "start.ps1")
        p = subprocess.Popen([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Port", str(port),
                              "-NoBrowser"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            line = wait_line(p)
            self.assertEqual(line, READY_LINE.format(port=port))
            deadline = time.time() + 30
            status = None
            while time.time() < deadline:
                try:
                    status, _ = get(f"http://127.0.0.1:{port}/api/health")
                    break
                except OSError:
                    time.sleep(0.3)
            self.assertEqual(status, 200)
        finally:
            kill_tree(p)

    def test_start_ps1_defaults(self):
        with open(os.path.join(_util.REPO, "tools", "start.ps1"), encoding="utf-8") as f:
            src = f.read()
        self.assertRegex(src, r"\[int\]\$Port\s*=\s*8765")
        self.assertIn("LOCALLLMS_ROOT", src)
        self.assertIn("config.local.json", src)
        self.assertIn("http://127.0.0.1:", src)
        self.assertIn("'-s'", src)

    def test_make_shortcut_to_given_folder(self):
        dest = _util.tmpdir(self)
        script = os.path.join(_util.REPO, "tools", "make-shortcut.ps1")
        r = subprocess.run([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Destination", dest],
                           capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        lnk = os.path.join(dest, "darkroom.lnk")
        self.assertTrue(os.path.exists(lnk))
        q = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $s.TargetPath; $s.Arguments" % lnk)
        out = subprocess.run([PWSH, "-NoProfile", "-Command", q], capture_output=True).stdout.decode("utf-8")
        target, args = out.splitlines()[:2]
        self.assertTrue(target.lower().endswith("pwsh.exe"), target)
        self.assertIn(os.path.join(_util.REPO, "tools", "start.ps1"), args)


class TestConfig(unittest.TestCase):
    def test_config_resolution(self):
        from darkroom_app import config
        d = _util.tmpdir(self)
        cfg = os.path.join(d, "config.local.json")
        self.assertEqual(config.load(cfg, env={}), {"localllms_root": None, "preset_dir": None})
        with self.assertRaises(config.ConfigError):
            config.preset_dir(cfg, env={})
        self.assertEqual(config.preset_dir(cfg, env={"LOCALLLMS_ROOT": "R"}), os.path.join("R", "artifact", "11_preset", "xmp"))
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"localllms_root": "Q"}, f)
        self.assertEqual(config.preset_dir(cfg, env={}), os.path.join("Q", "artifact", "11_preset", "xmp"))
        self.assertEqual(config.preset_dir(cfg, env={"LOCALLLMS_ROOT": "R"}), os.path.join("R", "artifact", "11_preset", "xmp"))
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"localllms_root": "Q", "preset_dir": "P"}, f)
        self.assertEqual(config.preset_dir(cfg, env={}), "P")

    def test_gitignore(self):
        with open(os.path.join(_util.REPO, ".gitignore"), encoding="utf-8") as f:
            lines = f.read().split()
        self.assertIn("config.local.json", lines)
        self.assertIn("*.lnk", lines)

    def test_no_hardcoded_user_paths(self):
        bad = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]", re.I)
        offenders = []
        for top in ("darkroom_app", "tools", "tests", "darkroom"):
            for root, _, files in os.walk(os.path.join(_util.REPO, top)):
                for f in files:
                    if f.endswith((".py", ".ps1", ".js", ".html", ".css")):
                        p = os.path.join(root, f)
                        with open(p, encoding="utf-8") as fh:
                            if bad.search(fh.read()):
                                offenders.append(os.path.relpath(p, _util.REPO))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
