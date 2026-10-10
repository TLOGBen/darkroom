"""darkroom core library: Lightroom xmp preset -> versioned parameters -> torch GPU rendering.

Where this sits (docs/architecture/plan-v2.md section 1): `darkroom/` is the innermost package of the whole
project. It knows nothing about `darkroom_app` (the App, CLI, MCP server, photo library, settings) and must never
import it; the App only ever uses the public names listed below (test_api B1 pins that `darkroom_app` imports
`from darkroom import <name in __all__>` and nothing private).

How data flows through it:

    .xmp file --(_xmp.load_preset)--> Params --(Params.at_strength)--> Params at 0..200%
    photo file --(_io.read_image)--> HxWx3 float32 sRGB in 0..1
    (image, Params, Geometry) --(_render.render)--> HxWx3 float32 sRGB in 0..1 (or a GPU tensor)
    result --(_io.write_image / the App's encoder)--> a new file (the input photo is never written)

Module map (all private, prefixed with "_"):
    _xmp       parse the Lightroom crs: attributes of a preset into Params (read-only)
    _params    the Params data class, defaults / range tables, strength interpolation
    _coverage  which crs keys the renderer applies; everything else is reported in Params.skipped
    _render    the torch pipeline that mimics Lightroom's develop module on an sRGB image
    _color     sRGB <-> linear transfer functions and Rec.709 luma
    _geometry  rotate / flip / straighten / crop (torch-free; pure arithmetic + PIL on the CPU)
    _io        read JPEG/PNG/TIFF/HEIC to float, write PNG/TIFF/JPEG (CLI only)
    _icc       convert embedded ICC profiles (Display P3, Adobe RGB, ...) to sRGB on read
    _heif      HEIC/HEIF decoding through pillow-heif
    _cli       `python -m darkroom apply|scan` (a thin standalone command, separate from darkroom_app.cli)

Torch is imported lazily (only by _render / _color) so that parsing presets and listing a folder stay fast and
work on a machine without CUDA.

Public API (everything else is private):
    load_preset(path) -> Params          parse a .xmp preset (read-only)
    Params                               versioned parameter object (to_json/from_json/at_strength)
    render(image, params, strength=1.0, *, geometry=None)
                                         apply parameters to an sRGB image in 0..1; a torch tensor already on
                                         the GPU stays there (the result is a tensor on the same device);
                                         geometry (a Geometry) decides the output picture first
    read_image(path)                     JPEG/PNG/TIFF/HEIC (8/10/16-bit) -> HxWx3 float32 array in 0..1 (read-only)
    write_image(path, img)               16-bit PNG/TIFF or 8-bit JPEG
    SCHEMA_VERSION                       "darkroom-params/1"
    UnsupportedPresetError               raised for process versions other than 6.x/10.x/11.x/15.x
    Geometry                             rotate / flip / straighten / crop of one photo (from_dict, to_dict,
                                         resolve, output_size, apply on the CPU); torch-free
"""
from ._errors import UnsupportedPresetError
from ._geometry import Geometry
from ._io import read_image, write_image
from ._params import SCHEMA_VERSION, Params
from ._xmp import load_preset


def render(image, params, strength=1.0, device=None, *, geometry=None):
    """Apply `params` at `strength` (0..2) to an sRGB image in 0..1. See darkroom._render.render.

    This thin wrapper exists only so that `import darkroom` does not import torch: the real implementation is
    loaded on the first render call. Arguments and return value are exactly those of `_render.render`
    (image: HxWx3 numpy array or torch tensor; params: Params; strength: 0..2 where 1.0 = 100%;
    device: torch device or None for "cuda if available"; geometry: Geometry or None). Raises ValueError for a
    strength outside 0..2. No side effects: nothing is written anywhere.
    """
    from ._render import render as _render_impl  # torch is imported lazily so parsing stays light
    return _render_impl(image, params, strength=strength, device=device, geometry=geometry)


__all__ = ["load_preset", "Params", "render", "read_image", "write_image", "SCHEMA_VERSION",
           "UnsupportedPresetError", "Geometry"]
