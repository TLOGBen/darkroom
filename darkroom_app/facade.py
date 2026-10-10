"""The facade every interface calls (ADR-0001, CONTRACT-layering L2; plan-v2 §1).

Layer: facade - the one interface shared by the three entry adapters (HTTP, CLI, MCP). They only translate formats
and call these methods; the rules live in darkroom_app.services. Each DarkroomFacade method is exactly one `return`
forwarding to a service (an AST test checks it), so there is no logic here to drift between entry points. The
`Facade` Protocol lists the operations in the order of `operations.OPERATIONS` (MCP tool order).

Depends on: domain (`KEEP`, re-exported for the entry points). The services are handed in by the composition; this
module imports none of them. Must not be imported by services, domain or persist (they sit below it).

Data flow: an entry adapter turns a request (HTTP JSON, argparse namespace, MCP arguments) into plain Python values
-> calls one facade method -> the service validates them into domain objects and does the work -> returns a plain,
JSON-able dict (or JPEG bytes for preview / thumbnail) -> the adapter formats it. Errors travel as DarkroomError
(domain/errors.py): the adapter maps `kind` to an HTTP status / CLI exit code / MCP isError and shows `message`
unchanged, which is how the three interfaces say exactly the same sentence (contract L7).

Why the methods below carry no docstrings: the layering test requires every DarkroomFacade method to be a single
`return` statement (a docstring would be a second statement). The behaviour of each operation is documented once,
on the `Facade` Protocol, and in detail on the service method it forwards to.

Contract codes used here: L2 = the facade's operations and their order (each one an HTTP route, a CLI subcommand
and an MCP tool); PL6 / PLP6 = the photo library operations 18..24; S4 = restore_edit (operation 25); SI1 = the
semantic index operations 26, 27; E25 = export presets, preset files and capabilities (28..33); plan-v2 section 3 =
settings and version (34..38).
"""
from typing import Protocol, runtime_checkable

from .domain.sentinels import KEEP  # noqa: F401  re-exported: the entry points import KEEP from the facade


@runtime_checkable
class Facade(Protocol):
    """Every operation darkroom offers, in MCP tool order. All of them raise DarkroomError on a refusal
    (kind invalid / not_found / conflict / unavailable); anything else escaping is a bug (CLI exit 1)."""

    # ---- presets (read-only) and photos (CONTRACT-layering L2: operations 1..8)
    def list_presets(self, query=None, offset=0, limit=None, favorites=False):
        """{items: [{id, group, name, supported, skipped, favorite, tags}], total, next_offset}; query matches
        name, group and semantic tags (case-insensitive substring). Read-only."""
        ...

    def preset_detail(self, preset_id):
        """One preset's values at 100%, curves and the settings it cannot apply (level minor / major).
        not_found for an unknown id. Read-only."""
        ...

    def preset_flags(self):
        """{preset id: "major" | "minor"} for presets with skipped settings. Read-only."""
        ...

    def slider_table(self):
        """Every slider (crs key, range, default, step, label); the only keys overrides accept. Read-only."""
        ...

    def open_photo(self, path):
        """Decode a photo onto the GPU -> {image_id, width, height, preview_width, preview_height, ...}.
        invalid / not_found for a bad path or format. Never writes the photo."""
        ...

    def list_folder(self, image_id):
        """Supported photos in the same folder (sorted by name) and the open photo's position. Read-only."""
        ...

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, geometry=KEEP,
                frame=False):
        """Render a downscaled JPEG (bytes + render time). geometry left out = the photo's saved crop, None = no
        crop; frame=True shows the whole straightened frame (crop mode). Writes nothing."""
        ...

    def export(self, items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None,
               metadata=None, remove_gps=None, sharpen=None, export_preset=None):
        """Full-resolution export of each item to a NEW file -> {results: [...], failed}. An item without colour
        keys uses the photo's saved edit (none = the original). Request-level problems are invalid; a single
        photo's failure is reported in its result and the others still export. Side effect: writes new files
        into dest_dir (default <photo folder>/darkroom 匯出), never over an existing file."""
        ...

    # ---- preset library organising (CONTRACT-preset-library K16: operations 9..17; write library.json only)
    def preset_groups(self):
        """The group tree (split at the first " - ") with counts. Read-only."""
        ...

    def rename_preset(self, preset_id, name):
        """Change the display name (1..100 characters). Writes the library index only."""
        ...

    def move_preset(self, preset_id, group):
        """Move a preset to a group (created when missing). Writes the library index only."""
        ...

    def set_favorite(self, preset_id, favorite):
        """Mark / unmark a favorite (favorite must be a real bool). Writes the library index only."""
        ...

    def create_group(self, group):
        """Create an empty group; conflict when it exists. Writes the library index only."""
        ...

    def rename_group(self, group, new_name):
        """Rename a group and its subgroups; conflict when the target exists (never merges). Index only."""
        ...

    def import_presets(self, paths=None, group=None, files=None):
        """Copy .xmp files (paths, or uploaded {name, data_base64}) into the library's import/ folder ->
        {results, failed}; identical content is not imported twice; sources are never touched."""
        ...

    def save_user_preset(self, name, group=None, preset_id=None, strength=100, overrides=None):
        """Save preset x strength + tweaks as a new user preset (a new file in user/, never overwriting)."""
        ...

    def rebuild_library(self):
        """Re-scan the preset folder into the index, keeping names / groups / favorites of files still there
        -> {added, removed, kept}. Writes the library index only."""
        ...

    # ---- photo library (CONTRACT-photo-library PL6 / PLP6: 18..24; S4: 25); writes only under data_dir
    def get_edit(self, path):
        """The saved edit of a photo, found by its content fingerprint -> {edit | None, preset_status, previous}."""
        ...

    def set_edit(self, path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP):
        """Replace the photo's edit (the preset is snapshotted now); geometry left out keeps the saved crop;
        nothing given removes the edit (kept as "previous" for restore_edit)."""
        ...

    def clear_edit(self, path):
        """Remove the photo's edit (the removed one stays restorable)."""
        ...

    def paste_edit(self, targets, source=None, edit=None, *, with_geometry=False):
        """Copy one edit (from a source photo or an edit object) to 1..500 targets -> {results, failed}; colour
        only unless with_geometry."""
        ...

    def folder_thumbnails(self, folder, offset=0, limit=None):
        """The thumbnail grid of a folder; thumbnails are generated in the background into data_dir."""
        ...

    def thumbnail(self, path):
        """One 256 px JPEG thumbnail (cached under data_dir)."""
        ...

    def save_edit_as_preset(self, path, name, group=None):
        """Save a photo's edit as a new user preset (a new file in the library's user/ folder)."""
        ...

    def restore_edit(self, path):
        """Put back the edit removed last; not_found when there is none, conflict when the photo already has
        a different edit (never overwrites it)."""
        ...

    # ---- semantic index (CONTRACT-semantic-index SI1: 26, 27)
    def semantic_build(self, limit=None, dry_run=False, wait_seconds=None):
        """Ask Claude (Message Batches) to tag presets from renders of 4 public calibration photos. Costs money
        and goes online; refused over HTTP; dry_run only estimates. Writes <library root>/semantic.json."""
        ...

    def semantic_status(self):
        """Whether the index can be built and why not, progress, budget, last usage. Offline, read-only."""
        ...

    # ---- export presets, preset files, capabilities (CONTRACT-s2-export-detect E25: 28..33)
    def list_export_presets(self):
        """{presets: [{name, settings}]}. Read-only."""
        ...

    def save_export_preset(self, name, settings):
        """Store named export settings (same name, case-insensitive, is replaced; returns `previous`).
        Writes data_dir/export-presets.json."""
        ...

    def delete_export_preset(self, name):
        """Delete one export preset and return it; not_found when missing. Writes export-presets.json."""
        ...

    def preset_files(self, preset_ids):
        """The .xmp bytes Lightroom can read for 1..500 presets (purchased / imported files unchanged).
        Read-only."""
        ...

    def export_preset_files(self, preset_ids, dest_dir):
        """Write those .xmp files into dest_dir (outside the preset folder and library; never overwriting).
        Refused over HTTP (the browser downloads instead)."""
        ...

    def capabilities(self, refresh=False):
        """{features: {gpu, heic, webp, photo_library, preset_library_writes, semantic_index, onepassword, ...:
        {available, reason}}}; cached per process unless refresh."""
        ...

    # ---- plan-v2 §3: operations 34..38 (settings and version)
    def get_settings(self):
        """{settings, defaults, sources: {key: file | env | default}, config_file}. Read-only."""
        ...

    def set_settings(self, values):
        """Partial update; everything is validated before anything is written (atomic), then applied at once.
        Writes the settings file."""
        ...

    def export_settings(self, dest=None):
        """{format: "darkroom-settings/1", version, settings}; with dest also written to that new file."""
        ...

    def import_settings(self, document=None, path=None):
        """Apply an exported settings document like set_settings; unknown keys / wrong format -> invalid."""
        ...

    def version(self):
        """{version, python, torch, cuda, platform}. Read-only."""
        ...


class DarkroomFacade:
    """The concrete facade: ten services handed in by the composition, one forwarding method per operation."""

    def __init__(self, presets, photos, previews, exports, library, photo_library, semantic, export_presets,
                 capabilities, settings):
        """Each argument is a service object (or the composition's _Unconfigured stand-in); see composition.py."""
        self._presets = presets
        self._photos = photos
        self._previews = previews
        self._exports = exports
        self._library = library
        self._photo_library = photo_library
        self._semantic = semantic
        self._export_presets = export_presets
        self._capabilities = capabilities
        self._settings = settings

    def list_presets(self, query=None, offset=0, limit=None, favorites=False):
        return self._presets.list_presets(query, offset, limit, favorites)

    def preset_detail(self, preset_id):
        return self._presets.preset_detail(preset_id)

    def preset_flags(self):
        return self._presets.preset_flags()

    def slider_table(self):
        return self._presets.slider_table()

    def open_photo(self, path):
        return self._photos.open_photo(path)

    def list_folder(self, image_id):
        return self._photos.list_folder(image_id)

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, geometry=KEEP,
                frame=False):
        return self._previews.preview(image_id, preset_id, strength, overrides, max_pixels, geometry=geometry, frame=frame)

    def export(self, items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None,
               metadata=None, remove_gps=None, sharpen=None, export_preset=None):
        return self._exports.export(items, format, quality, dest_dir, bit_depth=bit_depth, max_kb=max_kb,
                                    resize=resize, metadata=metadata, remove_gps=remove_gps, sharpen=sharpen,
                                    export_preset=export_preset)

    def preset_groups(self):
        return self._library.preset_groups()

    def rename_preset(self, preset_id, name):
        return self._library.rename_preset(preset_id, name)

    def move_preset(self, preset_id, group):
        return self._library.move_preset(preset_id, group)

    def set_favorite(self, preset_id, favorite):
        return self._library.set_favorite(preset_id, favorite)

    def create_group(self, group):
        return self._library.create_group(group)

    def rename_group(self, group, new_name):
        return self._library.rename_group(group, new_name)

    def import_presets(self, paths=None, group=None, files=None):
        return self._library.import_presets(paths, group, files)

    def save_user_preset(self, name, group=None, preset_id=None, strength=100, overrides=None):
        return self._library.save_user_preset(name, group, preset_id, strength, overrides)

    def rebuild_library(self):
        return self._library.rebuild_library()

    # CONTRACT-photo-library PL6 / PLP6: operations 18..24
    def get_edit(self, path):
        return self._photo_library.get_edit(path)

    def set_edit(self, path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP):
        return self._photo_library.set_edit(path, preset_id, strength, overrides, geometry=geometry)

    def clear_edit(self, path):
        return self._photo_library.clear_edit(path)

    def paste_edit(self, targets, source=None, edit=None, *, with_geometry=False):
        return self._photo_library.paste_edit(targets, source, edit, with_geometry=with_geometry)

    def folder_thumbnails(self, folder, offset=0, limit=None):
        return self._photo_library.folder_thumbnails(folder, offset, limit)

    def thumbnail(self, path):
        return self._photo_library.thumbnail(path)

    def save_edit_as_preset(self, path, name, group=None):
        return self._photo_library.save_edit_as_preset(path, name, group)

    # CONTRACT-s1-experience S4: operation 25
    def restore_edit(self, path):
        return self._photo_library.restore_edit(path)

    # CONTRACT-semantic-index SI1: operations 26, 27 (merge patch: restore_edit stays 25, after save_edit_as_preset)
    def semantic_build(self, limit=None, dry_run=False, wait_seconds=None):
        return self._semantic.semantic_build(limit, dry_run, wait_seconds)

    def semantic_status(self):
        return self._semantic.semantic_status()

    # CONTRACT-s2-export-detect E25: operations 28..33
    def list_export_presets(self):
        return self._export_presets.list_export_presets()

    def save_export_preset(self, name, settings):
        return self._export_presets.save_export_preset(name, settings)

    def delete_export_preset(self, name):
        return self._export_presets.delete_export_preset(name)

    def preset_files(self, preset_ids):
        return self._library.preset_files(preset_ids)

    def export_preset_files(self, preset_ids, dest_dir):
        return self._library.export_preset_files(preset_ids, dest_dir)

    def capabilities(self, refresh=False):
        return self._capabilities.capabilities(refresh)

    # plan-v2 §3: operations 34..38
    def get_settings(self):
        return self._settings.get_settings()

    def set_settings(self, values):
        return self._settings.set_settings(values)

    def export_settings(self, dest=None):
        return self._settings.export_settings(dest)

    def import_settings(self, document=None, path=None):
        return self._settings.import_settings(document, path)

    def version(self):
        return self._settings.version()
