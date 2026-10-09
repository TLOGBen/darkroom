"""CONTRACT-layering L2, L7, L13 and CONTRACT-write-guard G10: layering guards (AST) and controller-only tests.

AST 只管分層，不證明不寫檔；不寫檔由 _writeguard 執行期證明 (tests/_writeguard.py, CONTRACT-write-guard).
"""
import ast
import contextlib
import io
import json
import os
import unittest

from aiohttp.test_utils import AioHTTPTestCase

import _util
from _fakes import JPEG, FakeDarkroom
from darkroom_app.errors import DarkroomError

APP = os.path.join(_util.REPO, "darkroom_app")
FORBIDDEN_CALLS = ("os.path.isfile", "os.listdir", "os.replace")          # + os.replace (PLP8)
FORBIDDEN_NAMES = ("validate_strength", "validate_overrides", "effective_params", "folder_listing", "hashlib")
FORBIDDEN_MODULES = ("darkroom_app.services", "darkroom_app.preview", "hashlib")
FORBIDDEN_STRINGS = ("edits/", "thumbs/", "index/")                       # data_dir layout is the service's (PLP8)
SAFE_WRITE = "safe_write.py"
SAFE_WRITE_USERS = ("services/export.py", "services/preset_library.py", "services/photo_library.py",
                    "services/semantic_index.py")      # G10 whitelist: XP10, K18 / KP3, PL14 / PLP1, WG15 / SI1
SEMANTIC_TOOLS = ["darkroom_semantic_build", "darkroom_semantic_status"]   # verbatim, in order (SI11)
SEMANTIC_BUILD_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                              "openWorldHint": True}   # verbatim (SI11)
LIBRARY_TOOLS = ["darkroom_preset_groups", "darkroom_preset_rename", "darkroom_preset_move", "darkroom_preset_favorite",
                 "darkroom_group_create", "darkroom_group_rename", "darkroom_presets_import", "darkroom_preset_save",
                 "darkroom_presets_rebuild"]          # verbatim, in order (CONTRACT-preset-library K16)
LIBRARY_WRITES = {"darkroom_preset_rename": True, "darkroom_preset_move": True, "darkroom_preset_favorite": True,
                  "darkroom_presets_rebuild": True, "darkroom_group_create": False, "darkroom_group_rename": False,
                  "darkroom_presets_import": False, "darkroom_preset_save": False}   # idempotentHint (K16)
PHOTO_TOOLS = ["darkroom_edit_get", "darkroom_edit_set", "darkroom_edit_clear", "darkroom_edit_paste",
               "darkroom_folder_thumbnails", "darkroom_thumbnail", "darkroom_edit_save_preset"]   # verbatim (PL6, PLP6)
EDIT_WRITES = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}  # PL6
PHOTO_ANNOTATIONS = {"darkroom_edit_set": EDIT_WRITES, "darkroom_edit_clear": EDIT_WRITES,
                     "darkroom_edit_paste": EDIT_WRITES,
                     "darkroom_edit_save_preset": {"readOnlyHint": False, "destructiveHint": False,
                                                   "idempotentHint": False, "openWorldHint": False}}   # PLP6
NATIVE_WRITES = ("write_image", "imwrite", ".save(", ".tofile(")   # G10: no audit event, banned everywhere


def py_files(*parts):
    base = os.path.join(APP, *parts)
    if os.path.isfile(base):
        return [base]
    out = []
    for root, _, files in os.walk(base):
        out += [os.path.join(root, f) for f in files if f.endswith(".py")]
    return sorted(out)


def controllers():
    return py_files("server.py") + py_files("cli.py") + py_files("mcp_server")


def parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), path)


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def package_of(path):
    rel = os.path.relpath(os.path.dirname(path), _util.REPO).replace("\\", "/")
    return rel.replace("/", ".")


def imported_modules(path):
    """Absolute module names a file imports (for `from X import name`, both X and X.name)."""
    pkg = package_of(path).split(".")
    out = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = pkg[: len(pkg) - node.level + 1] if node.level else []
            mod = ".".join(base + ([node.module] if node.module else []))
            out.add(mod)
            out.update(f"{mod}.{a.name}" for a in node.names)
    return out


class TestLayering(unittest.TestCase):
    def test_controllers_hold_no_rules(self):  # L13
        files = controllers()
        self.assertGreaterEqual(len(files), 6)
        for path in files:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Call):
                    self.assertNotIn(dotted(node.func), FORBIDDEN_CALLS, path)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, FORBIDDEN_NAMES, path)
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, FORBIDDEN_NAMES, path)
            for mod in imported_modules(path):
                for bad in FORBIDDEN_MODULES:
                    self.assertFalse(mod == bad or mod.startswith(bad + "."), (path, mod))
            with open(path, encoding="utf-8") as f:
                src = f.read()
            for needle in FORBIDDEN_STRINGS:                    # PLP8: no controller knows the data_dir layout
                self.assertNotIn(needle, src, (path, needle))

    def test_server_uses_engine_and_presets_only_for_appkeys_and_make_app(self):  # L13
        path = py_files("server.py")[0]
        tree = parse(path)
        rule_modules = {m for m in imported_modules(path) if m.startswith("darkroom_app.")
                        and m.split(".")[1] in ("engine", "presets", "preview", "sliders", "skips", "services")}
        self.assertEqual({m.split(".")[1] for m in rule_modules}, {"engine", "presets"})
        for stmt in tree.body:
            used = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)} & {"engine_mod", "Library"}
            if not used or isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue
            ok = (isinstance(stmt, ast.FunctionDef) and stmt.name == "make_app") or (
                isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                and dotted(stmt.value.func) == "web.AppKey")
            self.assertTrue(ok, ast.dump(stmt)[:200])

    def test_services_import_no_interface_libraries(self):  # L13
        files = py_files("services")
        self.assertEqual({os.path.basename(f) for f in files},
                         {"__init__.py", "presets.py", "photos.py", "preview.py", "export.py",
                          "preset_library.py", "photo_library.py", "semantic_index.py"})   # XP1, K16, PL6, SI1
        for path in files:
            for mod in imported_modules(path):
                self.assertNotIn(mod.split(".")[0], ("aiohttp", "argparse"), path)

    def test_mcp_server_never_prints(self):  # L13
        for path in py_files("mcp_server"):
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("print(", f.read(), path)

    def test_recursive_source_scans(self):  # L13: the three scans over darkroom_app/** recursively
        files = py_files()
        self.assertTrue(any(os.sep + "services" + os.sep in f for f in files))
        self.assertTrue(any(os.sep + "mcp_server" + os.sep in f for f in files))
        for path in files:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            for needle in ("0.0.0.0", "--host", "torch.cuda.synchronize", "write_image", "imwrite"):
                self.assertNotIn(needle, src, path)

    def test_no_file_write_path_anywhere(self):  # L12 / L13 (seal patches S1, S7): no code path in darkroom_app writes
        """Photos and presets must never be overwritten: no write-mode open, no file mutation calls at all.

        CONTRACT-write-guard G10: kept as is and no longer extended; scans darkroom_app/** except safe_write.py.
        AST 只管分層，不證明不寫檔；不寫檔由 _writeguard 執行期證明.

        The one exemption is the MCP protocol stream: os.fdopen(protocol_fd, "wb") on the os.dup(1) copy of stdout.
        The other exact exemption (contract patch S7): Engine.open(path) in services/photos.py - receiver `eng`,
        exactly one positional argument, no keywords (it reads the photo). Every other .open(...) is checked.
        """
        banned_calls = {"os.open", "os.remove", "os.unlink", "os.rename", "os.renames", "os.replace", "os.rmdir",
                        "os.removedirs", "os.mkdir", "os.makedirs", "os.truncate", "os.link", "os.symlink",
                        "os.chmod", "os.fdopen", "io.FileIO", "__import__", "exec", "eval", "compile"}
        banned_attrs = {"write_bytes", "write_text", "touch", "unlink", "rmdir", "symlink_to", "hardlink_to",
                        "rename", "mkdir", "chmod", "imwrite", "write_image", "tofile", "save"}
        mutating_names = {"open", "write_bytes", "write_text", "replace", "rename", "remove", "unlink", "mkdir",
                          "makedirs", "rmdir", "touch", "chmod", "truncate", "FileIO", "fdopen"}
        banned_modules = ("shutil", "tempfile", "pathlib", "builtins")
        open_funcs = ("open", "io.open", "builtins.open", "codecs.open")
        offenders = []

        def literal_str(c):
            return isinstance(c, ast.Constant) and isinstance(c.value, str)

        def bad_mode(c):        # a mode that may write: a write letter, or anything that is not a plain literal
            return c is not None and not (literal_str(c) and not set(c.value) & set("wax+"))

        for path in py_files():
            rel = os.path.relpath(path, APP).replace("\\", "/")
            if rel == SAFE_WRITE:         # G10: the one write module is guarded at run time, not by this list
                continue
            tree = parse(path)
            alias = {}               # local name -> real dotted name (import os as o; from os import replace as r)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    alias.update({a.asname: a.name for a in node.names if a.asname})
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    alias.update({a.asname or a.name: f"{node.module}.{a.name}" for a in node.names})
            for mod in imported_modules(path):
                if mod.split(".")[0] in banned_modules:
                    offenders.append((rel, 0, "import " + mod))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in ("builtins", "__builtins__"):
                    offenders.append((rel, node.lineno, node.id))
                if not isinstance(node, ast.Call):
                    continue
                name = dotted(node.func)
                if name:
                    head, _, rest = name.partition(".")
                    name = alias.get(head, head) + ("." + rest if rest else "")
                attr = node.func.attr if isinstance(node.func, ast.Attribute) else None
                mode_kw = next((k.value for k in node.keywords if k.arg == "mode"), None)
                if name in open_funcs:
                    if bad_mode(node.args[1] if len(node.args) > 1 else None) or bad_mode(mode_kw):
                        offenders.append((rel, node.lineno, name))
                elif name == "os.open":       # S1: banned outright, however the flags are spelled (path=, flags=)
                    offenders.append((rel, node.lineno, name))
                elif attr == "open":          # Path(p).open(m), gzip/lzma/tarfile.open(p, m), zf.open(n, m), ...
                    # exact exemption (S7): Engine.open(path) in services/photos.py - receiver `eng`, one
                    # positional argument, no keywords; every other .open(...) gets the full rule
                    engine_read = (rel == "services/photos.py" and isinstance(node.func.value, ast.Name)
                                   and node.func.value.id == "eng" and len(node.args) == 1 and not node.keywords)
                    first_two = node.args[:2]
                    if not engine_read and (
                            any(literal_str(a) and set(a.value) & set("wax+") for a in first_two)   # write letter
                            or (len(node.args) > 1 and not literal_str(node.args[1]))           # computed mode
                            or (len(node.args) == 1 and not literal_str(node.args[0]))          # Path(p).open(m)
                            or bad_mode(mode_kw)):
                        offenders.append((rel, node.lineno, ".open"))
                elif name == "os.fdopen" and rel == "mcp_server/__init__.py" and len(node.args) >= 1 \
                        and isinstance(node.args[0], ast.Name) and node.args[0].id == "protocol_fd":
                    continue
                elif name in banned_calls:
                    offenders.append((rel, node.lineno, name))
                elif attr in banned_attrs:
                    offenders.append((rel, node.lineno, attr))
                elif attr == "replace" and len(node.args) < 2:      # Path.replace(target); str.replace takes two
                    offenders.append((rel, node.lineno, ".replace"))
                elif name == "getattr" and len(node.args) >= 2:
                    target, what = node.args[0], node.args[1]
                    if (literal_str(what) and what.value in mutating_names) or (
                            not literal_str(what) and dotted(target) in ("os", "io", "codecs", "shutil")):
                        offenders.append((rel, node.lineno, "getattr"))
        self.assertEqual(offenders, [])
        with open(os.path.join(APP, "mcp_server", "__init__.py"), encoding="utf-8") as fh:
            self.assertIn("protocol_fd = os.dup(1)", fh.read())     # the exemption is only for the dup of stdout

    def test_only_safe_write_writes(self):  # CONTRACT-write-guard G10
        """Only the whitelisted modules may import safe_write; native writers are banned everywhere.

        AST 只管分層，不證明不寫檔；不寫檔由 _writeguard 執行期證明.
        """
        files = py_files()
        self.assertIn(os.path.join(APP, SAFE_WRITE), files)
        self.assertEqual(SAFE_WRITE_USERS, ("services/export.py", "services/preset_library.py",
                                            "services/photo_library.py", "services/semantic_index.py"))   # + SI1
        for path in files:
            rel = os.path.relpath(path, APP).replace("\\", "/")
            with open(path, encoding="utf-8") as f:
                src = f.read()
            for needle in NATIVE_WRITES:
                self.assertNotIn(needle, src, (rel, needle))
            if rel == SAFE_WRITE or rel in SAFE_WRITE_USERS:
                continue
            mods = imported_modules(path)
            self.assertFalse({"darkroom_app.safe_write", "safe_write"} & mods, rel)
            self.assertNotIn("safe_write", src, rel)          # no importlib / __import__ spelling either

    def test_facade_methods_forward_once(self):  # L2
        from darkroom_app.facade import DarkroomFacade, Facade
        from darkroom_app.operations import OPERATIONS
        tree = parse(py_files("facade.py")[0])
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DarkroomFacade")
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual([m.name for m in methods], list(OPERATIONS))
        for m in methods:
            self.assertEqual(len(m.body), 1, m.name)
            ret = m.body[0]
            self.assertIsInstance(ret, ast.Return, m.name)
            self.assertIsInstance(ret.value, ast.Call, m.name)
            f = ret.value.func
            self.assertIsInstance(f, ast.Attribute, m.name)
            self.assertEqual(f.attr, m.name)
            self.assertEqual(dotted(f.value).split(".")[0], "self", m.name)
            self.assertEqual(sum(isinstance(n, ast.Return) for n in ast.walk(m)), 1, m.name)
        proto = [n for n, v in vars(Facade).items() if callable(v) and not n.startswith("_")]
        self.assertEqual(proto, list(OPERATIONS))
        self.assertEqual(list(OPERATIONS), ["list_presets", "preset_detail", "preset_flags", "slider_table",
                                            "open_photo", "list_folder", "preview", "export",   # XP1
                                            "preset_groups", "rename_preset", "move_preset", "set_favorite",
                                            "create_group", "rename_group", "import_presets", "save_user_preset",
                                            "rebuild_library",   # CONTRACT-preset-library K16
                                            "get_edit", "set_edit", "clear_edit", "paste_edit", "folder_thumbnails",
                                            "thumbnail", "save_edit_as_preset",   # CONTRACT-photo-library PL6, PLP6
                                            "semantic_build", "semantic_status"])   # CONTRACT-semantic-index SI1
        self.assertTrue(issubclass(DarkroomFacade, Facade))

    def test_operation_coverage(self):  # L2: every registered route, subcommand and tool exists
        import inspect
        from darkroom_app import cli
        from darkroom_app.facade import Facade
        from darkroom_app.mcp_server.tools import Tools
        from darkroom_app.operations import OPERATIONS
        from darkroom_app.server import make_app
        from test_app_server import make_presets
        d = os.path.join(_util.tmpdir(self), "p")
        os.makedirs(d)
        app = make_app(make_presets(d), engine=_NoEngine())
        routes = {(r.method, r.resource.canonical) for r in app.router.routes()}
        tools = [t["name"] for t in Tools(lambda: None).list()]
        self.assertEqual(tools, [spec["mcp"] for spec in OPERATIONS.values()])
        for op, spec in OPERATIONS.items():
            self.assertIn(tuple(spec["http"]), routes, op)
            parser = cli._parser()
            for word in spec["cli"].split():
                action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
                self.assertIn(word, action.choices, op)
                parser = action.choices[word]
            self.assertIn("--json", parser._option_string_actions, op)
            params = [n for n in inspect.signature(getattr(Facade, op)).parameters if n != "self"]
            self.assertEqual(list(spec["input_schema"]["properties"]), params, op)
            self.assertEqual(spec["input_schema"]["type"], "object")
            self.assertIs(spec["input_schema"]["additionalProperties"], False)
            for k in spec["mcp_defaults"]:
                self.assertIn(k, params, op)
        self.assertEqual(OPERATIONS["list_presets"]["mcp_defaults"], {"limit": 50})
        self.assertEqual(OPERATIONS["preview"]["mcp_defaults"], {"max_pixels": 786432})
        # CONTRACT-export XP1 / XP4: export is the 8th operation, its tool is last, with exactly these annotations
        self.assertEqual(OPERATIONS["export"]["http"], ("POST", "/api/export"))
        self.assertEqual((OPERATIONS["export"]["cli"], OPERATIONS["export"]["mcp"]), ("export", "darkroom_export"))
        listed = {t["name"]: t["annotations"] for t in Tools(lambda: None).list()}
        self.assertEqual(list(listed)[7], "darkroom_export")          # K16: the library tools come after export
        self.assertEqual(listed["darkroom_export"], {"readOnlyHint": False, "destructiveHint": False,
                                                     "idempotentHint": False, "openWorldHint": False})
        self.assertEqual(list(listed)[8:17], LIBRARY_TOOLS)
        self.assertEqual(list(listed)[17:24], PHOTO_TOOLS)                 # PL6 / PLP6: operations 18..24
        self.assertEqual(list(listed)[24:], SEMANTIC_TOOLS)                # SI1 / SI11: operations 25, 26
        for name, ann in listed.items():
            if name in LIBRARY_WRITES:
                self.assertEqual(ann, {"readOnlyHint": False, "destructiveHint": False,
                                       "idempotentHint": LIBRARY_WRITES[name], "openWorldHint": False}, name)
            elif name in PHOTO_ANNOTATIONS:
                self.assertEqual(ann, PHOTO_ANNOTATIONS[name], name)
            elif name == "darkroom_semantic_build":
                self.assertEqual(ann, SEMANTIC_BUILD_ANNOTATIONS)          # SI11: the one open-world tool
            elif name != "darkroom_export":
                self.assertEqual(ann, {"readOnlyHint": True, "openWorldHint": False}, name)
        self.assertEqual(OPERATIONS["semantic_build"]["mcp_defaults"], {"wait_seconds": 0})     # SI9
        self.assertEqual(OPERATIONS["semantic_build"]["http"], ("POST", "/api/preset-library/semantic/build"))
        self.assertEqual(OPERATIONS["semantic_status"]["http"], ("GET", "/api/preset-library/semantic"))
        self.assertEqual(OPERATIONS["folder_thumbnails"]["mcp_defaults"], {"limit": 50})
        self.assertEqual(OPERATIONS["set_edit"]["http"], ("PUT", "/api/edit"))
        self.assertEqual(OPERATIONS["clear_edit"]["http"], ("DELETE", "/api/edit"))
        schema = OPERATIONS["export"]["input_schema"]
        self.assertEqual(schema["required"], ["items", "format"])

    def test_fake_matches_facade(self):  # L13
        from darkroom_app.facade import Facade
        f = FakeDarkroom()
        self.assertIsInstance(f, Facade)
        public = lambda c: {n for n in dir(c) if not n.startswith("_") and callable(getattr(c, n))}
        self.assertEqual(public(FakeDarkroom), {n for n, v in vars(Facade).items()
                                                if callable(v) and not n.startswith("_")})


class _NoEngine:
    """Stand-in Engine for route-only checks (no GPU)."""
    images = {}

    def shutdown(self):
        pass


KINDS = {"invalid": (400, 2), "not_found": (404, 3), "conflict": (409, 4), "unavailable": (503, 5)}


class TestHttpControllerWithFake(AioHTTPTestCase):  # L7 / L13: HTTP translation only
    async def get_client(self, server):
        from aiohttp.test_utils import TestClient
        return TestClient(server, headers=_util.HTTP_HEADERS)     # PLP11

    async def get_application(self):
        from darkroom_app.server import FACADE, make_app
        from test_app_server import make_presets
        d = os.path.join(_util.tmpdir(self), "p")
        os.makedirs(d)
        app = make_app(make_presets(d), engine=_NoEngine())
        self.fake = FakeDarkroom()
        app[FACADE] = self.fake
        return app

    async def test_success_translation(self):
        r = await self.client.get("/api/presets")
        self.assertEqual(await r.json(), [{"id": "fake-1", "group": "假群組", "name": "假一", "supported": True,
                                           "skipped": [], "favorite": False, "tags": []}])
        r = await self.client.post("/api/preview", json={"image_id": "i", "preset_id": "p", "overrides": {"a": 1}})
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.read(), JPEG)
        self.assertEqual(r.headers["X-Render-Ms"], "1.23")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["Access-Control-Expose-Headers"], "X-Render-Ms")
        await self.client.get("/api/folder")
        await self.client.post("/api/open", json={"path": " x "})
        await self.client.get("/api/presets/abc")
        self.assertEqual(self.fake.calls, [("list_presets", (None, 0, None, False)),
                                           ("preview", ("i", "p", 100, {"a": 1}, None)),
                                           ("list_folder", ("",)), ("open_photo", (" x ",)),
                                           ("preset_detail", ("abc",))])

    async def test_export_translation(self):  # CONTRACT-export XP1 / XP11: 200 with results, no failed count
        items = [{"path": "a.jpg"}, {"path": "b.jpg", "preset_id": "p"}]
        r = await self.client.post("/api/export", json={"items": items, "format": "tiff", "quality": 80})
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.json(), {"results": RESULTS})
        r = await self.client.post("/api/export", json={"items": items[:1]})
        for dest in ("D:\\x", None):          # XP16: no dest_dir over HTTP, refused before the facade
            r = await self.client.post("/api/export", json={"items": items, "format": "jpeg", "dest_dir": dest})
            self.assertEqual((r.status, await r.json()),
                             (400, {"error": "dest_dir is not accepted over HTTP (use the CLI or MCP)"}))
        self.assertEqual(self.fake.calls, [("export", (items, "tiff", 80, None)),
                                           ("export", (items[:1], None, None, None))])
        self.fake.fail["export"] = DarkroomError("invalid", "沒有要匯出的照片")
        r = await self.client.post("/api/export", json={"items": []})
        self.assertEqual((r.status, await r.json()), (400, {"error": "沒有要匯出的照片"}))

    async def test_error_translation(self):
        for kind, (status, _) in KINDS.items():
            self.fake.fail["preset_flags"] = DarkroomError(kind, f"句子 {kind}")
            r = await self.client.get("/api/preset_flags")
            self.assertEqual((r.status, await r.json()), (status, {"error": f"句子 {kind}"}))
        self.fake.fail["preset_flags"] = RuntimeError("boom")
        with self.assertLogs("aiohttp.server", "ERROR"):
            r = await self.client.get("/api/preset_flags")
        self.assertEqual(r.status, 500)


RESULTS = [{"ok": True, "source": "a.jpg", "output": "D:\\out\\a.jpg"},
                   {"ok": False, "source": "b.jpg", "error": "匯出失敗：b.jpg：壞了"}]


class TestCliControllerWithFake(unittest.TestCase):  # L7 / L9 / L13
    def run_cli(self, argv, fake):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv, facade=fake)
        return rc, out.getvalue(), err.getvalue()

    def test_translation(self):
        fake = FakeDarkroom()
        rc, out, err = self.run_cli(["preview", "a.jpg", "--preset", "p", "--strength", "50", "--override",
                                     "Exposure2012=0.5", "--override", "Contrast2012=x", "--max-pixels", "70000",
                                     "--json"], fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out), {"ok": True, "result": {"render_ms": 1.23456, "width": 4, "height": 2,
                                                                  "jpeg_base64": "/9hmYWtlLWpwZWf/2Q=="}})
        self.assertEqual(fake.calls, [("open_photo", ("a.jpg",)),
                                      ("preview", ("fake-image", "p", 50.0,
                                                   {"Exposure2012": 0.5, "Contrast2012": "x"}, 70000))])
        fake.calls.clear()
        self.run_cli(["presets", "list", "--query", "q", "--offset", "3", "--limit", "7", "--json"], fake)
        self.run_cli(["folder", "b.png", "--json"], fake)
        self.assertEqual(fake.calls, [("list_presets", ("q", 3, 7, False)), ("open_photo", ("b.png",)),
                                      ("list_folder", ("fake-image",))])

    def test_cli_export_json(self):  # CONTRACT-export XP3 / XP11
        fake = FakeDarkroom()
        rc, out, err = self.run_cli(["export", "a.jpg", "b.jpg", "--preset", "p", "--strength", "50", "--override",
                                     "Exposure2012=0.5", "--format", "tiff", "--quality", "80", "--dest-dir", "D:\\x",
                                     "--json"], fake)
        self.assertEqual((rc, err), (6, ""))                         # one photo failed: exit 6, full result kept
        self.assertEqual(out, json.dumps({"ok": True, "result": {"results": RESULTS}}, ensure_ascii=False,
                                         separators=(",", ":")) + "\n")
        item = {"preset_id": "p", "strength": 50.0, "overrides": {"Exposure2012": 0.5}}
        self.assertEqual(fake.calls, [("export", ([{"path": "a.jpg", **item}, {"path": "b.jpg", **item}],
                                                  "tiff", 80, "D:\\x"))])
        rc, out, err = self.run_cli(["export", "a.jpg", "b.jpg"], fake)
        self.assertEqual((rc, out, err), (6, "已匯出：D:\\out\\a.jpg\n匯出失敗：b.jpg：壞了\n", ""))
        rc, out, err = self.run_cli(["export", "a.jpg", "--json"], fake)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out)["result"]["results"], RESULTS[:1])
        self.assertEqual(fake.calls[-1], ("export", ([{"path": "a.jpg", "preset_id": None, "strength": 100,
                                                       "overrides": None}], "jpeg", None, None)))
        rc, out, err = self.run_cli(["export", "--quality", "abc", "--json"], fake)   # the service judges it
        self.assertEqual(fake.calls[-1], ("export", ([], "jpeg", "abc", None)))
        fake.fail["export"] = DarkroomError("invalid", "沒有要匯出的照片")
        self.assertEqual(self.run_cli(["export"], fake), (2, "", "沒有要匯出的照片\n"))

    def test_error_translation(self):
        for kind, (_, code) in KINDS.items():
            fake = FakeDarkroom()
            fake.fail["slider_table"] = DarkroomError(kind, f"句子 {kind}")
            self.assertEqual(self.run_cli(["sliders"], fake), (code, "", f"句子 {kind}\n"))
            rc, out, err = self.run_cli(["sliders", "--json"], fake)
            self.assertEqual((rc, err), (code, ""))
            self.assertEqual(out, json.dumps({"ok": False, "error": {"kind": kind, "message": f"句子 {kind}"}},
                                             ensure_ascii=False, separators=(",", ":")) + "\n")
        fake = FakeDarkroom()
        fake.fail["slider_table"] = KeyError("x")
        self.assertEqual(self.run_cli(["sliders", "--json"], fake), (1, "", "未預期錯誤：KeyError：'x'\n"))


class TestMcpControllerWithFake(unittest.TestCase):  # L7 / L10 / L13
    def exchange(self, fake, *calls):
        from darkroom_app.mcp_server import serve
        msgs = b"".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                    "params": {"name": n, "arguments": a}}).encode() + b"\n"
                        for i, (n, a) in enumerate(calls, 1))
        out = io.BytesIO()
        serve(io.BytesIO(msgs), out, facade=fake)
        return [json.loads(x) for x in out.getvalue().decode("utf-8").splitlines()]

    def test_translation_and_defaults(self):
        fake = FakeDarkroom()
        res = self.exchange(fake, ("darkroom_presets_list", {}), ("darkroom_preview", {"image_id": "i"}),
                            ("darkroom_presets_list", {"limit": 3, "query": "q"}),
                            ("darkroom_preview", {"image_id": "i", "max_pixels": None, "strength": 5}))
        self.assertEqual(fake.calls, [("list_presets", (None, 0, 50, False)),
                                      ("preview", ("i", None, 100, None, 786432)),
                                      ("list_presets", ("q", 0, 3, False)), ("preview", ("i", None, 5, None, None))])
        self.assertEqual(res[1]["result"], {"content": [{"type": "image", "mimeType": "image/jpeg",
                                                         "data": "/9hmYWtlLWpwZWf/2Q=="}],
                                            "structuredContent": {"render_ms": 1.23456, "width": 4, "height": 2}})

    def test_mcp_export_annotations(self):  # CONTRACT-export XP4 / XP11
        from darkroom_app.mcp_server.tools import Tools
        tool = Tools(lambda: None).list()[7]
        self.assertEqual(tool["name"], "darkroom_export")
        self.assertEqual(tool["annotations"], {"readOnlyHint": False, "destructiveHint": False,
                                               "idempotentHint": False, "openWorldHint": False})
        self.assertEqual(tool["inputSchema"]["required"], ["items", "format"])
        fake = FakeDarkroom()
        items = [{"path": "a.jpg"}, {"path": "b.jpg"}]
        res = self.exchange(fake, ("darkroom_export", {"items": items, "format": "jpeg"}),
                            ("darkroom_export", {"items": items[:1], "format": "tiff", "quality": 5, "dest_dir": "D"}))
        self.assertEqual(fake.calls, [("export", (items, "jpeg", None, None)), ("export", (items[:1], "tiff", 5, "D"))])
        sc = {"results": RESULTS, "failed": 1}
        self.assertEqual(res[0]["result"], {"content": [{"type": "text", "text": json.dumps(sc, ensure_ascii=False)}],
                                            "structuredContent": sc})
        self.assertEqual(res[1]["result"]["structuredContent"], {"results": RESULTS[:1], "failed": 0})
        self.assertNotIn("isError", res[1]["result"])

    def test_error_translation(self):
        for kind in KINDS:
            fake = FakeDarkroom()
            fake.fail["open_photo"] = DarkroomError(kind, f"句子 {kind}", {"path": "p"})
            res = self.exchange(fake, ("darkroom_open_photo", {"path": "p"}))
            self.assertEqual(res[0]["result"], {"content": [{"type": "text", "text": f"句子 {kind}"}],
                                                "structuredContent": {"kind": kind, "message": f"句子 {kind}",
                                                                      "path": "p"},
                                                "isError": True})
        fake = FakeDarkroom()
        fake.fail["open_photo"] = ZeroDivisionError("x")
        res = self.exchange(fake, ("darkroom_open_photo", {"path": "p"}), ("darkroom_open_photo", {"bogus": 1}))
        self.assertEqual(res[0]["error"]["code"], -32603)
        self.assertEqual(res[1]["error"]["code"], -32602)
        self.assertEqual(res[1]["error"]["message"], "Unknown argument for darkroom_open_photo: bogus")   # S3


if __name__ == "__main__":
    unittest.main()
