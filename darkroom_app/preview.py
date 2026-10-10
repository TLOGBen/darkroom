"""相容用（compat shim）：舊路徑 `darkroom_app.preview` 指向 `darkroom_app.domain.adjustment`。新程式不要 import 這裡。

validate_strength / validate_overrides / effective_params / validate_geometry / validate_flag now live in
domain/adjustment.py next to `Adjustment.from_request`. The old name is an alias of that module (sys.modules), so
`from darkroom_app import preview as semantics` gets the very same functions.
"""
import sys

from .domain import adjustment as _real

sys.modules[__name__] = _real
