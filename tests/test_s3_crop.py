"""CONTRACT-s3-crop C1-C20, C28: geometry (rotate / flip / straighten / crop) in the core, the photo library, previews,
thumbnails, exports and the three interfaces.

Every photo, preset folder and data_dir lives in a fixture root (G7: the real preset library is only read by
test_library_has_no_crop_presets, and %LOCALAPPDATA%/darkroom is never touched).
"""
import builtins
import contextlib
import io
import json
import math
import os
import statistics
import subprocess
import time
import unittest
from unittest import mock

import cv2
import numpy as np
import torch

import _util
import _xmpgen
from darkroom import Geometry, Params, load_preset, read_image, render
from test_app_server import make_presets, write_photo
from test_export import pattern, write_jpeg

HAS_CUDA = torch.cuda.is_available()
CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")
# verbatim (C1 constants "invalid")
NOT_OBJECT = "幾何要是物件或 null：{geometry}"
UNKNOWN_KEY = "幾何設定不認得的鍵：{key}（可用 rotate、flip、angle、aspect、crop）"
BAD_ROTATE = "rotate 要是 0、90、180、270 其中之一：{rotate}"
BAD_FLIP = "flip 必須是 true 或 false"
BAD_ANGLE = "拉直角度要在 -45～45 度之間：{angle}"
BAD_ASPECT = "不支援的裁切比例：{aspect}（可用 original、free，或「寬:高」兩個 1～65535 的整數）"
BAD_CROP = '裁切框要是 {"left","top","right","bottom"}，而且 0 ≤ left < right ≤ 1、0 ≤ top < bottom ≤ 1：{crop}'
FRAME_INVALID = "frame 必須是 true 或 false"
WITH_GEOMETRY_INVALID = "with_geometry 必須是 true 或 false"
GEOMETRY_ONLY = "只有幾何不能只貼顏色：這份編輯只有裁切／旋轉，要貼上請連同幾何一起貼（with_geometry）"
CLI_BAD_CROP = "--crop 要是 L,T,R,B 四個 0～1 的數：{value}"
PRESET_CROP = "裁切（preset 帶的裁切與拉直不會套用）"
PRESET_CROP_LABEL = "裁切（preset 帶的，不套用）"
EDIT_KEYS_V2 = ["schema", "fingerprint", "preset", "strength", "overrides", "geometry"]   # verbatim order (C12)


def crop_msg(crop):
    return BAD_CROP.replace("{crop}", crop)


def G(rotate=0, flip=False, angle=0, aspect="original", crop=None):
    return {"rotate": rotate, "flip": flip, "angle": angle, "aspect": aspect,
            "crop": None if crop is None else dict(zip(("left", "top", "right", "bottom"), crop))}


def geo(**kw):
    return Geometry.from_dict(G(**kw))


def cases(name):
    with open(os.path.join(CASES, name), encoding="utf-8") as f:
        return json.load(f)["cases"]


def rand_img(h, w, seed=0):
    return np.random.default_rng(seed).random((h, w, 3), dtype=np.float32)


def smooth_img(h, w):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.clip(np.stack([xx / w, yy / h, 0.5 + 0.3 * np.sin(xx / 37.0) * np.cos(yy / 23.0)], -1), 0, 1)


def mad(a, b):
    return float(np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64)).mean())


def mask_params():
    """Exposure +1 only inside a linear gradient at the top (0..0.3) and a radial gradient in the lower left."""
    return Params(masks=[
        {"name": "top", "amount": 1.0, "values": {"LocalExposure2012": 1.0},
         "shapes": [{"type": "Mask/Gradient", "inverted": False, "opacity": 1.0,
                     "ZeroX": 0.5, "ZeroY": 0.3, "FullX": 0.5, "FullY": 0.0}]},
        {"name": "radial", "amount": 1.0, "values": {"LocalExposure2012": 0.8},
         "shapes": [{"type": "Mask/CircularGradient", "inverted": False, "opacity": 1.0, "Top": 0.55, "Left": 0.05,
                     "Bottom": 0.95, "Right": 0.4, "Angle": 20.0, "Feather": 50.0, "Flipped": True}]}])


# ---------------------------------------------------------------- C1-C5: the geometry object, the box, the map
class TestGeometryObject(unittest.TestCase):
    def test_geometry_validate_and_canonical(self):  # C1
        from darkroom import _geometry as gm
        self.assertEqual((gm.NOT_OBJECT, gm.UNKNOWN_KEY, gm.BAD_ROTATE, gm.BAD_FLIP, gm.BAD_ANGLE, gm.BAD_ASPECT),
                         (NOT_OBJECT, UNKNOWN_KEY, BAD_ROTATE, BAD_FLIP, BAD_ANGLE, BAD_ASPECT))
        self.assertEqual(gm.BAD_CROP.format(crop="x"), BAD_CROP.replace("{crop}", "x"))
        self.assertEqual(gm.KEYS, ("rotate", "flip", "angle", "aspect", "crop"))
        bad = [("x", NOT_OBJECT.format(geometry="x")), (5, NOT_OBJECT.format(geometry="5")),
               ([0], NOT_OBJECT.format(geometry="[0]")),
               ({"zoom": 2}, UNKNOWN_KEY.format(key="zoom")),
               ({"rotate": 45}, BAD_ROTATE.format(rotate="45")), ({"rotate": True}, BAD_ROTATE.format(rotate="true")),
               ({"rotate": "90"}, BAD_ROTATE.format(rotate="90")), ({"rotate": -90}, BAD_ROTATE.format(rotate="-90")),
               ({"flip": "yes"}, BAD_FLIP), ({"flip": 1}, BAD_FLIP),
               ({"angle": 46}, BAD_ANGLE.format(angle="46")), ({"angle": -45.5}, BAD_ANGLE.format(angle="-45.5")),
               ({"angle": True}, BAD_ANGLE.format(angle="true")), ({"angle": float("nan")}, BAD_ANGLE.format(angle="NaN")),
               ({"aspect": "0:3"}, BAD_ASPECT.format(aspect="0:3")), ({"aspect": "3:0"}, BAD_ASPECT.format(aspect="3:0")),
               ({"aspect": "65536:1"}, BAD_ASPECT.format(aspect="65536:1")), ({"aspect": "16/9"}, BAD_ASPECT.format(aspect="16/9")),
               ({"aspect": "４:5"}, BAD_ASPECT.format(aspect="４:5")), ({"aspect": 4}, BAD_ASPECT.format(aspect="4")),
               ({"crop": {"left": 0.6, "top": 0, "right": 0.4, "bottom": 1}},
                crop_msg('{"left": 0.6, "top": 0, "right": 0.4, "bottom": 1}')),
               ({"crop": {"left": 0, "top": 0, "right": 1}}, crop_msg('{"left": 0, "top": 0, "right": 1}')),
               ({"crop": {"left": 0, "top": 0, "right": 1, "bottom": 1, "x": 1}},
                crop_msg('{"left": 0, "top": 0, "right": 1, "bottom": 1, "x": 1}')),
               ({"crop": {"left": False, "top": 0, "right": 1, "bottom": 1}},
                crop_msg('{"left": false, "top": 0, "right": 1, "bottom": 1}')),
               ({"crop": {"left": 0, "top": 0, "right": 1.5, "bottom": 1}},
                crop_msg('{"left": 0, "top": 0, "right": 1.5, "bottom": 1}')),
               ({"crop": [0, 0, 1, 1]}, crop_msg("[0, 0, 1, 1]"))]
        for obj, sentence in bad:
            with self.assertRaises(ValueError, msg=repr(obj)) as cm:
                Geometry.from_dict(obj)
            self.assertEqual(str(cm.exception), sentence, repr(obj))
        self.assertIsNone(Geometry.from_dict(None))
        for ident in (G(), G(aspect="4:5"), G(aspect="free"), {}, {"angle": -0.0}):    # identity -> null, any aspect
            self.assertIsNone(Geometry.from_dict(ident).to_dict(), ident)
            self.assertTrue(Geometry.from_dict(ident).identity)
        g = Geometry.from_dict(G(rotate=90, angle=5.0, aspect="8:10", crop=(0.0, 0.25, 1.0, 0.75)))
        self.assertEqual(list(g.to_dict()), ["rotate", "flip", "angle", "aspect", "crop"])
        self.assertEqual(g.to_dict(), {"rotate": 90, "flip": False, "angle": 5, "aspect": "4:5",
                                       "crop": {"left": 0, "top": 0.25, "right": 1, "bottom": 0.75}})
        self.assertEqual(json.dumps(g.to_dict()), json.dumps(Geometry.from_dict(g.to_dict()).to_dict()))   # stable
        # implementation patch: a missing key takes its identity value
        self.assertEqual(Geometry.from_dict({"rotate": 270}).to_dict(), G(rotate=270))
        self.assertEqual(Geometry.from_dict({"aspect": "1920:1080", "flip": True}).aspect, "16:9")

    def test_geometry_shared_cases(self):  # C3: the same table as tests/js (L.fitCrop)
        table = cases("s3_geometry_cases.json")
        self.assertGreaterEqual(len(table), 40)
        names = " | ".join(c["name"] for c in table)
        for need in ("rotate 90", "rotate 180", "rotate 270", "flip", "angle 0.1", "angle -0.1", "angle 12.5",
                     "angle -12.5", "angle 45", "angle -45", "4:5", "16:9", "free", "outside the picture",
                     "blank corner", "reset", "1 pixel edge", "square photo", "orientation 6"):
            self.assertIn(need, names)
        for c in table:
            r = Geometry.from_dict(c["geometry"]).resolve(c["width"], c["height"])
            for a, b in zip(r["box"], c["expect"]["box"]):
                self.assertLessEqual(abs(a - b), 1e-9, c["name"])
            for k in ("left", "top", "right", "bottom", "width", "height"):
                self.assertEqual(r[k], c["expect"][k], f'{c["name"]}: {k}')
            self.assertEqual(Geometry.from_dict(c["geometry"]).output_size(c["width"], c["height"]),
                             (c["expect"]["width"], c["expect"]["height"]))
            self.assertEqual((r["width"], r["height"]), (r["right"] - r["left"], r["bottom"] - r["top"]))

    def test_resolve_rules(self):  # C3 steps (1)-(5) on hand-checked boxes
        self.assertEqual(geo(flip=True, aspect="1:1").resolve(400, 300)["left"], 50)           # (1) centred 300 x 300
        r = geo(flip=True, aspect="free", crop=(0.1, 0.2, 0.7, 0.9)).resolve(400, 300)        # angle 0: kept as given
        self.assertEqual((r["left"], r["top"], r["right"], r["bottom"]), (40, 60, 280, 270))
        r = geo(flip=True, aspect="4:5", crop=(0.25, 0.25, 0.75, 0.75)).resolve(400, 400)     # (2) same centre and area
        self.assertAlmostEqual((r["box"][2] - r["box"][0]) / (r["box"][3] - r["box"][1]), 0.8, places=9)
        self.assertAlmostEqual(r["box"][0] + r["box"][2], 1.0, places=9)
        r = geo(angle=30, aspect="free", crop=(0.0, 0.0, 0.04, 0.05)).resolve(600, 400)        # (3) blank corner
        self.assertAlmostEqual((r["box"][0] + r["box"][2]) / 2, 0.5, places=9)
        before = geo(angle=10, aspect="free", crop=(0.3, 0.3, 0.7, 0.7)).resolve(600, 400)["box"]
        self.assertEqual([round(v, 12) for v in before], [0.3, 0.3, 0.7, 0.7])                 # (4) never enlarged
        tiny = geo(flip=True, aspect="free", crop=(0.5, 0.5, 0.5001, 0.5001)).resolve(600, 400)
        self.assertEqual((tiny["width"], tiny["height"]), (1, 1))                               # (5) at least 1 x 1

    def test_geometry_inverse_map_cases(self):  # C2 constant "反向對應", written out here from the contract
        def ref(g, W, H, X, Y):
            fw, fh = (H, W) if g.rotate in (90, 270) else (W, H)
            r = g.resolve(W, H)
            p = (r["left"] + X, r["top"] + Y)
            th = math.radians(-g.angle)
            d = (p[0] - fw / 2, p[1] - fh / 2)
            q = (math.cos(th) * d[0] - math.sin(th) * d[1] + fw / 2, math.sin(th) * d[0] + math.cos(th) * d[1] + fh / 2)
            if g.flip:
                q = (fw - q[0], q[1])
            return {0: (q[0], q[1]), 90: (q[1], H - q[0]), 180: (W - q[0], H - q[1]), 270: (W - q[1], q[0])}[g.rotate]
        rng = np.random.default_rng(3)
        for c in cases("s3_geometry_cases.json"):
            g = Geometry.from_dict(c["geometry"])
            M = g.matrix(c["width"], c["height"])
            for _ in range(5):
                X, Y = rng.uniform(0, g.output_size(c["width"], c["height"])[0]), rng.uniform(0, 3)
                got = M @ np.array([X, Y, 1.0])
                want = ref(g, c["width"], c["height"], X, Y)
                self.assertLess(max(abs(got[0] - want[0]), abs(got[1] - want[1])), 1e-6, c["name"])
        # pixel centres: output (0.5, 0.5) of a plain rotate 90 is the source's bottom-left pixel centre
        np.testing.assert_allclose(geo(rotate=90).matrix(4, 2) @ np.array([0.5, 0.5, 1.0]), [0.5, 1.5])


class TestGeometryRender(unittest.TestCase):
    def test_geometry_rotate_flip_exact(self):  # C2: angle 0 = rot90 / fliplr, byte for byte (GPU and CPU)
        src = rand_img(48, 64)
        for r in (0, 90, 180, 270):
            for flip in (False, True):
                g = geo(rotate=r, flip=flip)
                want = np.rot90(src, k=-(r // 90))
                want = want[:, ::-1] if flip else want
                if r == 0 and not flip:
                    self.assertIsNone(g.to_dict())
                    continue
                self.assertTrue(np.array_equal(render(src, Params(), geometry=g), want), (r, flip))
                self.assertTrue(np.array_equal(g.apply(src), want), (r, flip))
                u8 = (src * 255).astype(np.uint8)
                self.assertTrue(np.array_equal(g.apply(u8), np.ascontiguousarray(
                    (np.rot90(u8, k=-(r // 90))[:, ::-1] if flip else np.rot90(u8, k=-(r // 90))))))

    def test_geometry_crop_exact_slice(self):  # C2
        src = rand_img(300, 400, 1)
        g = geo(aspect="free", crop=(0.1, 0.2, 0.7, 0.9))
        self.assertTrue(np.array_equal(render(src, Params(), geometry=g), src[60:270, 40:280]))
        g = geo(rotate=90, aspect="free", crop=(0.25, 0.5, 0.75, 1.0))
        self.assertTrue(np.array_equal(render(src, Params(), geometry=g), np.rot90(src, k=-1)[200:400, 75:225]))
        t = torch.from_numpy(src).permute(2, 0, 1)                                          # a tensor stays one
        out = render(t, Params(), geometry=g)
        self.assertEqual(tuple(out.shape), (3, 200, 150))

    def test_geometry_actions_match_pixels(self):  # C4: the operation table checked with pixels
        p = Params(values={"Exposure2012": 0.4, "Saturation": 20.0})
        turn = {"rotate_right": lambda a: np.rot90(a, k=-1), "rotate_left": lambda a: np.rot90(a, k=1),
                "flip_h": lambda a: a[:, ::-1], "flip_v": lambda a: a[::-1]}
        checked = 0
        for c in cases("s3_geometry_actions.json"):
            if c["action"] not in turn:
                continue
            src = rand_img(c["height"], c["width"], 5)
            before = render(src, p, geometry=Geometry.from_dict(c["before"]))
            after = render(src, p, geometry=Geometry.from_dict(c["after"]))
            want = np.ascontiguousarray(turn[c["action"]](before))
            self.assertEqual(after.shape, want.shape, c["name"])
            if c["before"]["angle"] == 0 and torch.cuda.is_available():
                self.assertTrue(np.array_equal(after, want), c["name"])
            elif c["before"]["angle"] == 0:
                # CPU torch (CI runners have no GPU): the colour pipeline's float reductions are not
                # bit-identical once the picture is turned / mirrored, so a turn is exact only up to float noise.
                self.assertLessEqual(mad(after, want), 1e-6, c["name"])
            else:
                self.assertLessEqual(mad(after, want), 1 / 255, c["name"])
            checked += 1
        self.assertGreaterEqual(checked, 40)

    def test_render_without_geometry_unchanged(self):  # C6: None (and an identity) = today's bytes
        img = rand_img(120, 160, 2)
        p = Params(values={"Exposure2012": 0.5, "Clarity2012": 30.0, "Dehaze": 20.0, "PostCropVignetteAmount": -30.0,
                           "GrainAmount": 20.0, "Sharpness": 40.0})
        a = render(img, p)
        self.assertTrue(np.array_equal(a, render(img, p, geometry=None)))
        self.assertTrue(np.array_equal(a, render(img, p, geometry=geo(aspect="4:5"))))
        with self.assertRaises(TypeError):
            render(img, p, geometry={"rotate": 90})

    def test_geometry_module_torch_free(self):  # C6: the core's Geometry never loads torch (thumbnails, L9)
        code = ("import sys, numpy as np; import darkroom; from darkroom import Geometry; "
                "g = Geometry.from_dict({'rotate': 90, 'flip': True, 'angle': 7.5, 'aspect': '4:5', 'crop': None}); "
                "g.resolve(600, 400); g.apply(np.zeros((40, 60, 3), np.uint8)); print('torch' in sys.modules)")
        r = subprocess.run([*_util.guarded_python(), "-c", code], capture_output=True, cwd=_util.REPO, timeout=120)
        self.assertEqual(r.stdout.decode().strip(), "False", r.stderr.decode("utf-8", "replace"))

    def test_vignette_is_post_crop(self):  # C7: the vignette belongs to the cropped picture
        src = smooth_img(96, 128)
        p = Params(values={"PostCropVignetteAmount": -60.0, "PostCropVignetteMidpoint": 30.0})
        g = geo(aspect="free", crop=(0.25, 0.25, 0.75, 0.75))
        cut = np.ascontiguousarray(src[24:72, 32:96])
        out = render(src, p, geometry=g)
        self.assertLessEqual(float(np.abs(out - render(cut, p)).max()), 1e-5)
        self.assertGreater(mad(out, render(src, p)[24:72, 32:96]), 1e-3)        # not "render, then cut"

    def test_masks_follow_content(self):  # C8: the gradients stay on the same content
        src = smooth_img(80, 120) * 0.5
        p = mask_params()
        full = render(src, p)
        self.assertGreater(mad(full, src), 1e-3)                                  # the masks really do something
        self.assertTrue(np.array_equal(render(src, p, geometry=geo(rotate=90)), np.rot90(full, k=-1)))
        self.assertTrue(np.array_equal(render(src, p, geometry=geo(flip=True)), full[:, ::-1]))
        self.assertTrue(np.array_equal(render(src, p, geometry=geo(rotate=270, flip=True)),
                                       np.rot90(full, k=1)[:, ::-1]))
        lower = render(src, p, geometry=geo(aspect="free", crop=(0.0, 0.5, 1.0, 1.0)))
        self.assertLessEqual(float(np.abs(lower - full[40:]).max()), 1e-5)
        g = geo(angle=10)
        same_warp = render(full, Params(), geometry=g)                           # the same resampling of the result
        self.assertLessEqual(mad(render(src, p, geometry=g), same_warp), 1 / 255)

    def test_degenerate_masks_with_geometry(self):  # seal F1 (C8): a mask with no area still renders, at the output size
        src = smooth_img(60, 80) * 0.5
        flat = {"type": "Mask/Gradient", "inverted": False, "opacity": 1.0, "ZeroX": 0.4, "ZeroY": 0.4, "FullX": 0.4,
                "FullY": 0.4}
        thin = {"type": "Mask/CircularGradient", "inverted": True, "opacity": 1.0, "Top": 0.2, "Left": 0.5, "Bottom": 0.8,
                "Right": 0.5, "Angle": 0.0, "Feather": 50.0, "Flipped": True}
        good = mask_params().masks[0]
        for shapes in ([flat], [thin], [flat, good["shapes"][0]]):
            p = Params(masks=[{"name": "m", "amount": 1.0, "values": {"LocalExposure2012": 0.25}, "shapes": shapes}])
            full = render(src, p)
            self.assertTrue(np.array_equal(render(src, p, geometry=geo(rotate=90)), np.rot90(full, k=-1)), shapes)
            lower = render(src, p, geometry=geo(aspect="free", crop=(0.0, 0.5, 1.0, 1.0)))
            self.assertLessEqual(float(np.abs(lower - full[30:]).max()), 1e-5)
            tilted = render(src, p, geometry=geo(angle=5))
            self.assertEqual(tilted.shape[:2], tuple(reversed(geo(angle=5).output_size(80, 60))))

    def test_geometry_cpu_matches_gpu(self):  # C9 (M2): grid_sample bicubic vs cv2.warpAffine INTER_CUBIC
        u8 = (smooth_img(300, 420) * 255 + 0.5).astype(np.uint8)
        u8 = np.clip(u8.astype(int) + np.random.default_rng(0).integers(-30, 30, u8.shape), 0, 255).astype(np.uint8)
        for a in (0.1, 7.5, -12.5, 45):
            for g in (geo(angle=a), geo(rotate=90, flip=True, angle=a, aspect="3:2")):
                gpu = (render(u8, Params(), geometry=g) * 255 + 0.5).astype(np.uint8)
                cpu = g.apply(u8)
                self.assertEqual(gpu.shape, cpu.shape)
                d = np.abs(gpu.astype(int) - cpu.astype(int))
                self.assertLessEqual(d.mean(), 1 / 255, a)
                self.assertLessEqual(int(d.max()), 1, a)                          # M2 constant: max 1/255

    def test_frame_mode_fill(self):  # C9: frame mode = the whole straightened frame, black outside the picture
        W, H = 120, 80
        white = np.ones((H, W, 3), np.float32)
        g = geo(angle=20, crop=(0.4, 0.4, 0.6, 0.6), aspect="free").bound(W, H, W, H, frame=True)
        out = render(white, Params(), geometry=g)
        self.assertEqual(out.shape, (H, W, 3))
        for y, x in ((0, 0), (0, W - 1), (H - 1, 0), (H - 1, W - 1)):
            self.assertLess(float(out[y, x].max()), 0.05, (y, x))
        self.assertGreater(float(out[H // 2, W // 2].min()), 0.99)
        cpu = g.apply((white * 255).astype(np.uint8))
        self.assertEqual(cpu.shape, (H, W, 3))
        self.assertEqual(int(cpu[0, 0].max()), 0)
        turned = geo(rotate=90, angle=5).bound(W, H, H, W, frame=True)
        self.assertEqual(render(white, Params(), geometry=turned).shape, (W, H, 3))

    @unittest.skipUnless(HAS_CUDA, "needs CUDA")
    def test_render_with_geometry_latency(self):  # C11: A17 with angle 7.5 + 4:5, same threshold (GPU busy rule R1)
        from darkroom_app.engine import preview_size
        from test_render import gpu_busy, heavy_params
        img = torch.rand(1, 3, 1000, 1500, device="cuda")
        g = geo(angle=7.5, aspect="4:5")
        pw, ph = preview_size(*g.output_size(6000, 4000))                        # a 24 MP photo's 1.5 MP preview
        self.assertGreater(pw * ph, 1400000)
        bound = g.bound(6000, 4000, pw, ph)
        p = heavy_params()
        render(img, p, geometry=bound)
        torch.cuda.synchronize()
        busy, reason = gpu_busy()
        if busy is None or busy:
            self.skipTest(f"[C11] skipped: {reason}")
        for _ in range(5):
            render(img, p, geometry=bound)
        torch.cuda.synchronize()
        ts = []
        for _ in range(20):
            t0 = time.perf_counter()
            render(img, p, geometry=bound)
            torch.cuda.synchronize()
            ts.append((time.perf_counter() - t0) * 1000)
        med = statistics.median(ts)
        print(f"\n[C11] {pw}x{ph} angle 7.5 + 4:5 full pipeline median {med:.2f} ms")
        self.assertLessEqual(med, 25.0)


class TestPresetCrop(unittest.TestCase):
    def test_preset_crop_never_applied(self):  # C10 (D5)
        from darkroom_app import skips
        d = _util.tmpdir(self)
        base = {"Exposure2012": "+0.50", "Contrast2012": "+20"}
        crop = {"HasCrop": "True", "CropTop": "0.1", "CropLeft": "0.05", "CropBottom": "0.9", "CropRight": "0.8",
                "CropAngle": "5", "CropConstrainToWarp": "0", "CropConstrainAspectRatio": "True"}
        plain = load_preset(_xmpgen.write(d, "plain.xmp", _xmpgen.xmp_text(base)))
        cropped = load_preset(_xmpgen.write(d, "crop.xmp", _xmpgen.xmp_text(dict(base, **crop))))
        img = rand_img(60, 80, 4)
        self.assertTrue(np.array_equal(render(img, plain), render(img, cropped)))
        self.assertEqual(cropped.skipped, plain.skipped + [PRESET_CROP])
        self.assertEqual((skips.level(PRESET_CROP), skips.label(PRESET_CROP)), ("minor", PRESET_CROP_LABEL))
        self.assertEqual(skips.summarize(cropped.skipped)["banner"], "")                   # never the look banner
        for extra in ({"CropConstrainToWarp": "0"}, {"HasCrop": "False", "CropLeft": "0", "CropRight": "1"}):
            p = load_preset(_xmpgen.write(d, "x.xmp", _xmpgen.xmp_text(dict(base, **extra))))
            self.assertNotIn(PRESET_CROP, p.skipped, extra)
            self.assertEqual(p.skipped, plain.skipped, extra)
        p = load_preset(_xmpgen.write(d, "y.xmp", _xmpgen.xmp_text(dict(base, CropAngle="-2"))))
        self.assertEqual(p.skipped.count(PRESET_CROP), 1)

    def test_library_has_no_crop_presets(self):  # C10: the user's 1466 presets carry no crop (G3); read only
        from darkroom import UnsupportedPresetError
        files = _util.preset_files()
        self.assertEqual(len(files), 1466)
        hits = 0
        for f in files:
            try:
                hits += PRESET_CROP in load_preset(f).skipped
            except UnsupportedPresetError:
                pass
        self.assertEqual(hits, 0)


# ---------------------------------------------------------------- C12-C16: the photo library
class LibCase(unittest.TestCase):
    def setUp(self):
        from darkroom_app.composition import build_facade
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "lib", "xmp")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.data = os.path.join(self.tmp, "data")
        self.f = build_facade(self.presets, data_dir=self.data)
        self.lib = self.f._photo_library
        self.addCleanup(self.lib.wait_thumbnails, 60)

    def p(self, name):
        return os.path.join(self.photos, name)

    def edit_file(self, path):
        fp = self.f.get_edit(path)["fingerprint"]
        return os.path.join(self.data, "edits", fp[:2], fp + ".json")

    def err(self, fn, *a, **kw):
        from darkroom_app.errors import DarkroomError
        with self.assertRaises(DarkroomError) as cm:
            fn(*a, **kw)
        return cm.exception.kind, cm.exception.message


class TestEditFile(LibCase):
    def test_edit_v1_bytes_unchanged(self):  # C12 (D3): no geometry -> darkroom-edit/1, byte for byte as before
        a = write_photo(self.p("a.jpg"), 64, 48)
        fp = self.f.get_edit(a)["fingerprint"]
        row = self.f._presets.library.by_id["p-expo"]
        snap = {"id": "p-expo", "name": row["name"], "group": row["group"],
                "params": self.f._presets.library.get("p-expo").to_dict()}
        want = json.dumps({"schema": "darkroom-edit/1", "fingerprint": fp, "preset": snap, "strength": 80,
                           "overrides": {"Contrast2012": 10.0}}, ensure_ascii=False).encode("utf-8")
        for geometry in ({}, {"geometry": None}, {"geometry": G(aspect="4:5")}):     # omitted, null, an identity
            self.f.set_edit(a, "p-expo", 80, {"Contrast2012": 10}, **geometry)
            with open(self.edit_file(a), "rb") as fh:
                self.assertEqual(fh.read(), want, geometry)

    def test_edit_v2_roundtrip(self):  # C12
        a = write_photo(self.p("a.jpg"), 64, 48)
        g = G(rotate=90, flip=True, angle=2.5, aspect="8:10", crop=(0.1, 0.2, 0.6, 0.9))
        res = self.f.set_edit(a, "p-expo", 120, None, geometry=g)
        norm = Geometry.from_dict(g).to_dict()
        self.assertEqual(norm["aspect"], "4:5")
        self.assertEqual(list(res["edit"]), EDIT_KEYS_V2)
        self.assertEqual((res["edit"]["schema"], res["edit"]["geometry"]), ("darkroom-edit/2", norm))
        with open(self.edit_file(a), encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertEqual(list(disk), EDIT_KEYS_V2)
        self.assertEqual(self.f.get_edit(a)["edit"], disk)
        only = self.f.set_edit(a, None, 100, None, geometry=G(rotate=180))                  # only a geometry: an edit
        self.assertEqual((only["edit"]["preset"], only["edit"]["overrides"], only["edit"]["geometry"]),
                         (None, {}, G(rotate=180)))
        self.assertEqual(self.f.get_edit(a)["edit"]["geometry"], G(rotate=180))

    def test_edit_v3_conflict_not_overwritten(self):  # C12 (PL9'): another version -> conflict; a bad /2 -> corrupt
        a = write_photo(self.p("a.jpg"), 64, 48)
        self.f.set_edit(a, "p-expo", 100, None, geometry=G(rotate=90))
        path = self.edit_file(a)
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        future = json.dumps(dict(obj, schema="darkroom-edit/3")).encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(future)
        msg = "編輯檔版本不支援：darkroom-edit/3（a.jpg）"
        for fn in (lambda: self.f.get_edit(a), lambda: self.f.set_edit(a, "p-expo", 50, None),
                   lambda: self.f.set_edit(a, None, 100, None, geometry=None), lambda: self.f.clear_edit(a)):
            self.assertEqual(self.err(fn), ("conflict", msg))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), future)
        bad = json.dumps(dict(obj, geometry={"rotate": 45})).encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(bad)
        self.assertEqual(self.err(self.f.get_edit, a), ("unavailable", f"照片庫的編輯檔損壞：{path}"))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), bad)

    def test_set_edit_geometry_tristate(self):  # C13 (D4): omitted keeps, null clears, an object replaces
        a = write_photo(self.p("a.jpg"), 64, 48)
        g1, g2 = G(rotate=90), G(flip=True, aspect="free", crop=(0.1, 0.1, 0.9, 0.9))
        self.assertEqual(self.f.set_edit(a, "p-expo", 100, None, geometry=g1)["edit"]["geometry"], g1)
        self.assertEqual(self.f.set_edit(a, "p-expo", 60, {"Contrast2012": 5})["edit"]["geometry"], g1)   # kept
        self.assertEqual(self.f.set_edit(a, "p-expo", 60, None, geometry=g2)["edit"]["geometry"], g2)     # replaced
        res = self.f.set_edit(a, "p-expo", 60, None, geometry=None)                                       # cleared
        self.assertEqual(res["edit"]["schema"], "darkroom-edit/1")
        self.assertNotIn("geometry", res["edit"])
        self.f.set_edit(a, None, 100, None, geometry=g1)
        self.assertEqual(self.f.set_edit(a, None, 100, None)["edit"]["geometry"], g1)       # only geometry, kept
        res = self.f.set_edit(a, None, 100, None, geometry=None)                             # all three empty: gone
        self.assertIsNone(res["edit"])
        self.assertFalse(os.path.exists(self.edit_file(a)))
        self.assertTrue(res["previous"])                                                     # S4: kept as previous
        # the order of the checks: path -> preset -> strength -> overrides -> geometry
        self.assertEqual(self.err(self.f.set_edit, a, "nope", 100, None, geometry=5)[0], "not_found")
        self.assertEqual(self.err(self.f.set_edit, a, None, 300, None, geometry=5)[1],
                         "strength must be within 0..200, got 300")
        self.assertEqual(self.err(self.f.set_edit, a, None, 100, {"Bogus": 1}, geometry=5)[1], "unknown slider key 'Bogus'")
        self.assertEqual(self.err(self.f.set_edit, a, None, 100, None, geometry=5), ("invalid", NOT_OBJECT.format(geometry="5")))

    def test_restore_compares_geometry(self):  # C12 / S4a': "the same edit" includes the geometry; C16 restore
        a = write_photo(self.p("a.jpg"), 64, 48)
        g1, g2 = G(rotate=90), G(rotate=270)
        self.f.set_edit(a, "p-expo", 100, None, geometry=g1)
        self.f.clear_edit(a)
        self.f.set_edit(a, "p-expo", 100, None, geometry=g2)                       # differs only in the geometry
        self.assertEqual(self.err(self.f.restore_edit, a)[0], "conflict")
        self.f.set_edit(a, "p-expo", 100, None, geometry=g1)                       # the same edit: a no-op success
        self.assertEqual(self.f.restore_edit(a)["edit"]["geometry"], g1)
        self.f.clear_edit(a)
        self.assertEqual(self.f.restore_edit(a)["edit"]["geometry"], g1)           # "取回上一份" brings the crop back


class TestPaste(LibCase):
    def setUp(self):
        super().setUp()
        self.src = write_photo(self.p("src.jpg"), 64, 48)
        self.t1 = write_photo(self.p("t1.jpg"), 64, 48, seed=1)
        self.t2 = write_photo(self.p("t2.jpg"), 64, 48, seed=2)
        self.g1 = G(rotate=90)
        self.g2 = G(flip=True, aspect="free", crop=(0.2, 0.2, 0.8, 0.8))
        self.f.set_edit(self.src, "p-expo", 70, {"Contrast2012": 15}, geometry=self.g1)
        self.f.set_edit(self.t1, "p-strong", 100, None, geometry=self.g2)

    def test_paste_keeps_target_geometry(self):  # C14: colours only by default; each target keeps its geometry
        res = self.f.paste_edit([self.t1, self.t2], self.src)
        self.assertEqual(res, {"results": [{"ok": True, "target": "t1.jpg"}, {"ok": True, "target": "t2.jpg"}]})
        e1, e2 = self.f.get_edit(self.t1)["edit"], self.f.get_edit(self.t2)["edit"]
        for e in (e1, e2):
            self.assertEqual((e["preset"]["id"], e["strength"], e["overrides"]), ("p-expo", 70, {"Contrast2012": 15.0}))
        self.assertEqual(e1["geometry"], self.g2)
        self.assertEqual(e2["schema"], "darkroom-edit/1")                         # had none, has none
        edit = self.f.get_edit(self.src)["edit"]                                   # the edit object path too
        self.f.paste_edit([self.t2], edit=edit)
        self.assertNotIn("geometry", self.f.get_edit(self.t2)["edit"])

    def test_paste_with_geometry(self):  # C14: with_geometry = the whole edit, geometry included
        self.f.paste_edit([self.t1, self.t2], self.src, with_geometry=True)
        for t in (self.t1, self.t2):
            self.assertEqual(self.f.get_edit(t)["edit"]["geometry"], self.g1)
        plain = write_photo(self.p("plain.jpg"), 64, 48, seed=3)
        self.f.set_edit(plain, "p-expo", 100, None)
        self.f.paste_edit([self.t1], plain, with_geometry=True)                     # no geometry: cleared
        self.assertNotIn("geometry", self.f.get_edit(self.t1)["edit"])

    def test_paste_geometry_only_refused(self):  # C14: an edit with only a geometry needs with_geometry
        only = write_photo(self.p("only.jpg"), 64, 48, seed=4)
        self.f.set_edit(only, None, 100, None, geometry=self.g1)
        before = {t: self.f.get_edit(t)["edit"] for t in (self.t1, self.t2)}
        self.assertEqual(self.err(self.f.paste_edit, [self.t1, self.t2], only), ("invalid", GEOMETRY_ONLY))
        self.assertEqual({t: self.f.get_edit(t)["edit"] for t in (self.t1, self.t2)}, before)   # nothing written
        self.f.paste_edit([self.t2], only, with_geometry=True)
        self.assertEqual(self.f.get_edit(self.t2)["edit"]["geometry"], self.g1)
        for bad in ("yes", 1, None):
            self.assertEqual(self.err(self.f.paste_edit, [self.t1], self.src, with_geometry=bad),
                             ("invalid", WITH_GEOMETRY_INVALID))


class TestSavedPreset(LibCase):
    def test_saved_preset_has_no_crop(self):  # C15: a saved preset is colour only
        _xmpgen.write(self.presets, "p-crop.xmp", _xmpgen.xmp_text(
            {"Exposure2012": "+0.30", "CropConstrainToWarp": "0", "CropLeft": "0.1", "CropRight": "0.9",
             "CropAngle": "3", "HasCrop": "True"}, name="有裁切", group="測試"))
        self.f.rebuild_library()
        a = write_photo(self.p("a.jpg"), 64, 48)
        self.f.set_edit(a, "p-crop", 100, None, geometry=G(rotate=90))
        libroot = os.path.dirname(self.presets)
        for res in (self.f.save_edit_as_preset(a, "存一"), self.f.save_user_preset("存二", None, "p-crop", 80)):
            with open(os.path.join(libroot, res["file"]), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("Crop", text)
            self.assertNotIn("HasCrop", text)
            self.assertIn('crs:Exposure2012="', text)


# ---------------------------------------------------------------- C17-C19: previews, thumbnails, exports
class EngineCase(LibCase):
    @classmethod
    def setUpClass(cls):
        from darkroom_app import engine as engine_mod
        cls.eng = engine_mod.Engine()

    @classmethod
    def tearDownClass(cls):
        cls.eng.shutdown()

    def setUp(self):
        super().setUp()
        from darkroom_app.composition import build_facade
        self.f = build_facade(self.presets, engine=self.eng, data_dir=self.data)
        self.lib = self.f._photo_library
        self.dest = os.path.join(self.tmp, "dest")
        os.makedirs(self.dest)

    def jpeg_size(self, data):
        a = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        return a.shape[1], a.shape[0]


class TestPreview(EngineCase):
    def test_preview_geometry_size(self):  # C17 (L5'): preview_size(output size, max_pixels or 1500000)
        from darkroom_app.engine import preview_size
        a = write_photo(self.p("a.jpg"), 640, 400)
        info = self.f.open_photo(a)
        self.assertEqual(set(info), {"image_id", "width", "height", "preview_width", "preview_height"})   # L8
        g = G(rotate=90, angle=4, aspect="4:5")
        out = Geometry.from_dict(g).output_size(640, 400)
        r = self.f.preview(info["image_id"], geometry=g)
        self.assertEqual((r.width, r.height), preview_size(*out))
        self.assertEqual(self.jpeg_size(r.jpeg), (r.width, r.height))
        r = self.f.preview(info["image_id"], geometry=g, max_pixels=65536)
        self.assertEqual((r.width, r.height), preview_size(*out, 65536))
        self.assertEqual(self.jpeg_size(r.jpeg), (r.width, r.height))
        self.assertEqual(self.err(self.f.preview, info["image_id"], geometry={"rotate": 45}),
                         ("invalid", BAD_ROTATE.format(rotate="45")))

    def test_preview_geometry_omitted_uses_saved(self):  # C17 (D4)
        a = write_photo(self.p("a.jpg"), 640, 400)
        info = self.f.open_photo(a)
        plain = self.f.preview(info["image_id"])
        self.assertEqual((plain.width, plain.height), (640, 400))
        g = G(rotate=90, aspect="free", crop=(0.0, 0.0, 1.0, 0.5))
        self.f.set_edit(a, None, 100, None, geometry=g)
        kept = self.f.preview(info["image_id"])
        self.assertEqual((kept.width, kept.height), (400, 320))
        self.assertEqual(kept.jpeg, self.f.preview(info["image_id"], geometry=g).jpeg)
        none = self.f.preview(info["image_id"], geometry=None)
        self.assertEqual(none.jpeg, plain.jpeg)                                   # null = the photo as it is

    def test_preview_frame_mode(self):  # C17: frame = the whole straightened frame W' x H', the crop ignored
        a = write_photo(self.p("a.jpg"), 640, 400)
        info = self.f.open_photo(a)
        g = G(rotate=90, angle=8, aspect="1:1", crop=(0.1, 0.1, 0.3, 0.3))
        r = self.f.preview(info["image_id"], geometry=g, frame=True)
        self.assertEqual((r.width, r.height), (400, 640))
        img = cv2.imdecode(np.frombuffer(r.jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertLess(int(img[0, 0].max()), 30)                                # blank corners are black
        for bad in (1, "true", None):
            self.assertEqual(self.err(self.f.preview, info["image_id"], geometry=g, frame=bad), ("invalid", FRAME_INVALID))
        same = self.f.preview(info["image_id"], geometry=None, frame=True)        # no geometry: the plain preview
        self.assertEqual(same.jpeg, self.f.preview(info["image_id"], geometry=None).jpeg)

    def test_preview_crop_stays_sharp(self):  # C17 (D6): a crop is rendered from the detail base, not upscaled
        from darkroom_app.engine import preview_size
        from darkroom_app import preview as semantics
        a = os.path.join(self.photos, "big.png")
        src = smooth_img(1600, 2400)                                              # + 1-2 px texture a 1.5 MP base loses
        n = cv2.GaussianBlur(np.random.default_rng(0).normal(0, 1, (1600, 2400)).astype(np.float32), (0, 0), 1.2)
        src = np.clip(src + 0.04 * (n / n.std())[..., None], 0, 1)
        ok, buf = cv2.imencode(".png", (src[..., ::-1] * 65535 + 0.5).astype(np.uint16))
        with open(a, "wb") as fh:
            fh.write(buf.tobytes())
        info = self.f.open_photo(a)
        self.assertEqual((info["preview_width"], info["preview_height"]), preview_size(2400, 1600))
        g = G(aspect="free", crop=(0.25, 0.25, 0.75, 0.75))                       # 3/4 of the area cut away
        r = self.f.preview(info["image_id"], geometry=g)
        self.assertEqual((r.width, r.height), preview_size(1200, 800))
        full = render(read_image(a), semantics.effective_params(None, 1.0, {}), geometry=Geometry.from_dict(g))
        ref = cv2.resize(full, (r.width, r.height), interpolation=cv2.INTER_AREA)
        got = cv2.imdecode(np.frombuffer(r.jpeg, np.uint8), cv2.IMREAD_COLOR)[..., ::-1].astype(np.float32) / 255
        self.assertLessEqual(mad(got, ref), 2 / 255)
        base_only = np.asarray(self.eng.images[info["image_id"]]["tensor"][0].permute(1, 2, 0).cpu())   # the old way
        up = cv2.resize(base_only[250:750, 375:1125], (r.width, r.height), interpolation=cv2.INTER_LINEAR)
        self.assertLess(mad(got, ref), mad(up, ref))                              # sharper than the 1.5 MP base


class TestThumbnail(EngineCase):
    def test_thumbnail_applies_geometry(self):  # C18 (D7): the cached original thumbnail, the geometry on return
        a = write_jpeg(self.p("a.jpg"), pattern(400, 640))
        plain = self.f.thumbnail(a)
        self.assertEqual((plain.width, plain.height), (256, 160))
        g = G(rotate=90, aspect="4:5")
        self.f.set_edit(a, "p-expo", 100, None, geometry=g)
        cached = os.path.join(self.data, "thumbs", plain.fingerprint[:2], plain.fingerprint + ".jpg")
        with open(cached, "rb") as fh:
            cached_bytes = fh.read()
        want = Geometry.from_dict(g).apply(cv2.imdecode(np.frombuffer(cached_bytes, np.uint8), cv2.IMREAD_COLOR))
        photos = os.path.normcase(self.photos) + os.sep
        opened, real_open = [], builtins.open

        def spy(file, *x, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.normcase(os.fsdecode(file)).startswith(photos):
                opened.append(file)
            return real_open(file, *x, **k)
        with mock.patch("builtins.open", spy):
            t = self.f.thumbnail(a)
        self.assertEqual(opened, [])                                              # warm: the photo is not opened
        self.assertEqual((t.width, t.height), (want.shape[1], want.shape[0]))
        self.assertEqual(self.jpeg_size(t.jpeg), (t.width, t.height))
        self.assertLessEqual(max(t.width, t.height), 256)
        with open(cached, "rb") as fh:
            self.assertEqual(fh.read(), cached_bytes)                            # no new cache file, none changed
        self.assertEqual(sorted(os.listdir(os.path.dirname(cached))), [os.path.basename(cached)])
        self.assertEqual(t.edit["geometry"], True)


class TestExport(EngineCase):
    def test_export_applies_geometry(self):  # C19 (XP35): the output size, the pixels of render_full with geometry
        from darkroom_app import preview as semantics
        a = write_jpeg(self.p("a.jpg"), pattern(200, 300))
        g = G(rotate=90, aspect="free", crop=(0.1, 0.2, 0.9, 0.7))
        res = self.f.export([{"path": a, "preset_id": "p-expo", "strength": 50, "geometry": g}], "png",
                            dest_dir=self.dest)["results"][0]
        self.assertTrue(res["ok"], res)
        out = Geometry.from_dict(g).output_size(300, 200)
        self.assertEqual((res["used"]["width"], res["used"]["height"]), out)
        got = cv2.imread(res["output"], cv2.IMREAD_UNCHANGED)
        params = semantics.effective_params(self.f._presets.library.get("p-expo"), 0.5, {})
        want = self.eng.render_full(read_image(a), params, 8, Geometry.from_dict(g))
        self.assertTrue(np.array_equal(got, want))
        self.assertEqual((got.shape[1], got.shape[0]), out)

    def test_export_saved_geometry(self):  # C19 (D4): left out = the saved geometry; --no-edit = the photo itself
        from darkroom_app import cli
        a = write_jpeg(self.p("a.jpg"), pattern(200, 300))
        g = G(rotate=90, aspect="4:5")
        self.f.set_edit(a, "p-expo", 80, None, geometry=g)
        out = Geometry.from_dict(g).output_size(300, 200)
        size = lambda r: (r["used"]["width"], r["used"]["height"])
        r = self.f.export([{"path": a}, {"path": a, "preset_id": None}, {"path": a, "geometry": None}], "png",
                          dest_dir=self.dest)["results"]
        self.assertEqual([size(x) for x in r], [out, out, (300, 200)])
        self.assertEqual([x["used"]["params_from"] for x in r], ["edit", "request", "request"])
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            rc = cli.main(["export", a, "--no-edit", "--format", "png", "--dest-dir", self.dest, "--json"], facade=self.f)
        self.assertEqual(rc, 0)
        self.assertEqual(size(json.loads(o.getvalue())["result"]["results"][0]), (300, 200))
        bad = self.f.export([{"path": a, "geometry": {"angle": 99}}], "png", dest_dir=self.dest)["results"][0]
        self.assertEqual(bad, {"ok": False, "source": "a.jpg", "error": "匯出失敗：a.jpg：" + BAD_ANGLE.format(angle="99")})

    def test_export_resize_after_crop(self):  # C19: E8 resizes the output size
        from darkroom_app.services.export import resize_target
        a = write_jpeg(self.p("a.jpg"), pattern(200, 300))
        g = G(angle=6, aspect="1:1")
        out = Geometry.from_dict(g).output_size(300, 200)
        r = self.f.export([{"path": a, "geometry": g}], "png", dest_dir=self.dest,
                          resize={"mode": "long_edge", "value": 100})["results"][0]
        self.assertEqual((r["used"]["width"], r["used"]["height"]), resize_target(*out, {"mode": "long_edge", "value": 100}))
        self.assertEqual(cv2.imread(r["output"]).shape[:2], (r["used"]["height"], r["used"]["width"]))

    def test_export_exif_dimensions_after_crop(self):  # C19: PixelX/YDimension = what was written, Orientation 1
        from PIL import Image
        a = write_jpeg(self.p("o6.jpg"), pattern(200, 300), orientation=6)        # upright 200 x 300
        g = G(aspect="free", crop=(0.0, 0.0, 1.0, 0.5))
        r = self.f.export([{"path": a, "geometry": g}], "jpeg", dest_dir=self.dest)["results"][0]
        self.assertEqual((r["used"]["width"], r["used"]["height"]), (200, 150))
        with Image.open(r["output"]) as im:
            self.assertEqual(im.size, (200, 150))
            ex = im.getexif()
            self.assertEqual(ex.get(0x0112, 1), 1)
            sub = ex.get_ifd(0x8769)
            self.assertEqual((sub[0xA002], sub[0xA003]), (200, 150))


# ---------------------------------------------------------------- C20: the three interfaces (format translation)
class TestInterfaces(unittest.TestCase):
    def run_cli(self, argv, fake):
        from darkroom_app import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(argv, facade=fake)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_cli_geometry_flags(self):  # C20 constant "CLI 幾何旗標"
        from _fakes import FakeDarkroom
        fake = FakeDarkroom()
        full = {"rotate": 90, "flip": True, "angle": 3.5, "aspect": "4:5",
                "crop": {"left": 0.1, "top": 0.2, "right": 0.8, "bottom": 0.9}}
        flags = ["--rotate", "90", "--flip", "--angle", "3.5", "--aspect", "4:5", "--crop", "0.1,0.2,0.8,0.9"]
        self.run_cli(["preview", "a.jpg", *flags, "--json"], fake)
        self.assertEqual(fake.calls[-1], ("preview", ("fake-image", None, 100, None, None, {"geometry": full})))
        self.run_cli(["preview", "a.jpg", "--frame", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("preview", ("fake-image", None, 100, None, None, {"frame": True})))
        self.run_cli(["preview", "a.jpg", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("preview", ("fake-image", None, 100, None, None)))   # no flag: KEEP
        self.run_cli(["preview", "a.jpg", "--angle", "2", "--json"], fake)                      # unset fields: identity
        # v2: only the flags given; Geometry.from_dict gives the others their identity values (the CLI adds none)
        self.assertEqual(fake.calls[-1][1][5], {"geometry": {"angle": 2}})
        self.run_cli(["preview", "a.jpg", "--rotate", "abc", "--angle", "x", "--json"], fake)    # raw: the service judges
        self.assertEqual((fake.calls[-1][1][5]["geometry"]["rotate"], fake.calls[-1][1][5]["geometry"]["angle"]), ("abc", "x"))
        self.run_cli(["edit", "set", "a.jpg", "--preset", "p", *flags, "--json"], fake)
        self.assertEqual(fake.calls[-1], ("set_edit", ("a.jpg", "p", 100, None, {"geometry": full})))
        self.run_cli(["edit", "set", "a.jpg", "--no-geometry", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("set_edit", ("a.jpg", None, 100, None, {"geometry": None})))
        self.run_cli(["edit", "set", "a.jpg", "--preset", "p", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("set_edit", ("a.jpg", "p", 100, None)))                 # KEEP
        self.run_cli(["edit", "paste", "--from", "s.jpg", "t.jpg", "--with-geometry", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("paste_edit", (["t.jpg"], "s.jpg", None, {"with_geometry": True})))
        self.run_cli(["edit", "paste", "--from", "s.jpg", "t.jpg", "--json"], fake)
        self.assertEqual(fake.calls[-1], ("paste_edit", (["t.jpg"], "s.jpg", None)))
        self.run_cli(["export", "a.jpg", *flags, "--json"], fake)
        self.assertEqual(fake.calls[-1][1][0], [{"path": "a.jpg", "geometry": full}])   # v2: only what was typed
        self.run_cli(["export", "a.jpg", "--preset", "p", "--json"], fake)                        # colours, saved geometry
        self.assertEqual(fake.calls[-1][1][0], [{"path": "a.jpg", "preset_id": "p"}])
        self.run_cli(["export", "a.jpg", "--no-geometry", "--json"], fake)
        self.assertEqual(fake.calls[-1][1][0][0]["geometry"], None)
        n = len(fake.calls)
        for argv in (["preview", "a.jpg", "--no-geometry", "--rotate", "90"], ["edit", "set", "a.jpg", "--no-geometry", "--flip"],
                     ["export", "a.jpg", "--no-edit", "--rotate", "90"], ["export", "a.jpg", "--no-edit", "--no-geometry"]):
            rc, out, err = self.run_cli(argv + ["--json"], fake)
            self.assertEqual((rc, out), (2, ""), argv)
            self.assertEqual(err.count("\n"), 1, argv)
            self.assertIn("not allowed with argument", err)
        for value in ("0.1,0.2,0.8", "a,b,c,d", ""):
            rc, out, err = self.run_cli(["edit", "set", "a.jpg", "--crop", value, "--json"], fake)
            self.assertEqual((rc, out), (2, ""))
            self.assertIn(CLI_BAD_CROP.format(value=value), err)
            self.assertEqual(err.count("\n"), 1)
        self.assertEqual(len(fake.calls), n)                                      # usage errors never reach the facade

    def test_mcp_geometry_schema(self):  # C20 constant "MCP geometry schema"
        from darkroom_app.mcp_server.tools import Tools
        from darkroom_app.operations import GEOMETRY_SCHEMA
        verbatim = {"type": ["object", "null"], "properties": {
            "rotate": {"enum": [0, 90, 180, 270]}, "flip": {"type": "boolean"},
            "angle": {"type": "number", "minimum": -45, "maximum": 45}, "aspect": {"type": "string"},
            "crop": {"type": ["object", "null"], "properties": {"left": {"type": "number"}, "top": {"type": "number"},
                                                                "right": {"type": "number"}, "bottom": {"type": "number"}},
                     "additionalProperties": False}}, "additionalProperties": False}
        self.assertEqual(GEOMETRY_SCHEMA, verbatim)
        tools = {t["name"]: t for t in Tools(lambda: None).list()}
        self.assertEqual(len(tools), 38)                    # v2: + 5 settings / version tools (plan-v2 §3)
        self.assertEqual(tools["darkroom_preview"]["inputSchema"]["properties"]["geometry"], verbatim)
        self.assertEqual(tools["darkroom_preview"]["inputSchema"]["properties"]["frame"]["type"], "boolean")
        self.assertEqual(tools["darkroom_edit_set"]["inputSchema"]["properties"]["geometry"], verbatim)
        self.assertEqual(tools["darkroom_export"]["inputSchema"]["properties"]["items"]["items"]["properties"]["geometry"],
                         verbatim)
        self.assertEqual(tools["darkroom_edit_paste"]["inputSchema"]["properties"]["with_geometry"]["type"], "boolean")
        from _fakes import FakeDarkroom
        fake = FakeDarkroom()
        Tools(lambda: fake).call("darkroom_edit_set", {"path": "a.jpg", "geometry": None})
        self.assertEqual(fake.calls[-1], ("set_edit", ("a.jpg", None, 100, None, {"geometry": None})))
        Tools(lambda: fake).call("darkroom_edit_set", {"path": "a.jpg"})
        self.assertEqual(fake.calls[-1], ("set_edit", ("a.jpg", None, 100, None)))                 # left out: KEEP
        Tools(lambda: fake).call("darkroom_preview", {"image_id": "i", "geometry": G(rotate=90), "frame": True})
        self.assertEqual(fake.calls[-1], ("preview", ("i", None, 100, None, 786432, {"geometry": G(rotate=90), "frame": True})))
        Tools(lambda: fake).call("darkroom_edit_paste", {"targets": ["t"], "source": "s", "with_geometry": True})
        self.assertEqual(fake.calls[-1], ("paste_edit", (["t"], "s", None, {"with_geometry": True})))

    def test_counts_unchanged(self):  # C20: no new operation, tool or route; G10 stays 5
        from darkroom_app.operations import OPERATIONS
        self.assertEqual(len(OPERATIONS), 38)               # v2: + 5 (plan-v2 §3); S3 itself added none
        from test_layering import SAFE_WRITE_USERS
        self.assertEqual(len(SAFE_WRITE_USERS), 7)          # v2: the writes moved into adapters/persist (+ settings)
        import inspect
        from darkroom_app.facade import KEEP, Facade
        sig = lambda op: str(inspect.signature(getattr(Facade, op)))
        self.assertEqual(sig("preview"), "(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, "
                                         "geometry=KEEP, frame=False)")
        self.assertEqual(sig("set_edit"), "(self, path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP)")
        self.assertEqual(sig("paste_edit"), "(self, targets, source=None, edit=None, *, with_geometry=False)")
        self.assertEqual(repr(KEEP), "KEEP")


class TestHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        from darkroom_app.server import FACADE, make_app
        from test_layering import _NoEngine
        self.tmp = _util.tmpdir(self)
        self.presets = os.path.join(self.tmp, "lib", "xmp")
        os.makedirs(self.presets)
        make_presets(self.presets)
        self.photos = os.path.join(self.tmp, "photos")
        os.makedirs(self.photos)
        self.app = make_app(self.presets, engine=_NoEngine(), data_dir=os.path.join(self.tmp, "data"))
        self.addCleanup(self.app[FACADE]._photo_library.wait_thumbnails, 60)
        self.client = TestClient(TestServer(self.app), headers=_util.HTTP_HEADERS)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_http_geometry_fields(self):  # C20: PUT /api/edit geometry, paste with_geometry, the sentences
        a = write_photo(os.path.join(self.photos, "a.jpg"), 64, 48)
        g = G(rotate=90, aspect="free", crop=(0.1, 0.1, 0.9, 0.9))
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "geometry": g})
        self.assertEqual((await r.json())["edit"]["geometry"], g)
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "strength": 50})   # no key: kept
        self.assertEqual((await r.json())["edit"]["geometry"], g)
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "geometry": None})
        self.assertNotIn("geometry", (await r.json())["edit"])
        r = await self.client.put("/api/edit", json={"path": a, "geometry": {"angle": 46}})
        self.assertEqual((r.status, await r.json()), (400, {"error": BAD_ANGLE.format(angle="46")}))
        r = await self.client.post("/api/edit/paste", json={"targets": [a], "source": a, "with_geometry": "x"})
        self.assertEqual((r.status, await r.json()), (400, {"error": WITH_GEOMETRY_INVALID}))
        r = await self.client.post("/api/export", json={"items": [{"path": a, "geometry": 7}], "format": "png"})
        res = (await r.json())["results"][0]
        self.assertEqual(res["error"], "匯出失敗：a.jpg：" + NOT_OBJECT.format(geometry="7"))

    async def test_autosave_keeps_crop(self):  # C14 S2b: the page's PASTE save carries with_geometry: true
        a = write_photo(os.path.join(self.photos, "a.jpg"), 64, 48)
        g1 = G(rotate=90)
        r = await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "strength": 100, "overrides": {},
                                                     "geometry": None})
        res = await r.json()
        snap = res["edit"]["preset"]
        # what L.editRequest sends after the crop mode committed g1 (a remembered snapshot -> PASTE)
        edit = {"schema": "darkroom-edit/2", "fingerprint": res["fingerprint"], "preset": snap, "strength": 100,
                "overrides": {}, "geometry": g1}
        r = await self.client.post("/api/edit/paste", json={"targets": [a], "edit": edit, "with_geometry": True})
        self.assertEqual((await r.json())["results"], [{"ok": True, "target": "a.jpg"}])
        r = await self.client.get("/api/edit", params={"path": a})
        self.assertEqual((await r.json())["edit"]["geometry"], g1)              # reopened: the crop is there
        # the trap S2b closes: without with_geometry the target's own (old) geometry would stay
        g2 = G(rotate=180)
        await self.client.post("/api/edit/paste", json={"targets": [a], "edit": dict(edit, geometry=g2)})
        r = await self.client.get("/api/edit", params={"path": a})
        self.assertEqual((await r.json())["edit"]["geometry"], g1)

    async def test_thumbnail_edit_header_geometry(self):  # C18 / S8b: X-Edit geometry and tweaks
        from urllib.parse import unquote
        a = write_photo(os.path.join(self.photos, "a.jpg"), 400, 300)
        await self.client.put("/api/edit", json={"path": a, "preset_id": None, "overrides": {}, "geometry": G(rotate=90)})
        r = await self.client.get("/api/thumbnail", params={"path": a})
        self.assertEqual(json.loads(unquote(r.headers["X-Edit"])),
                         {"preset": None, "strength": 100, "status": None, "geometry": True, "tweaks": False})
        data = await r.read()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[:2], (256, 192))                               # turned: portrait
        await self.client.put("/api/edit", json={"path": a, "preset_id": "p-expo", "overrides": {"Contrast2012": 5}})
        r = await self.client.get("/api/thumbnail", params={"path": a})
        info = json.loads(unquote(r.headers["X-Edit"]))
        self.assertEqual((info["geometry"], info["tweaks"]), (True, True))


if __name__ == "__main__":
    unittest.main()
