"""MCP tools: one per facade operation, described by darkroom_app.operations (CONTRACT-layering L10).

Translation only: arguments -> facade call -> CallToolResult. Whether a value is acceptable is decided by the
services; a DarkroomError becomes a result with isError true and the service's sentence unchanged.
"""
import base64
import inspect
import json

from ..errors import DarkroomError
from ..facade import Facade
from ..operations import OPERATIONS, READ_ONLY_ANNOTATIONS
from .protocol import INVALID_PARAMS, RpcError

BY_TOOL = {spec["mcp"]: op for op, spec in OPERATIONS.items()}


def _params(op):
    return [n for n in inspect.signature(getattr(Facade, op)).parameters if n != "self"]


class Tools:
    def __init__(self, facade_provider):
        self._facade_provider = facade_provider     # () -> Facade, called on the first tools/call

    def list(self):
        return [{"name": spec["mcp"], "description": spec["description"], "inputSchema": spec["input_schema"],
                 "annotations": dict(spec.get("mcp_annotations", READ_ONLY_ANNOTATIONS))}
                for spec in OPERATIONS.values()]

    def call(self, name, arguments):
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
        if op in ("export", "import_presets", "paste_edit"):   # XP11 / KP5 / PLP4: partial failure is counted
            result = {**result, "failed": sum(1 for r in result["results"] if not r["ok"])}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result}
