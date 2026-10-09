"""Preview parameter semantics (B5 as patched by R3): final = clamp(clamp(preset value at strength) + override)."""
import math

from darkroom import Params

from . import sliders


def validate_overrides(overrides):
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


def validate_geometry(geometry):
    """A geometry object or None -> darkroom.Geometry or None; the one rule is Geometry.from_dict (C1): its
    ValueError becomes invalid with the sentence unchanged. KEEP is not accepted here (the caller resolves it)."""
    from darkroom import Geometry

    from .errors import DarkroomError
    try:
        return Geometry.from_dict(geometry)
    except ValueError as e:
        raise DarkroomError("invalid", str(e)) from None


def validate_flag(value, sentence):
    """frame / with_geometry: true or false, else invalid with the constant sentence (C17, C14)."""
    from .errors import DarkroomError
    if not isinstance(value, bool):
        raise DarkroomError("invalid", sentence)
    return value
