"""Services: every rule behind the facade (ADR-0001; plan-v2 §1).

Layer: services. A service takes domain objects and the stores / the Engine the composition hands in; it never
imports the facade, the entry adapters (http / cli / mcp_server), config or the write module, and never parses a
request (no aiohttp, no argparse). What a service needs to read from the configuration arrives as a value or a
zero-argument function.

The GPU helpers live here so all services share one rule: Engine work runs on the Engine's single `darkroom-gpu`
executor (never a second one), and runs in place when the caller is already on that thread (L6).

Why one GPU thread: CUDA work from several Python threads would interleave on the device and fight over its 16 GB;
a single executor serialises renders (a newer preview simply queues behind the current one) and keeps every tensor
on one CUDA stream. "In place when already on that thread" prevents a deadlock when GPU code calls a helper that
itself asks for the GPU.

Modules: presets (list / detail / flags / sliders), photos (open a photo, list its folder), preview, export,
preset_library (organising presets, user presets, .xmp files), photo_library (edits, thumbnails), semantic_index
(Claude-written style tags), export_presets, capabilities (what this machine can do), settings.

Contract code: L6 = every Engine call runs on the `darkroom-gpu` executor, callable from any thread.
"""
import threading

GPU_THREAD_PREFIX = "darkroom-gpu"


class EngineRef:
    """The Engine, built on the first call of get() (torch / cv2 are only imported then).

    `factory` builds it (the composition passes the GPU adapter's `Engine`); an Engine given up front is used as is.
    One EngineRef is shared by every service and survives a settings change, so open images stay open."""

    def __init__(self, engine=None, factory=None):
        """engine: an existing Engine (tests) or None; factory: () -> Engine, called once on first get()."""
        self._engine = engine
        self._factory = factory
        self._lock = threading.Lock()

    def peek(self):
        """The Engine if it exists, else None (never builds it)."""
        return self._engine

    def get(self):
        """The Engine, building it on first use (double-checked under a lock so two threads never build two).

        Raises RuntimeError when no Engine and no factory were given (a wiring bug). Building it imports torch
        and initialises CUDA, which takes seconds."""
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    if self._factory is None:
                        raise RuntimeError("no Engine factory was given to EngineRef")
                    self._engine = self._factory()
        return self._engine


def on_gpu(engine, fn, *args):
    """Run fn(*args) on the Engine's darkroom-gpu executor and wait; in place if already on that thread."""
    if threading.current_thread().name.startswith(GPU_THREAD_PREFIX):
        return fn(*args)
    return engine.executor.submit(fn, *args).result()
