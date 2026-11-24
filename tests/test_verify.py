"""Verification rules on synthetic fixtures (offline)."""

from decimal import Decimal

from conftest import evaluate_html, load, make_src

from ps5watcher.models import Availability, FetchStatus, MatchResult, Verification


def test_verified_when_all_checks_pass():
    r = evaluate_html(load("jsonld_in_stock.html"), make_src())
    assert r.verification == Verification.VERIFIED, r.reasons
    assert r.total == Decimal("479.00")
    assert r.in_stock


def test_untested_integration_is_unverified():
    r = evaluate_html(load("jsonld_in_stock.html"), make_src(integration_tested=False))
    assert r.verification == Verification.UNVERIFIED
    assert any("live-tested" in x for x in r.reasons)


def test_unknown_shipping_is_unverified():
    r = evaluate_html(load("microdata.html"), make_src())
    assert r.verification == Verification.UNVERIFIED
    assert r.total is None
    assert any("shipping" in x for x in r.reasons)


def test_config_shipping_used():
    r = evaluate_html(load("microdata.html"), make_src(shipping_eur=Decimal("4.99")))
    assert r.verification == Verification.VERIFIED, r.reasons
    assert r.total == Decimal("503.99")


def test_free_shipping_threshold():
    r = evaluate_html(load("microdata.html"), make_src(free_shipping_from_eur=Decimal("50")))
    assert r.total == Decimal("499.00")


def test_page_shipping_beats_config():
    r = evaluate_html(load("jsonld_shipping_cost.html"), make_src(shipping_eur=Decimal("0")))
    assert r.total == Decimal("500.98")


def test_meta_only_never_verified():
    r = evaluate_html(load("meta_only.html"), make_src(shipping_eur=Decimal("0")))
    assert r.verification == Verification.UNVERIFIED
    assert any("weak source" in x for x in r.reasons)


def test_bundle_rejected():
    assert evaluate_html(load("jsonld_bundle.html"), make_src()).verification == Verification.REJECTED


def test_used_rejected():
    assert evaluate_html(load("jsonld_used.html"), make_src()).verification == Verification.REJECTED


def test_blocked_is_error_not_price():
    r = evaluate_html(load("blocked_amazon_captcha.html"), make_src())
    assert r.fetch_status == FetchStatus.BLOCKED
    assert r.verification == Verification.ERROR
    assert r.offer is None


def test_no_price_is_error():
    assert evaluate_html(load("no_price.html"), make_src()).verification == Verification.ERROR


def test_comparison_source_never_verified():
    r = evaluate_html(load("jsonld_aggregate.html"), make_src(kind="comparison"))
    assert r.verification == Verification.COMPARISON
    assert r.price == Decimal("469.90")
    assert any("merchant" in x for x in r.reasons)


def test_implausible_price():
    html = load("jsonld_in_stock.html").replace('"479.00"', '"49.00"').replace("479,00 €", "49,00 €")
    r = evaluate_html(html, make_src())
    assert r.verification == Verification.UNVERIFIED
    assert any("plausible" in x for x in r.reasons)


def test_stale_structured_price_not_on_page():
    html = load("jsonld_in_stock.html").replace("479,00 €", "529,00 €")
    r = evaluate_html(html, make_src())
    assert r.verification == Verification.UNVERIFIED
    assert any("not printed on the page" in x for x in r.reasons)


def test_visible_price_check_can_be_disabled_per_source():
    html = load("jsonld_in_stock.html").replace("479,00 €", "")
    assert evaluate_html(html, make_src(require_visible_price=False)).verification == Verification.VERIFIED


def test_amazon_sold_by_amazon_verified():
    src = make_src(extractor="amazon", required_seller=("amazon",), first_party_shop=False)
    r = evaluate_html(load("amazon_like.html"), src)
    assert r.verification == Verification.VERIFIED, r.reasons


def test_amazon_marketplace_unverified():
    src = make_src(extractor="amazon", required_seller=("amazon",), first_party_shop=False)
    r = evaluate_html(load("amazon_marketplace.html"), src)
    assert r.verification == Verification.UNVERIFIED
    assert any("marketplace" in x for x in r.reasons)
    assert r.match == MatchResult.MATCH


def test_seller_unknown_on_marketplace_shop_is_unverified():
    src = make_src(first_party_shop=False)
    html = load("jsonld_in_stock.html").replace('"seller":{"@type":"Organization","name":"Example Shop GmbH"},', "")
    html = html.replace("<p>Verkauf durch Example Shop GmbH</p>", "")
    r = evaluate_html(html, src)
    assert r.verification == Verification.UNVERIFIED
    assert any("seller not verified" in x for x in r.reasons)


def test_required_seller_mismatch():
    r = evaluate_html(load("jsonld_in_stock.html"), make_src(required_seller=("mediamarkt",)))
    assert any("not mediamarkt" in x for x in r.reasons)


def test_visible_out_of_stock_overrides_jsonld():
    html = load("jsonld_in_stock.html").replace("</body>", "<p>Derzeit nicht vorrätig.</p></body>")
    r = evaluate_html(html, make_src())
    assert r.availability == Availability.OUT_OF_STOCK
    assert "trusting the page" in r.offer.availability_note


def test_fast_ausverkauft_badge_does_not_flip_stock():
    html = load("jsonld_in_stock.html").replace("</body>", "<span>Fast ausverkauft</span></body>")
    assert evaluate_html(html, make_src()).availability == Availability.IN_STOCK
