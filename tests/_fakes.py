"""FakeDarkroom: a Facade with canned answers, for controller tests (CONTRACT-layering L13; tests only).

Controllers (HTTP handlers, CLI, MCP tools) are checked against it for format translation only: what they pass
to the facade, how a result is serialized, how each DarkroomError kind and an unexpected exception come out.
"""
from darkroom_app.services.preview import PreviewResult

JPEG = b"\xff\xd8fake-jpeg\xff\xd9"


class FakeDarkroom:
    def __init__(self):
        self.calls = []
        self.fail = {}          # operation -> exception to raise

    def _do(self, op, args, result):
        self.calls.append((op, args))
        if op in self.fail:
            raise self.fail[op]
        return result

    def list_presets(self, query=None, offset=0, limit=None):
        items = [{"id": "fake-1", "group": "假群組", "name": "假一", "supported": True, "skipped": []}]
        return self._do("list_presets", (query, offset, limit), {"items": items, "total": 1, "next_offset": None})

    def preset_detail(self, preset_id):
        return self._do("preset_detail", (preset_id,), {"id": preset_id, "fake": True})

    def preset_flags(self):
        return self._do("preset_flags", (), {"fake-1": "major"})

    def slider_table(self):
        return self._do("slider_table", (), {"groups": [["basic", "基本"]], "sliders": []})

    def open_photo(self, path):
        return self._do("open_photo", (path,), {"image_id": "fake-image", "width": 4, "height": 2,
                                                "preview_width": 4, "preview_height": 2})

    def list_folder(self, image_id):
        return self._do("list_folder", (image_id,), {"folder": "F", "files": [], "index": -1})

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None):
        return self._do("preview", (image_id, preset_id, strength, overrides, max_pixels),
                        PreviewResult(JPEG, 1.23456, 4, 2))

    def export(self, items, format, quality=None, dest_dir=None):
        results = [{"ok": True, "source": "a.jpg", "output": "D:\\out\\a.jpg"},
                   {"ok": False, "source": "b.jpg", "error": "匯出失敗：b.jpg：壞了"}][: len(items or [])]
        return self._do("export", (items, format, quality, dest_dir), {"results": results})
