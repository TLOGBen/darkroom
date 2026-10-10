"""Local-only request checks for the HTTP adapter (CONTRACT-export XP16, app shell R10 / R11, photo library PLP11).

Layer: adapters/http. Pure HTTP: imports aiohttp only. Every request first passes `local_only`, in this order:

1. Host must be 127.0.0.1:{port} or localhost:{port} - DNS rebinding cannot reach the API (421).
2. Sec-Fetch-Site cross-site / same-site is refused - an <img src> or <script src> from another page (403).
3. An Origin header must be the page's own origin (403).
4. A POST / PUT body must be declared application/json - a plain <form> cannot post here (415).
5. The GETs that read a local path (or answer with local paths) must carry X-Darkroom: 1 - an img / script tag
   cannot add a header, and a cross-site fetch that adds one needs a CORS preflight this server never answers (403).

Caching of the page (S19: an updated page is never stale) is set by the page handlers in server.py: index.html is
no-store, the hashed /assets/* bundles are immutable, the build's root files are revalidated (no-cache + ETag).
The sentences are verbatim constants pinned by tests; the server binds 127.0.0.1 only (B2).

Why all this for a server that only listens on 127.0.0.1: any web page the user visits runs in the same browser and
can send requests to 127.0.0.1. Binding locally stops other machines, but not a malicious page; these checks make
sure only darkroom's own page (served from this very host:port) can use the API or read local paths.

Contract codes: XP16 = the Host / Origin / Content-Type checks against cross-site requests and DNS rebinding;
R10 / R11 = the app-shell patches that introduced them; PLP11 / PLP12 = Sec-Fetch-Site, the X-Darkroom header on
path-reading GETs, and no HEAD on those routes; PLP2 = PUT bodies are JSON too; S2 E28 / R12 = capabilities is a
path-reading GET; B2 = bound to 127.0.0.1 only.
"""
from aiohttp import web

HOST_REFUSED = "request refused: Host must be 127.0.0.1:{port} or localhost:{port}"   # verbatim (XP16), 421
ORIGIN_REFUSED = "request refused: cross-site Origin {origin}"                        # verbatim (XP16), 403
CONTENT_TYPE_REFUSED = "request refused: POST body must be application/json"          # verbatim (XP16), 415
FETCH_SITE_REFUSED = "request refused: cross-site request (Sec-Fetch-Site {value})"     # verbatim (PLP11), 403
DARKROOM_HEADER_REFUSED = "request refused: X-Darkroom header required"                # verbatim (PLP11), 403
PATH_READING_GETS = frozenset(("/api/folder", "/api/edit", "/api/folder/thumbnails", "/api/thumbnail",
                               "/api/capabilities",           # PLP11; + /api/capabilities (S2 E28, R12)
                               "/api/settings", "/api/settings/export"))   # + v2: the settings name local folders


@web.middleware
async def local_only(request, handler):
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
