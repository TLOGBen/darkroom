"""Public error types."""


class UnsupportedPresetError(ValueError):
    """The preset uses a process version this library does not render (anything outside the PV2012 family 6.x/10.x/11.x/15.x, e.g. PV2010 5.7)."""

    def __init__(self, process_version, path=""):
        self.process_version = process_version
        self.path = path
        super().__init__(f"unsupported preset process version {process_version} ({path})")
