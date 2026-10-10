"""Sentinel values shared by every layer (plan-v2 §1: domain/sentinels.py).

`KEEP` is the default of every `geometry` argument (CONTRACT-s3-crop C13, D4): an argument left out means "the
photo's saved geometry", which is different from `None` ("no geometry"). It used to live in facade.py; it moved
here so services can use it without importing the facade (services never import the facade, adapters or config).
`darkroom_app.facade` re-exports it, so `from darkroom_app.facade import KEEP` keeps working for the entry points.

The object pickles to the same singleton (`__reduce__` returns the module-level name), so `x is KEEP` holds across
copies made by `copy.deepcopy` or `pickle`.
"""


class _Keep:
    """Left out = keep what is saved. One instance only (`KEEP`); compare with `is`."""
    __slots__ = ()

    def __repr__(self):
        return "KEEP"

    def __reduce__(self):
        return "KEEP"


KEEP = _Keep()
