"""Wiring: one DarkroomFacade over the services (CONTRACT-layering L1).

The Engine is built only when an operation first touches the GPU (open_photo); listing presets and sliders
never imports torch or cv2.
"""
from . import config
from .facade import DarkroomFacade
from .presets import Library
from .services import EngineRef
from .services.photos import PhotoService
from .services.presets import PresetService
from .services.preview import PreviewService


def build_facade(preset_dir=None, *, library=None, engine=None):
    """preset_dir defaults to config.preset_dir() (ConfigError if unset); library / engine may be given."""
    if library is None:
        library = Library(preset_dir if preset_dir is not None else config.preset_dir())
    ref = EngineRef(engine)
    return DarkroomFacade(PresetService(library), PhotoService(ref), PreviewService(library, ref))
