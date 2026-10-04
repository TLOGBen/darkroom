"""xmp parsing: A4, A5, A12 (parse side), A13 (parse side), A15."""
import builtins
import io
import os
import unittest
from unittest import mock

import _util
import _xmpgen
from darkroom import Params, UnsupportedPresetError, load_preset


class TestVersion(unittest.TestCase):
    def test_pv67_raises_unsupported(self):  # A4
        p = _util.find_preset(r'crs:ProcessVersion="6\.7"')
        with self.assertRaises(UnsupportedPresetError) as cm:
            load_preset(p)
        self.assertEqual(cm.exception.process_version, "6.7")

    def test_synthetic_pv67_raises(self):
        d = _util.tmpdir(self)
        p = _xmpgen.write(d, "old.xmp", _xmpgen.xmp_text({"ProcessVersion": "6.7", "Exposure2012": "+0.50"}))
        self.assertRaises(UnsupportedPresetError, load_preset, p)

    def test_supported_versions_load(self):
        for pv in ("10.0", "11.0", "15.4"):
            p = _util.find_preset(rf'crs:ProcessVersion="{pv}"')
            self.assertIsInstance(load_preset(p), Params)


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


if __name__ == "__main__":
    unittest.main()
