"""Check one source: fetch the configured product page, extract, cross-check, verify."""

from __future__ import annotations

from functools import partial
from typing import Callable

from ..config import ProductSpec, Settings, SourceConfig
from ..extract import extract_candidates
from ..fetch import FetcherPool
from ..matching import title_acceptable
from ..models import (
    CheckResult,
    ExtractedOffer,
    FetchResult,
    FetchStatus,
    MatchResult,
    Verification,
)
from ..pagecheck import apply_page_checks
from ..verify import evaluate_offer
from .amazon import extract_amazon
from .ceconomy import extract_ceconomy
from .idealo import extract_idealo


def extract_generic(html: str) -> ExtractedOffer | None:
    """First offer with a price, in trust order (JSON-LD, microdata, meta).

    We deliberately take the *first* structured product on the page (the main
    product) instead of hunting for one that matches, so a wrong product page
    is rejected rather than silently matched against a 'related products' block.
    """
    for c in extract_candidates(html):
        if c.price is not None:
            return c
    return None


def _generic_title(html: str) -> str | None:
    from ..extract import page_title, soup_of

    soup = soup_of(html)
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else page_title(soup)


def extract_offer(src: SourceConfig, html: str, spec: ProductSpec | None = None,
                  final_url: str | None = None) -> ExtractedOffer | None:
    """Run the configured extractor, then the visible-page cross-checks."""
    if src.extractor == "amazon":
        offer = extract_amazon(html) or extract_generic(html)
    elif src.extractor == "ceconomy":
        offer = extract_ceconomy(html, src.article_id, final_url, shop_name=src.name)
    elif src.extractor == "idealo":
        filt = partial(title_acceptable, spec=spec) if spec else None
        return extract_idealo(html, filt)  # comparison page: no retailer page checks
    else:
        offer = extract_generic(html)
    offer = apply_page_checks(offer, html)
    if offer is not None and not offer.title:
        offer.title = _generic_title(html)
    return offer


# Kept for callers/tests that want a simple callable per extractor name.
EXTRACTORS: dict[str, Callable[[str], ExtractedOffer | None]] = {
    "generic": extract_generic,
    "amazon": lambda html: extract_amazon(html) or extract_generic(html),
}


def skipped(src: SourceConfig, checked_at: str) -> CheckResult:
    status = FetchStatus.DISABLED if not src.enabled else FetchStatus.NOT_CONFIGURED
    reason = "disabled in config" if not src.enabled else "no product URL configured"
    if src.notes and src.enabled:
        reason += f" ({src.notes})"
    return CheckResult(
        source_id=src.id,
        source_name=src.name,
        kind=src.kind,
        url=src.url,
        fetch_status=status,
        verification=Verification.SKIPPED,
        match=MatchResult.UNKNOWN,
        reasons=[reason],
        checked_at=checked_at,
    )


def check_source(
    src: SourceConfig,
    pool: FetcherPool,
    spec: ProductSpec,
    settings: Settings,
    checked_at: str,
) -> tuple[CheckResult, FetchResult | None]:
    if not src.enabled or not src.url:
        return skipped(src, checked_at), None
    fetch = pool.get(src.fetcher).fetch(src.url)
    offer = None
    if fetch.status == FetchStatus.OK:
        try:
            offer = extract_offer(src, fetch.html, spec, fetch.final_url)
        except Exception as exc:  # noqa: BLE001 - a parser bug must not kill the whole run
            result = evaluate_offer(src, fetch, None, spec, settings, checked_at)
            result.reasons.append(f"extractor crashed: {type(exc).__name__}: {exc}"[:300])
            return result, fetch
    return evaluate_offer(src, fetch, offer, spec, settings, checked_at), fetch
