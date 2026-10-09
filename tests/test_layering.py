"""CONTRACT-layering L2, L7, L13: layering guards (AST) and controller-only tests against FakeDarkroom."""
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
FORBIDDEN_CALLS = ("os.path.isfile", "os.listdir")
FORBIDDEN_NAMES = ("validate_strength", "validate_overrides", "effective_params", "folder_listing")
FORBIDDEN_MODULES = ("darkroom_app.services", "darkroom_app.preview")


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
        self.assertEqual({os.path.basename(f) for f in files}, {"__init__.py", "presets.py", "photos.py", "preview.py"})
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

    def test_no_file_write_path_anywhere(self):  # L12 / L13 (seal patch S1): no code path in darkroom_app writes
        """Photos and presets must never be overwritten: no write-mode open, no file mutation calls at all.

        The one exemption is the MCP protocol stream: os.fdopen(protocol_fd, "wb") on the os.dup(1) copy of stdout.
        """
        banned_calls = {"os.open", "os.remove", "os.unlink", "os.rename", "os.renames", "os.replace", "os.rmdir",
                        "os.removedirs", "os.mkdir", "os.makedirs", "os.truncate", "os.link", "os.symlink",
                        "os.fdopen", "io.FileIO"}
        banned_attrs = {"write_bytes", "write_text", "touch", "unlink", "rmdir", "symlink_to", "hardlink_to",
                        "imwrite", "write_image", "tofile", "save"}
        offenders = []

        def writes(c):
            return isinstance(c, ast.Constant) and isinstance(c.value, str) and bool(set(c.value) & set("wax+"))
        for path in py_files():
            rel = os.path.relpath(path, APP).replace("\\", "/")
            tree = parse(path)
            alias = {}               # local name -> real dotted name (import os as o; from os import replace as r)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    alias.update({a.asname: a.name for a in node.names if a.asname})
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    alias.update({a.asname or a.name: f"{node.module}.{a.name}" for a in node.names})
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for mod in imported_modules(path):
                        if mod.split(".")[0] in ("shutil", "tempfile"):
                            offenders.append((rel, node.lineno, mod))
                if not isinstance(node, ast.Call):
                    continue
                name = dotted(node.func)
                if name:
                    head, _, rest = name.partition(".")
                    name = alias.get(head, head) + ("." + rest if rest else "")
                mode_kw = next((k.value for k in node.keywords if k.arg == "mode"), None)
                is_open = name in ("open", "io.open", "builtins.open", "codecs.open") or (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "open")
                if is_open:
                    # any write-mode constant in the first two positions or mode=, for open() and every .open()
                    # (Path(...).open("wb"), codecs.open(p, "w")); a non-constant mode= is refused outright
                    if any(writes(a) for a in node.args[:2]) or writes(mode_kw) or (
                            mode_kw is not None and not isinstance(mode_kw, ast.Constant)):
                        offenders.append((rel, node.lineno, name or node.func.attr))
                    elif name in ("open", "io.open", "builtins.open") and len(node.args) > 1                             and not isinstance(node.args[1], ast.Constant):
                        offenders.append((rel, node.lineno, name))
                elif name == "os.fdopen" and rel == "mcp_server/__init__.py" and len(node.args) >= 1                         and isinstance(node.args[0], ast.Name) and node.args[0].id == "protocol_fd":
                    continue
                elif name in banned_calls:
                    offenders.append((rel, node.lineno, name))
                elif isinstance(node.func, ast.Attribute) and node.func.attr in banned_attrs:
                    offenders.append((rel, node.lineno, node.func.attr))
        self.assertEqual(offenders, [])
        src = open(os.path.join(APP, "mcp_server", "__init__.py"), encoding="utf-8").read()
        self.assertIn("protocol_fd = os.dup(1)", src)     # the exemption is only for the dup of stdout

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
                                            "open_photo", "list_folder", "preview"])
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
                                           "skipped": []}])
        r = await self.client.post("/api/preview", json={"image_id": "i", "preset_id": "p", "overrides": {"a": 1}})
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.read(), JPEG)
        self.assertEqual(r.headers["X-Render-Ms"], "1.23")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["Access-Control-Expose-Headers"], "X-Render-Ms")
        await self.client.get("/api/folder")
        await self.client.post("/api/open", json={"path": " x "})
        await self.client.get("/api/presets/abc")
        self.assertEqual(self.fake.calls, [("list_presets", (None, 0, None)),
                                           ("preview", ("i", "p", 100, {"a": 1}, None)),
                                           ("list_folder", ("",)), ("open_photo", (" x ",)),
                                           ("preset_detail", ("abc",))])

    async def test_error_translation(self):
        for kind, (status, _) in KINDS.items():
            self.fake.fail["preset_flags"] = DarkroomError(kind, f"句子 {kind}")
            r = await self.client.get("/api/preset_flags")
            self.assertEqual((r.status, await r.json()), (status, {"error": f"句子 {kind}"}))
        self.fake.fail["preset_flags"] = RuntimeError("boom")
        with self.assertLogs("aiohttp.server", "ERROR"):
            r = await self.client.get("/api/preset_flags")
        self.assertEqual(r.status, 500)


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
        self.assertEqual(fake.calls, [("list_presets", ("q", 3, 7)), ("open_photo", ("b.png",)),
                                      ("list_folder", ("fake-image",))])

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
        self.assertEqual(fake.calls, [("list_presets", (None, 0, 50)), ("preview", ("i", None, 100, None, 786432)),
                                      ("list_presets", ("q", 0, 3)), ("preview", ("i", None, 5, None, None))])
        self.assertEqual(res[1]["result"], {"content": [{"type": "image", "mimeType": "image/jpeg",
                                                         "data": "/9hmYWtlLWpwZWf/2Q=="}],
                                            "structuredContent": {"render_ms": 1.23456, "width": 4, "height": 2}})

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
