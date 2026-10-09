"""CONTRACT-layering L11 / L12: the three interfaces over one facade give the same outcome and never write.

One build_facade (synthetic presets + the real Engine) is driven through HTTP (aiohttp TestClient), the CLI
(main(argv + ["--json"], facade=f)) and MCP (serve() fed from BytesIO). Every outcome is normalized to
Outcome(ok, kind, message); status code / exit code / isError must follow L7.
Export (CONTRACT-export XP6 / XP11 / XP13): the outcome plus every result's (ok, basename(output) or error); CLI exit 6
and MCP `failed` when some photo failed.
Preset library (CONTRACT-preset-library K17): TestPresetLibraryParity, every scenario on its own synthetic library copy.
"""
import base64
import builtins
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from collections import namedtuple
from unittest import mock

import cv2
import numpy as np
from aiohttp.test_utils import TestClient, TestServer

import _heicgen
import _util
from test_app_server import make_presets, snapshot, write_photo

Outcome = namedtuple("Outcome", "ok kind message")
HTTP_STATUS = {"invalid": 400, "not_found": 404}
CLI_EXIT = {"invalid": 2, "not_found": 3}
OK = Outcome(True, None, None)


def jpeg_size(data):
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return img.shape[1], img.shape[0]


class HttpDriver:
    name = "http"

    def __init__(self, test, client):
        self.t, self.c = test, client

    async def _out(self, r):
        if r.status == 200:
            return OK, r
        body = await r.json()
        kind = {v: k for k, v in HTTP_STATUS.items()}[r.status]
        self.t.assertEqual(list(body), ["error"])
        return Outcome(False, kind, body["error"]), r

    async def open(self, path):
        o, r = await self._out(await self.c.post("/api/open", json={"path": path}))
        return o, (await r.json() if o.ok else None)

    async def detail(self, pid):
        return (await self._out(await self.c.get(f"/api/presets/{pid}")))[0]

    async def presets(self, query=None, limit=None):
        if query is not None or limit is not None:
            return None      # HTTP never passes query / offset / limit (L4)
        return (await self._out(await self.c.get("/api/presets")))[0]

    async def preview_id(self, image_id, **body):
        o, r = await self._out(await self.c.post("/api/preview", json={"image_id": image_id, **body}))
        return o, (jpeg_size(await r.read()) if o.ok else None)

    async def preview(self, path, **body):
        o, info = await self.open(path)
        if not o.ok:
            return o, None
        return await self.preview_id(info["image_id"], **body)

    async def folder(self, image_id):
        return (await self._out(await self.c.get("/api/folder", params={"image_id": image_id})))[0]

    async def export(self, items, format, quality=None, dest_dir=None, raw_quality=None, send_dest=False):
        """HTTP takes no dest_dir (XP16): the export goes to '<photos>/darkroom 匯出', which is emptied and given
        the same existing files as `dest_dir` first, so the names come out as in the other interfaces."""
        body = {"items": items, "format": format}
        if quality is not None or raw_quality is not None:
            body["quality"] = raw_quality if raw_quality is not None else quality
        if send_dest:
            body["dest_dir"] = dest_dir
        elif dest_dir is not None:
            if not os.path.isdir(dest_dir) or os.path.normcase(dest_dir) == os.path.normcase(self.t.photos):
                return None                  # only the CLI and MCP can name a folder
            default = os.path.join(self.t.photos, "darkroom 匯出")
            shutil.rmtree(default, ignore_errors=True)
            os.makedirs(default)
            for n in os.listdir(dest_dir):
                shutil.copyfile(os.path.join(dest_dir, n), os.path.join(default, n))
        o, r = await self._out(await self.c.post("/api/export", json=body))
        if not o.ok:
            return o, None
        res = await r.json()
        self.t.assertEqual(list(res), ["results"])
        return o, normalize(res["results"])


def normalize(results):
    return [(r["ok"], os.path.basename(r["output"]) if r["ok"] else r["error"]) for r in results]


def same_params(items):
    """(paths, the one parameter set) when every item is a path item with the same parameters, else None."""
    if not items or any(set(it) - {"path", "preset_id", "strength", "overrides"} for it in items):
        return None if items else ([], {})
    rest = [{k: v for k, v in it.items() if k != "path"} for it in items]
    return ([it["path"] for it in items], rest[0]) if all(r == rest[0] for r in rest) else None


class CliDriver:
    name = "cli"

    def __init__(self, test, facade):
        self.t, self.f = test, facade
        self.totals = []

    def _run(self, argv):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv + ["--json"], facade=self.f)
        self.t.assertEqual(err.getvalue(), "", argv)
        self.t.assertEqual(out.getvalue().count("\n"), 1, argv)
        env = json.loads(out.getvalue())
        if env["ok"]:
            self.t.assertEqual(rc, 0)
            return OK, env["result"]
        kind = env["error"]["kind"]
        self.t.assertEqual(rc, CLI_EXIT[kind], argv)
        return Outcome(False, kind, env["error"]["message"]), None

    async def open(self, path):
        return self._run(["open", path])

    async def detail(self, pid):
        return self._run(["presets", "show", pid])[0]

    async def presets(self, query=None, limit=None):
        argv = ["presets", "list"]
        if query is not None:
            argv += ["--query", query]
        if limit is not None:
            argv += ["--limit", str(limit)]
        o, res = self._run(argv)
        self.totals.append(res["total"] if o.ok else None)
        return o

    async def preview(self, path, preset_id=None, strength=None, overrides=None):
        argv = ["preview", path]
        if preset_id is not None:
            argv += ["--preset", preset_id]
        if strength is not None:
            argv += ["--strength", str(strength)]
        for k, v in (overrides or {}).items():
            argv += ["--override", f"{k}={v}"]
        o, res = self._run(argv)
        return o, ((res["width"], res["height"]) if o.ok else None)

    async def export(self, items, format, quality=None, dest_dir=None, raw_quality=None):
        if raw_quality is not None:
            return None                      # a JSON true cannot be typed on a command line
        sp = same_params(items)
        if sp is None:
            return None                      # the CLI gives every photo the same parameters (XP3)
        paths, params = sp
        argv = ["export", *paths, "--format", format]
        if params.get("preset_id") is not None:
            argv += ["--preset", params["preset_id"]]
        if "strength" in params:
            argv += ["--strength", str(params["strength"])]
        for k, v in (params.get("overrides") or {}).items():
            argv += ["--override", f"{k}={v}"]
        if quality is not None:
            argv += ["--quality", str(quality)]
        if dest_dir is not None:
            argv += ["--dest-dir", dest_dir]
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv + ["--json"], facade=self.f)
        self.t.assertEqual(err.getvalue(), "", argv)
        self.t.assertEqual(out.getvalue().count("\n"), 1, argv)
        env = json.loads(out.getvalue())
        if not env["ok"]:
            self.t.assertEqual(rc, CLI_EXIT[env["error"]["kind"]], argv)
            return Outcome(False, env["error"]["kind"], env["error"]["message"]), None
        results = env["result"]["results"]
        self.t.assertEqual(rc, 0 if all(r["ok"] for r in results) else 6, argv)          # XP11
        return OK, normalize(results)


class McpDriver:
    name = "mcp"

    def __init__(self, test, facade):
        self.t, self.f = test, facade
        self.n = 0
        self.totals = []

    def _call(self, tool, arguments):
        from darkroom_app.mcp_server import serve
        self.n += 1
        line = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode("utf-8") + b"\n"
        out = io.BytesIO()
        serve(io.BytesIO(line), out, facade=self.f)
        res = json.loads(out.getvalue())["result"]
        sc = res["structuredContent"]
        if res.get("isError"):
            self.t.assertIs(res["isError"], True)
            self.t.assertEqual(res["content"], [{"type": "text", "text": sc["message"]}])
            return Outcome(False, sc["kind"], sc["message"]), None
        self.t.assertNotIn("isError", res)
        return OK, (res, sc)

    async def open(self, path):
        o, r = self._call("darkroom_open_photo", {"path": path})
        return o, (r[1] if o.ok else None)

    async def detail(self, pid):
        return self._call("darkroom_preset_show", {"preset_id": pid})[0]

    async def presets(self, query=None, limit=None):
        args = {k: v for k, v in (("query", query), ("limit", limit)) if v is not None}
        o, r = self._call("darkroom_presets_list", args)
        self.totals.append(r[1]["total"] if o.ok else None)
        return o

    async def preview_id(self, image_id, **args):
        o, r = self._call("darkroom_preview", {"image_id": image_id, **args})
        if not o.ok:
            return o, None
        res, sc = r
        self.t.assertEqual(jpeg_size(base64.b64decode(res["content"][0]["data"])), (sc["width"], sc["height"]))
        return o, (sc["width"], sc["height"])

    async def preview(self, path, **args):
        o, info = await self.open(path)
        if not o.ok:
            return o, None
        return await self.preview_id(info["image_id"], **args)

    async def folder(self, image_id):
        return self._call("darkroom_photo_folder", {"image_id": image_id})[0]

    async def export(self, items, format, quality=None, dest_dir=None, raw_quality=None):
        args = {"items": items, "format": format}
        if quality is not None or raw_quality is not None:
            args["quality"] = raw_quality if raw_quality is not None else quality
        if dest_dir is not None:
            args["dest_dir"] = dest_dir
        o, r = self._call("darkroom_export", args)
        if not o.ok:
            return o, None
        res, sc = r
        self.t.assertEqual(list(sc), ["results", "failed"])                                # XP11
        self.t.assertEqual(sc["failed"], sum(1 for x in sc["results"] if not x["ok"]))
        self.t.assertEqual(json.loads(res["content"][0]["text"]), sc)
        return o, normalize(sc["results"])


class TestInterfaceParity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from darkroom_app import engine as engine_mod
        from darkroom_app.composition import build_facade
        from darkroom_app.server import FACADE, make_app
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        eng = engine_mod.Engine()
        self.f = build_facade(self.presets, engine=eng)
        app = make_app(self.presets, engine=eng)
        app[FACADE] = self.f                      # one facade behind all three interfaces
        self.client = TestClient(TestServer(app), headers=_util.HTTP_HEADERS)   # PLP11
        await self.client.start_server()
        self.drivers = [HttpDriver(self, self.client), CliDriver(self, self.f), McpDriver(self, self.f)]

    async def asyncTearDown(self):
        await self.client.close()

    def files(self):
        p = lambda n: os.path.join(self.photos, n)
        photo = write_photo(p("ok.png"), 640, 400)          # small enough that the MCP default max_pixels is moot
        with open(p("notes.txt"), "w") as fh:
            fh.write("x")
        with open(p("broken.jpg"), "wb") as fh:
            fh.write(b"not an image")
        good = _heicgen.write_heic(p("good.heic"), _heicgen.pattern(32, 32))
        with open(good, "rb") as fh:
            data = fh.read()
        with open(p("half.heic"), "wb") as fh:
            fh.write(data[: len(data) // 2])
        return photo, p

    async def scenarios(self, photo, p):
        """[(name, {driver: outcome})]; a driver that cannot express a scenario is left out."""
        cases = [
            ("missing file", lambda d: d.open(p("missing.jpg"))),
            (".txt", lambda d: d.open(p("notes.txt"))),
            ("truncated HEIC", lambda d: d.open(p("half.heic"))),
            ("broken JPEG", lambda d: d.open(p("broken.jpg"))),
            ("empty path", lambda d: d.open("")),
            ("strength 250", lambda d: d.preview(photo, strength=250)),
            ("unknown slider key", lambda d: d.preview(photo, overrides={"Bogus": 1})),
            ("unknown preset (preview)", lambda d: d.preview(photo, preset_id="nope")),
            ("unknown preset (detail)", lambda d: d.detail("nope")),
            ("limit 0", lambda d: d.presets(limit=0)),
            ("query hit", lambda d: d.presets(query="海邊")),
            ("list, no filter", lambda d: d.presets()),
            ("preview success", lambda d: d.preview(photo, preset_id="p-expo")),
        ]
        out = []
        for name, fn in cases:
            got = {}
            for d in self.drivers:
                r = await fn(d)
                if r is not None:
                    got[d.name] = r
            out.append((name, got))
        for name, fn in (("unknown image_id (preview)", lambda d: d.preview_id("nope")),
                         ("unknown image_id (folder)", lambda d: d.folder("nope"))):
            out.append((name, {d.name: await fn(d) for d in self.drivers if d.name != "cli"}))
        return out

    async def test_interface_parity(self):
        photo, p = self.files()
        expected = {
            "missing file": Outcome(False, "not_found", f"photo not found: {p('missing.jpg')}"),
            ".txt": Outcome(False, "invalid", "unsupported photo format (JPEG/PNG/TIFF/HEIC)"),
            "broken JPEG": Outcome(False, "invalid", f"照片讀取失敗：broken.jpg：cannot decode image {p('broken.jpg')}"),
            "empty path": Outcome(False, "invalid", "path is required"),
            "strength 250": Outcome(False, "invalid", "strength must be within 0..200, got 250"),
            "unknown slider key": Outcome(False, "invalid", "unknown slider key 'Bogus'"),
            "unknown preset (preview)": Outcome(False, "not_found", "unknown or unsupported preset nope"),
            "unknown preset (detail)": Outcome(False, "not_found", "unknown preset nope"),
            "limit 0": Outcome(False, "invalid", "limit must be an integer in 1..200"),
            "query hit": OK,
            "list, no filter": OK,
            "preview success": OK,
            "unknown image_id (preview)": Outcome(False, "not_found", "unknown image_id"),
            "unknown image_id (folder)": Outcome(False, "not_found", "unknown image_id"),
        }
        for name, got in await self.scenarios(photo, p):
            outcomes = {k: (v if isinstance(v, Outcome) else v[0]) for k, v in got.items()}
            want_drivers = {"http", "mcp"} if "image_id" in name else (
                {"cli", "mcp"} if name in ("limit 0", "query hit") else {"http", "cli", "mcp"})
            self.assertEqual(set(outcomes), want_drivers, name)
            self.assertEqual(len(set(outcomes.values())), 1, (name, outcomes))
            one = next(iter(outcomes.values()))
            if name == "truncated HEIC":
                self.assertEqual(one.kind, "invalid")
                self.assertTrue(one.message.startswith("照片讀取失敗：half.heic：HEIC 解碼失敗："), one.message)
            else:
                self.assertEqual(one, expected[name], name)
            if name == "query hit":         # seal patch S4: the same filtered total on CLI and MCP
                cli, mcp = self.drivers[1], self.drivers[2]
                for d in (cli, mcp):
                    self.assertEqual(await d.presets(query="海邊"), OK)
                self.assertEqual(cli.totals[-1], mcp.totals[-1])
                self.assertEqual(cli.totals[-1], 1)
            if name == "preview success":
                sizes = {k: v[1] for k, v in got.items()}
                self.assertEqual(len(set(sizes.values())), 1, sizes)
                self.assertEqual(sizes["http"], (640, 400))

    async def test_cli_mcp_never_write(self):  # L12
        photo, p = self.files()
        before = snapshot(self.photos, self.presets)
        names = {d: sorted(os.listdir(d)) for d in (self.photos, self.presets)}
        writes = []
        real_open = builtins.open
        guarded = [os.path.normcase(os.path.abspath(d)) for d in (self.photos, self.presets)]

        def spy_open(file, mode="r", *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+"):
                q = os.path.normcase(os.path.abspath(os.fsdecode(file)))
                if any(q.startswith(g) for g in guarded):
                    writes.append(q)
            return real_open(file, mode, *a, **k)
        self.drivers = self.drivers[1:]            # CLI and MCP
        with mock.patch("builtins.open", spy_open):
            await self.scenarios(photo, p)
            for d in self.drivers:
                await d.preview(photo, preset_id="p-skip", strength=150, overrides={"Exposure2012": 0.2})
            self.drivers[0]._run(["folder", photo])
            self.drivers[0]._run(["presets", "flags"])
            self.drivers[0]._run(["sliders"])
            # CONTRACT-export XP5 / XP10: the export scenario adds X9-named files to its own dest_dir only
            for d in self.drivers:
                dest = os.path.join(self.tmp, f"dest-{d.name}")
                os.makedirs(dest)
                o, res = await d.export([{"path": photo, "preset_id": "p-expo"}, {"path": p("broken.jpg"),
                                                                                    "preset_id": "p-expo"}],
                                        "jpeg", dest_dir=dest)
                self.assertEqual(o, OK)
                self.assertEqual([r[0] for r in res], [True, False])
                self.assertEqual(sorted(os.listdir(dest)), ["ok.jpg"])
        self.assertEqual(writes, [])
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual({d: sorted(os.listdir(d)) for d in (self.photos, self.presets)}, names)

    async def test_export_parity(self):  # CONTRACT-export XP6, XP11, XP13
        photo, p = self.files()
        jpeg = os.path.join(self.photos, "shot.jpg")
        img = (np.random.default_rng(3).random((24, 36, 3)) * 255).astype(np.uint8)
        with open(jpeg, "wb") as fh:
            fh.write(cv2.imencode(".jpg", img)[1].tobytes())
        before = snapshot(self.photos, self.presets)
        n = [0]

        def fresh():
            n[0] += 1
            d = os.path.join(self.tmp, f"x{n[0]}")
            os.makedirs(d)
            return d
        rel = "relative-dest"
        missing = os.path.join(self.tmp, "no-such-dest")
        cases = [
            ("items empty", lambda d: d.export([], "jpeg", dest_dir=fresh()),
             Outcome(False, "invalid", "沒有要匯出的照片"), None),
            ("format png", lambda d: d.export([{"path": jpeg}], "png", dest_dir=fresh()),
             Outcome(False, "invalid", "不支援的匯出格式：png（可用 jpeg、tiff）"), None),
            ("quality 0", lambda d: d.export([{"path": jpeg}], "jpeg", 0, dest_dir=fresh()),
             Outcome(False, "invalid", "JPEG 品質要在 1～100 之間：0"), None),
            ("quality true", lambda d: d.export([{"path": jpeg}], "jpeg", dest_dir=fresh(), raw_quality=True),
             Outcome(False, "invalid", "JPEG 品質要在 1～100 之間：True"), None),
            ("dest_dir relative", lambda d: d.export([{"path": jpeg}], "jpeg", dest_dir=rel),
             Outcome(False, "invalid", f"找不到匯出資料夾：{rel}"), None),
            ("dest_dir missing", lambda d: d.export([{"path": jpeg}], "jpeg", dest_dir=missing),
             Outcome(False, "invalid", f"找不到匯出資料夾：{missing}"), None),
            ("unknown preset", lambda d: d.export([{"path": jpeg, "preset_id": "nope"}], "jpeg", dest_dir=fresh()),
             OK, [(False, "匯出失敗：shot.jpg：unknown or unsupported preset nope")]),
            ("path missing", lambda d: d.export([{"path": p("gone.jpg")}], "jpeg", dest_dir=fresh()),
             OK, [(False, f"匯出失敗：gone.jpg：photo not found: {p('gone.jpg')}")]),
            ("broken JPEG", lambda d: d.export([{"path": p("broken.jpg")}], "jpeg", dest_dir=fresh()),
             OK, [(False, f"匯出失敗：broken.jpg：cannot decode image {p('broken.jpg')}")]),
            ("JPEG success", lambda d: d.export([{"path": jpeg, "preset_id": "p-expo", "strength": 80}], "jpeg",
                                                dest_dir=fresh()),
             OK, [(True, "shot.jpg")]),
            ("name taken", lambda d: d.export([{"path": jpeg}], "jpeg", dest_dir=taken()),
             OK, [(True, "shot (2).jpg")]),
            ("one good one bad", lambda d: d.export([{"path": jpeg}, {"path": p("gone.jpg")}], "tiff",
                                                    dest_dir=fresh()),
             OK, [(True, "shot.tif"), (False, f"匯出失敗：gone.jpg：photo not found: {p('gone.jpg')}")]),
        ]

        def taken():
            d = fresh()
            with open(os.path.join(d, "shot.jpg"), "wb") as fh:
                fh.write(b"an earlier export")
            return d
        for name, fn, outcome, results in cases:
            got = {}
            for d in self.drivers:
                r = await fn(d)
                if r is not None:
                    got[d.name] = r
            want_drivers = {"http", "mcp"} if name == "quality true" else (
                {"cli", "mcp"} if name.startswith("dest_dir") else {"http", "cli", "mcp"})   # XP16
            self.assertEqual(set(got), want_drivers, name)
            for dname, (o, res) in got.items():
                self.assertEqual(o, outcome, (name, dname))
                self.assertEqual(res, results, (name, dname))
        # XP16: over HTTP a dest_dir is refused (an interface rule), whatever it is
        http = self.drivers[0]
        o, _ = await http.export([{"path": jpeg}], "jpeg", dest_dir=fresh(), send_dest=True)
        self.assertEqual(o, Outcome(False, "invalid", "dest_dir is not accepted over HTTP (use the CLI or MCP)"))
        shutil.rmtree(os.path.join(self.photos, "darkroom 匯出"))
        # XP13: dest_dir = the photo's own folder, where the photo itself is the same name (CLI and MCP, XP16)
        for d in self.drivers[1:]:
            folder = os.path.join(self.tmp, f"own-{d.name}")
            os.makedirs(folder)
            same = os.path.join(folder, "same.jpg")
            with open(same, "wb") as fh:
                fh.write(cv2.imencode(".jpg", img)[1].tobytes())
            sha_before = snapshot(folder)[same][2]
            o, res = await d.export([{"path": same}], "jpeg", dest_dir=folder)
            self.assertEqual((o, res), (OK, [(True, "same (2).jpg")]), d.name)
            self.assertEqual(snapshot(folder)[same][2], sha_before, d.name)
            self.assertEqual(sorted(os.listdir(folder)), ["same (2).jpg", "same.jpg"])
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertFalse(os.path.exists(os.path.join(self.photos, "darkroom 匯出")))


LIB_HTTP_STATUS = {"invalid": 400, "not_found": 404, "conflict": 409, "unavailable": 503}
LIB_CLI_EXIT = {"invalid": 2, "not_found": 3, "conflict": 4, "unavailable": 5}


class _Switch:
    """One facade slot behind all three interfaces; every library scenario puts a fresh facade in it (K17)."""

    def __init__(self):
        self.target = None

    def __getattr__(self, name):
        return getattr(self.target, name)


class TestPresetLibraryParity(unittest.IsolatedAsyncioTestCase):  # CONTRACT-preset-library K17
    """Each scenario runs on its own copy of a synthetic library, once per interface; outcomes and results agree."""

    async def asyncSetUp(self):
        from darkroom_app.server import FACADE, make_app
        from test_layering import _NoEngine
        self.tmp = _util.tmpdir(self)
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        make_presets(seed)
        self.switch = _Switch()
        app = make_app(seed, engine=_NoEngine())
        app[FACADE] = self.switch
        self.client = TestClient(TestServer(app), headers=_util.HTTP_HEADERS)   # PLP11
        await self.client.start_server()
        self.n = 0

    async def asyncTearDown(self):
        await self.client.close()

    def fresh(self):
        """A new library root with the synthetic presets and the import sources; the switch points at it."""
        from darkroom_app.composition import build_facade
        self.n += 1
        root = os.path.join(self.tmp, f"lib{self.n}")
        pd = os.path.join(root, "xmp")
        os.makedirs(pd)
        make_presets(pd)
        src = os.path.join(root, "src")
        os.makedirs(src)
        import _xmpgen
        _xmpgen.write(src, "good.xmp", _xmpgen.xmp_text({"Contrast2012": "+7"}, name="新來的", group="匯入"))
        shutil.copyfile(os.path.join(pd, "p-expo.xmp"), os.path.join(src, "dup.xmp"))
        with open(os.path.join(src, "note.txt"), "w") as fh:
            fh.write("x")
        with open(os.path.join(src, "bad.xmp"), "w") as fh:
            fh.write("<x")
        self.switch.target = build_facade(pd)
        return root, src

    # ---------------------------------------------------------------- the three drivers
    async def http(self, method, path, body=None):
        r = await (self.client.get(path) if method == "GET" else self.client.post(path, json=body))
        data = await r.json()
        if r.status == 200:
            return OK, data
        kind = {v: k for k, v in LIB_HTTP_STATUS.items()}[r.status]
        self.assertEqual(list(data), ["error"])
        return Outcome(False, kind, data["error"]), None

    def cli(self, argv):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv + ["--json"], facade=self.switch)
        self.assertEqual(err.getvalue(), "", argv)
        self.assertEqual(out.getvalue().count("\n"), 1, argv)
        env = json.loads(out.getvalue())
        if env["ok"]:
            res = env["result"]
            partial = isinstance(res, dict) and "results" in res and not all(x["ok"] for x in res["results"])
            self.assertEqual(rc, 6 if partial else 0, argv)                     # KP5
            return OK, res
        self.assertEqual(rc, LIB_CLI_EXIT[env["error"]["kind"]], argv)
        return Outcome(False, env["error"]["kind"], env["error"]["message"]), None

    def mcp(self, tool, arguments):
        from darkroom_app.mcp_server import serve
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode("utf-8") + b"\n"
        out = io.BytesIO()
        serve(io.BytesIO(line), out, facade=self.switch)
        res = json.loads(out.getvalue())["result"]
        sc = res["structuredContent"]
        if res.get("isError"):
            return Outcome(False, sc["kind"], sc["message"]), None
        self.assertNotIn("isError", res)
        if tool == "darkroom_presets_import":                                     # KP5
            self.assertEqual(sc["failed"], sum(1 for x in sc["results"] if not x["ok"]))
            sc = {"results": sc["results"]}
        return OK, sc

    async def run_three(self, http, cli, mcp, setup=None):
        got = {}
        for name, call in (("http", http), ("cli", cli), ("mcp", mcp)):
            if call is None:
                continue
            root, src = self.fresh()
            if setup:
                setup(root)
            if name == "http":
                got[name] = await self.http(*call(root, src))
            elif name == "cli":
                got[name] = self.cli(call(root, src))
            else:
                got[name] = self.mcp(*call(root, src))
        return got

    def b64(self, src, name):
        with open(os.path.join(src, name), "rb") as fh:
            return {"name": name, "data_base64": base64.b64encode(fh.read()).decode("ascii")}

    async def test_preset_library_parity(self):
        L = "/api/preset-library/"
        upload = ("bad.xmp", "dup.xmp", "good.xmp", "note.txt")
        cases = [
            ("group tree", (lambda r, s: ("GET", L + "groups")), (lambda r, s: ["presets", "groups"]),
             (lambda r, s: ("darkroom_preset_groups", {})), OK),
            ("rename to blank", (lambda r, s: ("POST", L + "rename", {"preset_id": "p-expo", "name": "  "})),
             (lambda r, s: ["presets", "rename", "p-expo", "  "]),
             (lambda r, s: ("darkroom_preset_rename", {"preset_id": "p-expo", "name": "  "})),
             Outcome(False, "invalid", "preset 名稱要 1～100 個字")),
            ("rename unknown preset", (lambda r, s: ("POST", L + "rename", {"preset_id": "nope", "name": "x"})),
             (lambda r, s: ["presets", "rename", "nope", "x"]),
             (lambda r, s: ("darkroom_preset_rename", {"preset_id": "nope", "name": "x"})),
             Outcome(False, "not_found", "unknown preset nope")),
            ("move to an empty level", (lambda r, s: ("POST", L + "move", {"preset_id": "p-expo", "group": "A -  - B"})),
             (lambda r, s: ["presets", "move", "p-expo", "A -  - B"]),
             (lambda r, s: ("darkroom_preset_move", {"preset_id": "p-expo", "group": "A -  - B"})),
             Outcome(False, "invalid", "群組名稱不能是空的，也不能有空的層級：A -  - B")),
            ("create an existing group", (lambda r, s: ("POST", L + "groups/create", {"group": "測試"})),
             (lambda r, s: ["groups", "create", "測試"]), (lambda r, s: ("darkroom_group_create", {"group": "測試"})),
             Outcome(False, "conflict", "群組已存在：測試")),
            ("rename to an existing group",
             (lambda r, s: ("POST", L + "groups/rename", {"group": "測試", "new_name": "風景"})),
             (lambda r, s: ["groups", "rename", "測試", "風景"]),
             (lambda r, s: ("darkroom_group_rename", {"group": "測試", "new_name": "風景"})),
             Outcome(False, "conflict", "群組已存在：風景")),
            ("rename an unknown group",
             (lambda r, s: ("POST", L + "groups/rename", {"group": "沒有", "new_name": "x"})),
             (lambda r, s: ["groups", "rename", "沒有", "x"]),
             (lambda r, s: ("darkroom_group_rename", {"group": "沒有", "new_name": "x"})),
             Outcome(False, "not_found", "找不到群組：沒有")),
            ("favorite 1", (lambda r, s: ("POST", L + "favorite", {"preset_id": "p-expo", "favorite": 1})),
             (lambda r, s: ["presets", "favorite", "p-expo", "1"]),
             (lambda r, s: ("darkroom_preset_favorite", {"preset_id": "p-expo", "favorite": 1})),
             Outcome(False, "invalid", "favorite 必須是 true 或 false")),
            ("import batch", (lambda r, s: ("POST", L + "import", {"files": [self.b64(s, n) for n in upload]})),
             (lambda r, s: ["presets", "import", *[os.path.join(s, n) for n in upload]]),
             (lambda r, s: ("darkroom_presets_import", {"paths": [os.path.join(s, n) for n in upload]})), OK),
            ("save, nothing chosen", (lambda r, s: ("POST", L + "save", {"name": "x"})),
             (lambda r, s: ["presets", "save", "--name", "x"]), (lambda r, s: ("darkroom_preset_save", {"name": "x"})),
             Outcome(False, "invalid", "沒有可以存的設定（沒選 preset 也沒有微調）")),
            ("save, strength 250",
             (lambda r, s: ("POST", L + "save", {"name": "x", "preset_id": "p-expo", "strength": 250})),
             (lambda r, s: ["presets", "save", "--name", "x", "--preset", "p-expo", "--strength", "250"]),
             (lambda r, s: ("darkroom_preset_save", {"name": "x", "preset_id": "p-expo", "strength": 250})),
             Outcome(False, "invalid", "strength must be within 0..200, got 250")),
            ("save success",
             (lambda r, s: ("POST", L + "save", {"name": "我的", "preset_id": "p-expo", "strength": 150,
                                                 "overrides": {"Exposure2012": 0.25}})),
             (lambda r, s: ["presets", "save", "--name", "我的", "--preset", "p-expo", "--strength", "150",
                            "--override", "Exposure2012=0.25"]),
             (lambda r, s: ("darkroom_preset_save", {"name": "我的", "preset_id": "p-expo", "strength": 150,
                                                     "overrides": {"Exposure2012": 0.25}})), OK),
        ]
        for name, http, cli, mcp, want in cases:
            got = await self.run_three(http, cli, mcp)
            self.assertEqual(set(got), {"http", "cli", "mcp"}, name)
            self.assertEqual({k: v[0] for k, v in got.items()}, dict.fromkeys(got, want), name)
            results = {k: v[1] for k, v in got.items()}
            self.assertEqual(len({json.dumps(v, sort_keys=True, ensure_ascii=False) for v in results.values()}), 1,
                             (name, results))
            if name == "import batch":
                res = results["http"]["results"]
                self.assertEqual([(x["ok"], x["source"]) for x in res],
                                 [(False, "bad.xmp"), (False, "dup.xmp"), (True, "good.xmp"), (False, "note.txt")])
                self.assertEqual(res[1]["duplicate_of"], "p-expo")
                self.assertEqual(res[2]["id"], "import:good")
            if name == "save success":
                from darkroom_app import preview as semantics
                self.assertEqual(results["http"]["id"], "user:我的")
                d = self.switch.target.preset_detail("user:我的")                # readable afterwards (K13)
                want_p = semantics.effective_params(self.switch.target._library.library.get("p-expo"), 1.5,
                                                    {"Exposure2012": 0.25})
                self.assertEqual(d["values"]["Exposure2012"], want_p.values["Exposure2012"])
                self.assertEqual(d["values"]["Contrast2012"], want_p.values["Contrast2012"])

    async def test_semantic_parity(self):  # CONTRACT-semantic-index SI11: status, build when off, build dry-run
        from test_semantic_index import NEED_KEY, REF, make_sources
        L = "/api/preset-library/semantic"

        def off(root):
            svc = self.switch.target._semantic
            svc.have_anthropic, svc.key_ref, svc.env_key, svc.budget_usd = (lambda: True), None, None, 5.0
            svc.sources_dir = make_sources(os.path.join(root, "sources"))

        def on(root):
            off(root)
            svc = self.switch.target._semantic
            svc.key_ref, svc.key_reader = REF, (lambda ref: "sk-ant-not-used-in-a-dry-run")
            svc.client_factory = lambda api_key: (_ for _ in ()).throw(AssertionError("dry run must not build a client"))
        got = await self.run_three(lambda r, s: ("GET", L), lambda r, s: ["presets", "semantic", "status"],
                                   lambda r, s: ("darkroom_semantic_status", {}), setup=off)
        self.assertEqual({k: v[0] for k, v in got.items()}, dict.fromkeys(got, OK))
        self.assertEqual(len({json.dumps(v[1], sort_keys=True) for v in got.values()}), 1, got)
        self.assertEqual((got["cli"][1]["available"], got["cli"][1]["reason"], got["cli"][1]["indexed"],
                          got["cli"][1]["total"]), (False, NEED_KEY, 0, 5))
        got = await self.run_three(lambda r, s: ("POST", L + "/build", {}),
                                   lambda r, s: ["presets", "semantic", "build", "--wait-seconds", "0"],
                                   lambda r, s: ("darkroom_semantic_build", {}), setup=off)
        self.assertEqual(got["cli"], got["mcp"])
        self.assertEqual(got["cli"][0], Outcome(False, "unavailable", NEED_KEY))
        self.assertEqual(got["http"][0], Outcome(False, "invalid",
                                                 "semantic build is not accepted over HTTP (use the CLI or MCP)"))
        got = await self.run_three(None, lambda r, s: ["presets", "semantic", "build", "--dry-run", "--limit", "2"],
                                   lambda r, s: ("darkroom_semantic_build", {"dry_run": True, "limit": 2}), setup=on)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"cli": OK, "mcp": OK})
        self.assertEqual(got["cli"][1], got["mcp"][1])
        self.assertEqual((got["cli"][1]["state"], got["cli"][1]["planned"]), ("dry_run", 2))
        self.assertGreater(got["cli"][1]["estimated_usd"], 0)
        self.assertEqual(got["cli"][1]["batch_ids"], [])

    async def test_favorites_view_parity(self):  # K9: the favorites view through each interface
        got = {}
        for name in ("http", "cli", "mcp"):
            self.fresh()
            self.switch.target.set_favorite("p-skip", True)
            self.switch.target.set_favorite("p-expo", True)
            if name == "http":
                o, rows = await self.http("GET", "/api/presets?favorites=1")
            elif name == "cli":
                o, res = self.cli(["presets", "list", "--favorites"])
                rows = res["items"]
            else:
                o, res = self.mcp("darkroom_presets_list", {"favorites": True})
                rows = res["items"]
            got[name] = (o, [r["id"] for r in rows], all(r["favorite"] for r in rows))
        self.assertEqual(len({(o, tuple(ids), fav) for o, ids, fav in got.values()}), 1, got)
        self.assertEqual(got["http"][1], ["p-skip", "p-expo"])

    async def test_lock_held_parity(self):  # K15 / K17: the lock is held by someone else -> conflict everywhere
        import msvcrt
        from darkroom_app.services import preset_library as pl
        got = {}
        for name in ("http", "cli", "mcp"):
            root, _ = self.fresh()
            fd = os.open(os.path.join(root, "library.json.lock"), os.O_RDWR | os.O_CREAT | os.O_BINARY)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                with mock.patch.object(pl, "LOCK_WAIT_S", 0.2):
                    if name == "http":
                        got[name] = await self.http("POST", "/api/preset-library/favorite",
                                                    {"preset_id": "p-expo", "favorite": True})
                    elif name == "cli":
                        got[name] = self.cli(["presets", "favorite", "p-expo", "on"])
                    else:
                        got[name] = self.mcp("darkroom_preset_favorite", {"preset_id": "p-expo", "favorite": True})
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)
            self.assertFalse(os.path.exists(os.path.join(root, "library.json")), name)
        self.assertEqual({k: v[0] for k, v in got.items()},
                         dict.fromkeys(got, Outcome(False, "conflict", "preset 庫正被其他程式修改，請稍後再試")))


class TestPhotoLibraryParity(unittest.IsolatedAsyncioTestCase):  # CONTRACT-photo-library PL17, PLP4, PLP6
    """Each scenario runs on its own copy of the photos, its own data_dir and preset library, once per interface."""

    async def asyncSetUp(self):
        from darkroom_app.server import FACADE, make_app
        from test_layering import _NoEngine
        self.tmp = _util.tmpdir(self)
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        make_presets(seed)
        self.switch = _Switch()
        app = make_app(seed, engine=_NoEngine())
        app[FACADE] = self.switch
        self.client = TestClient(TestServer(app), headers=_util.HTTP_HEADERS)   # PLP11
        await self.client.start_server()
        self.n = 0
        self.libs = []

    async def asyncTearDown(self):
        for lib in self.libs:
            lib.wait_thumbnails(60)
        await self.client.close()

    def fresh(self):
        """(photos folder, data_dir): a photo folder copy, an empty data_dir and a fresh facade in the switch."""
        from darkroom_app.composition import build_facade
        self.n += 1
        root = os.path.join(self.tmp, f"case{self.n}")
        pd = os.path.join(root, "lib", "xmp")
        os.makedirs(pd)
        make_presets(pd)
        photos = os.path.join(root, "photos")
        os.makedirs(photos)
        write_photo(os.path.join(photos, "a.jpg"), 400, 300)
        write_photo(os.path.join(photos, "b.jpg"), 400, 300, seed=1)
        write_photo(os.path.join(photos, "c.png"), 200, 150, seed=2)
        with open(os.path.join(photos, "notes.txt"), "w") as fh:
            fh.write("x")
        with open(os.path.join(photos, "broken.jpg"), "wb") as fh:
            fh.write(b"\xff\xd8not a jpeg")
        data = os.path.join(root, "data")
        self.switch.target = build_facade(pd, data_dir=data)
        self.libs.append(self.switch.target._photo_library)
        return photos, data

    # ---------------------------------------------------------------- the three drivers
    async def http(self, method, path, body=None, params=None):
        if method == "GET":
            r = await self.client.get(path, params=params)
        elif method == "DELETE":
            r = await self.client.delete(path, params=params)
        elif method == "PUT":
            r = await self.client.put(path, json=body)
        else:
            r = await self.client.post(path, json=body)
        if r.status == 200 and r.headers["Content-Type"] == "image/jpeg":
            data = await r.read()
            w, h = jpeg_size(data)
            return OK, {"fingerprint": r.headers["X-Fingerprint"], "edited": r.headers["X-Edited"] == "1",
                        "width": w, "height": h}
        data = await r.json()
        if r.status == 200:
            return OK, data
        kind = {v: k for k, v in LIB_HTTP_STATUS.items()}[r.status]
        self.assertEqual(list(data), ["error"])
        return Outcome(False, kind, data["error"]), None

    def cli(self, argv):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv + ["--json"], facade=self.switch)
        self.assertEqual(err.getvalue(), "", argv)
        self.assertEqual(out.getvalue().count("\n"), 1, argv)
        env = json.loads(out.getvalue())
        if env["ok"]:
            res = env["result"]
            partial = isinstance(res, dict) and "results" in res and not all(x["ok"] for x in res["results"])
            self.assertEqual(rc, 6 if partial else 0, argv)                     # PLP4
            if argv[0] == "thumbnail":
                w, h = jpeg_size(base64.b64decode(res.pop("jpeg_base64")))
                self.assertEqual((w, h), (res["width"], res["height"]))
            return OK, res
        self.assertEqual(rc, LIB_CLI_EXIT[env["error"]["kind"]], argv)
        return Outcome(False, env["error"]["kind"], env["error"]["message"]), None

    def mcp(self, tool, arguments):
        from darkroom_app.mcp_server import serve
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode("utf-8") + b"\n"
        out = io.BytesIO()
        serve(io.BytesIO(line), out, facade=self.switch)
        res = json.loads(out.getvalue())["result"]
        sc = res["structuredContent"]
        if res.get("isError"):
            return Outcome(False, sc["kind"], sc["message"]), None
        self.assertNotIn("isError", res)
        if tool == "darkroom_edit_paste":                                         # PLP4
            self.assertEqual(sc["failed"], sum(1 for x in sc["results"] if not x["ok"]))
            sc = {"results": sc["results"]}
        if tool == "darkroom_thumbnail":
            w, h = jpeg_size(base64.b64decode(res["content"][0]["data"]))
            self.assertEqual((w, h), (sc["width"], sc["height"]))
        return OK, sc

    async def run_three(self, http, cli, mcp, setup=None):
        got, folders = {}, {}
        for name, call in (("http", http), ("cli", cli), ("mcp", mcp)):
            if call is None:
                continue
            photos, data = self.fresh()
            if setup:
                setup(photos, data)
            before = snapshot(photos)
            names = sorted(os.listdir(photos))
            if name == "http":
                got[name] = await self.http(*call(photos, data))
            elif name == "cli":
                got[name] = self.cli(call(photos, data))
            else:
                got[name] = self.mcp(*call(photos, data))
            self.switch.target._photo_library.wait_thumbnails(60)
            self.assertEqual(snapshot(photos), before, name)                     # PL14: the photo folder is read only
            self.assertEqual(sorted(os.listdir(photos)), names, name)
            folders[name] = photos
        return got

    @staticmethod
    def seed_edit(photos, data, name="a.jpg"):
        from darkroom_app.composition import build_facade
        pd = os.path.join(os.path.dirname(photos), "lib", "xmp")
        f = build_facade(pd, data_dir=data)
        return f.set_edit(os.path.join(photos, name), "p-expo", 130, {"Exposure2012": 0.2})

    @staticmethod
    def write_edit_file(photos, data, raw):
        import hashlib
        with open(os.path.join(photos, "a.jpg"), "rb") as fh:
            fp = hashlib.sha256(fh.read()).hexdigest()
        folder = os.path.join(data, "edits", fp[:2])
        os.makedirs(folder)
        with open(os.path.join(folder, fp + ".json"), "wb") as fh:
            fh.write(raw)
        return os.path.join(folder, fp + ".json")

    async def test_photo_library_parity(self):
        p = lambda photos, n: os.path.join(photos, n)
        E = "/api/edit"
        cases = [
            ("get, missing file", (lambda ph, d: ("GET", E, None, {"path": p(ph, "gone.jpg")})),
             (lambda ph, d: ["edit", "get", p(ph, "gone.jpg")]),
             (lambda ph, d: ("darkroom_edit_get", {"path": p(ph, "gone.jpg")})),
             lambda ph: Outcome(False, "not_found", f"photo not found: {p(ph, 'gone.jpg')}"), None),
            ("get, .txt", (lambda ph, d: ("GET", E, None, {"path": p(ph, "notes.txt")})),
             (lambda ph, d: ["edit", "get", p(ph, "notes.txt")]),
             (lambda ph, d: ("darkroom_edit_get", {"path": p(ph, "notes.txt")})),
             lambda ph: Outcome(False, "invalid", "unsupported photo format (JPEG/PNG/TIFF/HEIC)"), None),
            ("get, no edit", (lambda ph, d: ("GET", E, None, {"path": p(ph, "a.jpg")})),
             (lambda ph, d: ["edit", "get", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_get", {"path": p(ph, "a.jpg")})), lambda ph: OK, None),
            ("set, strength 250",
             (lambda ph, d: ("PUT", E, {"path": p(ph, "a.jpg"), "preset_id": "p-expo", "strength": 250})),
             (lambda ph, d: ["edit", "set", p(ph, "a.jpg"), "--preset", "p-expo", "--strength", "250"]),
             (lambda ph, d: ("darkroom_edit_set", {"path": p(ph, "a.jpg"), "preset_id": "p-expo", "strength": 250})),
             lambda ph: Outcome(False, "invalid", "strength must be within 0..200, got 250"), None),
            ("set, unknown slider key",
             (lambda ph, d: ("PUT", E, {"path": p(ph, "a.jpg"), "overrides": {"Bogus": 1}})),
             (lambda ph, d: ["edit", "set", p(ph, "a.jpg"), "--override", "Bogus=1"]),
             (lambda ph, d: ("darkroom_edit_set", {"path": p(ph, "a.jpg"), "overrides": {"Bogus": 1}})),
             lambda ph: Outcome(False, "invalid", "unknown slider key 'Bogus'"), None),
            ("set, unknown preset",
             (lambda ph, d: ("PUT", E, {"path": p(ph, "a.jpg"), "preset_id": "nope"})),
             (lambda ph, d: ["edit", "set", p(ph, "a.jpg"), "--preset", "nope"]),
             (lambda ph, d: ("darkroom_edit_set", {"path": p(ph, "a.jpg"), "preset_id": "nope"})),
             lambda ph: Outcome(False, "not_found", "unknown or unsupported preset nope"), None),
            ("set success",
             (lambda ph, d: ("PUT", E, {"path": p(ph, "a.jpg"), "preset_id": "p-expo", "strength": 150,
                                        "overrides": {"Exposure2012": 0.25}})),
             (lambda ph, d: ["edit", "set", p(ph, "a.jpg"), "--preset", "p-expo", "--strength", "150",
                             "--override", "Exposure2012=0.25"]),
             (lambda ph, d: ("darkroom_edit_set", {"path": p(ph, "a.jpg"), "preset_id": "p-expo", "strength": 150,
                                                   "overrides": {"Exposure2012": 0.25}})), lambda ph: OK, None),
            ("set, empty edit becomes null",
             (lambda ph, d: ("PUT", E, {"path": p(ph, "a.jpg"), "preset_id": None, "overrides": {}})),
             (lambda ph, d: ["edit", "set", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_set", {"path": p(ph, "a.jpg")})), lambda ph: OK, self.seed_edit),
            ("clear (idempotent)", (lambda ph, d: ("DELETE", E, None, {"path": p(ph, "a.jpg")})),
             (lambda ph, d: ["edit", "clear", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_clear", {"path": p(ph, "a.jpg")})), lambda ph: OK, None),
            ("paste, source and edit",
             (lambda ph, d: ("POST", E + "/paste", {"targets": [p(ph, "b.jpg")], "source": p(ph, "a.jpg"), "edit": {}})),
             None,
             (lambda ph, d: ("darkroom_edit_paste", {"targets": [p(ph, "b.jpg")], "source": p(ph, "a.jpg"), "edit": {}})),
             lambda ph: Outcome(False, "invalid", "source 與 edit 要恰好給一個"), None),
            ("paste, source has no edit",
             (lambda ph, d: ("POST", E + "/paste", {"targets": [p(ph, "b.jpg")], "source": p(ph, "a.jpg")})),
             (lambda ph, d: ["edit", "paste", "--from", p(ph, "a.jpg"), p(ph, "b.jpg")]),
             (lambda ph, d: ("darkroom_edit_paste", {"targets": [p(ph, "b.jpg")], "source": p(ph, "a.jpg")})),
             lambda ph: Outcome(False, "not_found", "這張照片沒有編輯：a.jpg"), None),
            ("paste, targets empty",
             (lambda ph, d: ("POST", E + "/paste", {"targets": [], "source": p(ph, "a.jpg")})),
             (lambda ph, d: ["edit", "paste", "--from", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_paste", {"targets": [], "source": p(ph, "a.jpg")})),
             lambda ph: Outcome(False, "invalid", "targets 要是 1～500 個照片路徑"), self.seed_edit),
            ("paste, one good one bad",
             (lambda ph, d: ("POST", E + "/paste", {"targets": [p(ph, "b.jpg"), p(ph, "gone.jpg")], "source": p(ph, "a.jpg")})),
             (lambda ph, d: ["edit", "paste", "--from", p(ph, "a.jpg"), p(ph, "b.jpg"), p(ph, "gone.jpg")]),
             (lambda ph, d: ("darkroom_edit_paste", {"targets": [p(ph, "b.jpg"), p(ph, "gone.jpg")], "source": p(ph, "a.jpg")})),
             lambda ph: OK, self.seed_edit),
            ("edit file darkroom-edit/9", (lambda ph, d: ("GET", E, None, {"path": p(ph, "a.jpg")})),
             (lambda ph, d: ["edit", "get", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_get", {"path": p(ph, "a.jpg")})),
             lambda ph: Outcome(False, "conflict", "編輯檔版本不支援：darkroom-edit/9（a.jpg）"),
             lambda ph, d: self.write_edit_file(ph, d, b'{"schema": "darkroom-edit/9"}')),
            ("edit file broken", (lambda ph, d: ("PUT", E, {"path": p(ph, "a.jpg"), "preset_id": "p-expo"})),
             (lambda ph, d: ["edit", "set", p(ph, "a.jpg"), "--preset", "p-expo"]),
             (lambda ph, d: ("darkroom_edit_set", {"path": p(ph, "a.jpg"), "preset_id": "p-expo"})),
             lambda ph: Outcome(False, "unavailable", "照片庫的編輯檔損壞：" + os.path.join(
                 os.path.dirname(ph), "data", "edits", "{fp2}", "{fp}.json")),
             lambda ph, d: self.write_edit_file(ph, d, b"{broken")),
            ("thumbnails, folder missing",
             (lambda ph, d: ("GET", "/api/folder/thumbnails", None, {"folder": p(ph, "nope")})),
             (lambda ph, d: ["thumbnails", p(ph, "nope")]),
             (lambda ph, d: ("darkroom_folder_thumbnails", {"folder": p(ph, "nope")})),
             lambda ph: Outcome(False, "not_found", f"找不到照片資料夾：{p(ph, 'nope')}"), None),
            ("thumbnails, limit 0",
             (lambda ph, d: ("GET", "/api/folder/thumbnails", None, {"folder": ph, "limit": "0"})),
             (lambda ph, d: ["thumbnails", ph, "--limit", "0"]),
             (lambda ph, d: ("darkroom_folder_thumbnails", {"folder": ph, "limit": 0})),
             lambda ph: Outcome(False, "invalid", "limit must be an integer in 1..200"), None),
            ("thumbnails success",
             (lambda ph, d: ("GET", "/api/folder/thumbnails", None, {"folder": ph})),
             (lambda ph, d: ["thumbnails", ph]),
             (lambda ph, d: ("darkroom_folder_thumbnails", {"folder": ph})), lambda ph: OK, self.seed_edit),
            ("thumbnail, broken JPEG",
             (lambda ph, d: ("GET", "/api/thumbnail", None, {"path": p(ph, "broken.jpg")})),
             (lambda ph, d: ["thumbnail", p(ph, "broken.jpg")]),
             (lambda ph, d: ("darkroom_thumbnail", {"path": p(ph, "broken.jpg")})),
             lambda ph: ("invalid", "縮圖產生失敗：broken.jpg："), None),
            ("thumbnail success",
             (lambda ph, d: ("GET", "/api/thumbnail", None, {"path": p(ph, "a.jpg")})),
             (lambda ph, d: ["thumbnail", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_thumbnail", {"path": p(ph, "a.jpg")})), lambda ph: OK, self.seed_edit),
            ("save-preset, no edit",
             (lambda ph, d: ("POST", E + "/save-preset", {"path": p(ph, "b.jpg"), "name": "x"})),
             (lambda ph, d: ["edit", "save-preset", p(ph, "b.jpg"), "--name", "x"]),
             (lambda ph, d: ("darkroom_edit_save_preset", {"path": p(ph, "b.jpg"), "name": "x"})),
             lambda ph: Outcome(False, "not_found", "這張照片沒有編輯：b.jpg"), None),
            ("save-preset success",
             (lambda ph, d: ("POST", E + "/save-preset", {"path": p(ph, "a.jpg"), "name": "快照", "group": "A - B"})),
             (lambda ph, d: ["edit", "save-preset", p(ph, "a.jpg"), "--name", "快照", "--group", "A - B"]),
             (lambda ph, d: ("darkroom_edit_save_preset", {"path": p(ph, "a.jpg"), "name": "快照", "group": "A - B"})),
             lambda ph: OK, self.seed_edit),
        ]
        import hashlib
        for name, http, cli, mcp, want, setup in cases:
            photos_of = {}
            orig_fresh = self.fresh

            def fresh_recording():
                r = orig_fresh()
                photos_of[len(photos_of)] = r[0]
                return r
            self.fresh = fresh_recording
            got = await self.run_three(http, cli, mcp, setup)
            self.fresh = orig_fresh
            drivers = {"http", "cli", "mcp"} - ({"cli"} if cli is None else set())
            self.assertEqual(set(got), drivers, name)
            for i, (dname, (o, res)) in enumerate(got.items()):
                ph = photos_of[i]
                w = want(ph)
                if isinstance(w, tuple) and not isinstance(w, Outcome):          # a prefix (the reason varies)
                    self.assertEqual((o.ok, o.kind), (False, w[0]), (name, dname))
                    self.assertTrue(o.message.startswith(w[1]), (name, dname, o.message))
                elif "{fp}" in (w.message or ""):
                    with open(os.path.join(ph, "a.jpg"), "rb") as fh:
                        fp = hashlib.sha256(fh.read()).hexdigest()
                    self.assertEqual(o, w._replace(message=w.message.replace("{fp2}", fp[:2]).replace("{fp}", fp)),
                                     (name, dname))
                else:
                    self.assertEqual(o, w, (name, dname))
            results = {k: self.normalized(v[1], photos_of[i]) for i, (k, v) in enumerate(got.items())
                       if v[1] is not None}
            self.assertEqual(len({json.dumps(v, sort_keys=True, ensure_ascii=False) for v in results.values()}),
                             1 if results else 0, (name, results))
            if name == "set success":
                e = results["http"]["edit"]
                self.assertEqual((e["preset"]["id"], e["strength"], e["overrides"], results["http"]["preset_status"]),
                                 ("p-expo", 150, {"Exposure2012": 0.25}, "current"))
            if name == "set, empty edit becomes null":
                self.assertEqual((results["http"]["edit"], results["http"]["preset_status"]), (None, None))
            if name == "paste, one good one bad":
                self.assertEqual([(r["ok"], r["target"]) for r in results["http"]["results"]],
                                 [(True, "b.jpg"), (False, "gone.jpg")])
            if name == "thumbnails success":
                self.assertEqual([(i["name"], i["fingerprint"], i["edited"], i["cached"]) for i in results["http"]["items"]],
                                 [(n, None, None, False) for n in ("a.jpg", "b.jpg", "broken.jpg", "c.png")])  # no index yet
            if name == "thumbnail success":
                self.assertEqual((results["http"]["edited"], results["http"]["width"], results["http"]["height"]),
                                 (True, 256, 192))
            if name == "save-preset success":
                self.assertEqual(results["http"], {"id": "user:快照", "name": "快照", "group": "A - B", "file": "user/快照.xmp"})

    @staticmethod
    def normalized(res, photos):
        """Driver-independent view: every copy has its own photo folder, so that path becomes <photos>."""
        if isinstance(res, dict) and "items" in res:
            res = {"items": [{k: v for k, v in i.items() if k != "path"} for i in res["items"]],
                   "total": res["total"], "next_offset": res["next_offset"]}
        text = json.dumps(res, ensure_ascii=False).replace(json.dumps(photos)[1:-1], "<photos>")
        return json.loads(text)

    async def test_edit_set_then_get_matches_everywhere(self):  # PL17: set through each interface, get agrees
        for name in ("http", "cli", "mcp"):
            photos, data = self.fresh()
            a = os.path.join(photos, "a.jpg")
            if name == "http":
                o, res = await self.http("PUT", "/api/edit", {"path": a, "preset_id": "p-skip", "strength": 80})
            elif name == "cli":
                o, res = self.cli(["edit", "set", a, "--preset", "p-skip", "--strength", "80"])
            else:
                o, res = self.mcp("darkroom_edit_set", {"path": a, "preset_id": "p-skip", "strength": 80})
            self.assertEqual(o, OK, name)
            o2, got = await self.http("GET", "/api/edit", None, {"path": a})
            self.assertEqual((o2, got), (OK, res), name)
            self.assertEqual(self.cli(["edit", "get", a])[1], res, name)
            self.assertEqual(self.mcp("darkroom_edit_get", {"path": a})[1], res, name)


class TestPhotoLibrarySubprocessSmoke(unittest.TestCase):  # PL17: real processes, CLI edit set -> edit get, MCP edit get
    def setUp(self):
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.photo = write_photo(os.path.join(self.photos, "a.jpg"), 320, 240)
        self.data = os.path.join(self.tmp, "data")
        self.env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}

    def run_cli(self, *argv):
        return subprocess.run([*_util.guarded_python(), "-m", "darkroom_app.cli", "--preset-dir", self.presets,
                               "--data-dir", self.data, *argv, "--json"], cwd=_util.REPO, capture_output=True,
                              env=self.env, timeout=120)

    def test_cli_edit_set_then_get(self):
        r = self.run_cli("edit", "set", self.photo, "--preset", "p-expo", "--strength", "140", "--override", "Contrast2012=5")
        self.assertEqual((r.returncode, r.stderr), (0, b""), r.stderr)
        env = json.loads(r.stdout.decode("utf-8"))
        self.assertTrue(env["ok"])
        r2 = self.run_cli("edit", "get", self.photo)
        self.assertEqual((r2.returncode, r2.stderr), (0, b""))
        self.assertEqual(json.loads(r2.stdout.decode("utf-8")), env)
        self.assertEqual(env["result"]["edit"]["strength"], 140)
        r3 = self.run_cli("edit", "paste", "--from", self.photo, self.photo, os.path.join(self.photos, "gone.jpg"))
        self.assertEqual((r3.returncode, r3.stderr), (6, b""))                   # PLP4: one target failed
        self.assertEqual([x["ok"] for x in json.loads(r3.stdout)["result"]["results"]], [True, False])
        self.assertEqual(sorted(os.listdir(self.photos)), ["a.jpg"])

    def test_mcp_edit_get(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "darkroom_edit_set", "arguments": {"path": self.photo, "preset_id": "p-expo"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "darkroom_edit_get", "arguments": {"path": self.photo}}}]
        data = b"".join(json.dumps(m).encode() + b"\n" for m in msgs)
        r = subprocess.run([*_util.guarded_python(), "-m", "darkroom_app.mcp_server", "--preset-dir", self.presets,
                            "--data-dir", self.data], cwd=_util.REPO, input=data, capture_output=True, env=self.env,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        res = [json.loads(x) for x in r.stdout.decode("utf-8").split("\n") if x]
        self.assertEqual([x["id"] for x in res], [1, 2])
        self.assertEqual(res[0]["result"]["structuredContent"], res[1]["result"]["structuredContent"])
        self.assertEqual(res[1]["result"]["structuredContent"]["edit"]["preset"]["id"], "p-expo")
        self.assertNotIn("isError", res[1]["result"])
        self.assertTrue(os.path.isdir(os.path.join(self.data, "edits")))


class TestSubprocessSmoke(unittest.TestCase):  # L11: one real-process run per interface
    def setUp(self):
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}

    def test_cli_json_smoke(self):
        r = subprocess.run([*_util.guarded_python(), "-m", "darkroom_app.cli", "--preset-dir", self.presets,
                            "presets", "show", "nope", "--json"], cwd=_util.REPO, capture_output=True,
                           env=self.env, timeout=120)
        self.assertEqual((r.returncode, r.stderr), (3, b""))
        self.assertEqual(r.stdout, b'{"ok":false,"error":{"kind":"not_found","message":"unknown preset nope"}}\n')

    def test_mcp_legacy_and_discover_smoke(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "darkroom_preset_show", "arguments": {"preset_id": "nope"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "server/discover",
                 "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "darkroom_preset_show", "arguments": {"preset_id": "nope"},
                            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}}]
        data = b"".join(json.dumps(m).encode() + b"\n" for m in msgs)
        r = subprocess.run([*_util.guarded_python(), "-m", "darkroom_app.mcp_server", "--preset-dir", self.presets],
                           cwd=_util.REPO, input=data, capture_output=True, env=self.env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertNotIn(b"\r", r.stdout)
        res = [json.loads(x) for x in r.stdout.decode("utf-8").split("\n") if x]
        self.assertEqual([x["id"] for x in res], [1, 2, 3, 4])
        self.assertEqual(res[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(res[1]["result"]["content"][0]["text"], "unknown preset nope")
        self.assertEqual(res[2]["result"]["supportedVersions"], ["2026-07-28"])
        self.assertEqual(res[3]["result"]["resultType"], "complete")
        self.assertEqual(res[3]["result"]["structuredContent"]["message"], "unknown preset nope")


if __name__ == "__main__":
    unittest.main()
