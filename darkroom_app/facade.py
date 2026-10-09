"""The facade every interface calls (ADR-0001, CONTRACT-layering L2).

HTTP handlers, the CLI and the MCP server only translate formats; the rules live in darkroom_app.services.
Each DarkroomFacade method is exactly one `return` forwarding to a service.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Facade(Protocol):
    def list_presets(self, query=None, offset=0, limit=None): ...

    def preset_detail(self, preset_id): ...

    def preset_flags(self): ...

    def slider_table(self): ...

    def open_photo(self, path): ...

    def list_folder(self, image_id): ...

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None): ...


class DarkroomFacade:
    def __init__(self, presets, photos, previews):
        self._presets = presets
        self._photos = photos
        self._previews = previews

    def list_presets(self, query=None, offset=0, limit=None):
        return self._presets.list_presets(query, offset, limit)

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

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None):
        return self._previews.preview(image_id, preset_id, strength, overrides, max_pixels)
