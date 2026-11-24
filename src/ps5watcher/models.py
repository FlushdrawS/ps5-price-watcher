"""Plain data types shared across the package."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class FetchStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"  # captcha / bot wall / 403 / 429
    NOT_FOUND = "not_found"  # 404 / 410
    HTTP_ERROR = "http_error"  # other non-2xx
    NETWORK_ERROR = "network_error"  # timeout, DNS, TLS ...
    NOT_CONFIGURED = "not_configured"  # no URL in config yet
    DISABLED = "disabled"  # enabled = false in config


class Availability(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    UNKNOWN = "unknown"


class Verification(str, Enum):
    VERIFIED = "verified"  # every check passed - may trigger the main alert
    UNVERIFIED = "unverified"  # data found, but at least one check failed
    COMPARISON = "comparison"  # price-comparison source (idealo): indicative only
    REJECTED = "rejected"  # page shows a different / used / bundle product
    ERROR = "error"  # nothing usable (blocked, network, no price)
    SKIPPED = "skipped"  # not configured or disabled


class MatchResult(str, Enum):
    MATCH = "match"  # identity confirmed (EAN, or 825 GB + Digital in title)
    PROBABLE = "probable"  # looks right but not confirmed
    REJECT = "reject"  # wrong product
    UNKNOWN = "unknown"  # no title / no identifiers


@dataclass
class FetchResult:
    url: str
    status: FetchStatus
    http_status: int | None = None
    html: str = ""
    final_url: str | None = None
    error: str | None = None
    fetcher: str = "http"


@dataclass
class ExtractedOffer:
    title: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    availability: Availability = Availability.UNKNOWN
    shipping: Decimal | None = None
    gtin: str | None = None
    mpn: str | None = None
    condition: str | None = None  # "new" | "used" | "refurbished" | "damaged" | None
    seller: str | None = None
    method: str = "none"  # jsonld | microdata | meta | site:<name>
    offer_count: int | None = None  # set for AggregateOffer (comparison sites)
    is_marketplace: bool | None = None  # True = third-party seller on the retailer's site
    price_visible: bool | None = None  # price also found in the visible page text?
    availability_note: str | None = None  # e.g. structured data vs. page text conflict
    notes: list[str] = field(default_factory=list)  # extractor diagnostics shown in reports


@dataclass
class CheckResult:
    source_id: str
    source_name: str
    kind: str  # "retailer" | "comparison"
    url: str
    fetch_status: FetchStatus
    verification: Verification
    match: MatchResult
    reasons: list[str] = field(default_factory=list)
    offer: ExtractedOffer | None = None
    total: Decimal | None = None  # price + shipping, only when shipping is known
    http_status: int | None = None
    checked_at: str = ""
    final_url: str | None = None

    @property
    def price(self) -> Decimal | None:
        return self.offer.price if self.offer else None

    @property
    def availability(self) -> Availability:
        return self.offer.availability if self.offer else Availability.UNKNOWN

    @property
    def in_stock(self) -> bool:
        return self.availability == Availability.IN_STOCK

    @property
    def price_basis(self) -> Decimal | None:
        """Total if known, otherwise the bare item price."""
        return self.total if self.total is not None else self.price
