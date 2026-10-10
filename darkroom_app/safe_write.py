"""相容用（compat shim）：舊路徑 `darkroom_app.safe_write` 指向 `darkroom_app.utils.safe_write`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import safe_write` and
`mock.patch.object(safe_write, ...)` reach the very same module object as `darkroom_app.utils.safe_write`.
"""
import sys

from .utils import safe_write as _real

sys.modules[__name__] = _real
