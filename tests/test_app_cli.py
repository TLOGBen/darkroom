"""CONTRACT-layering L9: the agent CLI `python -s -m darkroom_app.cli` (envelope, exit codes, TTY, light imports)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import _util
from test_app_server import make_presets, write_photo

TTY_REFUSAL = "預覽是 JPEG 位元組，請導向檔案（> out.jpg）或加 --json"   # verbatim
UNEXPECTED = "未預期錯誤：{type_name}：{detail}"                          # verbatim
CONFIG_ERROR = "darkroom：{e}"                                            # verbatim


def run_cli(*args, cwd=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([*_util.guarded_python(), "-m", "darkroom_app.cli", *args], cwd=cwd or _util.REPO,
                       capture_output=True, env=env, timeout=300)
    return r.returncode, r.stdout, r.stderr.decode("utf-8")


def call(argv, facade=None):
    """main() in this process -> (exit code, stdout text, stderr text)."""
    from darkroom_app import cli
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cli.main(argv, facade=facade)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = _util.tmpdir(self)
        d = os.path.join(self.tmp, "presets")
        os.makedirs(d)
        self.presets = make_presets(d)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.photo = write_photo(os.path.join(self.photos, "a.png"), 640, 400)


class TestCliEnvelope(CliCase):
    def test_cli_json_envelope(self):
        cases = ((["presets", "list", "--limit", "2"], 0, True),
                 (["presets", "show", "p-expo"], 0, True),
                 (["presets", "flags"], 0, True),
                 (["sliders"], 0, True),
                 (["open", self.photo], 0, True),
                 (["folder", self.photo], 0, True),
                 (["preview", self.photo, "--preset", "p-expo", "--max-pixels", "65536"], 0, True),
                 (["presets", "show", "nope"], 3, False),
                 (["presets", "list", "--limit", "0"], 2, False),
                 (["open", os.path.join(self.photos, "missing.jpg")], 3, False),
                 (["preview", self.photo, "--strength", "250"], 2, False))
        for args, code, ok in cases:
            rc, out, err = run_cli("--preset-dir", self.presets, *args, "--json")
            self.assertEqual(rc, code, (args, err))
            self.assertEqual(err, "", args)
            text = out.decode("utf-8")
            self.assertTrue(text.endswith("\n") and text.count("\n") == 1 and "\r" not in text, (args, text[:200]))
            env = json.loads(text)
            self.assertEqual(env["ok"], ok, args)
            if ok:
                self.assertEqual(list(env), ["ok", "result"])
            else:
                self.assertEqual(list(env), ["ok", "error"])
                self.assertEqual(list(env["error"]), ["kind", "message"])
                self.assertEqual(env["error"]["kind"], "not_found" if code == 3 else "invalid")
        rc, out, _ = run_cli("--preset-dir", self.presets, "preview", self.photo, "--max-pixels", "65536", "--json")
        res = json.loads(out)["result"]
        self.assertEqual(list(res), ["render_ms", "width", "height", "jpeg_base64"])
        self.assertLessEqual(res["width"] * res["height"], 65536)
        self.assertEqual(json.loads(run_cli("--preset-dir", self.presets, "presets", "show", "nope", "--json")[1]),
                         {"ok": False, "error": {"kind": "not_found", "message": "unknown preset nope"}})

    def test_cli_plain_failure_is_one_stderr_line(self):
        rc, out, err = run_cli("--preset-dir", self.presets, "presets", "show", "nope")
        self.assertEqual((rc, out, err), (3, b"", "unknown preset nope\n"))
        rc, out, err = run_cli("--preset-dir", self.presets, "preview", self.photo, "--override", "Bogus=1")
        self.assertEqual((rc, out, err), (2, b"", "unknown slider key 'Bogus'\n"))
        rc, out, err = run_cli("--preset-dir", self.presets, "preview", self.photo, "--override", "Exposure2012=x")
        self.assertEqual((rc, out, err), (2, b"", "override for Exposure2012 must be a finite number\n"))

    def test_cli_preview_writes_jpeg_bytes(self):
        rc, out, err = run_cli("--preset-dir", self.presets, "preview", self.photo, "--preset", "p-expo",
                               "--strength", "50", "--override", "Exposure2012=0.3")
        self.assertEqual(rc, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(out[:2], b"\xff\xd8")
        self.assertEqual(out[-2:], b"\xff\xd9")


class TestCliExitCodes(CliCase):
    def test_cli_exit_codes(self):
        from darkroom_app.composition import build_facade
        f = build_facade(self.presets)
        self.assertEqual(call(["presets", "list"], f)[0], 0)
        self.assertEqual(call(["presets", "list", "--offset", "-1"], f)[:3],
                         (2, "", "offset must be an integer >= 0\n"))
        self.assertEqual(call(["presets", "show", "nope"], f), (3, "", "unknown preset nope\n"))
        rc, out, err = call(["presets", "list", "--limit", "x"], f)      # argparse usage error
        self.assertEqual((rc, out), (2, ""))
        self.assertTrue(err)
        self.assertEqual(call(["bogus"], f)[0], 2)

    def test_cli_usage_error_one_line(self):
        # L9 (S2 folded in): a usage error is exactly one stderr line and empty stdout, with or without --json
        from darkroom_app.composition import build_facade
        f = build_facade(self.presets)
        for argv in (["presets", "list", "--limit", "x"], ["presets", "list", "--limit", "x", "--json"],
                     ["bogus"], ["bogus", "--json"], ["preview"], ["preview", "--json"], []):
            rc, out, err = call(argv, f)
            self.assertEqual((rc, out), (2, ""), argv)
            self.assertTrue(err.endswith("\n"), (argv, err))
            self.assertEqual(err.count("\n"), 1, (argv, err))
            self.assertIn("error:", err, argv)

    def test_cli_unexpected_error(self):
        from darkroom_app.composition import build_facade
        f = build_facade(self.presets)
        with mock.patch.object(f, "list_presets", side_effect=RuntimeError("line one\nline two\r\nthree")):
            for extra in ([], ["--json"]):
                rc, out, err = call(["presets", "list", *extra], f)
                self.assertEqual((rc, out), (1, ""), extra)
                self.assertEqual(err, UNEXPECTED.format(type_name="RuntimeError", detail="line one line two three")
                                 + "\n")

    def test_cli_config_error(self):
        from darkroom_app import config
        with mock.patch.object(config, "preset_dir", side_effect=config.ConfigError("no preset folder")):
            rc, out, err = call(["presets", "list"])
        self.assertEqual((rc, out, err), (2, "", CONFIG_ERROR.format(e="no preset folder") + "\n"))

    def test_cli_missing_preset_folder(self):  # seal patch S5: same sentence form as ConfigError
        missing = os.path.join(self.tmp, "no-such-presets")
        for extra in ([], ["--json"]):
            rc, out, err = call(["--preset-dir", missing, "sliders", *extra])
            self.assertEqual((rc, out, err),
                             (2, "", CONFIG_ERROR.format(e=f"preset folder not found: {missing}") + "\n"), extra)

    def test_cli_preview_refuses_tty(self):
        from darkroom_app.composition import build_facade
        f = build_facade(self.presets)
        out, err = io.StringIO(), io.StringIO()
        out.isatty = lambda: True
        from darkroom_app import cli
        with mock.patch.object(f, "open_photo") as opened, contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            rc = cli.main(["preview", self.photo], facade=f)
        self.assertEqual((rc, out.getvalue(), err.getvalue()), (2, "", TTY_REFUSAL + "\n"))
        opened.assert_not_called()


class TestCliLightImports(CliCase):
    def test_presets_and_sliders_never_import_torch_or_cv2(self):
        code = ("import sys, contextlib, io\n"
                "from darkroom_app import cli\n"
                "for argv in (['presets','list'], ['presets','show','p-expo'], ['presets','flags'], ['sliders'],\n"
                "             ['presets','groups'], ['presets','favorite','p-expo','on'], ['presets','rename','p-expo','X'],\n"
                "             ['presets','save','--name','s','--preset','p-expo'], ['groups','create','G'],\n"
                "             ['presets','rebuild'],\n"   # KP11: the library commands that write stay torch-free
                "             ['edit','get',sys.argv[2]], ['edit','set',sys.argv[2],'--preset','p-expo'],\n"
                "             ['edit','paste','--from',sys.argv[2],sys.argv[2]], ['edit','clear',sys.argv[2]],\n"
                "             ['edit','set',sys.argv[2],'--preset','p-expo'],\n"
                "             ['edit','save-preset',sys.argv[2],'--name','e'], ['thumbnails',sys.argv[3]]):\n"  # PLP8
                "    with contextlib.redirect_stdout(io.StringIO()):\n"
                "        assert cli.main(['--preset-dir', sys.argv[1], '--data-dir', sys.argv[4], *argv, '--json']) == 0, argv\n"
                "print(sorted(m for m in ('torch', 'cv2') if m in sys.modules))\n"
                "with contextlib.redirect_stdout(io.StringIO()):\n"
                "    assert cli.main(['--preset-dir', sys.argv[1], '--data-dir', sys.argv[4], 'thumbnail', sys.argv[2], '--json']) == 0\n"
                "print(sorted(m for m in ('torch',) if m in sys.modules))\n")
        data_dir = os.path.join(self.tmp, "data")
        r = subprocess.run([*_util.guarded_python(), "-c", code, self.presets, self.photo, self.photos, data_dir],
                           cwd=_util.REPO, capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertEqual(r.stdout.decode().split(), ["[]", "[]"])


if __name__ == "__main__":
    unittest.main()
