"""aiohttp application: static editor page plus the JSON / JPEG API (contract B3-B8).

Handlers only translate HTTP <-> facade calls (ADR-0001, CONTRACT-layering): the rules and every error
sentence live in darkroom_app.services. Photos and purchased presets are only read; what writes is the facade's
`export` (POST /api/export: new files in the export folder only, CONTRACT-export X14) and the preset library
operations under /api/preset-library/ (the index, import/ and user/ of the library root only,
CONTRACT-preset-library K18 / KP1). None of them takes a path over HTTP: import takes uploaded bytes (KP4).

Cross-site protection (CONTRACT-export XP16, app shell R10): every request first passes `_local_only`: the Host
header must be 127.0.0.1:{port} or localhost:{port} (DNS rebinding), an Origin header must be the page's own origin,
and a POST body must be declared application/json (so a cross-site fetch always needs a CORS preflight, which this
server never answers). Over HTTP, export takes no dest_dir (the editor never picks a folder; CLI / MCP only).
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
HOST_REFUSED = "request refused: Host must be 127.0.0.1:{port} or localhost:{port}"   # verbatim (XP16), 421
ORIGIN_REFUSED = "request refused: cross-site Origin {origin}"                        # verbatim (XP16), 403
CONTENT_TYPE_REFUSED = "request refused: POST body must be application/json"          # verbatim (XP16), 415
DEST_DIR_REFUSED = "dest_dir is not accepted over HTTP (use the CLI or MCP)"           # verbatim (XP16), 400
PATHS_REFUSED = "paths is not accepted over HTTP (upload the files)"                   # verbatim (KP4), 400


@web.middleware
async def _local_only(request, handler):
    """Host -> Origin -> Content-Type, before any route (XP16)."""
    sock = request.transport.get_extra_info("sockname") if request.transport is not None else None
    port = sock[1] if sock else None
    allowed = (f"127.0.0.1:{port}", f"localhost:{port}")
    if request.headers.get("Host", "").lower() not in allowed:
        return web.json_response({"error": HOST_REFUSED.format(port=port)}, status=421)
    origin = request.headers.get("Origin")
    if origin is not None and origin.lower() not in tuple("http://" + a for a in allowed):
        return web.json_response({"error": ORIGIN_REFUSED.format(origin=origin)}, status=403)
    if request.method == "POST" and request.content_type != "application/json":
        return web.json_response({"error": CONTENT_TYPE_REFUSED}, status=415)
    return await handler(request)


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
    favorites = request.query.get("favorites") == "1"           # K9: GET /api/presets?favorites=1
    try:
        listing = await _call(request, "list_presets", None, 0, None, favorites)
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


async def api_export(request):
    body = await _json_body(request)
    if "dest_dir" in body:                 # an interface rule (XP16): the editor never picks a folder
        return web.json_response({"error": DEST_DIR_REFUSED}, status=400)
    return await _json(request, "export", body.get("items"), body.get("format"), body.get("quality"), None)


async def api_library_groups(request):
    return await _json(request, "preset_groups")


async def api_library_rename(request):
    body = await _json_body(request)
    return await _json(request, "rename_preset", body.get("preset_id"), body.get("name"))


async def api_library_move(request):
    body = await _json_body(request)
    return await _json(request, "move_preset", body.get("preset_id"), body.get("group"))


async def api_library_favorite(request):
    body = await _json_body(request)
    return await _json(request, "set_favorite", body.get("preset_id"), body.get("favorite"))


async def api_group_create(request):
    body = await _json_body(request)
    return await _json(request, "create_group", body.get("group"))


async def api_group_rename(request):
    body = await _json_body(request)
    return await _json(request, "rename_group", body.get("group"), body.get("new_name"))


async def api_library_import(request):
    body = await _json_body(request)
    if "paths" in body:                    # an interface rule (KP4): over HTTP only uploaded bytes, never a path
        return web.json_response({"error": PATHS_REFUSED}, status=400)
    return await _json(request, "import_presets", None, body.get("group"), body.get("files"))


async def api_library_save(request):
    body = await _json_body(request)
    return await _json(request, "save_user_preset", body.get("name"), body.get("group"), body.get("preset_id"),
                       body.get("strength", 100), body.get("overrides"))


async def api_library_rebuild(request):
    await _json_body(request)
    return await _json(request, "rebuild_library")


async def api_folder(request):
    return await _json(request, "list_folder", request.query.get("image_id", ""))


async def _on_cleanup(app):
    app[ENGINE].shutdown()


def make_app(preset_dir, engine=None, library_dir=None):
    """library_dir: the preset library root (default dirname(preset_dir); CONTRACT-preset-library KP2)."""
    app = web.Application(client_max_size=1 << 20, middlewares=[_local_only])
    app[LIBRARY] = Library(preset_dir, library_dir)
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
    app.router.add_post("/api/export", api_export)
    app.router.add_get("/api/preset-library/groups", api_library_groups)
    app.router.add_post("/api/preset-library/rename", api_library_rename)
    app.router.add_post("/api/preset-library/move", api_library_move)
    app.router.add_post("/api/preset-library/favorite", api_library_favorite)
    app.router.add_post("/api/preset-library/groups/create", api_group_create)
    app.router.add_post("/api/preset-library/groups/rename", api_group_rename)
    app.router.add_post("/api/preset-library/import", api_library_import)
    app.router.add_post("/api/preset-library/save", api_library_save)
    app.router.add_post("/api/preset-library/rebuild", api_library_rebuild)
    app.router.add_static("/static/", STATIC)
    app.on_cleanup.append(_on_cleanup)
    return app


async def start(preset_dir, port=DEFAULT_PORT, engine=None, warm_up=True, library_dir=None):
    """Start serving on 127.0.0.1:port (0 = any free port). Returns (runner, actual_port)."""
    app = make_app(preset_dir, engine, library_dir)
    if warm_up:
        await asyncio.get_running_loop().run_in_executor(app[ENGINE].executor, app[ENGINE].warm_up)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, port)
    await site.start()
    actual = runner.addresses[0][1]
    return runner, actual
