"""Public error types."""


class UnsupportedPresetError(ValueError):
    """The preset uses a process version this library does not render (ProcessVersion below 10, e.g. 6.7)."""

    def __init__(self, process_version, path=""):
        self.process_version = process_version
        self.path = path
        super().__init__(f"unsupported preset process version {process_version} ({path})")
