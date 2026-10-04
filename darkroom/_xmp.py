"""Lightroom .xmp preset -> Params. Files are only ever opened read-only ("rb")."""
import os
import re
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat

from . import _coverage as cov
from ._errors import UnsupportedPresetError
from ._params import CURVE_RANGE, UNCLAMPED_DATA_KEYS, Params, clamp_value, default

CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_NUM = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
# PV2012-family process versions (all use the *2012 sliders); any minor version of these majors is accepted.
SUPPORTED_PV_MAJORS = (6, 10, 11, 15)

# Numeric attributes that are adjustments (a parse failure on any of these fails the preset).
KNOWN_NUMERIC = frozenset(cov.RENDERED - {"ConvertToGrayscale"}) | cov.DETAIL | frozenset([
    "LuminanceSmoothing", "ColorNoiseReduction", "DefringePurpleAmount", "DefringeGreenAmount", "AutoLateralCA",
    "LensProfileEnable", "LensManualDistortionAmount", "VignetteAmount", "PerspectiveUpright", "PerspectiveVertical",
    "PerspectiveHorizontal", "PerspectiveRotate", "PerspectiveAspect", "PerspectiveScale", "PerspectiveX",
    "PerspectiveY", "CurveRefineSaturation", "ColorGradeShadowHue", "ColorGradeShadowSat", "ColorGradeHighlightHue",
    "ColorGradeHighlightSat", "HDREditMode",
])
# Attributes that describe the file or the shot, not an adjustment.
META = frozenset([
    "Version", "ProcessVersion", "CompatibleVersion", "PresetType", "Cluster", "UUID", "RequiresRGBTables",
    "CameraModelRestriction", "Copyright", "ContactInfo", "HasSettings", "ShowInPresets", "ShowInQuickActions",
    "CameraProfileDigest", "LensProfileName", "LensProfileFilename", "LensProfileDigest", "LensProfileIsEmbedded",
    "LensProfileSetup", "ToneCurveName", "ToneCurveName2012", "AsShotTemperature", "AsShotTint",
    "OverrideLookVignette", "AutoGrayscaleMix", "WhiteBalance", "CameraProfile",
])
NEUTRAL_PROFILES = ("Embedded", "Default Color", "Default Monochrome")
CURVE_TAGS = ("ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue")
TEXT_TAGS = ("Name", "ShortName", "SortName", "Group", "Description")


class PresetParseError(ValueError):
    pass


def number(text, what):
    t = (text or "").strip()
    if not _NUM.match(t):
        raise PresetParseError(f"{what}: not a number: {text!r}")
    return float(t)


def boolean(text, what):
    t = (text or "").strip().lower()
    if t not in ("true", "false"):
        raise PresetParseError(f"{what}: not a boolean: {text!r}")
    return t == "true"


def _attrs(el):
    return {k[len(CRS):]: v for k, v in el.attrib.items() if k.startswith(CRS)}


def _lang_alt(el):
    li = el.find(f"{RDF}Alt/{RDF}li")
    return (li.text or "").strip() if li is not None else ""


def _seq_items(el):
    seq = el.find(f"{RDF}Seq")
    return [] if seq is None else seq.findall(f"{RDF}li")


class _Skipped(list):
    def add(self, item):
        if item not in self:
            self.append(item)


def _parse_curve(el, tag, clamped):
    pts = []
    for li in _seq_items(el):
        parts = (li.text or "").split(",")
        if len(parts) != 2:
            raise PresetParseError(f"{tag}: bad curve point {li.text!r}")
        x, y = number(parts[0], tag), number(parts[1], tag)
        lo, hi = CURVE_RANGE
        cx, cy = min(hi, max(lo, x)), min(hi, max(lo, y))
        if (cx, cy) != (x, y):
            clamped.add(tag)
        pts.append([cx, cy])
    if len(pts) < 2:
        raise PresetParseError(f"{tag}: needs at least 2 points")
    pts.sort(key=lambda p: p[0])
    return pts


def _shape(li, skipped):
    el = li.find(f"{RDF}Description")
    a = _attrs(el if el is not None and not _attrs(li) else li)
    what = a.get("What", "")
    if "MaskActive" in a and not boolean(a["MaskActive"], "MaskActive"):
        return None
    if what not in cov.SUPPORTED_MASKS:
        skipped.add(what or "Mask/?")
        return None
    blend = number(a.get("MaskBlendMode", "0"), "MaskBlendMode")
    if blend != 0:
        skipped.add(f"{what}（MaskBlendMode {blend:g}）")
        return None
    shape = {"type": what, "inverted": boolean(a.get("MaskInverted", "false"), "MaskInverted"),
             "opacity": number(a.get("MaskValue", "1"), "MaskValue")}
    if what == "Mask/Gradient":
        for k in ("ZeroX", "ZeroY", "FullX", "FullY"):
            shape[k] = number(a.get(k), f"{what}.{k}")
    else:
        for k in ("Top", "Left", "Bottom", "Right"):
            shape[k] = number(a.get(k), f"{what}.{k}")
        for k, d in (("Angle", "0"), ("Midpoint", "50"), ("Roundness", "0"), ("Feather", "50")):
            shape[k] = number(a.get(k, d), f"{what}.{k}")
        shape["Flipped"] = boolean(a.get("Flipped", "false"), f"{what}.Flipped")
    return shape


def _parse_masks(el, skipped):
    masks = []
    for li in _seq_items(el):
        d = li.find(f"{RDF}Description")
        a = _attrs(d if d is not None else li)
        if a.get("What") != "Correction":
            skipped.add(a.get("What") or "MaskGroupBasedCorrections")
            continue
        if "CorrectionActive" in a and not boolean(a["CorrectionActive"], "CorrectionActive"):
            continue
        values = {}
        for k, v in a.items():
            if k.startswith("Local"):
                values[k], was = clamp_value(k, number(v, k))
                if was:
                    _note_clamp(skipped, k)
                if k not in cov.LOCAL_RENDERED and k not in cov.LOCAL_DETAIL and values[k] != 0:
                    skipped.add(k)
        node = d if d is not None else li
        rng = node.find(f"{CRS}CorrectionRangeMask")
        if rng is not None and number(_attrs(rng).get("Type", "0"), "CorrectionRangeMask.Type") != 0:
            skipped.add("CorrectionRangeMask")
        shapes = []
        cm = node.find(f"{CRS}CorrectionMasks")
        if cm is not None:
            for sli in _seq_items(cm):
                s = _shape(sli, skipped)
                if s is not None:
                    shapes.append(s)
        masks.append({"name": a.get("CorrectionName", ""),
                      "amount": number(a.get("CorrectionAmount", "1"), "CorrectionAmount"),
                      "values": values, "shapes": shapes})
    return masks


def _note_clamp(skipped, key):
    skipped.add(f"{key}（超出範圍，已夾值）")


class _DtdFound(Exception):
    pass


def _reject_dtd(data):
    """Refuse any DOCTYPE / ENTITY declaration (in whatever encoding) before ElementTree sees the bytes."""
    def stop(*_):
        raise _DtdFound()
    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = stop
    p.EntityDeclHandler = stop
    p.UnparsedEntityDeclHandler = stop
    p.ExternalEntityRefHandler = stop
    try:
        p.Parse(data, True)
    except _DtdFound:
        raise PresetParseError("DTD/entities are not allowed in a preset") from None
    except expat.ExpatError as e:
        raise PresetParseError(f"not valid XML: {e}") from None


def read_preset(path):
    """Parse a preset -> (Params, display name). Raises UnsupportedPresetError or ValueError."""
    with open(path, "rb") as f:
        data = f.read()
    _reject_dtd(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise PresetParseError(f"not valid XML: {e}") from None
    rdf = root if root.tag == f"{RDF}RDF" else root.find(f"{RDF}RDF")
    descs = [] if rdf is None else rdf.findall(f"{RDF}Description")
    if not descs:
        raise PresetParseError("no rdf:Description")
    attrs, children = {}, []
    for d in descs:
        attrs.update(_attrs(d))
        children.extend(list(d))

    pv_text = attrs.get("ProcessVersion")
    if pv_text is None:
        raise PresetParseError("missing ProcessVersion")
    if int(number(pv_text, "ProcessVersion")) not in SUPPORTED_PV_MAJORS:
        raise UnsupportedPresetError(pv_text.strip(), path)

    skipped = _Skipped()
    values = {}
    for k, v in attrs.items():
        if k in META or k.startswith("Supports"):
            continue
        if k == "ConvertToGrayscale":
            values[k] = boolean(v, k)
        elif k == "HDREditMode":
            number(v, k)
            skipped.add("HDREditMode")
        elif k in KNOWN_NUMERIC or _NUM.match(v.strip()):
            values[k] = number(v, k)
            if k not in UNCLAMPED_DATA_KEYS:
                values[k], was = clamp_value(k, values[k])
                if was:
                    _note_clamp(skipped, k)
        else:
            skipped.add(k)  # unknown non-numeric setting

    if attrs.get("WhiteBalance", "").strip() == "Auto":
        skipped.add("WhiteBalance（Auto）")
    for k in ("Temperature", "Tint"):  # absolute white balance only means something for RAW input
        if k in values:
            skipped.add(k)
    prof = attrs.get("CameraProfile", "").strip()
    if prof and prof not in NEUTRAL_PROFILES:
        skipped.add(f"CameraProfile（{prof}）")
    for k in ("ColorGradeShadowSat", "ColorGradeHighlightSat"):
        if values.get(k, 0) != 0:  # Lightroom stores these tones in SplitToning*; never applied twice
            skipped.add(k)
    for k, v in values.items():
        if k in cov.RENDERED or k in cov.DETAIL or k.startswith("ColorGradeShadow") or k.startswith("ColorGradeHighlight"):
            continue
        if v != cov.INACTIVE.get(k, default(k)):
            skipped.add(k)

    curves, masks, name = {}, [], ""
    for ch in children:
        tag = ch.tag[len(CRS):] if ch.tag.startswith(CRS) else ch.tag
        if tag in TEXT_TAGS:
            if tag == "Name":
                name = _lang_alt(ch)
        elif tag in CURVE_TAGS:
            cl = set()
            curves[tag] = _parse_curve(ch, tag, cl)
            if cl:
                _note_clamp(skipped, tag)
        elif tag == "Look":
            d = ch.find(f"{RDF}Description")
            look = _attrs(d).get("Name", "") if d is not None else ""
            skipped.add(f"Look（{look}）" if look else "Look")
        elif tag == "MaskGroupBasedCorrections":
            masks = _parse_masks(ch, skipped)
        elif tag == "PointColors":
            nums = [number(x, tag) for li in _seq_items(ch) for x in (li.text or "").split(",")]
            if any(n != -1 for n in nums):
                skipped.add("PointColors")
        elif tag == "ColorVariance":
            nums = [number(li.text, tag) for li in _seq_items(ch)]
            if any(n != 0 for n in nums):
                skipped.add("ColorVariance")
        else:
            skipped.add(tag)
    if not name:
        name = os.path.splitext(os.path.basename(path))[0]
    return Params(values=values, curves=curves, masks=masks, skipped=list(skipped)), name


def load_preset(path):
    """Parse a Lightroom .xmp preset into Params (read-only)."""
    return read_preset(path)[0]
