"""The photo library's edit object: schema, validation and the canonical form (CONTRACT-photo-library PL3, PLP8;
CONTRACT-s3-crop C12).

Layer: domain (plan-v2 §1). Pure: no file is read or written here. `adapters/persist/edit_store.py` reads and
writes edit files and asks `edit_problem` whether what it read is an edit; `services/photo_library.py` builds new
edits with `canonical_edit`.

An edit (`darkroom-edit/1`) holds the preset snapshot (id, name, group, Params) taken when it was chosen, the
strength and the overrides (PL3, PL4); a preset changed later never changes an edit already applied. An edit with a
geometry (rotate / flip / straighten / crop, C12) is written as `darkroom-edit/2` with one more key, `geometry`; an
edit without one is still `darkroom-edit/1`, byte for byte.

Why a snapshot: the user's purchased preset files may be replaced or edited later, and a photo they already finished
must not change look by itself. The edit therefore carries the preset's full Params as they were when applied, and
rendering always uses that snapshot (PL5), never the current file.

Contract codes used here: PL3 = the edit file's keys, order and value ranges; PL4 = the preset snapshot is taken when
the edit is set; PL5 = preview and export get their base parameters from the snapshot; PLP8 = the fixed sentences
for a malformed edit file; C12 = an edit with a geometry is schema /2 with one extra key; C14 = an edit with only a
geometry is "colourless" (pasting it needs with_geometry).
"""
from darkroom import Geometry, Params

from . import messages as M
from .adjustment import validate_overrides, validate_strength
from ..utils.text import one_line

EDIT_SCHEMA = "darkroom-edit/1"                          # verbatim (PL3)
EDIT_SCHEMA_V2 = "darkroom-edit/2"                       # verbatim (CONTRACT-s3-crop C12): an edit with a geometry
EDIT_KEYS = ("schema", "fingerprint", "preset", "strength", "overrides")      # verbatim order (PL3)
EDIT_KEYS_V2 = EDIT_KEYS + ("geometry",)                 # verbatim order (C12)
PRESET_KEYS = ("id", "name", "group", "params")


def _norm_strength(strength):
    # Stored as an int when whole so that an edit written before and after v2 is byte-identical (tests compare
    # files byte for byte).
    """100.0 -> 100, 80.5 stays 80.5: the stored strength is an int when it is whole (PL3 byte-for-byte)."""
    v = float(strength)
    return int(v) if v.is_integer() else v


def edit_problem(obj):
    """None when obj is a well-formed darkroom-edit/1 or /2 object, else the first reason (PLP8 constants; C12)."""
    if not isinstance(obj, dict):
        return M.PL_EDIT_NOT_OBJECT
    v2 = obj.get("schema") == EDIT_SCHEMA_V2
    if set(obj) != set(EDIT_KEYS_V2 if v2 else EDIT_KEYS):
        return M.PL_EDIT_KEYS_V2 if v2 else M.PL_EDIT_KEYS
    if not v2 and obj["schema"] != EDIT_SCHEMA:
        return M.PL_EDIT_SCHEMA.format(schema=obj["schema"])
    if v2:
        try:
            Geometry.from_dict(obj["geometry"])
        except ValueError as e:
            return str(e)
    p = obj["preset"]
    if p is not None:
        if not isinstance(p, dict) or set(p) != set(PRESET_KEYS) or not all(isinstance(p[k], str)
                                                                             for k in ("id", "name", "group")):
            return M.PL_EDIT_PRESET
        try:
            Params.from_dict(p["params"])
        except (ValueError, TypeError, AttributeError) as e:
            return M.PL_EDIT_PARAMS.format(reason=one_line(e))
    try:
        validate_strength(obj["strength"])
        validate_overrides(obj["overrides"])
    except ValueError as e:
        return str(e)
    return None


def canonical_edit(fp, preset, strength, overrides, geometry=None):
    """The edit object with the constant keys in order (PL3): darkroom-edit/1 without a geometry (byte for byte as
    before), darkroom-edit/2 with the normalised geometry as its last key (CONTRACT-s3-crop C12)."""
    p = None if preset is None else {k: preset[k] for k in PRESET_KEYS}
    g = Geometry.from_dict(geometry)
    g = None if g is None else g.to_dict()
    edit = {"schema": EDIT_SCHEMA if g is None else EDIT_SCHEMA_V2, "fingerprint": fp, "preset": p,
            "strength": _norm_strength(strength), "overrides": validate_overrides(overrides)}
    if g is not None:
        edit["geometry"] = g
    return edit


def edit_geometry(edit):
    """The geometry object of an edit (None: no edit, a darkroom-edit/1 edit, or no geometry)."""
    return None if edit is None else edit.get("geometry")


def colourless(edit):
    """An edit that changes no colour: no preset and no override (C14)."""
    return edit["preset"] is None and not edit["overrides"]


def edit_base_params(edit):
    """The Params of the edit's preset snapshot (None when the edit has no preset): the snapshot always wins (PL5)."""
    return None if edit["preset"] is None else Params.from_dict(edit["preset"]["params"])
