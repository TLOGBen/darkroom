"""相容用（compat shim）：舊路徑 `darkroom_app.gpucheck` 指向 `darkroom_app.utils.gpucheck`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app import gpucheck` and
`mock.patch.object(gpucheck, ...)` reach the very same module object as `darkroom_app.utils.gpucheck`.
"""
import sys

from .utils import gpucheck as _real

sys.modules[__name__] = _real
