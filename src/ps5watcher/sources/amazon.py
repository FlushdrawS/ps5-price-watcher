"""Amazon.de product-page extractor.

Observed live on 2026-11-24 in a desktop browser on https://www.amazon.de/dp/B0FN7ZG39D:
  * #productTitle "Playstation®5 Digital Edition – 825 GB", technical details
    "Item model number: CFI-2116", release date 15 Sep 2025.
  * NO buy box and NO price: only "See All Buying Options" (other sellers).
  * No JSON-LD.
The selectors for a page WITH a buy box could not be observed (no offer
existed) and remain UNTESTED. Amazon often serves a captcha to datacenter IPs
such as GitHub Actions; that is detected as BLOCKED, never as a price.
"""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import BeautifulSoup

from ..models import Availability, ExtractedOffer
from ..prices import parse_price

PRICE_SELECTORS = [
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#apex_desktop .priceToPay .a-offscreen",
    "#price_inside_buybox",
    "#priceblock_ourprice",
]
SELLER_SELECTORS = [
    "#merchantInfoFeature_feature_div .offer-display-feature-text-message",
    "#sellerProfileTriggerId",
    "#merchant-info",
]
DELIVERY_SELECTORS = ["#mir-layout-DELIVERY_BLOCK", "#deliveryBlockMessage", "#delivery-message"]
NO_BUYBOX_RE = re.compile(
    r"alle kaufoptionen anzeigen|alle angebote anzeigen|see all buying options|derzeit nicht verfügbar|currently unavailable",
    re.I,
)


def _text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for sel in selectors:
        tag = soup.select_one(sel)
        if tag:
            txt = tag.get_text(" ", strip=True)
            if txt:
                return txt
    return None


def _availability(text: str | None) -> Availability:
    if not text:
        return Availability.UNKNOWN
    t = text.lower()
    if any(x in t for x in ("derzeit nicht verfügbar", "nicht auf lager", "nicht verfügbar", "currently unavailable")):
        return Availability.OUT_OF_STOCK
    if "vorbestell" in t or "erscheint am" in t or "pre-order" in t:
        return Availability.PREORDER
    if any(x in t for x in ("auf lager", "nur noch", "in stock")):
        return Availability.IN_STOCK
    return Availability.UNKNOWN


def extract_amazon(html: str) -> ExtractedOffer | None:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _text(soup, ["#productTitle"])
    price_text = _text(soup, PRICE_SELECTORS)
    price = parse_price(price_text)
    if price is None:
        buybox = _text(soup, ["#buybox", "#rightCol", "#availability", "#outOfStock"]) or ""
        if title and NO_BUYBOX_RE.search(buybox):
            offer = ExtractedOffer(title=title, method="site:amazon", availability=Availability.OUT_OF_STOCK)
            offer.availability_note = "no buy box - Amazon itself does not offer it (other sellers only)"
            return offer
        return None
    delivery = (_text(soup, DELIVERY_SELECTORS) or "").lower()
    shipping = Decimal("0.00") if re.search(r"kostenlos|kostenfrei|gratis|free delivery", delivery) else None
    seller = _text(soup, SELLER_SELECTORS)
    return ExtractedOffer(
        title=title,
        price=price,
        currency="EUR" if price_text and "€" in price_text else None,
        availability=_availability(_text(soup, ["#availability"])),
        shipping=shipping,
        seller=seller,
        is_marketplace=None if not seller else ("amazon" not in seller.lower()),
        method="site:amazon",
    )
