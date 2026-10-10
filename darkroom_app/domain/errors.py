"""The one error type services raise (ADR-0001, CONTRACT-layering L7).

Layer: domain (imports nothing). The old path darkroom_app.errors is an alias of this module (compat shim).

Interfaces look only at `kind` and pass `message` through unchanged:
    invalid     -> HTTP 400 / CLI exit 2 / MCP isError
    not_found   -> HTTP 404 / CLI exit 3 / MCP isError
    conflict    -> HTTP 409 / CLI exit 4 / MCP isError   (reserved for later slices)
    unavailable -> HTTP 503 / CLI exit 5 / MCP isError   (reserved for later slices)

(L7 = "entry points look only at kind and never rewrite the sentence".) Kind conflict means "this would overwrite or
merge something; nothing was changed"; unavailable means "a feature is switched off or a resource is busy (lock,
missing data folder, no API key) - retry later or fix the configuration".
"""

KINDS = ("invalid", "not_found", "conflict", "unavailable")


class DarkroomError(Exception):
    """A refusal a user can understand: kind (one of KINDS), message (the verbatim sentence), detail (extra
    machine-readable fields some operations attach, e.g. a partial result)."""

    def __init__(self, kind, message, detail=None):
        """Raises ValueError for an unknown kind (a programming error, caught by the tests)."""
        if kind not in KINDS:
            raise ValueError(f"unknown error kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = dict(detail or {})

    def __repr__(self):
        return f"DarkroomError({self.kind!r}, {self.message!r}, {self.detail!r})"
