"""Rendering: A8-A12, A14, A17, A18."""
import os
import statistics
import time
import unittest
from unittest import mock

import numpy as np
import torch

import _util
import _xmpgen
from darkroom import Params, UnsupportedPresetError, load_preset, render

HAS_CUDA = torch.cuda.is_available()


def photo(name="landscape_lighthouse.png", max_side=640):
    from PIL import Image
    im = Image.open(os.path.join(_util.PHOTOS, name)).convert("RGB")
    im.thumbnail((max_side, max_side))
    return np.asarray(im).astype(np.float32) / 255.0


def ramp(h=8, w=256, lo=0.0, hi=1.0):
    g = np.linspace(lo, hi, w, dtype=np.float32)
    return np.repeat(np.repeat(g[None, :, None], h, 0), 3, 2)


def heavy_values():
    """Every global stage switched on with non-trivial values."""
    return {
        "IncrementalTemperature": 15.0, "IncrementalTint": -8.0, "Exposure2012": 0.6, "Contrast2012": 25.0,
        "Highlights2012": -60.0, "Shadows2012": 45.0, "Whites2012": 20.0, "Blacks2012": 30.0,
        "Clarity2012": 25.0, "Texture": 20.0, "Dehaze": 15.0, "Vibrance": 20.0, "Saturation": -10.0,
        "ParametricShadows": 10.0, "ParametricDarks": -5.0, "ParametricLights": 8.0, "ParametricHighlights": -10.0,
        "HueAdjustmentOrange": -10.0, "SaturationAdjustmentBlue": -30.0, "LuminanceAdjustmentGreen": 20.0,
        "SplitToningShadowHue": 210.0, "SplitToningShadowSaturation": 20.0, "SplitToningHighlightHue": 40.0,
        "SplitToningHighlightSaturation": 15.0, "SplitToningBalance": 10.0, "ColorGradeMidtoneHue": 30.0,
        "ColorGradeMidtoneSat": 10.0, "ColorGradeGlobalHue": 200.0, "ColorGradeGlobalSat": 5.0,
        "ColorGradeShadowLum": 5.0, "ColorGradeBlending": 60.0, "RedHue": 10.0, "BlueSaturation": -15.0,
        "ShadowTint": -5.0, "PostCropVignetteAmount": -20.0, "GrainAmount": 15.0, "Sharpness": 25.0,
    }


def heavy_params():
    return Params(values=heavy_values(), curves={
        "ToneCurvePV2012": [[0.0, 20.0], [64.0, 58.0], [192.0, 200.0], [255.0, 245.0]],
        "ToneCurvePV2012Red": [[0.0, 0.0], [128.0, 135.0], [255.0, 255.0]],
        "ToneCurvePV2012Blue": [[0.0, 10.0], [128.0, 122.0], [255.0, 250.0]]})


class TestIdentity(unittest.TestCase):
    def test_strength_zero_is_identity(self):  # A8
        img = photo()
        for p in (heavy_params(), load_preset(_util.find_preset(r"Mask/CircularGradient"))):
            out = render(img, p, strength=0.0)
            self.assertEqual(out.shape, img.shape)
            self.assertLessEqual(float(np.abs(out - img).max()), 1e-4)

    def test_strength_zero_identity_many_presets(self):
        img = photo(max_side=256)
        for path in _util.preset_files()[::60]:
            try:
                p = load_preset(path)
            except UnsupportedPresetError:
                continue
            self.assertLessEqual(float(np.abs(render(img, p, strength=0.0) - img).max()), 1e-4, path)

    def test_empty_params_identity(self):
        img = photo(max_side=256)
        self.assertLessEqual(float(np.abs(render(img, Params()) - img).max()), 1e-4)

    def test_tensor_in_tensor_out(self):
        img = torch.from_numpy(photo(max_side=128)).permute(2, 0, 1)
        out = render(img, heavy_params())
        self.assertIsInstance(out, torch.Tensor)
        self.assertEqual(tuple(out.shape), tuple(img.shape))
        self.assertEqual(out.device, img.device)

    def test_all_supported_presets_render(self):
        img = photo(max_side=96)
        for path in _util.preset_files():
            try:
                p = load_preset(path)
            except UnsupportedPresetError:
                continue
            out = render(img, p)
            self.assertTrue(np.isfinite(out).all(), path)
            self.assertGreaterEqual(float(out.min()), 0.0)
            self.assertLessEqual(float(out.max()), 1.0)


class TestTone(unittest.TestCase):
    def test_blacks_direction(self):  # A9
        img = ramp(lo=0.03, hi=1.0)
        y0 = img[:, :16].mean()
        up = render(img, Params(values={"Blacks2012": 50.0}))
        down = render(img, Params(values={"Blacks2012": -50.0}))
        self.assertGreater(up[:, :16].mean(), y0 + 0.01)
        self.assertLess(down[:, :16].mean(), y0 - 0.005)
        # the bright end barely moves
        self.assertLess(abs(up[:, -8:].mean() - img[:, -8:].mean()), 0.01)
        # monotonic ramp stays monotonic
        for o in (up, down):
            self.assertTrue((np.diff(o[0, :, 1]) >= -1e-5).all())

    def test_whites_direction(self):
        img = ramp(lo=0.0, hi=0.97)
        self.assertGreater(render(img, Params(values={"Whites2012": 50.0}))[:, -16:].mean(), img[:, -16:].mean() + 0.01)
        self.assertLess(render(img, Params(values={"Whites2012": -50.0}))[:, -16:].mean(), img[:, -16:].mean() - 0.01)

    def test_exposure_and_tone_directions(self):
        img = photo(max_side=256)
        m = img.mean()
        self.assertGreater(render(img, Params(values={"Exposure2012": 1.0})).mean(), m + 0.05)
        self.assertLess(render(img, Params(values={"Exposure2012": -1.0})).mean(), m - 0.05)
        self.assertGreater(render(img, Params(values={"Shadows2012": 80.0})).mean(), m)
        self.assertLess(render(img, Params(values={"Highlights2012": -80.0})).mean(), m)

    def test_curve_applies(self):
        img = ramp()
        out = render(img, Params(curves={"ToneCurvePV2012": [[0.0, 40.0], [255.0, 255.0]]}))
        self.assertAlmostEqual(float(out[0, 0, 0]), 40 / 255, places=3)


class TestColor(unittest.TestCase):
    def test_split_vs_colorgrade_once(self):  # A10
        from darkroom import _render
        img = ramp(lo=0.05, hi=0.95)
        base = Params(values={"SplitToningShadowHue": 220.0, "SplitToningShadowSaturation": 40.0,
                              "SplitToningHighlightHue": 40.0, "SplitToningHighlightSaturation": 30.0,
                              "ColorGradeMidtoneHue": 120.0, "ColorGradeMidtoneSat": 20.0,
                              "ColorGradeGlobalHue": 300.0, "ColorGradeGlobalSat": 10.0})
        # shadow/highlight tones come only from SplitToning*: ColorGrade{Shadow,Highlight}{Hue,Sat} are ignored
        extra = Params(values=dict(base.values, ColorGradeShadowHue=0.0, ColorGradeShadowSat=80.0,
                                   ColorGradeHighlightHue=180.0, ColorGradeHighlightSat=80.0))
        self.assertLessEqual(float(np.abs(render(img, base) - render(img, extra)).max()), 1e-6)
        # each zone is applied exactly once, from the expected keys
        calls = []
        real = _render._apply_tint

        def spy(x, Y, zone, hue, sat, *a, **k):
            calls.append((zone, hue, sat))
            return real(x, Y, zone, hue, sat, *a, **k)

        with mock.patch.object(_render, "_apply_tint", spy):
            render(img, base)
        self.assertEqual(sorted(calls), sorted([("shadow", 220.0, 40.0), ("highlight", 40.0, 30.0),
                                                ("midtone", 120.0, 20.0), ("global", 300.0, 10.0)]))
        # a shadow tone shifts dark pixels toward its hue, not bright ones
        out = render(img, Params(values={"SplitToningShadowHue": 240.0, "SplitToningShadowSaturation": 60.0}))
        dark, bright = out[:, 20], out[:, -20]
        self.assertGreater(dark[:, 2].mean() - dark[:, 0].mean(), 0.02)
        self.assertLess(abs(bright[:, 2].mean() - bright[:, 0].mean()), 0.01)

    def test_grayscale_equal_channels(self):  # A11
        img = photo()
        tone_sats = ("SplitToningShadowSaturation", "SplitToningHighlightSaturation", "ColorGradeMidtoneSat",
                     "ColorGradeGlobalSat")
        p = heavy_params()
        p.values["ConvertToGrayscale"] = True
        p.values["GrayMixerOrange"] = 20.0
        p.values["GrayMixerBlue"] = -30.0
        untoned = Params(values={k: v for k, v in p.values.items() if k not in tone_sats}, curves=p.curves)

        def chdiff(o):
            return float(max(np.abs(o[..., 0] - o[..., 1]).max(), np.abs(o[..., 1] - o[..., 2]).max()))

        for s in (0.5, 1.0, 2.0):
            self.assertLessEqual(chdiff(render(img, untoned, strength=s)), 1e-4)   # no tone: R=G=B
            self.assertGreater(chdiff(render(img, p, strength=s)), 0.01)            # toned B&W keeps its tone
        # GrayMixer weights act on the B&W conversion
        a = render(img, Params(values={"ConvertToGrayscale": True}))
        b = render(img, Params(values={"ConvertToGrayscale": True, "GrayMixerOrange": 80.0}))
        self.assertGreater(float(np.abs(a - b).max()), 0.01)
        # every real B&W preset: R=G=B when it has no tone, tinted when it has one
        small = photo(max_side=160)
        n = 0
        for path in _util.preset_files():
            if 'ConvertToGrayscale="True"' not in _util.read_text(path):
                continue
            q = load_preset(path)
            toned = any(q.values.get(k, 0) > 0 for k in tone_sats)
            d = chdiff(render(small, q))
            if toned:
                self.assertGreater(d, 1e-4, path)
            else:
                self.assertLessEqual(d, 1e-4, path)
            n += 1
        self.assertEqual(n, 21)

    def test_absolute_wb_skipped_non_raw(self):  # A12
        img = photo(max_side=256)
        d = _util.tmpdir(self)
        a = load_preset(_xmpgen.write(d, "a.xmp", _xmpgen.xmp_text({"IncrementalTemperature": "+20"})))
        b = load_preset(_xmpgen.write(d, "b.xmp", _xmpgen.xmp_text({"IncrementalTemperature": "+20",
                                                                     "WhiteBalance": "Custom",
                                                                     "Temperature": "2500", "Tint": "+60"})))
        self.assertIn("Temperature", b.skipped)
        self.assertIn("Tint", b.skipped)
        self.assertLessEqual(float(np.abs(render(img, a) - render(img, b)).max()), 1e-6)
        # incremental temperature does warm the picture
        warm = render(img, a)
        self.assertGreater((warm[..., 0] - warm[..., 2]).mean(), (img[..., 0] - img[..., 2]).mean() + 0.01)


class TestMasks(unittest.TestCase):  # A14
    def grey(self, h=100, w=200):
        return np.full((h, w, 3), 0.4, dtype=np.float32)

    def test_linear_gradient_geometry(self):
        d = _util.tmpdir(self)
        # zero at y=0.3, full at y=0.7 (relative), effect: brighter
        p = load_preset(_xmpgen.write(d, "lin.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.linear_mask((0.5, 0.3), (0.5, 0.7), {"LocalExposure2012": "0.5"}))))
        out = render(self.grey(), p)
        top, bottom, mid = out[:25].mean(), out[-25:].mean(), out[50].mean()
        self.assertLessEqual(abs(float(top) - 0.4), 1e-4)       # outside (before zero): untouched
        self.assertGreater(bottom, 0.5)                         # fully inside
        self.assertTrue(0.4 < mid < bottom)                     # ramp in between
        inv = load_preset(_xmpgen.write(d, "inv.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.linear_mask((0.5, 0.3), (0.5, 0.7), {"LocalExposure2012": "0.5"}, inverted=True))))
        out = render(self.grey(), inv)
        self.assertLessEqual(abs(float(out[-25:].mean()) - 0.4), 1e-4)
        self.assertGreater(out[:25].mean(), 0.5)

    def test_radial_gradient_geometry(self):
        d = _util.tmpdir(self)
        local = {"LocalExposure2012": "-0.5"}
        p = load_preset(_xmpgen.write(d, "rad.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.radial_mask(0.25, 0.25, 0.75, 0.75, local, flipped=True))))
        out = render(self.grey(), p)
        self.assertLess(out[50, 100].mean(), 0.3)                         # centre: inside ellipse, darker
        self.assertLessEqual(abs(float(out[2, 2].mean()) - 0.4), 1e-4)    # corner untouched
        # Flipped=false puts the effect outside; MaskInverted flips it back
        q = load_preset(_xmpgen.write(d, "rad2.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.radial_mask(0.25, 0.25, 0.75, 0.75, local, flipped=False))))
        out = render(self.grey(), q)
        self.assertLessEqual(abs(float(out[50, 100].mean()) - 0.4), 1e-4)
        self.assertLess(out[2, 2].mean(), 0.3)
        r = load_preset(_xmpgen.write(d, "rad3.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.radial_mask(0.25, 0.25, 0.75, 0.75, local, flipped=False, inverted=True))))
        out = render(self.grey(), r)
        self.assertLess(out[50, 100].mean(), 0.3)
        self.assertLessEqual(abs(float(out[2, 2].mean()) - 0.4), 1e-4)

    def test_radial_feather_softens(self):
        d = _util.tmpdir(self)
        p = load_preset(_xmpgen.write(d, "f.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.radial_mask(0.1, 0.1, 0.9, 0.9, {"LocalExposure2012": "-0.5"}, feather=80))))
        out = render(self.grey(), p)
        c, edge = out[50, 100].mean(), out[50, 30].mean()
        self.assertLess(c, edge)
        self.assertLess(edge, 0.4)


def gpu_busy():
    """A17 skip rule (amended with app-shell B7): (busy, reason) from darkroom_app.gpucheck.gpu_busy -
    utilization median of 5 samples > 15 %, or a busy ComfyUI queue; busy None = nvidia-smi unavailable."""
    from darkroom_app import gpucheck
    return gpucheck.gpu_busy()


RANGE_TABLE = """範圍表（未列者 -100～100）：Exposure2012 -5～5、LocalExposure2012 -4～4、SharpenRadius 0.5～3、Sharpness 0～150、
  SharpenDetail/SharpenEdgeMasking/LuminanceSmoothing/LuminanceNoiseReductionDetail/LuminanceNoiseReductionContrast/
  ColorNoiseReduction/ColorNoiseReductionDetail/ColorNoiseReductionSmoothness/GrainAmount/GrainSize/GrainFrequency/
  PostCropVignetteMidpoint/PostCropVignetteFeather/ParametricShadowSplit/ParametricMidtoneSplit/ParametricHighlightSplit/
  SplitToningShadowSaturation/SplitToningHighlightSaturation/ColorGradeMidtoneSat/ColorGradeGlobalSat/ColorGradeBlending 0～100、
  SplitToningShadowHue/SplitToningHighlightHue/ColorGradeMidtoneHue/ColorGradeGlobalHue/ColorGradeShadowHue/ColorGradeHighlightHue/LocalToningHue 0～360、曲線點 0～255"""


class TestRangeClamp(unittest.TestCase):  # A19
    def huge_params(self):
        vals = {k: 1e9 for k in heavy_values()}
        vals.update({"SharpenRadius": 1e9, "GrainSize": 1e9, "GrainFrequency": 1e9, "Sharpness": 1e9,
                     "PostCropVignetteFeather": 1e9, "PostCropVignetteMidpoint": -1e9, "Exposure2012": 1e9,
                     "ParametricShadowSplit": 1e9, "ColorGradeBlending": -1e9})
        return Params(values=vals, curves={"ToneCurvePV2012": [[0.0, -1e9], [1e9, 1e9]]},
                      masks=[{"name": "m", "amount": 1.0,
                              "values": {"LocalExposure2012": 1e9, "LocalClarity2012": -1e9},
                              "shapes": [{"type": "Mask/Gradient", "inverted": False, "opacity": 1.0, "ZeroX": 0.0,
                                          "ZeroY": 0.0, "FullX": 0.0, "FullY": 1.0}]}])

    def test_huge_values_bounded_time_and_memory(self):
        dev = "cuda" if HAS_CUDA else "cpu"
        img = torch.rand(1, 3, 1000, 1500, device=dev)
        before = 0
        if HAS_CUDA:
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            before = torch.cuda.memory_allocated()
        t0 = time.perf_counter()
        out = render(img, self.huge_params())
        if HAS_CUDA:
            torch.cuda.synchronize()
            peak = torch.cuda.max_memory_allocated() - before
            self.assertLess(peak, 2 * 2**30, f"peak {peak / 2**30:.2f} GiB")
        self.assertLess(time.perf_counter() - t0, 10.0)
        self.assertTrue(bool(torch.isfinite(out).all()))

    def test_render_uses_clamped_values(self):
        img = photo(max_side=128)
        a = render(img, Params(values={"Exposure2012": 5.0, "Sharpness": 150.0}))
        b = render(img, Params(values={"Exposure2012": 1e9, "Sharpness": 1e9}))
        self.assertLessEqual(float(np.abs(a - b).max()), 1e-6)

    def test_range_table_verbatim(self):
        import re
        from darkroom import _params
        body = RANGE_TABLE.split("：", 1)[1].replace("\n", "").replace(" ", "").replace("曲線點", "CURVE")
        expect = {}
        for keys, lo, hi in re.findall(r"([A-Za-z0-9/]+?)(-?[0-9.]+)～(-?[0-9.]+)", body):
            for k in keys.split("/"):
                expect[k] = (float(lo), float(hi))
        self.assertEqual(expect.pop("CURVE"), _params.CURVE_RANGE)
        self.assertGreaterEqual(len(expect), 32)
        for k in ("ColorGradeShadowHue", "ColorGradeHighlightHue", "LocalToningHue"):
            self.assertEqual(expect[k], (0.0, 360.0))
        for k, r in expect.items():
            self.assertEqual(_params.value_range(k), r, k)
        self.assertEqual(_params.value_range("Contrast2012"), (-100.0, 100.0))


@unittest.skipUnless(HAS_CUDA, "needs CUDA")
class TestSpeedAndDevice(unittest.TestCase):  # A17
    def test_full_pipeline_15mp_median(self):
        img = torch.rand(1, 3, 1000, 1500, device="cuda")
        p = heavy_params()
        render(img, p)
        torch.cuda.synchronize()
        busy, reason = gpu_busy()
        if busy is None or busy:
            msg = f"[A17] skipped: {reason}"
            print("\n" + msg)
            self.skipTest(msg)
        print(f"\n[A17] GPU idle, measuring: {reason}")
        for _ in range(5):
            render(img, p)
        torch.cuda.synchronize()
        ts = []
        for _ in range(20):
            t0 = time.perf_counter()
            render(img, p)
            torch.cuda.synchronize()
            ts.append((time.perf_counter() - t0) * 1000)
        med = statistics.median(ts)
        print(f"\n[A17] 1.5MP full global pipeline median {med:.2f} ms (min {min(ts):.2f})")
        self.assertLessEqual(med, 25.0)

    def test_cpu_matches_cuda(self):
        img = photo(max_side=512)
        p = heavy_params()
        a = render(img, p, device="cuda")
        b = render(img, p, device="cpu")
        self.assertLessEqual(float(np.abs(a - b).max()), 1e-3)

    def test_auto_cpu_without_cuda(self):
        from darkroom import _render
        img = photo(max_side=128)
        with mock.patch("torch.cuda.is_available", return_value=False):
            self.assertEqual(_render.pick_device(None).type, "cpu")
            out = render(img, heavy_params())
        self.assertLessEqual(float(np.abs(out - render(img, heavy_params(), device="cuda")).max()), 1e-3)


class TestColorSpace(unittest.TestCase):  # A18
    def test_srgb_linear_roundtrip(self):
        from darkroom import _color
        g = torch.linspace(0, 1, 4097)
        rgb = torch.stack(torch.meshgrid(g[::64], g[::64], g[::64], indexing="ij"), 0).reshape(1, 3, -1, 1)
        for x in (g.view(1, 1, -1, 1).expand(1, 3, -1, 1), rgb):
            back = _color.linear_to_srgb(_color.srgb_to_linear(x))
            self.assertLessEqual(float((back - x).abs().max()), 1e-4)

    def test_pipeline_working_space_roundtrip(self):
        from darkroom import _color
        x = torch.rand(1, 3, 64, 64)
        lin = _color.srgb_to_linear(x)
        self.assertTrue(bool((lin <= x + 1e-7).all()))  # linear light is darker than encoded
        self.assertLessEqual(float((_color.linear_to_srgb(lin) - x).abs().max()), 1e-4)


if __name__ == "__main__":
    unittest.main()
