"""xmp parsing: A4, A5, A12 (parse side), A13 (parse side), A15."""
import builtins
import io
import os
import re
import unittest
from unittest import mock

import _util
import _xmpgen
from darkroom import Params, UnsupportedPresetError, load_preset


class TestVersion(unittest.TestCase):
    def test_pv67_is_supported(self):  # A4 / P4: PV 6.7 is PV2012 (uses the *2012 sliders)
        p = _util.find_preset(r'crs:ProcessVersion="6\.7"')
        self.assertIn("Contrast2012", load_preset(p).values)

    def test_synthetic_old_versions_raise(self):  # A4: PV2010 and older (no *2012 sliders)
        d = _util.tmpdir(self)
        for pv in ("5.7", "5.0"):
            p = _xmpgen.write(d, "old.xmp", _xmpgen.xmp_text({"ProcessVersion": pv, "Exposure": "+0.50",
                                                               "FillLight": "20", "HighlightRecovery": "30"}))
            with self.assertRaises(UnsupportedPresetError) as cm:
                load_preset(p)
            self.assertEqual(cm.exception.process_version, pv)
        p = _xmpgen.write(d, "future.xmp", _xmpgen.xmp_text({"ProcessVersion": "99.0"}))
        self.assertRaises(UnsupportedPresetError, load_preset, p)

    def test_supported_versions_load(self):
        for pv in ("6.7", "10.0", "11.0", "15.4"):
            p = _util.find_preset(rf'crs:ProcessVersion="{pv}"')
            self.assertIsInstance(load_preset(p), Params)
        d = _util.tmpdir(self)
        for pv in ("6.9", "10.2", "11.3", "15.0"):  # other minor versions of the same majors
            p = _xmpgen.write(d, "m.xmp", _xmpgen.xmp_text({"ProcessVersion": pv}))
            self.assertIsInstance(load_preset(p), Params)


class TestSafeXml(unittest.TestCase):  # A20
    def test_doctype_and_entity_rejected(self):
        d = _util.tmpdir(self)
        base = _xmpgen.xmp_text({"Contrast2012": "+10"})
        evil = [
            '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>\n' + base,
            '<?xml version="1.0"?>\n<!DOCTYPE x SYSTEM "file:///C:/Windows/win.ini">\n' + base,
            "<!DOCTYPE x>" + base,
        ]
        for i, text in enumerate(evil):
            p = _xmpgen.write(d, f"e{i}.xmp", text)
            self.assertRaises(ValueError, load_preset, p)
        # same trick in UTF-16 (a plain byte search for "<!DOCTYPE" would miss it)
        p = os.path.join(d, "u16.xmp")
        with open(p, "wb") as f:
            f.write(('<?xml version="1.0" encoding="UTF-16"?>\n<!DOCTYPE x [<!ENTITY a "x">]>\n' + base).encode("utf-16"))
        self.assertRaises(ValueError, load_preset, p)

    def test_uses_xml_parser_not_regex(self):
        """Attribute with spaces around '=' and single quotes still parses (an attribute regex would miss it)."""
        d = _util.tmpdir(self)
        text = _xmpgen.xmp_text({"Contrast2012": "+10"}).replace('crs:Contrast2012="+10"', "crs:Contrast2012 =\n  '+25'")
        self.assertEqual(load_preset(_xmpgen.write(d, "q.xmp", text)).values["Contrast2012"], 25.0)


class TestClampOnParse(unittest.TestCase):  # A19 (parse side)
    def test_out_of_range_values_clamped_and_reported(self):
        d = _util.tmpdir(self)
        p = load_preset(_xmpgen.write(d, "big.xmp", _xmpgen.xmp_text(
            {"Exposure2012": "+9.00", "GrainSize": "1000000000", "SharpenRadius": "+0.10", "Contrast2012": "+400"},
            curves={"ToneCurvePV2012": [(0, 0), (128, 300), (255, 255)]})))
        self.assertEqual(p.values["Exposure2012"], 5.0)
        self.assertEqual(p.values["GrainSize"], 100.0)
        self.assertEqual(p.values["SharpenRadius"], 0.5)
        self.assertEqual(p.values["Contrast2012"], 100.0)
        self.assertEqual(p.curves["ToneCurvePV2012"][1], [128.0, 255.0])
        for k in ("Exposure2012", "GrainSize", "SharpenRadius", "Contrast2012", "ToneCurvePV2012"):
            self.assertTrue(any(s.startswith(k) for s in p.skipped), k)

    def test_in_range_not_reported(self):
        d = _util.tmpdir(self)
        p = load_preset(_xmpgen.write(d, "ok.xmp", _xmpgen.xmp_text({"Exposure2012": "+4.00",
                                                                      "SplitToningShadowHue": "350"})))
        self.assertEqual(p.skipped, [])


class TestNumbers(unittest.TestCase):  # A5
    def test_signs_and_decimals(self):
        d = _util.tmpdir(self)
        p = _xmpgen.write(d, "n.xmp", _xmpgen.xmp_text({
            "Contrast2012": "+15", "Exposure2012": "-0.24", "SharpenRadius": "+0.80", "Blacks2012": "-7"}))
        v = load_preset(p).values
        self.assertEqual(v["Contrast2012"], 15.0)
        self.assertEqual(v["Exposure2012"], -0.24)
        self.assertEqual(v["SharpenRadius"], 0.8)
        self.assertEqual(v["Blacks2012"], -7.0)

    def test_bad_known_numeric_fails_not_zero(self):
        d = _util.tmpdir(self)
        for bad in ("abc", "", "+", "1,5", "nan"):
            p = _xmpgen.write(d, "bad.xmp", _xmpgen.xmp_text({"Contrast2012": bad}))
            with self.assertRaises(ValueError, msg=repr(bad)):
                load_preset(p)

    def test_bad_curve_point_fails(self):
        d = _util.tmpdir(self)
        p = _xmpgen.write(d, "c.xmp", _xmpgen.xmp_text(curves={"ToneCurvePV2012": [(0, 0), ("x", 5), (255, 255)]}))
        self.assertRaises(ValueError, load_preset, p)

    def test_bad_mask_number_fails(self):
        d = _util.tmpdir(self)
        p = _xmpgen.write(d, "m.xmp", _xmpgen.xmp_text(extra=_xmpgen.linear_mask(("0.5", "bogus"), (0.5, 1), {"LocalExposure2012": "0.5"})))
        self.assertRaises(ValueError, load_preset, p)

    def test_curves_parsed(self):
        p = _util.find_preset(r"<crs:ToneCurvePV2012Red>")
        c = load_preset(p).curves
        self.assertIn("ToneCurvePV2012", c)
        for pts in c.values():
            self.assertGreaterEqual(len(pts), 2)
            for x, y in pts:
                self.assertTrue(0 <= x <= 255 and 0 <= y <= 255)


class TestSkipped(unittest.TestCase):
    def test_absolute_wb_in_skipped(self):  # A12
        d = _util.tmpdir(self)
        p = _xmpgen.write(d, "wb.xmp", _xmpgen.xmp_text({"WhiteBalance": "Custom", "Temperature": "5500", "Tint": "+10",
                                                         "IncrementalTemperature": "+12"}))
        pr = load_preset(p)
        self.assertIn("Temperature", pr.skipped)
        self.assertIn("Tint", pr.skipped)
        self.assertEqual(pr.values["IncrementalTemperature"], 12.0)

    def test_real_preset_with_temperature(self):
        p = _util.find_preset(r'crs:Temperature="\d+"', exclude=r'ProcessVersion="6\.7"')
        self.assertIn("Temperature", load_preset(p).skipped)

    def test_look_hdr_unknown_mask_skipped(self):  # A13
        p = _util.find_preset(r"<crs:Look>", exclude=r'ProcessVersion="6\.7"')
        self.assertTrue(any(s.startswith("Look") for s in load_preset(p).skipped))
        p = _util.find_preset(r"crs:HDREditMode=", exclude=r'ProcessVersion="6\.7"')
        self.assertIn("HDREditMode", load_preset(p).skipped)
        d = _util.tmpdir(self)
        p = _xmpgen.write(d, "brush.xmp", _xmpgen.xmp_text(
            extra=_xmpgen.linear_mask((0, 0), (0, 1), {"LocalExposure2012": "0.5"}, what="Mask/Paint")))
        pr = load_preset(p)
        self.assertIn("Mask/Paint", pr.skipped)
        self.assertEqual(sum(len(m["shapes"]) for m in pr.masks), 0)

    def test_monochrome_look_renders_gray(self):  # CONTRACT-s1-experience S5 / core patch K3
        import numpy as np
        from darkroom import render
        from darkroom._xmp import LOOK_APPROXIMATED, MONOCHROME_LOOK
        self.assertEqual(MONOCHROME_LOOK.pattern, r"monochrome|black\s*(?:&|and)\s*white|\bb&w\b")
        self.assertEqual(LOOK_APPROXIMATED, "Look（{name}，已以黑白近似）")
        d = _util.tmpdir(self)
        look = lambda name: f'   <crs:Look>\n    <rdf:Description crs:Name="{name.replace("&", "&amp;")}"/>\n   </crs:Look>\n'
        rng = np.random.default_rng(1)
        img = rng.uniform(0, 1, (48, 64, 3)).astype(np.float32)
        chdiff = lambda o: float(max(np.abs(o[..., 0] - o[..., 1]).max(), np.abs(o[..., 1] - o[..., 2]).max()))
        for name in ("Adobe Monochrome", "Black & White 03", "Kodak Tri-X b&w look", "Classic Black and White"):
            p = load_preset(_xmpgen.write(d, "m.xmp", _xmpgen.xmp_text({"Exposure2012": "+0.2"}, extra=look(name))))
            self.assertIs(p.values.get("ConvertToGrayscale"), True, name)
            self.assertIn(f"Look（{name}，已以黑白近似）", p.skipped, name)
            self.assertLessEqual(chdiff(render(img, p)), 1e-4, name)
        p = load_preset(_xmpgen.write(d, "c.xmp", _xmpgen.xmp_text({"Exposure2012": "+0.2"}, extra=look("Adobe Color"))))
        self.assertNotIn("ConvertToGrayscale", p.values)
        self.assertEqual([s for s in p.skipped if s.startswith("Look")], ["Look（Adobe Color）"])
        self.assertGreater(chdiff(render(img, p)), 0.01)
        from darkroom_app import skips
        self.assertEqual(skips.level("Look（Adobe Monochrome，已以黑白近似）"), "minor")
        self.assertEqual(skips.label("Look（Adobe Monochrome，已以黑白近似）"), "描述檔外觀（Adobe Monochrome，已以黑白近似）")
        self.assertEqual(skips.level("Look（Adobe Color）"), "major")

    def test_library_monochrome_looks(self):  # S5 on the user's library: exactly the 8 Adobe Monochrome presets
        from darkroom._xmp import MONOCHROME_LOOK
        from darkroom_app import skips
        hits = []
        for path in _util.preset_files():
            text = _util.read_text(path)
            m = re.search(r"<crs:Look>.*?crs:Name=\"([^\"]*)\"", text, re.S)
            if m and MONOCHROME_LOOK.search(m.group(1)):
                hits.append((path, m.group(1)))
        self.assertEqual(len(hits), 8)
        for path, name in hits:
            p = load_preset(path)
            self.assertIs(p.values.get("ConvertToGrayscale"), True, path)
            item = f"Look（{name}，已以黑白近似）"
            self.assertIn(item, p.skipped, path)
            self.assertEqual(skips.level(item), "minor", path)        # the Look itself is a note now, not a warning
            self.assertNotIn(skips.label(item), skips.summarize(p.skipped)["banner"], path)

    def test_supported_masks_parsed(self):  # A14 (parse side)
        p = _util.find_preset(r"Mask/CircularGradient", exclude=r'ProcessVersion="6\.7"')
        kinds = {s["type"] for m in load_preset(p).masks for s in m["shapes"]}
        self.assertTrue(kinds <= {"Mask/Gradient", "Mask/CircularGradient"})
        self.assertIn("Mask/CircularGradient", kinds)


class TestReadOnly(unittest.TestCase):  # A15
    def test_load_opens_read_only(self):
        p = _util.find_preset(r"<crs:Look>")
        modes = []
        real_open = builtins.open
        real_io_open = io.open

        def spy(file, mode="r", *a, **k):
            if str(file).endswith(".xmp"):
                modes.append(mode)
            return real_open(file, mode, *a, **k)

        def spy_io(file, mode="r", *a, **k):
            if str(file).endswith(".xmp"):
                modes.append(mode)
            return real_io_open(file, mode, *a, **k)

        with mock.patch("builtins.open", spy), mock.patch("io.open", spy_io):
            try:
                load_preset(p)
            except UnsupportedPresetError:
                pass
            load_preset(_util.find_preset(r'ProcessVersion="11\.0"'))
        self.assertTrue(modes)
        for m in modes:
            self.assertEqual(m, "rb")


# Value at which an unrendered key has no effect (else the contract default table, else 0), and the parent
# amount that switches a sub-setting on. Written out independently of darkroom._coverage on purpose.
NO_EFFECT = {"PerspectiveScale": 100.0, "CurveRefineSaturation": 100.0, "ColorNoiseReduction": 0.0}
PARENT = {"SharpenDetail": "Sharpness", "SharpenEdgeMasking": "Sharpness",
          "LuminanceNoiseReductionDetail": "LuminanceSmoothing", "LuminanceNoiseReductionContrast": "LuminanceSmoothing",
          "ColorNoiseReductionDetail": "ColorNoiseReduction", "ColorNoiseReductionSmoothness": "ColorNoiseReduction",
          "DefringePurpleHueLo": "DefringePurpleAmount", "DefringePurpleHueHi": "DefringePurpleAmount",
          "DefringeGreenHueLo": "DefringeGreenAmount", "DefringeGreenHueHi": "DefringeGreenAmount",
          "LensProfileDistortionScale": "LensProfileEnable", "LensProfileVignettingScale": "LensProfileEnable",
          "VignetteMidpoint": "VignetteAmount", "GrainFrequency": "GrainAmount",
          "PostCropVignetteStyle": "PostCropVignetteAmount", "PostCropVignetteHighlightContrast": "PostCropVignetteAmount",
          "ColorGradeShadowHue": "ColorGradeShadowSat", "ColorGradeHighlightHue": "ColorGradeHighlightSat",
          "LocalToningHue": "LocalToningSaturation"}


# B14 (1): the rendered keys written out independently of darkroom._coverage (one per renderer stage).
_COLORS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
RENDERED_KEYS = frozenset(
    ["IncrementalTemperature", "IncrementalTint", "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012",
     "Whites2012", "Blacks2012", "Clarity2012", "Texture", "Dehaze", "Vibrance", "Saturation",
     "ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights",
     "ParametricShadowSplit", "ParametricMidtoneSplit", "ParametricHighlightSplit",
     "SplitToningShadowHue", "SplitToningShadowSaturation", "SplitToningHighlightHue",
     "SplitToningHighlightSaturation", "SplitToningBalance",
     "ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeGlobalHue", "ColorGradeGlobalSat",
     "ColorGradeShadowLum", "ColorGradeMidtoneLum", "ColorGradeHighlightLum", "ColorGradeGlobalLum",
     "ColorGradeBlending",
     "RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation", "ShadowTint",
     "ConvertToGrayscale",
     "PostCropVignetteAmount", "PostCropVignetteMidpoint", "PostCropVignetteFeather", "PostCropVignetteRoundness",
     "GrainAmount", "GrainSize", "Sharpness", "SharpenRadius"]
    + [f"{kind}Adjustment{c}" for kind in ("Hue", "Saturation", "Luminance") for c in _COLORS]
    + [f"GrayMixer{c}" for c in _COLORS])
LOCAL_RENDERED_KEYS = frozenset(
    ["LocalExposure2012", "LocalContrast2012", "LocalHighlights2012", "LocalShadows2012", "LocalWhites2012",
     "LocalBlacks2012", "LocalClarity2012", "LocalTexture", "LocalDehaze", "LocalTemperature", "LocalTint",
     "LocalSaturation"])


class TestCoverage(unittest.TestCase):  # A13 (full library)
    def test_rendered_list_matches_coverage(self):  # B14 (1)
        from darkroom import _coverage
        self.assertEqual(RENDERED_KEYS, _coverage.RENDERED)
        self.assertEqual(LOCAL_RENDERED_KEYS, _coverage.LOCAL_RENDERED)

    def test_every_effective_key_rendered_or_skipped(self):
        from darkroom import _coverage, _params
        no_effect = lambda k: NO_EFFECT.get(k, _params.DEFAULTS.get(k, 0.0))
        counts = {"GrainFrequency": 0, "PostCropVignetteHighlightContrast": 0, "PostCropVignetteRoundness": 0}

        def check(values, skipped, rendered, path):
            for k, v in values.items():
                in_skipped = any(s == k or s.startswith(k + "（") for s in skipped)
                if k == "PostCropVignetteRoundness" and v < 0 and values.get("PostCropVignetteAmount", 0) != 0:
                    self.assertTrue(in_skipped, (path, k))
                    counts[k] += 1
                    continue
                if k in rendered or in_skipped:
                    if in_skipped and k in counts:
                        counts[k] += 1
                    continue
                parent = PARENT.get(k)
                if parent is not None and values.get(parent, no_effect(parent)) == no_effect(parent):
                    continue  # sub-setting of a feature that is off
                if parent is not None:
                    self.assertEqual(v, _params.DEFAULTS.get(k, 0.0), (path, k))
                else:
                    self.assertEqual(v, no_effect(k), (path, k))

        for path in _util.preset_files():
            p = load_preset(path)
            check(p.values, p.skipped, RENDERED_KEYS, path)
            for m in p.masks:
                check(m["values"], p.skipped, LOCAL_RENDERED_KEYS, path)
        # the three keys found unreported in seal round 1 (F3) are now reported wherever they have an effect
        self.assertEqual(counts, {"GrainFrequency": 173, "PostCropVignetteHighlightContrast": 20,
                                  "PostCropVignetteRoundness": 4})
        for k in ("GrainFrequency", "PostCropVignetteHighlightContrast", "PostCropVignetteStyle"):
            self.assertNotIn(k, RENDERED_KEYS)


if __name__ == "__main__":
    unittest.main()
