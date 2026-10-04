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
    "PostCropVignetteAmount", "PostCropVignetteMidpoint", "PostCropVignetteFeather", "PostCropVignetteRoundness",
    "PostCropVignetteStyle", "PostCropVignetteHighlightContrast",
    "GrainAmount", "GrainSize", "GrainFrequency",
    "Sharpness", "SharpenRadius",
    *_HSL, *_GRAY,
])

# Sub-settings of a feature: only meaningful when the feature's main amount is on (reported via that amount).
DETAIL = frozenset([
    "SharpenDetail", "SharpenEdgeMasking", "LuminanceNoiseReductionDetail", "LuminanceNoiseReductionContrast",
    "ColorNoiseReductionDetail", "ColorNoiseReductionSmoothness", "DefringePurpleHueLo", "DefringePurpleHueHi",
    "DefringeGreenHueLo", "DefringeGreenHueHi", "LensProfileDistortionScale", "LensProfileVignettingScale",
    "VignetteMidpoint", "CropConstrainToWarp",
    # absolute white balance is reported by name (Temperature / Tint) by the parser
    "Temperature", "Tint",
])

# Value at which an unrendered setting does nothing (otherwise 0).
INACTIVE = {"PerspectiveScale": 100.0, "CurveRefineSaturation": 100.0, "ColorNoiseReduction": 0.0}

LOCAL_RENDERED = frozenset([
    "LocalExposure2012", "LocalContrast2012", "LocalHighlights2012", "LocalShadows2012", "LocalWhites2012",
    "LocalBlacks2012", "LocalClarity2012", "LocalTexture", "LocalDehaze", "LocalTemperature", "LocalTint",
    "LocalSaturation",
])
LOCAL_DETAIL = frozenset(["LocalToningHue"])

SUPPORTED_MASKS = ("Mask/Gradient", "Mask/CircularGradient")
