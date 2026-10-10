"""MCP tools: one per facade operation, described by darkroom_app.operations (CONTRACT-layering L10).

Layer: adapters/mcp_server. Depends on the facade (signatures), operations (names, schemas, defaults, annotations)
and domain.errors; never on services or domain rules.

Translation only: arguments -> facade call -> CallToolResult. Whether a value is acceptable is decided by the
services; a DarkroomError becomes a result with isError true and the service's sentence unchanged.

Contract codes: L10 = tool names, schemas and annotations come from operations; S3 = an argument outside the
facade signature is -32602 "Unknown argument for {tool}: {key}"; XP11 / KP5 / PLP4 / E27 = batch tools add a
`failed` count; PL13 = thumbnail returns an image content block.
"""
import base64
import inspect
import json

from ...domain.errors import DarkroomError
from ...facade import Facade
from ...operations import OPERATIONS, READ_ONLY_ANNOTATIONS
from .protocol import INVALID_PARAMS, RpcError

BY_TOOL = {spec["mcp"]: op for op, spec in OPERATIONS.items()}


def _params(op):
    """The parameter names of a facade operation (its Protocol signature): the only argument names accepted."""
    return [n for n in inspect.signature(getattr(Facade, op)).parameters if n != "self"]


class Tools:
    """tools/list and tools/call over the facade."""

    def __init__(self, facade_provider):
        """facade_provider: () -> the facade to call (built lazily on the first tools/call)."""
        self._facade_provider = facade_provider     # () -> Facade, called on the first tools/call

    def list(self):
        """Every tool in operation order: name, description, inputSchema and annotations."""
        return [{"name": spec["mcp"], "description": spec["description"], "inputSchema": spec["input_schema"],
                 "annotations": dict(spec.get("mcp_annotations", READ_ONLY_ANNOTATIONS))}
                for spec in OPERATIONS.values()]

    def call(self, name, arguments):
        """Run one tool -> a CallToolResult dict.

        Unknown tool / non-object arguments / unknown argument names raise RpcError -32602. MCP defaults (e.g. limit
        50) fill in omitted arguments. preview and thumbnail answer an image block (the agent can look at it);
        everything else answers its JSON both as text and as structuredContent. A DarkroomError is a normal result
        with isError true, so the agent sees the sentence."""
        op = BY_TOOL.get(name) if isinstance(name, str) else None
        if op is None:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        allowed = _params(op)
        for key in arguments:
            if key not in allowed:
                raise RpcError(INVALID_PARAMS, f"Unknown argument for {name}: {key}")
        kwargs = {**OPERATIONS[op]["mcp_defaults"], **arguments}
        try:
            result = getattr(self._facade_provider(), op)(**kwargs)
        except DarkroomError as e:
            return {"content": [{"type": "text", "text": e.message}],
                    "structuredContent": {"kind": e.kind, "message": e.message, **e.detail}, "isError": True}
        if op == "preview":
            return {"content": [{"type": "image", "mimeType": "image/jpeg",
                                 "data": base64.b64encode(result.jpeg).decode("ascii")}],
                    "structuredContent": {"render_ms": result.render_ms, "width": result.width,
                                          "height": result.height}}
        if op == "thumbnail":                  # CONTRACT-photo-library PL13
            return {"content": [{"type": "image", "mimeType": "image/jpeg",
                                 "data": base64.b64encode(result.jpeg).decode("ascii")}],
                    "structuredContent": {"fingerprint": result.fingerprint, "edited": result.edited,
                                          "width": result.width, "height": result.height}}
        if op in ("export", "import_presets", "paste_edit", "export_preset_files"):   # XP11 / KP5 / PLP4 / S2 E27
            result = {**result, "failed": sum(1 for r in result["results"] if not r["ok"])}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result}
