"""aiohttp application: static editor page plus the JSON / JPEG API (contract B3-B8).

Handlers only translate HTTP <-> facade calls (ADR-0001, CONTRACT-layering): the rules and every error
sentence live in darkroom_app.services. Photos and purchased presets are only read; what writes is the facade's
`export` (POST /api/export: new files in the export folder only, CONTRACT-export X14) and the preset library
operations under /api/preset-library/ (the index, import/ and user/ of the library root only,
CONTRACT-preset-library K18 / KP1), and the photo library under /api/edit, /api/edit/paste, /api/edit/save-preset,
/api/folder/thumbnails and /api/thumbnail (edits, thumbnails and the thumbnail index in the configured data_dir
only, CONTRACT-photo-library PLP1 / PLP2). No request names a place to write: import takes uploaded bytes (KP4), the
photo library's paths are photos that are only read (hashed, decoded), like /api/open.

Cross-site protection (CONTRACT-export XP16, app shell R10 / R11, photo library PLP11): every request first passes
`_local_only`: the Host header must be 127.0.0.1:{port} or localhost:{port} (DNS rebinding), a Sec-Fetch-Site of
cross-site / same-site is refused (an <img src> or <script src> from another page), an Origin header must be the
page's own origin, a POST / PUT body must be declared application/json, and the four GETs that read a photo path
must carry X-Darkroom: 1 (an img / script tag cannot add it; a cross-site fetch that adds it needs a CORS
preflight, which this server never answers). Over HTTP, export takes no dest_dir (the editor never picks a folder;
CLI / MCP only).
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
DATA_DIR_REFUSED = "data_dir is not accepted over HTTP (it is configured)"             # verbatim (PLP2), 400
SEMANTIC_BUILD_REFUSED = "semantic build is not accepted over HTTP (use the CLI or MCP)"   # verbatim (SI11), 400
FETCH_SITE_REFUSED = "request refused: cross-site request (Sec-Fetch-Site {value})"     # verbatim (PLP11), 403
DARKROOM_HEADER_REFUSED = "request refused: X-Darkroom header required"                # verbatim (PLP11), 403
PATH_READING_GETS = frozenset(("/api/folder", "/api/edit", "/api/folder/thumbnails", "/api/thumbnail"))   # PLP11


def _lenient_int(text):
    """A query-string number -> int when it is all digits, else the raw string (the service says why; PLP8)."""
    return int(text) if text.isdigit() else text


@web.middleware
async def _local_only(request, handler):
    """Host -> Sec-Fetch-Site -> Origin -> Content-Type -> X-Darkroom, before any route (XP16, PLP11 / R11)."""
    sock = request.transport.get_extra_info("sockname") if request.transport is not None else None
    port = sock[1] if sock else None
    allowed = (f"127.0.0.1:{port}", f"localhost:{port}")
    if request.headers.get("Host", "").lower() not in allowed:
        return web.json_response({"error": HOST_REFUSED.format(port=port)}, status=421)
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None and site.lower() in ("cross-site", "same-site"):       # an <img src> from another page
        return web.json_response({"error": FETCH_SITE_REFUSED.format(value=site)}, status=403)
    origin = request.headers.get("Origin")
    if origin is not None and origin.lower() not in tuple("http://" + a for a in allowed):
        return web.json_response({"error": ORIGIN_REFUSED.format(origin=origin)}, status=403)
    if request.method in ("POST", "PUT") and request.content_type != "application/json":   # PLP2: PUT too
        return web.json_response({"error": CONTENT_TYPE_REFUSED}, status=415)
    if request.method in ("GET", "HEAD") and request.headers.get("X-Darkroom") != "1":   # PLP11 / PLP12
        resource = request.match_info.route.resource if request.match_info.route is not None else None
        # the resolved route, not the raw path; a HEAD that resolved to nothing (allow_head=False -> 405) is judged
        # by its path so it is refused the same way before the 405
        canonical = resource.canonical if resource is not None else request.path
        if canonical in PATH_READING_GETS:
            return web.json_response({"error": DARKROOM_HEADER_REFUSED}, status=403)   # img / script cannot add it
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


async def api_semantic_build(request):
    """An interface rule (CONTRACT-semantic-index SI11): building costs money, so the page never triggers it."""
    return web.json_response({"error": SEMANTIC_BUILD_REFUSED}, status=400)


async def api_semantic_status(request):
    return await _json(request, "semantic_status")


async def api_folder(request):
    return await _json(request, "list_folder", request.query.get("image_id", ""))


# ---- CONTRACT-photo-library PL6 / PLP2: paths over HTTP are only read; every write lands in the configured data_dir
async def api_edit_get(request):
    return await _json(request, "get_edit", request.query.get("path"))


async def api_edit_set(request):
    body = await _json_body(request)
    if "data_dir" in body:                 # an interface rule (PLP2): the data folder is configured, never sent
        return web.json_response({"error": DATA_DIR_REFUSED}, status=400)
    return await _json(request, "set_edit", body.get("path"), body.get("preset_id"), body.get("strength", 100),
                       body.get("overrides"))


async def api_edit_clear(request):
    return await _json(request, "clear_edit", request.query.get("path"))


async def api_edit_paste(request):
    body = await _json_body(request)
    if "data_dir" in body:
        return web.json_response({"error": DATA_DIR_REFUSED}, status=400)
    return await _json(request, "paste_edit", body.get("targets"), body.get("source"), body.get("edit"))


async def api_edit_save_preset(request):
    body = await _json_body(request)
    if "data_dir" in body:
        return web.json_response({"error": DATA_DIR_REFUSED}, status=400)
    return await _json(request, "save_edit_as_preset", body.get("path"), body.get("name"), body.get("group"))


async def api_folder_thumbnails(request):
    q = request.query
    offset = _lenient_int(q["offset"]) if "offset" in q else 0
    limit = _lenient_int(q["limit"]) if "limit" in q else None
    return await _json(request, "folder_thumbnails", q.get("folder"), offset, limit)


async def api_thumbnail(request):
    try:
        res = await _call(request, "thumbnail", request.query.get("path"))
    except DarkroomError as e:
        return _error(e)
    return web.Response(body=res.jpeg, content_type="image/jpeg",
                        headers={"X-Fingerprint": res.fingerprint, "X-Edited": "1" if res.edited else "0",
                                 "Cache-Control": "no-store"})


async def _on_cleanup(app):
    app[ENGINE].shutdown()


def make_app(preset_dir, engine=None, library_dir=None, data_dir=None):
    """library_dir: the preset library root (default dirname(preset_dir); CONTRACT-preset-library KP2);
    data_dir: the photo library's folder (default config.data_dir() on first use; CONTRACT-photo-library PL1)."""
    app = web.Application(client_max_size=1 << 20, middlewares=[_local_only])
    app[LIBRARY] = Library(preset_dir, library_dir)
    app[ENGINE] = engine or engine_mod.Engine()
    app[FACADE] = build_facade(library=app[LIBRARY], engine=app[ENGINE], data_dir=data_dir)
    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/presets", api_presets)
    app.router.add_get("/api/preset_flags", api_preset_flags)
    app.router.add_get("/api/presets/{id}", api_preset_detail)
    app.router.add_get("/api/sliders", api_sliders)
    app.router.add_post("/api/open", api_open)
    app.router.add_post("/api/preview", api_preview)
    app.router.add_get("/api/folder", api_folder, allow_head=False)             # PLP12: no HEAD on path-reading GETs
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
    app.router.add_post("/api/preset-library/semantic/build", api_semantic_build)   # SI11: always refused
    app.router.add_get("/api/preset-library/semantic", api_semantic_status)
    app.router.add_get("/api/edit", api_edit_get, allow_head=False)
    app.router.add_put("/api/edit", api_edit_set)
    app.router.add_delete("/api/edit", api_edit_clear)
    app.router.add_post("/api/edit/paste", api_edit_paste)
    app.router.add_post("/api/edit/save-preset", api_edit_save_preset)
    app.router.add_get("/api/folder/thumbnails", api_folder_thumbnails, allow_head=False)
    app.router.add_get("/api/thumbnail", api_thumbnail, allow_head=False)
    app.router.add_static("/static/", STATIC)
    app.on_cleanup.append(_on_cleanup)
    return app


async def start(preset_dir, port=DEFAULT_PORT, engine=None, warm_up=True, library_dir=None, data_dir=None):
    """Start serving on 127.0.0.1:port (0 = any free port). Returns (runner, actual_port)."""
    app = make_app(preset_dir, engine, library_dir, data_dir)
    if warm_up:
        await asyncio.get_running_loop().run_in_executor(app[ENGINE].executor, app[ENGINE].warm_up)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, port)
    await site.start()
    actual = runner.addresses[0][1]
    return runner, actual
