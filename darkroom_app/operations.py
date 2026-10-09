"""The registry of facade operations (CONTRACT-layering L2, L10).

Describes only: which HTTP route, CLI subcommand and MCP tool expose each operation, the MCP input schema and
the MCP defaults and annotations. It does not dispatch and does not validate; whether a value is acceptable is decided by the
services (the schemas below are descriptions for the agent, nothing checks arguments against them).
"""

MCP_DEFAULT_LIMIT = 50
MCP_DEFAULT_MAX_PIXELS = 786432
READ_ONLY_ANNOTATIONS = {"readOnlyHint": True, "openWorldHint": False}                          # L10
EXPORT_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,   # XP4 (verbatim)
                      "openWorldHint": False}


def _schema(properties, required=()):
    s = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        s["required"] = list(required)
    return s


_STR = {"type": "string"}

OPERATIONS = {
    "list_presets": {
        "http": ("GET", "/api/presets"),
        "cli": "presets list",
        "mcp": "darkroom_presets_list",
        "description": "List the user's Lightroom presets (id, group, name, supported, skipped), sorted by group "
                       "and name. Filter with query (case-insensitive substring of name or group); page with "
                       "offset / limit; next_offset is null on the last page.",
        "input_schema": _schema({
            "query": {"type": "string", "description": "substring of the preset name or group"},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": MCP_DEFAULT_LIMIT},
        }),
        "mcp_defaults": {"limit": MCP_DEFAULT_LIMIT},
    },
    "preset_detail": {
        "http": ("GET", "/api/presets/{id}"),
        "cli": "presets show",
        "mcp": "darkroom_preset_show",
        "description": "One preset in detail: its slider values at 100%, curves, and the settings darkroom "
                       "cannot apply (level, banner, note).",
        "input_schema": _schema({"preset_id": dict(_STR, description="id from darkroom_presets_list")},
                                ["preset_id"]),
        "mcp_defaults": {},
    },
    "preset_flags": {
        "http": ("GET", "/api/preset_flags"),
        "cli": "presets flags",
        "mcp": "darkroom_preset_flags",
        "description": "Presets with skipped settings: {preset_id: \"major\" | \"minor\"}.",
        "input_schema": _schema({}),
        "mcp_defaults": {},
    },
    "slider_table": {
        "http": ("GET", "/api/sliders"),
        "cli": "sliders",
        "mcp": "darkroom_sliders",
        "description": "The editor's sliders (Lightroom crs keys with range, default and step) and their groups; "
                       "these keys are the only ones accepted in preview overrides.",
        "input_schema": _schema({}),
        "mcp_defaults": {},
    },
    "open_photo": {
        "http": ("POST", "/api/open"),
        "cli": "open",
        "mcp": "darkroom_open_photo",
        "description": "Open a photo (JPEG/PNG/TIFF/HEIC, read-only) for previewing. Returns image_id, the "
                       "photo size and the preview size. The photo is never written.",
        "input_schema": _schema({"path": dict(_STR, description="absolute path of the photo")}, ["path"]),
        "mcp_defaults": {},
    },
    "list_folder": {
        "http": ("GET", "/api/folder"),
        "cli": "folder",
        "mcp": "darkroom_photo_folder",
        "description": "The supported photos in the folder of an opened photo, sorted by file name, and the "
                       "index of the opened one.",
        "input_schema": _schema({"image_id": dict(_STR, description="from darkroom_open_photo")}, ["image_id"]),
        "mcp_defaults": {},
    },
    "preview": {
        "http": ("POST", "/api/preview"),
        "cli": "preview",
        "mcp": "darkroom_preview",
        "description": "Render a JPEG preview of an opened photo: preset (optional) at strength 0..200 percent, "
                       "plus overrides {slider key: difference added after strength}. max_pixels limits the "
                       "returned image size (65536..1500000).",
        "input_schema": _schema({
            "image_id": dict(_STR, description="from darkroom_open_photo"),
            "preset_id": {"type": ["string", "null"], "description": "id from darkroom_presets_list; null = none"},
            "strength": {"type": "number", "minimum": 0, "maximum": 200, "default": 100},
            "overrides": {"type": "object", "additionalProperties": {"type": "number"},
                          "description": "{slider key from darkroom_sliders: difference}"},
            "max_pixels": {"type": "integer", "minimum": 65536, "maximum": 1500000,
                           "default": MCP_DEFAULT_MAX_PIXELS},
        }, ["image_id"]),
        "mcp_defaults": {"max_pixels": MCP_DEFAULT_MAX_PIXELS},
    },
    "export": {
        "http": ("POST", "/api/export"),
        "cli": "export",
        "mcp": "darkroom_export",
        "description": "Export photos at full resolution as new files (JPEG 8-bit, quality 1..100, default 92; or "
                       "TIFF 16-bit), with the sRGB profile, the photo's EXIF and upright pixels. Each item is a "
                       "photo (path, or image_id from darkroom_open_photo) with an optional preset, strength 0..200 "
                       "and overrides, as in darkroom_preview. Files go to '<photo folder>/darkroom 匯出' or dest_dir "
                       "(an existing absolute folder); an existing file is never overwritten (a numbered name is "
                       "used instead) and the photo is never changed. results has one entry per item, in order: "
                       "{ok, source, output} or {ok: false, source, error}; failed counts the failures.",
        "input_schema": _schema({
            "items": {"type": "array", "minItems": 1, "items": {
                "type": "object", "additionalProperties": False, "properties": {
                    "path": dict(_STR, description="absolute path of the photo"),
                    "image_id": dict(_STR, description="from darkroom_open_photo (instead of path)"),
                    "preset_id": {"type": ["string", "null"], "description": "id from darkroom_presets_list"},
                    "strength": {"type": "number", "minimum": 0, "maximum": 200, "default": 100},
                    "overrides": {"type": "object", "additionalProperties": {"type": "number"},
                                  "description": "{slider key from darkroom_sliders: difference}"}}}},
            "format": {"type": "string", "enum": ["jpeg", "tiff"]},
            "quality": {"type": "integer", "minimum": 1, "maximum": 100, "default": 92,
                        "description": "JPEG quality"},
            "dest_dir": dict(_STR, description="existing absolute folder; default '<photo folder>/darkroom 匯出'"),
        }, ["items", "format"]),
        "mcp_defaults": {},
        "mcp_annotations": EXPORT_ANNOTATIONS,
    },
}
