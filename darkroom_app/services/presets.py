"""Preset library and slider table operations (CONTRACT-layering L3, L4; CONTRACT-preset-library K9)."""
import copy

from .. import messages as M
from .. import sliders
from ..errors import DarkroomError

from ..presets import ROW_KEYS    # B3 as patched by K9: id, group, name, supported, skipped, favorite


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class PresetService:
    def __init__(self, library):
        self.library = library

    def list_presets(self, query=None, offset=0, limit=None, favorites=False):
        if not _is_int(offset) or offset < 0:
            raise DarkroomError("invalid", M.OFFSET_INVALID)
        if limit is not None and (not _is_int(limit) or not 1 <= limit <= M.LIMIT_MAX):
            raise DarkroomError("invalid", M.LIMIT_INVALID)
        if not isinstance(favorites, bool):
            raise DarkroomError("invalid", M.LIB_FAVORITE_INVALID)
        entries = self.library.entries
        if favorites:
            entries = [e for e in entries if e["favorite"]]
        if query is not None and query != "":
            q = str(query).casefold()
            entries = [e for e in entries if q in e["name"].casefold() or q in e["group"].casefold()]
        total = len(entries)
        end = total if limit is None else offset + limit
        items = [{k: (list(e[k]) if k == "skipped" else e[k]) for k in ROW_KEYS} for e in entries[offset:end]]
        nxt = offset + len(items)
        return {"items": items, "total": total, "next_offset": nxt if nxt < total else None}

    def preset_detail(self, preset_id):
        if not isinstance(preset_id, str) or preset_id not in self.library.by_id:
            raise DarkroomError("not_found", M.UNKNOWN_PRESET.format(pid=preset_id))
        return self.library.detail(preset_id)

    def preset_flags(self):
        return self.library.flags()

    def slider_table(self):
        return {"groups": [list(g) for g in sliders.GROUPS], "sliders": copy.deepcopy(sliders.SLIDERS)}
