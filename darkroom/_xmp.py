"""Lightroom .xmp preset -> Params. Files are only ever opened read-only ("rb").

Layer: core library. Depends on `_params` (the Params object, range table), `_coverage` (what the renderer
implements) and `_errors`; standard-library XML only. Used by `darkroom.load_preset`, the core CLI `scan`, and by
the App's preset catalogue through the public `load_preset`.

What a Lightroom preset file looks like: an XMP packet (RDF/XML) whose `rdf:Description` element carries every
develop setting as an attribute in the Camera Raw Settings namespace, e.g. `crs:Exposure2012="+0.35"`. Settings
that are lists live in child elements instead: tone curves (`crs:ToneCurvePV2012` as an rdf:Seq of "x, y"
points), the preset name (`crs:Name` as an rdf:Alt language list), local adjustments
(`crs:MaskGroupBasedCorrections`, a list of corrections each with Local* values and mask shapes) and the
creative profile (`crs:Look`).

Parsing policy (core contract):
- A4 = only PV2012-family process versions (6, 10, 11, 15) are rendered; others raise UnsupportedPresetError.
- A5 = numbers may carry a sign and decimals ("+15", "-0.24"); a known numeric key that does not parse fails the
  whole preset instead of silently becoming 0.
- A13 = every setting the renderer does not apply and that would change the picture ends up in Params.skipped,
  in a human-readable form, so the App can tell the user.
- A20 = the XML parser never resolves external entities / DTDs (an .xmp from the internet is untrusted input);
  any DOCTYPE or ENTITY declaration fails the parse before ElementTree runs.
Out-of-range values are clamped to Lightroom's slider limits and noted in skipped as "clamped".
"""
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
KNOWN_NUMERIC = frozenset(cov.RENDERED - {"ConvertToGrayscale"}) | frozenset(cov.DETAIL_PARENT) | cov.ABSOLUTE_WB | frozenset([
    "LuminanceSmoothing", "CropConstrainToWarp", "ColorNoiseReduction", "DefringePurpleAmount", "DefringeGreenAmount", "AutoLateralCA",
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
# A Look whose name says black & white is approximated by the grayscale conversion (CONTRACT-s1-experience S5,
# core patch K3); the Look's own tone and curves are still not applied, so it stays listed, as "approximated".
MONOCHROME_LOOK = re.compile(r"monochrome|black\s*(?:&|and)\s*white|\bb&w\b", re.I)   # verbatim (S5)
LOOK_APPROXIMATED = "Look（{name}，已以黑白近似）"                                     # verbatim (S5)
# CONTRACT-s3-crop C10 (D5): a preset's crop is never applied (the geometry belongs to each photo); a real crop in
# the preset is reported once as a minor skipped item.
CROP_KEYS = frozenset(["HasCrop", "CropTop", "CropLeft", "CropBottom", "CropRight", "CropAngle", "CropConstrainToWarp",
                       "CropConstrainAspectRatio", "CropWidth", "CropHeight", "CropUnit"])                # verbatim (C10)
PRESET_CROP_SKIPPED = "裁切（preset 帶的裁切與拉直不會套用）"                                             # verbatim (C10)
CURVE_TAGS = ("ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue")
TEXT_TAGS = ("Name", "ShortName", "SortName", "Group", "Description")


class PresetParseError(ValueError):
    """The file is not a usable preset (bad XML, missing ProcessVersion, unparsable number, ...)."""


def number(text, what):
    """Parse an xmp numeric attribute ("+0.80", "-15", ".5") to float; `what` names the key in the error.

    Deliberately stricter than float(): "nan", "1e3" or "" are rejected (PresetParseError), because Lightroom
    never writes them and accepting them would hide a corrupted file (contract A5)."""
    t = (text or "").strip()
    if not _NUM.match(t):
        raise PresetParseError(f"{what}: not a number: {text!r}")
    return float(t)


def boolean(text, what):
    """Parse "True"/"False" (any case) to bool; anything else raises PresetParseError naming `what`."""
    t = (text or "").strip().lower()
    if t not in ("true", "false"):
        raise PresetParseError(f"{what}: not a boolean: {text!r}")
    return t == "true"


def _attrs(el):
    """The element's crs:* attributes as {key without namespace: raw string value}."""
    return {k[len(CRS):]: v for k, v in el.attrib.items() if k.startswith(CRS)}


def _lang_alt(el):
    """Text of the first rdf:li of an rdf:Alt (Lightroom writes the preset name as x-default first)."""
    li = el.find(f"{RDF}Alt/{RDF}li")
    return (li.text or "").strip() if li is not None else ""


def _seq_items(el):
    """The rdf:li children of the element's rdf:Seq (curve points, mask list entries); [] when there is none."""
    seq = el.find(f"{RDF}Seq")
    return [] if seq is None else seq.findall(f"{RDF}li")


class _Skipped(list):
    """An ordered list without duplicates: the order settings were met in is the order the user reads them."""

    def add(self, item):
        if item not in self:
            self.append(item)


def _parse_curve(el, tag, clamped):
    """A tone curve element -> [[x, y], ...] sorted by x, each coordinate clamped to 0..255.

    Lightroom stores curve points as strings "x, y" in 0..255 (input level, output level). Adds `tag` to the
    `clamped` set when a point had to be clamped. Raises PresetParseError for a malformed point or fewer than two
    points (a curve needs at least its two end points to be interpolated)."""
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
    """One mask shape entry -> a shape dict for _render, or None when it is inactive or unsupported.

    Supported: "Mask/Gradient" (linear: the ramp runs from the Zero point, 0% effect, to the Full point, 100%)
    and "Mask/CircularGradient" (radial: an ellipse given by its Top/Left/Bottom/Right box, Angle, Feather,
    Roundness and Midpoint; Flipped means the effect is outside). All coordinates are 0..1 fractions of the image,
    exactly as Lightroom stores them (contract A14). Other mask kinds, or a non-default MaskBlendMode (subtract /
    intersect), are added to `skipped` and dropped. The attributes may sit on the rdf:li itself or on a nested
    rdf:Description, depending on the Lightroom version that wrote the file."""
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
    """crs:MaskGroupBasedCorrections -> list of local adjustments for Params.masks.

    Each active "Correction" becomes {"name", "amount", "values": {Local*: clamped float}, "shapes": [...]}.
    Anything that cannot be reproduced is recorded in `skipped`: non-correction entries, Local* keys outside
    LOCAL_RENDERED with an effect, a luminance / colour range mask (Type != 0), unsupported shapes. A correction
    whose shapes were all dropped keeps an empty shape list (the renderer then applies nothing for it)."""
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
        for k in values:
            if cov.unrendered_active(k, values, cov.LOCAL_RENDERED):
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
    """Record that `key` held a value outside Lightroom's range and was clamped."""
    skipped.add(f"{key}（超出範圍，已夾值）")


class _DtdFound(Exception):
    """Internal signal raised from the expat handlers to abort the pre-scan at the first declaration."""


def _reject_dtd(data):
    """Refuse any DOCTYPE / ENTITY declaration (in whatever encoding) before ElementTree sees the bytes.

    Why a separate expat pass: ElementTree expands internal entities (the "billion laughs" memory bomb) and
    offers no switch to forbid a DTD. Running raw expat with handlers that abort on the first declaration closes
    that door for every encoding the XML declaration may announce (contract A20)."""
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
    """Parse a preset -> (Params, display name). Raises UnsupportedPresetError or ValueError.

    Steps: read bytes ("rb" only) -> reject DTDs -> parse XML -> merge the crs attributes of every
    rdf:Description (some writers split them) -> check ProcessVersion -> convert attributes to numbers
    (clamped), sorting out metadata, crop keys and unknown text settings -> list everything not rendered in
    skipped -> parse child elements (name, curves, Look, local masks, point colours). The display name is the
    crs:Name, else the file name without extension. Side effects: none.
    """
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
        if k in CROP_KEYS and not _NUM.match(v.strip()):
            continue                     # C10: HasCrop / CropConstrainAspectRatio are read below, never kept
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
    # Everything present with an effect the renderer does not apply (incl. ColorGradeShadow/HighlightSat: Lightroom
    # stores those tones in SplitToning*, so they are never applied a second time).
    for k in values:
        if k in CROP_KEYS:               # C10: one item for the whole crop, below
            continue
        if cov.unrendered_active(k, values):
            skipped.add("PostCropVignetteRoundness（負值）" if k == "PostCropVignetteRoundness" else k)

    edges = tuple(values.get(k, d) for k, d in (("CropLeft", 0.0), ("CropTop", 0.0), ("CropRight", 1.0),
                                                ("CropBottom", 1.0)))
    if (attrs.get("HasCrop", "").strip().lower() == "true" or values.get("CropAngle", 0.0) != 0
            or edges != (0.0, 0.0, 1.0, 1.0)):
        skipped.add(PRESET_CROP_SKIPPED)

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
            if look and MONOCHROME_LOOK.search(look):          # K3: a black & white Look -> grayscale conversion
                values["ConvertToGrayscale"] = True
                skipped.add(LOOK_APPROXIMATED.format(name=look))
            else:
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
    """Parse a Lightroom .xmp preset into Params (read-only).

    Public entry point (`darkroom.load_preset`): same as read_preset without the display name. Raises
    UnsupportedPresetError for other process versions, ValueError (PresetParseError) for broken files, OSError
    when the file cannot be read."""
    return read_preset(path)[0]
