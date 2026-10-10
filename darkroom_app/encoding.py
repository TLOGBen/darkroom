"""相容用（compat shim）：舊路徑 `darkroom_app.encoding` 指向 `darkroom_app.utils.encoding`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import encoding` and
`mock.patch.object(encoding, ...)` reach the very same module object as `darkroom_app.utils.encoding`.
"""
import sys

from .utils import encoding as _real

sys.modules[__name__] = _real
