"""HTTP adapter (plan-v2 §1): aiohttp routes (`server.py`) and the local-only checks (`middleware.py`).

Request -> facade -> HTTP status; no rules, no sentences of its own except the HTTP-only refusals.

Dependency rule: may import the facade, composition (to build the app), the GPU and persist adapters only for the
aiohttp AppKeys, and domain errors / messages for translation; never services or domain rules (test_layering).
"""
