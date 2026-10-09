"""CONTRACT-s2-export-detect E1-E21, E33: export settings, formats, resize, metadata, output sharpening, export
presets, the saved edit, presets as .xmp, data_dir / config, the preset library in a photo folder.

Every photo, preset folder, library root, data_dir and export folder lives in a fixture root (G7: the real preset
library and %LOCALAPPDATA%/darkroom are never touched). Facade-level tests use the real Engine.
"""
import base64
import hashlib
import io
import json
import math
import msvcrt
import os
import shutil
import struct
import subprocess
import sys
import unittest
import zlib
from unittest import mock

import cv2
import numpy as np

import _util
from test_app_server import make_presets, snapshot
from test_export import EXPORT_DIR, icc_is_srgb, pattern, write_jpeg, write_png

CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases", "s2_resize_cases.json")
DEFAULTS = {"format": "jpeg", "bit_depth": 8, "quality": 92, "max_kb": None, "resize": None, "metadata": "all",
            "remove_gps": False, "sharpen": None}                       # verbatim (E1 常數「預設值」)
LR_ATTRS = ['crs:UUID="{uuid}"', 'crs:SupportsAmount2="True"', 'crs:SupportsAmount="True"',
            'crs:SupportsColor="True"', 'crs:SupportsMonochrome="True"', 'crs:SupportsHighDynamicRange="True"',
            'crs:SupportsNormalDynamicRange="True"', 'crs:SupportsSceneReferred="True"',
            'crs:SupportsOutputReferred="True"', 'crs:RequiresRGBTables="False"', 'crs:Version="15.4"']   # verbatim
SHARPEN = {"screen": {"low": (0.5, 0.35), "standard": (0.6, 0.55), "high": (0.7, 0.80)},
           "glossy": {"low": (0.7, 0.45), "standard": (0.8, 0.70), "high": (1.0, 1.00)},
           "matte": {"low": (0.8, 0.60), "standard": (1.0, 0.90), "high": (1.2, 1.25)}}      # verbatim (E10)
COPYRIGHT = "(c) 2026 Darkroom Tester"


def exif_with_copyright(orientation=1, dims=None, copyright=True, gps=True):
    """APP1 Exif: IFD0 (Make, Model, Orientation, Copyright), Exif IFD (Interop, MakerNote), GPS IFD."""
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational as R
    ex = Image.Exif()
    ex[0x010F], ex[0x0110], ex[0x0112] = "DarkCam", "DR-1", orientation
    if copyright:
        ex[0x8298] = COPYRIGHT
    sub = {0x9003: "2024:05:06 07:08:09", 0x8827: 400, 0x927C: b"maker-note-bytes", 0xA005: {1: "R98"}}
    if dims:
        sub[0xA002], sub[0xA003] = dims
    ex[0x8769] = sub
    if gps:
        ex[0x8825] = {1: "N", 2: (R(25, 1), R(2, 1), R(30, 1)), 3: "E", 4: (R(121, 1), R(33, 1), R(15, 1))}
    body = ex.tobytes()
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def write_jpeg_cr(path, rgb, **kw):
    ok, enc = cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    data = enc.tobytes()
    h, w = rgb.shape[:2]
    data = data[:2] + exif_with_copyright(dims=(w, h), **kw) + data[2:]
    with open(path, "wb") as f:
        f.write(data)
    return path


def noisy(h, w, seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(pattern(h, w).astype(np.int16) + rng.integers(-60, 60, (h, w, 3)), 0, 255).astype(np.uint8)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------- independent container readers
def png_chunks(data):
    """[(type, body)] of PNG bytes; every CRC checked."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    out, pos = [], 8
    while pos < len(data):
        (n,) = struct.unpack_from(">I", data, pos)
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        (crc,) = struct.unpack_from(">I", data, pos + 8 + n)
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        out.append((kind, body))
        pos += 12 + n
    return out


def riff_chunks(data):
    """(declared RIFF size, [(fourcc, body)]) of WebP bytes; odd chunks are padded."""
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    (size,) = struct.unpack_from("<I", data, 4)
    out, pos = [], 12
    while pos < len(data):
        kind = data[pos:pos + 4]
        (n,) = struct.unpack_from("<I", data, pos + 4)
        out.append((kind, data[pos + 8:pos + 8 + n]))
        pos += 8 + n + (n % 2)
    assert pos == len(data)
    return size, out


def jpeg_app(data, marker, prefix):
    pos = 2
    while pos + 4 <= len(data):
        m = data[pos + 1]
        (n,) = struct.unpack_from(">H", data, pos + 2)
        body = data[pos + 4:pos + 2 + n]
        if m == marker and body.startswith(prefix):
            return body[len(prefix):]
        if m == 0xDA:
            return None
        pos += 2 + n
    return None


def tiff_ifds(t):
    """{"ifd0", "exif", "gps", "interop"} -> {tag: raw value bytes} of TIFF-structured bytes (independent reader)."""
    e = "<" if t[:2] == b"II" else ">"
    size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

    def ifd(off):
        (n,) = struct.unpack_from(e + "H", t, off)
        out = {}
        for i in range(n):
            tag, typ, count, raw = struct.unpack_from(e + "HHI4s", t, off + 2 + 12 * i)
            nb = size.get(typ, 1) * count
            if nb <= 4:
                out[tag] = raw[:nb]
            else:
                (at,) = struct.unpack(e + "I", raw)
                out[tag] = t[at:at + nb]
        return out
    (first,) = struct.unpack_from(e + "I", t, 4)
    out = {"ifd0": ifd(first)}
    for name, tag, parent in (("exif", 34665, "ifd0"), ("gps", 34853, "ifd0"), ("interop", 40965, "exif")):
        if parent in out and tag in out[parent]:
            (at,) = struct.unpack(e + "I", out[parent][tag])
            out[name] = ifd(at)
    return out


def exif_of(path):
    """The TIFF-structured EXIF of an exported file (None when it has none), by its own container."""
    data = read_bytes(path)
    ext = os.path.splitext(path)[1]
    if ext == ".jpg":
        return jpeg_app(data, 0xE1, b"Exif\0\0")
    if ext == ".png":
        return next((b for k, b in png_chunks(data) if k == b"eXIf"), None)
    if ext == ".webp":
        return next((b for k, b in riff_chunks(data)[1] if k == b"EXIF"), None)
    return data                                     # TIFF: the file itself


TIFF_STRUCTURE = {256, 257, 258, 259, 262, 273, 277, 278, 279, 284, 339, 34675}


# ---------------------------------------------------------------- base
class S2Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from darkroom_app import engine as engine_mod
        cls.eng = engine_mod.Engine()

    @classmethod
    def tearDownClass(cls):
        cls.eng.shutdown()

    def setUp(self):
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "presets")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.data = os.path.join(self.tmp, "data")
        self.dest = os.path.join(self.tmp, "dest")
        os.makedirs(self.dest)
        self.f = self.facade()

    def facade(self, **kw):
        from darkroom_app.composition import build_facade
        kw.setdefault("data_dir", self.data)
        return build_facade(self.presets, engine=self.eng, **kw)

    def p(self, *names):
        return os.path.join(self.photos, *names)

    def export(self, paths, f=None, item=None, **kw):
        kw.setdefault("dest_dir", self.dest)
        return (f or self.f).export([{"path": p, **(item or {})} for p in paths], **kw)["results"]

    def one(self, path, **kw):
        res = self.export([path], **kw)
        self.assertTrue(res[0]["ok"], res)
        return res[0]

    def err(self, fn, *a, **kw):
        from darkroom_app.errors import DarkroomError
        with self.assertRaises(DarkroomError) as cm:
            fn(*a, **kw)
        return cm.exception.kind, cm.exception.message

    def render(self, photo, bits, params=None):
        from darkroom import read_image
        from darkroom_app import preview as semantics
        params = params if params is not None else semantics.effective_params(None, 1.0, {})
        return self.eng.render_full(read_image(photo), params, bits)


# ---------------------------------------------------------------- E1, E2
class TestSettings(S2Case):
    def test_normalize_settings_defaults_and_precedence(self):  # E1
        from darkroom_app.services.export import SETTING_KEYS, normalize_settings
        self.assertEqual(SETTING_KEYS, ("format", "bit_depth", "quality", "max_kb", "resize", "metadata",
                                        "remove_gps", "sharpen"))
        self.assertEqual(normalize_settings({}), DEFAULTS)
        self.assertEqual(list(normalize_settings({})), list(SETTING_KEYS))
        self.assertEqual(normalize_settings({"format": "tiff"}), dict(DEFAULTS, format="tiff", bit_depth=16,
                                                                     quality=None))
        self.assertEqual(normalize_settings({"format": "png"}), dict(DEFAULTS, format="png", quality=None))
        self.assertEqual(normalize_settings({"format": "webp"}), dict(DEFAULTS, format="webp"))
        self.assertEqual(normalize_settings({"format": "png", "quality": 0}),
                         dict(DEFAULTS, format="png", quality=None))          # X13: ignored, never judged
        preset = normalize_settings({"format": "png", "bit_depth": 16, "resize": {"mode": "long_edge", "value": 1000},
                                     "metadata": "copyright", "sharpen": {"target": "matte", "amount": "low"}})
        self.assertEqual(normalize_settings({}, preset), preset)
        got = normalize_settings({"format": "jpeg", "metadata": "none"}, preset)   # explicit wins, depth follows
        self.assertEqual(got, {"format": "jpeg", "bit_depth": 8, "quality": 92, "max_kb": None,
                               "resize": {"mode": "long_edge", "value": 1000}, "metadata": "none",
                               "remove_gps": False, "sharpen": {"target": "matte", "amount": "low"}})
        jp = normalize_settings({"quality": 70, "max_kb": 500, "remove_gps": True})
        self.assertEqual(normalize_settings({"format": "webp"}, jp)["quality"], 92)    # not the jpeg preset's
        self.assertEqual(normalize_settings({"format": "webp"}, jp)["max_kb"], None)
        self.assertEqual(normalize_settings({}, jp), jp)
        self.assertIs(normalize_settings({}, jp)["remove_gps"], True)
        self.assertEqual(normalize_settings({"remove_gps": False}, jp)["remove_gps"], False)   # False is "given"

    def test_export_settings_errors(self):  # E2: every constant sentence, nothing written, nothing read
        photo = write_jpeg(self.p("a.jpg"), pattern(20, 30))
        before = snapshot(self.photos, self.dest, self.presets)
        items = [{"path": photo}]
        cases = [
            ({"format": "bmp"}, "不支援的匯出格式：bmp（可用 jpeg、png、tiff、webp）"),
            ({"format": 5}, "不支援的匯出格式：5（可用 jpeg、png、tiff、webp）"),
            ({"format": "jpeg", "quality": 0}, "JPEG 品質要在 1～100 之間：0"),
            ({"format": "webp", "quality": 101}, "WebP 品質要在 1～100 之間：101"),
            ({"format": "webp", "quality": True}, "WebP 品質要在 1～100 之間：True"),
            ({"bit_depth": 12}, "位元深度要是 8 或 16：12"),
            ({"bit_depth": "8"}, "位元深度要是 8 或 16：8"),
            ({"bit_depth": True}, "位元深度要是 8 或 16：True"),
            ({"format": "jpeg", "bit_depth": 16}, "JPEG 只能輸出 8-bit：16"),
            ({"format": "webp", "bit_depth": 16}, "WebP 只能輸出 8-bit：16"),
            ({"format": "png", "max_kb": 100}, "檔案大小上限只適用於 JPEG"),
            ({"format": "tiff", "max_kb": 100}, "檔案大小上限只適用於 JPEG"),
            ({"max_kb": 9}, "檔案大小上限要是 10～1048576 之間的整數（KB）：9"),
            ({"max_kb": 1048577}, "檔案大小上限要是 10～1048576 之間的整數（KB）：1048577"),
            ({"max_kb": 10.5}, "檔案大小上限要是 10～1048576 之間的整數（KB）：10.5"),
            ({"max_kb": True}, "檔案大小上限要是 10～1048576 之間的整數（KB）：True"),
            ({"resize": "x"}, '尺寸設定要是 {"mode": …, "value": …}：x'),
            ({"resize": {"mode": "long_edge"}}, '尺寸設定要是 {"mode": …, "value": …}：' + str({"mode": "long_edge"})),
            ({"resize": {"mode": "diag", "value": 5}},
             "不支援的尺寸方式：diag（可用 long_edge、short_edge、width、height、megapixels、percent）"),
            ({"resize": {"mode": "long_edge", "value": 0}}, "long_edge 的值要是 1～65535 的整數：0"),
            ({"resize": {"mode": "width", "value": 65536}}, "width 的值要是 1～65535 的整數：65536"),
            ({"resize": {"mode": "height", "value": 2048.0}}, "height 的值要是 1～65535 的整數：2048.0"),
            ({"resize": {"mode": "short_edge", "value": True}}, "short_edge 的值要是 1～65535 的整數：True"),
            ({"resize": {"mode": "megapixels", "value": 0}}, "megapixels 的值要是大於 0、不超過 1000 的數：0"),
            ({"resize": {"mode": "megapixels", "value": 1000.5}}, "megapixels 的值要是大於 0、不超過 1000 的數：1000.5"),
            ({"resize": {"mode": "megapixels", "value": "2"}}, "megapixels 的值要是大於 0、不超過 1000 的數：2"),
            ({"resize": {"mode": "percent", "value": 150}}, "percent 的值要是大於 0、不超過 100 的數（不會放大）：150"),
            ({"resize": {"mode": "percent", "value": float("nan")}},
             "percent 的值要是大於 0、不超過 100 的數（不會放大）：nan"),
            ({"metadata": "gps"}, "不支援的中繼資料選項：gps（可用 all、copyright、none）"),
            ({"remove_gps": "yes"}, "remove_gps 必須是 true 或 false"),
            ({"remove_gps": 1}, "remove_gps 必須是 true 或 false"),
            ({"sharpen": "screen"}, '銳利化設定要是 {"target": …, "amount": …}：screen'),
            ({"sharpen": {"target": "tv", "amount": "low"}}, "不支援的銳利化對象：tv（可用 screen、matte、glossy）"),
            ({"sharpen": {"target": "screen", "amount": "max"}}, "不支援的銳利化強度：max（可用 low、standard、high）"),
            ({"dest_dir": "relative"}, "找不到匯出資料夾：relative"),
            # E2 order: the first bad value in the constant order wins
            ({"format": "bmp", "quality": 0, "bit_depth": 3}, "不支援的匯出格式：bmp（可用 jpeg、png、tiff、webp）"),
            ({"bit_depth": 3, "quality": 0}, "位元深度要是 8 或 16：3"),
            ({"quality": 0, "max_kb": 1}, "JPEG 品質要在 1～100 之間：0"),
            ({"max_kb": 1, "resize": "x"}, "檔案大小上限要是 10～1048576 之間的整數（KB）：1"),
            ({"resize": "x", "metadata": "x"}, '尺寸設定要是 {"mode": …, "value": …}：x'),
            ({"metadata": "x", "remove_gps": "x"}, "不支援的中繼資料選項：x（可用 all、copyright、none）"),
            ({"remove_gps": "x", "sharpen": "x"}, "remove_gps 必須是 true 或 false"),
            ({"sharpen": "x", "dest_dir": "relative"}, '銳利化設定要是 {"target": …, "amount": …}：x'),
        ]
        for kw, sentence in cases:
            with self.subTest(kw=kw):
                kw = dict(kw)
                kw.setdefault("dest_dir", self.dest)
                with mock.patch("darkroom_app.services.export.read_image") as read:
                    self.assertEqual(self.err(self.f.export, items, **kw), ("invalid", sentence))
                read.assert_not_called()
        self.assertEqual(self.err(self.f.export, [], format="bmp"), ("invalid", "沒有要匯出的照片"))   # items first
        self.assertEqual(self.err(self.f.export, items, format="bmp", export_preset="nope"),
                         ("not_found", "找不到匯出預設：nope"))                       # export_preset before format
        self.assertEqual(snapshot(self.photos, self.dest, self.presets), before)
        self.assertFalse(os.path.exists(self.p(EXPORT_DIR)))


# ---------------------------------------------------------------- E4-E7
class TestFormats(S2Case):
    def test_export_png_8_and_16(self):  # E4
        from PIL import Image
        photo = write_jpeg_cr(self.p("a.jpg"), pattern(40, 60))
        r8 = self.one(photo, format="png")
        self.assertEqual(os.path.basename(r8["output"]), "a.png")
        self.assertEqual(r8["used"], {"params_from": "original", "quality": None, "width": 60, "height": 40})
        a = cv2.imread(r8["output"], cv2.IMREAD_UNCHANGED)
        self.assertEqual((a.dtype, a.shape), (np.uint8, (40, 60, 3)))
        self.assertLessEqual(int(np.abs(a.astype(int) - self.render(photo, 8).astype(int)).max()), 1)
        r16 = self.one(photo, format="png", bit_depth=16)
        self.assertEqual(os.path.basename(r16["output"]), "a (2).png")
        b = cv2.imread(r16["output"], cv2.IMREAD_UNCHANGED)
        self.assertEqual((b.dtype, b.shape), (np.uint16, (40, 60, 3)))
        ref = self.render(photo, 16)
        self.assertLessEqual(int(np.abs(b[..., ::-1].astype(int) - ref.astype(int)).max()), 1)
        for out in (r8["output"], r16["output"]):
            with Image.open(out) as im:
                icc_is_srgb(self, im.info["icc_profile"])
                ex = im.getexif()
                self.assertEqual((ex[0x0112], ex[0x8298], ex[0x010F]), (1, COPYRIGHT, "DarkCam"))

    def test_export_png_chunks(self):  # E4
        from darkroom_app import encoding
        photo = write_jpeg_cr(self.p("a.jpg"), pattern(30, 50))
        out = self.one(photo, format="png")["output"]
        chunks = png_chunks(read_bytes(out))
        kinds = [k for k, _ in chunks]
        self.assertEqual(kinds[:3], [b"IHDR", b"iCCP", b"eXIf"])
        self.assertEqual(kinds[-1], b"IEND")
        self.assertEqual(set(kinds[3:-1]), {b"IDAT"})
        iccp = dict(chunks)[b"iCCP"]
        self.assertTrue(iccp.startswith(b"sRGB\0\0"))
        self.assertEqual(zlib.decompress(iccp[6:]), encoding.srgb_icc())
        jpeg_exif = exif_of(self.one(photo)["output"])
        self.assertEqual(tiff_ifds(dict(chunks)[b"eXIf"]), tiff_ifds(jpeg_exif))     # the same EXIF as X7
        none = self.one(photo, format="png", metadata="none")["output"]
        self.assertEqual([k for k, _ in png_chunks(read_bytes(none))][:2], [b"IHDR", b"iCCP"])
        self.assertNotIn(b"eXIf", [k for k, _ in png_chunks(read_bytes(none))])
        png_src = write_png(self.p("b.png"), pattern(10, 12))                      # a PNG source has no EXIF
        self.assertNotIn(b"eXIf", [k for k, _ in png_chunks(read_bytes(self.one(png_src, format="png")["output"]))])

    def test_export_tiff_8bit_readers_agree(self):  # E5
        import tifffile
        from PIL import Image
        photo = write_jpeg(self.p("t.jpg"), pattern(36, 52))
        res = self.one(photo, format="tiff", bit_depth=8, item={"preset_id": "p-mixed", "strength": 70})
        self.assertEqual(os.path.basename(res["output"]), "t.tif")
        self.assertEqual(res["used"], {"params_from": "request", "quality": None, "width": 52, "height": 36})
        a = tifffile.imread(res["output"])
        with Image.open(res["output"]) as im:
            b = np.asarray(im)
            icc_is_srgb(self, im.info["icc_profile"])
        c = cv2.imread(res["output"], cv2.IMREAD_UNCHANGED)[..., ::-1]
        self.assertEqual(a.dtype, np.uint8)
        self.assertTrue(np.array_equal(a, b) and np.array_equal(a, c))
        self.assertEqual(tiff_ifds(read_bytes(res["output"]))["ifd0"][258], struct.pack("<HHH", 8, 8, 8))
        from darkroom_app import preview as semantics
        params = semantics.effective_params(self.f._presets.library.get("p-mixed"), 0.7, {})
        self.assertLessEqual(int(np.abs(a.astype(int) - self.render(photo, 8, params)[..., ::-1].astype(int)).max()), 1)

    def test_export_webp_container(self):  # E6
        from PIL import Image
        photo = write_jpeg_cr(self.p("w.jpg"), pattern(30, 41))
        res = self.one(photo, format="webp", quality=80)
        self.assertEqual(os.path.basename(res["output"]), "w.webp")
        self.assertEqual(res["used"], {"params_from": "original", "quality": 80, "width": 41, "height": 30})
        data = read_bytes(res["output"])
        size, chunks = riff_chunks(data)
        self.assertEqual(size, len(data) - 8)
        self.assertEqual([k for k, _ in chunks], [b"VP8X", b"ICCP", b"VP8 ", b"EXIF"])
        vp8x = chunks[0][1]
        self.assertEqual(vp8x[0], 0x20 | 0x08)
        self.assertEqual(int.from_bytes(vp8x[4:7], "little") + 1, 41)
        self.assertEqual(int.from_bytes(vp8x[7:10], "little") + 1, 30)
        from darkroom_app import encoding
        self.assertEqual(chunks[1][1], encoding.srgb_icc())
        with Image.open(res["output"]) as im:
            self.assertEqual(im.size, (41, 30))
            icc_is_srgb(self, im.info["icc_profile"])
            self.assertEqual(im.getexif()[0x8298], COPYRIGHT)
        px = self.render(photo, 8)
        ok, ref = cv2.imencode(".webp", px, [cv2.IMWRITE_WEBP_QUALITY, 80])
        self.assertEqual(chunks[2][1], riff_chunks(ref.tobytes())[1][0][1])        # the VP8 data untouched
        self.assertTrue(np.array_equal(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR),
                                       cv2.imdecode(ref, cv2.IMREAD_COLOR)))
        bare = read_bytes(self.one(photo, format="webp", metadata="none")["output"])
        _, chunks = riff_chunks(bare)
        self.assertEqual([k for k, _ in chunks], [b"VP8X", b"ICCP", b"VP8 "])
        self.assertEqual(chunks[0][1][0], 0x20)

    def test_export_webp_too_large(self):  # E6
        photo = write_png(self.p("long.png"), pattern(2, 16384))
        res = self.export([photo], format="webp")
        self.assertEqual(res, [{"ok": False, "source": "long.png",
                                "error": "匯出失敗：long.png：WebP 最大 16383×16383 像素，這張是 16384×2；請縮小尺寸後再匯出"}])
        self.assertEqual(os.listdir(self.dest), [])
        ok = self.one(photo, format="webp", resize={"mode": "long_edge", "value": 16383})
        self.assertEqual((ok["used"]["width"], ok["used"]["height"]), (16383, 2))

    def test_export_max_kb(self):  # E7
        from PIL import Image
        from darkroom import read_image
        from darkroom_app import encoding
        photo = write_jpeg(self.p("n.jpg"), noisy(400, 600))
        px = self.render(photo, 8)
        exif = encoding.read_exif(photo)
        full = len(encoding.jpeg_bytes(px, 92, exif, encoding.srgb_icc()))
        limit_kb = (full // 1024) // 3
        calls = []
        real = encoding.jpeg_bytes
        with mock.patch.object(encoding, "jpeg_bytes", lambda *a: calls.append(a[1]) or real(*a)):
            res = self.one(photo, max_kb=limit_kb)
        self.assertLessEqual(len(calls), 8)
        q = res["used"]["quality"]
        self.assertLess(q, 92)
        size = os.path.getsize(res["output"])
        self.assertLessEqual(size, limit_kb * 1024)
        self.assertGreater(len(real(px, q + 1, exif, encoding.srgb_icc())), limit_kb * 1024)
        self.assertEqual(read_bytes(res["output"]), real(px, q, exif, encoding.srgb_icc()))
        with Image.open(res["output"]) as im:
            ref = io.BytesIO()
            Image.fromarray(np.asarray(im)).save(ref, "JPEG", quality=q)
            self.assertEqual(im.quantization, Image.open(ref).quantization)
        roomy = self.one(photo, max_kb=(full // 1024) + 10)                            # fits at 92: 92 is used
        self.assertEqual(roomy["used"]["quality"], 92)
        self.assertEqual(os.path.getsize(roomy["output"]), full)
        del read_image

    def test_export_max_kb_impossible(self):  # E7
        from darkroom_app import encoding
        photo = write_jpeg(self.p("big.jpg"), noisy(1200, 1600, 3))
        px = self.render(photo, 8)
        q1 = len(encoding.jpeg_bytes(px, 1, encoding.read_exif(photo), encoding.srgb_icc()))
        self.assertGreater(q1, 10 * 1024)
        res = self.export([photo], max_kb=10)
        self.assertEqual(res, [{"ok": False, "source": "big.jpg",
                                "error": f"匯出失敗：big.jpg：無法壓到 10 KB 以內：品質 1 也有 {math.ceil(q1 / 1024)} KB"}])
        self.assertEqual(os.listdir(self.dest), [])


# ---------------------------------------------------------------- E8-E10
class TestResizeMetadataSharpen(S2Case):
    def test_resize_shared_cases(self):  # E8: the same table drives tests/js/test_logic.cjs (L.resizeTarget)
        from darkroom_app.services.export import resize_target
        with open(CASES, encoding="utf-8") as f:
            cases = json.load(f)
        modes = {c["resize"]["mode"] for c in cases if c["resize"]}
        self.assertEqual(modes, {"long_edge", "short_edge", "width", "height", "megapixels", "percent"})
        self.assertGreaterEqual(len(cases), 15)
        for c in cases:
            with self.subTest(c["name"]):
                self.assertEqual(list(resize_target(c["width"], c["height"], c["resize"])), c["expect"])
                if c["resize"] and c["resize"]["mode"] == "megapixels":
                    w, h = c["expect"]
                    self.assertLessEqual(w * h, c["resize"]["value"] * 1e6)

    def test_export_resize_pixels(self):  # E8, D2: rendered at full resolution, then shrunk (INTER_AREA)
        from PIL import Image
        photo = write_jpeg(self.p("r.jpg"), pattern(200, 300))
        res = self.one(photo, format="png", resize={"mode": "long_edge", "value": 100})
        self.assertEqual((res["used"]["width"], res["used"]["height"]), (100, 67))
        a = cv2.imread(res["output"], cv2.IMREAD_UNCHANGED)
        ref = cv2.resize(self.render(photo, 8), (100, 67), interpolation=cv2.INTER_AREA)
        self.assertLessEqual(int(np.abs(a.astype(int) - ref.astype(int)).max()), 1)
        turned = write_jpeg(self.p("o6.jpg"), pattern(200, 300), orientation=6)        # upright 200 x 300
        res = self.one(turned, resize={"mode": "long_edge", "value": 100})
        with Image.open(res["output"]) as im:
            self.assertEqual(im.size, (67, 100))
            sub = im.getexif().get_ifd(0x8769)
            self.assertEqual((sub[0xA002], sub[0xA003]), (67, 100))                    # X7: the output size
        same = self.one(photo, format="png", resize={"mode": "percent", "value": 100})  # s = 1: no resize
        self.assertTrue(np.array_equal(cv2.imread(same["output"], cv2.IMREAD_UNCHANGED),
                                       cv2.imread(self.one(photo, format="png")["output"], cv2.IMREAD_UNCHANGED)))
        bigger = self.one(photo, resize={"mode": "width", "value": 5000})
        self.assertEqual((bigger["used"]["width"], bigger["used"]["height"]), (300, 200))

    def test_export_metadata_modes(self):  # E9: four formats x three choices + remove_gps
        photo = write_jpeg_cr(self.p("m.jpg"), pattern(24, 32))
        bare = write_jpeg_cr(self.p("bare.jpg"), pattern(24, 32), copyright=False)
        exif_ifd0 = {271, 272, 274, 33432, 34665, 34853}
        for fmt in ("jpeg", "png", "webp", "tiff"):
            with self.subTest(fmt=fmt):
                full = tiff_ifds(exif_of(self.one(photo, format=fmt)["output"]))
                extra = TIFF_STRUCTURE if fmt == "tiff" else set()
                self.assertEqual(set(full["ifd0"]), exif_ifd0 | extra)
                self.assertIn(0x927C, full["exif"])
                self.assertEqual(set(full["gps"]), {1, 2, 3, 4})
                for gps_choice in (False, True):
                    nogps = tiff_ifds(exif_of(self.one(photo, format=fmt, remove_gps=True)["output"]))
                    self.assertEqual(set(nogps["ifd0"]), (exif_ifd0 - {34853}) | extra)
                    self.assertNotIn("gps", nogps)
                    pointer = 40965                                    # the Interop offset moves with the layout
                    self.assertEqual({k: v for k, v in nogps["exif"].items() if k != pointer},
                                     {k: v for k, v in full["exif"].items() if k != pointer})
                    self.assertEqual(nogps["interop"], full["interop"])
                    cr = tiff_ifds(exif_of(self.one(photo, format=fmt, metadata="copyright",
                                                    remove_gps=gps_choice)["output"]))
                    self.assertEqual(set(cr["ifd0"]), {274, 33432} | extra)
                    self.assertEqual(cr["ifd0"][33432].rstrip(b"\0"), COPYRIGHT.encode("ascii"))
                    self.assertEqual(cr["ifd0"][274][:2], struct.pack("<H", 1))
                    self.assertEqual(set(cr) - {"ifd0"}, set())
                    none = self.one(photo, format=fmt, metadata="none", remove_gps=gps_choice)["output"]
                    t = exif_of(none)
                    if fmt == "tiff":
                        self.assertEqual(set(tiff_ifds(t)["ifd0"]), {274} | TIFF_STRUCTURE)
                    else:
                        self.assertIsNone(t)
                    no_cr = exif_of(self.one(bare, format=fmt, metadata="copyright", remove_gps=gps_choice)["output"])
                    if fmt == "tiff":
                        self.assertEqual(set(tiff_ifds(no_cr)["ifd0"]), {274} | TIFF_STRUCTURE)
                    else:
                        self.assertIsNone(no_cr)                      # no copyright in the source: no EXIF at all
        jpeg_none = read_bytes(self.one(photo, metadata="none")["output"])
        self.assertIsNone(jpeg_app(jpeg_none, 0xE1, b""))                    # no APP1 at all
        self.assertIsNotNone(jpeg_app(jpeg_none, 0xE2, b"ICC_PROFILE\0"))     # the profile is colour, always kept
        for data in (jpeg_none, read_bytes(self.one(photo, format="png", metadata="none")["output"])):
            self.assertNotIn(b"http://ns.adobe.com/xap/1.0/", data)          # never XMP
            self.assertNotIn(b"Photoshop 3.0", data)                          # never IPTC

    def _ref_sharpen(self, x, sigma, a):
        y = x[..., 0] * 0.2126 + x[..., 1] * 0.7152 + x[..., 2] * 0.0722
        r = int(math.ceil(4 * sigma))
        k = np.exp(-(np.arange(-r, r + 1) ** 2) / (2 * sigma * sigma))
        k /= k.sum()
        pad = np.pad(y, r, mode="reflect")
        rows = np.stack([np.convolve(row, k, mode="valid") for row in pad], 0)
        blur = np.stack([np.convolve(col, k, mode="valid") for col in rows.T], 0).T
        return np.clip(x + a * (y - blur)[..., None], 0, 1)

    def test_output_sharpen_formula(self):  # E10
        from darkroom_app.services.export import SHARPEN as TABLE, output_sharpen
        self.assertEqual(TABLE, SHARPEN)
        x = noisy(40, 56, 5).astype(np.float32) / 255.0
        for target, amounts in SHARPEN.items():
            for amount, (sigma, a) in amounts.items():
                with self.subTest(target=target, amount=amount):
                    got = (output_sharpen(x, target, amount) * 255 + 0.5).astype(np.uint8)
                    ref = (self._ref_sharpen(x.astype(np.float64), sigma, a) * 255 + 0.5).astype(np.uint8)
                    self.assertLessEqual(int(np.abs(got.astype(int) - ref.astype(int)).max()), 1)
                    d = output_sharpen(x, target, amount) - x                          # one difference, 3 channels
                    inside = (output_sharpen(x, target, amount) > 0) & (output_sharpen(x, target, amount) < 1)
                    both = inside.all(-1)
                    self.assertLess(float(np.abs(d[both][:, 0] - d[both][:, 1]).max()), 1e-5)
        photo = write_jpeg(self.p("s.jpg"), noisy(48, 64, 7))
        out = self.one(photo, format="png", sharpen={"target": "glossy", "amount": "high"})["output"]
        ref = self._ref_sharpen(self.render(photo, 16).astype(np.float64) / 65535, 1.0, 1.0)
        got = cv2.imread(out, cv2.IMREAD_UNCHANGED)[..., ::-1]
        self.assertLessEqual(int(np.abs(got.astype(int) - (ref * 255 + 0.5).astype(int)).max()), 1)

    def test_output_sharpen_monotonic(self):  # E10
        from darkroom import read_image
        from darkroom_app.services.export import output_sharpen
        src = sorted(f for f in os.listdir(_util.PHOTOS) if f.lower().endswith(".jpg"))[0]
        x = np.ascontiguousarray(read_image(os.path.join(_util.PHOTOS, src))[:256, :256])   # read only

        def lap(target, amount):
            g = output_sharpen(x, target, amount)
            y = (g[..., 0] * 0.2126 + g[..., 1] * 0.7152 + g[..., 2] * 0.0722).astype(np.float32)
            return float(cv2.Laplacian(y, cv2.CV_32F).var())
        for target in ("screen", "glossy", "matte"):
            self.assertLess(lap(target, "low"), lap(target, "standard"), target)
            self.assertLess(lap(target, "standard"), lap(target, "high"), target)
        for amount in ("low", "standard", "high"):
            self.assertLess(lap("screen", amount), lap("glossy", amount), amount)
            self.assertLess(lap("glossy", amount), lap("matte", amount), amount)

    def test_output_sharpen_off_is_identity(self):  # E10
        photo = write_jpeg(self.p("i.jpg"), noisy(30, 40, 9))
        plain = self.one(photo, format="png")["output"]
        off = self.one(photo, format="png", sharpen=None, resize=None)["output"]
        self.assertTrue(np.array_equal(cv2.imread(plain, cv2.IMREAD_UNCHANGED), cv2.imread(off, cv2.IMREAD_UNCHANGED)))
        self.assertTrue(np.array_equal(cv2.imread(plain, cv2.IMREAD_UNCHANGED), self.render(photo, 8)))
        on = self.one(photo, format="png", sharpen={"target": "screen", "amount": "low"})["output"]
        self.assertFalse(np.array_equal(cv2.imread(plain, cv2.IMREAD_UNCHANGED), cv2.imread(on, cv2.IMREAD_UNCHANGED)))

    def test_export_batch_throughput_s2(self):  # E11
        import importlib.util
        spec = importlib.util.spec_from_file_location("bench_export", os.path.join(_util.REPO, "tools",
                                                                                   "bench_export.py"))
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
        self.assertEqual(bench.S2_SETTINGS, {"resize": {"mode": "long_edge", "value": 2048},
                                             "sharpen": {"target": "screen", "amount": "standard"},
                                             "max_kb": 800})                          # verbatim (E11)
        skip, msg = bench.gpu_check()
        enc = sys.stdout.encoding or "utf-8"
        print(msg.encode(enc, "replace").decode(enc))
        if skip:
            self.skipTest(msg)              # R1: only while the GPU is really busy, or without CUDA (reason shown)
        out = bench.measure(_util.tmpdir(self), log=lambda s: print(s.encode(enc, "replace").decode(enc)), s2=True)
        self.assertLessEqual(out["per_photo"], 0.8, out)


# ---------------------------------------------------------------- E12-E14
class TestExportPresets(S2Case):
    def test_export_presets_storage(self):  # E12
        from darkroom_app import safe_write
        from darkroom_app.services import export_presets as XP
        self.assertEqual((XP.FILE_NAME, XP.SCHEMA, XP.NAME_MAX, XP.PRESETS_MAX),
                         ("export-presets.json", "darkroom-export-presets/1", 60, 200))
        roots = []
        real_create = safe_write.create_new

        def create(path, root, data, *, preset_dir=None):
            roots.append((os.path.basename(path), root, preset_dir))
            return real_create(path, root, data, preset_dir=preset_dir)
        with mock.patch.object(safe_write, "create_new", create):
            self.f.save_export_preset("網頁", {"format": "jpeg", "max_kb": 800})
            self.f.save_export_preset("Archive", {"format": "tiff"})
        self.assertTrue(all(r == (self.data) and pd == self.presets for _, r, pd in roots), roots)
        self.assertTrue(all(n.startswith("export-presets.json.tmp-") for n, _, _ in roots))
        path = os.path.join(self.data, "export-presets.json")
        raw = read_bytes(path)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        obj = json.loads(raw.decode("utf-8"))
        self.assertEqual(list(obj), ["schema", "presets"])
        self.assertEqual(list(obj["presets"]), ["Archive", "網頁"])                     # casefold order
        self.assertEqual(obj["presets"]["網頁"], dict(DEFAULTS, max_kb=800))
        self.assertEqual(sorted(os.listdir(self.data)), ["export-presets.json", "export-presets.json.lock"])
        # a bad file reads as empty and is kept byte for byte before the next write
        with open(path, "wb") as f:
            f.write(b"{not json")
        self.assertEqual(self.f.list_export_presets(), {"presets": []})
        self.assertEqual(read_bytes(path), b"{not json")                               # reading never writes
        with mock.patch("time.time", return_value=1700000000):
            self.f.save_export_preset("新", {})
        bad = os.path.join(self.data, "export-presets.json.bad-1700000000")
        self.assertEqual(read_bytes(bad), b"{not json")
        self.assertEqual([p["name"] for p in self.f.list_export_presets()["presets"]], ["新"])
        with open(path, "wb") as f:
            f.write(json.dumps({"schema": "darkroom-export-presets/1",
                                "presets": {"x": {"format": "gif"}}}).encode("utf-8"))   # not the schema: bad
        with mock.patch("time.time", return_value=1700000000):
            self.f.save_export_preset("新", {})
        self.assertTrue(os.path.exists(bad + "-2"))
        # the cross-process lock: held elsewhere -> conflict, nothing written
        before = read_bytes(path)
        fd = os.open(os.path.join(self.data, "export-presets.json.lock"), os.O_RDWR)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            with mock.patch.object(XP, "LOCK_WAIT_S", 0.2):
                self.assertEqual(self.err(self.f.save_export_preset, "y", {}),
                                 ("conflict", "匯出預設正被其他程式修改，請稍後再試"))
                self.assertEqual(self.err(self.f.delete_export_preset, "新"),
                                 ("conflict", "匯出預設正被其他程式修改，請稍後再試"))
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)
        self.assertEqual(read_bytes(path), before)
        self.assertFalse([n for n in os.listdir(self.data) if ".tmp-" in n])
        # a failed replace never leaves the temporary file
        with mock.patch.object(safe_write, "replace_into", side_effect=OSError("disk full")):
            self.assertEqual(self.err(self.f.save_export_preset, "z", {}),
                             ("unavailable", "無法寫入匯出預設：disk full"))
        self.assertFalse([n for n in os.listdir(self.data) if ".tmp-" in n])
        # where the data folder may be (PLP1 / PLP17 sentences)
        inside = self.facade(data_dir=os.path.join(self.presets, "data"))
        self.assertEqual(self.err(inside.save_export_preset, "a", {}),
                         ("unavailable", "照片庫資料區不能在照片或 preset 資料夾底下："
                                         + os.path.join(self.presets, "data")))
        parent = os.path.join(self.tmp, "no-parent")
        missing = self.facade(data_dir=os.path.join(parent, "darkroom"))
        self.assertEqual(self.err(missing.save_export_preset, "a", {}),
                         ("unavailable", f"無法寫入匯出預設：上層資料夾不存在：{parent}"))
        self.assertFalse(os.path.exists(parent))
        self.assertEqual(missing.list_export_presets(), {"presets": []})

    def test_export_presets_ops(self):  # E13
        from darkroom_app.services import export_presets as XP
        r = self.f.save_export_preset("  網頁 長邊 2048\x07 ", {"resize": {"mode": "long_edge", "value": 2048}})
        s = dict(DEFAULTS, resize={"mode": "long_edge", "value": 2048})
        self.assertEqual(r, {"name": "網頁 長邊 2048", "settings": s, "previous": None})
        self.assertEqual(self.f.list_export_presets(), {"presets": [{"name": "網頁 長邊 2048", "settings": s}]})
        r2 = self.f.save_export_preset("網頁 長邊 2048".upper(), {"format": "webp"})       # casefold: replaced
        self.assertEqual(r2["previous"], s)
        self.assertEqual(self.f.list_export_presets()["presets"],
                         [{"name": "網頁 長邊 2048".upper(), "settings": dict(DEFAULTS, format="webp")}])
        path = os.path.join(self.data, "export-presets.json")
        before = read_bytes(path)
        gone = self.f.delete_export_preset("網頁 長邊 2048")
        self.assertEqual(gone, {"name": "網頁 長邊 2048".upper(), "settings": dict(DEFAULTS, format="webp")})
        self.assertEqual(self.f.list_export_presets(), {"presets": []})
        self.f.save_export_preset(gone["name"], gone["settings"])                         # the page's 復原
        self.assertEqual(read_bytes(path), before)
        self.assertEqual(self.err(self.f.delete_export_preset, "沒有"), ("not_found", "找不到匯出預設：沒有"))
        self.assertEqual(self.err(self.f.delete_export_preset, None), ("not_found", "找不到匯出預設：None"))
        for bad in ("", "   ", "\x07\x08", "x" * 61, None, 5):
            self.assertEqual(self.err(self.f.save_export_preset, bad, {}), ("invalid", "匯出預設名稱要 1～60 個字"), bad)
        self.assertEqual(self.f.save_export_preset("x" * 60, {})["name"], "x" * 60)
        self.assertEqual(self.err(self.f.save_export_preset, "a", {"dest_dir": "D:/x"}),
                         ("invalid", "匯出預設不包含匯出資料夾（dest_dir）"))
        self.assertEqual(self.err(self.f.save_export_preset, "a", {"colour": "p3"}),
                         ("invalid", "匯出設定不認得的鍵：colour（可用 format、bit_depth、quality、max_kb、resize、"
                                     "metadata、remove_gps、sharpen）"))
        self.assertEqual(self.err(self.f.save_export_preset, "a", "jpeg"), ("invalid", "匯出設定要是物件：jpeg"))
        self.assertEqual(self.err(self.f.save_export_preset, "a", {"format": "bmp"}),
                         ("invalid", "不支援的匯出格式：bmp（可用 jpeg、png、tiff、webp）"))       # E1 / E2 sentence
        with mock.patch.object(XP, "PRESETS_MAX", 3):
            self.f.save_export_preset("b", {})
            self.assertEqual(self.err(self.f.save_export_preset, "c", {}), ("invalid", "匯出預設最多 200 個"))
            self.f.save_export_preset("B", {"format": "png"})                            # replacing is fine
        # light: no photo, no GPU, no torch / cv2
        code = ("import sys, json\nfrom darkroom_app.composition import build_facade\n"
                "f = build_facade(sys.argv[1], data_dir=sys.argv[2])\n"
                "f.save_export_preset('a', {'format': 'png'}); f.list_export_presets(); f.delete_export_preset('a')\n"
                "print(json.dumps(sorted(m for m in ('torch', 'cv2') if m in sys.modules)))\n")
        r = subprocess.run([*_util.guarded_python(), "-c", code, self.presets, os.path.join(self.tmp, "d2")],
                           capture_output=True, cwd=_util.REPO)
        self.assertEqual((r.returncode, r.stdout.decode().strip()), (0, "[]"), r.stderr.decode("utf-8", "replace"))

    def test_export_presets_keep_good_entries_and_foreign_version(self):  # E12a (seal F2)
        path = os.path.join(self.data, "export-presets.json")
        os.makedirs(self.data)
        good = dict(DEFAULTS, format="png", quality=None)
        raw = json.dumps({"schema": "darkroom-export-presets/1",
                          "presets": {"好的": good, "壞的": {"format": "gif"}, "舊版鍵": {"format": "jpeg"}}},
                         ensure_ascii=False).encode("utf-8")
        with open(path, "wb") as f:
            f.write(raw)
        self.assertEqual(self.f.list_export_presets(), {"presets": [{"name": "好的", "settings": good}]})
        with mock.patch("time.time", return_value=1700000001):
            self.f.save_export_preset("新", {})
        self.assertEqual([p["name"] for p in self.f.list_export_presets()["presets"]], ["好的", "新"])   # kept
        self.assertEqual(read_bytes(os.path.join(self.data, "export-presets.json.bad-1700000001")), raw)
        # another version of the schema is never rewritten: conflict on every operation, the bytes stay
        foreign = json.dumps({"schema": "darkroom-export-presets/2", "presets": {}, "extra": 1}).encode("utf-8")
        with open(path, "wb") as f:
            f.write(foreign)
        want = ("conflict", "匯出預設檔版本不支援：darkroom-export-presets/2（export-presets.json）")
        self.assertEqual(self.err(self.f.list_export_presets), want)
        self.assertEqual(self.err(self.f.save_export_preset, "x", {}), want)
        self.assertEqual(self.err(self.f.delete_export_preset, "x"), want)
        photo = write_jpeg(self.p("f.jpg"), pattern(10, 12))
        self.assertEqual(self.err(self.f.export, [{"path": photo}], export_preset="x", dest_dir=self.dest), want)
        self.assertEqual(read_bytes(path), foreign)
        self.assertEqual(sorted(n for n in os.listdir(self.data) if n.startswith("export-presets.json.bad")),
                         ["export-presets.json.bad-1700000001"])

    def test_export_with_export_preset(self):  # E14
        photo = write_jpeg(self.p("e.jpg"), pattern(1000, 1500))
        self.f.save_export_preset("大檔", {"format": "png", "bit_depth": 16,
                                         "resize": {"mode": "long_edge", "value": 1000}})
        res = self.one(photo, format="jpeg", export_preset="大檔")
        self.assertTrue(res["output"].endswith("e.jpg"))
        self.assertEqual(res["used"], {"params_from": "original", "quality": 92, "width": 1000, "height": 667})
        self.assertEqual(cv2.imread(res["output"], cv2.IMREAD_UNCHANGED).dtype, np.uint8)
        res = self.one(photo, export_preset="大檔")
        self.assertTrue(res["output"].endswith("e.png"))
        a = cv2.imread(res["output"], cv2.IMREAD_UNCHANGED)
        self.assertEqual((a.dtype, a.shape), (np.uint16, (667, 1000, 3)))
        before = snapshot(self.dest)
        self.assertEqual(self.err(self.f.export, [{"path": photo}], export_preset="沒有", dest_dir=self.dest),
                         ("not_found", "找不到匯出預設：沒有"))
        self.assertEqual(snapshot(self.dest), before)


# ---------------------------------------------------------------- E15
class TestSavedEdit(S2Case):
    def test_export_uses_saved_edit(self):  # E15
        from darkroom_app import preview as semantics
        photo = write_jpeg(self.p("a.jpg"), pattern(30, 40))
        other = write_jpeg(self.p("b.jpg"), pattern(30, 40, 1))
        other = write_png(self.p("b.png"), pattern(30, 40))
        self.f.set_edit(photo, "p-expo", 50, {"Contrast2012": 10})
        lib = self.f._presets.library
        params = semantics.effective_params(lib.get("p-expo"), 0.5, {"Contrast2012": 10.0})
        res = self.export([photo, other], format="png")
        self.assertEqual([r["used"]["params_from"] for r in res], ["edit", "original"])
        a = cv2.imread(res[0]["output"], cv2.IMREAD_UNCHANGED)
        self.assertTrue(np.array_equal(a, self.render(photo, 8, params)))
        info = self.f.open_photo(photo)                                                # the image_id item too
        res2 = self.f.export([{"image_id": info["image_id"]}], "png", dest_dir=self.dest)["results"][0]
        self.assertEqual(res2["used"]["params_from"], "edit")
        self.assertTrue(np.array_equal(cv2.imread(res2["output"], cv2.IMREAD_UNCHANGED), a))
        orig = self.export([photo], item={"preset_id": None}, format="png")[0]            # null = no preset
        self.assertEqual(orig["used"]["params_from"], "request")
        self.assertTrue(np.array_equal(cv2.imread(orig["output"], cv2.IMREAD_UNCHANGED), self.render(photo, 8)))
        none = self.export([other], format="png")[0]
        self.assertTrue(np.array_equal(cv2.imread(none["output"], cv2.IMREAD_UNCHANGED), self.render(other, 8)))

    def test_export_saved_edit_snapshot_after_preset_changed(self):  # E15, PL4
        import _xmpgen
        from darkroom_app import preview as semantics
        photo = write_jpeg(self.p("a.jpg"), pattern(30, 40))
        snap = semantics.effective_params(self.f._presets.library.get("p-expo"), 1.0, {})
        self.f.set_edit(photo, "p-expo", 100, None)
        _xmpgen.write(self.presets, "p-expo.xmp", _xmpgen.xmp_text({"Exposure2012": "-2.00"}, name="曝光一",
                                                                    group="風景 - 海邊"))
        self.f.rebuild_library()                                                      # the view sees the new file
        self.assertEqual(self.f.get_edit(photo)["preset_status"], "changed")
        res = self.export([photo], format="png")[0]
        self.assertEqual(res["used"]["params_from"], "edit")
        self.assertTrue(np.array_equal(cv2.imread(res["output"], cv2.IMREAD_UNCHANGED), self.render(photo, 8, snap)))
        os.remove(os.path.join(self.presets, "p-expo.xmp"))
        self.f.rebuild_library()
        self.assertEqual(self.f.get_edit(photo)["preset_status"], "missing")
        res = self.export([photo], format="png")[0]
        self.assertTrue(np.array_equal(cv2.imread(res["output"], cv2.IMREAD_UNCHANGED), self.render(photo, 8, snap)))

    def test_export_saved_edit_library_unavailable(self):  # E15: never silently the original instead
        from darkroom_app import config
        from darkroom_app.composition import build_facade
        photo = write_jpeg(self.p("a.jpg"), pattern(30, 40))
        f = build_facade(self.presets, engine=self.eng)                                # data_dir from config
        with mock.patch.object(config, "data_dir", side_effect=config.ConfigError(config.DATA_DIR_ERROR)):
            res = f.export([{"path": photo}, {"path": photo, "preset_id": "p-expo"}], dest_dir=self.dest)["results"]
        self.assertEqual(res[0], {"ok": False, "source": "a.jpg", "error": f"匯出失敗：a.jpg：{config.DATA_DIR_ERROR}"})
        self.assertFalse(res[1]["ok"])                                                  # PLP5 reads the edit too
        self.f.set_edit(photo, "p-expo", 80, None)
        fp = self.f.get_edit(photo)["fingerprint"]
        edit = os.path.join(self.data, "edits", fp[:2], fp + ".json")
        with open(edit, "wb") as fh:
            fh.write(b"{broken")
        res = self.export([photo, photo], format="png")
        # XP35 (CONTRACT-s3-crop C19, D4): an item without "geometry" uses the saved one, so it reads the edit too;
        # "geometry": null asks for none and needs no edit
        res = self.f.export([{"path": photo}, {"path": photo, "preset_id": None, "geometry": None},
                             {"path": photo, "preset_id": None}], "png", dest_dir=self.dest)["results"]
        self.assertEqual(res[0], {"ok": False, "source": "a.jpg",
                                  "error": f"匯出失敗：a.jpg：照片庫的編輯檔損壞：{edit}"})
        self.assertTrue(res[1]["ok"])
        self.assertEqual(res[2], res[0])
        self.assertEqual(os.listdir(self.dest), ["a.png"])
        # seal F6: an edit file of another version is the third "cannot read" case - that item fails, never the original
        with open(edit, "w", encoding="utf-8") as fh:
            json.dump({"schema": "darkroom-edit/99", "fingerprint": fp}, fh)
        res = self.f.export([{"path": photo}], "png", dest_dir=self.dest)["results"]
        self.assertEqual(res, [{"ok": False, "source": "a.jpg",
                                "error": "匯出失敗：a.jpg：編輯檔版本不支援：darkroom-edit/99（a.jpg）"}])
        self.assertEqual(os.listdir(self.dest), ["a.png"])


# ---------------------------------------------------------------- E16, E17
class TestPresetFiles(S2Case):
    def setUp(self):
        super().setUp()
        self.lib_root = os.path.join(self.tmp, "lib")
        os.makedirs(self.lib_root)
        self.f = self.facade(library_dir=self.lib_root)
        self.lib = self.f._presets.library

    def test_preset_files_bytes(self):  # E16, D6
        from darkroom import load_preset
        res = self.f.preset_files(["p-expo", "nope", "p-skip"])["files"]
        self.assertEqual([r["ok"] for r in res], [True, False, True])
        self.assertEqual(res[1], {"ok": False, "preset_id": "nope", "error": "unknown preset nope"})
        self.assertEqual(sorted(res[0]), ["data_base64", "file_name", "ok", "preset_id"])
        for r, pid in ((res[0], "p-expo"), (res[2], "p-skip")):
            data = base64.b64decode(r["data_base64"])
            self.assertEqual(data, read_bytes(os.path.join(self.presets, pid + ".xmp")))      # byte for byte
            self.assertEqual(hashlib.sha256(data).hexdigest(), self.lib.files()[pid].sha256)
        imp = os.path.join(self.tmp, "imp")
        os.makedirs(imp)
        shutil.copy(os.path.join(self.presets, "p-minor.xmp"), os.path.join(imp, "bought.xmp"))
        with open(os.path.join(imp, "bought.xmp"), "ab") as fh:
            fh.write(b"\n")
        iid = self.f.import_presets([imp])["results"][0]["id"]
        data = base64.b64decode(self.f.preset_files([iid])["files"][0]["data_base64"])
        self.assertEqual(data, read_bytes(os.path.join(imp, "bought.xmp")))
        # a user preset gets the Lightroom attributes it lacks, right after crs:PresetType="Normal"
        uid = self.f.save_user_preset("我的暖調", None, "p-mixed", 120, {"Contrast2012": 10})["id"]
        orig = read_bytes(os.path.join(self.lib_root, "user", "我的暖調.xmp"))
        self.assertNotIn(b"crs:UUID", orig)
        out1 = base64.b64decode(self.f.preset_files([uid])["files"][0]["data_base64"])
        out2 = base64.b64decode(self.f.preset_files([uid])["files"][0]["data_base64"])
        self.assertEqual(out1, out2)                                                     # the same UUID each time
        uuid = hashlib.sha256(orig).hexdigest()[:32].upper()
        added = "".join(" " + a.format(uuid=uuid) for a in LR_ATTRS).encode("utf-8")
        anchor = b'crs:PresetType="Normal"'
        at = orig.index(anchor) + len(anchor)
        self.assertEqual(out1, orig[:at] + added + orig[at:])                            # nothing else changed
        for a in LR_ATTRS:
            self.assertEqual(out1.count((" " + a.split("=")[0] + "=").encode()), 1, a)
        tmp = os.path.join(self.tmp, "roundtrip.xmp")
        with open(tmp, "wb") as fh:
            fh.write(out1)
        back, lib = load_preset(tmp), self.lib.get(uid)
        self.assertEqual((back.values, back.curves, back.masks), (lib.values, lib.curves, lib.masks))
        # only the missing ones are added
        from darkroom_app.services.preset_library import lightroom_bytes
        half = orig.replace(anchor, anchor + b' crs:SupportsAmount="True" crs:Version="15.4"')
        once = lightroom_bytes(half)
        self.assertEqual(once.count(b' crs:SupportsAmount="'), 1)
        self.assertEqual(once.count(b' crs:Version="'), 1)
        self.assertEqual(once.count(b' crs:SupportsAmount2="'), 1)
        for bad in ([], [5], "p-expo", None, ["p-expo"] * 501):
            self.assertEqual(self.err(self.f.preset_files, bad), ("invalid", "preset_ids 要是 1～500 個 preset id"))
        self.assertEqual(len(self.f.preset_files(["p-expo"] * 500)["files"]), 500)

    def test_preset_files_names(self):  # E16
        self.f.rename_preset("p-expo", "同名")
        self.f.rename_preset("p-minor", "同名")
        self.f.rename_preset("p-skip", "a/b:c")
        self.f.rename_preset("p-mixed", "ABC")
        self.f.rename_preset("p-strong", "abc")
        names = [r["file_name"] for r in self.f.preset_files(
            ["p-expo", "p-minor", "p-skip", "p-mixed", "p-strong", "p-expo"])["files"]]
        self.assertEqual(names, ["同名.xmp", "同名 (2).xmp", "a_b_c.xmp", "ABC.xmp", "abc (2).xmp", "同名 (3).xmp"])

    def test_export_preset_files_never_overwrite(self):  # E17
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        with open(os.path.join(out, "曝光一.xmp"), "wb") as fh:
            fh.write(b"someone else's")
        with open(os.path.join(out, "很亮 (2).XMP"), "wb") as fh:
            fh.write(b"mine")
        res = self.f.export_preset_files(["p-expo", "p-strong", "p-strong", "nope"], out)
        self.assertEqual(res["results"], [
            {"ok": True, "preset_id": "p-expo", "output": os.path.join(out, "曝光一 (2).xmp")},
            {"ok": True, "preset_id": "p-strong", "output": os.path.join(out, "很亮.xmp")},
            {"ok": True, "preset_id": "p-strong", "output": os.path.join(out, "很亮 (3).xmp")},
            {"ok": False, "preset_id": "nope", "error": "unknown preset nope"}])
        self.assertEqual(read_bytes(os.path.join(out, "曝光一.xmp")), b"someone else's")
        self.assertEqual(read_bytes(os.path.join(out, "很亮 (2).XMP")), b"mine")
        self.assertEqual(read_bytes(os.path.join(out, "很亮.xmp")), read_bytes(os.path.join(self.presets, "p-strong.xmp")))
        from darkroom_app.services import preset_library as PL
        with mock.patch.object(PL, "N_MAX", 3):
            res = self.f.export_preset_files(["p-strong"], out)["results"]
        self.assertEqual(res, [{"ok": False, "preset_id": "p-strong",
                                "error": "很亮 的匯出檔名已用到 (3)，請清理匯出資料夾後再試"}])
        self.assertEqual(self.err(self.f.export_preset_files, ["p-expo"], "relative"),
                         ("invalid", "找不到匯出資料夾：relative"))
        self.assertEqual(self.err(self.f.export_preset_files, ["p-expo"], os.path.join(self.tmp, "missing")),
                         ("invalid", "找不到匯出資料夾：" + os.path.join(self.tmp, "missing")))
        self.assertEqual(self.err(self.f.export_preset_files, [], out),
                         ("invalid", "preset_ids 要是 1～500 個 preset id"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "missing")))

    def test_export_preset_files_refuses_preset_folder(self):  # E17: judged first, never left to SafeWriteRefused
        self.f.save_user_preset("x", None, "p-expo", 100, None)
        before = snapshot(self.presets, self.lib_root)
        for dest in (self.presets, self.lib_root, os.path.join(self.lib_root, "user")):
            with self.subTest(dest=dest):
                self.assertEqual(self.err(self.f.export_preset_files, ["p-expo"], dest),
                                 ("invalid", f"不能把 preset 匯出到 preset 資料夾或 preset 庫裡：{dest}"))
        self.assertEqual(snapshot(self.presets, self.lib_root), before)


# ---------------------------------------------------------------- E18, E19
class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = _util.tmpdir(self)
        self.cfg = os.path.join(self.tmp, "c.json")

    def write(self, obj):
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def test_data_dir_platform_defaults(self):  # E18 (PLP18)
        from darkroom_app import config
        home = "D:\\home\\tester"
        self.write({"data_dir": "D:/x/data"})
        self.assertEqual(config.data_dir(self.cfg, {}, "darwin", home), "D:/x/data")             # the key first
        self.write({})
        self.assertEqual(config.data_dir(self.cfg, {"LOCALAPPDATA": "C:/L"}, "win32", home),
                         os.path.join("C:/L", "darkroom"))
        with self.assertRaises(config.ConfigError) as cm:
            config.data_dir(self.cfg, {}, "win32", home)
        self.assertEqual(str(cm.exception), "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 LOCALAPPDATA 存在")
        self.assertEqual(config.data_dir(self.cfg, {}, "darwin", home),
                         os.path.join(home, "Library", "Application Support", "darkroom"))
        self.assertEqual(config.data_dir(self.cfg, {"XDG_DATA_HOME": "D:\\xdg"}, "linux", home),
                         os.path.join("D:\\xdg", "darkroom"))
        self.assertEqual(config.data_dir(self.cfg, {"XDG_DATA_HOME": "relative"}, "linux", home),
                         os.path.join(home, ".local", "share", "darkroom"))
        self.assertEqual(config.data_dir(self.cfg, {}, "linux", home), os.path.join(home, ".local", "share", "darkroom"))
        for plat in ("linux", "darwin"):
            with self.assertRaises(config.ConfigError) as cm:
                config.data_dir(self.cfg, {}, plat, "relative-home")
            self.assertEqual(str(cm.exception), "找不到照片庫資料區：請在 config.local.json 設定 data_dir，或確認 HOME 存在")

    def test_relative_data_dir_is_made_absolute(self):  # E19
        from darkroom_app import config
        self.write({"data_dir": "rel/data", "preset_dir": "xmp", "preset_library_dir": "..\\lib"})
        self.assertEqual(config.data_dir(self.cfg), os.path.normpath(os.path.join(self.tmp, "rel/data")))
        self.assertEqual(config.preset_dir(self.cfg, env={}), os.path.join(self.tmp, "xmp"))
        self.assertEqual(config.preset_library_dir(self.cfg), os.path.normpath(os.path.join(self.tmp, "..", "lib")))
        # the CLI makes --data-dir / --preset-dir absolute against the working directory before anything is made
        work = os.path.join(self.tmp, "work")
        os.makedirs(os.path.join(work, "presets"))
        make_presets(os.path.join(work, "presets"))
        os.makedirs(os.path.join(work, "photos"))
        photo = write_jpeg(os.path.join(work, "photos", "a.jpg"), pattern(10, 12))
        r = subprocess.run([*_util.guarded_python(), "-m", "darkroom_app.cli", "--preset-dir", "presets",
                            "--data-dir", "data", "edit", "set", os.path.join("photos", "a.jpg"), "--preset",
                            "p-expo", "--json"],
                           capture_output=True, cwd=work, env={**os.environ, "PYTHONPATH": _util.REPO})
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).decode("utf-8", "replace"))
        fp = json.loads(r.stdout)["result"]["fingerprint"]
        self.assertTrue(os.path.isfile(os.path.join(work, "data", "edits", fp[:2], fp + ".json")))
        self.assertEqual(sorted(os.listdir(work)), ["data", "photos", "presets"])         # no other folder made
        self.assertEqual(sorted(os.listdir(os.path.join(work, "data"))), ["edits"])
        del photo

    def test_bad_config_json_is_config_error(self):  # E19
        from darkroom_app import cli, config
        with open(self.cfg, "wb") as f:
            f.write(b'{\n  "data_dir": "x",\n  oops\n}')
        try:
            json.loads('{\n  "data_dir": "x",\n  oops\n}')
        except ValueError as e:
            want = f"c.json 不是正確的 JSON（第 {e.lineno} 行第 {e.colno} 欄）：{e.msg}"
        for fn in (lambda: config.preset_dir(self.cfg, env={}), lambda: config.data_dir(self.cfg),
                   lambda: config.load(self.cfg, env={})):
            with self.assertRaises(config.ConfigError) as cm:
                fn()
            self.assertEqual(str(cm.exception), want)
        self.assertEqual(want, "c.json 不是正確的 JSON（第 3 行第 3 欄）：Expecting property name enclosed in double quotes")
        with open(self.cfg, "wb") as f:
            f.write(b'{"data_dir": "\xff\xfe"}')
        with self.assertRaises(config.ConfigError) as cm:
            config.data_dir(self.cfg)
        self.assertEqual(str(cm.exception), "c.json 不是正確的 JSON（第 1 行第 15 欄）：invalid start byte")
        # the CLI and the App: one line, exit 2 (L9), not a traceback
        with open(self.cfg, "wb") as f:
            f.write(b"{oops")
        out, err = io.StringIO(), io.StringIO()
        import contextlib
        with mock.patch.object(config, "CONFIG_FILE", self.cfg), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            rc = cli.main(["presets", "flags", "--json"])
        line = "darkroom：c.json 不是正確的 JSON（第 1 行第 2 欄）：Expecting property name enclosed in double quotes\n"
        self.assertEqual((rc, out.getvalue(), err.getvalue()), (2, "", line))
        from darkroom_app import __main__ as app_main
        err = io.StringIO()
        with mock.patch.object(config, "CONFIG_FILE", self.cfg), contextlib.redirect_stderr(err):
            self.assertEqual(app_main.main([]), 2)
        self.assertEqual(err.getvalue(), line)


# ---------------------------------------------------------------- E20, E21
class TestLibraryInPhotoFolder(S2Case):
    WRITES = (("rename_preset", ("p-expo", "新名")), ("move_preset", ("p-expo", "新群")),
              ("set_favorite", ("p-expo", True)), ("create_group", ("新群組",)),
              ("rename_group", ("測試", "測驗")), ("import_presets", None), ("save_user_preset", ("u", None, "p-expo")),
              ("rebuild_library", ()), ("save_edit_as_preset", None))

    def _calls(self, f, lib_root):
        imp = os.path.join(self.tmp, "imp")
        os.makedirs(imp, exist_ok=True)
        shutil.copy(os.path.join(self.presets, "p-minor.xmp"), os.path.join(imp, "new.xmp"))
        with open(os.path.join(imp, "new.xmp"), "ab") as fh:
            fh.write(b" ")
        photo = write_jpeg(self.p("a.jpg"), pattern(10, 12))
        f.set_edit(photo, "p-expo", 50, None)
        for name, args in self.WRITES:
            if name == "import_presets":
                args = ([imp],)
            elif name == "save_edit_as_preset":
                args = (photo, "存")
            yield name, args

    def test_library_root_in_photo_folder_disables_writes(self):  # E20, KP22, D9
        from darkroom_app.services.preset_library import photo_folder_of
        cases = {}
        a = os.path.join(self.tmp, "a", "lib")                      # (a) the library root itself holds a photo
        os.makedirs(a)
        write_jpeg(os.path.join(a, "x.jpg"), pattern(4, 4))
        cases["root"] = (a, os.path.realpath(a))
        b = os.path.join(self.tmp, "b", "lib")                      # (b) its parent holds one
        os.makedirs(b)
        write_png(os.path.join(self.tmp, "b", "y.PNG"), pattern(4, 4))
        cases["parent"] = (b, os.path.realpath(os.path.join(self.tmp, "b")))
        c = os.path.join(self.tmp, "c", "lib")                      # (c) neither
        os.makedirs(c)
        cases["none"] = (c, None)
        for label, (root, folder) in cases.items():
            with self.subTest(label):
                self.assertEqual(photo_folder_of(root), folder)
                f = self.facade(library_dir=root)
                calls = list(self._calls(f, root))
                before = snapshot(root, self.presets)
                if folder is None:
                    for name, args in calls:
                        getattr(f, name)(*args)
                    continue
                want = ("unavailable", f"preset 庫的位置 {os.path.abspath(root)} 在照片資料夾裡（{folder} 有照片），為了不在"
                                       "照片資料夾裡寫檔，整理 preset、匯入、存成 preset 先關閉；請在 config.local.json 把 "
                                       "preset_library_dir 設到別的資料夾")
                self.assertEqual(len(calls), 9)
                for name, args in calls:
                    self.assertEqual(self.err(getattr(f, name), *args), want, name)
                self.assertEqual(snapshot(root, self.presets), before)
                self.assertFalse(os.path.exists(os.path.join(root, "library.json")))
                self.assertGreater(f.list_presets()["total"], 0)                       # reads go on
                self.assertTrue(f.preset_groups()["groups"])
                self.assertEqual(f.preset_detail("p-expo")["id"], "p-expo")
                self.assertTrue(f.preset_files(["p-expo"])["files"][0]["ok"])
                caps = f.capabilities()["features"]["preset_library_writes"]
                self.assertEqual(caps, {"available": False, "reason": want[1]})

    def test_photo_folder_skips_home_temp_and_drive_root(self):  # D9 (C), IP3
        from darkroom_app.services.preset_library import photo_folder_of
        top = os.path.join(self.tmp, "home")
        lib = os.path.join(top, "lib")
        os.makedirs(lib)
        write_jpeg(os.path.join(top, "me.jpg"), pattern(4, 4))
        temp = {"TEMP": os.environ["TEMP"]}                    # %TEMP% itself holds other programs' pictures
        self.assertEqual(photo_folder_of(lib, env=temp), os.path.realpath(top))
        self.assertIsNone(photo_folder_of(lib, home=top, env=temp))                   # the home folder itself
        self.assertIsNone(photo_folder_of(lib, env={"TEMP": top, "TMP": os.environ["TEMP"]}))   # a temp folder
        self.assertIsNone(photo_folder_of(lib, env={"TMP": top, "TMPDIR": os.environ["TEMP"]}))
        seen = []
        real = os.scandir

        def scan(p):
            seen.append(os.path.normcase(os.path.realpath(p)))
            return real(p)
        with mock.patch("os.scandir", scan):
            photo_folder_of(os.path.join(self.tmp, "home", "lib"), home=top, env={"TEMP": top})
        drive = os.path.normcase(os.path.splitdrive(os.path.realpath(self.tmp))[0] + os.sep)
        self.assertNotIn(drive, seen)                                                  # the drive root is never read
        self.assertNotIn(os.path.normcase(os.path.realpath(top)), seen)
        self.assertIn(os.path.normcase(os.path.realpath(lib)), seen)

    def test_export_photo_inside_preset_folder_fails_one_item(self):  # E21 (S1 finding [11])
        import contextlib
        from darkroom_app import cli
        photos = [write_jpeg(self.p(f"p{i}.jpg"), pattern(10, 12, i)) for i in range(5)]
        inside = write_jpeg(os.path.join(self.presets, "in.jpg"), pattern(10, 12))
        res = self.f.export([{"path": p} for p in photos[:3] + [inside] + photos[3:]])["results"]
        self.assertEqual([r["ok"] for r in res], [True, True, True, False, True, True])
        self.assertEqual(res[3], {"ok": False, "source": "in.jpg",
                                  "error": "匯出失敗：in.jpg：照片在 preset 資料夾裡，請指定匯出資料夾（dest_dir）"})
        self.assertFalse(os.path.exists(os.path.join(self.presets, EXPORT_DIR)))
        self.assertEqual(len(os.listdir(self.p(EXPORT_DIR))), 5)
        ok = self.f.export([{"path": inside}], dest_dir=self.dest)["results"][0]           # with dest_dir it works
        self.assertTrue(ok["ok"])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["export", photos[0], inside, "--json"], facade=self.f)
        self.assertEqual(rc, 6)

    def test_semantic_build_refused_in_photo_folder(self):  # E20 / KP22: nothing sent, nothing written
        from test_semantic_index import Harness
        h = Harness(self)
        write_jpeg(os.path.join(h.tmp, "photo.jpg"), pattern(4, 4))
        before = snapshot(h.tmp)
        kind, message = self.err(h.f.semantic_build, None, False, 0)
        self.assertEqual(kind, "unavailable")
        self.assertTrue(message.startswith(f"preset 庫的位置 {os.path.abspath(h.tmp)} 在照片資料夾裡"), message)
        self.assertEqual((h.clients, h.reads, h.rendered), ([], [], []))
        self.assertEqual(snapshot(h.tmp), before)
        self.assertEqual(h.f.semantic_build(None, True, 0)["state"], "dry_run")            # a dry run still reports


# ---------------------------------------------------------------- E33
class TestHousekeeping(unittest.TestCase):
    def test_svg_line_endings_pinned(self):  # E33, D15
        with open(os.path.join(_util.REPO, ".gitattributes"), encoding="utf-8") as f:
            self.assertIn("*.svg text eol=lf", f.read().splitlines())
        for rel in ("darkroom_app/static/logo.svg", "docs/assets/logo.svg"):
            self.assertNotIn(b"\r", read_bytes(os.path.join(_util.REPO, rel)), rel)


if __name__ == "__main__":
    unittest.main()
