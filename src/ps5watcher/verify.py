"""Decide whether an extracted offer counts as a VERIFIED price.

A price is VERIFIED only when *every* check passes. Any failed check makes it
UNVERIFIED and the reason is recorded, so a cheap-looking listing is never
treated as a real deal without the user seeing why.

The purchase alert additionally requires (see alerts.py): VERIFIED price,
availability IN_STOCK (structured data not contradicted by the page) and a
known total including shipping <= target.
"""

from __future__ import annotations

from decimal import Decimal

from .config import ProductSpec, Settings, SourceConfig
from .extract import TRUSTED_METHODS
from .matching import match_offer
from .models import (
    Availability,
    CheckResult,
    ExtractedOffer,
    FetchResult,
    FetchStatus,
    MatchResult,
    Verification,
)


def compute_total(offer: ExtractedOffer, src: SourceConfig) -> tuple[Decimal | None, str | None]:
    """Return (total, how) or (None, None) if shipping is unknown."""
    if offer.price is None:
        return None, None
    if offer.shipping is not None:
        return offer.price + offer.shipping, "shipping from page data"
    if src.free_shipping_from_eur is not None and offer.price >= src.free_shipping_from_eur:
        return offer.price, "free shipping threshold (config)"
    if src.shipping_eur is not None:
        return offer.price + src.shipping_eur, "shipping from config"
    return None, None


def _seller_reasons(offer: ExtractedOffer, src: SourceConfig) -> list[str]:
    seller = (offer.seller or "").strip()
    if offer.is_marketplace:
        return [f"marketplace offer sold by {seller or 'a third party'}, not by {src.name}"]
    if src.required_seller:
        if not seller:
            return ["seller not shown (required: " + "/".join(src.required_seller) + ")"]
        if not any(req in seller.lower() for req in src.required_seller):
            return [f"sold by {seller!r}, not {'/'.join(src.required_seller)}"]
        return []
    if src.first_party_shop:
        return []
    return ["seller not verified (shop hosts third-party sellers)" if not seller else f"seller {seller!r} not confirmed"]


def evaluate_offer(
    src: SourceConfig,
    fetch: FetchResult,
    offer: ExtractedOffer | None,
    spec: ProductSpec,
    settings: Settings,
    checked_at: str,
) -> CheckResult:
    base = dict(
        source_id=src.id,
        source_name=src.name,
        kind=src.kind,
        url=src.url,
        fetch_status=fetch.status,
        http_status=fetch.http_status,
        checked_at=checked_at,
        final_url=fetch.final_url,
    )

    if fetch.status != FetchStatus.OK:
        detail = fetch.error or fetch.status.value
        return CheckResult(
            **base, verification=Verification.ERROR, match=MatchResult.UNKNOWN, reasons=[f"fetch failed: {detail}"]
        )

    no_price_but_unavailable = (
        offer is not None and offer.price is None and offer.availability == Availability.OUT_OF_STOCK
    )
    if offer is None or (offer.price is None and not no_price_but_unavailable):
        return CheckResult(
            **base,
            verification=Verification.ERROR,
            match=MatchResult.UNKNOWN,
            offer=offer,
            reasons=["page loaded but no price could be extracted (layout change, JS-only page or soft block)"],
        )

    outcome = match_offer(offer, spec)
    match = outcome.result
    match_reasons = list(outcome.reasons)
    if match == MatchResult.REJECT:
        return CheckResult(**base, verification=Verification.REJECTED, match=match, offer=offer, reasons=match_reasons)
    # Evidence-based upgrade: a person confirmed this exact URL is the console
    # (e.g. via EAN search or the model number). Never overrides a foreign EAN.
    if match in (MatchResult.PROBABLE, MatchResult.UNKNOWN) and src.url_identity_verified and not outcome.gtin_mismatch:
        match = MatchResult.MATCH
        match_reasons = [f"identity confirmed for this URL: {src.url_identity_evidence}"]

    if no_price_but_unavailable:
        reasons = ["no price shown - not currently offered"]
        if offer.availability_note:
            reasons.append(offer.availability_note)
        if match != MatchResult.MATCH:
            reasons.extend(match_reasons)
        return CheckResult(
            **base, verification=Verification.UNVERIFIED, match=match, offer=offer, reasons=reasons
        )

    total, _how = compute_total(offer, src)
    reasons: list[str] = []

    if src.is_comparison:
        reasons.append("price comparison - confirm on the merchant's own site before buying")
        if total is None:
            reasons.append("shipping may be extra")
        if offer.is_marketplace:
            reasons.append("cheapest offer is a marketplace seller")
        if match != MatchResult.MATCH:
            reasons.extend(match_reasons)
        return CheckResult(
            **base, verification=Verification.COMPARISON, match=match, offer=offer, total=total, reasons=reasons
        )

    if not src.integration_tested:
        reasons.append("integration not live-tested yet (run `probe`, then set integration_tested = true)")
    if offer.method not in TRUSTED_METHODS and not offer.method.startswith("site:"):
        reasons.append(f"price came from weak source ({offer.method})")
    if offer.currency and offer.currency != "EUR":
        reasons.append(f"currency is {offer.currency}, not EUR")
    elif not offer.currency:
        reasons.append("currency not stated on page")
    if not (settings.min_plausible_eur <= offer.price <= settings.max_plausible_eur):
        reasons.append(
            f"price {offer.price} outside plausible range "
            f"{settings.min_plausible_eur}-{settings.max_plausible_eur} EUR"
        )
    if src.require_visible_price and offer.price_visible is False:
        reasons.append(f"price {offer.price} not printed on the page (structured data may be stale)")
    if match != MatchResult.MATCH:
        reasons.extend(match_reasons or ["product identity not confirmed"])
    if total is None:
        reasons.append("shipping cost unknown (set shipping_eur in config after checking the retailer)")
    reasons.extend(_seller_reasons(offer, src))

    verification = Verification.VERIFIED if not reasons else Verification.UNVERIFIED
    return CheckResult(
        **base, verification=verification, match=match, offer=offer, total=total, reasons=reasons
    )
