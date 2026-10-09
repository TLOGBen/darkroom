"""CONTRACT-layering L8: HTTP behaviour pinned verbatim before the handlers are thinned.

Every error path of the 9 routes: status code and the complete {"error"} string; the keys of every success
response; the preview headers. Written and run green against the pre-refactor server (00121be / eef3a46).
"""
import json
import os
import re
import unittest
from unittest import mock

import _heicgen
import _writeguard  # noqa: F401  (CONTRACT-write-guard G1)
from darkroom import read_image
from test_app_server import AppCase, write_photo

OPEN_ERROR = "照片讀取失敗：{file_name}：{reason}"           # verbatim
BODY_NOT_JSON = '{"error": "body must be JSON"}'           # verbatim (HTTP entry sentence)
BODY_NOT_OBJECT = '{"error": "body must be a JSON object"}'  # verbatim (HTTP entry sentence)

PRESET_ROW = ["id", "group", "name", "supported", "skipped", "favorite", "tags"]   # K9 + CONTRACT-semantic-index SI10
DETAIL_KEYS = ["id", "group", "name", "supported", "skipped", "level", "banner", "note", "values", "curves"]
OPEN_KEYS = ["image_id", "width", "height", "preview_width", "preview_height"]
FOLDER_KEYS = ["folder", "files", "index"]


class GoldenCase(AppCase):
    async def err(self, method, url, status, message, **kw):
        r = await self.client.request(method, url, **kw)
        text = await r.text()
        self.assertEqual(r.status, status, (url, kw, text))
        self.assertEqual(r.headers["Content-Type"].split(";")[0], "application/json", text)
        self.assertEqual(json.loads(text), {"error": message}, (url, kw))
        return r

    async def raw_err(self, url, data, body):
        r = await self.client.post(url, data=data, headers={"Content-Type": "application/json"})
        self.assertEqual(r.status, 400)
        self.assertEqual(await r.text(), body)
        self.assertEqual(r.headers["Content-Type"].split(";")[0], "application/json")


class TestGoldenGetRoutes(GoldenCase):
    async def test_index(self):
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertIn("<html", (await r.text()).lower())

    async def test_health(self):
        r = await self.client.get("/api/health")
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.json(), {"ok": True})

    async def test_presets(self):
        r = await self.client.get("/api/presets")
        self.assertEqual(r.status, 200)
        rows = await r.json()
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(list(row), PRESET_ROW)
        self.assertEqual([x["id"] for x in rows], ["p-old", "p-skip", "p-minor", "p-strong", "p-mixed", "p-expo"])

    async def test_preset_flags(self):
        r = await self.client.get("/api/preset_flags")
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.json(), {"p-skip": "major", "p-mixed": "major", "p-minor": "minor"})

    async def test_preset_detail(self):
        r = await self.client.get("/api/presets/p-expo")
        self.assertEqual(r.status, 200)
        self.assertEqual(list(await r.json()), DETAIL_KEYS)
        r = await self.client.get("/api/presets/p-old")      # unsupported presets still have a detail
        self.assertEqual(r.status, 200)
        self.assertEqual(list(await r.json()), DETAIL_KEYS)
        await self.err("GET", "/api/presets/nope", 404, "unknown preset nope")
        await self.err("GET", "/api/presets/%E6%9B%9D", 404, "unknown preset 曝")

    async def test_sliders(self):
        r = await self.client.get("/api/sliders")
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertEqual(list(data), ["groups", "sliders"])
        self.assertEqual(list(data["sliders"][0]), ["key", "label", "group", "min", "max", "default", "step", "sub",
                                                    "hue"])


class TestGoldenOpen(GoldenCase):
    async def test_open_success_keys(self):
        path = write_photo(os.path.join(self.photos, "a.png"), 320, 200)
        r = await self.client.post("/api/open", json={"path": path})
        self.assertEqual(r.status, 200)
        self.assertEqual(list(await r.json()), OPEN_KEYS)
        r = await self.client.post("/api/open", json={"path": f'  "{path}"  '})    # strip, then strip quotes
        self.assertEqual(r.status, 200, await r.text())

    async def test_open_body_errors(self):
        await self.raw_err("/api/open", b"{not json", BODY_NOT_JSON)
        await self.raw_err("/api/open", b"[1, 2]", BODY_NOT_OBJECT)
        await self.raw_err("/api/open", b'"x"', BODY_NOT_OBJECT)

    async def test_open_error_paths(self):
        for body in ({}, {"path": None}, {"path": 5}, {"path": ""}, {"path": "   "}, {"path": ["a"]}):
            await self.err("POST", "/api/open", 400, "path is required", json=body)
        missing = os.path.join(self.photos, "missing.jpg")
        await self.err("POST", "/api/open", 404, f"photo not found: {missing}", json={"path": missing})
        await self.err("POST", "/api/open", 404, f"photo not found: {missing}", json={"path": f' "{missing}" '})
        os.makedirs(os.path.join(self.photos, "dir.jpg"))
        d = os.path.join(self.photos, "dir.jpg")
        await self.err("POST", "/api/open", 404, f"photo not found: {d}", json={"path": d})
        txt = os.path.join(self.photos, "notes.txt")
        with open(txt, "w") as f:
            f.write("x")
        await self.err("POST", "/api/open", 400, "unsupported photo format (JPEG/PNG/TIFF/HEIC)", json={"path": txt})
        bad = os.path.join(self.photos, "broken.jpg")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        await self.err("POST", "/api/open", 400,
                       OPEN_ERROR.format(file_name="broken.jpg", reason=f"cannot decode image {bad}"),
                       json={"path": bad})
        good = _heicgen.write_heic(os.path.join(self.photos, "good.heic"), _heicgen.pattern(32, 32))
        with open(good, "rb") as f:
            data = f.read()
        half = os.path.join(self.photos, "half.heic")
        with open(half, "wb") as f:
            f.write(data[: len(data) // 2])
        with self.assertRaises(ValueError) as cm:
            read_image(half)
        await self.err("POST", "/api/open", 400, OPEN_ERROR.format(file_name="half.heic", reason=str(cm.exception)),
                       json={"path": half})

    async def test_open_engine_error_types(self):
        from darkroom_app.server import ENGINE
        eng = self.app[ENGINE]
        path = write_photo(os.path.join(self.photos, "a.png"), 64, 48)
        for exc, reason in ((OSError("disk gone"), "disk gone"), (ValueError("bad pixels"), "bad pixels")):
            with mock.patch.object(eng, "open", side_effect=exc):
                await self.err("POST", "/api/open", 400, OPEN_ERROR.format(file_name="a.png", reason=reason),
                               json={"path": path})
        with mock.patch.object(eng, "open", side_effect=RuntimeError("boom")),                 self.assertLogs("aiohttp.server", "ERROR"):
            r = await self.client.post("/api/open", json={"path": path})
            self.assertEqual(r.status, 500)                  # unexpected errors are not translated


class TestGoldenPreview(GoldenCase):
    async def test_preview_success_headers(self):
        _, info = await self.open_photo("p.png", 320, 200)
        r, data = await self.preview(image_id=info["image_id"], preset_id="p-expo", strength=100, overrides={})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/jpeg")
        self.assertRegex(r.headers["X-Render-Ms"], r"^\d+\.\d\d$")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["Access-Control-Expose-Headers"], "X-Render-Ms")
        self.assertEqual(data[:2], b"\xff\xd8")
        r, _ = await self.preview(image_id=info["image_id"])        # every field but image_id is optional
        self.assertEqual(r.status, 200)

    async def test_preview_render_ms_two_decimals(self):
        from darkroom_app.server import ENGINE
        eng = self.app[ENGINE]
        _, info = await self.open_photo("p.png", 64, 48)
        with mock.patch.object(eng, "preview", return_value=(b"\xff\xd8\xff\xd9", 12.345678)):
            r, data = await self.preview(image_id=info["image_id"])
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["X-Render-Ms"], "12.35")
        self.assertEqual(data, b"\xff\xd8\xff\xd9")

    async def test_preview_body_errors(self):
        await self.raw_err("/api/preview", b"nope", BODY_NOT_JSON)
        await self.raw_err("/api/preview", b"null", BODY_NOT_OBJECT)

    async def test_preview_error_paths(self):
        from darkroom_app.server import ENGINE
        _, info = await self.open_photo("p.png", 64, 48)
        iid = info["image_id"]
        P = "/api/preview"
        for body in ({}, {"image_id": "x"}, {"image_id": 5}, {"image_id": None}):
            await self.err("POST", P, 404, "unknown image_id", json=body)
        # image_id is checked before the preset, the preset before strength / overrides
        await self.err("POST", P, 404, "unknown image_id", json={"image_id": "x", "preset_id": "nope", "strength": 999})
        for pid, shown in (("nope", "nope"), ("p-old", "p-old"), (5, "5"), (["a"], "['a']"), (False, "False")):
            await self.err("POST", P, 404, f"unknown or unsupported preset {shown}",
                           json={"image_id": iid, "preset_id": pid, "strength": 999})
        cases = (({"strength": 250}, "strength must be within 0..200, got 250"),
                 ({"strength": -1}, "strength must be within 0..200, got -1"),
                 ({"strength": 200.5}, "strength must be within 0..200, got 200.5"),
                 ({"strength": "1"}, "strength must be a number in 0..200"),
                 ({"strength": True}, "strength must be a number in 0..200"),
                 ({"strength": None}, "strength must be a number in 0..200"),
                 ({"overrides": [1]}, "overrides must be an object {key: difference}"),
                 ({"overrides": "x"}, "overrides must be an object {key: difference}"),
                 ({"overrides": {"Bogus": 1}}, "unknown slider key 'Bogus'"),
                 ({"overrides": {"Exposure2012": "1"}}, "override for Exposure2012 must be a finite number"),
                 ({"overrides": {"Exposure2012": True}}, "override for Exposure2012 must be a finite number"),
                 # strength is validated before the overrides
                 ({"strength": 250, "overrides": {"Bogus": 1}}, "strength must be within 0..200, got 250"))
        for extra, message in cases:
            await self.err("POST", P, 400, message, json={"image_id": iid, "preset_id": "p-expo", **extra})
        eng = self.app[ENGINE]
        with mock.patch.object(eng, "preview", side_effect=KeyError(iid)):      # evicted between check and render
            await self.err("POST", P, 404, "unknown image_id", json={"image_id": iid})
        with mock.patch.object(eng, "preview", side_effect=RuntimeError("JPEG encoding failed")),                 self.assertLogs("aiohttp.server", "ERROR"):
            r = await self.client.post(P, json={"image_id": iid})
            self.assertEqual(r.status, 500)


class TestGoldenFolder(GoldenCase):
    async def test_folder(self):
        _, info = await self.open_photo("a.png", 64, 48)
        r = await self.client.get("/api/folder", params={"image_id": info["image_id"]})
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertEqual(list(data), FOLDER_KEYS)
        self.assertEqual(list(data["files"][0]), ["name", "path"])
        self.assertEqual(data["index"], 0)
        await self.err("GET", "/api/folder", 404, "unknown image_id")
        await self.err("GET", "/api/folder?image_id=nope", 404, "unknown image_id")
        await self.err("GET", "/api/folder?image_id=", 404, "unknown image_id")


class TestGoldenCrossSite(GoldenCase):  # CONTRACT-export XP16 / app shell R10: the only assertions added here
    async def test_refusals(self):
        port = self.client.port
        await self.err("GET", "/api/presets", 421,
                       f"request refused: Host must be 127.0.0.1:{port} or localhost:{port}",
                       headers={"Host": "evil.example"})
        await self.err("GET", "/api/presets", 403, "request refused: cross-site Origin http://evil.example",
                       headers={"Origin": "http://evil.example"})
        await self.err("POST", "/api/open", 415, "request refused: POST body must be application/json",
                       data=b'{"path": "x"}', headers={"Content-Type": "text/plain"})


class TestGoldenRoutes(GoldenCase):
    async def test_exactly_twenty_eight_routes(self):  # nine of L8 + export (XP1) + nine library (K16) + seven photo library (PL6, PLP2) + two semantic (SI11)
        routes = sorted((r.method, r.resource.canonical) for r in self.app.router.routes()
                        if r.method != "HEAD" and not r.resource.canonical.startswith("/static"))
        self.assertEqual(routes, sorted([
            ("GET", "/"), ("GET", "/api/health"), ("GET", "/api/presets"), ("GET", "/api/preset_flags"),
            ("GET", "/api/presets/{id}"), ("GET", "/api/sliders"), ("POST", "/api/open"), ("POST", "/api/preview"),
            ("GET", "/api/folder"), ("POST", "/api/export"),
            ("GET", "/api/preset-library/groups"), ("POST", "/api/preset-library/rename"),
            ("POST", "/api/preset-library/move"), ("POST", "/api/preset-library/favorite"),
            ("POST", "/api/preset-library/groups/create"), ("POST", "/api/preset-library/groups/rename"),
            ("POST", "/api/preset-library/import"), ("POST", "/api/preset-library/save"),
            ("POST", "/api/preset-library/rebuild"),
            ("GET", "/api/edit"), ("PUT", "/api/edit"), ("DELETE", "/api/edit"), ("POST", "/api/edit/paste"),
            ("POST", "/api/edit/save-preset"), ("GET", "/api/folder/thumbnails"), ("GET", "/api/thumbnail"),
            ("POST", "/api/preset-library/semantic/build"), ("GET", "/api/preset-library/semantic")]))

    async def test_semantic_build_refused_over_http(self):  # CONTRACT-semantic-index SI11: the page never spends money
        from darkroom_app.server import FACADE
        calls = []
        self.app[FACADE].semantic_build = lambda *a, **k: calls.append((a, k))
        for body in ({}, {"limit": 3}, {"dry_run": True}):
            await self.err("POST", "/api/preset-library/semantic/build", 400,
                           "semantic build is not accepted over HTTP (use the CLI or MCP)", json=body)
        self.assertEqual(calls, [])
        r = await self.client.get("/api/preset-library/semantic")
        self.assertEqual(r.status, 200)
        self.assertEqual(list(await r.json()), ["available", "reason", "model", "index_state", "indexed", "total",
                                                "pending", "in_flight", "budget_usd", "last_usage"])


if __name__ == "__main__":
    unittest.main()
