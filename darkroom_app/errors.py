"""The one error type services raise (ADR-0001, CONTRACT-layering L7).

Interfaces look only at `kind` and pass `message` through unchanged:
    invalid     -> HTTP 400 / CLI exit 2 / MCP isError
    not_found   -> HTTP 404 / CLI exit 3 / MCP isError
    conflict    -> HTTP 409 / CLI exit 4 / MCP isError   (reserved for later slices)
    unavailable -> HTTP 503 / CLI exit 5 / MCP isError   (reserved for later slices)
"""

KINDS = ("invalid", "not_found", "conflict", "unavailable")


class DarkroomError(Exception):
    def __init__(self, kind, message, detail=None):
        if kind not in KINDS:
            raise ValueError(f"unknown error kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = dict(detail or {})

    def __repr__(self):
        return f"DarkroomError({self.kind!r}, {self.message!r}, {self.detail!r})"
