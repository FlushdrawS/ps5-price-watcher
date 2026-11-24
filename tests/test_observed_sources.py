"""Regression tests on structures observed live on 2026-11-24 (offline).

Uses the SHIPPED config/sources.toml, so a config change that would break a
real-world case fails here. See tests/fixtures/README.md for what "observed"
means (browser-observed structure, minimal reconstruction).
"""

import dataclasses
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from conftest import evaluate_html, load

from ps5watcher.alerts import EventType, evaluate
from ps5watcher.config import DEFAULT_CONFIG, load_config
from ps5watcher.models import Availability, MatchResult, Verification
from ps5watcher.state import empty_state

CFG = load_config(DEFAULT_CONFIG)

FIXTURE = {
    "sony": ("observed_sony_2026-11-24.html", None),
    "amazon": ("observed_amazon_no_buybox_2026-11-24.html", None),
    "mediamarkt": ("observed_mediamarkt_2026-11-24.html",
                   "https://www.mediamarkt.de/de/product/_sony-playstation-5-slim-digital-edition-165421836.html"),
    "saturn": ("observed_saturn_2026-11-24.html",
               "https://www.saturn.de/de/product/_sony-playstation-5-slim-digital-edition-165421836.html"),
    "otto": ("observed_otto_2026-11-24.html", None),
    "alternate": ("observed_alternate_2026-11-24.html", None),
    "expert": ("observed_expert_soldout_2026-11-24.html", None),
    "idealo": ("observed_idealo_2026-11-24.html", None),
}


def check(source_id, tested=False):
    src = CFG.source(source_id)
    if tested:
        src = dataclasses.replace(src, integration_tested=True)
    name, final = FIXTURE[source_id]
    return evaluate_html(load(name), src, CFG.product, CFG.settings, final_url=final)


def test_every_configured_source_has_an_observed_fixture():
    configured = {s.id for s in CFG.sources if s.url}
    assert configured == set(FIXTURE)


@pytest.mark.parametrize("sid", list(FIXTURE))
def test_untested_integrations_are_never_verified(sid):
    assert check(sid).verification != Verification.VERIFIED


def test_sony_page_text_overrides_jsonld_instock():
    r = check("sony", tested=True)
    assert r.price == Decimal("599.99")
    assert r.availability == Availability.OUT_OF_STOCK
    assert "trusting the page" in r.offer.availability_note
    assert r.match == MatchResult.MATCH
    assert r.total == Decimal("599.99")  # free shipping >= 40
    assert r.verification == Verification.VERIFIED  # price verified, but NOT in stock


@pytest.mark.parametrize("sid,seller", [("mediamarkt", "MediaMarkt"), ("saturn", "Saturn")])
def test_ceconomy_tracks_own_article_not_marketplace(sid, seller):
    r = check(sid, tested=True)
    assert r.price == Decimal("599.99")  # own article, not the 1099.99 marketplace offer
    assert r.offer.seller == seller and r.offer.is_marketplace is False
    assert r.availability == Availability.OUT_OF_STOCK  # NOT_IN_ASSORTMENT
    assert r.offer.gtin == "0711719020837"
    assert any("Collectronics" in n for n in r.offer.notes)
    # the page shows the marketplace price, not 599.99 -> stays unverified
    assert r.verification == Verification.UNVERIFIED
    assert any("not printed on the page" in x for x in r.reasons)


def test_otto_marketplace_with_foreign_ean():
    r = check("otto", tested=True)
    assert r.price == Decimal("1299.99")
    assert r.offer.seller == "Hakla-Shop"
    assert r.match == MatchResult.PROBABLE  # EAN 4262451074603 is not Sony's
    assert r.verification == Verification.UNVERIFIED
    assert any("not Sony's EAN" in x for x in r.reasons)
    assert any("Hakla-Shop" in x for x in r.reasons)


def test_alternate_full_record():
    r = check("alternate", tested=True)
    assert r.verification == Verification.VERIFIED, r.reasons
    assert r.price == Decimal("899.00") and r.total == Decimal("906.99")
    assert r.offer.gtin == "0711719020837"  # taken from the mislabelled 'gtin8' field
    assert r.offer.seller == "ALTERNATE GmbH"
    assert r.availability == Availability.OUT_OF_STOCK


def test_amazon_without_buybox_is_a_valid_not_offered_observation():
    r = check("amazon", tested=True)
    assert r.verification == Verification.UNVERIFIED
    assert r.price is None and r.availability == Availability.OUT_OF_STOCK
    assert r.match == MatchResult.MATCH
    assert any("not currently offered" in x for x in r.reasons)


def test_expert_soldout_without_structured_data():
    r = check("expert", tested=True)
    assert r.price is None and r.availability == Availability.OUT_OF_STOCK
    assert r.match == MatchResult.MATCH  # via url_identity_verified (EAN search)
    assert r.verification == Verification.UNVERIFIED


def test_idealo_comparison_lowest_total_and_bundle_filtered():
    r = check("idealo")
    assert r.verification == Verification.COMPARISON
    assert r.price_basis == Decimal("799.90")
    assert r.offer.seller == "maxgaming.gg"
    assert any("skipped by title filter" in n for n in r.offer.notes)  # synthetic 649 EUR bundle offer dropped


def test_observed_market_produces_no_purchase_alert():
    """24 Nov 2026: nothing new <= 500 EUR anywhere - the bot must stay quiet about deals."""
    results = [check(sid, tested=True) for sid in FIXTURE]
    events = evaluate(results, empty_state(), CFG.settings, datetime(2026, 11, 24, 14, tzinfo=timezone.utc))
    assert not [e for e in events if e.type in (EventType.TARGET_HIT, EventType.CANDIDATE)]
