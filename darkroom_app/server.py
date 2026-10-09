"""aiohttp application: static editor page plus the JSON / JPEG API (contract B3-B8).

Handlers only translate HTTP <-> facade calls (ADR-0001, CONTRACT-layering): the rules and every error
sentence live in darkroom_app.services. The server only reads photos and presets; it never writes either.
"""
import asyncio
import os

from aiohttp import web

from . import engine as engine_mod
from .composition import build_facade
from .errors import DarkroomError
from .facade import Facade
from .messages import OPEN_ERROR  # noqa: F401  (re-exported: verbatim constant, CONTRACT-heic)
from .presets import Library

HOST = "127.0.0.1"          # only ever bound to the local machine (B2)
DEFAULT_PORT = 8765
READY_LINE = "darkroom 已啟動：http://127.0.0.1:{port}/"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

LIBRARY = web.AppKey("library", Library)
ENGINE = web.AppKey("engine", engine_mod.Engine)
FACADE = web.AppKey("facade", Facade)

STATUS = {"invalid": 400, "not_found": 404, "conflict": 409, "unavailable": 503}


def _error(e):
    return web.json_response({"error": e.message}, status=STATUS[e.kind])


async def _json_body(request):
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text='{"error": "body must be JSON"}', content_type="application/json")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='{"error": "body must be a JSON object"}', content_type="application/json")
    return body


async def _call(request, operation, *args):
    """facade.<operation>(*args) off the event loop; DarkroomError propagates for the handler to translate."""
    return await asyncio.to_thread(getattr(request.app[FACADE], operation), *args)


async def _json(request, operation, *args):
    try:
        return web.json_response(await _call(request, operation, *args))
    except DarkroomError as e:
        return _error(e)


async def index(request):
    return web.FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


async def health(request):
    return web.json_response({"ok": True})


async def api_presets(request):
    try:
        listing = await _call(request, "list_presets")
    except DarkroomError as e:
        return _error(e)
    return web.json_response(listing["items"])


async def api_preset_detail(request):
    return await _json(request, "preset_detail", request.match_info["id"])


async def api_preset_flags(request):
    return await _json(request, "preset_flags")


async def api_sliders(request):
    return await _json(request, "slider_table")


async def api_open(request):
    body = await _json_body(request)
    return await _json(request, "open_photo", body.get("path"))


async def api_preview(request):
    body = await _json_body(request)
    try:
        res = await _call(request, "preview", body.get("image_id"), body.get("preset_id"),
                          body.get("strength", 100), body.get("overrides"))
    except DarkroomError as e:
        return _error(e)
    return web.Response(body=res.jpeg, content_type="image/jpeg",
                        headers={"X-Render-Ms": f"{res.render_ms:.2f}", "Cache-Control": "no-store",
                                 "Access-Control-Expose-Headers": "X-Render-Ms"})


async def api_folder(request):
    return await _json(request, "list_folder", request.query.get("image_id", ""))


async def _on_cleanup(app):
    app[ENGINE].shutdown()


def make_app(preset_dir, engine=None):
    app = web.Application(client_max_size=1 << 20)
    app[LIBRARY] = Library(preset_dir)
    app[ENGINE] = engine or engine_mod.Engine()
    app[FACADE] = build_facade(library=app[LIBRARY], engine=app[ENGINE])
    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/presets", api_presets)
    app.router.add_get("/api/preset_flags", api_preset_flags)
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
