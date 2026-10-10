"""相容用（compat shim）：舊路徑 `darkroom_app.skips` 指向 `darkroom_app.domain.skips`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import skips` and
`mock.patch.object(skips, ...)` reach the very same module object as `darkroom_app.domain.skips`.
"""
import sys

from .domain import skips as _real

sys.modules[__name__] = _real
