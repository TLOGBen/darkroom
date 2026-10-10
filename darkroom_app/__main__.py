"""`python -s -m darkroom_app [--port 8765] [--preset-dir DIR] [--data-dir DIR]`: serve the editor on 127.0.0.1.

Entry point (plan-v2 §1): parses the command line, checks the configuration once so a missing preset folder is one
clear line (exit 2), then starts the HTTP adapter (`adapters/http/server.py`). Folders given here win over the
settings file for this run; without --preset-dir the preset folder comes from the settings, and changing it in the
settings applies at once (the server's Runtime rebuilds the app).

Layer: entry point (allowed to read `config`). Depends on `config` and the HTTP adapter only; it holds no rules.
Side effects: binds a TCP port on 127.0.0.1 (never another interface) and prints READY_LINE to stdout once the
server accepts connections (tools/start.ps1 and the desktop shell wait for that line or for /api/health).
Exit codes: 0 normal stop (Ctrl+C), 1 the server could not start (e.g. port in use), 2 no preset folder configured.
"""
import argparse
import asyncio
import os
import sys

from . import config
from .adapters.http.server import DEFAULT_PORT, READY_LINE, start


async def _serve(preset_dir, port, library_dir=None, data_dir=None):
    """Start the aiohttp app, announce the actual port, then wait forever (until the process is interrupted)."""
    runner, actual = await start(preset_dir, port, library_dir=library_dir, data_dir=data_dir)
    print(READY_LINE.format(port=actual), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main(argv=None):
    """Parse `argv` (None = sys.argv[1:]), check the configuration, run the server; returns the exit code."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m darkroom_app", description="darkroom editor (local only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--preset-dir", default=None, help="default: from LOCALLLMS_ROOT or config.local.json")
    ap.add_argument("--data-dir", default=None, help="photo library folder (default: config data_dir or "
                                                     "%%LOCALAPPDATA%%/darkroom)")
    a = ap.parse_args(argv)
    # S2 E19 (relative folders are resolved once, up front): here against the working directory, before anything
    # uses them, so a later chdir or another module cannot reinterpret them
    data_dir = os.path.abspath(a.data_dir) if a.data_dir else a.data_dir
    preset_dir = os.path.abspath(a.preset_dir) if a.preset_dir else None
    try:
        if preset_dir is None:
            config.preset_dir()            # a missing configuration is one line and exit 2, before anything starts
    except config.ConfigError as e:
        print(f"darkroom：{e}", file=sys.stderr)
        return 2
    try:
        # the configured library root goes with the configured preset folder (CONTRACT-preset-library KP2 = "the
        # settings file's preset_library_dir is used only when preset_dir also comes from the settings"): both are
        # read by the composition when preset_dir is None
        asyncio.run(_serve(preset_dir, a.port, None, data_dir))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"darkroom：無法啟動伺服器：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
