"""Skipped preset settings for the editor: Chinese names (Lightroom zh-TW wording) and two levels (contract R4).

minor = detail settings that barely change how a JPEG preview looks (noise reduction, sharpening details, lens
corrections, grain roughness, values clamped while reading); major = everything else, including keys this
table does not know (white balance, Look, camera profile, HDR, masks, point colours).
"""
import re

LABELS = {
    # look-changing
    "Temperature": "色溫（絕對值）", "Tint": "色調（絕對值）", "Look": "描述檔外觀", "CameraProfile": "相機描述檔",
    "HDREditMode": "HDR 編輯模式", "WhiteBalance": "白平衡", "PointColors": "點顏色", "ColorVariance": "點顏色變化",
    "MaskGroupBasedCorrections": "局部調整", "CorrectionRangeMask": "範圍遮色片", "Mask": "局部遮色片",
    # detail
    "ColorNoiseReduction": "雜色減少（顏色）", "LuminanceSmoothing": "雜色減少（明度）",
    "ColorNoiseReductionDetail": "顏色雜色細節", "ColorNoiseReductionSmoothness": "顏色雜色平滑度",
    "LuminanceNoiseReductionDetail": "明度雜色細節", "LuminanceNoiseReductionContrast": "明度雜色對比",
    "SharpenDetail": "銳利化細節", "SharpenEdgeMasking": "銳利化遮色片", "GrainFrequency": "顆粒粗糙度",
    "AutoLateralCA": "移除色差", "LensProfileEnable": "鏡頭描述檔校正", "LensProfileVignettingScale": "鏡頭暈影校正量",
    "LensProfileDistortionScale": "鏡頭扭曲校正量", "DefringePurpleAmount": "去邊（紫色量）",
    "DefringePurpleHueLo": "去邊（紫色色相下限）", "DefringePurpleHueHi": "去邊（紫色色相上限）",
    "DefringeGreenAmount": "去邊（綠色量）", "DefringeGreenHueLo": "去邊（綠色色相下限）",
    "DefringeGreenHueHi": "去邊（綠色色相上限）", "VignetteAmount": "鏡頭暈影量", "VignetteMidpoint": "鏡頭暈影中點",
    "PostCropVignetteHighlightContrast": "裁切後暈影亮部", "PostCropVignetteStyle": "裁切後暈影樣式",
    "PostCropVignetteRoundness": "裁切後暈影圓度",
}

MINOR = frozenset([
    "ColorNoiseReduction", "LuminanceSmoothing", "ColorNoiseReductionDetail", "ColorNoiseReductionSmoothness",
    "LuminanceNoiseReductionDetail", "LuminanceNoiseReductionContrast", "SharpenDetail", "SharpenEdgeMasking",
    "GrainFrequency", "AutoLateralCA", "LensProfileEnable", "LensProfileVignettingScale",
    "LensProfileDistortionScale", "DefringePurpleAmount", "DefringePurpleHueLo", "DefringePurpleHueHi",
    "DefringeGreenAmount", "DefringeGreenHueLo", "DefringeGreenHueHi", "VignetteAmount", "VignetteMidpoint",
    "PostCropVignetteHighlightContrast", "PostCropVignetteStyle", "PostCropVignetteRoundness",
])

# Names for keys that may appear as "<key>（超出範圍，已夾值）" (clamped while reading).
VALUE_LABELS = {
    "Exposure2012": "曝光", "Contrast2012": "對比", "Highlights2012": "亮部", "Shadows2012": "陰影",
    "Whites2012": "白色", "Blacks2012": "黑色", "Texture": "紋理", "Clarity2012": "清晰度", "Dehaze": "去朦朧",
    "Vibrance": "鮮豔度", "Saturation": "飽和度", "Sharpness": "銳利化", "GrainAmount": "顆粒",
    "ToneCurvePV2012": "點曲線", "ToneCurvePV2012Red": "點曲線（紅）", "ToneCurvePV2012Green": "點曲線（綠）",
    "ToneCurvePV2012Blue": "點曲線（藍）",
}

PRESET_CROP = "裁切（preset 帶的裁切與拉直不會套用）"     # verbatim (CONTRACT-s3-crop C10): minor
PRESET_CROP_LABEL = "裁切（preset 帶的，不套用）"           # verbatim (C10)
CLAMPED = "（超出範圍，已夾值）"
APPROXIMATED = "，已以黑白近似）"     # a black & white Look rendered as the grayscale conversion (S5): minor
BANNER = "這個 preset 有 {n} 項會改變觀感的設定無法套用：{items_joined_by_、}"   # verbatim (contract R4)
NOTE = "另有 {n} 項細節設定未套用：{items_joined_by_、}"                          # verbatim (contract R4)

_SPLIT = re.compile(r"^([^（]+)(（.*）)?$")


def _parts(item):
    m = _SPLIT.match(item)
    key, suffix = (m.group(1), m.group(2) or "") if m else (item, "")
    base = key.split("/")[0] if key.startswith("Mask/") else key
    return key, base, suffix


def level(item):
    if item == PRESET_CROP:
        return "minor"
    key, base, suffix = _parts(item)
    if suffix == CLAMPED or base in MINOR:
        return "minor"
    if key == "Look" and suffix.endswith(APPROXIMATED):
        return "minor"
    return "major"


def label(item):
    if item == PRESET_CROP:
        return PRESET_CROP_LABEL
    key, base, suffix = _parts(item)
    if suffix == CLAMPED:
        return VALUE_LABELS.get(key, LABELS.get(key, key)) + CLAMPED
    if base == "Mask":
        return f"{LABELS['Mask']}（{key[len('Mask/'):]}）{suffix}"
    if key == "WhiteBalance" and suffix == "（Auto）":
        return "白平衡（自動）"
    if key == "PostCropVignetteRoundness" and suffix:
        return LABELS[key] + "（負值）"
    name = LABELS.get(key)
    if name is None:
        return item
    return name + suffix


def _sentence(template, items):
    if not items:
        return ""
    return template.replace("{n}", str(len(items))).replace("{items_joined_by_、}", "、".join(items))


def summarize(skipped):
    """{"level": "major"|"minor"|"", "banner": str, "note": str}."""
    major = [label(i) for i in skipped if level(i) == "major"]
    minor = [label(i) for i in skipped if level(i) == "minor"]
    return {"level": "major" if major else ("minor" if minor else ""),
            "banner": _sentence(BANNER, major), "note": _sentence(NOTE, minor)}
