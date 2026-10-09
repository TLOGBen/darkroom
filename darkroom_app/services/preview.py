"""Rendering previews (CONTRACT-layering L3, L5, L6; B5 as patched by R3)."""
from dataclasses import dataclass

from .. import messages as M
from .. import preview as semantics
from ..errors import DarkroomError
from . import on_gpu
from .photos import known_engine


@dataclass(frozen=True)
class PreviewResult:
    jpeg: bytes
    render_ms: float
    width: int
    height: int


def _render(eng, image_id, final, max_pixels):
    from ..engine import preview_size
    t = eng.get(image_id)["tensor"]
    width, height = int(t.shape[-1]), int(t.shape[-2])
    if max_pixels is None:
        data, ms = eng.preview(image_id, final)            # exactly the App's preview
    else:
        width, height = preview_size(width, height, max_pixels)
        data, ms = eng.preview(image_id, final, max_pixels=max_pixels)
    return PreviewResult(data, ms, width, height)


class PreviewService:
    def __init__(self, library, engine_ref):
        self.library = library
        self.engine_ref = engine_ref

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None):
        eng = known_engine(self.engine_ref, image_id)
        params = None
        if preset_id is not None:
            if not isinstance(preset_id, str) or preset_id not in self.library.params:
                raise DarkroomError("not_found", M.UNKNOWN_OR_UNSUPPORTED_PRESET.format(pid=preset_id))
            params = self.library.get(preset_id)
        try:
            strength = semantics.validate_strength(strength)
            overrides = semantics.validate_overrides(overrides)
        except ValueError as e:
            raise DarkroomError("invalid", str(e)) from None
        if max_pixels is not None and (isinstance(max_pixels, bool) or not isinstance(max_pixels, int)
                                       or not M.MAX_PIXELS_MIN <= max_pixels <= M.MAX_PIXELS_MAX):
            raise DarkroomError("invalid", M.MAX_PIXELS_INVALID)
        final = semantics.effective_params(params, strength, overrides)
        try:
            return on_gpu(eng, _render, eng, image_id, final, max_pixels)
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
