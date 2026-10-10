"""相容用（compat shim）：舊路徑 `darkroom_app.cli` 指向 `darkroom_app.adapters.cli`。新程式不要 import 這裡。

`python -s -m darkroom_app.cli ...` keeps working: run as a script this file calls the real `main`; imported, the
old module name becomes an alias of the real module (sys.modules), so `from darkroom_app import cli` and patches on
it reach the very same module object.
"""
import sys

from .adapters import cli as _real

if __name__ == "__main__":
    sys.exit(_real.main())
else:
    sys.modules[__name__] = _real
