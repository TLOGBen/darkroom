"""相容用（compat shim）：舊路徑 `darkroom_app.sliders` 指向 `darkroom_app.domain.sliders`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import sliders` and
`mock.patch.object(sliders, ...)` reach the very same module object as `darkroom_app.domain.sliders`.
"""
import sys

from .domain import sliders as _real

sys.modules[__name__] = _real
