from decimal import Decimal

import pytest

from ps5watcher.prices import fmt_eur, parse_price


@pytest.mark.parametrize(
    "raw, expected",
    [
        (499.99, "499.99"),
        (499, "499.00"),
        ("499.99", "499.99"),
        ("499,99 €", "499.99"),
        ("€ 499,99", "499.99"),
        ("1.299,00 €", "1299.00"),
        ("1,299.00", "1299.00"),
        ("1.299", "1299.00"),
        ("499,-", "499.00"),
        ("499,– €", "499.00"),
        ("EUR 479,9", "479.90"),
        ("479 €", "479.00"),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "gratis", "0", 0, -5, True, "€"])
def test_parse_price_rejects(raw):
    assert parse_price(raw) is None


def test_fmt_eur():
    assert fmt_eur(Decimal("1299.5")) == "1.299,50 €"
    assert fmt_eur(Decimal("499.99")) == "499,99 €"
    assert fmt_eur(None) == "n/a"
