"""Small text and type helpers shared by every layer (plan-v2 §1: utils/text.py).

These used to be private copies in five service modules (`_one_line`, `_is_int`); one copy now, so an error sentence
built from an exception reads the same everywhere.

Layer: utils (standard library only, no imports at all). Pure functions, no side effects.
"""


def one_line(e):
    """str(e) on one line (every run of whitespace, CR / LF included, becomes one space); the exception's type name
    when that is empty. Used for the `{reason}` part of user-facing sentences."""
    return " ".join(str(e).split()) or type(e).__name__


def is_int(v):
    """True for a real int (bool is not an int here: True must never pass as 1 for an offset or a limit)."""
    return isinstance(v, int) and not isinstance(v, bool)
