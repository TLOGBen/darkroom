"""Parameter schema and strength: A6, A7."""
import json
import re
import unittest

import _util
import _xmpgen
from darkroom import SCHEMA_VERSION, Params, UnsupportedPresetError, load_preset

# Verbatim from the contract (copy-paste, do not retype).
DEFAULT_TABLE = """預設表（未列者為 0）：SharpenRadius 1.0、SharpenDetail 25、SharpenEdgeMasking 0、LuminanceNoiseReductionDetail 50、
  LuminanceNoiseReductionContrast 0、ColorNoiseReduction 25、ColorNoiseReductionDetail 50、ColorNoiseReductionSmoothness 50、
  GrainSize 25、GrainFrequency 50、PostCropVignetteMidpoint 50、PostCropVignetteFeather 50、PostCropVignetteRoundness 0、
  PostCropVignetteStyle 1、PostCropVignetteHighlightContrast 0、ParametricShadowSplit 25、ParametricMidtoneSplit 50、
  ParametricHighlightSplit 75、ColorGradeBlending 50、SplitToningBalance 0"""


def contract_defaults():
    body = DEFAULT_TABLE.split("：", 1)[1]
    return {k: float(v) for k, v in re.findall(r"([A-Za-z]+) ([0-9.]+)", body)}


class TestSchema(unittest.TestCase):
    def test_params_json_roundtrip_and_schema(self):  # A6
        self.assertEqual(SCHEMA_VERSION, "darkroom-params/1")
        n = 0
        for path in _util.preset_files():
            try:
                p = load_preset(path)
            except UnsupportedPresetError:
                continue
            d = json.loads(p.to_json())
            self.assertEqual(list(d.keys()), ["schema", "values", "curves", "masks", "skipped"])
            self.assertEqual(d["schema"], SCHEMA_VERSION)
            self.assertIsInstance(d["values"], dict)
            self.assertIsInstance(d["curves"], dict)
            self.assertIsInstance(d["masks"], list)
            self.assertIsInstance(d["skipped"], list)
            for k in d["values"]:
                self.assertFalse(k.startswith("crs:"), k)
                self.assertRegex(k, r"^[A-Za-z][A-Za-z0-9]*$")
            back = Params.from_json(p.to_json())
            self.assertEqual(back, p, path)
            self.assertEqual(back.to_json(), p.to_json())
            n += 1
        self.assertEqual(n, 1466)

    def test_known_lightroom_keys(self):
        d = _util.tmpdir(self)
        p = load_preset(_xmpgen.write(d, "k.xmp", _xmpgen.xmp_text({"Exposure2012": "+0.50", "Clarity2012": "+20"})))
        self.assertEqual(p.values["Exposure2012"], 0.5)
        self.assertEqual(p.values["Clarity2012"], 20.0)

    def test_from_dict_rejects_other_schema(self):
        self.assertRaises(ValueError, Params.from_json, json.dumps(
            {"schema": "darkroom-params/0", "values": {}, "curves": {}, "masks": [], "skipped": []}))
        self.assertRaises(ValueError, Params.from_json, json.dumps({"schema": SCHEMA_VERSION, "values": {}}))

    def test_direct_construction(self):
        p = Params(values={"Exposure2012": 1.0})
        self.assertEqual(Params.from_json(p.to_json()), p)


class TestStrength(unittest.TestCase):
    def test_strength_interpolates_from_defaults(self):  # A7
        from darkroom import _params
        self.assertEqual(_params.DEFAULTS, contract_defaults())
        vals = {"Exposure2012": 1.0, "Contrast2012": 40.0, "SharpenRadius": 2.0, "GrainSize": 75.0,
                "ParametricShadowSplit": 35.0, "ColorGradeBlending": 100.0, "PostCropVignetteStyle": 2.0,
                "SplitToningShadowHue": 200.0, "SplitToningHighlightHue": 40.0, "ColorGradeMidtoneHue": 120.0,
                "ColorGradeGlobalHue": 300.0, "ColorGradeShadowHue": 10.0, "ColorGradeHighlightHue": 20.0,
                "SplitToningShadowSaturation": 30.0, "HueAdjustmentRed": 20.0, "ConvertToGrayscale": True}
        p = Params(values=vals, curves={"ToneCurvePV2012": [[0.0, 30.0], [128.0, 140.0], [255.0, 230.0]]})
        for s in (0.0, 0.5, 1.0, 1.5, 2.0):
            q = p.at_strength(s)
            for k, v in vals.items():
                if k == "ConvertToGrayscale":
                    self.assertEqual(q.values[k], s > 0)
                elif k.endswith("Hue") and (k.startswith("SplitToning") or k.startswith("ColorGrade")):
                    self.assertEqual(q.values[k], v, k)
                else:
                    dflt = contract_defaults().get(k, 0.0)
                    self.assertAlmostEqual(q.values[k], dflt + s * (v - dflt), places=9, msg=(k, s))
            for (x, y), (qx, qy) in zip(p.curves["ToneCurvePV2012"], q.curves["ToneCurvePV2012"]):
                self.assertEqual(qx, x)
                self.assertAlmostEqual(qy, min(255.0, max(0.0, x + s * (y - x))), places=9)
        # HSL hue shift is a slider (scaled), not a hue angle
        self.assertEqual(p.at_strength(0.5).values["HueAdjustmentRed"], 10.0)
        # clamp: y = 0 + 2*(30-0) = 60 fine; 255 -> 2*(230-255)+255 = 205; an overshoot gets clamped
        q = Params(curves={"ToneCurvePV2012": [[200.0, 250.0]]}).at_strength(2.0)
        self.assertEqual(q.curves["ToneCurvePV2012"][0][1], 255.0)

    def test_strength_range(self):
        p = Params(values={"Exposure2012": 1.0})
        self.assertRaises(ValueError, p.at_strength, -0.1)
        self.assertRaises(ValueError, p.at_strength, 2.01)

    def test_strength_does_not_mutate(self):
        p = Params(values={"Exposure2012": 1.0})
        p.at_strength(0.0)
        self.assertEqual(p.values["Exposure2012"], 1.0)


if __name__ == "__main__":
    unittest.main()
