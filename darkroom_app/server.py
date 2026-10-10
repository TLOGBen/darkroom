"""相容用（compat shim）：舊路徑 `darkroom_app.server` 指向 `darkroom_app.adapters.http.server`。新程式不要 import 這裡。

The old module name is made an alias of the real module (sys.modules), so `from darkroom_app.server import FACADE,
make_app` and patches on `darkroom_app.server` reach the very same module object.
"""
import sys

from .adapters.http import server as _real

sys.modules[__name__] = _real
