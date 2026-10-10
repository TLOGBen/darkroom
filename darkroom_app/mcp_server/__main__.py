"""相容用（compat shim）：`python -s -m darkroom_app.mcp_server` runs the MCP stdio server in adapters/mcp_server."""
import sys

from darkroom_app.adapters.mcp_server import main

sys.exit(main())
