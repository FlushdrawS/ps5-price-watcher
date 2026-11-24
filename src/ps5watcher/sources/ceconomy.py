"""MediaMarkt.de / Saturn.de extractor (both run on the same Ceconomy platform).

Observed live on 2026-11-24 in a desktop browser:
  * No Product JSON-LD on product pages (only Language, BreadcrumbList, BuyAction).
  * Data is in an inline script:  window.__PRELOADED_STATE__ = {...};
    with an Apollo cache under "apolloState".
  * The retailer's OWN article (Art.-Nr. 3012188, EAN 0711719020837) had
    onlineStatus NOT_IN_ASSORTMENT, price 599.99, shippingCost 0, and the URL
    redirected to a MARKETPLACE listing (seller "Collectronics", 1099.99).
  * Other variants on the same page carry other EANs (incl. the 2-controller
    bundle 0711719022633) - so we only ever read the configured article.

STATUS: structure confirmed in a browser; NOT yet confirmed via the bot's HTTP
fetcher (bot protection may differ). Run `probe` before trusting it.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from ..ids import normalize_gtin
from ..models import Availability, ExtractedOffer
from ..prices import parse_price

STATE_MARKER = "window.__PRELOADED_STATE__"

IN_STOCK_STATUSES = {"AVAILABLE", "ONLINE_AVAILABLE", "MP_OFFER"}
OUT_STATUSES = {
    "NOT_IN_ASSORTMENT",
    "TEMPORARILY_NOT_AVAILABLE",
    "CURRENTLY_NOT_AVAILABLE",
    "NOT_AVAILABLE",
    "PERMANENTLY_NOT_AVAILABLE",
    "OFFLINE",
    "SOLD_OUT",
}


_STATE_RE = re.compile(r"window\.__PRELOADED_STATE__\s*=\s*(?=\{)")


def parse_state(html: str) -> dict | None:
    """Parse `window.__PRELOADED_STATE__ = {...};` (first occurrence that parses)."""
    decoder = json.JSONDecoder()
    for m in _STATE_RE.finditer(html or ""):
        try:
            obj, _ = decoder.raw_decode(html, m.end())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def article_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"-(\d{5,12})\.html", url)
    return m.group(1) if m else None


def _by_type(apollo: dict, typename: str) -> list[dict]:
    return [v for v in apollo.values() if isinstance(v, dict) and v.get("__typename") == typename]


def _find(apollo: dict, typename: str, entity_id: str) -> dict | None:
    for v in _by_type(apollo, typename):
        if v.get("id") == entity_id:
            return v
    return None


def _availability(status: dict | None) -> Availability:
    if not status:
        return Availability.UNKNOWN
    online = str(status.get("onlineStatus") or "").upper()
    buyable = status.get("isAvailableAndBuyable")
    if "PRE" in online and "ORDER" in online:
        return Availability.PREORDER
    if buyable is True and (online in IN_STOCK_STATUSES or not online):
        return Availability.IN_STOCK
    if buyable is False or online in OUT_STATUSES:
        return Availability.OUT_OF_STOCK
    return Availability.UNKNOWN


def extract_ceconomy(html: str, article_id: str | None = None, final_url: str | None = None,
                     shop_name: str = "") -> ExtractedOffer | None:
    state = parse_state(html)
    if not state:
        return None
    apollo = state.get("apolloState") or {}
    article = article_id or article_from_url(final_url)
    if not article:
        return None

    # Entity ids look like "Media:de:3012188" / "Saturn:de:3012188" (own article)
    # and "Media:de:165421836[1880524004]" (marketplace offer).
    own_id = None
    for v in _by_type(apollo, "CofrPriceFeature"):
        vid = str(v.get("id") or "")
        if vid.endswith(f":{article}"):
            own_id = vid
            break
    product = None
    for v in _by_type(apollo, "GraphqlProduct"):
        if str(v.get("id")) == str(article):
            product = v
            break
    if own_id is None and product is None:
        return None

    price_f = _find(apollo, "CofrPriceFeature", own_id) if own_id else None
    status_f = _find(apollo, "CofrOnlineStatusFeature", own_id) if own_id else None
    core_f = _find(apollo, "CofrCoreFeature", own_id) if own_id else None

    title = None
    for src in (core_f or {}, product or {}):
        title = title or src.get("productName") or src.get("title")
    if not title and product and product.get("url"):
        title = re.sub(r"[-_]+", " ", str(product["url"]).rsplit("/", 1)[-1].replace(".html", "")).strip()
        title = re.sub(r"playstationr5", "playstation 5", title, flags=re.I)
        title = re.sub(r"\s\d{5,12}$", "", title)  # trailing article number

    gtin = normalize_gtin((core_f or {}).get("ean") or (product or {}).get("ean"))
    offer = ExtractedOffer(title=title, gtin=gtin, method="site:ceconomy", condition="new")

    if price_f:
        price = price_f.get("price") or {}
        offer.price = parse_price(price.get("amount"))
        offer.currency = (price_f.get("currency") or "").upper() or None
        ship = price.get("shippingCost")
        if ship is not None:
            offer.shipping = Decimal("0.00") if str(ship) in {"0", "0.0", "0.00"} else parse_price(ship)
        seller = price_f.get("marketplaceSeller") or None
        if seller and seller.get("sellerName"):
            offer.seller = seller["sellerName"]
            offer.is_marketplace = True
        else:
            offer.seller = shop_name or None
            offer.is_marketplace = bool(price_f.get("isProductOfTypeMarketplace"))
    offer.availability = _availability(status_f)
    if status_f and status_f.get("onlineStatus"):
        offer.notes.append(f"own article {article}: status {status_f.get('onlineStatus')}")

    # Report marketplace offers for the same EAN, but never use them as the price.
    if gtin:
        for core in _by_type(apollo, "CofrCoreFeature"):
            cid = str(core.get("id") or "")
            if "[" not in cid or normalize_gtin(core.get("ean")) != gtin:
                continue
            mp_price = _find(apollo, "CofrPriceFeature", cid)
            if not mp_price:
                continue
            seller = (mp_price.get("marketplaceSeller") or {}).get("sellerName") or "?"
            amount = parse_price((mp_price.get("price") or {}).get("amount"))
            offer.notes.append(f"marketplace offer on page (ignored): {seller} {amount} EUR")
    return offer
