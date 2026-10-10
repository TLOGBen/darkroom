"""相容用（compat shim）：舊路徑 `darkroom_app.errors` 指向 `darkroom_app.domain.errors`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import errors` and
`mock.patch.object(errors, ...)` reach the very same module object as `darkroom_app.domain.errors`.
"""
import sys

from .domain import errors as _real

sys.modules[__name__] = _real
