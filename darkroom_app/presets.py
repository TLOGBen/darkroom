"""The preset library as the editor sees it: id, group, name, supported, skipped, favorite (read only).

Three folders hold presets: the purchased ones in `preset_dir` (id = file stem), `<root>/import/` (id
`import:{stem}`) and `<root>/user/` (id `user:{stem}`); `<root>/library.json` (the index) keeps names, groups
and favorites, so organising presets never touches a file (CONTRACT-preset-library K1-K5). This module only
reads: without an index the index lives in memory only (K3); writing it is services/preset_library.py.

The view is always merge(index on disk, the three folders) (K5 rule); it is recomputed when library.json changes
(its (st_ino, st_mtime_ns, st_size), KP8) or after this process wrote it (`adopt`). Files are parsed once per
(path, mtime, size). Display name and group come from <crs:Name> / <crs:Group>, read here because the core
library's public API returns parameters only; files with a DOCTYPE are never parsed here (load_preset rejects them
first, and such files are listed as unsupported).
"""
import hashlib
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from darkroom import Params, UnsupportedPresetError, load_preset

from . import skips, sliders

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"

INDEX_SCHEMA = "darkroom-preset-library/1"     # verbatim (K4)
INDEX_NAME = "library.json"                     # K1
IMPORT_DIR, USER_DIR = "import", "user"          # K1
IMPORT_PREFIX, USER_PREFIX = "import:", "user:"  # verbatim (K4)
GROUP_SEP = " - "                               # verbatim (K7)
ROW_KEYS = ("id", "group", "name", "supported", "skipped", "favorite", "tags")   # B3, K9, + tags (SI10)
SEMANTIC_NAME = "semantic.json"                          # CONTRACT-semantic-index SI6
SEMANTIC_SCHEMA = "darkroom-semantic-index/1"            # verbatim (SI6)
SEMANTIC_MODEL = "claude-haiku-5-5"                      # verbatim (SI5)
SEMANTIC_FIELDS = ("look_zh", "look_en", "tags_zh", "tags_en", "tone", "contrast", "saturation", "temperature",
                   "good_for", "confidence")             # verbatim (SI5 SCHEMA), in order
SEMANTIC_ENUMS = {"tone": ("dark", "balanced", "bright"), "contrast": ("low", "medium", "high"),
                  "saturation": ("muted", "natural", "vivid", "monochrome"), "temperature": ("cool", "neutral", "warm")}
SEMANTIC_SEARCH_FIELDS = ("tags_zh", "tags_en", "good_for", "look_zh", "look_en")   # SI10: what a query matches
READ_RETRIES, READ_RETRY_S = 10, 0.1            # K15 / KP8: a reader can meet a replace in progress
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")   # KP6
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def clean_text(text):
    """text without the characters XML 1.0 does not allow (KP6)."""
    return _XML_BAD.sub("", text)


def normalize_group(group):
    """K7: split on " - ", strip every part, join again; None when not a string, empty or with an empty part."""
    if not isinstance(group, str):
        return None
    parts = [clean_text(p).strip() for p in group.split(GROUP_SEP)]
    if not parts or any(not p for p in parts):
        return None
    return GROUP_SEP.join(parts)


def split_group(group):
    """(top, child or None) - only the first " - " splits (B9)."""
    g = group.strip()
    top, sep, child = g.partition(GROUP_SEP)
    return top, (child if sep else None)


def _text(root, tag):
    for el in root.iter(f"{CRS}{tag}"):
        li = el.find(f"{RDF}Alt/{RDF}li")
        if li is not None and (li.text or "").strip():
            return li.text.strip()
    return ""


def meta_of(data):
    """(crs:Name, crs:Group) of xmp bytes; ("", "") when it has a DTD or does not parse."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return "", ""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return "", ""
    return _text(root, "Name"), _text(root, "Group")


def _meta(path):
    with open(path, "rb") as f:
        return meta_of(f.read())


@dataclass
class PresetFile:
    """One xmp file as read: content hash, parse result and the name / group written in it."""
    path: str
    rel: str            # K4: relative to the library root, "/" separators
    stamp: tuple        # (st_mtime_ns, st_size) when read
    sha256: str
    supported: bool
    skipped: list
    params: object      # Params or None
    meta_name: str
    meta_group: str


def _rel(path, root):
    try:
        rel = os.path.relpath(path, root)
    except ValueError:              # another drive (KP9)
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


def valid_index(obj):
    """True when obj is exactly the K4 index schema."""
    if not isinstance(obj, dict) or list(obj) != ["schema", "groups", "presets"] or obj["schema"] != INDEX_SCHEMA:
        return False
    if not isinstance(obj["groups"], list) or not all(isinstance(g, str) for g in obj["groups"]):
        return False
    if not isinstance(obj["presets"], dict):
        return False
    for pid, e in obj["presets"].items():
        if not isinstance(e, dict) or list(e) != ["file", "sha256", "name", "group", "favorite"]:
            return False
        if not isinstance(e["file"], str) or not isinstance(e["sha256"], str) or not _HEX64.match(e["sha256"]):
            return False
        if not isinstance(e["name"], str) or not isinstance(e["group"], str) or not isinstance(e["favorite"], bool):
            return False
        if _stem_of(pid) is None:
            return False
    return True


def valid_entry(obj):
    """None when obj is a well-formed semantic entry (SI5: the 10 fields, legal enums, non-empty string arrays,
    confidence in 0..1), else the reason (one phrase)."""
    if not isinstance(obj, dict):
        return "not an object"
    if set(obj) - set(SEMANTIC_FIELDS) - {"at"} or any(k not in obj for k in SEMANTIC_FIELDS):
        return "fields must be exactly " + ", ".join(SEMANTIC_FIELDS)
    for k in ("look_zh", "look_en"):
        if not isinstance(obj[k], str) or not obj[k].strip():
            return f"{k} must be a non-empty string"
    for k in ("tags_zh", "tags_en", "good_for"):
        if not isinstance(obj[k], list) or not all(isinstance(t, str) and t.strip() for t in obj[k]):
            return f"{k} must be an array of non-empty strings"
    for k, allowed in SEMANTIC_ENUMS.items():
        if obj[k] not in allowed:
            return f"{k} must be one of " + "|".join(allowed)
    c = obj["confidence"]
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
        return "confidence must be a number in 0..1"
    return None


def valid_semantic(obj):
    """True when obj is exactly the SI6 semantic index schema (entries keyed by sha256)."""
    if not isinstance(obj, dict) or list(obj) != ["schema", "model", "entries", "batches", "usage"]:
        return False
    if obj["schema"] != SEMANTIC_SCHEMA or not isinstance(obj["model"], str):
        return False
    if not isinstance(obj["entries"], dict) or not isinstance(obj["batches"], dict) or not isinstance(obj["usage"], list):
        return False
    for sha, e in obj["entries"].items():
        if not _HEX64.match(sha) or valid_entry(e) is not None or not isinstance(e.get("at"), (int, float)):
            return False
    for bid, b in obj["batches"].items():
        if not isinstance(bid, str) or not isinstance(b, dict) or not isinstance(b.get("items"), dict):
            return False
        if not all(_HEX64.match(k) and isinstance(v, str) for k, v in b["items"].items()):
            return False
    return True


def empty_semantic():
    return {"schema": SEMANTIC_SCHEMA, "model": SEMANTIC_MODEL, "entries": {}, "batches": {}, "usage": []}


def semantic_tags(entry):
    """The row's 7th column (SI10): tags_zh + tags_en, de-duplicated, order kept; [] without an entry."""
    if entry is None:
        return []
    return list(dict.fromkeys([*entry["tags_zh"], *entry["tags_en"]]))


def _stem_of(pid):
    """(prefix, stem) of a well-formed id, else None (no separators, no "." / ".." stems)."""
    if not isinstance(pid, str):
        return None
    for prefix in (IMPORT_PREFIX, USER_PREFIX, ""):
        if pid.startswith(prefix):
            stem = pid[len(prefix):]
            if not stem or stem in (".", "..") or any(c in stem for c in '/\\:'):
                return None
            return prefix, stem
    return None


def merge(old, files, stem_name):
    """The K5 rule: files still there keep name / group / favorite (sha256 updated); new files take crs:Name
    (empty -> stem) and crs:Group; ids whose file is gone are dropped; only valid explicit groups stay."""
    old_presets = old["presets"] if old else {}
    presets = {}
    for pid in sorted(files):
        f = files[pid]
        o = old_presets.get(pid)
        if o is not None:
            presets[pid] = {"file": f.rel, "sha256": f.sha256, "name": o["name"], "group": o["group"],
                            "favorite": o["favorite"]}
        else:
            presets[pid] = {"file": f.rel, "sha256": f.sha256, "name": f.meta_name or stem_name(pid),
                            "group": f.meta_group, "favorite": False}
    groups, seen = [], set()
    for g in (old["groups"] if old else []):
        if normalize_group(g) == g and g.casefold() not in seen:
            seen.add(g.casefold())
            groups.append(g)
    return {"schema": INDEX_SCHEMA, "groups": groups, "presets": presets}


def index_bytes(index):
    """K4: UTF-8 without BOM."""
    return json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Library:
    def __init__(self, preset_dir, library_dir=None):
        self.preset_dir = preset_dir
        if not os.path.isdir(preset_dir):
            raise FileNotFoundError(f"preset folder not found: {preset_dir}")
        self.root = os.path.abspath(library_dir if library_dir is not None
                                    else os.path.dirname(os.path.abspath(preset_dir)))
        self.index_path = os.path.join(self.root, INDEX_NAME)
        self.import_dir = os.path.join(self.root, IMPORT_DIR)
        self.user_dir = os.path.join(self.root, USER_DIR)
        self.semantic_path = os.path.join(self.root, SEMANTIC_NAME)
        self._lock = threading.RLock()
        self._cache = {}          # normcase(path) -> PresetFile
        self._stamp = None        # stat key of library.json behind the current view (None: missing)
        self._semantic = (None, empty_semantic(), "missing")   # (stamp, index, state) of semantic.json (SI6)
        self._load()

    # ---------------------------------------------------------------- the semantic index (read only, SI6)
    def _stat_key(self, path):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def read_semantic(self):
        """(index, state): the semantic index on disk, or the empty one; state missing | ok | bad. A bad or
        unparsable file is left alone (never renamed or deleted)."""
        for attempt in range(READ_RETRIES):
            try:
                with open(self.semantic_path, "rb") as f:
                    raw = f.read()
                break
            except FileNotFoundError:
                return empty_semantic(), "missing"
            except PermissionError:           # a replace in progress
                if attempt == READ_RETRIES - 1:
                    raise
                time.sleep(READ_RETRY_S)
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return empty_semantic(), "bad"
        return (obj, "ok") if valid_semantic(obj) else (empty_semantic(), "bad")

    def semantic(self):
        """The semantic index, re-read when semantic.json changed (stat key, like library.json)."""
        stamp = self._stat_key(self.semantic_path)
        with self._lock:
            if stamp != self._semantic[0]:
                try:
                    index, state = self.read_semantic()
                except PermissionError:
                    return self._semantic[1]
                self._semantic = (stamp, index, state)
            return self._semantic[1]

    def semantic_state(self):
        self.semantic()
        return self._semantic[2]

    def sha_of(self, pid):
        """The content sha256 of a preset in the view (None when unknown)."""
        f = self.files().get(pid)
        return None if f is None else f.sha256

    def semantic_entry(self, pid):
        sha = self.sha_of(pid)
        return None if sha is None else self.semantic()["entries"].get(sha)

    # ---------------------------------------------------------------- reading files
    def stem_name(self, pid):
        return _stem_of(pid)[1]

    def path_of(self, pid):
        prefix, stem = _stem_of(pid)
        folder = {IMPORT_PREFIX: self.import_dir, USER_PREFIX: self.user_dir}.get(prefix, self.preset_dir)
        return os.path.join(folder, stem + ".xmp")

    def file_info(self, path, stamp=None):
        """PresetFile for an xmp path (cached per (mtime, size)); None when it cannot be read."""
        try:
            if stamp is None:
                st = os.stat(path)
                stamp = (st.st_mtime_ns, st.st_size)
            key = os.path.normcase(os.path.abspath(path))
            with self._lock:
                hit = self._cache.get(key)
            if hit is not None and hit.stamp == stamp:
                return hit
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        try:
            params = load_preset(path)
            supported, skipped = True, list(params.skipped)
        except (UnsupportedPresetError, OSError, ValueError, LookupError):   # LookupError: unknown XML encoding
            params, supported, skipped = None, False, []
        name, group = meta_of(data) if supported else ("", "")
        info = PresetFile(path, _rel(path, self.root), stamp, hashlib.sha256(data).hexdigest(), supported, skipped,
                          params, name, group)
        with self._lock:
            self._cache[key] = info
        return info

    def scan(self):
        """{id: PresetFile} for the first-level *.xmp of preset_dir, import/ and user/ (K5)."""
        out = {}
        for folder, prefix in ((self.preset_dir, ""), (self.import_dir, IMPORT_PREFIX), (self.user_dir, USER_PREFIX)):
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except (FileNotFoundError, NotADirectoryError):
                continue
            for e in entries:
                stem, ext = os.path.splitext(e.name)
                if ext.lower() != ".xmp" or _stem_of(prefix + stem) is None:
                    continue
                try:
                    if not e.is_file():
                        continue
                    st = e.stat()
                except OSError:
                    continue
                info = self.file_info(e.path, (st.st_mtime_ns, st.st_size))
                if info is not None:
                    out[prefix + stem] = info
        return out

    def index_stamp(self):
        try:
            st = os.stat(self.index_path)
        except FileNotFoundError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def read_index(self):
        """(index or None, raw bytes or None, "missing" | "ok" | "bad"); the file is closed right after reading."""
        for attempt in range(READ_RETRIES):
            try:
                with open(self.index_path, "rb") as f:
                    raw = f.read()
                break
            except FileNotFoundError:
                return None, None, "missing"
            except PermissionError:           # a replace in progress (P6)
                if attempt == READ_RETRIES - 1:
                    raise
                time.sleep(READ_RETRY_S)
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return None, raw, "bad"
        return (obj, raw, "ok") if valid_index(obj) else (None, raw, "bad")

    def merged(self, index, files=None):
        return merge(index, self.scan() if files is None else files, self.stem_name)

    # ---------------------------------------------------------------- the view
    def _load(self):
        with self._lock:
            stamp = self.index_stamp()
            try:
                index, _, _ = self.read_index()
            except PermissionError:
                if hasattr(self, "_entries"):
                    return
                index = None
            files = self.scan()
            self._set_view(merge(index, files, self.stem_name), files, stamp)

    def refresh(self):
        """Re-read the index when library.json changed since the view was built (K15, KP8)."""
        if self.index_stamp() != self._stamp:
            self._load()

    def adopt(self, index, files):
        """The view after this process wrote `index` (files: {id: PresetFile} it was built from)."""
        with self._lock:
            self._set_view(index, files, self.index_stamp())

    def _set_view(self, index, files, stamp):
        entries, params = [], {}
        for pid, e in index["presets"].items():
            f = files.get(pid)
            if f is None:
                continue
            entries.append({"id": pid, "group": e["group"], "name": e["name"], "supported": f.supported,
                            "skipped": list(f.skipped), "favorite": e["favorite"]})
            if f.params is not None:
                params[pid] = f.params
        entries.sort(key=lambda e: (e["group"].casefold(), e["name"].casefold(), e["id"]))
        self._index, self._files = index, files
        self._entries, self._by_id, self._params = entries, {e["id"]: e for e in entries}, params
        self._stamp = stamp

    @property
    def entries(self):
        self.refresh()
        return self._entries

    @property
    def by_id(self):
        self.refresh()
        return self._by_id

    @property
    def params(self):
        self.refresh()
        return self._params

    @property
    def index(self):
        self.refresh()
        return self._index

    def files(self):
        self.refresh()
        return self._files

    def get(self, pid):
        """Params for a supported preset id, else KeyError."""
        return self.params[pid]

    def row(self, pid):
        """The 7-column row (B3, K9, SI10): the view's 6 columns plus tags from the semantic index."""
        e = self.by_id[pid]
        return {**{k: (list(v) if k == "skipped" else v) for k, v in e.items()},
                "tags": semantic_tags(self.semantic_entry(pid))}

    def detail(self, pid):
        e = self.by_id[pid]
        p = self._params.get(pid) or Params()
        values = {k: p.get(k) for k in sliders.BY_KEY}
        summary = skips.summarize(e["skipped"])
        return {"id": pid, "group": e["group"], "name": e["name"], "supported": e["supported"],
                "skipped": list(e["skipped"]), "level": summary["level"], "banner": summary["banner"],
                "note": summary["note"], "values": values,
                "curves": {k: [[float(x), float(y)] for x, y in pts] for k, pts in p.curves.items()}}

    def flags(self):
        """{id: "major"|"minor"} for presets with skipped settings (contract R4)."""
        out = {}
        for e in self.entries:
            lv = skips.summarize(e["skipped"])["level"]
            if lv:
                out[e["id"]] = lv
        return out

    def group_tree(self):
        """K10: {"groups": [{name, path, count, children: [{name, path, count}]}], "ungrouped": n}."""
        tops, ungrouped = {}, 0
        entries, index = self.entries, self._index
        for e in entries:
            top, child = split_group(e["group"])
            if not top:
                ungrouped += 1
                continue
            node = tops.setdefault(top, {"count": 0, "children": {}})
            node["count"] += 1
            if child is not None:
                node["children"][child] = node["children"].get(child, 0) + 1
        for g in index["groups"]:
            top, child = split_group(g)
            node = tops.setdefault(top, {"count": 0, "children": {}})
            if child is not None:
                node["children"].setdefault(child, 0)
        order = lambda s: (s.casefold(), s)
        return {"groups": [{"name": top, "path": top, "count": tops[top]["count"],
                            "children": [{"name": c, "path": top + GROUP_SEP + c, "count": n}
                                         for c, n in sorted(tops[top]["children"].items(), key=lambda kv: order(kv[0]))]}
                           for top in sorted(tops, key=order)],
                "ungrouped": ungrouped}
