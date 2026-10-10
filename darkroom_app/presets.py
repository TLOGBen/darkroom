"""相容用（compat shim）：舊路徑 `darkroom_app.presets`。新程式不要 import 這裡。

The module was split in v2 (plan-v2 §1): the preset library rules (ids, groups, the index and semantic schemas,
merge, the view's queries) are `darkroom_app.domain.presets`; the `Library` that reads the folders, library.json and
semantic.json is `darkroom_app.adapters.persist.preset_index`. This module re-exports both so old imports keep working.
"""
from .adapters.persist.preset_index import Library, _rel  # noqa: F401
from .domain.presets import *  # noqa: F401,F403
from .domain.presets import _stem_of  # noqa: F401
