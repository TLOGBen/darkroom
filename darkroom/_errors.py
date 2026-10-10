"""Public error types of the core library (re-exported by `darkroom/__init__.py`).

Layer: core library; depends on nothing. Only errors a caller is expected to handle specifically live here;
everything else surfaces as plain OSError (file problems) or ValueError (bad content / arguments).
"""


class UnsupportedPresetError(ValueError):
    """The preset uses a process version this library does not render (anything outside the PV2012 family 6.x/10.x/11.x/15.x, e.g. PV2010 5.7)."""

    # Why refuse instead of rendering anyway: Lightroom's older process versions (PV2010 and before) use different
    # tone math under the same slider names (e.g. "Exposure" vs "Exposure2012"), so applying them with the PV2012
    # pipeline would silently produce a different picture. Subclassing ValueError lets callers that only care
    # about "bad preset" catch it together with parse errors.

    def __init__(self, process_version, path=""):
        """process_version: the crs:ProcessVersion string found in the file; path: the .xmp path (for messages)."""
        self.process_version = process_version
        self.path = path
        super().__init__(f"unsupported preset process version {process_version} ({path})")
