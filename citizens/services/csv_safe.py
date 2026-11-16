"""One rule for every CSV the app writes: a cell that a spreadsheet would read
as a formula is prefixed with an apostrophe so it stays text."""

_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize(value):
    """Return the value unchanged unless it is a string a spreadsheet would
    evaluate; then prefix it with an apostrophe."""
    if isinstance(value, str) and value.startswith(_FORMULA_LEADERS):
        return "'" + value
    return value
