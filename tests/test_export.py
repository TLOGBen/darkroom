"""CONTRACT-export X1-X15, XP1-XP15: full-resolution export through the facade (service, HTTP shape, files).

Every photo is made by the test (JPEG with EXIF and orientation, P3 HEIC, PNG without EXIF); outputs go to fixture
roots only. Facade-level tests use the real Engine (CUDA when present, CPU otherwise).
"""
import hashlib
import io
import os
import struct
import sys
import threading
import time
import unittest
from unittest import mock

import cv2
import numpy as np
from aiohttp.test_utils import AioHTTPTestCase

import _heicgen
import _iccgen
import _util
from test_app_server import make_presets, snapshot

EXPORT_DIR = "darkroom 匯出"                                                         # verbatim (X8)
OOM = "顯示卡記憶體不足，可能有其他程式正在使用 GPU；關掉它們後再匯出一次"               # verbatim (X11)
SRGB8_MAX = 2 / 255                                                                  # H4 8-bit tolerance (X6)
MIB = 1 << 20


# ---------------------------------------------------------------- photos made by the test
def pattern(h, w, seed=0):
    """Smooth asymmetric RGB uint8 picture with a red block in the top-left corner (orientation is visible)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([xx / max(1, w - 1), yy / max(1, h - 1), 0.5 + 0.3 * np.sin(xx / 9.0) * np.cos(yy / 7.0)], -1)
    img = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    img[: max(1, h // 4), : max(1, w // 3)] = (230, 20, 20)
    return img


def exif_app1(orientation=1, dims=None, thumbnail=False, endian=">", maker_note=None):
    """APP1 Exif segment: IFD0 (Make, Model, Orientation, Software), Exif IFD (with an Interop IFD), GPS IFD;
    optionally an IFD1 and a maker note. endian ">" (PIL's default, MM) or "<" (II, as most cameras write)."""
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational as R
    ex = Image.Exif()
    ex.endian = endian
    ex[0x010F] = "DarkCam"
    ex[0x0110] = "DR-1"
    ex[0x0112] = orientation
    ex[0x0131] = "fw 1.0"
    sub = {0x9003: "2024:05:06 07:08:09", 0x829A: R(1, 125), 0x829D: R(28, 10), 0x8827: 400,
           0x920A: R(35, 1), 0xA434: "DR 35mm F2.8"}
    if dims:
        sub[0xA002], sub[0xA003] = dims
    sub[0xA005] = {1: "R98", 2: b"0100"}                         # Interop IFD (XP20: kept)
    if maker_note is not None:
        sub[0x927C] = maker_note
    ex[0x8769] = sub
    ex[0x8825] = {1: "N", 2: (R(25, 1), R(2, 1), R(30, 1)), 3: "E", 4: (R(121, 1), R(33, 1), R(15, 1)),
                  6: R(12, 1)}
    body = ex.tobytes()
    if thumbnail:
        body = body[:6] + add_ifd1(body[6:])
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def add_ifd1(t):
    """Append an IFD1 (JPEG thumbnail) to TIFF-structured bytes `t` and link it from IFD0."""
    e = "<" if t[:2] == b"II" else ">"
    (ifd0,) = struct.unpack_from(e + "I", t, 4)
    (n,) = struct.unpack_from(e + "H", t, ifd0)
    at = len(t) + (len(t) % 2)
    thumb = cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))[1].tobytes()
    ifd1 = struct.pack(e + "H", 3)
    data_at = at + 2 + 36 + 4
    ifd1 += struct.pack(e + "HHIHH", 259, 3, 1, 6, 0)
    ifd1 += struct.pack(e + "HHII", 513, 4, 1, data_at)
    ifd1 += struct.pack(e + "HHII", 514, 4, 1, len(thumb))
    ifd1 += struct.pack(e + "I", 0)
    t = bytearray(t + b"\0" * (at - len(t)) + ifd1 + thumb)
    struct.pack_into(e + "I", t, ifd0 + 2 + 12 * n, at)
    return bytes(t)


def write_jpeg(path, rgb, orientation=1, exif=True, thumbnail=False, quality=95, endian=">", maker_note=None):
    ok, enc = cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    data = enc.tobytes()
    if exif:
        h, w = rgb.shape[:2]
        data = data[:2] + exif_app1(orientation, (w, h), thumbnail, endian, maker_note) + data[2:]
    with open(path, "wb") as f:
        f.write(data)
    return path


def write_png(path, rgb):
    ok, enc = cv2.imencode(".png", rgb[..., ::-1])
    assert ok
    with open(path, "wb") as f:
        f.write(enc.tobytes())
    return path


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------- independent readers for the outputs
def jpeg_segments(data):
    """[(marker, body)] up to the first SOS."""
    out, pos = [], 2
    assert data[:2] == b"\xff\xd8"
    while True:
        m = data[pos + 1]
        (n,) = struct.unpack_from(">H", data, pos + 2)
        out.append((m, data[pos + 4:pos + 2 + n]))
        if m == 0xDA:
            return out
        pos += 2 + n


def ifd_tags(t, off):
    """(tags in this IFD in file order, next-IFD offset) of TIFF-structured bytes."""
    e = "<" if t[:2] == b"II" else ">"
    (n,) = struct.unpack_from(e + "H", t, off)
    tags = [struct.unpack_from(e + "H", t, off + 2 + 12 * i)[0] for i in range(n)]
    (nxt,) = struct.unpack_from(e + "I", t, off + 2 + 12 * n)
    return tags, nxt


def tiff_value(t, off, tag):
    e = "<" if t[:2] == b"II" else ">"
    (n,) = struct.unpack_from(e + "H", t, off)
    for i in range(n):
        tg, typ, count, val = struct.unpack_from(e + "HHII", t, off + 2 + 12 * i)
        if tg == tag:
            return val
    return None


def check_exif_structure(test, t):
    """No tag twice in any IFD, no IFD1, Orientation 1 (X7)."""
    e = "<" if t[:2] == b"II" else ">"
    (ifd0,) = struct.unpack_from(e + "I", t, 4)
    tags, nxt = ifd_tags(t, ifd0)
    test.assertEqual(nxt, 0, "IFD1 must not be kept")
    test.assertEqual(len(tags), len(set(tags)))
    test.assertEqual(tags, sorted(tags))
    for sub in (34665, 34853):
        at = tiff_value(t, ifd0, sub)
        if at:
            st, snxt = ifd_tags(t, at)
            test.assertEqual(len(st), len(set(st)), sub)
    test.assertIn(274, tags)


def icc_is_srgb(test, icc):
    from darkroom import _icc
    conv = _icc.from_icc(icc)
    test.assertIsNotNone(conv, "matrix / curve profile expected")
    vals = np.array([0.0, 0.5, 1.0], np.float32)
    grid = np.stack(np.meshgrid(vals, vals, vals, indexing="ij"), -1).reshape(1, -1, 3)
    test.assertLessEqual(float(np.abs(conv(grid) - grid).max()), 1e-3)


class ExportCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from darkroom_app import engine as engine_mod
        cls.eng = engine_mod.Engine()

    @classmethod
    def tearDownClass(cls):
        cls.eng.shutdown()

    def setUp(self):
        from darkroom_app.composition import build_facade
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.f = build_facade(self.presets, engine=self.eng)

    def p(self, *names):
        return os.path.join(self.photos, *names)

    def export(self, paths, format="jpeg", **kw):
        items = [{"path": p, **kw.pop("item", {})} for p in paths]
        return self.f.export(items, format, kw.pop("quality", None), kw.pop("dest_dir", None))["results"]


class TestRequest(ExportCase):  # X1 / XP2: request-level checks, nothing written
    def test_export_error_texts(self):
        from darkroom_app.errors import DarkroomError
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        before = snapshot(self.photos, self.presets)
        cases = [(([], "jpeg"), "沒有要匯出的照片"),
                 ((None, "jpeg"), "沒有要匯出的照片"),
                 (([{"path": photo}], "png"), "不支援的匯出格式：png（可用 jpeg、tiff）"),
                 (([{"path": photo}], "jpeg", 0), "JPEG 品質要在 1～100 之間：0"),
                 (([{"path": photo}], "jpeg", 101), "JPEG 品質要在 1～100 之間：101"),
                 (([{"path": photo}], "jpeg", True), "JPEG 品質要在 1～100 之間：True"),
                 (([{"path": photo}], "jpeg", 92.0), "JPEG 品質要在 1～100 之間：92.0"),
                 (([{"path": photo}], "jpeg", None, "relative"), "找不到匯出資料夾：relative"),
                 (([{"path": photo}], "jpeg", None, self.p("missing")), f"找不到匯出資料夾：{self.p('missing')}")]
        for args, sentence in cases:
            with self.subTest(args=args[1:]):
                with self.assertRaises(DarkroomError) as cm:
                    self.f.export(*args)
                self.assertEqual((cm.exception.kind, cm.exception.message), ("invalid", sentence))
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual(os.listdir(self.photos), ["a.jpg"])

    def test_item_failures_do_not_stop_others(self):  # X1, X12
        good = write_jpeg(self.p("good.jpg"), pattern(20, 30))
        with open(self.p("broken.jpg"), "wb") as f:
            f.write(b"not an image")
        items = [{"path": good, "preset_id": "nope"}, {"path": self.p("missing.jpg")}, {"path": self.p("broken.jpg")},
                 {"path": good, "strength": 250}, {"path": good, "overrides": {"Bogus": 1}}, {"image_id": "nope"},
                 {"path": ""}, "x", {"path": good, "presetid": "p-expo"}, {"path": good}]
        res = self.f.export(items, "jpeg")["results"]
        self.assertEqual(len(res), len(items))
        want = [("good.jpg", "unknown or unsupported preset nope"),
                ("missing.jpg", f"photo not found: {self.p('missing.jpg')}"),
                ("broken.jpg", f"cannot decode image {os.path.abspath(self.p('broken.jpg'))}"),
                ("good.jpg", "strength must be within 0..200, got 250"),
                ("good.jpg", "unknown slider key 'Bogus'"),
                ("nope", "unknown image_id"),
                ("", "path is required"),
                ("", "each item must be an object {image_id | path, preset_id, strength, overrides}"),
                ("", "unknown item key 'presetid' (allowed: image_id, path, preset_id, strength, overrides)")]
        for r, (source, reason) in zip(res, want):
            self.assertEqual(r, {"ok": False, "source": source, "error": f"匯出失敗：{source}：{reason}"})
        self.assertEqual(res[-1], {"ok": True, "source": "good.jpg",
                                   "output": os.path.join(self.photos, EXPORT_DIR, "good.jpg")})
        self.assertEqual(sorted(os.listdir(self.p(EXPORT_DIR))), ["good.jpg"])


class TestFiles(ExportCase):
    def test_export_never_touches_source(self):  # X10
        photo = write_jpeg(self.p("a.jpg"), pattern(30, 40))
        st = os.stat(photo)
        before = sha(photo)
        self.export([photo])
        self.export([photo], "tiff")
        self.assertEqual(sha(photo), before)
        self.assertEqual(os.stat(photo).st_mtime_ns, st.st_mtime_ns)

    def test_export_never_overwrites(self):  # X9, X10, XP2
        photo = write_jpeg(self.p("IMG_1.jpg"), pattern(30, 40))
        out = self.p(EXPORT_DIR)
        os.makedirs(out)
        for name, body in (("IMG_1.jpg", b"earlier export"), ("img_1 (2).JPG", b"another")):
            with open(os.path.join(out, name), "wb") as f:
                f.write(body)
        before = snapshot(out)
        res = self.export([photo, photo])
        self.assertEqual([os.path.basename(r["output"]) for r in res], ["IMG_1 (3).jpg", "IMG_1 (4).jpg"])
        after = snapshot(out)
        for k, v in before.items():
            self.assertEqual(after[k], v)                  # content and mtime of the earlier files unchanged
        self.assertEqual(sorted(os.listdir(out)), ["IMG_1 (3).jpg", "IMG_1 (4).jpg", "IMG_1.jpg", "img_1 (2).JPG"])

    def test_same_stem_in_one_list(self):  # X9 + seal F2: names follow the item order, whatever finishes first
        from darkroom_app import encoding
        a = write_jpeg(self.p("IMG_1.jpg"), pattern(20, 30))
        b = _heicgen.write_heic(self.p("IMG_1.heic"), pattern(20, 30).astype(np.float32) / 255)
        real = encoding.jpeg_bytes
        calls = []

        def first_is_slow(*args):
            calls.append(1)
            if len(calls) % 2 == 1:
                time.sleep(0.3)                   # the first item finishes encoding after the second
            return real(*args)
        for round_ in range(3):
            dest = os.path.join(self.tmp, f"d{round_}")
            os.makedirs(dest)
            with mock.patch.object(encoding, "jpeg_bytes", first_is_slow):
                res = self.export([b, a], dest_dir=dest)
            self.assertEqual([os.path.basename(r["output"]) for r in res], ["IMG_1.jpg", "IMG_1 (2).jpg"], round_)
            self.assertEqual([r["source"] for r in res], ["IMG_1.heic", "IMG_1.jpg"])
            with open(res[0]["output"], "rb") as f:          # and the first name holds the first item's pixels
                first = f.read()
            self.assertEqual(sha(res[0]["output"]), hashlib.sha256(first).hexdigest())

    def test_export_concurrent_names(self):  # X9: two exports at the same time never share a name
        photo = write_jpeg(self.p("c.jpg"), pattern(40, 60))
        dest = os.path.join(self.tmp, "dest")
        os.makedirs(dest)
        outs, errors = [], []
        barrier = threading.Barrier(3)

        def run():
            try:
                barrier.wait()
                outs.extend(r["output"] for r in self.export([photo, photo], dest_dir=dest))
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)
        threads = [threading.Thread(target=run) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(errors, [])
        self.assertEqual(len(outs), 6)
        self.assertEqual(len(set(os.path.normcase(o) for o in outs)), 6)
        self.assertEqual(sorted(os.listdir(dest)), sorted(["c.jpg"] + [f"c ({n}).jpg" for n in range(2, 7)]))

    def test_dest_is_photo_folder_with_same_name(self):  # XP13
        photo = write_jpeg(self.p("same.jpg"), pattern(20, 30))
        before = sha(photo)
        res = self.export([photo], dest_dir=self.photos)
        self.assertEqual(res, [{"ok": True, "source": "same.jpg", "output": self.p("same (2).jpg")}])
        self.assertEqual(sha(photo), before)

    def test_export_folder_rules(self):  # X8
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        self.assertEqual(self.export([photo])[0]["output"], self.p(EXPORT_DIR, "a.jpg"))
        again = self.export([self.p(EXPORT_DIR, "a.jpg")])[0]["output"]          # already in "darkroom 匯出"
        self.assertEqual(again, self.p(EXPORT_DIR, "a (2).jpg"))
        self.assertFalse(os.path.exists(self.p(EXPORT_DIR, EXPORT_DIR)))
        dest = os.path.join(self.tmp, "chosen")
        os.makedirs(dest)
        self.assertEqual(self.export([photo], "tiff", dest_dir=dest)[0]["output"], os.path.join(dest, "a.tif"))
        self.assertEqual(os.listdir(dest), ["a.tif"])

    def test_unexpected_read_error_fails_one_item(self):  # X1 / X12 + seal F1 (cv2.error on a damaged TIFF)
        from darkroom_app.services import export as export_mod
        photos = [write_jpeg(self.p(f"IMG_{i}.jpg"), pattern(20, 30, i)) for i in (1, 2, 3)]
        real = export_mod.read_image

        def read(path):
            if path.endswith("IMG_2.jpg"):
                raise cv2.error("OpenCV(5.0.0) loadsave.cpp:77: error: (-215:Assertion failed)\nsize <= limit")
            return real(path)
        dest = os.path.join(self.tmp, "dest")
        os.makedirs(dest)
        with mock.patch.object(export_mod, "read_image", read):
            res = self.export(photos, dest_dir=dest)
        self.assertEqual([r["ok"] for r in res], [True, False, True])
        self.assertEqual(res[1]["error"], "匯出失敗：IMG_2.jpg：OpenCV(5.0.0) loadsave.cpp:77: error: "
                                          "(-215:Assertion failed) size <= limit")
        self.assertEqual(sorted(os.listdir(dest)), ["IMG_1.jpg", "IMG_3.jpg"])

    def test_export_failure_leaves_no_file(self):  # X10, X11, X12
        from darkroom_app import safe_write
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        dest = os.path.join(self.tmp, "dest")
        os.makedirs(dest)
        with mock.patch.object(safe_write.os, "write", side_effect=OSError(28, "No space left on device")):
            res = self.export([photo], dest_dir=dest)
        self.assertEqual(res, [{"ok": False, "source": "a.jpg",
                                "error": f"匯出失敗：a.jpg：無法寫入匯出資料夾：{dest}"}])
        with mock.patch.object(self.eng, "render_full", side_effect=RuntimeError("boom\nsecond line")):
            res = self.export([photo], "tiff", dest_dir=dest)
        self.assertEqual(res[0]["error"], "匯出失敗：a.jpg：渲染失敗：boom second line")
        self.assertEqual(os.listdir(dest), [])

    def test_export_name_exhausted(self):  # XP2
        from darkroom_app.services import export as export_mod
        self.assertEqual(export_mod.N_MAX, 9999)
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        dest = os.path.join(self.tmp, "dest")
        os.makedirs(dest)
        for name in ("a.jpg", "a (2).jpg", "a (3).jpg"):
            with open(os.path.join(dest, name), "wb") as f:
                f.write(b"x")
        with mock.patch.object(export_mod, "N_MAX", 3):
            res = self.export([photo], dest_dir=dest)
        self.assertEqual(res[0]["error"], "匯出失敗：a.jpg：a 的匯出檔名已用到 (3)，請清理匯出資料夾後再試")
        self.assertEqual(len(os.listdir(dest)), 3)

    def test_export_refuses_preset_folder(self):  # XP12: the preset folder in use, whatever config says
        from darkroom_app import safe_write
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        before = snapshot(self.presets)
        names = sorted(os.listdir(self.presets))
        with self.assertRaises(safe_write.SafeWriteRefused) as cm:
            self.export([photo], dest_dir=self.presets)
        self.assertEqual(str(cm.exception), f"refused: {os.path.join(self.presets, 'a.jpg')} is inside the preset folder")
        self.assertEqual(snapshot(self.presets), before)
        self.assertEqual(sorted(os.listdir(self.presets)), names)


class TestContent(ExportCase):
    def tiff(self, path):
        import tifffile
        return tifffile.imread(path)

    def test_export_embeds_srgb_and_jpeg_tables(self):  # X4, X5
        from PIL import Image
        photo = write_jpeg(self.p("a.jpg"), pattern(48, 64))
        for q in (None, 75):
            out = self.export([photo], quality=q)[0]["output"]
            im = Image.open(out)
            self.assertEqual((im.format, im.mode, im.size), ("JPEG", "RGB", (64, 48)))
            icc_is_srgb(self, im.info["icc_profile"])
            ref = io.BytesIO()
            Image.fromarray(np.asarray(im)).save(ref, "JPEG", quality=q or 92)
            self.assertEqual(im.quantization, Image.open(ref).quantization, q)
        out = self.export([photo], "tiff")[0]["output"]
        im = Image.open(out)
        icc_is_srgb(self, im.info["icc_profile"])

    def test_export_tiff_16bit_readers_agree(self):  # X3, X4
        import tifffile
        from darkroom import read_image, render
        from darkroom_app import preview as semantics
        photo = write_jpeg(self.p("t.jpg"), pattern(36, 52))
        out = self.export([photo], "tiff", item={"preset_id": "p-mixed", "strength": 70,
                                                 "overrides": {"Exposure2012": 0.3}})[0]["output"]
        a = tifffile.imread(out)
        with tifffile.TiffFile(out) as tf:
            page = tf.pages[0]
            self.assertEqual((page.bitspersample, page.samplesperpixel, page.dtype), (16, 3, np.dtype("uint16")))
            self.assertEqual(page.photometric, 2)
            self.assertEqual(page.tags["ExtraSamples"] if "ExtraSamples" in page.tags else None, None)
        b = cv2.imdecode(np.fromfile(out, np.uint8), cv2.IMREAD_UNCHANGED)[..., ::-1]
        np.testing.assert_array_equal(a, b)
        from PIL import Image
        im = Image.open(out)
        self.assertEqual(im.size, (52, 36))
        c = np.asarray(im)       # XP24: PIL 12.3.0 opens 16-bit RGB TIFF as 8-bit RGB = the high bytes
        self.assertEqual((im.mode, c.dtype), ("RGB", np.dtype("uint8")))
        np.testing.assert_array_equal((a >> 8).astype(np.uint8), c)
        lib = self.f._presets.library
        final = semantics.effective_params(lib.get("p-mixed"), 0.7, {"Exposure2012": 0.3})
        want = np.floor(np.clip(np.asarray(render(read_image(photo), final)), 0, 1) * 65535 + 0.5)
        self.assertLessEqual(float(np.abs(a.astype(np.float64) - want).max()), 1.0)        # <= 1/65535

    def test_export_orientation_jpeg(self):  # X6
        from PIL import Image
        src = pattern(40, 64)
        base = Image.fromarray(src)
        for tag, op in ((3, Image.Transpose.ROTATE_180), (6, Image.Transpose.ROTATE_270),
                        (8, Image.Transpose.ROTATE_90)):
            with self.subTest(orientation=tag):
                photo = write_jpeg(self.p(f"o{tag}.jpg"), src, orientation=tag, quality=100)
                from darkroom import read_image
                plain = np.round(read_image(write_jpeg(self.p(f"p{tag}.jpg"), src, exif=False, quality=100)) * 255)
                want = np.asarray(Image.fromarray(plain.astype(np.uint8)).transpose(op)) / 255.0
                out = self.export([photo], "tiff")[0]["output"]
                got = self.tiff(out) / 65535.0
                self.assertEqual(got.shape, want.shape)
                self.assertLessEqual(float(np.abs(got - want).max()), SRGB8_MAX)
                jpg = Image.open(self.export([photo])[0]["output"])
                self.assertEqual(jpg.size, (want.shape[1], want.shape[0]))
                self.assertEqual(jpg.getexif()[0x0112], 1)
                self.assertEqual(Image.open(out).getexif()[0x0112], 1)
        del base

    def test_open_and_preview_are_upright(self):  # X6: /api/open sizes and the preview are turned too
        photo = write_jpeg(self.p("v.jpg"), pattern(40, 64), orientation=6)
        info = self.f.open_photo(photo)
        self.assertEqual((info["width"], info["height"]), (40, 64))
        res = self.f.preview(info["image_id"])
        self.assertEqual((res.width, res.height), (40, 64))

    def test_export_orientation_heic_once(self):  # X6: libheif already turned it
        from darkroom import read_image
        img = pattern(40, 64).astype(np.float32) / 255
        heic = _heicgen.write_heic(self.p("h6.heic"), img, orientation=6)
        want = read_image(heic)
        self.assertEqual(want.shape[:2], (64, 40))
        got = self.tiff(self.export([heic], "tiff")[0]["output"]) / 65535.0
        self.assertEqual(got.shape, want.shape)
        self.assertLessEqual(float(np.abs(got - want).max()), 1 / 65535 + 1e-7)

    def test_export_p3_heic_not_double_converted(self):  # X5
        from PIL import Image
        from darkroom import read_image
        img = pattern(32, 48).astype(np.float32) / 255
        heic = _heicgen.write_heic(self.p("p3.heic"), img, icc=_iccgen.display_p3())
        for fmt in ("jpeg", "tiff"):
            out = self.export([heic], fmt)[0]["output"]
            icc = Image.open(out).info["icc_profile"]
            self.assertNotEqual(icc, _iccgen.display_p3())
            icc_is_srgb(self, icc)
        got = self.tiff(out) / 65535.0
        self.assertLessEqual(float(np.abs(got - read_image(heic)).max()), 1 / 65535 + 1e-7)  # pixels: sRGB as read

    def test_export_exif_kept(self):  # X7
        from PIL import Image
        photo = write_jpeg(self.p("e.jpg"), pattern(30, 50), orientation=6, thumbnail=True)
        src = Image.open(photo).getexif()
        from PIL import ExifTags
        self.assertTrue(src.get_ifd(ExifTags.IFD.IFD1))              # the source really has a thumbnail IFD
        for fmt in ("jpeg", "tiff"):
            with self.subTest(fmt=fmt):
                out = self.export([photo], fmt)[0]["output"]
                im = Image.open(out)
                ex = im.getexif()
                self.assertEqual(ex[0x0112], 1)
                for tag in (0x010F, 0x0110):
                    self.assertEqual(ex[tag], src[tag])
                se, oe = src.get_ifd(0x8769), ex.get_ifd(0x8769)
                for tag in (0x9003, 0x829A, 0x829D, 0x8827, 0x920A, 0xA434):     # DateTimeOriginal ... LensModel
                    self.assertEqual(oe[tag], se[tag], hex(tag))
                self.assertEqual((oe[0xA002], oe[0xA003]), im.size)               # PixelX/YDimension = output
                self.assertEqual(ex.get_ifd(0x8825), src.get_ifd(0x8825))
                self.assertEqual(dict(ex.get_ifd(ExifTags.IFD.IFD1)), {})              # no IFD1
                if fmt == "jpeg":
                    with open(out, "rb") as f:
                        segs = jpeg_segments(f.read())
                    app1 = [b for m, b in segs if m == 0xE1 and b[:6] == b"Exif\0\0"]
                    self.assertEqual(len(app1), 1)
                    check_exif_structure(self, app1[0][6:])
                    self.assertEqual([m for m, _ in segs][:3], [0xE0, 0xE1, 0xE2])
                else:
                    with open(out, "rb") as f:
                        check_exif_structure(self, f.read(1 << 16))

    def test_export_exif_little_endian_interop_and_maker_note(self):  # X7 / XP20 + seal F6
        from PIL import Image
        for endian in ("<", ">"):
            for note in (b"N" * 200,):
                with self.subTest(endian=endian, note=len(note)):
                    photo = write_jpeg(self.p(f"e{len(note)}{endian == '<'}.jpg"), pattern(30, 50), orientation=8,
                                       endian=endian, maker_note=note)
                    src = Image.open(photo).getexif()
                    for fmt in ("jpeg", "tiff"):
                        out = self.export([photo], fmt)[0]["output"]
                        im = Image.open(out)
                        ex = im.getexif()
                        self.assertEqual((ex[0x0112], ex[0x010F], ex[0x0110]), (1, "DarkCam", "DR-1"), fmt)
                        self.assertEqual(im.size, (30, 50), fmt)                  # orientation 8 turned
                        oe = ex.get_ifd(0x8769)
                        self.assertEqual(oe[0x9003], src.get_ifd(0x8769)[0x9003], fmt)
                        self.assertEqual(ex.get_ifd(0x8825), src.get_ifd(0x8825), fmt)
                        self.assertEqual(ex.get_ifd(0xA005), {1: "R98", 2: b"0100"}, fmt)     # Interop kept
                        self.assertEqual(oe[0x927C], note, fmt)                          # maker note kept
        # XP20: EXIF over the 64 KB APP1 limit (a TIFF source can carry it) -> the maker note goes, the rest stays
        from PIL import Image as PILImage
        from darkroom_app import encoding
        for endian in ("<", ">"):
            ex = PILImage.Exif()
            ex.endian = endian
            ex[0x010F], ex[0x0112] = "DarkCam", 6
            ex[0x8769] = {0x9003: "2024:05:06 07:08:09", 0x927C: b"M" * 70000}
            parsed = encoding.parse_tiff_exif(ex.tobytes()[6:])
            data = encoding.jpeg_bytes(np.zeros((8, 12, 3), np.uint8), 90, parsed, encoding.srgb_icc())
            out = PILImage.open(io.BytesIO(data)).getexif()
            self.assertEqual((out[0x010F], out[0x0112]), ("DarkCam", 1), endian)
            self.assertEqual(out.get_ifd(0x8769)[0x9003], "2024:05:06 07:08:09", endian)
            self.assertNotIn(0x927C, out.get_ifd(0x8769), endian)

    def test_png_without_exif(self):  # X7: no EXIF in, none out, no error
        from PIL import Image
        png = write_png(self.p("n.png"), pattern(20, 30))
        out = self.export([png])[0]["output"]
        im = Image.open(out)
        self.assertNotIn("exif", im.info)
        with open(out, "rb") as f:
            self.assertFalse([m for m, b in jpeg_segments(f.read()) if m == 0xE1])
        tif = self.export([png], "tiff")[0]["output"]
        import tifffile
        with tifffile.TiffFile(tif) as tf:
            tags = {t.code for t in tf.pages[0].tags.values()}
        self.assertFalse(tags & {34665, 34853, 271, 272})

    def test_export_params_equal_preview(self):  # X2
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        info = self.f.open_photo(photo)
        seen = {}
        real_preview, real_full = self.eng.preview, self.eng.render_full

        def spy_preview(image_id, params, max_pixels=None):
            seen["preview"] = params.to_json()
            return real_preview(image_id, params, max_pixels)

        def spy_full(image, params, bits):
            seen.setdefault("export", []).append(params.to_json())
            return real_full(image, params, bits)
        args = {"preset_id": "p-mixed", "strength": 150, "overrides": {"Exposure2012": 0.4, "Contrast2012": -20}}
        with mock.patch.object(self.eng, "preview", spy_preview), mock.patch.object(self.eng, "render_full", spy_full):
            self.f.preview(info["image_id"], args["preset_id"], args["strength"], args["overrides"])
            res = self.f.export([{"image_id": info["image_id"], **args}, {"path": photo, **args}], "jpeg")["results"]
        self.assertTrue(all(r["ok"] for r in res))
        self.assertEqual(seen["export"], [seen["preview"], seen["preview"]])


class TestGpu(ExportCase):
    def test_export_oom_message_and_server_alive(self):  # X11
        import torch
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        calls = []

        def oom(*a):
            calls.append(1)
            raise torch.cuda.OutOfMemoryError("CUDA out of memory. Tried to allocate 9 GiB")
        with mock.patch.object(self.eng, "render_full", oom), mock.patch("torch.cuda.synchronize") as sync:
            res = self.export([photo, photo])
        self.assertEqual(len(calls), 2)                                  # no retry, no CPU fallback
        self.assertEqual([r["error"] for r in res], [f"匯出失敗：a.jpg：{OOM}"] * 2)
        sync.assert_not_called()
        self.assertFalse(os.path.exists(self.p(EXPORT_DIR, "a.jpg")))
        info = self.f.open_photo(photo)                                 # the editor still works
        self.assertEqual(self.f.preview(info["image_id"]).width, 30)

    def test_export_one_gpu_job_in_flight(self):  # XP7
        from darkroom_app import encoding
        from darkroom_app.services import export as export_mod
        photos = [write_jpeg(self.p(f"s{i}.jpg"), pattern(30, 40, i)) for i in range(7)]
        lock = threading.Lock()
        state = {"gpu": 0, "gpu_max": 0, "held": 0, "held_max": 0, "threads": set(), "order": []}
        real_full, real_read, real_jpeg = self.eng.render_full, export_mod.read_image, encoding.jpeg_bytes

        def full(image, params, bits):
            with lock:
                state["gpu"] += 1
                state["gpu_max"] = max(state["gpu_max"], state["gpu"])
                state["threads"].add(threading.current_thread().name.split("_")[0])
            try:
                time.sleep(0.02)
                return real_full(image, params, bits)
            finally:
                with lock:
                    state["gpu"] -= 1

        def read(path):
            with lock:
                state["held"] += 1
                state["held_max"] = max(state["held_max"], state["held"])
            return real_read(path)

        def slow_jpeg(*a):
            time.sleep(0.15)                       # slow writers: reads would run ahead if nothing held them back
            return real_jpeg(*a)

        real_create = export_mod.safe_write.create_new

        def create(path, root, data, **kw):
            try:
                return real_create(path, root, data, **kw)
            finally:
                with lock:
                    state["held"] -= 1
        with mock.patch.object(self.eng, "render_full", full), mock.patch.object(export_mod, "read_image", read), \
                mock.patch.object(encoding, "jpeg_bytes", slow_jpeg), \
                mock.patch.object(export_mod.safe_write, "create_new", create):
            res = self.export(photos)
        self.assertEqual([r["source"] for r in res], [f"s{i}.jpg" for i in range(7)])     # same order
        self.assertTrue(all(r["ok"] for r in res))
        self.assertEqual(state["gpu_max"], 1)
        self.assertEqual(state["threads"], {"darkroom-gpu"})
        self.assertLessEqual(state["held_max"], 3)
        self.assertGreaterEqual(state["held_max"], 2)                                     # the stages overlap

    def test_export_releases_memory(self):  # XP7
        import torch
        if not torch.cuda.is_available():
            self.skipTest("needs CUDA")
        photo = write_jpeg(self.p("big.jpg"), pattern(1500, 2000))
        before = torch.cuda.memory_reserved()
        res = self.export([photo, photo])
        self.assertTrue(all(r["ok"] for r in res))
        self.assertLessEqual(torch.cuda.memory_reserved(), before + 256 * MIB)


class TestThroughput(unittest.TestCase):  # XP8 (ADR-0003): the numbers of tools/bench_export.py, inside a root
    def test_export_batch_throughput(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("bench_export", os.path.join(_util.REPO, "tools",
                                                                                   "bench_export.py"))
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
        self.assertEqual((bench.N_PHOTOS, bench.WIDTH, bench.HEIGHT, bench.QUALITY, bench.PER_PHOTO_LIMIT_S,
                          bench.OVERLAP_LIMIT), (20, 6000, 4000, 92, 0.8, 0.7))          # verbatim (XP8)
        skip, msg = bench.gpu_check()
        enc = sys.stdout.encoding or "utf-8"
        print(msg.encode(enc, "replace").decode(enc))
        if skip:
            self.skipTest(msg)              # R1: only while the GPU is really busy, or without CUDA (reason shown)
        enc = sys.stdout.encoding or "utf-8"
        out = bench.measure(_util.tmpdir(self), log=lambda s: print(s.encode(enc, "replace").decode(enc)))
        self.assertLessEqual(out["per_photo"], 0.8, out)
        self.assertLessEqual(out["overlap"], 0.7, out)


class TestHttpExport(AioHTTPTestCase):  # X1 shape over HTTP, XP5 writes only in dest_dir
    async def get_application(self):
        from darkroom_app.server import make_app
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        return make_app(self.presets)

    async def test_api_export_shape(self):  # over HTTP only the default folder (XP16)
        photo = write_jpeg(os.path.join(self.photos, "a.jpg"), pattern(20, 30))
        dest = os.path.join(self.photos, EXPORT_DIR)
        before = snapshot(self.photos, self.presets)
        r = await self.client.post("/api/export", json={"items": [{"path": photo, "preset_id": "p-expo",
                                                                    "strength": 50},
                                                                   {"path": photo, "preset_id": "nope"}],
                                                         "format": "jpeg"})
        self.assertEqual(r.status, 200)
        body = await r.json()
        self.assertEqual(body, {"results": [{"ok": True, "source": "a.jpg", "output": os.path.join(dest, "a.jpg")},
                                            {"ok": False, "source": "a.jpg",
                                             "error": "匯出失敗：a.jpg：unknown or unsupported preset nope"}]})
        after = snapshot(self.photos, self.presets)
        self.assertEqual({k: v for k, v in after.items() if not k.startswith(dest + os.sep)}, before)
        self.assertEqual(os.listdir(dest), ["a.jpg"])
        for body, err in (({"items": [], "format": "jpeg"}, "沒有要匯出的照片"),
                          ({"items": [{"path": photo}], "format": "jpeg", "quality": True},
                           "JPEG 品質要在 1～100 之間：True"),
                          ({"items": [{"path": photo}], "format": "jpeg", "dest_dir": self.tmp},
                           "dest_dir is not accepted over HTTP (use the CLI or MCP)")):
            r = await self.client.post("/api/export", json=body)
            self.assertEqual((r.status, await r.json()), (400, {"error": err}))
        r = await self.client.post("/api/open", json={"path": photo})
        self.assertEqual(r.status, 200)
        self.assertEqual(os.listdir(dest), ["a.jpg"])


if __name__ == "__main__":
    unittest.main()
