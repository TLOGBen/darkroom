"""Adapters: the outermost ring (plan-v2 §1, clean architecture's adapter layer). Every package here is at the same
level and none imports another's internals:

* `http/`        aiohttp routes and the local-only middleware: request -> facade -> HTTP status
* `cli.py`       argparse -> facade -> exit code / --json envelope
* `mcp_server/`  stdio JSON-RPC -> facade -> MCP result
* `persist/`     every file the app keeps (locks, edits, thumbnails, the preset index, export presets, the semantic
                 index, the settings file) - injected into services by `darkroom_app.composition`
* `gpu/`         the torch / CUDA Engine (preview and full-resolution rendering)

The three entry adapters talk to the facade only (never to services or domain rules); persist and gpu are handed to
services by the composition, so services depend on what they are given, not on these modules.
"""
