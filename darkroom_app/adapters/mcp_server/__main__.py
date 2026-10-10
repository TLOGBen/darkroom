"""`python -s -m darkroom_app.adapters.mcp_server`: the MCP stdio server (same as `-m darkroom_app.mcp_server`)."""
import sys

from . import main

sys.exit(main())
