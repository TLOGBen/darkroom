"""Preset library rules: ids, groups, the index schema, the merge rule, the semantic index schema, the view's queries.

Layer: domain (plan-v2 §1). Pure: no file is opened here. The persist side (`adapters/persist/preset_index.py`) reads
the three preset folders, `library.json` and `semantic.json`, and asks these functions what the bytes mean and what
the editor sees.

Three folders hold presets: the purchased ones in `preset_dir` (id = file stem), `<root>/import/` (id
`import:{stem}`) and `<root>/user/` (id `user:{stem}`); `<root>/library.json` (the index) keeps names, groups
and favorites, so organising presets never touches a file (CONTRACT-preset-library K1-K5). The view is always
merge(index on disk, the three folders) (K5 rule). Display name and group come from <crs:Name> / <crs:Group>
(`meta_of`); files with a DOCTYPE are never parsed (load_preset rejects them first, and such files are listed as
unsupported).

Contract codes used here (CONTRACT-preset-library unless noted): K1 = where the library root, index and the
import/ and user/ folders are; K4 = the exact index schema (library.json); K5 = rebuild / merge keeps names, groups
and favorites of files still present; K7 = groups are "Top - Child", split at the first " - "; K9 = favorites;
K10 = the group tree's shape and sort order; KP6 = text written into a user preset is cleaned of characters XML
forbids; B3 / B9 (CONTRACT-app-shell) = the preset row's columns and the two-level tree; R4 = the skipped-settings
levels; SI5 / SI6 / SI10 (CONTRACT-semantic-index) = a model answer's fields, the semantic.json schema, and which
semantic fields a search query matches.
"""
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from darkroom import Params

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
    """The first non-empty rdf:Alt text of a crs:<tag> element anywhere in the document, else ""."""
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


def stem_of(pid):
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


_stem_of = stem_of      # the name the persist side and older callers use


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
        if stem_of(pid) is None:
            return False
    return True


def valid_entry(obj, stored=True):
    """None when obj is a well-formed semantic entry (SI5: exactly the 10 fields, legal enums, non-empty string
    arrays, confidence in 0..1), else the reason (one phrase). A stored entry (semantic.json) also carries `at`;
    a model answer (stored=False) must not."""
    if not isinstance(obj, dict):
        return "not an object"
    extra = set(obj) - set(SEMANTIC_FIELDS) - ({"at"} if stored else set())
    if extra or any(k not in obj for k in SEMANTIC_FIELDS):
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
    """A fresh, empty semantic index object (what a missing or invalid semantic.json reads as)."""
    return {"schema": SEMANTIC_SCHEMA, "model": SEMANTIC_MODEL, "entries": {}, "batches": {}, "usage": []}


def semantic_tags(entry):
    """The row's 7th column (SI10): tags_zh + tags_en, de-duplicated, order kept; [] without an entry."""
    if entry is None:
        return []
    return list(dict.fromkeys([*entry["tags_zh"], *entry["tags_en"]]))


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


# ---------------------------------------------------------------------- the view (what the editor sees)
def build_view(index, files):
    """(entries sorted by group / name / id, {id: entry}, {id: Params}) of an index and the files it was built from.

    An entry is the 6-column row B3 / K9 (tags are added per query from the semantic index); a preset without a
    file is left out; Params only for the supported presets."""
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
    return entries, {e["id"]: e for e in entries}, params


def row(entry, semantic_entry):
    """The 7-column row (B3, K9, SI10): the view's 6 columns plus tags from the semantic index."""
    return {**{k: (list(v) if k == "skipped" else v) for k, v in entry.items()}, "tags": semantic_tags(semantic_entry)}


def detail(pid, entry, params):
    """One preset in detail: every slider's value at 100%, the curves, the skipped settings and their wording."""
    p = params or Params()
    values = {k: p.get(k) for k in sliders.BY_KEY}
    summary = skips.summarize(entry["skipped"])
    return {"id": pid, "group": entry["group"], "name": entry["name"], "supported": entry["supported"],
            "skipped": list(entry["skipped"]), "level": summary["level"], "banner": summary["banner"],
            "note": summary["note"], "values": values,
            "curves": {k: [[float(x), float(y)] for x, y in pts] for k, pts in p.curves.items()}}


def flags(entries):
    """{id: "major"|"minor"} for presets with skipped settings (contract R4)."""
    out = {}
    for e in entries:
        lv = skips.summarize(e["skipped"])["level"]
        if lv:
            out[e["id"]] = lv
    return out


def group_tree(entries, index):
    """K10: {"groups": [{name, path, count, children: [{name, path, count}]}], "ungrouped": n}."""
    tops, ungrouped = {}, 0
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
    order = lambda s: (s.casefold(), s)  # noqa: E731
    return {"groups": [{"name": top, "path": top, "count": tops[top]["count"],
                        "children": [{"name": c, "path": top + GROUP_SEP + c, "count": n}
                                     for c, n in sorted(tops[top]["children"].items(), key=lambda kv: order(kv[0]))]}
                       for top in sorted(tops, key=order)],
            "ungrouped": ungrouped}
