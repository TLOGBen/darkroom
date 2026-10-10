"""The editor's sliders: Lightroom crs keys the renderer applies, with their range and default.

Overrides sent by the front end are differences added after strength (see preview.effective_params); only
these keys are accepted. Ranges and defaults agree with the core library's tables (checked by the tests).

Layer: domain (pure data). Used by domain/adjustment.py (which keys an override may name) and the preset detail.

Each entry: key (crs name), label (zh-TW, Lightroom wording), group (the panel it appears in), min / max / default /
step (what the slider allows), sub (h / s / l for the HSL panel's three tabs), hue (a hue angle, drawn as a colour
wheel). The order of SLIDERS is the order the editor draws them.
"""

_C = (("Red", "紅"), ("Orange", "橙"), ("Yellow", "黃"), ("Green", "綠"), ("Aqua", "淺綠"), ("Blue", "藍"),
      ("Purple", "紫"), ("Magenta", "洋紅"))

GROUPS = (("basic", "基本"), ("curve", "曲線"), ("hsl", "HSL"), ("grade", "顏色分級"), ("detail", "細節"),
          ("effect", "效果"), ("calib", "校正"))


def _s(group, key, label, lo=-100.0, hi=100.0, default=0.0, step=1.0, sub=None, hue=False):
    """One slider entry (defaults: the common -100..100 slider with default 0 and step 1)."""
    return {"key": key, "label": label, "group": group, "min": lo, "max": hi, "default": default, "step": step,
            "sub": sub, "hue": hue}


SLIDERS = [
    _s("basic", "IncrementalTemperature", "色溫（增量）"),
    _s("basic", "IncrementalTint", "色調（增量）"),
    _s("basic", "Exposure2012", "曝光", -5.0, 5.0, step=0.05),
    _s("basic", "Contrast2012", "對比"),
    _s("basic", "Highlights2012", "亮部"),
    _s("basic", "Shadows2012", "陰影"),
    _s("basic", "Whites2012", "白色"),
    _s("basic", "Blacks2012", "黑色"),
    _s("basic", "Texture", "紋理"),
    _s("basic", "Clarity2012", "清晰度"),
    _s("basic", "Dehaze", "去朦朧"),
    _s("basic", "Vibrance", "鮮豔度"),
    _s("basic", "Saturation", "飽和度"),
    _s("curve", "ParametricHighlights", "亮部區"),
    _s("curve", "ParametricLights", "亮色調"),
    _s("curve", "ParametricDarks", "暗色調"),
    _s("curve", "ParametricShadows", "陰影區"),
    *[_s("hsl", f"HueAdjustment{c}", n, sub="h") for c, n in _C],
    *[_s("hsl", f"SaturationAdjustment{c}", n, sub="s") for c, n in _C],
    *[_s("hsl", f"LuminanceAdjustment{c}", n, sub="l") for c, n in _C],
    _s("grade", "SplitToningShadowHue", "陰影 色相", 0.0, 360.0, hue=True),
    _s("grade", "SplitToningShadowSaturation", "陰影 飽和", 0.0, 100.0),
    _s("grade", "ColorGradeMidtoneHue", "中間調 色相", 0.0, 360.0, hue=True),
    _s("grade", "ColorGradeMidtoneSat", "中間調 飽和", 0.0, 100.0),
    _s("grade", "SplitToningHighlightHue", "亮部 色相", 0.0, 360.0, hue=True),
    _s("grade", "SplitToningHighlightSaturation", "亮部 飽和", 0.0, 100.0),
    _s("grade", "ColorGradeBlending", "混合", 0.0, 100.0, 50.0),
    _s("grade", "SplitToningBalance", "平衡"),
    _s("detail", "Sharpness", "銳化 量", 0.0, 150.0),
    _s("detail", "SharpenRadius", "銳化 半徑", 0.5, 3.0, 1.0, 0.1),
    _s("effect", "PostCropVignetteAmount", "暗角 量"),
    _s("effect", "PostCropVignetteMidpoint", "暗角 中點", 0.0, 100.0, 50.0),
    _s("effect", "GrainAmount", "顆粒 量", 0.0, 100.0),
    _s("effect", "GrainSize", "顆粒 大小", 0.0, 100.0, 25.0),
    _s("calib", "RedHue", "紅原色 色相"),
    _s("calib", "RedSaturation", "紅原色 飽和"),
    _s("calib", "GreenHue", "綠原色 色相"),
    _s("calib", "GreenSaturation", "綠原色 飽和"),
    _s("calib", "BlueHue", "藍原色 色相"),
    _s("calib", "BlueSaturation", "藍原色 飽和"),
]

BY_KEY = {s["key"]: s for s in SLIDERS}
