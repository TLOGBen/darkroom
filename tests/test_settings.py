"""plan-v2 §3: settings - the domain rules, the settings file store, the service, live re-composition, and the HTTP /
CLI / MCP entry points (the three-interface parity of the same steps is test_interface_parity.TestSettingsParity).

Every test writes only into its own temporary folder: the settings file is a temporary file handed in through
`settings_path` or `DARKROOM_CONFIG` - the repository's config.local.json is never read for writing nor written.
"""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from aiohttp.test_utils import AioHTTPTestCase, TestClient

import _util
from darkroom_app.domain import messages as M
from darkroom_app.domain import settings as S
from darkroom_app.domain.errors import DarkroomError
from test_app_server import make_presets

NO_NET = {"comfyui": lambda: (False, "假的 ComfyUI"), "agent_sdk": lambda: (False, "假的 SDK"),
          "semantic_index": lambda: (False, "假的語意索引"), "onepassword": lambda: (False, "假的 1Password")}


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


class World:
    """A preset folder, a data folder and a settings file, all inside one temporary root."""

    def __init__(self, test, config=None):
        self.root = _util.tmpdir(test)
        self.pd = os.path.join(self.root, "lib", "xmp")
        self.data = os.path.join(self.root, "data")
        os.makedirs(self.pd)
        os.makedirs(self.data)
        make_presets(self.pd)
        self.cfg = os.path.join(self.root, "config.json")
        if config is not None:
            write_json(self.cfg, config)

    def facade(self, **kw):
        from darkroom_app.composition import build_facade
        return build_facade(self.pd, data_dir=self.data, detect=dict(NO_NET), settings_path=lambda: self.cfg, **kw)


def err(fn, *a, **k):
    try:
        fn(*a, **k)
    except DarkroomError as e:
        return e.kind, e.message
    raise AssertionError("no DarkroomError")


class TestDomain(unittest.TestCase):
    def test_flatten_reads_new_and_old_keys(self):
        obj = {"anthropic_api_key_ref": "op://v/i/f", "semantic_index_budget_usd": 2.5, "language": "en-US",
               "data_dir": "rel", "agent": {"model": "m"}, "other": 1}
        base = "C:\\base" if os.name == "nt" else "/base"            # absolute on this platform
        flat = S.flatten(obj, base_dir=base)
        self.assertEqual(flat, {"language": "en-US", "data_dir": os.path.normpath(os.path.join(base, "rel")),
                                "agent.api_key_ref": "op://v/i/f", "agent.model": "m", "agent.budget_usd": 2.5})
        obj["agent"]["api_key_ref"] = "op://new/i/f"                 # the new key wins over the old name
        self.assertEqual(S.flatten(obj)["agent.api_key_ref"], "op://new/i/f")

    def test_file_with_writes_new_shape_and_keeps_unknown_keys(self):
        obj = {"anthropic_api_key_ref": "op://v/i/f", "keep_me": [1], "agent": {"model": "m"}}
        out = S.file_with(obj, {"agent.api_key_ref": "op://v/i/g", "language": "en-US"})
        self.assertEqual(out, {"keep_me": [1], "agent": {"model": "m", "api_key_ref": "op://v/i/g"},
                               "language": "en-US"})
        out = S.file_with(out, {"agent.model": None, "agent.api_key_ref": None, "language": None})
        self.assertEqual(out, {"keep_me": [1]})                       # an empty "agent" object is dropped
        self.assertEqual(obj["agent"], {"model": "m"})                # the input is not changed

    def test_effective_sources_and_defaults(self):
        llm, local = ("E:\\llm", "C:\\L") if os.name == "nt" else ("/e/llm", "/c/L")   # absolute on this platform
        env = {"LOCALLLMS_ROOT": llm, "LOCALAPPDATA": local}
        settings, defaults, sources = S.effective({"language": "en-US", "localllms_root": "X:\\ignored"}, env, "win32")
        self.assertEqual(list(settings), list(S.KEYS))
        self.assertEqual(sources["localllms_root"], "env")             # LOCALLLMS_ROOT wins (as config.load)
        self.assertEqual(sources["language"], "file")
        self.assertEqual(sources["preset_dir"], "default")
        self.assertEqual(settings["preset_dir"], os.path.join(llm, "artifact", "11_preset", "xmp"))
        self.assertEqual(settings["preset_library_dir"], os.path.join(llm, "artifact", "11_preset"))
        self.assertEqual(settings["data_dir"], os.path.join(local, "darkroom"))
        self.assertEqual((settings["comfyui_url"], settings["agent.model"], settings["agent.budget_usd"]),
                         ("http://127.0.0.1:8188", "claude-haiku-5-5", 5.0))
        self.assertEqual(defaults["language"], "zh-TW")

    def test_validate_changes(self):
        tmp = _util.tmpdir(self)
        pd = os.path.join(tmp, "presets")
        os.makedirs(pd)
        isdir = os.path.isdir
        cur = {"preset_dir": pd}
        bad = [({"colour": 1}, M.SET_UNKNOWN_KEY.format(key="colour", keys="、".join(S.KEYS))),
               ({}, M.SET_NOTHING),
               ({"language": "fr"}, M.SET_LANGUAGE.format(value="fr")),
               ({"data_dir": "relative"}, M.SET_PATH_TYPE.format(key="data_dir", value="relative")),
               ({"preset_dir": os.path.join(tmp, "nope")},
                M.SET_PATH_MISSING.format(key="preset_dir", value=os.path.join(tmp, "nope"))),
               ({"data_dir": os.path.join(tmp, "a", "b")},
                M.SET_DATA_DIR_PARENT.format(value=os.path.join(tmp, "a", "b"))),
               ({"data_dir": os.path.join(pd, "data")},
                M.SET_INSIDE_PRESET_DIR.format(key="data_dir", value=os.path.join(pd, "data"))),
               ({"comfyui_url": "http://example.com:8188"}, M.SET_URL.format(value="http://example.com:8188")),
               ({"comfyui_url": "http://127.0.0.1"}, M.SET_URL.format(value="http://127.0.0.1")),
               ({"agent.api_key_ref": "sk-ant-api03-xyz"}, M.SET_SECRET),
               ({"agent.api_key_ref": "vault/item"}, M.SET_KEY_REF.format(value="vault/item")),
               ({"agent.model": "two words"}, M.SET_MODEL.format(value="two words")),
               ({"agent.budget_usd": 0}, M.SET_BUDGET.format(value=0)),
               ({"agent.budget_usd": True}, M.SET_BUDGET.format(value=True)),
               ([1], M.SET_NOT_OBJECT.format(value=[1])),
               ({"language": "en-US", "colour": 1}, M.SET_UNKNOWN_KEY.format(key="colour", keys="、".join(S.KEYS)))]
        for values, sentence in bad:
            self.assertEqual(err(S.validate_changes, values, cur, isdir), ("invalid", sentence), values)
        ok = S.validate_changes({"language": "en-US", "data_dir": os.path.join(tmp, "new-data"), "comfyui_root": "",
                                 "comfyui_url": "http://localhost:8190/", "agent.api_key_ref": " op://v/i/f ",
                                 "agent.budget_usd": 2}, cur, isdir)
        self.assertEqual(ok, {"language": "en-US", "data_dir": os.path.join(tmp, "new-data"), "comfyui_url":
                              "http://localhost:8190", "comfyui_root": None, "agent.api_key_ref": "op://v/i/f",
                              "agent.budget_usd": 2})

    def test_export_document(self):
        doc = S.export_document({"language": "en-US"}, "9.9.9")
        self.assertEqual(doc, {"format": "darkroom-settings/1", "version": "9.9.9", "settings": {"language": "en-US"}})
        self.assertEqual(S.document_values(doc), {"language": "en-US"})
        for bad in ({"format": "x", "settings": {}}, {"format": S.FORMAT, "settings": []}, [],
                    {"format": S.FORMAT, "settings": {}, "extra": 1}):
            self.assertEqual(err(S.document_values, bad), ("invalid", M.SET_DOC_FORMAT.format(format=S.FORMAT)))


class TestStoreLocation(unittest.TestCase):
    def test_locate_order(self):
        from darkroom_app.adapters.persist.settings_store import locate, platform_path
        tmp = _util.tmpdir(self)
        repo_file = os.path.join(tmp, "config.local.json")
        appdata = os.path.join(tmp, "appdata")
        plat = os.path.join(appdata, "darkroom", "config.json")
        env = {"APPDATA": appdata}
        self.assertEqual(platform_path(env, "win32"), plat)
        self.assertEqual(platform_path({"XDG_CONFIG_HOME": tmp}, "linux"), os.path.join(tmp, "darkroom", "config.json"))
        self.assertEqual(locate(repo_file, env, "win32"), plat)                # nothing exists: the platform file
        os.makedirs(os.path.dirname(plat))
        write_json(plat, {})
        self.assertEqual(locate(repo_file, env, "win32"), plat)
        write_json(repo_file, {})
        self.assertEqual(locate(repo_file, env, "win32"), repo_file)           # the repository file comes first
        given = os.path.join(tmp, "elsewhere.json")
        self.assertEqual(locate(repo_file, dict(env, DARKROOM_CONFIG=given), "win32"), given)   # DARKROOM_CONFIG wins

    def test_config_reads_darkroom_config(self):
        from darkroom_app import config
        tmp = _util.tmpdir(self)
        cfg = os.path.join(tmp, "c.json")
        write_json(cfg, {"agent": {"api_key_ref": "op://a/b/c", "budget_usd": 1.5}, "comfyui_url": "http://[::1]:9/"})
        with mock.patch.dict(os.environ, {"DARKROOM_CONFIG": cfg}):
            self.assertEqual(config.config_path(), cfg)
            self.assertEqual(config.anthropic_api_key_ref(), "op://a/b/c")
            self.assertEqual(config.semantic_index_budget_usd(), 1.5)
            self.assertEqual(config.comfyui_url(), "http://[::1]:9")


class TestService(unittest.TestCase):
    def test_get_set_all_or_nothing(self):
        w = World(self, {"keep_me": True, "semantic_index_budget_usd": 2})
        f = w.facade()
        got = f.get_settings()
        self.assertEqual(list(got), ["settings", "defaults", "sources", "config_file"])
        self.assertEqual(got["config_file"], w.cfg)
        self.assertEqual((got["settings"]["agent.budget_usd"], got["sources"]["agent.budget_usd"]), (2, "file"))
        before = read_json(w.cfg)
        # one bad value -> nothing written, even the good one next to it
        self.assertEqual(err(f.set_settings, {"language": "en-US", "agent.budget_usd": -1}),
                         ("invalid", M.SET_BUDGET.format(value=-1)))
        self.assertEqual(read_json(w.cfg), before)
        res = f.set_settings({"language": "en-US", "agent.budget_usd": 3})
        self.assertEqual(list(res), ["settings", "applied", "pending_restart", "checks"])
        self.assertEqual(res["pending_restart"], [])
        self.assertEqual(res["applied"], ["language", "agent.budget_usd"])
        self.assertEqual(res["checks"], {"comfyui": {"available": False, "reason": "假的 ComfyUI"},
                                         "agent_sdk": {"available": False, "reason": "假的 SDK"},
                                         "photo_library": {"available": True, "reason": None},
                                         "preset_library_writes": {"available": True, "reason": None}})
        self.assertEqual(read_json(w.cfg), {"keep_me": True, "language": "en-US", "agent": {"budget_usd": 3}})
        self.assertEqual([n for n in os.listdir(w.root) if ".tmp-" in n], [])     # the replace left no tmp
        self.assertEqual(f.set_settings({"language": None})["settings"]["language"], "zh-TW")   # null resets
        self.assertNotIn("language", read_json(w.cfg))

    def test_broken_file_is_never_overwritten(self):
        w = World(self)
        with open(w.cfg, "wb") as fh:
            fh.write(b"{nope")
        f = w.facade()
        kind, msg = err(f.set_settings, {"language": "en-US"})
        self.assertEqual(kind, "unavailable")
        self.assertTrue(msg.startswith("config.json 不是正確的 JSON（第 1 行第 2 欄）"), msg)
        with open(w.cfg, "rb") as fh:
            self.assertEqual(fh.read(), b"{nope")

    def test_export_and_import(self):
        w = World(self, {"language": "en-US", "anthropic_api_key_ref": "op://v/i/f"})
        f = w.facade()
        doc = f.export_settings()
        self.assertEqual(doc["settings"], {"language": "en-US", "agent.api_key_ref": "op://v/i/f"})
        dest = os.path.join(w.root, "out.json")
        self.assertEqual(f.export_settings(dest)["output"], dest)
        self.assertEqual(read_json(dest), doc)
        self.assertEqual(err(f.export_settings, dest), ("conflict", M.SET_EXPORT_EXISTS.format(path=dest)))
        missing = os.path.join(w.root, "no", "x.json")
        self.assertEqual(err(f.export_settings, missing), ("invalid", M.SET_EXPORT_DEST.format(path=missing)))
        # import on another world: the document's keys only, through the same checks
        w2 = World(self, {"keep": 1})
        g = w2.facade()
        self.assertEqual(g.import_settings(path=dest)["applied"], ["language", "agent.api_key_ref"])
        self.assertEqual(read_json(w2.cfg), {"keep": 1, "language": "en-US", "agent": {"api_key_ref": "op://v/i/f"}})
        self.assertEqual(err(g.import_settings), ("invalid", M.SET_IMPORT_SOURCE))
        self.assertEqual(err(g.import_settings, doc, dest), ("invalid", M.SET_IMPORT_SOURCE))
        nowhere = os.path.join(w2.root, "nowhere.json")
        self.assertEqual(err(g.import_settings, None, nowhere), ("not_found", M.SET_IMPORT_NOT_FOUND.format(path=nowhere)))
        self.assertEqual(err(g.import_settings, "{x")[0], "invalid")
        bad = dict(doc, settings={"language": "en-US", "colour": 1})
        before = read_json(w2.cfg)
        self.assertEqual(err(g.import_settings, bad)[0], "invalid")
        self.assertEqual(read_json(w2.cfg), before)                 # unknown key: the whole document is refused
        self.assertEqual(g.import_settings(json.dumps(doc))["applied"], ["language", "agent.api_key_ref"])

    def test_version(self):
        from darkroom_app import __version__
        v = World(self).facade().version()
        self.assertEqual(list(v), ["version", "python", "torch", "cuda", "platform"])
        self.assertEqual(v["version"], __version__)

    def test_unconfigured_settings_still_work(self):  # a first-time setup: no preset folder anywhere
        from darkroom_app import config
        from darkroom_app.composition import build_facade
        tmp = _util.tmpdir(self)
        cfg = os.path.join(tmp, "config.json")
        pd = os.path.join(tmp, "presets")
        os.makedirs(pd)
        with mock.patch.object(config, "preset_dir", side_effect=config.ConfigError("no preset folder")):
            with self.assertRaises(config.ConfigError):
                build_facade(settings_path=lambda: cfg)
            f = build_facade(settings_path=lambda: cfg, allow_unconfigured=True)
            self.assertEqual(err(f.set_settings, {"language": "en-US"}), ("unavailable", M.SET_NEED_PRESET_DIR))
            self.assertEqual(f.set_settings({"preset_dir": pd})["applied"], ["preset_dir"])
            with self.assertRaises(config.ConfigError):
                f.slider_table()                                    # every other operation: the configuration error
        self.assertEqual(read_json(cfg), {"preset_dir": pd})


class TestRuntime(unittest.TestCase):
    def test_settings_change_rebuilds_and_keeps_the_engine(self):
        from darkroom_app.composition import Runtime
        w = World(self, {"data_dir": None})
        data2 = os.path.join(w.root, "data2")
        os.makedirs(data2)
        sentinel = object()
        rt = Runtime(w.pd, engine=sentinel, detect=dict(NO_NET), settings_path=lambda: w.cfg)
        first = rt.facade
        with mock.patch("darkroom_app.config.data_dir", side_effect=lambda: read_json(w.cfg).get("data_dir")
                        or w.data):
            self.assertEqual(first._photo_library.data_dir, os.path.abspath(w.data))
            res = rt.facade.set_settings({"data_dir": data2})
            self.assertEqual(res["applied"], ["data_dir"])
            self.assertIsNot(rt.facade, first)                       # the next call gets the new facade
            self.assertEqual(rt.facade._photo_library.data_dir, os.path.abspath(data2))
            self.assertEqual(first._photo_library.data_dir, os.path.abspath(w.data))   # running calls keep theirs
        self.assertIs(rt.facade._photos.engine_ref.peek(), sentinel)   # open photos stay open
        self.assertIs(rt.facade._presets.library, first._presets.library)   # no library key changed: view kept
        rt.facade.set_settings({"preset_dir": w.pd})
        self.assertIs(rt.facade._presets.library, first._presets.library)   # --preset-dir given: it stays in force

    def test_capability_cache_is_fresh_after_a_change(self):
        from darkroom_app.composition import Runtime
        w = World(self)
        calls = []
        detect = dict(NO_NET, gpu=lambda: calls.append(1) or (True, None))
        rt = Runtime(w.pd, engine=object(), data_dir=w.data, detect=detect, settings_path=lambda: w.cfg)
        rt.facade.capabilities()
        rt.facade.capabilities()
        self.assertEqual(len(calls), 1)
        rt.facade.set_settings({"language": "en-US"})
        rt.facade.capabilities()
        self.assertEqual(len(calls), 2)                              # the rebuilt app measures again


FAKE_KEY = "sk-ant-api03-FAKEFAKEFAKEFAKE"   # shaped like an Anthropic key; never a real one


class TestReviewFixes(unittest.TestCase):
    """Acceptance findings on the v2 settings: the whole must still add up before the file is written, a key-shaped
    value is refused (and never echoed) for every key, folders pinned by the command line are reported as in use,
    another process's change is picked up, and a hand-edited file shows and uses the same values."""

    def test_settings_that_leave_no_usable_preset_folder_are_refused_before_writing(self):
        w = World(self, {})
        root_b = os.path.join(w.root, "rootB")                       # exists, but holds no artifact/11_preset/xmp
        os.makedirs(root_b)
        write_json(w.cfg, {"preset_dir": w.pd})
        f = w.facade()
        before = read_json(w.cfg)
        want = os.path.join(root_b, "artifact", "11_preset", "xmp")
        with mock.patch.dict(os.environ, {"LOCALLLMS_ROOT": ""}):
            self.assertEqual(err(f.set_settings, {"preset_dir": None, "localllms_root": root_b}),
                             ("invalid", M.SET_PRESET_DIR_AFTER_MISSING.format(value=want)))
            self.assertEqual(err(f.set_settings, {"preset_dir": None}), ("invalid", M.SET_NO_PRESET_DIR_AFTER))
            self.assertEqual(read_json(w.cfg), before)
            f.set_settings({"localllms_root": root_b})                # preset_dir is still written: fine
        self.assertEqual(read_json(w.cfg)["localllms_root"], root_b)

    def test_a_rebuild_that_fails_puts_the_old_file_back(self):
        from darkroom_app.composition import build_facade
        w = World(self, {"language": "zh-TW"})

        def boom(keys):
            raise FileNotFoundError("preset folder not found: X")
        f = build_facade(w.pd, data_dir=w.data, detect=dict(NO_NET), settings_path=lambda: w.cfg, on_applied=boom)
        self.assertEqual(err(f.set_settings, {"language": "en-US"}),
                         ("unavailable", M.SET_APPLY_FAILED.format(reason="preset folder not found: X")))
        self.assertEqual(read_json(w.cfg), {"language": "zh-TW"})

    def test_runtime_put_of_an_unusable_root_is_refused_and_the_file_is_kept(self):
        from darkroom_app.composition import Runtime
        w = World(self)
        root_b = os.path.join(w.root, "rootB")
        os.makedirs(root_b)
        write_json(w.cfg, {"preset_dir": w.pd, "data_dir": w.data})
        with mock.patch.dict(os.environ, {"DARKROOM_CONFIG": w.cfg, "LOCALLLMS_ROOT": ""}):
            rt = Runtime(engine=object(), detect=dict(NO_NET), settings_path=lambda: w.cfg)
            kind, _ = err(rt.facade.set_settings, {"preset_dir": None, "localllms_root": root_b})
            self.assertEqual(kind, "invalid")
            self.assertEqual(read_json(w.cfg), {"preset_dir": w.pd, "data_dir": w.data})

    def test_key_shaped_values_are_refused_for_every_key_and_never_echoed(self):
        w = World(self, {"language": "zh-TW"})
        f = w.facade()
        for key in S.KEYS:
            for value in (FAKE_KEY, "http://127.0.0.1:1/" + FAKE_KEY, [FAKE_KEY]):
                kind, msg = err(f.set_settings, {key: value})
                self.assertEqual((kind, msg), ("invalid", M.SET_SECRET), (key, value))
        self.assertEqual(err(f.set_settings, {FAKE_KEY: 1}), ("invalid", M.SET_SECRET))     # a key name too
        self.assertEqual(err(f.set_settings, FAKE_KEY), ("invalid", M.SET_SECRET))          # not even an object
        doc = {"format": S.FORMAT, "version": "0", "settings": {"agent.model": FAKE_KEY}}
        self.assertEqual(err(f.import_settings, doc), ("invalid", M.SET_SECRET))
        self.assertEqual(read_json(w.cfg), {"language": "zh-TW"})

    def test_key_shaped_values_through_the_cli_and_mcp(self):
        w = World(self, {})
        rc, out, err_ = TestCli.run_cli(None, ["--preset-dir", w.pd, "--data-dir", w.data, "settings", "set",
                                               "agent.model=" + FAKE_KEY, "--json"], {"DARKROOM_CONFIG": w.cfg})
        self.assertEqual((rc, json.loads(out)["error"]["message"]), (2, M.SET_SECRET))
        self.assertNotIn("sk-ant", out + err_)
        res = TestMcp.call(None, w.facade(), ("darkroom_settings_set", {"values": {"comfyui_url": FAKE_KEY}}))
        self.assertTrue(res[0]["result"]["isError"])
        self.assertNotIn("sk-ant", json.dumps(res))
        self.assertEqual(read_json(w.cfg), {})

    def test_folders_pinned_on_the_command_line_are_what_settings_report(self):
        w = World(self, {})
        data_b = os.path.join(w.root, "dataB")
        os.makedirs(data_b)
        f = w.facade()                                                # --preset-dir and --data-dir given
        got = f.get_settings()
        self.assertEqual((got["settings"]["data_dir"], got["sources"]["data_dir"]), (os.path.abspath(w.data), "cli"))
        self.assertEqual((got["settings"]["preset_dir"], got["sources"]["preset_dir"]), (w.pd, "cli"))
        res = f.set_settings({"data_dir": data_b, "language": "en-US"})
        self.assertEqual((res["applied"], res["pending_restart"]), (["language"], ["data_dir"]))
        self.assertEqual(res["settings"]["data_dir"], os.path.abspath(w.data))      # still the one in use
        self.assertEqual(read_json(w.cfg)["data_dir"], data_b)                       # used from the next start

    def test_a_change_by_another_process_is_picked_up(self):
        from darkroom_app.composition import Runtime
        w = World(self, {})
        data_c = os.path.join(w.root, "dataC")
        os.makedirs(data_c)
        write_json(w.cfg, {"data_dir": w.data})
        with mock.patch("darkroom_app.config.data_dir", side_effect=lambda: read_json(w.cfg).get("data_dir")):
            rt = Runtime(w.pd, engine=object(), detect=dict(NO_NET), settings_path=lambda: w.cfg)
            first = rt.current()
            self.assertIs(rt.current(), first)                       # nothing changed: no rebuild
            self.assertEqual(first._photo_library.data_dir, os.path.abspath(w.data))
            write_json(w.cfg, {"data_dir": data_c, "language": "en-US"})   # the CLI / MCP in another process
            st = os.stat(w.cfg)
            os.utime(w.cfg, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
            self.assertTrue(rt.stale())
            now = rt.current()
            self.assertIsNot(now, first)
            self.assertEqual(now._photo_library.data_dir, os.path.abspath(data_c))
            self.assertIs(now._presets.library, first._presets.library)   # no library key changed
            self.assertIs(rt.current(), now)
            with open(w.cfg, "wb") as fh:                            # a broken file: keep running as before
                fh.write(b"{nope")
            self.assertIs(rt.current(), now)

    def test_a_hand_edited_file_shows_and_uses_the_same_values(self):
        from darkroom_app import config
        from darkroom_app.services.capabilities import detect_comfyui
        w = World(self, {"agent": {"budget_usd": -3}, "comfyui_url": "http://example.com:1"})
        got = w.facade().get_settings()
        self.assertEqual((got["settings"]["agent.budget_usd"], got["sources"]["agent.budget_usd"]), (5.0, "default"))
        self.assertEqual((got["settings"]["comfyui_url"], got["sources"]["comfyui_url"]),
                         (S.DEFAULT_COMFYUI_URL, "default"))
        self.assertEqual(config.semantic_index_budget_usd(w.cfg), 5.0)
        self.assertEqual(config.comfyui_url(w.cfg), S.DEFAULT_COMFYUI_URL)
        self.assertEqual(detect_comfyui("http://example.com:1"),
                         (False, M.CAP_COMFYUI_NOT_LOCAL.format(url="http://example.com:1")))


class _NoEngine:
    images = {}

    def shutdown(self):
        pass


class TestHttp(AioHTTPTestCase):
    async def get_client(self, server):
        return TestClient(server, headers=_util.HTTP_HEADERS)

    async def get_application(self):
        from darkroom_app.server import make_app
        self.w = World(self, {"language": "zh-TW"})
        return make_app(self.w.pd, engine=_NoEngine(), data_dir=self.w.data, detect=dict(NO_NET),
                        settings_path=lambda: self.w.cfg)

    async def test_routes(self):
        r = await self.client.get("/api/settings")
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["settings"]["language"], "zh-TW")
        r = await self.client.put("/api/settings", json={"values": {"language": "xx"}})
        self.assertEqual((r.status, await r.json()), (400, {"error": M.SET_LANGUAGE.format(value="xx")}))
        r = await self.client.put("/api/settings", json={"values": {"language": "en-US"}})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["applied"], ["language"])
        r = await self.client.get("/api/settings/export")
        self.assertEqual(await r.json(), {"format": "darkroom-settings/1", "version": (await (
            await self.client.get("/api/version")).json())["version"], "settings": {"language": "en-US"}})
        r = await self.client.get("/api/settings/export", params={"dest": "C:\\x.json"})
        self.assertEqual((r.status, await r.json()),
                         (400, {"error": "dest is not accepted over HTTP (the page downloads the document)"}))
        r = await self.client.post("/api/settings/import", json={"path": self.w.cfg})
        self.assertEqual((r.status, await r.json()),
                         (400, {"error": "path is not accepted over HTTP (send the document)"}))
        r = await self.client.post("/api/settings/import", json={"document": {
            "format": "darkroom-settings/1", "version": "0", "settings": {"language": "zh-TW"}}})
        self.assertEqual(r.status, 200)
        self.assertEqual(read_json(self.w.cfg), {"language": "zh-TW"})

    async def test_local_only_and_new_facade_after_put(self):
        from darkroom_app.server import FACADE, RUNTIME
        r = await self.client.get("/api/settings", headers={"X-Darkroom": "0"})
        self.assertEqual((r.status, await r.json()), (403, {"error": "request refused: X-Darkroom header required"}))
        r = await self.client.put("/api/settings", data=b'{"values": {}}', headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status, 415)
        first = self.app[FACADE]
        r = await self.client.put("/api/settings", json={"values": {"agent.model": "claude-sonnet-5"}})
        self.assertEqual(r.status, 200)
        self.assertIsNot(self.app[RUNTIME].facade, first)          # the server now uses the rebuilt facade
        r = await self.client.get("/api/version", headers={"X-Darkroom": "0"})
        self.assertEqual(r.status, 200)                             # names no local path: no header needed

    async def test_page_is_the_web_build_or_a_503_that_says_how_to_build_it(self):  # plan-v2 §2 (integration)
        from darkroom_app.adapters.http import server
        empty = os.path.join(self.w.root, "no-dist")
        os.makedirs(empty)
        with mock.patch.dict(os.environ, {server.ENV_WEB_DIST: empty}):
            for path in ("/", "/settings"):
                r = await self.client.get(path)
                self.assertEqual((r.status, r.headers.get("Cache-Control")), (503, "no-store"), path)
                self.assertEqual(r.content_type, "text/html")
                self.assertIn("cd web\nnpm ci\nnpm run build", await r.text())
            self.assertEqual((await self.client.get("/assets/x.js")).status, 404)
            self.assertEqual((await self.client.get("/logo.svg")).status, 404)
            self.assertEqual((await self.client.get("/api/health")).status, 200)    # the API works without a page
        dist = os.path.join(self.w.root, "dist")
        os.makedirs(os.path.join(dist, "assets"))
        for rel, text in (("index.html", "<!doctype html><div id=root>react</div>"), ("assets/app.js", "js"),
                          ("logo.svg", "<svg/>")):
            with open(os.path.join(dist, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        with mock.patch.dict(os.environ, {server.ENV_WEB_DIST: dist}):
            self.assertIn("react", await (await self.client.get("/")).text())
            self.assertIn("react", await (await self.client.get("/settings")).text())   # the page's own route
            self.assertEqual(await (await self.client.get("/assets/app.js")).text(), "js")
            self.assertEqual(await (await self.client.get("/logo.svg")).text(), "<svg/>")
            self.assertEqual((await self.client.get("/assets/..%5cindex.html")).status, 404)   # no way out of assets/
            self.assertEqual((await self.client.get("/api/nope")).status, 404)       # never the page for /api
            self.assertEqual((await self.client.get("/static/app.js")).status, 404)  # the v1 page is gone

    def test_build_is_looked_for_in_the_wheel_then_the_checkout(self):  # plan-v2 §4: the wheel carries web_dist
        from darkroom_app.adapters.http import server
        self.assertEqual(server.PACKAGED_WEB_DIST, os.path.join(_util.REPO, "darkroom_app", "web_dist"))
        self.assertEqual(server.WEB_DIST, os.path.join(_util.REPO, "web", "dist"))
        packaged, checkout = (os.path.join(self.w.root, n) for n in ("packaged", "checkout"))
        for d in (packaged, checkout):
            os.makedirs(d)
        env = {k: v for k, v in os.environ.items() if k != server.ENV_WEB_DIST}
        with mock.patch.dict(os.environ, env, clear=True),                 mock.patch.object(server, "PACKAGED_WEB_DIST", packaged), mock.patch.object(server, "WEB_DIST", checkout):
            self.assertIsNone(server._dist())
            with open(os.path.join(checkout, "index.html"), "w", encoding="utf-8") as fh:
                fh.write("checkout")
            self.assertEqual(server._dist(), checkout)
            with open(os.path.join(packaged, "index.html"), "w", encoding="utf-8") as fh:
                fh.write("packaged")
            self.assertEqual(server._dist(), packaged)


class TestCli(unittest.TestCase):
    def run_cli(self, argv, env):
        from darkroom_app import cli
        out, err_ = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err_):
            try:
                rc = cli.main(argv)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err_.getvalue()

    def test_settings_commands(self):
        w = World(self, {})
        env = {"DARKROOM_CONFIG": w.cfg}
        base = ["--preset-dir", w.pd, "--data-dir", w.data]
        rc, out, _ = self.run_cli(base + ["settings", "set", "language=en-US", "agent.budget_usd=4",
                                          "comfyui_root=null", "--json"], env)
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(out)["result"]["applied"], ["language", "agent.budget_usd", "comfyui_root"])
        self.assertEqual(read_json(w.cfg), {"language": "en-US", "agent": {"budget_usd": 4}})
        rc, out, _ = self.run_cli(base + ["settings", "get", "--json"], env)
        self.assertEqual(json.loads(out)["result"]["settings"]["agent.budget_usd"], 4)
        dest = os.path.join(w.root, "s.json")
        rc, out, _ = self.run_cli(base + ["settings", "export", "--out", dest, "--json"], env)
        self.assertEqual((rc, json.loads(out)["result"]["output"]), (0, dest))
        rc, out, err_ = self.run_cli(base + ["settings", "export", "--out", dest, "--json"], env)
        self.assertEqual((rc, json.loads(out)["error"]["kind"]), (4, "conflict"))
        rc, out, _ = self.run_cli(base + ["settings", "import", dest, "--json"], env)
        self.assertEqual(rc, 0)
        rc, out, err_ = self.run_cli(base + ["settings", "set", "language=xx"], env)
        self.assertEqual((rc, out, err_), (2, "", M.SET_LANGUAGE.format(value="xx") + "\n"))
        rc, out, err_ = self.run_cli(base + ["settings", "set", "novalue", "--json"], env)
        self.assertEqual((rc, out), (2, ""))                       # usage error: one line, exit 2

    def test_version_flag_and_unconfigured(self):
        from darkroom_app import __version__, config
        tmp = _util.tmpdir(self)
        cfg = os.path.join(tmp, "config.json")
        rc, out, _ = self.run_cli(["--version"], {})
        self.assertEqual((rc, out), (0, f"darkroom {__version__}\n"))
        with mock.patch.object(config, "preset_dir", side_effect=config.ConfigError("no preset folder")):
            rc, out, _ = self.run_cli(["settings", "get", "--json"], {"DARKROOM_CONFIG": cfg})
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out)["result"]["config_file"], cfg)
            rc, out, _ = self.run_cli(["version", "--json"], {"DARKROOM_CONFIG": cfg})
            self.assertEqual(json.loads(out)["result"]["version"], __version__)
            rc, out, err_ = self.run_cli(["sliders", "--json"], {"DARKROOM_CONFIG": cfg})
            self.assertEqual((rc, out, err_), (2, "", "darkroom：no preset folder\n"))   # as before v2


class TestMcp(unittest.TestCase):
    def call(self, provider, *calls):
        from darkroom_app.mcp_server import serve
        msgs = b"".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                    "params": {"name": n, "arguments": a}}).encode() + b"\n"
                        for i, (n, a) in enumerate(calls, 1))
        out = io.BytesIO()
        serve(io.BytesIO(msgs), out, facade=provider)
        return [json.loads(x) for x in out.getvalue().decode("utf-8").splitlines()]

    def test_tools(self):
        w = World(self, {})
        f = w.facade()
        res = self.call(f, ("darkroom_settings_set", {"values": {"language": "en-US"}}),
                        ("darkroom_settings_get", {}), ("darkroom_settings_set", {"values": {"x": 1}}),
                        ("darkroom_settings_export", {"dest": os.path.join(w.root, "e.json")}),
                        ("darkroom_version", {}), ("darkroom_settings_get", {"bogus": 1}))
        self.assertEqual(res[0]["result"]["structuredContent"]["applied"], ["language"])
        self.assertEqual(res[1]["result"]["structuredContent"]["settings"]["language"], "en-US")
        self.assertTrue(res[2]["result"]["isError"])
        self.assertEqual(res[3]["result"]["structuredContent"]["output"], os.path.join(w.root, "e.json"))
        self.assertEqual(list(res[4]["result"]["structuredContent"]), ["version", "python", "torch", "cuda", "platform"])
        self.assertEqual(res[5]["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
