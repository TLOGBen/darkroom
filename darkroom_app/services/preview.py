"""Rendering previews (CONTRACT-layering L3, L5, L6; B5 as patched by R3; CONTRACT-s3-crop C17).

Layer: services. Depends on domain (`Adjustment`, the geometry / flag checks, errors, messages), the Engine handed
in through `EngineRef`, and the photo library service (the saved edit's snapshot and geometry). Never imports the
facade, adapters or config.

Order of the checks is part of the contract (the three-interface parity tests compare the sentence that comes out):
image_id (not_found) -> preset (not_found; the photo library's snapshot first, PL5) -> strength, overrides
(invalid, `Adjustment.from_request`) -> max_pixels -> geometry -> frame. Rendering runs on the Engine's
`darkroom-gpu` executor (L6).

Data flow: image_id -> the photo already resident on the GPU (opened by PhotoService) -> base Params from the photo
library (the saved edit's preset snapshot when it is the same preset, else the preset as it is now) -> Adjustment
(strength + overrides) -> final Params -> Engine.preview renders and JPEG-encodes on the GPU thread -> PreviewResult.
Nothing is written to disk.

Contract codes: L3 = check order and sentences; L5 = max_pixels None gives exactly the App's preview size, otherwise
65536..1500000; L6 = GPU work on the single executor; B5 / R3 = final value = clamp(clamp(preset at strength) +
override); C17 = geometry left out means the saved crop, None means none, frame=True shows the whole straightened
frame; PL5 = the edit's snapshot wins over the current preset file.
"""
from dataclasses import dataclass

from darkroom import Geometry

from ..domain import messages as M
from ..domain.adjustment import Adjustment, validate_flag, validate_geometry
from ..domain.errors import DarkroomError
from ..domain.sentinels import KEEP
from ..utils.imaging import preview_size
from . import on_gpu
from .photos import known_engine, photo_fingerprint


@dataclass(frozen=True)
class PreviewResult:
    """A rendered preview: JPEG bytes, render time in ms (sent as X-Render-Ms), and the JPEG's pixel size."""
    jpeg: bytes
    render_ms: float
    width: int
    height: int


def _render(eng, image_id, final, max_pixels, geometry=None, frame=False):
    """Render on the GPU thread (called through on_gpu) and report the output size alongside the bytes."""
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
    """The preview operation."""

    def __init__(self, library, engine_ref, photo_library):
        """library: the preset view; engine_ref: the shared EngineRef; photo_library: PhotoLibraryService."""
        self.library = library
        self.engine_ref = engine_ref
        self.photo_library = photo_library      # resolve_params: snapshot first (CONTRACT-photo-library PL5)

    def _fingerprint(self, eng, image_id):
        """The opened photo's content fingerprint (cached on the Engine's image record after the first hash)."""
        try:
            info = eng.get(image_id)
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
        if "fingerprint" not in info:               # opened without the service: hash once, keep it
            info["fingerprint"] = photo_fingerprint(info["path"])
        return info["fingerprint"]

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *,
                geometry=KEEP, frame=False):
        """PreviewResult for one photo at the given preset / strength / overrides / geometry.

        Raises DarkroomError not_found (unknown image or preset) or invalid (bad strength, overrides, max_pixels,
        geometry or frame), in the order given in the module docstring. No side effects besides GPU work."""
        eng = known_engine(self.engine_ref, image_id)
        params = None
        if preset_id is not None:
            params = self.photo_library.resolve_params(self._fingerprint(eng, image_id), preset_id)
        adj = Adjustment.from_request(strength, overrides)          # VO -> BO: invalid with the L3 sentences
        if max_pixels is not None and (isinstance(max_pixels, bool) or not isinstance(max_pixels, int)
                                       or not M.MAX_PIXELS_MIN <= max_pixels <= M.MAX_PIXELS_MAX):
            raise DarkroomError("invalid", M.MAX_PIXELS_INVALID)
        if geometry is KEEP:              # CONTRACT-s3-crop C17 (D4): left out = the saved geometry
            geometry = Geometry.from_dict(self.photo_library.saved_geometry(self._fingerprint(eng, image_id)))
        else:
            geometry = validate_geometry(geometry)
        validate_flag(frame, M.FRAME_INVALID)
        final = adj.final(params)
        try:
            return on_gpu(eng, _render, eng, image_id, final, max_pixels, geometry, frame)
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
