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
import hashlib
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
        self.f = build_facade(self.presets, engine=eng, data_dir=os.path.join(self.tmp, "data"))   # S2 E15 / G7
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
            ("format bmp", lambda d: d.export([{"path": jpeg}], "bmp", dest_dir=fresh()),   # XP31: png is a format now
             Outcome(False, "invalid", "不支援的匯出格式：bmp（可用 jpeg、png、tiff、webp）"), None),   # XP31
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
        from darkroom_app.adapters.persist import locks
        got = {}
        for name in ("http", "cli", "mcp"):
            root, _ = self.fresh()
            fd = os.open(os.path.join(root, "library.json.lock"), os.O_RDWR | os.O_CREAT | os.O_BINARY)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                with mock.patch.object(locks, "LOCK_WAIT_S", 0.2):
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
    def seed_cleared(photos, data, name="a.jpg"):   # S4: an edit that was set and then cleared (kept as previous)
        from darkroom_app.composition import build_facade
        pd = os.path.join(os.path.dirname(photos), "lib", "xmp")
        f = build_facade(pd, data_dir=data)
        f.set_edit(os.path.join(photos, name), "p-expo", 130, {"Exposure2012": 0.2})
        return f.clear_edit(os.path.join(photos, name))

    @staticmethod
    def seed_cleared_then_edited(photos, data, name="a.jpg"):   # S4a: a previous edit kept, then a new edit made
        from darkroom_app.composition import build_facade
        pd = os.path.join(os.path.dirname(photos), "lib", "xmp")
        f = build_facade(pd, data_dir=data)
        p = os.path.join(photos, name)
        f.set_edit(p, "p-expo", 130, {"Exposure2012": 0.2})
        f.clear_edit(p)
        return f.set_edit(p, "p-expo", 60)

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
            ("restore, nothing kept", (lambda ph, d: ("POST", E + "/restore", {"path": p(ph, "a.jpg")})),   # S4
             (lambda ph, d: ["edit", "restore", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_restore", {"path": p(ph, "a.jpg")})),
             lambda ph: Outcome(False, "not_found", "這張照片沒有上一份編輯可以取回：a.jpg"), None),
            ("restore after clear", (lambda ph, d: ("POST", E + "/restore", {"path": p(ph, "a.jpg")})),   # S4
             (lambda ph, d: ["edit", "restore", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_restore", {"path": p(ph, "a.jpg")})), lambda ph: OK, self.seed_cleared),
            ("restore over another edit", (lambda ph, d: ("POST", E + "/restore", {"path": p(ph, "a.jpg")})),   # S4a
             (lambda ph, d: ["edit", "restore", p(ph, "a.jpg")]),
             (lambda ph, d: ("darkroom_edit_restore", {"path": p(ph, "a.jpg")})),
             lambda ph: Outcome(False, "conflict", "這張照片已經有別的編輯，取回上一份會蓋掉它；要取回請先還原成原圖：a.jpg"),
             self.seed_cleared_then_edited),
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


S2_FEATURES = ("gpu", "heic", "webp", "photo_library", "preset_library_writes", "semantic_index", "onepassword",
               "comfyui", "agent_sdk")                                            # + plan-v2 §3
NO_WEBP = "這台電腦的 OpenCV 不能寫 WebP，WebP 匯出先關閉"                                 # verbatim (S2 E23)
LIB_IN_PHOTOS = ("preset 庫的位置 {root} 在照片資料夾裡（{photo_folder} 有照片），為了不在照片資料夾裡寫檔，整理 preset、"
                 "匯入、存成 preset 先關閉；請在 config.local.json 把 preset_library_dir 設到別的資料夾")   # verbatim (S2 E23)
SETTING_FLAGS = (("format", "--format"), ("bit_depth", "--bit-depth"), ("quality", "--quality"), ("max_kb", "--max-kb"),
                 ("metadata", "--metadata"), ("export_preset", "--export-preset"))


def _no_op_detect(**more):
    """Every facade here: the two items that could reach `op` are fakes (tests never run op)."""
    return {"semantic_index": lambda: (False, "假的語意索引"), "onepassword": lambda: (False, "假的 1Password"), **more}


class TestS2Parity(unittest.IsolatedAsyncioTestCase):  # CONTRACT-s2-export-detect E31
    """Every scenario, once per interface, on that driver's own data_dir, photo copy, preset library and dest_dir
    (HTTP: the default export folder); outcomes and results agree."""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(7)
        cls.shot = cv2.imencode(".jpg", (rng.random((1000, 1500, 3)) * 255).astype(np.uint8))[1].tobytes()

    async def asyncSetUp(self):
        from darkroom_app import engine as engine_mod
        from darkroom_app.server import FACADE, make_app
        self.eng = engine_mod.Engine()          # the app's cleanup shuts it down
        self.tmp = _util.tmpdir(self)
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        make_presets(seed)
        self.switch = _Switch()
        app = make_app(seed, engine=self.eng)
        app[FACADE] = self.switch
        self.client = TestClient(TestServer(app), headers=_util.HTTP_HEADERS)
        await self.client.start_server()
        self.n = 0

    async def asyncTearDown(self):
        await self.client.close()

    def fresh(self, detect=None):
        """A new world: <root>/lib/xmp (library root <root>/lib), photos/shot.jpg, data/, dest/."""
        from darkroom_app.composition import build_facade
        self.n += 1
        root = os.path.join(self.tmp, f"w{self.n}")
        ctx = {"root": root, "lib": os.path.join(root, "lib"), "pd": os.path.join(root, "lib", "xmp"),
               "photos": os.path.join(root, "photos"), "data": os.path.join(root, "data"),
               "dest": os.path.join(root, "dest")}
        for k in ("pd", "photos", "dest"):
            os.makedirs(ctx[k])
        make_presets(ctx["pd"])
        ctx["photo"] = os.path.join(ctx["photos"], "shot.jpg")
        with open(ctx["photo"], "wb") as fh:
            fh.write(self.shot)
        self.switch.target = build_facade(ctx["pd"], engine=self.eng, data_dir=ctx["data"],
                                          detect=_no_op_detect(**(detect or {})))
        return ctx

    # ---------------------------------------------------------------- drivers
    async def http(self, method, path, body=None, params=None):
        r = await self.client.request(method, path, json=body, params=params)
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
            rows = res.get("results", res.get("files")) if isinstance(res, dict) else None
            partial = rows is not None and isinstance(rows, list) and not all(x["ok"] for x in rows)
            self.assertEqual(rc, 6 if partial else 0, argv)
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
            self.assertEqual(res["content"], [{"type": "text", "text": sc["message"]}])
            return Outcome(False, sc["kind"], sc["message"]), None
        self.assertNotIn("isError", res)
        if tool in ("darkroom_export", "darkroom_presets_export"):              # XP11
            self.assertEqual(sc["failed"], sum(1 for x in sc["results"] if not x["ok"]))
            sc = {"results": sc["results"]}
        return OK, sc

    # ---------------------------------------------------------------- export through each interface
    def export_cli_argv(self, ctx, items, settings):
        argv = ["export", *[it["path"] for it in items]]
        if any("preset_id" in it for it in items):
            argv.append("--no-edit")
        for key, flag in SETTING_FLAGS:
            if settings.get(key) is not None:
                argv += [flag, str(settings[key])]
        if settings.get("resize") is not None:
            argv += ["--resize", f"{settings['resize']['mode']}={settings['resize']['value']}"]
        if settings.get("sharpen") is not None:
            argv += ["--sharpen", f"{settings['sharpen']['target']}={settings['sharpen']['amount']}"]
        if settings.get("remove_gps"):
            argv.append("--remove-gps")
        return argv + ["--dest-dir", ctx["dest"]]

    async def export_three(self, settings, items=None, before=None, detect=None):
        """{driver: (outcome, [(ok, basename or error, used, sha256 of the file)])}."""
        import hashlib
        got = {}
        for name in ("http", "cli", "mcp"):
            ctx = self.fresh(detect)
            if before:
                before(ctx)
            its = items(ctx) if items else [{"path": ctx["photo"]}]
            if name == "http":
                o, res = await self.http("POST", "/api/export", {"items": its, **settings})
            elif name == "cli":
                o, res = self.cli(self.export_cli_argv(ctx, its, settings))
            else:
                o, res = self.mcp("darkroom_export", {"items": its, **settings, "dest_dir": ctx["dest"]})
            rows = None
            if o.ok:
                self.assertEqual(list(res), ["results"])
                rows = []
                for r in res["results"]:
                    if r["ok"]:
                        want_dir = os.path.join(ctx["photos"], "darkroom 匯出") if name == "http" else ctx["dest"]
                        self.assertEqual(os.path.dirname(r["output"]), want_dir, name)
                        with open(r["output"], "rb") as fh:
                            digest = hashlib.sha256(fh.read()).hexdigest()
                        rows.append((True, os.path.basename(r["output"]), r["used"], digest))
                    else:
                        rows.append((False, r["error"], None, None))
            got[name] = (o, rows)
        return got

    def assert_same(self, got, name):
        self.assertEqual(set(got), {"http", "cli", "mcp"}, name)
        self.assertEqual(len({json.dumps(v, sort_keys=True, ensure_ascii=False, default=str) for v in got.values()}),
                         1, (name, got))
        return next(iter(got.values()))

    async def test_s2_export_parity(self):  # E31: settings errors, WebP switched off, successes, saved edits
        cases = [
            ("format bmp", {"format": "bmp"}, Outcome(False, "invalid", "不支援的匯出格式：bmp（可用 jpeg、png、tiff、webp）")),
            ("bit_depth 16 + jpeg", {"format": "jpeg", "bit_depth": 16},
             Outcome(False, "invalid", "JPEG 只能輸出 8-bit：16")),
            ("quality 0 + webp", {"format": "webp", "quality": 0}, Outcome(False, "invalid", "WebP 品質要在 1～100 之間：0")),
            ("max_kb + png", {"format": "png", "max_kb": 800}, Outcome(False, "invalid", "檔案大小上限只適用於 JPEG")),
            ("resize mode wrong", {"resize": {"mode": "diagonal", "value": 10}},
             Outcome(False, "invalid", "不支援的尺寸方式：diagonal（可用 long_edge、short_edge、width、height、megapixels、percent）")),
            ("percent 150", {"resize": {"mode": "percent", "value": 150}},
             Outcome(False, "invalid", "percent 的值要是大於 0、不超過 100 的數（不會放大）：150")),
            ("metadata wrong", {"metadata": "some"},
             Outcome(False, "invalid", "不支援的中繼資料選項：some（可用 all、copyright、none）")),
            ("sharpen amount wrong", {"sharpen": {"target": "screen", "amount": "max"}},
             Outcome(False, "invalid", "不支援的銳利化強度：max（可用 low、standard、high）")),
            ("export_preset missing", {"export_preset": "nope"}, Outcome(False, "not_found", "找不到匯出預設：nope")),
        ]
        for name, settings, want in cases:
            got = await self.export_three(settings)
            self.assertEqual(self.assert_same(got, name), (want, None), name)
        got = await self.export_three({"format": "webp"}, detect={"webp": lambda: (False, NO_WEBP)})
        self.assertEqual(self.assert_same(got, "webp off"), (Outcome(False, "unavailable", NO_WEBP), None))
        got = await self.export_three({"format": "png", "bit_depth": 16})
        o, rows = self.assert_same(got, "png 16")
        self.assertEqual((o, [r[:3] for r in rows]), (OK, [(True, "shot.png", {"params_from": "original",
                                                                                "quality": None, "width": 1500,
                                                                                "height": 1000})]))
        got = await self.export_three({"resize": {"mode": "long_edge", "value": 1000}})
        o, rows = self.assert_same(got, "long_edge 1000")
        self.assertEqual((o, [r[:3] for r in rows]), (OK, [(True, "shot.jpg", {"params_from": "original",
                                                                                "quality": 92, "width": 1000,
                                                                                "height": 667})]))
        # a saved edit and nothing else: every interface exports it, byte for byte the same file
        got = await self.export_three({}, before=lambda c: self.switch.target.set_edit(c["photo"], "p-expo", 80))
        o, rows = self.assert_same(got, "saved edit")
        self.assertEqual((o, rows[0][2]["params_from"]), (OK, "edit"))
        got_orig = await self.export_three({})
        o, orig = self.assert_same(got_orig, "no edit")
        self.assertEqual(orig[0][2]["params_from"], "original")
        self.assertNotEqual(orig[0][3], rows[0][3])                              # the edit really changed the pixels
        got = await self.export_three({}, items=lambda c: [{"path": c["photo"], "preset_id": None}],
                                      before=lambda c: self.switch.target.set_edit(c["photo"], "p-expo", 80))
        o, req = self.assert_same(got, "preset_id null")
        self.assertEqual((req[0][2]["params_from"], req[0][3]), ("request", orig[0][3]))   # null = the original

    async def test_s2_export_presets_parity(self):  # E31: save -> list -> delete, the same results everywhere
        got = {}
        for name in ("http", "cli", "mcp"):
            self.fresh()
            if name == "http":
                steps = [await self.http("PUT", "/api/export-presets", {"name": "網頁",
                                                                        "settings": {"format": "jpeg", "max_kb": 800}}),
                         await self.http("GET", "/api/export-presets"),
                         await self.http("DELETE", "/api/export-presets", params={"name": "網頁"}),
                         await self.http("DELETE", "/api/export-presets", params={"name": "網頁"})]
            elif name == "cli":
                steps = [self.cli(["export-presets", "save", "--name", "網頁", "--format", "jpeg", "--max-kb", "800"]),
                         self.cli(["export-presets", "list"]), self.cli(["export-presets", "delete", "網頁"]),
                         self.cli(["export-presets", "delete", "網頁"])]
            else:
                steps = [self.mcp("darkroom_export_preset_save", {"name": "網頁",
                                                                  "settings": {"format": "jpeg", "max_kb": 800}}),
                         self.mcp("darkroom_export_presets_list", {}),
                         self.mcp("darkroom_export_preset_delete", {"name": "網頁"}),
                         self.mcp("darkroom_export_preset_delete", {"name": "網頁"})]
            got[name] = steps
        steps = self.assert_same(got, "export presets")
        self.assertEqual(steps[0][1]["previous"], None)
        self.assertEqual(steps[1][1]["presets"][0]["name"], "網頁")
        self.assertEqual(steps[2][1]["settings"], steps[0][1]["settings"])
        self.assertEqual(steps[3], (Outcome(False, "not_found", "找不到匯出預設：網頁"), None))

    async def test_s2_preset_files_parity(self):  # E31: one unknown, one known; files to a folder (CLI / MCP)
        got = {}
        for name in ("http", "cli", "mcp"):
            self.fresh()
            if name == "http":
                got[name] = await self.http("POST", "/api/preset-library/files", {"preset_ids": ["nope", "p-expo"]})
            elif name == "cli":
                got[name] = self.cli(["presets", "files", "nope", "p-expo"])
            else:
                got[name] = self.mcp("darkroom_preset_files", {"preset_ids": ["nope", "p-expo"]})
        o, res = self.assert_same(got, "preset files")
        self.assertEqual([(f["ok"], f.get("file_name"), f.get("error")) for f in res["files"]],
                         [(False, None, "unknown preset nope"), (True, "曝光一.xmp", None)])
        got = {}
        for name in ("cli", "mcp"):
            ctx = self.fresh()
            with open(os.path.join(ctx["dest"], "曝光一.xmp"), "wb") as fh:
                fh.write(b"someone else's file")
            if name == "cli":
                o, res = self.cli(["presets", "export", "p-expo", "nope", "--dest-dir", ctx["dest"]])
            else:
                o, res = self.mcp("darkroom_presets_export", {"preset_ids": ["p-expo", "nope"], "dest_dir": ctx["dest"]})
            with open(os.path.join(ctx["dest"], "曝光一.xmp"), "rb") as fh:
                self.assertEqual(fh.read(), b"someone else's file")              # never overwritten
            got[name] = (o, [(r["ok"], os.path.basename(r["output"]) if r["ok"] else r["error"])
                             for r in res["results"]])
        self.assertEqual(got["cli"], got["mcp"])
        self.assertEqual(got["cli"], (OK, [(True, "曝光一 (2).xmp"), (False, "unknown preset nope")]))
        ctx = self.fresh()
        o, _ = await self.http("POST", "/api/preset-library/export", {"preset_ids": ["p-expo"], "dest_dir": ctx["dest"]})
        self.assertEqual(o, Outcome(False, "invalid", "preset export to a folder is not accepted over HTTP (use the CLI "
                                                      "or MCP; the page downloads the files)"))
        self.assertEqual(os.listdir(ctx["dest"]), [])

    async def test_s2_capabilities_parity(self):  # E31: the same injected detectors give the same answer
        detect = {"gpu": lambda: (False, "沒有偵測到可用的 NVIDIA 顯示卡（CUDA），預覽與匯出改用 CPU，會慢很多"),
                  "heic": lambda: (True, None), "webp": lambda: (False, NO_WEBP),
                  "photo_library": lambda: (True, None), "preset_library_writes": lambda: (True, "ignored")}
        got = {}
        for name in ("http", "cli", "mcp"):
            self.fresh(detect)
            if name == "http":
                got[name] = await self.http("GET", "/api/capabilities", params={"refresh": "1"})
            elif name == "cli":
                got[name] = self.cli(["capabilities", "--refresh"])
            else:
                got[name] = self.mcp("darkroom_capabilities", {"refresh": True})
        o, res = self.assert_same(got, "capabilities")
        self.assertEqual(list(res["features"]), list(S2_FEATURES))
        self.assertEqual(res["features"]["preset_library_writes"], {"available": True, "reason": None})
        self.assertEqual(res["features"]["webp"], {"available": False, "reason": NO_WEBP})

    async def test_s2_library_in_photo_folder_parity(self):  # E20 / E31: one world, a photo in the library root
        ctx = self.fresh()
        with open(os.path.join(ctx["lib"], "IMG_0001.JPG"), "wb") as fh:
            fh.write(self.shot)
        before = snapshot(ctx["lib"])
        want = Outcome(False, "unavailable", LIB_IN_PHOTOS.format(root=ctx["lib"], photo_folder=ctx["lib"]))
        got = {"http": await self.http("POST", "/api/preset-library/rename", {"preset_id": "p-expo", "name": "x"}),
               "cli": self.cli(["presets", "rename", "p-expo", "x"]),
               "mcp": self.mcp("darkroom_preset_rename", {"preset_id": "p-expo", "name": "x"})}
        self.assertEqual(got, dict.fromkeys(got, (want, None)))
        self.assertEqual(snapshot(ctx["lib"]), before)                           # nothing written
        self.assertFalse(os.path.exists(os.path.join(ctx["lib"], "library.json")))


# ---------------------------------------------------------------- CONTRACT-s3-crop C21
GEO_NOT_OBJECT = "幾何要是物件或 null：{geometry}"                                         # verbatim (C1)
GEO_UNKNOWN_KEY = "幾何設定不認得的鍵：{key}（可用 rotate、flip、angle、aspect、crop）"
GEO_ROTATE = "rotate 要是 0、90、180、270 其中之一：{rotate}"
GEO_FLIP = "flip 必須是 true 或 false"
GEO_ANGLE = "拉直角度要在 -45～45 度之間：{angle}"
GEO_ASPECT = "不支援的裁切比例：{aspect}（可用 original、free，或「寬:高」兩個 1～65535 的整數）"
GEO_CROP = '裁切框要是 {"left","top","right","bottom"}，而且 0 ≤ left < right ≤ 1、0 ≤ top < bottom ≤ 1：'
GEO_FRAME = "frame 必須是 true 或 false"
GEO_ONLY = "只有幾何不能只貼顏色：這份編輯只有裁切／旋轉，要貼上請連同幾何一起貼（with_geometry）"


def geometry_flags(g):
    """The CLI flags of a geometry object (C20), or None when a value cannot be typed as a flag."""
    if g is None:
        return ["--no-geometry"]
    if not isinstance(g, dict) or set(g) - {"rotate", "flip", "angle", "aspect", "crop"} or \
            not isinstance(g.get("flip", False), bool):
        return None
    argv = []
    if "rotate" in g:
        argv += ["--rotate", str(g["rotate"])]
    if g.get("flip"):
        argv += ["--flip"]
    if "angle" in g:
        argv += ["--angle", str(g["angle"])]
    if "aspect" in g:
        argv += ["--aspect", str(g["aspect"])]
    if g.get("crop") is not None:
        c = g["crop"]
        argv += ["--crop", ",".join(str(c[k]) for k in ("left", "top", "right", "bottom"))]
    return argv


class TestS3GeometryParity(unittest.IsolatedAsyncioTestCase):
    """C21: every driver has its own data_dir and its own copy of the photos (same bytes, same fingerprints)."""

    @classmethod
    def setUpClass(cls):
        from darkroom_app import engine as engine_mod
        cls.eng = engine_mod.Engine()

    @classmethod
    def tearDownClass(cls):
        cls.eng.shutdown()

    async def asyncSetUp(self):
        from darkroom_app.composition import build_facade
        from darkroom_app.server import FACADE, make_app
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        write_photo(os.path.join(src, "a.png"), 300, 200)
        write_photo(os.path.join(src, "b.png"), 300, 200, seed=1)
        write_photo(os.path.join(src, "c.png"), 300, 200, seed=2)
        self.w = {}
        for name in ("http", "cli", "mcp"):
            photos, data = os.path.join(self.tmp, name, "photos"), os.path.join(self.tmp, name, "data")
            shutil.copytree(src, photos)
            os.makedirs(os.path.join(self.tmp, name, "dest"))
            f = build_facade(self.presets, engine=self.eng, data_dir=data)
            self.addCleanup(f._photo_library.wait_thumbnails, 60)
            self.w[name] = {"photos": photos, "data": data, "f": f, "dest": os.path.join(self.tmp, name, "dest")}
        from test_layering import _NoEngine
        app = make_app(self.presets, engine=_NoEngine())      # the shared Engine outlives each test's server
        app[FACADE] = self.w["http"]["f"]
        self.client = TestClient(TestServer(app), headers=_util.HTTP_HEADERS)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def ph(self, d, n):
        return os.path.join(self.w[d]["photos"], n)

    # ---- the three interfaces, each answering (Outcome, result)
    async def http(self, method, url, body=None, params=None, raw=False):
        r = await self.client.request(method, url, json=body, params=params)
        if r.status != 200:
            kind = {400: "invalid", 404: "not_found", 409: "conflict", 503: "unavailable"}[r.status]
            return Outcome(False, kind, (await r.json())["error"]), None
        return OK, (await r.read() if raw else await r.json())

    def cli(self, d, argv):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv + ["--json"], facade=self.w[d]["f"])
        self.assertEqual(err.getvalue(), "", argv)
        env = json.loads(out.getvalue())
        if env["ok"]:
            self.assertIn(rc, (0, 6), argv)
            return OK, env["result"]
        self.assertEqual(rc, {"invalid": 2, "not_found": 3, "conflict": 4, "unavailable": 5}[env["error"]["kind"]])
        return Outcome(False, env["error"]["kind"], env["error"]["message"]), None

    def mcp(self, d, tool, args):
        from darkroom_app.mcp_server import serve
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}}).encode("utf-8") + b"\n"
        out = io.BytesIO()
        serve(io.BytesIO(line), out, facade=self.w[d]["f"])
        res = json.loads(out.getvalue())["result"]
        sc = res["structuredContent"]
        if res.get("isError"):
            return Outcome(False, sc["kind"], sc["message"]), None
        if "failed" in sc:                                    # PLP4 / XP11: MCP counts the failures as well
            self.assertEqual(sc["failed"], sum(1 for r in sc["results"] if not r["ok"]))
            sc = {k: v for k, v in sc.items() if k != "failed"}
        return OK, sc

    async def set_edit(self, d, name, preset=None, geometry="omit"):
        path = self.ph(d, name)
        if d == "http":
            body = {"path": path, "preset_id": preset}
            if geometry != "omit":
                body["geometry"] = geometry
            return await self.http("PUT", "/api/edit", body)
        if d == "cli":
            argv = ["edit", "set", path] + (["--preset", preset] if preset else [])
            if geometry != "omit":
                flags = geometry_flags(geometry)
                if flags is None:
                    return None
                argv += flags
            return self.cli(d, argv)
        args = {"path": path, "preset_id": preset}
        if geometry != "omit":
            args["geometry"] = geometry
        return self.mcp(d, "darkroom_edit_set", args)

    async def get_edit(self, d, name):
        path = self.ph(d, name)
        if d == "http":
            return await self.http("GET", "/api/edit", params={"path": path})
        if d == "cli":
            return self.cli(d, ["edit", "get", path])
        return self.mcp(d, "darkroom_edit_get", {"path": path})

    async def paste(self, d, source, targets, with_geometry=False):
        s, t = self.ph(d, source), [self.ph(d, n) for n in targets]
        if d == "http":
            return await self.http("POST", "/api/edit/paste", {"targets": t, "source": s, "with_geometry": with_geometry})
        if d == "cli":
            return self.cli(d, ["edit", "paste", "--from", s, *t] + (["--with-geometry"] if with_geometry else []))
        return self.mcp(d, "darkroom_edit_paste", {"targets": t, "source": s, "with_geometry": with_geometry})

    async def preview(self, d, name, geometry="omit", frame=None):
        path = self.ph(d, name)
        if d == "cli":
            argv = ["preview", path]
            if geometry != "omit":
                flags = geometry_flags(geometry)
                if flags is None:
                    return None
                argv += flags
            if frame is not None:
                if frame is not True:
                    return None                  # only --frame can be typed
                argv += ["--frame"]
            o, res = self.cli(d, argv)
            return o, ((res["width"], res["height"]) if o.ok else None)
        if d == "http":
            o, info = await self.http("POST", "/api/open", {"path": path})
            body = {"image_id": info["image_id"]}
        else:
            o, info = self.mcp(d, "darkroom_open_photo", {"path": path})
            body = {"image_id": info["image_id"], "max_pixels": 1500000}
        if geometry != "omit":
            body["geometry"] = geometry
        if frame is not None:
            body["frame"] = frame
        if d == "http":
            o, data = await self.http("POST", "/api/preview", body, raw=True)
            return o, (jpeg_size(data) if o.ok else None)
        o, sc = self.mcp(d, "darkroom_preview", body)
        return o, ((sc["width"], sc["height"]) if o.ok else None)

    async def thumbnail(self, d, name):
        path = self.ph(d, name)
        if d == "http":
            r = await self.client.get("/api/thumbnail", params={"path": path})
            self.assertEqual(r.status, 200)
            return OK, (jpeg_size(await r.read()), r.headers["X-Fingerprint"])
        if d == "cli":
            o, res = self.cli(d, ["thumbnail", path])
        else:
            o, res = self.mcp(d, "darkroom_thumbnail", {"path": path})
        return o, ((res["width"], res["height"]), res["fingerprint"])

    async def export(self, d, name, no_edit=False):
        path = self.ph(d, name)
        if d == "http":
            item = {"path": path, **({"preset_id": None, "geometry": None} if no_edit else {})}
            o, res = await self.http("POST", "/api/export", {"items": [item], "format": "png"})
        elif d == "cli":
            o, res = self.cli(d, ["export", path, "--format", "png", "--dest-dir", self.w[d]["dest"]]
                              + (["--no-edit"] if no_edit else []))
        else:
            item = {"path": path, **({"preset_id": None, "geometry": None} if no_edit else {})}
            o, res = self.mcp(d, "darkroom_export", {"items": [item], "format": "png", "dest_dir": self.w[d]["dest"]})
        r = res["results"][0]
        self.assertTrue(r["ok"], r)
        with open(r["output"], "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        os.remove(r["output"])
        return o, ((r["used"]["width"], r["used"]["height"]), digest)

    async def each(self, fn, *a, **kw):
        out = {}
        for d in ("http", "cli", "mcp"):
            r = await fn(d, *a, **kw)
            if r is not None:
                out[d] = r
        return out

    def same(self, got, what, want=None):
        self.assertGreaterEqual(len(got), 2, what)
        first = next(iter(got.values()))
        for d, v in got.items():
            self.assertEqual(v, first, f"{what}: {d}")
        if want is not None:
            self.assertEqual(first[0], want, what)
        return first

    async def test_geometry_errors_parity(self):  # C21: every invalid geometry sentence, the same everywhere
        crop_bad = {"left": 0.6, "top": 0, "right": 0.4, "bottom": 1}
        cases = [({"rotate": 45, "flip": False, "angle": 0, "aspect": "original", "crop": None}, GEO_ROTATE.format(rotate="45")),
                 ({"rotate": 0, "flip": False, "angle": 46, "aspect": "original", "crop": None}, GEO_ANGLE.format(angle="46")),
                 ({"rotate": 0, "flip": False, "angle": 0, "aspect": "0:3", "crop": None}, GEO_ASPECT.format(aspect="0:3")),
                 ({"rotate": 0, "flip": False, "angle": 0, "aspect": "free", "crop": crop_bad},
                  GEO_CROP + '{"left": 0.6, "top": 0, "right": 0.4, "bottom": 1}'),
                 ({"rotate": 0, "zoom": 2}, GEO_UNKNOWN_KEY.format(key="zoom")),
                 ({"flip": "yes"}, GEO_FLIP),
                 (7, GEO_NOT_OBJECT.format(geometry="7"))]
        for g, sentence in cases:
            got = await self.each(self.set_edit, "a.png", "p-expo", g)
            self.same(got, f"set_edit {g}", Outcome(False, "invalid", sentence))
            got = await self.each(self.preview, "a.png", g)
            self.same(got, f"preview {g}", Outcome(False, "invalid", sentence))
        got = await self.each(self.preview, "a.png", None, 1)
        self.same(got, "frame 1", Outcome(False, "invalid", GEO_FRAME))
        for d in self.w:                                                      # nothing was written anywhere
            self.assertFalse(os.path.exists(os.path.join(self.w[d]["data"], "edits")), d)

    async def test_geometry_edit_parity(self):  # C21: set / get / keep / clear / only geometry / paste / versions
        g1 = {"rotate": 90, "flip": False, "angle": 3.5, "aspect": "4:5", "crop": None}
        g2 = {"rotate": 0, "flip": True, "angle": 0, "aspect": "free",
              "crop": {"left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.8}}
        o, res = self.same(await self.each(self.set_edit, "a.png", "p-expo", g1), "set with geometry", OK)
        self.assertEqual(res["edit"]["geometry"], g1)
        _, res = self.same(await self.each(self.get_edit, "a.png"), "get", OK)
        self.assertEqual((res["edit"]["schema"], res["edit"]["geometry"]), ("darkroom-edit/2", g1))
        _, res = self.same(await self.each(self.set_edit, "a.png", "p-strong"), "set, geometry left out", OK)
        self.assertEqual(res["edit"]["geometry"], g1)                         # kept
        _, res = self.same(await self.each(self.set_edit, "b.png", None, g2), "only a geometry", OK)
        self.assertEqual((res["edit"]["preset"], res["edit"]["geometry"]), (None, g2))
        # preview with the saved geometry (left out) and an explicit one: the same sizes everywhere
        from darkroom import Geometry
        from darkroom_app.engine import preview_size
        _, size = self.same(await self.each(self.preview, "a.png"), "preview, saved geometry", OK)
        self.assertEqual(size, preview_size(*Geometry.from_dict(g1).output_size(300, 200)))
        _, size = self.same(await self.each(self.preview, "a.png", g2), "preview, given geometry", OK)
        self.assertEqual(size, Geometry.from_dict(g2).output_size(300, 200))
        _, size = self.same(await self.each(self.preview, "a.png", None, True), "preview, frame", OK)
        self.assertEqual(size, (300, 200))
        # thumbnail with a geometry: the same size and fingerprint
        _, (tsize, fp) = self.same(await self.each(self.thumbnail, "a.png"), "thumbnail", OK)
        self.assertEqual(tsize, Geometry.from_dict(g1).output_size(256, 171))
        # export of the saved edit: the same size and the same bytes; --no-edit: the photo as it is
        _, (esize, _) = self.same(await self.each(self.export, "a.png"), "export saved", OK)
        self.assertEqual(esize, Geometry.from_dict(g1).output_size(300, 200))
        _, (nsize, _) = self.same(await self.each(self.export, "a.png", True), "export --no-edit", OK)
        self.assertEqual(nsize, (300, 200))
        # paste: colours only by default (the target keeps its own geometry), with_geometry carries it
        self.same(await self.each(self.paste, "a.png", ["b.png", "c.png"]), "paste", OK)
        got = await self.each(self.get_edit, "b.png")
        _, res = self.same(got, "b after paste", OK)
        self.assertEqual((res["edit"]["preset"]["id"], res["edit"]["geometry"]), ("p-strong", g2))
        _, res = self.same(await self.each(self.get_edit, "c.png"), "c after paste", OK)
        self.assertNotIn("geometry", res["edit"])
        self.same(await self.each(self.paste, "a.png", ["c.png"], True), "paste with geometry", OK)
        _, res = self.same(await self.each(self.get_edit, "c.png"), "c after with_geometry", OK)
        self.assertEqual(res["edit"]["geometry"], g1)
        # a source with only a geometry cannot paste colours only
        _, res = self.same(await self.each(self.set_edit, "b.png", None, g2), "b only geometry again", OK)
        self.same(await self.each(self.paste, "b.png", ["c.png"]), "geometry-only source", Outcome(False, "invalid", GEO_ONLY))
        # null clears; then nothing at all removes the edit
        _, res = self.same(await self.each(self.set_edit, "a.png", "p-expo", None), "clear geometry", OK)
        self.assertNotIn("geometry", res["edit"])
        _, res = self.same(await self.each(self.set_edit, "b.png", None, None), "nothing left", OK)
        self.assertIsNone(res["edit"])
        # a darkroom-edit/3 file: conflict everywhere, never overwritten
        for d in self.w:
            fp = self.w[d]["f"].get_edit(self.ph(d, "a.png"))["fingerprint"]
            path = os.path.join(self.w[d]["data"], "edits", fp[:2], fp + ".json")
            with open(path, encoding="utf-8") as fh:
                obj = json.load(fh)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(dict(obj, schema="darkroom-edit/3"), fh)
        conflict = Outcome(False, "conflict", "編輯檔版本不支援：darkroom-edit/3（a.png）")
        self.same(await self.each(self.get_edit, "a.png"), "v3 get", conflict)
        self.same(await self.each(self.set_edit, "a.png", "p-expo", g1), "v3 set", conflict)


class TestSettingsParity(unittest.IsolatedAsyncioTestCase):  # plan-v2 §3: settings and version, three interfaces
    """Each interface gets its own world (presets, data folder, settings file via settings_path - never the repo's
    config.local.json); the same steps give the same outcome and the same result (paths normalised)."""
    http = TestS2Parity.http
    cli = TestS2Parity.cli
    mcp = TestS2Parity.mcp
    assert_same = TestS2Parity.assert_same

    async def asyncSetUp(self):
        from darkroom_app import engine as engine_mod
        from darkroom_app.server import FACADE, make_app
        self.eng = engine_mod.Engine()
        self.tmp = _util.tmpdir(self)
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        make_presets(seed)
        self.switch = _Switch()
        app = make_app(seed, engine=self.eng, settings_path=lambda: os.path.join(self.tmp, "seed-config.json"))
        app[FACADE] = self.switch
        self.client = TestClient(TestServer(app), headers=_util.HTTP_HEADERS)
        await self.client.start_server()
        self.n = 0

    async def asyncTearDown(self):
        await self.client.close()

    def fresh(self):
        from darkroom_app.composition import build_facade
        self.n += 1
        root = os.path.join(self.tmp, f"s{self.n}")
        pd = os.path.join(root, "lib", "xmp")
        os.makedirs(pd)
        os.makedirs(os.path.join(root, "data"))
        make_presets(pd)
        cfg = os.path.join(root, "config.json")
        detect = _no_op_detect(comfyui=lambda: (False, "假的 ComfyUI"), agent_sdk=lambda: (False, "假的 SDK"))
        self.switch.target = build_facade(pd, engine=self.eng, data_dir=os.path.join(root, "data"), detect=detect,
                                          settings_path=lambda: cfg)
        return root, cfg

    async def test_settings_parity(self):
        bad_doc = {"format": "something-else", "settings": {}}
        got = {}
        for name in ("http", "cli", "mcp"):
            root, cfg = self.fresh()
            good_doc_path = os.path.join(root, "doc.json")
            with open(good_doc_path, "w", encoding="utf-8") as fh:
                json.dump({"format": "darkroom-settings/1", "version": "0.1.0",
                           "settings": {"language": "zh-TW", "agent.model": "claude-haiku-5-5"}}, fh)
            if name == "http":
                steps = [await self.http("PUT", "/api/settings", {"values": {"language": "fr-FR"}}),
                         await self.http("PUT", "/api/settings", {"values": {"colour": 1}}),
                         await self.http("PUT", "/api/settings", {"values": {"comfyui_url": "http://10.0.0.5:8188"}}),
                         await self.http("PUT", "/api/settings", {"values": {"agent.api_key_ref": "sk-ant-abc"}}),
                         await self.http("PUT", "/api/settings", {"values": {"language": "en-US",
                                                                            "agent.budget_usd": 3}}),
                         await self.http("GET", "/api/settings"),
                         await self.http("GET", "/api/settings/export"),
                         await self.http("POST", "/api/settings/import", {"document": bad_doc}),
                         await self.http("POST", "/api/settings/import",
                                         {"document": json.load(open(good_doc_path, encoding="utf-8"))})]
            elif name == "cli":
                steps = [self.cli(["settings", "set", "language=fr-FR"]),
                         self.cli(["settings", "set", "colour=1"]),
                         self.cli(["settings", "set", "comfyui_url=http://10.0.0.5:8188"]),
                         self.cli(["settings", "set", "agent.api_key_ref=sk-ant-abc"]),
                         self.cli(["settings", "set", "language=en-US", "agent.budget_usd=3"]),
                         self.cli(["settings", "get"]),
                         self.cli(["settings", "export"]),
                         None, self.cli(["settings", "import", good_doc_path])]
                bad = os.path.join(root, "bad.json")
                with open(bad, "w", encoding="utf-8") as fh:
                    json.dump(bad_doc, fh)
                steps[7] = self.cli(["settings", "import", bad])
            else:
                steps = [self.mcp("darkroom_settings_set", {"values": {"language": "fr-FR"}}),
                         self.mcp("darkroom_settings_set", {"values": {"colour": 1}}),
                         self.mcp("darkroom_settings_set", {"values": {"comfyui_url": "http://10.0.0.5:8188"}}),
                         self.mcp("darkroom_settings_set", {"values": {"agent.api_key_ref": "sk-ant-abc"}}),
                         self.mcp("darkroom_settings_set", {"values": {"language": "en-US", "agent.budget_usd": 3}}),
                         self.mcp("darkroom_settings_get", {}),
                         self.mcp("darkroom_settings_export", {}),
                         self.mcp("darkroom_settings_import", {"document": bad_doc}),
                         self.mcp("darkroom_settings_import", {"path": good_doc_path})]
            text = json.dumps(steps, ensure_ascii=False, sort_keys=True)
            got[name] = json.loads(text.replace(json.dumps(root)[1:-1], "<root>"))
            with open(cfg, encoding="utf-8") as fh:            # the file itself: new key shape, all-or-nothing
                self.assertEqual(json.load(fh), {"language": "zh-TW", "agent": {"budget_usd": 3,
                                                                              "model": "claude-haiku-5-5"}}, name)
        steps = self.assert_same(got, "settings")
        from darkroom_app.domain import messages as M
        self.assertEqual(steps[0][0], [False, "invalid", M.SET_LANGUAGE.format(value="fr-FR")])
        self.assertEqual(steps[1][0][:2], [False, "invalid"])
        self.assertTrue(steps[1][0][2].startswith("不認得的設定鍵：colour"))
        self.assertEqual(steps[2][0], [False, "invalid", M.SET_URL.format(value="http://10.0.0.5:8188")])
        self.assertEqual(steps[3][0], [False, "invalid", M.SET_SECRET])     # the key is never echoed back
        self.assertNotIn("sk-ant", json.dumps(steps[3]))
        self.assertEqual(steps[4][0], [True, None, None])
        self.assertEqual(steps[4][1]["applied"], ["language", "agent.budget_usd"])
        self.assertEqual(steps[4][1]["checks"]["comfyui"], {"available": False, "reason": "假的 ComfyUI"})
        self.assertEqual(steps[5][1]["sources"]["language"], "file")
        self.assertEqual(steps[5][1]["settings"]["language"], "en-US")
        self.assertEqual(steps[6][1], {"format": "darkroom-settings/1", "version": "0.1.0",
                                       "settings": {"language": "en-US", "agent.budget_usd": 3}})
        self.assertEqual(steps[7][0], [False, "invalid", M.SET_DOC_FORMAT.format(format="darkroom-settings/1")])
        self.assertEqual(steps[8][1]["applied"], ["language", "agent.model"])

    async def test_version_parity(self):
        self.fresh()
        got = {"http": [await self.http("GET", "/api/version")], "cli": [self.cli(["version"])],
               "mcp": [self.mcp("darkroom_version", {})]}
        steps = json.loads(json.dumps(self.assert_same(json.loads(json.dumps(got)), "version")))
        from darkroom_app import __version__
        self.assertEqual(steps[0][0], [True, None, None])
        self.assertEqual(list(steps[0][1]), ["version", "python", "torch", "cuda", "platform"])
        self.assertEqual(steps[0][1]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
