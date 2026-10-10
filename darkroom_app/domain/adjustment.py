"""Strength + slider overrides: the adjustment a request asks for, checked once (plan-v2 §1: VO -> BO).

Layer: domain. Imports the core `darkroom.Params` and the slider table; nothing else.

What a preview, an export item, `edit set`, `presets save` and a saved edit all carry is the same pair: a strength
in percent (0..200, as on the strength slider and the CLI) and slider overrides ({crs key: difference}). Before v2
five service methods checked that pair each on their own; now an entry point's raw values (a JSON body, argparse
values, MCP arguments) become an `Adjustment` through `Adjustment.from_request`, and a value that is not acceptable
is `DarkroomError("invalid", <the sentence>)` with the sentences below, unchanged (the three-interface parity tests
compare them byte for byte):

    strength must be a number in 0..200 | strength must be within 0..200, got {strength:g}
    overrides must be an object {key: difference} | unknown slider key {k!r} | override for {k} must be a finite number

The final parameters are computed by one function, `effective_params` (B5 as patched by R3):
final = clamp(clamp(preset value at strength) + override). The old module `darkroom_app.preview` is an alias of
this one (compat shim), so `validate_strength`, `validate_overrides`, `effective_params`, `validate_geometry` and
`validate_flag` keep their old import path.

Contract codes used here: B5 / R3 = an override is a difference added to the preset's value at the chosen strength,
and both the intermediate and the final value are clamped to the slider range; L3 = the checks run in a fixed order
(strength before overrides) with fixed sentences; PL3 = the edit file stores strength in percent; C1 = the geometry
object's shape (darkroom.Geometry.from_dict decides); C17 / C14 = `frame` (preview) and `with_geometry` (paste) must
be real booleans.
"""
import math
from dataclasses import dataclass, field

from darkroom import Params

from . import sliders
from .errors import DarkroomError

DEFAULT_STRENGTH = 100        # percent: a request that names no strength means the preset as it is


def validate_overrides(overrides):
    """None -> {}; {slider key: finite number} -> {key: float}; anything else -> ValueError (sentences above)."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object {key: difference}")
    out = {}
    for k, v in overrides.items():
        if k not in sliders.BY_KEY:
            raise ValueError(f"unknown slider key {k!r}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"override for {k} must be a finite number")
        out[k] = float(v)
    return out


def validate_strength(strength):
    """Strength in percent, 0..200 (as on the strength slider and the CLI) -> 0..2."""
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength):
        raise ValueError("strength must be a number in 0..200")
    if not 0.0 <= strength <= 200.0:
        raise ValueError(f"strength must be within 0..200, got {strength:g}")
    return strength / 100.0


def effective_params(params, strength, overrides):
    """Params at their final values for rendering at strength 1.

    params: the preset's Params, or None (no preset: only the overrides apply, on top of the defaults)
    strength: 0..2; overrides: {slider key: difference added to the clamped value at strength}. Results
    are clamped to range again (contract R3).
    """
    base = (params.at_strength(strength) if params is not None else Params()).clamped()
    values = dict(base.values)
    for k, d in overrides.items():
        values[k] = base.get(k) + d
    out = Params(values=values, curves=base.curves, masks=base.masks, skipped=list(base.skipped))
    return out.clamped()


@dataclass(frozen=True)
class Adjustment:
    """A checked strength (fraction 0..2) and overrides ({key: float}); the business object behind every request.

    `percent` keeps the strength as it was given (the edit file stores percent, PL3)."""
    strength: float = 1.0
    overrides: dict = field(default_factory=dict)
    percent: float = DEFAULT_STRENGTH

    @classmethod
    def from_request(cls, strength=DEFAULT_STRENGTH, overrides=None):
        """Raw request values -> Adjustment; invalid with the constant sentence on the first bad value.

        Order is part of the contract: strength is judged before overrides (L3)."""
        try:
            s = validate_strength(strength)
            o = validate_overrides(overrides)
        except ValueError as e:
            raise DarkroomError("invalid", str(e)) from None
        return cls(s, o, strength)

    @property
    def is_empty(self):
        """No override at all (the strength alone changes nothing without a preset)."""
        return not self.overrides

    def final(self, params):
        """The Params to render: `params` (a preset's, or None) at this strength plus the overrides (B5 / R3)."""
        return effective_params(params, self.strength, self.overrides)


ORIGINAL = Adjustment()        # strength 100 %, no overrides: with no preset, the photo as it is


def validate_geometry(geometry):
    """A geometry object or None -> darkroom.Geometry or None; the one rule is Geometry.from_dict (C1): its
    ValueError becomes invalid with the sentence unchanged. KEEP is not accepted here (the caller resolves it)."""
    from darkroom import Geometry
    try:
        return Geometry.from_dict(geometry)
    except ValueError as e:
        raise DarkroomError("invalid", str(e)) from None


def validate_flag(value, sentence):
    """frame / with_geometry: true or false, else invalid with the constant sentence (C17, C14)."""
    if not isinstance(value, bool):
        raise DarkroomError("invalid", sentence)
    return value
