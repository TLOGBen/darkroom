"""相容用（compat shim）：舊路徑 `darkroom_app.formats` 指向 `darkroom_app.domain.formats`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import formats` and
`mock.patch.object(formats, ...)` reach the very same module object as `darkroom_app.domain.formats`.
"""
import sys

from .domain import formats as _real

sys.modules[__name__] = _real
