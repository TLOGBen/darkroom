"""Which Lightroom settings the renderer applies (kept torch-free so parsing stays fast).

Anything present in a preset that is neither rendered nor a harmless detail key, and differs from its
inactive value, is reported in Params.skipped instead of being silently dropped.

Layer: core library. Depends only on `_params` (imported lazily inside functions to avoid an import cycle,
because `_params` itself is imported by `_xmp`, which imports this module). Used by `_xmp` while parsing (to fill
`Params.skipped`) and by the App's skip classification (minor / major) through the parsed Params.

Why a coverage table at all: the user bought these presets and expects them to look like Lightroom. When a
preset relies on something the renderer cannot reproduce (lens profiles, noise reduction, perspective, ...),
saying so is better than showing a picture that silently differs. The rules below are written to avoid false
alarms: a setting only counts when it would actually change the picture.
"""

_HSL = [f"{kind}Adjustment{c}" for kind in ("Hue", "Saturation", "Luminance")
        for c in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")]
_GRAY = [f"GrayMixer{c}" for c in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")]

# Global crs keys (without the "crs:" prefix) that _render actually implements. Anything in a preset outside this
# set (and outside the exceptions below) is a candidate for Params.skipped.
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

# Absolute white balance: kept as data, always reported by name by the parser (A12 = contract rule "an absolute
# Kelvin/tint white balance is never rendered on JPEG/TIFF input and is always listed in skipped by name").
# Lightroom only applies absolute Temperature/Tint to RAW files; on already-developed pixels it uses the relative
# IncrementalTemperature/IncrementalTint, which the renderer does implement.
ABSOLUTE_WB = frozenset(["Temperature", "Tint"])

# Value at which an unrendered setting does nothing (otherwise its default from the defaults table).
# These three differ from the defaults table because their "off" position is not their Lightroom default
# (e.g. PerspectiveScale is a percentage where 100 means "no scaling").
INACTIVE = {"PerspectiveScale": 100.0, "CurveRefineSaturation": 100.0, "ColorNoiseReduction": 0.0}


def inactive_value(key):
    """The value of `key` at which it has no visible effect (INACTIVE, else the defaults table, else 0)."""
    from ._params import default
    return INACTIVE.get(key, default(key))


def unrendered_active(key, values, rendered=None):
    """True when `key` is present with an effect the renderer does not apply (so it belongs in skipped).

    key: a crs key present in `values`; values: the whole parsed {key: value} dict of the preset (needed because
    some keys only matter when a parent amount is on); rendered: the set of keys considered implemented (defaults
    to RENDERED, the local-adjustment parser passes LOCAL_RENDERED). Pure function, no side effects.

    Decision order: a negative vignette roundness is the one rendered key with an unsupported range; rendered and
    absolute-WB keys are never "active-unrendered" here (absolute WB is reported separately by the parser); a
    detail sub-setting only counts when its parent is switched on; anything else counts when it differs from its
    inactive value.
    """
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


# Local (masked) adjustment keys the renderer applies inside a supported mask; other Local* keys with a non-zero
# value make the mask's entry appear in skipped.
LOCAL_RENDERED = frozenset([
    "LocalExposure2012", "LocalContrast2012", "LocalHighlights2012", "LocalShadows2012", "LocalWhites2012",
    "LocalBlacks2012", "LocalClarity2012", "LocalTexture", "LocalDehaze", "LocalTemperature", "LocalTint",
    "LocalSaturation",
])

# Mask shapes the renderer can rebuild from numbers alone (linear and radial gradients). Brush strokes, AI subject
# / sky masks and range masks need pixel data or a model, so presets using them are reported instead.
SUPPORTED_MASKS = ("Mask/Gradient", "Mask/CircularGradient")
