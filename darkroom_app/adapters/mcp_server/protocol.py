"""MCP over stdio, written by hand (CONTRACT-layering L10; no `mcp` package, ADR-0003 / L14).

Layer: adapters/mcp_server. JSON-RPC framing and the protocol handshake only; the tools are tools.py.

One UTF-8 JSON-RPC 2.0 message per line. Dual-era: legacy clients open with `initialize` (answered with
2025-11-25), modern clients may probe with `server/discover` and send the protocol version in every request's
params._meta (2026-07-28: results then carry resultType "complete", and tools/list the caching hints;
any other version -> -32022).
Notifications are never answered. Logging and listChanged are not declared.

Depends on nothing of darkroom_app but the version string. Data flow: one line of bytes -> JSON -> validated
JSON-RPC envelope -> method dispatch (initialize / server/discover / ping / tools/list / tools/call) -> result or
error dict -> `encode` -> one line. Unexpected exceptions become -32603 and the server keeps running.

Contract codes: L10 = framing (no CR, ensure_ascii=False) and the tool interface; L14 = no third-party MCP package;
ADR-0003 = the earlier "Python only, no new dependencies" decision this followed.
"""
import json

from ... import __version__

LEGACY_VERSION = "2025-11-25"
MODERN_VERSION = "2026-07-28"
SERVER_INFO = {"name": "darkroom", "version": __version__}   # the one version source (plan-v2 §0)
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
CAPABILITIES = {"tools": {}}
# 2026-07-28 caching hints, required on complete results of server/discover and tools/list (the tool list is
# fixed for the life of the process and the same for every caller).
CACHE_HINTS = {"ttlMs": 3600000, "cacheScope": "public"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_VERSION = -32022


class RpcError(Exception):
    """A JSON-RPC error to send back: numeric code, message, optional data."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def encode(msg):
    """One message -> one line of UTF-8 bytes (JSON escapes every CR / LF inside strings)."""
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _error(id_, code, message, data=None):
    """A JSON-RPC error response dict."""
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def _valid_id(v):
    """JSON-RPC ids are strings or integers (a bool is not an id even though Python treats it as an int)."""
    return (isinstance(v, str) or (isinstance(v, int) and not isinstance(v, bool)))


class Dispatcher:
    """handle(line) -> the response dict, or None when nothing must be sent."""

    def __init__(self, tools):
        """tools: the Tools object (list / call)."""
        self.tools = tools      # .list() -> [tool], .call(name, arguments) -> CallToolResult dict

    def handle(self, line):
        """One incoming line (bytes or str) -> the response dict, or None for blank lines, notifications and
        client responses. Never raises."""
        if not line.strip():
            return None
        try:
            msg = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
        except (ValueError, UnicodeDecodeError):
            return _error(None, PARSE_ERROR, "Parse error")
        if not isinstance(msg, dict):
            return _error(None, INVALID_REQUEST, "Invalid Request")
        if "method" not in msg and ("result" in msg or "error" in msg):
            return None         # a response from the client: this server never sends requests
        if msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(msg.get("id") if _valid_id(msg.get("id")) else None, INVALID_REQUEST, "Invalid Request")
        if "id" not in msg:
            return None         # notification: never answered
        id_ = msg["id"]
        if not _valid_id(id_):
            return _error(None, INVALID_REQUEST, "Invalid Request")
        try:
            return {"jsonrpc": "2.0", "id": id_, "result": self._request(msg["method"], msg.get("params"))}
        except RpcError as e:
            return _error(id_, e.code, e.message, e.data)
        except Exception as e:     # unexpected: -32603, the server keeps running
            return _error(id_, INTERNAL_ERROR, f"Internal error: {type(e).__name__}: {e}")

    def _request(self, method, params):
        """The result of one request; raises RpcError for bad params, an unsupported protocol version or an
        unknown method. A modern (2026-07-28) request gets resultType "complete" and, for tools/list, cache hints."""
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        modern = False
        meta = params.get("_meta")
        if isinstance(meta, dict) and META_VERSION in meta:
            requested = meta[META_VERSION]
            if requested != MODERN_VERSION:
                raise RpcError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                               {"supported": [MODERN_VERSION, LEGACY_VERSION], "requested": requested})
            modern = True
        if method == "initialize":
            result = {"protocolVersion": LEGACY_VERSION, "capabilities": CAPABILITIES, "serverInfo": SERVER_INFO}
        elif method == "server/discover":
            result = {"resultType": "complete", "supportedVersions": [MODERN_VERSION], "capabilities": CAPABILITIES,
                      "_meta": {META_SERVER_INFO: SERVER_INFO}, **CACHE_HINTS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tools.list()}
        elif method == "tools/call":
            result = self.tools.call(params.get("name"), params.get("arguments"))
        else:
            raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
        if modern:
            result["resultType"] = "complete"
            if method == "tools/list":
                result.update(CACHE_HINTS)
        return result
