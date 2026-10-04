"""`python -s -m darkroom_app [--port 8765] [--preset-dir DIR]`: serve the editor on 127.0.0.1."""
import argparse
import asyncio
import sys

from . import config
from .server import DEFAULT_PORT, READY_LINE, start


async def _serve(preset_dir, port):
    runner, actual = await start(preset_dir, port)
    print(READY_LINE.format(port=actual), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m darkroom_app", description="darkroom editor (local only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--preset-dir", default=None, help="default: from LOCALLLMS_ROOT or config.local.json")
    a = ap.parse_args(argv)
    try:
        preset_dir = a.preset_dir or config.preset_dir()
    except config.ConfigError as e:
        print(f"darkroom：{e}", file=sys.stderr)
        return 2
    try:
        asyncio.run(_serve(preset_dir, a.port))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"darkroom：無法啟動伺服器：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
