"""aiohttp application: static editor page plus the JSON / JPEG API (contract B3-B8).

The server only reads photos and presets; it never writes either (there is no export in this slice).
"""
import asyncio
import os

from aiohttp import web

from . import engine as engine_mod
from . import preview, sliders
from .presets import Library

HOST = "127.0.0.1"          # only ever bound to the local machine (B2)
DEFAULT_PORT = 8765
READY_LINE = "darkroom 已啟動：http://127.0.0.1:{port}/"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

LIBRARY = web.AppKey("library", Library)
ENGINE = web.AppKey("engine", engine_mod.Engine)


def _bad(msg, status=400):
    return web.json_response({"error": msg}, status=status)


async def _json_body(request):
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text='{"error": "body must be JSON"}', content_type="application/json")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='{"error": "body must be a JSON object"}', content_type="application/json")
    return body


async def _run(request, fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(request.app[ENGINE].executor, fn, *args)


async def index(request):
    return web.FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


async def health(request):
    return web.json_response({"ok": True})


async def api_presets(request):
    return web.json_response([{k: e[k] for k in ("id", "group", "name", "supported", "skipped")}
                              for e in request.app[LIBRARY].entries])


async def api_preset_detail(request):
    lib = request.app[LIBRARY]
    pid = request.match_info["id"]
    if pid not in lib.by_id:
        return _bad(f"unknown preset {pid}", 404)
    return web.json_response(lib.detail(pid))


async def api_sliders(request):
    return web.json_response({"groups": [list(g) for g in sliders.GROUPS], "sliders": sliders.SLIDERS})


async def api_open(request):
    body = await _json_body(request)
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        return _bad("path is required")
    path = path.strip().strip('"')
    if not os.path.isfile(path):
        return _bad(f"photo not found: {path}", 404)
    if os.path.splitext(path)[1].lower() not in engine_mod.PHOTO_EXT:
        return _bad("unsupported photo format (JPEG/PNG/TIFF)")
    try:
        info = await _run(request, request.app[ENGINE].open, path)
    except (OSError, ValueError) as e:
        return _bad(f"cannot read photo: {e}")
    return web.json_response(info)


async def api_preview(request):
    body = await _json_body(request)
    eng, lib = request.app[ENGINE], request.app[LIBRARY]
    image_id = body.get("image_id")
    if not isinstance(image_id, str) or image_id not in eng.images:
        return _bad("unknown image_id", 404)
    pid = body.get("preset_id")
    params = None
    if pid is not None:
        if not isinstance(pid, str) or pid not in lib.params:
            return _bad(f"unknown or unsupported preset {pid}", 404)
        params = lib.get(pid)
    try:
        strength = preview.validate_strength(body.get("strength", 100))
        overrides = preview.validate_overrides(body.get("overrides"))
    except ValueError as e:
        return _bad(str(e))
    final = preview.effective_params(params, strength, overrides)
    try:
        data, ms = await _run(request, eng.preview, image_id, final)
    except KeyError:
        return _bad("unknown image_id", 404)
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"X-Render-Ms": f"{ms:.2f}", "Cache-Control": "no-store",
                                 "Access-Control-Expose-Headers": "X-Render-Ms"})


def folder_listing(path):
    folder = os.path.dirname(os.path.abspath(path))
    names = [n for n in os.listdir(folder)
             if os.path.splitext(n)[1].lower() in engine_mod.PHOTO_EXT and os.path.isfile(os.path.join(folder, n))]
    names.sort(key=lambda n: (n.casefold(), n))
    files = [{"name": n, "path": os.path.join(folder, n)} for n in names]
    base = os.path.normcase(os.path.basename(path))
    index = next((i for i, n in enumerate(names) if os.path.normcase(n) == base), -1)
    return {"folder": folder, "files": files, "index": index}


async def api_folder(request):
    eng = request.app[ENGINE]
    image_id = request.query.get("image_id", "")
    if image_id not in eng.images:
        return _bad("unknown image_id", 404)
    return web.json_response(folder_listing(eng.get(image_id)["path"]))


async def _on_cleanup(app):
    app[ENGINE].shutdown()


def make_app(preset_dir, engine=None):
    app = web.Application(client_max_size=1 << 20)
    app[LIBRARY] = Library(preset_dir)
    app[ENGINE] = engine or engine_mod.Engine()
    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/presets", api_presets)
    app.router.add_get("/api/presets/{id}", api_preset_detail)
    app.router.add_get("/api/sliders", api_sliders)
    app.router.add_post("/api/open", api_open)
    app.router.add_post("/api/preview", api_preview)
    app.router.add_get("/api/folder", api_folder)
    app.router.add_static("/static/", STATIC)
    app.on_cleanup.append(_on_cleanup)
    return app


async def start(preset_dir, port=DEFAULT_PORT, engine=None, warm_up=True):
    """Start serving on 127.0.0.1:port (0 = any free port). Returns (runner, actual_port)."""
    app = make_app(preset_dir, engine)
    if warm_up:
        await asyncio.get_running_loop().run_in_executor(app[ENGINE].executor, app[ENGINE].warm_up)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, port)
    await site.start()
    actual = runner.addresses[0][1]
    return runner, actual
