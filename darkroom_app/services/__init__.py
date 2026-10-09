"""Services: every rule behind the facade (ADR-0001). No interface code here (no aiohttp, no argparse).

The GPU helpers live here so all services share one rule: Engine work runs on the Engine's single
`darkroom-gpu` executor (never a second one), and runs in place when the caller is already on that thread.
"""
import threading

GPU_THREAD_PREFIX = "darkroom-gpu"


class EngineRef:
    """The Engine, built on the first call of get() (torch / cv2 are only imported then)."""

    def __init__(self, engine=None):
        self._engine = engine
        self._lock = threading.Lock()

    def peek(self):
        """The Engine if it exists, else None (never builds it)."""
        return self._engine

    def get(self):
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    from .. import engine as engine_mod
                    self._engine = engine_mod.Engine()
        return self._engine


def on_gpu(engine, fn, *args):
    """Run fn(*args) on the Engine's darkroom-gpu executor and wait; in place if already on that thread."""
    if threading.current_thread().name.startswith(GPU_THREAD_PREFIX):
        return fn(*args)
    return engine.executor.submit(fn, *args).result()
