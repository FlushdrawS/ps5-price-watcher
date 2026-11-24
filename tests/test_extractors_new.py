"""Unit tests for page cross-checks, MediaMarkt/Saturn state parser and idealo parser."""

import json
from decimal import Decimal

import pytest
from conftest import SPEC, load

from ps5watcher.matching import match_offer, title_acceptable
from ps5watcher.models import Availability, ExtractedOffer, MatchResult
from ps5watcher.pagecheck import (
    apply_page_checks,
    find_unavailable_phrase,
    visible_prices,
    visible_seller,
    visible_text,
)
from ps5watcher.sources.ceconomy import article_from_url, extract_ceconomy, parse_state
from ps5watcher.sources.idealo import extract_idealo, parse_offer_list


# --------------------------- pagecheck ---------------------------
@pytest.mark.parametrize(
    "text,price",
    [
        ("1099, 99 € 1099,99€ inkl. MwSt.", "1099.99"),  # Saturn spacing
        ("Konsole €599,99", "599.99"),                     # Sony
        ("€ 899,00 inkl. MwSt.", "899.00"),                # Alternate
        ("1.299,99 €", "1299.99"),                         # OTTO
        ("Preis 222.- inkl. MwSt.", "222.00"),             # expert style
        ("nur 499,- €", "499.00"),
        ("EUR 479,90", None),                              # currency before w/o € not supported -> no false match
    ],
)
def test_visible_prices(text, price):
    found = visible_prices(text)
    if price is None:
        assert Decimal("479.90") not in found
    else:
        assert Decimal(price) in found


@pytest.mark.parametrize(
    "text,seller",
    [
        ("Verkäufer: Hakla-Shop AGB | Datenschutz", "Hakla-Shop"),
        ("1099,99€ versandkostenfrei Verkauf und Versand durch Collectronics Finanzierung", "Collectronics"),
        ("Verkauf durch: leipzigsells\nZum Shop", "leipzigsells"),
        ("kein Verkäuferhinweis hier", None),
    ],
)
def test_visible_seller(text, seller):
    assert visible_seller(text) == seller


def test_unavailable_phrases_are_specific():
    assert find_unavailable_phrase("Derzeit nicht vorrätig. Schau bald wieder vorbei") == "derzeit nicht vorrätig"
    assert find_unavailable_phrase("Fast ausverkauft") is None
    assert find_unavailable_phrase("ausverkauft") is None


def test_visible_text_ignores_scripts():
    html = '<script>var x = "Derzeit nicht vorrätig";</script><p>Auf Lager</p>'
    assert find_unavailable_phrase(visible_text(html)) is None


def test_no_offer_and_no_phrase_stays_none():
    assert apply_page_checks(None, "<p>Hallo</p>") is None


def test_preorder_not_overridden_without_phrase():
    o = ExtractedOffer(title="x", price=Decimal("499"), availability=Availability.PREORDER)
    assert apply_page_checks(o, "<p>499,00 €</p>").availability == Availability.PREORDER


# --------------------------- ceconomy ---------------------------
def _state_html(apollo, comment_marker=True):
    s = json.dumps({"apolloState": apollo})
    pre = "<!-- mentions window.__PRELOADED_STATE__ in a comment -->" if comment_marker else ""
    return f"<html>{pre}<script>window.__PRELOADED_STATE__ = {s};</script></html>"


def _entities(status="AVAILABLE", buyable=True, mp_seller=None, price=599.99, ean="0711719020837"):
    own = "Media:de:3012188"
    return {
        "GraphqlProduct:Media:de-DE:3012188": {"__typename": "GraphqlProduct", "id": "3012188", "ean": ean,
                                                "title": "SONY PlayStation®5 Digital Edition (Slim) – 825 GB"},
        "P1": {"__typename": "CofrPriceFeature", "id": own, "currency": "EUR",
               "price": {"amount": price, "shippingCost": 0},
               "marketplaceSeller": ({"sellerName": mp_seller} if mp_seller else None)},
        "S1": {"__typename": "CofrOnlineStatusFeature", "id": own, "isAvailableAndBuyable": buyable,
               "onlineStatus": status},
        "V1": {"__typename": "CofrPriceFeature", "id": "Media:de:3020826", "currency": "EUR",
               "price": {"amount": 649.99, "shippingCost": 0}},
        "GraphqlProduct:Media:de-DE:3020826": {"__typename": "GraphqlProduct", "id": "3020826", "ean": "0711719022633"},
    }


def test_ceconomy_in_stock_own_offer():
    o = extract_ceconomy(_state_html(_entities()), "3012188", shop_name="MediaMarkt")
    assert o.price == Decimal("599.99") and o.shipping == Decimal("0.00")
    assert o.availability == Availability.IN_STOCK
    assert o.seller == "MediaMarkt" and o.is_marketplace is False
    assert o.gtin == "0711719020837"
    assert match_offer(o, SPEC).result == MatchResult.MATCH


@pytest.mark.parametrize("status", ["NOT_IN_ASSORTMENT", "TEMPORARILY_NOT_AVAILABLE"])
def test_ceconomy_out_statuses(status):
    o = extract_ceconomy(_state_html(_entities(status=status, buyable=False)), "3012188")
    assert o.availability == Availability.OUT_OF_STOCK


def test_ceconomy_marketplace_seller_on_own_article():
    o = extract_ceconomy(_state_html(_entities(mp_seller="Collectronics")), "3012188")
    assert o.is_marketplace is True and o.seller == "Collectronics"


def test_ceconomy_never_uses_other_variant():
    o = extract_ceconomy(_state_html(_entities()), "3020826")
    assert o.gtin == "0711719022633"  # the bundle's own EAN ...
    assert match_offer(o, SPEC).result == MatchResult.REJECT  # ... is rejected


def test_ceconomy_missing_article_or_state():
    assert extract_ceconomy(_state_html(_entities()), "9999999") is None
    assert extract_ceconomy("<html>no state</html>", "3012188") is None
    assert parse_state("window.__PRELOADED_STATE__ = {broken") is None


def test_article_from_url():
    assert article_from_url("https://www.saturn.de/de/product/_x-3012188.html") == "3012188"
    assert article_from_url(None) is None


# --------------------------- idealo ---------------------------
def test_idealo_offer_list_parsed():
    offers = parse_offer_list(load("observed_idealo_2026-11-24.html"))
    assert len(offers) == 4
    first = offers[0]
    assert first["price"] == Decimal("799.90") and first["total"] == Decimal("799.90")
    assert first["shop"] == "maxgaming.gg"
    assert offers[1]["marketplace_seller"] == "leipzigsells"
    assert offers[2]["total"] == Decimal("907.99") and offers[2]["preorder"]
    assert "Play­" not in first["title"]  # soft hyphens removed


def test_idealo_without_filter_would_pick_bundle():
    o = extract_idealo(load("observed_idealo_2026-11-24.html"))
    assert o.price == Decimal("649.00")  # proves the filter matters


def test_idealo_fallback_to_jsonld():
    o = extract_idealo(load("jsonld_aggregate.html"))
    assert o.price == Decimal("469.90")
    assert any("offer list not found" in n for n in o.notes)


@pytest.mark.parametrize(
    "title,ok",
    [
        ("Sony PlayStation 5 (PS5) Digital Edition Slim (E-Chassi)", True),
        ("Sony PlayStation 5 Digital Konsole Slim - ohne Laufwerk, 825GB SSD-Speicher, inkl. 1x DualSense Wireless Controller", True),
        ("PS5 Digital Edition 825 GB + 2 DualSense Controller", False),
        ("Sony PS5 Slim Digital Edition Disc Laufwerk", False),
    ],
)
def test_idealo_title_filter(title, ok):
    assert title_acceptable(title, SPEC) is ok
