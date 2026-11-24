"""Cross-checks between structured data and what a shopper actually sees.

Why this exists (observed live on 2026-11-24):
  * playstation.com's JSON-LD said "InStock" while the page said
    "Derzeit nicht vorrätig" / "Nicht zum Kauf erhältlich".
  * OTTO's JSON-LD had no seller; the visible page said "Verkäufer: Hakla-Shop".
So structured data is never trusted on its own for stock or seller.

Rules
  * A strong "not available" sentence in the visible text overrides
    structured "InStock" (the safe direction: at worst we miss a deal, we never
    send a false purchase alert).
  * If no price is shown at all but such a sentence is present, the result is
    a valid "not offered / out of stock" observation instead of an error.
  * The seller is taken from the visible text when structured data lacks it.
  * `price_visible` records whether the extracted price is printed on the page
    (stale JSON-LD prices are a known failure mode).
"""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import BeautifulSoup

from .models import Availability, ExtractedOffer
from .prices import parse_price

# Full sentences / fixed labels only. Bare words such as "ausverkauft" also
# appear in badges of *other* products ("Fast ausverkauft") and are not used.
UNAVAILABLE_PHRASES = [
    "derzeit nicht vorrätig",
    "nicht zum kauf erhältlich",
    "artikel kann derzeit nicht gekauft werden",
    "das von ihnen ausgewählte produkt ist ausverkauft",
    "dieser artikel ist leider ausverkauft",
    "dieser artikel ist derzeit nicht verfügbar",
    "derzeit nicht verfügbar.",
    "online ausverkauft",
    "nicht mehr lieferbar",
    "currently unavailable.",
    "we don't know when or if this item will be back in stock",
]

_PRICE_TOKEN = re.compile(
    r"(?:€\s?(\d{1,3}(?:[.\s]\d{3})*(?:\s?[,.]\s?(?:\d{2}|[-–]))?|\d+(?:\s?[,.]\s?(?:\d{2}|[-–]))?))"
    r"|(?:(\d{1,3}(?:[.\s]\d{3})*(?:\s?[,.]\s?(?:\d{2}|[-–]))?|\d+(?:\s?[,.]\s?(?:\d{2}|[-–]))?)\s?(?:€|EUR\b))"
    r"|(?:\b(\d{3,4})\.-)"  # expert style "499.-"
)

_SELLER_RE = re.compile(
    r"(?:Verkauf und Versand durch|Verkauf durch|Verkäufer:|Verkauft von|Sold by)\s*:?\s*([^\n|]{2,60})",
    re.I,
)
_SELLER_STOP = re.compile(r"\s{2,}|\s(AGB|Datenschutz|Impressum|Finanzierung|Lieferung|Versand)\b|[|·]")


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = text.replace(" ", " ").replace("­", "")
    return re.sub(r"[ \t]+", " ", text)


def find_unavailable_phrase(text: str) -> str | None:
    low = text.lower()
    for phrase in UNAVAILABLE_PHRASES:
        if phrase in low:
            return phrase
    return None


def visible_prices(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for m in _PRICE_TOKEN.finditer(text):
        raw = next((g for g in m.groups() if g), None)
        if not raw:
            continue
        compact = re.sub(r"(?<=\d)\s(?=\d{3}\b)", "", raw)  # "1 099" -> "1099"
        compact = re.sub(r"\s?([,.])\s?", r"\1", compact)  # "1099, 99" -> "1099,99"
        value = parse_price(compact)
        if value is not None:
            found.add(value)
    return found


def visible_seller(text: str) -> str | None:
    m = _SELLER_RE.search(text)
    if not m:
        return None
    name = _SELLER_STOP.split(m.group(1).strip(), maxsplit=1)[0].strip(" :-")
    return name or None


def apply_page_checks(offer: ExtractedOffer | None, html: str) -> ExtractedOffer | None:
    """Enrich/correct an extracted offer with visible-page evidence."""
    text = visible_text(html)
    phrase = find_unavailable_phrase(text)

    if offer is None:
        if not phrase:
            return None
        # No price on the page, but the page clearly says it cannot be bought.
        offer = ExtractedOffer(method="page-text")
        offer.availability = Availability.OUT_OF_STOCK
        offer.availability_note = f"page says {phrase!r}; no price shown"
        return offer

    if phrase and offer.availability in (Availability.IN_STOCK, Availability.UNKNOWN, Availability.PREORDER):
        if offer.availability == Availability.IN_STOCK:
            offer.availability_note = f"structured data said in stock, but page says {phrase!r} - trusting the page"
        else:
            offer.availability_note = f"page says {phrase!r}"
        offer.availability = Availability.OUT_OF_STOCK
    elif offer.price is None and phrase:
        offer.availability = Availability.OUT_OF_STOCK
        offer.availability_note = f"page says {phrase!r}; no price shown"

    if not offer.seller:
        offer.seller = visible_seller(text)
        if offer.seller and offer.is_marketplace is None:
            offer.notes.append(f"seller from page text: {offer.seller}")

    if offer.price is not None:
        offer.price_visible = offer.price in visible_prices(text)
    return offer
