"""Organising the preset library: groups, names, favorites, import, user presets, rebuild (CONTRACT-preset-library).

Every rule of these operations lives here; every write goes through `safe_write` (CONTRACT-write-guard G8 / G10,
patch KP1) with the library root as `root` and the preset folder in use as `preset_dir=` (the purchased xmp
folder is never written; the default root is its parent, so library.json, import/ and user/ lie outside it).

An organising operation: arguments checked -> the cross-process lock (`<root>/library.json.lock`, msvcrt byte lock,
released by Windows when the holder dies; waiting longer than LOCK_WAIT_S -> conflict) -> the index on disk read
again and merged with the three folders (K5 rule) -> the change -> `library.json.tmp-{pid}-{12 hex}` written with
create_new and moved over library.json with replace_into (PermissionError retried, P6 / KP21: a reader holding the
file open blocks the rename outright on Windows, and collisions come in GIL-phase-coupled streaks, so the budget is
200 x 0.01 s, not 10 x 0.1 s) -> the in-process view
adopted. An unreadable index is first kept as `library.json.bad-{unix seconds}` (a byte copy: safe_write has no
rename). Purchased xmp, imported and user files already there are never rewritten, renamed or deleted.
`SafeWriteRefused` is never caught (G8).
"""
import base64
import binascii
import hashlib
import msvcrt
import os
import secrets
import threading
import time
from decimal import Decimal
from xml.sax.saxutils import escape

from darkroom import UnsupportedPresetError, load_preset

from .. import messages as M
from .. import preview as semantics
from .. import safe_write
from ..errors import DarkroomError
from ..presets import (GROUP_SEP, IMPORT_PREFIX, INDEX_NAME, USER_PREFIX, clean_text, index_bytes, meta_of,
                       normalize_group, split_group)

LOCK_WAIT_S = 5.0                   # verbatim (K15, KP8)
LOCK_POLL_S = 0.02
REPLACE_RETRIES, REPLACE_RETRY_S = 200, 0.01   # verbatim (K15 as revised by KP21: 200 times, about 2 s)
NAME_MAX = 100                      # K6
USER_GROUP = "自存 preset"           # verbatim (K12)
FILE_MAX = 80                       # K14
N_MAX = 9999                        # numbered names {stem} (n).xmp, n = 2..N_MAX
_UNSAFE = set('<>:"/\\|?*') | {chr(c) for c in range(32)}       # verbatim (K14)
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_NO_WRITE = {"Temperature", "Tint", "WhiteBalance"}            # KP6 (P4)
XMP_HEAD = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Normal" '
            'crs:ProcessVersion="15.4" crs:HasSettings="True"')   # verbatim (K13)
_ATTR = {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}
_TEXT = {"\r": "&#13;"}
CURVE_ORDER = ("ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue")
GRADIENT_KEYS = ("ZeroX", "ZeroY", "FullX", "FullY")
CIRCULAR_KEYS = ("Top", "Left", "Bottom", "Right", "Angle", "Midpoint", "Roundness", "Feather")


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
    return f' crs:{name}="{escape(value, _ATTR)}"'


def _alt(tag, text):
    return (f"<crs:{tag}><rdf:Alt><rdf:li xml:lang=\"x-default\">{escape(text, _TEXT)}</rdf:li></rdf:Alt>"
            f"</crs:{tag}>")


def _bool(v):
    return "true" if v else "false"


def xmp_bytes(params, name, group):
    """The user preset file (K13 constant "自存 xmp"): values as crs attributes, curves, masks, Name and Group."""
    out = [XMP_HEAD]
    for k in sorted(params.values):
        if k in _NO_WRITE:
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


def _one_line(e):
    return " ".join(str(e).split()) or type(e).__name__


def _name(name):
    """K6 / KP6: strip, XML-invalid characters removed, 1..100 characters."""
    n = clean_text(name).strip() if isinstance(name, str) else ""
    if not 1 <= len(n) <= NAME_MAX:
        raise DarkroomError("invalid", M.LIB_NAME_LENGTH)
    return n


def _group(group):
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


class PresetLibraryService:
    def __init__(self, library, preset_dir):
        self.library = library
        self.preset_dir = preset_dir           # the purchased preset folder in use, for safe_write (KP1)
        self._tlock = threading.Lock()         # one organising operation at a time in this process

    # ------------------------------------------------------------------ writing (safe_write only)
    @property
    def root(self):
        return self.library.root

    def _sw(self, fn, *args):
        return fn(*args, preset_dir=self.preset_dir)

    def _acquire(self):
        lock = os.path.join(self.root, INDEX_NAME + ".lock")
        try:
            fd = self._sw(safe_write.open_lock, lock, self.root)
        except OSError as e:
            raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise DarkroomError("conflict", M.LIB_BUSY) from None
                time.sleep(LOCK_POLL_S)

    @staticmethod
    def _release(fd):
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

    def _keep_bad(self, raw):
        """K5 / KP1: a byte copy library.json.bad-{unix seconds} (-{n} when that second is taken)."""
        base = os.path.join(self.root, f"{INDEX_NAME}.bad-{int(time.time())}")
        for n in range(1, N_MAX + 1):
            path = base if n == 1 else f"{base}-{n}"
            try:
                self._sw(safe_write.create_new, path, self.root, raw)
                return path
            except FileExistsError:
                continue
            except OSError as e:
                raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason="no free .bad name"))

    def _write_index(self, index):
        tmp = os.path.join(self.root, f"{INDEX_NAME}.tmp-{os.getpid()}-{secrets.token_hex(6)}")
        try:
            self._sw(safe_write.create_new, tmp, self.root, index_bytes(index))
        except OSError as e:
            raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        try:
            for attempt in range(REPLACE_RETRIES):
                try:
                    self._sw(safe_write.replace_into, tmp, self.library.index_path, self.root)
                    return
                except PermissionError as e:      # a reader has library.json open (P6)
                    if attempt == REPLACE_RETRIES - 1:
                        raise DarkroomError("unavailable",
                                            M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
                    time.sleep(REPLACE_RETRY_S)
                except OSError as e:
                    raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
        finally:
            if os.path.exists(tmp):
                self._sw(safe_write.remove, tmp, self.root)

    def _mutate(self, change):
        """Lock -> index on disk merged with the folders -> change(index, files) -> atomic write -> adopt.

        change returns (result, changed); nothing is written when changed is False."""
        with self._tlock:
            fd = self._acquire()
            try:
                try:
                    disk, raw, state = self.library.read_index()
                except PermissionError as e:
                    raise DarkroomError("unavailable", M.LIB_INDEX_UNAVAILABLE.format(reason=_one_line(e))) from None
                files = self.library.scan()
                index = self.library.merged(disk, files)
                result, changed = change(index, files, disk)
                if changed or state == "bad":
                    if state == "bad":
                        self._keep_bad(raw)
                    self._write_index(index)
                self.library.adopt(index, files)
                return result
            finally:
                self._release(fd)

    def _make_dir(self, folder):
        if not os.path.isdir(folder):
            self._sw(safe_write.make_dirs, folder, self.root)

    def _create_numbered(self, folder, stem, data, unavailable):
        """create_new {stem}.xmp, {stem} (2).xmp ... in folder; (final stem, path). Never overwrites."""
        try:
            self._make_dir(folder)
            for s in numbered(stem):
                path = os.path.join(folder, s + ".xmp")
                if os.path.dirname(os.path.abspath(path)) != os.path.abspath(folder):    # K14: stays in folder
                    continue
                try:
                    self._sw(safe_write.create_new, path, self.root, data)
                    return s, path
                except FileExistsError:
                    continue
        except OSError as e:
            raise unavailable(_one_line(e)) from None
        raise unavailable(f"{stem} 的檔名已用到 ({N_MAX})")

    # ------------------------------------------------------------------ checks under the lock
    @staticmethod
    def _known(index, preset_id):
        if not isinstance(preset_id, str) or preset_id not in index["presets"]:
            raise DarkroomError("not_found", M.UNKNOWN_PRESET.format(pid=preset_id))
        return index["presets"][preset_id]

    def _precheck(self, preset_id):
        """KP9 order: the id is judged before the other arguments (on the view; again under the lock)."""
        if not isinstance(preset_id, str) or preset_id not in self.library.by_id:
            raise DarkroomError("not_found", M.UNKNOWN_PRESET.format(pid=preset_id))

    def _row(self, pid):
        return self.library.row(pid)

    # ------------------------------------------------------------------ operations
    def preset_groups(self):
        return self.library.group_tree()

    def rename_preset(self, preset_id, name):
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
        g = _group(group)

        def change(index, files, disk):
            if group_exists(index, g):
                raise DarkroomError("conflict", M.LIB_GROUP_EXISTS.format(group=g))
            index["groups"].append(g)
            return {"group": g}, True
        return self._mutate(change)

    def rename_group(self, group, new_name):
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
        def change(index, files, disk):
            old = set(disk["presets"]) if disk else set()
            new = set(index["presets"])
            return {"added": len(new - old), "removed": len(old - new), "kept": len(new & old)}, True
        return self._mutate(change)

    def save_user_preset(self, name, group=None, preset_id=None, strength=100, overrides=None):
        n = _name(name)
        g = USER_GROUP if group is None else _group(group)
        params = None
        if preset_id is not None:
            if not isinstance(preset_id, str) or preset_id not in self.library.params:
                raise DarkroomError("not_found", M.UNKNOWN_OR_UNSUPPORTED_PRESET.format(pid=preset_id))
            params = self.library.get(preset_id)          # the snapshot at this moment (K12)
        try:
            s = semantics.validate_strength(strength)
            o = semantics.validate_overrides(overrides)
        except ValueError as e:
            raise DarkroomError("invalid", str(e)) from None
        if preset_id is None and not o:
            raise DarkroomError("invalid", M.LIB_NOTHING_TO_SAVE)
        data = xmp_bytes(semantics.effective_params(params, s, o), n, g)    # the preview's own function (K12)

        def unavailable(reason):
            return DarkroomError("unavailable", M.LIB_SAVE_UNAVAILABLE.format(reason=reason))

        def change(index, files, disk):
            stem, path = self._create_numbered(self.library.user_dir, safe_stem(n), data, unavailable)
            pid = USER_PREFIX + stem
            info = self.library.file_info(path)
            files[pid] = info
            index["presets"][pid] = {"file": info.rel, "sha256": info.sha256, "name": n, "group": g,
                                     "favorite": False}
            return {"id": pid, "name": n, "group": g, "file": info.rel}, True
        return self._mutate(change)

    # ------------------------------------------------------------------ import (K11, KP4)
    def _sources(self, paths, files):
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
                with open(x, "rb") as fh:
                    data = fh.read()
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
        except _ItemWriteFailed as e:
            return {"ok": False, "source": source,
                    "error": M.LIB_IMPORT_WRITE_FAILED.format(file_name=source, reason=e.reason)}
        except (UnsupportedPresetError, ValueError, OSError, LookupError) as e:   # LookupError: unknown XML encoding
            return fail(e)

        def unavailable(reason):
            return _ItemWriteFailed(reason)
        try:
            final, path = self._create_numbered(self.library.import_dir, safe_stem(stem), data, unavailable)
        except _ItemWriteFailed as e:
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
        """load_preset on uploaded bytes: a temporary import/.upload-{pid}-{12 hex}.tmp, always removed (KP4)."""
        tmp = os.path.join(self.library.import_dir, f".upload-{os.getpid()}-{secrets.token_hex(6)}.tmp")
        try:
            self._make_dir(self.library.import_dir)
            self._sw(safe_write.create_new, tmp, self.root, data)
        except OSError as e:
            raise _ItemWriteFailed(_one_line(e)) from None
        try:
            load_preset(tmp)
        finally:
            self._sw(safe_write.remove, tmp, self.root)


class _ItemWriteFailed(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason
