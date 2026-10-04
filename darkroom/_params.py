"""Versioned parameter object: Lightroom crs key names, one defaults table, strength interpolation."""
import copy
import json
import math
from dataclasses import dataclass, field

SCHEMA_VERSION = "darkroom-params/1"

# The single defaults table (contract Verbatim Constants). Keys not listed default to 0.
DEFAULTS = {
    "SharpenRadius": 1.0, "SharpenDetail": 25.0, "SharpenEdgeMasking": 0.0, "LuminanceNoiseReductionDetail": 50.0,
    "LuminanceNoiseReductionContrast": 0.0, "ColorNoiseReduction": 25.0, "ColorNoiseReductionDetail": 50.0,
    "ColorNoiseReductionSmoothness": 50.0, "GrainSize": 25.0, "GrainFrequency": 50.0,
    "PostCropVignetteMidpoint": 50.0, "PostCropVignetteFeather": 50.0, "PostCropVignetteRoundness": 0.0,
    "PostCropVignetteStyle": 1.0, "PostCropVignetteHighlightContrast": 0.0, "ParametricShadowSplit": 25.0,
    "ParametricMidtoneSplit": 50.0, "ParametricHighlightSplit": 75.0, "ColorGradeBlending": 50.0,
    "SplitToningBalance": 0.0,
}

BOOL_KEYS = frozenset({"ConvertToGrayscale"})
LOCAL_HUE_KEYS = frozenset({"LocalToningHue"})


def default(key):
    return DEFAULTS.get(key, 0.0)


def is_hue_angle(key):
    """Hue angles are positions on the colour wheel, not amounts: strength never scales them."""
    if key in ("SplitToningShadowHue", "SplitToningHighlightHue"):
        return True
    return key.startswith("ColorGrade") and key.endswith("Hue")


def _check_strength(s):
    s = float(s)
    if not (0.0 <= s <= 2.0) or math.isnan(s):
        raise ValueError(f"strength must be within 0..2 (0..200%), got {s}")
    return s


@dataclass
class Params:
    """Preset parameters. JSON form: {"schema", "values", "curves", "masks", "skipped"}.

    values  : {Lightroom key without "crs:" -> float (bool for ConvertToGrayscale)}
    curves  : {"ToneCurvePV2012"/"...Red"/"...Green"/"...Blue" -> [[x, y], ...] in 0..255}
    masks   : [{"name", "amount", "values": {Local* -> float}, "shapes": [{"type": "Mask/Gradient"|..., ...}]}]
    skipped : human-readable list of settings present in the preset that are not applied
    """
    values: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)
    masks: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    # ---- serialisation
    def to_dict(self):
        return {"schema": SCHEMA_VERSION, "values": copy.deepcopy(self.values), "curves": copy.deepcopy(self.curves),
                "masks": copy.deepcopy(self.masks), "skipped": list(self.skipped)}

    def to_json(self, **kw):
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or d.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"not a {SCHEMA_VERSION} parameter object (schema={d.get('schema') if isinstance(d, dict) else None!r})")
        missing = [k for k in ("values", "curves", "masks", "skipped") if k not in d]
        if missing:
            raise ValueError(f"parameter object is missing {missing}")
        values = {}
        for k, v in d["values"].items():
            values[k] = bool(v) if k in BOOL_KEYS else float(v)
        curves = {k: [[float(x), float(y)] for x, y in pts] for k, pts in d["curves"].items()}
        return cls(values=values, curves=curves, masks=copy.deepcopy(list(d["masks"])), skipped=list(d["skipped"]))

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(json.loads(text))

    # ---- strength
    def at_strength(self, s):
        """New Params at strength s in [0, 2]: slider = default + s*(v - default); hue angles fixed;
        curve y = x + s*(y - x) clamped to 0..255; boolean keys on only when s > 0; local mask amounts s*v."""
        s = _check_strength(s)
        values = {}
        for k, v in self.values.items():
            if k in BOOL_KEYS:
                values[k] = bool(v) and s > 0
            elif is_hue_angle(k):
                values[k] = v
            else:
                d = default(k)
                values[k] = d + s * (v - d)
        curves = {k: [[x, min(255.0, max(0.0, x + s * (y - x)))] for x, y in pts] for k, pts in self.curves.items()}
        masks = []
        for m in self.masks:
            m = copy.deepcopy(m)
            m["values"] = {k: (v if k in LOCAL_HUE_KEYS else s * v) for k, v in m.get("values", {}).items()}
            masks.append(m)
        return Params(values=values, curves=curves, masks=masks, skipped=list(self.skipped))

    def get(self, key):
        """Value of `key`, falling back to the defaults table."""
        return self.values.get(key, default(key))
