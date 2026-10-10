"""darkroom App shell: local preview server (aiohttp) plus the three-column editor page.

Run with `python -s -m darkroom_app` (tools/start.ps1 does this with the darkroom Python and opens the browser).
Uses only the public names of the `darkroom` core library.

Package map (docs/architecture/plan-v2.md section 1; dependencies only point inward,
adapters -> facade -> services -> domain -> utils, and `darkroom/` never imports this package):

    adapters/      the outer ring: http/ (aiohttp routes + local-only middleware), cli.py (argparse),
                   mcp_server/ (stdio JSON-RPC), persist/ (every file store), gpu/ (the torch Engine)
    facade.py      the one interface all three entry points call (Facade protocol + DarkroomFacade)
    operations.py  the operation list: order, MCP tool names, input schemas, HTTP routes, CLI words
    composition.py the only place that reads the configuration and wires stores + services into a facade
    config.py      configuration readers (entry points and composition only)
    services/      business logic; receives domain objects and injected stores, never reads config or requests
    domain/        business objects and rules (Adjustment, Geometry checks, Settings, ExportOptions, messages)
    utils/         no business knowledge: the guarded write module, encoders, imaging helpers, GPU check

The remaining top-level modules (server.py, cli.py, engine.py, presets.py, preview.py, ...) are compatibility
shims for pre-v2 import paths; new code must not import them.
"""

# Single source of the product version: pyproject.toml, the Tauri shell, /api/version and `cli --version` read this.
__version__ = "0.1.0"
