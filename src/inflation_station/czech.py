"""Numbers as Czech documents write them: `"1 501,01"`."""

import re
from decimal import Decimal

# Thousands separators may be a plain, no-break or narrow no-break space.
_SPACES = re.compile(r"[ \u00a0\u202f]")
_NUMBER = re.compile(r"-?(\d+(\.\d*)?|\.\d+)")


def decimal(text: str) -> Decimal | None:
    """The number in text like "1 501,01", or None if it isn't one."""
    plain = _SPACES.sub("", text).replace(",", ".")
    return Decimal(plain) if _NUMBER.fullmatch(plain) else None
