"""CONTRACT-preset-library K1-K15, K18, KP1-KP11: the preset library index and its organising operations.

Every write test runs on a synthetic library inside a write-guard fixture root (`<tmp>/xmp` purchased presets,
the library root `<tmp>`); the user's real library is only read (K2, K3).
"""
import base64
import contextlib
import hashlib
import io
import json
import msvcrt
import os
import re
import subprocess
import threading
import time
import unittest
from unittest import mock

from aiohttp.test_utils import AioHTTPTestCase

import _util
import _xmpgen
from darkroom import load_preset
from darkroom_app import preview as semantics
from darkroom_app.errors import DarkroomError

NUM = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")      # P3 (verbatim)
SCHEMA = "darkroom-preset-library/1"                       # verbatim (K4)
USER_GROUP = "自存 preset"                                  # verbatim (K12)
XMP_HEAD = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Normal" '
            'crs:ProcessVersion="15.4" crs:HasSettings="True"')    # verbatim (K13)


def lib_presets(d):
    """The synthetic purchased presets: curves, a linear and a radial mask, a hue key, absolute white balance."""
    _xmpgen.write(d, "p-curve.xmp", _xmpgen.xmp_text(
        {"Exposure2012": "+1.00", "Contrast2012": "+40", "SplitToningShadowHue": "200",
         "SplitToningShadowSaturation": "+30", "Temperature": "5500", "Tint": "+10", "ConvertToGrayscale": "True"},
        name="曲線", group="電影 - 暖調",
        curves={"ToneCurvePV2012": [(0, 20), (128, 140), (255, 240)], "ToneCurvePV2012Red": [(0, 0), (255, 230)]}))
    _xmpgen.write(d, "p-linear.xmp", _xmpgen.xmp_text(
        {"Exposure2012": "-0.50", "Highlights2012": "-80"}, name="線性", group="電影 - 冷調",
        extra=_xmpgen.linear_mask((0.1, 0.2), (0.5, 0.75), {"LocalExposure2012": "0.5", "LocalContrast2012": "-20"})))
    _xmpgen.write(d, "p-radial.xmp", _xmpgen.xmp_text(
        {"Vibrance": "+25"}, name="放射", group="人像",
        extra=_xmpgen.radial_mask(0.1, 0.2, 0.8, 0.9, {"LocalToningHue": "120", "LocalSaturation": "40"},
                                  feather=37, angle=12.5, inverted=True)))
    _xmpgen.write(d, "p-plain.xmp", _xmpgen.xmp_text({"Contrast2012": "+20"}, name="平"))
    _xmpgen.write(d, "p-old.xmp", _xmpgen.xmp_text({"ProcessVersion": "5.7", "Exposure": "+0.50"}, name="舊版"))
    return d


def tree_snapshot(d):
    out = {}
    for root, dirs, files in os.walk(d):
        for x in dirs:
            out[os.path.relpath(os.path.join(root, x), d)] = "dir"
        for f in files:
            p = os.path.join(root, f)
            st = os.stat(p)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, d)] = (st.st_mtime_ns, hashlib.sha256(fh.read()).hexdigest())
    return out


def read_index_like_the_app(path, failures):
    """One read as darkroom does it (KP12): PermissionError while a replace is in flight is retried (10 x 0.1 s);
    a missing file is fine; anything else - or a partial / undecodable file - is a failure."""
    for attempt in range(10):
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            return 0
        except PermissionError:
            time.sleep(0.1 if attempt else 0.001)
            continue
        try:
            json.loads(raw)
        except Exception as e:                      # noqa: BLE001 - a partial file is the finding
            failures.append(repr(e))
        return 1
    failures.append("PermissionError 10 times")
    return 0


def read_json(p):
    with open(p, "rb") as f:
        return json.loads(f.read())


class LibCase(unittest.TestCase):
    def setUp(self):
        self.root = _util.tmpdir(self)
        self.pd = os.path.join(self.root, "xmp")
        os.makedirs(self.pd)
        lib_presets(self.pd)
        self.f = self.facade()

    def facade(self):
        from darkroom_app.composition import build_facade
        return build_facade(self.pd)

    @property
    def index_path(self):
        return os.path.join(self.root, "library.json")

    def err(self, fn, *a, **k):
        with self.assertRaises(DarkroomError) as cm:
            fn(*a, **k)
        return cm.exception.kind, cm.exception.message

    def src(self, name="src"):
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        return d


class TestLocationAndReadOnly(LibCase):
    def test_library_root_is_parent_of_preset_dir(self):  # K1 / KP2
        lib = self.f._library.library
        self.assertEqual(os.path.normcase(lib.root), os.path.normcase(self.root))
        self.assertEqual(lib.index_path, os.path.join(self.root, "library.json"))

    def test_config_library_dir_only_with_configured_preset_dir(self):  # KP2
        from darkroom_app import composition, config
        other = self.src("elsewhere")
        with mock.patch.object(config, "preset_library_dir", return_value=other), \
                mock.patch.object(config, "preset_dir", return_value=self.pd):
            self.assertEqual(composition.build_facade()._library.library.root, os.path.abspath(other))
            self.assertEqual(os.path.normcase(composition.build_facade(self.pd)._library.library.root),
                             os.path.normcase(self.root))

    def test_read_ops_never_write_index(self):  # K3
        before = tree_snapshot(self.root)
        self.f.list_presets()
        self.f.list_presets("曲", 0, 2, True)
        self.f.preset_detail("p-curve")
        self.f.preset_flags()
        self.f.preset_groups()
        self.assertEqual(tree_snapshot(self.root), before)
        self.assertFalse(os.path.exists(self.index_path))

    def test_read_ops_never_write_real_library(self):  # K3 against the user's library (read only)
        from darkroom_app.presets import Library
        from darkroom_app.services.preset_library import PresetLibraryService
        from darkroom_app.services.presets import PresetService
        real = _util.preset_dir()
        root = os.path.dirname(real)
        names = sorted(os.listdir(root))
        lib = Library(real)
        ps, pl = PresetService(lib), PresetLibraryService(lib, real)
        self.assertEqual(ps.list_presets()["total"], 1466)
        ps.list_presets(favorites=True)
        pl.preset_groups()
        ps.preset_flags()
        self.assertEqual(sorted(os.listdir(root)), names)

    def test_six_columns_and_favorites_view(self):  # K9
        r = self.f.list_presets()
        for row in r["items"]:
            self.assertEqual(list(row), ["id", "group", "name", "supported", "skipped", "favorite"])
        self.assertEqual(self.f.list_presets(favorites=True)["items"], [])
        self.f.set_favorite("p-plain", True)
        self.assertEqual([x["id"] for x in self.f.list_presets(favorites=True)["items"]], ["p-plain"])
        self.assertEqual(self.err(self.f.list_presets, favorites=1), ("invalid", "favorite 必須是 true 或 false"))


class TestIndex(LibCase):
    def test_index_format(self):  # K4
        self.f.set_favorite("p-curve", True)
        with open(self.index_path, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        idx = json.loads(raw.decode("utf-8"))
        self.assertEqual(list(idx), ["schema", "groups", "presets"])
        self.assertEqual(idx["schema"], SCHEMA)
        self.assertEqual(sorted(idx["presets"]), ["p-curve", "p-linear", "p-old", "p-plain", "p-radial"])
        e = idx["presets"]["p-curve"]
        self.assertEqual(list(e), ["file", "sha256", "name", "group", "favorite"])
        self.assertEqual(e["file"], "xmp/p-curve.xmp")
        with open(os.path.join(self.pd, "p-curve.xmp"), "rb") as f:
            self.assertEqual(e["sha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertEqual((e["name"], e["group"], e["favorite"]), ("曲線", "電影 - 暖調", True))
        self.assertEqual(idx["presets"]["p-old"]["name"], "p-old")      # unsupported: name = id (as before)

    def test_bom_accepted(self):  # K4
        self.f.rename_preset("p-plain", "有 BOM")
        with open(self.index_path, "rb") as f:
            raw = f.read()
        os.remove(self.index_path)
        with open(self.index_path, "wb") as f:
            f.write(b"\xef\xbb\xbf" + raw)
        self.assertEqual(self.facade().preset_detail("p-plain")["name"], "有 BOM")

    def test_rebuild(self):  # K5
        self.assertEqual(self.f.rebuild_library(), {"added": 5, "removed": 0, "kept": 0})
        self.f.rename_preset("p-plain", "改過")
        self.f.move_preset("p-plain", "新群組")
        self.f.set_favorite("p-plain", True)
        self.f.create_group("空 - 子")
        os.remove(os.path.join(self.pd, "p-old.xmp"))
        _xmpgen.write(self.pd, "p-new.xmp", _xmpgen.xmp_text({"Contrast2012": "+1"}, name="新的", group="新 - 群"))
        with open(os.path.join(self.pd, "p-linear.xmp"), "a", encoding="utf-8") as f:
            f.write("\n")                                                  # content changed: sha256 updated
        self.assertEqual(self.f.rebuild_library(), {"added": 1, "removed": 1, "kept": 4})
        idx = read_json(self.index_path)
        self.assertEqual(idx["presets"]["p-plain"], {"file": "xmp/p-plain.xmp", "sha256": idx["presets"]["p-plain"]["sha256"],
                                                     "name": "改過", "group": "新群組", "favorite": True})
        self.assertEqual((idx["presets"]["p-new"]["name"], idx["presets"]["p-new"]["group"]), ("新的", "新 - 群"))
        with open(os.path.join(self.pd, "p-linear.xmp"), "rb") as f:
            self.assertEqual(idx["presets"]["p-linear"]["sha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertNotIn("p-old", idx["presets"])
        self.assertEqual(idx["groups"], ["空 - 子"])
        os.remove(self.index_path)                                          # deleted index -> same as a new library
        fresh = self.facade()._library.library.index
        self.f.rebuild_library()
        self.assertEqual(read_json(self.index_path), fresh)

    def test_bad_index_kept(self):  # K5 / KP1
        bad = b'{"schema": "something else", "presets": {}}'
        for content in (bad, b"\x00not json"):
            with open(self.index_path, "wb") as f:
                f.write(content)
            t0 = int(time.time())
            r = self.facade().rebuild_library()
            self.assertEqual(r["added"], 5)
            kept = [n for n in os.listdir(self.root) if n.startswith("library.json.bad-")]
            self.assertTrue(kept)
            newest = max(kept, key=lambda n: os.stat(os.path.join(self.root, n)).st_mtime_ns)
            self.assertRegex(newest, r"^library\.json\.bad-\d+(-\d+)?$")
            self.assertGreaterEqual(int(newest.split("-")[1]), t0)
            with open(os.path.join(self.root, newest), "rb") as f:
                self.assertEqual(f.read(), content)
            self.assertEqual(read_json(self.index_path)["schema"], SCHEMA)
        self.assertEqual(len([n for n in os.listdir(self.root) if n.startswith("library.json.bad-")]), 2)

    def test_external_change_seen(self):  # K15 / KP8: another process's change shows on the next list
        other = self.facade()
        self.f.list_presets()
        other.set_favorite("p-radial", True)
        self.assertTrue(self.f.preset_detail("p-radial") and
                        [x for x in self.f.list_presets(favorites=True)["items"]][0]["id"] == "p-radial")
        r = other.save_user_preset("外面存的", preset_id="p-plain")
        self.assertIn(r["id"], [x["id"] for x in self.f.list_presets()["items"]])
        self.assertIn(r["id"], self.f._library.library.params)


class TestOrganise(LibCase):
    def test_rename(self):  # K6
        row = self.f.rename_preset("p-curve", "  新名  ")
        self.assertEqual((row["name"], row["group"], row["id"]), ("新名", "電影 - 暖調", "p-curve"))
        self.assertEqual(self.f.rename_preset("p-plain", "新名")["name"], "新名")     # same name allowed
        self.assertEqual(self.f.rename_preset("p-plain", "a" * 100)["name"], "a" * 100)
        for bad in ("", "   ", "a" * 101, 3, None, "\x01\x02"):
            self.assertEqual(self.err(self.f.rename_preset, "p-plain", bad), ("invalid", "preset 名稱要 1～100 個字"))
        self.assertEqual(self.f.rename_preset("p-plain", "x\x07y")["name"], "xy")     # KP6
        self.assertEqual(self.err(self.f.rename_preset, "nope", "x"), ("not_found", "unknown preset nope"))
        self.assertEqual(self.err(self.f.rename_preset, "nope", ""), ("not_found", "unknown preset nope"))  # id first
        self.assertEqual(self.f._library.library.get("p-curve").to_dict(),
                         load_preset(os.path.join(self.pd, "p-curve.xmp")).to_dict())   # Params unchanged

    def test_move(self):  # K7
        self.assertEqual(self.f.move_preset("p-plain", "  A  -  B ")["group"], "A - B")
        self.assertEqual(self.f.move_preset("p-plain", "C")["group"], "C")
        for bad in ("", " ", "A -  - B", "A - ", " - B", None, 1):
            self.assertEqual(self.err(self.f.move_preset, "p-plain", bad),
                             ("invalid", f"群組名稱不能是空的，也不能有空的層級：{bad}"))
        self.assertEqual(self.err(self.f.move_preset, "nope", "A"), ("not_found", "unknown preset nope"))
        tree = self.f.preset_groups()
        self.assertIn("C", [g["name"] for g in tree["groups"]])

    def test_groups(self):  # K8
        self.assertEqual(self.f.create_group("空的"), {"group": "空的"})
        for exists in ("空的", "電影", "電影 - 暖調", "人像", "電影 - 暖調".upper()):
            self.assertEqual(self.err(self.f.create_group, exists), ("conflict", f"群組已存在：{exists}"))
        self.assertEqual(self.err(self.f.create_group, "A -  - B")[0], "invalid")
        tree = self.f.preset_groups()
        self.assertIn({"name": "空的", "path": "空的", "count": 0, "children": []}, tree["groups"])
        self.assertEqual(self.err(self.f.rename_group, "沒有", "x"), ("not_found", "找不到群組：沒有"))
        self.assertEqual(self.err(self.f.rename_group, "電影", "人像"), ("conflict", "群組已存在：人像"))
        self.f.create_group("電影 - 舊 - 更深")
        self.assertEqual(self.f.rename_group("電影", "影片"), {"group": "影片", "presets": 2})
        rows = {r["id"]: r["group"] for r in self.f.list_presets()["items"]}
        self.assertEqual((rows["p-curve"], rows["p-linear"]), ("影片 - 暖調", "影片 - 冷調"))
        self.assertIn("影片 - 舊 - 更深", read_json(self.index_path)["groups"])
        self.assertEqual(self.f.rename_group("影片", "影片")["group"], "影片")
        self.assertEqual(self.f.rename_group("影片", "Films")["presets"], 2)
        self.assertEqual(self.f.rename_group("films", "FILMS")["group"], "FILMS")         # case only: not "exists"

    def test_favorite(self):  # K9
        for bad in (1, "true", None, 0):
            self.assertEqual(self.err(self.f.set_favorite, "p-plain", bad), ("invalid", "favorite 必須是 true 或 false"))
        self.assertIs(self.f.set_favorite("p-plain", True)["favorite"], True)
        st = os.stat(self.index_path)
        self.assertIs(self.f.set_favorite("p-plain", True)["favorite"], True)            # idempotent, no write
        self.assertEqual(os.stat(self.index_path).st_ino, st.st_ino)
        self.assertIs(self.f.set_favorite("p-plain", False)["favorite"], False)
        self.assertEqual(self.err(self.f.set_favorite, "nope", True), ("not_found", "unknown preset nope"))

    def test_group_tree(self):  # K10
        self.f.move_preset("p-plain", "電影")
        self.f.create_group("人像 - 空")
        self.assertEqual(self.f.preset_groups(), {"groups": [
            {"name": "人像", "path": "人像", "count": 1, "children": [{"name": "空", "path": "人像 - 空", "count": 0}]},
            {"name": "電影", "path": "電影", "count": 3, "children": [
                {"name": "冷調", "path": "電影 - 冷調", "count": 1}, {"name": "暖調", "path": "電影 - 暖調", "count": 1}]}],
            "ungrouped": 1})
        self.f.move_preset("p-plain", "電影 - 暖調 - 深")
        child = self.f.preset_groups()["groups"][1]["children"]
        self.assertIn({"name": "暖調 - 深", "path": "電影 - 暖調 - 深", "count": 1}, child)   # first " - " only (B9)

    def test_purchased_presets_never_written(self):  # K2 / K18
        before = tree_snapshot(self.pd)
        self.f.rename_preset("p-curve", "x")
        self.f.move_preset("p-curve", "y")
        self.f.set_favorite("p-curve", True)
        self.f.create_group("z")
        self.f.rename_group("z", "zz")
        self.f.save_user_preset("s", preset_id="p-curve")
        src = self.src()
        _xmpgen.write(src, "i.xmp", _xmpgen.xmp_text({"Contrast2012": "+3"}, name="匯入"))
        self.f.import_presets([src])
        self.f.rebuild_library()
        self.assertEqual(tree_snapshot(self.pd), before)
        self.assertEqual(sorted(os.listdir(self.root)), ["import", "library.json", "library.json.lock", "src", "user",
                                                          "xmp"])

    def test_no_write_into_preset_dir(self):  # K1 / KP1: the root inside the preset folder is refused by safe_write
        from darkroom_app.composition import build_facade
        from darkroom_app.safe_write import SafeWriteRefused
        before = tree_snapshot(self.pd)
        f = build_facade(self.pd, library_dir=self.pd)
        with self.assertRaises(SafeWriteRefused):
            f.set_favorite("p-plain", True)
        with self.assertRaises(SafeWriteRefused):
            f.save_user_preset("s", preset_id="p-plain")
        self.assertEqual(tree_snapshot(self.pd), before)

    def test_lock_wait_constant_and_conflict(self):  # K15 / KP8
        from darkroom_app.services import preset_library as pl
        self.assertEqual(pl.LOCK_WAIT_S, 5.0)
        self.assertEqual((pl.REPLACE_RETRIES, pl.REPLACE_RETRY_S), (10, 0.1))
        fd = os.open(os.path.join(self.root, "library.json.lock"), os.O_RDWR | os.O_CREAT | os.O_BINARY)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            with mock.patch.object(pl, "LOCK_WAIT_S", 0.3):
                t0 = time.monotonic()
                self.assertEqual(self.err(self.f.set_favorite, "p-plain", True),
                                 ("conflict", "preset 庫正被其他程式修改，請稍後再試"))
                self.assertGreaterEqual(time.monotonic() - t0, 0.3)
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)
        self.assertTrue(self.f.set_favorite("p-plain", True)["favorite"])
        self.assertEqual([n for n in os.listdir(self.root) if ".tmp-" in n], [])

    def test_replace_retry_then_unavailable(self):  # K15: PermissionError retried, then unavailable, no tmp left
        from darkroom_app import safe_write
        from darkroom_app.services import preset_library as pl
        self.f.set_favorite("p-plain", True)
        calls = []

        def busy(*a, **k):
            calls.append(1)
            raise PermissionError(5, "Access is denied")
        with mock.patch.object(safe_write, "replace_into", busy), mock.patch.object(pl, "REPLACE_RETRY_S", 0.001):
            kind, msg = self.err(self.f.set_favorite, "p-plain", False)
        self.assertEqual((kind, len(calls)), ("unavailable", 10))
        self.assertTrue(msg.startswith("無法寫入 preset 庫索引："), msg)
        self.assertEqual([n for n in os.listdir(self.root) if ".tmp-" in n], [])
        self.assertTrue(read_json(self.index_path)["presets"]["p-plain"]["favorite"])


class TestImport(LibCase):
    def test_import_batch(self):  # K11
        src = self.src()
        _xmpgen.write(src, "b.xmp", _xmpgen.xmp_text({"Contrast2012": "+5"}, name="乙", group="來源 - 群"))
        _xmpgen.write(src, "a.xmp", _xmpgen.xmp_text({"Contrast2012": "+6"}, name=""))
        with open(os.path.join(self.pd, "p-plain.xmp"), "rb") as f:
            dup = f.read()
        with open(os.path.join(src, "dup.xmp"), "wb") as f:
            f.write(dup)
        with open(os.path.join(src, "note.txt"), "w") as f:
            f.write("x")
        with open(os.path.join(src, "bad.xmp"), "w") as f:
            f.write("<x")
        missing = os.path.join(src, "missing.xmp")
        r = self.f.import_presets([src, os.path.join(src, "note.txt"), missing, os.path.join(src, "b.xmp")])
        self.assertEqual(r["results"][0]["source"], "a.xmp")
        self.assertEqual(r, {"results": [
            {"ok": True, "source": "a.xmp", "id": "import:a"},
            {"ok": True, "source": "b.xmp", "id": "import:b"},
            {"ok": False, "source": "bad.xmp", "error": r["results"][2]["error"]},
            {"ok": False, "source": "dup.xmp", "error": "已在 preset 庫裡（平），未重複匯入", "duplicate_of": "p-plain"},
            {"ok": False, "source": "note.txt", "error": "不是 .xmp 檔：note.txt"},
            {"ok": False, "source": "missing.xmp", "error": f"找不到檔案：{missing}"},
            {"ok": False, "source": "b.xmp", "error": "已在 preset 庫裡（乙），未重複匯入", "duplicate_of": "import:b"}]})
        self.assertTrue(r["results"][2]["error"].startswith("無法讀取 preset：bad.xmp："))
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "import"))), ["a.xmp", "b.xmp"])
        with open(os.path.join(self.root, "import", "b.xmp"), "rb") as f, open(os.path.join(src, "b.xmp"), "rb") as g:
            self.assertEqual(f.read(), g.read())                          # bytes copied as they are
        rows = {x["id"]: x for x in self.f.list_presets()["items"]}
        self.assertEqual((rows["import:a"]["name"], rows["import:b"]["name"], rows["import:b"]["group"]),
                         ("a", "乙", "來源 - 群"))
        self.assertEqual(self.f.preset_detail("import:b")["values"]["Contrast2012"], 5.0)
        for bad in ([], None, "x", [1]):
            self.assertEqual(self.err(self.f.import_presets, bad), ("invalid", "沒有要匯入的 xmp 檔"))
        self.assertEqual(self.err(self.f.import_presets, [self.src("empty")]), ("invalid", "沒有要匯入的 xmp 檔"))
        self.assertEqual(self.err(self.f.import_presets, None, None, [{"name": "a.xmp"}]),
                         ("invalid", "files 必須是 [{name, data_base64}] 陣列"))

    def test_import_group(self):  # K11 + K7
        src = self.src()
        _xmpgen.write(src, "g.xmp", _xmpgen.xmp_text({"Contrast2012": "+9"}, name="群", group="原本"))
        self.assertEqual(self.err(self.f.import_presets, [src], "A -  - B")[0], "invalid")
        self.assertFalse(os.path.exists(os.path.join(self.root, "import")))
        self.f.import_presets([src], " 新 - 群 ")
        self.assertEqual(self.f.list_presets("群")["items"][0]["group"], "新 - 群")

    def test_import_source_untouched(self):  # K11
        src = self.src()
        p = _xmpgen.write(src, "s.xmp", _xmpgen.xmp_text({"Contrast2012": "+8"}, name="來源"))
        before = tree_snapshot(src)
        self.f.import_presets([p])
        self.assertEqual(tree_snapshot(src), before)

    def test_import_name_collision(self):  # K11
        for i, (folder, name) in enumerate((("s1", "x.xmp"), ("s2", "x.xmp"), ("s3", "X.xmp"))):
            d = self.src(folder)
            _xmpgen.write(d, name, _xmpgen.xmp_text({"Contrast2012": str(i + 1)}, name=f"n{i}"))
            r = self.f.import_presets([d])
            self.assertTrue(r["results"][0]["ok"], r)
        self.assertEqual(sorted(n.casefold() for n in os.listdir(os.path.join(self.root, "import"))),
                         ["x (2).xmp", "x (3).xmp", "x.xmp"])          # names compared without case (K11)
        self.assertEqual(self.f.preset_detail("import:X (3)")["values"]["Contrast2012"], 3.0)
        with open(os.path.join(self.root, "import", "x.xmp"), encoding="utf-8") as f:
            self.assertIn('crs:Contrast2012="1"', f.read())               # the first one was never overwritten

    def test_upload_import(self):  # KP4: uploaded bytes, temp file removed, bad bytes leave nothing
        good = _xmpgen.xmp_text({"Contrast2012": "+11"}, name="上傳").encode()
        files = [{"name": "C:\\fake\\dir/up.xmp", "data_base64": base64.b64encode(good).decode()},
                 {"name": "bad.xmp", "data_base64": base64.b64encode(b"<x").decode()},
                 {"name": "nob64.xmp", "data_base64": "@@@"},
                 {"name": "evil.txt", "data_base64": base64.b64encode(good).decode()},
                 {"name": "..\\..\\CON.xmp", "data_base64": base64.b64encode(good + b" ").decode()}]
        r = self.f.import_presets(None, None, files)["results"]
        self.assertEqual([x["ok"] for x in r], [True, False, False, False, True])
        self.assertEqual(r[0], {"ok": True, "source": "up.xmp", "id": "import:up"})
        self.assertEqual(r[3]["error"], "不是 .xmp 檔：evil.txt")
        self.assertTrue(r[2]["error"].startswith("無法讀取 preset：nob64.xmp："))
        self.assertEqual(r[4]["id"], "import:_CON")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "import"))), ["_CON.xmp", "up.xmp"])

    def test_import_write_failure_is_an_item_error(self):  # KP9
        from darkroom_app import safe_write
        src = self.src()
        _xmpgen.write(src, "w.xmp", _xmpgen.xmp_text({"Contrast2012": "+12"}, name="寫"))
        real = safe_write.create_new

        def full(path, root, data, **k):
            if path.endswith(".xmp"):
                raise OSError(28, "No space left on device")
            return real(path, root, data, **k)
        with mock.patch.object(safe_write, "create_new", full):
            r = self.f.import_presets([src])["results"]
        self.assertEqual(r, [{"ok": False, "source": "w.xmp",
                              "error": "無法寫入 preset 庫：w.xmp：[Errno 28] No space left on device"}])


class TestUserPreset(LibCase):
    def check_roundtrip(self, preset_id, strength, overrides, name="存"):
        r = self.f.save_user_preset(name, preset_id=preset_id, strength=strength, overrides=overrides)
        path = os.path.join(self.root, *r["file"].split("/"))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith(XMP_HEAD), text[:300])
        for k, v in re.findall(r'crs:(\w+)="([^"]*)"', text):
            if k not in ("PresetType", "ProcessVersion", "HasSettings", "What", "CorrectionName", "MaskInverted",
                         "Flipped", "ConvertToGrayscale"):
                self.assertRegex(v, NUM, k)
        for k in ("Temperature", "Tint", "WhiteBalance"):
            self.assertNotIn(f"crs:{k}=", text)
        src = self.f._library.library.get(preset_id) if preset_id else None
        want = semantics.effective_params(src, semantics.validate_strength(strength),
                                          semantics.validate_overrides(overrides))
        got = load_preset(path)
        self.assertEqual(got.values, {k: v for k, v in want.values.items() if k not in ("Temperature", "Tint")})
        self.assertEqual(got.curves, want.curves)
        self.assertEqual(got.masks, want.masks)
        self.assertLessEqual(set(got.skipped), set(want.skipped))
        self.assertEqual(self.f.preset_detail(r["id"])["name"], name.strip())
        return r, got

    def test_user_preset_roundtrip(self):  # K13 / KP6
        cases = [("p-curve", 100, None), ("p-curve", 0, None), ("p-curve", 150, {"Exposure2012": 0.00001}),
                 ("p-curve", 200, {"Contrast2012": 500.0, "Exposure2012": -50.0}), ("p-linear", 150, None),
                 ("p-radial", 200, {"Saturation": 1e-05}), ("p-radial", 37.5, {"Vibrance": -0.1}),
                 (None, 100, {"Exposure2012": 0.35, "SplitToningShadowHue": 359.5})]
        for pid, s, o in cases:
            with self.subTest(pid=pid, s=s, o=o):
                self.check_roundtrip(pid, s, o)
        r, got = self.check_roundtrip("p-curve", 100, None, name=' 名稱 <&"\'> 中文 ')
        self.assertEqual(r["name"], '名稱 <&"\'> 中文')
        self.assertIs(got.values["ConvertToGrayscale"], True)
        self.assertEqual(got.values["SplitToningShadowHue"], 200.0)     # hue key not scaled
        self.assertEqual(len(load_preset(os.path.join(self.root, "user", "存 (2).xmp")).masks), 0)

    def test_save_shape_and_order(self):  # K12 / KP9
        r = self.f.save_user_preset("我的", preset_id="p-plain", strength=50)
        self.assertEqual(r, {"id": "user:我的", "name": "我的", "group": USER_GROUP, "file": "user/我的.xmp"})
        self.assertEqual(self.f.save_user_preset("我的", group="A - B", overrides={"Contrast2012": 3})["group"], "A - B")
        cases = [((), {"name": ""}, ("invalid", "preset 名稱要 1～100 個字")),
                 ((), {"name": "", "preset_id": "nope", "strength": 250}, ("invalid", "preset 名稱要 1～100 個字")),
                 ((), {"name": "x", "group": "A -  - B", "preset_id": "nope"},
                  ("invalid", "群組名稱不能是空的，也不能有空的層級：A -  - B")),
                 ((), {"name": "x", "preset_id": "nope", "strength": 250},
                  ("not_found", "unknown or unsupported preset nope")),
                 ((), {"name": "x", "preset_id": "p-old"}, ("not_found", "unknown or unsupported preset p-old")),
                 ((), {"name": "x", "preset_id": "p-plain", "strength": 250},
                  ("invalid", "strength must be within 0..200, got 250")),
                 ((), {"name": "x", "preset_id": "p-plain", "overrides": {"Bogus": 1}},
                  ("invalid", "unknown slider key 'Bogus'")),
                 ((), {"name": "x"}, ("invalid", "沒有可以存的設定（沒選 preset 也沒有微調）")),
                 ((), {"name": "x", "overrides": {}}, ("invalid", "沒有可以存的設定（沒選 preset 也沒有微調）"))]
        for a, k, want in cases:
            self.assertEqual(self.err(self.f.save_user_preset, *a, **k), want, k)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "user"))), ["我的 (2).xmp", "我的.xmp"])

    def test_save_never_overwrites(self):  # K12
        user = self.src("user")
        with open(os.path.join(user, "同名.xmp"), "wb") as f:
            f.write(b"an earlier file")
        before = tree_snapshot(user)
        ids = [self.f.save_user_preset("同名", preset_id="p-plain")["id"] for _ in range(3)]
        self.assertEqual(ids, ["user:同名 (2)", "user:同名 (3)", "user:同名 (4)"])
        after = tree_snapshot(user)
        self.assertEqual(after["同名.xmp"], before["同名.xmp"])
        self.assertEqual(len(after), 4)

    def test_save_failure_leaves_no_file(self):  # K12
        from darkroom_app import safe_write
        real = safe_write.create_new

        def broken(path, root, data, **k):
            if path.endswith(".xmp"):
                raise OSError(28, "No space left on device")
            return real(path, root, data, **k)
        with mock.patch.object(safe_write, "create_new", broken):
            kind, msg = self.err(self.f.save_user_preset, "失敗", preset_id="p-plain")
        self.assertEqual((kind, msg), ("unavailable", "無法寫入自存 preset：[Errno 28] No space left on device"))
        self.assertEqual(os.listdir(os.path.join(self.root, "user")), [])
        self.assertFalse(os.path.exists(self.index_path))

    def test_safe_filename_stays_in_user(self):  # K14
        from darkroom_app.services.preset_library import safe_stem
        self.assertEqual(safe_stem('a<b>c:d"e/f\\g|h?i*j\x01k'), "a_b_c_d_e_f_g_h_i_j_k")
        self.assertEqual(safe_stem("name. . "), "name")
        self.assertEqual(safe_stem("..."), "preset")
        self.assertEqual(safe_stem("   "), "preset")
        for res in ("CON", "prn", "Aux", "nul", "COM1", "com9", "LPT1", "lpt9", "con.txt"):
            self.assertEqual(safe_stem(res), "_" + res)
        self.assertEqual(safe_stem("COM10"), "COM10")
        for spaced in ("CON .x", "nul .a.b", " aux", "Lpt1 "):            # reserved part with spaces around it
            self.assertTrue(safe_stem(spaced).startswith("_"), spaced)
        self.assertEqual(len(safe_stem("長" * 200)), 80)
        user = os.path.join(self.root, "user")
        for name in ("..\\x", "a/b", "../../y", "CON", "...", "C:\\abs"):
            r = self.f.save_user_preset(name, preset_id="p-plain")
            p = os.path.join(self.root, *r["file"].split("/"))
            self.assertEqual(os.path.normcase(os.path.dirname(os.path.abspath(p))), os.path.normcase(user), name)
        self.assertEqual(sorted(os.listdir(self.root)), ["library.json", "library.json.lock", "user", "xmp"])

    def test_numbers_never_use_exponents(self):  # K13
        from darkroom_app.services.preset_library import num_text
        for v in (1e-05, -2.5e-07, 0.1, 100.0, -0.0, 3, 1e-300, 123456.789):
            t = num_text(v)
            self.assertRegex(t, NUM, v)
            self.assertEqual(float(t), float(v))


class TestConcurrency(LibCase):
    def test_index_concurrent_processes(self):  # K15: App in-process + 2 CLI child processes, 20 favorites each
        for i in range(60):
            _xmpgen.write(self.pd, f"c{i:02d}.xmp", _xmpgen.xmp_text({"Contrast2012": str(i)}, name=f"c{i}"))
        f = self.facade()
        code = ("import sys, io, contextlib\n"
                "from darkroom_app import cli\n"
                "for i in range(int(sys.argv[2]), int(sys.argv[2]) + 20):\n"
                "    with contextlib.redirect_stdout(io.StringIO()):\n"
                "        rc = cli.main(['--preset-dir', sys.argv[1], 'presets', 'favorite', f'c{i:02d}', 'on', '--json'])\n"
                "    assert rc == 0, (i, rc)\n")
        stop, failures, reads = threading.Event(), [], [0]

        def reader():
            while not stop.is_set():
                reads[0] += read_index_like_the_app(self.index_path, failures)
        f.rebuild_library()
        t = threading.Thread(target=reader)
        t.start()
        try:
            procs = [subprocess.Popen([*_util.guarded_python(), "-c", code, self.pd, str(start)], cwd=_util.REPO,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for start in (0, 20)]
            for i in range(40, 60):
                f.set_favorite(f"c{i:02d}", True)
            outs = [p.communicate(timeout=300) for p in procs]
        finally:
            stop.set()
            t.join()
        for p, (out, err) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, err.decode("utf-8", "replace"))
        self.assertEqual(failures, [])
        self.assertGreater(reads[0], 0)
        idx = read_json(self.index_path)
        self.assertEqual(sorted(k for k, e in idx["presets"].items() if e["favorite"]), [f"c{i:02d}" for i in range(60)])
        self.assertEqual(len(f.list_presets(favorites=True)["items"]), 60)
        self.assertEqual([n for n in os.listdir(self.root) if ".tmp-" in n], [])

    def test_index_atomic_reader_never_fails(self):  # K15: a reader in this process during 100 writes
        stop, failures = threading.Event(), []

        def reader():
            while not stop.is_set():
                read_index_like_the_app(self.index_path, failures)
        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(100):
                self.f.rename_preset("p-plain", f"名{i}")
        finally:
            stop.set()
            t.join()
        self.assertEqual(failures, [])
        self.assertEqual(read_json(self.index_path)["presets"]["p-plain"]["name"], "名99")


class TestLibraryHttp(AioHTTPTestCase):  # KP4: R10 middleware, no paths over HTTP
    async def get_application(self):
        from darkroom_app.server import make_app
        from test_layering import _NoEngine
        self.root = _util.tmpdir(self)
        self.pd = os.path.join(self.root, "xmp")
        os.makedirs(self.pd)
        lib_presets(self.pd)
        return make_app(self.pd, engine=_NoEngine())

    async def test_paths_refused_over_http(self):
        src = os.path.join(self.root, "src")
        os.makedirs(src)
        _xmpgen.write(src, "a.xmp", _xmpgen.xmp_text({"Contrast2012": "+1"}, name="a"))
        for paths in ([src], None, []):
            r = await self.client.post("/api/preset-library/import", json={"paths": paths})
            self.assertEqual((r.status, await r.json()),
                             (400, {"error": "paths is not accepted over HTTP (upload the files)"}))
        self.assertEqual(sorted(os.listdir(self.root)), ["src", "xmp"])

    async def test_upload_and_favorites(self):
        data = base64.b64encode(_xmpgen.xmp_text({"Contrast2012": "+1"}, name="上傳").encode()).decode()
        r = await self.client.post("/api/preset-library/import", json={"files": [{"name": "u.xmp", "data_base64": data}]})
        self.assertEqual((r.status, await r.json()), (200, {"results": [{"ok": True, "source": "u.xmp",
                                                                         "id": "import:u"}]}))
        r = await self.client.post("/api/preset-library/favorite", json={"preset_id": "import:u", "favorite": True})
        self.assertEqual(r.status, 200)
        rows = await (await self.client.get("/api/presets?favorites=1")).json()
        self.assertEqual([x["id"] for x in rows], ["import:u"])
        self.assertEqual(len(await (await self.client.get("/api/presets")).json()), 6)
        r = await self.client.get("/api/presets/" + "import%3Au")
        self.assertEqual((await r.json())["name"], "上傳")
        r = await self.client.post("/api/preset-library/save", json={"name": "存", "preset_id": "p-plain"})
        self.assertEqual(await r.json(), {"id": "user:存", "name": "存", "group": USER_GROUP, "file": "user/存.xmp"})
        r = await self.client.post("/api/preset-library/favorite", json={"preset_id": "nope", "favorite": True})
        self.assertEqual((r.status, await r.json()), (404, {"error": "unknown preset nope"}))

    async def test_cross_site_refused_and_nothing_written(self):
        before = sorted(os.listdir(self.root))
        for path, body in (("/api/preset-library/favorite", {"preset_id": "p-plain", "favorite": True}),
                           ("/api/preset-library/save", {"name": "x", "preset_id": "p-plain"}),
                           ("/api/preset-library/rebuild", {}),
                           ("/api/preset-library/import", {"files": []})):
            r = await self.client.post(path, data=json.dumps(body), headers={"Content-Type": "text/plain"})
            self.assertEqual(r.status, 415, path)
            r = await self.client.post(path, json=body, headers={"Origin": "http://evil.example"})
            self.assertEqual(r.status, 403, path)
            r = await self.client.post(path, json=body, headers={"Host": "evil.example"})
            self.assertEqual(r.status, 421, path)
        r = await self.client.get("/api/preset-library/groups", headers={"Origin": "null"})
        self.assertEqual(r.status, 403)
        self.assertEqual(sorted(os.listdir(self.root)), before)


class TestBadEncoding(LibCase):  # seal F2: an unknown XML encoding is one failed item / one unsupported preset
    BAD = b"<?xml version='1.0' encoding='bogus'?><x:xmpmeta xmlns:x='adobe:ns:meta/'/>"

    def test_import_bad_encoding_fails_one_item(self):
        good = base64.b64encode(_xmpgen.xmp_text({"Contrast2012": "+2"}, name="好").encode()).decode()
        r = self.f.import_presets(None, None, [{"name": "good.xmp", "data_base64": good},
                                               {"name": "bad.xmp", "data_base64": base64.b64encode(self.BAD).decode()}])
        self.assertEqual([x["ok"] for x in r["results"]], [True, False])
        self.assertTrue(r["results"][1]["error"].startswith("無法讀取 preset：bad.xmp："), r)
        self.assertIn("import:good", [x["id"] for x in self.f.list_presets()["items"]])
        src = self.src()
        with open(os.path.join(src, "bad2.xmp"), "wb") as fh:
            fh.write(self.BAD)
        r = self.f.import_presets([src])
        self.assertEqual(r["results"][0]["ok"], False)
        self.assertEqual(os.listdir(os.path.join(self.root, "import")), ["good.xmp"])

    def test_library_loads_with_bad_encoding_file(self):
        user = self.src("user")
        with open(os.path.join(user, "dropped.xmp"), "wb") as fh:
            fh.write(self.BAD)
        rows = {x["id"]: x for x in self.facade().list_presets()["items"]}
        self.assertIs(rows["user:dropped"]["supported"], False)


class TestLibraryCli(LibCase):
    def call(self, argv):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv, facade=self.f)
        return rc, out.getvalue(), err.getvalue()

    def test_cli_uses_configured_library_root(self):  # seal F1 / KP2: no --preset-dir -> preset_library_dir
        from darkroom_app import cli, config
        lib = self.src("configured-lib")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(config, "preset_dir", return_value=self.pd), \
                mock.patch.object(config, "preset_library_dir", return_value=lib), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["presets", "favorite", "p-plain", "on", "--json"])
        self.assertEqual((rc, err.getvalue()), (0, ""))
        self.assertTrue(os.path.exists(os.path.join(lib, "library.json")))
        self.assertFalse(os.path.exists(self.index_path))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["--preset-dir", self.pd, "presets", "favorite", "p-plain", "on", "--json"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.index_path))               # explicit folder -> dirname(preset_dir)

    def test_cli_commands(self):  # K16 / KP5 / KP9
        self.assertEqual(self.call(["presets", "favorite", "p-plain", "on", "--json"])[0], 0)
        self.assertTrue(self.f.preset_detail("p-plain") and self.f.list_presets(favorites=True)["total"] == 1)
        self.assertEqual(self.call(["presets", "favorite", "p-plain", "off"])[0], 0)
        self.assertEqual(self.call(["presets", "favorite", "p-plain", "yes"]), (2, "", "favorite 必須是 true 或 false\n"))
        rc, out, _ = self.call(["presets", "list", "--favorites", "--json"])
        self.assertEqual(json.loads(out)["result"]["total"], 0)
        src = self.src()
        _xmpgen.write(src, "a.xmp", _xmpgen.xmp_text({"Contrast2012": "+4"}, name="a"))
        with open(os.path.join(src, "b.txt"), "w") as f:
            f.write("x")
        rc, out, err = self.call(["presets", "import", src, os.path.join(src, "b.txt")])
        self.assertEqual((rc, out, err), (6, "已匯入：import:a\n不是 .xmp 檔：b.txt\n", ""))
        rc, out, err = self.call(["presets", "save", "--name", "N", "--preset", "p-plain", "--strength", "50",
                                  "--override", "Exposure2012=0.5", "--json"])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out)["result"]["id"], "user:N")
        self.assertEqual(self.call(["groups", "create", "電影"]), (4, "", "群組已存在：電影\n"))
        self.assertEqual(self.call(["groups", "rename", "沒有", "x"]), (3, "", "找不到群組：沒有\n"))
        self.assertEqual(self.call(["presets", "rebuild", "--json"])[0], 0)
        self.assertEqual(self.call(["presets", "groups", "--json"])[0], 0)


if __name__ == "__main__":
    unittest.main()
