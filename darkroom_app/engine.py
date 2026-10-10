"""相容用（compat shim）：舊路徑 `darkroom_app.engine` 指向 `darkroom_app.adapters.gpu.engine`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import engine as
engine_mod` and `mock.patch.object(engine_mod, "render", ...)` reach the very same module object.
"""
import sys

from .adapters.gpu import engine as _real

sys.modules[__name__] = _real
