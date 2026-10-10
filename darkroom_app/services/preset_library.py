"""Organising the preset library: groups, names, favorites, import, user presets, rebuild (CONTRACT-preset-library).

Layer: services. Every rule of these operations lives here (names, groups, dedup, the user preset's bytes, which
ids exist); every file operation is the `PresetLibraryStore` the composition hands in
(adapters/persist/preset_index.py: the cross-process lock, the atomic library.json write, the `.bad-{t}` copy, new
xmp files that never overwrite). Depends on domain (presets rules, adjustment, errors, messages) and utils; never
imports the facade, adapters' entry points, config or the write module.

An organising operation: arguments checked -> the cross-process lock (`<root>/library.json.lock`; waiting longer
than LOCK_WAIT_S -> conflict) -> the index on disk read again and merged with the three folders (K5 rule) -> the
change -> library.json replaced atomically (PermissionError retried with the KP21 budget) -> the in-process view
adopted. An unreadable index is first kept as `library.json.bad-{unix seconds}`. Purchased xmp, imported and user
files already there are never rewritten, renamed or deleted. `SafeWriteRefused` is never caught (G8).

Why an index instead of renaming files: the purchased .xmp files are the user's property and their content hash is
how the semantic index and Lightroom recognise them. Names, groups and favorites therefore live only in
library.json, and organising never changes a byte of a preset file.

Contract codes used here (CONTRACT-preset-library unless noted): K5 = rebuild merges folders and index, keeping
names / groups / favorites; K6 = display names 1..100 characters; K7 = groups "Top - Child"; K9 = favorites must be
real booleans; K11 = import copies .xmp files into import/, skipping identical content; K12 = user presets go to
user/ in the group "自存 preset" and are built with the preview's own parameter function; K13 = the exact user
preset XML; K14 = safe file names on Windows; K15 / KP21 = the cross-process lock and the retry budget for a busy
library.json; KP1 = every write goes through the store (and the guarded write module); KP4 / KP5 = uploads and
partial import failures; KP6 = which values are never written into a user preset (absolute white balance) and
XML-invalid characters; KP9 = check order (the id first) and return shapes; KP22 = writes are unavailable when the
library lies in a photo folder. CONTRACT-s2-export-detect: E16 / E17 / D6 = handing presets to Lightroom (bytes,
or files in a folder; user presets get the attributes Lightroom needs); E20 / IP3 = detecting a library inside a
photo folder. CONTRACT-s3-crop C15 = a saved preset never carries a crop.
"""
import base64
import binascii
import hashlib
import os
import secrets
import threading
import time
from decimal import Decimal
from xml.sax.saxutils import escape

from darkroom import UnsupportedPresetError, load_preset

from ..domain import messages as M
from ..domain.adjustment import Adjustment
from ..domain.errors import DarkroomError
from ..domain.formats import PHOTO_EXT
from ..domain.presets import (GROUP_SEP, IMPORT_PREFIX, USER_PREFIX, clean_text, meta_of, normalize_group,
                              split_group)
from ..utils.text import one_line as _one_line

NAME_MAX = 100                      # K6
USER_GROUP = "自存 preset"           # verbatim (K12)
FILE_MAX = 80                       # K14
N_MAX = 9999                        # numbered names {stem} (n).xmp, n = 2..N_MAX
_UNSAFE = set('<>:"/\\|?*') | {chr(c) for c in range(32)}       # verbatim (K14)
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_NO_WRITE = {"Temperature", "Tint", "WhiteBalance"}            # KP6 (P4)
# CONTRACT-s3-crop C15: a saved preset is colour only - none of C10's crop attributes is ever written
CROP_KEYS = frozenset(["HasCrop", "CropTop", "CropLeft", "CropBottom", "CropRight", "CropAngle", "CropConstrainToWarp",
                       "CropConstrainAspectRatio", "CropWidth", "CropHeight", "CropUnit"])
XMP_HEAD = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Normal" '
            'crs:ProcessVersion="15.4" crs:HasSettings="True"')   # verbatim (K13)
_ATTR = {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}
_TEXT = {"\r": "&#13;"}
CURVE_ORDER = ("ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue")
GRADIENT_KEYS = ("ZeroX", "ZeroY", "FullX", "FullY")
CIRCULAR_KEYS = ("Top", "Left", "Bottom", "Right", "Angle", "Midpoint", "Roundness", "Feather")
PRESET_IDS_MAX = 500                # verbatim (S2 E16)
LR_ANCHOR = 'crs:PresetType="Normal"'
LR_ATTRS = (("UUID", None), ("SupportsAmount2", "True"), ("SupportsAmount", "True"), ("SupportsColor", "True"),
            ("SupportsMonochrome", "True"), ("SupportsHighDynamicRange", "True"),
            ("SupportsNormalDynamicRange", "True"), ("SupportsSceneReferred", "True"),
            ("SupportsOutputReferred", "True"), ("RequiresRGBTables", "False"), ("Version", "15.4"))   # verbatim (E16)


# ---------------------------------------------------------------------- pure helpers
def safe_stem(name):
    """K14: a file stem that stays one name inside its folder on Windows."""
    s = "".join("_" if c in _UNSAFE else c for c in name)
    s = s.rstrip(". ")
    if not s:
        s = "preset"
    if s.split(".")[0].strip().casefold() in _RESERVED:      # "CON .x" is reserved on Windows too
        s = "_" + s
    s = s[:FILE_MAX].rstrip(". ")
    return s or "preset"


def numbered(stem):
    """{stem}, {stem} (2) ... {stem} (N_MAX) (K11, K12)."""
    yield stem
    for n in range(2, N_MAX + 1):
        yield f"{stem} ({n})"


def num_text(v):
    """K13: matches ^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)$ and float(text) == v (never an exponent)."""
    return format(Decimal(repr(float(v))), "f")


def _attr(name, value):
    """` crs:<name>="<value>"` with the value escaped for an XML attribute (quotes and whitespace characters)."""
    return f' crs:{name}="{escape(value, _ATTR)}"'


def _alt(tag, text):
    """A crs:<tag> rdf:Alt element with one x-default entry (how Lightroom stores Name and Group)."""
    return (f"<crs:{tag}><rdf:Alt><rdf:li xml:lang=\"x-default\">{escape(text, _TEXT)}</rdf:li></rdf:Alt>"
            f"</crs:{tag}>")


def _bool(v):
    """Python bool -> the lower-case XML boolean the mask attributes use."""
    return "true" if v else "false"


def xmp_bytes(params, name, group):
    """The user preset file (K13 constant "自存 xmp"): values as crs attributes, curves, masks, Name and Group.

    params: final Params (already at strength, overrides applied); name / group: display texts. Returns UTF-8 bytes
    that darkroom's own parser reads back to the same Params (K13 round trip) and that use Lightroom's attribute
    names, so Lightroom can import the file too (with lightroom_bytes adding what it additionally requires).
    Attributes are sorted, so the same Params always give the same bytes."""
    out = [XMP_HEAD]
    for k in sorted(params.values):
        if k in _NO_WRITE or k in CROP_KEYS:
            continue
        v = params.values[k]
        out.append(_attr(k, ("True" if v else "False") if isinstance(v, bool) else num_text(v)))
    out.append(">")
    out.append(_alt("Name", name))
    out.append(_alt("Group", group))
    for tag in sorted(params.curves, key=lambda t: (CURVE_ORDER.index(t) if t in CURVE_ORDER else 9, t)):
        lis = "".join(f"<rdf:li>{num_text(x)}, {num_text(y)}</rdf:li>" for x, y in params.curves[tag])
        out.append(f"<crs:{tag}><rdf:Seq>{lis}</rdf:Seq></crs:{tag}>")
    if params.masks:
        out.append("<crs:MaskGroupBasedCorrections><rdf:Seq>")
        for m in params.masks:
            out.append('<rdf:li><rdf:Description crs:What="Correction"')
            out.append(_attr("CorrectionAmount", num_text(m.get("amount", 1))))
            out.append(_attr("CorrectionName", str(m.get("name", ""))))
            for k in sorted(m.get("values", {})):
                out.append(_attr(k, num_text(m["values"][k])))
            out.append("><crs:CorrectionMasks><rdf:Seq>")
            for s in m.get("shapes", []):
                out.append("<rdf:li")
                out.append(_attr("What", s["type"]))
                out.append(_attr("MaskInverted", _bool(s.get("inverted", False))))
                out.append(_attr("MaskValue", num_text(s.get("opacity", 1))))
                if s["type"] == "Mask/Gradient":
                    for k in GRADIENT_KEYS:
                        out.append(_attr(k, num_text(s[k])))
                else:
                    for k in CIRCULAR_KEYS:
                        out.append(_attr(k, num_text(s[k])))
                    out.append(_attr("Flipped", _bool(s.get("Flipped", False))))
                out.append("/>")
            out.append("</rdf:Seq></crs:CorrectionMasks></rdf:Description></rdf:li>")
        out.append("</rdf:Seq></crs:MaskGroupBasedCorrections>")
    out.append("</rdf:Description></rdf:RDF></x:xmpmeta>\n")
    return "".join(out).encode("utf-8")


def lightroom_bytes(data):
    """S2 E16 / D6: a user preset with the Lightroom attributes it lacks added right after crs:PresetType="Normal"
    (crs:UUID = the first 32 upper-case hex of the file's SHA-256, so the same content always gets the same UUID);
    every other byte is unchanged. Bytes without the anchor are returned as they are."""
    text = data.decode("utf-8")
    at = text.find(LR_ANCHOR)
    if at < 0:
        return data
    uuid = hashlib.sha256(data).hexdigest()[:32].upper()
    add = "".join(f' crs:{k}="{uuid if v is None else v}"' for k, v in LR_ATTRS if f' crs:{k}="' not in text)
    at += len(LR_ANCHOR)
    return (text[:at] + add + text[at:]).encode("utf-8")


def _skip_levels(home=None, env=None):
    """normcase(realpath) of the levels never judged a photo folder (S2 E20 / D9, IP3): the home folder itself and
    the system temporary folders themselves (TMPDIR, TEMP, TMP); drive roots are skipped by the walk."""
    env = os.environ if env is None else env
    out = set()
    for d in [home if home is not None else os.path.expanduser("~")] + [env.get(k) for k in ("TMPDIR", "TEMP", "TMP")]:
        if isinstance(d, str) and d and os.path.isabs(d):
            out.add(os.path.normcase(os.path.realpath(d)))
    return out


def photo_folder_of(root, home=None, env=None):
    """S2 E20: the first folder, from realpath(root) upwards, whose first level holds a file with a photo extension
    (formats.PHOTO_EXT); None when there is none. Drive roots, the home folder and the temporary folders themselves
    are not judged. Only names are read (os.scandir); no file is opened, nothing is written."""
    skip = _skip_levels(home, env)
    cur = os.path.realpath(root)
    while True:
        parent = os.path.dirname(cur)
        if parent != cur and os.path.normcase(cur) not in skip:
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        try:
                            if os.path.splitext(e.name)[1].lower() in PHOTO_EXT and e.is_file():
                                return cur
                        except OSError:
                            continue
            except OSError:
                pass
        if parent == cur:
            return None
        cur = parent


def _name(name):
    """K6 / KP6: strip, XML-invalid characters removed, 1..100 characters."""
    n = clean_text(name).strip() if isinstance(name, str) else ""
    if not 1 <= len(n) <= NAME_MAX:
        raise DarkroomError("invalid", M.LIB_NAME_LENGTH)
    return n


def _group(group):
    """The normalised group path, or invalid with the K7 sentence."""
    g = normalize_group(group)
    if g is None:
        raise DarkroomError("invalid", M.LIB_GROUP_INVALID.format(group=group))
    return g


def group_exists(index, group):
    """KP9: a preset's full group, the top level of a preset's group, or an explicit group (casefold)."""
    c = group.casefold()
    for e in index["presets"].values():
        g = e["group"].strip()
        if g.casefold() == c or split_group(g)[0].casefold() == c:
            return True
    return any(g.casefold() == c for g in index["groups"])


def _renamed(path, old, new):
    """path with the group `old` (or its sub-path "old - ...") replaced by `new`, else None (casefold)."""
    if path.casefold() == old.casefold():
        return new
    head = path[:len(old)]
    if head.casefold() == old.casefold() and path[len(old):len(old) + len(GROUP_SEP)] == GROUP_SEP:
        return new + path[len(old):]
    return None


def writes_status(root):
    """(available, reason) of the library writes (S2 E20): false when the library root lies in a photo folder.

    A module function (not a method) so the composition can measure it once and share the result between this
    service, the semantic index and the capability report without the three referring to each other."""
    folder = photo_folder_of(root)
    if folder is None:
        return True, None
    return False, M.LIB_IN_PHOTO_FOLDER.format(root=root, photo_folder=folder)


class PresetLibraryService:
    """The organising operations (9..17) plus preset files (E16 / E17) and the save path used by the photo library."""

    def __init__(self, library, store, writes_gate=None, clock=None):
        """library: the preset view (Library); store: PresetLibraryStore; writes_gate: shared Probe of E20; clock:
        () -> unix seconds (tests fix it)."""
        self.library = library
        self.store = store                     # PresetLibraryStore (adapters/persist/preset_index.py)
        self.preset_dir = store.preset_dir     # the purchased preset folder in use (KP1)
        self._tlock = threading.Lock()         # one organising operation at a time in this process
        self.writes_gate = writes_gate         # () -> (available, reason): the capability preset_library_writes (E20)
        self.clock = clock                     # names the library.json.bad-{t} copy

    def writes_status(self):
        """(available, reason) of the library writes (S2 E20), measured now."""
        return writes_status(self.root)

    def _check_writable(self):
        """Raise unavailable with the measured reason when library writes are switched off (E20 / KP22)."""
        ok, reason = self.writes_gate() if self.writes_gate is not None else self.writes_status()
        if not ok:
            raise DarkroomError("unavailable", reason)

    @property
    def root(self):
        """The preset library root folder (library.json, import/, user/)."""
        return self.library.root

    def _create(self, folder, stem, data, unavailable):
        """A new xmp named by the K11 / K12 rule ({stem}, {stem} (2) ... {stem} (N_MAX)) through the store."""
        return self.store.create_numbered(folder, numbered(stem), data, unavailable, f"{stem} 的檔名已用到 ({N_MAX})")

    def _mutate(self, change):
        """Lock -> index on disk merged with the folders -> change(index, files) -> atomic write -> adopt.

        change returns (result, changed); nothing is written when changed is False. Refused before anything when the
        library root lies in a photo folder (S2 E20, KP22)."""
        self._check_writable()
        with self._tlock, self.store.locked():
            try:
                disk, raw, state = self.library.read_index()
            except PermissionError as e:
                raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
            files = self.library.scan()
            index = self.library.merged(disk, files)
            result, changed = change(index, files, disk)
            if changed or state == "bad":
                if state == "bad":
                    self.store.keep_bad(raw, (self.clock or time.time)())
                self.store.write_index(index)
            self.library.adopt(index, files)
            return result

    # ------------------------------------------------------------------ checks under the lock
    @staticmethod
    def _known(index, preset_id):
        """The index entry of preset_id (judged again under the lock: another process may have removed it)."""
        if not isinstance(preset_id, str) or preset_id not in index["presets"]:
            raise DarkroomError("not_found", M.UNKNOWN_PRESET.format(pid=preset_id))
        return index["presets"][preset_id]

    def _precheck(self, preset_id):
        """KP9 order: the id is judged before the other arguments (on the view; again under the lock)."""
        if not isinstance(preset_id, str) or preset_id not in self.library.by_id:
            raise DarkroomError("not_found", M.UNKNOWN_PRESET.format(pid=preset_id))

    def _row(self, pid):
        """The preset's row as list_presets shows it (returned by rename / move / favorite, KP9)."""
        return self.library.row(pid)

    # ------------------------------------------------------------------ operations
    # Every writing operation below follows the same pattern: check the arguments, then pass a `change(index,
    # files, disk)` function to _mutate, which runs it under the lock on the freshly merged index and writes the
    # result. change returns (result, changed); `disk is None` (no library.json yet) forces a first write.
    def preset_groups(self):
        """The group tree (K10). Read-only."""
        return self.library.group_tree()

    def rename_preset(self, preset_id, name):
        """Set the display name -> the preset's row. not_found / invalid / unavailable / conflict (lock)."""
        self._precheck(preset_id)
        n = _name(name)

        def change(index, files, disk):
            e = self._known(index, preset_id)
            changed = e["name"] != n
            e["name"] = n
            return None, changed or disk is None
        self._mutate(change)
        return self._row(preset_id)

    def move_preset(self, preset_id, group):
        """Set the preset's group (any valid path; it need not exist yet) -> the preset's row."""
        self._precheck(preset_id)
        g = _group(group)

        def change(index, files, disk):
            e = self._known(index, preset_id)
            changed = e["group"] != g
            e["group"] = g
            return None, changed or disk is None
        self._mutate(change)
        return self._row(preset_id)

    def set_favorite(self, preset_id, favorite):
        """Mark / unmark as favorite (idempotent) -> the preset's row."""
        self._precheck(preset_id)
        if not isinstance(favorite, bool):
            raise DarkroomError("invalid", M.LIB_FAVORITE_INVALID)

        def change(index, files, disk):
            e = self._known(index, preset_id)
            changed = e["favorite"] != favorite
            e["favorite"] = favorite
            return None, changed or disk is None
        self._mutate(change)
        return self._row(preset_id)

    def create_group(self, group):
        """Add an explicit empty group -> {"group"}; conflict when any preset or group already uses that name."""
        g = _group(group)

        def change(index, files, disk):
            if group_exists(index, g):
                raise DarkroomError("conflict", M.LIB_GROUP_EXISTS.format(group=g))
            index["groups"].append(g)
            return {"group": g}, True
        return self._mutate(change)

    def rename_group(self, group, new_name):
        """Rename a group and every sub-path under it -> {"group", "presets": number moved}.

        not_found when the group does not exist; conflict when the new name exists (never merges two groups).
        Renaming to a different case of the same name is allowed."""
        g, n = _group(group), _group(new_name)

        def change(index, files, disk):
            if not group_exists(index, g):
                raise DarkroomError("not_found", M.LIB_GROUP_NOT_FOUND.format(group=g))
            if n.casefold() != g.casefold() and group_exists(index, n):
                raise DarkroomError("conflict", M.LIB_GROUP_EXISTS.format(group=n))
            moved = 0
            for e in index["presets"].values():
                r = _renamed(e["group"].strip(), g, n)
                if r is not None:
                    e["group"] = r
                    moved += 1
            groups = []
            for x in index["groups"]:
                r = _renamed(x, g, n)
                groups.append(x if r is None else r)
            index["groups"] = list(dict.fromkeys(groups))
            return {"group": n, "presets": moved}, True
        return self._mutate(change)

    def rebuild_library(self):
        """Re-scan the folders and rewrite the index -> {added, removed, kept} compared with the old index."""
        def change(index, files, disk):
            old = set(disk["presets"]) if disk else set()
            new = set(index["presets"])
            return {"added": len(new - old), "removed": len(old - new), "kept": len(new & old)}, True
        return self._mutate(change)

    def save_user_preset(self, name, group=None, preset_id=None, strength=100, overrides=None):
        """Save preset x strength + overrides as a new user preset -> {id, name, group, file}.

        Raises invalid (name, group, strength, overrides, nothing to save), not_found (unknown or unsupported
        preset), unavailable (writes switched off / the file cannot be created). Writes a new file in user/ and
        library.json."""
        n = _name(name)
        g = USER_GROUP if group is None else _group(group)
        params = None
        if preset_id is not None:
            if not isinstance(preset_id, str) or preset_id not in self.library.params:
                raise DarkroomError("not_found", M.UNKNOWN_OR_UNSUPPORTED_PRESET.format(pid=preset_id))
            params = self.library.get(preset_id)          # the snapshot at this moment (K12)
        adj = Adjustment.from_request(strength, overrides)      # VO -> BO: invalid with the validate_* sentence
        if preset_id is None and adj.is_empty:
            raise DarkroomError("invalid", M.LIB_NOTHING_TO_SAVE)
        return self._save(n, g, adj.final(params))              # the preview's own function (K12)

    def save_params(self, name, group, params):
        """The K12 write for Params already final - the photo library's "save the edit's snapshot as a preset"
        (CONTRACT-photo-library PLP6); name / group rules and sentences as K6 / K7."""
        return self._save(_name(name), USER_GROUP if group is None else _group(group), params)

    def _save(self, n, g, final):
        """Write the user preset file (first free numbered name) and add it to the index -> the new row's info."""
        data = xmp_bytes(final, n, g)

        def unavailable(reason):
            return DarkroomError("unavailable", M.LIB_SAVE_UNAVAILABLE.format(reason=reason))

        def change(index, files, disk):
            stem, path = self._create(self.library.user_dir, safe_stem(n), data, unavailable)
            pid = USER_PREFIX + stem
            info = self.library.file_info(path)
            files[pid] = info
            index["presets"][pid] = {"file": info.rel, "sha256": info.sha256, "name": n, "group": g,
                                     "favorite": False}
            return {"id": pid, "name": n, "group": g, "file": info.rel}, True
        return self._mutate(change)

    # ------------------------------------------------------------------ preset files (S2 E16, E17)
    @staticmethod
    def _ids(preset_ids):
        """A list of 1..500 strings, else invalid (E16)."""
        if (not isinstance(preset_ids, list) or not 1 <= len(preset_ids) <= PRESET_IDS_MAX
                or not all(isinstance(p, str) for p in preset_ids)):
            raise DarkroomError("invalid", M.PRESET_IDS_INVALID)
        return preset_ids

    def _file_of(self, pid):
        """(stem, bytes) of one preset as handed to Lightroom (D6), or (None, the failure sentence)."""
        row = self.library.by_id.get(pid)
        info = self.library.files().get(pid)
        if row is None or info is None:
            return None, M.UNKNOWN_PRESET.format(pid=pid)
        try:
            data = self.library.read_bytes(info.path)
        except OSError as e:
            return None, M.LIB_IMPORT_UNREADABLE.format(file_name=os.path.basename(info.path), reason=_one_line(e))
        if pid.startswith(USER_PREFIX):
            data = lightroom_bytes(data)
        return safe_stem(row["name"]), data

    def preset_files(self, preset_ids):
        """S2 E16: the presets' .xmp bytes (base64), in order; reads only."""
        ids = self._ids(preset_ids)
        out, taken = [], set()
        for pid in ids:
            stem, data = self._file_of(pid)
            if stem is None:
                out.append({"ok": False, "preset_id": pid, "error": data})
                continue
            name = next(f"{s}.xmp" for s in numbered(stem) if f"{s}.xmp".casefold() not in taken)
            taken.add(name.casefold())
            out.append({"ok": True, "preset_id": pid, "file_name": name,
                        "data_base64": base64.b64encode(data).decode("ascii")})
        return {"files": out}

    def export_preset_files(self, preset_ids, dest_dir):
        """S2 E17: the presets' .xmp files written into an existing folder outside the preset folder and the library;
        never overwrites (numbered names), never creates a folder."""
        ids = self._ids(preset_ids)
        if not isinstance(dest_dir, str) or not os.path.isabs(dest_dir) or not os.path.isdir(dest_dir):
            raise DarkroomError("invalid", M.EXPORT_NO_DEST.format(dest_dir=dest_dir))
        real = os.path.normcase(os.path.realpath(dest_dir))
        for folder in (self.preset_dir, self.root):
            f = os.path.normcase(os.path.realpath(folder))
            try:
                inside = os.path.commonpath([real, f]) == f
            except ValueError:
                inside = False
            if inside:
                raise DarkroomError("invalid", M.PRESET_EXPORT_INTO_LIBRARY.format(dest_dir=dest_dir))
        try:
            taken = {n.casefold() for n in os.listdir(dest_dir)}
        except OSError:
            taken = set()
        results = []
        for pid in ids:
            stem, data = self._file_of(pid)
            if stem is None:
                results.append({"ok": False, "preset_id": pid, "error": data})
                continue
            results.append(self._write_one(pid, stem, data, dest_dir, taken))
        return {"results": results}

    def _write_one(self, pid, stem, data, dest_dir, taken):
        """Write one preset file under the first free numbered name in dest_dir -> its result entry."""
        try:
            for s in numbered(stem):
                name = f"{s}.xmp"
                if name.casefold() in taken:
                    continue
                try:
                    path = self.store.create_in(dest_dir, name, data)
                except FileExistsError:
                    taken.add(name.casefold())
                    continue
                taken.add(name.casefold())
                return {"ok": True, "preset_id": pid, "output": path}
        except OSError:
            return {"ok": False, "preset_id": pid, "error": M.EXPORT_CANNOT_WRITE.format(folder=dest_dir)}
        return {"ok": False, "preset_id": pid, "error": M.EXPORT_NAMES_USED_UP.format(stem=stem, n_max=N_MAX)}

    # ------------------------------------------------------------------ import (K11, KP4)
    def _sources(self, paths, files):
        """[(kind, source)] to import: each path (a folder expands to its first-level .xmp files, sorted) and each
        upload {name, data_base64}; invalid when nothing usable was given."""
        out = []
        if paths is not None:
            if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                raise DarkroomError("invalid", M.LIB_NOTHING_TO_IMPORT)
            for p in paths:
                if os.path.isdir(p):
                    names = sorted((e.name for e in os.scandir(p)
                                    if e.name.lower().endswith(".xmp") and e.is_file()),
                                   key=lambda s: (s.casefold(), s))
                    out += [("path", os.path.join(p, x)) for x in names]
                else:
                    out.append(("path", p))
        if files is not None:
            if not isinstance(files, list) or not all(
                    isinstance(f, dict) and set(f) == {"name", "data_base64"} and isinstance(f["name"], str)
                    and isinstance(f["data_base64"], str) for f in files):
                raise DarkroomError("invalid", M.LIB_FILES_INVALID)
            out += [("upload", f) for f in files]
        if not out:
            raise DarkroomError("invalid", M.LIB_NOTHING_TO_IMPORT)
        return out

    def import_presets(self, paths=None, group=None, files=None):
        """Copy presets into import/ -> {"results": [one per source]} (KP5: partial failure is not an error).

        Each source is read, de-duplicated by content hash against every preset already in the library, parsed
        (must be a supported preset), then written under a numbered safe name. The source files are only read."""
        g = None if group is None else _group(group)
        sources = self._sources(paths, files)

        def change(index, lib_files, disk):
            by_sha = {}
            for pid, f in lib_files.items():
                by_sha.setdefault(f.sha256, pid)
            results = [self._import_one(kind, x, g, index, lib_files, by_sha) for kind, x in sources]
            return {"results": results}, any(r["ok"] for r in results)
        return self._mutate(change)

    def _import_one(self, kind, x, group, index, lib_files, by_sha):
        """Import one source into the index being changed -> {ok, source, id} or {ok: false, source, error}."""
        if kind == "path":
            source = os.path.basename(x)
            if not os.path.isfile(x):
                return {"ok": False, "source": source, "error": M.LIB_IMPORT_MISSING.format(path=x)}
        else:
            source = x["name"].replace("\\", "/").split("/")[-1]
        stem, ext = os.path.splitext(source)
        if ext.lower() != ".xmp":
            return {"ok": False, "source": source, "error": M.LIB_IMPORT_NOT_XMP.format(file_name=source)}

        def fail(reason):
            return {"ok": False, "source": source,
                    "error": M.LIB_IMPORT_UNREADABLE.format(file_name=source, reason=_one_line(reason))}
        try:
            if kind == "path":
                data = self.library.read_bytes(x)
            else:
                data = base64.b64decode(x["data_base64"], validate=True)
        except (OSError, binascii.Error, ValueError) as e:
            return fail(e)
        sha = hashlib.sha256(data).hexdigest()
        if sha in by_sha:
            dup = by_sha[sha]
            return {"ok": False, "source": source,
                    "error": M.LIB_IMPORT_DUPLICATE.format(name=index["presets"][dup]["name"]), "duplicate_of": dup}
        try:
            if kind == "path":
                load_preset(x)
            else:
                self._check_upload(data)
        except ItemWriteFailed as e:
            return {"ok": False, "source": source,
                    "error": M.LIB_IMPORT_WRITE_FAILED.format(file_name=source, reason=e.reason)}
        except (UnsupportedPresetError, ValueError, OSError, LookupError) as e:   # LookupError: unknown XML encoding
            return fail(e)

        try:
            final, path = self._create(self.library.import_dir, safe_stem(stem), data, ItemWriteFailed)
        except ItemWriteFailed as e:
            return {"ok": False, "source": source,
                    "error": M.LIB_IMPORT_WRITE_FAILED.format(file_name=source, reason=e.reason)}
        pid = IMPORT_PREFIX + final
        info = self.library.file_info(path)
        lib_files[pid] = info
        by_sha[sha] = pid
        meta_name, meta_group = meta_of(data)
        index["presets"][pid] = {"file": info.rel, "sha256": sha, "name": meta_name or final,
                                 "group": group if group is not None else meta_group, "favorite": False}
        return {"ok": True, "source": source, "id": pid}

    def _check_upload(self, data):
        """load_preset on uploaded bytes, through a temporary file the store removes again (KP4)."""
        self.store.check_upload(data, secrets.token_hex(6), ItemWriteFailed)


class ItemWriteFailed(Exception):
    """One imported xmp could not be written: the reason goes into that item's sentence (KP5)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason
