"""CONTRACT-layering L11 / L12: the three interfaces over one facade give the same outcome and never write.

One build_facade (synthetic presets + the real Engine) is driven through HTTP (aiohttp TestClient), the CLI
(main(argv + ["--json"], facade=f)) and MCP (serve() fed from BytesIO). Every outcome is normalized to
Outcome(ok, kind, message); status code / exit code / isError must follow L7.
Export (CONTRACT-export XP6 / XP11 / XP13): the outcome plus every result's (ok, basename(output) or error); CLI exit 6
and MCP `failed` when some photo failed.
"""
import base64
import builtins
import contextlib
import io
import json
import os
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

    async def export(self, items, format, quality=None, dest_dir=None, raw_quality=None):
        body = {"items": items, "format": format}
        if quality is not None or raw_quality is not None:
            body["quality"] = raw_quality if raw_quality is not None else quality
        if dest_dir is not None:
            body["dest_dir"] = dest_dir
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
        self.client = TestClient(TestServer(app))
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
            want_drivers = {"http", "mcp"} if name == "quality true" else {"http", "cli", "mcp"}
            self.assertEqual(set(got), want_drivers, name)
            for dname, (o, res) in got.items():
                self.assertEqual(o, outcome, (name, dname))
                self.assertEqual(res, results, (name, dname))
        # XP13: dest_dir = the photo's own folder, where the photo itself is the same name
        for d in self.drivers:
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
