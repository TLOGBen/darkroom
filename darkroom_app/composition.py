"""Wiring: one DarkroomFacade over the services (CONTRACT-layering L1).

The Engine is built only when an operation first touches the GPU (open_photo); listing presets and sliders
never imports torch or cv2.
"""
from . import config
from .facade import DarkroomFacade
from .presets import Library
from .services import EngineRef
from .services.export import ExportService
from .services.photos import PhotoService
from .services.preset_library import PresetLibraryService
from .services.presets import PresetService
from .services.preview import PreviewService


def build_facade(preset_dir=None, *, library=None, engine=None, library_dir=None):
    """preset_dir defaults to config.preset_dir() (ConfigError if unset); library / engine may be given.

    The preset library root (CONTRACT-preset-library K1, KP2): library_dir when given; else, when preset_dir comes
    from the configuration too, config's preset_library_dir; else dirname(preset_dir)."""
    if library is None:
        if preset_dir is None:
            preset_dir = config.preset_dir()
            if library_dir is None:
                library_dir = config.preset_library_dir()
        library = Library(preset_dir, library_dir)
    ref = EngineRef(engine)
    # the export service gets the preset folder in use, so writes into it are refused (CONTRACT-export XP12)
    return DarkroomFacade(PresetService(library), PhotoService(ref), PreviewService(library, ref),
                          ExportService(library, ref, library.preset_dir),
                          PresetLibraryService(library, library.preset_dir))
