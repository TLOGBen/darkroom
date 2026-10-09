"""Rendering previews (CONTRACT-layering L3, L5, L6; B5 as patched by R3)."""
from dataclasses import dataclass

from .. import messages as M
from .. import preview as semantics
from ..errors import DarkroomError
from ..facade import KEEP
from . import on_gpu
from .photos import known_engine


@dataclass(frozen=True)
class PreviewResult:
    jpeg: bytes
    render_ms: float
    width: int
    height: int


def _render(eng, image_id, final, max_pixels, geometry=None, frame=False):
    from ..engine import preview_size
    if geometry is not None and not geometry.identity:      # CONTRACT-s3-crop C17 (L5')
        width, height = eng.preview_target(image_id, geometry, frame, max_pixels)
        data, ms = eng.preview(image_id, final, max_pixels, geometry, frame)
        return PreviewResult(data, ms, width, height)
    t = eng.get(image_id)["tensor"]
    width, height = int(t.shape[-1]), int(t.shape[-2])
    if max_pixels is None:
        data, ms = eng.preview(image_id, final)            # exactly the App's preview
    else:
        width, height = preview_size(width, height, max_pixels)
        data, ms = eng.preview(image_id, final, max_pixels=max_pixels)
    return PreviewResult(data, ms, width, height)


class PreviewService:
    def __init__(self, library, engine_ref, photo_library):
        self.library = library
        self.engine_ref = engine_ref
        self.photo_library = photo_library      # resolve_params: snapshot first (CONTRACT-photo-library PL5)

    def _fingerprint(self, eng, image_id):
        try:
            info = eng.get(image_id)
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
        if "fingerprint" not in info:               # opened without the service: hash once, keep it
            from .photo_library import fingerprint
            from .photos import read_error
            try:
                info["fingerprint"] = fingerprint(info["path"])
            except OSError as e:
                raise read_error(info["path"], e) from None
        return info["fingerprint"]

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *,
                geometry=KEEP, frame=False):
        eng = known_engine(self.engine_ref, image_id)
        params = None
        if preset_id is not None:
            params = self.photo_library.resolve_params(self._fingerprint(eng, image_id), preset_id)
        try:
            strength = semantics.validate_strength(strength)
            overrides = semantics.validate_overrides(overrides)
        except ValueError as e:
            raise DarkroomError("invalid", str(e)) from None
        if max_pixels is not None and (isinstance(max_pixels, bool) or not isinstance(max_pixels, int)
                                       or not M.MAX_PIXELS_MIN <= max_pixels <= M.MAX_PIXELS_MAX):
            raise DarkroomError("invalid", M.MAX_PIXELS_INVALID)
        if geometry is KEEP:              # CONTRACT-s3-crop C17 (D4): left out = the saved geometry
            from darkroom import Geometry
            geometry = Geometry.from_dict(self.photo_library.saved_geometry(self._fingerprint(eng, image_id)))
        else:
            geometry = semantics.validate_geometry(geometry)
        semantics.validate_flag(frame, M.FRAME_INVALID)
        final = semantics.effective_params(params, strength, overrides)
        try:
            return on_gpu(eng, _render, eng, image_id, final, max_pixels, geometry, frame)
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
