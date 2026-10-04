"""Preview parameter semantics (B5): final value = clamp(preset value at strength + override)."""
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
    strength: 0..2; overrides: {slider key: difference added after strength}. Values are clamped to range.
    """
    base = params.at_strength(strength) if params is not None else Params()
    values = dict(base.values)
    for k, d in overrides.items():
        values[k] = base.get(k) + d
    out = Params(values=values, curves=base.curves, masks=base.masks, skipped=list(base.skipped))
    return out.clamped()
