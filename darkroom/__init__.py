"""darkroom core library: Lightroom xmp preset -> versioned parameters -> torch GPU rendering.

Public API (everything else is private):
    load_preset(path) -> Params          parse a .xmp preset (read-only)
    Params                               versioned parameter object (to_json/from_json/at_strength)
    render(image, params, strength=1.0)  apply parameters to an sRGB image in 0..1
    SCHEMA_VERSION                       "darkroom-params/1"
    UnsupportedPresetError               raised for process versions other than 6.x/10.x/11.x/15.x
"""
from ._errors import UnsupportedPresetError
from ._params import SCHEMA_VERSION, Params
from ._xmp import load_preset


def render(image, params, strength=1.0, device=None):
    """Apply `params` at `strength` (0..2) to an sRGB image in 0..1. See darkroom._render.render."""
    from ._render import render as _render_impl  # torch is imported lazily so parsing stays light
    return _render_impl(image, params, strength=strength, device=device)


__all__ = ["load_preset", "Params", "render", "SCHEMA_VERSION", "UnsupportedPresetError"]
