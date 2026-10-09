"""`python -s -m darkroom_app.mcp_server [--preset-dir DIR] [--data-dir DIR]`: darkroom as an MCP stdio server
(CONTRACT-layering L10).

stdout carries only protocol lines: at start-up fd 1 is kept (os.dup) for the protocol and then pointed at
stderr (os.dup2), and sys.stdout becomes sys.stderr, so stray output from any library lands in the log.
The facade (preset library, and the Engine on first GPU use) is built on the first tools/call.
"""
import argparse
import os
import sys
import threading

from .protocol import Dispatcher, encode
from .tools import Tools


def _log(text):
    sys.stderr.write(f"[darkroom-mcp] {text}\n")
    sys.stderr.flush()


class _LazyFacade:
    def __init__(self, preset_dir=None, facade=None, data_dir=None):
        self._preset_dir, self._facade, self._data_dir = preset_dir, facade, data_dir
        self._lock = threading.Lock()

    def __call__(self):
        if self._facade is None:
            with self._lock:
                if self._facade is None:
                    from ..composition import build_facade
                    self._facade = build_facade(self._preset_dir, data_dir=self._data_dir)
        return self._facade


def serve(stdin, stdout, facade=None, preset_dir=None, data_dir=None):
    """Answer requests read line by line from binary `stdin` on binary `stdout` until EOF. Returns 0."""
    dispatcher = Dispatcher(Tools(_LazyFacade(preset_dir, facade, data_dir)))
    for line in iter(stdin.readline, b""):
        response = dispatcher.handle(line)
        if response is not None:
            stdout.write(encode(response))
            stdout.flush()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m darkroom_app.mcp_server")
    ap.add_argument("--preset-dir", default=None, help="default: from LOCALLLMS_ROOT or config.local.json")
    ap.add_argument("--data-dir", default=None, help="photo library folder (default: config data_dir or "
                                                     "%%LOCALAPPDATA%%/darkroom)")
    a = ap.parse_args(argv)
    # S2 E19: relative folders are made absolute against the working directory before anything uses them
    preset_dir = os.path.abspath(a.preset_dir) if a.preset_dir else a.preset_dir
    data_dir = os.path.abspath(a.data_dir) if a.data_dir else a.data_dir
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    out = os.fdopen(protocol_fd, "wb")
    _log("ready (stdio)")
    try:
        return serve(sys.stdin.buffer, out, preset_dir=preset_dir, data_dir=data_dir)
    finally:
        _log("stdin closed, exiting")
        out.flush()
