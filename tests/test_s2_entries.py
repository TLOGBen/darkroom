"""CONTRACT-s2-export-detect E22-E28: capability detection and the three entries of the six new operations.

Detection is always injected where it could start a subprocess: no test runs `op` (WG15 / WG16) and none calls the
Anthropic API. Every facade gets a temporary data_dir and a synthetic preset copy (G7).
"""
import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from aiohttp.test_utils import AioHTTPTestCase

import _util
from _fakes import FakeDarkroom
from test_app_server import make_presets, snapshot, write_photo

FEATURES = ["gpu", "heic", "webp", "photo_library", "preset_library_writes", "semantic_index", "onepassword"]  # E22
NO_GPU = "沒有偵測到可用的 NVIDIA 顯示卡（CUDA），預覽與匯出改用 CPU，會慢很多"                     # verbatim (E23)
NO_WEBP = "這台電腦的 OpenCV 不能寫 WebP，WebP 匯出先關閉"                                        # verbatim (E23)
OP_NOT_SIGNED_IN = "1Password 尚未登入（請解鎖 1Password App 或執行 op signin）"                    # verbatim (E24)
OP_NO_OP = "找不到 op（1Password CLI）"                                                            # verbatim (SI3)
OP_TIMEOUT = "1Password 尚未登入或還在等解鎖（op whoami 逾時）"                                   # verbatim (E24)
OP_NOT_USED = "沒有用到 1Password（config.local.json 沒有 anthropic_api_key_ref）"                 # verbatim (E24)
LIB_IN_PHOTOS = ("preset 庫的位置 {root} 在照片資料夾裡（{photo_folder} 有照片），為了不在照片資料夾裡寫檔，整理 preset、"
                 "匯入、存成 preset 先關閉；請在 config.local.json 把 preset_library_dir 設到別的資料夾")   # verbatim (E23)
PL_INSIDE = "照片庫資料區不能在照片或 preset 資料夾底下：{data_dir}"                                 # verbatim (PLP1)
PL_PARENT = "無法寫入照片庫：{data_dir}：上層資料夾不存在：{parent}"                                 # verbatim (PLP17)
DATA_DIR_ERROR = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在"   # verbatim (PL1)
KEY_FAILED = "無法取得 Anthropic 金鑰：{reason}"                                                    # verbatim (SI3)
PRESET_EXPORT_REFUSED = ("preset export to a folder is not accepted over HTTP (use the CLI or MCP; the page "
                         "downloads the files)")                                                    # verbatim (E17)
DATA_DIR_REFUSED = "data_dir is not accepted over HTTP (it is configured)"                         # verbatim (PLP2)
DEST_DIR_REFUSED = "dest_dir is not accepted over HTTP (use the CLI or MCP)"                       # verbatim (XP16)
SECRET = "sk-ant-TESTSECRET-whoami-must-not-leak"
REF = "op://Personal/ClaudeAPIKey/credential"
S2_ANNOTATIONS = {   # verbatim (操作表)
    "darkroom_export_presets_list": {"readOnlyHint": True, "openWorldHint": False},
    "darkroom_export_preset_save": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                                    "openWorldHint": False},
    "darkroom_export_preset_delete": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                                      "openWorldHint": False},
    "darkroom_preset_files": {"readOnlyHint": True, "openWorldHint": False},
    "darkroom_presets_export": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                                "openWorldHint": False},
    "darkroom_capabilities": {"readOnlyHint": True, "openWorldHint": False}}


def no_op():
    """The two items that could reach `op`, always injected (tests never run op)."""
    return {"semantic_index": lambda: (False, "假的語意索引"), "onepassword": lambda: (False, "假的 1Password")}


def all_fake(off=()):
    return {n: ((lambda n=n: (False, f"{n} 關閉")) if n in off else (lambda: (True, None))) for n in FEATURES}


class _NoEngine:
    images = {}

    def shutdown(self):
        pass


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = _util.tmpdir(self)
        self.pd = os.path.join(self.tmp, "lib", "xmp")
        os.makedirs(self.pd)
        make_presets(self.pd)
        self.data = os.path.join(self.tmp, "data")
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)

    def facade(self, **kw):
        from darkroom_app.composition import build_facade
        kw.setdefault("data_dir", self.data)
        return build_facade(self.pd, **kw)


# ---------------------------------------------------------------------- E22
class TestCapabilities(Fixture):
    def test_capabilities_shape_and_cache(self):  # E22
        counts = dict.fromkeys(FEATURES, 0)

        def det(name, ok):
            def f():
                counts[name] += 1
                return (True, "ignored when available") if ok else (False, f"{name} 關閉")
            return f
        detect = {n: det(n, n not in ("webp", "onepassword")) for n in FEATURES}
        f = self.facade(detect=detect)
        res = f.capabilities()
        self.assertEqual(list(res), ["features"])
        self.assertEqual(list(res["features"]), FEATURES)
        for n, v in res["features"].items():
            self.assertEqual(list(v), ["available", "reason"], n)
            if n in ("webp", "onepassword"):
                self.assertEqual(v, {"available": False, "reason": f"{n} 關閉"})
            else:
                self.assertEqual(v, {"available": True, "reason": None})        # available -> reason null
        self.assertEqual(counts, dict.fromkeys(FEATURES, 1))
        self.assertEqual(f.capabilities(), res)
        self.assertEqual(f.capabilities(False), res)
        self.assertEqual(counts, dict.fromkeys(FEATURES, 1))                    # kept for the process
        self.assertEqual(f.capabilities(refresh=True), res)
        self.assertEqual(counts, dict.fromkeys(FEATURES, 2))                    # refresh measures again
        with self.assertRaises(ValueError):
            self.facade(detect={"bogus": lambda: (True, None)})

    def test_capabilities_never_write(self):  # E22: the real detectors (except the two that could reach op)
        photo = write_photo(os.path.join(self.photos, "a.jpg"), 64, 48)
        before = snapshot(self.tmp)
        names = sorted(os.listdir(self.tmp))
        f = self.facade(detect=no_op())
        res = f.capabilities()
        f.capabilities(refresh=True)
        self.assertEqual(list(res["features"]), FEATURES)
        self.assertEqual(res["features"]["photo_library"], {"available": True, "reason": None})
        self.assertEqual(res["features"]["preset_library_writes"], {"available": True, "reason": None})
        self.assertEqual(snapshot(self.tmp), before)
        self.assertEqual(sorted(os.listdir(self.tmp)), names)
        self.assertFalse(os.path.exists(self.data))
        self.assertTrue(os.path.exists(photo))


class TestReadyLine(unittest.IsolatedAsyncioTestCase):
    async def test_app_ready_line_not_delayed_by_detection(self):  # E22 / IP6
        from darkroom_app import server
        from darkroom_app.services.capabilities import WARM_UP
        tmp = _util.tmpdir(self)
        pd = os.path.join(tmp, "p")
        os.makedirs(pd)
        make_presets(pd)
        gate, calls, lock = threading.Event(), [], threading.Lock()

        def slow(name):
            def f():
                with lock:
                    calls.append(name)
                gate.wait(10)                    # a detector that takes as long as it takes
                return True, None
            return f
        self.addCleanup(gate.set)
        t0 = time.monotonic()
        runner, port = await server.start(pd, port=0, engine=_NoEngine(), warm_up=False,
                                          data_dir=os.path.join(tmp, "data"),
                                          detect={n: slow(n) for n in FEATURES})
        elapsed = time.monotonic() - t0
        try:
            self.assertLess(elapsed, 1.0)        # the ready line follows start() right away
            self.assertGreater(port, 0)
            gate.set()
            deadline = time.monotonic() + 10
            while len(calls) < len(WARM_UP) and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.1)
            self.assertEqual(sorted(calls), sorted(WARM_UP))   # background warm-up: never op (no onepassword)
            self.assertNotIn("onepassword", calls)
            self.assertNotIn("semantic_index", calls)
        finally:
            await runner.cleanup()


# ---------------------------------------------------------------------- E23
class TestCapabilityRules(Fixture):
    def feature(self, f, name):
        return f.capabilities(refresh=True)["features"][name]

    def test_capability_rules(self):  # E23: every item, available and not, the sentences verbatim
        import darkroom._heif
        from darkroom_app import messages as M
        from darkroom_app.services import capabilities as C
        self.assertEqual(M.CAP_NO_GPU, NO_GPU)
        self.assertEqual(M.CAP_NO_WEBP, NO_WEBP)
        self.assertEqual(M.CAP_NO_HEIC, darkroom._heif.MISSING)
        # gpu
        import torch
        with mock.patch.object(torch.cuda, "is_available", return_value=False):
            self.assertEqual(C.detect_gpu(), (False, NO_GPU))
        with mock.patch.object(torch.cuda, "is_available", return_value=True):
            self.assertEqual(C.detect_gpu(), (True, None))
        # heic
        self.assertEqual(C.detect_heic(), (True, None))
        with mock.patch.dict(sys.modules, {"pillow_heif": None}):
            self.assertEqual(C.detect_heic(), (False, darkroom._heif.MISSING))
        # webp
        import cv2
        self.assertEqual(C.detect_webp(), (True, None))
        with mock.patch.object(cv2, "haveImageWriter", return_value=False):
            self.assertEqual(C.detect_webp(), (False, NO_WEBP))
        # through the facade: the default detectors give the same words
        f = self.facade(detect=no_op())
        with mock.patch.object(torch.cuda, "is_available", return_value=False):
            self.assertEqual(self.feature(f, "gpu"), {"available": False, "reason": NO_GPU})
        with mock.patch.object(cv2, "haveImageWriter", return_value=False):
            self.assertEqual(self.feature(f, "webp"), {"available": False, "reason": NO_WEBP})
        with mock.patch.dict(sys.modules, {"pillow_heif": None}):
            self.assertEqual(self.feature(f, "heic"), {"available": False, "reason": darkroom._heif.MISSING})
        # photo_library: fine / configuration names none / parent missing / inside the preset folder
        self.assertEqual(self.feature(f, "photo_library"), {"available": True, "reason": None})
        from darkroom_app import config
        g = self.facade(detect=no_op(), data_dir=None)
        with mock.patch.object(config, "data_dir", side_effect=config.ConfigError(DATA_DIR_ERROR)):
            self.assertEqual(self.feature(g, "photo_library"), {"available": False, "reason": DATA_DIR_ERROR})
        parent = os.path.join(self.tmp, "no-such-parent")
        bad = os.path.join(parent, "darkroom")
        g = self.facade(detect=no_op(), data_dir=bad)
        self.assertEqual(self.feature(g, "photo_library"),
                         {"available": False, "reason": PL_PARENT.format(data_dir=bad, parent=parent)})
        inside = os.path.join(self.pd, "data")
        g = self.facade(detect=no_op(), data_dir=inside)
        self.assertEqual(self.feature(g, "photo_library"),
                         {"available": False, "reason": PL_INSIDE.format(data_dir=inside)})
        self.assertFalse(os.path.exists(inside))
        # preset_library_writes: the library root, or a folder above it, holds a photo
        self.assertEqual(self.feature(f, "preset_library_writes"), {"available": True, "reason": None})
        root = os.path.join(self.tmp, "lib")
        write_photo(os.path.join(self.tmp, "on-top.jpg"), 8, 8)
        self.assertEqual(self.feature(f, "preset_library_writes"),
                         {"available": False, "reason": LIB_IN_PHOTOS.format(root=root, photo_folder=self.tmp)})
        write_photo(os.path.join(root, "in-root.png"), 8, 8)
        self.assertEqual(self.feature(f, "preset_library_writes"),
                         {"available": False, "reason": LIB_IN_PHOTOS.format(root=root, photo_folder=root)})
        os.remove(os.path.join(root, "in-root.png"))
        os.remove(os.path.join(self.tmp, "on-top.jpg"))
        self.assertEqual(self.feature(f, "preset_library_writes"), {"available": True, "reason": None})

    def test_semantic_and_onepassword_rules(self):  # E23 semantic_index / onepassword (fake op runner only)
        from darkroom_app import messages as M
        from darkroom_app.services import semantic_index as S
        from test_semantic_index import NEED_KEY, NEED_PACKAGE, make_sources
        src = make_sources(os.path.join(self.tmp, "sources"))
        runs = []

        def runner(rc):
            def run(argv, **kw):
                runs.append(argv)
                return SimpleNamespace(returncode=rc, stdout=SECRET.encode(), stderr=SECRET.encode())
            return run

        def sem(**kw):
            base = dict(key_ref=None, env_key=None, sources_dir=src, budget_usd=5.0, have_anthropic=lambda: True,
                        client_factory=lambda k: (_ for _ in ()).throw(AssertionError("no client")),
                        key_reader=lambda ref: (_ for _ in ()).throw(AssertionError("no key read")),
                        signin_check=lambda: (_ for _ in ()).throw(AssertionError("no op")))
            base.update(kw)
            return self.facade(semantic=base).capabilities()["features"]
        feats = sem(have_anthropic=lambda: False)
        self.assertEqual(feats["semantic_index"], {"available": False, "reason": NEED_PACKAGE})
        self.assertEqual(feats["onepassword"], {"available": False, "reason": OP_NOT_USED})   # no ref: op not run
        self.assertEqual(sem()["semantic_index"], {"available": False, "reason": NEED_KEY})
        feats = sem(env_key="k")
        self.assertEqual(feats["semantic_index"], {"available": True, "reason": None})
        self.assertEqual(feats["onepassword"], {"available": False, "reason": OP_NOT_USED})
        feats = sem(key_ref=REF, signin_check=lambda: S.op_signed_in(run=runner(0)))
        self.assertEqual(feats["semantic_index"], {"available": True, "reason": None})
        self.assertEqual(feats["onepassword"], {"available": True, "reason": None})
        feats = sem(key_ref=REF, signin_check=lambda: S.op_signed_in(run=runner(1)))
        self.assertEqual(feats["semantic_index"], {"available": False, "reason": OP_NOT_SIGNED_IN})
        self.assertEqual(feats["onepassword"], {"available": False, "reason": OP_NOT_SIGNED_IN})
        self.assertEqual(runs, [["op", "whoami"]] * 2)                 # measured once per facade, then cached
        self.assertEqual(M.OP_NOT_SIGNED_IN, OP_NOT_SIGNED_IN)
        self.assertEqual(M.OP_WHOAMI_TIMEOUT, OP_TIMEOUT)
        self.assertEqual(M.OP_NOT_USED, OP_NOT_USED)
        self.assertNotIn(SECRET, json.dumps(feats, ensure_ascii=False))


class TestPhotoLibraryUnavailable(AioHTTPTestCase):
    async def get_client(self, server):
        from aiohttp.test_utils import TestClient
        return TestClient(server, headers=_util.HTTP_HEADERS)

    async def get_application(self):
        from darkroom_app.server import make_app
        self.tmp = _util.tmpdir(self)
        self.pd = os.path.join(self.tmp, "p")
        os.makedirs(self.pd)
        make_presets(self.pd)
        self.photo = write_photo(os.path.join(self.tmp, "a.jpg"), 32, 24)
        return make_app(self.pd, engine=_NoEngine(), detect=no_op())      # data_dir from the (mocked) config

    async def test_photo_library_unavailable_is_503_not_500(self):  # E23 / PLP19
        from darkroom_app import cli, config
        from darkroom_app.composition import build_facade
        from darkroom_app.mcp_server import serve
        with mock.patch.object(config, "data_dir", side_effect=config.ConfigError(DATA_DIR_ERROR)):
            r = await self.client.get("/api/edit", params={"path": self.photo})
            self.assertEqual((r.status, await r.json()), (503, {"error": DATA_DIR_ERROR}))
            r = await self.client.put("/api/edit", json={"path": self.photo, "preset_id": "p-expo"})
            self.assertEqual((r.status, await r.json()), (503, {"error": DATA_DIR_ERROR}))
            r = await self.client.get("/api/export-presets")
            self.assertEqual((r.status, await r.json()), (503, {"error": DATA_DIR_ERROR}))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["--preset-dir", self.pd, "edit", "get", self.photo, "--json"])
            self.assertEqual((rc, err.getvalue()), (5, ""))
            self.assertEqual(json.loads(out.getvalue()),
                             {"ok": False, "error": {"kind": "unavailable", "message": DATA_DIR_ERROR}})
            f = build_facade(self.pd, detect=no_op())
            line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "darkroom_edit_get", "arguments": {"path": self.photo}}})
            o = io.BytesIO()
            serve(io.BytesIO(line.encode() + b"\n"), o, facade=f)
            res = json.loads(o.getvalue())["result"]
            self.assertIs(res["isError"], True)
            self.assertEqual(res["content"], [{"type": "text", "text": DATA_DIR_ERROR}])
            self.assertEqual(res["structuredContent"], {"kind": "unavailable", "message": DATA_DIR_ERROR})


# ---------------------------------------------------------------------- E24
class TestOnePassword(Fixture):
    def test_onepassword_detection(self):  # E24: a fake runner only; argv exactly op whoami, timeout 10
        from darkroom_app.services import semantic_index as S
        seen = []

        def make(result):
            def run(argv, **kw):
                seen.append((list(argv), kw))
                if isinstance(result, BaseException):
                    raise result
                return SimpleNamespace(returncode=result, stdout=SECRET.encode(), stderr=SECRET.encode())
            return run
        cases = [(0, (True, None)), (1, (False, OP_NOT_SIGNED_IN)), (6, (False, OP_NOT_SIGNED_IN)),
                 (FileNotFoundError(), (False, OP_NO_OP)),
                 (subprocess.TimeoutExpired(["op", "whoami"], 10, output=SECRET.encode()), (False, OP_TIMEOUT))]
        for result, want in cases:
            with self.subTest(result=result):
                got = S.op_signed_in(run=make(result))
                self.assertEqual(got, want)
                self.assertNotIn(SECRET, repr(got))
        self.assertEqual(seen, [(["op", "whoami"], {"capture_output": True, "timeout": 10})] * len(cases))
        self.assertEqual(S.WHOAMI_TIMEOUT_S, 10)
        # the default runner is subprocess.run (patched here: the test never starts op)
        with mock.patch.object(subprocess, "run", make(0)):
            self.assertEqual(S.op_signed_in(), (True, None))
        # no reference configured: onepassword is off with its own sentence and op is never run
        n = len(seen)
        f = self.facade(semantic=dict(key_ref=None, signin_check=lambda: S.op_signed_in(run=make(0))))
        self.assertEqual(f.capabilities()["features"]["onepassword"], {"available": False, "reason": OP_NOT_USED})
        self.assertEqual(len(seen), n)

    def test_semantic_build_checks_signin_first(self):  # E24 / SIP10: not signed in -> op read never runs
        from darkroom_app.errors import DarkroomError
        from darkroom_app.services import semantic_index as S
        from test_semantic_index import make_sources
        reads = []

        def read(ref):
            reads.append(ref)
            return SECRET
        with self.assertRaises(S._KeyUnavailable) as cm:
            S.op_key(REF, signed_in=lambda: (False, OP_NOT_SIGNED_IN), read=read)
        self.assertEqual(str(cm.exception), OP_NOT_SIGNED_IN)
        self.assertEqual(reads, [])
        self.assertEqual(S.op_key(REF, signed_in=lambda: (True, None), read=read), SECRET)
        self.assertEqual(reads, [REF])
        reads.clear()
        src = make_sources(os.path.join(self.tmp, "sources"))
        for signed in ((False, OP_NOT_SIGNED_IN), (False, OP_TIMEOUT), (False, OP_NO_OP)):
            f = self.facade(semantic=dict(
                key_ref=REF, env_key=None, sources_dir=src, budget_usd=5.0, have_anthropic=lambda: True,
                client_factory=lambda k: (_ for _ in ()).throw(AssertionError("no client without a key")),
                key_reader=lambda ref, signed=signed: S.op_key(ref, signed_in=lambda: signed, read=read),
                renderer=lambda *a: (_ for _ in ()).throw(AssertionError("nothing rendered"))))
            with self.assertRaises(DarkroomError) as cm:
                f.semantic_build(limit=1)
            self.assertEqual((cm.exception.kind, cm.exception.message),
                             ("unavailable", KEY_FAILED.format(reason=signed[1])))
        self.assertEqual(reads, [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "lib", "semantic.json")))


# ---------------------------------------------------------------------- E26 (CLI over FakeDarkroom)
class TestCliS2(unittest.TestCase):
    def run_cli(self, argv, fake):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(argv, facade=fake)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_cli_s2_flags(self):  # E26
        fake = FakeDarkroom()
        rc, out, err = self.run_cli(["export", "a.jpg", "--format", "png", "--bit-depth", "16", "--quality", "80",
                                     "--max-kb", "800", "--resize", "long_edge=2048", "--metadata", "copyright",
                                     "--remove-gps", "--sharpen", "screen=standard", "--export-preset", "網頁",
                                     "--json"], fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(fake.calls[-1], ("export", ([{"path": "a.jpg"}], "png", 80, None, {
            "bit_depth": 16, "max_kb": 800, "resize": {"mode": "long_edge", "value": 2048}, "metadata": "copyright",
            "remove_gps": True, "sharpen": {"target": "screen", "amount": "standard"}, "export_preset": "網頁"})))
        # raw values go to the service unchanged (it judges them, the sentences are the service's)
        self.run_cli(["export", "a.jpg", "--resize", "abc", "--max-kb", "x", "--bit-depth", "y", "--sharpen", "bad",
                      "--json"], fake)
        self.assertEqual(fake.calls[-1], ("export", ([{"path": "a.jpg"}], None, None, None,
                                                     {"bit_depth": "y", "max_kb": "x", "resize": "abc",
                                                      "sharpen": "bad"})))
        self.run_cli(["export", "a.jpg", "--resize", "percent=33.5", "--sharpen", "matte=", "--json"], fake)
        self.assertEqual(fake.calls[-1][1][4], {"resize": {"mode": "percent", "value": 33.5},
                                                "sharpen": {"target": "matte", "amount": ""}})
        self.run_cli(["export", "a.jpg", "--resize", "width=wide", "--json"], fake)
        self.assertEqual(fake.calls[-1][1][4], {"resize": {"mode": "width", "value": "wide"}})
        self.run_cli(["export", "a.jpg", "--json"], fake)          # nothing given: no S2 keyword at all
        self.assertEqual(fake.calls[-1], ("export", ([{"path": "a.jpg"}], None, None, None)))
        # export-presets
        rc, out, err = self.run_cli(["export-presets", "list", "--json"], fake)
        self.assertEqual((rc, err, fake.calls[-1]), (0, "", ("list_export_presets", ())))
        self.assertEqual(json.loads(out)["result"], {"presets": [{"name": "網頁", "settings": {"format": "jpeg"}}]})
        rc, out, err = self.run_cli(["export-presets", "save", "--name", "網頁", "--format", "jpeg", "--max-kb", "800",
                                     "--resize", "long_edge=2048", "--json"], fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(fake.calls[-1], ("save_export_preset", ("網頁", {"format": "jpeg", "max_kb": 800,
                                                                         "resize": {"mode": "long_edge",
                                                                                    "value": 2048}})))
        self.run_cli(["export-presets", "save", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("save_export_preset", (None, {})))
        rc, out, err = self.run_cli(["export-presets", "delete", "網頁", "--json"], fake)
        self.assertEqual((rc, err, fake.calls[-1]), (0, "", ("delete_export_preset", ("網頁",))))
        # presets files: one line per file "{file_name}\t{bytes}", a failure is its sentence, exit 6
        rc, out, err = self.run_cli(["presets", "files", "p1", "nope"], fake)
        self.assertEqual((rc, out, err), (6, "p1.xmp\t3\nunknown preset nope\n", ""))
        self.assertEqual(fake.calls[-1], ("preset_files", (["p1", "nope"],)))
        rc, out, err = self.run_cli(["presets", "files", "p1"], fake)
        self.assertEqual((rc, out, err), (0, "p1.xmp\t3\n", ""))
        rc, out, err = self.run_cli(["presets", "files", "p1", "nope", "--json"], fake)
        self.assertEqual((rc, err), (6, ""))
        self.assertEqual(json.loads(out)["result"]["files"][1], {"ok": False, "preset_id": "nope",
                                                                 "error": "unknown preset nope"})
        # presets export
        rc, out, err = self.run_cli(["presets", "export", "p1", "nope", "--dest-dir", "D:\\x"], fake)
        self.assertEqual((rc, out, err), (6, "已匯出 preset：D:\\out\\p1.xmp\nunknown preset nope\n", ""))
        self.assertEqual(fake.calls[-1], ("export_preset_files", (["p1", "nope"], "D:\\x")))
        rc, out, err = self.run_cli(["presets", "export", "p1", "--dest-dir", "D:\\x"], fake)
        self.assertEqual((rc, out, err), (0, "已匯出 preset：D:\\out\\p1.xmp\n", ""))
        self.run_cli(["presets", "export", "p1", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("export_preset_files", (["p1"], None)))   # the service says why

    def test_cli_export_no_edit(self):  # E26 / E15
        fake = FakeDarkroom()
        self.run_cli(["export", "a.jpg", "b.jpg", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("export", ([{"path": "a.jpg"}, {"path": "b.jpg"}], None, None, None)))
        self.run_cli(["export", "a.jpg", "--no-edit", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("export", ([{"path": "a.jpg", "preset_id": None, "strength": 100,
                                                       "overrides": None}], None, None, None)))
        self.run_cli(["export", "a.jpg", "--strength", "50", "--json"], fake)
        self.assertEqual(fake.calls[-1][1][0], [{"path": "a.jpg", "preset_id": None, "strength": 50.0,
                                                 "overrides": None}])
        self.run_cli(["export", "a.jpg", "--override", "Exposure2012=0.5", "--json"], fake)
        self.assertEqual(fake.calls[-1][1][0], [{"path": "a.jpg", "preset_id": None, "strength": 100,
                                                 "overrides": {"Exposure2012": 0.5}}])
        self.run_cli(["export", "a.jpg", "--preset", "p", "--json"], fake)
        self.assertEqual(fake.calls[-1][1][0], [{"path": "a.jpg", "preset_id": "p", "strength": 100,
                                                 "overrides": None}])
        n = len(fake.calls)
        rc, out, err = self.run_cli(["export", "a.jpg", "--preset", "p", "--no-edit", "--json"], fake)
        self.assertEqual((rc, out), (2, ""))
        self.assertEqual(err.count("\n"), 1, err)                  # one usage line (L9)
        self.assertIn("--no-edit", err)
        self.assertEqual(len(fake.calls), n)

    def test_cli_capabilities_human(self):  # E26
        fake = FakeDarkroom()
        rc, out, err = self.run_cli(["capabilities"], fake)
        self.assertEqual((rc, out, err), (0, "gpu\t可用\nwebp\t關閉：假原因\n", ""))
        self.assertEqual(fake.calls[-1], ("capabilities", (False,)))
        rc, out, err = self.run_cli(["capabilities", "--refresh", "--json"], fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(fake.calls[-1], ("capabilities", (True,)))
        self.assertEqual(json.loads(out)["result"]["features"]["webp"], {"available": False, "reason": "假原因"})

    def test_cli_relative_dirs_are_absolute(self):  # E19 (CLI side): --preset-dir / --data-dir before any use
        from darkroom_app import cli, composition
        seen = []

        def build(*a, **k):
            seen.append((a, k))
            return FakeDarkroom()
        with mock.patch.object(composition, "build_facade", build):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                cli.main(["--preset-dir", "rel-presets", "--data-dir", "rel-data", "sliders", "--json"])
        self.assertEqual(seen, [((os.path.abspath("rel-presets"),), {"data_dir": os.path.abspath("rel-data")})])


# ---------------------------------------------------------------------- E27 (MCP)
class TestMcpS2(unittest.TestCase):
    def exchange(self, fake, *calls):
        from darkroom_app.mcp_server import serve
        msgs = b"".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                    "params": {"name": n, "arguments": a}}).encode() + b"\n"
                        for i, (n, a) in enumerate(calls, 1))
        out = io.BytesIO()
        serve(io.BytesIO(msgs), out, facade=fake)
        return [json.loads(x)["result"] for x in out.getvalue().decode("utf-8").splitlines()]

    def test_mcp_s2_schemas(self):  # E27 / XP32
        from darkroom_app.mcp_server.tools import Tools
        tools = {t["name"]: t for t in Tools(lambda: None).list()}
        self.assertEqual(len(tools), 33)
        self.assertEqual(list(tools)[27:], list(S2_ANNOTATIONS))
        for name, ann in S2_ANNOTATIONS.items():
            self.assertEqual(tools[name]["annotations"], ann, name)
            self.assertIs(tools[name]["inputSchema"]["additionalProperties"], False, name)
        ex = tools["darkroom_export"]["inputSchema"]
        for k in ("bit_depth", "max_kb", "resize", "metadata", "remove_gps", "sharpen", "export_preset"):
            self.assertIn(k, ex["properties"], k)
        self.assertEqual(ex["required"], ["items"])
        self.assertEqual(ex["properties"]["format"]["enum"], ["jpeg", "png", "tiff", "webp"])
        self.assertEqual(tools["darkroom_presets_export"]["inputSchema"]["required"], ["preset_ids", "dest_dir"])
        self.assertEqual(tools["darkroom_preset_files"]["inputSchema"]["required"], ["preset_ids"])
        self.assertEqual(tools["darkroom_export_preset_save"]["inputSchema"]["required"], ["name", "settings"])
        self.assertEqual(tools["darkroom_export_preset_delete"]["inputSchema"]["required"], ["name"])
        self.assertNotIn("required", tools["darkroom_capabilities"]["inputSchema"])
        fake = FakeDarkroom()
        res = self.exchange(fake, ("darkroom_presets_export", {"preset_ids": ["p1", "nope"], "dest_dir": "D:\\x"}),
                            ("darkroom_preset_files", {"preset_ids": ["p1", "nope"]}),
                            ("darkroom_capabilities", {}), ("darkroom_capabilities", {"refresh": True}),
                            ("darkroom_export_presets_list", {}),
                            ("darkroom_export_preset_save", {"name": "網頁", "settings": {"format": "png"}}),
                            ("darkroom_export_preset_delete", {"name": "網頁"}),
                            ("darkroom_export", {"items": [{"path": "a.jpg"}], "max_kb": 800,
                                                 "export_preset": "網頁"}))
        sc = res[0]["structuredContent"]
        self.assertEqual(sc["failed"], 1)                                # XP11: partial failure counted
        self.assertEqual([r["ok"] for r in sc["results"]], [True, False])
        self.assertNotIn("isError", res[0])
        self.assertEqual(res[1]["structuredContent"], {"files": [
            {"ok": True, "preset_id": "p1", "file_name": "p1.xmp", "data_base64": "eG1w"},
            {"ok": False, "preset_id": "nope", "error": "unknown preset nope"}]})   # exactly {"files"}: no failed
        self.assertEqual([c["type"] for c in res[1]["content"]], ["text"])          # base64 text, not an image
        self.assertEqual(json.loads(res[1]["content"][0]["text"]), res[1]["structuredContent"])
        self.assertEqual(fake.calls, [("export_preset_files", (["p1", "nope"], "D:\\x")),
                                      ("preset_files", (["p1", "nope"],)),
                                      ("capabilities", (False,)), ("capabilities", (True,)),
                                      ("list_export_presets", ()), ("save_export_preset", ("網頁", {"format": "png"})),
                                      ("delete_export_preset", ("網頁",)),
                                      ("export", ([{"path": "a.jpg"}], None, None, None,
                                                  {"max_kb": 800, "export_preset": "網頁"}))])
        self.assertEqual(res[2]["structuredContent"]["features"]["gpu"], {"available": True, "reason": None})
        self.assertEqual(res[7]["structuredContent"]["failed"], 0)


# ---------------------------------------------------------------------- E28 (HTTP over FakeDarkroom)
class TestHttpS2(AioHTTPTestCase):
    async def get_client(self, server):
        from aiohttp.test_utils import TestClient
        return TestClient(server, headers=_util.HTTP_HEADERS)

    async def get_application(self):
        from darkroom_app.server import FACADE, make_app
        d = os.path.join(_util.tmpdir(self), "p")
        os.makedirs(d)
        app = make_app(make_presets(d), engine=_NoEngine())
        self.fake = FakeDarkroom()
        app[FACADE] = self.fake
        return app

    async def test_preset_export_refused_over_http(self):  # E17 / E28
        for body in ({"preset_ids": ["p1"], "dest_dir": "D:\\x"}, {"preset_ids": ["p1"]}, {}):
            r = await self.client.post("/api/preset-library/export", json=body)
            self.assertEqual((r.status, await r.json()), (400, {"error": PRESET_EXPORT_REFUSED}), body)
        self.assertEqual(self.fake.calls, [])

    async def test_writes_take_no_folder_over_http(self):  # E28 / PLP2 / XP16
        for dd in ("D:\\x", None, ""):
            r = await self.client.put("/api/export-presets", json={"name": "n", "settings": {}, "data_dir": dd})
            self.assertEqual((r.status, await r.json()), (400, {"error": DATA_DIR_REFUSED}), dd)
        r = await self.client.post("/api/export", json={"items": [{"path": "a.jpg"}], "dest_dir": "D:\\x"})
        self.assertEqual((r.status, await r.json()), (400, {"error": DEST_DIR_REFUSED}))
        self.assertEqual(self.fake.calls, [])

    async def test_translation(self):  # E28: each new route forwards its arguments once
        r = await self.client.get("/api/export-presets")
        self.assertEqual((r.status, await r.json()), (200, {"presets": [{"name": "網頁",
                                                                          "settings": {"format": "jpeg"}}]}))
        r = await self.client.put("/api/export-presets", json={"name": "網頁", "settings": {"format": "png"}})
        self.assertEqual(r.status, 200)
        r = await self.client.delete("/api/export-presets", params={"name": "網頁"})
        self.assertEqual((r.status, await r.json()), (200, {"name": "網頁", "settings": {"format": "jpeg"}}))
        r = await self.client.post("/api/preset-library/files", json={"preset_ids": ["p1"]})
        self.assertEqual((r.status, list(await r.json())), (200, ["files"]))
        for q, want in (("", False), ("?refresh=1", True), ("?refresh=0", False), ("?refresh=true", True)):
            r = await self.client.get("/api/capabilities" + q)
            self.assertEqual(r.status, 200, q)
            self.assertEqual(self.fake.calls[-1], ("capabilities", (want,)), q)
        r = await self.client.post("/api/export", json={"items": [{"path": "a.jpg"}], "format": "png",
                                                        "bit_depth": 16, "resize": {"mode": "percent", "value": 50},
                                                        "metadata": "none", "remove_gps": True,
                                                        "sharpen": {"target": "glossy", "amount": "high"},
                                                        "max_kb": 9, "export_preset": "網頁"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.fake.calls[:4], [("list_export_presets", ()),
                                               ("save_export_preset", ("網頁", {"format": "png"})),
                                               ("delete_export_preset", ("網頁",)),
                                               ("preset_files", (["p1"],))])
        self.assertEqual(self.fake.calls[-1], ("export", ([{"path": "a.jpg"}], "png", None, None, {
            "bit_depth": 16, "max_kb": 9, "resize": {"mode": "percent", "value": 50}, "metadata": "none",
            "remove_gps": True, "sharpen": {"target": "glossy", "amount": "high"}, "export_preset": "網頁"})))


if __name__ == "__main__":
    unittest.main()
