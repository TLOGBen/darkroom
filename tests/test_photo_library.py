"""CONTRACT-photo-library PL1-PL14, PLP1-PLP8: the photo library behind the facade (edits, snapshots, thumbnails, index).

Every photo is made by the test (JPEG with orientation 6 and an IFD1 thumbnail, JPEG with a letterboxed IFD1
thumbnail, JPEG without EXIF, PNG, TIFF, HEIC with and without a thumbnail). data_dir is always a folder inside the
fixture root; the real %LOCALAPPDATA%/darkroom is never touched (G7, test_tests_never_touch_real_data_dir).
"""
import ast
import builtins
import copy
import hashlib
import io
import json
import os
import shutil
import struct
import threading
import unittest
from unittest import mock

import cv2
import numpy as np
from aiohttp.test_utils import AioHTTPTestCase

import _heicgen
import _util
import _writeguard
import _xmpgen
from darkroom import Params, load_preset, read_image
from darkroom_app import config, preview as semantics, safe_write
from darkroom_app.errors import DarkroomError
from darkroom_app.services import photo_library as pl
from test_app_server import make_presets, snapshot, write_photo
from test_export import exif_app1, pattern, write_jpeg, write_png

NO_EDIT = "這張照片沒有編輯：{file_name}"                                   # verbatim (PL7)
FOLDER_NOT_FOUND = "找不到照片資料夾：{folder}"                              # verbatim (PL13)
SOURCE_OR_EDIT = "source 與 edit 要恰好給一個"                                # verbatim (PL8)
EDIT_INVALID = "edit 不是 darkroom-edit/1 編輯：{reason}"                     # verbatim (PL8)
TARGETS_INVALID = "targets 要是 1～500 個照片路徑"                            # verbatim (PL8)
THUMB_FAILED = "縮圖產生失敗：{file_name}：{reason}"                          # verbatim (PL11)
SCHEMA_CONFLICT = "編輯檔版本不支援：{schema}（{file_name}）"                  # verbatim (PL9)
EDIT_CORRUPT = "照片庫的編輯檔損壞：{edit_file}"                              # verbatim (PL9)
CANNOT_WRITE = "無法寫入照片庫：{data_dir}：{reason}"                         # verbatim (PL9)
DATA_DIR_INSIDE = "照片庫資料區不能在照片或 preset 資料夾底下：{data_dir}"       # verbatim (PLP1)
CONFIG_ERROR = "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在"   # verbatim (PL1)
EDIT_KEYS = ["schema", "fingerprint", "preset", "strength", "overrides"]    # verbatim order (PL3)
THUMB_TOL = 6 / 255                                                          # verbatim (PLP8)


# ---------------------------------------------------------------- photos made by the test
def add_ifd1(t, thumb):
    """Append an IFD1 pointing at JPEG `thumb` to TIFF-structured bytes `t` and link it from IFD0."""
    e = "<" if t[:2] == b"II" else ">"
    (ifd0,) = struct.unpack_from(e + "I", t, 4)
    (n,) = struct.unpack_from(e + "H", t, ifd0)
    at = len(t) + (len(t) % 2)
    ifd1 = struct.pack(e + "H", 3)
    data_at = at + 2 + 36 + 4
    ifd1 += struct.pack(e + "HHIHH", 259, 3, 1, 6, 0)
    ifd1 += struct.pack(e + "HHII", 513, 4, 1, data_at)
    ifd1 += struct.pack(e + "HHII", 514, 4, 1, len(thumb))
    ifd1 += struct.pack(e + "I", 0)
    t = bytearray(t + b"\0" * (at - len(t)) + ifd1 + thumb)
    struct.pack_into(e + "I", t, ifd0 + 2 + 12 * n, at)
    return bytes(t)


def write_jpeg_with_thumb(path, rgb, thumb_rgb, orientation=1, quality=95):
    """JPEG with EXIF (orientation) and an IFD1 thumbnail holding `thumb_rgb` (stored in sensor orientation)."""
    ok, enc = cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    h, w = rgb.shape[:2]
    app1 = exif_app1(orientation, (w, h))
    body = app1[4:]
    body = body[:6] + add_ifd1(body[6:], cv2.imencode(".jpg", thumb_rgb[..., ::-1])[1].tobytes())
    app1 = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    data = enc.tobytes()
    with open(path, "wb") as f:
        f.write(data[:2] + app1 + data[2:])
    return path


def write_tiff(path, rgb):
    ok, enc = cv2.imencode(".tif", rgb[..., ::-1])
    assert ok
    with open(path, "wb") as f:
        f.write(enc.tobytes())
    return path


def write_heic(path, rgb, thumbnail=None):
    import pillow_heif
    h, w = rgb.shape[:2]
    hf = pillow_heif.from_bytes(mode="RGB", size=(w, h), data=np.ascontiguousarray(rgb).tobytes())
    if thumbnail:
        hf.info["thumbnails"] = [thumbnail]
    hf.save(path, quality=-1, chroma=444, matrix_coefficients=0)
    return path


def letterboxed(rgb, tw, th):
    """`rgb` fitted into a tw x th black frame (what some cameras write as the EXIF thumbnail)."""
    h, w = rgb.shape[:2]
    s = min(tw / w, th / h)
    small = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    out = np.zeros((th, tw, 3), np.uint8)
    y, x = (th - small.shape[0]) // 2, (tw - small.shape[1]) // 2
    out[y:y + small.shape[0], x:x + small.shape[1]] = small
    return out


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def decode_bgr(jpeg):
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def reference_thumb(path, size):
    """What the thumbnail must look like: read_image (display orientation, sRGB) shrunk to `size` (w, h)."""
    img = (np.clip(read_image(path), 0, 1) * 255 + 0.5).astype(np.uint8)[..., ::-1]
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA) if img.shape[1::-1] != size else img


def mean_abs_diff(a, b):
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean()) / 255.0


class PhotoLibCase(unittest.TestCase):
    engine = False

    def setUp(self):
        from darkroom_app.composition import build_facade
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "lib", "xmp")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.data = os.path.join(self.tmp, "data")
        eng = None
        if self.engine:
            from darkroom_app import engine as engine_mod
            eng = engine_mod.Engine()
            self.addCleanup(eng.shutdown)
        self.f = build_facade(self.presets, engine=eng, data_dir=self.data)
        self.lib = self.f._photo_library
        self.addCleanup(self.lib.wait_thumbnails, 60)       # background work ends inside the test's own root

    def photo(self, name="a.jpg", w=640, h=480, seed=0):
        return write_photo(os.path.join(self.photos, name), w, h, seed)

    def err(self, fn, *a, **k):
        with self.assertRaises(DarkroomError) as cm:
            fn(*a, **k)
        return cm.exception.kind, cm.exception.message

    def edit_file(self, fp):
        return os.path.join(self.data, "edits", fp[:2], fp + ".json")

    def change_preset(self, pid="p-expo", exposure="+2.50"):
        """Rewrite a purchased preset file and let the library see it (K5 rebuild)."""
        _xmpgen.write(self.presets, pid + ".xmp", _xmpgen.xmp_text({"Exposure2012": exposure}, name="變了", group="風景 - 海邊"))
        self.f.rebuild_library()


# ---------------------------------------------------------------- PL1, PL2
class TestDataDirAndFingerprint(PhotoLibCase):
    def test_data_dir_config(self):  # PL1
        cfg = os.path.join(self.tmp, "c.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"data_dir": "D:/x/data"}, f)
        self.assertEqual(config.data_dir(cfg, {"LOCALAPPDATA": "C:/L"}), "D:/x/data")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"data_dir": ""}, f)
        self.assertEqual(config.data_dir(cfg, {"LOCALAPPDATA": "C:/L"}), os.path.join("C:/L", "darkroom"))
        with self.assertRaises(config.ConfigError) as cm:
            config.data_dir(cfg, {})
        self.assertEqual(str(cm.exception), CONFIG_ERROR)

    def test_reads_create_nothing(self):  # PL1: only a write creates edits/, thumbs/, index/
        a = self.photo()
        r = self.f.get_edit(a)
        self.assertEqual((r["edit"], r["preset_status"]), (None, None))
        self.f.clear_edit(a)
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.f.folder_thumbnails(empty)                       # nothing to thumbnail: no background write either
        self.assertTrue(self.lib.wait_thumbnails(30))
        self.assertFalse(os.path.exists(self.data))
        self.f.folder_thumbnails(self.photos)                 # PL12: the background pre-generation writes (seal F2)
        self.assertTrue(self.lib.wait_thumbnails(30))
        self.assertEqual(sorted(os.listdir(self.data)), ["index", "thumbs"])

    def test_data_dir_parent_missing_is_unavailable(self):  # PL9 / PLP17 (seal F1)
        from darkroom_app.composition import build_facade
        a = self.photo()
        parent = os.path.join(self.tmp, "no-such-parent")
        bad = os.path.join(parent, "darkroom")
        f = build_facade(self.presets, data_dir=bad)
        self.addCleanup(f._photo_library.wait_thumbnails, 60)
        want = ("unavailable", CANNOT_WRITE.format(data_dir=bad, reason=f"上層資料夾不存在：{parent}"))
        self.assertEqual(self.err(f.set_edit, a, "p-expo"), want)
        self.assertEqual(self.err(f.thumbnail, a), want)
        self.assertEqual(f.paste_edit([a], edit=self.f.set_edit(a, "p-expo")["edit"])["results"],
                         [{"ok": False, "target": "a.jpg", "error": want[1]}])
        self.assertEqual(f.get_edit(a)["edit"], None)          # reads still work
        self.assertFalse(os.path.exists(parent))
        with mock.patch.object(safe_write, "make_dirs", side_effect=OSError("read-only")):
            g = build_facade(self.presets, data_dir=os.path.join(self.tmp, "fresh"))
            self.assertEqual(self.err(g.set_edit, a, "p-expo"),
                             ("unavailable", CANNOT_WRITE.format(data_dir=os.path.join(self.tmp, "fresh"),
                                                                 reason="read-only")))

    def test_fingerprint_content_only(self):  # PL2
        a = self.photo("a.jpg")
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        b = shutil.copyfile(a, os.path.join(other, "renamed.jpg"))
        fa, fb = pl.fingerprint(a), pl.fingerprint(b)
        self.assertEqual(fa, fb)
        self.assertEqual(fa, sha(a))
        self.assertRegex(fa, r"^[0-9a-f]{64}$")
        with open(a, "rb") as f:
            data = bytearray(f.read())
        data[-1] ^= 1
        c = os.path.join(self.photos, "c.jpg")
        with open(c, "wb") as f:
            f.write(data)
        self.assertNotEqual(pl.fingerprint(c), fa)
        with open(a, "rb") as f:
            self.assertEqual(pl.fingerprint_bytes(f.read()), fa)
        self.assertEqual(self.f.get_edit(a)["fingerprint"], fa)
        self.assertEqual(self.f.get_edit(b)["fingerprint"], fa)         # moved / renamed: the same photo

    def test_same_content_shares_the_edit(self):  # PL2 / ADR-0002
        a = self.photo("a.jpg")
        b = shutil.copyfile(a, os.path.join(self.photos, "copy.jpg"))
        self.f.set_edit(a, "p-expo", 120, {"Contrast2012": 5})
        self.assertEqual(self.f.get_edit(b)["edit"], self.f.get_edit(a)["edit"])

    def test_tests_never_touch_real_data_dir(self):  # PL1 / G7
        real = _writeguard.protected_folders()[2]
        self.assertTrue(real.lower().endswith(os.path.join("appdata", "local", "darkroom").lower()))
        self.assertEqual(_writeguard.snapshot([real]), {real: _writeguard.arm_snapshot()[real]})


class TestOpenFingerprint(PhotoLibCase):
    engine = True

    def test_open_rehashes_after_change(self):  # PL2
        a = self.photo("a.png", 320, 200)
        info = self.f.open_photo(a)
        eng = self.f._photos.engine_ref.peek()
        fp1 = eng.get(info["image_id"])["fingerprint"]
        self.assertEqual(fp1, sha(a))
        self.assertEqual(sorted(info), ["height", "image_id", "preview_height", "preview_width", "width"])   # L8 shape
        write_photo(a, 320, 200, seed=7)
        info2 = self.f.open_photo(a)
        self.assertNotEqual(eng.get(info2["image_id"])["fingerprint"], fp1)
        self.assertEqual(eng.get(info2["image_id"])["fingerprint"], sha(a))


# ---------------------------------------------------------------- PL3, PL4, PL7, PL9, PL10
class TestEdits(PhotoLibCase):
    def test_edit_file_shape(self):  # PL3
        a = self.photo()
        r = self.f.set_edit(a, "p-expo", 150.0, {"Exposure2012": 0.25})
        fp = r["fingerprint"]
        p = self.edit_file(fp)
        self.assertTrue(os.path.isfile(p))
        with open(p, "rb") as f:
            raw = f.read()
        self.assertIn("曝光一".encode("utf-8"), raw)                          # ensure_ascii=False
        obj = json.loads(raw.decode("utf-8"))
        self.assertEqual(list(obj), EDIT_KEYS)
        self.assertEqual(list(obj["preset"]), ["id", "name", "group", "params"])
        self.assertEqual(obj["preset"]["params"], self.lib.library.get("p-expo").to_dict())
        self.assertEqual((obj["preset"]["id"], obj["preset"]["name"], obj["preset"]["group"]),
                         ("p-expo", "曝光一", "風景 - 海邊"))
        self.assertEqual(obj["strength"], 150)
        self.assertIsInstance(obj["strength"], int)                             # PLP8: whole numbers as ints
        self.assertEqual(obj["overrides"], {"Exposure2012": 0.25})
        self.assertEqual(obj, r["edit"])
        self.assertEqual(self.f.set_edit(a, "p-expo", 87.5)["edit"]["strength"], 87.5)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [fp + ".json"])   # no tmp left

    def test_empty_edit_removes_file(self):  # PL3
        a = self.photo()
        fp = self.f.set_edit(a, None, 100, {"Exposure2012": 0.5})["fingerprint"]
        self.assertTrue(os.path.exists(self.edit_file(fp)))
        r = self.f.set_edit(a, None, 100, {})
        self.assertEqual(r, {"fingerprint": fp, "edit": None, "preset_status": None, "previous": True})   # S4
        self.assertFalse(os.path.exists(self.edit_file(fp)))
        self.assertEqual(self.f.set_edit(a, None, 100, None)["edit"], None)   # idempotent

    def test_set_edit_order_and_sentences(self):  # PL7
        a = self.photo()
        self.assertEqual(self.err(self.f.set_edit, ""), ("invalid", "path is required"))
        self.assertEqual(self.err(self.f.set_edit, 5), ("invalid", "path is required"))
        missing = os.path.join(self.photos, "nope.jpg")
        self.assertEqual(self.err(self.f.set_edit, missing), ("not_found", f"photo not found: {missing}"))
        txt = os.path.join(self.photos, "n.txt")
        with open(txt, "w") as f:
            f.write("x")
        self.assertEqual(self.err(self.f.set_edit, txt), ("invalid", "unsupported photo format (JPEG/PNG/TIFF/HEIC)"))
        self.assertEqual(self.err(self.f.set_edit, a, "nope", 250), ("not_found", "unknown or unsupported preset nope"))
        self.assertEqual(self.err(self.f.set_edit, a, "p-old", 250), ("not_found", "unknown or unsupported preset p-old"))
        self.assertEqual(self.err(self.f.set_edit, a, "p-expo", 250, {"Bogus": 1}),
                         ("invalid", "strength must be within 0..200, got 250"))
        self.assertEqual(self.err(self.f.set_edit, a, "p-expo", 100, {"Bogus": 1}), ("invalid", "unknown slider key 'Bogus'"))
        self.assertEqual(self.err(self.f.set_edit, a, "p-expo", "x"), ("invalid", "strength must be a number in 0..200"))
        for fn in (self.f.get_edit, self.f.clear_edit, self.f.thumbnail):
            self.assertEqual(self.err(fn, missing), ("not_found", f"photo not found: {missing}"))
            self.assertEqual(self.err(fn, txt), ("invalid", "unsupported photo format (JPEG/PNG/TIFF/HEIC)"))
        self.assertFalse(os.path.exists(self.data))

    def test_get_set_clear_shapes(self):  # PL7, as revised by CONTRACT-s1-experience S4 (previous)
        a = self.photo()
        r = self.f.set_edit(a, "p-expo")
        self.assertEqual(list(r), ["fingerprint", "edit", "preset_status", "previous"])
        self.assertIs(r["previous"], False)
        self.assertEqual(self.f.get_edit(a), r)
        c = self.f.clear_edit(a)
        self.assertEqual(c, {"fingerprint": r["fingerprint"], "edit": None, "preset_status": None, "previous": True})
        self.assertEqual(self.f.clear_edit(a), c)                               # idempotent
        self.assertEqual(self.f.get_edit(a)["edit"], None)

    def test_restore_previous_edit(self):  # CONTRACT-s1-experience S4
        a = self.photo()
        b = self.photo("b.jpg", seed=3)
        fp = sha(a)
        prev_file = os.path.join(self.data, "edits", fp[:2], fp + ".prev.json")
        self.assertEqual(self.err(self.f.restore_edit, a), ("not_found", "這張照片沒有上一份編輯可以取回：a.jpg"))
        first = self.f.set_edit(a, "p-expo", 130, {"Contrast2012": 4})
        self.assertFalse(os.path.exists(prev_file))
        self.f.set_edit(a, "p-strong", 90)                                  # replacing keeps nothing
        self.assertFalse(os.path.exists(prev_file))
        self.f.paste_edit([b], source=a)                                   # pasting keeps nothing
        self.assertFalse(os.path.exists(os.path.join(self.data, "edits", sha(b)[:2], sha(b) + ".prev.json")))
        with open(self.edit_file(fp), "rb") as f:
            cleared_bytes = f.read()
        c = self.f.clear_edit(a)
        self.assertEqual((c["edit"], c["previous"]), (None, True))
        with open(prev_file, "rb") as f:
            self.assertEqual(f.read(), cleared_bytes)                       # kept byte for byte
        self.assertEqual(self.f.get_edit(a)["previous"], True)
        r = self.f.restore_edit(a)
        self.assertEqual(list(r), ["fingerprint", "edit", "preset_status", "previous"])
        self.assertEqual((r["edit"]["preset"]["id"], r["edit"]["strength"], r["previous"]), ("p-strong", 90, True))
        with open(self.edit_file(fp), "rb") as f:
            self.assertEqual(f.read(), cleared_bytes)
        self.assertTrue(os.path.exists(prev_file))                          # the kept copy stays
        self.assertEqual(self.f.restore_edit(a)["edit"], r["edit"])         # repeatable
        # clearing through set_edit with nothing chosen keeps the previous edit too
        self.f.set_edit(a, "p-expo", 100)
        self.f.set_edit(a)
        self.assertEqual(self.f.restore_edit(a)["edit"]["preset"]["id"], "p-expo")
        # PL10: nothing else in edits/ is touched; the photo folder is unchanged
        names = sorted(os.listdir(os.path.join(self.data, "edits", fp[:2])))
        self.assertEqual(names, [fp + ".json", fp + ".prev.json"])
        self.assertEqual(sorted(os.listdir(self.photos)), ["a.jpg", "b.jpg"])
        self.assertEqual(first["edit"]["preset"]["id"], "p-expo")

    def test_restore_never_over_another_edit(self):  # seal patch S4a: the current edit has no copy anywhere
        a = self.photo()
        fp = sha(a)
        self.f.set_edit(a, "p-expo", 130)
        self.f.clear_edit(a)                                                # previous = p-expo 130
        self.f.set_edit(a, "p-strong", 70, {"Contrast2012": 5})             # edited again, autosaved
        with open(self.edit_file(fp), "rb") as f:
            now = f.read()
        self.assertEqual(self.err(self.f.restore_edit, a),
                         ("conflict", "這張照片已經有別的編輯，取回上一份會蓋掉它；要取回請先還原成原圖：a.jpg"))
        with open(self.edit_file(fp), "rb") as f:
            self.assertEqual(f.read(), now)                                 # untouched, byte for byte
        self.assertEqual(self.f.get_edit(a)["edit"]["preset"]["id"], "p-strong")
        # the documented way: reset to original (the current edit becomes the previous one), then restore
        self.f.clear_edit(a)
        self.assertEqual(self.f.restore_edit(a)["edit"]["preset"]["id"], "p-strong")
        self.assertEqual(self.f.restore_edit(a)["edit"]["strength"], 70)    # the same edit again: a no-op success

    def test_previous_is_written_before_the_edit_is_removed(self):  # seal F2 / S4: no window without a copy
        a = self.photo()
        fp = sha(a)
        self.f.set_edit(a, "p-expo", 130)
        lib = self.f._photo_library
        real = lib._write_json

        def failing(target, *args, **kwargs):
            if target.endswith(".prev.json"):
                raise DarkroomError("unavailable", "injected: cannot write the previous edit")
            return real(target, *args, **kwargs)
        lib._write_json = failing
        try:
            for clear in (lambda: self.f.clear_edit(a), lambda: self.f.set_edit(a)):
                self.assertEqual(self.err(clear), ("unavailable", "injected: cannot write the previous edit"))
                self.assertTrue(os.path.exists(self.edit_file(fp)))          # the edit is still there
                self.assertEqual(self.f.get_edit(a)["edit"]["preset"]["id"], "p-expo")
        finally:
            lib._write_json = real

    def test_snapshot_survives_preset_change(self):  # PL4
        a = self.photo()
        before = self.lib.library.get("p-expo").to_dict()
        r = self.f.set_edit(a, "p-expo", 100)
        self.assertEqual(r["preset_status"], "current")
        self.change_preset("p-expo", "+2.50")
        self.assertNotEqual(self.lib.library.get("p-expo").to_dict(), before)
        g = self.f.get_edit(a)
        self.assertEqual(g["edit"]["preset"]["params"], before)
        self.assertEqual(g["preset_status"], "changed")
        again = self.f.set_edit(a, "p-expo", 130, {"Contrast2012": 3})          # same id: the snapshot is kept
        self.assertEqual(again["edit"]["preset"]["params"], before)
        self.assertEqual(again["edit"]["preset"]["name"], "曝光一")
        self.assertEqual(again["preset_status"], "changed")
        self.f.set_edit(a, "p-strong")
        fresh = self.f.set_edit(a, "p-expo")                                      # another id in between: new snapshot
        self.assertEqual(fresh["edit"]["preset"]["params"], self.lib.library.get("p-expo").to_dict())
        self.assertEqual(fresh["preset_status"], "current")

    def test_preset_status_missing_keeps_working(self):  # PL4 / PL5
        a = self.photo()
        snap = self.f.set_edit(a, "p-expo", 140)["edit"]["preset"]["params"]
        os.remove(os.path.join(self.presets, "p-expo.xmp"))      # the test's own synthetic preset file
        self.f.rebuild_library()
        self.assertNotIn("p-expo", self.lib.library.params)
        self.assertEqual(self.f.get_edit(a)["preset_status"], "missing")
        r = self.f.set_edit(a, "p-expo", 160)                      # the snapshot still resolves (PL5)
        self.assertEqual((r["edit"]["preset"]["params"], r["edit"]["strength"], r["preset_status"]), (snap, 160, "missing"))
        self.assertEqual(self.lib.resolve_params(r["fingerprint"], "p-expo").to_dict(), snap)
        b = self.photo("b.jpg", seed=3)
        self.assertEqual(self.err(self.f.set_edit, b, "p-expo"), ("not_found", "unknown or unsupported preset p-expo"))

    def test_old_edit_kept_after_content_change(self):  # PL10
        a = self.photo()
        r1 = self.f.set_edit(a, "p-expo", 110)
        p1 = self.edit_file(r1["fingerprint"])
        bytes1 = open(p1, "rb").read()
        write_photo(a, 640, 480, seed=9)
        self.assertEqual(self.f.get_edit(a)["edit"], None)                       # a new photo
        r2 = self.f.set_edit(a, "p-strong", 90)
        self.assertNotEqual(r2["fingerprint"], r1["fingerprint"])
        self.f.clear_edit(a)
        self.assertEqual(open(p1, "rb").read(), bytes1)
        self.assertFalse(os.path.exists(self.edit_file(r2["fingerprint"])))

    def test_edit_future_schema_not_overwritten(self):  # PL9
        a = self.photo()
        fp = self.f.set_edit(a, "p-expo")["fingerprint"]
        p = self.edit_file(fp)
        future = json.dumps({"schema": "darkroom-edit/9", "fingerprint": fp, "x": 1}).encode("utf-8")
        with open(p, "wb") as f:
            f.write(future)
        want = ("conflict", SCHEMA_CONFLICT.format(schema="darkroom-edit/9", file_name="a.jpg"))
        for fn, args in ((self.f.get_edit, ()), (self.f.set_edit, ("p-expo",)), (self.f.clear_edit, ()),
                         (self.f.set_edit, (None, 100, {}))):
            self.assertEqual(self.err(fn, a, *args), want)
        self.assertEqual(open(p, "rb").read(), future)
        # resolve_params raises the same conflict (never falls back to the library silently, PLP5)
        self.assertEqual(self.err(self.lib.resolve_params, fp, "p-expo"), ("conflict", want[1].replace("a.jpg", fp)))
        res = self.f.paste_edit([a], edit=self.f.set_edit(self.photo("b.jpg", seed=2), "p-strong")["edit"])
        self.assertEqual(res["results"], [{"ok": False, "target": "a.jpg", "error": want[1]}])
        self.assertEqual(open(p, "rb").read(), future)
        with open(p, "wb") as f:
            f.write(b"{not json")
        want = ("unavailable", EDIT_CORRUPT.format(edit_file=p))
        for fn, args in ((self.f.get_edit, ()), (self.f.set_edit, ("p-expo",)), (self.f.clear_edit, ())):
            self.assertEqual(self.err(fn, a, *args), want)
        with open(p, "wb") as f:                                 # valid JSON, not an edit (a key missing)
            f.write(json.dumps({"schema": "darkroom-edit/1", "fingerprint": fp}).encode())
        self.assertEqual(self.err(self.f.get_edit, a), want)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [fp + ".json"])

    def test_edit_atomic_write(self):  # PL3: a failed replace leaves no half edit and no tmp file
        a = self.photo()
        fp = self.f.set_edit(a, "p-expo", 100)["fingerprint"]
        p = self.edit_file(fp)
        bytes1 = open(p, "rb").read()
        with mock.patch.object(safe_write, "replace_into", side_effect=OSError("disk full")):
            self.assertEqual(self.err(self.f.set_edit, a, "p-expo", 150),
                             ("unavailable", CANNOT_WRITE.format(data_dir=self.data, reason="disk full")))
        self.assertEqual(open(p, "rb").read(), bytes1)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [fp + ".json"])
        with mock.patch.object(safe_write, "create_new", side_effect=OSError("no space")):
            self.assertEqual(self.err(self.f.set_edit, self.photo("c.jpg", seed=4), "p-expo"),
                             ("unavailable", CANNOT_WRITE.format(data_dir=self.data, reason="no space")))
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [fp + ".json"])

    def test_edit_replace_retry_then_unavailable(self):  # PLP3 (KP21 budget)
        a = self.photo()
        fp = self.f.set_edit(a, "p-expo", 100)["fingerprint"]
        p = self.edit_file(fp)
        self.assertEqual((pl.REPLACE_RETRIES, pl.REPLACE_RETRY_S), (200, 0.01))
        self.assertEqual((pl.READ_RETRIES, pl.READ_RETRY_S), (10, 0.1))
        real = safe_write.replace_into
        calls = []

        def busy(tmp, dest, root, **kw):
            calls.append(tmp)
            raise PermissionError(13, "存取被拒")
        with mock.patch.object(pl, "REPLACE_RETRY_S", 0.001), mock.patch.object(safe_write, "replace_into", busy):
            kind, msg = self.err(self.f.set_edit, a, "p-expo", 150)
        self.assertEqual(kind, "unavailable")
        self.assertTrue(msg.startswith(CANNOT_WRITE.format(data_dir=self.data, reason="")), msg)
        self.assertEqual(len(calls), 200)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [fp + ".json"])
        n = [0]

        def flaky(tmp, dest, root, **kw):
            n[0] += 1
            if n[0] < 4:
                raise PermissionError(13, "存取被拒")
            return real(tmp, dest, root, **kw)
        with mock.patch.object(pl, "REPLACE_RETRY_S", 0.001), mock.patch.object(safe_write, "replace_into", flaky):
            self.assertEqual(self.f.set_edit(a, "p-expo", 150)["edit"]["strength"], 150)
        self.assertEqual(n[0], 4)

    def test_edit_reader_retries_permission_error(self):  # PLP3 (KP12 budget)
        a = self.photo()
        fp = self.f.set_edit(a, "p-expo", 100)["fingerprint"]
        p = os.path.normcase(self.edit_file(fp))
        real_open = builtins.open
        n = [0]

        def flaky(file, mode="r", *args, **kw):
            if isinstance(file, str) and os.path.normcase(file) == p and "r" in mode:
                n[0] += 1
                if n[0] <= 2:
                    raise PermissionError(13, "存取被拒")
            return real_open(file, mode, *args, **kw)
        with mock.patch.object(pl, "READ_RETRY_S", 0.001), mock.patch("builtins.open", flaky):
            self.assertEqual(self.f.get_edit(a)["edit"]["strength"], 100)
        self.assertEqual(n[0], 3)

        def always(file, mode="r", *args, **kw):
            if isinstance(file, str) and os.path.normcase(file) == p and "r" in mode:
                raise PermissionError(13, "存取被拒")
            return real_open(file, mode, *args, **kw)
        with mock.patch.object(pl, "READ_RETRY_S", 0.001), mock.patch("builtins.open", always):
            kind, msg = self.err(self.f.get_edit, a)
        self.assertEqual(kind, "unavailable")
        self.assertTrue(msg.startswith(f"無法讀取照片庫：{self.edit_file(fp)}："), msg)


# ---------------------------------------------------------------- PL8, PLP4
class TestPaste(PhotoLibCase):
    def test_paste_rules(self):
        a, b, c = self.photo("a.jpg"), self.photo("b.jpg", seed=1), self.photo("c.jpg", seed=2)
        self.f.set_edit(a, "p-expo", 130, {"Exposure2012": 0.3})
        self.assertEqual(self.err(self.f.paste_edit, [b]), ("invalid", SOURCE_OR_EDIT))
        self.assertEqual(self.err(self.f.paste_edit, [b], a, {}), ("invalid", SOURCE_OR_EDIT))
        for bad in ([], [b] * 501, "b", [1], [b, None], None):
            self.assertEqual(self.err(self.f.paste_edit, bad, a), ("invalid", TARGETS_INVALID), bad)
        self.assertEqual(self.err(self.f.paste_edit, [b], source=c), ("not_found", NO_EDIT.format(file_name="c.jpg")))
        missing = os.path.join(self.photos, "nope.jpg")
        self.assertEqual(self.err(self.f.paste_edit, [b], source=missing), ("not_found", f"photo not found: {missing}"))
        edit = self.f.get_edit(a)["edit"]
        reasons = [
            ("x", "not an object"), ({"schema": "darkroom-edit/1"}, "keys must be exactly schema, fingerprint, preset, strength, overrides"),
            ({**edit, "schema": "darkroom-edit/2"}, "schema is 'darkroom-edit/2', not darkroom-edit/1"),
            ({**edit, "preset": {"id": "p"}}, "preset must be null or {id, name, group, params}"),
            ({**edit, "preset": {**edit["preset"], "params": {"schema": "x"}}},
             "params: not a darkroom-params/1 parameter object (schema='x')"),
            ({**edit, "strength": 250}, "strength must be within 0..200, got 250"),
            ({**edit, "overrides": {"Bogus": 1}}, "unknown slider key 'Bogus'"),
        ]
        for obj, reason in reasons:
            self.assertEqual(self.err(self.f.paste_edit, [b], edit=obj), ("invalid", EDIT_INVALID.format(reason=reason)))
        self.assertEqual(self.f.get_edit(b)["edit"], None)                  # nothing was pasted by the refused calls

    def test_paste_results(self):
        a, b, c = self.photo("a.jpg"), self.photo("b.jpg", seed=1), self.photo("c.jpg", seed=2)
        self.f.set_edit(b, "p-strong", 50)
        src = self.f.set_edit(a, "p-expo", 130, {"Exposure2012": 0.3})["edit"]
        self.change_preset("p-expo")                                              # the snapshot travels, not the file
        missing = os.path.join(self.photos, "nope.jpg")
        txt = os.path.join(self.photos, "n.txt")
        with open(txt, "w") as f:
            f.write("x")
        res = self.f.paste_edit([b, missing, c, txt, "", a], source=a)
        self.assertEqual(res["results"], [
            {"ok": True, "target": "b.jpg"},
            {"ok": False, "target": "nope.jpg", "error": f"photo not found: {missing}"},
            {"ok": True, "target": "c.jpg"},
            {"ok": False, "target": "n.txt", "error": "unsupported photo format (JPEG/PNG/TIFF/HEIC)"},
            {"ok": False, "target": "", "error": "path is required"},
            {"ok": True, "target": "a.jpg"}])
        for p in (b, c):
            e = self.f.get_edit(p)["edit"]
            self.assertEqual({k: v for k, v in e.items() if k != "fingerprint"},
                             {k: v for k, v in src.items() if k != "fingerprint"})
            self.assertEqual(e["fingerprint"], sha(p))
        self.assertEqual(self.f.get_edit(b)["preset_status"], "changed")
        # the edit object of get_edit pastes the same way (the page's clipboard)
        d = self.photo("d.jpg", seed=5)
        res = self.f.paste_edit([d], edit=self.f.get_edit(a)["edit"])
        self.assertEqual(res, {"results": [{"ok": True, "target": "d.jpg"}]})
        self.assertEqual(self.f.get_edit(d)["edit"]["preset"], src["preset"])
        self.assertEqual(self.f.paste_edit([d], edit={**src, "fingerprint": "nonsense"})["results"][0]["ok"], True)
        self.assertEqual(self.f.get_edit(d)["edit"]["fingerprint"], sha(d))   # the target's own fingerprint


# ---------------------------------------------------------------- PL5, PLP5, PLP6
class TestResolveParams(PhotoLibCase):
    engine = True

    def test_resolve_params_is_the_only_rule(self):  # PLP5 (AST)
        services = os.path.join(_util.REPO, "darkroom_app", "services")
        hits = []
        for name in sorted(os.listdir(services)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(services, name), encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    body = ast.get_source_segment(src, node)
                    if "library.params" in body or "library.get(" in body:
                        hits.append((name, node.name))
        self.assertEqual(sorted(set(hits)), [("photo_library.py", "_resolve"), ("photo_library.py", "_status"),
                                             ("photo_library.py", "set_edit"),
                                             ("preset_library.py", "save_user_preset"),
                                             # CONTRACT-semantic-index SI4: presets rendered on the calibration
                                             # photos at their current values (no photo, no snapshot involved)
                                             ("semantic_index.py", "_submit"), ("semantic_index.py", "_supported")])
        self.assertEqual(self.lib.resolve_params("00" * 32, None), None)

    def preview_bytes(self, path, pid="p-expo"):
        info = self.f.open_photo(path)
        return self.f.preview(info["image_id"], pid, 120, {"Contrast2012": 4}).jpeg

    def test_preview_uses_snapshot(self):  # PL5 / PLP5
        a = self.photo("a.png", 320, 200)
        before = self.preview_bytes(a)
        self.f.set_edit(a, "p-expo", 120, {"Contrast2012": 4})
        self.change_preset("p-expo", "+3.00")
        self.assertEqual(self.preview_bytes(a), before)                           # the edit's snapshot
        self.f.clear_edit(a)
        after = self.preview_bytes(a)
        self.assertNotEqual(after, before)                                        # the library's new file
        self.assertEqual(self.err(self.f.preview, self.f.open_photo(a)["image_id"], "nope"),
                         ("not_found", "unknown or unsupported preset nope"))
        self.assertEqual(self.err(self.f.preview, self.f.open_photo(a)["image_id"], "p-old"),
                         ("not_found", "unknown or unsupported preset p-old"))

    def test_export_uses_snapshot(self):  # PL5 / PLP5
        a = self.photo("a.png", 240, 160)
        dest = os.path.join(self.tmp, "out")
        os.makedirs(dest)
        item = {"path": a, "preset_id": "p-expo", "strength": 120, "overrides": {"Contrast2012": 4}}
        out1 = self.f.export([item], "tiff", dest_dir=dest)["results"][0]["output"]
        self.f.set_edit(a, "p-expo", 120, {"Contrast2012": 4})
        self.change_preset("p-expo", "+3.00")
        out2 = self.f.export([item], "tiff", dest_dir=dest)["results"][0]["output"]
        self.assertTrue(np.array_equal(cv2.imread(out1, cv2.IMREAD_UNCHANGED), cv2.imread(out2, cv2.IMREAD_UNCHANGED)))
        self.f.clear_edit(a)
        out3 = self.f.export([item], "tiff", dest_dir=dest)["results"][0]["output"]
        self.assertFalse(np.array_equal(cv2.imread(out1, cv2.IMREAD_UNCHANGED), cv2.imread(out3, cv2.IMREAD_UNCHANGED)))
        info = self.f.open_photo(a)
        self.f.set_edit(a, "p-expo")
        self.change_preset("p-expo", "+1.00")
        r = self.f.export([{"image_id": info["image_id"], "preset_id": "p-expo"}, {"path": a, "preset_id": "p-old"}],
                          "jpeg", dest_dir=dest)["results"]
        self.assertTrue(r[0]["ok"])
        self.assertEqual(r[1], {"ok": False, "source": "a.png", "error": "匯出失敗：a.png：unknown or unsupported preset p-old"})
        fp = self.f.get_edit(a)["fingerprint"]
        with open(self.edit_file(fp), "wb") as f:
            f.write(b"{broken")
        r = self.f.export([{"path": a, "preset_id": "p-expo"}], "jpeg", dest_dir=dest)["results"]
        self.assertEqual(r, [{"ok": False, "source": "a.png",
                              "error": f"匯出失敗：a.png：{EDIT_CORRUPT.format(edit_file=self.edit_file(fp))}"}])
        self.assertEqual(self.err(self.f.preview, self.f.open_photo(a)["image_id"], "p-expo"),
                         ("unavailable", EDIT_CORRUPT.format(edit_file=self.edit_file(fp))))

    def test_save_edit_as_preset_uses_snapshot(self):  # PLP6
        a = self.photo()
        snap = self.f.set_edit(a, "p-expo", 150, {"Exposure2012": 0.25})["edit"]["preset"]["params"]
        self.change_preset("p-expo", "+3.00")
        self.assertEqual(self.err(self.f.save_edit_as_preset, self.photo("b.jpg", seed=2), "x"),
                         ("not_found", NO_EDIT.format(file_name="b.jpg")))
        self.assertEqual(self.err(self.f.save_edit_as_preset, a, "  "), ("invalid", "preset 名稱要 1～100 個字"))
        self.assertEqual(self.err(self.f.save_edit_as_preset, a, "x", "A -  - B"),
                         ("invalid", "群組名稱不能是空的，也不能有空的層級：A -  - B"))
        r = self.f.save_edit_as_preset(a, "我的快照")
        self.assertEqual((r["id"], r["name"], r["group"], r["file"]), ("user:我的快照", "我的快照", "自存 preset", "user/我的快照.xmp"))
        saved = load_preset(os.path.join(self.lib.library.root, "user", "我的快照.xmp"))
        want = semantics.effective_params(Params.from_dict(snap), 1.5, {"Exposure2012": 0.25})
        strip = lambda p: {k: v for k, v in p.values.items() if k not in ("Temperature", "Tint")}
        self.assertEqual(strip(saved), strip(want))
        self.assertEqual(saved.values["Exposure2012"], 1.75)                      # 1.0 x 1.5 + 0.25, not the new 3.0
        self.assertEqual(self.f.preset_detail("user:我的快照")["values"]["Exposure2012"], 1.75)
        r2 = self.f.save_edit_as_preset(a, "我的快照", "A - B")
        self.assertEqual((r2["id"], r2["group"]), ("user:我的快照 (2)", "A - B"))          # never overwrites (K12)


# ---------------------------------------------------------------- PLP1: data_dir placement and the write surface
class TestWriteSurface(PhotoLibCase):
    def test_data_dir_inside_photo_or_preset_folder_refused(self):  # PLP1
        from darkroom_app.composition import build_facade
        a = self.photo()
        inside = os.path.join(self.photos, ".darkroom")
        f = build_facade(self.presets, data_dir=inside)
        self.addCleanup(f._photo_library.wait_thumbnails, 60)
        want = ("unavailable", DATA_DIR_INSIDE.format(data_dir=inside))
        self.assertEqual(self.err(f.set_edit, a, "p-expo"), want)
        self.assertEqual(self.err(f.thumbnail, a), want)
        self.assertEqual(f.paste_edit([a], edit=self.f.set_edit(a, "p-expo")["edit"])["results"],
                         [{"ok": False, "target": "a.jpg", "error": want[1]}])
        f.folder_thumbnails(self.photos)
        f._photo_library.wait_thumbnails(10)
        self.assertFalse(os.path.exists(inside))
        self.assertEqual(f.get_edit(a)["edit"], None)                     # reads are fine, nothing is created
        in_presets = os.path.join(self.presets, "data")
        g = build_facade(self.presets, data_dir=in_presets)
        self.addCleanup(g._photo_library.wait_thumbnails, 60)
        self.assertEqual(self.err(g.set_edit, a, "p-expo"), ("unavailable", DATA_DIR_INSIDE.format(data_dir=in_presets)))
        self.assertFalse(os.path.exists(in_presets))
        self.assertEqual(sorted(os.listdir(self.photos)), ["a.jpg"])

    def test_cache_hit_still_refuses_data_dir_inside_photo_folder(self):  # PLP1 (seal patrol): the index write too
        from darkroom_app.composition import build_facade
        folder_a = os.path.join(self.tmp, "A")
        os.makedirs(folder_a)
        inside = os.path.join(folder_a, "data")
        f = build_facade(self.presets, data_dir=inside)
        b = self.photo("b.jpg")                                            # folder B, thumbnailed first
        other = build_facade(self.presets, data_dir=inside)
        for x in (f, other):
            self.addCleanup(x._photo_library.wait_thumbnails, 60)
        # a thumbnail for the same content made with a *valid* data_dir, then copied into inside/: cache hit
        fp = self.f.thumbnail(b).fingerprint
        os.makedirs(os.path.join(inside, "thumbs", fp[:2]))
        shutil.copyfile(os.path.join(self.data, "thumbs", fp[:2], fp + ".jpg"),
                        os.path.join(inside, "thumbs", fp[:2], fp + ".jpg"))
        a = shutil.copyfile(b, os.path.join(folder_a, "same.jpg"))
        want = ("unavailable", DATA_DIR_INSIDE.format(data_dir=inside))
        self.assertEqual(self.err(f.thumbnail, a), want)                   # cached content, still refused
        f.folder_thumbnails(folder_a)
        f._photo_library.wait_thumbnails(10)
        self.assertEqual(sorted(os.listdir(inside)), ["thumbs"])           # no index/, no edits/
        self.assertEqual(self.err(other.thumbnail, a), want)
        self.assertEqual(sorted(os.listdir(folder_a)), ["data", "same.jpg"])

    def test_photo_library_writes_under_data_dir(self):  # PL14
        a = self.photo("a.jpg")
        b = self.photo("b.png", 300, 200, seed=1)
        heic = _heicgen.write_heic(os.path.join(self.photos, "c.heic"), _heicgen.pattern(96, 128))
        written = []
        real = {n: getattr(safe_write, n) for n in ("create_new", "make_dirs", "replace_into", "remove")}

        def spy(name):
            def fn(*args, **kw):
                written.append((name, args[0] if name != "replace_into" else args[1], threading.current_thread().name))
                return real[name](*args, **kw)
            return fn
        before = snapshot(self.photos, self.presets)
        names = sorted(os.listdir(self.photos))
        with mock.patch.multiple(safe_write, **{n: spy(n) for n in real}):
            self.f.set_edit(a, "p-expo", 120)
            self.f.paste_edit([b, heic], source=a)
            self.f.clear_edit(heic)
            self.f.folder_thumbnails(self.photos)
            self.lib.wait_thumbnails(30)
            for p in (a, b, heic):
                self.f.thumbnail(p)
        self.assertTrue(written)
        root = os.path.normcase(os.path.realpath(self.data))
        for name, path, thread in written:
            self.assertEqual(os.path.commonpath([root, os.path.normcase(os.path.realpath(path))]), root, (name, path))
            if name == "create_new" and path.endswith(".jpg"):
                self.assertTrue(thread.startswith("darkroom-thumb-"), thread)
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual(sorted(os.listdir(self.photos)), names)
        self.assertEqual(sorted(os.listdir(self.data)), ["edits", "index", "thumbs"])

    def test_photo_folder_untouched(self):  # PL14 (facade level; the three interfaces in test_interface_parity)
        a = self.photo("a.jpg")
        self.photo("b.tif", 200, 150, seed=2)
        write_png(os.path.join(self.photos, "c.png"), pattern(90, 120))
        with open(os.path.join(self.photos, "broken.jpg"), "wb") as f:
            f.write(b"not a jpeg")
        before = snapshot(self.photos, self.presets)
        tree = sorted(os.path.relpath(os.path.join(r, n), self.photos) for r, ds, fs in os.walk(self.photos)
                      for n in ds + fs)
        self.f.set_edit(a, "p-expo", 120, {"Exposure2012": 0.1})
        self.f.paste_edit([p["path"] for p in self.f.folder_thumbnails(self.photos)["items"]], source=a)
        self.lib.wait_thumbnails(30)
        for p in self.f.folder_thumbnails(self.photos)["items"]:
            try:
                self.f.thumbnail(p["path"])
            except DarkroomError as e:
                self.assertTrue(e.message.startswith(THUMB_FAILED.format(file_name="broken.jpg", reason="")), e.message)
        self.f.save_edit_as_preset(a, "x")
        self.f.clear_edit(a)
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual(sorted(os.path.relpath(os.path.join(r, n), self.photos) for r, ds, fs in os.walk(self.photos)
                                for n in ds + fs), tree)


# ---------------------------------------------------------------- PL11-PL13, PLP8: thumbnails
class TestThumbnails(PhotoLibCase):
    def sources(self):
        p = lambda n: os.path.join(self.photos, n)
        big = pattern(600, 900)
        files = {
            "o6-thumb.jpg": write_jpeg_with_thumb(p("o6-thumb.jpg"), big, cv2.resize(big, (300, 200)), orientation=6),
            "letterbox.jpg": write_jpeg_with_thumb(p("letterbox.jpg"), big, letterboxed(big, 160, 120)),
            "plain.jpg": write_jpeg(p("plain.jpg"), big, exif=False),
            "o3.jpg": write_jpeg(p("o3.jpg"), pattern(480, 320), orientation=3),
            "small.jpg": write_jpeg(p("small.jpg"), pattern(90, 120), exif=False),
            "pic.png": write_png(p("pic.png"), pattern(300, 450)),
            "pic.tif": write_tiff(p("pic.tif"), pattern(300, 450)),
            "thumb.heic": write_heic(p("thumb.heic"), pattern(600, 800), thumbnail=256),
            "plain.heic": write_heic(p("plain.heic"), pattern(600, 800)),
        }
        return files

    def test_thumb_matches_read_image_for_every_source(self):  # PL11 / PLP8 judgement
        for name, path in self.sources().items():
            t = self.f.thumbnail(path)
            img = decode_bgr(t.jpeg)
            self.assertEqual((img.shape[1], img.shape[0]), (t.width, t.height), name)
            full_w, full_h = read_image(path).shape[1], read_image(path).shape[0]
            if max(full_w, full_h) >= 256:
                self.assertEqual(max(t.width, t.height), 256, name)
            else:
                self.assertEqual((t.width, t.height), (full_w, full_h), name)       # never upscaled
            self.assertAlmostEqual(t.width / t.height, full_w / full_h, delta=0.02, msg=name)
            ref = reference_thumb(path, (t.width, t.height))
            self.assertLessEqual(mean_abs_diff(img, ref), THUMB_TOL, name)
            self.assertEqual(t.fingerprint, sha(path), name)
            self.assertFalse(t.edited, name)

    def test_thumb_orientation(self):  # PL11: orientation 6 (red block top-left after turning) and 3
        files = self.sources()
        def red_corner(bgr):
            """Which quadrant holds the red block: (top?, left?)."""
            h, w = bgr.shape[:2]
            redness = bgr[..., 2].astype(int) - bgr[..., 1].astype(int) - bgr[..., 0].astype(int)
            q = {(t, l): redness[(0 if t else h // 2):(h // 2 if t else h), (0 if l else w // 2):(w // 2 if l else w)].mean()
                 for t in (True, False) for l in (True, False)}
            return max(q, key=q.get)
        for name in ("o6-thumb.jpg", "o3.jpg", "plain.jpg"):
            t = self.f.thumbnail(files[name])
            img = decode_bgr(t.jpeg)
            full = (read_image(files[name]) * 255).astype(np.uint8)[..., ::-1]
            self.assertEqual((img.shape[1] > img.shape[0]), (full.shape[1] > full.shape[0]), name)
            self.assertEqual(red_corner(img), red_corner(full), name)          # the same display orientation
        sensor = cv2.imdecode(np.frombuffer(open(files["o6-thumb.jpg"], "rb").read(), np.uint8),
                              cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        self.assertNotEqual(red_corner(sensor), red_corner(decode_bgr(self.f.thumbnail(files["o6-thumb.jpg"]).jpeg)))

    def test_thumb_rejects_letterboxed_exif(self):  # PL11
        files = self.sources()
        t = self.f.thumbnail(files["letterbox.jpg"])
        self.assertEqual((t.width, t.height), (256, 171))                       # 3:2, not the thumbnail's 4:3
        img = decode_bgr(t.jpeg)
        self.assertGreater(img[:4].mean(), 40)                                  # no black bars at the top
        self.assertGreater(img[-4:].mean(), 40)
        self.assertLessEqual(mean_abs_diff(img, reference_thumb(files["letterbox.jpg"], (256, 171))), THUMB_TOL)

    def test_thumb_uses_embedded_when_it_fits(self):  # PL11 (1): a good IFD1 thumbnail is what we return
        big = pattern(600, 900)
        other = np.zeros((200, 300, 3), np.uint8)
        other[:] = (20, 200, 20)                                                # a green thumbnail, unlike the photo
        path = write_jpeg_with_thumb(os.path.join(self.photos, "green.jpg"), big, other)
        img = decode_bgr(self.f.thumbnail(path).jpeg)
        self.assertEqual((img.shape[1], img.shape[0]), (256, 171))
        self.assertGreater(img[..., 1].mean(), 150)                              # green: the embedded one was used
        self.assertLess(img[..., 2].mean(), 60)
        tiny = np.zeros((80, 120, 3), np.uint8)
        tiny[:] = (20, 200, 20)
        path = write_jpeg_with_thumb(os.path.join(self.photos, "tiny.jpg"), big, tiny)   # long edge 120 < 160: rejected
        img = decode_bgr(self.f.thumbnail(path).jpeg)
        self.assertLessEqual(mean_abs_diff(img, reference_thumb(path, (256, 171))), THUMB_TOL)

    def test_thumbnail_failures(self):  # PL11 sentence
        broken = os.path.join(self.photos, "broken.jpg")
        with open(broken, "wb") as f:
            f.write(b"\xff\xd8not a jpeg")
        kind, msg = self.err(self.f.thumbnail, broken)
        self.assertEqual(kind, "invalid")
        self.assertTrue(msg.startswith(THUMB_FAILED.format(file_name="broken.jpg", reason="")), msg)
        self.assertNotIn("\n", msg)
        self.assertEqual(self.err(self.f.thumbnail, ""), ("invalid", "path is required"))
        half = os.path.join(self.photos, "half.heic")
        with open(half, "wb") as f:
            f.write(b"\0" * 100)
        kind, msg = self.err(self.f.thumbnail, half)
        self.assertEqual(kind, "invalid")
        self.assertTrue(msg.startswith(THUMB_FAILED.format(file_name="half.heic", reason="")), msg)
        self.f.folder_thumbnails(self.photos)
        self.assertTrue(self.lib.wait_thumbnails(30))                           # failures never hang the queue

    def test_background_failures_are_logged_to_stderr(self):  # PLP13 (seal F7)
        import io
        from darkroom_app.safe_write import SafeWriteRefused
        self.sources()
        err = io.StringIO()
        with mock.patch.object(safe_write, "create_new", side_effect=SafeWriteRefused("refused: nope")), \
                mock.patch("sys.stderr", err):
            self.f.folder_thumbnails(self.photos)
            self.assertTrue(self.lib.wait_thumbnails(60))
        lines = [ln for ln in err.getvalue().splitlines() if ln]
        self.assertTrue(lines)
        self.assertTrue(all(ln.startswith("[darkroom-photo-library] background thumbnail of ") and
                            ln.endswith(" failed: SafeWriteRefused: refused: nope") for ln in lines), lines)
        self.assertEqual([f for _, _, fs in os.walk(self.data) for f in fs], [])   # no thumbnail, no index
        with self.assertRaises(SafeWriteRefused):            # a direct request still raises it (G8)
            with mock.patch.object(safe_write, "create_new", side_effect=SafeWriteRefused("refused: nope")):
                self.f.thumbnail(self.sources()["plain.jpg"])
        err = io.StringIO()
        real = safe_write.replace_into

        def no_index(tmp, dest, root, **kw):
            if os.sep + "index" + os.sep in dest:
                raise OSError("index disk full")
            return real(tmp, dest, root, **kw)
        with mock.patch.object(safe_write, "replace_into", no_index), mock.patch("sys.stderr", err):
            self.f.thumbnail(self.sources()["plain.jpg"])
            self.assertTrue(self.lib.wait_thumbnails(60))
        self.assertIn("[darkroom-photo-library] index not written: " + CANNOT_WRITE.format(data_dir=self.data,
                                                                                           reason="index disk full"),
                      err.getvalue())

    def test_thumbs_not_on_gpu_executor(self):  # PL12
        self.sources()
        self.f.folder_thumbnails(self.photos)
        self.assertTrue(self.lib.wait_thumbnails(60))
        self.assertIsNone(self.f._photos.engine_ref.peek())                     # the Engine was never built
        items = self.f.folder_thumbnails(self.photos)["items"]
        self.assertTrue(all(i["cached"] and i["fingerprint"] for i in items), items)
        names = {t.name for t in threading.enumerate() if t.name.startswith("darkroom-")}
        self.assertTrue(names and all(n.startswith("darkroom-thumb-") for n in names), names)
        self.assertEqual(pl.THUMB_WORKERS, max(1, min(4, os.cpu_count() // 2)))

    def test_folder_thumbnails_listing(self):  # PL13
        files = self.sources()
        with open(os.path.join(self.photos, "notes.txt"), "w") as f:
            f.write("x")
        self.assertEqual(self.err(self.f.folder_thumbnails, ""), ("invalid", "path is required"))
        self.assertEqual(self.err(self.f.folder_thumbnails, None), ("invalid", "path is required"))
        gone = os.path.join(self.tmp, "gone")
        self.assertEqual(self.err(self.f.folder_thumbnails, gone), ("not_found", FOLDER_NOT_FOUND.format(folder=gone)))
        self.assertEqual(self.err(self.f.folder_thumbnails, self.photos, -1), ("invalid", "offset must be an integer >= 0"))
        self.assertEqual(self.err(self.f.folder_thumbnails, self.photos, 0, 0), ("invalid", "limit must be an integer in 1..200"))
        self.assertEqual(self.err(self.f.folder_thumbnails, self.photos, "1"), ("invalid", "offset must be an integer >= 0"))
        r = self.f.folder_thumbnails(f'"{self.photos}"')
        self.assertEqual(list(r), ["folder", "items", "total", "next_offset"])
        self.assertEqual(r["folder"], self.photos)
        want = sorted(files, key=lambda n: (n.casefold(), n))
        self.assertEqual([i["name"] for i in r["items"]], want)                 # the folder_listing rule, no .txt
        self.assertEqual([list(i) for i in r["items"]][0], ["name", "path", "fingerprint", "edited", "cached"])
        self.assertEqual([i["path"] for i in r["items"]], [files[n] for n in want])
        for i in r["items"]:
            self.assertEqual((i["fingerprint"], i["edited"], i["cached"]), (None, None, False))   # no index yet
        self.assertEqual((r["total"], r["next_offset"]), (len(files), None))
        page = self.f.folder_thumbnails(self.photos, 2, 3)
        self.assertEqual(([i["name"] for i in page["items"]], page["next_offset"]), (want[2:5], 5))
        self.assertEqual(self.f.folder_thumbnails(self.photos, 7, 3)["next_offset"], None)
        self.assertTrue(self.lib.wait_thumbnails(60))
        self.f.set_edit(files["plain.jpg"], "p-expo")
        r = self.f.folder_thumbnails(self.photos)
        for i in r["items"]:
            self.assertEqual(i["fingerprint"], sha(i["path"]))
            self.assertEqual(i["cached"], True)
            self.assertEqual(i["edited"], i["name"] == "plain.jpg")
        write_photo(files["plain.jpg"], 400, 300, seed=11)                      # changed: the index entry is stale
        i = next(x for x in self.f.folder_thumbnails(self.photos)["items"] if x["name"] == "plain.jpg")
        self.assertEqual((i["fingerprint"], i["edited"], i["cached"]), (None, None, False))
        self.assertTrue(self.lib.wait_thumbnails(60))
        self.assertTrue(self.f.thumbnail(files["plain.jpg"]).edited is False)

    def test_warm_grid_opens_no_photo(self):  # PL16 (b) / PLP8: a fresh service, everything cached
        from darkroom_app.composition import build_facade
        files = self.sources()
        self.f.folder_thumbnails(self.photos)
        self.assertTrue(self.lib.wait_thumbnails(60))
        self.f.set_edit(files["pic.png"], "p-expo")
        self.assertTrue(self.lib.wait_thumbnails(5))
        g = build_facade(self.presets, data_dir=self.data)                       # like a new process
        self.addCleanup(g._photo_library.wait_thumbnails, 60)
        photos = os.path.normcase(self.photos) + os.sep
        shas = {p: sha(p) for p in files.values()}
        opened = []
        real_open = builtins.open

        def spy(file, *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.normcase(os.fsdecode(file)).startswith(photos):
                opened.append(os.fsdecode(file))
            return real_open(file, *a, **k)
        with mock.patch("builtins.open", spy):
            r = g.folder_thumbnails(self.photos)
            self.assertTrue(all(i["cached"] and i["fingerprint"] == shas[i["path"]] for i in r["items"]))
            self.assertEqual([i["edited"] for i in r["items"]], [i["name"] == "pic.png" for i in r["items"]])
            for i in r["items"]:
                t = g.thumbnail(i["path"])
                self.assertEqual((t.fingerprint, t.edited), (i["fingerprint"], i["edited"]))
                self.assertEqual(max(t.width, t.height), 256 if i["name"] != "small.jpg" else 120)
        self.assertEqual(opened, [])

    def test_index_file(self):  # PLP8
        files = self.sources()
        self.f.folder_thumbnails(self.photos)
        self.assertTrue(self.lib.wait_thumbnails(60))
        real = os.path.realpath(self.photos)
        key = hashlib.sha256(os.path.normcase(real).encode("utf-8")).hexdigest()[:16]
        p = os.path.join(self.data, "index", key + ".json")
        self.assertTrue(os.path.isfile(p), os.listdir(os.path.join(self.data, "index")))
        obj = json.loads(open(p, "rb").read().decode("utf-8"))
        self.assertEqual((obj["schema"], obj["folder"], sorted(obj["files"])), ("darkroom-thumb-index/1", real, sorted(files)))
        for n, e in obj["files"].items():
            st = os.stat(files[n])
            self.assertEqual(e, {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "fingerprint": sha(files[n])})
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [key + ".json"])   # no tmp left
        with open(p, "wb") as f:
            f.write(b"garbage")
        from darkroom_app.composition import build_facade
        g = build_facade(self.presets, data_dir=self.data)
        self.addCleanup(g._photo_library.wait_thumbnails, 60)
        i = g.folder_thumbnails(self.photos)["items"][0]
        self.assertEqual((i["fingerprint"], i["cached"]), (None, False))            # a bad index is no index
        self.assertTrue(g._photo_library.wait_thumbnails(60))
        self.assertEqual(g.folder_thumbnails(self.photos)["items"][0]["cached"], True)

    def test_direct_request_jumps_the_queue_and_stale_folders_are_dropped(self):  # PL12
        p = lambda n: os.path.join(self.photos, n)
        for i in range(12):
            write_jpeg(p(f"f{i:02d}.jpg"), pattern(300, 400, seed=i), exif=False)
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        for i in range(12):
            write_jpeg(os.path.join(other, f"g{i:02d}.jpg"), pattern(300, 400, seed=20 + i), exif=False)
        order = []
        real = pl.make_thumbnail

        def slow(data, ext):
            import time
            time.sleep(0.05)
            return real(data, ext)
        with mock.patch.object(pl, "make_thumbnail", slow):
            with mock.patch.object(self.lib._queue, "work", side_effect=lambda path: (order.append(path),
                                                                                   self.lib._generate(path))[1]):
                self.f.folder_thumbnails(self.photos)
                self.f.folder_thumbnails(other)                                 # the first folder keeps its jobs
                t = self.f.thumbnail(p("f11.jpg"))                              # jumps ahead of the background work
                self.assertEqual(t.fingerprint, sha(p("f11.jpg")))
                pos = [os.path.basename(x) for x in order].index("f11.jpg")
                self.assertLess(pos, 12 + pl.THUMB_WORKERS, order)
                self.f.folder_thumbnails(self.photos)                           # a new generation of the same folder
                self.assertTrue(self.lib.wait_thumbnails(120))
        names = [os.path.basename(x) for x in order]
        self.assertEqual(sorted(set(names)), sorted(os.listdir(self.photos) + os.listdir(other)))
        self.assertLessEqual(len(names), 24 + pl.THUMB_WORKERS)                 # stale jobs were dropped, not redone
        # a direct request that jumped a background job still counts that job as done: both indexes are written
        self.assertEqual(len(os.listdir(os.path.join(self.data, "index"))), 2)
        self.assertTrue(all(i["cached"] for i in self.f.folder_thumbnails(self.photos)["items"]))


# ---------------------------------------------------------------- HTTP (PL6, PL13, PLP2)
class TestPhotoLibraryHttp(AioHTTPTestCase):
    async def get_client(self, server):
        from aiohttp.test_utils import TestClient
        return TestClient(server, headers=_util.HTTP_HEADERS)     # PLP11

    async def get_application(self):
        from darkroom_app.server import make_app
        from test_layering import _NoEngine
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "lib", "xmp")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.data = os.path.join(self.tmp, "data")
        app = make_app(self.presets, engine=_NoEngine(), data_dir=self.data)
        from darkroom_app.server import FACADE
        self.addCleanup(app[FACADE]._photo_library.wait_thumbnails, 60)
        return app

    async def test_routes(self):
        a = write_photo(os.path.join(self.photos, "a.jpg"), 400, 300)
        b = write_photo(os.path.join(self.photos, "b.jpg"), 400, 300, seed=1)
        r = await self.client.get("/api/edit", params={"path": a})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["edit"], None)
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "strength": 120,
                                                     "overrides": {"Exposure2012": 0.1}})
        self.assertEqual(r.status, 200)
        edit = (await r.json())["edit"]
        self.assertEqual((edit["strength"], edit["overrides"]), (120, {"Exposure2012": 0.1}))
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "strength": 250})
        self.assertEqual((r.status, await r.json()), (400, {"error": "strength must be within 0..200, got 250"}))
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "nope"})
        self.assertEqual((r.status, await r.json()), (404, {"error": "unknown or unsupported preset nope"}))
        r = await self.client.post("/api/edit/paste", json={"targets": [b, "x.jpg"], "source": a})
        self.assertEqual(r.status, 200)
        res = await r.json()
        self.assertEqual(list(res), ["results"])
        self.assertEqual([x["ok"] for x in res["results"]], [True, False])
        r = await self.client.post("/api/edit/paste", json={"targets": [b]})
        self.assertEqual((r.status, await r.json()), (400, {"error": SOURCE_OR_EDIT}))
        r = await self.client.get("/api/folder/thumbnails", params={"folder": self.photos, "offset": "1", "limit": "1"})
        self.assertEqual(r.status, 200)
        listing = await r.json()
        self.assertEqual(([i["name"] for i in listing["items"]], listing["total"]), (["b.jpg"], 2))
        r = await self.client.get("/api/folder/thumbnails", params={"folder": self.photos, "limit": "x"})
        self.assertEqual((r.status, await r.json()), (400, {"error": "limit must be an integer in 1..200"}))
        r = await self.client.get("/api/folder/thumbnails", params={"folder": os.path.join(self.tmp, "no")})
        self.assertEqual(r.status, 404)
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/jpeg")
        self.assertEqual(r.headers["X-Fingerprint"], sha(a))
        self.assertEqual(r.headers["X-Edited"], "1")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        img = decode_bgr(await r.read())
        self.assertEqual((img.shape[1], img.shape[0]), (256, 192))
        r = await self.client.get("/api/thumbnail", params={"path": os.path.join(self.photos, "gone.jpg")})
        self.assertEqual(r.status, 404)
        fp = sha(a)
        p = os.path.join(self.data, "edits", fp[:2], fp + ".json")
        with open(p, "wb") as f:
            f.write(json.dumps({"schema": "darkroom-edit/7", "fingerprint": fp}).encode())
        r = await self.client.get("/api/edit", params={"path": a})
        self.assertEqual((r.status, await r.json()), (409, {"error": SCHEMA_CONFLICT.format(schema="darkroom-edit/7", file_name="a.jpg")}))
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(r.headers["X-Edited"], "1")                           # exists: edited (content not read)
        with open(p, "wb") as f:
            f.write(b"{")
        r = await self.client.delete("/api/edit", params={"path": a})
        self.assertEqual((r.status, await r.json()), (503, {"error": EDIT_CORRUPT.format(edit_file=p)}))
        os.remove(p)
        r = await self.client.delete("/api/edit", params={"path": a})
        self.assertEqual((r.status, (await r.json())["edit"]), (200, None))
        r = await self.client.post("/api/edit/save-preset", json={"path": b, "name": "網頁"})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["id"], "user:網頁")
        r = await self.client.post("/api/edit/save-preset", json={"path": a, "name": "網頁"})
        self.assertEqual((r.status, await r.json()), (404, {"error": NO_EDIT.format(file_name="a.jpg")}))

    async def test_lenient_int_unicode_digits(self):  # CONTRACT-s1-experience S15: isdecimal, never a 500
        from darkroom_app.server import _lenient_int
        self.assertEqual([_lenient_int(t) for t in ("12", "²", "①", "x", "", "٣")], [12, "²", "①", "x", "", 3])
        write_photo(os.path.join(self.photos, "a.jpg"), 400, 300)
        for odd in ("²", "①", "³", "⑦"):        # digits int() refuses: the service's 400 sentence
            r = await self.client.get("/api/folder/thumbnails", params={"folder": self.photos, "offset": odd})
            self.assertEqual((r.status, await r.json()), (400, {"error": "offset must be an integer >= 0"}), odd)
            r = await self.client.get("/api/folder/thumbnails", params={"folder": self.photos, "limit": odd})
            self.assertEqual((r.status, await r.json()), (400, {"error": "limit must be an integer in 1..200"}), odd)
        r = await self.client.get("/api/folder/thumbnails", params={"folder": self.photos, "offset": "٠"})   # decimal: int
        self.assertEqual(r.status, 200)

    async def test_thumbnail_edit_header(self):  # CONTRACT-s1-experience S8: X-Edit on GET /api/thumbnail
        from urllib.parse import unquote
        from darkroom_app.server import FACADE
        a = write_photo(os.path.join(self.photos, "a.jpg"), 400, 300)
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual((r.status, r.headers["X-Edited"]), (200, "0"))
        self.assertNotIn("X-Edit", r.headers)                                   # no edit: no header at all
        await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "strength": 130})
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(r.headers["X-Edited"], "1")
        self.assertRegex(r.headers["X-Edit"], r"^[A-Za-z0-9%._~!'()*-]+$")     # ASCII only (percent-encoded)
        from darkroom_app.server import x_edit                                 # seal F6: encodeURIComponent exactly
        self.assertEqual(x_edit({"preset": "A (2)!*'", "strength": 100, "status": "current"}),
                         "%7B%22preset%22%3A%22A%20(2)!*'%22%2C%22strength%22%3A100%2C%22status%22%3A%22current%22%7D")
        self.assertEqual(json.loads(unquote(r.headers["X-Edit"])),
                         {"preset": "曝光一", "strength": 130, "status": "current"})   # Chinese name survives
        _xmpgen.write(self.presets, "p-expo.xmp", _xmpgen.xmp_text({"Exposure2012": "+2.50"}, name="變了", group="風景 - 海邊"))
        self.app[FACADE].rebuild_library()
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(json.loads(unquote(r.headers["X-Edit"]))["status"], "changed")
        os.remove(os.path.join(self.presets, "p-expo.xmp"))
        self.app[FACADE].rebuild_library()
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(json.loads(unquote(r.headers["X-Edit"]))["status"], "missing")
        await self.client.put("/api/edit", json={"path": a, "preset_id": None, "overrides": {"Exposure2012": 0.3}})
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(json.loads(unquote(r.headers["X-Edit"])), {"preset": None, "strength": 100, "status": None})
        # the CLI / MCP thumbnail result shape is unchanged (the summary is an HTTP header only)
        res = self.app[FACADE].thumbnail(a)
        self.assertEqual(res.edit, {"preset": None, "strength": 100, "status": None})
        from darkroom_app.mcp_server.tools import Tools
        out = Tools(lambda: self.app[FACADE]).call("darkroom_thumbnail", {"path": a})
        self.assertEqual(set(out["structuredContent"]), {"fingerprint", "edited", "width", "height"})

    async def test_autosave_uses_remembered_snapshot(self):  # CONTRACT-s1-experience S2: the page's save path
        """What the page sends when it remembers a snapshot: paste with that snapshot, then GET. After the
        preset file changed in the library, and after switching to another preset and back, the old snapshot is
        what lands on disk (never the library's current file); a preset gone from the library still saves."""
        from darkroom_app.server import FACADE
        lib = self.app[FACADE]._photo_library
        a = write_photo(os.path.join(self.photos, "a.jpg"), 400, 300)
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "strength": 100})
        first = await r.json()
        snap = first["edit"]["preset"]
        old = snap["params"]
        _xmpgen.write(self.presets, "p-expo.xmp", _xmpgen.xmp_text({"Exposure2012": "+2.50"}, name="變了", group="風景 - 海邊"))
        self.app[FACADE].rebuild_library()
        self.assertNotEqual(lib.library.get("p-expo").to_dict(), old)
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-strong", "strength": 100})   # switched away
        self.assertEqual((await r.json())["edit"]["preset"]["id"], "p-strong")
        # back to p-expo the page's way: paste with the remembered snapshot, strength changed meanwhile
        edit = {"schema": "darkroom-edit/1", "fingerprint": first["fingerprint"], "preset": snap, "strength": 130,
                "overrides": {"Contrast2012": 5}}
        r = await self.client.post("/api/edit/paste", json={"targets": [a], "edit": edit})
        self.assertEqual((r.status, [x["ok"] for x in (await r.json())["results"]]), (200, [True]))
        r = await self.client.get("/api/edit", params={"path": a})
        got = await r.json()
        self.assertEqual((got["edit"]["preset"]["params"], got["edit"]["strength"], got["edit"]["overrides"],
                          got["preset_status"]), (old, 130, {"Contrast2012": 5}, "changed"))
        # the preset gone from the library: the same path still saves (PUT would be not_found)
        os.remove(os.path.join(self.presets, "p-expo.xmp"))
        self.app[FACADE].rebuild_library()
        r = await self.client.post("/api/edit/paste", json={"targets": [a], "edit": dict(edit, strength=140)})
        self.assertEqual([x["ok"] for x in (await r.json())["results"]], [True])
        r = await self.client.get("/api/edit", params={"path": a})
        got = await r.json()
        self.assertEqual((got["edit"]["strength"], got["preset_status"]), (140, "missing"))


if __name__ == "__main__":
    unittest.main()
