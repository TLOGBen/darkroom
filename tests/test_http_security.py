"""CONTRACT-export XP16 / app shell R10: cross-site requests and DNS rebinding are refused before any route.

Host must be 127.0.0.1:{port} or localhost:{port}; an Origin must be the page's own; a POST body must be declared
application/json; over HTTP, export takes no dest_dir. A refused request never reaches the facade.
"""
import json
import os
import unittest

from aiohttp.test_utils import AioHTTPTestCase

import _util
from _fakes import FakeDarkroom
from test_app_server import make_presets, snapshot, write_photo

HOST_REFUSED = "request refused: Host must be 127.0.0.1:{port} or localhost:{port}"   # verbatim (XP16)
ORIGIN_REFUSED = "request refused: cross-site Origin {origin}"                        # verbatim (XP16)
CONTENT_TYPE_REFUSED = "request refused: POST body must be application/json"          # verbatim (XP16)
DEST_DIR_REFUSED = "dest_dir is not accepted over HTTP (use the CLI or MCP)"           # verbatim (XP16)
ROUTES = [("GET", "/"), ("GET", "/api/health"), ("GET", "/api/presets"), ("GET", "/api/preset_flags"),
          ("GET", "/api/presets/x"), ("GET", "/api/sliders"), ("GET", "/api/folder?image_id=i"),
          ("GET", "/assets/app.js"), ("POST", "/api/open"), ("POST", "/api/preview"), ("POST", "/api/export"),
          # CONTRACT-photo-library PLP2: the seven photo library routes, PUT and DELETE included
          ("GET", "/api/edit?path=a.jpg"), ("PUT", "/api/edit"), ("DELETE", "/api/edit?path=a.jpg"),
          ("POST", "/api/edit/paste"), ("POST", "/api/edit/save-preset"),
          ("GET", "/api/folder/thumbnails?folder=f"), ("GET", "/api/thumbnail?path=a.jpg"),
          # CONTRACT-s2-export-detect E28: the six new routes pass the same checks
          ("GET", "/api/export-presets"), ("PUT", "/api/export-presets"), ("DELETE", "/api/export-presets?name=x"),
          ("POST", "/api/preset-library/files"), ("POST", "/api/preset-library/export"),
          ("GET", "/api/capabilities")]
DATA_DIR_REFUSED = "data_dir is not accepted over HTTP (it is configured)"            # verbatim (PLP2)
FETCH_SITE_REFUSED = "request refused: cross-site request (Sec-Fetch-Site {value})"   # verbatim (PLP11)
DARKROOM_HEADER_REFUSED = "request refused: X-Darkroom header required"              # verbatim (PLP11)
PATH_GETS = [("GET", "/api/folder?image_id=i"), ("GET", "/api/edit?path=a.jpg"),
             ("GET", "/api/folder/thumbnails?folder=f"), ("GET", "/api/thumbnail?path=a.jpg")]   # verbatim (PLP11)


class _NoEngine:
    images = {}

    def shutdown(self):
        pass


class SecurityCase(AioHTTPTestCase):
    async def get_application(self):
        from darkroom_app.server import FACADE, make_app
        self.tmp = _util.tmpdir(self)
        d = os.path.join(self.tmp, "p")
        os.makedirs(d)
        app = make_app(make_presets(d), engine=_NoEngine())
        self.fake = FakeDarkroom()
        app[FACADE] = self.fake
        return app

    @property
    def port(self):
        return self.client.port

    async def send(self, method, path, headers=None, body=b'{"items": [{"path": "a.jpg"}], "format": "jpeg"}'):
        with_body = method in ("POST", "PUT")
        h = {"Content-Type": "application/json", **(headers or {})} if with_body else dict(headers or {})
        r = await self.client.request(method, path, headers=h, data=body if with_body else None)
        raw = await r.read()
        return r.status, raw.decode("utf-8", "replace")     # a thumbnail answer is JPEG bytes (PLP11 test)


class TestRefused(SecurityCase):
    async def test_wrong_host(self):  # DNS rebinding: the page's Host is the attacker's name
        for host in ("evil.example", f"evil.example:{self.port}", f"127.0.0.1:{self.port + 1}", "127.0.0.1",
                     f"localhost.evil.example:{self.port}", f"0.0.0.0:{self.port}"):
            for method, path in ROUTES:
                status, text = await self.send(method, path, {"Host": host})
                self.assertEqual((status, json.loads(text)), (421, {"error": HOST_REFUSED.format(port=self.port)}),
                                 (host, path))
        self.assertEqual(self.fake.calls, [])

    async def test_cross_site_origin(self):
        for origin in ("http://evil.example", "null", f"http://127.0.0.1:{self.port + 1}", f"https://127.0.0.1:{self.port}",
                       f"http://evil.example:{self.port}"):
            for method, path in ROUTES:
                status, text = await self.send(method, path, {"Origin": origin})
                self.assertEqual((status, json.loads(text)), (403, {"error": ORIGIN_REFUSED.format(origin=origin)}),
                                 (origin, path))
        self.assertEqual(self.fake.calls, [])

    async def test_post_needs_json_content_type(self):  # a simple (no-preflight) cross-site POST is refused
        for ctype in ("text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded",
                      "multipart/form-data; boundary=x", None):
            for path in ("/api/export", "/api/open", "/api/preview"):
                h = {"Content-Type": ctype} if ctype else {}
                r = await self.client.post(path, data=b'{"items": [], "format": "jpeg", "path": "x"}', headers=h,
                                           skip_auto_headers=["Content-Type"])
                self.assertEqual((r.status, await r.json()), (415, {"error": CONTENT_TYPE_REFUSED}), (ctype, path))
        self.assertEqual(self.fake.calls, [])

    async def test_http_export_takes_no_dest_dir(self):
        for dest in (self.tmp, "relative", None, ""):
            r = await self.client.post("/api/export", json={"items": [{"path": "a.jpg"}], "format": "jpeg",
                                                            "dest_dir": dest})
            self.assertEqual((r.status, await r.json()), (400, {"error": DEST_DIR_REFUSED}), dest)
        self.assertEqual(self.fake.calls, [])

    async def test_photo_library_bodies_need_json_content_type(self):  # PLP2: PUT too, and the two POSTs
        for ctype in ("text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", None):
            for method, path in (("PUT", "/api/edit"), ("POST", "/api/edit/paste"), ("POST", "/api/edit/save-preset")):
                h = {"Content-Type": ctype} if ctype else {}
                r = await self.client.request(method, path, data=b'{"path": "a.jpg", "targets": ["a.jpg"], "name": "n"}',
                                              headers=h, skip_auto_headers=["Content-Type"])
                self.assertEqual((r.status, await r.json()), (415, {"error": CONTENT_TYPE_REFUSED}), (ctype, path))
        self.assertEqual(self.fake.calls, [])

    async def test_http_photo_library_takes_no_data_dir(self):  # PLP2: the data folder is configured, never sent
        for method, path, body in (("PUT", "/api/edit", {"path": "a.jpg"}),
                                   ("POST", "/api/edit/paste", {"targets": ["a.jpg"], "source": "b.jpg"}),
                                   ("POST", "/api/edit/save-preset", {"path": "a.jpg", "name": "n"})):
            for dd in (self.tmp, "relative", None, ""):
                r = await self.client.request(method, path, json={**body, "data_dir": dd})
                self.assertEqual((r.status, await r.json()), (400, {"error": DATA_DIR_REFUSED}), (path, dd))
        self.assertEqual(self.fake.calls, [])

    async def test_cross_site_fetch_site_refused(self):  # PLP11 (1): <img src> / <script src> from another page
        for value in ("cross-site", "same-site", "Cross-Site"):
            for method, path in ROUTES:
                status, text = await self.send(method, path, {"Sec-Fetch-Site": value, "X-Darkroom": "1"})
                self.assertEqual((status, json.loads(text)), (403, {"error": FETCH_SITE_REFUSED.format(value=value)}),
                                 (value, path))
        self.assertEqual(self.fake.calls, [])
        for value in ("same-origin", "none"):
            for method, path in (("GET", "/"), ("GET", "/api/presets"), ("GET", "/assets/app.js")):
                status, _ = await self.send(method, path, {"Sec-Fetch-Site": value})
                self.assertEqual(status, 200, (value, path))

    async def test_path_reading_gets_need_the_darkroom_header(self):  # PLP11 (2)
        for method, path in PATH_GETS:
            status, text = await self.send(method, path)
            self.assertEqual((status, json.loads(text)), (403, {"error": DARKROOM_HEADER_REFUSED}), path)
            status, text = await self.send(method, path, {"X-Darkroom": "0"})
            self.assertEqual(status, 403, path)
        self.assertEqual(self.fake.calls, [])
        for method, path in PATH_GETS:
            status, _ = await self.send(method, path, {"X-Darkroom": "1"})
            self.assertEqual(status, 200, path)
        self.assertEqual([c[0] for c in self.fake.calls], ["list_folder", "get_edit", "folder_thumbnails", "thumbnail"])
        for method, path in (("GET", "/api/presets"), ("GET", "/"), ("DELETE", "/api/edit?path=a.jpg")):
            status, _ = await self.send(method, path)                        # the other routes need no header
            self.assertEqual(status, 200, path)

    async def test_head_and_path_spellings_cannot_bypass_the_header(self):  # PLP12
        for method, path in PATH_GETS:
            r = await self.client.request("HEAD", path)
            self.assertEqual(r.status, 403, path)                                # still checked
            r = await self.client.request("HEAD", path, headers={"X-Darkroom": "1"})
            self.assertEqual(r.status, 405, path)                                # allow_head=False
        for path in ("/API/thumbnail?path=a.jpg", "/api/thumbnail/?path=a.jpg", "/api//thumbnail?path=a.jpg",
                     "/api/thumbnail%2F?path=a.jpg", "/api/%74humbnail?path=a.jpg", "/api/Folder?image_id=i",
                     "/api/folder/?image_id=i", "/api/edit/?path=a.jpg", "/api/folder/thumbnails/?folder=f"):
            r = await self.client.get(path)
            self.assertIn(r.status, (403, 404), path)
        self.assertEqual(self.fake.calls, [])
        r = await self.client.get("/api/thumbnail?path=a.jpg", headers={"X-Darkroom": "1"})
        self.assertEqual(r.status, 200)
        self.assertEqual([c[0] for c in self.fake.calls], ["thumbnail"])

    async def test_check_order(self):  # Host -> Sec-Fetch-Site -> Origin -> Content-Type -> X-Darkroom -> route
        status, _ = await self.send("GET", "/api/folder?image_id=i", {"Host": "evil.example", "Sec-Fetch-Site": "cross-site",
                                                                       "Origin": "http://evil.example"})
        self.assertEqual(status, 421)
        status, text = await self.send("GET", "/api/folder?image_id=i", {"Sec-Fetch-Site": "cross-site",
                                                                          "Origin": "http://evil.example"})
        self.assertEqual((status, json.loads(text)["error"]), (403, FETCH_SITE_REFUSED.format(value="cross-site")))
        status, text = await self.send("GET", "/api/folder?image_id=i", {"Origin": "http://evil.example"})
        self.assertEqual((status, json.loads(text)["error"]), (403, ORIGIN_REFUSED.format(origin="http://evil.example")))
        status, text = await self.send("POST", "/api/export", {"Content-Type": "text/plain", "Sec-Fetch-Site": "same-site"})
        self.assertEqual((status, json.loads(text)["error"]), (403, FETCH_SITE_REFUSED.format(value="same-site")))
        self.assertEqual(self.fake.calls, [])
        status, _ = await self.send("POST", "/api/export", {"Host": "evil.example", "Origin": "http://evil.example",
                                                            "Content-Type": "text/plain"})
        self.assertEqual(status, 421)
        status, _ = await self.send("POST", "/api/export", {"Origin": "http://evil.example",
                                                            "Content-Type": "text/plain"})
        self.assertEqual(status, 403)


class TestS2Routes(SecurityCase):  # CONTRACT-s2-export-detect E28 / R12
    async def test_capabilities_needs_the_darkroom_header(self):  # R12: it answers with local paths
        for path in ("/api/capabilities", "/api/capabilities?refresh=1"):
            status, text = await self.send("GET", path)
            self.assertEqual((status, json.loads(text)), (403, {"error": DARKROOM_HEADER_REFUSED}), path)
            status, _ = await self.send("GET", path, {"X-Darkroom": "0"})
            self.assertEqual(status, 403, path)
            r = await self.client.request("HEAD", path)
            self.assertEqual(r.status, 403, path)                               # HEAD checked too (PLP12)
            r = await self.client.request("HEAD", path, headers={"X-Darkroom": "1"})
            self.assertEqual(r.status, 405, path)                               # allow_head=False
        for path in ("/API/capabilities", "/api/capabilities/", "/api//capabilities"):
            r = await self.client.get(path)
            self.assertIn(r.status, (403, 404), path)
        self.assertEqual(self.fake.calls, [])
        status, _ = await self.send("GET", "/api/capabilities", {"X-Darkroom": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.calls, [("capabilities", (False,))])

    async def test_s2_bodies_need_json_content_type(self):
        for ctype in ("text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", None):
            for method, path in (("PUT", "/api/export-presets"), ("POST", "/api/preset-library/files"),
                                 ("POST", "/api/preset-library/export")):
                h = {"Content-Type": ctype} if ctype else {}
                r = await self.client.request(method, path, data=b'{"name": "n", "settings": {}, "preset_ids": ["p"]}',
                                              headers=h, skip_auto_headers=["Content-Type"])
                self.assertEqual((r.status, await r.json()), (415, {"error": CONTENT_TYPE_REFUSED}), (ctype, path))
        self.assertEqual(self.fake.calls, [])

    async def test_other_s2_routes_need_no_header(self):  # only the capabilities GET reads local paths
        for method, path in (("GET", "/api/export-presets"), ("DELETE", "/api/export-presets?name=x")):
            status, _ = await self.send(method, path)
            self.assertEqual(status, 200, path)
        self.assertEqual([c[0] for c in self.fake.calls], ["list_export_presets", "delete_export_preset"])


class TestAllowed(SecurityCase):
    async def test_same_origin_requests_pass(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LOCALHOST:{self.port}"):
            for origin in (None, f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"):
                h = {"Host": host, **({"Origin": origin} if origin else {})}
                for method, path in (("GET", "/"), ("GET", "/api/presets"), ("GET", "/assets/app.js")):
                    status, _ = await self.send(method, path, h)
                    self.assertEqual(status, 200, (host, origin, path))
                status, _ = await self.send("POST", "/api/export",
                                            {**h, "Content-Type": "application/json; charset=utf-8"})
                self.assertEqual(status, 200, (host, origin))
        self.assertEqual(sum(1 for c in self.fake.calls if c[0] == "export"), 9)

    def test_front_end_posts_json(self):  # XP16 (5): every request declares its body as JSON and carries X-Darkroom
        # v2 (plan-v2 §2): the page is web/ (React). Every request leaves through requests/client.ts api(), whose
        # middleware localHeaders() adds X-Darkroom: 1 and, with a body, Content-Type: application/json.
        src = os.path.join(_util.REPO, "web", "src")
        with open(os.path.join(src, "middlewares", "index.ts"), encoding="utf-8") as f:
            mw = f.read()
        self.assertIn("headers.set('X-Darkroom', '1');", mw)
        self.assertIn("headers.set('Content-Type', 'application/json');", mw)
        code = {}
        for root, _dirs, files in os.walk(src):
            if "__tests__" in root:
                continue
            for name in files:
                if name.endswith((".ts", ".tsx")) and ".test." not in name:
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        code[os.path.relpath(os.path.join(root, name), src)] = f.read()
        fetchers = [rel for rel, text in code.items() if "fetch(" in text]
        self.assertEqual(fetchers, [os.path.join("requests", "client.ts")])     # every request goes through api()
        self.assertEqual(code[os.path.join("requests", "client.ts")].count("fetch("), 1)
        self.assertIn("fetch(url, localHeaders(", code[os.path.join("requests", "client.ts")])
        everything = "".join(code.values())
        self.assertNotRegex(everything, r"""src=\{?["'`]/api/""")       # PLP11: thumbnails come through api()
        self.assertNotIn("XMLHttpRequest", everything)
        self.assertNotIn("sendBeacon", everything)                        # no header can be set on a beacon


class TestRealFacadeUntouched(AioHTTPTestCase):  # a refused export reads and writes nothing
    async def get_application(self):
        from darkroom_app.server import make_app
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.data_dir = os.path.join(self.tmp, "data")
        return make_app(self.presets, data_dir=self.data_dir)

    async def test_refused_photo_library_requests_touch_nothing(self):  # PLP2: no edit, thumbnail or index appears
        photo = write_photo(os.path.join(self.photos, "a.jpg"), 64, 48)
        before = snapshot(self.photos, self.presets)
        evil = ({"Content-Type": "text/plain;charset=UTF-8", "Origin": f"http://127.0.0.1:{self.client.port}"},
                {"Content-Type": "application/json", "Origin": "http://evil.example"},
                {"Content-Type": "application/json", "Host": "evil.example"})
        for headers in evil:
            for method, path, body in (("PUT", "/api/edit", {"path": photo, "preset_id": "p-expo"}),
                                       ("POST", "/api/edit/paste", {"targets": [photo], "source": photo}),
                                       ("POST", "/api/edit/save-preset", {"path": photo, "name": "n"})):
                r = await self.client.request(method, path, data=json.dumps(body).encode(), headers=headers)
                self.assertIn(r.status, (403, 415, 421), (path, headers))
        gets = (("GET", f"/api/edit?path={photo}"), ("DELETE", f"/api/edit?path={photo}"),
                ("GET", f"/api/thumbnail?path={photo}"), ("GET", f"/api/folder/thumbnails?folder={self.photos}"))
        for headers in evil[1:]:                      # GET / DELETE carry no body: Origin and Host decide
            for method, path in gets:
                r = await self.client.request(method, path, headers={k: v for k, v in headers.items()
                                                                     if k != "Content-Type"})
                self.assertIn(r.status, (403, 421), (path, headers))
        for method, path in gets:                     # PLP11: an <img src> (no header, Sec-Fetch-Site cross-site)
            r = await self.client.request(method, path, headers={"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(r.status, 403, path)
            if method == "GET":
                r = await self.client.request(method, path)
                self.assertEqual((r.status, (await r.json())["error"]), (403, DARKROOM_HEADER_REFUSED), path)
        self.assertFalse(os.path.exists(self.data_dir))
        self.assertEqual(snapshot(self.photos, self.presets), before)

    async def test_no_cors_export_writes_nothing(self):
        photo = write_photo(os.path.join(self.photos, "a.jpg"), 64, 48)
        dest = os.path.join(self.tmp, "attacker")
        os.makedirs(dest)
        before = snapshot(self.photos, self.presets)
        body = json.dumps({"items": [{"path": photo}], "format": "jpeg", "dest_dir": dest}).encode()
        for headers in ({"Content-Type": "text/plain;charset=UTF-8", "Origin": f"http://127.0.0.1:{self.client.port}"},
                        {"Content-Type": "application/json", "Origin": "http://evil.example"},
                        {"Content-Type": "application/json", "Host": "evil.example"},
                        {"Content-Type": "application/json"}):
            r = await self.client.post("/api/export", data=body, headers=headers)
            self.assertIn(r.status, (400, 403, 415, 421), headers)
        self.assertEqual(os.listdir(dest), [])
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual(sorted(os.listdir(self.photos)), ["a.jpg"])


if __name__ == "__main__":
    unittest.main()
