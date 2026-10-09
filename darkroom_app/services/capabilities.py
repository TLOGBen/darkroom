"""Capability detection (CONTRACT-s2-export-detect E22-E24): what this machine and configuration can do, and why not.

Seven items, in this order, each {"available": bool, "reason": str | None}. Every item has one detector, a
zero-argument function returning (available, reason); `build_facade(detect={...})` replaces any of them (tests
always do). Results are kept for the life of the process; `capabilities(refresh=True)` measures again. Detection
writes nothing, reads no photo and touches no network - except `op whoami` for `onepassword` (WG16), which only runs
when an Anthropic key reference is configured and is never part of the App's start-up warm-up (IP6).

A feature that is off is switched off where it is used, with this very sentence: the export refuses WebP, the
preset library refuses writes (E20); the photo library, the GPU and HEIC say it themselves in the same words.
"""
import threading

from .. import messages as M

FEATURES = ("gpu", "heic", "webp", "photo_library", "preset_library_writes", "semantic_index", "onepassword")   # E22
WARM_UP = ("gpu", "heic", "webp", "photo_library", "preset_library_writes")      # IP6: never op at App start-up


def detect_gpu():
    import torch
    return (True, None) if torch.cuda.is_available() else (False, M.CAP_NO_GPU)


def detect_heic():
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        return False, M.CAP_NO_HEIC
    return True, None


def detect_webp():
    import cv2
    return (True, None) if cv2.haveImageWriter(".webp") else (False, M.CAP_NO_WEBP)


class CapabilityService:
    def __init__(self, photo_library, preset_library, semantic, detect=None):
        self._detect = {
            "gpu": detect_gpu,
            "heic": detect_heic,
            "webp": detect_webp,
            "photo_library": photo_library.availability,
            "preset_library_writes": preset_library.writes_status,
            "semantic_index": lambda: self._semantic(semantic),
            "onepassword": lambda: self._onepassword(semantic),
        }
        unknown = set(detect or {}) - set(FEATURES)
        if unknown:
            raise ValueError(f"unknown capability {sorted(unknown)}")
        self._detect.update(detect or {})
        self._cache = {}
        self._lock = threading.Lock()

    @staticmethod
    def _onepassword(semantic):
        if not semantic.key_ref_in_use():
            return False, M.OP_NOT_USED
        return semantic.signed_in()

    def _semantic(self, semantic):
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
        try:
            ok, reason = self._detect[name]()
        except Exception as e:          # a detector that breaks says so instead of failing the request
            ok, reason = False, " ".join(str(e).split()) or type(e).__name__
        value = (bool(ok), None if ok else reason)
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
        out = {}
        for name in FEATURES:
            ok, reason = self.feature(name)
            out[name] = {"available": ok, "reason": reason}
        return {"features": out}
