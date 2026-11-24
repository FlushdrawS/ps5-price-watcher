import pytest

from ps5watcher.models import ExtractedOffer, MatchResult
from ps5watcher.matching import match_offer


def m(title, spec, **kw):
    return match_offer(ExtractedOffer(title=title, **kw), spec).result


@pytest.mark.parametrize(
    "title",
    [
        "Sony PlayStation 5 Slim Digital Edition (E-Chassis) 825 GB",
        "PlayStation®5 Digital Edition – 825 GB",
        "SONY PlayStation®5 Digital Edition (Slim) – 825 GB",
        "PS5 Digital Edition 825GB Slim",
        "PlayStation 5 Digital Edition CFI-2116",
        "PlayStation 5 Slim Digital Edition 825 GB ohne Disc-Laufwerk",
        "Sony PlayStation 5 Digital Edition 825 GB inkl. DualSense Wireless-Controller",
    ],
)
def test_accepts_target_model(title, spec):
    assert m(title, spec) == MatchResult.MATCH


@pytest.mark.parametrize(
    "title",
    [
        "PlayStation 5 Slim Digital Edition 1 TB",
        "PS5 Digital Edition 1TB",
        "PlayStation 5 Pro Digital Edition 2 TB",
        "PlayStation 5 Slim Disc Edition 1 TB",
        "PlayStation 5 Slim 825 GB",  # no "Digital" -> disc model
        "PS5 Digital Edition 825 GB + 2 DualSense Controller",
        "PS5 Digital Edition 825 GB - Fortnite Flowering Chaos Bundle",
        "PlayStation 5 Digital Edition 825 GB EA SPORTS FC 26 Bundle",
        "PlayStation 5 Digital Edition 825 GB (Generalüberholt)",
        "PlayStation 5 Digital Edition 825 GB - B-Ware",
        "PlayStation 5 Digital Edition 825 GB Refurbished",
        "Disc-Laufwerk für PS5 Digital Edition",
        "Konsolen-Cover für PS5 Digital Edition",
        "PlayStation Portal Remote Player",
        "Sony PlayStation 5 Digital Edition 825 GB Marvel's Wolverine Limited Edition",
        "PlayStation 5 Digital Edition CFI-1116B 825 GB",
        "Vertikaler Standfuß für PS5 Slim Digital",
        "Xbox Series S Digital 512 GB",
    ],
)
def test_rejects_other_products(title, spec):
    assert m(title, spec) == MatchResult.REJECT


def test_probable_without_storage(spec):
    assert m("Sony PlayStation 5 Slim Digital Edition", spec) == MatchResult.PROBABLE


def test_gtin_wins(spec):
    assert m("Spielkonsole", spec, gtin="0711719020837") == MatchResult.MATCH
    assert m("PS5 Digital 825 GB", spec, gtin="0711719022633") == MatchResult.REJECT


def test_unknown_gtin_is_only_probable(spec):
    assert m("PS5 Digital Edition 825 GB", spec, gtin="4006381333931") == MatchResult.PROBABLE


def test_used_condition_rejected(spec):
    assert m("PS5 Digital Edition 825 GB", spec, condition="used") == MatchResult.REJECT


def test_no_title(spec):
    assert m(None, spec) == MatchResult.UNKNOWN
