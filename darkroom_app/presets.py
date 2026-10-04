"""The preset library as the editor sees it: id (file stem), group, name, supported, skipped.

Files are only opened for reading. Display name and group come from <crs:Name> / <crs:Group>, read here
because the core library's public API returns parameters only; files with a DOCTYPE are never parsed here
(load_preset rejects them first, and such files are listed as unsupported).
"""
import glob
import os
import xml.etree.ElementTree as ET

from darkroom import Params, UnsupportedPresetError, load_preset

from . import skips, sliders

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"

def _text(root, tag):
    for el in root.iter(f"{CRS}{tag}"):
        li = el.find(f"{RDF}Alt/{RDF}li")
        if li is not None and (li.text or "").strip():
            return li.text.strip()
    return ""


def _meta(path):
    with open(path, "rb") as f:
        data = f.read()
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return "", ""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return "", ""
    return _text(root, "Name"), _text(root, "Group")


class Library:
    def __init__(self, preset_dir):
        self.preset_dir = preset_dir
        self.entries = []      # public rows (B3)
        self.params = {}       # id -> Params
        if not os.path.isdir(preset_dir):
            raise FileNotFoundError(f"preset folder not found: {preset_dir}")
        for path in sorted(glob.glob(os.path.join(preset_dir, "*.xmp")), key=os.path.basename):
            pid = os.path.splitext(os.path.basename(path))[0]
            try:
                p = load_preset(path)
                supported, skipped = True, list(p.skipped)
                self.params[pid] = p
            except (UnsupportedPresetError, OSError, ValueError):
                supported, skipped = False, []
            name, group = _meta(path) if supported else ("", "")
            self.entries.append({"id": pid, "group": group, "name": name or pid, "supported": supported,
                                 "skipped": skipped})
        self.entries.sort(key=lambda e: (e["group"].casefold(), e["name"].casefold(), e["id"]))
        self.by_id = {e["id"]: e for e in self.entries}

    def get(self, pid):
        """Params for a supported preset id, else KeyError."""
        return self.params[pid]

    def detail(self, pid):
        e = self.by_id[pid]
        p = self.params.get(pid) or Params()
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
