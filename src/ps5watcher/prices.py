"""Robust parsing of German / international price strings into Decimal."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CLEAN_RE = re.compile(r"[^\d.,\-–]")


def parse_price(value: object) -> Decimal | None:
    """Parse a price into a Decimal with two decimal places.

    Handles: 499.99, "499.99", "499,99 €", "€ 1.299,00", "1,299.00",
    "499,-", "499,–", "499", 499 (int/float). Returns None if unparseable
    or not positive.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            return None
        return _finish(d)

    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", " ").replace(" ", " ")
    # Strip currency and words; keep digits and separators.
    text = _CLEAN_RE.sub("", text)
    # "499,-" / "499,–" / "499.-" mean whole euros.
    text = re.sub(r"[.,][\-–]+$", "", text)
    text = text.replace("–", "").replace("-", "")
    if not text or not any(ch.isdigit() for ch in text):
        return None

    last_dot = text.rfind(".")
    last_comma = text.rfind(",")
    if last_dot != -1 and last_comma != -1:
        # Whichever separator comes last is the decimal separator.
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif last_comma != -1:
        decimals = len(text) - last_comma - 1
        if decimals == 3 and text.count(",") >= 1 and len(text) > 4:
            text = text.replace(",", "")  # "1,299" thousands separator
        else:
            text = text.replace(",", ".")
    elif last_dot != -1:
        decimals = len(text) - last_dot - 1
        if decimals == 3 and text.count(".") >= 1 and len(text) > 4:
            text = text.replace(".", "")  # "1.299" thousands separator
        elif text.count(".") > 1:
            head, _, tail = text.rpartition(".")
            text = head.replace(".", "") + "." + tail
    try:
        return _finish(Decimal(text))
    except InvalidOperation:
        return None


def _finish(d: Decimal) -> Decimal | None:
    if not d.is_finite() or d <= 0:
        return None
    return d.quantize(Decimal("0.01"))


def fmt_eur(value: Decimal | None) -> str:
    """Format as German euro string: 1.299,99 €"""
    if value is None:
        return "n/a"
    s = f"{value:,.2f}"  # 1,299.99
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"
