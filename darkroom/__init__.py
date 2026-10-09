"""darkroom core library: Lightroom xmp preset -> versioned parameters -> torch GPU rendering.

Public API (everything else is private):
    load_preset(path) -> Params          parse a .xmp preset (read-only)
    Params                               versioned parameter object (to_json/from_json/at_strength)
    render(image, params, strength=1.0)  apply parameters to an sRGB image in 0..1; a torch tensor already on
                                         the GPU stays there (the result is a tensor on the same device)
    read_image(path)                     JPEG/PNG/TIFF/HEIC (8/10/16-bit) -> HxWx3 float32 array in 0..1 (read-only)
    write_image(path, img)               16-bit PNG/TIFF or 8-bit JPEG
    SCHEMA_VERSION                       "darkroom-params/1"
    UnsupportedPresetError               raised for process versions other than 6.x/10.x/11.x/15.x
"""
from ._errors import UnsupportedPresetError
from ._io import read_image, write_image
from ._params import SCHEMA_VERSION, Params
from ._xmp import load_preset


def render(image, params, strength=1.0, device=None):
    """Apply `params` at `strength` (0..2) to an sRGB image in 0..1. See darkroom._render.render."""
    from ._render import render as _render_impl  # torch is imported lazily so parsing stays light
    return _render_impl(image, params, strength=strength, device=device)


__all__ = ["load_preset", "Params", "render", "read_image", "write_image", "SCHEMA_VERSION",
           "UnsupportedPresetError"]
