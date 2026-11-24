from decimal import Decimal

from conftest import load

from ps5watcher.extract import extract_candidates, normalize_gtin
from ps5watcher.models import Availability
from ps5watcher.sources.amazon import extract_amazon
from ps5watcher.sources.base import extract_generic


def test_jsonld_main_product_first():
    offer = extract_generic(load("jsonld_in_stock.html"))
    assert offer.method == "jsonld"
    assert offer.title.startswith("Sony PlayStation 5 Slim Digital")
    assert offer.price == Decimal("479.00")
    assert offer.currency == "EUR"
    assert offer.availability == Availability.IN_STOCK
    assert offer.condition == "new"
    assert offer.shipping == Decimal("0.00")
    assert offer.gtin == "0711719020837"
    assert offer.seller == "Example Shop GmbH"


def test_jsonld_graph_and_list_offers():
    offer = extract_generic(load("jsonld_graph_out_of_stock.html"))
    assert offer.price == Decimal("529.99")
    assert offer.availability == Availability.OUT_OF_STOCK
    assert offer.gtin == "0711719020837"  # 12-digit UPC form normalised to EAN-13


def test_jsonld_shipping_cost_and_german_decimal():
    offer = extract_generic(load("jsonld_shipping_cost.html"))
    assert offer.price == Decimal("494.99")
    assert offer.shipping == Decimal("5.99")
    assert offer.availability == Availability.IN_STOCK


def test_aggregate_offer():
    offer = extract_generic(load("jsonld_aggregate.html"))
    assert offer.price == Decimal("469.90")
    assert offer.offer_count == 37


def test_microdata():
    offer = extract_generic(load("microdata.html"))
    assert offer.method == "microdata"
    assert offer.price == Decimal("499.00")
    assert offer.availability == Availability.IN_STOCK
    assert offer.gtin == "0711719020837"


def test_meta_only_is_weak():
    offer = extract_generic(load("meta_only.html"))
    assert offer.method == "meta"
    assert offer.price == Decimal("489.00")


def test_no_price():
    assert extract_generic(load("no_price.html")) is None
    assert extract_candidates(load("no_price.html")) == []


def test_broken_jsonld_is_ignored():
    html = '<script type="application/ld+json">{not json</script>'
    assert extract_candidates(html) == []


def test_amazon_like_page():
    offer = extract_amazon(load("amazon_like.html"))
    assert offer.price == Decimal("469.99")
    assert offer.currency == "EUR"
    assert offer.availability == Availability.IN_STOCK
    assert offer.shipping == Decimal("0.00")
    assert offer.seller == "Amazon"
    assert offer.method == "site:amazon"


def test_normalize_gtin():
    assert normalize_gtin("711719020837") == normalize_gtin("0711719020837") == "0711719020837"
    assert normalize_gtin("abc") is None
    assert normalize_gtin(None) is None
