"""idealo.de price-comparison extractor. idealo is NEVER treated as a retailer.

Observed live on 2026-11-24 in a desktop browser on
https://www.idealo.de/preisvergleich/OffersOfProduct/207748718_-playstation-5-slim-ps5-slim-digital-edition-standard-edition-825gb-sony.html
  * h1: "Sony PlayStation 5 Slim (PS5 Slim) Digital Edition Standard Edition 825GB"
    (variant page; product details: Modell PS5 Digital, 825 GB, 2025)
  * JSON-LD Product with AggregateOffer (lowPrice 799.9, offerCount 5). Its
    "name" lacks the 825 GB variant, so the h1 is used as title.
  * Offer list: ul.productOffers-list > li.productOffers-listItem with
      .productOffers-listItemTitleInner        offer title (contains soft hyphens)
      .productOffers-listItemOfferPrice        item price
      text "799,90 € inkl. Versand"           total incl. shipping
      [data-shop-name] / logo alt "<shop> - Shop aus <city>"
      "Verkauf durch: <seller>"                 marketplace seller (eBay etc.)
  * Offers came from a Swedish shop and marketplace sellers (eBay, Hakla-Shop,
    FabKoh24Deals) - exactly why idealo prices stay unverified.

STATUS: structure confirmed in a browser; NOT confirmed via the bot's HTTP
fetcher. idealo is known to block automated clients.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..extract import extract_candidates
from ..models import Availability, ExtractedOffer
from ..prices import parse_price

_TOTAL_RE = re.compile(r"(\d[\d.]*,\d{2})\s?€\s*inkl\.?\s*Versand", re.I)
_SELLER_RE = re.compile(r"Verkauf durch:?\s*([^\n]{2,50})", re.I)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("­", "")).strip()


def parse_offer_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    offers = []
    for li in soup.select("li.productOffers-listItem"):
        title_el = li.select_one(".productOffers-listItemTitleInner") or li.select_one(".productOffers-listItemTitle")
        price_el = li.select_one(".productOffers-listItemOfferPrice")
        text = _clean(li.get_text(" "))
        price = parse_price(price_el.get_text()) if price_el else None
        m = _TOTAL_RE.search(text)
        total = parse_price(m.group(1)) if m else None
        shop = li.get("data-shop-name") or None
        shop_el = li.select_one("[data-shop-name]")
        if not shop and shop_el and shop_el.get("data-shop-name"):
            shop = shop_el["data-shop-name"].strip()
        if not shop:
            for img in li.select("img[alt]"):
                alt = img["alt"]
                if " - Shop aus " in alt:
                    shop = alt.split(" - Shop aus ")[0].strip()
                    break
        sm = _SELLER_RE.search(li.get_text("\n"))
        offers.append(
            {
                "title": _clean(title_el.get_text()) if title_el else None,
                "price": price,
                "total": total,
                "shop": shop,
                "marketplace_seller": _clean(sm.group(1)).split(" Zum Shop")[0] if sm else None,
                "preorder": "vorbestell" in text.lower(),
            }
        )
    return [o for o in offers if o["price"] is not None]


def extract_idealo(html: str, title_filter=None) -> ExtractedOffer | None:
    """Lowest *total* among offers whose title passes `title_filter` (if given)."""
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    page_title = _clean(h1.get_text()) if h1 else None

    offers = parse_offer_list(html)
    if title_filter:
        kept = [o for o in offers if o["title"] is None or title_filter(o["title"])]
        dropped = len(offers) - len(kept)
        offers = kept
    else:
        dropped = 0

    if offers:
        best = min(offers, key=lambda o: o["total"] if o["total"] is not None else o["price"])
        offer = ExtractedOffer(
            title=page_title,
            price=best["price"],
            currency="EUR",
            availability=Availability.PREORDER if best["preorder"] else Availability.UNKNOWN,
            shipping=(best["total"] - best["price"]) if best["total"] is not None else None,
            seller=best["shop"] or None,
            method="site:idealo",
            offer_count=len(offers),
        )
        if best["marketplace_seller"]:
            offer.seller = f"{best['shop'] or 'marketplace'} / {best['marketplace_seller']}"
            offer.is_marketplace = True
        offer.notes.append(f"{len(offers)} offer(s) listed" + (f", {dropped} skipped by title filter" if dropped else ""))
        for o in sorted(offers, key=lambda o: o["total"] or o["price"])[:3]:
            who = o["shop"] or "?"
            if o["marketplace_seller"]:
                who += f" / {o['marketplace_seller']}"
            offer.notes.append(f"{o['total'] or o['price']} EUR total - {who}")
        return offer

    # Fallback: AggregateOffer from JSON-LD (shipping unknown).
    for c in extract_candidates(html):
        if c.price is not None:
            c.title = page_title or c.title
            c.availability = Availability.UNKNOWN  # aggregate stock says nothing reliable
            c.notes.append("offer list not found; using JSON-LD lowPrice (shipping unknown)")
            return c
    return None
