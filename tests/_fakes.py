"""FakeDarkroom: a Facade with canned answers, for controller tests (CONTRACT-layering L13; tests only).

Controllers (HTTP handlers, CLI, MCP tools) are checked against it for format translation only: what they pass
to the facade, how a result is serialized, how each DarkroomError kind and an unexpected exception come out.
"""
from darkroom_app.facade import KEEP
from darkroom_app.services.photo_library import ThumbnailResult
from darkroom_app.services.preview import PreviewResult

JPEG = b"\xff\xd8fake-jpeg\xff\xd9"
FP = "ab" * 32
EDIT = {"schema": "darkroom-edit/1", "fingerprint": FP, "preset": None, "strength": 100, "overrides": {"Exposure2012": 0.5}}


class FakeDarkroom:
    def __init__(self):
        self.calls = []
        self.fail = {}          # operation -> exception to raise

    def _do(self, op, args, result):
        self.calls.append((op, args))
        if op in self.fail:
            raise self.fail[op]
        return result

    def list_presets(self, query=None, offset=0, limit=None, favorites=False):
        items = [{"id": "fake-1", "group": "假群組", "name": "假一", "supported": True, "skipped": [], "favorite": False,
                  "tags": []}]
        return self._do("list_presets", (query, offset, limit, favorites),
                        {"items": items, "total": 1, "next_offset": None})

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

    def preview(self, image_id, preset_id=None, strength=100, overrides=None, max_pixels=None, *, geometry=KEEP,
                frame=False):
        # CONTRACT-s3-crop C20: geometry / frame are recorded only when given (old calls unchanged)
        s3 = {k: v for k, v in (("geometry", geometry), ("frame", frame)) if v is not KEEP and v is not False}
        return self._do("preview", (image_id, preset_id, strength, overrides, max_pixels) + ((s3,) if s3 else ()),
                        PreviewResult(JPEG, 1.23456, 4, 2))

    def export(self, items, format=None, quality=None, dest_dir=None, *, bit_depth=None, max_kb=None, resize=None,
               metadata=None, remove_gps=None, sharpen=None, export_preset=None):
        results = [{"ok": True, "source": "a.jpg", "output": "D:\\out\\a.jpg"},
                   {"ok": False, "source": "b.jpg", "error": "匯出失敗：b.jpg：壞了"}][: len(items or [])]
        # CONTRACT-s2-export-detect E25: the S2 settings are recorded only when one is given (old calls unchanged)
        s2 = {k: v for k, v in (("bit_depth", bit_depth), ("max_kb", max_kb), ("resize", resize),
                                ("metadata", metadata), ("remove_gps", remove_gps), ("sharpen", sharpen),
                                ("export_preset", export_preset)) if v is not None}
        args = (items, format, quality, dest_dir) + ((s2,) if s2 else ())
        return self._do("export", args, {"results": results})

    # CONTRACT-preset-library K16
    def preset_groups(self):
        return self._do("preset_groups", (), {"groups": [], "ungrouped": 0})

    def rename_preset(self, preset_id, name):
        return self._do("rename_preset", (preset_id, name), {"id": preset_id, "name": name})

    def move_preset(self, preset_id, group):
        return self._do("move_preset", (preset_id, group), {"id": preset_id, "group": group})

    def set_favorite(self, preset_id, favorite):
        return self._do("set_favorite", (preset_id, favorite), {"id": preset_id, "favorite": favorite})

    def create_group(self, group):
        return self._do("create_group", (group,), {"group": group})

    def rename_group(self, group, new_name):
        return self._do("rename_group", (group, new_name), {"group": new_name, "presets": 0})

    def import_presets(self, paths=None, group=None, files=None):
        results = [{"ok": True, "source": "a.xmp", "id": "import:a"},
                   {"ok": False, "source": "b.txt", "error": "不是 .xmp 檔：b.txt"}]
        return self._do("import_presets", (paths, group, files), {"results": results})

    def save_user_preset(self, name, group=None, preset_id=None, strength=100, overrides=None):
        return self._do("save_user_preset", (name, group, preset_id, strength, overrides),
                        {"id": "user:x", "name": name, "group": group, "file": "user/x.xmp"})

    def rebuild_library(self):
        return self._do("rebuild_library", (), {"added": 0, "removed": 0, "kept": 0})

    # CONTRACT-photo-library PL6 / PLP6
    def get_edit(self, path):
        return self._do("get_edit", (path,), {"fingerprint": FP, "edit": EDIT, "preset_status": None})

    def set_edit(self, path, preset_id=None, strength=100, overrides=None, *, geometry=KEEP):
        extra = () if geometry is KEEP else ({"geometry": geometry},)       # C20: recorded only when given
        return self._do("set_edit", (path, preset_id, strength, overrides) + extra,
                        {"fingerprint": FP, "edit": EDIT, "preset_status": None})

    def clear_edit(self, path):
        return self._do("clear_edit", (path,), {"fingerprint": FP, "edit": None, "preset_status": None})

    def paste_edit(self, targets, source=None, edit=None, *, with_geometry=False):
        results = [{"ok": True, "target": "a.jpg"},
                   {"ok": False, "target": "b.jpg", "error": "photo not found: b.jpg"}][: len(targets or [])]
        extra = ({"with_geometry": with_geometry},) if with_geometry is not False else ()   # C20: only when given
        return self._do("paste_edit", (targets, source, edit) + extra, {"results": results})

    def folder_thumbnails(self, folder, offset=0, limit=None):
        return self._do("folder_thumbnails", (folder, offset, limit),
                        {"folder": folder, "items": [], "total": 0, "next_offset": None})

    def thumbnail(self, path):
        return self._do("thumbnail", (path,), ThumbnailResult(JPEG, FP, True, 4, 2))

    def save_edit_as_preset(self, path, name, group=None):
        return self._do("save_edit_as_preset", (path, name, group),
                        {"id": "user:x", "name": name, "group": group, "file": "user/x.xmp"})

    # CONTRACT-s1-experience S4
    def restore_edit(self, path):
        return self._do("restore_edit", (path,), {"fingerprint": FP, "edit": EDIT, "preset_status": None, "previous": True})

    # CONTRACT-semantic-index SI1
    def semantic_build(self, limit=None, dry_run=False, wait_seconds=None):
        return self._do("semantic_build", (limit, dry_run, wait_seconds), {"state": "dry_run", "planned": 0})

    def semantic_status(self):
        return self._do("semantic_status", (), {"available": False, "reason": "假原因", "indexed": 0, "total": 1})

    # CONTRACT-s2-export-detect E25: operations 28..33
    def list_export_presets(self):
        return self._do("list_export_presets", (), {"presets": [{"name": "網頁", "settings": {"format": "jpeg"}}]})

    def save_export_preset(self, name, settings):
        return self._do("save_export_preset", (name, settings), {"name": name, "settings": settings, "previous": None})

    def delete_export_preset(self, name):
        return self._do("delete_export_preset", (name,), {"name": name, "settings": {"format": "jpeg"}})

    def preset_files(self, preset_ids):
        files = [{"ok": True, "preset_id": "p1", "file_name": "p1.xmp", "data_base64": "eG1w"},
                 {"ok": False, "preset_id": "nope", "error": "unknown preset nope"}][: len(preset_ids or [])]
        return self._do("preset_files", (preset_ids,), {"files": files})

    def export_preset_files(self, preset_ids, dest_dir):
        results = [{"ok": True, "preset_id": "p1", "output": "D:\\out\\p1.xmp"},
                   {"ok": False, "preset_id": "nope", "error": "unknown preset nope"}][: len(preset_ids or [])]
        return self._do("export_preset_files", (preset_ids, dest_dir), {"results": results})

    def capabilities(self, refresh=False):
        return self._do("capabilities", (refresh,), {"features": {"gpu": {"available": True, "reason": None},
                                                                  "webp": {"available": False, "reason": "假原因"}}})

    # plan-v2 §3: operations 34..38 (settings and version)
    def get_settings(self):
        return self._do("get_settings", (), {"settings": {"language": "zh-TW"}, "defaults": {"language": "zh-TW"},
                                             "sources": {"language": "default"}, "config_file": "C:\cfg.json"})

    def set_settings(self, values):
        return self._do("set_settings", (values,), {"settings": {"language": "en-US"}, "applied": ["language"],
                                                    "checks": {}})

    def export_settings(self, dest=None):
        doc = {"format": "darkroom-settings/1", "version": "0.1.0", "settings": {"language": "en-US"}}
        return self._do("export_settings", (dest,), doc if dest is None else {**doc, "output": dest})

    def import_settings(self, document=None, path=None):
        return self._do("import_settings", (document, path), {"settings": {"language": "en-US"},
                                                              "applied": ["language"], "checks": {}})

    def version(self):
        return self._do("version", (), {"version": "0.1.0", "python": "3.13", "torch": None, "cuda": None,
                                         "platform": "fake"})
