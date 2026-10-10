"""Capability detection (CONTRACT-s2-export-detect E22-E24): what this machine and configuration can do, and why not.

Layer: services. Items, in this order, each {"available": bool, "reason": str | None}. Every item has one detector,
a zero-argument function returning (available, reason); `build_facade(detect={...})` replaces any of them (tests
always do). Results are kept for the life of the process; `capabilities(refresh=True)` measures again. Detection
writes nothing and reads no photo; `op whoami` for `onepassword` (WG16) only runs when an Anthropic key reference is
configured and is never part of the App's start-up warm-up (IP6).

A feature that is off is switched off where it is used, with this very sentence: the export refuses WebP, the
preset library refuses writes (E20); the photo library, the GPU and HEIC say it themselves in the same words.

`Probe` is how one measurement is shared without the services referring to each other (v2: the composition used to
hand the capability service back to the preset library and the semantic index after building them). The composition
makes one Probe for "may the preset library be written", gives it to both services as their gate and to this
service as the item's detector; `capabilities(refresh=True)` refreshes it.

Why measure instead of letting things fail: a user should learn "WebP is not available on this machine because ..."
before choosing WebP, and an agent should be able to ask what works before trying. Measuring once per process keeps
the report cheap (importing torch to ask about CUDA takes seconds).

Contract codes: E22 = the operation and its item order; E23 = what each item checks and what "off" means; E24 =
1Password sign-in detection and its sentence; E20 = the preset-library-writes item; IP6 = what the start-up
warm-up may measure; WG16 = `op whoami` is an allowed subprocess only in this shape.
"""
import threading

from ..domain import messages as M
from ..domain.settings import LOOPBACK_HOSTS
from ..utils.text import one_line

FEATURES = ("gpu", "heic", "webp", "photo_library", "preset_library_writes", "semantic_index", "onepassword",   # E22
            "comfyui", "agent_sdk")                                                      # + plan-v2 §3 (v2)
COMFYUI_TIMEOUT_S = 1.0                     # plan-v2 §3: GET {comfyui_url}/system_stats, 1 s
WARM_UP = ("gpu", "heic", "webp", "photo_library", "preset_library_writes")      # IP6: never op at App start-up


def detect_gpu():
    """CUDA usable? (imports torch, which takes seconds the first time)."""
    import torch
    return (True, None) if torch.cuda.is_available() else (False, M.CAP_NO_GPU)


def detect_heic():
    """pillow-heif installed?"""
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        return False, M.CAP_NO_HEIC
    return True, None


def detect_webp():
    """Does this OpenCV build have a WebP encoder?"""
    import cv2
    return (True, None) if cv2.haveImageWriter(".webp") else (False, M.CAP_NO_WEBP)


def detect_comfyui(url, timeout=None):
    """plan-v2 §3: ComfyUI answers GET {url}/system_stats with 200 within COMFYUI_TIMEOUT_S. Loopback only (the
    setting refuses anything else); system proxies are bypassed so a proxy never answers for the local server."""
    import http.client
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url)
        if (u.hostname or "").lower() not in LOOPBACK_HOSTS:   # second line of defence: never another machine
            return False, M.CAP_COMFYUI_NOT_LOCAL.format(url=url)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(u.hostname, u.port, timeout=COMFYUI_TIMEOUT_S if timeout is None else timeout)
        try:                                    # a direct connection: no proxy ever answers for the local server
            conn.request("GET", "/system_stats")
            status = conn.getresponse().status
        finally:
            conn.close()
    except Exception as e:                      # refused, timed out, not HTTP: why, in one line
        return False, M.CAP_COMFYUI_DOWN.format(url=url, reason=one_line(e))
    if status != 200:
        return False, M.CAP_COMFYUI_DOWN.format(url=url, reason=f"HTTP {status}")
    return True, None


def _agent_sdk(semantic):
    """plan-v2 §3: the anthropic package is installed and a key source is configured (the 1Password reference or
    DARKROOM_ANTHROPIC_API_KEY). The secret is never read here."""
    if not semantic.have_anthropic():
        return False, M.SEM_NEED_PACKAGE
    if not semantic.key_source_known():
        return False, M.CAP_AGENT_NEED_KEY
    return True, None


def _measure(detect):
    """(bool, reason or None) of one detector; a detector that breaks says so instead of failing the request."""
    try:
        ok, reason = detect()
    except Exception as e:
        ok, reason = False, one_line(e)
    return bool(ok), None if ok else reason


class Probe:
    """One check measured once and shared: calling it gives the cached (available, reason); refresh() forgets it."""

    def __init__(self, detect):
        """detect: () -> (available, reason)."""
        self._detect = detect
        self._value = None
        self._lock = threading.Lock()

    def __call__(self):
        # The detector runs outside the lock: a slow check must not block other threads asking for the cached value.
        # Two threads may then measure at once; both store the same kind of answer, which is harmless.
        with self._lock:
            if self._value is not None:
                return self._value
        value = _measure(self._detect)
        with self._lock:
            self._value = value
        return value

    def refresh(self):
        """Forget the cached value; the next call measures again."""
        with self._lock:
            self._value = None


class CapabilityService:
    """The capabilities operation plus `feature(name)`, which other services use to switch a feature off."""

    def __init__(self, photo_library, preset_writes, semantic, detect=None, comfyui_url_of=None):
        """photo_library: has availability(); preset_writes: () -> (available, reason) (a Probe in the App);
        semantic: has capability(), key_ref_in_use(), key_source_known(), signed_in(), have_anthropic();
        detect: tests' replacements by item name; comfyui_url_of: () -> the comfyui_url setting."""
        url_of = comfyui_url_of or (lambda: "http://127.0.0.1:8188")
        self._detect = {
            "gpu": detect_gpu,
            "heic": detect_heic,
            "webp": detect_webp,
            "photo_library": photo_library.availability,
            "preset_library_writes": preset_writes,
            "semantic_index": lambda: self._semantic(semantic),
            "onepassword": lambda: self._onepassword(semantic),
            "comfyui": lambda: detect_comfyui(url_of()),
            "agent_sdk": lambda: _agent_sdk(semantic),
        }
        unknown = set(detect or {}) - set(FEATURES)
        if unknown:
            raise ValueError(f"unknown capability {sorted(unknown)}")
        self._detect.update(detect or {})
        self._cache = {}
        self._lock = threading.Lock()

    @staticmethod
    def _onepassword(semantic):
        """Only relevant when a 1Password reference is configured; then: is the op CLI signed in?"""
        if not semantic.key_ref_in_use():
            return False, M.OP_NOT_USED
        return semantic.signed_in()

    def _semantic(self, semantic):
        """The semantic index is usable only if its own checks pass and, when the key comes from 1Password, op is
        signed in (otherwise a build would fail at the last step)."""
        ok, reason = semantic.capability()
        if ok and semantic.key_ref_in_use():
            op_ok, op_reason = self.feature("onepassword")
            if not op_ok:
                return False, op_reason
        return ok, reason

    def feature(self, name, refresh=False):
        """(available, reason) of one item, measured once (refresh: again)."""
        with self._lock:
            if not refresh and name in self._cache:
                return self._cache[name]
        detect = self._detect[name]
        if refresh and isinstance(detect, Probe):
            detect.refresh()
        value = _measure(detect)
        with self._lock:
            self._cache[name] = value
        return value

    def warm_up(self):
        """App start-up (E22): the items that need no subprocess, measured in the background."""
        for name in WARM_UP:
            try:
                self.feature(name)
            except Exception:           # a detector failing here is measured again by the first request
                with self._lock:
                    self._cache.pop(name, None)

    def capabilities(self, refresh=False):
        """{"features": {item: {available, reason}}} in the E22 order; refresh measures every item again."""
        if refresh:
            with self._lock:
                self._cache.clear()
            for detect in self._detect.values():
                if isinstance(detect, Probe):
                    detect.refresh()
        out = {}
        for name in FEATURES:
            ok, reason = self.feature(name)
            out[name] = {"available": ok, "reason": reason}
        return {"features": out}
