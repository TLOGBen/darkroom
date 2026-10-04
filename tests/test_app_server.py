"""App shell server: B3-B6, B8, B11, B12 (aiohttp test client, no browser)."""
import asyncio
import builtins
import hashlib
import json
import os
import threading
import time
import unittest
from unittest import mock

import cv2
import numpy as np
from aiohttp.test_utils import AioHTTPTestCase

import _util
import _xmpgen
from darkroom import Params

SKIP_BANNER = "這個 preset 有 {n} 項會改變觀感的設定無法套用：{items_joined_by_、}"  # verbatim (contract R4)
SKIP_NOTE = "另有 {n} 項細節設定未套用：{items_joined_by_、}"                      # verbatim (contract R4)
PREVIEW_MAX = 1500000                                              # verbatim (contract B4)


def write_photo(path, w, h, seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([xx / w, yy / h, 0.5 + 0.3 * np.sin(xx / 37.0) * np.cos(yy / 23.0)], -1)
    img = np.clip(img + rng.normal(0, 0.02, img.shape).astype(np.float32), 0, 1)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".tif", ".tiff"):
        data = (img[..., ::-1] * 65535 + 0.5).astype(np.uint16)
    else:
        data = (img[..., ::-1] * 255 + 0.5).astype(np.uint8)
    ok, buf = cv2.imencode(ext if ext != ".tiff" else ".tif", data)
    assert ok
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return path


def make_presets(d):
    look = '   <crs:Look>\n    <rdf:Description crs:Name="Adobe Color"/>\n   </crs:Look>\n'
    _xmpgen.write(d, "p-expo.xmp", _xmpgen.xmp_text(
        {"Exposure2012": "+1.00", "Contrast2012": "+40", "SplitToningShadowHue": "200",
         "SplitToningShadowSaturation": "+30"}, name="曝光一", group="風景 - 海邊"))
    _xmpgen.write(d, "p-strong.xmp", _xmpgen.xmp_text({"Exposure2012": "+4.50"}, name="很亮", group="測試"))
    _xmpgen.write(d, "p-skip.xmp", _xmpgen.xmp_text(
        {"HDREditMode": "1", "Temperature": "5500", "Tint": "+10", "Exposure2012": "+0.20"},
        name="有略過", group="人像 - 女生", extra=look))
    _xmpgen.write(d, "p-minor.xmp", _xmpgen.xmp_text(
        {"LuminanceSmoothing": "+20", "ColorNoiseReduction": "30", "Exposure2012": "+0.10"}, name="只有細節", group="測試"))
    _xmpgen.write(d, "p-mixed.xmp", _xmpgen.xmp_text(
        {"Temperature": "5200", "LuminanceSmoothing": "+20", "Exposure2012": "+0.10"}, name="混合", group="測試",
        curves={"ToneCurvePV2012": [(0, 20), (128, 140), (255, 240)],
                "ToneCurvePV2012Red": [(0, 0), (255, 230)]}))
    _xmpgen.write(d, "p-old.xmp", _xmpgen.xmp_text({"ProcessVersion": "5.7", "Exposure": "+0.50"}, name="舊版"))
    return d


def snapshot(*dirs):
    out = {}
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                st = os.stat(p)
                with open(p, "rb") as fh:
                    out[p] = (st.st_size, st.st_mtime_ns, hashlib.sha256(fh.read()).hexdigest())
    return out


def decode(data):
    a = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return a[..., ::-1].astype(np.float32) / 255.0


class AppCase(AioHTTPTestCase):
    preset_dir = None

    async def get_application(self):
        from darkroom_app.server import make_app
        self.tmp = _util.tmpdir(self)
        if self.preset_dir is None:
            d = os.path.join(self.tmp, "presets")
            os.makedirs(d)
            self.presets = make_presets(d)
        else:
            self.presets = self.preset_dir
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        return make_app(self.presets)

    async def open_photo(self, name="photo.png", w=2400, h=1600):
        path = os.path.join(self.photos, name)
        if not os.path.exists(path):
            write_photo(path, w, h)
        r = await self.client.post("/api/open", json={"path": path})
        self.assertEqual(r.status, 200, await r.text())
        return path, await r.json()

    async def preview(self, **body):
        r = await self.client.post("/api/preview", json=body)
        return r, await r.read()


class TestPresetsApi(AppCase):  # B3 (the user's real library)
    preset_dir = None

    async def get_application(self):
        type(self).preset_dir = _util.preset_dir()
        return await super().get_application()

    async def test_api_presets_shape(self):
        r = await self.client.get("/api/presets")
        self.assertEqual(r.status, 200)
        text = await r.text()
        rows = json.loads(text)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 1466)
        for row in rows:
            self.assertEqual(set(row), {"id", "group", "name", "supported", "skipped"})
            self.assertIs(row["supported"], True)
            self.assertIsInstance(row["skipped"], list)
            self.assertIsInstance(row["group"], str)
            self.assertTrue(row["name"])
        self.assertEqual(len({r["id"] for r in rows}), 1466)
        ids = {os.path.splitext(f)[0] for f in os.listdir(self.presets) if f.endswith(".xmp")}
        self.assertEqual({r["id"] for r in rows}, ids)
        # no full preset path in the response, in any spelling
        low = text.casefold()
        for spelling in (self.presets, self.presets.replace("\\", "/"), self.presets.replace("/", "\\"),
                         json.dumps(self.presets.replace("/", "\\"))[1:-1]):
            self.assertNotIn(spelling.casefold(), low)
        self.assertNotIn(".xmp", low)
        self.assertNotIn("artifact", low)


class TestPresetDetail(AppCase):
    async def test_api_presets_synthetic_rows(self):
        rows = await (await self.client.get("/api/presets")).json()
        by = {r["id"]: r for r in rows}
        self.assertEqual(by["p-expo"], {"id": "p-expo", "group": "風景 - 海邊", "name": "曝光一",
                                        "supported": True, "skipped": []})
        self.assertIs(by["p-old"]["supported"], False)
        self.assertEqual(by["p-skip"]["skipped"], ["HDREditMode", "Temperature", "Tint", "Look（Adobe Color）"])

    async def test_skip_banner_text(self):  # B11 / R4: only look-changing items, Chinese names
        d = await (await self.client.get("/api/presets/p-skip")).json()
        items = "、".join(["HDR 編輯模式", "色溫（絕對值）", "色調（絕對值）", "描述檔外觀（Adobe Color）"])
        self.assertEqual(d["banner"], SKIP_BANNER.replace("{n}", "4").replace("{items_joined_by_、}", items))
        self.assertEqual(d["banner"],
                         "這個 preset 有 4 項會改變觀感的設定無法套用：HDR 編輯模式、色溫（絕對值）、色調（絕對值）、描述檔外觀（Adobe Color）")
        self.assertEqual(d["note"], "")
        minor = await (await self.client.get("/api/presets/p-minor")).json()
        self.assertEqual(minor["banner"], "")
        self.assertEqual(minor["note"], "另有 2 項細節設定未套用：雜色減少（明度）、雜色減少（顏色）")
        mixed = await (await self.client.get("/api/presets/p-mixed")).json()
        self.assertEqual(mixed["banner"], "這個 preset 有 1 項會改變觀感的設定無法套用：色溫（絕對值）")
        self.assertEqual(mixed["note"], SKIP_NOTE.replace("{n}", "1").replace("{items_joined_by_、}", "雜色減少（明度）"))
        clean = await (await self.client.get("/api/presets/p-expo")).json()
        self.assertEqual((clean["banner"], clean["note"]), ("", ""))
        self.assertEqual(clean["values"]["Exposure2012"], 1.0)
        self.assertEqual(clean["values"]["GrainSize"], 25.0)  # default from the core table
        r = await self.client.get("/api/presets/nope")
        self.assertEqual(r.status, 404)

    async def test_preset_flags(self):  # R4
        flags = await (await self.client.get("/api/preset_flags")).json()
        self.assertEqual(flags, {"p-skip": "major", "p-mixed": "major", "p-minor": "minor"})
        rows = await (await self.client.get("/api/presets")).json()
        for row in rows:
            self.assertEqual(set(row), {"id", "group", "name", "supported", "skipped"})   # B3 unchanged

    async def test_api_preset_detail_curves(self):  # R6
        d = await (await self.client.get("/api/presets/p-mixed")).json()
        self.assertEqual(d["curves"], {"ToneCurvePV2012": [[0.0, 20.0], [128.0, 140.0], [255.0, 240.0]],
                                       "ToneCurvePV2012Red": [[0.0, 0.0], [255.0, 230.0]]})
        e = await (await self.client.get("/api/presets/p-expo")).json()
        self.assertEqual(e["curves"], {})

    def test_skip_levels(self):  # R4
        from darkroom_app import skips
        major = ["Temperature", "Tint", "Look（Adobe Color）", "CameraProfile（Camera Vivid）", "HDREditMode",
                 "WhiteBalance（Auto）", "Mask/Brush", "CorrectionRangeMask", "PointColors", "ColorVariance",
                 "MaskGroupBasedCorrections", "SomethingNew"]
        minor = ["ColorNoiseReduction", "LuminanceSmoothing", "LuminanceNoiseReductionDetail",
                 "LuminanceNoiseReductionContrast", "ColorNoiseReductionDetail", "ColorNoiseReductionSmoothness",
                 "SharpenDetail", "SharpenEdgeMasking", "GrainFrequency", "AutoLateralCA", "LensProfileEnable",
                 "LensProfileVignettingScale", "LensProfileDistortionScale", "DefringePurpleAmount",
                 "DefringeGreenHueLo", "VignetteAmount", "VignetteMidpoint", "PostCropVignetteHighlightContrast",
                 "PostCropVignetteStyle", "PostCropVignetteRoundness（負值）", "Contrast2012（超出範圍，已夾值）"]
        for item in major:
            self.assertEqual(skips.level(item), "major", item)
        for item in minor:
            self.assertEqual(skips.level(item), "minor", item)
        for item in major + minor:
            label = skips.label(item)
            self.assertTrue(label)
            if item != "SomethingNew":
                self.assertRegex(label, r"[一-鿿]", item)   # Chinese name
        self.assertEqual(skips.label("Contrast2012（超出範圍，已夾值）"), "對比（超出範圍，已夾值）")
        self.assertEqual(skips.label("SomethingNew"), "SomethingNew")

    async def test_library_items_all_labelled(self):  # R4: every item in the user's library has a Chinese name
        from darkroom import load_preset
        from darkroom_app import skips
        unknown = set()
        for f in _util.preset_files():
            for item in load_preset(f).skipped:
                if skips.label(item) == item:
                    unknown.add(item)
        self.assertEqual(unknown, set())

    async def test_sliders_agree_with_core_tables(self):
        from darkroom import _coverage, _params
        data = await (await self.client.get("/api/sliders")).json()
        self.assertTrue(data["sliders"])
        for s in data["sliders"]:
            self.assertIn(s["key"], _coverage.RENDERED, s["key"])
            self.assertEqual((s["min"], s["max"]), _params.value_range(s["key"]), s["key"])
            self.assertEqual(s["default"], _params.default(s["key"]), s["key"])
            self.assertEqual(s["hue"], _params.is_hue_angle(s["key"]), s["key"])


class TestOpen(AppCase):  # B4
    async def test_api_open_shape(self):
        path = write_photo(os.path.join(self.photos, "big.png"), 2400, 1601)
        before = snapshot(self.photos)
        r = await self.client.post("/api/open", json={"path": path})
        self.assertEqual(r.status, 200)
        info = await r.json()
        self.assertEqual(set(info), {"image_id", "width", "height", "preview_width", "preview_height"})
        self.assertEqual((info["width"], info["height"]), (2400, 1601))
        pw, ph = info["preview_width"], info["preview_height"]
        self.assertLessEqual(pw * ph, PREVIEW_MAX)
        self.assertGreater(pw * ph, PREVIEW_MAX * 0.99)
        self.assertAlmostEqual(pw / ph, 2400 / 1601, delta=2400 / 1601 / min(pw, ph))
        self.assertEqual(snapshot(self.photos), before)  # read-only
        small = write_photo(os.path.join(self.photos, "small.jpg"), 300, 200)
        info = await (await self.client.post("/api/open", json={"path": small})).json()
        self.assertEqual((info["preview_width"], info["preview_height"]), (300, 200))

    def test_preview_size_rule(self):
        from darkroom_app.engine import preview_size
        for w, h in ((6000, 4000), (4000, 6000), (8192, 5464), (1501, 1000), (1225, 1225), (9000, 100), (1, 1),
                     (5472, 3648), (1000, 1500)):
            pw, ph = preview_size(w, h)
            self.assertLessEqual(pw * ph, PREVIEW_MAX, (w, h))
            self.assertLessEqual(pw, w)
            self.assertLessEqual(ph, h)
            self.assertLessEqual(abs(pw * h - ph * w), max(w, h), (w, h, pw, ph))  # within one pixel of the ratio

    async def test_open_errors(self):
        r = await self.client.post("/api/open", json={"path": os.path.join(self.photos, "missing.jpg")})
        self.assertEqual(r.status, 404)
        txt = os.path.join(self.photos, "notes.txt")
        with open(txt, "w") as f:
            f.write("x")
        r = await self.client.post("/api/open", json={"path": txt})
        self.assertEqual(r.status, 400)
        bad = os.path.join(self.photos, "broken.jpg")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        r = await self.client.post("/api/open", json={"path": bad})
        self.assertEqual(r.status, 400)


class TestPreview(AppCase):  # B5
    async def test_api_preview_semantics(self):
        _, info = await self.open_photo()
        iid = info["image_id"]
        r, data = await self.preview(image_id=iid, preset_id="p-expo", strength=100, overrides={})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/jpeg")
        self.assertGreaterEqual(float(r.headers["X-Render-Ms"]), 0.0)
        img = decode(data)
        self.assertEqual(img.shape, (info["preview_height"], info["preview_width"], 3))
        # preset null and no overrides = the photo itself
        r, data0 = await self.preview(image_id=iid, preset_id=None, strength=100, overrides={})
        self.assertEqual(r.status, 200)
        eng = self.app[__import__("darkroom_app.server", fromlist=["ENGINE"]).ENGINE]
        orig = eng.get(iid)["tensor"][0].permute(1, 2, 0).cpu().numpy()
        self.assertLess(float(np.abs(decode(data0) - orig).mean()), 0.01)
        # preset null: only the overrides apply
        r, data1 = await self.preview(image_id=iid, preset_id=None, strength=100, overrides={"Exposure2012": 1.0})
        self.assertGreater(float(decode(data1).mean()), float(decode(data0).mean()) + 0.05)

    async def test_overrides_added_after_strength(self):
        from darkroom_app.preview import effective_params
        from darkroom_app.server import LIBRARY, ENGINE
        lib, eng = self.app[LIBRARY], self.app[ENGINE]
        p = lib.get("p-expo")
        e = effective_params(p, 0.5, {"Exposure2012": 0.3, "SplitToningShadowHue": 30.0})
        self.assertAlmostEqual(e.values["Exposure2012"], 0.8)          # 0 + 0.5 * (1.0 - 0) + 0.3
        self.assertAlmostEqual(e.values["Contrast2012"], 20.0)         # strength only
        self.assertAlmostEqual(e.values["SplitToningShadowHue"], 230.0)  # hue angle not scaled, then + 30
        self.assertAlmostEqual(e.values["SplitToningShadowSaturation"], 15.0)
        strong = effective_params(lib.get("p-strong"), 1.0, {"Exposure2012": 2.0})
        self.assertEqual(strong.values["Exposure2012"], 5.0)            # clamp(4.5 + 2) = 5
        low = effective_params(lib.get("p-strong"), 1.0, {"Exposure2012": -20.0})
        self.assertEqual(low.values["Exposure2012"], -5.0)
        none = effective_params(None, 1.0, {"Contrast2012": 10.0, "GrainSize": 5.0})
        self.assertEqual(none.values, {"Contrast2012": 10.0, "GrainSize": 30.0})   # GrainSize default 25 + 5
        # the endpoint renders exactly these values
        _, info = await self.open_photo()
        iid = info["image_id"]
        r, data = await self.preview(image_id=iid, preset_id="p-expo", strength=50, overrides={"Exposure2012": 0.3})
        self.assertEqual(r.status, 200)
        expect = Params(values={"Exposure2012": 0.8, "Contrast2012": 20.0, "SplitToningShadowHue": 200.0,
                                "SplitToningShadowSaturation": 15.0})
        wrong = Params(values={"Exposure2012": 0.65, "Contrast2012": 20.0, "SplitToningShadowHue": 200.0,
                               "SplitToningShadowSaturation": 15.0})   # strength applied after the override
        loop = asyncio.get_running_loop()
        good_bytes, _ = await loop.run_in_executor(eng.executor, eng.preview, iid, expect)
        wrong_bytes, _ = await loop.run_in_executor(eng.executor, eng.preview, iid, wrong)
        got = decode(data)
        d_good = float(np.abs(got - decode(good_bytes)).mean())
        d_wrong = float(np.abs(got - decode(wrong_bytes)).mean())
        self.assertLess(d_good, 0.002)
        self.assertGreater(d_wrong, 10 * d_good + 0.005)

    async def test_overrides_added_after_clamped_strength(self):  # R3
        from darkroom_app.preview import effective_params
        from darkroom_app.server import LIBRARY
        lib = self.app[LIBRARY]
        e = effective_params(lib.get("p-strong"), 2.0, {"Exposure2012": -1.0})
        self.assertEqual(e.values["Exposure2012"], 4.0)     # clamp(clamp(4.5 * 2) - 1) = 4, not clamp(9 - 1) = 5
        e = effective_params(lib.get("p-strong"), 2.0, {})
        self.assertEqual(e.values["Exposure2012"], 5.0)
        e = effective_params(lib.get("p-expo"), 1.5, {"Contrast2012": 10.0})
        self.assertEqual(e.values["Contrast2012"], 70.0)    # 60 is inside the range: plain sum

    async def test_preview_validation(self):
        _, info = await self.open_photo()
        iid = info["image_id"]
        for body, status in (({"image_id": "x", "preset_id": None, "strength": 100, "overrides": {}}, 404),
                             ({"image_id": iid, "preset_id": "nope", "strength": 100, "overrides": {}}, 404),
                             ({"image_id": iid, "preset_id": "p-old", "strength": 100, "overrides": {}}, 404),
                             ({"image_id": iid, "preset_id": None, "strength": 250, "overrides": {}}, 400),
                             ({"image_id": iid, "preset_id": None, "strength": -1, "overrides": {}}, 400),
                             ({"image_id": iid, "preset_id": None, "strength": 100, "overrides": {"Bogus": 1}}, 400),
                             ({"image_id": iid, "preset_id": None, "strength": 100,
                               "overrides": {"Exposure2012": "1"}}, 400)):
            r, _ = await self.preview(**body)
            self.assertEqual(r.status, status, body)
        r, _ = await self.preview(image_id=iid, preset_id="p-expo", strength=0, overrides={})
        self.assertEqual(r.status, 200)
        r, _ = await self.preview(image_id=iid, preset_id="p-expo", strength=200, overrides={})
        self.assertEqual(r.status, 200)


class TestGpuDiscipline(AppCase):  # B6
    async def test_preview_on_own_high_priority_stream(self):
        import torch
        if not torch.cuda.is_available():
            self.skipTest("needs CUDA")
        from darkroom_app import engine as engine_mod
        from darkroom_app.server import ENGINE
        eng = self.app[ENGINE]
        self.assertEqual(eng.executor._max_workers, 1)
        self.assertIsNotNone(eng.stream)
        self.assertEqual(eng.stream.priority, torch.cuda.Stream.priority_range()[1])
        self.assertLess(eng.stream.priority, 0)
        _, info = await self.open_photo()
        seen = {}
        real_render, real_encode = engine_mod.render, engine_mod.cv2.imencode

        def spy_render(img, params, strength=1.0, device=None):
            seen["stream"] = torch.cuda.current_stream()
            seen["thread"] = threading.current_thread().name
            seen["input_device"] = img.device.type
            out = real_render(img, params, strength=strength, device=device)
            seen["output_device"] = out.device.type
            return out

        def spy_encode(ext, arr, *a):
            seen["encode_input"] = type(arr).__name__
            return real_encode(ext, arr, *a)

        def no_device_sync(*a, **k):
            raise AssertionError("torch.cuda.synchronize() called on the preview path")
        with mock.patch.object(engine_mod, "render", spy_render), \
                mock.patch.object(engine_mod.cv2, "imencode", spy_encode), \
                mock.patch("torch.cuda.synchronize", no_device_sync):
            r, _ = await self.preview(image_id=info["image_id"], preset_id="p-expo", strength=100, overrides={})
        self.assertEqual(r.status, 200)
        self.assertEqual(seen["stream"], eng.stream)
        self.assertTrue(seen["thread"].startswith("darkroom-gpu"), seen["thread"])
        self.assertEqual((seen["input_device"], seen["output_device"]), ("cuda", "cuda"))
        self.assertEqual(seen["encode_input"], "ndarray")

    def test_no_device_wide_sync_in_app_source(self):
        app = os.path.join(_util.REPO, "darkroom_app")
        for f in os.listdir(app):
            if f.endswith(".py"):
                with open(os.path.join(app, f), encoding="utf-8") as fh:
                    self.assertNotIn("torch.cuda.synchronize", fh.read(), f)

    async def test_preview_does_not_block_event_loop(self):
        from darkroom_app.server import ENGINE
        eng = self.app[ENGINE]
        _, info = await self.open_photo()

        def slow_preview(image_id, params):
            time.sleep(0.8)
            return b"\xff\xd8\xff\xd9", 800.0
        with mock.patch.object(eng, "preview", slow_preview):
            task = asyncio.ensure_future(self.preview(image_id=info["image_id"], preset_id=None, strength=100,
                                                      overrides={}))
            await asyncio.sleep(0.1)
            t0 = time.perf_counter()
            r = await self.client.get("/api/health")
            took = time.perf_counter() - t0
            self.assertEqual(r.status, 200)
            self.assertLess(took, 0.3)
            self.assertFalse(task.done())
            await task


class TestFolder(AppCase):  # B8
    async def test_api_folder(self):
        for n in ("a.jpg", "B.png", "c.tif", "e.jpeg", "F.tiff"):
            write_photo(os.path.join(self.photos, n), 64, 48)
        with open(os.path.join(self.photos, "d.txt"), "w") as f:
            f.write("x")
        os.makedirs(os.path.join(self.photos, "g.jpg"))   # a folder, not a photo
        _, info = await self.open_photo("c.tif")
        r = await self.client.get("/api/folder", params={"image_id": info["image_id"]})
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertEqual([f["name"] for f in data["files"]], ["a.jpg", "B.png", "c.tif", "e.jpeg", "F.tiff"])
        self.assertEqual(data["index"], 2)
        self.assertEqual(os.path.normcase(data["folder"]), os.path.normcase(os.path.abspath(self.photos)))
        for f in data["files"]:
            self.assertTrue(os.path.isfile(f["path"]))
        r = await self.client.get("/api/folder", params={"image_id": "nope"})
        self.assertEqual(r.status, 404)


class TestNeverWrites(AppCase):  # B12
    async def test_server_never_writes(self):
        for n in ("a.jpg", "b.png", "c.tif"):
            write_photo(os.path.join(self.photos, n), 640, 480)
        before = snapshot(self.photos, self.presets)
        names_before = {d: sorted(os.listdir(d)) for d in (self.photos, self.presets)}
        writes = []
        real_open = builtins.open
        guarded = [os.path.normcase(os.path.abspath(d)) for d in (self.photos, self.presets)]

        def spy_open(file, mode="r", *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+"):
                p = os.path.normcase(os.path.abspath(os.fsdecode(file)))
                if any(p.startswith(g) for g in guarded):
                    writes.append(p)
            return real_open(file, mode, *a, **k)
        with mock.patch("builtins.open", spy_open):
            await self.client.get("/api/presets")
            for pid in ("p-expo", "p-skip"):
                await self.client.get(f"/api/presets/{pid}")
            for n in ("a.jpg", "b.png", "c.tif"):
                _, info = await self.open_photo(n)
                for pid, s in (("p-expo", 100), ("p-skip", 150), (None, 100)):
                    r, _ = await self.preview(image_id=info["image_id"], preset_id=pid, strength=s,
                                              overrides={"Exposure2012": 0.2})
                    self.assertEqual(r.status, 200)
                await self.client.get("/api/folder", params={"image_id": info["image_id"]})
        self.assertEqual(writes, [])
        self.assertEqual(snapshot(self.photos, self.presets), before)
        self.assertEqual({d: sorted(os.listdir(d)) for d in (self.photos, self.presets)}, names_before)

    def test_app_has_no_write_path(self):
        app = os.path.join(_util.REPO, "darkroom_app")
        for root, _, files in os.walk(app):
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(root, f), encoding="utf-8") as fh:
                        src = fh.read()
                    self.assertNotIn("write_image", src, f)
                    self.assertNotIn("imwrite", src, f)


if __name__ == "__main__":
    unittest.main()
