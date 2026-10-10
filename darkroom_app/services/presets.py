"""Preset library and slider table operations (CONTRACT-layering L3, L4; CONTRACT-preset-library K9).

Layer: services. Reads the preset library view (`Library`, handed in by the composition) and answers list / detail /
flags / sliders; the row and detail shapes are rules in domain/presets.py. Never imports the facade, adapters or
config.

Data flow: the Library (adapters/persist/preset_index.py) holds the parsed presets and the index in memory; this
service filters / pages its rows and adds the semantic tags of each preset (looked up by the preset file's content
hash in semantic.json). Nothing here writes.

Contract codes: L3 = argument checks in a fixed order with fixed sentences; L4 = list_presets returns
{items, total, next_offset} with paging; B3 / K9 = the row's columns (incl. favorite); SI10 = a query also matches
the semantic tags and descriptions.
"""
import copy

from ..domain import messages as M
from ..domain import sliders
from ..domain.errors import DarkroomError
from ..domain.presets import ROW_KEYS, SEMANTIC_SEARCH_FIELDS, semantic_tags   # B3, K9, + tags (SI10)
from ..utils.text import is_int as _is_int


def _haystack(e, entry):
    """SI10: name, group and the semantic entry's tags_zh, tags_en, good_for, look_zh, look_en (casefold)."""
    parts = [e["name"], e["group"]]
    if entry is not None:
        for k in SEMANTIC_SEARCH_FIELDS:
            v = entry[k]
            parts += v if isinstance(v, list) else [v]
    return "\n".join(parts).casefold()


class PresetService:
    """Read-only questions about the preset catalogue (operations list_presets .. slider_table)."""

    def __init__(self, library):
        """library: the preset library view (adapters/persist/preset_index.Library)."""
        self.library = library

    def list_presets(self, query=None, offset=0, limit=None, favorites=False):
        """Rows sorted by group / name, filtered by favorites and query, then paged.

        offset >= 0, limit 1..200 or None (all), favorites a real bool; otherwise invalid with the L3 sentences.
        next_offset is None on the last page. Read-only."""
        if not _is_int(offset) or offset < 0:
            raise DarkroomError("invalid", M.OFFSET_INVALID)
        if limit is not None and (not _is_int(limit) or not 1 <= limit <= M.LIMIT_MAX):
            raise DarkroomError("invalid", M.LIMIT_INVALID)
        if not isinstance(favorites, bool):
            raise DarkroomError("invalid", M.LIB_FAVORITE_INVALID)
        lib = self.library
        entries = lib.entries
        if favorites:
            entries = [e for e in entries if e["favorite"]]
        semantic = lib.semantic()["entries"]
        files = lib.files()

        def entry_of(e):
            f = files.get(e["id"])
            return None if f is None else semantic.get(f.sha256)
        if query is not None and query != "":
            q = str(query).casefold()
            entries = [e for e in entries if q in _haystack(e, entry_of(e))]
        total = len(entries)
        end = total if limit is None else offset + limit
        items = [{**{k: (list(e[k]) if k == "skipped" else e[k]) for k in ROW_KEYS if k != "tags"},
                  "tags": semantic_tags(entry_of(e))} for e in entries[offset:end]]
        nxt = offset + len(items)
        return {"items": items, "total": total, "next_offset": nxt if nxt < total else None}

    def preset_detail(self, preset_id):
        """Values at 100%, curves and skipped settings of one preset; not_found for an unknown id."""
        if not isinstance(preset_id, str) or preset_id not in self.library.by_id:
            raise DarkroomError("not_found", M.UNKNOWN_PRESET.format(pid=preset_id))
        return self.library.detail(preset_id)

    def preset_flags(self):
        """{preset id: "major" | "minor"} for presets with settings that cannot be applied."""
        return self.library.flags()

    def slider_table(self):
        """{groups: [[key, label]], sliders: [...]}; a deep copy so a caller cannot change the shared table."""
        return {"groups": [list(g) for g in sliders.GROUPS], "sliders": copy.deepcopy(sliders.SLIDERS)}
