"""Wiring: the one place that builds the app (CONTRACT-layering L1; plan-v2 §1, §3).

Layer: composition (with the entry points, the only code that reads the configuration). It builds the persist stores,
hands them and the settings the services need to the services (as values or zero-argument functions, read when
used), and puts one `DarkroomFacade` over them. Nothing else wires objects together; services never import each
other's construction, the facade, adapters or config.

    build_facade(...)   one facade (the CLI, tests, a single MCP call)
    Runtime(...)        the live facade of a long-running process (the App, the MCP server): when settings change it
                        builds a new facade from the new settings - keeping the Engine, so open photos stay open -
                        and later calls get the new one; calls already running finish with the old one.

The Engine is built only when an operation first touches the GPU (open_photo); listing presets, sliders and settings
never imports torch or cv2. The photo library's data folder is resolved from the configuration only when a photo
library operation first needs it (CONTRACT-photo-library PLP8), unless `data_dir` is given.

v2 removed the cycle where the capability service was built last and then handed back to the preset library and the
semantic index (`writes_gate` filled in afterwards): "may the preset library be written" is now one `Probe`, built
first and given to all three.

Dependencies: config, every persist store, every service, the facade, domain.settings, the write module (only to
install the configured-preset-folder hook). Must not be imported by services, domain, utils or persist (it sits
above them). Data flow: configuration values -> store constructors (folders) -> service constructors (stores +
settings functions + the shared EngineRef) -> DarkroomFacade(services...) -> returned to an entry adapter.
Side effects of building: none on disk (stores create their folders lazily on first write); the GPU is not touched.

Contract codes used here:
    L1    the module layout of the layering refactor (errors, messages, services, one facade).
    K1 / KP2  where the preset library root is: explicit library_dir, else the settings' preset_library_dir only when
          the preset folder also came from the settings, else the preset folder's parent.
    PL1 / PLP8  where the photo library's data folder is, and that it is resolved lazily on first use.
    PLP19 / E23  an unresolvable data folder makes photo-library features "unavailable" (never an HTTP 500).
    XP12  the write module refuses writes inside the configured preset folder too (extra protection).
    E20   "may the preset library be written" is measured once and shared.
    E22 / IP6  the capability report; the App pre-measures the cheap items in the background at start-up.
"""
import functools
import os
import sys
import threading

from . import __version__, config
from .adapters.persist.data_folder import DataFolder
from .adapters.persist.edit_store import EditStore
from .adapters.persist.export_presets_store import ExportPresetStore
from .adapters.persist.preset_index import Library, PresetLibraryStore
from .adapters.persist.semantic_store import SemanticStore
from .adapters.persist.settings_store import SettingsStore
from .adapters.persist.thumb_store import ThumbStore
from .domain.errors import DarkroomError
from .domain.settings import KEYS, LIBRARY_KEYS, flatten
from .facade import DarkroomFacade
from .services import EngineRef
from .services.capabilities import CapabilityService, Probe
from .services.export import ExportService
from .services.export_presets import ExportPresetService
from .services.photo_library import PhotoLibraryService
from .services.photos import PhotoService
from .services.preset_library import PresetLibraryService, writes_status
from .services.presets import PresetService
from .services.preview import PreviewService
from .services.semantic_index import SemanticIndexService
from .services.settings import SettingsService
from .utils import safe_write

UNCONFIGURED_ERRORS = (config.ConfigError, FileNotFoundError)   # no preset folder configured / found


# Everything below runs once per (re)build; nothing here holds business rules, it only decides which object gets
# which dependency.


def _engine_factory():
    """The GPU adapter's Engine (torch / cv2 are imported here, on first GPU use only)."""
    from .adapters.gpu import engine as engine_mod
    return engine_mod.Engine()


def _configured_preset_dir():
    """The configured preset folder, or None (for the write module's extra protection, CONTRACT-export XP12)."""
    try:
        return config.preset_dir()
    except config.ConfigError:
        return None


def _configured_data_dir():
    """The configured photo library folder; a configuration that names none is unavailable with ConfigError's
    sentence (S2 E23 / PLP19: never an HTTP 500 or a CLI configuration exit)."""
    try:
        return config.data_dir()
    except config.ConfigError as e:
        raise DarkroomError("unavailable", str(e)) from None


def _semantic_settings():
    """The semantic index's settings as functions of the configuration (read each time they are needed)."""
    return {"key_ref": lambda: config.anthropic_api_key_ref(),
            "env_key": lambda: os.environ.get(config.ENV_API_KEY),
            "sources_dir": lambda: config.calibration_sources_dir(),
            "budget_usd": lambda: config.semantic_index_budget_usd()}


class _Unconfigured:
    """Stands in for every service that needs the preset folder when none is configured yet: any call raises the
    configuration error itself, so the entry points answer exactly as before v2 (CLI "darkroom：…" exit 2, MCP -32603
    "Internal error: …"), while the settings operations - which need no preset folder - work, so a first-time setup
    can write preset_dir."""

    def __init__(self, error):
        """error: the ConfigError / FileNotFoundError to raise from every method call."""
        self._error = error

    def __getattr__(self, name):
        """Any public attribute is a function that raises the stored error (dunder lookups stay normal)."""
        if name.startswith("__"):
            raise AttributeError(name)

        def refuse(*args, **kwargs):
            raise self._error
        return refuse


def build_facade(preset_dir=None, *, library=None, engine=None, library_dir=None, data_dir=None, semantic=None,
                 detect=None, engine_ref=None, on_applied=None, settings_path=None, allow_unconfigured=False):
    """preset_dir defaults to config.preset_dir() (ConfigError if unset); library / engine may be given.

    The preset library root (CONTRACT-preset-library K1, KP2): library_dir when given; else, when preset_dir comes
    from the configuration too, config's preset_library_dir; else dirname(preset_dir).
    data_dir (CONTRACT-photo-library PL1): when None, config.data_dir() on first use.
    semantic (CONTRACT-semantic-index): keyword settings for SemanticIndexService (tests inject fakes); by default
    the key reference, budget and calibration photos are read from the configuration when first needed.
    detect (CONTRACT-s2-export-detect E22): {capability item: () -> (available, reason)} replacing the default
    detectors (tests always inject; a feature switched off is switched off where it is used).
    engine_ref: an EngineRef to share (Runtime keeps one across rebuilds); on_applied: called by set_settings /
    import_settings with the changed keys (Runtime.reload); settings_path: () -> the settings file (default: the
    configuration's, DARKROOM_CONFIG first); allow_unconfigured: without a preset folder, build a facade whose
    settings / version operations work and every other operation raises the configuration error.

    Returns a DarkroomFacade. Raises ConfigError / FileNotFoundError when no preset folder is configured / found
    (unless allow_unconfigured). Side effect: sets the write module's `configured_preset_dir` hook (a function,
    evaluated at write time). Nothing is written to disk and the GPU is not initialised here."""
    settings_store = SettingsStore(settings_path or config.config_path)
    safe_write.configured_preset_dir = _configured_preset_dir      # v2: injected, the write module reads no config
    # Folders given by the caller (the command line's --preset-dir / --data-dir, kept by Runtime) win over the
    # settings file for this process; the settings service reports them as in use (source "cli") and lists a
    # change to one as pending a restart instead of applied.
    preset_dir_given, library_dir_given = preset_dir is not None, library_dir is not None
    pinned = {"data_dir": os.path.abspath(data_dir)} if data_dir is not None else {}
    try:
        if library is None:
            if preset_dir is None:
                preset_dir = config.preset_dir()
                if library_dir is None:
                    library_dir = config.preset_library_dir()
            library = Library(preset_dir, library_dir)
    except UNCONFIGURED_ERRORS as e:
        if not allow_unconfigured:
            raise
        stub = _Unconfigured(e)
        settings = SettingsService(settings_store, app_version=__version__, preset_dir_of=lambda: None,
                                   on_applied=on_applied, pinned=pinned)
        return DarkroomFacade(stub, stub, stub, stub, stub, stub, stub, stub, stub, settings)
    if preset_dir_given:
        pinned.update(preset_dir=library.preset_dir, preset_library_dir=library.root)
    elif library_dir_given:
        pinned["preset_library_dir"] = library.root
    ref = engine_ref if engine_ref is not None else EngineRef(engine, _engine_factory)
    detect = dict(detect or {})
    pdir = library.preset_dir
    # one measurement of "may the library be written" (S2 E20), shared by the two writers and the report
    writes = Probe(detect.pop("preset_library_writes", None) or functools.partial(writes_status, library.root))
    presets_lib = PresetLibraryService(library, PresetLibraryStore(library, pdir), writes_gate=writes)
    folder = DataFolder((lambda: data_dir) if data_dir is not None else _configured_data_dir, pdir)
    photo_lib = PhotoLibraryService(library, folder, EditStore(folder), ThumbStore(folder), presets_lib)
    sem = {**_semantic_settings(), "writes_gate": writes, **(semantic or {})}
    semantic_svc = SemanticIndexService(library, SemanticStore(library, pdir, sem.get("clock")), ref, **sem)
    caps = CapabilityService(photo_lib, writes, semantic_svc, detect, comfyui_url_of=lambda: config.comfyui_url())
    export_presets = ExportPresetService(ExportPresetStore(photo_lib.usable_data_dir, pdir))
    settings = SettingsService(settings_store, app_version=__version__, preset_dir_of=lambda: library.preset_dir,
                               capabilities=caps, on_applied=on_applied, pinned=pinned)
    return DarkroomFacade(PresetService(library), PhotoService(ref), PreviewService(library, ref, photo_lib),
                          ExportService(library, ref, pdir, photo_lib, export_presets, caps.feature),
                          presets_lib, photo_lib, semantic_svc, export_presets, caps, settings)


class Runtime:
    """The live facade of a long-running process; `facade` is replaced when the settings change (plan-v2 §3).

    Folders given on the command line (`--preset-dir`, `--data-dir`) stay in force over the settings file for the
    life of the process. The Engine (and its open photos) and, when no library key changed, the preset library view
    are kept; everything else is built again, so the capability cache starts empty.

    A change made by another process (the CLI or the MCP server while the App runs, AGENTS.md) is picked up too:
    the runtime remembers the settings file's signature (path, mtime, size) and the values it was built from;
    `current()` - what the entry adapters call per request - compares the signature (one stat, cheap) and, when the
    file changed, rebuilds with the keys whose values differ, exactly like a change made in this process. So every
    setting - data_dir as much as comfyui_url - takes effect at the same moment, and get_settings (which reads the
    file) never shows values the app is not using. A file that cannot be read (broken JSON) or whose rebuild fails
    leaves the running app as it was (the settings page shows the file's error)."""

    def __init__(self, preset_dir=None, *, library=None, engine=None, library_dir=None, data_dir=None, semantic=None,
                 detect=None, settings_path=None, allow_unconfigured=False):
        self._args = {"preset_dir": preset_dir, "library_dir": library_dir, "data_dir": data_dir,
                      "semantic": semantic, "detect": detect, "settings_path": settings_path,
                      "allow_unconfigured": allow_unconfigured}
        self._store = SettingsStore(settings_path or config.config_path)
        self._ref = EngineRef(engine, _engine_factory)
        self._lock = threading.RLock()         # re-entrant: current() -> reload() on the same thread
        self._sig, self._values = self._signature(), self._file_values()
        self.facade = self._build(library)
        self.first = self.facade               # the facade the process started with (the server compares)

    def _build(self, library=None):
        """A new facade from the remembered command-line arguments, sharing this runtime's EngineRef."""
        return build_facade(library=library, engine_ref=self._ref, on_applied=self.reload, **self._args)

    def _signature(self):
        """(path, mtime_ns, size) of the settings file, (path, None, None) when it does not exist."""
        path = self._store.path
        try:
            st = os.stat(path)
        except OSError:
            return path, None, None
        return path, st.st_mtime_ns, st.st_size

    def _file_values(self):
        """{flat key: value} written in the settings file, or None when it cannot be read (kept as is then)."""
        try:
            obj = self._store.read()
        except DarkroomError:
            return None
        return flatten(obj, os.path.dirname(os.path.abspath(self._store.path)))

    def stale(self):
        """Has the settings file changed since the facade in use was built? One stat; safe on the event loop."""
        return self._signature() != self._sig

    def current(self):
        """The facade to use for the next call: rebuilt first when another process changed the settings file.

        May take seconds when a library key changed (the presets are parsed again), so the App calls it off the
        event loop when `stale()` says so."""
        if not self.stale():
            return self.facade
        with self._lock:
            sig = self._signature()
            if sig == self._sig:
                return self.facade             # another thread already caught up
            values = self._file_values()
            if values is None:                 # broken file: keep running as before, look again when it changes
                self._sig = sig
                return self.facade
            keys = [k for k in KEYS if (self._values or {}).get(k) != values.get(k)]
            if keys:
                try:
                    self.reload(keys)
                except Exception as e:         # e.g. the other process left a preset folder that is gone
                    sys.stderr.write(f"darkroom：設定檔改了，但套用失敗，繼續用原本的設定：{e}\n")
            self._sig, self._values = sig, values
            return self.facade

    def reload(self, keys):
        """Rebuild after a settings change; returns the new capability service (the settings checks use it).

        keys: the flat settings keys that changed. The preset library view (the parsed presets) is reused unless
        a library location key changed and the preset folder is not pinned by the command line, because re-parsing
        1466 presets takes seconds. Thread-safe: concurrent reloads are serialised by a lock; a call already
        running on the old facade finishes with it. On success the file's signature and values are remembered, so
        `current()` does not rebuild a second time for the change this process wrote itself."""
        with self._lock:
            old = self.facade
            library = getattr(old, "_presets", None)
            library = getattr(library, "library", None)
            if set(keys) & set(LIBRARY_KEYS) and self._args["preset_dir"] is None:
                library = None                 # the preset folder or the library root may have moved: read again
            self.facade = self._build(library)
            self._sig, self._values = self._signature(), self._file_values()
            return getattr(self.facade, "_capabilities", None)


def warm_capabilities(facade):
    """CONTRACT-s2-export-detect E22 / IP6: the App measures the capability items that need no subprocess on a
    background thread at start-up (op whoami waits for the first capabilities request).

    Does nothing when the facade has no CapabilityService (e.g. the unconfigured stand-in). The thread is a daemon
    so it never keeps the process alive."""
    caps = getattr(facade, "_capabilities", None)
    if isinstance(caps, CapabilityService):
        threading.Thread(target=caps.warm_up, name="darkroom-capabilities", daemon=True).start()
