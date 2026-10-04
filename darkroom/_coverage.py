"""Which Lightroom settings the renderer applies (kept torch-free so parsing stays fast).

Anything present in a preset that is neither rendered nor a harmless detail key, and differs from its
inactive value, is reported in Params.skipped instead of being silently dropped.
"""

_HSL = [f"{kind}Adjustment{c}" for kind in ("Hue", "Saturation", "Luminance")
        for c in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")]
_GRAY = [f"GrayMixer{c}" for c in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")]

RENDERED = frozenset([
    "IncrementalTemperature", "IncrementalTint",
    "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
    "Clarity2012", "Texture", "Dehaze", "Vibrance", "Saturation",
    "ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights",
    "ParametricShadowSplit", "ParametricMidtoneSplit", "ParametricHighlightSplit",
    "SplitToningShadowHue", "SplitToningShadowSaturation", "SplitToningHighlightHue",
    "SplitToningHighlightSaturation", "SplitToningBalance",
    "ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeGlobalHue", "ColorGradeGlobalSat",
    "ColorGradeShadowLum", "ColorGradeMidtoneLum", "ColorGradeHighlightLum", "ColorGradeGlobalLum",
    "ColorGradeBlending",
    "RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation", "ShadowTint",
    "ConvertToGrayscale",
    "PostCropVignetteAmount", "PostCropVignetteMidpoint", "PostCropVignetteFeather",
    "PostCropVignetteRoundness",  # positive values only; negative ones are reported (see unrendered_active)
    "GrainAmount", "GrainSize",
    "Sharpness", "SharpenRadius",
    *_HSL, *_GRAY,
])

# Sub-settings that do nothing while their parent amount sits at its inactive value. When the parent is on and
# the sub-setting differs from its default, it is reported like any other unrendered setting.
DETAIL_PARENT = {
    "SharpenDetail": "Sharpness", "SharpenEdgeMasking": "Sharpness",
    "LuminanceNoiseReductionDetail": "LuminanceSmoothing", "LuminanceNoiseReductionContrast": "LuminanceSmoothing",
    "ColorNoiseReductionDetail": "ColorNoiseReduction", "ColorNoiseReductionSmoothness": "ColorNoiseReduction",
    "DefringePurpleHueLo": "DefringePurpleAmount", "DefringePurpleHueHi": "DefringePurpleAmount",
    "DefringeGreenHueLo": "DefringeGreenAmount", "DefringeGreenHueHi": "DefringeGreenAmount",
    "LensProfileDistortionScale": "LensProfileEnable", "LensProfileVignettingScale": "LensProfileEnable",
    "VignetteMidpoint": "VignetteAmount",
    "GrainFrequency": "GrainAmount",
    "PostCropVignetteStyle": "PostCropVignetteAmount", "PostCropVignetteHighlightContrast": "PostCropVignetteAmount",
    "ColorGradeShadowHue": "ColorGradeShadowSat", "ColorGradeHighlightHue": "ColorGradeHighlightSat",
    "LocalToningHue": "LocalToningSaturation",
}

# Absolute white balance: kept as data, always reported by name by the parser (A12).
ABSOLUTE_WB = frozenset(["Temperature", "Tint"])

# Value at which an unrendered setting does nothing (otherwise its default from the defaults table).
INACTIVE = {"PerspectiveScale": 100.0, "CurveRefineSaturation": 100.0, "ColorNoiseReduction": 0.0}


def inactive_value(key):
    from ._params import default
    return INACTIVE.get(key, default(key))


def unrendered_active(key, values, rendered=None):
    """True when `key` is present with an effect the renderer does not apply (so it belongs in skipped)."""
    rendered = RENDERED if rendered is None else rendered
    v = values[key]
    if key == "PostCropVignetteRoundness":
        return v < 0 and values.get("PostCropVignetteAmount", 0.0) != 0
    if key in rendered or key in ABSOLUTE_WB:
        return False
    parent = DETAIL_PARENT.get(key)
    if parent is not None:
        if values.get(parent, inactive_value(parent)) == inactive_value(parent):
            return False
        from ._params import default
        return v != default(key)
    return v != inactive_value(key)


LOCAL_RENDERED = frozenset([
    "LocalExposure2012", "LocalContrast2012", "LocalHighlights2012", "LocalShadows2012", "LocalWhites2012",
    "LocalBlacks2012", "LocalClarity2012", "LocalTexture", "LocalDehaze", "LocalTemperature", "LocalTint",
    "LocalSaturation",
])

SUPPORTED_MASKS = ("Mask/Gradient", "Mask/CircularGradient")
