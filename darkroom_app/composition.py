"""Wiring: one DarkroomFacade over the services (CONTRACT-layering L1).

The Engine is built only when an operation first touches the GPU (open_photo); listing presets and sliders
never imports torch or cv2. The photo library's data folder is resolved from the configuration only when a
photo library operation first needs it (CONTRACT-photo-library PLP8), unless `data_dir` is given.
"""
import threading

from . import config
from .facade import DarkroomFacade
from .presets import Library
from .services import EngineRef
from .services.capabilities import CapabilityService
from .services.export import ExportService
from .services.export_presets import ExportPresetService
from .services.photo_library import PhotoLibraryService
from .services.photos import PhotoService
from .services.preset_library import PresetLibraryService
from .services.presets import PresetService
from .services.preview import PreviewService
from .services.semantic_index import SemanticIndexService


def build_facade(preset_dir=None, *, library=None, engine=None, library_dir=None, data_dir=None, semantic=None,
                 detect=None):
    """preset_dir defaults to config.preset_dir() (ConfigError if unset); library / engine may be given.

    The preset library root (CONTRACT-preset-library K1, KP2): library_dir when given; else, when preset_dir comes
    from the configuration too, config's preset_library_dir; else dirname(preset_dir).
    data_dir (CONTRACT-photo-library PL1): when None, config.data_dir() on first use.
    semantic (CONTRACT-semantic-index): keyword settings for SemanticIndexService (tests inject fakes); by default
    the key reference, budget and calibration photos are read from the configuration when first needed.
    detect (CONTRACT-s2-export-detect E22): {capability item: () -> (available, reason)} replacing the default
    detectors (tests always inject; a feature switched off is switched off where it is used)."""
    if library is None:
        if preset_dir is None:
            preset_dir = config.preset_dir()
            if library_dir is None:
                library_dir = config.preset_library_dir()
        library = Library(preset_dir, library_dir)
    ref = EngineRef(engine)
    # the writing services get the preset folder in use, so writes into it are refused (CONTRACT-export XP12)
    presets_lib = PresetLibraryService(library, library.preset_dir)
    photo_lib = PhotoLibraryService(library, library.preset_dir, data_dir, presets_lib)
    semantic_svc = SemanticIndexService(library, library.preset_dir, ref, **(semantic or {}))
    caps = CapabilityService(photo_lib, presets_lib, semantic_svc, detect)
    presets_lib.writes_gate = semantic_svc.writes_gate = lambda: caps.feature("preset_library_writes")   # E20
    export_presets = ExportPresetService(photo_lib.usable_data_dir, library.preset_dir)
    return DarkroomFacade(PresetService(library), PhotoService(ref), PreviewService(library, ref, photo_lib),
                          ExportService(library, ref, library.preset_dir, photo_lib, export_presets, caps.feature),
                          presets_lib, photo_lib, semantic_svc, export_presets, caps)


def warm_capabilities(facade):
    """CONTRACT-s2-export-detect E22 / IP6: the App measures the capability items that need no subprocess on a
    background thread at start-up (op whoami waits for the first capabilities request)."""
    caps = getattr(facade, "_capabilities", None)
    if caps is not None:
        threading.Thread(target=caps.warm_up, name="darkroom-capabilities", daemon=True).start()
