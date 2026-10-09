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


def _writes(idempotent):
    """CONTRACT-preset-library K16: the organising tools write the library (never a photo or a purchased preset)."""
    return {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": idempotent, "openWorldHint": False}


def _edits():
    """CONTRACT-photo-library PL6: set / clear / paste replace a photo's edit (idempotent, destructive to the old edit)."""
    return {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}


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
        "description": "List the user's Lightroom presets (id, group, name, supported, skipped, favorite), sorted "
                       "by group and name. Filter with query (case-insensitive substring of name or group) and "
                       "favorites (only the favorites); page with offset / limit; next_offset is null on the last page.",
        "input_schema": _schema({
            "query": {"type": "string", "description": "substring of the preset name or group"},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": MCP_DEFAULT_LIMIT},
            "favorites": {"type": "boolean", "default": False, "description": "only the favorite presets"},
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
    # ---- CONTRACT-preset-library K16: operations 9..17, in this order
    "preset_groups": {
        "http": ("GET", "/api/preset-library/groups"),
        "cli": "presets groups",
        "mcp": "darkroom_preset_groups",
        "description": "The preset group tree: top-level groups with their counts and sub-groups (only the first "
                       "' - ' in a group splits it), plus the number of presets without a group.",
        "input_schema": _schema({}),
        "mcp_defaults": {},
    },
    "rename_preset": {
        "http": ("POST", "/api/preset-library/rename"),
        "cli": "presets rename",
        "mcp": "darkroom_preset_rename",
        "description": "Change a preset's display name (1..100 characters) in the library index; the preset file "
                       "is never changed.",
        "input_schema": _schema({"preset_id": dict(_STR, description="id from darkroom_presets_list"),
                                 "name": _STR}, ["preset_id", "name"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(True),
    },
    "move_preset": {
        "http": ("POST", "/api/preset-library/move"),
        "cli": "presets move",
        "mcp": "darkroom_preset_move",
        "description": "Move a preset to a group (levels joined by ' - ', e.g. '電影 - 暖調'; created when missing). "
                       "Only the library index changes.",
        "input_schema": _schema({"preset_id": dict(_STR, description="id from darkroom_presets_list"),
                                 "group": _STR}, ["preset_id", "group"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(True),
    },
    "set_favorite": {
        "http": ("POST", "/api/preset-library/favorite"),
        "cli": "presets favorite",
        "mcp": "darkroom_preset_favorite",
        "description": "Mark (true) or unmark (false) a preset as a favorite.",
        "input_schema": _schema({"preset_id": dict(_STR, description="id from darkroom_presets_list"),
                                 "favorite": {"type": "boolean"}}, ["preset_id", "favorite"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(True),
    },
    "create_group": {
        "http": ("POST", "/api/preset-library/groups/create"),
        "cli": "groups create",
        "mcp": "darkroom_group_create",
        "description": "Create an empty group (conflict when it already exists).",
        "input_schema": _schema({"group": _STR}, ["group"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(False),
    },
    "rename_group": {
        "http": ("POST", "/api/preset-library/groups/rename"),
        "cli": "groups rename",
        "mcp": "darkroom_group_rename",
        "description": "Rename a group and every sub-group under it (new_name is the full new path; conflict when "
                       "it already exists - groups are never merged).",
        "input_schema": _schema({"group": _STR, "new_name": _STR}, ["group", "new_name"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(False),
    },
    "import_presets": {
        "http": ("POST", "/api/preset-library/import"),
        "cli": "presets import",
        "mcp": "darkroom_presets_import",
        "description": "Copy Lightroom .xmp presets into the library (the sources are never changed): paths are "
                       "files or folders (their first-level *.xmp), files are uploads {name, data_base64}. A preset "
                       "already in the library (same content) is not copied again. results has one entry per file, "
                       "in order: {ok, source, id} or {ok: false, source, error}; failed counts the failures.",
        "input_schema": _schema({
            "paths": {"type": "array", "items": _STR, "description": "absolute paths of .xmp files or folders"},
            "group": dict(_STR, description="group for every imported preset (default: the one in the file)"),
            "files": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "properties": {"name": _STR, "data_base64": _STR},
                                                 "required": ["name", "data_base64"]}},
        }),
        "mcp_defaults": {},
        "mcp_annotations": _writes(False),
    },
    "save_user_preset": {
        "http": ("POST", "/api/preset-library/save"),
        "cli": "presets save",
        "mcp": "darkroom_preset_save",
        "description": "Save a preset (optional) at strength 0..200 plus overrides, as in darkroom_preview, as a new "
                       "user preset .xmp (never overwrites; group default '自存 preset'). Returns {id, name, group, file}.",
        "input_schema": _schema({
            "name": _STR,
            "group": _STR,
            "preset_id": {"type": ["string", "null"], "description": "id from darkroom_presets_list; null = none"},
            "strength": {"type": "number", "minimum": 0, "maximum": 200, "default": 100},
            "overrides": {"type": "object", "additionalProperties": {"type": "number"},
                          "description": "{slider key from darkroom_sliders: difference}"},
        }, ["name"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(False),
    },
    "rebuild_library": {
        "http": ("POST", "/api/preset-library/rebuild"),
        "cli": "presets rebuild",
        "mcp": "darkroom_presets_rebuild",
        "description": "Rebuild the library index from the preset folders (names, groups and favorites of files "
                       "still there are kept). Returns {added, removed, kept}.",
        "input_schema": _schema({}),
        "mcp_defaults": {},
        "mcp_annotations": _writes(True),
    },
    # ---- CONTRACT-photo-library PL6 / PLP6: operations 18..24, in this order
    "get_edit": {
        "http": ("GET", "/api/edit"),
        "cli": "edit get",
        "mcp": "darkroom_edit_get",
        "description": "The edit darkroom keeps for a photo (by its content fingerprint, in the app's data folder): "
                       "{fingerprint, edit: null | {schema, fingerprint, preset: null | {id, name, group, params "
                       "snapshot}, strength, overrides}, preset_status: null | current | changed | missing, "
                       "previous: whether a cleared edit is kept for darkroom_edit_restore}.",
        "input_schema": _schema({"path": dict(_STR, description="absolute path of the photo")}, ["path"]),
        "mcp_defaults": {},
    },
    "set_edit": {
        "http": ("PUT", "/api/edit"),
        "cli": "edit set",
        "mcp": "darkroom_edit_set",
        "description": "Replace a photo's edit: preset (its parameters are snapshotted now; a later change of the "
                       "preset file never changes this edit), strength 0..200 and overrides as in darkroom_preview. "
                       "No preset and no overrides removes the edit. The photo itself is never written.",
        "input_schema": _schema({
            "path": dict(_STR, description="absolute path of the photo"),
            "preset_id": {"type": ["string", "null"], "description": "id from darkroom_presets_list; null = none"},
            "strength": {"type": "number", "minimum": 0, "maximum": 200, "default": 100},
            "overrides": {"type": "object", "additionalProperties": {"type": "number"},
                          "description": "{slider key from darkroom_sliders: difference}"},
        }, ["path"]),
        "mcp_defaults": {},
        "mcp_annotations": _edits(),
    },
    "clear_edit": {
        "http": ("DELETE", "/api/edit"),
        "cli": "edit clear",
        "mcp": "darkroom_edit_clear",
        "description": "Remove a photo's edit (fine when it has none). The photo itself is never written.",
        "input_schema": _schema({"path": dict(_STR, description="absolute path of the photo")}, ["path"]),
        "mcp_defaults": {},
        "mcp_annotations": _edits(),
    },
    "paste_edit": {
        "http": ("POST", "/api/edit/paste"),
        "cli": "edit paste",
        "mcp": "darkroom_edit_paste",
        "description": "Copy one edit (from the photo `source`, or the `edit` object of darkroom_edit_get) onto "
                       "1..500 target photos, replacing their edits (snapshot, strength and overrides as they are). "
                       "results has one entry per target, in order: {ok, target} or {ok: false, target, error}; "
                       "failed counts the failures.",
        "input_schema": _schema({
            "targets": {"type": "array", "minItems": 1, "maxItems": 500, "items": _STR,
                        "description": "absolute paths of the photos to paste onto"},
            "source": dict(_STR, description="absolute path of the photo whose edit is copied"),
            "edit": {"type": "object", "description": "a darkroom-edit/1 object (instead of source)"},
        }, ["targets"]),
        "mcp_defaults": {},
        "mcp_annotations": _edits(),
    },
    "folder_thumbnails": {
        "http": ("GET", "/api/folder/thumbnails"),
        "cli": "thumbnails",
        "mcp": "darkroom_folder_thumbnails",
        "description": "The supported photos of a folder, sorted by file name, for the thumbnail grid: {folder, "
                       "items: [{name, path, fingerprint, edited, cached}], total, next_offset}; fingerprint and "
                       "edited are null until the photo has been thumbnailed. Thumbnails of the whole folder are "
                       "made in the background. Page with offset / limit.",
        "input_schema": _schema({
            "folder": dict(_STR, description="absolute path of the photo folder"),
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": MCP_DEFAULT_LIMIT},
        }, ["folder"]),
        "mcp_defaults": {"limit": MCP_DEFAULT_LIMIT},
    },
    "thumbnail": {
        "http": ("GET", "/api/thumbnail"),
        "cli": "thumbnail",
        "mcp": "darkroom_thumbnail",
        "description": "A JPEG thumbnail of a photo (long edge 256, upright; colours are approximate), cached in "
                       "the app's data folder, plus {fingerprint, edited, width, height}.",
        "input_schema": _schema({"path": dict(_STR, description="absolute path of the photo")}, ["path"]),
        "mcp_defaults": {},
    },
    "save_edit_as_preset": {
        "http": ("POST", "/api/edit/save-preset"),
        "cli": "edit save-preset",
        "mcp": "darkroom_edit_save_preset",
        "description": "Save a photo's edit (its preset snapshot at its strength plus its overrides) as a new user "
                       "preset .xmp (never overwrites; group default '自存 preset'). Returns {id, name, group, file}.",
        "input_schema": _schema({
            "path": dict(_STR, description="absolute path of the photo"),
            "name": _STR,
            "group": _STR,
        }, ["path", "name"]),
        "mcp_defaults": {},
        "mcp_annotations": _writes(False),
    },
    # ---- CONTRACT-s1-experience S4: operation 25
    "restore_edit": {
        "http": ("POST", "/api/edit/restore"),
        "cli": "edit restore",
        "mcp": "darkroom_edit_restore",
        "description": "Bring back the edit that was kept when this photo's edit was last cleared (edit clear, or "
                       "edit set with nothing chosen): it becomes the photo's edit again; the kept copy stays, so this "
                       "can be repeated. Returns the same shape as darkroom_edit_get; not_found when nothing was kept.",
        "input_schema": _schema({"path": dict(_STR, description="absolute path of the photo")}, ["path"]),
        "mcp_defaults": {},
        "mcp_annotations": _edits(),
    },
}
