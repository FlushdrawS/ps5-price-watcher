"""Product identifiers. Standard library only (used by the dependency-free gate)."""

from __future__ import annotations

import re
from typing import Any


def normalize_gtin(value: Any) -> str | None:
    """Digits only, left-padded to 13 (EAN-13). '0711719020837' == '711719020837'.

    Returns None for values that cannot be an EAN/UPC/GTIN (fewer than 8 or
    more than 14 digits), e.g. a 7-digit manufacturer part number.
    """
    if value is None or isinstance(value, bool):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 8 or len(digits) > 14:
        return None
    digits = digits.lstrip("0")
    if not digits:
        return None
    return digits.zfill(13) if len(digits) <= 13 else digits
