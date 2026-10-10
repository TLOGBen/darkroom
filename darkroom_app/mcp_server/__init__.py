"""相容用（compat shim）：舊路徑 `darkroom_app.mcp_server` 指向 `darkroom_app.adapters.mcp_server`。新程式不要 import 這裡。

`python -s -m darkroom_app.mcp_server` keeps working (see __main__.py here); imported, the old package name becomes
an alias of the real package (sys.modules), so `from darkroom_app.mcp_server import serve` and
`darkroom_app.mcp_server.tools` reach the very same modules.
"""
import sys

from ..adapters import mcp_server as _real
from ..adapters.mcp_server import protocol, tools  # noqa: F401  (submodules reachable under the old name)

sys.modules[__name__] = _real
sys.modules[__name__ + ".protocol"] = protocol
sys.modules[__name__ + ".tools"] = tools
