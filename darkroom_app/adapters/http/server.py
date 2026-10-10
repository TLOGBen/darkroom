"""aiohttp application: the editor page plus the JSON / JPEG API (contract B3-B8; plan-v2 §1, §3).

Layer: adapters/http. Handlers only translate HTTP <-> facade calls (ADR-0001, CONTRACT-layering): parse the request,
call one facade operation off the event loop, turn the result or the DarkroomError's kind into a response. The rules
and every error sentence live in darkroom_app.services; the local-only checks are `middleware.local_only`.
Depends on: the facade (and `KEEP`), `composition` (to build the app in `make_app`), `operations`-described routes,
the GPU adapter's `Engine` and the preset index's `Library` (AppKeys only). Never imports services or domain rules.

Photos and purchased presets are only read; what writes is the facade's `export` (POST /api/export: new files in the
export folder only, CONTRACT-export X14), the preset library operations under /api/preset-library/ (the index,
import/ and user/ of the library root only, CONTRACT-preset-library K18 / KP1), the photo library under /api/edit,
/api/edit/paste, /api/edit/save-preset, /api/folder/thumbnails and /api/thumbnail (the configured data_dir only,
CONTRACT-photo-library PLP1 / PLP2), and the settings (PUT /api/settings, POST /api/settings/import: the settings file
only, plan-v2 §3). No request names a place to write: import takes uploaded bytes (KP4), settings import takes the
document (never a path), the photo library's paths are photos that are only read, like /api/open.

Over HTTP, export takes no dest_dir (the editor never picks a folder; CLI / MCP only). The presets' .xmp go to the
browser as bytes (POST /api/preset-library/files) and are never written by the server over HTTP.

The facade in use: `Runtime` (composition) holds it and replaces it when the settings change (plan-v2 §3); each
request takes the current one when it starts, so a request already running finishes with the facade it began with.
Tests may put their own facade in `app[FACADE]` before the app starts; that one is then used as is.

The page: the React build (`npm run build` in web/, plan-v2 §2) is the only page. It is looked for, per request, in
`DARKROOM_WEB_DIST` (tests, another build), then `darkroom_app/web_dist/` (an installed wheel: the hatch hook copies
web/dist there), then `<repo>/web/dist` (a source checkout); the first folder holding an index.html wins, so a build
that appears while the server runs is picked up. `/`, `/assets/*`, the files at the root of the build and the page's
own routes (`/settings`) come from there. With no build the page routes answer HTTP 503 with a short bilingual page
that says how to build it (`cd web && npm ci && npm run build`); the API works the same either way.

Status mapping (contract L7): DarkroomError kind invalid -> 400, not_found -> 404, conflict -> 409, unavailable -> 503;
the body is {"error": <the service's sentence>}. Facade calls run in a worker thread (asyncio.to_thread) so a slow
render or export never blocks the event loop, and the GPU work itself then hops onto the Engine's own thread.

Other contract codes: B2 = bound to 127.0.0.1; B3 / B4 / B5 / B8 = the presets, open, preview and folder routes;
XP16 / KP4 / PLP2 / SI11 / E17 = request fields refused over HTTP (folders to write into, local paths to import,
paid operations); PLP8 = query-string numbers are passed through for the service to judge; PLP12 = no HEAD on
path-reading GETs; S8 = the X-Edit header of a thumbnail; S15 / S19 = number parsing and page caching; C20 = no
"geometry" in a body means the saved one; E22 = start-up capability warm-up.
"""
import asyncio
import functools
import json
import os
from urllib.parse import quote

from aiohttp import web

from ..gpu import engine as engine_mod
from ...composition import Runtime, warm_capabilities
from ...domain.errors import DarkroomError
from ...domain.messages import OPEN_ERROR  # noqa: F401  (re-exported: verbatim constant, CONTRACT-heic)
from ...facade import KEEP, Facade   # KEEP: a body without "geometry" = the photo's saved geometry (C20)
from ..persist.preset_index import Library
from .middleware import (CONTENT_TYPE_REFUSED, DARKROOM_HEADER_REFUSED, FETCH_SITE_REFUSED,  # noqa: F401
                         HOST_REFUSED, ORIGIN_REFUSED, PATH_READING_GETS, local_only)

HOST = "127.0.0.1"          # only ever bound to the local machine (B2)
DEFAULT_PORT = 8765
READY_LINE = "darkroom 已啟動：http://127.0.0.1:{port}/"
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # darkroom_app/
PACKAGED_WEB_DIST = os.path.join(APP_DIR, "web_dist")             # an installed wheel (desktop/scripts/hatch_build.py)
WEB_DIST = os.path.join(os.path.dirname(APP_DIR), "web", "dist")   # a source checkout: the React build (plan-v2 §2)
ENV_WEB_DIST = "DARKROOM_WEB_DIST"     # another build folder; when set it is the only place looked at
NO_BUILD_STATUS = 503                  # the page is not built yet: "unavailable", like the API's 503

LIBRARY = web.AppKey("library", Library)
ENGINE = web.AppKey("engine", engine_mod.Engine)
FACADE = web.AppKey("facade", Facade)
RUNTIME = web.AppKey("runtime", Runtime)

STATUS = {"invalid": 400, "not_found": 404, "conflict": 409, "unavailable": 503}
DEST_DIR_REFUSED = "dest_dir is not accepted over HTTP (use the CLI or MCP)"           # verbatim (XP16), 400
PATHS_REFUSED = "paths is not accepted over HTTP (upload the files)"                   # verbatim (KP4), 400
DATA_DIR_REFUSED = "data_dir is not accepted over HTTP (it is configured)"             # verbatim (PLP2), 400
SEMANTIC_BUILD_REFUSED = "semantic build is not accepted over HTTP (use the CLI or MCP)"   # verbatim (SI11), 400
PRESET_EXPORT_REFUSED = ("preset export to a folder is not accepted over HTTP (use the CLI or MCP; the page "
                         "downloads the files)")                                 # verbatim (S2 E17), 400
SETTINGS_PATH_REFUSED = "path is not accepted over HTTP (send the document)"   # plan-v2 §3: import takes the document
SETTINGS_DEST_REFUSED = "dest is not accepted over HTTP (the page downloads the document)"   # plan-v2 §3
_ROOT_FILE_EXT = (".svg", ".png", ".ico", ".webmanifest", ".txt", ".json", ".webp", ".jpg")


def _lenient_int(text):
    """A query-string number -> int when it is all decimal digits, else the raw string (the service says why; PLP8).

    isdecimal, not isdigit (CONTRACT-s1-experience S15): '²' and '①' are digits int() refuses."""
    return int(text) if text.isdecimal() else text


async def _facade(request):
    """The facade for this request: the Runtime's current one, unless a test replaced app[FACADE] (then that one).

    When another process (the CLI, the MCP server) changed the settings file, the Runtime rebuilds first; that can
    take seconds (presets parsed again), so it runs off the event loop. The usual case is one stat on the loop."""
    app = request.app
    given = app[FACADE]
    runtime = app.get(RUNTIME)
    if runtime is not None and given is runtime.first:
        if runtime.stale():
            return await asyncio.to_thread(runtime.current)
        return runtime.facade
    return given


def _error(e):
    """A DarkroomError as an HTTP response: status from its kind, the sentence unchanged (L7)."""
    return web.json_response({"error": e.message}, status=STATUS[e.kind])


def _refused(sentence):
    """HTTP 400 for a request field the HTTP interface never accepts (see the *_REFUSED constants)."""
    return web.json_response({"error": sentence}, status=400)


async def _json_body(request):
    """The request body as a JSON object; HTTP 400 when it is not JSON or not an object."""
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text='{"error": "body must be JSON"}', content_type="application/json")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='{"error": "body must be a JSON object"}', content_type="application/json")
    return body


async def _call(request, operation, *args, **kwargs):
    """facade.<operation>(*args, **kwargs) off the event loop; DarkroomError propagates for the handler."""
    fn = getattr(await _facade(request), operation)
    return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))


async def _json(request, operation, *args, **kwargs):
    """The common handler shape: call one facade operation and answer its result as JSON (or the error)."""
    try:
        return web.json_response(await _call(request, operation, *args, **kwargs))
    except DarkroomError as e:
        return _error(e)


# ---------------------------------------------------------------------- the page
NO_BUILD_PAGE = """<!doctype html>
<html lang="zh-Hant-TW">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>darkroom：頁面還沒建置</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.6 system-ui, "Microsoft JhengHei", sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; }
  code, pre { font-family: ui-monospace, Consolas, monospace; }
  pre { padding: .75rem 1rem; border-radius: 6px; background: rgba(127, 127, 127, .15); overflow-x: auto; }
</style>
</head>
<body>
<h1>darkroom：網頁介面還沒建置</h1>
<p>伺服器正常在跑（API 可以用），但找不到前端的建置結果 <code>web/dist/index.html</code>。
在 repo 根目錄執行下面的指令（第一次約 1～3 分鐘，要下載 npm 套件），建好後重新整理這一頁：</p>
<pre>cd web
npm ci
npm run build</pre>
<p>用 <code>tools/start.ps1</code> 啟動時會自動做這一步。</p>
<hr>
<h2 lang="en">The web page has not been built yet</h2>
<p lang="en">The server is running (the API works), but the front-end build <code>web/dist/index.html</code> is missing.
From the repository root run <code>cd web &amp;&amp; npm ci &amp;&amp; npm run build</code>, then reload this page.</p>
</body>
</html>
"""


def _dist():
    """The folder of the React build to serve, or None when there is none (the page routes then answer 503).

    DARKROOM_WEB_DIST, when set, is the only candidate (tests pin a fixed build with it, or a folder without one to
    see the 503 page); otherwise the wheel's darkroom_app/web_dist, then the checkout's web/dist."""
    env = os.environ.get(ENV_WEB_DIST)
    candidates = (env,) if env else (PACKAGED_WEB_DIST, WEB_DIST)
    for dist in candidates:
        if os.path.exists(os.path.join(dist, "index.html")):
            return dist
    return None


def _no_build():
    """HTTP 503 with the page that says how to build web/dist (never cached: the build may appear any moment)."""
    return web.Response(text=NO_BUILD_PAGE, status=NO_BUILD_STATUS, content_type="text/html",
                        headers={"Cache-Control": "no-store"})


def _page(dist):
    """The build's index.html; no-store so a rebuilt page (new bundle names) is picked up on the next load (S19)."""
    return web.FileResponse(os.path.join(dist, "index.html"), headers={"Cache-Control": "no-store"})


async def index(request):
    """GET /: the React page (or the 503 "not built yet" page)."""
    dist = _dist()
    return _page(dist) if dist else _no_build()


async def web_assets(request):
    """/assets/{path}: the React build's bundles. Vite puts a content hash in every name, so a name never changes
    meaning and the browser may keep it; a path that leaves assets/ (or a missing build) is 404."""
    dist = _dist()
    if dist is None:
        raise web.HTTPNotFound()
    base = os.path.realpath(os.path.join(dist, "assets"))
    target = os.path.realpath(os.path.join(base, request.match_info["path"]))
    if os.path.commonpath([base, target]) != base or not os.path.exists(target):
        raise web.HTTPNotFound()
    return web.FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})


async def web_page(request):
    """Any other GET outside /api, /static and /assets: a file at the build's root (logo, favicon; revalidated with
    its ETag, S19), else the page itself (the React router decides, e.g. /settings). Without a build: the 503 page
    for page routes, 404 for root files."""
    dist = _dist()
    tail = request.match_info["tail"]
    if tail.lower().split("/")[0] in ("api", "static", "assets"):   # /API/... is never the page
        raise web.HTTPNotFound()
    if "/" not in tail and tail.lower().endswith(_ROOT_FILE_EXT):
        if dist is None:
            raise web.HTTPNotFound()
        target = os.path.realpath(os.path.join(dist, tail))
        if os.path.dirname(target) == os.path.realpath(dist) and os.path.exists(target):
            return web.FileResponse(target, headers={"Cache-Control": "no-cache"})
        raise web.HTTPNotFound()
    return _page(dist) if dist else _no_build()


async def health(request):
    """GET /api/health: {"ok": true} as soon as the server accepts requests (start scripts poll it)."""
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------- presets, photos, previews, export
# Each api_* handler below: read the query / JSON body, pass the values as they are to one facade operation (the
# service validates them), and translate the result. A handler only adds rules that exist because of HTTP itself
# (refusing fields a web page must never send, response headers).
async def api_presets(request):
    """GET /api/presets[?favorites=1]: the whole list (the page pages nothing), rows only (B3)."""
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
    """POST /api/preview: JPEG bytes; X-Render-Ms carries the GPU time so the page can show it. Never cached."""
    body = await _json_body(request)
    try:
        res = await _call(request, "preview", body.get("image_id"), body.get("preset_id"), body.get("strength", 100),
                          body.get("overrides"), None, geometry=body.get("geometry", KEEP),
                          frame=body.get("frame", False))
    except DarkroomError as e:
        return _error(e)
    return web.Response(body=res.jpeg, content_type="image/jpeg",
                        headers={"X-Render-Ms": f"{res.render_ms:.2f}", "Cache-Control": "no-store",
                                 "Access-Control-Expose-Headers": "X-Render-Ms"})


async def api_export(request):
    """POST /api/export: always into the default folder next to each photo (no dest_dir over HTTP)."""
    body = await _json_body(request)
    if "dest_dir" in body:                 # an interface rule (XP16): the editor never picks a folder
        return _refused(DEST_DIR_REFUSED)
    return await _json(request, "export", body.get("items"), body.get("format"), body.get("quality"), None,
                       bit_depth=body.get("bit_depth"), max_kb=body.get("max_kb"), resize=body.get("resize"),
                       metadata=body.get("metadata"), remove_gps=body.get("remove_gps"),
                       sharpen=body.get("sharpen"), export_preset=body.get("export_preset"))


async def api_folder(request):
    return await _json(request, "list_folder", request.query.get("image_id", ""))


# ---------------------------------------------------------------------- the preset library (K16)
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
        return _refused(PATHS_REFUSED)
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
    return _refused(SEMANTIC_BUILD_REFUSED)


async def api_semantic_status(request):
    return await _json(request, "semantic_status")


# ---- CONTRACT-photo-library PL6 / PLP2: paths over HTTP are only read; every write lands in the configured data_dir
async def api_edit_get(request):
    return await _json(request, "get_edit", request.query.get("path"))


async def api_edit_set(request):
    body = await _json_body(request)
    if "data_dir" in body:                 # an interface rule (PLP2): the data folder is configured, never sent
        return _refused(DATA_DIR_REFUSED)
    return await _json(request, "set_edit", body.get("path"), body.get("preset_id"), body.get("strength", 100),
                       body.get("overrides"), geometry=body.get("geometry", KEEP))


async def api_edit_clear(request):
    return await _json(request, "clear_edit", request.query.get("path"))


async def api_edit_paste(request):
    body = await _json_body(request)
    if "data_dir" in body:
        return _refused(DATA_DIR_REFUSED)
    return await _json(request, "paste_edit", body.get("targets"), body.get("source"), body.get("edit"),
                       with_geometry=body.get("with_geometry", False))


async def api_edit_save_preset(request):
    body = await _json_body(request)
    if "data_dir" in body:
        return _refused(DATA_DIR_REFUSED)
    return await _json(request, "save_edit_as_preset", body.get("path"), body.get("name"), body.get("group"))


async def api_edit_restore(request):   # CONTRACT-s1-experience S4
    body = await _json_body(request)
    if "data_dir" in body:
        return _refused(DATA_DIR_REFUSED)
    return await _json(request, "restore_edit", body.get("path"))


async def api_folder_thumbnails(request):
    q = request.query
    offset = _lenient_int(q["offset"]) if "offset" in q else 0
    limit = _lenient_int(q["limit"]) if "limit" in q else None
    return await _json(request, "folder_thumbnails", q.get("folder"), offset, limit)


def x_edit(summary):
    """S8: encodeURIComponent(JSON.stringify(summary)) byte for byte - encodeURIComponent keeps !'()* as they are."""
    return quote(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), safe="!'()*")


async def api_thumbnail(request):
    try:
        res = await _call(request, "thumbnail", request.query.get("path"))
    except DarkroomError as e:
        return _error(e)
    headers = {"X-Fingerprint": res.fingerprint, "X-Edited": "1" if res.edited else "0", "Cache-Control": "no-store"}
    if res.edit is not None:            # S8: the grid's badge text, percent-encoded JSON (header values are ASCII)
        headers["X-Edit"] = x_edit(res.edit)
    return web.Response(body=res.jpeg, content_type="image/jpeg", headers=headers)


# ---- CONTRACT-s2-export-detect E28: operations 28..33
async def api_export_presets(request):
    return await _json(request, "list_export_presets")


async def api_export_preset_save(request):
    body = await _json_body(request)
    if "data_dir" in body:                 # PLP2: the data folder is configured, never sent
        return _refused(DATA_DIR_REFUSED)
    return await _json(request, "save_export_preset", body.get("name"), body.get("settings"))


async def api_export_preset_delete(request):
    return await _json(request, "delete_export_preset", request.query.get("name"))


async def api_preset_files(request):
    body = await _json_body(request)
    return await _json(request, "preset_files", body.get("preset_ids"))


async def api_preset_export(request):
    """An interface rule (S2 E17): over HTTP the server never writes .xmp into a folder; the page downloads them."""
    return _refused(PRESET_EXPORT_REFUSED)


async def api_capabilities(request):
    return await _json(request, "capabilities", request.query.get("refresh") in ("1", "true"))


# ---- plan-v2 §3: settings and version (operations 34..38)
async def api_settings_get(request):
    return await _json(request, "get_settings")


async def api_settings_set(request):
    """PUT {"values": {key: value}}: all checked, then written and applied (the next request sees the new app)."""
    body = await _json_body(request)
    return await _json(request, "set_settings", body.get("values"))


async def api_settings_export(request):
    """The document to download; the server never writes it to a folder over HTTP."""
    if "dest" in request.query:
        return _refused(SETTINGS_DEST_REFUSED)
    return await _json(request, "export_settings")


async def api_settings_import(request):
    """POST {"document": {format, version, settings}}; a path is never accepted over HTTP."""
    body = await _json_body(request)
    if "path" in body:
        return _refused(SETTINGS_PATH_REFUSED)
    return await _json(request, "import_settings", body.get("document"))


async def api_version(request):
    return await _json(request, "version")


async def _on_cleanup(app):
    """Server shutdown: stop the GPU thread and release the open photos."""
    app[ENGINE].shutdown()


def make_app(preset_dir=None, engine=None, library_dir=None, data_dir=None, detect=None, settings_path=None):
    """preset_dir: the preset folder (None: from the settings, and a settings change may move it);
    library_dir: the preset library root (default dirname(preset_dir); CONTRACT-preset-library KP2);
    data_dir: the photo library's folder (default config.data_dir() on first use; CONTRACT-photo-library PL1);
    detect: capability detectors to use instead of the real ones (CONTRACT-s2-export-detect E22; tests);
    settings_path: () -> the settings file (tests; default DARKROOM_CONFIG -> config.local.json -> platform).

    Returns the aiohttp Application with every route registered (the list mirrors operations.OPERATIONS; a test
    checks each operation has its route). Builds the Engine (imports torch) unless one is given. Request bodies are
    limited to 1 MiB (uploaded presets are small; photos are never uploaded, only named by path)."""
    app = web.Application(client_max_size=1 << 20, middlewares=[local_only])
    app[ENGINE] = engine or engine_mod.Engine()
    runtime = Runtime(preset_dir, engine=app[ENGINE], library_dir=library_dir, data_dir=data_dir, detect=detect,
                      settings_path=settings_path)
    app[RUNTIME] = runtime
    app[FACADE] = runtime.first
    app[LIBRARY] = runtime.first._presets.library
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
    app.router.add_post("/api/edit/restore", api_edit_restore)
    app.router.add_get("/api/folder/thumbnails", api_folder_thumbnails, allow_head=False)
    app.router.add_get("/api/thumbnail", api_thumbnail, allow_head=False)
    app.router.add_get("/api/export-presets", api_export_presets)
    app.router.add_put("/api/export-presets", api_export_preset_save)
    app.router.add_delete("/api/export-presets", api_export_preset_delete)
    app.router.add_post("/api/preset-library/files", api_preset_files)
    app.router.add_post("/api/preset-library/export", api_preset_export)          # E17: always refused
    app.router.add_get("/api/capabilities", api_capabilities, allow_head=False)  # R12: X-Darkroom, no HEAD
    app.router.add_get("/api/settings", api_settings_get, allow_head=False)      # local folders: X-Darkroom, no HEAD
    app.router.add_put("/api/settings", api_settings_set)
    app.router.add_get("/api/settings/export", api_settings_export, allow_head=False)
    app.router.add_post("/api/settings/import", api_settings_import)
    app.router.add_get("/api/version", api_version)
    app.router.add_get("/assets/{path:.+}", web_assets, allow_head=False)       # the React build's bundles
    # last: the React page's own routes; never /api/*, /static/* (the v1 page's old folder) or /assets/* (404)
    app.router.add_get(r"/{tail:(?!api(/|$)|static(/|$)|assets(/|$)).+}", web_page, allow_head=False)
    app.on_cleanup.append(_on_cleanup)
    return app


async def start(preset_dir=None, port=DEFAULT_PORT, engine=None, warm_up=True, library_dir=None, data_dir=None,
                detect=None):
    """Start serving on 127.0.0.1:port (0 = any free port). Returns (runner, actual_port).

    With warm_up the GPU pipeline runs once before the socket opens, so the ready line means "fast from the first
    preview". The caller keeps the runner and calls runner.cleanup() to stop."""
    app = make_app(preset_dir, engine, library_dir, data_dir, detect)
    warm_capabilities(app[FACADE])        # S2 E22: background, never delays the ready line
    if warm_up:
        await asyncio.get_running_loop().run_in_executor(app[ENGINE].executor, app[ENGINE].warm_up)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, port)
    await site.start()
    actual = runner.addresses[0][1]
    return runner, actual
