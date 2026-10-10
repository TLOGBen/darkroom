"""Persist adapters: every file darkroom keeps, and nothing else (plan-v2 §1).

Each store does file I/O for one kind of data and nothing about what the data means: the rules (what may be
written, the sentences, the schemas' meaning) are in domain/ and services/. All writes go through
`darkroom_app.utils` 's write module (CONTRACT-write-guard G8); `locks.py` holds the one copy of the cross-process
lock, the atomic replace, the retried read and the `.bad-{t}` copy that every store shares.

Dependency rule: persist imports domain and utils only; it never imports services, the facade, composition or config
(the composition constructs the stores and passes them to services). Data in: bytes or JSON-able objects from a
service; data out: bytes / parsed objects, or None when a file does not exist yet.

Where things are kept: the preset library root (library.json, import/, user/, semantic.json, their .lock files),
data_dir (edits/, thumbs/, index/, export-presets.json) and the settings file. Never inside a photo folder or the
purchased preset folder.
"""
