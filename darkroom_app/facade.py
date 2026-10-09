"""The facade every interface calls (ADR-0001, CONTRACT-layering L2).

HTTP handlers, the CLI and the MCP server only translate formats; the rules live in darkroom_app.services.
Each DarkroomFacade method is exactly one `return` forwarding to a service.
"""
from typing import Protocol, runtime_checkable


class _Keep:
    """The default of every `geometry` argument (CONTRACT-s3-crop C13, D4): left out = the photo's saved geometry.
    Lives here, with the signatures every interface shares (an interface may import the facade, never the rules)."""
    __slots__ = ()

    def __repr__(self):
        return "KEEP"

    def __reduce__(self):
        return "KEEP"


KEEP = _Keep()


@runtime_checkable
class Facade(Protocol):
    def list_presets(self, query=None, offset=0, limit=None, favorites=False): ...

    def preset_detail(self, preset_id): ...

    def preset_flags(self): ...

    def slider_table(self): ...

    def open_photo(self, path): ...

    def list_folder(self, image_id): ...

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, geometry=KEEP,
                frame=False): ...

    def export(self, items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None,
               metadata=None, remove_gps=None, sharpen=None, export_preset=None): ...

    def preset_groups(self): ...

    def rename_preset(self, preset_id, name): ...

    def move_preset(self, preset_id, group): ...

    def set_favorite(self, preset_id, favorite): ...

    def create_group(self, group): ...

    def rename_group(self, group, new_name): ...

    def import_presets(self, paths=None, group=None, files=None): ...

    def save_user_preset(self, name, group=None, preset_id=None, strength=100, overrides=None): ...

    def rebuild_library(self): ...

    def get_edit(self, path): ...

    def set_edit(self, path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP): ...

    def clear_edit(self, path): ...

    def paste_edit(self, targets, source=None, edit=None, *, with_geometry=False): ...

    def folder_thumbnails(self, folder, offset=0, limit=None): ...

    def thumbnail(self, path): ...

    def save_edit_as_preset(self, path, name, group=None): ...

    def restore_edit(self, path): ...

    def semantic_build(self, limit=None, dry_run=False, wait_seconds=None): ...

    def semantic_status(self): ...

    def list_export_presets(self): ...

    def save_export_preset(self, name, settings): ...

    def delete_export_preset(self, name): ...

    def preset_files(self, preset_ids): ...

    def export_preset_files(self, preset_ids, dest_dir): ...

    def capabilities(self, refresh=False): ...


class DarkroomFacade:
    def __init__(self, presets, photos, previews, exports, library, photo_library, semantic, export_presets,
                 capabilities):
        self._presets = presets
        self._photos = photos
        self._previews = previews
        self._exports = exports
        self._library = library
        self._photo_library = photo_library
        self._semantic = semantic
        self._export_presets = export_presets
        self._capabilities = capabilities

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
